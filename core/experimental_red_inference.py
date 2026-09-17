# -*- coding: utf-8 -*-
"""Experimental Red Probability Inference Lab (PR-B).

A strictly experimental, shadow-only module for inferring red quality (红色品质)
count probability mass functions (PMF), total-value distributions, and conditional
distributions from Canonical MatchRecord v7 / FINALIZED history.

Strict Invariants:
1. experimental = True, productionEligible = False.
2. Zero mutation of production solvers, six-quality joint constraints, or bidding lines.
3. Zero copying of competitor source code, weights, decay constants, or magic tables.
4. Input data must pass canonical history admission and eligibility gates.
5. Replay, test, synthetic, and mock records are strictly excluded from training history.
6. Default sampling assumption is explicitly 'unknown' (no assumed replacement model).
7. Known red items are observational evidence only ('observational_only').
8. Small or zero eligible samples strictly trigger insufficientData=True without smoothing.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

# Ensure project paths are in sys.path
_CORE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_CORE_DIR, ".."))
_APP_DIR = os.path.join(_PROJECT_ROOT, "app")
for _p in (_PROJECT_ROOT, _CORE_DIR, _APP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from history_admission import (
        DuplicateIndex,
        HistoryAdmissionDecision,
        build_duplicate_index,
        evaluate_history_admission,
    )
except ImportError:
    try:
        from app.history_admission import (
            DuplicateIndex,
            HistoryAdmissionDecision,
            build_duplicate_index,
            evaluate_history_admission,
        )
    except ImportError:
        DuplicateIndex = Any
        evaluate_history_admission = None
        build_duplicate_index = None

_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MIN_CONFIDENCE_SAMPLE_COUNT = 5
DISALLOWED_DATA_ORIGINS = frozenset({"replay", "test", "synthetic", "mock", "diagnostic"})


@dataclass(frozen=True)
class RedEligibilityBreakdown:
    record_id: str
    match_eligible: bool
    red_count_eligible: bool
    red_item_identity_eligible: bool
    warehouse_complete_eligible: bool
    exclusion_reasons: Tuple[str, ...]
    observed_red_count: Optional[int]
    observed_red_total_value: Optional[float]
    known_red_items: Tuple[Dict[str, Any], ...]
    played_at: Optional[str]
    venue: Optional[str]
    box: Optional[str]
    q: Optional[int]
    gold_avg: Optional[float]
    data_origin: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recordId": self.record_id,
            "matchEligible": self.match_eligible,
            "redCountEligible": self.red_count_eligible,
            "redItemIdentityEligible": self.red_item_identity_eligible,
            "warehouseCompleteEligible": self.warehouse_complete_eligible,
            "exclusionReasons": list(self.exclusion_reasons),
            "observedRedCount": self.observed_red_count,
            "observedRedTotalValue": self.observed_red_total_value,
            "knownRedItems": list(self.known_red_items),
            "playedAt": self.played_at,
            "venue": self.venue,
            "box": self.box,
            "q": self.q,
            "goldAvg": self.gold_avg,
            "dataOrigin": self.data_origin,
        }


@dataclass(frozen=True)
class SimilarityFeatures:
    venue: Optional[str] = None
    box: Optional[str] = None
    q: Optional[int] = None
    gold_avg: Optional[float] = None
    quality_counts: Dict[str, Optional[int]] = field(default_factory=dict)
    known_red_count: int = 0
    warehouse_evidence_class: Optional[str] = None


@dataclass(frozen=True)
class RedQuantiles:
    p10: Optional[float] = None
    p20: Optional[float] = None
    p25: Optional[float] = None
    p50: Optional[float] = None
    p75: Optional[float] = None
    p80: Optional[float] = None
    p90: Optional[float] = None
    p95: Optional[float] = None

    def to_dict(self) -> Dict[str, Optional[float]]:
        return {
            "p10": self.p10,
            "p20": self.p20,
            "p25": self.p25,
            "p50": self.p50,
            "p75": self.p75,
            "p80": self.p80,
            "p90": self.p90,
            "p95": self.p95,
        }

    def is_monotonic(self) -> bool:
        vals = [v for v in (self.p10, self.p20, self.p25, self.p50, self.p75, self.p80, self.p90, self.p95) if v is not None]
        for i in range(len(vals) - 1):
            if vals[i] > vals[i + 1]:
                return False
        return True


@dataclass
class RedInferenceReport:
    schema_version: int = SCHEMA_VERSION
    experimental: bool = True
    production_eligible: bool = False
    eligible_match_count: int = 0
    eligible_observation_count: int = 0
    effective_sample_weight: float = 0.0
    sampling_assumption: str = "unknown"
    conditioning_mode: str = "observational_only"
    red_count_pmf: Dict[int, float] = field(default_factory=dict)
    red_total_quantiles: RedQuantiles = field(default_factory=RedQuantiles)
    red_total_mean: Optional[float] = None
    red_total_median: Optional[float] = None
    conditional_distributions: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    history_evidence_ids: List[str] = field(default_factory=list)
    history_generation: int = 0
    warnings: List[str] = field(default_factory=list)
    insufficient_data: bool = True
    delta_vs_production: Dict[str, Any] = field(default_factory=dict)
    delta_vs_historical_shadow: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "experimental": self.experimental,
            "productionEligible": self.production_eligible,
            "eligibleMatchCount": self.eligible_match_count,
            "eligibleObservationCount": self.eligible_observation_count,
            "effectiveSampleWeight": round(self.effective_sample_weight, 4),
            "samplingAssumption": self.sampling_assumption,
            "conditioningMode": self.conditioning_mode,
            "redCountPmf": {str(k): round(v, 6) for k, v in sorted(self.red_count_pmf.items())},
            "redTotalQuantiles": self.red_total_quantiles.to_dict(),
            "redTotalMean": round(self.red_total_mean, 2) if self.red_total_mean is not None else None,
            "redTotalMedian": round(self.red_total_median, 2) if self.red_total_median is not None else None,
            "conditionalDistributions": self.conditional_distributions,
            "historyEvidenceIds": list(self.history_evidence_ids),
            "historyGeneration": self.history_generation,
            "warnings": list(self.warnings),
            "insufficientData": self.insufficient_data,
            "deltaVsProduction": self.delta_vs_production,
            "deltaVsHistoricalShadow": self.delta_vs_historical_shadow,
            "disclaimer": "实验结果 · 不参与正式出价",
        }


def _is_finite_nonnegative_int(val: Any) -> bool:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    return math.isfinite(val) and val >= 0 and int(val) == val


def _is_positive_finite(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val) and val > 0


def evaluate_record_red_eligibility(
    record: Mapping[str, Any],
    duplicate_index: Optional[Any] = None,
) -> RedEligibilityBreakdown:
    """Evaluate a canonical record across layered admission and red-specific eligibility gates."""
    rid = str(record.get("id") or "").strip()
    reasons: List[str] = []

    # 1. Base History Admission Check
    if evaluate_history_admission is not None and duplicate_index is not None:
        adm = evaluate_history_admission(record, duplicate_index)
        if not adm.admitted:
            reasons.append(f"ADMISSION_REJECTED_{adm.exclusion_reason or 'UNKNOWN'}")
    else:
        lifecycle = str(record.get("lifecycleStatus") or record.get("status") or "").upper()
        if lifecycle not in ("FINALIZED", "VERIFIED"):
            reasons.append(f"LIFECYCLE_NOT_FINALIZED_{lifecycle or 'NONE'}")

    # 2. Lifecycle Status Gate
    effective_lifecycle = str(record.get("lifecycleStatus") or record.get("status") or "").upper()
    if effective_lifecycle in ("DRAFT", "CANCELLED", "CANCELED"):
        if f"LIFECYCLE_{effective_lifecycle}" not in reasons:
            reasons.append(f"LIFECYCLE_{effective_lifecycle}")

    # 3. Data Origin Filter
    origin = str(record.get("dataOrigin") or "").strip().lower()
    if origin in DISALLOWED_DATA_ORIGINS:
        reasons.append(f"DISALLOWED_DATA_ORIGIN_{origin.upper()}")

    # 4. Diagnostic Flag Gate
    if record.get("diagnosticOnly") is True or str(record.get("solverStatus") or "").lower() == "diagnostic":
        reasons.append("DIAGNOSTIC_ONLY_RECORD")

    match_eligible = (len(reasons) == 0)

    # 5. Red Count Extraction & Verification
    observed_red_count: Optional[int] = None
    qualities = record.get("qualities") if isinstance(record.get("qualities"), Mapping) else {}
    red_q = qualities.get("red") if isinstance(qualities.get("red"), Mapping) else {}
    raw_count = red_q.get("count")
    if _is_finite_nonnegative_int(raw_count):
        observed_red_count = int(raw_count)

    settlement = record.get("settlement") if isinstance(record.get("settlement"), Mapping) else {}
    st_items = settlement.get("settlementItems") if isinstance(settlement.get("settlementItems"), list) else []
    red_st_items = [
        item for item in st_items
        if isinstance(item, Mapping) and str(item.get("quality") or item.get("rarity") or "").lower() in ("red", "红")
    ]
    if observed_red_count is None and settlement.get("verified") is True and len(st_items) > 0:
        observed_red_count = len(red_st_items)

    red_count_eligible = match_eligible and (observed_red_count is not None)

    # 6. Red Item Identity & Value Extraction
    known_items = red_q.get("knownItems") if isinstance(red_q.get("knownItems"), list) else []
    known_red_items = tuple(it for it in known_items if isinstance(it, dict))

    confirmed_red_identities = []
    total_val = 0.0
    val_complete = False

    if red_st_items:
        has_all_vals = True
        for it in red_st_items:
            name = str(it.get("name") or it.get("itemName") or "").strip()
            if name:
                confirmed_red_identities.append(name)
            v = it.get("value") or it.get("price") or it.get("unitPrice")
            if _is_positive_finite(v):
                total_val += float(v)
            else:
                has_all_vals = False
        if has_all_vals and len(red_st_items) == observed_red_count:
            val_complete = True

    if observed_red_count == 0:
        observed_red_total_value = 0.0
        val_complete = True
        red_item_identity_eligible = match_eligible
    elif val_complete:
        observed_red_total_value = total_val
        red_item_identity_eligible = match_eligible and len(confirmed_red_identities) > 0
    else:
        observed_red_total_value = None
        red_item_identity_eligible = False

    # 7. Warehouse Complete Gate
    warehouse_complete = bool(red_q.get("redInventoryComplete") is True or (settlement.get("verified") is True and len(st_items) > 0))
    warehouse_complete_eligible = match_eligible and warehouse_complete

    # Context fields
    env = record.get("environment") if isinstance(record.get("environment"), Mapping) else {}
    venue = str(record.get("venue") or env.get("venue") or env.get("venueTier") or "").strip() or None
    box = str(record.get("box") or env.get("box") or env.get("boxType") or "").strip() or None
    pub = record.get("publicIntel") if isinstance(record.get("publicIntel"), Mapping) else {}
    raw_q = pub.get("q") if pub.get("q") is not None else record.get("q")
    q_val = int(raw_q) if _is_finite_nonnegative_int(raw_q) else None
    gold_avg = None
    gold_q = qualities.get("gold") if isinstance(qualities.get("gold"), Mapping) else {}
    raw_gold_avg = gold_q.get("avg") if gold_q.get("avg") is not None else record.get("goldAvg")
    if _is_positive_finite(raw_gold_avg):
        gold_avg = float(raw_gold_avg)

    return RedEligibilityBreakdown(
        record_id=rid,
        match_eligible=match_eligible,
        red_count_eligible=red_count_eligible,
        red_item_identity_eligible=red_item_identity_eligible,
        warehouse_complete_eligible=warehouse_complete_eligible,
        exclusion_reasons=tuple(reasons),
        observed_red_count=observed_red_count,
        observed_red_total_value=observed_red_total_value,
        known_red_items=known_red_items,
        played_at=str(record.get("playedAt") or record.get("timestamp") or "").strip() or None,
        venue=venue,
        box=box,
        q=q_val,
        gold_avg=gold_avg,
        data_origin=origin or None,
    )


def compute_canonical_similarity(
    context_features: SimilarityFeatures,
    candidate: RedEligibilityBreakdown,
) -> float:
    """Compute independent multi-feature canonical similarity score between context and candidate record."""
    if candidate.observed_red_count is not None and context_features.known_red_count > candidate.observed_red_count:
        return 0.0

    sim_venue = 1.0
    if context_features.venue and candidate.venue:
        sim_venue = 1.0 if context_features.venue == candidate.venue else 0.3

    sim_box = 1.0
    if context_features.box and candidate.box:
        sim_box = 1.0 if context_features.box == candidate.box else 0.4

    sim_q = 1.0
    if context_features.q is not None and candidate.q is not None:
        q_diff = abs(context_features.q - candidate.q)
        sim_q = 1.0 / (1.0 + 0.1 * q_diff)

    return max(0.01, sim_venue * sim_box * sim_q)


def _compute_weighted_quantiles(
    values: Sequence[float],
    weights: Sequence[float],
) -> RedQuantiles:
    """Compute weighted quantiles enforcing strict monotonicity."""
    if not values or not weights or len(values) != len(weights):
        return RedQuantiles()

    sorted_pairs = sorted(zip(values, weights), key=lambda p: p[0])
    sorted_vals = [p[0] for p in sorted_pairs]
    sorted_weights = [p[1] for p in sorted_pairs]
    total_w = sum(sorted_weights)
    if total_w <= 0:
        return RedQuantiles()

    cum_weights = []
    c = 0.0
    for w in sorted_weights:
        c += w
        cum_weights.append(c / total_w)

    def _interp_quantile(q: float) -> float:
        for i, cw in enumerate(cum_weights):
            if cw >= q:
                return float(sorted_vals[i])
        return float(sorted_vals[-1])

    p10 = _interp_quantile(0.10)
    p20 = _interp_quantile(0.20)
    p25 = _interp_quantile(0.25)
    p50 = _interp_quantile(0.50)
    p75 = _interp_quantile(0.75)
    p80 = _interp_quantile(0.80)
    p90 = _interp_quantile(0.90)
    p95 = _interp_quantile(0.95)

    p20 = max(p10, p20)
    p25 = max(p20, p25)
    p50 = max(p25, p50)
    p75 = max(p50, p75)
    p80 = max(p75, p80)
    p90 = max(p80, p90)
    p95 = max(p90, p95)

    return RedQuantiles(
        p10=p10,
        p20=p20,
        p25=p25,
        p50=p50,
        p75=p75,
        p80=p80,
        p90=p90,
        p95=p95,
    )


class ExperimentalRedInferenceLab:
    """Stateful coordinator for the experimental red probability inference lab."""

    def __init__(self, history_records: Optional[Sequence[Mapping[str, Any]]] = None):
        self._records_cache: Dict[str, Mapping[str, Any]] = {}
        self._eligibility_cache: Dict[str, RedEligibilityBreakdown] = {}
        self._duplicate_index: Optional[Any] = None
        self._history_generation: int = 0
        if history_records:
            self.set_records(history_records)

    @property
    def history_generation(self) -> int:
        return self._history_generation

    def clear(self) -> None:
        self._records_cache.clear()
        self._eligibility_cache.clear()
        self._duplicate_index = None
        self._history_generation += 1

    def set_records(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Replace all records idempotently."""
        self._records_cache.clear()
        self._eligibility_cache.clear()
        if build_duplicate_index is not None:
            self._duplicate_index = build_duplicate_index(records)
        else:
            self._duplicate_index = None

        for r in records:
            if isinstance(r, Mapping):
                rid = str(r.get("id") or "").strip()
                if rid and rid not in self._records_cache:
                    self._records_cache[rid] = r
                    self._eligibility_cache[rid] = evaluate_record_red_eligibility(r, self._duplicate_index)

        self._history_generation += 1

    def ingest_record(self, record: Mapping[str, Any]) -> bool:
        """Idempotently ingest a single record."""
        if not isinstance(record, Mapping):
            return False
        rid = str(record.get("id") or "").strip()
        if not rid:
            return False
        if rid in self._records_cache:
            return False

        self._records_cache[rid] = record
        all_recs = list(self._records_cache.values())
        if build_duplicate_index is not None:
            self._duplicate_index = build_duplicate_index(all_recs)
        self._eligibility_cache[rid] = evaluate_record_red_eligibility(record, self._duplicate_index)
        self._history_generation += 1
        return True

    def evaluate_inference(
        self,
        session_ctx: Mapping[str, Any],
        production_metrics: Optional[Mapping[str, Any]] = None,
        shadow_profile: Optional[Mapping[str, Any]] = None,
    ) -> RedInferenceReport:
        """Evaluate experimental red probability and value distribution for a given session context."""
        warnings: List[str] = []

        venue = session_ctx.get("venue") or (session_ctx.get("environment") or {}).get("venue")
        box = session_ctx.get("box") or (session_ctx.get("environment") or {}).get("box")
        q = session_ctx.get("q")
        gold_avg = session_ctx.get("goldAvg") or session_ctx.get("avg")

        known_red_raw = session_ctx.get("knownRed")
        if isinstance(known_red_raw, list):
            known_red_count = len(known_red_raw)
        elif isinstance(known_red_raw, str) and known_red_raw.strip():
            known_red_count = len([p for p in known_red_raw.split("+") if p.strip()])
        elif isinstance(known_red_raw, (int, float)):
            known_red_count = int(known_red_raw)
        else:
            known_red_count = 0

        features = SimilarityFeatures(
            venue=str(venue).strip() if venue else None,
            box=str(box).strip() if box else None,
            q=int(q) if _is_finite_nonnegative_int(q) else None,
            gold_avg=float(gold_avg) if _is_positive_finite(gold_avg) else None,
            known_red_count=known_red_count,
        )

        eligible_candidates: List[Tuple[RedEligibilityBreakdown, float]] = []
        for cand in self._eligibility_cache.values():
            if not cand.match_eligible or not cand.red_count_eligible:
                continue
            sim = compute_canonical_similarity(features, cand)
            if sim > 0:
                eligible_candidates.append((cand, sim))

        eligible_match_count = len(eligible_candidates)
        total_effective_weight = sum(sim for _, sim in eligible_candidates)

        insufficient_data = (
            eligible_match_count < MIN_CONFIDENCE_SAMPLE_COUNT
            or total_effective_weight < float(MIN_CONFIDENCE_SAMPLE_COUNT) * 0.5
        )
        if eligible_match_count == 0:
            warnings.append("No eligible canonical history matches observed for red inference.")
        elif insufficient_data:
            warnings.append(
                f"Small sample warning: only {eligible_match_count} eligible history observations available; "
                "insufficient for high-confidence statistical inference."
            )

        red_count_pmf: Dict[int, float] = {}
        if eligible_candidates and total_effective_weight > 0:
            count_weights: Dict[int, float] = {}
            for cand, weight in eligible_candidates:
                rc = cand.observed_red_count
                if rc is not None:
                    count_weights[rc] = count_weights.get(rc, 0.0) + weight

            sum_w = sum(count_weights.values())
            if sum_w > 0:
                for k, w in count_weights.items():
                    red_count_pmf[k] = w / sum_w

        val_samples: List[float] = []
        val_weights: List[float] = []
        for cand, weight in eligible_candidates:
            if cand.observed_red_total_value is not None:
                val_samples.append(cand.observed_red_total_value)
                val_weights.append(weight)

        quantiles = RedQuantiles()
        mean_val: Optional[float] = None
        median_val: Optional[float] = None

        if val_samples and sum(val_weights) > 0:
            quantiles = _compute_weighted_quantiles(val_samples, val_weights)
            median_val = quantiles.p50
            mean_val = sum(v * w for v, w in zip(val_samples, val_weights)) / sum(val_weights)
        else:
            warnings.append("Insufficient verified red item settlement values; total value quantiles unavailable.")

        conditional_dists: Dict[int, Dict[str, Any]] = {}
        for k in sorted(red_count_pmf.keys()):
            k_samples = [cand.observed_red_total_value for cand, _ in eligible_candidates if cand.observed_red_count == k and cand.observed_red_total_value is not None]
            k_weights = [weight for cand, weight in eligible_candidates if cand.observed_red_count == k and cand.observed_red_total_value is not None]
            if k_samples:
                k_q = _compute_weighted_quantiles(k_samples, k_weights)
                k_mean = sum(v * w for v, w in zip(k_samples, k_weights)) / sum(k_weights)
                conditional_dists[k] = {
                    "sampleCount": len(k_samples),
                    "mean": round(k_mean, 2),
                    "quantiles": k_q.to_dict(),
                    "samplingAssumption": "unknown",
                }
            else:
                conditional_dists[k] = {
                    "sampleCount": 0,
                    "mean": None,
                    "quantiles": RedQuantiles().to_dict(),
                    "samplingAssumption": "unknown",
                }

        delta_vs_prod: Dict[str, Any] = {}
        if production_metrics:
            prod_med = production_metrics.get("medianEstimate")
            if prod_med is not None and median_val is not None:
                delta_vs_prod["medianDelta"] = round(median_val - float(prod_med), 2)
            prod_mean = production_metrics.get("meanEstimate")
            if prod_mean is not None and mean_val is not None:
                delta_vs_prod["meanDelta"] = round(mean_val - float(prod_mean), 2)

        delta_vs_shadow: Dict[str, Any] = {}
        if shadow_profile:
            shadow_p50 = shadow_profile.get("p50")
            if shadow_p50 is not None and median_val is not None:
                delta_vs_shadow["p50Delta"] = round(median_val - float(shadow_p50), 2)
            shadow_p20 = shadow_profile.get("p20")
            if shadow_p20 is not None and quantiles.p20 is not None:
                delta_vs_shadow["p20Delta"] = round(quantiles.p20 - float(shadow_p20), 2)

        return RedInferenceReport(
            schema_version=SCHEMA_VERSION,
            experimental=True,
            production_eligible=False,
            eligible_match_count=eligible_match_count,
            eligible_observation_count=len(val_samples),
            effective_sample_weight=total_effective_weight,
            sampling_assumption="unknown",
            conditioning_mode="observational_only",
            red_count_pmf=red_count_pmf,
            red_total_quantiles=quantiles,
            red_total_mean=mean_val,
            red_total_median=median_val,
            conditional_distributions=conditional_dists,
            history_evidence_ids=[cand.record_id for cand, _ in eligible_candidates],
            history_generation=self._history_generation,
            warnings=warnings,
            insufficient_data=insufficient_data,
            delta_vs_production=delta_vs_prod,
            delta_vs_historical_shadow=delta_vs_shadow,
        )


_GLOBAL_RED_LAB: Optional[ExperimentalRedInferenceLab] = None


def get_authoritative_red_inference_lab() -> ExperimentalRedInferenceLab:
    """Singleton getter for the runtime Red Inference Lab."""
    global _GLOBAL_RED_LAB
    if _GLOBAL_RED_LAB is None:
        _GLOBAL_RED_LAB = ExperimentalRedInferenceLab()
        try:
            from live_shadow import load_history_snapshot
            recs = load_history_snapshot()
            if recs:
                _GLOBAL_RED_LAB.set_records(recs)
        except Exception as e:
            _LOG.warning("Could not pre-load live history snapshot for RedInferenceLab: %s", e)
    return _GLOBAL_RED_LAB
