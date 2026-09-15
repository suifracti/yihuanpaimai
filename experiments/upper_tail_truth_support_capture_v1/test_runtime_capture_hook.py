# -*- coding: utf-8 -*-
"""Focused integrity tests for the experiment-only runtime capture hook."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

from experiments.upper_tail_truth_support_capture_v1.capture_contract import (
    ContractError,
    build_truth_capture,
    canonical_json_bytes,
    sha256_file,
    sha256_json,
    validate_truth_capture,
)
from experiments.upper_tail_truth_support_capture_v1.runtime_capture_hook import (
    CAPTURE_PHASE,
    build_capture_input_from_envelope,
    capture_prediction_support_envelope,
    load_and_validate_capture,
    resolve_capture_store,
    source_package_parity_signature,
)


HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _runtime_envelope() -> dict:
    fixture = _load("prediction_capture_input.json")
    snapshot = deepcopy(fixture["predictionSnapshot"])
    full_states = [
        {key: row[key] for key in ("g", "p", "r")}
        for row in fixture["candidateSpace"]["fullCandidateStates"]
    ]
    valuation_states = []
    for row in fixture["candidateSpace"]["valuationStates"]:
        component = {
            part["category"]: {
                "lower": part["lower"],
                "mid": part["mid"],
                "upper": part["upper"],
                "source": part["provenance"]["method"],
            }
            for part in row["valuationBreakdown"]["components"]
        }
        provenance = row["tailContribution"]["provenance"]
        valuation_states.append(
            {
                "g": row["g"],
                "p": row["p"],
                "r": row["r"],
                "relativeWeight": row["normalizedWeight"],
                "component": component,
                "shadow": deepcopy(row["tailContribution"]["distribution"]),
                "redMode": provenance["mode"],
                "redByR": [
                    {
                        "r": row["r"],
                        "mode": provenance["mode"],
                        "directGames": provenance["directGameCount"],
                        "bootstrapN": provenance["bootstrapSampleCount"],
                    }
                ],
            }
        )
    return {
        "schemaVersion": "production-support-envelope.v1",
        "capturePhase": CAPTURE_PHASE,
        "capturedAt": fixture["capturedAt"],
        "predictionSnapshot": snapshot,
        "predictionSnapshotSha256": sha256_json(snapshot),
        "runtimeMatchId": snapshot["matchId"],
        "collectionClass": "RUNTIME_SMOKE_CAPTURE",
        "fullCandidateStates": full_states,
        "valuationStates": valuation_states,
        "aggregateDistribution": deepcopy(fixture["aggregateDistribution"]["quantiles"]),
        "tailEvidence": {"fixture": "deterministic-v1"},
    }


class RuntimeCaptureHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _assert_rejected_without_artifact(self, envelope: dict, reason: str) -> None:
        result = capture_prediction_support_envelope(envelope, self.store)
        self.assertEqual(result.status, "REJECTED")
        self.assertIn(reason, result.reason or "")
        self.assertEqual(list(self.store.glob("*.json")), [])

    def test_deterministic_capture_preserves_prediction_and_shadow_hashes(self) -> None:
        envelope = _runtime_envelope()
        prediction_before = sha256_json(envelope["predictionSnapshot"])
        shadow_before = sha256_json(
            {
                "valuationStates": envelope["valuationStates"],
                "aggregateDistribution": envelope["aggregateDistribution"],
            }
        )
        first = capture_prediction_support_envelope(envelope, self.store)
        self.assertEqual(first.status, "WRITTEN")
        artifact = load_and_validate_capture(first.path)
        self.assertEqual(artifact["predictionSnapshotSha256"], prediction_before)
        self.assertEqual(
            artifact["aggregateDistribution"]["quantiles"],
            envelope["predictionSnapshot"]["forecast"]["quantiles"],
        )
        self.assertEqual(sha256_json(envelope["predictionSnapshot"]), prediction_before)
        self.assertEqual(
            sha256_json(
                {
                    "valuationStates": envelope["valuationStates"],
                    "aggregateDistribution": envelope["aggregateDistribution"],
                }
            ),
            shadow_before,
        )

        second_store = self.store / "second"
        second = capture_prediction_support_envelope(deepcopy(envelope), second_store)
        self.assertEqual(second.status, "WRITTEN")
        self.assertEqual(Path(first.path).read_bytes(), Path(second.path).read_bytes())

    def test_duplicate_capture_is_idempotent(self) -> None:
        envelope = _runtime_envelope()
        first = capture_prediction_support_envelope(envelope, self.store)
        before = Path(first.path).stat().st_mtime_ns
        envelope["capturedAt"] = "2026-08-22T10:01:00+08:00"
        second = capture_prediction_support_envelope(envelope, self.store)
        self.assertEqual(second.status, "DUPLICATE")
        self.assertEqual(Path(first.path).stat().st_mtime_ns, before)

    def test_corrupted_existing_artifact_is_rejected_not_overwritten(self) -> None:
        envelope = _runtime_envelope()
        first = capture_prediction_support_envelope(envelope, self.store)
        target = Path(first.path)
        target.write_text('{"corrupt":true}\n', encoding="utf-8")
        corrupted_hash = sha256_file(target)
        second = capture_prediction_support_envelope(envelope, self.store)
        self.assertEqual(second.status, "REJECTED")
        self.assertIn("CORRUPTED_CAPTURE_ARTIFACT", second.reason or "")
        self.assertEqual(sha256_file(target), corrupted_hash)

    def test_prediction_truth_link_validation(self) -> None:
        result = capture_prediction_support_envelope(_runtime_envelope(), self.store)
        prediction = load_and_validate_capture(result.path)
        truth = build_truth_capture(_load("truth_capture_input.json"), prediction)
        self.assertEqual(validate_truth_capture(truth, prediction), [])
        corrupted = deepcopy(truth)
        corrupted["predictionCaptureRef"]["predictionHash"] = "0" * 64
        self.assertIn("PREDICTION_HASH_LINK_MISMATCH", validate_truth_capture(corrupted, prediction)[0])

    def test_missing_state_mapping_fails_closed(self) -> None:
        envelope = _runtime_envelope()
        envelope["fullCandidateStates"].pop()
        self._assert_rejected_without_artifact(envelope, "STATE_MAPPING_MISSING")

    def test_weight_sum_fails_closed(self) -> None:
        envelope = _runtime_envelope()
        envelope["valuationStates"][0]["relativeWeight"] = 0.1
        self._assert_rejected_without_artifact(envelope, "NORMALIZED_WEIGHT_SUM_INVALID")

    def test_quantile_mismatch_fails_closed(self) -> None:
        envelope = _runtime_envelope()
        envelope["aggregateDistribution"]["p80"] += 1
        self._assert_rejected_without_artifact(envelope, "AGGREGATE_FORECAST_QUANTILES_MISMATCH")

    def test_snapshot_hash_mismatch_fails_closed(self) -> None:
        envelope = _runtime_envelope()
        envelope["predictionSnapshotSha256"] = "0" * 64
        self._assert_rejected_without_artifact(envelope, "ENVELOPE_PREDICTION_SNAPSHOT_HASH_MISMATCH")

    def test_post_settlement_field_fails_closed(self) -> None:
        envelope = _runtime_envelope()
        envelope["settlement"] = {"actualTotal": 999999}
        self._assert_rejected_without_artifact(envelope, "POST_SETTLEMENT_FIELD_FORBIDDEN")

    def test_missing_runtime_match_id_fails_closed(self) -> None:
        envelope = _runtime_envelope()
        envelope["runtimeMatchId"] = None
        self._assert_rejected_without_artifact(envelope, "RUNTIME_MATCH_ID_MISSING")

    def test_naive_capture_timestamp_fails_closed(self) -> None:
        envelope = _runtime_envelope()
        envelope["capturedAt"] = "2026-08-22T10:00:00"
        self._assert_rejected_without_artifact(envelope, "CAPTURE_TIMESTAMP_NOT_TIMEZONE_AWARE")

    def test_capture_must_follow_solve(self) -> None:
        envelope = _runtime_envelope()
        envelope["capturedAt"] = "2026-08-22T09:00:00+08:00"
        self._assert_rejected_without_artifact(envelope, "CAPTURE_PRECEDES_PREDICTION_SOLVE")

    def test_source_and_packaged_store_resolution_are_equivalent(self) -> None:
        expected = self.store.resolve()
        with mock.patch.dict(os.environ, {"YIHUAN_UPPER_TAIL_CAPTURE_DIR": str(expected)}):
            source_value = resolve_capture_store()
        with mock.patch("sys.frozen", True, create=True), mock.patch.dict(
            os.environ, {"YIHUAN_UPPER_TAIL_CAPTURE_DIR": str(expected)}
        ):
            packaged_value = resolve_capture_store()
        self.assertEqual(source_value, packaged_value)
        self.assertEqual(source_package_parity_signature(), source_package_parity_signature())

    def test_packaging_declares_hook_and_source_root(self) -> None:
        spec = (HERE.parents[1] / "app" / "异环拍卖助手.spec").read_text(encoding="utf-8")
        self.assertIn("experiments.upper_tail_truth_support_capture_v1.runtime_capture_hook", spec)
        self.assertIn("pathex=[PROJECT_ROOT,", spec)
        for runtime_asset in (
            "live_shadow_runtime.js",
            "shadow_profile_v06.js",
            "solver_core_v06.js",
        ):
            self.assertIn(runtime_asset, spec)
        main_source = (HERE.parents[1] / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn("--smoke-upper-tail-capture-hook", main_source)

    def test_converter_is_deterministic_and_does_not_mutate_envelope(self) -> None:
        envelope = _runtime_envelope()
        before = canonical_json_bytes(envelope)
        first = build_capture_input_from_envelope(envelope)
        second = build_capture_input_from_envelope(envelope)
        self.assertEqual(first, second)
        self.assertEqual(canonical_json_bytes(envelope), before)


if __name__ == "__main__":
    unittest.main()
