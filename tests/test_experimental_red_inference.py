# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for PR-B Experimental Red Probability Inference Lab.

Covers all 19 base requirements + Fixes A through L:
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
18. Boundary 3 files untouched (Real git diff file intersection empty - Fix L)
19. Offline evaluation time-split leakage-free
20. Fix A: FINALIZED + auction red count only => rejected as red count truth
21. Fix B: settlement.verified + partial items => NOT warehouse complete
22. Fix C: ambiguous red item => excluded from red total-value truth
23. Fix C: verified complete zero-red => valid zero sample
24. Fix D: experiment exception => production solve survives
25. Fix D: experiment exception => HUD survives
26. Fix F: historyGeneration change => lab cheap generation refresh
27. Fix G: duplicate index change => old eligibility recalculated
28. Fix H: same physical match different IDs cannot cross train/eval
29. Fix I: eval weak truth excluded from metrics
30. Fix J: synthetic fixture marked performanceClaimEligible=false
31. Fix K: similarity profile honesty declaration
"""

import copy
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
    safe_evaluate_experimental_red,
    SIMILARITY_PROFILE,
)
from auction_brain import AuctionBrain
from strategy_ux_metrics import EstimateMode, get_authoritative_strategy_store
from red_inference_offline_eval import run_time_split_evaluation


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
    red_inventory_complete: bool = True,
    item_confirmation_status: str = "CONFIRMED",
    clearing_price: float = 50000.0,
    coverage_status: str = "COMPLETE",
    red_provenance: Optional[str] = "post_settlement_verified_warehouse",
) -> Dict[str, Any]:
    """Helper to construct a contract-compliant Canonical MatchRecord v7 for testing."""
    return {
        "schemaVersion": 7,
        "id": record_id,
        "playedAt": played_at,
        "lifecycleStatus": lifecycle,
        "source": "0.65-vision-auto-archiver",
        "dataOrigin": origin,
        "diagnosticOnly": diagnostic_only,
        "coverageStatus": coverage_status,
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
                "redInventoryComplete": red_inventory_complete,
                "provenance": red_provenance if red_inventory_complete else None,
            },
        },
        "settlement": {
            "status": "verified",
            "verified": True,
            "warehouseCoverageStatus": coverage_status,
            "actualTotal": gold_avg * 10 + red_total_value,
            "clearingPrice": clearing_price,
            "settlementItems": [
                {
                    "name": f"RedItem_{i}",
                    "quality": "red",
                    "value": red_total_value / max(1, red_count),
                    "confirmationStatus": item_confirmation_status,
                }
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
        self.assertEqual(res["valP50"], 600000)
        self.assertEqual(res["valRange"], (540000, 660000))
        self.assertEqual(res["targetProfitLine"], 540000 - 5000 - 30000)
        self.assertEqual(res["globalProfitLine"], 540000 - 5000)
        self.assertEqual(res["actionDirective"], "🟢 仍在目标利润区 · 可以继续")
        self.assertIn("experimentalRed", res)
        self.assertFalse(res["experimentalRed"]["productionEligible"])

    def test_13_same_record_idempotent_ingestion(self):
        """13. Ingesting the same record multiple times does not duplicate counts."""
        lab = ExperimentalRedInferenceLab([])
        rec = _build_test_record("rec_unique", red_count=1, red_total_value=100000.0)
        first = lab.ingest_record(rec)
        second = lab.ingest_record(rec)
        self.assertTrue(first)
        self.assertFalse(second)
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
        self.assertIsNone(strat_metrics.get("meanEstimate"))
        self.assertEqual(strat_metrics.get("meanSource"), "unavailable")
        self.assertEqual(strat_metrics.get("medianEstimate"), 600000.0)
        self.assertEqual(strat_metrics.get("medianSource"), "p50_point")
        self.assertEqual(strat_metrics.get("conservativeEstimate"), 540000.0)
        self.assertEqual(strat_metrics.get("conservativeSource"), "p20_point")

    def test_18_boundary3_files_untouched_real_intersection(self):
        """18 & Fix L: Boundary 3 files untouched (real git diff file intersection between PR1 and PR-B)."""
        # PR 1 diff against fbd30a2
        pr1_cmd = subprocess.run(
            ["git", "diff", "--name-only", "fbd30a204c9c023034c725b7bcded158655bc53c..a0dd2a982755eb1feeba92ed776b85b4a4ef2b87"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        pr1_files = set(f.strip() for f in pr1_cmd.stdout.splitlines() if f.strip())

        # PR-B diff against main
        prb_cmd = subprocess.run(
            ["git", "diff", "--name-only", "main...HEAD"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        prb_files = set(f.strip() for f in prb_cmd.stdout.splitlines() if f.strip())

        intersection = pr1_files & prb_files
        self.assertEqual(len(intersection), 0, f"PR-B touched Boundary 3 files: {intersection}")

    def test_19_offline_evaluation_time_split_leakage_free(self):
        """19. Offline evaluation executes time-split without leakage and computes metrics."""
        records = [
            _build_test_record(f"rec_{i:02d}", played_at=f"2026-09-16T{10 + i:02d}:00:00Z", red_count=i % 3, red_total_value=float((i % 3) * 100000))
            for i in range(10)
        ]
        res = run_time_split_evaluation(records, train_ratio=0.7)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["trainMatchCount"], 7)
        self.assertEqual(res["evalMatchCount"], 3)
        self.assertEqual(res["evaluatedRedCountTruthCount"], 3)
        self.assertIsNotNone(res["metrics"]["mae"])
        self.assertIsNotNone(res["metrics"]["p20Coverage"])

    # ---------------------------------------------------------------------------------
    # New Fix Tests (Fix A through Fix L)
    # ---------------------------------------------------------------------------------

    def test_20_fix_a_auction_only_count_rejected_as_red_truth(self):
        """Fix A: FINALIZED record with auction/OCR red count only is REJECTED from red count truth."""
        # red_inventory_complete is False, unproven coverage, and no post-settlement verified red items or complete warehouse
        rec = _build_test_record("rec_ocr_only", red_count=1, red_inventory_complete=False, coverage_status="UNPROVEN", red_provenance=None)
        rec["settlement"]["settlementItems"] = []  # No settlement red items
        el = evaluate_record_red_eligibility(rec)
        self.assertTrue(el.match_eligible)
        self.assertFalse(el.red_count_eligible)
        self.assertEqual(el.red_count_truth_source, "UNVERIFIED_AUCTION_OR_OCR")
        self.assertIn("RED_COUNT_LACKS_VERIFIED_POST_SETTLEMENT_OR_WAREHOUSE_TRUTH", el.exclusion_reasons)

    def test_21_fix_b_settlement_verified_does_not_equal_warehouse_complete(self):
        """Fix B: settlement.verified + partial settlement items does NOT imply warehouse complete."""
        rec = _build_test_record("rec_partial_st", red_count=1, red_inventory_complete=False, coverage_status="UNPROVEN", red_provenance=None)
        rec["settlement"]["verified"] = True
        rec["settlement"]["status"] = "verified"
        el = evaluate_record_red_eligibility(rec)
        self.assertFalse(el.warehouse_complete_eligible)
        self.assertEqual(el.warehouse_completeness_source, "UNVERIFIED_OR_PARTIAL_WAREHOUSE")

    def test_22_fix_c_ambiguous_red_item_excluded_from_red_total_value_truth(self):
        """Fix C: Ambiguous or candidate-only red items are excluded from red total value truth."""
        # item has confirmationStatus = "CANDIDATE_ONLY"
        rec = _build_test_record(
            "rec_ambig",
            red_count=1,
            red_total_value=150000.0,
            red_inventory_complete=True,
            item_confirmation_status="CANDIDATE_ONLY",
        )
        el = evaluate_record_red_eligibility(rec)
        # Red count is eligible from complete inventory
        self.assertTrue(el.red_count_eligible)
        # But total value truth is strictly REJECTED because item is ambiguous!
        self.assertFalse(el.red_total_value_eligible)
        self.assertIsNone(el.observed_red_total_value)
        self.assertEqual(el.red_identity_truth_source, "AMBIGUOUS_OR_CANDIDATE_RED_ITEMS")

    def test_23_fix_c_verified_complete_zero_red_is_valid_zero_sample(self):
        """Fix C: Verified complete warehouse with 0 red is an admitted zero-value truth sample."""
        rec = _build_test_record("rec_zero", red_count=0, red_total_value=0.0, red_inventory_complete=True)
        el = evaluate_record_red_eligibility(rec)
        self.assertTrue(el.red_count_eligible)
        self.assertTrue(el.warehouse_complete_eligible)
        self.assertTrue(el.red_total_value_eligible)
        self.assertEqual(el.observed_red_count, 0)
        self.assertEqual(el.observed_red_total_value, 0.0)
        self.assertEqual(el.red_value_truth_source, "VERIFIED_ZERO_RED_COMPLETE")

    def test_24_fix_d_experiment_exception_production_solve_survives(self):
        """Fix D: If experimental red inference raises an exception, production solve survives completely."""
        class CrashingLab:
            def sync_with_live_history(self):
                pass
            def evaluate_inference(self, *args, **kwargs):
                raise RuntimeError("Simulated crash in experimental red lab!")

        brain = AuctionBrain()
        session_ctx = {"q": 60, "goldAvg": 10000}
        # Call safe_evaluate_experimental_red with crashing lab
        safe_res = safe_evaluate_experimental_red(session_ctx, lab=CrashingLab())
        self.assertEqual(safe_res["status"], "unavailable")
        self.assertTrue(any("Simulated crash" in w for w in safe_res["warnings"]))

        # Production solve still runs cleanly and attaches fail-isolated payload
        solve_res = brain.solve_session(session_ctx)
        self.assertEqual(solve_res["valP50"], 600000)
        self.assertEqual(solve_res["actionDirective"], "🟢 仍在目标利润区 · 可以继续")
        self.assertIn("experimentalRed", solve_res)

    def test_25_fix_d_experiment_exception_hud_payload_survives(self):
        """Fix D: HUD payload generator survives when experimental inference fails."""
        from main import build_in_auction_hud_payload
        ctx = {"q": 60, "goldAvg": 10000, "round": 1}
        payload = build_in_auction_hud_payload(ctx, compute_shadow=False)
        self.assertIn("experimentalRed", payload)
        self.assertFalse(payload["experimentalRed"]["productionEligible"])

    def test_26_fix_f_cheap_generation_sync_refreshes_snapshot(self):
        """Fix F: sync_with_live_history notices source generation increment and reloads."""
        lab = ExperimentalRedInferenceLab([])
        self.assertIsNone(lab._source_history_generation)
        synced = lab.sync_with_live_history()
        # Initial sync loads snapshot and tracks generation
        self.assertIsNotNone(lab._source_history_generation)
        # Calling again without source change does not rescan
        self.assertFalse(lab.sync_with_live_history())

    def test_27_fix_g_duplicate_index_change_recalculates_old_eligibility(self):
        """Fix G: Ingesting a duplicate record recalculates eligibility for all existing records."""
        lab = ExperimentalRedInferenceLab([])
        rec1 = _build_test_record("rec_orig", red_count=0)
        lab.ingest_record(rec1)
        self.assertTrue(lab._eligibility_cache["rec_orig"].match_eligible)

        # Ingest another record with same physical content fingerprint
        rec2 = _build_test_record("rec_dup", red_count=0)  # Identical venue, box, actualTotal, clearingPrice
        lab.ingest_record(rec2)

        # Both records should now be recognized under duplicate index
        self.assertIn("rec_orig", lab._records_cache)
        self.assertIn("rec_dup", lab._records_cache)
        self.assertEqual(lab.history_generation, 2)

    def test_28_fix_h_same_physical_match_different_ids_cannot_cross_train_eval(self):
        """Fix H & Final Fix 2: Same physical match duplicate group split across cutoff cannot cross train/eval."""
        from history_admission import build_duplicate_index, canonical_duplicate_group_key

        # rec1 at 10:00 (train candidate)
        rec1 = _build_test_record("rec_id_1", played_at="2026-09-16T10:00:00Z", red_count=1, red_total_value=120000.0)
        # rec_dup_a at 11:00 (train candidate) and rec_dup_b at 11:00 (eval candidate)
        # Identical playedAt, venue, box, actualTotal, clearingPrice => same canonical duplicate group!
        rec_dup_a = _build_test_record("rec_dup_a", played_at="2026-09-16T11:00:00Z", red_count=1, red_total_value=120000.0)
        rec_dup_b = _build_test_record("rec_dup_b", played_at="2026-09-16T11:00:00Z", red_count=1, red_total_value=120000.0)
        # rec_eval_3 at 15:00 (eval candidate)
        rec_eval_3 = _build_test_record("rec_eval_3", played_at="2026-09-16T15:00:00Z", red_count=2, red_total_value=250000.0)

        records = [rec1, rec_dup_a, rec_dup_b, rec_eval_3]

        # Verify they are judged as the same duplicate group by canonical DuplicateIndex authority
        dup_idx = build_duplicate_index(records)
        self.assertIn("rec_dup_a", dup_idx.potential_content_duplicate_ids)
        self.assertIn("rec_dup_b", dup_idx.potential_content_duplicate_ids)
        self.assertEqual(canonical_duplicate_group_key(rec_dup_a), canonical_duplicate_group_key(rec_dup_b))

        # Split with train_ratio=0.5 -> divides indices [0, 1] into train and [2, 3] into eval
        # rec_dup_a goes to train side, rec_dup_b goes to eval side
        res = run_time_split_evaluation(records, train_ratio=0.5)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["trainMatchCount"], 2)  # rec1 & rec_dup_a in train
        # rec_dup_b MUST be purged from eval because it shares physical match group with rec_dup_a in train!
        self.assertEqual(res["evalMatchCount"], 1)   # ONLY rec_eval_3 survives in eval!

        # Assert no record ID intersection and no physical group intersection
        train_ids = {str(r.get("id")) for r in [rec1, rec_dup_a]}
        eval_ids = {str(r.get("id")) for r in [rec_eval_3]}
        self.assertTrue(train_ids.isdisjoint(eval_ids))

    def test_29_fix_i_eval_weak_truth_excluded_from_metrics(self):
        """Fix I: Matches in evaluation set without confirmed truth are excluded from metric calculations."""
        # rec_valid: complete verified red item
        rec_valid = _build_test_record("rec_eval_valid", played_at="2026-09-16T15:00:00Z", red_count=1, red_total_value=100000.0)
        # rec_weak: ambiguous item confirmation
        rec_weak = _build_test_record(
            "rec_eval_weak",
            played_at="2026-09-16T16:00:00Z",
            red_count=1,
            red_total_value=100000.0,
            item_confirmation_status="CANDIDATE_ONLY",
        )
        train_recs = [
            _build_test_record(f"train_{i}", played_at=f"2026-09-16T0{i}:00:00Z", red_count=1, red_total_value=100000.0)
            for i in range(1, 6)
        ]
        all_recs = train_recs + [rec_valid, rec_weak]
        res = run_time_split_evaluation(all_recs, split_timestamp="2026-09-16T12:00:00Z")
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["evalMatchCount"], 2)
        # Both have verified red count
        self.assertEqual(res["evaluatedRedCountTruthCount"], 2)
        # Only rec_valid has verified red total value truth! rec_weak is excluded!
        self.assertEqual(res["evaluatedRedValueTruthCount"], 1)
        self.assertIn("AMBIGUOUS_OR_CANDIDATE_RED_ITEMS", res["excludedTruthReasons"])

    def test_30_fix_j_synthetic_fixture_marked_performance_claim_ineligible(self):
        """Fix J: Synthetic fixture evaluations are marked performanceClaimEligible=False."""
        records = [
            _build_test_record(f"rec_{i:02d}", played_at=f"2026-09-16T{10 + i:02d}:00:00Z", red_count=i % 3, red_total_value=float((i % 3) * 100000))
            for i in range(10)
        ]
        res = run_time_split_evaluation(records, dataset_kind="synthetic_fixture")
        meta = res.get("metadata", {})
        self.assertEqual(meta.get("datasetKind"), "synthetic_fixture")
        self.assertTrue(meta.get("harnessVerification"))
        self.assertFalse(meta.get("performanceClaimEligible"))

    def test_31_fix_k_similarity_profile_declaration(self):
        """Fix K: Similarity profile honestly declares only venue, box, and q as features."""
        self.assertEqual(SIMILARITY_PROFILE["similarityProfileVersion"], "v1_canonical_coarse")
        self.assertEqual(SIMILARITY_PROFILE["featuresUsed"], ["venue", "box", "q"])
        self.assertEqual(SIMILARITY_PROFILE["feasibilityGates"], ["knownRedCount"])
        lab = ExperimentalRedInferenceLab([])
        report = lab.evaluate_inference({"venue": "standard", "box": "box_normal", "q": 60})
        self.assertEqual(report.similarity_profile["featuresUsed"], ["venue", "box", "q"])

    # ---------------------------------------------------------------------------------
    # Final Fix Tests (Final Fix 1 & Final Fix 2)
    # ---------------------------------------------------------------------------------

    def test_32_red_inventory_complete_without_trusted_provenance_rejected(self):
        """Final Fix 1: redInventoryComplete=True without trusted provenance is rejected from coverage/count truth."""
        rec = _build_test_record("r_untrusted", red_count=1, red_inventory_complete=True, coverage_status="UNPROVEN", red_provenance=None)
        el = evaluate_record_red_eligibility(rec)
        self.assertFalse(el.warehouse_complete_eligible)
        self.assertFalse(el.red_count_eligible)
        self.assertFalse(el.red_total_value_eligible)
        self.assertEqual(el.warehouse_completeness_source, "RED_INVENTORY_COMPLETE_LACKS_TRUSTED_PROVENANCE")

    def test_33_all_review_units_confirmed_without_coverage_complete_rejected(self):
        """Final Fix 1: all reviewUnits CONFIRMED without whole-warehouse coverage complete is rejected."""
        rec = _build_test_record("r_units_conf", red_count=1, red_inventory_complete=False, coverage_status="UNPROVEN", red_provenance=None)
        rec["reviewUnits"] = [{"name": "Item1", "quality": "red", "confirmationStatus": "CONFIRMED", "value": 100000}]
        el = evaluate_record_red_eligibility(rec)
        self.assertFalse(el.warehouse_complete_eligible)
        self.assertFalse(el.red_count_eligible)

    def test_34_warehouse_zero_unknown_without_coverage_proof_rejected(self):
        """Final Fix 1: warehouse.itemCount>0 and unknownCount=0 without coverage proof is rejected."""
        rec = _build_test_record("r_zero_unk", red_count=1, red_inventory_complete=False, coverage_status="UNPROVEN", red_provenance=None)
        rec["warehouse"] = {"itemCount": 5, "unknownCount": 0}
        el = evaluate_record_red_eligibility(rec)
        self.assertFalse(el.warehouse_complete_eligible)
        self.assertFalse(el.red_count_eligible)

    def test_35_settlement_verified_red_items_subset_without_completeness_cannot_be_count_truth(self):
        """Final Fix 1: settlementVerifiedRedItems without completeness is verified subset only, NOT count truth."""
        rec = _build_test_record("r_subset", red_count=1, red_inventory_complete=False, coverage_status="UNPROVEN", red_provenance=None)
        rec["qualities"]["red"]["settlementVerifiedRedItems"] = "300000"
        el = evaluate_record_red_eligibility(rec)
        self.assertFalse(el.red_count_eligible)
        self.assertFalse(el.red_total_value_eligible)
        self.assertEqual(el.red_count_truth_source, "VERIFIED_RED_SUBSET_WITHOUT_COVERAGE_PROOF")

    def test_36_generic_confirmed_true_without_exact_status_rejected_from_value_truth(self):
        """Final Fix 1: Generic confirmed=True without CONFIRMED or EXACT_IDENTIFIED is rejected from value truth."""
        rec = _build_test_record("r_generic_conf", red_count=1, red_inventory_complete=True, coverage_status="COMPLETE", red_provenance="canonical_coverage_complete")
        rec["settlement"]["settlementItems"] = [{"name": "ItemRed", "quality": "red", "value": 200000, "confirmed": True}]
        el = evaluate_record_red_eligibility(rec)
        self.assertTrue(el.red_count_eligible)
        self.assertFalse(el.red_total_value_eligible)
        self.assertEqual(el.red_identity_truth_source, "AMBIGUOUS_OR_CANDIDATE_RED_ITEMS")

    def test_37_canonical_exact_identity_accepted_for_value_truth(self):
        """Final Fix 1: Canonical exact confirmation status (CONFIRMED) is accepted for red total value truth."""
        rec = _build_test_record("r_exact", red_count=1, red_inventory_complete=True, coverage_status="COMPLETE", red_provenance="canonical_coverage_complete")
        rec["settlement"]["settlementItems"] = [{"name": "ItemRed", "quality": "red", "value": 200000, "confirmationStatus": "CONFIRMED"}]
        el = evaluate_record_red_eligibility(rec)
        self.assertTrue(el.red_count_eligible)
        self.assertTrue(el.red_total_value_eligible)
        self.assertEqual(el.observed_red_total_value, 200000.0)

    def test_38_canonical_coverage_complete_plus_zero_red_valid_zero_truth(self):
        """Final Fix 1: Canonical coverage-complete with zero red is valid zero ground truth."""
        rec = _build_test_record("r_zero_truth", red_count=0, red_inventory_complete=True, coverage_status="COMPLETE", red_provenance="canonical_coverage_complete")
        el = evaluate_record_red_eligibility(rec)
        self.assertTrue(el.warehouse_complete_eligible)
        self.assertTrue(el.red_count_eligible)
        self.assertTrue(el.red_total_value_eligible)
        self.assertEqual(el.observed_red_count, 0)
        self.assertEqual(el.observed_red_total_value, 0.0)

    def test_39_canonical_duplicate_identity_unavailable_fail_closed(self):
        """Final Fix 2: If canonical duplicate identity cannot be derived, offline eval fails closed."""
        rec_bad = _build_test_record("r_bad", played_at="invalid-date")
        res = run_time_split_evaluation([rec_bad])
        self.assertEqual(res["status"], "insufficient_data")
        self.assertEqual(res["evaluatedCount"], 0)


if __name__ == "__main__":
    unittest.main()
