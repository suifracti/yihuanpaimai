# -*- coding: utf-8 -*-
"""Experimental Red Probability Inference Lab (PR-B).

A strictly experimental, shadow-only module for inferring red quality (红色品质)
count probability mass functions (PMF), total-value distributions, and conditional
distributions from Canonical MatchRecord v7 / FINALIZED history.

Strict Invariants:
1. experimental = True, productionEligible = False.
2. Zero mutation of production solvers, six-quality joint constraints, or bidding lines.
3. Zero copying of competitor source code, weights, decay constants, or magic tables.
4. Input data must pass canonical history admission and post-settlement truth gates.
5. Replay, test, synthetic, and mock records are strictly excluded from training history.
6. Default sampling assumption is explicitly 'unknown' (no assumed replacement model).
7. Known red items are observational evidence only ('observational_only').
8. Small or zero eligible samples strictly trigger insufficientData=True without smoothing.
9. Runtime calls must be fail-isolated (exceptions never crash production solve/HUD).
10. O(1) cached lookups using (historyGeneration, contextFingerprint).
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

SIMILARITY_PROFILE = {
    "similarityProfileVersion": "v1_canonical_coarse",
    "featuresUsed": ["venue", "box", "q"],
    "feasibilityGates": ["knownRedCount"],
}


@dataclass(frozen=True)
class RedEligibilityBreakdown:
    record_id: str
    match_eligible: bool
    red_count_eligible: bool
    red_item_identity_eligible: bool
    red_total_value_eligible: bool
    warehouse_complete_eligible: bool
    red_count_truth_source: str
    red_identity_truth_source: str
    red_value_truth_source: str
    warehouse_completeness_source: str
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
            "redTotalValueEligible": self.red_total_value_eligible,
            "warehouseCompleteEligible": self.warehouse_complete_eligible,
            "redCountTruthSource": self.red_count_truth_source,
            "redIdentityTruthSource": self.red_identity_truth_source,
            "redValueTruthSource": self.red_value_truth_source,
            "warehouseCompletenessSource": self.warehouse_completeness_source,
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
    similarity_profile: Dict[str, Any] = field(default_factory=lambda: dict(SIMILARITY_PROFILE))
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
            "similarityProfile": self.similarity_profile,
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
    """Evaluate a canonical record across strict layered admission and verified truth gates (Fix A, B, C)."""
    rid = str(record.get("id") or "").strip()
    reasons: List[str] = []

    # 1. Base History Admission Check & Duplicate Fail-Closed Exclusion (Final Fix B)
    if duplicate_index is not None:
        if rid in duplicate_index.duplicate_record_ids:
            reasons.append("DUPLICATE_RECORD_ID")
        if rid in duplicate_index.potential_content_duplicate_ids:
            reasons.append("POTENTIAL_CONTENT_DUPLICATE")

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

    # 5. Whole-Warehouse Coverage Completeness Gate (Final Fix 1)
    # Authority must be strictly two-axis:
    # Axis 1: Coverage Truth: whole inventory covered / all red slots observed?
    # Axis 2: Identity Truth: observed items exact?
    qualities = record.get("qualities") if isinstance(record.get("qualities"), Mapping) else {}
    red_q = qualities.get("red") if isinstance(qualities.get("red"), Mapping) else {}
    settlement = record.get("settlement") if isinstance(record.get("settlement"), Mapping) else {}
    warehouse = record.get("warehouse") if isinstance(record.get("warehouse"), Mapping) else {}
    review_units = record.get("reviewUnits") or settlement.get("reviewUnits") or []
    field_states = record.get("fieldStates") if isinstance(record.get("fieldStates"), Mapping) else {}
    wh_cov = settlement.get("warehouseCoverage") if isinstance(settlement.get("warehouseCoverage"), Mapping) else {}
    wh_rev = settlement.get("warehouseIdentityReview") if isinstance(settlement.get("warehouseIdentityReview"), Mapping) else {}

    coverage_complete = False
    coverage_completeness_source = "UNVERIFIED_OR_PARTIAL_WAREHOUSE"

    # Authority A: Canonical coverage status = COMPLETE (from ledger or canonical match record)
    if str(record.get("coverageStatus") or "").strip().upper() == "COMPLETE":
        coverage_complete = True
        coverage_completeness_source = "CANONICAL_RECORD_COVERAGE_COMPLETE"
    elif str(settlement.get("warehouseCoverageStatus") or "").strip().upper() == "COMPLETE":
        coverage_complete = True
        coverage_completeness_source = "CANONICAL_SETTLEMENT_COVERAGE_COMPLETE"
    elif str(wh_cov.get("status") or "").strip().upper() == "COMPLETE":
        coverage_complete = True
        coverage_completeness_source = "CANONICAL_WAREHOUSE_COVERAGE_DOC_COMPLETE"
    elif str(warehouse.get("coverageStatus") or "").strip().upper() == "COMPLETE":
        coverage_complete = True
        coverage_completeness_source = "CANONICAL_WAREHOUSE_COVERAGE_COMPLETE"
    elif str(wh_rev.get("warehouseCoverageStatus") or "").strip().upper() == "COMPLETE":
        coverage_complete = True
        coverage_completeness_source = "CANONICAL_REVIEW_COVERAGE_COMPLETE"

    # Authority B: Settlement TruthEvidence with complete inventoryScope and verified post-settlement warehouse
    if not coverage_complete:
        truth_ev = settlement.get("truthEvidence") if isinstance(settlement.get("truthEvidence"), Mapping) else {}
        if truth_ev:
            inv_scope = truth_ev.get("inventoryScope") if isinstance(truth_ev.get("inventoryScope"), Mapping) else {}
            truth_src = str(truth_ev.get("truthSource") or "").strip().lower()
            if inv_scope.get("complete") is True and truth_src in (
                "post_settlement_verified_warehouse",
                "post-settlement-warehouse",
                "canonical_coverage_complete",
                "post-settlement verified warehouse",
            ):
                coverage_complete = True
                coverage_completeness_source = "SETTLEMENT_TRUTH_EVIDENCE_WAREHOUSE_COMPLETE"

    # Authority C: redInventoryComplete with explicit trusted post-settlement / canonical provenance
    if not coverage_complete and red_q.get("redInventoryComplete") is True:
        # Verify provenance is trusted and not manual / auction / solver / pre-settlement
        red_field_state = field_states.get("redInventoryComplete") if isinstance(field_states.get("redInventoryComplete"), Mapping) else {}
        red_fs_source = str(red_field_state.get("source") or "").strip().lower()
        prov = str(
            red_q.get("provenance")
            or red_q.get("source")
            or red_q.get("redInventoryCompleteSource")
            or record.get("redInventoryCompleteProvenance")
            or ""
        ).strip().lower()

        if red_fs_source in ("manual", "auction", "solver", "pre-settlement", "vision_pre_settlement", "legacy"):
            coverage_complete = False
            coverage_completeness_source = f"RED_INVENTORY_COMPLETE_DISALLOWED_FIELDSTATE_{red_fs_source.upper()}"
        elif prov in (
            "post_settlement_verified_warehouse",
            "canonical_coverage_complete",
            "post-settlement verified warehouse",
        ):
            coverage_complete = True
            coverage_completeness_source = "RED_INVENTORY_COMPLETE_TRUSTED_PROVENANCE"
        else:
            coverage_complete = False
            coverage_completeness_source = "RED_INVENTORY_COMPLETE_LACKS_TRUSTED_PROVENANCE"

    warehouse_complete_eligible = coverage_complete and match_eligible
    warehouse_completeness_source = coverage_completeness_source

    # 6. Red Count Ground Truth Gate (Final Semantic Fix A)
    # Strictly TWO authorities permitted:
    # Authority 1: trusted redInventoryComplete
    #   - redInventoryComplete == True
    #   - explicit finite non-negative int count
    #   - trusted provenance (post_settlement_verified_warehouse or canonical_coverage_complete)
    #   - fieldStates/source NOT in (manual, auction, solver, pre-settlement, vision_pre_settlement, legacy, unknown)
    # Authority 2: Complete physical ledger + complete quality/rarity classification
    #   - whole warehouse coverage COMPLETE
    #   - every physical item/unit in the complete ledger has trusted rarity/quality classification
    #   - R = count of units classified red
    # If any unit has quality unknown/unclassified -> redCountEligible = False (even if coverage COMPLETE)
    # DELETE default R=0! "没看到红" cannot be inferred as R=0!
    # settlementVerifiedRedItems is NEVER a direct red-count authority!

    observed_red_count: Optional[int] = None
    red_count_eligible = False
    red_count_truth_source = "UNVERIFIED_AUCTION_OR_OCR"

    # Authority 1: Trusted redInventoryComplete
    auth1_applied = False
    if red_q.get("redInventoryComplete") is True and _is_finite_nonnegative_int(red_q.get("count")):
        red_field_state = field_states.get("redInventoryComplete") if isinstance(field_states.get("redInventoryComplete"), Mapping) else {}
        red_fs_source = str(red_field_state.get("source") or "").strip().lower()
        prov = str(
            red_q.get("provenance")
            or red_q.get("source")
            or red_q.get("redInventoryCompleteSource")
            or record.get("redInventoryCompleteProvenance")
            or ""
        ).strip().lower()

        is_disallowed_source = red_fs_source in (
            "manual", "auction", "solver", "pre-settlement", "vision_pre_settlement", "legacy", "unknown"
        )
        is_trusted_prov = prov in (
            "post_settlement_verified_warehouse",
            "canonical_coverage_complete",
            "post-settlement verified warehouse",
        )

        if is_trusted_prov and not is_disallowed_source:
            observed_red_count = int(red_q.get("count"))
            red_count_eligible = match_eligible
            red_count_truth_source = "TRUSTED_RED_INVENTORY_COMPLETE"
            auth1_applied = True

    # Authority 2: Complete physical ledger + complete quality/rarity classification
    if not auth1_applied:
        if warehouse_complete_eligible:
            CANONICAL_RARITIES = frozenset({
                "red", "gold", "purple", "blue", "green", "white",
                "红", "金", "紫", "蓝", "绿", "白",
            })

            ledger_units: Optional[Sequence[Any]] = None
            if isinstance(review_units, list) and len(review_units) > 0:
                ledger_units = review_units
            elif isinstance(settlement.get("settlementItems"), list) and len(settlement.get("settlementItems")) > 0:
                ledger_units = settlement.get("settlementItems")
            elif isinstance(warehouse.get("slots"), list) and len(warehouse.get("slots")) > 0:
                ledger_units = warehouse.get("slots")

            if ledger_units is not None and len(ledger_units) > 0:
                all_units_classified = True
                classified_red_count = 0
                for unit in ledger_units:
                    if not isinstance(unit, Mapping):
                        all_units_classified = False
                        break
                    raw_q = unit.get("quality") or unit.get("rarity")
                    if not raw_q or not isinstance(raw_q, str):
                        all_units_classified = False
                        break
                    norm_q = raw_q.strip().lower()
                    if norm_q not in CANONICAL_RARITIES:
                        all_units_classified = False
                        break
                    if norm_q in ("red", "红"):
                        classified_red_count += 1

                if all_units_classified:
                    observed_red_count = classified_red_count
                    red_count_eligible = match_eligible
                    red_count_truth_source = "COMPLETE_LEDGER_FULL_QUALITY_CLASSIFICATION"
                else:
                    red_count_eligible = False
                    red_count_truth_source = "QUALITY_CLASSIFICATION_INCOMPLETE"
                    reasons.append("QUALITY_CLASSIFICATION_INCOMPLETE")
            elif warehouse.get("itemCount") == 0:
                observed_red_count = 0
                red_count_eligible = match_eligible
                red_count_truth_source = "COMPLETE_LEDGER_EMPTY_WAREHOUSE"
            else:
                red_count_eligible = False
                red_count_truth_source = "PHYSICAL_LEDGER_UNITS_MISSING"
                reasons.append("PHYSICAL_LEDGER_UNITS_MISSING")
        else:
            if red_q.get("settlementVerifiedRedItems"):
                red_count_truth_source = "VERIFIED_RED_SUBSET_WITHOUT_COVERAGE_PROOF"
                reasons.append("VERIFIED_RED_SUBSET_WITHOUT_COVERAGE_PROOF")
            else:
                red_count_truth_source = "UNVERIFIED_AUCTION_OR_OCR"
                reasons.append("RED_COUNT_LACKS_VERIFIED_POST_SETTLEMENT_OR_WAREHOUSE_TRUTH")

    # 7. Red Item Identity & Value Truth Gate (Final Semantic Fix A)
    # Total value truth requires:
    # - redCountEligible == True
    # - complete red-item set available (len(candidate_red_items) == observed_red_count)
    # - every red identity exact (CONFIRMED or EXACT_IDENTIFIED)
    # - every red value finite positive (> 0)
    known_items = red_q.get("knownItems") if isinstance(red_q.get("knownItems"), list) else []
    known_red_items = tuple(it for it in known_items if isinstance(it, dict))

    observed_red_total_value: Optional[float] = None
    red_item_identity_eligible = False
    red_total_value_eligible = False
    red_identity_truth_source = "UNVERIFIED_RED_IDENTITIES"
    red_value_truth_source = "UNVERIFIED_RED_VALUES"

    if not red_count_eligible:
        red_item_identity_eligible = False
        red_total_value_eligible = False
        red_value_truth_source = "RED_COUNT_NOT_ELIGIBLE"
    elif observed_red_count == 0:
        observed_red_total_value = 0.0
        red_item_identity_eligible = match_eligible
        red_total_value_eligible = match_eligible
        red_identity_truth_source = "VERIFIED_ZERO_RED_COMPLETE"
        red_value_truth_source = "VERIFIED_ZERO_RED_COMPLETE"
    elif observed_red_count is not None and observed_red_count > 0:
        # Collect candidate red items from available verified sources
        candidate_items = []
        if isinstance(review_units, list) and len(review_units) > 0:
            candidate_items = [
                u for u in review_units
                if isinstance(u, dict) and str(u.get("quality") or u.get("rarity") or "").strip().lower() in ("red", "红")
            ]
        elif isinstance(settlement.get("settlementItems"), list) and len(settlement.get("settlementItems")) > 0:
            candidate_items = [
                u for u in settlement["settlementItems"]
                if isinstance(u, dict) and str(u.get("quality") or u.get("rarity") or "").strip().lower() in ("red", "红")
            ]
        elif isinstance(warehouse.get("slots"), list) and len(warehouse.get("slots")) > 0:
            candidate_items = [
                u for u in warehouse["slots"]
                if isinstance(u, dict) and str(u.get("quality") or u.get("rarity") or "").strip().lower() in ("red", "红")
            ]
        elif isinstance(red_q.get("settlementVerifiedRedItems"), list) and len(red_q.get("settlementVerifiedRedItems")) > 0:
            candidate_items = [
                u for u in red_q["settlementVerifiedRedItems"]
                if isinstance(u, dict)
            ]
        elif isinstance(settlement.get("settlementVerifiedRedItems"), list) and len(settlement.get("settlementVerifiedRedItems")) > 0:
            candidate_items = [
                u for u in settlement["settlementVerifiedRedItems"]
                if isinstance(u, dict)
            ]

        if len(candidate_items) == observed_red_count:
            all_exact = True
            all_valued = True
            tot_v = 0.0
            for item in candidate_items:
                conf_status = str(item.get("confirmationStatus") or "").upper()
                ident_status = str(item.get("identityStatus") or "").upper()
                # Strict exact identity: ONLY CONFIRMED or EXACT_IDENTIFIED (no generic confirmed=True fallback!)
                is_exact = (conf_status == "CONFIRMED" or ident_status == "EXACT_IDENTIFIED")
                if not is_exact:
                    all_exact = False
                val = item.get("value") or item.get("price") or item.get("unitPrice")
                if _is_positive_finite(val):
                    tot_v += float(val)
                else:
                    all_valued = False

            if all_exact and all_valued:
                observed_red_total_value = tot_v
                red_item_identity_eligible = match_eligible
                red_total_value_eligible = match_eligible
                red_identity_truth_source = "EXACT_CONFIRMED_RED_ITEMS"
                red_value_truth_source = "EXACT_CONFIRMED_RED_PRICES"
            elif all_exact:
                red_item_identity_eligible = match_eligible
                red_total_value_eligible = False
                red_identity_truth_source = "EXACT_CONFIRMED_RED_ITEMS"
                red_value_truth_source = "AMBIGUOUS_OR_MISSING_RED_VALUES"
            else:
                red_item_identity_eligible = False
                red_total_value_eligible = False
                red_identity_truth_source = "AMBIGUOUS_OR_CANDIDATE_RED_ITEMS"
                red_value_truth_source = "AMBIGUOUS_OR_CANDIDATE_RED_ITEMS"
        else:
            red_item_identity_eligible = False
            red_total_value_eligible = False
            red_identity_truth_source = "INCOMPLETE_RED_ITEMS_RECORDED"
            red_value_truth_source = "INCOMPLETE_RED_ITEMS_RECORDED"

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
        red_total_value_eligible=red_total_value_eligible,
        warehouse_complete_eligible=warehouse_complete_eligible,
        red_count_truth_source=red_count_truth_source,
        red_identity_truth_source=red_identity_truth_source,
        red_value_truth_source=red_value_truth_source,
        warehouse_completeness_source=warehouse_completeness_source,
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
    """Compute independent multi-feature canonical similarity score (Fix K: honest declaration).

    Features used: venue, box, q.
    Feasibility gate: knownRedCount <= candidate.observed_red_count.
    """
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
    """Stateful coordinator for the experimental red probability inference lab (Fix E, F, G)."""

    def __init__(self, history_records: Optional[Sequence[Mapping[str, Any]]] = None):
        self._records_cache: Dict[str, Mapping[str, Any]] = {}
        self._eligibility_cache: Dict[str, RedEligibilityBreakdown] = {}
        self._eval_cache: Dict[Tuple[int, str], RedInferenceReport] = {}
        self._duplicate_index: Optional[Any] = None
        self._history_generation: int = 0
        self._source_history_generation: Optional[int] = None
        if history_records:
            self.set_records(history_records)

    @property
    def history_generation(self) -> int:
        return self._history_generation

    def clear(self) -> None:
        self._records_cache.clear()
        self._eligibility_cache.clear()
        self._eval_cache.clear()
        self._duplicate_index = None
        self._history_generation += 1

    def sync_with_live_history(self) -> bool:
        """Cheap generation sync: reloads canonical snapshot only when source history generation changed (Fix F)."""
        try:
            import live_shadow
            current_source_gen = live_shadow.history_generation()
            if current_source_gen != self._source_history_generation:
                recs = live_shadow.load_history_snapshot()
                self.set_records(recs)
                self._source_history_generation = current_source_gen
                return True
        except Exception as e:
            _LOG.warning("Failed cheap generation sync with live_shadow: %s", e)
        return False

    def set_records(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Replace all records idempotently."""
        self._records_cache.clear()
        self._eligibility_cache.clear()
        self._eval_cache.clear()

        valid_recs = [r for r in records if isinstance(r, Mapping)]
        if build_duplicate_index is not None:
            self._duplicate_index = build_duplicate_index(valid_recs)
        else:
            self._duplicate_index = None

        for r in valid_recs:
            rid = str(r.get("id") or "").strip()
            if rid and rid not in self._records_cache:
                self._records_cache[rid] = r
                self._eligibility_cache[rid] = evaluate_record_red_eligibility(r, self._duplicate_index)

        self._history_generation += 1

    def ingest_record(self, record: Mapping[str, Any]) -> bool:
        """Idempotently ingest a single record and re-evaluate all records' duplicate eligibility (Fix G)."""
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
        else:
            self._duplicate_index = None

        # Re-evaluate eligibility for ALL records to ensure duplicate status updates (Fix G)
        self._eligibility_cache = {
            r_id: evaluate_record_red_eligibility(rec, self._duplicate_index)
            for r_id, rec in self._records_cache.items()
        }
        self._eval_cache.clear()
        self._history_generation += 1
        return True

    def evaluate_inference(
        self,
        session_ctx: Mapping[str, Any],
        production_metrics: Optional[Mapping[str, Any]] = None,
        shadow_profile: Optional[Mapping[str, Any]] = None,
    ) -> RedInferenceReport:
        """Evaluate experimental red probability and value distribution with O(1) snapshot caching (Fix E)."""
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

        # Check O(1) cache before running full history scan
        fingerprint = f"{venue}|{box}|{q}|{known_red_count}"
        cache_key = (self._history_generation, fingerprint)
        if cache_key in self._eval_cache:
            cached_base = self._eval_cache[cache_key]
            # Attach current production deltas without recomputing distribution
            return self._attach_deltas(cached_base, production_metrics, shadow_profile)

        warnings: List[str] = []
        features = SimilarityFeatures(
            venue=str(venue).strip() if venue else None,
            box=str(box).strip() if box else None,
            q=int(q) if _is_finite_nonnegative_int(q) else None,
            gold_avg=float(gold_avg) if _is_positive_finite(gold_avg) else None,
            known_red_count=known_red_count,
        )

        # 1. Gather Eligible Red Count Candidates (Fix A & C)
        eligible_count_candidates: List[Tuple[RedEligibilityBreakdown, float]] = []
        for cand in self._eligibility_cache.values():
            if not cand.match_eligible or not cand.red_count_eligible:
                continue
            sim = compute_canonical_similarity(features, cand)
            if sim > 0:
                eligible_count_candidates.append((cand, sim))

        eligible_match_count = len(eligible_count_candidates)
        total_effective_weight = sum(sim for _, sim in eligible_count_candidates)

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

        # 2. Compute Red Count PMF
        red_count_pmf: Dict[int, float] = {}
        if eligible_count_candidates and total_effective_weight > 0:
            count_weights: Dict[int, float] = {}
            for cand, weight in eligible_count_candidates:
                rc = cand.observed_red_count
                if rc is not None:
                    count_weights[rc] = count_weights.get(rc, 0.0) + weight

            sum_w = sum(count_weights.values())
            if sum_w > 0:
                for k, w in count_weights.items():
                    red_count_pmf[k] = w / sum_w

        # 3. Gather Eligible Total Value Candidates (Fix C: redTotalValueEligible gate)
        val_samples: List[float] = []
        val_weights: List[float] = []
        for cand, weight in eligible_count_candidates:
            if cand.red_total_value_eligible and cand.observed_red_total_value is not None:
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

        # 4. Conditional Distribution P(totalRedValue | R = k)
        conditional_dists: Dict[int, Dict[str, Any]] = {}
        for k in sorted(red_count_pmf.keys()):
            k_samples = [
                cand.observed_red_total_value for cand, _ in eligible_count_candidates
                if cand.observed_red_count == k and cand.red_total_value_eligible and cand.observed_red_total_value is not None
            ]
            k_weights = [
                weight for cand, weight in eligible_count_candidates
                if cand.observed_red_count == k and cand.red_total_value_eligible and cand.observed_red_total_value is not None
            ]
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

        report = RedInferenceReport(
            schema_version=SCHEMA_VERSION,
            experimental=True,
            production_eligible=False,
            eligible_match_count=eligible_match_count,
            eligible_observation_count=len(val_samples),
            effective_sample_weight=total_effective_weight,
            sampling_assumption="unknown",
            conditioning_mode="observational_only",
            similarity_profile=dict(SIMILARITY_PROFILE),
            red_count_pmf=red_count_pmf,
            red_total_quantiles=quantiles,
            red_total_mean=mean_val,
            red_total_median=median_val,
            conditional_distributions=conditional_dists,
            history_evidence_ids=[cand.record_id for cand, _ in eligible_count_candidates],
            history_generation=self._history_generation,
            warnings=warnings,
            insufficient_data=insufficient_data,
        )

        # Store in eval cache
        self._eval_cache[cache_key] = report
        return self._attach_deltas(report, production_metrics, shadow_profile)

    def _attach_deltas(
        self,
        base_report: RedInferenceReport,
        production_metrics: Optional[Mapping[str, Any]],
        shadow_profile: Optional[Mapping[str, Any]],
    ) -> RedInferenceReport:
        delta_vs_prod: Dict[str, Any] = {}
        if production_metrics:
            prod_med = production_metrics.get("medianEstimate")
            if prod_med is not None and base_report.red_total_median is not None:
                delta_vs_prod["medianDelta"] = round(base_report.red_total_median - float(prod_med), 2)
            prod_mean = production_metrics.get("meanEstimate")
            if prod_mean is not None and base_report.red_total_mean is not None:
                delta_vs_prod["meanDelta"] = round(base_report.red_total_mean - float(prod_mean), 2)

        delta_vs_shadow: Dict[str, Any] = {}
        if shadow_profile:
            shadow_p50 = shadow_profile.get("p50")
            if shadow_p50 is not None and base_report.red_total_median is not None:
                delta_vs_shadow["p50Delta"] = round(base_report.red_total_median - float(shadow_p50), 2)
            shadow_p20 = shadow_profile.get("p20")
            if shadow_p20 is not None and base_report.red_total_quantiles.p20 is not None:
                delta_vs_shadow["p20Delta"] = round(base_report.red_total_quantiles.p20 - float(shadow_p20), 2)

        rep = copy.copy(base_report)
        rep.delta_vs_production = delta_vs_prod
        rep.delta_vs_historical_shadow = delta_vs_shadow
        return rep


_GLOBAL_RED_LAB: Optional[ExperimentalRedInferenceLab] = None


def get_authoritative_red_inference_lab() -> ExperimentalRedInferenceLab:
    """Singleton getter for the runtime Red Inference Lab."""
    global _GLOBAL_RED_LAB
    if _GLOBAL_RED_LAB is None:
        _GLOBAL_RED_LAB = ExperimentalRedInferenceLab()
        _GLOBAL_RED_LAB.sync_with_live_history()
    return _GLOBAL_RED_LAB


def safe_evaluate_experimental_red(
    session_ctx: Mapping[str, Any],
    production_metrics: Optional[Mapping[str, Any]] = None,
    shadow_profile: Optional[Mapping[str, Any]] = None,
    lab: Optional[ExperimentalRedInferenceLab] = None,
) -> Dict[str, Any]:
    """Fail-isolated runtime entrypoint: guarantees zero crash on production solve or HUD (Fix D)."""
    try:
        active_lab = lab if lab is not None else get_authoritative_red_inference_lab()
        active_lab.sync_with_live_history()
        report = active_lab.evaluate_inference(
            session_ctx=session_ctx,
            production_metrics=production_metrics,
            shadow_profile=shadow_profile,
        )
        return report.to_payload()
    except Exception as exc:
        _LOG.warning("Experimental red inference isolated failure: %s", exc)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "experimental": True,
            "productionEligible": False,
            "status": "unavailable",
            "eligibleMatchCount": 0,
            "eligibleObservationCount": 0,
            "effectiveSampleWeight": 0.0,
            "samplingAssumption": "unknown",
            "conditioningMode": "observational_only",
            "similarityProfile": dict(SIMILARITY_PROFILE),
            "redCountPmf": {},
            "redTotalQuantiles": RedQuantiles().to_dict(),
            "redTotalMean": None,
            "redTotalMedian": None,
            "conditionalDistributions": {},
            "historyEvidenceIds": [],
            "historyGeneration": 0,
            "warnings": [f"Experimental red inference failed safely: {exc}"],
            "insufficientData": True,
            "deltaVsProduction": {},
            "deltaVsHistoricalShadow": {},
            "disclaimer": "实验结果 · 不参与正式出价",
        }
