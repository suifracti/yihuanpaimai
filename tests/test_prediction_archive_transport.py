"""The last completed pre-settlement prediction reaches the actual disk archive."""
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import main
import live_shadow
from auto_archiver import AutoArchiver
from current_match import CurrentMatch
from prediction_archive_transport import PredictionArchiveTransport
from prediction_snapshot_holder import ActivePredictionSnapshotHolder
from test_prediction_snapshot_persistence_v1 import run_js_solver
import test_live_settlement_authority as settlement_fixture
from vision_worker_loop import run_vision_capture_loop


class PredictionArchiveTransportTests(unittest.TestCase):
    def test_save_draft_does_not_copy_invalid_prediction_around_validation(self):
        current = CurrentMatch()
        snapshot = run_js_solver({"matchId": current.id,
                                  "codeRevision": "fixture-revision"})["predictionSnapshot"]
        for corruption in (None, "matchId", "inputHash"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as directory:
                draft = current.to_canonical()
                candidate = copy.deepcopy(snapshot)
                if corruption == "inputHash":
                    candidate["input"]["inputHash"] = "invalid"
                elif corruption:
                    candidate[corruption] = "invalid"
                draft["predictionSnapshot"] = candidate
                original = copy.deepcopy(draft)
                db = Path(directory) / "history.json"
                saved = AutoArchiver([str(db)]).save_draft(draft)
                self.assertIsNotNone(saved)
                if corruption:
                    self.assertNotIn("predictionSnapshot", saved)
                else:
                    self.assertEqual(saved["predictionSnapshot"], candidate)
                self.assertEqual(draft, original)
                self.assertEqual(json.loads(db.read_text(encoding="utf-8"))["records"][0], saved)

    def test_real_fallback_survives_auto_archive_and_later_finalization(self):
        from evaluation_eligibility import validate_prediction_snapshot
        from canonical_history_store import CanonicalHistoryStore

        for start_with_saved_draft in (False, True):
            with self.subTest(saved_draft=start_with_saved_draft), tempfile.TemporaryDirectory() as directory:
                current = CurrentMatch()
                holder = ActivePredictionSnapshotHolder()
                snapshot = run_js_solver({"matchId": current.id,
                                          "codeRevision": "fixture-revision"})["predictionSnapshot"]
                self.assertEqual(snapshot["status"]["solverStatus"], "fallback")
                db = str(Path(directory) / "history.json")
                with patch("auto_archiver.ACTIVE_SNAPSHOT_HOLDER", holder):
                    if start_with_saved_draft:
                        draft = current.to_canonical()
                        draft["predictionSnapshot"] = snapshot
                        CanonicalHistoryStore(db).persist_record_transactional(draft, is_finalized=False)
                    else:
                        holder.update(current.id, snapshot=snapshot)
                        draft = AutoArchiver([db]).archive_match(
                            settlement_fixture.LiveSettlementAuthorityTests().context(current.id, None))
                        self.assertEqual(draft.get("predictionSnapshot"), snapshot)
                    holder.clear()
                    final = AutoArchiver([db]).archive_match(
                        settlement_fixture.LiveSettlementAuthorityTests().context(current.id, False))
                    self.assertEqual(final["lifecycleStatus"], "FINALIZED")
                    self.assertEqual(final.get("predictionSnapshot"), snapshot)
                    self.assertFalse(validate_prediction_snapshot(snapshot, match_id=current.id)[0])

    def test_draft_then_new_ownership_evidence_keeps_prediction(self):
        current = CurrentMatch()
        holder = ActivePredictionSnapshotHolder()
        snapshot = run_js_solver({"matchId": current.id, "q": 9, "goldAvg": 33538,
                                  "purpleCount": 5})["predictionSnapshot"]
        holder.update(current.id, snapshot=snapshot)
        with tempfile.TemporaryDirectory() as directory, patch("auto_archiver.ACTIVE_SNAPSHOT_HOLDER", holder):
            archiver = AutoArchiver([str(Path(directory) / "history.json")])
            draft = archiver.archive_match(settlement_fixture.LiveSettlementAuthorityTests().context(current.id, None))
            self.assertEqual(draft["predictionSnapshot"], snapshot)
            # Repeat using a fresh archiver, as after a worker restart.
            holder.clear()
            archiver = AutoArchiver([str(Path(directory) / "history.json")])
            final = archiver.archive_match(settlement_fixture.LiveSettlementAuthorityTests().context(current.id, False))
            self.assertEqual(final["predictionSnapshot"], snapshot)

    def test_completed_result_is_copied_and_never_schedules_solver(self):
        snapshot = {"matchId": "a", "forecast": {"value": 100}}
        with patch.object(live_shadow, "_LATEST_PREDICTION_SNAPSHOT", snapshot), \
             patch.object(live_shadow, "_LATEST_FROZEN_PREDICTION", {}), \
             patch.object(live_shadow, "compute_live_probability_profile") as compute:
            result = live_shadow.completed_prediction_for_match("a")
            result["snapshot"]["forecast"]["value"] = 200
            self.assertEqual(snapshot["forecast"]["value"], 100)
            self.assertEqual(live_shadow.completed_prediction_for_match("b"), {})
            compute.assert_not_called()

    def test_timeout_preserves_settlement_and_existing_prediction(self):
        async def run():
            current = CurrentMatch()
            holder = ActivePredictionSnapshotHolder()
            holder.update(current.id, snapshot={"matchId": current.id})
            async def send(request):
                pass
            bridge = PredictionArchiveTransport(send, current, holder, timeout=0.01)
            self.assertTrue(await bridge.collect({"id": current.id}))
            self.assertIsNotNone(holder.get_snapshot_for_match(current.id))
            self.assertEqual(bridge.pending, {})
        asyncio.run(run())

    def test_next_match_during_request_prevents_old_archive(self):
        async def run():
            current = CurrentMatch()
            holder = ActivePredictionSnapshotHolder()
            old_id = current.id
            async def send(request):
                current.begin_next_match()
                bridge.receive({**request, "snapshot": {"matchId": old_id}})
            bridge = PredictionArchiveTransport(send, current, holder)
            self.assertFalse(await bridge.collect({"id": old_id}))
            self.assertIsNone(holder.get_snapshot_for_match(current.id))
        asyncio.run(run())

    def test_disconnected_gui_does_not_block_local_settlement_save(self):
        async def run():
            current = CurrentMatch()
            async def send(request):
                raise OSError("disconnected")
            bridge = PredictionArchiveTransport(send, current, ActivePredictionSnapshotHolder())
            self.assertTrue(await bridge.collect({"id": current.id}))
            self.assertEqual(bridge.pending, {})
        asyncio.run(run())

    def test_real_ws_completed_prediction_saved_by_worker_loop(self):
        async def run():
            current = CurrentMatch()
            gui_holder = ActivePredictionSnapshotHolder()
            worker_holder = ActivePredictionSnapshotHolder()
            snapshot = run_js_solver({"matchId": current.id, "q": 9, "goldAvg": 33538,
                                      "purpleCount": 5})["predictionSnapshot"]
            stop = {"stop": False}
            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(main, "CURRENT_MATCH", current), \
                 patch.object(main, "ACTIVE_SNAPSHOT_HOLDER", gui_holder), \
                 patch.object(main, "LATEST_PAYLOAD", {}), \
                 patch.object(main, "CONNECTED_CLIENTS", set()), \
                 patch.object(main, "_LIVE_WORKER_SOCKET", None), \
                 patch.object(live_shadow, "_LATEST_PREDICTION_SNAPSHOT", snapshot), \
                 patch.object(live_shadow, "_LATEST_FROZEN_PREDICTION", {}), \
                 patch("auto_archiver.ACTIVE_SNAPSHOT_HOLDER", worker_holder):
                path = Path(directory) / "history.json"
                async with main.websockets.serve(main.ws_handler, "127.0.0.1", 0) as server:
                    port = server.sockets[0].getsockname()[1]
                    async with main.websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                        await ws.send(json.dumps({"type": "vision_worker_hello"}))
                        self.assertEqual(json.loads(await ws.recv())["action"], "worker_resume")
                        async def send(request):
                            await ws.send(json.dumps(request))
                        bridge = PredictionArchiveTransport(send, current, worker_holder)
                        async def watch():
                            async for raw in ws:
                                bridge.receive(json.loads(raw))
                        watcher = asyncio.create_task(watch())
                        async def publish(payload):
                            stop["stop"] = True
                        ctx = settlement_fixture.LiveSettlementAuthorityTests().context(current.id, False)
                        try:
                            await asyncio.wait_for(run_vision_capture_loop(
                                pipeline=Mock(), current_match=current, stop_flag=stop,
                                frame_provider=lambda: (1, np.zeros((2, 2, 3), dtype=np.uint8), "now"),
                                process_frame_fn=lambda *a, **kw: copy.deepcopy(ctx),
                                archiver=AutoArchiver([str(path)]), before_archive_fn=bridge.collect,
                                publish_fn=publish, fps=1000), timeout=5)
                        finally:
                            watcher.cancel()
                            await asyncio.gather(watcher, return_exceptions=True)
                rows = json.loads(path.read_text(encoding="utf-8"))
                rows = rows if isinstance(rows, list) else rows["records"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["predictionSnapshot"], snapshot)
                self.assertEqual(rows[0]["id"], current.id)
                self.assertEqual(rows[0]["lifecycleStatus"], "FINALIZED")
        asyncio.run(run())
