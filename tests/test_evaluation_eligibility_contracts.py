import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from evaluation_eligibility import (  # noqa: E402
    EligibilityReason,
    ModelCohort,
    build_input_sha256,
    build_truth_payload_sha256,
    scan_history_file,
    scan_records,
)
from history_admission import (  # noqa: E402
    HistoryAdmissionFlag,
    build_duplicate_index,
    evaluate_history_admission,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def _truth(match_id, actual=500000, observed="2026-08-21T10:05:00+08:00"):
    source = "reviewed-settlement-screenshot"
    return {
        "schemaVersion": "settlement-truth-evidence.v1",
        "matchId": match_id,
        "actualTotal": actual,
        "settlementObservedAt": observed,
        "truthSource": source,
        "truthConfidence": "high",
        "evidenceReferences": [{"uri": "evidence://settlement/one", "sha256": SHA_A}],
        "verification": {
            "method": "human_screenshot_review",
            "version": "1",
            "verifier": {"type": "reviewer", "id": "reviewer-1"},
        },
        "truthPayloadSha256": build_truth_payload_sha256(
            match_id=match_id,
            actual_total=actual,
            settlement_observed_at=observed,
            truth_source=source,
        ),
        "unresolvedTruthConflict": False,
        "inventoryScope": {"complete": None},
        "itemLedger": {"verified": False, "deduplicated": False, "sha256": None},
    }


def _prediction(
    match_id,
    *,
    model="model-1",
    solved="2026-08-21T10:00:00+08:00",
    cutoff="2026-08-21T09:59:00+08:00",
    mode="full_shadow",
    coverage=1.0,
):
    facts = {"q": 9, "goldAvg": 33538, "fieldCondition": "standard"}
    return {
        "schemaVersion": "prediction-snapshot.v1",
        "predictionId": f"prediction-{match_id}",
        "matchId": match_id,
        "solvedAt": solved,
        "informationCutoffAt": cutoff,
        "snapshotRole": "latest_valid_pre_settlement",
        "producer": {
            "runtime": "overlay_runtime",
            "solverName": "auction_engine_v06",
            "solverVersion": "solver-1",
            "modelVersion": model,
            "catalogVersion": "catalog-1",
            "codeRevision": "commit-1",
        },
        "input": {
            "contractVersion": 1,
            "normalizedFacts": facts,
            "hashAlgorithm": "sha256",
            "inputHash": build_input_sha256(facts),
            "datasetRevision": {
                "sourceId": "canonical_match_history",
                "sha256": SHA_B,
                "recordCount": 10,
                "admissionPolicyVersion": 1,
                "cutoffExclusive": cutoff,
                "eligibleRecordIdsSha256": SHA_A,
            },
        },
        "mode": {
            "informationMode": mode,
            "coverageRatio": coverage,
            "supportedStateCount": 2 if coverage else 0,
            "totalStateCount": 2,
        },
        "status": {
            "solverStatus": "valid",
            "provisional": False,
            "diagnosticOnly": False,
        },
        "forecast": {
            "target": "full_inventory_actual_total",
            "scope": "full_inventory",
            "quantiles": {"p20": 400000, "p50": 500000, "p80": 600000},
        },
        "frozen": True,
    }


def _valid_record(
    match_id="match-1",
    *,
    data_origin="live",
    model="model-1",
    played_at="2026-08-21T09:00:00+08:00",
    observed="2026-08-21T10:05:00+08:00",
    solved="2026-08-21T10:00:00+08:00",
    cutoff="2026-08-21T09:59:00+08:00",
    mode="full_shadow",
    coverage=1.0,
):
    actual = 500000
    return {
        "schemaVersion": 7,
        "productVersion": "v0.67-alpha",
        "id": match_id,
        "lifecycleStatus": "FINALIZED",
        "playedAt": played_at,
        "source": "vision-auto-archiver",
        "dataOrigin": data_origin,
        "environment": {
            "venueTier": "zhongji",
            "venue": "venue-a",
            "venueName": "中级场",
            "box": "box-a",
            "boxType": "wood",
            "fieldCondition": "standard",
            "fieldConditionName": "标准",
            "fieldConditionSource": "ocr_banner",
        },
        "loadout": {
            "character": "达芙蒂尔",
            "lobbyToolGroup": None,
            "solverToolGroup": "group1",
        },
        "costs": {
            "entry": 5000,
            "intel": 0,
            "other": 0,
            "sunkCost": 5000,
            "futureIncrementalCost": 0,
            "total": 5000,
        },
        "publicIntel": {
            "q": 9,
            "totalItems": 66,
            "totalGrid": 84,
            "avgValueBasis": "all_inclusive",
        },
        "qualities": {
            "white": {"count": None, "avg": None, "grid": None, "knownItems": []},
            "green": {"count": None, "avg": None, "grid": None, "knownItems": []},
            "blue": {"count": None, "avg": None, "grid": None, "knownItems": []},
            "purple": {"count": 5, "minCount": 2, "avg": 2007, "grid": None, "knownItems": []},
            "gold": {"count": 4, "minCount": 1, "avg": 33538, "total": None, "grid": None, "knownItems": []},
            "red": {"count": None, "minCount": None, "maxCount": None, "grid": None, "knownItems": [], "redInventoryComplete": None, "settlementVerifiedRedItems": ""},
        },
        "bidding": {
            "seats": [],
            "myName": "玩家本人",
            "myFinalBid": 300000,
            "leaderName": "玩家本人",
            "leaderBid": 300000,
            "leaderTies": [],
            "isMyLead": True,
            "historicalBids": {},
            "finalBids": {},
            "rounds": [],
        },
        "settlement": {
            "status": "verified",
            "verified": True,
            "actualTotal": actual,
            "clearingPrice": 300000,
            "realizedProfit": 195000,
            "acquired": True,
            "winner": "玩家本人",
            "settlementItems": [],
            "truthEvidence": _truth(match_id, actual, observed),
        },
        "predictionSnapshot": _prediction(
            match_id,
            model=model,
            solved=solved,
            cutoff=cutoff,
            mode=mode,
            coverage=coverage,
        ),
    }


class EvaluationEligibilityContractTests(unittest.TestCase):
    def test_draft_cancelled_and_diagnostic_fail_history_admission(self):
        records = [
            {"id": "draft", "lifecycleStatus": "DRAFT", "playedAt": "2026-08-21T10:00:00"},
            {"id": "cancel", "lifecycleStatus": "CANCELED", "playedAt": "2026-08-21T10:00:00"},
            {"id": "diag", "lifecycleStatus": "FINALIZED", "playedAt": "2026-08-21T10:00:00", "diagnosticOnly": True},
        ]
        payload = scan_records(records).to_payload()
        self.assertEqual(payload["counts"]["historyAdmittedCount"], 0)
        self.assertEqual(
            payload["historyExclusionReasonCounts"],
            {"CANCELLED": 1, "DIAGNOSTIC": 1, "DRAFT": 1},
        )

    def test_duplicate_id_fails_closed(self):
        records = [_valid_record("same"), _valid_record("same", played_at="2026-08-21T09:01:00+08:00")]
        payload = scan_records(records).to_payload()
        self.assertEqual(payload["historyExclusionReasonCounts"], {"DUPLICATE_RECORD_ID": 2})
        self.assertEqual(payload["counts"]["formallyEligibleCount"], 0)

    def test_probable_content_duplicate_is_history_flag_and_evaluation_block(self):
        records = [_valid_record("one"), _valid_record("two")]
        duplicate_index = build_duplicate_index(records)
        decisions = [evaluate_history_admission(r, duplicate_index) for r in records]
        self.assertTrue(all(d.admitted for d in decisions))
        self.assertTrue(
            all(HistoryAdmissionFlag.POTENTIAL_CONTENT_DUPLICATE in d.flags for d in decisions)
        )
        payload = scan_records(records).to_payload()
        self.assertEqual(payload["potentialContentDuplicateGroupCount"], 1)
        self.assertEqual(payload["primaryRejectionReasonCounts"], {"POTENTIAL_CONTENT_DUPLICATE": 2})

    def test_naive_timestamp_is_fixed_to_asia_shanghai(self):
        record = _valid_record()
        record["playedAt"] = "2026-08-21T00:01:00"
        decision = evaluate_history_admission(record, build_duplicate_index([record]))
        self.assertEqual(decision.normalized_time.local_time.utcoffset().total_seconds(), 8 * 3600)
        self.assertIn(
            HistoryAdmissionFlag.LEGACY_TIMESTAMP_ASSUMED_ASIA_SHANGHAI,
            decision.flags,
        )

    def test_legacy_verified_is_not_automatically_high_confidence_truth(self):
        record = {
            "id": "legacy",
            "playedAt": "2026-08-21T10:00:00",
            "actualTotal": 100,
            "settlement": {"status": "verified", "verified": True, "actualTotal": 100},
        }
        payload = scan_records([record]).to_payload()
        self.assertEqual(payload["counts"]["historyAdmittedCount"], 1)
        self.assertEqual(payload["counts"]["evaluationCandidateCount"], 0)
        self.assertEqual(payload["counts"]["formallyEligibleCount"], 0)

    def test_weak_legacy_hash_fails_closed(self):
        record = _valid_record()
        record.pop("predictionSnapshot")
        record["prediction"] = {
            "inputHash": "sha1-deadbeef",
            "solvedAt": "2026-08-21T10:00:00+08:00",
            "solverVersion": "legacy-solver",
            "modelVersion": "legacy-model",
        }
        payload = scan_records([record]).to_payload()
        self.assertEqual(payload["allReasonCounts"][EligibilityReason.LEGACY_WEAK_INPUT_HASH], 1)
        self.assertEqual(payload["counts"]["formallyEligibleCount"], 0)

    def test_missing_exact_input_and_dataset_revision_fail(self):
        record = _valid_record()
        record["predictionSnapshot"]["input"].pop("normalizedFacts")
        record["predictionSnapshot"]["input"].pop("datasetRevision")
        payload = scan_records([record]).to_payload()
        reasons = payload["allReasonCounts"]
        self.assertIn(EligibilityReason.EXACT_NORMALIZED_INPUT_MISSING, reasons)
        self.assertIn(EligibilityReason.DATASET_REVISION_MISSING, reasons)

    def test_prediction_after_settlement_fails(self):
        record = _valid_record(solved="2026-08-21T10:06:00+08:00")
        payload = scan_records([record]).to_payload()
        self.assertIn(EligibilityReason.PREDICTION_AFTER_SETTLEMENT, payload["allReasonCounts"])

    def test_partial_shadow_cannot_target_full_actual(self):
        record = _valid_record(mode="partial_shadow", coverage=0.5)
        payload = scan_records([record]).to_payload()
        self.assertIn(
            EligibilityReason.PARTIAL_SHADOW_FULL_TRUTH_TARGET_MISMATCH,
            payload["allReasonCounts"],
        )

    def test_structural_only_cannot_masquerade_as_full_shadow(self):
        record = _valid_record(mode="structural_only", coverage=0.0)
        payload = scan_records([record]).to_payload()
        self.assertIn(
            EligibilityReason.STRUCTURAL_ONLY_FULL_SHADOW_TARGET_MISMATCH,
            payload["allReasonCounts"],
        )

    def test_incomplete_fallback_and_diagnostic_predictions_fail_closed(self):
        for status, expected in (
            ("incomplete", EligibilityReason.SOLVER_STATUS_INCOMPLETE),
            ("fallback", EligibilityReason.SOLVER_STATUS_FALLBACK),
            ("diagnostic", EligibilityReason.SOLVER_STATUS_DIAGNOSTIC),
        ):
            with self.subTest(status=status):
                record = _valid_record(f"match-{status}")
                record["predictionSnapshot"]["status"]["solverStatus"] = status
                if status == "diagnostic":
                    record["predictionSnapshot"]["status"]["diagnosticOnly"] = True
                payload = scan_records([record]).to_payload()
                self.assertIn(expected, payload["allReasonCounts"])
                self.assertEqual(payload["counts"]["formallyEligibleCount"], 0)

    def test_model_versions_are_separate_cohorts_and_required_cohort_fails_closed(self):
        records = [
            _valid_record("model-a-record", model="model-a"),
            _valid_record("model-b-record", model="model-b", played_at="2026-08-21T09:01:00+08:00"),
        ]
        payload = scan_records(records).to_payload()
        self.assertEqual(payload["counts"]["formallyEligibleCount"], 2)
        self.assertEqual(len(payload["eligibleCohortCounts"]), 2)
        required = ModelCohort(
            "solver-1", "model-a", "catalog-1", "commit-1", "full_shadow", "full_inventory_actual_total"
        )
        restricted = scan_records(records, required_cohort=required).to_payload()
        self.assertEqual(restricted["counts"]["formallyEligibleCount"], 1)
        self.assertEqual(restricted["allReasonCounts"][EligibilityReason.MODEL_COHORT_MISMATCH], 1)

    def test_red_tail_requires_complete_verified_deduplicated_ledger(self):
        payload = scan_records([_valid_record()], target_kind="red_tail").to_payload()
        reasons = payload["allReasonCounts"]
        self.assertIn(EligibilityReason.RED_TAIL_INVENTORY_SCOPE_INCOMPLETE, reasons)
        self.assertIn(EligibilityReason.RED_TAIL_ITEM_LEDGER_UNVERIFIED, reasons)
        self.assertIn(EligibilityReason.RED_TAIL_ITEM_LEDGER_NOT_DEDUPLICATED, reasons)
        self.assertIn(EligibilityReason.RED_TAIL_ITEM_LEDGER_HASH_MISSING, reasons)

    def test_primary_reason_counts_are_conservative(self):
        records = [_valid_record("ok"), {"id": "draft", "lifecycleStatus": "DRAFT", "playedAt": "2026-08-21T10:00:00"}]
        payload = scan_records(records).to_payload()
        self.assertTrue(payload["invariants"]["primaryReasonsPlusEligibleEqualsRecordCount"])
        self.assertEqual(payload["invariants"]["primaryReasonsPlusEligible"], 2)
        self.assertFalse(payload["invariants"]["metricsComputed"])

    def test_scanner_does_not_modify_history_file(self):
        with tempfile.TemporaryDirectory(prefix="nte-eval-eligibility-") as temp_dir:
            path = Path(temp_dir) / "history.json"
            path.write_text(json.dumps({"schemaVersion": 7, "records": [_valid_record()]}), encoding="utf-8")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            scan_history_file(path)
            after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_scanner_imports_no_production_solver_or_runtime(self):
        forbidden = {"auction_engine_v06", "solver_core_v06", "live_shadow", "current_match", "vision_pipeline", "ocr"}
        for source_path in (
            APP_DIR / "history_admission.py",
            APP_DIR / "evaluation_eligibility.py",
        ):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
            self.assertTrue(imports.isdisjoint(forbidden), source_path.name)

    def test_main_view_state_uses_shared_history_authority(self):
        source = (APP_DIR / "main_view_state.py").read_text(encoding="utf-8")
        self.assertIn("from history_admission import", source)
        self.assertNotIn("def _admission_exclusion_reason", source)

    def test_contract_schema_documents_are_valid_json(self):
        for name in (
            "match-record-v7.schema.json",
            "prediction-snapshot-v1.schema.json",
            "settlement-truth-evidence-v1.schema.json",
            "settlement-truth-evidence-v2.schema.json",
            "settlement-evidence-original-v2.schema.json",
            "prediction-evaluation-summary-v1.schema.json",
        ):
            payload = json.loads(
                (PROJECT_ROOT / "docs" / "contracts" / name).read_text(encoding="utf-8")
            )
            self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_provenance_data_origin_gate(self):
        from evaluation_eligibility import evaluate_record_eligibility
        # 1. 100% field-complete record with dataOrigin="live" passes formal evaluation
        live_rec = _valid_record("match-live", data_origin="live")
        res_live = evaluate_record_eligibility(live_rec, build_duplicate_index([live_rec]))
        self.assertTrue(res_live.history.admitted)
        self.assertTrue(res_live.formally_eligible)
        self.assertEqual(res_live.reasons, ())

        # 2. Same record with dataOrigin="replay" is admitted to history, but formally rejected strictly for origin
        replay_rec = _valid_record("match-replay", data_origin="replay")
        res_replay = evaluate_record_eligibility(replay_rec, build_duplicate_index([replay_rec]))
        self.assertTrue(res_replay.history.admitted)
        self.assertFalse(res_replay.formally_eligible)
        self.assertEqual(res_replay.reasons, (EligibilityReason.DATA_ORIGIN_NOT_LIVE,))
        self.assertEqual(res_replay.primary_reason, EligibilityReason.DATA_ORIGIN_NOT_LIVE)

        # 3. Same record with dataOrigin="test" is admitted to history, but formally rejected strictly for origin
        test_rec = _valid_record("match-test", data_origin="test")
        res_test = evaluate_record_eligibility(test_rec, build_duplicate_index([test_rec]))
        self.assertTrue(res_test.history.admitted)
        self.assertFalse(res_test.formally_eligible)
        self.assertEqual(res_test.reasons, (EligibilityReason.DATA_ORIGIN_NOT_LIVE,))
        self.assertEqual(res_test.primary_reason, EligibilityReason.DATA_ORIGIN_NOT_LIVE)

        # 4. Legacy record with missing dataOrigin is admitted to history, but formally rejected with DATA_ORIGIN_MISSING
        legacy_rec = _valid_record("match-legacy", data_origin=None)
        res_legacy = evaluate_record_eligibility(legacy_rec, build_duplicate_index([legacy_rec]))
        self.assertTrue(res_legacy.history.admitted)
        self.assertFalse(res_legacy.formally_eligible)
        self.assertEqual(res_legacy.reasons, (EligibilityReason.DATA_ORIGIN_MISSING,))
        self.assertEqual(res_legacy.primary_reason, EligibilityReason.DATA_ORIGIN_MISSING)


if __name__ == "__main__":
    unittest.main()
