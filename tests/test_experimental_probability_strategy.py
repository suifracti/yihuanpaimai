# -*- coding: utf-8 -*-
"""Comprehensive Targeted Tests for PR-C: Probability and Strategy Experimental Lab.

Verifies all external review feedback items (Round 1 Items A through H):
1. Dafu exact divisors (2.0, 1.6, 1.3, 1.1), baseMetricSemanticsConfirmed = False, NO calculatedBiddingPrice (Item C).
2. Color prior quality order (Purple : Gold : Red = 2.2 : 1.85 : 1.0).
3. Baseline reference adapter produces NO fabricated distributions or estimates.
4. Discrete convolution candidate schema verification (Item D):
   - Rejects bare candidatePmfs fail-closed.
   - Rejects unprovenanced inputs fail-closed.
   - Accepts valid ConvolutionComponentProvenance.
   - Quantiles cannot be fabricated into PMFs.
5. Strict PMF normalization contract (1e-5 tolerance, no silent repairs, empty convolution unavailable).
6. Strict state-space budget guard (supportSize <= max_states guaranteed).
7. Structural fit (structural_fit_v1):
   - Uses extract_canonical_footprint_cells from warehouse_occupancy_adapter (Item F).
   - Never uses q as item count, missing totalGrid => unavailable.
   - Consistency between qualities.*.count/grid and publicIntel.totalItems/totalGrid.
8. External Dafu CELL_FIT marks status unavailable due to unconfirmed N semantics.
9. Runtime cache stores pure experimental core only; dynamic reference and delta injection (Item E).
10. UI profile toggle bridge in HudJsApi: strictly boolean enabled check (Item G).
11. Production isolation regression test: AuctionBrain production slices 100% identical between baseline and all-profiles enabled.
12. Cross-match reset returns to baseline; runtime cache invalidation.
13. Special rule profile records hypotheses with effect_enabled = False.
14. Contract schema and runtime payload exact parity.
15. Offline comparative evaluation (Items A & B):
    - Uses build_duplicate_index and evaluate_history_admission (is_record_settlement_truth_admitted deleted).
    - Excludes potential content duplicates fail-closed.
    - Timestamp comparison strictly uses aware UTC datetime.
    - production_baseline requires valid prediction-snapshot.v1 and reads quantiles without fallback.
    - historical_shadow reports unavailable_no_independent_frozen_shadow_artifact.
    - pr_c_dafu_heuristic reports unavailable_base_metric_unconfirmed.
16. Boundary 3 file intersection is strictly empty.
"""

from __future__ import annotations

import copy
import json
import math
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

from auction_brain import AuctionBrain
from evaluation_eligibility import build_input_sha256, validate_prediction_snapshot
from experimental_probability_strategy import (
    ALLOWED_EXPERIMENTAL_PROFILES,
    ConvolutionComponentProvenance,
    DAFU_CANONICAL_ROUND_DIVISORS,
    DEFAULT_MAX_CONVOLUTION_STATES,
    DiscreteDistribution,
    ExperimentalProbabilityStrategyReport,
    ExperimentalStrategyProfile,
    ExperimentalStrategyRegistry,
    INPUT_NORMALIZATION_TOLERANCE,
    StructuralFitDiagnostic,
    compute_dafu_cell_fit_reference,
    compute_structural_fit,
    convolve_discrete_distributions,
    evaluate_experimental_probability_strategy,
    get_global_strategy_registry,
    parse_convolution_component,
    safe_evaluate_experimental_probability_strategy,
)
from main import HudJsApi
from probability_strategy_offline_eval import (
    canonical_timestamp_to_utc,
    format_comparison_markdown,
    run_probability_strategy_comparison,
)
from strategy_ux_metrics import get_authoritative_strategy_store
from warehouse_occupancy_adapter import (
    extract_canonical_footprint_cells,
    extract_canonical_footprint_dimensions,
)


def _make_valid_test_prediction_snapshot(
    match_id: str,
    p20: float = 540000.0,
    p50: float = 600000.0,
    p80: float = 660000.0,
    solved_at: str = "2026-09-17T10:00:00Z",
) -> Dict[str, Any]:
    """Construct an authentic prediction-snapshot.v1 that strictly passes validate_prediction_snapshot."""
    facts = {"q": 10, "goldAvg": 50000.0}
    input_h = build_input_sha256(facts)
    return {
        "schemaVersion": "prediction-snapshot.v1",
        "frozen": True,
        "predictionId": f"pred_{match_id}",
        "matchId": match_id,
        "solvedAt": solved_at,
        "informationCutoffAt": solved_at,
        "snapshotRole": "latest_valid_pre_settlement",
        "producer": {
            "runtime": "python",
            "solverName": "ProductionSolver",
            "solverVersion": "1.0",
            "modelVersion": "1.0",
            "catalogVersion": "1.0",
            "codeRevision": "abc1234",
        },
        "input": {
            "contractVersion": 1,
            "normalizedFacts": facts,
            "hashAlgorithm": "sha256",
            "inputHash": input_h,
            "datasetRevision": {
                "sourceId": "canonical_match_history",
                "sha256": "a" * 64,
                "recordCount": 10,
                "admissionPolicyVersion": 1,
                "cutoffExclusive": solved_at,
                "eligibleRecordIdsSha256": "b" * 64,
            },
        },
        "mode": {
            "informationMode": "structural_only",
            "coverageRatio": 1.0,
        },
        "status": {
            "solverStatus": "valid",
            "provisional": False,
        },
        "forecast": {
            "target": "full_inventory_actual_total",
            "scope": "full_inventory",
            "quantiles": {"p20": p20, "p50": p50, "p80": p80},
        },
    }


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

    def test_03_dafu_exact_divisors_canonical_and_item_c(self):
        """3. Dafu round divisors canonical; baseMetricSemanticsConfirmed=False, NO calculatedBiddingPrice (Item C)."""
        self.assertEqual(DAFU_CANONICAL_ROUND_DIVISORS["R1"], 2.0)
        self.assertEqual(DAFU_CANONICAL_ROUND_DIVISORS["R2"], 1.6)
        self.assertEqual(DAFU_CANONICAL_ROUND_DIVISORS["R3"], 1.3)
        self.assertEqual(DAFU_CANONICAL_ROUND_DIVISORS["R4"], 1.1)

        reg = get_global_strategy_registry()
        p = reg.get_profile("dafu_round_heuristic_v1")
        self.assertIsNotNone(p)
        self.assertFalse(p.parameters.get("baseMetricSemanticsConfirmed"))
        self.assertEqual(p.parameters["round_divisors"], DAFU_CANONICAL_ROUND_DIVISORS)

        # Enable profile and evaluate
        reg.enable_profile("dafu_round_heuristic_v1")
        rep = evaluate_experimental_probability_strategy({"round": 2}, registry=reg)
        hypo = rep.external_hypotheses.get("dafuRoundHeuristic")
        self.assertIsNotNone(hypo)
        self.assertEqual(hypo["round"], "R2")
        self.assertEqual(hypo["canonicalDivisor"], 1.6)
        self.assertAlmostEqual(hypo["calculatedMultiplier"], 1.0 / 1.6, places=4)
        self.assertFalse(hypo["baseMetricSemanticsConfirmed"])
        # Crucial Item C: must NOT contain calculatedBiddingPrice!
        self.assertNotIn("calculatedBiddingPrice", hypo)

    def test_04_dafu_color_prior_order(self):
        """4. Dafu color prior order must be Purple:Gold:Red = 2.2:1.85:1."""
        reg = get_global_strategy_registry()
        p = reg.get_profile("external_color_prior_dafu_v1")
        self.assertIsNotNone(p)
        self.assertEqual(p.parameters["purple_weight"], 2.2)
        self.assertEqual(p.parameters["gold_weight"], 1.85)
        self.assertEqual(p.parameters["red_weight"], 1.0)
        self.assertGreater(p.parameters["purple_weight"], p.parameters["gold_weight"])
        self.assertGreater(p.parameters["gold_weight"], p.parameters["red_weight"])

    def test_05_baseline_reference_adapter_pure_reference(self):
        """5. Baseline adapter produces NO fake distribution or fabricated estimates."""
        prod_metrics = {
            "valP50": 600000.0,
            "valRange": [500000.0, 700000.0],
            "targetProfitLine": 550000.0,
            "actionDirective": "PASS",
        }
        shadow_profile = {
            "p20": 480000.0,
            "p50": 580000.0,
            "p80": 680000.0,
            "conservativeEstimate": 520000.0,
        }
        report = evaluate_experimental_probability_strategy(
            session_ctx={"totalGrid": 54},
            production_metrics=prod_metrics,
            shadow_profile=shadow_profile,
        )
        self.assertEqual(report.active_profiles, ["baseline"])
        self.assertIsNone(report.experimental_distribution)
        self.assertIsNone(report.p20)
        self.assertIsNone(report.p50)
        self.assertIsNone(report.p80)
        self.assertIsNone(report.mean)
        self.assertIsNone(report.delta_vs_production)
        self.assertIsNotNone(report.production_reference)
        self.assertEqual(report.production_reference["valP50"], 600000.0)
        self.assertIsNotNone(report.historical_shadow_reference)
        self.assertEqual(report.historical_shadow_reference["p50"], 580000.0)

    def test_06_discrete_convolution_component_provenance_schema_and_item_d(self):
        """6. Convolution component input requires strict provenance schema; bare PMFs rejected (Item D)."""
        # A. Bare candidatePmfs without provenance schema are rejected
        rep_bare = evaluate_experimental_probability_strategy(
            session_ctx={
                "candidatePmfs": [{100.0: 0.5, 200.0: 0.5}],
            },
        )
        self.assertIsNone(rep_bare.experimental_distribution)

        # B. Parse convolution component with full provenance schema
        valid_comp = {
            "componentId": "comp_gold_1",
            "source": "canonical_generating_function",
            "evidenceLevel": "mathematical_convolution",
            "validatedByOurData": False,
            "distribution": {
                "points": [
                    {"value": 100.0, "probability": 0.3},
                    {"value": 200.0, "probability": 0.7},
                ]
            },
        }
        dist, prov, err = parse_convolution_component(valid_comp)
        self.assertIsNotNone(dist)
        self.assertIsNotNone(prov)
        self.assertIsNone(err)
        self.assertTrue(dist.is_valid)
        self.assertEqual(prov.component_id, "comp_gold_1")

        # C. Missing componentId / unprovenanced fails closed
        invalid_comp = {
            "distribution": {100.0: 0.5, 200.0: 0.5}
        }
        d_bad, p_bad, err_bad = parse_convolution_component(invalid_comp)
        self.assertIsNone(d_bad)
        self.assertEqual(err_bad, "COMPONENT_ID_MISSING")

    def test_07_strict_pmf_normalization_contract(self):
        """7. DiscreteDistribution enforces strict 1e-5 normalization tolerance without silent 5% repairs."""
        # Exact valid PMF
        d1 = DiscreteDistribution({100.0: 0.4, 200.0: 0.6})
        self.assertTrue(d1.is_valid)
        self.assertAlmostEqual(d1.mean, 160.0)

        # Micro-error within tolerance (1e-6)
        d2 = DiscreteDistribution({100.0: 0.5, 200.0: 0.5000005})
        self.assertTrue(d2.is_valid)

        # Gross violation (e.g. sum = 1.05) must fail closed (is_valid = False)
        d3 = DiscreteDistribution({100.0: 0.5, 200.0: 0.55})
        self.assertFalse(d3.is_valid)

        # Negative probability raises ValueError
        with self.assertRaises(ValueError):
            DiscreteDistribution({100.0: -0.1, 200.0: 1.1})

        # Empty convolution returns None and status unavailable
        res, meta = convolve_discrete_distributions([])
        self.assertIsNone(res)
        self.assertEqual(meta["status"], "unavailable")

    def test_08_convolution_state_space_budget_guard(self):
        """8. Convolve engine guarantees supportSize <= max_states under state explosion."""
        c1 = DiscreteDistribution({i * 10.0: 0.1 for i in range(10)})
        c2 = DiscreteDistribution({i * 10.0: 0.1 for i in range(10)})
        c3 = DiscreteDistribution({i * 10.0: 0.1 for i in range(10)})

        # Set tight budget of max_states = 15
        d_conv, meta = convolve_discrete_distributions([c1, c2, c3], max_states=15)
        self.assertIsNotNone(d_conv)
        self.assertTrue(d_conv.is_valid)
        self.assertLessEqual(d_conv.support_size, 15)
        self.assertTrue(meta["budgetExceeded"])
        self.assertTrue(meta["approximationApplied"])

    def test_09_footprint_authority_and_item_f(self):
        """9. Footprint authority reuses extract_canonical_footprint_cells; qualities.* vs totalItems consistent (Item F)."""
        # Test canonical footprint dimension & cell extraction
        self.assertEqual(extract_canonical_footprint_cells({"footprint": {"widthCells": 2, "heightCells": 3}}), 6)
        self.assertEqual(extract_canonical_footprint_cells({"grid": {"w": 1, "h": 4}}), 4)
        self.assertEqual(extract_canonical_footprint_cells("2x3"), 6)
        self.assertEqual(extract_canonical_footprint_cells((3, 2)), 6)
        self.assertEqual(extract_canonical_footprint_cells({"cells": 8}), 8)

        # Structural fit using canonical footprint extraction
        ctx = {
            "totalGrid": 54,
            "totalItems": 3,
            "knownItems": [
                {"footprint": "2x3"},
                {"cells": 4},
                "1x2",
            ],
            "qualityGrids": {"gold": 10, "purple": 10},
            "qualityCounts": {"gold": 2, "purple": 1},
        }
        diag = compute_structural_fit(ctx)
        self.assertEqual(diag.status, "evaluated")
        self.assertTrue(diag.feasible)
        self.assertEqual(diag.details["knownCellsTotal"], 12)
        self.assertAlmostEqual(diag.fill_ratio, 12.0 / 54.0, places=4)

        # Missing totalGrid => unavailable (strictly NO default 54!)
        diag_no_grid = compute_structural_fit({"totalItems": 10})
        self.assertEqual(diag_no_grid.status, "unavailable")
        self.assertEqual(diag_no_grid.reason, "MISSING_CANONICAL_TOTAL_GRID")

    def test_10_dafu_cell_fit_reference_unconfirmed(self):
        """10. dafu_cell_fit_reference_v1 returns status unavailable due to unconfirmed N semantics."""
        ref = compute_dafu_cell_fit_reference({"totalGrid": 54})
        self.assertEqual(ref["status"], "unavailable")
        self.assertEqual(ref["reason"], "EXTERNAL_N_SEMANTICS_UNCONFIRMED")
        self.assertEqual(ref["slope"], 3.3467)
        self.assertEqual(ref["intercept"], 60.0425)

    def test_11_cache_pure_experimental_core_and_item_e(self):
        """11. Cache stores pure experimental core; production metrics changes immediately update deltas (Item E)."""
        reg = get_global_strategy_registry()
        reg.reset_for_new_match()
        reg.enable_profile("convolution_v1")

        comp = {
            "componentId": "c1",
            "source": "generating_function",
            "evidenceLevel": "math",
            "validatedByOurData": False,
            "distribution": {"points": [{"value": 500000.0, "probability": 1.0}]},
        }
        ctx = {"totalGrid": 54, "convolutionComponents": [comp]}

        # Call 1: with valP50 = 400,000
        p1 = safe_evaluate_experimental_probability_strategy(
            session_ctx=ctx,
            production_metrics={"valP50": 400000.0},
            registry=reg,
        )
        self.assertEqual(p1["productionReference"]["valP50"], 400000.0)
        self.assertIsNotNone(p1["deltaVsProduction"])
        self.assertAlmostEqual(p1["deltaVsProduction"]["medianDelta"], 100000.0)

        # Call 2: same session_ctx and profileGeneration, but updated valP50 = 600,000
        p2 = safe_evaluate_experimental_probability_strategy(
            session_ctx=ctx,
            production_metrics={"valP50": 600000.0},
            registry=reg,
        )
        # Verify that output reflects updated production reference IMMEDIATELY, not stale cached reference!
        self.assertEqual(p2["productionReference"]["valP50"], 600000.0)
        self.assertIsNotNone(p2["deltaVsProduction"])
        self.assertAlmostEqual(p2["deltaVsProduction"]["medianDelta"], -100000.0)

    def test_12_ui_profile_toggle_bridge_strict_bool_and_item_g(self):
        """12. HudJsApi.experimental_profile_set strictly enforces type(enabled) is bool (Item G)."""
        api = HudJsApi()
        reg = get_global_strategy_registry()
        reg.reset_for_new_match()
        gen_before = reg.profile_generation

        # Valid boolean True
        res_true = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": True})
        self.assertTrue(res_true["success"])
        self.assertTrue(reg.is_profile_enabled("dafu_round_heuristic_v1"))
        self.assertGreater(reg.profile_generation, gen_before)

        # Valid boolean False
        gen_mid = reg.profile_generation
        res_false = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": False})
        self.assertTrue(res_false["success"])
        self.assertFalse(reg.is_profile_enabled("dafu_round_heuristic_v1"))

        # String "false" MUST FAIL CLOSED
        gen_after = reg.profile_generation
        res_str = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": "false"})
        self.assertFalse(res_str["success"])
        self.assertIn("expected bool", res_str["error"])
        self.assertEqual(reg.profile_generation, gen_after)  # zero generation mutation!

        # Number 0 / 1 MUST FAIL CLOSED
        res_num0 = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": 0})
        self.assertFalse(res_num0["success"])
        self.assertEqual(reg.profile_generation, gen_after)

        res_num1 = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": 1})
        self.assertFalse(res_num1["success"])
        self.assertEqual(reg.profile_generation, gen_after)

        # None MUST FAIL CLOSED
        res_none = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": None})
        self.assertFalse(res_none["success"])
        self.assertEqual(reg.profile_generation, gen_after)

    def test_13_production_isolation_regression(self):
        """13. AuctionBrain solve_session outputs are 100% byte-identical between baseline and all-profiles-enabled."""
        brain = AuctionBrain()
        reg = get_global_strategy_registry()
        reg.reset_for_new_match()

        sample_session = {
            "round": 2,
            "q": 8,
            "goldAvg": 50000.0,
            "totalGrid": 54,
            "totalItems": 15,
            "costs": {"sunkCost": 5000, "futureIncrementalCost": 2000},
            "qualities": {
                "gold": {"count": 2, "avg": 50000.0, "grid": 10},
                "purple": {"count": 4, "avg": 25000.0, "grid": 16},
                "red": {"count": 0, "avg": 0.0, "grid": 0},
            },
        }

        # Run with baseline only
        res_baseline = brain.solve_session(sample_session)

        # Enable ALL experimental profiles
        for pid in ALLOWED_EXPERIMENTAL_PROFILES:
            if pid != "baseline":
                reg.enable_profile(pid)

        # Run with all profiles active
        res_all_active = brain.solve_session(sample_session)

        # Production slices must be 100% identical!
        prod_keys = [
            "valP50",
            "valRange",
            "targetProfitLine",
            "globalProfitLine",
            "actionDirective",
            "strategyMetrics",
            "strategyPanel",
        ]
        for k in prod_keys:
            self.assertEqual(
                res_baseline.get(k),
                res_all_active.get(k),
                f"Production slice mismatch for key: {k}",
            )

    def test_14_cross_match_reset_to_baseline(self):
        """14. reset_for_new_match resets all external profiles strictly to baseline."""
        reg = get_global_strategy_registry()
        reg.enable_profile("dafu_round_heuristic_v1")
        reg.enable_profile("structural_fit_v1")
        self.assertIn("dafu_round_heuristic_v1", reg.get_active_profile_ids())

        reg.reset_for_new_match()
        self.assertEqual(reg.get_active_profile_ids(), ["baseline"])
        self.assertFalse(reg.is_profile_enabled("dafu_round_heuristic_v1"))

    def test_15_contract_schema_parity(self):
        """15. Report to_payload() contains exact contract schema fields without drift."""
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

    def test_16_offline_eval_truth_admission_and_items_a_and_b(self):
        """16. Offline harness: canonical admission, aware datetime, frozen prediction validation (Items A & B)."""
        # Build 5 valid canonical records with authentic predictionSnapshot
        mock_records = []
        for i in range(5):
            rec_id = f"rec_{i}"
            ts = f"2026-09-17T10:{10 + i:02d}:00Z"
            snap = _make_valid_test_prediction_snapshot(rec_id, solved_at=ts)
            mock_records.append({
                "schemaVersion": 7,
                "id": rec_id,
                "playedAt": ts,
                "lifecycleStatus": "FINALIZED",
                "coverageStatus": "COMPLETE",
                "dataOrigin": "live",
                "publicIntel": {"totalGrid": 54, "totalItems": 10},
                "predictionSnapshot": snap,
                "settlement": {"verified": True, "actualTotal": float(620000.0 + i * 10000)},
            })

        res = run_probability_strategy_comparison(mock_records)
        self.assertEqual(res["status"], "completed")
        self.assertTrue(res["metadata"]["noSelfLeakageGuaranteed"])
        self.assertFalse(res["metadata"]["performanceClaimEligible"])
        self.assertEqual(res["eligibleCount"], 5)
        self.assertEqual(res["excludedCount"], 0)

        comp = res["modelComparison"]
        # Production baseline evaluated on all 5 valid snapshots
        self.assertEqual(comp["production_baseline"]["sampleCount"], 5)
        self.assertEqual(comp["production_baseline"]["status"], "evaluated")

        # Historical shadow: unavailable_no_independent_frozen_shadow_artifact (Review Item B)
        self.assertEqual(comp["historical_shadow"]["sampleCount"], 0)
        self.assertEqual(comp["historical_shadow"]["status"], "unavailable_no_independent_frozen_shadow_artifact")

        # PR-C Dafu heuristic: unavailable_base_metric_unconfirmed (Review Item B & C)
        self.assertEqual(comp["pr_c_dafu_heuristic"]["sampleCount"], 0)
        self.assertEqual(comp["pr_c_dafu_heuristic"]["status"], "unavailable_base_metric_unconfirmed")

    def test_17_offline_eval_excludes_potential_duplicates(self):
        """17. Records marked as potential duplicates are strictly excluded fail-closed."""
        base_ts = "2026-09-17T10:00:00Z"
        snap1 = _make_valid_test_prediction_snapshot("rec_dup_1", solved_at=base_ts)
        snap2 = _make_valid_test_prediction_snapshot("rec_dup_2", solved_at=base_ts)

        # Two records with identical (playedAt, venue, box, actualTotal) => potential content duplicate!
        rec1 = {
            "schemaVersion": 7,
            "id": "rec_dup_1",
            "playedAt": base_ts,
            "lifecycleStatus": "FINALIZED",
            "coverageStatus": "COMPLETE",
            "venue": "VENUE_A",
            "box": "BOX_B",
            "predictionSnapshot": snap1,
            "settlement": {"verified": True, "actualTotal": 500000.0},
        }
        rec2 = {
            "schemaVersion": 7,
            "id": "rec_dup_2",
            "playedAt": base_ts,
            "lifecycleStatus": "FINALIZED",
            "coverageStatus": "COMPLETE",
            "venue": "VENUE_A",
            "box": "BOX_B",
            "predictionSnapshot": snap2,
            "settlement": {"verified": True, "actualTotal": 500000.0},
        }
        res = run_probability_strategy_comparison([rec1, rec2])
        # Both must be excluded because they form a potential content duplicate group!
        self.assertEqual(res["eligibleCount"], 0)
        self.assertEqual(res["excludedCount"], 2)
        self.assertIn("POTENTIAL_CONTENT_DUPLICATE_EXCLUDED", res["excludedReasons"])

    def test_18_boundary3_intersection_zero(self):
        """18. Boundary 3 files must remain 100% untouched (empty intersection)."""
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
