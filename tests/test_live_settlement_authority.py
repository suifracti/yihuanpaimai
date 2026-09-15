"""Exercise settlement evidence through live sync, disk archive and worker loop."""
import asyncio
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for directory in (PROJECT_ROOT / "app", PROJECT_ROOT / "core"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import numpy as np
import main
from auto_archiver import AutoArchiver
from current_match import CurrentMatch
from vision_worker_loop import apply_archive_lifecycle, run_vision_capture_loop


class LiveSettlementAuthorityTests(unittest.TestCase):
    def test_closed_worker_socket_exits_loop_for_reconnect(self):
        class ClosedSocket:
            async def send(self, payload):
                raise OSError("connection closed")
        with self.assertRaises(ConnectionError):
            asyncio.run(run_vision_capture_loop(
                pipeline=None, ws=ClosedSocket(),
                frame_provider=lambda: (None, None, "now"),
            ))

    def test_live_facts_are_synchronized_before_archive_runs(self):
        current = CurrentMatch()
        stop = {"stop": False}
        ctx = self.context(current.id, False)
        ctx["goldCount"] = 4
        observed = []
        def archive(frame):
            observed.append(current.to_canonical())
            return {"id": current.id, "lifecycleStatus": "DRAFT"}
        async def publish(payload):
            stop["stop"] = True
        with patch.object(main, "CURRENT_MATCH", current):
            asyncio.run(run_vision_capture_loop(
                pipeline=Mock(), current_match=current, stop_flag=stop,
                frame_provider=lambda: (1, np.zeros((2, 2, 3), dtype=np.uint8), "now"),
                process_frame_fn=lambda *a, **kw: ctx,
                sync_context_fn=main.sync_vision_to_current_match,
                archiver=Mock(archive_match=archive), publish_fn=publish, fps=1000,
            ))
        self.assertEqual(observed[0]["qualities"]["gold"]["count"], 4)
        self.assertIs(observed[0]["settlement"]["acquired"], False)

    def context(self, match_id, acquired):
        return {"id": match_id, "matchId": match_id, "isSettlement": True,
                "scene": "SETTLEMENT", "settlementReady": True,
                "box": "实木宝箱", "fieldCondition": "standard",
                "settlementData": {"isSettlement": True, "clearingPrice": 10000,
                                   "actualTotal": 15000, "profit": 5000,
                                   "winner": "TestWinner", "acquired": acquired}}

    def test_live_sync_and_archive_agree_on_explicit_bool_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            for raw in (True, False, None, "false", "true", "unknown", 0, 1, 2, {"x": 1}):
                with self.subTest(raw=raw):
                    current = CurrentMatch()
                    ctx = self.context(current.id, raw)
                    with patch.object(main, "CURRENT_MATCH", current):
                        main.sync_vision_to_current_match(ctx)
                    expected = raw if isinstance(raw, bool) else None
                    self.assertIs(current.to_canonical()["settlement"]["acquired"], expected)
                    saved = AutoArchiver([str(Path(tmp) / "history.json")]).archive_match(ctx)
                    self.assertIsNotNone(saved)
                    self.assertIs(saved["settlement"]["acquired"], expected)

    def test_direct_current_match_rejects_non_boolean_values(self):
        for key in ("isAcquired", "didCurrentUserAcquire", "acquired"):
            for raw in ("false", "unknown", 1, 2, {"x": 1}):
                current = CurrentMatch()
                current.apply_facts({key: raw})
                self.assertIsNone(current.to_canonical()["settlement"]["acquired"])

    def test_live_observed_quantities_survive_into_canonical_record(self):
        current = CurrentMatch()
        with patch.object(main, "CURRENT_MATCH", current):
            main.sync_vision_to_current_match({
                "scene": "IN_AUCTION", "goldCount": 4, "totalItems": 30,
                "blueCount": 0, "greenAvg": 1234, "q": 12,
            })
        record = current.to_canonical()
        self.assertEqual(record["qualities"]["gold"]["count"], 4)
        self.assertEqual(record["qualities"]["blue"]["count"], 0)
        self.assertEqual(record["qualities"]["green"]["avg"], 1234)
        self.assertEqual(record["publicIntel"]["totalItems"], 30)

    def test_same_bill_next_match_and_new_evidence_are_not_debounced(self):
        with tempfile.TemporaryDirectory() as tmp:
            archiver = AutoArchiver([str(Path(tmp) / "history.json")])
            for match_id, acquired in (("first", None), ("first", False), ("second", False)):
                saved = archiver.archive_match(self.context(match_id, acquired))
                self.assertIsNotNone(saved)
                self.assertEqual(saved["id"], match_id)
                self.assertIs(saved["settlement"]["acquired"], acquired)

    def test_worker_draft_remains_draft_and_does_not_finalize_pipeline(self):
        current = CurrentMatch()
        pipe = Mock()
        stop = {"stop": False}
        ctx = self.context(current.id, None)
        archived = {"id": current.id, "lifecycleStatus": "DRAFT"}
        async def publish(payload):
            stop["stop"] = True
        asyncio.run(run_vision_capture_loop(
            pipeline=pipe, current_match=current, stop_flag=stop,
            frame_provider=lambda: (1, np.zeros((2, 2, 3), dtype=np.uint8), "now"),
            process_frame_fn=lambda *a, **kw: copy.deepcopy(ctx),
            archiver=Mock(archive_match=Mock(return_value=archived)),
            publish_fn=publish, fps=1000,
        ))
        self.assertEqual(current.lifecycle_status, "DRAFT")
        pipe.mark_settlement_finalized.assert_not_called()

    def test_finalize_requires_same_record_and_actual_final_status(self):
        current = CurrentMatch()
        pipe = Mock()
        apply_archive_lifecycle({"id": "old", "lifecycleStatus": "FINALIZED"}, pipe, current)
        self.assertEqual(current.lifecycle_status, "DRAFT")
        pipe.mark_settlement_finalized.assert_not_called()
        apply_archive_lifecycle({"id": current.id, "lifecycleStatus": "FINALIZED"}, pipe, current)
        self.assertEqual(current.lifecycle_status, "FINALIZED")
        pipe.mark_settlement_finalized.assert_called_once()

    def test_saved_draft_can_leave_settlement_without_false_finalization(self):
        from vision_pipeline import NTEVisionPipeline
        pipe = NTEVisionPipeline()
        current = CurrentMatch()
        pipe.current_context.update({"scene": "SETTLEMENT", "isSettlement": True,
                                     "q": 12, "settlementData": {"actualTotal": 15000}})
        self.assertFalse(pipe.clear_match_trunk())
        apply_archive_lifecycle({"id": current.id, "lifecycleStatus": "DRAFT"}, pipe, current)
        self.assertFalse(pipe._settlement_finalized)
        self.assertEqual(current.lifecycle_status, "DRAFT")
        pipe._end_match_on_lobby_or_egress()
        self.assertIsNone(pipe.current_context["q"])
        self.assertIsNone(pipe.current_context["settlementData"])
