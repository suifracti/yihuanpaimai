"""Unit tests for Warehouse Coverage Ledger v1."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(CORE_DIR),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from settlement_truth_evidence_contract import ORIGINAL_V2
from warehouse_coverage_ledger import (
    REASON_COMPLETE,
    REASON_MISSING_OVERLAP,
    REASON_TIMEOUT,
    REASON_USER_STOP,
    SCHEMA_VERSION,
    STATUS_COMPLETE,
    STATUS_PARTIAL,
    STATUS_UNPROVEN,
    WarehouseCoverageLedger,
    WarehouseCoverageLedgerError,
    validate_warehouse_coverage_ledger,
)


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _segment_original(evidence_id: str, seed: str, key: str = "recWH01", **overrides):
    digest = _digest(seed)
    item = {
        "schemaVersion": ORIGINAL_V2,
        "evidenceId": evidence_id,
        "recordStableKey": key,
        "kind": "warehouse-segment",
        "capturedAt": "2026-08-25T12:00:00Z",
        "storageMode": "file",
        "relativePath": f"evidence/settlement_v2/blobs/{digest[:2]}/{digest}.png",
        "sha256": digest,
        "byteSize": 1024,
        "mimeType": "image/png",
        "width": 640,
        "height": 720,
        "coverageMode": "viewport-segment",
        "coverageStatus": "PARTIAL",
    }
    item.update(overrides)
    return item


def _top(proof_id="top-1"):
    return {"trusted": True, "proofId": proof_id}


def _bottom(proof_id="bottom-1"):
    return {"trusted": True, "proofId": proof_id}


def _overlap(prev_id: str, proof_id="ov-1"):
    return {"trusted": True, "aligned": True, "proofId": proof_id, "previousEvidenceId": prev_id}


class WarehouseCoverageLedgerV1Tests(unittest.TestCase):
    def test_empty_ledger_is_unproven(self):
        ledger = WarehouseCoverageLedger("recWH01")
        snap = ledger.snapshot()
        self.assertEqual(snap["coverageStatus"], STATUS_UNPROVEN)
        self.assertFalse(snap["finalized"])
        ok, reasons = validate_warehouse_coverage_ledger(snap)
        self.assertTrue(ok, reasons)

    def test_top_only_finalize_partial(self):
        ledger = WarehouseCoverageLedger("recWH01")
        ledger.add_segment(_segment_original("s1", "aa"), sequence_index=0, top_proof=_top())
        snap = ledger.finalize(REASON_COMPLETE)
        self.assertEqual(snap["coverageStatus"], STATUS_PARTIAL)
        self.assertNotEqual(snap["coverageStatus"], STATUS_COMPLETE)

    def test_bottom_only_finalize_partial(self):
        ledger = WarehouseCoverageLedger("recWH01")
        ledger.add_segment(_segment_original("s1", "bb"), sequence_index=0, bottom_proof=_bottom())
        snap = ledger.finalize(REASON_COMPLETE)
        self.assertEqual(snap["coverageStatus"], STATUS_PARTIAL)

    def test_top_mid_bottom_with_overlap_can_complete(self):
        ledger = WarehouseCoverageLedger("recWH01")
        ledger.add_segment(_segment_original("top", "aa"), sequence_index=0, top_proof=_top())
        ledger.add_segment(
            _segment_original("mid", "bb"),
            sequence_index=1,
            overlap_proof=_overlap("top"),
        )
        ledger.add_segment(
            _segment_original("bot", "cc"),
            sequence_index=2,
            bottom_proof=_bottom(),
            overlap_proof=_overlap("mid", "ov-2"),
        )
        open_snap = ledger.snapshot()
        self.assertNotEqual(open_snap["coverageStatus"], STATUS_COMPLETE)
        snap = ledger.finalize(REASON_COMPLETE)
        self.assertEqual(snap["coverageStatus"], STATUS_COMPLETE)
        self.assertTrue(snap["finalized"])
        self.assertEqual(snap["terminationReason"], REASON_COMPLETE)
        again = ledger.finalize(REASON_USER_STOP)
        self.assertEqual(again["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(again["terminationReason"], REASON_COMPLETE)

    def test_missing_overlap_is_partial(self):
        ledger = WarehouseCoverageLedger("recWH01")
        ledger.add_segment(_segment_original("top", "aa"), sequence_index=0, top_proof=_top())
        ledger.add_segment(_segment_original("bot", "cc"), sequence_index=1, bottom_proof=_bottom())
        snap = ledger.finalize(REASON_COMPLETE)
        self.assertEqual(snap["coverageStatus"], STATUS_PARTIAL)
        self.assertEqual(snap["terminationReason"], REASON_MISSING_OVERLAP)
        self.assertTrue(snap["gaps"])

    def test_order_regression_is_conflict_partial(self):
        ledger = WarehouseCoverageLedger("recWH01")
        ledger.add_segment(_segment_original("top", "aa"), sequence_index=2, top_proof=_top())
        snap = ledger.add_segment(_segment_original("back", "bb"), sequence_index=1, bottom_proof=_bottom())
        self.assertTrue(any(item["code"] == "ORDER_CONFLICT" for item in snap["conflicts"]))
        final = ledger.finalize(REASON_COMPLETE)
        self.assertEqual(final["coverageStatus"], STATUS_PARTIAL)

    def test_user_stop_and_timeout_are_partial(self):
        ledger = WarehouseCoverageLedger("recWH01")
        ledger.add_segment(_segment_original("top", "aa"), sequence_index=0, top_proof=_top())
        snap = ledger.finalize(REASON_USER_STOP)
        self.assertEqual(snap["coverageStatus"], STATUS_PARTIAL)
        self.assertEqual(snap["terminationReason"], REASON_USER_STOP)
        other = WarehouseCoverageLedger("recWH02")
        other.add_segment(_segment_original("top", "aa", key="recWH02"), sequence_index=0, top_proof=_top())
        timed = other.finalize(REASON_TIMEOUT)
        self.assertEqual(timed["coverageStatus"], STATUS_PARTIAL)
        self.assertEqual(timed["terminationReason"], REASON_TIMEOUT)

    def test_duplicate_segment_is_idempotent(self):
        ledger = WarehouseCoverageLedger("recWH01")
        original = _segment_original("s1", "aa")
        ledger.add_segment(original, sequence_index=0, top_proof=_top())
        ledger.add_segment(copy.deepcopy(original), sequence_index=0, top_proof=_top())
        self.assertEqual(len(ledger.snapshot()["segments"]), 1)

    def test_same_id_different_hash_is_conflict(self):
        ledger = WarehouseCoverageLedger("recWH01")
        first = _segment_original("s1", "aa")
        ledger.add_segment(first, sequence_index=0, top_proof=_top())
        second = _segment_original("s1", "ff")
        snap = ledger.add_segment(second, sequence_index=1, bottom_proof=_bottom())
        self.assertTrue(any(item["code"] == "HASH_CONFLICT" for item in snap["conflicts"]))
        self.assertEqual(len(snap["segments"]), 1)
        final = ledger.finalize(REASON_COMPLETE)
        self.assertEqual(final["coverageStatus"], STATUS_PARTIAL)

    def test_stable_key_mismatch_is_rejected(self):
        ledger = WarehouseCoverageLedger("recWH01")
        with self.assertRaises(WarehouseCoverageLedgerError) as raised:
            ledger.add_segment(_segment_original("s1", "aa", key="otherKey"), sequence_index=0)
        self.assertEqual(raised.exception.code, "RECORD_KEY_MISMATCH")
        with self.assertRaises(WarehouseCoverageLedgerError) as raised:
            ledger.add_segment(_segment_original("s1", "aa", kind="main-settlement"), sequence_index=0)
        self.assertEqual(raised.exception.code, "INVALID_KIND")

    def test_single_segment_with_top_and_bottom_can_complete(self):
        ledger = WarehouseCoverageLedger("recWH01")
        ledger.add_segment(
            _segment_original("full", "aa"),
            sequence_index=0,
            top_proof=_top(),
            bottom_proof=_bottom(),
        )
        self.assertNotEqual(ledger.snapshot()["coverageStatus"], STATUS_COMPLETE)
        snap = ledger.finalize(REASON_COMPLETE)
        self.assertEqual(snap["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(len(snap["segments"]), 1)

    def test_not_finalized_cannot_be_complete(self):
        ledger = WarehouseCoverageLedger("recWH01")
        ledger.add_segment(
            _segment_original("full", "aa"),
            sequence_index=0,
            top_proof=_top(),
            bottom_proof=_bottom(),
        )
        snap = ledger.snapshot()
        self.assertEqual(snap["coverageStatus"], STATUS_PARTIAL)
        self.assertFalse(snap["finalized"])

    def test_contract_rejects_unknown_fields_and_complete_segment_status(self):
        ledger = WarehouseCoverageLedger("recWH01")
        snap = ledger.snapshot()
        snap["unexpected"] = True
        ok, reasons = validate_warehouse_coverage_ledger(snap)
        self.assertFalse(ok)
        self.assertIn("UNKNOWN_FIELD_unexpected", reasons)
        with self.assertRaises(WarehouseCoverageLedgerError):
            ledger.add_segment(_segment_original("s1", "aa", extra="nope"), sequence_index=0)
        schema = json.loads(
            (PROJECT_ROOT / "docs" / "contracts" / "warehouse-coverage-ledger-v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
