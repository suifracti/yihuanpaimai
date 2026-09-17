# -*- coding: utf-8 -*-
"""Offline Comparative Evaluation Harness for Probability and Strategy Lab (PR-C).

Compares candidate probabilistic models and heuristic profiles across admitted matches:
1. production_baseline (frozen pre-settlement prediction snapshot)
2. historical_shadow (frozen empirical shadow profile, if independent frozen schema exists)
3. pr_b_red_inference (evaluated using strictly prior history; no self-leakage)
4. pr_c_convolution (discrete PMF convolution when valid components with provenance exist)
5. pr_c_dafu_heuristic (canonical Dafu round divisors R1-R4)

Strict Invariants (Round 2 Review Updates):
- 1. Formal Truth/Evaluation Gate: Calls evaluate_record_eligibility(rec, duplicate_index, target_kind="full_value")
  and requires formally_eligible for formal evaluation cohort. Reuses _validate_truth_evidence.
  Legacy settlement.verified=True without SettlementTruthEvidence is rejected.
- 2. Canonical Timestamp Normalization: Reuses normalize_record_timestamp from history_admission.
  Legacy naive timestamps are explicitly assigned Asia/Shanghai and converted to UTC instant;
  aware offsets (+08:00, Z) convert to UTC instant. Strictly NO naive_datetime.replace(tzinfo=UTC).
- 3. Full-inventory Prediction Snapshot Lockdown: Requires snapshot.frozen=True, informationMode="full_shadow",
  coverageRatio >= 0.999999, forecast.target="full_inventory_actual_total", forecast.scope="full_inventory",
  and finite monotonic quantiles. Modes like structural_only, partial_shadow, partial_inventory_conditional,
  structural_inventory are strictly unavailable for actualTotal comparison.
- 4. Honest Leakage Statement: Declares stablePhysicalMatchIdentityAvailable=False,
  leakageProofLevel="record_id_known_potential_duplicate_and_temporal_prior". No false absolute claims.
- 5. Independent sample denominator tracked per model.
- 6. Does NOT automatically declare a "winner" or promote external hypotheses to production.
- 7. performanceClaimEligible = False (harness verification only).
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
        normalize_record_timestamp,
        positive_finite,
    )
except ImportError:
    from app.history_admission import (
        DuplicateIndex,
        HistoryAdmissionFlag,
        build_duplicate_index,
        evaluate_history_admission,
        normalize_record_timestamp,
        positive_finite,
    )

try:
    from evaluation_eligibility import (
        EligibilityReason,
        FULL_VALUE_SCOPE,
        FULL_VALUE_TARGET,
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
        FULL_VALUE_SCOPE,
        FULL_VALUE_TARGET,
        PREDICTION_SNAPSHOT_SCHEMA_VERSION,
        TRUTH_EVIDENCE_SCHEMA_VERSION,
        _parse_aware_iso,
        _validate_truth_evidence,
        evaluate_record_eligibility,
        validate_prediction_snapshot,
    )

_LOG = logging.getLogger(__name__)


def canonical_timestamp_to_utc(ts_or_record: Any) -> Optional[datetime]:
    """Parse and normalize timestamp into aware UTC datetime using History Admission authority.

    Strict legacy rules:
    - naive timestamp => assigned Asia/Shanghai => converted to UTC instant.
    - aware timestamp with offset (+08:00, Z) => converted to UTC instant.
    Strictly NO naive_datetime.replace(tzinfo=timezone.utc).
    """
    if isinstance(ts_or_record, Mapping):
        norm = normalize_record_timestamp(ts_or_record)
        return norm.utc_time if norm else None
    if isinstance(ts_or_record, str) and ts_or_record.strip():
        norm = normalize_record_timestamp({"playedAt": ts_or_record.strip()})
        return norm.utc_time if norm else None
    return None


def extract_full_inventory_prediction(
    rec_or_snapshot: Mapping[str, Any],
) -> Tuple[Optional[Tuple[float, float, float]], Optional[str]]:
    """Extract full-inventory quantiles from frozen prediction snapshot.

    Strict full actualTotal comparison cohort lockdown (Round 2 Review Item 3):
    - snapshot.frozen == True
    - mode.informationMode == 'full_shadow'
    - mode.coverageRatio >= 0.999999
    - forecast.target == 'full_inventory_actual_total'
    - forecast.scope == 'full_inventory'
    - p20, p50, p80 finite numbers with p20 <= p50 <= p80

    Modes like 'partial_shadow', 'structural_only', 'partial_inventory_conditional',
    'structural_inventory' are strictly UNAVAILABLE for full actualTotal comparison.
    """
    if not isinstance(rec_or_snapshot, Mapping):
        return None, "PREDICTION_SNAPSHOT_MISSING"

    if "predictionSnapshot" in rec_or_snapshot and isinstance(rec_or_snapshot["predictionSnapshot"], Mapping):
        snapshot = rec_or_snapshot["predictionSnapshot"]
        rec_to_validate = rec_or_snapshot
    elif rec_or_snapshot.get("schemaVersion") == "prediction-snapshot.v1":
        snapshot = rec_or_snapshot
        rec_to_validate = {
            "id": snapshot.get("matchId") or "unknown_match",
            "predictionSnapshot": rec_or_snapshot,
        }
    else:
        return None, "PREDICTION_SNAPSHOT_MISSING"

    is_valid_snap, snap_reasons = validate_prediction_snapshot(rec_to_validate)
    if not is_valid_snap:
        return None, f"INVALID_SNAPSHOT:{snap_reasons[0] if snap_reasons else 'UNKNOWN'}"

    if snapshot.get("frozen") is not True:
        return None, "PREDICTION_SNAPSHOT_NOT_FROZEN"

    mode = snapshot.get("mode")
    if not isinstance(mode, Mapping):
        return None, "PREDICTION_MODE_MISSING"

    info_mode = str(mode.get("informationMode") or "").strip()
    if info_mode != "full_shadow":
        return None, f"DISALLOWED_INFORMATION_MODE:{info_mode}"

    coverage = mode.get("coverageRatio")
    if not isinstance(coverage, (int, float)) or isinstance(coverage, bool) or coverage < 0.999999:
        return None, f"INSUFFICIENT_COVERAGE_RATIO:{coverage}"

    forecast = snapshot.get("forecast")
    if not isinstance(forecast, Mapping):
        return None, "FORECAST_OBJECT_MISSING"

    target = str(forecast.get("target") or "").strip()
    if target != FULL_VALUE_TARGET:
        return None, f"TARGET_NOT_FULL_INVENTORY:{target}"

    scope = str(forecast.get("scope") or "").strip()
    if scope != FULL_VALUE_SCOPE:
        return None, f"SCOPE_NOT_FULL_INVENTORY:{scope}"

    quantiles = forecast.get("quantiles")
    if not isinstance(quantiles, Mapping):
        return None, "FORECAST_QUANTILES_MISSING"

    q20, q50, q80 = quantiles.get("p20"), quantiles.get("p50"), quantiles.get("p80")
    if not (positive_finite(q20) and positive_finite(q50) and positive_finite(q80)):
        return None, "NON_FINITE_QUANTILES"

    if not (float(q20) <= float(q50) <= float(q80)):
        return None, "NON_MONOTONIC_QUANTILES"

    return (float(q20), float(q50), float(q80)), None


def run_probability_strategy_comparison(
    records: Sequence[Mapping[str, Any]],
    dataset_kind: str = "synthetic_fixture",
    harness_verification: bool = False,
) -> Dict[str, Any]:
    """Run multi-model comparative evaluation across canonical match records with strict no-leakage."""
    valid_recs = [r for r in records if isinstance(r, Mapping)]
    candidate_count = len(valid_recs)

    # 1. Build canonical duplicate index across candidate records
    duplicate_index = build_duplicate_index(valid_recs)

    # 2. Canonical Admission & Formal Truth Gating (Round 2 Review Items 1 & 2)
    admitted_records: List[Tuple[datetime, Mapping[str, Any], Any]] = []
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

        # Formal Evaluation & Truth Eligibility Authority (Review Item 1)
        eligibility = evaluate_record_eligibility(rec, duplicate_index, target_kind="full_value")

        if not harness_verification:
            # Formal evaluation cohort requires formal eligibility
            if not eligibility.formally_eligible:
                excluded_count += 1
                r_key = eligibility.primary_reason or "FORMAL_ELIGIBILITY_REJECTED"
                excluded_reasons[r_key] = excluded_reasons.get(r_key, 0) + 1
                continue
        else:
            # Synthetic harness verification: test mechanics while verifying settlement truth
            truth_reasons, _ = _validate_truth_evidence(rec, "full_value")
            settlement = rec.get("settlement") if isinstance(rec.get("settlement"), Mapping) else {}
            if "truthEvidence" in settlement:
                if truth_reasons:
                    excluded_count += 1
                    r_key = truth_reasons[0]
                    excluded_reasons[r_key] = excluded_reasons.get(r_key, 0) + 1
                    continue
            else:
                if settlement.get("verified") is not True or not positive_finite(settlement.get("actualTotal")):
                    excluded_count += 1
                    excluded_reasons["SETTLEMENT_NOT_VERIFIED"] = (
                        excluded_reasons.get("SETTLEMENT_NOT_VERIFIED", 0) + 1
                    )
                    continue

        # Aware UTC timestamp normalization (Asia/Shanghai -> aware UTC instant)
        dt = canonical_timestamp_to_utc(rec)
        if dt is None:
            excluded_count += 1
            excluded_reasons["INVALID_OR_MISSING_PLAYED_AT"] = (
                excluded_reasons.get("INVALID_OR_MISSING_PLAYED_AT", 0) + 1
            )
            continue

        admitted_records.append((dt, rec, eligibility))

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

    for idx, (dt_cur, rec, el) in enumerate(admitted_records):
        actual_val = float(rec["settlement"]["actualTotal"])

        # 1. Strict No-Leakage Training Cohort for PR-B Red Lab
        # Only historical records strictly prior to current rec's dt_cur (datetime < dt_cur)!
        # Current rec NEVER enters its own training set!
        prior_history = [
            r_prior for dt_prior, r_prior, _ in admitted_records[:idx]
            if dt_prior < dt_cur
        ]

        # 2. Production Baseline: requires locked-down full-inventory prediction snapshot!
        # Validated via validate_prediction_snapshot; mode=full_shadow, coverageRatio>=0.999999,
        # target=full_inventory_actual_total, scope=full_inventory (Review Item 3)
        prod_pred, prod_err = extract_full_inventory_prediction(rec)

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

        # 5. PR-C Discrete Convolution (requires strict convolutionComponents with provenance)
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
            "harnessVerification": harness_verification,
            "performanceClaimEligible": False,
            "formalCohortMode": not harness_verification,
            "formalEligibleRecordCount": evaluated_count if not harness_verification else 0,
            "formalCohortAdmitted": (not harness_verification) and (evaluated_count > 0),
            "recordIdSelfLeakageGuard": True,
            "potentialDuplicateGuard": "exclude_all",
            "temporalPriorGuard": "strict",
            "stablePhysicalMatchIdentityAvailable": False,
            "leakageProofLevel": "record_id_known_potential_duplicate_and_temporal_prior",
            "physicalMatchLeakageImpossible": False,
            "absoluteZeroPhysicalLeakage": False,
            "noAutomatedWinnerDeclaration": True,
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
    perf_claim = meta.get("performanceClaimEligible", False)
    formal_mode = meta.get("formalCohortMode", False)
    formal_count = meta.get("formalEligibleRecordCount", 0)

    lines = [
        "# PR-C: Comparative Probability & Strategy Lab Evaluation Report",
        "",
        f"- **Status**: `{report.get('status')}`",
        f"- **Dataset Kind**: `{meta.get('datasetKind')}`",
        f"- **Harness Verification**: `{meta.get('harnessVerification')}`",
        f"- **Formal Cohort Mode**: `{formal_mode}`",
        f"- **Formal Eligible Record Count**: `{formal_count}`",
        f"- **Performance Claim Eligible**: `{perf_claim}`",
        f"- **Leakage Proof Level**: `{meta.get('leakageProofLevel')}`",
        f"- **Stable Physical Match Identity Available**: `{meta.get('stablePhysicalMatchIdentityAvailable')}`",
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
