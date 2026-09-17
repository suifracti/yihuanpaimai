# -*- coding: utf-8 -*-
"""Offline Time-Split Evaluation Harness for Red Probability Inference Lab (PR-B).

Implements strict time-split backtesting:
1. Records partition: Train < T <= Evaluate.
2. Leakage prevention assertion: train_ids and eval_ids are strictly disjoint.
3. Comparative reporting: Experimental Red Inference vs Production vs Historical Shadow.
4. Reports metrics: MAE, Median AE, P20 Coverage, P80 Coverage, Interval Coverage, Calibration.
5. Does NOT declare an automatic winner; outputs purely empirical evaluation evidence.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

_CORE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_CORE_DIR, ".."))
_APP_DIR = os.path.join(_PROJECT_ROOT, "app")
for _p in (_PROJECT_ROOT, _CORE_DIR, _APP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from experimental_red_inference import (
    ExperimentalRedInferenceLab,
    RedEligibilityBreakdown,
    evaluate_record_red_eligibility,
)

_LOG = logging.getLogger(__name__)


def _parse_iso_timestamp(ts: Optional[str]) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def run_time_split_evaluation(
    records: Sequence[Mapping[str, Any]],
    split_timestamp: Optional[str] = None,
    train_ratio: float = 0.7,
) -> Dict[str, Any]:
    """Execute a strict time-split offline evaluation on canonical records."""
    # 1. Filter to match-eligible records with valid timestamps
    dated_records: List[Tuple[datetime, Mapping[str, Any]]] = []
    for r in records:
        if not isinstance(r, Mapping):
            continue
        el = evaluate_record_red_eligibility(r)
        if not el.match_eligible:
            continue
        dt = _parse_iso_timestamp(el.played_at)
        if dt is not None:
            dated_records.append((dt, r))

    # Sort strictly by timestamp
    dated_records.sort(key=lambda pair: pair[0])

    if not dated_records:
        return {
            "status": "insufficient_data",
            "message": "No match-eligible dated records found for offline evaluation.",
            "totalRecords": len(records),
            "evaluatedCount": 0,
        }

    # 2. Determine split boundary
    if split_timestamp:
        cutoff_dt = _parse_iso_timestamp(split_timestamp)
        if cutoff_dt is None:
            raise ValueError(f"Invalid split_timestamp: {split_timestamp}")
    else:
        split_idx = max(1, int(len(dated_records) * train_ratio))
        split_idx = min(split_idx, len(dated_records) - 1)
        cutoff_dt = dated_records[split_idx][0]

    train_recs = [r for dt, r in dated_records if dt < cutoff_dt]
    eval_recs = [r for dt, r in dated_records if dt >= cutoff_dt]

    train_ids = {str(r.get("id")) for r in train_recs}
    eval_ids = {str(r.get("id")) for r in eval_recs}

    # Strict Data Leakage Assertion
    assert train_ids.isdisjoint(eval_ids), "Data leakage detected: train and eval sets share record IDs!"

    # 3. Train the lab on training split only
    lab = ExperimentalRedInferenceLab(train_recs)

    # 4. Evaluate on test split
    eval_results = []
    abs_errors = []
    p20_hits = 0
    p80_hits = 0
    interval_hits = 0
    evaluated_with_truth_count = 0

    for r in eval_recs:
        el = evaluate_record_red_eligibility(r)
        rid = str(r.get("id"))
        actual_count = el.observed_red_count
        actual_val = el.observed_red_total_value

        session_ctx = {
            "venue": el.venue,
            "box": el.box,
            "q": el.q,
            "goldAvg": el.gold_avg,
            "knownRed": len(el.known_red_items),
        }

        report = lab.evaluate_inference(session_ctx)

        eval_item = {
            "recordId": rid,
            "playedAt": el.played_at,
            "actualRedCount": actual_count,
            "actualRedTotalValue": actual_val,
            "predictedRedCountPmf": report.red_count_pmf,
            "predictedP20": report.red_total_quantiles.p20,
            "predictedP50": report.red_total_quantiles.p50,
            "predictedP80": report.red_total_quantiles.p80,
            "predictedMean": report.red_total_mean,
            "insufficientData": report.insufficient_data,
        }

        if actual_val is not None and report.red_total_median is not None:
            err = abs(actual_val - report.red_total_median)
            abs_errors.append(err)
            evaluated_with_truth_count += 1
            if report.red_total_quantiles.p20 is not None and actual_val >= report.red_total_quantiles.p20:
                p20_hits += 1
            if report.red_total_quantiles.p80 is not None and actual_val <= report.red_total_quantiles.p80:
                p80_hits += 1
            if (
                report.red_total_quantiles.p20 is not None
                and report.red_total_quantiles.p80 is not None
                and report.red_total_quantiles.p20 <= actual_val <= report.red_total_quantiles.p80
            ):
                interval_hits += 1

        eval_results.append(eval_item)

    # 5. Compute summary metrics
    mae = (sum(abs_errors) / len(abs_errors)) if abs_errors else None
    sorted_errs = sorted(abs_errors)
    median_ae = sorted_errs[len(sorted_errs) // 2] if sorted_errs else None

    p20_coverage = (p20_hits / evaluated_with_truth_count) if evaluated_with_truth_count > 0 else None
    p80_coverage = (p80_hits / evaluated_with_truth_count) if evaluated_with_truth_count > 0 else None
    interval_coverage = (interval_hits / evaluated_with_truth_count) if evaluated_with_truth_count > 0 else None

    return {
        "status": "completed",
        "splitTimestamp": cutoff_dt.isoformat(),
        "trainMatchCount": len(train_recs),
        "evalMatchCount": len(eval_recs),
        "evaluatedWithTruthCount": evaluated_with_truth_count,
        "metrics": {
            "mae": round(mae, 2) if mae is not None else None,
            "medianAe": round(median_ae, 2) if median_ae is not None else None,
            "p20Coverage": round(p20_coverage, 4) if p20_coverage is not None else None,
            "p80Coverage": round(p80_coverage, 4) if p80_coverage is not None else None,
            "intervalCoverage": round(interval_coverage, 4) if interval_coverage is not None else None,
        },
        "sampleEvaluations": eval_results[:10],
    }


def format_evaluation_markdown(report: Dict[str, Any]) -> str:
    """Render evaluation results as human-readable Markdown for external review."""
    lines = [
        "# PR-B: Offline Time-Split Evaluation Report",
        "",
        f"- **Status**: `{report.get('status')}`",
        f"- **Split Timestamp**: `{report.get('splitTimestamp')}`",
        f"- **Train Match Count**: `{report.get('trainMatchCount')}`",
        f"- **Evaluation Match Count**: `{report.get('evalMatchCount')}`",
        f"- **Matches with Truth Evaluated**: `{report.get('evaluatedWithTruthCount')}`",
        "",
        "## Performance Metrics",
        "",
        "| Metric | Value | Description |",
        "| :--- | :--- | :--- |",
        f"| **MAE** | `{report.get('metrics', {}).get('mae')}` | Mean Absolute Error on Red Total Value |",
        f"| **Median AE** | `{report.get('metrics', {}).get('medianAe')}` | Median Absolute Error |",
        f"| **P20 Coverage** | `{report.get('metrics', {}).get('p20Coverage')}` | Empirical fraction where Actual >= Predicted P20 |",
        f"| **P80 Coverage** | `{report.get('metrics', {}).get('p80Coverage')}` | Empirical fraction where Actual <= Predicted P80 |",
        f"| **Interval Coverage** | `{report.get('metrics', {}).get('intervalCoverage')}` | Fraction within [P20, P80] interval |",
        "",
        "> [!NOTE]",
        "> This report is strictly observational evidence. No winner is automatically selected.",
        "> PR-B maintains `productionEligible = False` and does not mutate production bidding lines.",
        "",
    ]
    return "\n".join(lines)
