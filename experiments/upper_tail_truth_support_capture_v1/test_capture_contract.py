# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location("upper_tail_capture_contract", HERE / "capture_contract.py")
contract = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(contract)


class UpperTailTruthSupportCaptureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prediction_input = json.loads((HERE / "fixtures" / "prediction_capture_input.json").read_text(encoding="utf-8"))
        cls.truth_input = json.loads((HERE / "fixtures" / "truth_capture_input.json").read_text(encoding="utf-8"))
        cls.database_path = ROOT / "异环拍卖数据.json"
        cls.solver_path = ROOT / "core" / "auction_engine_v06.js"
        cls.database_hash = contract.sha256_file(cls.database_path)
        cls.solver_hash = contract.sha256_file(cls.solver_path)

    def build_prediction(self, source=None):
        return contract.build_prediction_capture(source or deepcopy(self.prediction_input))

    def build_truth(self, source=None, prediction=None):
        return contract.build_truth_capture(
            source or deepcopy(self.truth_input),
            prediction or self.build_prediction(),
        )

    def test_prediction_capture_is_valid_and_deterministic(self):
        first = self.build_prediction()
        second = self.build_prediction()
        self.assertEqual(first, second)
        self.assertEqual(contract.validate_prediction_capture(first), [])
        self.assertEqual(first["candidateSpace"]["fullStateCount"], 2)
        self.assertEqual(first["candidateSpace"]["valuationStateCount"], 2)
        self.assertAlmostEqual(sum(row["normalizedWeight"] for row in first["candidateSpace"]["valuationStates"]), 1.0)

    def test_every_full_state_must_be_mapped_exactly_once(self):
        source = deepcopy(self.prediction_input)
        source["candidateSpace"]["valuationStates"][1]["sourceFullStateIds"] = ["full-g4-p7-r4", "full-g5-p7-r3"]
        source["candidateSpace"]["valuationStates"][1]["aggregationMethod"] = "representative_state"
        with self.assertRaisesRegex(contract.ContractError, "FULL_STATE_MAPPING_INCOMPLETE_OR_DUPLICATE"):
            self.build_prediction(source)

    def test_valuation_geometry_must_match_single_source_state(self):
        source = deepcopy(self.prediction_input)
        source["candidateSpace"]["valuationStates"][0]["g"] = 9
        with self.assertRaisesRegex(contract.ContractError, "VALUATION_SOURCE_GEOMETRY_MISMATCH"):
            self.build_prediction(source)

    def test_full_state_count_mismatch_fails_closed(self):
        source = deepcopy(self.prediction_input)
        source["candidateSpace"]["fullStateCount"] = 99
        with self.assertRaisesRegex(contract.ContractError, "FULL_STATE_COUNT_MISMATCH"):
            self.build_prediction(source)

    def test_normalized_weights_must_sum_to_one(self):
        source = deepcopy(self.prediction_input)
        source["candidateSpace"]["valuationStates"][0]["normalizedWeight"] = 0.1
        with self.assertRaisesRegex(contract.ContractError, "NORMALIZED_WEIGHT_SUM_INVALID"):
            self.build_prediction(source)

    def test_supported_weight_must_match_snapshot_coverage(self):
        source = deepcopy(self.prediction_input)
        source["predictionSnapshot"]["mode"]["coverageRatio"] = 0.5
        with self.assertRaisesRegex(contract.ContractError, "SUPPORTED_WEIGHT_COVERAGE_MISMATCH"):
            self.build_prediction(source)

    def test_per_state_valuation_breakdown_is_mandatory_and_reconciled(self):
        source = deepcopy(self.prediction_input)
        source["candidateSpace"]["valuationStates"][0].pop("valuationBreakdown")
        with self.assertRaisesRegex(contract.ContractError, "VALUATION_BREAKDOWN_MISSING"):
            self.build_prediction(source)
        source = deepcopy(self.prediction_input)
        source["candidateSpace"]["valuationStates"][0]["valuationBreakdown"]["total"]["mid"] += 1
        with self.assertRaisesRegex(contract.ContractError, "VALUATION_TOTAL_MID_MISMATCH"):
            self.build_prediction(source)

    def test_supported_tail_requires_provenance_and_evidence(self):
        source = deepcopy(self.prediction_input)
        source["candidateSpace"]["valuationStates"][0]["tailContribution"]["provenance"]["evidenceReferences"] = []
        with self.assertRaisesRegex(contract.ContractError, "TAIL_EVIDENCE_REFERENCE_MISSING"):
            self.build_prediction(source)

    def test_aggregate_quantiles_must_equal_frozen_prediction_snapshot(self):
        source = deepcopy(self.prediction_input)
        source["aggregateDistribution"]["quantiles"]["p80"] += 1
        with self.assertRaisesRegex(contract.ContractError, "AGGREGATE_FORECAST_QUANTILES_MISMATCH"):
            self.build_prediction(source)

    def test_prediction_hash_detects_tampering(self):
        artifact = self.build_prediction()
        artifact["candidateSpace"]["valuationStates"][0]["normalizedWeight"] += 0.01
        reasons = contract.validate_prediction_capture(artifact)
        self.assertTrue(reasons)
        self.assertNotEqual(reasons, [""])

    def test_truth_capture_is_valid_and_links_exact_prediction(self):
        prediction = self.build_prediction()
        truth = self.build_truth(prediction=prediction)
        self.assertEqual(contract.validate_truth_capture(truth, prediction), [])
        self.assertEqual(truth["predictionCaptureRef"]["predictionHash"], prediction["predictionHash"])
        self.assertEqual(truth["verifiedState"]["verificationStatus"], "VERIFIED")
        self.assertEqual(truth["actualValueDecomposition"]["reconciliationDelta"], 0)

    def test_truth_state_and_evidence_are_required(self):
        source = deepcopy(self.truth_input)
        source["verifiedState"]["verificationStatus"] = "PSEUDO"
        with self.assertRaisesRegex(contract.ContractError, "STATE_NOT_VERIFIED"):
            self.build_truth(source)
        source = deepcopy(self.truth_input)
        source["truthEvidenceReferences"] = []
        with self.assertRaisesRegex(contract.ContractError, "TRUTH_EVIDENCE_REFERENCES_MISSING"):
            self.build_truth(source)

    def test_capture_timestamps_must_be_timezone_aware(self):
        source = deepcopy(self.prediction_input)
        source["capturedAt"] = "2026-08-22T10:00:00"
        with self.assertRaisesRegex(contract.ContractError, "CAPTURED_AT_INVALID"):
            self.build_prediction(source)
        source = deepcopy(self.truth_input)
        source["reviewedAt"] = "2026-08-22T10:15:00"
        with self.assertRaisesRegex(contract.ContractError, "TRUTH_REVIEWED_AT_INVALID"):
            self.build_truth(source)

    def test_verified_state_must_reconcile_with_prediction_q(self):
        source = deepcopy(self.truth_input)
        source["verifiedState"]["g"] = 5
        with self.assertRaisesRegex(contract.ContractError, "VERIFIED_STATE_Q_MISMATCH"):
            self.build_truth(source)

    def test_actual_value_decomposition_must_reconcile(self):
        source = deepcopy(self.truth_input)
        source["actualValueDecomposition"]["components"][0]["value"] += 1
        with self.assertRaisesRegex(contract.ContractError, "ACTUAL_DECOMPOSITION_SUM_MISMATCH"):
            self.build_truth(source)

    def test_truth_cannot_be_relinked_to_another_prediction(self):
        prediction = self.build_prediction()
        truth = self.build_truth(prediction=prediction)
        other = deepcopy(prediction)
        other["matchId"] = "other-match"
        self.assertTrue(contract.validate_truth_capture(truth, other))

    def test_atomic_writer_roundtrip_and_no_history_mutation(self):
        artifact = self.build_prediction()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "prediction.json"
            contract.atomic_write_json(path, artifact)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded, artifact)
            self.assertEqual(contract.validate_prediction_capture(loaded), [])
        self.assertEqual(contract.sha256_file(self.database_path), self.database_hash)
        self.assertEqual(contract.sha256_file(self.solver_path), self.solver_hash)

    def test_artifacts_contain_no_accuracy_result(self):
        prediction = self.build_prediction()
        truth = self.build_truth(prediction=prediction)
        serialized = json.dumps({"prediction": prediction, "truth": truth}, ensure_ascii=False).lower()
        for forbidden in ('"mae"', '"accuracy"', '"bias"', '"modelverdict"'):
            self.assertNotIn(forbidden, serialized)

    def test_json_schemas_are_parseable(self):
        for filename in (
            "upper_tail_prediction_support_capture_v1.schema.json",
            "upper_tail_settlement_truth_v1.schema.json",
        ):
            schema = json.loads((HERE / filename).read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")


if __name__ == "__main__":
    unittest.main()
