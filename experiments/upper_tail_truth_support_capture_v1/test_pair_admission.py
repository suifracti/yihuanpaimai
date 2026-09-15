# -*- coding: utf-8 -*-
"""First-valid-pair admission and fake-pair isolation tests."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from .capture_contract import build_prediction_capture, build_truth_capture
from .pair_admission import VALID_PAIR_STATUS, validate_upper_tail_pair


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _synthetic_natural_shaped_pair() -> tuple[dict, dict]:
    prediction_input = _load("prediction_capture_input.json")
    prediction_input["collectionClass"] = "NATURAL_RUNTIME_CAPTURE"
    prediction = build_prediction_capture(prediction_input)
    truth_input = _load("truth_capture_input.json")
    truth_input["reviewClass"] = "INDEPENDENT_REVIEWED_SETTLEMENT"
    truth = build_truth_capture(truth_input, prediction)
    return prediction, truth


class PairAdmissionTests(unittest.TestCase):
    def test_fixture_pair_is_contract_valid_but_never_counted_as_real(self) -> None:
        prediction = build_prediction_capture(_load("prediction_capture_input.json"))
        truth = build_truth_capture(_load("truth_capture_input.json"), prediction)
        result = validate_upper_tail_pair(prediction, truth)
        self.assertFalse(result.admitted)
        self.assertIn("PREDICTION_NOT_NATURAL_RUNTIME_CAPTURE", result.reason_codes)
        self.assertIn("TRUTH_NOT_INDEPENDENT_REVIEW", result.reason_codes)

    def test_synthetic_natural_shaped_pair_exercises_admission_only(self) -> None:
        prediction, truth = _synthetic_natural_shaped_pair()
        result = validate_upper_tail_pair(prediction, truth)
        self.assertTrue(result.admitted)
        self.assertEqual(result.status, VALID_PAIR_STATUS)
        self.assertEqual(result.realized_state_relation, "MATCHED_VALUATION_STATE")
        self.assertTrue(result.value_model_error_eligible)

    def test_partial_truth_cannot_become_complete_pair(self) -> None:
        prediction, _ = _synthetic_natural_shaped_pair()
        truth_input = _load("truth_capture_input.json")
        truth_input["reviewClass"] = "INDEPENDENT_REVIEWED_SETTLEMENT"
        decomposition = truth_input["actualValueDecomposition"]
        decomposition["decompositionStatus"] = "PARTIAL"
        decomposition["components"][0]["value"] -= 100
        decomposition["unattributedValue"] = 100
        truth = build_truth_capture(truth_input, prediction)
        result = validate_upper_tail_pair(prediction, truth)
        self.assertFalse(result.admitted)
        self.assertIn("TRUTH_DECOMPOSITION_NOT_COMPLETE", result.reason_codes)
        self.assertFalse(result.value_model_error_eligible)

    def test_link_mismatch_rejects(self) -> None:
        prediction, truth = _synthetic_natural_shaped_pair()
        truth["predictionCaptureRef"]["predictionHash"] = "0" * 64
        result = validate_upper_tail_pair(prediction, truth)
        self.assertFalse(result.admitted)
        self.assertTrue(any("PREDICTION_HASH_LINK_MISMATCH" in reason for reason in result.reason_codes))

    def test_truth_review_cannot_precede_prediction_capture(self) -> None:
        prediction, truth = _synthetic_natural_shaped_pair()
        truth["reviewedAt"] = "2026-08-22T09:00:00+08:00"
        result = validate_upper_tail_pair(prediction, truth)
        self.assertFalse(result.admitted)
        self.assertIn("TRUTH_REVIEW_PRECEDES_PREDICTION_CAPTURE", result.reason_codes)

    def test_missing_realized_state_is_support_diagnostic_not_value_model_evidence(self) -> None:
        prediction, _ = _synthetic_natural_shaped_pair()
        truth_input = _load("truth_capture_input.json")
        truth_input["reviewClass"] = "INDEPENDENT_REVIEWED_SETTLEMENT"
        truth_input["verifiedState"] = {
            **truth_input["verifiedState"],
            "g": 6,
            "p": 5,
            "r": 4,
        }
        truth = build_truth_capture(truth_input, prediction)
        result = validate_upper_tail_pair(prediction, truth)
        self.assertTrue(result.admitted)
        self.assertEqual(result.realized_state_relation, "STATE_SPACE_MISSING")
        self.assertFalse(result.value_model_error_eligible)


if __name__ == "__main__":
    unittest.main()
