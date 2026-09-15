import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for entry in (str(PROJECT_ROOT / "core"), str(PROJECT_ROOT / "app"), str(PROJECT_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import main
from canonical_history_store import CanonicalHistoryStore, FinalizedRecordConflictError, HistoryStoreError
from canonical_match_record import build_canonical_match_record_v7
from current_match import CurrentMatch


class TestFinalizedEvidenceEnrichment(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_finalized_enrich_"))
        self.history_path = self.temp_dir / "history" / "异环拍卖数据.json"
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = CanonicalHistoryStore(str(self.history_path))

        self.match_id = "test_match_finalized_20260913"
        self.base_record = build_canonical_match_record_v7(
            match_id=self.match_id,
            played_at="2026-09-13T21:20:00Z",
            lifecycle_status="FINALIZED",
            source="manual",
            environment={"venue": "珊瑚场", "box": "实木宝箱", "fieldCondition": "standard"},
            qualities={"gold": {"count": 4, "avg": 50000}},
            public_intel={"q": 17},
            bidding={
                "roundQuotes": {"R1": [711111, 0, 555555, 333333]},
                "historicalBids": {"致敬最良心不歪": {"1": 711111}},
            },
            settlement={
                "status": "verified",
                "verified": True,
                "clearingPrice": 1222222,
                "actualTotal": 1556124,
                "realizedProfit": 333902,
                "winner": "致敬最良心不歪",
                "acquired": True,
            },
        )
        self.store.persist_record_transactional(self.base_record, is_finalized=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generic_persist_remains_strictly_forbidden_on_finalized_record(self):
        """Generic persist_record_transactional must continue to fail-closed on differing content."""
        differing = copy.deepcopy(self.base_record)
        differing["settlement"]["clearingPrice"] = 999999
        with self.assertRaises(FinalizedRecordConflictError):
            self.store.persist_record_transactional(differing, is_finalized=True)

    def test_append_finalized_evidence_success_and_audit_trail(self):
        """append_finalized_evidence safely appends evidence link and increments audit trail."""
        evidence_entry = {
            "evidenceId": "sev2_test_capture_001",
            "kind": "manual-game",
            "capturedAt": "2026-09-13T21:23:25+08:00",
            "relativePath": "evidence/settlement_v2/blobs/ab/abcdef1234567890.png",
            "sha256": "abcdef1234567890" * 4,
            "width": 1920,
            "height": 1080,
        }
        updated = self.store.append_finalized_evidence(
            self.match_id,
            evidence_entry=evidence_entry,
            audit_reason="TEST_POST_FINALIZATION_EVIDENCE",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated["lifecycleStatus"], "FINALIZED")
        # Core facts strictly unchanged
        self.assertEqual(updated["settlement"]["clearingPrice"], 1222222)
        self.assertEqual(updated["settlement"]["actualTotal"], 1556124)
        self.assertEqual(updated["settlement"]["winner"], "致敬最良心不歪")

        # Evidence appended
        captures = updated["settlement"]["evidenceAttachments"]["captures"]
        self.assertEqual(len(captures), 1)
        self.assertEqual(captures[0]["evidenceId"], "sev2_test_capture_001")

        # Audit trail recorded
        audit = updated["evidenceAuditTrail"]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["revision"], 1)
        self.assertEqual(audit[0]["auditReason"], "TEST_POST_FINALIZATION_EVIDENCE")

        # Second append increments audit trail and deduplicates if identical sha
        updated2 = self.store.append_finalized_evidence(
            self.match_id,
            evidence_entry=evidence_entry,
            audit_reason="TEST_DUPLICATE_APPEND",
        )
        self.assertEqual(len(updated2["settlement"]["evidenceAttachments"]["captures"]), 1)
        self.assertEqual(len(updated2["evidenceAuditTrail"]), 2)
        self.assertEqual(updated2["evidenceAuditTrail"][1]["revision"], 2)

    def test_append_finalized_evidence_rejects_forbidden_core_fields(self):
        """Mutating core settlement facts via append_finalized_evidence must be rejected."""
        with self.assertRaises(HistoryStoreError) as ctx:
            self.store.append_finalized_evidence(
                self.match_id,
                review_update={"clearingPrice": 999999},
            )
        self.assertIn("FORBIDDEN_MUTATION", str(ctx.exception))

    def test_append_finalized_evidence_rejects_unauthorized_fields(self):
        """Mutating unallowlisted arbitrary fields must be rejected."""
        with self.assertRaises(HistoryStoreError) as ctx:
            self.store.append_finalized_evidence(
                self.match_id,
                review_update={"unauthorizedCustomField": "evil"},
            )
        self.assertIn("UNAUTHORIZED_FIELD", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
