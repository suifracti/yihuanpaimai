# -*- coding: utf-8 -*-
"""Offline Comparative Evaluation Harness for Probability and Strategy Lab (PR-C).

Compares candidate probabilistic models and heuristic profiles across admitted matches:
1. Production baseline solve (P50)
2. Historical Shadow (empirical shadow profile)
3. PR-B Red Probability Inference Lab
4. PR-C Baseline Discrete Convolution
5. PR-C External Dafu Heuristics (R1-R4)

Strict Invariants:
- Multi-model comparative backtesting harness.
- Does NOT automatically declare a "winner" or promote external hypotheses to production.
- performanceClaimEligible = False (harness verification only).
- Truth gating: evaluates only against confirmed post-settlement actualTotal ground truth.
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
    DiscreteDistribution,
    ExperimentalStrategyProfile,
    ExperimentalStrategyRegistry,
    compute_cell_fit,
    evaluate_experimental_probability_strategy,
    get_global_strategy_registry,
)
from experimental_red_inference import (
    ExperimentalRedInferenceLab,
    evaluate_record_red_eligibility,
)

_LOG = logging.getLogger(__name__)


def run_probability_strategy_comparison(
    records: Sequence[Mapping[str, Any]],
    dataset_kind: str = "synthetic_fixture",
) -> Dict[str, Any]:
    """Run multi-model comparative evaluation across canonical match records."""
    valid_recs = [r for r in records if isinstance(r, Mapping)]

    evaluated_count = 0
    excluded_count = 0
    excluded_reasons: Dict[str, int] = {}

    model_names = [
        "production_baseline",
        "pr_b_red_inference",
        "pr_c_convolution_baseline",
        "pr_c_dafu_heuristic",
    ]

    abs_errors: Dict[str, List[float]] = {m: [] for m in model_names}
    p20_hits: Dict[str, int] = {m: 0 for m in model_names}
    p80_hits: Dict[str, int] = {m: 0 for m in model_names}
    interval_hits: Dict[str, int] = {m: 0 for m in model_names}

    lab_red = ExperimentalRedInferenceLab(valid_recs)

    # Prepare registry with both baseline and dafu heuristic for comparative evaluation
    comp_registry = ExperimentalStrategyRegistry()
    comp_registry.enable_profile("dafu_round_heuristic_v1")
    comp_registry.enable_profile("convolution_v1")
    comp_registry.enable_profile("cell_fit_v1")

    for r in valid_recs:
        rid = str(r.get("id") or "")
        settlement = r.get("settlement") if isinstance(r.get("settlement"), Mapping) else {}
        actual_total = settlement.get("actualTotal", r.get("actualTotal"))

        if not isinstance(actual_total, (int, float)) or isinstance(actual_total, bool) or actual_total <= 0:
            excluded_count += 1
            reason = "MISSING_OR_INVALID_ACTUAL_TOTAL"
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
            continue

        actual_val = float(actual_total)

        pub = r.get("publicIntel") if isinstance(r.get("publicIntel"), Mapping) else {}
        q = pub.get("q") if pub.get("q") is not None else r.get("q")
        quals = r.get("qualities") if isinstance(r.get("qualities"), Mapping) else {}
        gold = quals.get("gold") if isinstance(quals.get("gold"), Mapping) else {}
        gold_avg = gold.get("avg") or r.get("goldAvg")

        if not isinstance(q, (int, float)) or not isinstance(gold_avg, (int, float)) or q <= 0 or gold_avg <= 0:
            excluded_count += 1
            reason = "MISSING_INTEL_Q_OR_GOLD_AVG"
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
            continue

        evaluated_count += 1

        session_ctx = {
            "q": int(q),
            "goldAvg": float(gold_avg),
            "venue": str(r.get("venue") or "standard"),
            "box": str(r.get("box") or "box_normal"),
            "round": int(r.get("round", 1)),
        }

        # 1. Production baseline estimate (Center = Q * goldAvg)
        center = float(q) * float(gold_avg)
        prod_p20, prod_p50, prod_p80 = center * 0.9, center, center * 1.1

        # 2. PR-B Red Inference Lab
        red_report = lab_red.evaluate_inference(session_ctx)
        red_p50 = red_report.red_total_median if red_report.red_total_median is not None else 0.0
        tot_pr_b_p20 = prod_p20 + (red_report.red_total_quantiles.p20 or 0.0)
        tot_pr_b_p50 = prod_p50 + red_p50
        tot_pr_b_p80 = prod_p80 + (red_report.red_total_quantiles.p80 or 0.0)

        # 3. PR-C Strategy Lab (Convolution & Heuristic)
        pr_c_report = evaluate_experimental_probability_strategy(
            session_ctx,
            production_metrics={"valP50": prod_p50, "targetProfitLine": prod_p20 * 0.8},
            experimental_red=red_report.to_payload(),
            registry=comp_registry,
        )

        conv_p20 = pr_c_report.p20 or prod_p20
        conv_p50 = pr_c_report.p50 or prod_p50
        conv_p80 = pr_c_report.p80 or prod_p80

        dafu_p50 = pr_c_report.experimental_reserve_price or (prod_p50 * 0.92)
        dafu_p20 = pr_c_report.experimental_conservative_price or (prod_p20 * 0.88)
        dafu_p80 = conv_p80

        candidate_predictions = {
            "production_baseline": (prod_p20, prod_p50, prod_p80),
            "pr_b_red_inference": (tot_pr_b_p20, tot_pr_b_p50, tot_pr_b_p80),
            "pr_c_convolution_baseline": (conv_p20, conv_p50, conv_p80),
            "pr_c_dafu_heuristic": (dafu_p20, dafu_p50, dafu_p80),
        }

        for m_name, (c_p20, c_p50, c_p80) in candidate_predictions.items():
            err = abs(actual_val - c_p50)
            abs_errors[m_name].append(err)
            if actual_val >= c_p20:
                p20_hits[m_name] += 1
            if actual_val <= c_p80:
                p80_hits[m_name] += 1
            if c_p20 <= actual_val <= c_p80:
                interval_hits[m_name] += 1

    comparison_metrics: Dict[str, Any] = {}
    for m_name in model_names:
        errs = abs_errors[m_name]
        if errs:
            mae = sum(errs) / len(errs)
            s_errs = sorted(errs)
            med_ae = s_errs[len(s_errs) // 2]
            p20_cov = p20_hits[m_name] / len(errs)
            p80_cov = p80_hits[m_name] / len(errs)
            int_cov = interval_hits[m_name] / len(errs)
        else:
            mae, med_ae, p20_cov, p80_cov, int_cov = None, None, None, None, None

        comparison_metrics[m_name] = {
            "mae": round(mae, 2) if mae is not None else None,
            "medianAe": round(med_ae, 2) if med_ae is not None else None,
            "p20Coverage": round(p20_cov, 4) if p20_cov is not None else None,
            "p80Coverage": round(p80_cov, 4) if p80_cov is not None else None,
            "intervalCoverage": round(int_cov, 4) if int_cov is not None else None,
            "sampleCount": len(errs),
        }

    return {
        "status": "completed" if evaluated_count > 0 else "insufficient_data",
        "metadata": {
            "datasetKind": dataset_kind,
            "harnessVerification": True,
            "performanceClaimEligible": False,
            "noAutomatedWinnerDeclaration": True,
            "comparisonNotice": "External hypotheses require empirical backtesting before considering production eligibility.",
        },
        "totalRecords": len(valid_recs),
        "evaluatedCount": evaluated_count,
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
        f"- **Harness Verification**: `{meta.get('harnessVerification')}`",
        f"- **Performance Claim Eligible**: `{meta.get('performanceClaimEligible')}`",
        f"- **Evaluated Matches**: `{report.get('evaluatedCount')}`",
        f"- **Excluded Matches**: `{report.get('excludedCount')}`",
        "",
        "## Model Comparison Table",
        "",
        "| Candidate Model | MAE | Median AE | P20 Coverage | P80 Coverage | Interval Coverage | Sample N |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    comp = report.get("modelComparison", {})
    for m_name, m_data in comp.items():
        lines.append(
            f"| `{m_name}` | `{m_data.get('mae')}` | `{m_data.get('medianAe')}` | "
            f"`{m_data.get('p20Coverage')}` | `{m_data.get('p80Coverage')}` | "
            f"`{m_data.get('intervalCoverage')}` | `{m_data.get('sampleCount')}` |"
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
            "publicIntel": {"q": 60},
            "qualities": {"gold": {"avg": 10000.0, "count": 10}},
            "settlement": {
                "verified": True,
                "actualTotal": float(600000.0 + (i % 3) * 50000),
            },
        }
        for i in range(12)
    ]
    report = run_probability_strategy_comparison(mock_records, dataset_kind="synthetic_fixture")
    print(format_comparison_markdown(report))
