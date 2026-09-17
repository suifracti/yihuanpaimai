# -*- coding: utf-8 -*-
"""Comprehensive Targeted Tests for PR-C: Probability and Strategy Experimental Lab.

Verifies all external review feedback items (Round 1 & Round 2 Review Items):
1. Dafu exact divisors (2.0, 1.6, 1.3, 1.1), baseMetricSemanticsConfirmed = False, NO calculatedBiddingPrice.
2. Color prior quality order (Purple : Gold : Red = 2.2 : 1.85 : 1.0).
3. Baseline reference adapter produces NO fabricated distributions or estimates.
4. Discrete convolution candidate schema verification:
   - Rejects bare candidatePmfs fail-closed.
   - Rejects unprovenanced inputs fail-closed.
   - Accepts valid ConvolutionComponentProvenance.
   - Quantiles cannot be fabricated into PMFs.
5. Strict PMF normalization contract (1e-5 tolerance, no silent repairs, empty convolution unavailable).
6. Strict state-space budget guard (supportSize <= max_states guaranteed).
7. Structural fit (structural_fit_v1):
   - Uses extract_canonical_footprint_cells from warehouse_occupancy_adapter.
   - Never uses q as item count, missing totalGrid => unavailable.
   - Adapts canonical qualities.* shape and publicIntel.totalItems/totalGrid.
8. Structural score provenance: internal_experimental_heuristic_v1, validatedByOurData=False.
9. External Dafu CELL_FIT marks status unavailable due to unconfirmed N semantics.
10. Runtime cache stores pure experimental core only; dynamic reference and delta injection.
11. UI profile toggle bridge in HudJsApi: strictly boolean enabled check.
12. Production isolation regression test: AuctionBrain production slices 100% identical between baseline and all-profiles enabled.
13. Production state immutability: solve_session does NOT mutate session_ctx, facts, or shadow state.
14. Cross-match reset returns to baseline; runtime cache invalidation.
15. Special rule profile records hypotheses with effect_enabled = False.
16. Contract schema and runtime payload exact parity.
17. Offline comparative evaluation (Items 1-4 of Round 2):
    - Formal truth admission authority (evaluate_record_eligibility; missing SettlementTruthEvidence rejected).
    - Legacy timestamp normalization (Asia/Shanghai naive to UTC instant; aware UTC instant parity; NO naive.replace(tzinfo=UTC)).
    - Prediction snapshot target and scope lockdown (full_inventory_actual_total + full_inventory + full_shadow + coverage 1.0; structural_only or partial unavailable).
    - Honest leakage capability statement (stablePhysicalMatchIdentityAvailable=False, honest leakageProofLevel).
18. Boundary 3 file intersection is strictly empty.
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
from evaluation_eligibility import (
    build_input_sha256,
    build_truth_payload_sha256,
    validate_prediction_snapshot,
)
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
    extract_full_inventory_prediction,
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
    cutoff_at: str = "2026-09-17T09:59:00Z",
    mode: str = "full_shadow",
    coverage: float = 1.0,
    target: str = "full_inventory_actual_total",
    scope: str = "full_inventory",
    frozen: bool = True,
) -> Dict[str, Any]:
    """Construct an authentic prediction-snapshot.v1 that strictly passes validate_prediction_snapshot."""
    facts = {"q": 10, "goldAvg": 50000.0}
    input_h = build_input_sha256(facts)
    return {
        "schemaVersion": "prediction-snapshot.v1",
        "frozen": frozen,
        "predictionId": f"pred_{match_id}",
        "matchId": match_id,
        "solvedAt": solved_at,
        "informationCutoffAt": cutoff_at,
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
                "cutoffExclusive": cutoff_at,
                "eligibleRecordIdsSha256": "b" * 64,
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
            "target": target,
            "scope": scope,
            "quantiles": {"p20": p20, "p50": p50, "p80": p80},
        },
    }


def _make_valid_test_truth_evidence(
    match_id: str,
    actual_total: float = 600000.0,
    observed_at: str = "2026-09-17T10:05:00+08:00",
) -> Dict[str, Any]:
    """Construct authentic SettlementTruthEvidence matching canonical contract."""
    source = "reviewed-settlement-screenshot"
    return {
        "schemaVersion": "settlement-truth-evidence.v1",
        "matchId": match_id,
        "actualTotal": actual_total,
        "settlementObservedAt": observed_at,
        "truthSource": source,
        "truthConfidence": "high",
        "evidenceReferences": [{"uri": "evidence://settlement/one", "sha256": "a" * 64}],
        "verification": {
            "method": "human_screenshot_review",
            "version": "1",
            "verifier": {"type": "reviewer", "id": "reviewer-1"},
        },
        "truthPayloadSha256": build_truth_payload_sha256(
            match_id=match_id,
            actual_total=actual_total,
            settlement_observed_at=observed_at,
            truth_source=source,
        ),
        "unresolvedTruthConflict": False,
        "inventoryScope": {"complete": None},
        "itemLedger": {"verified": False, "deduplicated": False, "sha256": None},
    }


def _make_valid_test_record(
    match_id: str,
    actual_total: float = 600000.0,
    played_at: str = "2026-09-17T09:00:00+08:00",
    solved_at: str = "2026-09-17T08:59:00+08:00",
    observed_at: str = "2026-09-17T09:05:00+08:00",
    include_truth_evidence: bool = True,
    prediction_kwargs: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Construct an authentic canonical match record v7 admitted by evaluate_record_eligibility."""
    pred_kw = prediction_kwargs or {}
    snap = _make_valid_test_prediction_snapshot(
        match_id,
        p50=actual_total,
        solved_at=solved_at,
        cutoff_at=solved_at,
        **pred_kw,
    )
    rec = {
        "schemaVersion": 7,
        "productVersion": "v0.67-alpha",
        "id": match_id,
        "lifecycleStatus": "FINALIZED",
        "coverageStatus": "COMPLETE",
        "playedAt": played_at,
        "source": "vision-auto-archiver",
        "dataOrigin": "live",
        "environment": {
            "venueTier": "zhongji",
            "venue": f"venue_{match_id}",
            "venueName": "中级场",
            "box": f"box_{match_id}",
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
            "totalItems": 10,
            "totalGrid": 54,
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
            "actualTotal": actual_total,
            "clearingPrice": 300000,
            "realizedProfit": actual_total - 300000,
            "acquired": True,
            "winner": "玩家本人",
            "settlementItems": [],
        },
        "predictionSnapshot": snap,
    }
    if include_truth_evidence:
        rec["settlement"]["truthEvidence"] = _make_valid_test_truth_evidence(
            match_id, actual_total=actual_total, observed_at=observed_at
        )
    return rec


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
        """3. Dafu round divisors canonical; baseMetricSemanticsConfirmed=False, NO calculatedBiddingPrice."""
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

    def test_06_discrete_convolution_component_provenance_schema(self):
        """6. Convolution component input requires strict provenance schema; bare PMFs rejected."""
        rep_bare = evaluate_experimental_probability_strategy(
            session_ctx={
                "candidatePmfs": [{100.0: 0.5, 200.0: 0.5}],
            },
        )
        self.assertIsNone(rep_bare.experimental_distribution)

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

        invalid_comp = {
            "distribution": {100.0: 0.5, 200.0: 0.5}
        }
        d_bad, p_bad, err_bad = parse_convolution_component(invalid_comp)
        self.assertIsNone(d_bad)
        self.assertEqual(err_bad, "COMPONENT_ID_MISSING")

    def test_07_strict_pmf_normalization_contract(self):
        """7. DiscreteDistribution enforces strict 1e-5 normalization tolerance without silent 5% repairs."""
        d1 = DiscreteDistribution({100.0: 0.4, 200.0: 0.6})
        self.assertTrue(d1.is_valid)
        self.assertAlmostEqual(d1.mean, 160.0)

        d2 = DiscreteDistribution({100.0: 0.5, 200.0: 0.5000005})
        self.assertTrue(d2.is_valid)

        d3 = DiscreteDistribution({100.0: 0.5, 200.0: 0.55})
        self.assertFalse(d3.is_valid)

        with self.assertRaises(ValueError):
            DiscreteDistribution({100.0: -0.1, 200.0: 1.1})

        res, meta = convolve_discrete_distributions([])
        self.assertIsNone(res)
        self.assertEqual(meta["status"], "unavailable")

    def test_08_convolution_state_space_budget_guard(self):
        """8. Convolve engine guarantees supportSize <= max_states under state explosion."""
        c1 = DiscreteDistribution({i * 10.0: 0.1 for i in range(10)})
        c2 = DiscreteDistribution({i * 10.0: 0.1 for i in range(10)})
        c3 = DiscreteDistribution({i * 10.0: 0.1 for i in range(10)})

        d_conv, meta = convolve_discrete_distributions([c1, c2, c3], max_states=15)
        self.assertIsNotNone(d_conv)
        self.assertTrue(d_conv.is_valid)
        self.assertLessEqual(d_conv.support_size, 15)
        self.assertTrue(meta["budgetExceeded"])
        self.assertTrue(meta["approximationApplied"])

    def test_09_footprint_authority_and_item_f(self):
        """9. Footprint authority reuses extract_canonical_footprint_cells; qualities.* vs totalItems consistent."""
        self.assertEqual(extract_canonical_footprint_cells({"footprint": {"widthCells": 2, "heightCells": 3}}), 6)
        self.assertEqual(extract_canonical_footprint_cells({"grid": {"w": 1, "h": 4}}), 4)
        self.assertEqual(extract_canonical_footprint_cells("2x3"), 6)
        self.assertEqual(extract_canonical_footprint_cells((3, 2)), 6)
        self.assertEqual(extract_canonical_footprint_cells({"cells": 8}), 8)

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

    def test_11_cache_pure_experimental_core(self):
        """11. Cache stores pure experimental core; production metrics changes immediately update deltas."""
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

        p1 = safe_evaluate_experimental_probability_strategy(
            session_ctx=ctx,
            production_metrics={"valP50": 400000.0},
            registry=reg,
        )
        self.assertEqual(p1["productionReference"]["valP50"], 400000.0)
        self.assertIsNotNone(p1["deltaVsProduction"])
        self.assertAlmostEqual(p1["deltaVsProduction"]["medianDelta"], 100000.0)

        p2 = safe_evaluate_experimental_probability_strategy(
            session_ctx=ctx,
            production_metrics={"valP50": 600000.0},
            registry=reg,
        )
        self.assertEqual(p2["productionReference"]["valP50"], 600000.0)
        self.assertIsNotNone(p2["deltaVsProduction"])
        self.assertAlmostEqual(p2["deltaVsProduction"]["medianDelta"], -100000.0)

    def test_12_ui_profile_toggle_bridge_strict_bool(self):
        """12. HudJsApi.experimental_profile_set strictly enforces type(enabled) is bool."""
        api = HudJsApi()
        reg = get_global_strategy_registry()
        reg.reset_for_new_match()
        gen_before = reg.profile_generation

        res_true = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": True})
        self.assertTrue(res_true["success"])
        self.assertTrue(reg.is_profile_enabled("dafu_round_heuristic_v1"))
        self.assertGreater(reg.profile_generation, gen_before)

        gen_mid = reg.profile_generation
        res_false = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": False})
        self.assertTrue(res_false["success"])
        self.assertFalse(reg.is_profile_enabled("dafu_round_heuristic_v1"))

        gen_after = reg.profile_generation
        res_str = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": "false"})
        self.assertFalse(res_str["success"])
        self.assertIn("expected bool", res_str["error"])
        self.assertEqual(reg.profile_generation, gen_after)

        res_num0 = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": 0})
        self.assertFalse(res_num0["success"])
        self.assertEqual(reg.profile_generation, gen_after)

        res_num1 = api.experimental_profile_set({"profileId": "dafu_round_heuristic_v1", "enabled": 1})
        self.assertFalse(res_num1["success"])
        self.assertEqual(reg.profile_generation, gen_after)

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
            "warehouse": {
                "boxWidth": 9,
                "boxHeight": 6,
                "grid": [[0]*9 for _ in range(6)],
                "items": [],
            },
        }

        res_baseline = brain.solve_session(sample_session)

        for pid in ALLOWED_EXPERIMENTAL_PROFILES:
            if pid != "baseline":
                reg.enable_profile(pid)

        res_all_active = brain.solve_session(sample_session)

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

    def test_14_production_isolation_and_state_immutability(self):
        """14. Production state immutability: solve_session does NOT mutate session_ctx, facts, or shadow state."""
        brain = AuctionBrain()
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
            "warehouse": {
                "boxWidth": 9,
                "boxHeight": 6,
                "grid": [[0]*9 for _ in range(6)],
                "items": [],
            },
        }
        frozen_session_copy = copy.deepcopy(sample_session)

        res = brain.solve_session(sample_session)
        self.assertIsNotNone(res)

        # Input session MUST remain completely identical
        self.assertEqual(sample_session, frozen_session_copy)
        self.assertEqual(sample_session["costs"], frozen_session_copy["costs"])
        self.assertEqual(sample_session["qualities"], frozen_session_copy["qualities"])
        self.assertEqual(sample_session["warehouse"], frozen_session_copy["warehouse"])

    def test_15_cross_match_reset_to_baseline(self):
        """15. reset_for_new_match resets all external profiles strictly to baseline."""
        reg = get_global_strategy_registry()
        reg.enable_profile("dafu_round_heuristic_v1")
        reg.enable_profile("structural_fit_v1")
        self.assertIn("dafu_round_heuristic_v1", reg.get_active_profile_ids())

        reg.reset_for_new_match()
        self.assertEqual(reg.get_active_profile_ids(), ["baseline"])
        self.assertFalse(reg.is_profile_enabled("dafu_round_heuristic_v1"))

    def test_16_contract_schema_parity(self):
        """16. Report to_payload() contains exact contract schema fields without drift."""
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

    def test_17_offline_eval_canonical_admission_and_items_a_and_b(self):
        """17. Offline harness: canonical admission, aware datetime, frozen prediction validation (Items A & B)."""
        mock_records = []
        for i in range(5):
            rec_id = f"rec_{i}"
            played_ts = f"2026-09-17T10:{10 + i:02d}:00+08:00"
            solved_ts = f"2026-09-17T10:{10 + i:02d}:00+08:00"
            observed_ts = f"2026-09-17T10:{15 + i:02d}:00+08:00"
            rec = _make_valid_test_record(
                rec_id,
                actual_total=float(620000.0 + i * 10000),
                played_at=played_ts,
                solved_at=solved_ts,
                observed_at=observed_ts,
            )
            mock_records.append(rec)

        res = run_probability_strategy_comparison(mock_records)
        self.assertEqual(res["status"], "completed")
        self.assertTrue(res["metadata"]["recordIdSelfLeakageGuard"])
        self.assertFalse(res["metadata"]["performanceClaimEligible"])
        self.assertEqual(res["eligibleCount"], 5)
        self.assertEqual(res["excludedCount"], 0)

        comp = res["modelComparison"]
        self.assertEqual(comp["production_baseline"]["sampleCount"], 5)
        self.assertEqual(comp["production_baseline"]["status"], "evaluated")
        self.assertEqual(comp["historical_shadow"]["sampleCount"], 0)
        self.assertEqual(comp["historical_shadow"]["status"], "unavailable_no_independent_frozen_shadow_artifact")
        self.assertEqual(comp["pr_c_dafu_heuristic"]["sampleCount"], 0)
        self.assertEqual(comp["pr_c_dafu_heuristic"]["status"], "unavailable_base_metric_unconfirmed")

    def test_18_offline_eval_excludes_potential_duplicates(self):
        """18. Records marked as potential duplicates are strictly excluded fail-closed."""
        base_ts = "2026-09-17T10:00:00+08:00"
        solved_ts = "2026-09-17T09:59:00+08:00"
        obs_ts = "2026-09-17T10:05:00+08:00"
        rec1 = _make_valid_test_record("rec_dup_1", actual_total=500000.0, played_at=base_ts, solved_at=solved_ts, observed_at=obs_ts)
        rec2 = _make_valid_test_record("rec_dup_2", actual_total=500000.0, played_at=base_ts, solved_at=solved_ts, observed_at=obs_ts)
        rec2["environment"]["venue"] = rec1["environment"]["venue"]
        rec2["environment"]["box"] = rec1["environment"]["box"]

        res = run_probability_strategy_comparison([rec1, rec2])
        self.assertEqual(res["eligibleCount"], 0)
        self.assertEqual(res["excludedCount"], 2)
        self.assertIn("POTENTIAL_CONTENT_DUPLICATE_EXCLUDED", res["excludedReasons"])

    def test_19_offline_eval_formal_truth_gate_rejects_missing_evidence(self):
        """19. Formal truth gate rejects legacy records lacking SettlementTruthEvidence (Item 1)."""
        base_ts = "2026-09-17T10:00:00+08:00"
        solved_ts = "2026-09-17T09:59:00+08:00"
        obs_ts = "2026-09-17T10:05:00+08:00"
        rec_no_truth = _make_valid_test_record(
            "rec_no_truth",
            actual_total=500000.0,
            played_at=base_ts,
            solved_at=solved_ts,
            observed_at=obs_ts,
            include_truth_evidence=False,
        )
        self.assertNotIn("truthEvidence", rec_no_truth["settlement"])
        res = run_probability_strategy_comparison([rec_no_truth])
        self.assertEqual(res["eligibleCount"], 0)
        self.assertEqual(res["excludedCount"], 1)
        self.assertIn("TRUTH_EVIDENCE_MISSING", res["excludedReasons"])

    def test_20_canonical_timestamp_normalization_and_instant_parity(self):
        """20. Timestamp normalization: naive Asia/Shanghai and aware +08:00/Z evaluate to exact UTC instant (Item 2)."""
        dt_naive = canonical_timestamp_to_utc("2026-09-17 10:00:00")
        dt_aware_shanghai = canonical_timestamp_to_utc("2026-09-17T10:00:00+08:00")
        dt_aware_utc = canonical_timestamp_to_utc("2026-09-17T02:00:00Z")

        self.assertIsNotNone(dt_naive)
        self.assertIsNotNone(dt_aware_shanghai)
        self.assertIsNotNone(dt_aware_utc)

        # All three must map to the exact same UTC instant: 2026-09-17 02:00:00 UTC
        self.assertEqual(dt_naive, dt_aware_shanghai)
        self.assertEqual(dt_aware_shanghai, dt_aware_utc)
        self.assertEqual(dt_naive.hour, 2)
        self.assertEqual(dt_naive.minute, 0)
        self.assertEqual(dt_naive.tzinfo, timezone.utc)

    def test_21_prediction_snapshot_target_and_scope_lockdown(self):
        """21. Prediction snapshot extraction rejects non-full-inventory or non-full-shadow targets (Item 3)."""
        # Valid full shadow / full inventory
        valid_snap = _make_valid_test_prediction_snapshot("s1")
        pred, reason = extract_full_inventory_prediction(valid_snap)
        self.assertIsNotNone(pred)
        self.assertIsNone(reason)
        self.assertEqual(pred[1], 600000.0)

        # Disallowed informationMode: structural_only
        bad_mode_snap = _make_valid_test_prediction_snapshot("s2", mode="structural_only")
        pred_bad, reason_bad = extract_full_inventory_prediction(bad_mode_snap)
        self.assertIsNone(pred_bad)
        self.assertIn("DISALLOWED_INFORMATION_MODE", reason_bad)

        # Disallowed coverageRatio: 0.8
        bad_cov_snap = _make_valid_test_prediction_snapshot("s3", coverage=0.8)
        pred_cov, reason_cov = extract_full_inventory_prediction(bad_cov_snap)
        self.assertIsNone(pred_cov)
        self.assertTrue("COVERAGE" in reason_cov)

        # Disallowed target: partial_value
        bad_target_snap = _make_valid_test_prediction_snapshot("s4", target="structural_only")
        pred_t, reason_t = extract_full_inventory_prediction(bad_target_snap)
        self.assertIsNone(pred_t)
        self.assertIn("TARGET_NOT_FULL_INVENTORY", reason_t)

        # Disallowed scope: partial_inventory
        bad_scope_snap = _make_valid_test_prediction_snapshot("s5", scope="partial_inventory")
        pred_s, reason_s = extract_full_inventory_prediction(bad_scope_snap)
        self.assertIsNone(pred_s)
        self.assertTrue("SCOPE" in reason_s)

        # Disallowed frozen: False
        unfrozen_snap = _make_valid_test_prediction_snapshot("s6", frozen=False)
        pred_u, reason_u = extract_full_inventory_prediction(unfrozen_snap)
        self.assertIsNone(pred_u)
        self.assertTrue("FROZEN" in reason_u)

    def test_22_leakage_capability_honest_statement(self):
        """22. Metadata states honest leakage capability without absolute-zero overclaims (Item 4)."""
        base_ts = "2026-09-17T10:00:00+08:00"
        solved_ts = "2026-09-17T09:59:00+08:00"
        obs_ts = "2026-09-17T10:05:00+08:00"
        rec = _make_valid_test_record("rec_leakage", played_at=base_ts, solved_at=solved_ts, observed_at=obs_ts)
        res = run_probability_strategy_comparison([rec])
        meta = res["metadata"]

        self.assertFalse(meta["stablePhysicalMatchIdentityAvailable"])
        self.assertEqual(meta["leakageProofLevel"], "record_id_known_potential_duplicate_and_temporal_prior")
        self.assertFalse(meta["physicalMatchLeakageImpossible"])
        self.assertFalse(meta["absoluteZeroPhysicalLeakage"])

    def test_23_canonical_qualities_adapter_and_provenance(self):
        """23. Adapts canonical qualities structure and sets heuristic provenance (Items 5 & 6)."""
        ctx = {
            "publicIntel": {"totalGrid": 54, "totalItems": 6},
            "qualities": {
                "purple": {
                    "count": 2,
                    "grid": 8,
                    "knownItems": [{"footprint": "2x2"}, {"cells": 4}],
                },
                "gold": {
                    "count": 4,
                    "grid": 16,
                    "knownItems": ["2x2", "2x2", "2x2", "2x2"],
                },
            },
        }
        diag = compute_structural_fit(ctx)
        self.assertEqual(diag.status, "evaluated")
        self.assertTrue(diag.feasible)
        self.assertEqual(diag.details["knownCellsTotal"], 24)
        self.assertEqual(diag.details["qualityScoreSource"], "internal_experimental_heuristic_v1")
        self.assertFalse(diag.details["qualityScoreValidatedByOurData"])
        self.assertFalse(diag.details["qualityScoreProductionEligible"])

    def test_24_boundary3_intersection_zero(self):
        """24. Boundary 3 files must remain 100% untouched (empty intersection)."""
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

    def test_25_live_formal_dataset_still_performance_claim_ineligible(self):
        """25. performanceClaimEligible strictly False even if datasetKind == 'live'."""
        rec = _make_valid_test_record("rec_live_test")
        res = run_probability_strategy_comparison([rec], dataset_kind="live", harness_verification=False)
        self.assertFalse(res["metadata"]["performanceClaimEligible"])

    def test_26_harness_verification_true_formal_cohort_mode_false(self):
        """26. harness_verification=True can never claim formal cohort mode or admission."""
        rec = _make_valid_test_record("rec_harness_test")
        res = run_probability_strategy_comparison([rec], dataset_kind="live", harness_verification=True)
        self.assertFalse(res["metadata"]["formalCohortMode"])
        self.assertFalse(res["metadata"]["formalCohortAdmitted"])
        self.assertEqual(res["metadata"]["formalEligibleRecordCount"], 0)

    def test_27_zero_eligible_formal_run_count_zero(self):
        """27. When formal run has 0 eligible records, formalEligibleRecordCount is 0 and formalCohortAdmitted is False."""
        rec_bad = _make_valid_test_record("rec_bad", include_truth_evidence=False)
        res = run_probability_strategy_comparison([rec_bad], dataset_kind="live", harness_verification=False)
        self.assertTrue(res["metadata"]["formalCohortMode"])
        self.assertEqual(res["metadata"]["formalEligibleRecordCount"], 0)
        self.assertFalse(res["metadata"]["formalCohortAdmitted"])

    def test_28_markdown_metadata_parity(self):
        """28. format_comparison_markdown reads metadata fields and renders Performance Claim Eligible: False."""
        rec = _make_valid_test_record("rec_md_test")
        res = run_probability_strategy_comparison([rec], dataset_kind="live", harness_verification=False)
        md = format_comparison_markdown(res)
        self.assertIn("- **Performance Claim Eligible**: `False`", md)
        self.assertIn("- **Formal Cohort Mode**: `True`", md)
        self.assertIn("- **Formal Eligible Record Count**: `1`", md)

    def test_29_dafu_ui_contains_divisor_multiplier_and_no_calculated_bidding_price(self):
        """29. Overlay UI displays round divisor/multiplier and semantics warning; no calculatedBiddingPrice."""
        overlay_html_path = os.path.join(_CORE_DIR, "overlay_alpha.html")
        with open(overlay_html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # calculatedBiddingPrice must NOT exist in overlay UI
        self.assertNotIn("calculatedBiddingPrice", html_content)

        # Must display divisor, multiplier, and unconfirmed semantics text
        self.assertIn("canonicalDivisor", html_content)
        self.assertIn("calculatedMultiplier", html_content)
        self.assertIn("基准量语义未确认", html_content)


if __name__ == "__main__":
    unittest.main()
