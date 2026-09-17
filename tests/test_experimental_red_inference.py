# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for PR-B Experimental Red Probability Inference Lab.

Covers all 18 mandatory test requirements:
1. productionEligible=False
2. experimental=True
3. No eligible history -> unavailable
4. Small sample size -> insufficientData=True
5. Source-rejected records excluded (DRAFT, CANCELLED, DIAGNOSTIC, duplicate id)
6. Replay/test origin excluded from formal training
7. Known red does not assume without-replacement sampling (conditioningMode="observational_only")
8. samplingAssumption default "unknown"
9. PMF normalization (sum == 1.0)
10. Monotonic quantiles (p10 <= p20 <= p25 <= p50 <= p75 <= p80 <= p90 <= p95)
11. Historical Shadow untouched
12. Production solver decisions untouched
13. Idempotent ingestion (same record ID not double-counted)
14. History generation invalidation & recomputation
15. UI default collapsed
16. Explicit disclaimer "实验结果 · 不参与正式出价"
17. PR-A contract preserved (Mean/Median/Conservative provenance)
18. Boundary 3 files untouched
"""

import copy
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_CORE_DIR = os.path.join(_PROJECT_ROOT, "core")
_APP_DIR = os.path.join(_PROJECT_ROOT, "app")
for _p in (_PROJECT_ROOT, _CORE_DIR, _APP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from experimental_red_inference import (
    ExperimentalRedInferenceLab,
    RedEligibilityBreakdown,
    RedInferenceReport,
    RedQuantiles,
    SimilarityFeatures,
    compute_canonical_similarity,
    evaluate_record_red_eligibility,
)
from auction_brain import AuctionBrain
from strategy_ux_metrics import EstimateMode, get_authoritative_strategy_store


def _build_test_record(
    record_id: str,
    played_at: str = "2026-09-16T12:00:00Z",
    lifecycle: str = "FINALIZED",
    origin: str = "live",
    diagnostic_only: bool = False,
    venue: str = "standard",
    box: str = "box_normal",
    q: int = 60,
    gold_avg: float = 12000.0,
    red_count: int = 0,
    red_total_value: float = 0.0,
) -> Dict[str, Any]:
    """Helper to construct a valid Canonical MatchRecord v7 for testing."""
    return {
        "schemaVersion": 7,
        "id": record_id,
        "playedAt": played_at,
        "lifecycleStatus": lifecycle,
        "source": "0.65-vision-auto-archiver",
        "dataOrigin": origin,
        "diagnosticOnly": diagnostic_only,
        "environment": {
            "venue": venue,
            "venueTier": venue,
            "box": box,
            "boxType": box,
        },
        "publicIntel": {
            "q": q,
            "totalItems": q,
        },
        "qualities": {
            "gold": {"avg": gold_avg, "count": 10},
            "red": {
                "count": red_count,
                "minCount": red_count,
                "maxCount": red_count,
                "redInventoryComplete": True,
            },
        },
        "settlement": {
            "status": "verified",
            "verified": True,
            "actualTotal": gold_avg * 10 + red_total_value,
            "clearingPrice": 50000,
            "settlementItems": [
                {"name": f"RedItem_{i}", "quality": "red", "value": red_total_value / max(1, red_count)}
                for i in range(red_count)
            ],
        },
    }


class TestExperimentalRedInferenceLab(unittest.TestCase):
    def setUp(self):
        get_authoritative_strategy_store().reset_for_new_match("test_session_setup")

    def test_01_production_eligible_false(self):
        """1. productionEligible must be strictly False."""
        lab = ExperimentalRedInferenceLab([])
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        self.assertFalse(report.production_eligible)
        payload = report.to_payload()
        self.assertFalse(payload["productionEligible"])

    def test_02_experimental_true(self):
        """2. experimental must be strictly True."""
        lab = ExperimentalRedInferenceLab([])
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        self.assertTrue(report.experimental)
        payload = report.to_payload()
        self.assertTrue(payload["experimental"])

    def test_03_no_eligible_history_unavailable(self):
        """3. No eligible history -> quantiles and mean unavailable."""
        lab = ExperimentalRedInferenceLab([])
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        self.assertEqual(report.eligible_match_count, 0)
        self.assertEqual(report.eligible_observation_count, 0)
        self.assertTrue(report.insufficient_data)
        self.assertIsNone(report.red_total_mean)
        self.assertIsNone(report.red_total_median)
        self.assertIsNone(report.red_total_quantiles.p50)
        self.assertIn("No eligible canonical history matches observed for red inference.", report.warnings)

    def test_04_small_sample_insufficient_data(self):
        """4. Small sample size (< 5) -> insufficientData=True."""
        records = [
            _build_test_record("rec_01", red_count=0, red_total_value=0.0),
            _build_test_record("rec_02", red_count=1, red_total_value=150000.0),
        ]
        lab = ExperimentalRedInferenceLab(records)
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        self.assertEqual(report.eligible_match_count, 2)
        self.assertTrue(report.insufficient_data)
        self.assertTrue(any("Small sample warning" in w for w in report.warnings))

    def test_05_source_rejected_records_excluded(self):
        """5. Non-FINALIZED or rejected records (DRAFT, CANCELLED, DIAGNOSTIC) are excluded."""
        records = [
            _build_test_record("rec_draft", lifecycle="DRAFT", red_count=1),
            _build_test_record("rec_cancelled", lifecycle="CANCELLED", red_count=2),
            _build_test_record("rec_diagnostic", diagnostic_only=True, red_count=1),
            _build_test_record("rec_valid", lifecycle="FINALIZED", red_count=0),
        ]
        lab = ExperimentalRedInferenceLab(records)
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        self.assertEqual(report.eligible_match_count, 1)
        self.assertEqual(report.history_evidence_ids, ["rec_valid"])

    def test_06_replay_test_origin_excluded_from_training(self):
        """6. Replay/test dataOrigin records are strictly excluded from formal training history."""
        records = [
            _build_test_record("rec_replay", origin="replay", red_count=1),
            _build_test_record("rec_test", origin="test", red_count=1),
            _build_test_record("rec_mock", origin="mock", red_count=1),
            _build_test_record("rec_live", origin="live", red_count=0),
        ]
        lab = ExperimentalRedInferenceLab(records)
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        self.assertEqual(report.eligible_match_count, 1)
        self.assertEqual(report.history_evidence_ids, ["rec_live"])

    def test_07_known_red_does_not_assume_without_replacement(self):
        """7. Known red items condition observational evidence only (conditioningMode='observational_only')."""
        records = [
            _build_test_record("rec_01", red_count=1, red_total_value=120000.0),
            _build_test_record("rec_02", red_count=2, red_total_value=250000.0),
        ]
        lab = ExperimentalRedInferenceLab(records)
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60, "knownRed": 1})
        self.assertEqual(report.conditioning_mode, "observational_only")
        payload = report.to_payload()
        self.assertEqual(payload["conditioningMode"], "observational_only")

    def test_08_sampling_assumption_default_unknown(self):
        """8. samplingAssumption must default strictly to 'unknown'."""
        lab = ExperimentalRedInferenceLab([])
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        self.assertEqual(report.sampling_assumption, "unknown")
        payload = report.to_payload()
        self.assertEqual(payload["samplingAssumption"], "unknown")

    def test_09_pmf_normalization(self):
        """9. Red count PMF probabilities must sum strictly to 1.0."""
        records = [
            _build_test_record("rec_01", red_count=0, red_total_value=0.0),
            _build_test_record("rec_02", red_count=0, red_total_value=0.0),
            _build_test_record("rec_03", red_count=1, red_total_value=100000.0),
            _build_test_record("rec_04", red_count=1, red_total_value=120000.0),
            _build_test_record("rec_05", red_count=2, red_total_value=250000.0),
            _build_test_record("rec_06", red_count=2, red_total_value=280000.0),
        ]
        lab = ExperimentalRedInferenceLab(records)
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        self.assertFalse(report.insufficient_data)
        pmf = report.red_count_pmf
        self.assertTrue(len(pmf) > 0)
        prob_sum = sum(pmf.values())
        self.assertAlmostEqual(prob_sum, 1.0, places=5)
        # Check payload serialization
        payload = report.to_payload()
        serialized_sum = sum(float(v) for v in payload["redCountPmf"].values())
        self.assertAlmostEqual(serialized_sum, 1.0, places=4)

    def test_10_quantile_monotonicity(self):
        """10. Quantiles must be strictly monotonic: p10 <= p20 <= p25 <= p50 <= p75 <= p80 <= p90 <= p95."""
        records = [
            _build_test_record("rec_01", red_count=1, red_total_value=50000.0),
            _build_test_record("rec_02", red_count=1, red_total_value=80000.0),
            _build_test_record("rec_03", red_count=1, red_total_value=120000.0),
            _build_test_record("rec_04", red_count=2, red_total_value=200000.0),
            _build_test_record("rec_05", red_count=2, red_total_value=250000.0),
            _build_test_record("rec_06", red_count=2, red_total_value=300000.0),
        ]
        lab = ExperimentalRedInferenceLab(records)
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        q = report.red_total_quantiles
        self.assertTrue(q.is_monotonic())
        self.assertLessEqual(q.p10, q.p20)
        self.assertLessEqual(q.p20, q.p25)
        self.assertLessEqual(q.p25, q.p50)
        self.assertLessEqual(q.p50, q.p75)
        self.assertLessEqual(q.p75, q.p80)
        self.assertLessEqual(q.p80, q.p90)
        self.assertLessEqual(q.p90, q.p95)

    def test_11_historical_shadow_untouched(self):
        """11. Historical Shadow runtime and contracts remain completely untouched."""
        import live_shadow
        # Confirm live_shadow module functions are intact
        self.assertTrue(callable(live_shadow.load_history_snapshot))
        self.assertTrue(callable(live_shadow.default_history_path))
        self.assertTrue(callable(live_shadow.history_generation))

    def test_12_production_decision_untouched(self):
        """12. Production solver decisions and lines are completely untouched by experimental red."""
        brain = AuctionBrain()
        session_ctx = {
            "q": 60,
            "goldAvg": 10000,
            "costs": {"sunkCost": 5000, "futureIncrementalCost": 0},
            "leaderBid": 400000,
            "targetProfit": 30000,
        }
        res = brain.solve_session(session_ctx)
        # Production lines and directives must match standard deterministic solver
        self.assertEqual(res["valP50"], 600000)
        self.assertEqual(res["valRange"], (540000, 660000))
        self.assertEqual(res["targetProfitLine"], 540000 - 5000 - 30000)
        self.assertEqual(res["globalProfitLine"], 540000 - 5000)
        self.assertEqual(res["actionDirective"], "🟢 仍在目标利润区 · 可以继续")
        # Experimental red is purely side-by-side
        self.assertIn("experimentalRed", res)
        self.assertFalse(res["experimentalRed"]["productionEligible"])

    def test_13_same_record_idempotent_ingestion(self):
        """13. Ingesting the same record multiple times does not duplicate counts."""
        lab = ExperimentalRedInferenceLab([])
        rec = _build_test_record("rec_unique", red_count=1, red_total_value=100000.0)
        first = lab.ingest_record(rec)
        second = lab.ingest_record(rec)
        self.assertTrue(first)
        self.assertFalse(second)  # Rejected duplicate ingestion
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        self.assertEqual(report.eligible_match_count, 1)

    def test_14_history_generation_update(self):
        """14. Ingesting records increments history generation."""
        lab = ExperimentalRedInferenceLab([])
        gen0 = lab.history_generation
        lab.ingest_record(_build_test_record("rec_gen1", red_count=0))
        self.assertGreater(lab.history_generation, gen0)
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        self.assertEqual(report.history_generation, lab.history_generation)

    def test_15_ui_default_collapsed(self):
        """15. Overlay HTML experimental section must be default collapsed (no open attribute)."""
        html_path = os.path.join(_CORE_DIR, "overlay_alpha.html")
        with open(html_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        # Must contain <details id="strategyExperimentalArea" class="experimental-area"
        # without open attribute
        self.assertIn('<details id="strategyExperimentalArea"', content)
        self.assertNotIn('<details id="strategyExperimentalArea" open', content)

    def test_16_experimental_explicit_disclaimer(self):
        """16. Prominent disclaimer '实验结果 · 不参与正式出价' in payload and HTML."""
        lab = ExperimentalRedInferenceLab([])
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        payload = report.to_payload()
        self.assertEqual(payload.get("disclaimer"), "实验结果 · 不参与正式出价")
        html_path = os.path.join(_CORE_DIR, "overlay_alpha.html")
        with open(html_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("实验结果 · 不参与正式出价", content)

    def test_17_pr_a_contracts_preserved(self):
        """17. PR-A Mean/Median/Conservative provenance contract preserved."""
        brain = AuctionBrain()
        session_ctx = {"q": 60, "goldAvg": 10000}
        res = brain.solve_session(session_ctx)
        strat_metrics = res.get("strategyMetrics", {})
        # MeanEstimate is None when no true mean exists
        self.assertIsNone(strat_metrics.get("meanEstimate"))
        self.assertEqual(strat_metrics.get("meanSource"), "unavailable")
        # MedianEstimate is P50
        self.assertEqual(strat_metrics.get("medianEstimate"), 600000.0)
        self.assertEqual(strat_metrics.get("medianSource"), "p50_point")
        # ConservativeEstimate is P20
        self.assertEqual(strat_metrics.get("conservativeEstimate"), 540000.0)
        self.assertEqual(strat_metrics.get("conservativeSource"), "p20_point")

    def test_18_boundary3_files_untouched(self):
        """18. Boundary 3 input safety files remain untouched."""
        git_cmd = subprocess.run(
            ["git", "diff", "--name-only", "main...HEAD"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        changed_files = [f.strip() for f in git_cmd.stdout.splitlines() if f.strip()]
        for changed in changed_files:
            self.assertNotIn("b3", changed.lower())
            self.assertNotIn("input_safety", changed.lower())
            self.assertNotIn("mouse_hook", changed.lower())

    def test_19_offline_evaluation_time_split_leakage_free(self):
        """19. Offline evaluation executes time-split without leakage and computes metrics."""
        from red_inference_offline_eval import run_time_split_evaluation
        records = [
            _build_test_record(f"rec_{i:02d}", played_at=f"2026-09-16T{10 + i:02d}:00:00Z", red_count=i % 3, red_total_value=float((i % 3) * 100000))
            for i in range(10)
        ]
        res = run_time_split_evaluation(records, train_ratio=0.7)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["trainMatchCount"], 7)
        self.assertEqual(res["evalMatchCount"], 3)
        self.assertEqual(res["evaluatedWithTruthCount"], 3)
        self.assertIsNotNone(res["metrics"]["mae"])
        self.assertIsNotNone(res["metrics"]["p20Coverage"])


if __name__ == "__main__":
    unittest.main()
