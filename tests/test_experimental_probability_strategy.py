# -*- coding: utf-8 -*-
"""Comprehensive Targeted Test Suite for PR-C: Experimental Probability and Strategy Lab.

Covers all 22 required points:
1. all PR-C profiles default disabled (except baseline)
2. productionEligible=false
3. production output exact parity when disabled
4. convolution normalization
5. convolution quantile monotonicity
6. state-space budget
7. invalid distribution rejected
8. R1-R4 profile metadata/source present
9. external constants never enter production path
10. color prior disabled by default
11. external color prior != PR-B empirical red
12. CELL_FIT feasible case
13. CELL_FIT impossible case
14. CELL_FIT cannot delete production state
15. special profile invalid -> fail closed
16. experiment exception -> production survives
17. UI default collapsed
18. warning text present
19. cross-match reset behavior
20. PR-B contracts unchanged
21. PR-A contracts unchanged
22. Boundary3 file intersection == 0
"""

import os
import subprocess
import sys
import unittest
from typing import Any, Dict

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_CORE_DIR = os.path.join(_PROJECT_ROOT, "core")
_APP_DIR = os.path.join(_PROJECT_ROOT, "app")
for _p in (_PROJECT_ROOT, _CORE_DIR, _APP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from auction_brain import AuctionBrain
from experimental_probability_strategy import (
    DiscreteDistribution,
    ExperimentalStrategyProfile,
    ExperimentalStrategyRegistry,
    CellFitDiagnostic,
    compute_cell_fit,
    convolve_discrete_distributions,
    evaluate_experimental_probability_strategy,
    get_global_strategy_registry,
    safe_evaluate_experimental_probability_strategy,
)
from probability_strategy_offline_eval import (
    format_comparison_markdown,
    run_probability_strategy_comparison,
)
from strategy_ux_metrics import EstimateMode, get_authoritative_strategy_store


class TestExperimentalProbabilityStrategyLab(unittest.TestCase):
    def setUp(self):
        get_authoritative_strategy_store().reset_for_new_match("test_session_setup")
        get_global_strategy_registry().reset_for_new_match()

    def test_01_all_external_profiles_default_disabled(self):
        """1. All external PR-C profiles must be disabled by default; only baseline enabled."""
        reg = get_global_strategy_registry()
        reg.reset_for_new_match()
        active = reg.get_active_profile_ids()
        self.assertEqual(active, ["baseline"])
        self.assertTrue(reg.is_profile_enabled("baseline"))
        self.assertFalse(reg.is_profile_enabled("dafu_round_heuristic_v1"))
        self.assertFalse(reg.is_profile_enabled("external_color_prior_dafu_v1"))
        self.assertFalse(reg.is_profile_enabled("cell_fit_v1"))
        self.assertFalse(reg.is_profile_enabled("convolution_v1"))

    def test_02_production_eligible_strictly_false(self):
        """2. productionEligible must be strictly False across all PR-C outputs."""
        report = evaluate_experimental_probability_strategy({"q": 60, "goldAvg": 10000})
        self.assertFalse(report.production_eligible)
        self.assertTrue(report.experimental)
        payload = report.to_payload()
        self.assertFalse(payload["productionEligible"])
        self.assertTrue(payload["experimental"])

    def test_03_production_output_exact_parity_when_disabled(self):
        """3. Production solver output must be strictly identical before and after PR-C integration."""
        brain = AuctionBrain()
        session_ctx = {
            "q": 60,
            "goldAvg": 12000.0,
            "venue": "standard",
            "box": "box_normal",
            "costs": {"entry": 5000, "futureIncrementalCost": 0},
            "targetProfit": 30000,
        }
        dec = brain.solve_session(session_ctx)
        # Verify core production fields are untouched
        self.assertEqual(dec["valP50"], 720000.0)
        self.assertEqual(dec["valRange"], (648000, 792000))
        self.assertEqual(dec["targetProfitLine"], 613000)
        self.assertEqual(dec["actionDirective"], "🟢 仍在目标利润区 · 可以继续")
        self.assertIn("experimentalProbabilityStrategy", dec)
        self.assertFalse(dec["experimentalProbabilityStrategy"]["productionEligible"])

    def test_04_convolution_normalization(self):
        """4. Discrete convolution must produce strictly normalized PMF (sum == 1.0 within tolerance)."""
        d1 = DiscreteDistribution({100.0: 0.3, 200.0: 0.7})
        d2 = DiscreteDistribution({50.0: 0.5, 150.0: 0.5})
        d_conv, budget_exceeded = convolve_discrete_distributions([d1, d2])
        self.assertFalse(budget_exceeded)
        self.assertTrue(d_conv.is_valid)
        prob_sum = sum(d_conv.pmf.values())
        self.assertAlmostEqual(prob_sum, 1.0, places=5)
        self.assertAlmostEqual(d_conv.normalization_error, 0.0, places=4)

    def test_05_convolution_quantile_monotonicity(self):
        """5. Convolved distribution quantiles must be strictly monotonic."""
        d1 = DiscreteDistribution({100.0: 0.2, 200.0: 0.5, 300.0: 0.3})
        d2 = DiscreteDistribution({50.0: 0.4, 100.0: 0.6})
        d3 = DiscreteDistribution({10.0: 0.5, 20.0: 0.5})
        d_conv, _ = convolve_discrete_distributions([d1, d2, d3])
        q = d_conv.quantiles
        self.assertLessEqual(q.p10, q.p20)
        self.assertLessEqual(q.p20, q.p25)
        self.assertLessEqual(q.p25, q.p50)
        self.assertLessEqual(q.p50, q.p75)
        self.assertLessEqual(q.p75, q.p80)
        self.assertLessEqual(q.p80, q.p90)
        self.assertLessEqual(q.p90, q.p95)

    def test_06_state_space_budget_exceeded_handled_gracefully(self):
        """6. State-space budget limits prevent explosion and set budget_exceeded flag safely."""
        # Create distributions with high cardinality
        d1 = DiscreteDistribution({float(i): 1.0 / 50 for i in range(50)})
        d2 = DiscreteDistribution({float(i * 10): 1.0 / 50 for i in range(50)})
        # Set artificially low max_states budget to trigger guard
        d_conv, budget_exceeded = convolve_discrete_distributions([d1, d2], max_states=30)
        self.assertTrue(budget_exceeded)
        self.assertTrue(d_conv.is_valid)
        self.assertLessEqual(d_conv.support_size, 40)
        self.assertAlmostEqual(sum(d_conv.pmf.values()), 1.0, places=4)

    def test_07_invalid_distribution_rejected(self):
        """7. Negative probabilities or NaN values are strictly rejected."""
        with self.assertRaises(ValueError):
            DiscreteDistribution({100.0: -0.2, 200.0: 1.2})
        d_nan = DiscreteDistribution({float("nan"): 1.0})
        self.assertFalse(d_nan.is_valid)
        d_empty = DiscreteDistribution({})
        self.assertFalse(d_empty.is_valid)

    def test_08_r1_r4_profile_metadata_and_provenance(self):
        """8. R1-R4 profile declares external_reference origin and validatedByOurData=False."""
        reg = get_global_strategy_registry()
        p = reg.get_profile("dafu_round_heuristic_v1")
        self.assertIsNotNone(p)
        self.assertEqual(p.source, "external_reference")
        self.assertEqual(p.source_project, "dafu_calculator")
        self.assertEqual(p.source_version, "v2.0-v2.3")
        self.assertEqual(p.evidence_level, "unverified_external_hypothesis")
        self.assertFalse(p.validated_by_our_data)
        self.assertFalse(p.production_eligible)
        self.assertIn("r1_discount", p.parameters)
        self.assertIn("r2_discount", p.parameters)
        self.assertIn("r3_discount", p.parameters)
        self.assertIn("r4_discount", p.parameters)

    def test_09_external_constants_never_enter_production_path(self):
        """9. External heuristic constants never mutate production decision lines."""
        brain = AuctionBrain()
        reg = get_global_strategy_registry()
        reg.enable_profile("dafu_round_heuristic_v1")
        ctx = {"q": 60, "goldAvg": 10000.0, "round": 1}
        dec = brain.solve_session(ctx)
        # Production lines remain strictly derived from authoritative center
        self.assertEqual(dec["valP50"], 600000.0)
        self.assertEqual(dec["valRange"], (540000, 660000))
        # Experimental price is available separately without replacing conservative
        exp_strat = dec.get("experimentalProbabilityStrategy", {})
        self.assertIsNotNone(exp_strat.get("experimentalReservePrice"))
        self.assertIsNotNone(exp_strat.get("experimentalConservativePrice"))
        self.assertNotEqual(dec["targetProfitLine"], exp_strat.get("experimentalReservePrice"))

    def test_10_color_prior_disabled_by_default(self):
        """10. Color prior profile is strictly disabled by default."""
        reg = get_global_strategy_registry()
        reg.reset_for_new_match()
        self.assertFalse(reg.is_profile_enabled("external_color_prior_dafu_v1"))
        report = evaluate_experimental_probability_strategy({"q": 60, "goldAvg": 10000}, registry=reg)
        self.assertIsNone(report.external_color_prior)

    def test_11_external_color_prior_not_equal_to_pr_b_empirical_red(self):
        """11. External color prior and PR-B empirical red are distinct and compared side-by-side."""
        reg = get_global_strategy_registry()
        reg.enable_profile("external_color_prior_dafu_v1")
        ctx = {"q": 60, "goldAvg": 10000}
        mock_red = {"eligibleMatchCount": 5, "redTotalMedian": 150000.0, "redTotalQuantiles": {"p50": 150000.0}}
        report = evaluate_experimental_probability_strategy(ctx, experimental_red=mock_red, registry=reg)
        self.assertIsNotNone(report.external_color_prior)
        self.assertEqual(report.external_color_prior["profileId"], "external_color_prior_dafu_v1")
        self.assertFalse(report.external_color_prior["validatedByOurData"])
        # Both appear in report side-by-side without fusion
        self.assertIsNotNone(report.delta_vs_pr_b_red)

    def test_12_cell_fit_feasible_case(self):
        """12. CELL_FIT reports feasible=True and fitScore > 0 when items fit in grid."""
        ctx = {
            "q": 30,
            "knownItems": [{"name": "Item1", "cells": 4}, {"name": "Item2", "cells": 6}],
            "qualityCounts": {"gold": 5},
            "qualityGrids": {"gold": 12},
        }
        cf = compute_cell_fit(ctx, total_grid=54)
        self.assertTrue(cf.feasible)
        self.assertFalse(cf.experimental_rejected)
        self.assertGreater(cf.fit_score, 0.5)
        self.assertEqual(len(cf.conflicts), 0)

    def test_13_cell_fit_impossible_case(self):
        """13. CELL_FIT detects impossible packing constraints and records conflict."""
        ctx = {
            "q": 60,
            "knownItems": [{"name": "ItemGigantic", "cells": 60}],  # exceeds 54 grid
        }
        cf = compute_cell_fit(ctx, total_grid=54)
        self.assertFalse(cf.feasible)
        self.assertTrue(cf.experimental_rejected)
        self.assertEqual(cf.fit_score, 0.0)
        self.assertIn("KNOWN_ITEM_FOOTPRINTS_EXCEED_TOTAL_GRID", cf.conflicts)

    def test_14_cell_fit_cannot_delete_production_state(self):
        """14. CELL_FIT impossibility does not delete or invalidate production solver decision."""
        brain = AuctionBrain()
        reg = get_global_strategy_registry()
        reg.enable_profile("cell_fit_v1")
        ctx = {
            "q": 80,  # exceeds grid 54
            "goldAvg": 10000.0,
            "knownItems": [{"name": "Huge", "cells": 70}],
        }
        dec = brain.solve_session(ctx)
        # Production decision is valid and unaffected
        self.assertEqual(dec["solverStatus"], "valid")
        self.assertEqual(dec["valP50"], 800000.0)
        # CELL_FIT only flags experimentalRejected in experimentalStrategyLab
        exp_strat = dec.get("experimentalProbabilityStrategy", {})
        cf = exp_strat.get("cellFit", {})
        self.assertTrue(cf.get("experimentalRejected"))

    def test_15_special_profile_invalid_fails_closed(self):
        """15. Invalid special profile fails closed without corrupting registry."""
        reg = get_global_strategy_registry()
        # Disabling nonexistent profile returns False
        self.assertFalse(reg.disable_profile("nonexistent_profile"))
        # Baseline profile cannot be disabled
        self.assertFalse(reg.disable_profile("baseline"))
        self.assertTrue(reg.is_profile_enabled("baseline"))

    def test_16_experiment_exception_production_survives(self):
        """16. Exceptions inside experimental evaluation are fail-isolated from production solve."""
        brain = AuctionBrain()
        # Pass broken context that would crash naive code
        ctx = {"q": 60, "goldAvg": 10000.0, "knownItems": "invalid_not_a_list"}
        dec = brain.solve_session(ctx)
        self.assertEqual(dec["solverStatus"], "valid")
        self.assertEqual(dec["valP50"], 600000.0)
        self.assertIn("experimentalProbabilityStrategy", dec)
        self.assertFalse(dec["experimentalProbabilityStrategy"]["productionEligible"])

    def test_17_ui_default_collapsed(self):
        """17. Experimental container in overlay_alpha.html is default collapsed (no open attribute)."""
        html_path = os.path.join(_CORE_DIR, "overlay_alpha.html")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('<details id="strategyExperimentalArea" class="experimental-area"', content)
        # Assert it does NOT contain 'open' attribute on strategyExperimentalArea
        self.assertNotIn('<details id="strategyExperimentalArea" class="experimental-area" open', content)

    def test_18_warning_text_present(self):
        """18. Disclaimer and unverified external parameter warnings are present."""
        reg = get_global_strategy_registry()
        reg.reset_for_new_match()
        # Baseline only
        rep_base = evaluate_experimental_probability_strategy({"q": 60, "goldAvg": 10000}, registry=reg)
        self.assertIn("实验结果 · 不参与正式出价", rep_base.disclaimers)
        self.assertNotIn("外部经验参数 · 未经我方真实历史验证", rep_base.disclaimers)

        # With external profile enabled
        reg.enable_profile("dafu_round_heuristic_v1")
        rep_ext = evaluate_experimental_probability_strategy({"q": 60, "goldAvg": 10000}, registry=reg)
        self.assertIn("实验结果 · 不参与正式出价", rep_ext.disclaimers)
        self.assertIn("外部经验参数 · 未经我方真实历史验证", rep_ext.disclaimers)

    def test_19_cross_match_reset_behavior(self):
        """19. Strategy registry resets active profiles strictly to baseline on new match."""
        reg = get_global_strategy_registry()
        reg.enable_profile("dafu_round_heuristic_v1")
        reg.enable_profile("cell_fit_v1")
        self.assertEqual(len(reg.get_active_profile_ids()), 3)
        reg.reset_for_new_match()
        self.assertEqual(reg.get_active_profile_ids(), ["baseline"])

    def test_20_pr_b_contracts_unchanged(self):
        """20. PR-B experimentalRed contract remains intact."""
        brain = AuctionBrain()
        dec = brain.solve_session({"q": 60, "goldAvg": 10000.0})
        self.assertIn("experimentalRed", dec)
        self.assertFalse(dec["experimentalRed"]["productionEligible"])
        self.assertTrue(dec["experimentalRed"]["experimental"])

    def test_21_pr_a_contracts_unchanged(self):
        """21. PR-A strategyMetrics (Mean/Median/Conservative provenance) remains intact."""
        brain = AuctionBrain()
        dec = brain.solve_session({"q": 60, "goldAvg": 10000.0})
        sm = dec["strategyMetrics"]
        self.assertIn("meanEstimate", sm)
        self.assertIn("meanSource", sm)
        self.assertIn("medianEstimate", sm)
        self.assertIn("medianSource", sm)
        self.assertIn("conservativeEstimate", sm)
        self.assertIn("conservativeSource", sm)

    def test_22_boundary3_intersection_zero(self):
        """22. Boundary 3 files must remain 100% untouched (empty intersection)."""
        try:
            out_b3 = subprocess.check_output(
                ["git", "diff", "--name-only", "main...origin/feature/b3-input-safety"],
                cwd=_PROJECT_ROOT,
                encoding="utf-8",
            )
            b3_files = set(filter(None, [line.strip() for line in out_b3.splitlines()]))
            out_branch = subprocess.check_output(
                ["git", "diff", "--name-only", "main"],
                cwd=_PROJECT_ROOT,
                encoding="utf-8",
            )
            branch_files = set(filter(None, [line.strip() for line in out_branch.splitlines()]))
            intersection = b3_files & branch_files
            self.assertEqual(len(intersection), 0, f"Boundary 3 file intersection not empty: {intersection}")
        except Exception as e:
            self.fail(f"Boundary 3 intersection check failed: {e}")

    def test_23_offline_comparison_harness(self):
        """23. Offline comparative harness runs and outputs structured metrics without declaring a winner."""
        mock_records = [
            {
                "schemaVersion": 7,
                "id": f"rec_comp_{i}",
                "playedAt": f"2026-09-17T10:{10 + i:02d}:00Z",
                "lifecycleStatus": "FINALIZED",
                "coverageStatus": "COMPLETE",
                "publicIntel": {"q": 60},
                "qualities": {"gold": {"avg": 10000.0, "count": 10}},
                "settlement": {
                    "verified": True,
                    "actualTotal": float(600000.0 + (i % 3) * 50000),
                },
            }
            for i in range(8)
        ]
        res = run_probability_strategy_comparison(mock_records)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["evaluatedCount"], 8)
        self.assertFalse(res["metadata"]["performanceClaimEligible"])
        self.assertTrue(res["metadata"]["noAutomatedWinnerDeclaration"])
        comp = res["modelComparison"]
        self.assertIn("production_baseline", comp)
        self.assertIn("pr_b_red_inference", comp)
        self.assertIn("pr_c_convolution_baseline", comp)
        self.assertIn("pr_c_dafu_heuristic", comp)
        md = format_comparison_markdown(res)
        self.assertIn("Model Comparison Table", md)


if __name__ == "__main__":
    unittest.main()
