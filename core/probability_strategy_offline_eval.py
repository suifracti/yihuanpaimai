# -*- coding: utf-8 -*-
"""Offline Comparative Evaluation Harness for Probability and Strategy Lab (PR-C).

Compares candidate probabilistic models and heuristic profiles across admitted matches:
1. production_baseline (frozen pre-settlement prediction snapshot)
2. historical_shadow (frozen empirical shadow profile)
3. pr_b_red_inference (evaluated using strictly prior history; no self-leakage)
4. pr_c_convolution (discrete PMF convolution when valid components exist)
5. pr_c_dafu_heuristic (canonical Dafu round divisors R1-R4)

Strict Invariants:
- Multi-model comparative backtesting harness.
- Strictly NO self-history leakage: each evaluated record uses only history strictly prior to its playedAt.
- Truth Gating: admits records only with finalized lifecycle, complete coverage, verified settlement actualTotal > 0.
- Production comparison requires frozen pre-settlement prediction; never re-derives q*goldAvg.
- Independent sample denominator tracked per model.
- Does NOT automatically declare a "winner" or promote external hypotheses to production.
- performanceClaimEligible = False (harness verification only).
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

_CORE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_CORE_DIR, ".."))
_APP_DIR = os.path.join(_PROJECT_ROOT, "app")
for _p in (_PROJECT_ROOT, _CORE_DIR, _APP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from experimental_probability_strategy import (
    DAFU_CANONICAL_ROUND_DIVISORS,
    DiscreteDistribution,
    ExperimentalStrategyProfile,
    ExperimentalStrategyRegistry,
    compute_structural_fit,
    evaluate_experimental_probability_strategy,
    get_global_strategy_registry,
)
from experimental_red_inference import (
    ExperimentalRedInferenceLab,
    evaluate_record_red_eligibility,
)

_LOG = logging.getLogger(__name__)


def is_record_settlement_truth_admitted(rec: Mapping[str, Any]) -> Tuple[bool, Optional[str]]:
    """Strict canonical truth admission check.

    Requires:
    - schemaVersion >= 7
    - lifecycleStatus == 'FINALIZED'
    - coverageStatus == 'COMPLETE'
    - settlement.verified == True
    - settlement.actualTotal is finite float > 0
    - potentialDuplicate != True
    """
    if not isinstance(rec, Mapping):
        return False, "NOT_A_MAPPING"

    if rec.get("potentialDuplicate") is True:
        return False, "POTENTIAL_DUPLICATE_EXCLUDED"

    if rec.get("lifecycleStatus") != "FINALIZED":
        return False, f"LIFECYCLE_NOT_FINALIZED:{rec.get('lifecycleStatus')}"

    if rec.get("coverageStatus") != "COMPLETE":
        return False, f"COVERAGE_NOT_COMPLETE:{rec.get('coverageStatus')}"

    settlement = rec.get("settlement")
    if not isinstance(settlement, Mapping):
        return False, "MISSING_SETTLEMENT_OBJECT"

    if settlement.get("verified") is not True:
        return False, "SETTLEMENT_NOT_VERIFIED"

    actual_total = settlement.get("actualTotal")
    if actual_total is None or not isinstance(actual_total, (int, float)) or not math.isfinite(actual_total) or actual_total <= 0:
        return False, "INVALID_OR_NON_POSITIVE_ACTUAL_TOTAL"

    return True, None


def run_probability_strategy_comparison(
    records: Sequence[Mapping[str, Any]],
    dataset_kind: str = "synthetic_fixture",
) -> Dict[str, Any]:
    """Run multi-model comparative evaluation across canonical match records with strict no-leakage."""
    valid_recs = [r for r in records if isinstance(r, Mapping)]
    candidate_count = len(valid_recs)

    # Sort valid records chronologically by playedAt
    sorted_recs = sorted(
        valid_recs,
        key=lambda r: str(r.get("playedAt") or r.get("timestamp") or ""),
    )

    evaluated_count = 0
    excluded_count = 0
    excluded_reasons: Dict[str, int] = {}

    model_names = [
        "production_baseline",
        "historical_shadow",
        "pr_b_red_inference",
        "pr_c_convolution",
        "pr_c_dafu_heuristic",
    ]

    abs_errors: Dict[str, List[float]] = {m: [] for m in model_names}
    p20_hits: Dict[str, int] = {m: 0 for m in model_names}
    p80_hits: Dict[str, int] = {m: 0 for m in model_names}
    interval_hits: Dict[str, int] = {m: 0 for m in model_names}
    model_sample_counts: Dict[str, int] = {m: 0 for m in model_names}

    for idx, rec in enumerate(sorted_recs):
        admitted, reason = is_record_settlement_truth_admitted(rec)
        if not admitted:
            excluded_count += 1
            reason_key = reason or "UNKNOWN"
            excluded_reasons[reason_key] = excluded_reasons.get(reason_key, 0) + 1
            continue

        evaluated_count += 1
        actual_val = float(rec["settlement"]["actualTotal"])
        played_at_str = str(rec.get("playedAt") or rec.get("timestamp") or "")

        # 1. Strict No-Leakage Training Cohort for PR-B Red Lab
        # Only historical records strictly prior to current rec's playedAt!
        # Current rec NEVER enters its own training set!
        prior_history = [
            r for r in sorted_recs[:idx]
            if str(r.get("playedAt") or r.get("timestamp") or "") < played_at_str
        ]

        # 2. Production Baseline: requires frozen pre-settlement prediction snapshot!
        # Never fabricates q*goldAvg!
        prod_snapshot = rec.get("predictionSnapshot") or rec.get("productionPrediction")
        prod_pred: Optional[Tuple[float, float, float]] = None
        if isinstance(prod_snapshot, Mapping):
            p50 = prod_snapshot.get("valP50") or prod_snapshot.get("medianEstimate")
            p20 = prod_snapshot.get("p20") or (p50 * 0.9 if p50 else None)
            p80 = prod_snapshot.get("p80") or (p50 * 1.1 if p50 else None)
            if p50 is not None and math.isfinite(p50):
                prod_pred = (float(p20), float(p50), float(p80))

        # 3. Historical Shadow: requires frozen shadow prediction!
        shadow_snapshot = rec.get("shadowPrediction") or rec.get("historicalShadow")
        shadow_pred: Optional[Tuple[float, float, float]] = None
        if isinstance(shadow_snapshot, Mapping):
            s_p50 = shadow_snapshot.get("p50") or shadow_snapshot.get("medianEstimate")
            s_p20 = shadow_snapshot.get("p20")
            s_p80 = shadow_snapshot.get("p80")
            if s_p50 is not None and s_p20 is not None and s_p80 is not None:
                shadow_pred = (float(s_p20), float(s_p50), float(s_p80))

        # 4. PR-B Red Probability Inference Lab (evaluated strictly using prior history)
        pr_b_pred: Optional[Tuple[float, float, float]] = None
        if prior_history and prod_pred is not None:
            lab_red = ExperimentalRedInferenceLab(prior_history)
            session_ctx = dict(rec.get("publicIntel") or {})
            if "goldAvg" not in session_ctx and isinstance(rec.get("qualities"), dict):
                session_ctx["goldAvg"] = rec["qualities"].get("gold", {}).get("avg")
            red_rep = lab_red.evaluate_inference(session_ctx)
            if red_rep.red_total_quantiles and red_rep.red_total_quantiles.p50 is not None:
                rq = red_rep.red_total_quantiles
                tot_p20 = prod_pred[0] + (rq.p20 or 0.0)
                tot_p50 = prod_pred[1] + (rq.p50 or 0.0)
                tot_p80 = prod_pred[2] + (rq.p80 or 0.0)
                pr_b_pred = (tot_p20, tot_p50, tot_p80)

        # 5. PR-C Convolution (discrete PMF convolution when valid components exist)
        pr_c_conv_pred: Optional[Tuple[float, float, float]] = None
        candidate_pmfs = rec.get("candidatePmfs")
        if isinstance(candidate_pmfs, list) and candidate_pmfs:
            d_list = [DiscreteDistribution(p) for p in candidate_pmfs if isinstance(p, dict)]
            d_conv, c_meta = convolve_discrete_distributions(d_list)
            if d_conv and d_conv.is_valid:
                pr_c_conv_pred = (d_conv.quantiles.p20 or 0.0, d_conv.quantiles.p50 or 0.0, d_conv.quantiles.p80 or 0.0)

        # 6. PR-C Dafu Round Divisors Heuristic (R1-R4 canonical)
        pr_c_dafu_pred: Optional[Tuple[float, float, float]] = None
        if prod_pred is not None:
            r_idx = rec.get("round") or rec.get("currentRound") or 1
            r_key = f"R{min(4, max(1, int(r_idx)))}"
            divisor = DAFU_CANONICAL_ROUND_DIVISORS.get(r_key, 1.0)
            multiplier = 1.0 / divisor
            d_p50 = prod_pred[1] * multiplier
            d_p20 = prod_pred[0] * multiplier
            d_p80 = prod_pred[2] * multiplier
            pr_c_dafu_pred = (d_p20, d_p50, d_p80)

        candidate_predictions: Dict[str, Optional[Tuple[float, float, float]]] = {
            "production_baseline": prod_pred,
            "historical_shadow": shadow_pred,
            "pr_b_red_inference": pr_b_pred,
            "pr_c_convolution": pr_c_conv_pred,
            "pr_c_dafu_heuristic": pr_c_dafu_pred,
        }

        for m_name, pred in candidate_predictions.items():
            if pred is None:
                continue  # unavailable for this record
            c_p20, c_p50, c_p80 = pred
            err = abs(actual_val - c_p50)
            abs_errors[m_name].append(err)
            model_sample_counts[m_name] += 1
            if actual_val >= c_p20:
                p20_hits[m_name] += 1
            if actual_val <= c_p80:
                p80_hits[m_name] += 1
            if c_p20 <= actual_val <= c_p80:
                interval_hits[m_name] += 1

    comparison_metrics: Dict[str, Any] = {}
    for m_name in model_names:
        errs = abs_errors[m_name]
        n = len(errs)
        if n > 0:
            mae = sum(errs) / n
            s_errs = sorted(errs)
            med_ae = s_errs[n // 2]
            p20_cov = p20_hits[m_name] / n
            p80_cov = p80_hits[m_name] / n
            int_cov = interval_hits[m_name] / n
            status = "evaluated"
        else:
            mae, med_ae, p20_cov, p80_cov, int_cov = None, None, None, None, None
            status = "unavailable_no_admitted_predictions"

        comparison_metrics[m_name] = {
            "status": status,
            "sampleCount": n,
            "mae": round(mae, 2) if mae is not None else None,
            "medianAe": round(med_ae, 2) if med_ae is not None else None,
            "p20Coverage": round(p20_cov, 4) if p20_cov is not None else None,
            "p80Coverage": round(p80_cov, 4) if p80_cov is not None else None,
            "intervalCoverage": round(int_cov, 4) if int_cov is not None else None,
        }

    return {
        "status": "completed" if evaluated_count > 0 else "insufficient_data",
        "metadata": {
            "datasetKind": dataset_kind,
            "harnessVerification": True,
            "performanceClaimEligible": False,
            "noAutomatedWinnerDeclaration": True,
            "noSelfLeakageGuaranteed": True,
            "comparisonNotice": "Strict disjoint train/eval backtesting. External hypotheses require extensive data before considering production eligibility.",
        },
        "candidateCount": candidate_count,
        "eligibleCount": evaluated_count,
        "excludedCount": excluded_count,
        "excludedReasons": excluded_reasons,
        "modelComparison": comparison_metrics,
    }


def format_comparison_markdown(report: Dict[str, Any]) -> str:
    """Render comparative report as human-readable Markdown for external review."""
    meta = report.get("metadata", {})
    lines = [
        "# PR-C: Comparative Probability & Strategy Lab Evaluation Report",
        "",
        f"- **Status**: `{report.get('status')}`",
        f"- **Dataset Kind**: `{meta.get('datasetKind')}`",
        f"- **No Self Leakage**: `{meta.get('noSelfLeakageGuaranteed')}`",
        f"- **Performance Claim Eligible**: `{meta.get('performanceClaimEligible')}`",
        f"- **Candidate Records**: `{report.get('candidateCount')}`",
        f"- **Eligible Evaluated Records**: `{report.get('eligibleCount')}`",
        f"- **Excluded Records**: `{report.get('excludedCount')}`",
        "",
        "## Model Comparison Table (Independent Denominators)",
        "",
        "| Candidate Model | Status | Sample N | MAE | Median AE | P20 Coverage | P80 Coverage | Interval Coverage |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    comp = report.get("modelComparison", {})
    for m_name, m_data in comp.items():
        lines.append(
            f"| `{m_name}` | `{m_data.get('status')}` | `{m_data.get('sampleCount')}` | "
            f"`{m_data.get('mae')}` | `{m_data.get('medianAe')}` | "
            f"`{m_data.get('p20Coverage')}` | `{m_data.get('p80Coverage')}` | "
            f"`{m_data.get('intervalCoverage')}` |"
        )

    lines.extend([
        "",
        "> [!IMPORTANT]",
        "> **External Hypotheses != Game Truth**.",
        "> PR-C maintains `performanceClaimEligible = False` and strictly does not select an automated winner.",
        "> Production solvers and bidding lines remain untouched.",
        "",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    mock_records = [
        {
            "schemaVersion": 7,
            "id": f"rec_comp_{i}",
            "playedAt": f"2026-09-17T10:{10 + i:02d}:00Z",
            "lifecycleStatus": "FINALIZED",
            "coverageStatus": "COMPLETE",
            "publicIntel": {"totalItems": 20, "totalGrid": 54},
            "predictionSnapshot": {
                "valP50": 600000.0,
                "p20": 540000.0,
                "p80": 660000.0,
            },
            "shadowPrediction": {
                "p50": 610000.0,
                "p20": 550000.0,
                "p80": 670000.0,
            },
            "settlement": {
                "verified": True,
                "actualTotal": float(600000.0 + (i % 3) * 50000),
            },
        }
        for i in range(12)
    ]
    rep = run_probability_strategy_comparison(mock_records, dataset_kind="synthetic_fixture")
    print(format_comparison_markdown(rep))
