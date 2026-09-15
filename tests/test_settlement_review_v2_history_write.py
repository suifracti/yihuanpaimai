"""Explicit review save writes Truth Evidence v2 fileOriginals into History."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from runtime_data import runtime_data_paths
from settlement_evidence_store_v2 import KIND_MAIN, KIND_WAREHOUSE, SettlementEvidenceStoreV2
from settlement_review import SettlementReviewService
from settlement_truth_evidence_contract import TRUTH_EVIDENCE_V1, TRUTH_EVIDENCE_V2
from settlement_truth_holder import build_settlement_truth_evidence_v1


def _png_bytes(color=(10, 20, 30)) -> bytes:
    image = np.zeros((16, 20, 3), dtype=np.uint8)
    image[:] = color
    return cv2.imencode(".png", image)[1].tobytes()


def _v1_truth(match_id: str, actual: float = 200000.0) -> dict:
    return build_settlement_truth_evidence_v1(
        match_id=match_id,
        actual_total=actual,
        settlement_observed_at="2026-08-25T12:00:00+08:00",
        truth_source="test_fixture",
        truth_confidence="medium",
        evidence_uri="evidence/settlement/old.png",
        evidence_sha256="ab" * 32,
    )


class ReviewSaveTruthEvidenceV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.prev_env = os.environ.get("YIHUAN_DATA_ROOT")
        prod_env = {key: value for key, value in os.environ.items() if key != "YIHUAN_DATA_ROOT"}
        try:
            self.prod_paths = runtime_data_paths(prod_env)
            self.prod_history = (
                self.prod_paths.history_path.read_bytes()
                if self.prod_paths.history_path.exists()
                else None
            )
        except Exception:
            self.prod_paths = None
            self.prod_history = None
        os.environ["YIHUAN_DATA_ROOT"] = str(self.root)
        self.history_path = self.root / "history" / "异环拍卖数据.json"
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = SettlementEvidenceStoreV2(self.root)
        self.history = CanonicalHistoryStore(self.history_path)
        self.service = SettlementReviewService(
            history_path_provider=lambda: str(self.history_path),
            data_root_provider=lambda: str(self.root),
        )

    def tearDown(self):
        if self.prev_env is None:
            os.environ.pop("YIHUAN_DATA_ROOT", None)
        else:
            os.environ["YIHUAN_DATA_ROOT"] = self.prev_env
        if self.prod_paths is not None:
            after = (
                self.prod_paths.history_path.read_bytes()
                if self.prod_paths.history_path.exists()
                else None
            )
            self.assertEqual(after, self.prod_history)
        self.tmp.cleanup()

    def _seed_record(self, match_id: str, truth=None) -> None:
        record = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-25T12:00:00+08:00",
            lifecycle_status="FINALIZED",
            source="vision-auto-archiver",
            environment={"venue": "珊瑚场", "box": "皮制宝箱", "fieldCondition": "standard"},
            settlement={
                "status": "verified",
                "verified": True,
                "clearingPrice": 100000,
                "actualTotal": 200000,
                "realizedProfit": 50000,
                "acquired": True,
                "winner": "玩家本人",
                "settlementItems": [],
                **({"truthEvidence": truth} if truth is not None else {}),
            },
        )
        self.history.persist_record_transactional(record, is_finalized=True)

    def _save_original(self, match_id: str, color=(1, 2, 3), kind=KIND_MAIN) -> dict:
        return self.store.save_original(
            record_stable_key=match_id,
            kind=kind,
            image_bytes=_png_bytes(color),
            captured_at="2026-08-25T12:00:00Z",
        )

    def _reviewed(self):
        return [{"slotIndex": 1, "itemId": "万有星仪", "status": "confirmed"}]

    def test_current_save_upgrades_v1_and_writes_one_descriptor(self):
        match_id = "recUpgrade01"
        self._seed_record(match_id, _v1_truth(match_id))
        desc = self._save_original(match_id)
        before = self.history_path.read_bytes()
        saved = self.service.save_reviewed_settlement(
            match_id, self._reviewed(), runtime_file_originals=[desc]
        )
        self.assertTrue(saved["ok"], saved)
        rec = self.history.lookup(match_id)
        ev = rec["settlement"]["truthEvidence"]
        self.assertEqual(ev["schemaVersion"], TRUTH_EVIDENCE_V2)
        self.assertEqual(ev["truthSource"], "test_fixture")
        self.assertEqual(ev["truthConfidence"], "medium")
        self.assertEqual(len(ev["fileOriginals"]), 1)
        self.assertEqual(ev["fileOriginals"][0]["evidenceId"], desc["evidenceId"])
        self.assertEqual(ev["fileOriginals"][0]["relativePath"], desc["relativePath"])
        self.assertTrue(all(set(ref.keys()) == {"uri", "sha256"} for ref in ev["evidenceReferences"]))
        self.assertNotEqual(self.history_path.read_bytes(), before)

    def test_repeat_save_is_idempotent(self):
        match_id = "recIdem01"
        self._seed_record(match_id, _v1_truth(match_id))
        desc = self._save_original(match_id, (4, 5, 6))
        self.service.save_reviewed_settlement(match_id, self._reviewed(), runtime_file_originals=[desc])
        self.service.save_reviewed_settlement(match_id, self._reviewed(), runtime_file_originals=[desc])
        rec = self.history.lookup(match_id)
        self.assertEqual(len(rec["settlement"]["truthEvidence"]["fileOriginals"]), 1)

    def test_append_different_legal_original(self):
        match_id = "recAppend01"
        self._seed_record(match_id, _v1_truth(match_id))
        first = self._save_original(match_id, (7, 8, 9), KIND_MAIN)
        self.service.save_reviewed_settlement(match_id, self._reviewed(), runtime_file_originals=[first])
        second = self._save_original(match_id, (11, 12, 13), KIND_WAREHOUSE)
        saved = self.service.save_reviewed_settlement(match_id, self._reviewed(), runtime_file_originals=[second])
        self.assertTrue(saved["ok"], saved)
        rec = self.history.lookup(match_id)
        self.assertEqual(len(rec["settlement"]["truthEvidence"]["fileOriginals"]), 2)

    def test_same_id_different_hash_rejects_and_keeps_history(self):
        match_id = "recConflict01"
        self._seed_record(match_id, _v1_truth(match_id))
        first = self._save_original(match_id, (20, 21, 22))
        self.service.save_reviewed_settlement(match_id, self._reviewed(), runtime_file_originals=[first])
        second = self._save_original(match_id, (23, 24, 25), KIND_WAREHOUSE)
        before = self.history_path.read_bytes()
        forged = dict(second)
        forged["evidenceId"] = first["evidenceId"]
        saved = self.service.save_reviewed_settlement(match_id, self._reviewed(), runtime_file_originals=[forged])
        self.assertFalse(saved["ok"])
        self.assertEqual(saved["status"], "FILE_ORIGINAL_ID_CONFLICT")
        self.assertEqual(self.history_path.read_bytes(), before)

    def test_key_mismatch_missing_file_and_traversal_reject(self):
        match_id = "recReject01"
        self._seed_record(match_id, _v1_truth(match_id))
        desc = self._save_original(match_id, (30, 31, 32))
        before = self.history_path.read_bytes()

        other = dict(desc)
        other["recordStableKey"] = "otherRecord"
        saved = self.service.save_reviewed_settlement(match_id, self._reviewed(), runtime_file_originals=[other])
        self.assertFalse(saved["ok"])
        self.assertEqual(saved["status"], "FILE_ORIGINAL_KEY_MISMATCH")

        missing = dict(desc)
        (self.root / desc["relativePath"]).unlink()
        saved = self.service.save_reviewed_settlement(match_id, self._reviewed(), runtime_file_originals=[missing])
        self.assertFalse(saved["ok"])
        self.assertIn(saved["status"], {"MISSING", "FILE_ORIGINAL_VERIFY_FAILED"})

        bad_path = dict(desc)
        bad_path["relativePath"] = "../escape/" + "ab" * 32 + ".png"
        saved = self.service.save_reviewed_settlement(match_id, self._reviewed(), runtime_file_originals=[bad_path])
        self.assertFalse(saved["ok"])
        self.assertEqual(self.history_path.read_bytes(), before)

    def test_no_runtime_descriptor_keeps_legal_v1(self):
        match_id = "recV1Only01"
        self._seed_record(match_id, _v1_truth(match_id))
        saved = self.service.save_reviewed_settlement(
            match_id, self._reviewed(), runtime_file_originals=[]
        )
        self.assertTrue(saved["ok"], saved)
        ev = self.history.lookup(match_id)["settlement"]["truthEvidence"]
        self.assertEqual(ev["schemaVersion"], TRUTH_EVIDENCE_V1)
        self.assertNotIn("fileOriginals", ev)

    def test_client_forged_descriptor_is_ignored(self):
        match_id = "recForge01"
        self._seed_record(match_id, _v1_truth(match_id))
        fake = {
            "schemaVersion": "settlement-evidence-original-v2",
            "evidenceId": "forged",
            "recordStableKey": match_id,
            "kind": "main-settlement",
            "capturedAt": "2026-08-25T12:00:00Z",
            "storageMode": "file",
            "relativePath": "evidence/settlement_v2/blobs/aa/" + "aa" * 32 + ".png",
            "sha256": "aa" * 32,
            "byteSize": 9,
            "mimeType": "image/png",
            "width": 1,
            "height": 1,
            "coverageMode": "viewport-segment",
            "coverageStatus": "COVERAGE_UNPROVEN",
        }
        saved = self.service.save_reviewed_settlement(
            match_id,
            self._reviewed(),
            review_meta={"fileOriginals": [fake], "descriptor": fake, "relativePath": "C:/evil.png"},
            runtime_file_originals=[],
        )
        self.assertTrue(saved["ok"], saved)
        ev = self.history.lookup(match_id)["settlement"]["truthEvidence"]
        self.assertEqual(ev["schemaVersion"], TRUTH_EVIDENCE_V1)
        self.assertNotIn("fileOriginals", ev)

    def test_screenshot_refs_do_not_include_type(self):
        match_id = "recNoType01"
        self._seed_record(match_id, _v1_truth(match_id))
        saved = self.service.save_reviewed_settlement(
            match_id,
            self._reviewed(),
            review_meta={"screenshotUri": "evidence/settlement/import_x.png", "screenshotSha256": "cd" * 32},
            runtime_file_originals=[],
        )
        self.assertTrue(saved["ok"], saved)
        refs = self.history.lookup(match_id)["settlement"]["truthEvidence"]["evidenceReferences"]
        self.assertTrue(all(set(ref.keys()) == {"uri", "sha256"} for ref in refs))
        self.assertNotIn("type", json.dumps(refs))

    def test_legacy_source_does_not_change_canonical_history(self):
        match_id = "recLegacy01"
        self._seed_record(match_id, _v1_truth(match_id))
        before = self.history_path.read_bytes()
        saved = self.service.save_reviewed_settlement(
            match_id, self._reviewed(), source="legacy", runtime_file_originals=[self._save_original(match_id)]
        )
        self.assertFalse(saved.get("ok"))
        self.assertEqual(self.history_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
