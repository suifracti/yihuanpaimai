"""Historical settlement continuation must not become current-match work."""

import copy
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from native_trial_drafts import NativeTrialDraftStore
from settlement_inventory_archive import SettlementInventoryArchive


class SettlementInventoryArchiveTests(unittest.TestCase):
    def test_leaving_match_then_retry_preserves_current_and_human_review(self):
        session = ROOT / "build/native-observation/session-67a3ae28777a406eaf6e18614237d62e"
        original = NativeTrialDraftStore(ROOT / "build/native-observation/trial-drafts/canonical-history.json")
        state = json.loads((session / "settlement-final-state.json").read_text(encoding="utf-8"))
        last = state["state"]["lastFrame"]
        saved = original.lookup(last["stateMatchId"])
        self.assertIsNotNone(saved)
        known_before = {key: saved.get(key) for key in ("knownGold", "knownPurple", "predictionSnapshot")}
        expected_items = copy.deepcopy(saved["settlement"]["settlementItems"])
        expected_visible = copy.deepcopy(saved["settlement"]["visibleInventory"])

        with tempfile.TemporaryDirectory(dir=ROOT / "build") as temp:
            store = NativeTrialDraftStore(Path(temp) / "canonical-history.json")
            old = copy.deepcopy(saved)
            old["settlement"].pop("inventoryArchive", None)
            old["settlement"].pop("settlementItems", None)
            old["settlement"].pop("visibleInventory", None)
            native = old["auctionEvidence"]["nativeObservation"]
            native.update(sourceFrames=[], intelSourceFrames=[], warehouseSlotSources=[], warehouseInstanceDecisions=[])
            source = store.capture_frame(session / "settlement-final-frame.bmp", {
                "frameSequence": last["frameSequence"], "capturedAtUtc": last["capturedAt"],
                "observationSessionId": state["state"]["sessionId"],
                "targetInstance": state["state"]["observationTargetIdentity"],
            }, expected_pixel_sha256=last["pixelSha256"])
            source.update(settlementBoundary=True, pixelSha256=last["pixelSha256"])
            native["sourceFrames"] = [source]
            store.save_draft(old)
            next_match = copy.deepcopy(old)
            next_match["id"] = "draft_unrelated_next_match"
            next_match["recordStableKey"] = next_match["id"]
            next_match["auctionEvidence"]["nativeObservation"]["sourceFrames"] = []
            next_match["settlement"] = {}
            store.save_draft(next_match)
            next_before = store.lookup(next_match["id"])

            calls = []
            def processor(_store, record_id, received_source):
                calls.append(record_id)
                self.assertEqual(received_source["pixelSha256"], last["pixelSha256"])
                if len(calls) == 1:
                    raise RuntimeError("one transient archival failure")
                return {"settlementItems": expected_items, "visibleInventory": expected_visible}

            archive = SettlementInventoryArchive(store, processor)
            self.assertEqual(archive.enqueue_saved_draft(store.lookup(old["id"])), "PENDING")
            archive.executor.shutdown(wait=True)
            failed = store.lookup(old["id"])
            self.assertEqual(failed["settlement"]["inventoryArchive"]["status"], "FAILED")

            # Another match may now be current; the historical worker must
            # only patch the bound old DRAFT and preserve late human review.
            store.patch_inventory_archive(old["id"], {"reviewedItems": [{"reviewedBy": "user", "name": "manual"}]},
                                          {"sourceKey": failed["settlement"]["inventoryArchive"]["sourceKey"]})
            retry_archive = SettlementInventoryArchive(store, processor)
            # Simulate process termination after the durable retry transition
            # but before its worker could run.
            retry_archive.executor.shutdown(wait=True)
            retry_archive.executor = ThreadPoolExecutor(max_workers=1)
            original_submit = retry_archive.executor.submit
            retry_archive.executor.submit = lambda *args, **kwargs: None
            self.assertEqual(retry_archive.retry(old["id"]), "PENDING")
            retry_archive.executor.submit = original_submit
            retry_archive.executor.shutdown(wait=True)
            resumed = SettlementInventoryArchive(store, processor)
            self.assertEqual(resumed.resume_pending(), 1)
            resumed.executor.shutdown(wait=True)
            done = store.lookup(old["id"])
            self.assertEqual(done["settlement"]["inventoryArchive"]["status"], "SAVED")
            self.assertEqual(done["settlement"]["reviewedItems"], [{"reviewedBy": "user", "name": "manual"}])
            self.assertEqual({key: done.get(key) for key in known_before}, known_before)
            self.assertEqual(store.lookup(next_match["id"]), next_before)
            self.assertEqual(len(calls), 2)
            store.save_draft(old)  # a delayed ordinary draft write has stale settlement fields
            self.assertEqual(store.lookup(old["id"])["settlement"]["inventoryArchive"]["status"], "SAVED")
            self.assertEqual(store.lookup(old["id"])["settlement"]["reviewedItems"],
                             [{"reviewedBy": "user", "name": "manual"}])
            self.assertEqual(resumed.enqueue_saved_draft(done), "SAVED")
            self.assertEqual(len(calls), 2)
