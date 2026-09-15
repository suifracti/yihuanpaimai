"""Contract tests for Truth Evidence v2 and Settlement Evidence Original v2."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
CONTRACTS = PROJECT_ROOT / "docs" / "contracts"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_match_record import (
    build_canonical_match_record_v7,
    validate_canonical_match_record_v7,
)
from settlement_truth_evidence_contract import (
    ORIGINAL_V2,
    TRUTH_EVIDENCE_V1,
    TRUTH_EVIDENCE_V2,
    classify_truth_evidence_version,
    load_contract_schema,
    matches_truth_evidence_versions,
    validate_settlement_evidence_original_v2,
    validate_truth_evidence_contract,
)
from settlement_truth_holder import build_settlement_truth_evidence_v1


def _digest(seed: str = "a") -> str:
    return (seed * 64)[:64]


def _original_v2(**overrides):
    digest = _digest("ab")
    item = {
        "schemaVersion": ORIGINAL_V2,
        "evidenceId": "sev2_recA_ab12_main-settlement",
        "recordStableKey": "recA",
        "kind": "main-settlement",
        "capturedAt": "2026-08-25T12:00:00Z",
        "storageMode": "file",
        "relativePath": f"evidence/settlement_v2/blobs/{digest[:2]}/{digest}.png",
        "sha256": digest,
        "byteSize": 2048,
        "mimeType": "image/png",
        "width": 1920,
        "height": 1080,
        "coverageMode": "viewport-segment",
        "coverageStatus": "COVERAGE_UNPROVEN",
    }
    item.update(overrides)
    return item


def _truth_v1(**overrides):
    evidence = {
        "schemaVersion": TRUTH_EVIDENCE_V1,
        "matchId": "recA",
        "actualTotal": 150000,
        "settlementObservedAt": "2026-08-25T12:00:00+08:00",
        "truthSource": "user_review",
        "truthConfidence": "high",
        "evidenceReferences": [{"uri": "evidence/settlement/recA.png", "sha256": _digest("cd")}],
        "verification": {
            "method": "human_screenshot_audit_v1",
            "version": "review.v1",
            "verifier": {"type": "reviewer", "id": "user"},
        },
        "truthPayloadSha256": _digest("ef"),
        "unresolvedTruthConflict": False,
        "inventoryScope": {"complete": None},
        "itemLedger": {"verified": False, "deduplicated": False, "sha256": None},
    }
    evidence.update(overrides)
    return evidence


def _truth_v2(**overrides):
    evidence = _truth_v1(schemaVersion=TRUTH_EVIDENCE_V2, fileOriginals=[_original_v2()])
    evidence.update(overrides)
    return evidence


def _match_record(truth) -> dict:
    record = build_canonical_match_record_v7(
        match_id="recA",
        played_at="2026-08-25T12:00:00+08:00",
        lifecycle_status="DRAFT",
        source="manual",
        environment={
            "venueTier": "zhongji",
            "venue": "shanhu",
            "box": "实木宝箱",
            "boxType": "wood",
            "fieldCondition": "standard",
        },
        public_intel={"q": 11, "totalItems": 66, "totalGrid": 84},
        qualities={"purple": {"count": 3, "avg": 4357}},
        settlement={
            "status": "pending",
            "verified": False,
            "clearingPrice": 100000,
            "actualTotal": 150000,
            "realizedProfit": 50000,
            "acquired": True,
            "winner": "player",
            "settlementItems": [],
            "truthEvidence": truth,
        },
    )
    return record


class TruthEvidenceV2ContractTests(unittest.TestCase):
    def test_schema_documents_are_closed_and_versioned(self):
        original = load_contract_schema("settlement-evidence-original-v2.schema.json")
        v2 = load_contract_schema("settlement-truth-evidence-v2.schema.json")
        v1 = load_contract_schema("settlement-truth-evidence-v1.schema.json")
        match = load_contract_schema("match-record-v7.schema.json")
        self.assertIs(v1["additionalProperties"], False)
        self.assertIs(v2["additionalProperties"], False)
        self.assertIs(original["additionalProperties"], False)
        self.assertEqual(v1["properties"]["schemaVersion"]["const"], TRUTH_EVIDENCE_V1)
        self.assertEqual(v2["properties"]["schemaVersion"]["const"], TRUTH_EVIDENCE_V2)
        self.assertIn("fileOriginals", v2["required"])
        self.assertNotIn("fileOriginals", v1.get("properties", {}))
        self.assertEqual(v1["properties"]["schemaVersion"]["const"], "settlement-truth-evidence.v1")
        one_of = match["properties"]["settlement"]["properties"]["truthEvidence"]["oneOf"]
        self.assertEqual(len(one_of), 2)
        self.assertEqual(match["properties"]["schemaVersion"]["const"], 7)

    def test_existing_v1_fixture_remains_valid_and_is_not_v2(self):
        evidence = _truth_v1()
        ok, reasons, version = validate_truth_evidence_contract(evidence)
        self.assertTrue(ok, reasons)
        self.assertEqual(version, TRUTH_EVIDENCE_V1)
        self.assertEqual(matches_truth_evidence_versions(evidence), [TRUTH_EVIDENCE_V1])
        record = _match_record(evidence)
        valid, rec_reasons = validate_canonical_match_record_v7(record)
        self.assertTrue(valid, rec_reasons)
        self.assertEqual(record["schemaVersion"], 7)

    def test_runtime_v1_builder_still_embeds_in_match_record_v7(self):
        built = build_settlement_truth_evidence_v1(
            match_id="recA",
            actual_total=150000,
            settlement_observed_at="2026-08-25T12:00:00+08:00",
            truth_source="test",
            truth_confidence="medium",
            evidence_uri="evidence/settlement/recA.png",
            evidence_sha256=_digest("11"),
        )
        record = _match_record(built)
        valid, reasons = validate_canonical_match_record_v7(record)
        self.assertTrue(valid, reasons)

    def test_valid_v2_embeds_in_match_record_v7(self):
        evidence = _truth_v2()
        ok, reasons, version = validate_truth_evidence_contract(evidence)
        self.assertTrue(ok, reasons)
        self.assertEqual(version, TRUTH_EVIDENCE_V2)
        self.assertEqual(matches_truth_evidence_versions(evidence), [TRUTH_EVIDENCE_V2])
        record = _match_record(evidence)
        valid, rec_reasons = validate_canonical_match_record_v7(record)
        self.assertTrue(valid, rec_reasons)
        self.assertEqual(len(record["settlement"]["truthEvidence"]["fileOriginals"]), 1)

    def test_complete_original_descriptor_is_valid(self):
        ok, reasons = validate_settlement_evidence_original_v2(_original_v2())
        self.assertTrue(ok, reasons)

    def test_full_descriptor_inside_v1_evidence_references_is_illegal(self):
        stuffed = _truth_v1(evidenceReferences=[_original_v2()])
        ok, reasons, version = validate_truth_evidence_contract(stuffed)
        self.assertEqual(version, TRUTH_EVIDENCE_V1)
        self.assertFalse(ok)
        self.assertTrue(any(item.startswith("UNKNOWN_FIELD_") for item in reasons))

    def test_unknown_fields_are_illegal(self):
        v1 = _truth_v1(extra="nope")
        v2 = _truth_v2(extra="nope")
        original = _original_v2(note="nope")
        self.assertFalse(validate_truth_evidence_contract(v1)[0])
        self.assertFalse(validate_truth_evidence_contract(v2)[0])
        self.assertFalse(validate_settlement_evidence_original_v2(original)[0])

    def test_missing_required_fields_are_illegal(self):
        v2 = _truth_v2()
        del v2["fileOriginals"]
        ok, reasons, version = validate_truth_evidence_contract(v2)
        self.assertEqual(version, TRUTH_EVIDENCE_V2)
        self.assertFalse(ok)
        self.assertIn("FILE_ORIGINALS_MISSING", reasons)
        original = _original_v2()
        del original["relativePath"]
        self.assertFalse(validate_settlement_evidence_original_v2(original)[0])

    def test_complete_coverage_is_illegal(self):
        ok, reasons = validate_settlement_evidence_original_v2(_original_v2(coverageStatus="COMPLETE"))
        self.assertFalse(ok)
        self.assertIn("COVERAGE_STATUS_COMPLETE_FORBIDDEN", reasons)

    def test_absolute_and_traversal_paths_are_illegal(self):
        cases = [
            "C:/evidence/settlement_v2/blobs/ab/" + _digest("ab") + ".png",
            "/evidence/settlement_v2/blobs/ab/" + _digest("ab") + ".png",
            "evidence/../settlement_v2/blobs/ab/" + _digest("ab") + ".png",
            "evidence/settlement_v2/blobs/../" + _digest("ab") + ".png",
        ]
        for path in cases:
            ok, reasons = validate_settlement_evidence_original_v2(_original_v2(relativePath=path))
            self.assertFalse(ok, path)
            self.assertTrue(
                "RELATIVE_PATH_TRAVERSAL" in reasons or "RELATIVE_PATH_INVALID" in reasons,
                reasons,
            )

    def test_v1_and_v2_never_double_match(self):
        self.assertEqual(matches_truth_evidence_versions(_truth_v1()), [TRUTH_EVIDENCE_V1])
        self.assertEqual(matches_truth_evidence_versions(_truth_v2()), [TRUTH_EVIDENCE_V2])
        hybrid = _truth_v1(fileOriginals=[_original_v2()])
        ok, reasons, version = validate_truth_evidence_contract(hybrid)
        self.assertEqual(version, TRUTH_EVIDENCE_V1)
        self.assertFalse(ok)
        self.assertEqual(matches_truth_evidence_versions(hybrid), [])
        self.assertEqual(classify_truth_evidence_version(_truth_v1()), TRUTH_EVIDENCE_V1)
        self.assertEqual(classify_truth_evidence_version(_truth_v2()), TRUTH_EVIDENCE_V2)


if __name__ == "__main__":
    unittest.main()
