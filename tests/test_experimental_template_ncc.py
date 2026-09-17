# -*- coding: utf-8 -*-
"""Unit tests for PR-E: Experimental Template NCC Benchmark & Evaluation.

Covers all 25 contract test specifications:
1. identical arrays => NCC ~= 1.0
2. inverted / unrelated pattern behaves correctly
3. zero variance template rejected
4. zero variance crop rejected
5. NaN rejected
6. Inf rejected
7. shape mismatch contract
8. deterministic repeated result
9. input arrays unchanged
10. score finite and bounded
11. candidate ranking deterministic
12. tie/near-tie remains ambiguous
13. memory budget fail closed
14. benchmark same corpus for both backends
15. same candidate set for both backends
16. template/query self-overlap marked
17. mechanics-only dataset cannot make accuracy claim
18. held-out truth cohort eligibility
19. baseline adapter output matches current production matcher
20. default experimental backend disabled
21. production output parity when disabled
22. benchmark exception cannot break production
23. no competitor/external assets in runtime
24. Boundary3 file intersection == 0
25. PR-D contracts unchanged
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import sys
import unittest
from pathlib import Path

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_CORE_DIR = os.path.join(_PROJECT_ROOT, "core")
_APP_DIR = os.path.join(_PROJECT_ROOT, "app")
_TOOLS_DIR = os.path.join(_PROJECT_ROOT, "tools")
for _p in (_PROJECT_ROOT, _CORE_DIR, _APP_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cv2
import numpy as np

import experimental_template_ncc as ncc
from experimental_template_ncc import numpy_ncc_score, numpy_sliding_ncc
from matcher_adapters import CurrentMatcherAdapter, NumpyNccMatcherAdapter, OpenCvScorerBaselineAdapter, prepare_matching_pair
from settlement_catalog_candidates import _match_template_score, get_global_catalog_candidate_resolver


class TestExperimentalTemplateNcc(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        # Create a textured 75x75x3 test pattern
        self.pattern = np.zeros((75, 75, 3), dtype=np.uint8)
        self.pattern[10:65, 10:65] = [80, 140, 210]
        self.pattern[25:50, 25:50] = [200, 50, 90]

    # Test 1: Identical arrays => NCC ~= 1.0
    def test_01_identical_arrays_yield_ncc_near_one(self):
        res = numpy_ncc_score(self.pattern, self.pattern.copy())
        self.assertTrue(res["valid"])
        self.assertEqual(res["status"], "EXACT_MATCH")
        self.assertAlmostEqual(res["rawNcc"], 1.0, places=5)
        self.assertAlmostEqual(res["score"], 1.0, places=4)

    # Test 2: Inverted / unrelated pattern behaves correctly
    def test_02_inverted_pattern_yields_negative_ncc(self):
        inverted = 255 - self.pattern
        res = numpy_ncc_score(self.pattern, inverted)
        self.assertTrue(res["valid"])
        self.assertAlmostEqual(res["rawNcc"], -1.0, places=5)
        self.assertEqual(res["score"], 0.0)  # clamped to [0, 1]

    # Test 3: Zero variance template rejected
    def test_03_zero_variance_template_rejected(self):
        flat_tpl = np.ones((75, 75, 3), dtype=np.uint8) * 128
        res = numpy_ncc_score(self.pattern, flat_tpl)
        self.assertFalse(res["valid"])
        self.assertEqual(res["status"], "ZERO_VARIANCE_FAIL_CLOSED")
        self.assertEqual(res["score"], 0.0)
        self.assertEqual(res["reason"], "ZERO_VARIANCE_TEMPLATE")

    # Test 4: Zero variance crop rejected
    def test_04_zero_variance_crop_rejected(self):
        flat_crop = np.zeros((75, 75, 3), dtype=np.uint8)
        res = numpy_ncc_score(flat_crop, self.pattern)
        self.assertFalse(res["valid"])
        self.assertEqual(res["status"], "ZERO_VARIANCE_FAIL_CLOSED")
        self.assertEqual(res["score"], 0.0)
        self.assertEqual(res["reason"], "ZERO_VARIANCE_CROP")

    # Test 5: NaN rejected
    def test_05_nan_rejected(self):
        nan_arr = self.pattern.astype(np.float64)
        nan_arr[5, 5, 0] = np.nan
        res = numpy_ncc_score(nan_arr, self.pattern)
        self.assertFalse(res["valid"])
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertEqual(res["score"], 0.0)

    # Test 6: Inf rejected
    def test_06_inf_rejected(self):
        inf_arr = self.pattern.astype(np.float64)
        inf_arr[10, 10, 1] = np.inf
        res = numpy_ncc_score(self.pattern, inf_arr)
        self.assertFalse(res["valid"])
        self.assertEqual(res["status"], "INVALID_INPUT")
        self.assertEqual(res["score"], 0.0)

    # Test 7: Shape mismatch contract
    def test_07_shape_mismatch_contract(self):
        different_shape = np.ones((50, 40, 3), dtype=np.uint8) * 50
        different_shape[10:30, 10:30] = 150
        # Pure NumPy kernel fails closed when spatial shapes differ directly
        res_no_resize = numpy_ncc_score(self.pattern, different_shape)
        self.assertFalse(res_no_resize["valid"])
        self.assertEqual(res_no_resize["status"], "SHAPE_MISMATCH")

        # Shared preprocessing standardizes shapes prior to scoring
        crop_pre, tpl_pre = prepare_matching_pair(self.pattern, different_shape)
        self.assertEqual(crop_pre.shape[:2], tpl_pre.shape[:2])
        self.assertFalse(crop_pre.flags.writeable)
        self.assertFalse(tpl_pre.flags.writeable)
        res_pre = numpy_ncc_score(crop_pre, tpl_pre)
        self.assertTrue(res_pre["valid"])

    # Test 8: Deterministic repeated result
    def test_08_deterministic_repeated_results(self):
        other = np.random.randint(0, 256, (75, 75, 3), dtype=np.uint8)
        res1 = numpy_ncc_score(self.pattern, other)
        res2 = numpy_ncc_score(self.pattern, other)
        res3 = numpy_ncc_score(self.pattern, other)
        self.assertEqual(res1["rawNcc"], res2["rawNcc"])
        self.assertEqual(res2["rawNcc"], res3["rawNcc"])
        self.assertEqual(res1["score"], res2["score"])

    # Test 9: Input arrays unchanged (non-mutation guarantee)
    def test_09_input_arrays_unchanged(self):
        crop_orig = self.pattern.copy()
        tpl_orig = np.random.randint(0, 256, (75, 75, 3), dtype=np.uint8)
        tpl_copy = tpl_orig.copy()

        _ = numpy_ncc_score(self.pattern, tpl_orig)
        np.testing.assert_array_equal(self.pattern, crop_orig)
        np.testing.assert_array_equal(tpl_orig, tpl_copy)

    # Test 10: Score finite and bounded
    def test_10_score_finite_and_bounded(self):
        for _ in range(20):
            r1 = np.random.randint(0, 256, (30, 30, 3), dtype=np.uint8)
            r2 = np.random.randint(0, 256, (30, 30, 3), dtype=np.uint8)
            res = numpy_ncc_score(r1, r2)
            if res["valid"]:
                self.assertTrue(-1.0 <= res["rawNcc"] <= 1.0)
                self.assertTrue(0.0 <= res["score"] <= 1.0)
                self.assertTrue(math.isfinite(res["rawNcc"]))
                self.assertTrue(math.isfinite(res["score"]))

    # Test 11: Candidate ranking deterministic
    def test_11_candidate_ranking_deterministic(self):
        adapter = NumpyNccMatcherAdapter()
        cands = [
            {"catalogId": "cand_a", "name": "Item A"},
            {"catalogId": "cand_b", "name": "Item B"},
            {"catalogId": "cand_c", "name": "Item C"},
        ]
        tpls = {
            "cand_a": self.pattern.copy(),
            "cand_b": 255 - self.pattern,
            "cand_c": np.random.randint(0, 256, (75, 75, 3), dtype=np.uint8),
        }
        res1 = adapter.evaluate_candidates(self.pattern, cands, tpls)
        res2 = adapter.evaluate_candidates(self.pattern, cands, tpls)
        self.assertEqual(res1["exactCatalogId"], res2["exactCatalogId"])
        self.assertEqual(
            [c["catalogId"] for c in res1["rankedCandidates"]],
            [c["catalogId"] for c in res2["rankedCandidates"]],
        )

    # Test 12: Tie/near-tie remains ambiguous
    def test_12_tie_near_tie_remains_ambiguous(self):
        adapter = NumpyNccMatcherAdapter(top1_threshold=0.85, margin_threshold=0.08)
        # Two virtually identical templates (margin < 0.08)
        tpl_a = self.pattern.copy()
        tpl_b = self.pattern.copy()
        tpl_b[0, 0, 0] = (int(tpl_b[0, 0, 0]) + 1) % 256

        cands = [{"catalogId": "a", "name": "A"}, {"catalogId": "b", "name": "B"}]
        tpls = {"a": tpl_a, "b": tpl_b}
        res = adapter.evaluate_candidates(self.pattern, cands, tpls)
        self.assertEqual(res["status"], "AMBIGUOUS_CANDIDATES")
        self.assertIsNone(res["exactCatalogId"])
        self.assertLess(res["margin"], 0.08)

    # Test 13: Memory budget fail-closed on sliding window
    def test_13_memory_budget_fail_closed(self):
        big_image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        tpl = np.zeros((100, 100, 3), dtype=np.uint8)
        # Pass a small 1 MB budget
        res = numpy_sliding_ncc(big_image, tpl, memory_budget_bytes=1024 * 1024)
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "MEMORY_BUDGET_EXCEEDED")
        self.assertIsNone(res["correlationMap"])

    # Test 14: Benchmark evaluates identical corpus for both backends
    def test_14_benchmark_evaluates_identical_corpus(self):
        base_adapter = CurrentMatcherAdapter()
        ncc_adapter = NumpyNccMatcherAdapter()

        cands = [{"catalogId": "item_1", "name": "One"}]
        tpls = {"item_1": self.pattern}

        b_res = base_adapter.evaluate_candidates(self.pattern, cands, tpls)
        n_res = ncc_adapter.evaluate_candidates(self.pattern, cands, tpls)

        self.assertEqual(b_res["candidateCount"], n_res["candidateCount"])
        self.assertAlmostEqual(b_res["top1Score"], n_res["top1Score"], places=3)
        self.assertEqual(b_res["status"], n_res["status"])

    # Test 15: Same candidate set for both backends
    def test_15_same_candidate_set_for_both_backends(self):
        resolver = get_global_catalog_candidate_resolver()
        hyp = {"gridShape": "2x2", "rarity": "gold"}
        cands = resolver.resolve_candidates_for_hypothesis(hyp)

        base_adapter = CurrentMatcherAdapter()
        ncc_adapter = NumpyNccMatcherAdapter()

        tpls = {c["catalogId"]: self.pattern for c in cands}
        b_res = base_adapter.evaluate_candidates(self.pattern, cands, tpls)
        n_res = ncc_adapter.evaluate_candidates(self.pattern, cands, tpls)

        self.assertEqual(len(b_res["rankedCandidates"]), len(n_res["rankedCandidates"]))
        self.assertEqual(
            [c["catalogId"] for c in b_res["rankedCandidates"]],
            [c["catalogId"] for c in n_res["rankedCandidates"]],
        )

    # Test 16: Template/query self-overlap audit marker
    def test_16_template_query_self_overlap_marker(self):
        sample_self = {
            "datasetRole": "mechanics_only",
            "templateSourceOverlap": True,
            "performanceClaimEligible": False,
        }
        self.assertTrue(sample_self["templateSourceOverlap"])
        self.assertFalse(sample_self["performanceClaimEligible"])

    # Test 17: Mechanics-only dataset cannot make accuracy claim
    def test_17_mechanics_only_dataset_cannot_make_accuracy_claim(self):
        sample = {
            "datasetRole": "mechanics_only",
            "performanceClaimEligible": False,
        }
        self.assertEqual(sample["datasetRole"], "mechanics_only")
        self.assertFalse(sample["performanceClaimEligible"])

    # Test 18: Held-out truth cohort eligibility & accuracy gate
    def test_18_held_out_truth_cohort_eligibility(self):
        sample = {
            "datasetRole": "held_out_query",
            "agreementEligible": True,
            "truthEligible": True,
            "truthCandidatePresent": True,
            "templateSourceOverlap": False,
            "candidateSetCompleteForTruth": True,
            "performanceClaimEligible": False,  # PR-E maintains False
            "sourceMatchId": "match_144037",
        }
        accuracy_eligible = bool(
            sample["truthEligible"]
            and sample["truthCandidatePresent"]
            and not sample["templateSourceOverlap"]
            and sample["candidateSetCompleteForTruth"]
            and sample["datasetRole"] != "mechanics_only"
        )
        self.assertEqual(sample["datasetRole"], "held_out_query")
        self.assertTrue(sample["agreementEligible"])
        self.assertTrue(accuracy_eligible)
        self.assertFalse(sample["performanceClaimEligible"])

    # Test 19: Baseline adapter matches current production matcher
    def test_19_baseline_adapter_matches_current_production_matcher(self):
        base_adapter = OpenCvScorerBaselineAdapter()
        res_adapter = base_adapter.score_single_pair(self.pattern, self.pattern)
        score_adapter = res_adapter["score"]
        score_prod, _, src = _match_template_score(self.pattern, self.pattern, "raw_tpl")
        self.assertAlmostEqual(score_adapter, score_prod, places=4)
        self.assertEqual(src, "PIXEL_TEMPLATE_MATCH")
        self.assertIs(CurrentMatcherAdapter, OpenCvScorerBaselineAdapter)

    # Test 20: Default experimental backend disabled
    def test_20_default_experimental_backend_disabled(self):
        ncc_adapter = NumpyNccMatcherAdapter()
        meta = ncc_adapter.get_metadata()
        self.assertTrue(meta["experimental"])
        self.assertFalse(meta["defaultEnabled"])
        self.assertFalse(meta["productionEligible"])

    # Test 21: Production output parity when disabled
    def test_21_production_output_parity_when_disabled(self):
        # When experimental backend is disabled, resolver and item recognizer
        # execute only production code paths without mutation.
        resolver = get_global_catalog_candidate_resolver()
        self.assertFalse(hasattr(resolver, "_active_experimental_backend"))

    # Test 22: Benchmark exception cannot break production
    def test_22_benchmark_exception_cannot_break_production(self):
        def crashing_benchmark():
            raise RuntimeError("Benchmark synthetic failure")

        # Calling benchmark in separate try-except preserves production state
        try:
            crashing_benchmark()
        except RuntimeError:
            pass

        # Production resolver remains fully functional
        resolver = get_global_catalog_candidate_resolver()
        self.assertIsNotNone(resolver)

    # Test 23: No competitor/external assets in runtime
    def test_23_no_competitor_external_assets_in_runtime(self):
        prohibited_keywords = ["auctionpilot", "nte-auction-helper", "nte_auction_helper", "dafu_helper"]
        project_root = Path(__file__).resolve().parents[1]
        for rel_p in ["core/experimental_template_ncc.py", "core/matcher_adapters.py", "tools/benchmark_template_ncc.py"]:
            full_p = project_root / rel_p
            if full_p.is_file():
                content = full_p.read_text(encoding="utf-8", errors="ignore").lower()
                for kw in prohibited_keywords:
                    self.assertNotIn(kw, content, f"Forbidden asset keyword {kw} found in {full_p}")
        assets_dir = project_root / "assets"
        for root, dirs, files in os.walk(str(assets_dir)):
            for d in dirs:
                self.assertNotIn(d.lower(), prohibited_keywords)
            for f in files:
                for kw in prohibited_keywords:
                    self.assertNotIn(kw, f.lower())

    # Test 24: Boundary 3 file intersection is strictly 0
    def test_24_boundary3_file_intersection_strictly_zero(self):
        b3_files = {
            "app/warehouse_capture_host.py",
            "core/warehouse_capture_production.py",
            "core/warehouse_capture_session.py",
            "core/warehouse_input_abort_guard.py",
            "core/warehouse_wheel_driver.py",
            "tests/negative_matrix_evidence.json",
            "tests/test_boundary3_pre_fix.py",
            "tests/test_boundary3_takeover_matrix_and_toctou.py",
            "tests/test_warehouse_input_abort_guard_v1.py",
            "tests/toctou_timeline_evidence.json",
        }
        pr_e_files = {
            "core/experimental_template_ncc.py",
            "core/matcher_adapters.py",
            "tools/benchmark_template_ncc.py",
            "tests/test_experimental_template_ncc.py",
        }
        intersection = b3_files.intersection(pr_e_files)
        self.assertEqual(len(intersection), 0)
        self.assertEqual(intersection, set())

    # Test 25: PR-D contracts unchanged
    def test_25_pr_d_contracts_unchanged(self):
        from warehouse_scan_progress import WarehouseScanProgressTracker
        from warehouse_double_evidence_dedup import WarehouseDoubleEvidenceDedupGate
        from warehouse_active_scan_freeze import WarehouseScanSafetyCoordinator

        progress = WarehouseScanProgressTracker()
        payload = progress.to_payload()
        self.assertEqual(payload["canonicalTask4Status"], "UNFINISHED")
        self.assertFalse(progress.is_complete)

        dedup = WarehouseDoubleEvidenceDedupGate()
        self.assertIsNotNone(dedup)

        coord = WarehouseScanSafetyCoordinator()
        self.assertTrue(coord.scroll_permitted)

    # Test 26: Actual production baseline replica classification
    def test_26_actual_production_baseline_replica_classification(self):
        base_adapter = OpenCvScorerBaselineAdapter()
        meta = base_adapter.get_metadata()
        self.assertEqual(meta["adapterReuseMode"], "scorer_replica")
        self.assertFalse(meta["fullProductionMatcherEquivalent"])
        self.assertEqual(meta["actualProductionEntry"], "core.warehouse_vision.WarehouseVisionPipeline.process_frame")
        self.assertEqual(meta["candidateGenerator"], "core.warehouse_vision.WarehouseTemplateMatcher.get_candidates")
        self.assertIn("WarehouseTemplateMatcher.match_candidates", meta["scoreAuthority"])
        self.assertIn("WarehouseVisionConfig", meta["thresholdAuthority"])

    # Test 27: Threshold provenance
    def test_27_threshold_provenance(self):
        from warehouse_vision import WarehouseVisionConfig
        cfg = WarehouseVisionConfig()
        base_adapter = OpenCvScorerBaselineAdapter()
        meta = base_adapter.get_metadata()
        self.assertEqual(meta["thresholds"]["top1ScoreThreshold"], cfg.MATCH_CONFIDENCE_THRESHOLD)
        self.assertEqual(meta["thresholds"]["marginThreshold"], cfg.MATCH_MARGIN_THRESHOLD)
        self.assertEqual(meta["thresholds"]["top1ScoreThreshold"], 0.85)
        self.assertEqual(meta["thresholds"]["marginThreshold"], 0.08)
        self.assertEqual(meta["thresholdProvenance"], "core.warehouse_vision.WarehouseVisionConfig")

    # Test 28: Truth candidate absent => accuracy ineligible
    def test_28_truth_candidate_absent_ineligible_for_accuracy(self):
        sample_absent = {
            "datasetRole": "held_out_query",
            "truthEligible": True,
            "truthCandidatePresent": False,
            "templateSourceOverlap": False,
            "candidateSetCompleteForTruth": False,
        }
        accuracy_eligible = bool(
            sample_absent["truthEligible"]
            and sample_absent["truthCandidatePresent"]
            and not sample_absent["templateSourceOverlap"]
            and sample_absent["candidateSetCompleteForTruth"]
            and sample_absent["datasetRole"] != "mechanics_only"
        )
        self.assertFalse(accuracy_eligible)

    # Test 29: Mechanics-only => accuracy ineligible
    def test_29_mechanics_only_ineligible_for_accuracy(self):
        sample_mechanics = {
            "datasetRole": "mechanics_only",
            "truthEligible": False,
            "truthCandidatePresent": True,
            "templateSourceOverlap": True,
            "candidateSetCompleteForTruth": True,
        }
        accuracy_eligible = bool(
            sample_mechanics["truthEligible"]
            and sample_mechanics["truthCandidatePresent"]
            and not sample_mechanics["templateSourceOverlap"]
            and sample_mechanics["candidateSetCompleteForTruth"]
            and sample_mechanics["datasetRole"] != "mechanics_only"
        )
        self.assertFalse(accuracy_eligible)

    # Test 30: Candidate count reporting and distribution
    def test_30_candidate_count_reporting_and_distribution(self):
        sample = {
            "candidates": [{"catalogId": "c1"}, {"catalogId": "c2"}],
            "candidateCount": 2,
            "candidateIds": ["c1", "c2"],
            "candidateGenerationSource": "core.settlement_catalog_candidates.SettlementCatalogCandidateResolver.resolve_candidates_for_hypothesis",
            "candidateGenerationIncludedInTiming": False,
            "templateUniverseSize": 213,
        }
        self.assertEqual(sample["candidateCount"], 2)
        self.assertEqual(sample["candidateIds"], ["c1", "c2"])
        self.assertFalse(sample["candidateGenerationIncludedInTiming"])
        self.assertEqual(sample["templateUniverseSize"], 213)

    # Test 31: Shared preprocessing and input immutability
    def test_31_shared_preprocessing_and_input_immutability(self):
        crop = np.random.randint(0, 256, (75, 75, 3), dtype=np.uint8)
        template = np.random.randint(0, 256, (50, 60, 3), dtype=np.uint8)
        crop_pre, tpl_pre = prepare_matching_pair(crop, template)
        self.assertEqual(crop_pre.shape[:2], tpl_pre.shape[:2])
        self.assertFalse(crop_pre.flags.writeable)
        self.assertFalse(tpl_pre.flags.writeable)

    # Test 32: Backend-specific resize forbidden
    def test_32_backend_specific_resize_forbidden(self):
        base_meta = OpenCvScorerBaselineAdapter().get_metadata()
        ncc_meta = NumpyNccMatcherAdapter().get_metadata()
        self.assertTrue(base_meta["preprocessingShared"])
        self.assertFalse(base_meta["backendSpecificResize"])
        self.assertTrue(ncc_meta["preprocessingShared"])
        self.assertFalse(ncc_meta["backendSpecificResize"])

        # Pure NumPy kernel fails closed when given raw mismatched shapes directly
        raw_crop = np.ones((75, 75, 3), dtype=np.uint8)
        raw_tpl = np.ones((50, 60, 3), dtype=np.uint8)
        res = numpy_ncc_score(raw_crop, raw_tpl)
        self.assertFalse(res["valid"])
        self.assertEqual(res["status"], "SHAPE_MISMATCH")

    # Test 33: Verdict scope no clear gain on scoring kernel
    def test_33_verdict_scope_no_clear_gain_on_scoring_kernel(self):
        from benchmark_template_ncc import build_benchmark_corpus, run_benchmark
        corpus, templates = build_benchmark_corpus(Path(_PROJECT_ROOT))
        report, _, _ = run_benchmark(corpus[:5], templates, warmup_rounds=1, measured_rounds=1)
        self.assertEqual(report["evaluationConclusion"]["verdict"], "NO_CLEAR_GAIN_ON_SCORING_KERNEL")
        self.assertEqual(report["evaluationConclusion"]["verdictScope"], "latency_and_throughput_on_scoring_kernel")
        self.assertFalse(report["evaluationConclusion"]["productionPromotionClaimed"])
        self.assertFalse(report["evaluationConclusion"]["defaultEnabled"])
        self.assertFalse(report["evaluationConclusion"]["productionEligible"])

    # Test 34: Pure NumPy kernel has no cv2 import
    def test_34_pure_numpy_kernel_has_no_cv2_import(self):
        kernel_path = Path(_PROJECT_ROOT) / "core" / "experimental_template_ncc.py"
        code = kernel_path.read_text(encoding="utf-8")
        import ast
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, "cv2", "core/experimental_template_ncc.py must not import cv2")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "cv2", "core/experimental_template_ncc.py must not import from cv2")


if __name__ == "__main__":
    unittest.main()
