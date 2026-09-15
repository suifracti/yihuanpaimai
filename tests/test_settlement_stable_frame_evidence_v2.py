"""Stable settlement frame -> Evidence Store v2 integration tests."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from runtime_data import runtime_data_paths
from settlement_evidence_store_v2 import KIND_MAIN, SettlementEvidenceStoreV2
from settlement_stable_frame_persist import (
    STATUS_EVIDENCE_PERSIST_FAILED,
    STATUS_IDEMPOTENT,
    STATUS_MISSING_STABLE_KEY,
    STATUS_SAVED,
    STATUS_SKIPPED_NOT_SETTLEMENT,
    persist_stable_settlement_original,
)
from vision_pipeline import SETTLEMENT_STABLE_FRAMES, NTEVisionPipeline


def _frame(color=(20, 40, 60)) -> np.ndarray:
    image = np.zeros((24, 32, 3), dtype=np.uint8)
    image[:] = color
    return image


def _final_settlement() -> dict:
    return {
        "isSettlement": True,
        "clearingPrice": 100000,
        "actualTotal": 150000,
        "profit": 50000,
    }


class SettlementStableFrameEvidenceV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "runtime"
        self.root.mkdir()
        self.store = SettlementEvidenceStoreV2(self.root)
        self.prod = runtime_data_paths()
        self.prod_history = (
            self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        )

    def tearDown(self):
        after = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        self.assertEqual(after, self.prod_history)
        self.tmp.cleanup()

    def _pipe(self) -> NTEVisionPipeline:
        pipe = NTEVisionPipeline()
        pipe._settlement_evidence_store = self.store
        pipe.current_context["id"] = "stableMatch01"
        pipe.current_context["matchId"] = "stableMatch01"
        return pipe

    def _stabilize_until_ready(self, pipe, frame=None, captured_at="2026-08-25T12:00:00+08:00"):
        image = frame if frame is not None else _frame()
        for _ in range(SETTLEMENT_STABLE_FRAMES):
            pipe._stabilize_settlement(_final_settlement(), frame=image, captured_at=captured_at)
        return image

    def test_stable_frame_writes_one_blob_and_descriptor(self):
        pipe = self._pipe()
        frame = self._stabilize_until_ready(pipe)
        self.assertTrue(pipe.current_context["settlementReady"])
        desc = pipe.current_context["settlementFileEvidence"]
        self.assertIsInstance(desc, dict)
        self.assertEqual(desc["kind"], KIND_MAIN)
        self.assertEqual(desc["coverageMode"], "viewport-segment")
        self.assertEqual(desc["coverageStatus"], "COVERAGE_UNPROVEN")
        self.assertEqual(desc["recordStableKey"], "stableMatch01")
        self.assertEqual(pipe.current_context["settlementFileEvidenceStatus"], STATUS_SAVED)
        blobs = list((self.root / "evidence" / "settlement_v2" / "blobs").rglob("*"))
        blob_files = [path for path in blobs if path.is_file()]
        self.assertEqual(len(blob_files), 1)
        listed = self.store.list_record_evidence("stableMatch01")
        self.assertEqual(len(listed), 1)
        encoded = cv2.imencode(".png", frame)[1].tobytes()
        self.assertEqual(self.store.load_original(desc), encoded)
        self.assertEqual(desc["sha256"], hashlib.sha256(encoded).hexdigest())

    def test_repeated_stable_frames_are_idempotent(self):
        pipe = self._pipe()
        frame = _frame((7, 8, 9))
        self._stabilize_until_ready(pipe, frame=frame)
        first = dict(pipe.current_context["settlementFileEvidence"])
        pipe._stabilize_settlement(_final_settlement(), frame=frame, captured_at="2026-08-25T12:00:01+08:00")
        second = pipe.current_context["settlementFileEvidence"]
        self.assertEqual(first["evidenceId"], second["evidenceId"])
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(pipe.current_context["settlementFileEvidenceStatus"], STATUS_IDEMPOTENT)
        self.assertEqual(len(self.store.list_record_evidence("stableMatch01")), 1)
        self.assertEqual(len([p for p in (self.root / "evidence" / "settlement_v2" / "blobs").rglob("*") if p.is_file()]), 1)

    def test_non_settlement_does_not_write(self):
        result = persist_stable_settlement_original(
            store=self.store,
            is_settlement=False,
            record_stable_key="stableMatch01",
            frame=_frame(),
        )
        self.assertEqual(result["status"], STATUS_SKIPPED_NOT_SETTLEMENT)
        self.assertIsNone(result["descriptor"])
        self.assertFalse((self.root / "evidence").exists())

    def test_missing_stable_key_does_not_write(self):
        pipe = NTEVisionPipeline()
        pipe._settlement_evidence_store = self.store
        self._stabilize_until_ready(pipe)
        self.assertTrue(pipe.current_context["settlementReady"])
        self.assertIsNone(pipe.current_context.get("settlementFileEvidence"))
        self.assertEqual(pipe.current_context["settlementFileEvidenceStatus"], STATUS_MISSING_STABLE_KEY)
        self.assertIn("missing recordStableKey", pipe.current_context["settlementFileEvidenceWarning"])
        self.assertFalse((self.root / "evidence").exists())

    def test_store_failure_does_not_block_settlement_ready(self):
        pipe = self._pipe()
        boom_store = mock.Mock()
        boom_store.save_original.side_effect = RuntimeError("disk full")
        pipe._settlement_evidence_store = boom_store
        self._stabilize_until_ready(pipe)
        self.assertTrue(pipe.current_context["settlementReady"])
        self.assertIsNone(pipe.current_context.get("settlementFileEvidence"))
        self.assertEqual(pipe.current_context["settlementFileEvidenceStatus"], STATUS_EVIDENCE_PERSIST_FAILED)
        self.assertIn("EVIDENCE_PERSIST_FAILED", pipe.current_context["settlementFileEvidenceWarning"])
        self.assertFalse((self.root / "evidence").exists())

    def test_real_settlement_fixture_writes_evidence_store_v2_with_partial_coverage(self):
        """
        Verify Settlement Stable-Frame -> Evidence Store v2 Wiring (4D2D1M-C3.1):
        1. Stable settlement frame written to file-backed Evidence Store v2.
        2. Raw image bytes can be re-read and decoded back to exact dimensions (1920x1080).
        3. sha256 matches exactly with original PNG bytes.
        4. coverageStatus is strictly COVERAGE_UNPROVEN / PARTIAL (never COMPLETE).
        5. knownItems is untouched.
        """
        fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "real_snapshots_4d2d1j" / "fixture_settlement_client_sanitized.png"
        img = cv2.imread(str(fixture_path))
        self.assertIsNotNone(img)

        pipe = self._pipe()
        pipe.current_context["id"] = "match_c31_real_001"
        pipe.current_context["matchId"] = "match_c31_real_001"
        pipe.current_context["recordStableKey"] = "match_c31_real_001"

        settlement_info = {
            "isSettlement": True,
            "clearingPrice": 600000,
            "actualTotal": 785974,
            "profit": 185974,
        }

        for _ in range(SETTLEMENT_STABLE_FRAMES):
            pipe._stabilize_settlement(settlement_info, frame=img, captured_at="2026-08-30T00:00:01+08:00")

        self.assertTrue(pipe.current_context["settlementReady"])
        desc = pipe.current_context.get("settlementFileEvidence")
        self.assertIsInstance(desc, dict)
        self.assertEqual(desc["kind"], KIND_MAIN)
        self.assertEqual(desc["recordStableKey"], "match_c31_real_001")
        self.assertEqual(desc["coverageStatus"], "COVERAGE_UNPROVEN")
        self.assertEqual(desc["coverageMode"], "viewport-segment")
        self.assertEqual(desc["width"], 1920)
        self.assertEqual(desc["height"], 1080)
        self.assertEqual(desc["mimeType"], "image/png")
        self.assertEqual(pipe.current_context["settlementFileEvidenceStatus"], STATUS_SAVED)

        # 2. File can be re-read from store
        loaded_bytes = self.store.load_original(desc)
        self.assertIsNotNone(loaded_bytes)
        self.assertEqual(len(loaded_bytes), desc["byteSize"])

        # 3. SHA-256 matches
        self.assertEqual(hashlib.sha256(loaded_bytes).hexdigest(), desc["sha256"])

        # 4. Coverage is strictly PARTIAL/COVERAGE_UNPROVEN, never COMPLETE
        self.assertNotEqual(desc["coverageStatus"], "COMPLETE")
        self.assertIn(desc["coverageStatus"], ("COVERAGE_UNPROVEN", "PARTIAL"))

        # 5. knownItems is untouched
        self.assertNotIn("knownItems", desc)
        self.assertEqual(pipe.current_context.get("knownGold"), [])
        self.assertEqual(pipe.current_context.get("knownPurple"), [])

    def test_live_bill_persistence_never_waits_for_item_recognition(self):
        # Regression: synchronous identity extraction stalled animated bill OCR
        # for 43 seconds. Explicit review has separate recognition coverage.
        pipe = self._pipe()
        with mock.patch("settlement_item_proposals.extract_settlement_warehouse_proposals",
                        side_effect=AssertionError("live bill must not recognize items")) as extract:
            self._stabilize_until_ready(pipe, frame=_frame((10, 20, 30)))
            first = dict(pipe.current_context["settlementFileEvidence"])
            # A changed countdown must not create another original every frame.
            pipe._stabilize_settlement(_final_settlement(), frame=_frame((20, 30, 40)),
                                       captured_at="2026-08-25T12:00:01+08:00")
            extract.assert_not_called()
        self.assertTrue(pipe.current_context["settlementReady"])
        self.assertEqual(pipe.current_context["settlementFileEvidence"]["sha256"], first["sha256"])
        self.assertEqual(len(self.store.list_record_evidence("stableMatch01")), 1)
        self.assertEqual(first["coverageStatus"], "COVERAGE_UNPROVEN")
        self.assertFalse(pipe.current_context.get("settlementIdentityEvidence"))
        # A genuinely different final bill must still be captured.
        changed = {**_final_settlement(), "actualTotal": 160000, "profit": 60000}
        for _ in range(SETTLEMENT_STABLE_FRAMES):
            pipe._stabilize_settlement(changed, frame=_frame((30, 40, 50)),
                                       captured_at="2026-08-25T12:00:02+08:00")
        self.assertEqual(len(self.store.list_record_evidence("stableMatch01")), 2)


if __name__ == "__main__":
    unittest.main()
