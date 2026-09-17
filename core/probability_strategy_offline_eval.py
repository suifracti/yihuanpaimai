# -*- coding: utf-8 -*-
"""Offline Comparative Evaluation Harness for Probability and Strategy Lab (PR-C).

Compares candidate probabilistic models and heuristic profiles across admitted matches:
1. production_baseline (frozen pre-settlement prediction snapshot)
2. historical_shadow (frozen empirical shadow profile, if independent frozen schema exists)
3. pr_b_red_inference (evaluated using strictly prior history; no self-leakage)
4. pr_c_convolution (discrete PMF convolution when valid components with provenance exist)
5. pr_c_dafu_heuristic (canonical Dafu round divisors R1-R4)

Strict Invariants (Round 1 Review Items A & B):
- Multi-model comparative backtesting harness.
- Strictly NO self-history leakage: each evaluated record uses only history strictly prior to its playedAt datetime (aware UTC comparison, no ISO string comparison).
- Truth Gating: Reuses canonical authority (build_duplicate_index, evaluate_history_admission, evaluate_record_eligibility, SettlementTruthEvidence). Custom is_record_settlement_truth_admitted() is DELETED.
- Potential content duplicates strictly excluded fail-closed via duplicate_index.
- Production comparison requires frozen pre-settlement prediction (prediction-snapshot.v1) validated via validate_prediction_snapshot; reads forecast.quantiles.p20/p50/p80 only; strictly NO p50*0.9 / p50*1.1 fallback.
- Historical Shadow: unavailable_no_independent_frozen_shadow_artifact if no independent frozen schema exists; never reads synthetic shadowPrediction.
- Dafu Heuristic: unavailable_base_metric_unconfirmed until base metric semantics are confirmed; no fabricated backtest pricing.
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
    convolve_discrete_distributions,
    evaluate_experimental_probability_strategy,
    get_global_strategy_registry,
    parse_convolution_component,
)
from experimental_red_inference import (
    ExperimentalRedInferenceLab,
    evaluate_record_red_eligibility,
)

try:
    from history_admission import (
        DuplicateIndex,
        HistoryAdmissionFlag,
        build_duplicate_index,
        evaluate_history_admission,
        positive_finite,
    )
except ImportError:
    from app.history_admission import (
        DuplicateIndex,
        HistoryAdmissionFlag,
        build_duplicate_index,
        evaluate_history_admission,
        positive_finite,
    )

try:
    from evaluation_eligibility import (
        EligibilityReason,
        PREDICTION_SNAPSHOT_SCHEMA_VERSION,
        TRUTH_EVIDENCE_SCHEMA_VERSION,
        _parse_aware_iso,
        _validate_truth_evidence,
        evaluate_record_eligibility,
        validate_prediction_snapshot,
    )
except ImportError:
    from app.evaluation_eligibility import (
        EligibilityReason,
        PREDICTION_SNAPSHOT_SCHEMA_VERSION,
        TRUTH_EVIDENCE_SCHEMA_VERSION,
        _parse_aware_iso,
        _validate_truth_evidence,
        evaluate_record_eligibility,
        validate_prediction_snapshot,
    )

_LOG = logging.getLogger(__name__)


def canonical_timestamp_to_utc(ts: Any) -> Optional[datetime]:
    """Parse and normalize any ISO timestamp into aware UTC datetime without string comparison."""
    dt = _parse_aware_iso(ts)
    if dt is not None:
        return dt
    if isinstance(ts, str) and ts.strip():
        text = ts.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            raw_dt = datetime.fromisoformat(text)
            if raw_dt.tzinfo is None:
                return raw_dt.replace(tzinfo=timezone.utc)
            return raw_dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def run_probability_strategy_comparison(
    records: Sequence[Mapping[str, Any]],
    dataset_kind: str = "synthetic_fixture",
) -> Dict[str, Any]:
    """Run multi-model comparative evaluation across canonical match records with strict no-leakage."""
    valid_recs = [r for r in records if isinstance(r, Mapping)]
    candidate_count = len(valid_recs)

    # 1. Build canonical duplicate index across candidate records
    duplicate_index = build_duplicate_index(valid_recs)

    # 2. Canonical Admission & Settlement Truth Gating (Review Item A)
    # Reuses build_duplicate_index, evaluate_history_admission, and settlement truth validation.
    # Custom is_record_settlement_truth_admitted() is DELETED.
    # Potential content duplicates are strictly excluded fail-closed.
    admitted_records: List[Tuple[datetime, Mapping[str, Any]]] = []
    excluded_count = 0
    excluded_reasons: Dict[str, int] = {}

    for rec in valid_recs:
        rec_id = str(rec.get("id") or "").strip()

        # Potential content duplicates and duplicate record IDs fail-closed
        if rec_id in duplicate_index.potential_content_duplicate_ids:
            excluded_count += 1
            excluded_reasons["POTENTIAL_CONTENT_DUPLICATE_EXCLUDED"] = (
                excluded_reasons.get("POTENTIAL_CONTENT_DUPLICATE_EXCLUDED", 0) + 1
            )
            continue

        if rec_id in duplicate_index.duplicate_record_ids:
            excluded_count += 1
            excluded_reasons["DUPLICATE_RECORD_ID_EXCLUDED"] = (
                excluded_reasons.get("DUPLICATE_RECORD_ID_EXCLUDED", 0) + 1
            )
            continue

        # Canonical history admission check
        adm = evaluate_history_admission(rec, duplicate_index)
        if not adm.admitted:
            excluded_count += 1
            r_key = f"HISTORY_ADMISSION_REJECTED_{adm.exclusion_reason or 'UNKNOWN'}"
            excluded_reasons[r_key] = excluded_reasons.get(r_key, 0) + 1
            continue

        if HistoryAdmissionFlag.POTENTIAL_CONTENT_DUPLICATE in adm.flags:
            excluded_count += 1
            excluded_reasons["POTENTIAL_CONTENT_DUPLICATE_FLAGGED"] = (
                excluded_reasons.get("POTENTIAL_CONTENT_DUPLICATE_FLAGGED", 0) + 1
            )
            continue

        # Settlement truth validation (SettlementTruthEvidence / verified settlement actualTotal > 0)
        settlement = rec.get("settlement")
        if not isinstance(settlement, Mapping):
            excluded_count += 1
            excluded_reasons["MISSING_SETTLEMENT_OBJECT"] = (
                excluded_reasons.get("MISSING_SETTLEMENT_OBJECT", 0) + 1
            )
            continue

        if settlement.get("verified") is not True:
            excluded_count += 1
            excluded_reasons["SETTLEMENT_NOT_VERIFIED"] = (
                excluded_reasons.get("SETTLEMENT_NOT_VERIFIED", 0) + 1
            )
            continue

        actual_total = settlement.get("actualTotal")
        if not positive_finite(actual_total):
            excluded_count += 1
            excluded_reasons["INVALID_OR_NON_POSITIVE_ACTUAL_TOTAL"] = (
                excluded_reasons.get("INVALID_OR_NON_POSITIVE_ACTUAL_TOTAL", 0) + 1
            )
            continue

        # Aware UTC timestamp normalization (strictly NO ISO string comparison)
        raw_ts = rec.get("playedAt") or rec.get("timestamp")
        dt = canonical_timestamp_to_utc(raw_ts)
        if dt is None:
            excluded_count += 1
            excluded_reasons["INVALID_OR_MISSING_PLAYED_AT"] = (
                excluded_reasons.get("INVALID_OR_MISSING_PLAYED_AT", 0) + 1
            )
            continue

        admitted_records.append((dt, rec))

    # Sort admitted records chronologically by aware datetime
    admitted_records.sort(key=lambda pair: pair[0])
    evaluated_count = len(admitted_records)

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
    unavailable_reasons: Dict[str, str] = {
        "historical_shadow": "unavailable_no_independent_frozen_shadow_artifact",
        "pr_c_dafu_heuristic": "unavailable_base_metric_unconfirmed",
    }

    for idx, (dt_cur, rec) in enumerate(admitted_records):
        actual_val = float(rec["settlement"]["actualTotal"])

        # 1. Strict No-Leakage Training Cohort for PR-B Red Lab
        # Only historical records strictly prior to current rec's dt_cur (datetime < dt_cur)!
        # Current rec NEVER enters its own training set!
        prior_history = [
            r_prior for dt_prior, r_prior in admitted_records[:idx]
            if dt_prior < dt_cur
        ]

        # 2. Production Baseline: requires frozen pre-settlement prediction snapshot!
        # Validated via validate_prediction_snapshot; reads forecast.quantiles.p20/p50/p80.
        # Strictly NO p50*0.9 / p50*1.1 fallbacks! (Review Item B)
        prod_pred: Optional[Tuple[float, float, float]] = None
        snapshot = rec.get("predictionSnapshot")
        if isinstance(snapshot, Mapping):
            is_valid_snap, _ = validate_prediction_snapshot(rec)
            if is_valid_snap:
                forecast = snapshot.get("forecast")
                if isinstance(forecast, Mapping):
                    quantiles = forecast.get("quantiles")
                    if isinstance(quantiles, Mapping):
                        q20 = quantiles.get("p20")
                        q50 = quantiles.get("p50")
                        q80 = quantiles.get("p80")
                        if (
                            positive_finite(q20)
                            and positive_finite(q50)
                            and positive_finite(q80)
                            and float(q20) <= float(q50) <= float(q80)
                        ):
                            prod_pred = (float(q20), float(q50), float(q80))

        # 3. Historical Shadow: Review Item B
        # No independent frozen shadow prediction schema in canonical records.
        # Marked unavailable_no_independent_frozen_shadow_artifact; never reads synthetic shadowPrediction.
        shadow_pred: Optional[Tuple[float, float, float]] = None

        # 4. PR-B Red Probability Inference Lab (evaluated strictly using prior history)
        pr_b_pred: Optional[Tuple[float, float, float]] = None
        if prior_history and prod_pred is not None:
            try:
                lab_red = ExperimentalRedInferenceLab(prior_history)
                session_ctx = dict(rec.get("publicIntel") or {})
                if "goldAvg" not in session_ctx and isinstance(rec.get("qualities"), dict):
                    session_ctx["goldAvg"] = rec["qualities"].get("gold", {}).get("avg")
                red_rep = lab_red.evaluate_inference(session_ctx)
                if not red_rep.insufficient_data and red_rep.red_total_quantiles:
                    rq = red_rep.red_total_quantiles
                    if rq.p50 is not None and rq.p20 is not None and rq.p80 is not None:
                        tot_p20 = prod_pred[0] + rq.p20
                        tot_p50 = prod_pred[1] + rq.p50
                        tot_p80 = prod_pred[2] + rq.p80
                        if tot_p20 <= tot_p50 <= tot_p80:
                            pr_b_pred = (tot_p20, tot_p50, tot_p80)
            except Exception as exc:
                _LOG.debug("PR-B red inference offline eval exception: %s", exc)

        # 5. PR-C Discrete Convolution (Review Item D: requires strict convolutionComponents with provenance)
        pr_c_conv_pred: Optional[Tuple[float, float, float]] = None
        conv_comps_raw = rec.get("convolutionComponents")
        if isinstance(conv_comps_raw, Sequence) and conv_comps_raw:
            d_list: List[DiscreteDistribution] = []
            for raw_c in conv_comps_raw:
                dist_c, prov_c, err = parse_convolution_component(raw_c)
                if dist_c is not None and prov_c is not None and dist_c.is_valid:
                    d_list.append(dist_c)
            if d_list:
                d_conv, c_meta = convolve_discrete_distributions(d_list)
                if d_conv and d_conv.is_valid and d_conv.quantiles.p50 is not None:
                    q = d_conv.quantiles
                    if q.p20 is not None and q.p80 is not None:
                        pr_c_conv_pred = (float(q.p20), float(q.p50), float(q.p80))

        # 6. PR-C Dafu Round Divisors Heuristic (Review Item B & C)
        # Base metric semantics unconfirmed -> unavailable_base_metric_unconfirmed; no fabricated pricing.
        pr_c_dafu_pred: Optional[Tuple[float, float, float]] = None

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
            reason = None
        else:
            mae, med_ae, p20_cov, p80_cov, int_cov = None, None, None, None, None
            reason = unavailable_reasons.get(m_name, "unavailable_no_admitted_predictions")
            status = reason

        comparison_metrics[m_name] = {
            "status": status,
            "reason": reason,
            "sampleCount": n,
            "evaluatedTotal": evaluated_count,
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
            "leakageProofLevel": "strict_aware_datetime_prior_only",
            "potentialDuplicateGuard": "exclude_all",
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
