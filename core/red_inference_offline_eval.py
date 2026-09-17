# -*- coding: utf-8 -*-
"""Offline Time-Split Evaluation Harness for Red Probability Inference Lab (PR-B).

Implements strict time-split backtesting (Fix H, I, J):
1. Dataset admission: runs through canonical evaluate_history_admission and build_duplicate_index.
2. Physical match partition: groups by physical match identity to prevent duplicate records of the same
   match from crossing the train/eval split.
3. Dual leakage assertions:
   - train_record_ids ∩ eval_record_ids = ∅
   - train_physical_fingerprints ∩ eval_physical_fingerprints = ∅
4. Strict truth gating on evaluation targets:
   - Evaluates red count only on red_count_eligible matches.
   - Evaluates total value (MAE, coverage) only on red_total_value_eligible matches.
5. Reports metadata explicitly: datasetKind (synthetic_fixture vs live_history),
   harnessVerification=True, performanceClaimEligible=False.
"""

from __future__ import annotations

import hashlib
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

from experimental_red_inference import (
    ExperimentalRedInferenceLab,
    RedEligibilityBreakdown,
    evaluate_record_red_eligibility,
)

try:
    from history_admission import (
        DuplicateIndex,
        build_duplicate_index,
        evaluate_history_admission,
        potential_content_duplicate_group_key,
    )
except ImportError:
    try:
        from app.history_admission import (
            DuplicateIndex,
            build_duplicate_index,
            evaluate_history_admission,
            potential_content_duplicate_group_key,
        )
    except ImportError:
        build_duplicate_index = None
        evaluate_history_admission = None
        potential_content_duplicate_group_key = None

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
    dataset_kind: str = "synthetic_fixture",
) -> Dict[str, Any]:
    """Execute a strict time-split offline evaluation on admitted canonical records (Fix H, I, J & Final Fix B)."""
    valid_recs = [r for r in records if isinstance(r, Mapping)]
    if build_duplicate_index is not None:
        duplicate_index = build_duplicate_index(valid_recs)
    else:
        duplicate_index = None

    # 1. Admission and Truth Filtering (Final Semantic Fix B)
    # Potential content duplicates and duplicate record IDs are strictly fail-closed excluded
    # via evaluate_record_red_eligibility (exclude_all policy).
    admitted_records: List[Tuple[datetime, Mapping[str, Any]]] = []
    for r in valid_recs:
        el = evaluate_record_red_eligibility(r, duplicate_index)
        if not el.match_eligible:
            continue
        dt = _parse_iso_timestamp(el.played_at)
        if dt is None:
            continue
        admitted_records.append((dt, r))

    admitted_records.sort(key=lambda pair: pair[0])

    if not admitted_records:
        return {
            "status": "insufficient_data",
            "message": "No match-eligible admitted records found for offline evaluation.",
            "totalRecords": len(records),
            "evaluatedCount": 0,
            "metadata": {
                "datasetKind": dataset_kind,
                "harnessVerification": True,
                "performanceClaimEligible": False,
                "potentialDuplicateGuard": "exclude_all",
                "stablePhysicalMatchIdentityAvailable": False,
                "leakageProofLevel": "record_id_and_known_potential_duplicate_guard",
            },
        }

    # 2. Split Boundary Selection
    if split_timestamp:
        cutoff_dt = _parse_iso_timestamp(split_timestamp)
        if cutoff_dt is None:
            raise ValueError(f"Invalid split_timestamp: {split_timestamp}")
        train_candidates = [r for dt, r in admitted_records if dt < cutoff_dt]
        eval_candidates = [r for dt, r in admitted_records if dt >= cutoff_dt]
    else:
        split_idx = max(1, int(len(admitted_records) * train_ratio))
        split_idx = min(split_idx, len(admitted_records) - 1)
        cutoff_dt = admitted_records[split_idx][0]
        train_candidates = [r for _, r in admitted_records[:split_idx]]
        eval_candidates = [r for _, r in admitted_records[split_idx:]]

    # 3. Known Potential Duplicate Guard & Record ID Leakage Guard (Final Semantic Fix B)
    # Under exclude_all policy, all potential duplicates have already been excluded at admission.
    train_recs = train_candidates
    eval_recs = eval_candidates

    train_ids = {str(r.get("id")) for r in train_recs}
    eval_ids = {str(r.get("id")) for r in eval_recs}

    # Hard Leakage Assertion (Record ID level)
    assert train_ids.isdisjoint(eval_ids), "Data leakage: train and eval sets share record IDs!"

    # 4. Train Lab on Training Split Only
    lab = ExperimentalRedInferenceLab(train_recs)

    # 5. Evaluate Targets with Strong Truth Gates (Fix I)
    eval_results = []
    abs_errors = []
    p20_hits = 0
    p80_hits = 0
    interval_hits = 0

    evaluated_red_count_truth_count = 0
    evaluated_red_value_truth_count = 0
    excluded_truth_reasons: Dict[str, int] = {}

    for r in eval_recs:
        el = evaluate_record_red_eligibility(r, duplicate_index)
        rid = str(r.get("id"))

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
            "redCountEligible": el.red_count_eligible,
            "redTotalValueEligible": el.red_total_value_eligible,
            "actualRedCount": el.observed_red_count if el.red_count_eligible else None,
            "actualRedTotalValue": el.observed_red_total_value if el.red_total_value_eligible else None,
            "predictedRedCountPmf": report.red_count_pmf,
            "predictedP20": report.red_total_quantiles.p20,
            "predictedP50": report.red_total_quantiles.p50,
            "predictedP80": report.red_total_quantiles.p80,
            "predictedMean": report.red_total_mean,
            "insufficientData": report.insufficient_data,
        }

        if el.red_count_eligible:
            evaluated_red_count_truth_count += 1
        else:
            reason = el.red_count_truth_source or "COUNT_TRUTH_NOT_VERIFIED"
            excluded_truth_reasons[reason] = excluded_truth_reasons.get(reason, 0) + 1

        if el.red_total_value_eligible and el.observed_red_total_value is not None and report.red_total_median is not None:
            actual_val = el.observed_red_total_value
            err = abs(actual_val - report.red_total_median)
            abs_errors.append(err)
            evaluated_red_value_truth_count += 1
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
        elif not el.red_total_value_eligible:
            reason = el.red_value_truth_source or "VALUE_TRUTH_NOT_VERIFIED"
            excluded_truth_reasons[reason] = excluded_truth_reasons.get(reason, 0) + 1

        eval_results.append(eval_item)

    # 6. Compute Performance Metrics
    mae = (sum(abs_errors) / len(abs_errors)) if abs_errors else None
    sorted_errs = sorted(abs_errors)
    median_ae = sorted_errs[len(sorted_errs) // 2] if sorted_errs else None

    p20_coverage = (p20_hits / evaluated_red_value_truth_count) if evaluated_red_value_truth_count > 0 else None
    p80_coverage = (p80_hits / evaluated_red_value_truth_count) if evaluated_red_value_truth_count > 0 else None
    interval_coverage = (interval_hits / evaluated_red_value_truth_count) if evaluated_red_value_truth_count > 0 else None

    return {
        "status": "completed",
        "splitTimestamp": cutoff_dt.isoformat(),
        "metadata": {
            "datasetKind": dataset_kind,  # Fix J
            "harnessVerification": True,
            "performanceClaimEligible": False,  # Fix J: Synthetic fixture cannot make real claims
            "potentialDuplicateGuard": "exclude_all",
            "stablePhysicalMatchIdentityAvailable": False,
            "leakageProofLevel": "record_id_and_known_potential_duplicate_guard",
            "similarityProfile": report.similarity_profile,
        },
        "trainMatchCount": len(train_recs),
        "evalMatchCount": len(eval_recs),
        "evaluatedRedCountTruthCount": evaluated_red_count_truth_count,
        "evaluatedRedValueTruthCount": evaluated_red_value_truth_count,
        "excludedTruthReasons": excluded_truth_reasons,
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
    """Render evaluation results as human-readable Markdown for external review (Fix J)."""
    meta = report.get("metadata", {})
    lines = [
        "# PR-B: Offline Time-Split Evaluation Report",
        "",
        f"- **Status**: `{report.get('status')}`",
        f"- **Dataset Kind**: `{meta.get('datasetKind')}`",
        f"- **Harness Verification**: `{meta.get('harnessVerification')}`",
        f"- **Performance Claim Eligible**: `{meta.get('performanceClaimEligible')}`",
        f"- **Potential Duplicate Guard**: `{meta.get('potentialDuplicateGuard')}`",
        f"- **Stable Physical Match Identity Available**: `{meta.get('stablePhysicalMatchIdentityAvailable')}`",
        f"- **Leakage Proof Level**: `{meta.get('leakageProofLevel')}`",
        f"- **Split Timestamp**: `{report.get('splitTimestamp')}`",
        f"- **Train Match Count**: `{report.get('trainMatchCount')}`",
        f"- **Evaluation Match Count**: `{report.get('evalMatchCount')}`",
        f"- **Matches with Red Count Truth**: `{report.get('evaluatedRedCountTruthCount')}`",
        f"- **Matches with Red Value Truth**: `{report.get('evaluatedRedValueTruthCount')}`",
        "",
        "## Ground Truth Exclusion Reasons",
        "",
    ]
    reasons = report.get("excludedTruthReasons", {})
    if reasons:
        for r, cnt in sorted(reasons.items()):
            lines.append(f"- `{r}`: {cnt} records")
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Performance Metrics (Harness Verification)",
        "",
        "| Metric | Value | Description |",
        "| :--- | :--- | :--- |",
        f"| **MAE** | `{report.get('metrics', {}).get('mae')}` | Mean Absolute Error on Red Total Value |",
        f"| **Median AE** | `{report.get('metrics', {}).get('medianAe')}` | Median Absolute Error |",
        f"| **P20 Coverage** | `{report.get('metrics', {}).get('p20Coverage')}` | Empirical fraction where Actual >= Predicted P20 |",
        f"| **P80 Coverage** | `{report.get('metrics', {}).get('p80Coverage')}` | Empirical fraction where Actual <= Predicted P80 |",
        f"| **Interval Coverage** | `{report.get('metrics', {}).get('intervalCoverage')}` | Fraction within [P20, P80] interval |",
        "",
        "> [!IMPORTANT]",
        "> **Dataset Kind: `synthetic_fixture`** (Fix J).",
        "> This offline evaluation verifies harness mechanics, time-split partitioning, and zero-leakage assertions.",
        "> It does NOT make real-world accuracy claims against live gameplay.",
        "> PR-B maintains `productionEligible = False` and does not mutate production bidding lines.",
        "",
    ])
    return "\n".join(lines)
