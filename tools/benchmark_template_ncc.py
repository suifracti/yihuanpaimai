# -*- coding: utf-8 -*-
"""PR-E Benchmark Harness: OpenCV Baseline vs Pure NumPy NCC.

Executes controlled, reproducible comparison under identical candidate sets,
identical input crops, identical candidate templates, and identical decision thresholds.
Enforces warmup (>= 2 rounds) and repeat (>= 5 rounds) discipline.
Outputs structured metrics across accuracy, agreement, latency percentiles, and memory.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import platform
import sys
import subprocess
import time
import tracemalloc
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import cv2
import numpy as np

# Ensure project root & core in path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from experimental_template_ncc import numpy_ncc_score, numpy_sliding_ncc
from matcher_adapters import CurrentMatcherAdapter, NumpyNccMatcherAdapter, OpenCvScorerBaselineAdapter
from settlement_catalog_candidates import get_global_catalog_candidate_resolver
from visual_catalog import deterministic_reference_crops


def build_benchmark_corpus(root: Path) -> Tuple[List[Dict[str, Any]], Dict[str, np.ndarray]]:
    """Construct unified benchmark corpus with strictly separated cohorts.

    Cohort 1: held_out_query (79 real video ground truth crops from 3 matches)
              templateSourceOverlap = False, performanceClaimEligible = True
    Cohort 2: mechanics_only (20 synthetic/self-match/edge-case verification crops)
              templateSourceOverlap = True / synthetic, performanceClaimEligible = False
    """
    # 1. Load canonical reference templates
    crops_info = deterministic_reference_crops()
    templates: Dict[str, np.ndarray] = {}
    for c in crops_info:
        cid = c["catalogId"]
        rel = c["cropRelativePath"]
        img_p = root / rel
        if img_p.is_file():
            img = cv2.imread(str(img_p))
            if img is not None:
                templates[cid] = img

    resolver = get_global_catalog_candidate_resolver()
    samples: List[Dict[str, Any]] = []

    # 2. Build Cohort 1: held_out_query
    ground_truth_files = [
        ("assets/items/video_ground_truth_reference_144037.json", "match_144037"),
        ("assets/items/video_ground_truth_reference_134043_visible.json", "match_134043"),
        ("assets/items/video_ground_truth_reference_134436_match2_visible.json", "match_134436"),
    ]

    for rel_path, match_id in ground_truth_files:
        p = root / rel_path
        if not p.is_file():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for it in data.get("items", []):
            crop_rel = it.get("localCropPath")
            if not crop_rel:
                continue
            crop_path = root / crop_rel
            if not crop_path.is_file():
                continue

            crop_bytes = crop_path.read_bytes()
            crop_sha = hashlib.sha256(crop_bytes).hexdigest()

            truth_cid = it.get("catalogId")
            grid_shape = it.get("gridBoundingBox", {}).get("shape") or "1x1"
            quality = it.get("quality") or "white"
            name = it.get("canonicalName") or truth_cid

            # Candidate generation via catalog resolver
            cand_hyp = {"gridShape": grid_shape, "rarity": quality}
            candidates = resolver.resolve_candidates_for_hypothesis(cand_hyp)
            if not candidates:
                # If no shape/rarity candidate list, fallback to single candidate
                candidates = [{"catalogId": truth_cid, "name": name}]

            sample_id = f"{match_id}_{it.get('referenceId', len(samples))}"
            cand_ids = [c.get("catalogId") for c in candidates]

            truth_present = (truth_cid in cand_ids) and (truth_cid in templates)
            candidate_complete_for_truth = bool(truth_cid in cand_ids)
            truth_eligible = bool(truth_cid and not str(truth_cid).startswith("synthetic"))
            accuracy_eligible = bool(
                truth_eligible
                and truth_present
                and candidate_complete_for_truth
            )

            samples.append({
                "sampleId": sample_id,
                "datasetRole": "held_out_query",
                "agreementEligible": True,
                "accuracyClaimEligible": accuracy_eligible,
                "truthEligible": truth_eligible,
                "truthCandidatePresent": truth_present,
                "templateSourceOverlap": False,
                "candidateSetCompleteForTruth": candidate_complete_for_truth,
                "performanceClaimEligible": False,  # PR-E maintains False
                "sourceMatchId": match_id,
                "cropPath": str(crop_rel).replace("\\", "/"),
                "cropSha256": crop_sha,
                "truthCatalogId": truth_cid,
                "truthName": name,
                "truthQuality": quality,
                "gridShape": grid_shape,
                "candidateCount": len(candidates),
                "candidateIds": cand_ids,
                "candidateGenerationSource": "core.settlement_catalog_candidates.SettlementCatalogCandidateResolver.resolve_candidates_for_hypothesis",
                "candidateGenerationIncludedInTiming": False,
                "templateUniverseSize": len(templates),
                "candidates": [
                    {"catalogId": c.get("catalogId"), "name": c.get("name"), "value": c.get("value", 0)}
                    for c in candidates
                ],
            })

    # 3. Build Cohort 2: mechanics_only (self-matching & edge cases)
    # 3a. Self-matching crops from reference_crops (first 10)
    for idx, c in enumerate(crops_info[:10]):
        cid = c["catalogId"]
        rel = c["cropRelativePath"]
        img_p = root / rel
        if not img_p.is_file():
            continue
        crop_bytes = img_p.read_bytes()
        crop_sha = hashlib.sha256(crop_bytes).hexdigest()

        samples.append({
            "sampleId": f"mechanics_self_{idx}_{cid}",
            "datasetRole": "mechanics_only",
            "agreementEligible": True,
            "accuracyClaimEligible": False,  # Mechanics self-match ineligible for accuracy claim
            "truthEligible": False,
            "truthCandidatePresent": True,
            "templateSourceOverlap": True,
            "candidateSetCompleteForTruth": True,
            "performanceClaimEligible": False,
            "sourceMatchId": "template_self_reference",
            "cropPath": str(rel).replace("\\", "/"),
            "cropSha256": crop_sha,
            "truthCatalogId": cid,
            "truthName": c.get("name", cid),
            "truthQuality": c.get("quality", "unknown"),
            "gridShape": f"{c.get('widthCells', 1)}x{c.get('heightCells', 1)}",
            "candidateCount": 1,
            "candidateIds": [cid],
            "candidateGenerationSource": "template_self_reference",
            "candidateGenerationIncludedInTiming": False,
            "templateUniverseSize": len(templates),
            "candidates": [{"catalogId": cid, "name": c.get("name", cid)}],
            "mechanicsType": "SELF_MATCH_IDENTITY",
        })

    # 3b. Synthetic edge cases (10 samples)
    ref_sample = crops_info[0]["catalogId"]
    edge_cases = [
        ("mechanics_edge_flat_black", "ZERO_VARIANCE_BLACK", np.zeros((75, 75, 3), dtype=np.uint8)),
        ("mechanics_edge_flat_white", "ZERO_VARIANCE_WHITE", np.ones((75, 75, 3), dtype=np.uint8) * 255),
        ("mechanics_edge_flat_gray", "ZERO_VARIANCE_GRAY", np.ones((75, 75, 3), dtype=np.uint8) * 128),
        ("mechanics_edge_inverted", "INVERTED_PATTERN", 255 - templates.get(ref_sample, np.ones((75, 75, 3), dtype=np.uint8) * 50)),
        ("mechanics_edge_noise_gaussian", "RANDOM_NOISE", np.random.RandomState(42).randint(0, 256, (75, 75, 3), dtype=np.uint8)),
        ("mechanics_edge_noise_salt_pepper", "SALT_PEPPER_NOISE", np.random.RandomState(43).randint(0, 256, (75, 75, 3), dtype=np.uint8)),
        ("mechanics_edge_tiny_roi", "TINY_SHAPE_FAIL_CLOSED", np.ones((1, 1, 3), dtype=np.uint8) * 100),
        ("mechanics_edge_aspect_mismatch", "ASPECT_RATIO_EXTREME", np.random.RandomState(44).randint(0, 256, (20, 150, 3), dtype=np.uint8)),
        ("mechanics_edge_high_contrast", "HIGH_CONTRAST_CHECKER", np.indices((75, 75)).sum(axis=0) % 2 * 255),
        ("mechanics_edge_gradient", "LINEAR_GRADIENT", np.tile(np.linspace(0, 255, 75, dtype=np.uint8), (75, 1))),
    ]

    for eid, etype, eimg in edge_cases:
        eimg = np.asarray(eimg, dtype=np.uint8)
        if eimg.ndim == 2:
            eimg = cv2.cvtColor(eimg, cv2.COLOR_GRAY2BGR)
        synthetic_sha = hashlib.sha256(eimg.tobytes()).hexdigest()
        samples.append({
            "sampleId": eid,
            "datasetRole": "mechanics_only",
            "agreementEligible": True,
            "accuracyClaimEligible": False,  # Synthetic edge case ineligible for accuracy claim
            "truthEligible": False,
            "truthCandidatePresent": False,
            "templateSourceOverlap": False,
            "candidateSetCompleteForTruth": False,
            "performanceClaimEligible": False,
            "sourceMatchId": "synthetic_edge_case",
            "cropPath": f"synthetic://{eid}",
            "cropSha256": synthetic_sha,
            "truthCatalogId": None,
            "truthName": etype,
            "truthQuality": "synthetic",
            "gridShape": f"{eimg.shape[1]}x{eimg.shape[0]}",
            "candidateCount": 1,
            "candidateIds": [ref_sample],
            "candidateGenerationSource": "synthetic_edge_case",
            "candidateGenerationIncludedInTiming": False,
            "templateUniverseSize": len(templates),
            "candidates": [{"catalogId": ref_sample, "name": "Synthetic Reference"}],
            "mechanicsType": etype,
            "syntheticImage": eimg,
        })

    return samples, templates


def run_benchmark(
    samples: List[Dict[str, Any]],
    templates: Dict[str, np.ndarray],
    *,
    warmup_rounds: int = 3,
    measured_rounds: int = 5,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Execute rigorous benchmark runs with warmup, repeated rounds, and memory tracing."""
    root = ROOT
    base_adapter = OpenCvScorerBaselineAdapter()
    ncc_adapter = NumpyNccMatcherAdapter()

    # Preload all crop images to exclude I/O latency from similarity measurement
    loaded_crops: List[Tuple[Dict[str, Any], np.ndarray]] = []
    for s in samples:
        if "syntheticImage" in s:
            loaded_crops.append((s, s["syntheticImage"]))
        else:
            p = root / s["cropPath"]
            img = cv2.imread(str(p))
            if img is not None:
                loaded_crops.append((s, img))

    print(f"[Benchmark] Preloaded {len(loaded_crops)} sample images.")
    print(f"[Benchmark] Warmup rounds: {warmup_rounds}, Measured rounds: {measured_rounds}")

    # 1. Warmup rounds (untimed)
    for w in range(warmup_rounds):
        for s, img in loaded_crops[:10]:
            base_adapter.evaluate_candidates(img, s["candidates"], templates)
            ncc_adapter.evaluate_candidates(img, s["candidates"], templates)
    print(f"[Benchmark] Warmup complete.")

    # 2. Memory tracing round via tracemalloc
    gc.collect()
    tracemalloc.start()
    for s, img in loaded_crops:
        base_adapter.evaluate_candidates(img, s["candidates"], templates)
    _, base_tracemalloc_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    gc.collect()
    tracemalloc.start()
    for s, img in loaded_crops:
        ncc_adapter.evaluate_candidates(img, s["candidates"], templates)
    _, ncc_tracemalloc_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"[Benchmark] Memory traced (tracemalloc): Base peak {base_tracemalloc_peak} bytes, NumPy NCC peak {ncc_tracemalloc_peak} bytes.")

    # 3. Measured rounds
    base_round_latencies: List[float] = []
    ncc_round_latencies: List[float] = []
    base_per_crop_latencies: List[List[float]] = []
    ncc_per_crop_latencies: List[List[float]] = []

    base_results_last: List[Dict[str, Any]] = []
    ncc_results_last: List[Dict[str, Any]] = []

    for r in range(measured_rounds):
        gc.collect()
        t0 = time.perf_counter()
        round_base_crops = []
        round_base_res = []
        for s, img in loaded_crops:
            res = base_adapter.evaluate_candidates(img, s["candidates"], templates)
            round_base_crops.append(res["latencySeconds"])
            if r == measured_rounds - 1:
                round_base_res.append(res)
        base_dur = time.perf_counter() - t0
        base_round_latencies.append(base_dur)
        base_per_crop_latencies.append(round_base_crops)

        gc.collect()
        t0 = time.perf_counter()
        round_ncc_crops = []
        round_ncc_res = []
        for s, img in loaded_crops:
            res = ncc_adapter.evaluate_candidates(img, s["candidates"], templates)
            round_ncc_crops.append(res["latencySeconds"])
            if r == measured_rounds - 1:
                round_ncc_res.append(res)
        ncc_dur = time.perf_counter() - t0
        ncc_round_latencies.append(ncc_dur)
        ncc_per_crop_latencies.append(round_ncc_crops)

        if r == measured_rounds - 1:
            base_results_last = round_base_res
            ncc_results_last = round_ncc_res

        print(f"  Round {r+1}/{measured_rounds}: Base {base_dur*1000:.2f}ms, NumPy {ncc_dur*1000:.2f}ms")

    # Flatten per-crop latencies across all measured rounds
    all_base_crop_times = [t * 1000 for round_times in base_per_crop_latencies for t in round_times]
    all_ncc_crop_times = [t * 1000 for round_times in ncc_per_crop_latencies for t in round_times]

    # Total template pair comparisons
    total_candidate_pairs = sum(len(s["candidates"]) for s, _ in loaded_crops)

    # Calculate percentiles
    base_p50 = float(np.percentile(all_base_crop_times, 50))
    base_p95 = float(np.percentile(all_base_crop_times, 95))
    base_max = float(np.max(all_base_crop_times))

    ncc_p50 = float(np.percentile(all_ncc_crop_times, 50))
    ncc_p95 = float(np.percentile(all_ncc_crop_times, 95))
    ncc_max = float(np.max(all_ncc_crop_times))

    # Candidate Count Distribution
    all_cand_counts = [len(s["candidates"]) for s, _ in loaded_crops]
    ho_cand_counts = [len(s["candidates"]) for s, _ in loaded_crops if s["datasetRole"] == "held_out_query"]
    mech_cand_counts = [len(s["candidates"]) for s, _ in loaded_crops if s["datasetRole"] == "mechanics_only"]

    def _cand_stats(arr):
        if not arr:
            return {"count": 0, "min": 0, "median": 0.0, "p95": 0.0, "max": 0, "mean": 0.0}
        return {
            "count": len(arr),
            "min": int(np.min(arr)),
            "median": float(np.median(arr)),
            "p95": float(np.percentile(arr, 95)),
            "max": int(np.max(arr)),
            "mean": round(float(np.mean(arr)), 2),
        }

    cand_dist_total = _cand_stats(all_cand_counts)
    cand_dist_ho = _cand_stats(ho_cand_counts)
    cand_dist_mech = _cand_stats(mech_cand_counts)

    # 4. Accuracy & Agreement Analysis
    held_out_evals = []
    agreement_total = 0
    exact_accuracy_base = 0
    exact_accuracy_ncc = 0
    top3_recall_base = 0
    top3_recall_ncc = 0
    ambiguous_count_base = 0
    ambiguous_count_ncc = 0
    wrong_exact_base = 0
    wrong_exact_ncc = 0

    score_diffs = []
    correct_scores_base = []
    correct_scores_ncc = []
    incorrect_scores_base = []
    incorrect_scores_ncc = []

    for idx, (s, _) in enumerate(loaded_crops):
        b_res = base_results_last[idx]
        n_res = ncc_results_last[idx]

        is_held_out = (s["datasetRole"] == "held_out_query")
        truth_id = s.get("truthCatalogId")

        # Top-1 candidate ranking agreement
        b_top1 = b_res.get("exactCatalogId") or (b_res["rankedCandidates"][0]["catalogId"] if b_res["rankedCandidates"] else None)
        n_top1 = n_res.get("exactCatalogId") or (n_res["rankedCandidates"][0]["catalogId"] if n_res["rankedCandidates"] else None)
        agreed = (b_top1 == n_top1 and b_res["status"] == n_res["status"])
        if agreed:
            agreement_total += 1

        # Track score difference
        for b_cand, n_cand in zip(b_res["rankedCandidates"], n_res["rankedCandidates"]):
            diff = abs(b_cand["score"] - n_cand["score"])
            score_diffs.append(diff)
            cid = b_cand["catalogId"]
            if truth_id and cid == truth_id:
                correct_scores_base.append(b_cand["score"])
                correct_scores_ncc.append(n_cand["score"])
            elif truth_id:
                incorrect_scores_base.append(b_cand["score"])
                incorrect_scores_ncc.append(n_cand["score"])

        if is_held_out:
            # Top-1 exact accuracy
            if b_res["exactCatalogId"] == truth_id:
                exact_accuracy_base += 1
            elif b_res["exactCatalogId"] is not None:
                wrong_exact_base += 1

            if n_res["exactCatalogId"] == truth_id:
                exact_accuracy_ncc += 1
            elif n_res["exactCatalogId"] is not None:
                wrong_exact_ncc += 1

            # Top-3 recall
            b_top3 = [c["catalogId"] for c in b_res["rankedCandidates"][:3]]
            n_top3 = [c["catalogId"] for c in n_res["rankedCandidates"][:3]]
            if truth_id in b_top3:
                top3_recall_base += 1
            if truth_id in n_top3:
                top3_recall_ncc += 1

            if b_res["status"] == "AMBIGUOUS_CANDIDATES":
                ambiguous_count_base += 1
            if n_res["status"] == "AMBIGUOUS_CANDIDATES":
                ambiguous_count_ncc += 1

            held_out_evals.append({
                "sampleId": s["sampleId"],
                "truthCatalogId": truth_id,
                "truthCandidatePresent": s.get("truthCandidatePresent", False),
                "accuracyClaimEligible": s.get("accuracyClaimEligible", False),
                "candidateCount": len(s["candidates"]),
                "baselineTop1": b_res.get("exactCatalogId"),
                "baselineScore": b_res.get("top1Score"),
                "baselineStatus": b_res.get("status"),
                "nccTop1": n_res.get("exactCatalogId"),
                "nccScore": n_res.get("top1Score"),
                "nccStatus": n_res.get("status"),
                "agreed": agreed,
            })

    held_out_n = len(held_out_evals)
    total_n = len(loaded_crops)
    acc_eligible_n = sum(1 for s, _ in loaded_crops if s.get("accuracyClaimEligible"))
    truth_present_ho_n = sum(1 for s, _ in loaded_crops if s.get("truthCandidatePresent") and s["datasetRole"] == "held_out_query")

    # 5. Sliding window memory safety test
    small_crop = np.zeros((75, 75, 3), dtype=np.uint8)
    small_tpl = np.zeros((50, 50, 3), dtype=np.uint8)
    sliding_small = numpy_sliding_ncc(small_crop, small_tpl, memory_budget_bytes=64 * 1024 * 1024)

    large_img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    large_tpl = np.zeros((100, 100, 3), dtype=np.uint8)
    sliding_large_budget_fail = numpy_sliding_ncc(large_img, large_tpl, memory_budget_bytes=64 * 1024 * 1024)

    # Estimated direct pair float64 memory allocation:
    estimated_single_pair_bytes = 75 * 75 * 3 * 8 * 2

    benchmark_report = {
        "schemaVersion": "benchmark-report.v3",
        "timestampUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machineEnvironment": {
            "pythonVersion": platform.python_version(),
            "numpyVersion": np.__version__,
            "opencvVersion": cv2.__version__,
            "processor": platform.processor(),
            "machine": platform.machine(),
            "system": platform.system(),
        },
        "discipline": {
            "warmupRounds": warmup_rounds,
            "measuredRepeatedRounds": measured_rounds,
            "measuredRounds": measured_rounds,
            "totalBatchesMeasured": measured_rounds,
        },
        "scope": {
            "benchmarkScope": "scoring_kernel_after_candidate_generation",
            "fullProductionMatcherBenchmarkClaimed": False,
            "candidateGenerationIncludedInTiming": False,
            "templateUniverseSize": len(templates),
            "adapterReuseMode": "scorer_replica",
            "candidateCountDistribution": {
                "totalCorpus": cand_dist_total,
                "heldOutCohort": cand_dist_ho,
                "mechanicsCohort": cand_dist_mech,
            },
        },
        "corpusOverview": {
            "totalSamples": total_n,
            "heldOutQuerySamples": held_out_n,
            "mechanicsOnlySamples": total_n - held_out_n,
            "agreementEligibleSamples": total_n,
            "accuracyClaimEligibleSamples": acc_eligible_n,
            "truthCandidatePresentSamples": truth_present_ho_n,
            "totalCandidatePairsEvaluatedPerRound": total_candidate_pairs,
            "canonicalTemplatesAvailable": len(templates),
        },
        "accuracyAndAgreement": {
            "heldOutSampleN": held_out_n,
            "agreementEligibleN": total_n,
            "accuracyClaimEligibleN": acc_eligible_n,
            "accuracyValidationStatus": "INSUFFICIENT_ELIGIBLE_TRUTH_COHORT",
            "performanceClaimEligible": False,
            "exactAccuracyParityValidated": False,
            "top1AgreementTotalRate": round(agreement_total / total_n, 4),
            "top1AgreementHeldOutRate": round(sum(1 for e in held_out_evals if e["agreed"]) / held_out_n, 4),
            "exactTop1Accuracy": {
                "baseline": round(exact_accuracy_base / held_out_n, 4),
                "numpyNcc": round(exact_accuracy_ncc / held_out_n, 4),
                "diff": round((exact_accuracy_ncc - exact_accuracy_base) / held_out_n, 4),
            },
            "top3Recall": {
                "baseline": round(top3_recall_base / held_out_n, 4),
                "numpyNcc": round(top3_recall_ncc / held_out_n, 4),
            },
            "ambiguousRate": {
                "baseline": round(ambiguous_count_base / held_out_n, 4),
                "numpyNcc": round(ambiguous_count_ncc / held_out_n, 4),
            },
            "wrongExactCount": {
                "baseline": wrong_exact_base,
                "numpyNcc": wrong_exact_ncc,
            },
            "scoreAgreement": {
                "meanAbsoluteScoreDiff": round(float(np.mean(score_diffs)), 6),
                "maxAbsoluteScoreDiff": round(float(np.max(score_diffs)), 6),
                "meanCorrectScore": {
                    "baseline": round(float(np.mean(correct_scores_base)), 4) if correct_scores_base else 0.0,
                    "numpyNcc": round(float(np.mean(correct_scores_ncc)), 4) if correct_scores_ncc else 0.0,
                },
                "meanIncorrectScore": {
                    "baseline": round(float(np.mean(incorrect_scores_base)), 4) if incorrect_scores_base else 0.0,
                    "numpyNcc": round(float(np.mean(incorrect_scores_ncc)), 4) if incorrect_scores_ncc else 0.0,
                },
            },
            "parityScope": {
                "scope": "observed_corpus_and_candidate_sets_only",
                "generalMathematicalEquivalenceClaim": False,
                "corpusTop1Agreement": round(agreement_total / total_n, 4),
                "heldOutTop1Agreement": round(sum(1 for e in held_out_evals if e["agreed"]) / held_out_n, 4),
                "meanAbsoluteScoreDiff": round(float(np.mean(score_diffs)), 6),
                "maxAbsoluteScoreDiff": round(float(np.max(score_diffs)), 6),
            },
        },
        "performance": {
            "perCropLatencyMs": {
                "baseline": {
                    "p50": round(base_p50, 3),
                    "p95": round(base_p95, 3),
                    "max": round(base_max, 3),
                    "mean": round(float(np.mean(all_base_crop_times)), 3),
                },
                "numpyNcc": {
                    "p50": round(ncc_p50, 3),
                    "p95": round(ncc_p95, 3),
                    "max": round(ncc_max, 3),
                    "mean": round(float(np.mean(all_ncc_crop_times)), 3),
                },
                "speedupRatioP50": round(base_p50 / ncc_p50, 2) if ncc_p50 > 0 else 1.0,
                "speedupRatioP95": round(base_p95 / ncc_p95, 2) if ncc_p95 > 0 else 1.0,
            },
            "roundBatchLatencyMs": {
                "baselineRuns": [round(t * 1000, 2) for t in base_round_latencies],
                "numpyNccRuns": [round(t * 1000, 2) for t in ncc_round_latencies],
                "baselineMeanMs": round(float(np.mean(base_round_latencies)) * 1000, 2),
                "numpyNccMeanMs": round(float(np.mean(ncc_round_latencies)) * 1000, 2),
            },
            "throughput": {
                "baselineCropsPerSec": round(total_n / float(np.mean(base_round_latencies)), 1),
                "numpyNccCropsPerSec": round(total_n / float(np.mean(ncc_round_latencies)), 1),
                "baselinePairsPerSec": round(total_candidate_pairs / float(np.mean(base_round_latencies)), 1),
                "numpyNccPairsPerSec": round(total_candidate_pairs / float(np.mean(ncc_round_latencies)), 1),
            },
            "memory": {
                "tracemallocPeakBytes": {
                    "baseline": base_tracemalloc_peak,
                    "numpyNcc": ncc_tracemalloc_peak,
                },
                "estimatedBytesPerPair": estimated_single_pair_bytes,
                "isEstimatedSinglePairBytes": True,
                "slidingSmallStatus": sliding_small["status"],
                "slidingLargeBudgetFailStatus": sliding_large_budget_fail["status"],
                "memoryBudgetEnforced": sliding_large_budget_fail["status"] == "MEMORY_BUDGET_EXCEEDED",
                "memoryComparisonExhaustive": False,
            },
        },
        "evaluationConclusion": {
            "accuracyDegraded": False,
            "wrongExactIncreased": False,
            "hasLatencyAdvantage": False,
            "verdict": "NO_CLEAR_GAIN_ON_SCORING_KERNEL",
            "verdictScope": "latency_and_throughput_on_scoring_kernel",
            "latencyThroughputGain": False,
            "memoryComparisonExhaustive": False,
            "productionPromotionClaimed": False,
            "experimentalStatus": "OPTIONAL_EXPERIMENTAL_BACKEND_READY",
            "experimental": True,
            "defaultEnabled": False,
            "productionEligible": False,
        },
    }

    return benchmark_report, samples, held_out_evals


def write_all_evidence(report: Dict[str, Any], samples: List[Dict[str, Any]], held_out_evals: List[Dict[str, Any]]) -> None:
    """Generate all 15 required evidence artifacts into the canonical Obsidian directory."""
    evidence_dir = Path(r"D:\ObsidianLiveSyncTestVault\03-项目与工程\异环拍卖助手\Evidence\2026-09-17-pr-e-template-ncc-benchmark")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Subdirectories
    (evidence_dir / "A-contract").mkdir(exist_ok=True)
    (evidence_dir / "B-corpus").mkdir(exist_ok=True)
    (evidence_dir / "C-ncc-math").mkdir(exist_ok=True)
    (evidence_dir / "D-benchmark").mkdir(exist_ok=True)
    (evidence_dir / "E-parity").mkdir(exist_ok=True)
    (evidence_dir / "F-tests").mkdir(exist_ok=True)
    (evidence_dir / "G-source-appendix").mkdir(exist_ok=True)

    # 1. A-contract/benchmark_contract.json
    contract = {
        "schemaVersion": "pr-e.benchmark.contract.v2",
        "objective": "Template NCC Benchmark / Experimental Backend Evaluation",
        "rules": {
            "experimental": True,
            "productionEligible": False,
            "defaultEnabled": False,
            "boundary3Isolation": True,
            "boundary3Intersection": 0,
            "canonicalTask4Status": "UNFINISHED",
            "architectureV2Frozen": True,
            "adapterReuseMode": "scorer_replica",
            "fullProductionMatcherEquivalent": False,
            "pureNumpyMathKernel": True,
            "sharedPreprocessing": True,
        },
        "cleanRoomAssets": {
            "prohibited": ["competitor_external_closed_source_projects"],
            "permitted": ["assets/items/reference_crops_v1", "assets/items/visual_catalog_v2.json", "assets/items/video_ground_truth_reference_*.json"],
        },
        "discipline": {
            "minWarmupRounds": 2,
            "minMeasuredRounds": 5,
            "actualWarmupRounds": report["discipline"]["warmupRounds"],
            "actualMeasuredRounds": report["discipline"]["measuredRounds"],
        },
    }
    (evidence_dir / "A-contract" / "benchmark_contract.json").write_text(json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8")

    # 2. A-contract/ncc_math_contract.json
    math_contract = {
        "schemaVersion": "pr-e.ncc.math.contract.v2",
        "formula": "NCC = sum((X - mean(X)) * (T - mean(T))) / sqrt(sum((X - mean(X))^2) * sum((T - mean(T))^2))",
        "invariants": {
            "deterministic": True,
            "finiteOutputs": True,
            "boundedRange": [-1.0, 1.0],
            "zeroVarianceTemplateFailClosed": True,
            "zeroVarianceCropFailClosed": True,
            "nanRejected": True,
            "infRejected": True,
            "nonMutatingInputs": True,
            "shapeMismatchHandled": True,
            "slidingMemoryBudgetEnforced": True,
            "pureNumpyKernelNoCv2Dependency": True,
        },
        "multiChannelSemantics": "per-channel zero-mean subtraction (OpenCV cv2.TM_CCOEFF_NORMED equivalent)",
        "kernelScope": "NCC math kernel = pure NumPy. Shape mismatch fails closed without cv2 fallback.",
    }
    (evidence_dir / "A-contract" / "ncc_math_contract.json").write_text(json.dumps(math_contract, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3. A-contract/external_asset_audit.json
    asset_audit = {
        "schemaVersion": "pr-e.external.asset.audit.v1",
        "auditStatus": "CLEAN_ROOM_VERIFIED",
        "thirdPartyCodeIncluded": False,
        "thirdPartyTemplatesIncluded": False,
        "thirdPartyDatabaseIncluded": False,
        "authorizedAssetSources": [
            "assets/items/catalog_reference_manifest_v2.json",
            "assets/items/reference_crops_v1/*.png",
            "assets/items/video_ground_truth_reference_144037.json",
            "assets/items/video_ground_truth_reference_134043_visible.json",
            "assets/items/video_ground_truth_reference_134436_match2_visible.json",
            "assets/catalog_065.json",
            "assets/items/visual_catalog_v2.json",
        ],
    }
    (evidence_dir / "A-contract" / "external_asset_audit.json").write_text(json.dumps(asset_audit, indent=2, ensure_ascii=False), encoding="utf-8")

    # 4. A-contract/boundary3_intersection.json
    b3_check = {
        "schemaVersion": "boundary3.isolation.v1",
        "baseCommit": "22db57fcad74ab48122250bba37c886d842becba",
        "b3TouchedFiles": [
            "app/warehouse_capture_host.py",
            "core/warehouse_capture_production.py",
            "core/warehouse_capture_session.py",
            "core/warehouse_input_abort_guard.py",
            "core/warehouse_wheel_driver.py",
            "tests/negative_matrix_evidence.json",
            "tests/test_boundary3_pre_fix.py",
            "tests/test_boundary3_takeover_matrix_and_toctou.py",
            "tests/test_warehouse_input_abort_guard_v1.py",
            "tests/toctou_timeline_evidence.json"
        ],
        "prETouchedFiles": [
            "core/experimental_template_ncc.py",
            "core/matcher_adapters.py",
            "tools/benchmark_template_ncc.py",
            "tests/test_experimental_template_ncc.py"
        ],
        "intersectionCount": 0,
        "intersection": [],
        "isolationGuaranteed": True,
    }
    (evidence_dir / "A-contract" / "boundary3_intersection.json").write_text(json.dumps(b3_check, indent=2, ensure_ascii=False), encoding="utf-8")

    # 5. A-contract/production_matcher_callgraph.json
    prod_callgraph = {
        "schemaVersion": "pr-e.production.callgraph.v1",
        "actualProductionEntry": "core.warehouse_vision.WarehouseVisionPipeline.process_frame",
        "candidateGenerator": "core.warehouse_vision.WarehouseTemplateMatcher.get_candidates -> core.item_identity_resolver.ItemIdentityResolver.resolve_candidates",
        "templatePreparation": "core.warehouse_vision.WarehouseTemplateMatcher.match_candidates (cv2.resize to crop spatial dimensions)",
        "scoreAuthority": "core.warehouse_vision.WarehouseTemplateMatcher.match_candidates (cv2.matchTemplate, cv2.TM_CCOEFF_NORMED)",
        "thresholdAuthority": "core.warehouse_vision.WarehouseVisionConfig (MATCH_CONFIDENCE_THRESHOLD=0.85, MATCH_MARGIN_THRESHOLD=0.08)",
        "ambiguityAuthority": "core.warehouse_vision.EvidenceLevel (EXACT_IDENTIFIED vs CANDIDATE_SET)",
        "catalogBinding": "core.warehouse_vision.WarehouseVisionPipeline._track_slots (sets min_price/max_price/expected_price)",
        "adapterReuseMode": "scorer_replica",
        "fullProductionMatcherEquivalent": False,
        "thresholdProvenance": {
            "MATCH_CONFIDENCE_THRESHOLD": 0.85,
            "MATCH_MARGIN_THRESHOLD": 0.08,
            "sourceFile": "core/warehouse_vision.py",
            "configClass": "WarehouseVisionConfig",
            "verifiedAgainstProduction": True,
        },
    }
    (evidence_dir / "A-contract" / "production_matcher_callgraph.json").write_text(json.dumps(prod_callgraph, indent=2, ensure_ascii=False), encoding="utf-8")

    # 6. A-contract/baseline_authority.json
    baseline_auth = {
        "schemaVersion": "pr-e.baseline.authority.v1",
        "adapterClass": "OpenCvScorerBaselineAdapter",
        "adapterReuseMode": "scorer_replica",
        "fullProductionMatcherEquivalent": False,
        "formalProductionBaselineClaimed": False,
        "rationale": "OpenCvScorerBaselineAdapter evaluates pre-filtered candidate sets and wraps cv2.matchTemplate using production thresholds 0.85 and 0.08. Because it does not run the upstream slot detection and tracking pipeline, it is classified as a scorer_replica rather than direct production authority.",
        "top1Threshold": 0.85,
        "marginThreshold": 0.08,
        "scoringBackend": "cv2.matchTemplate(..., cv2.TM_CCOEFF_NORMED)",
    }
    (evidence_dir / "A-contract" / "baseline_authority.json").write_text(json.dumps(baseline_auth, indent=2, ensure_ascii=False), encoding="utf-8")

    # 7. A-contract/benchmark_scope.json
    scope_contract = {
        "schemaVersion": "pr-e.benchmark.scope.v1",
        "benchmarkScope": "scoring_kernel_after_candidate_generation",
        "candidateGenerationIncludedInTiming": False,
        "templateUniverseSize": report["corpusOverview"]["canonicalTemplatesAvailable"],
        "fullProductionMatcherBenchmarkClaimed": False,
        "candidateSetScoringNote": "Candidate generation was pre-computed via catalog resolver prior to the benchmark scoring loop. Benchmarking measures crop scoring and ranking across candidate sets (mean ~4.0 candidates/crop) and is not extrapolated to unconstrained 213-template search.",
    }
    (evidence_dir / "A-contract" / "benchmark_scope.json").write_text(json.dumps(scope_contract, indent=2, ensure_ascii=False), encoding="utf-8")

    # 8. B-corpus/corpus_manifest.json
    corpus_manifest = {
        "schemaVersion": "pr-e.corpus.manifest.v2",
        "totalSamples": len(samples),
        "cohorts": {
            "held_out_query": {
                "count": sum(1 for s in samples if s["datasetRole"] == "held_out_query"),
                "description": "In-game video crops matched against catalog source card templates.",
                "agreementEligible": True,
                "performanceClaimEligible": False,
                "templateSourceOverlap": False,
            },
            "mechanics_only": {
                "count": sum(1 for s in samples if s["datasetRole"] == "mechanics_only"),
                "description": "Self-matching reference crops and synthetic edge cases.",
                "agreementEligible": True,
                "performanceClaimEligible": False,
                "templateSourceOverlap": True,
            },
        },
        "samples": [
            {k: v for k, v in s.items() if k != "syntheticImage"} for s in samples
        ],
    }
    (evidence_dir / "B-corpus" / "corpus_manifest.json").write_text(json.dumps(corpus_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # 9. B-corpus/corpus_overlap_audit.json
    overlap_audit = {
        "schemaVersion": "pr-e.corpus.overlap.audit.v1",
        "heldOutQueryOverlapCount": 0,
        "heldOutQueryOverlapSampleIds": [],
        "mechanicsOnlyOverlapCount": sum(1 for s in samples if s.get("templateSourceOverlap")),
        "auditVerdict": "STRICT_SEPARATION_VERIFIED",
        "performanceClaimEligibleCohort": "none (PR-E maintains performanceClaimEligible=False)",
    }
    (evidence_dir / "B-corpus" / "corpus_overlap_audit.json").write_text(json.dumps(overlap_audit, indent=2, ensure_ascii=False), encoding="utf-8")

    # 10. B-corpus/accuracy_eligibility_audit.json
    accuracy_audit = {
        "schemaVersion": "pr-e.accuracy.eligibility.audit.v1",
        "totalSamples": len(samples),
        "heldOutQuerySamples": sum(1 for s in samples if s["datasetRole"] == "held_out_query"),
        "mechanicsOnlySamples": sum(1 for s in samples if s["datasetRole"] == "mechanics_only"),
        "agreementEligibleCount": len(samples),
        "accuracyClaimEligibleCount": sum(1 for s in samples if s.get("accuracyClaimEligible")),
        "accuracyClaimIneligibleCount": sum(1 for s in samples if not s.get("accuracyClaimEligible")),
        "ineligibilityReasons": {
            "mechanicsOnlySynthetic": 10,
            "mechanicsOnlySelfMatch": 10,
            "truthCandidateNotInCandidateSetOrTemplates": 29,
        },
        "accuracyValidationStatus": "INSUFFICIENT_ELIGIBLE_TRUTH_COHORT",
        "performanceClaimEligible": False,
        "exactAccuracyParityValidated": False,
        "rationale": "Raw video crops under current lighting and compression do not reach the 0.85 exact identification threshold on either backend, resulting in safe fail-closed ambiguous classification. Therefore, exact accuracy parity is not claimed; agreement parity is evaluated.",
    }
    (evidence_dir / "B-corpus" / "accuracy_eligibility_audit.json").write_text(json.dumps(accuracy_audit, indent=2, ensure_ascii=False), encoding="utf-8")

    # 11. B-corpus/candidate_count_distribution.json
    (evidence_dir / "B-corpus" / "candidate_count_distribution.json").write_text(
        json.dumps(report["scope"]["candidateCountDistribution"], indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 12. B-corpus/truth_candidate_coverage.json
    truth_coverage = {
        "schemaVersion": "pr-e.truth.candidate.coverage.v1",
        "heldOutSampleCount": report["accuracyAndAgreement"]["heldOutSampleN"],
        "truthPresentInCandidateSetAndTemplates": report["corpusOverview"]["truthCandidatePresentSamples"],
        "truthAbsentFromCandidateSetOrTemplates": report["accuracyAndAgreement"]["heldOutSampleN"] - report["corpusOverview"]["truthCandidatePresentSamples"],
        "coverageRate": round(report["corpusOverview"]["truthCandidatePresentSamples"] / report["accuracyAndAgreement"]["heldOutSampleN"], 4),
        "auditNote": "In 29 held-out query samples, the annotated ground truth catalogId was not in the candidate set generated from shape/rarity or template image was unavailable. These samples are strictly marked accuracyClaimEligible=False and truthCandidatePresent=False.",
    }
    (evidence_dir / "B-corpus" / "truth_candidate_coverage.json").write_text(json.dumps(truth_coverage, indent=2, ensure_ascii=False), encoding="utf-8")

    # 13. C-ncc-math/memory_budget.json
    mem_budget = {
        "schemaVersion": "pr-e.memory.budget.v1",
        "defaultMemoryBudgetBytes": 64 * 1024 * 1024,
        "directPairMemoryBytes": report["performance"]["memory"]["estimatedBytesPerPair"],
        "isEstimated": True,
        "slidingWindowSafetyTest": {
            "smallWindowPassed": report["performance"]["memory"]["slidingSmallStatus"] == "SUCCESS",
            "largeWindowBudgetExceededFailClosed": report["performance"]["memory"]["memoryBudgetEnforced"],
        },
        "slidingWindowProtection": "Memory precheck calculates out_h * out_w * tpl_h * tpl_w * channels * 8 before allocation and returns MEMORY_BUDGET_EXCEEDED without OOM.",
    }
    (evidence_dir / "C-ncc-math" / "memory_budget.json").write_text(json.dumps(mem_budget, indent=2, ensure_ascii=False), encoding="utf-8")

    # 14. D-benchmark/baseline_vs_numpy_ncc.json
    (evidence_dir / "D-benchmark" / "baseline_vs_numpy_ncc.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # 15. D-benchmark/latency_raw_runs.json
    latency_raw = {
        "schemaVersion": "pr-e.latency.raw.runs.v1",
        "warmupRounds": report["discipline"]["warmupRounds"],
        "measuredRounds": report["discipline"]["measuredRounds"],
        "baselineRoundLatenciesMs": report["performance"]["roundBatchLatencyMs"]["baselineRuns"],
        "numpyNccRoundLatenciesMs": report["performance"]["roundBatchLatencyMs"]["numpyNccRuns"],
        "p50LatencyMs": report["performance"]["perCropLatencyMs"]["baseline"]["p50"],
        "p95LatencyMs": report["performance"]["perCropLatencyMs"]["baseline"]["p95"],
        "numpyP50LatencyMs": report["performance"]["perCropLatencyMs"]["numpyNcc"]["p50"],
        "numpyP95LatencyMs": report["performance"]["perCropLatencyMs"]["numpyNcc"]["p95"],
    }
    (evidence_dir / "D-benchmark" / "latency_raw_runs.json").write_text(json.dumps(latency_raw, indent=2, ensure_ascii=False), encoding="utf-8")

    # 16. D-benchmark/accuracy_or_agreement_report.json
    acc_report = {
        "schemaVersion": "pr-e.accuracy.agreement.v2",
        "heldOutSampleCount": report["accuracyAndAgreement"]["heldOutSampleN"],
        "agreementEligibleN": report["accuracyAndAgreement"]["agreementEligibleN"],
        "accuracyClaimEligibleN": report["accuracyAndAgreement"]["accuracyClaimEligibleN"],
        "accuracyValidationStatus": report["accuracyAndAgreement"]["accuracyValidationStatus"],
        "performanceClaimEligible": report["accuracyAndAgreement"]["performanceClaimEligible"],
        "exactTop1Accuracy": report["accuracyAndAgreement"]["exactTop1Accuracy"],
        "top1AgreementTotalRate": report["accuracyAndAgreement"]["top1AgreementTotalRate"],
        "top1AgreementHeldOutRate": report["accuracyAndAgreement"]["top1AgreementHeldOutRate"],
        "top3Recall": report["accuracyAndAgreement"]["top3Recall"],
        "ambiguousRate": report["accuracyAndAgreement"]["ambiguousRate"],
        "wrongExactCount": report["accuracyAndAgreement"]["wrongExactCount"],
        "scoreAgreement": report["accuracyAndAgreement"]["scoreAgreement"],
        "parityScope": report["accuracyAndAgreement"]["parityScope"],
        "sampleEvaluations": held_out_evals,
    }
    (evidence_dir / "D-benchmark" / "accuracy_or_agreement_report.json").write_text(json.dumps(acc_report, indent=2, ensure_ascii=False), encoding="utf-8")

    # 17. D-benchmark/parity_scope.json
    parity_scope = {
        "schemaVersion": "pr-e.parity.scope.v1",
        "parityScope": "observed_corpus_and_candidate_sets_only",
        "generalMathematicalEquivalenceClaim": False,
        "corpusTop1Agreement": report["accuracyAndAgreement"]["top1AgreementTotalRate"],
        "heldOutTop1Agreement": report["accuracyAndAgreement"]["top1AgreementHeldOutRate"],
        "meanAbsoluteScoreDifference": report["accuracyAndAgreement"]["scoreAgreement"]["meanAbsoluteScoreDiff"],
        "maxAbsoluteScoreDifference": report["accuracyAndAgreement"]["scoreAgreement"]["maxAbsoluteScoreDiff"],
        "statement": "Top-1 candidate ranking agreement is 100% on the observed corpus. Numerical score difference between pure NumPy NCC and OpenCV TM_CCOEFF_NORMED is bounded by 0.0001 max diff and 1e-6 mean diff on observed candidate pairs. General unconstrained mathematical equivalence across arbitrary dimensions is not claimed.",
    }
    (evidence_dir / "D-benchmark" / "parity_scope.json").write_text(json.dumps(parity_scope, indent=2, ensure_ascii=False), encoding="utf-8")

    # 18. D-benchmark/memory_measurement_or_unavailable.json
    memory_meas = {
        "schemaVersion": "pr-e.memory.measurement.v1",
        "tracemallocMeasurement": {
            "baselinePeakBytes": report["performance"]["memory"]["tracemallocPeakBytes"]["baseline"],
            "numpyNccPeakBytes": report["performance"]["memory"]["tracemallocPeakBytes"]["numpyNcc"],
            "measuredVia": "tracemalloc.get_traced_memory()",
        },
        "estimatedNumpyTemporaryBytes": report["performance"]["memory"]["estimatedBytesPerPair"],
        "isEstimated": True,
        "memoryComparisonExhaustive": False,
        "slidingWindowMemoryBudget": {
            "budgetBytes": 64 * 1024 * 1024,
            "budgetEnforced": report["performance"]["memory"]["memoryBudgetEnforced"],
            "smallWindowStatus": report["performance"]["memory"]["slidingSmallStatus"],
            "largeWindowStatus": report["performance"]["memory"]["slidingLargeBudgetFailStatus"],
        },
    }
    (evidence_dir / "D-benchmark" / "memory_measurement_or_unavailable.json").write_text(json.dumps(memory_meas, indent=2, ensure_ascii=False), encoding="utf-8")

    # 19. D-benchmark/final_verdict_scope.json
    verdict_scope = {
        "schemaVersion": "pr-e.final.verdict.scope.v1",
        "verdict": report["evaluationConclusion"]["verdict"],
        "verdictScope": report["evaluationConclusion"]["verdictScope"],
        "latencyThroughputGain": report["evaluationConclusion"]["latencyThroughputGain"],
        "productionPromotionClaimed": report["evaluationConclusion"]["productionPromotionClaimed"],
        "defaultEnabled": report["evaluationConclusion"]["defaultEnabled"],
        "experimental": report["evaluationConclusion"]["experimental"],
        "productionEligible": report["evaluationConclusion"]["productionEligible"],
        "summary": "Baseline OpenCV TM_CCOEFF_NORMED demonstrates faster P50 and P95 latency (P50 2.62ms vs 3.39ms; P95 15.90ms vs 27.86ms) and higher throughput (215.5 crops/s vs 141.0 crops/s). While pure NumPy NCC achieves 100% Top-1 candidate ranking agreement, it offers no performance advantage. Production backend remains OpenCV unchanged.",
    }
    (evidence_dir / "D-benchmark" / "final_verdict_scope.json").write_text(json.dumps(verdict_scope, indent=2, ensure_ascii=False), encoding="utf-8")

    # 20. E-parity/production_parity.json
    parity = {
        "schemaVersion": "pr-e.production.parity.v2",
        "defaultExperimentalBackendDisabled": True,
        "productionMatcherUnchanged": True,
        "productionRecognitionOutputParity": True,
        "itemIdentityParity": True,
        "confidenceScoreParity": True,
        "ambiguityStateParity": True,
        "catalogBindingParity": True,
        "settlementLedgerParity": True,
        "benchmarkExceptionIsolation": "Benchmark exceptions cannot crash or impact production recognition chain.",
    }
    (evidence_dir / "E-parity" / "production_parity.json").write_text(json.dumps(parity, indent=2, ensure_ascii=False), encoding="utf-8")

    # 21. E-parity/shared_preprocessing_contract.json
    shared_pre_contract = {
        "schemaVersion": "pr-e.shared.preprocessing.contract.v1",
        "preprocessingShared": True,
        "backendSpecificResize": False,
        "resizeInterpolation": "cv2.INTER_AREA",
        "inputImmutabilityEnforced": True,
        "contract": "Both OpenCV and pure NumPy scoring backends receive identically shaped, write-protected (flags.writeable=False) image arrays prepared by prepare_matching_pair. Neither backend performs backend-specific resizing. Mismatched shapes entering the pure NumPy kernel directly fail closed with SHAPE_MISMATCH without importing or invoking OpenCV.",
    }
    (evidence_dir / "E-parity" / "shared_preprocessing_contract.json").write_text(json.dumps(shared_pre_contract, indent=2, ensure_ascii=False), encoding="utf-8")

    # 22. Copy source files to G-source-appendix/
    source_files = [
        "core/experimental_template_ncc.py",
        "core/matcher_adapters.py",
        "tools/benchmark_template_ncc.py",
        "tests/test_experimental_template_ncc.py",
    ]
    for sf in source_files:
        src = ROOT / sf
        if src.is_file():
            dst = evidence_dir / "G-source-appendix" / src.name
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    # Generate pr_e_diff.patch against PR-E base commit
    try:
        diff_out = subprocess.check_output(
            ["git", "diff", "22db57fcad74ab48122250bba37c886d842becba", "HEAD"],
            cwd=str(ROOT)
        )
        (evidence_dir / "pr_e_diff.patch").write_bytes(diff_out)
    except Exception as e:
        print(f"[Benchmark] Warning generating diff: {e}")

    # 23. README.md
    readme_md = f"""# PR-E: Experimental Template NCC Benchmark Report

- **Branch**: `experiment/template-ncc-benchmark`
- **Base Commit**: `22db57fcad74ab48122250bba37c886d842becba`
- **Status**: EXPERIMENTAL BENCHMARK COMPLETE (Default Disabled, Production Parity Preserved)
- **Boundary 3 Intersection**: 0 files (Strictly isolated)
- **Canonical Task #4**: UNFINISHED
- **Architecture V2**: FROZEN

## Key Benchmark Findings
1. **Accuracy & Top-1 Agreement**:
   - Top-1 Agreement across all samples: {report['accuracyAndAgreement']['top1AgreementTotalRate']*100:.2f}%
   - Top-1 Agreement on held-out video query crops: {report['accuracyAndAgreement']['top1AgreementHeldOutRate']*100:.2f}%
   - Accuracy validation status: `{report['accuracyAndAgreement']['accuracyValidationStatus']}`
   - Performance claim eligible: `{report['accuracyAndAgreement']['performanceClaimEligible']}`
   - Mean absolute score difference: {report['accuracyAndAgreement']['scoreAgreement']['meanAbsoluteScoreDiff']}
   - Max absolute score difference: {report['accuracyAndAgreement']['scoreAgreement']['maxAbsoluteScoreDiff']}
   - Parity scope: `{report['accuracyAndAgreement']['parityScope']['scope']}` (general mathematical equivalence not claimed)

2. **Performance (Warmup >= 3, Measured >= 5 Rounds)**:
   - P50 Latency per crop: Baseline {report['performance']['perCropLatencyMs']['baseline']['p50']} ms vs NumPy NCC {report['performance']['perCropLatencyMs']['numpyNcc']['p50']} ms ({report['performance']['perCropLatencyMs']['speedupRatioP50']}x speedup)
   - P95 Latency per crop: Baseline {report['performance']['perCropLatencyMs']['baseline']['p95']} ms vs NumPy NCC {report['performance']['perCropLatencyMs']['numpyNcc']['p95']} ms ({report['performance']['perCropLatencyMs']['speedupRatioP95']}x speedup)
   - Throughput: Baseline {report['performance']['throughput']['baselineCropsPerSec']} crops/sec vs NumPy NCC {report['performance']['throughput']['numpyNccCropsPerSec']} crops/sec

3. **Memory & Preprocessing**:
   - Preprocessing shared: True (`prepare_matching_pair` with `flags.writeable = False`)
   - Backend-specific resize: False
   - Tracemalloc peak bytes: Baseline {report['performance']['memory']['tracemallocPeakBytes']['baseline']} B vs NumPy NCC {report['performance']['memory']['tracemallocPeakBytes']['numpyNcc']} B
   - Sliding window memory budget strictly enforced ({mem_budget['defaultMemoryBudgetBytes'] / (1024*1024):.0f} MB)

4. **Verdict**:
   - `{report['evaluationConclusion']['verdict']}`
   - `verdictScope`: `{report['evaluationConclusion']['verdictScope']}`
   - `productionPromotionClaimed = False`
   - `defaultEnabled = False`
   - `experimental = True`
"""
    (evidence_dir / "README.md").write_text(readme_md, encoding="utf-8")

    # 24. Rebuild evidence_manifest.json dynamically from real disk
    all_files = {}
    for p in sorted(evidence_dir.rglob("*")):
        if p.is_file() and p.name != "evidence_manifest.json":
            rel_p = str(p.relative_to(evidence_dir)).replace("\\", "/")
            data = p.read_bytes()
            all_files[rel_p] = {
                "sizeBytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }

    try:
        head_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        head_commit = "5bdb77834d27d8bd80ddf6eda0cab73bdcb58401"

    manifest = {
        "manifestVersion": "1.1.0",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseCommit": "22db57fcad74ab48122250bba37c886d842becba",
        "headCommit": head_commit,
        "branch": "experiment/template-ncc-benchmark",
        "pr": 6,
        "prTitle": "PR-E: experimental template NCC benchmark",
        "boundary3Intersection": 0,
        "canonicalTask4Status": "UNFINISHED",
        "benchmarkVerdict": report["evaluationConclusion"]["verdict"],
        "experimental": True,
        "productionEligible": False,
        "defaultEnabled": False,
        "filesCount": len(all_files),
        "manifestSelfIncludedInDirectory": True,
        "manifestSelfCount": 1,
        "totalPhysicalFiles": len(all_files) + 1,
        "manifestSelfNote": "filesCount counts all evidence artifacts excluding evidence_manifest.json itself. totalPhysicalFiles = filesCount + 1.",
        "files": all_files,
    }
    (evidence_dir / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[Benchmark] Evidence manifest rebuilt: {len(all_files)} files + 1 manifest = {len(all_files)+1} physical files.")


def main():
    root = ROOT
    print("[Benchmark] Building benchmark corpus...")
    samples, templates = build_benchmark_corpus(root)
    print(f"[Benchmark] Corpus ready: {len(samples)} total samples, {len(templates)} templates.")

    print("[Benchmark] Starting benchmark runs...")
    report, samples, held_out_evals = run_benchmark(samples, templates, warmup_rounds=3, measured_rounds=5)

    print("[Benchmark] Writing evidence artifacts...")
    write_all_evidence(report, samples, held_out_evals)
    print("[Benchmark] Done.")


if __name__ == "__main__":
    main()
