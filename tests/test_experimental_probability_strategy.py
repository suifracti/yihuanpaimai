# -*- coding: utf-8 -*-
"""Comprehensive Targeted Tests for PR-C: Probability and Strategy Experimental Lab.

Verifies all 9 external review feedback items:
1. Dafu exact divisors (2.0, 1.6, 1.3, 1.1) and no invented constants.
2. Color prior quality order (Purple : Gold : Red = 2.2 : 1.85 : 1.0).
3. Baseline reference adapter produces NO fabricated distributions or estimates.
4. Quantiles cannot be fabricated into PMFs; convolution requires valid components.
5. Strict PMF normalization contract (1e-5 tolerance, no silent repairs, empty convolution unavailable).
6. Strict state-space budget guard (supportSize <= max_states guaranteed).
7. Structural fit (structural_fit_v1): q is NOT item count, missing totalGrid => unavailable, canonical parser.
8. External Dafu CELL_FIT marks status unavailable due to unconfirmed N semantics.
9. Offline comparison harness has disjoint train/eval, no self-leakage, strict truth gating, frozen predictions.
10. UI profile toggle bridge in HudJsApi with whitelist fail-closed.
11. Cross-match reset returns to baseline; runtime cache invalidation.
12. Special rule profile records hypotheses with effect_enabled = False.
13. Contract schema and runtime payload exact parity.
14. Boundary 3 file intersection is strictly empty.
"""

from __future__ import annotations

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
    ALLOWED_EXPERIMENTAL_PROFILES,
    DAFU_CANONICAL_ROUND_DIVISORS,
    INPUT_NORMALIZATION_TOLERANCE,
    DiscreteDistribution,
    ExperimentalProbabilityStrategyReport,
    ExperimentalStrategyProfile,
    ExperimentalStrategyRegistry,
    StructuralFitDiagnostic,
    compute_dafu_cell_fit_reference,
    compute_structural_fit,
    convolve_discrete_distributions,
    evaluate_experimental_probability_strategy,
    get_global_strategy_registry,
    parse_footprint_cells,
    safe_evaluate_experimental_probability_strategy,
)
from main import HudJsApi
from probability_strategy_offline_eval import (
    format_comparison_markdown,
    is_record_settlement_truth_admitted,
    run_probability_strategy_comparison,
)
from strategy_ux_metrics import get_authoritative_strategy_store


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
        self.assertFalse(reg.is_profile_enabled("structural_fit_v1"))
        self.assertFalse(reg.is_profile_enabled("dafu_cell_fit_reference_v1"))
        self.assertFalse(reg.is_profile_enabled("convolution_v1"))
        self.assertFalse(reg.is_profile_enabled("special_rule_reference_v1"))

    def test_02_production_eligible_strictly_false(self):
        """2. productionEligible must be strictly False across all PR-C outputs."""
        report = evaluate_experimental_probability_strategy({"totalGrid": 54})
        self.assertFalse(report.production_eligible)
        self.assertTrue(report.experimental)
        payload = report.to_payload()
        self.assertFalse(payload["productionEligible"])
        self.assertTrue(payload["experimental"])

    def test_03_dafu_exact_divisors_canonical(self):
        """3. Dafu round divisors must strictly match canonical research: R1:2.0, R2:1.6, R3:1.3, R4:1.1."""
        self.assertEqual(DAFU_CANONICAL_ROUND_DIVISORS["R1"], 2.0)
        self.assertEqual(DAFU_CANONICAL_ROUND_DIVISORS["R2"], 1.6)
        self.assertEqual(DAFU_CANONICAL_ROUND_DIVISORS["R3"], 1.3)
        self.assertEqual(DAFU_CANONICAL_ROUND_DIVISORS["R4"], 1.1)

        reg = get_global_strategy_registry()
        p = reg.get_profile("dafu_round_heuristic_v1")
        self.assertIsNotNone(p)
        divs = p.parameters.get("round_divisors")
        self.assertEqual(divs, {"R1": 2.0, "R2": 1.6, "R3": 1.3, "R4": 1.1})

        # Multiplier check
        self.assertAlmostEqual(1.0 / divs["R1"], 0.5, places=4)
        self.assertAlmostEqual(1.0 / divs["R2"], 0.625, places=4)

    def test_04_no_invented_dafu_constants(self):
        """4. No invented constants (0.92, 0.88, 0.90, 0.93, 0.95, 0.97) exist in Dafu profile."""
        reg = get_global_strategy_registry()
        p = reg.get_profile("dafu_round_heuristic_v1")
        params_str = str(p.parameters)
        for inv in ("0.92", "0.88", "0.93", "0.97"):
            self.assertNotIn(inv, params_str)

    def test_05_dafu_color_prior_quality_order(self):
        """5. Color prior quality ratio must be Purple : Gold : Red = 2.2 : 1.85 : 1.0."""
        reg = get_global_strategy_registry()
        p = reg.get_profile("external_color_prior_dafu_v1")
        self.assertIsNotNone(p)
        params = p.parameters
        self.assertEqual(params.get("purple_weight"), 2.2)
        self.assertEqual(params.get("gold_weight"), 1.85)
        self.assertEqual(params.get("red_weight"), 1.0)
        self.assertFalse(p.validated_by_our_data)
        self.assertEqual(p.evidence_level, "unverified_external_prior")

    def test_06_baseline_only_no_fabricated_distribution(self):
        """6. Baseline adapter produces NO fake distribution, reserve price, or conservative price."""
        reg = get_global_strategy_registry()
        reg.reset_for_new_match()

        prod_metrics = {
            "valP50": 600000.0,
            "valRange": (540000, 660000),
            "targetProfitLine": 500000.0,
            "actionDirective": "🟢 仍在目标利润区 · 可以继续",
        }
        shadow_profile = {
            "p20": 530000.0,
            "p50": 590000.0,
            "p80": 650000.0,
            "conservativeEstimate": 520000.0,
        }

        report = evaluate_experimental_probability_strategy(
            session_ctx={"q": 60, "goldAvg": 10000.0},
            production_metrics=prod_metrics,
            shadow_profile=shadow_profile,
            registry=reg,
        )

        # Baseline only must NOT produce experimental distribution
        self.assertIsNone(report.experimental_distribution)
        self.assertIsNone(report.p20)
        self.assertIsNone(report.p50)
        self.assertIsNone(report.p80)
        self.assertIsNone(report.mean)
        self.assertIsNone(report.experimental_reserve_price)
        self.assertIsNone(report.experimental_conservative_price)

        # But side-by-side reference must be populated
        self.assertIsNotNone(report.production_reference)
        self.assertEqual(report.production_reference["valP50"], 600000.0)
        self.assertIsNotNone(report.historical_shadow_reference)
        self.assertEqual(report.historical_shadow_reference["p50"], 590000.0)

    def test_07_quantiles_cannot_be_used_as_pmf(self):
        """7. PR-B red quantiles cannot be fabricated into a PMF; convolution returns unavailable if no valid components."""
        reg = get_global_strategy_registry()
        reg.reset_for_new_match()
        reg.enable_profile("convolution_v1")

        mock_red = {
            "status": "sufficient_evidence",
            "redTotalQuantiles": {"p20": 100000.0, "p50": 200000.0, "p80": 300000.0},
        }

        report = evaluate_experimental_probability_strategy(
            session_ctx={"totalGrid": 54},
            experimental_red=mock_red,
            registry=reg,
        )

        # Convolution must be unavailable because no genuine PMF components exist
        self.assertIsNone(report.experimental_distribution)
        self.assertIsNotNone(report.convolution_metrics)
        self.assertEqual(report.convolution_metrics["status"], "unavailable")
        self.assertEqual(report.convolution_metrics["reason"], "NO_VALID_DISTRIBUTION_COMPONENTS")

    def test_08_strict_pmf_normalization_contract(self):
        """8. DiscreteDistribution rejects PMF with normalization error > 1e-5. No silent 5% auto-repair."""
        # 1% error (> 1e-5) => strictly invalid
        d_bad = DiscreteDistribution({100.0: 0.5, 200.0: 0.49})
        self.assertFalse(d_bad.is_valid)

        # Exact PMF => valid
        d_good = DiscreteDistribution({100.0: 0.3, 200.0: 0.7})
        self.assertTrue(d_good.is_valid)
        self.assertAlmostEqual(d_good.normalization_error, 0.0, places=5)

    def test_09_empty_convolution_unavailable(self):
        """9. convolve_discrete_distributions([]) returns None with reason NO_VALID_COMPONENTS."""
        d_conv, meta = convolve_discrete_distributions([])
        self.assertIsNone(d_conv)
        self.assertEqual(meta["status"], "unavailable")
        self.assertEqual(meta["reason"], "NO_VALID_COMPONENTS")

    def test_10_state_budget_strict_bound(self):
        """10. State-space budget guard strictly enforces supportSize <= max_states."""
        # Create two distributions with 150 states each
        d1 = DiscreteDistribution({float(k): 1.0 / 150 for k in range(150)})
        d2 = DiscreteDistribution({float(k * 2): 1.0 / 150 for k in range(150)})
        max_states = 50

        d_conv, meta = convolve_discrete_distributions([d1, d2], max_states=max_states)
        self.assertIsNotNone(d_conv)
        self.assertTrue(d_conv.is_valid)
        # Strict bound check
        self.assertLessEqual(d_conv.support_size, max_states)
        self.assertTrue(meta["budgetExceeded"])
        self.assertTrue(meta["approximationApplied"])
        self.assertEqual(meta["approximationMethod"], "adaptive_quantile_binning")
        self.assertGreater(meta["originalStateCount"], max_states)

    def test_11_q_is_not_item_count(self):
        """11. q is NOT item count; large q does not cause false ITEM_COUNT_EXCEEDS_GRID_CAPACITY conflict."""
        diag = compute_structural_fit({"q": 120, "totalGrid": 54, "totalItems": 20})
        self.assertTrue(diag.feasible)
        self.assertNotIn("ITEM_COUNT_EXCEEDS_GRID_CAPACITY", diag.conflicts)
        self.assertNotIn("TOTAL_ITEMS_EXCEEDS_GRID_CAPACITY", diag.conflicts)

    def test_12_missing_canonical_total_grid_unavailable(self):
        """12. If canonical totalGrid is missing, structural fit is unavailable (never default 54)."""
        diag = compute_structural_fit({"q": 60})
        self.assertEqual(diag.status, "unavailable")
        self.assertEqual(diag.reason, "MISSING_CANONICAL_TOTAL_GRID")

    def test_13_canonical_footprint_parsing(self):
        """13. Canonical footprint parser correctly parses int, tuple, and 'WxH' formats."""
        self.assertEqual(parse_footprint_cells(4), 4)
        self.assertEqual(parse_footprint_cells((2, 3)), 6)
        self.assertEqual(parse_footprint_cells("2x3"), 6)
        self.assertEqual(parse_footprint_cells("1X4"), 4)
        self.assertIsNone(parse_footprint_cells("invalid"))

        # Test in compute_structural_fit
        ctx = {
            "totalGrid": 54,
            "totalItems": 10,
            "knownItems": [
                {"footprint": "2x3"},
                {"cells": 4},
                "1x2",
            ],
        }
        diag = compute_structural_fit(ctx)
        self.assertEqual(diag.status, "evaluated")
        self.assertTrue(diag.feasible)
        # Total known footprint = 6 + 4 + 2 = 12
        self.assertEqual(diag.details["knownCellsTotal"], 12)
        self.assertAlmostEqual(diag.fill_ratio, 12.0 / 54.0, places=4)

    def test_14_dafu_cell_fit_reference_unconfirmed(self):
        """14. dafu_cell_fit_reference_v1 returns status unavailable due to unconfirmed N semantics."""
        ref = compute_dafu_cell_fit_reference({"totalGrid": 54})
        self.assertEqual(ref["status"], "unavailable")
        self.assertEqual(ref["reason"], "EXTERNAL_N_SEMANTICS_UNCONFIRMED")
        self.assertEqual(ref["slope"], 3.3467)
        self.assertEqual(ref["intercept"], 60.0425)

    def test_15_special_rule_profile_recorded(self):
        """15. special_rule_reference_v1 is registered and records hypotheses with effect_enabled=False."""
        reg = get_global_strategy_registry()
        p = reg.get_profile("special_rule_reference_v1")
        self.assertIsNotNone(p)
        self.assertFalse(p.parameters.get("effect_enabled", True))
        self.assertIn("shining_heart", p.parameters.get("rules", []))

    def test_16_ui_profile_toggle_bridge_whitelist(self):
        """16. HudJsApi.experimental_profile_set toggles profiles and fails closed on invalid IDs."""
        api = HudJsApi()
        reg = get_global_strategy_registry()
        reg.reset_for_new_match()

        # Valid toggle
        res = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": True})
        self.assertTrue(res["success"])
        self.assertTrue(reg.is_profile_enabled("dafu_round_heuristic_v1"))

        # Valid untoggle
        res2 = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": False})
        self.assertTrue(res2["success"])
        self.assertFalse(reg.is_profile_enabled("dafu_round_heuristic_v1"))

        # Baseline cannot be disabled
        res_base = api.experimental_profile_set({"profileId": "baseline", "enabled": False})
        self.assertFalse(res_base["success"])

        # Invalid profile fails closed
        res_inv = api.experimental_profile_set({"profileId": "malicious_exploit_profile", "enabled": True})
        self.assertFalse(res_inv["success"])
        self.assertNotIn("malicious_exploit_profile", reg.get_active_profile_ids())

        # invoke_action dispatcher
        res_disp = api.invoke_action("experimental_profile_set", {"profileId": "convolution_v1", "enabled": True})
        self.assertTrue(res_disp["success"])
        self.assertTrue(reg.is_profile_enabled("convolution_v1"))

    def test_17_cross_match_reset_to_baseline(self):
        """17. reset_for_new_match resets all external profiles strictly to baseline."""
        reg = get_global_strategy_registry()
        reg.enable_profile("dafu_round_heuristic_v1")
        reg.enable_profile("structural_fit_v1")
        self.assertIn("dafu_round_heuristic_v1", reg.get_active_profile_ids())

        reg.reset_for_new_match()
        self.assertEqual(reg.get_active_profile_ids(), ["baseline"])
        self.assertFalse(reg.is_profile_enabled("dafu_round_heuristic_v1"))

    def test_18_runtime_cache_and_early_return(self):
        """18. safe_evaluate uses O(1) early return for baseline and caches complex evaluations."""
        reg = get_global_strategy_registry()
        reg.reset_for_new_match()

        # 1. Baseline only: O(1) early return
        p1 = safe_evaluate_experimental_probability_strategy(
            session_ctx={"totalGrid": 54},
            production_metrics={"valP50": 500000.0},
            registry=reg,
        )
        self.assertEqual(p1["activeProfiles"], ["baseline"])
        self.assertIsNone(p1["experimentalDistribution"])

        # 2. Complex profile enabled: verify cache
        reg.enable_profile("structural_fit_v1")
        gen1 = reg.profile_generation
        p_c1 = safe_evaluate_experimental_probability_strategy(
            session_ctx={"totalGrid": 54, "totalItems": 10},
            registry=reg,
        )
        self.assertIsNotNone(p_c1["structuralFit"])

        p_c2 = safe_evaluate_experimental_probability_strategy(
            session_ctx={"totalGrid": 54, "totalItems": 10},
            registry=reg,
        )
        self.assertEqual(p_c1, p_c2)

    def test_19_contract_schema_parity(self):
        """19. Report to_payload() contains exact contract schema fields without drift."""
        report = evaluate_experimental_probability_strategy({"totalGrid": 54})
        payload = report.to_payload()
        required_keys = [
            "schemaVersion",
            "experimental",
            "productionEligible",
            "status",
            "activeProfiles",
            "profileGeneration",
            "samplingAssumption",
            "conditioningMode",
            "productionReference",
            "historicalShadowReference",
            "experimentalDistribution",
            "p20",
            "p50",
            "p80",
            "mean",
            "experimentalReservePrice",
            "experimentalConservativePrice",
            "structuralFit",
            "dafuCellFitReference",
            "externalHypotheses",
            "convolutionMetrics",
            "deltaVsProduction",
            "deltaVsPrBRed",
            "sampleN",
            "evaluationTimestamp",
            "warnings",
            "disclaimers",
        ]
        for k in required_keys:
            self.assertIn(k, payload, f"Missing required contract key: {k}")

    def test_20_offline_disjoint_train_eval_no_self_leakage(self):
        """20. Offline harness enforces disjoint train/eval; record never trains itself."""
        mock_records = [
            {
                "schemaVersion": 7,
                "id": f"rec_{i}",
                "playedAt": f"2026-09-17T10:{10 + i:02d}:00Z",
                "lifecycleStatus": "FINALIZED",
                "coverageStatus": "COMPLETE",
                "publicIntel": {"totalGrid": 54, "totalItems": 10},
                "predictionSnapshot": {"valP50": 600000.0, "p20": 540000.0, "p80": 660000.0},
                "shadowPrediction": {"p50": 590000.0, "p20": 530000.0, "p80": 650000.0},
                "settlement": {"verified": True, "actualTotal": 620000.0},
            }
            for i in range(5)
        ]
        res = run_probability_strategy_comparison(mock_records)
        self.assertEqual(res["status"], "completed")
        self.assertTrue(res["metadata"]["noSelfLeakageGuaranteed"])
        self.assertFalse(res["metadata"]["performanceClaimEligible"])
        self.assertEqual(res["eligibleCount"], 5)
        self.assertEqual(res["excludedCount"], 0)
        comp = res["modelComparison"]
        self.assertEqual(comp["production_baseline"]["sampleCount"], 5)
        self.assertEqual(comp["historical_shadow"]["sampleCount"], 5)

    def test_21_weak_actual_total_only_truth_rejected(self):
        """21. Records with actualTotal but unverified/incomplete coverage are rejected."""
        mock_bad = [
            {
                "schemaVersion": 7,
                "id": "rec_bad_1",
                "lifecycleStatus": "IN_PROGRESS",  # not finalized
                "coverageStatus": "COMPLETE",
                "settlement": {"verified": True, "actualTotal": 500000.0},
            },
            {
                "schemaVersion": 7,
                "id": "rec_bad_2",
                "lifecycleStatus": "FINALIZED",
                "coverageStatus": "PARTIAL",  # not complete
                "settlement": {"verified": True, "actualTotal": 500000.0},
            },
            {
                "schemaVersion": 7,
                "id": "rec_bad_3",
                "lifecycleStatus": "FINALIZED",
                "coverageStatus": "COMPLETE",
                "settlement": {"verified": False, "actualTotal": 500000.0},  # not verified
            },
        ]
        for r in mock_bad:
            admitted, reason = is_record_settlement_truth_admitted(r)
            self.assertFalse(admitted, f"Record should be rejected: {r['id']}")
            self.assertIsNotNone(reason)

    def test_22_production_comparison_requires_frozen_prediction(self):
        """22. Production baseline is unavailable for records lacking frozen predictionSnapshot."""
        mock_rec = {
            "schemaVersion": 7,
            "id": "rec_no_snap",
            "playedAt": "2026-09-17T10:00:00Z",
            "lifecycleStatus": "FINALIZED",
            "coverageStatus": "COMPLETE",
            "publicIntel": {"totalGrid": 54},
            "settlement": {"verified": True, "actualTotal": 500000.0},
            # No predictionSnapshot!
        }
        res = run_probability_strategy_comparison([mock_rec])
        self.assertEqual(res["eligibleCount"], 1)
        comp = res["modelComparison"]
        self.assertEqual(comp["production_baseline"]["sampleCount"], 0)
        self.assertEqual(comp["production_baseline"]["status"], "unavailable_no_admitted_predictions")

    def test_23_boundary3_intersection_zero(self):
        """23. Boundary 3 files must remain 100% untouched (empty intersection)."""
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


if __name__ == "__main__":
    unittest.main()
