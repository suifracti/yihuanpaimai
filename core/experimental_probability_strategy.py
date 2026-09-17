# -*- coding: utf-8 -*-
"""Experimental Probability and Strategy Lab (PR-C).

A strictly experimental, shadow-only module integrating reference probability and
strategy hypotheses from external research (e.g. Dafu Calculator v2-v2.3, legacy tools).

Strict Invariants:
1. experimental = True, productionEligible = False, defaultEnabled = False.
2. Zero mutation of production solvers, six-quality joint constraints, bidding lines, or Historical Shadow.
3. Zero direct copying of competitor source code or proprietary implementations.
4. All external hypotheses/constants have explicit provenance:
   - origin, sourceProject, sourceVersion, evidenceLevel, validatedByOurData = False.
5. In baseline state (all external profiles disabled), production output is byte-for-byte identical.
6. Baseline adapter consumes production_metrics / shadow_profile references ONLY; does NOT fabricate fake distributions.
7. Discrete convolution engine enforces probability normalization (tolerance 1e-5) and quantile monotonicity.
8. State-space budget limits prevent memory/CPU explosion; supportSize <= max_states strictly guaranteed.
9. Structural fit (structural_fit_v1) performs geometry checks only; never uses q as item count, never defaults totalGrid.
10. External Dafu CELL_FIT marks status unavailable when external N semantics are unconfirmed.
11. Runtime calls are fail-isolated: experimental exceptions never crash production solve or HUD.
12. Cross-match reset returns active profiles strictly to baseline.
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

_LOG = logging.getLogger(__name__)

# Single authoritative constant for state-space budget limit
DEFAULT_MAX_CONVOLUTION_STATES = 2000

# Strict PMF normalization tolerances
INPUT_NORMALIZATION_TOLERANCE = 1e-5
FLOAT_RENORM_TOLERANCE = 1e-12

# Canonical Dafu external round divisors (research confirmed)
DAFU_CANONICAL_ROUND_DIVISORS = {
    "R1": 2.0,
    "R2": 1.6,
    "R3": 1.3,
    "R4": 1.1,
}

# Whitelist of legal experimental profile IDs
ALLOWED_EXPERIMENTAL_PROFILES = {
    "baseline",
    "dafu_round_heuristic_v1",
    "external_color_prior_dafu_v1",
    "structural_fit_v1",
    "dafu_cell_fit_reference_v1",
    "convolution_v1",
    "special_rule_reference_v1",
}


@dataclass(frozen=True)
class ProbabilityQuantiles:
    """Strictly monotonic quantiles across standard percentiles."""
    p10: Optional[float] = None
    p20: Optional[float] = None
    p25: Optional[float] = None
    p50: Optional[float] = None
    p75: Optional[float] = None
    p80: Optional[float] = None
    p90: Optional[float] = None
    p95: Optional[float] = None

    def to_dict(self) -> Dict[str, Optional[float]]:
        return asdict(self)


class DiscreteDistribution:
    """Discrete probability mass function (PMF) with validated normalization and monotonic quantiles."""

    def __init__(
        self,
        pmf: Mapping[float, float],
        tolerance: float = INPUT_NORMALIZATION_TOLERANCE,
    ):
        clean_pmf: Dict[float, float] = {}
        prob_sum = 0.0
        for val, prob in pmf.items():
            if not isinstance(val, (int, float)) or not isinstance(prob, (int, float)):
                continue
            if isinstance(val, bool) or isinstance(prob, bool):
                continue
            f_val = float(val)
            f_prob = float(prob)
            if not math.isfinite(f_val) or not math.isfinite(f_prob):
                continue
            if f_prob < 0.0:
                raise ValueError(f"Negative probability observed: {f_prob}")
            if f_prob > 0.0:
                clean_pmf[f_val] = clean_pmf.get(f_val, 0.0) + f_prob
                prob_sum += f_prob

        self._pmf = clean_pmf
        self._norm_error = abs(1.0 - prob_sum) if clean_pmf else 1.0
        self._pre_normalization_error = self._norm_error
        self._renormalized = False

        # Strict contract: error > tolerance => invalid. Silent 5% repairs are rejected.
        if clean_pmf and self._norm_error <= tolerance:
            self._is_valid = True
            if self._norm_error > 0.0:
                # Re-normalize floating micro-error
                self._pmf = {k: v / prob_sum for k, v in clean_pmf.items()}
                self._norm_error = abs(1.0 - sum(self._pmf.values()))
                self._renormalized = True
        else:
            self._is_valid = False

        self._mean: Optional[float] = None
        self._quantiles = ProbabilityQuantiles()
        if self._is_valid and self._pmf:
            self._compute_statistics()

    @property
    def pmf(self) -> Dict[float, float]:
        return dict(self._pmf)

    @property
    def is_valid(self) -> bool:
        return self._is_valid

    @property
    def normalization_error(self) -> float:
        return self._norm_error

    @property
    def pre_normalization_error(self) -> float:
        return self._pre_normalization_error

    @property
    def renormalized(self) -> bool:
        return self._renormalized

    @property
    def support_size(self) -> int:
        return len(self._pmf)

    @property
    def mean(self) -> Optional[float]:
        return self._mean

    @property
    def median(self) -> Optional[float]:
        return self._quantiles.p50

    @property
    def quantiles(self) -> ProbabilityQuantiles:
        return self._quantiles

    def _compute_statistics(self) -> None:
        sorted_pairs = sorted(self._pmf.items(), key=lambda p: p[0])
        sorted_vals = [p[0] for p in sorted_pairs]
        sorted_probs = [p[1] for p in sorted_pairs]

        self._mean = sum(v * p for v, p in sorted_pairs)

        total_p = sum(sorted_probs)
        if total_p <= 0:
            return

        cum = 0.0
        cum_weights: List[float] = []
        for p in sorted_probs:
            cum += p
            cum_weights.append(cum / total_p)

        def _interp(q: float) -> float:
            for i, cw in enumerate(cum_weights):
                if cw >= q:
                    return float(sorted_vals[i])
            return float(sorted_vals[-1])

        p10 = _interp(0.10)
        p20 = max(p10, _interp(0.20))
        p25 = max(p20, _interp(0.25))
        p50 = max(p25, _interp(0.50))
        p75 = max(p50, _interp(0.75))
        p80 = max(p75, _interp(0.80))
        p90 = max(p80, _interp(0.90))
        p95 = max(p90, _interp(0.95))

        self._quantiles = ProbabilityQuantiles(
            p10=p10, p20=p20, p25=p25, p50=p50, p75=p75, p80=p80, p90=p90, p95=p95
        )

    def to_payload(self) -> Dict[str, Any]:
        return {
            "isValid": self._is_valid,
            "supportSize": self.support_size,
            "normalizationError": round(self._norm_error, 8),
            "preNormalizationError": round(self._pre_normalization_error, 8),
            "renormalized": self._renormalized,
            "mean": round(self._mean, 2) if self._mean is not None else None,
            "median": round(self.median, 2) if self.median is not None else None,
            "quantiles": self._quantiles.to_dict(),
            "pmfSample": {f"{k:.2f}": round(v, 6) for k, v in sorted(self._pmf.items())[:20]},
        }


def convolve_discrete_distributions(
    distributions: Sequence[DiscreteDistribution],
    max_states: int = DEFAULT_MAX_CONVOLUTION_STATES,
) -> Tuple[Optional[DiscreteDistribution], Dict[str, Any]]:
    """Compute discrete convolution D_total = D1 * D2 * ... * Dn with strict budget safety.

    Guarantees:
    - Empty or non-valid input distributions return None with reason NO_VALID_COMPONENTS.
    - Resulting support size strictly satisfies: supportSize <= max_states.
    - Returns metadata tracking approximation method and state compression.
    """
    valid_dists = [
        d for d in distributions
        if isinstance(d, DiscreteDistribution) and d.is_valid and d.support_size > 0
    ]
    if not valid_dists:
        return None, {
            "status": "unavailable",
            "reason": "NO_VALID_COMPONENTS",
            "budgetExceeded": False,
            "approximationApplied": False,
            "originalStateCount": 0,
            "finalStateCount": 0,
            "normalizationError": 0.0,
            "approximationMethod": "none",
        }

    current_pmf: Dict[float, float] = {0.0: 1.0}
    budget_exceeded = False
    original_state_count = 0

    for d in valid_dists:
        next_pmf: Dict[float, float] = {}
        for x1, p1 in current_pmf.items():
            for x2, p2 in d.pmf.items():
                tot_x = round(x1 + x2, 2)
                next_pmf[tot_x] = next_pmf.get(tot_x, 0.0) + (p1 * p2)

        original_state_count = max(original_state_count, len(next_pmf))

        # Strict budget guard: supportSize must be <= max_states
        if len(next_pmf) > max_states:
            budget_exceeded = True
            sorted_items = sorted(next_pmf.items(), key=lambda p: p[0])
            total_items = len(sorted_items)
            # Partition sorted items into at most max_states contiguous chunks
            chunk_size = math.ceil(total_items / max_states)
            compressed_pmf: Dict[float, float] = {}
            for i in range(0, total_items, chunk_size):
                chunk = sorted_items[i : i + chunk_size]
                chunk_prob = sum(p for _, p in chunk)
                if chunk_prob > 0:
                    weighted_val = round(sum(v * p for v, p in chunk) / chunk_prob, 2)
                    compressed_pmf[weighted_val] = compressed_pmf.get(weighted_val, 0.0) + chunk_prob

            # Ensure strict bound
            if len(compressed_pmf) > max_states:
                sorted_comp = sorted(compressed_pmf.items(), key=lambda p: p[0])
                trimmed = sorted_comp[:max_states]
                trim_sum = sum(p for _, p in trimmed)
                compressed_pmf = {k: v / trim_sum for k, v in trimmed}

            current_pmf = compressed_pmf
        else:
            current_pmf = next_pmf

    dist = DiscreteDistribution(current_pmf, tolerance=INPUT_NORMALIZATION_TOLERANCE)
    meta = {
        "status": "evaluated" if dist.is_valid else "invalid",
        "reason": None if dist.is_valid else "NORMALIZATION_FAILURE",
        "budgetExceeded": budget_exceeded,
        "approximationApplied": budget_exceeded,
        "originalStateCount": original_state_count,
        "finalStateCount": dist.support_size,
        "normalizationError": dist.normalization_error,
        "approximationMethod": "adaptive_quantile_binning" if budget_exceeded else "exact_discrete_convolution",
    }
    return (dist if dist.is_valid else None), meta


@dataclass(frozen=True)
class StructuralFitDiagnostic:
    """Internal structural geometric diagnostic (structural_fit_v1).

    Reads only authoritative canonical fields:
    - totalGrid
    - totalItems
    - quality counts and grids
    - item footprint areas
    Never uses q as item count. Never defaults totalGrid to 54.
    """
    status: str = "evaluated"
    feasible: bool = True
    fill_ratio: Optional[float] = None
    mean_area: Optional[float] = None
    variance_area: Optional[float] = None
    quality_score: Optional[float] = None
    conflicts: Tuple[str, ...] = ()
    evidence_used: Tuple[str, ...] = ()
    details: Dict[str, Any] = field(default_factory=dict)
    reason: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "feasible": self.feasible,
            "fillRatio": round(self.fill_ratio, 4) if self.fill_ratio is not None else None,
            "meanArea": round(self.mean_area, 4) if self.mean_area is not None else None,
            "varianceArea": round(self.variance_area, 4) if self.variance_area is not None else None,
            "qualityScore": round(self.quality_score, 4) if self.quality_score is not None else None,
            "conflicts": list(self.conflicts),
            "evidenceUsed": list(self.evidence_used),
            "details": self.details,
            "reason": self.reason,
        }


def parse_footprint_cells(footprint: Any) -> Optional[int]:
    """Parse footprint into cell area using standard canonical format (e.g. '1x2', (2, 3), 4)."""
    if isinstance(footprint, (int, float)) and footprint > 0:
        return int(footprint)
    if isinstance(footprint, (list, tuple)) and len(footprint) == 2:
        try:
            return int(footprint[0]) * int(footprint[1])
        except Exception:
            return None
    if isinstance(footprint, str):
        parts = footprint.lower().replace("*", "x").split("x")
        if len(parts) == 2:
            try:
                w, h = int(parts[0].strip()), int(parts[1].strip())
                return w * h
            except Exception:
                return None
    return None


def compute_structural_fit(session_ctx: Mapping[str, Any]) -> StructuralFitDiagnostic:
    """Compute internal structural fit diagnostic against canonical inventory intel."""
    public_intel = session_ctx.get("publicIntel") or {}
    total_grid = session_ctx.get("totalGrid") or public_intel.get("totalGrid")

    # If totalGrid is missing, diagnostic is unavailable (strict no default 54!)
    if total_grid is None or not isinstance(total_grid, (int, float)) or total_grid <= 0:
        return StructuralFitDiagnostic(
            status="unavailable",
            feasible=True,
            reason="MISSING_CANONICAL_TOTAL_GRID",
            conflicts=("TOTAL_GRID_UNAVAILABLE",),
            evidence_used=(),
            details={"sessionCtxHasTotalGrid": "totalGrid" in session_ctx},
        )

    total_grid = int(total_grid)
    conflicts: List[str] = []
    evidence_used: List[str] = ["totalGrid"]

    # Canonical totalItems (NOT q!)
    total_items = session_ctx.get("totalItems") or public_intel.get("totalItems")
    if isinstance(total_items, (int, float)) and total_items > 0:
        evidence_used.append("totalItems")
        if total_items > total_grid:
            conflicts.append("TOTAL_ITEMS_EXCEEDS_GRID_CAPACITY")

    # Known items footprint parsing
    known_items = session_ctx.get("knownItems") or []
    item_areas: List[int] = []
    if isinstance(known_items, list) and known_items:
        evidence_used.append("knownItems")
        for item in known_items:
            area = None
            if isinstance(item, dict):
                fp = item.get("cells") or item.get("footprint") or item.get("gridFootprint") or item.get("size")
                area = parse_footprint_cells(fp)
            else:
                area = parse_footprint_cells(item)
            if area is not None and area > 0:
                item_areas.append(area)

    known_cells_total = sum(item_areas)
    if known_cells_total > total_grid:
        conflicts.append("KNOWN_ITEM_FOOTPRINTS_EXCEED_TOTAL_GRID")

    # Quality counts vs quality grids
    quality_grids = session_ctx.get("qualityGrids") or {}
    quality_counts = session_ctx.get("qualityCounts") or {}
    if isinstance(quality_grids, dict) and isinstance(quality_counts, dict):
        for q_name in ("white", "green", "blue", "purple", "gold", "red"):
            g_cells = quality_grids.get(q_name)
            cnt = quality_counts.get(q_name)
            if isinstance(g_cells, (int, float)) and isinstance(cnt, (int, float)):
                evidence_used.append(f"quality_{q_name}")
                if cnt > 0 and g_cells < cnt:
                    conflicts.append(f"{q_name.upper()}_GRID_LESS_THAN_ITEM_COUNT")

    fill_ratio = min(1.0, known_cells_total / max(1, total_grid))
    mean_area = (sum(item_areas) / len(item_areas)) if item_areas else 0.0
    if len(item_areas) > 1:
        variance_area = sum((a - mean_area) ** 2 for a in item_areas) / len(item_areas)
    else:
        variance_area = 0.0

    feasible = (len(conflicts) == 0)
    # Quality score heuristic in [0.0, 1.0]
    if not feasible:
        quality_score = 0.0
    else:
        quality_score = max(0.01, round(1.0 - (0.4 * fill_ratio) - min(0.3, variance_area * 0.02), 4))

    return StructuralFitDiagnostic(
        status="evaluated",
        feasible=feasible,
        fill_ratio=fill_ratio,
        mean_area=mean_area,
        variance_area=variance_area,
        quality_score=quality_score,
        conflicts=tuple(conflicts),
        evidence_used=tuple(evidence_used),
        details={
            "totalGrid": total_grid,
            "totalItems": total_items,
            "knownCellsTotal": known_cells_total,
            "itemAreasCount": len(item_areas),
        },
    )


def compute_dafu_cell_fit_reference(session_ctx: Mapping[str, Any]) -> Dict[str, Any]:
    """External Dafu CELL_FIT sanity-check reference (slope=3.3467, intercept=60.0425).

    Contract:
    - If external N semantics are unconfirmed, mark unavailable.
    - Strictly non-intrusive, never used as boundary4 oracle.
    """
    return {
        "status": "unavailable",
        "reason": "EXTERNAL_N_SEMANTICS_UNCONFIRMED",
        "profileId": "dafu_cell_fit_reference_v1",
        "origin": "external_reference",
        "sourceProject": "dafu_calculator",
        "sourceVersion": "v2.0-v2.3",
        "evidenceLevel": "unverified_external_hypothesis",
        "validatedByOurData": False,
        "productionEligible": False,
        "slope": 3.3467,
        "intercept": 60.0425,
        "formula": "CELL_FIT = 3.3467 * N + 60.0425 (N unconfirmed)",
    }


@dataclass(frozen=True)
class ExperimentalStrategyProfile:
    """Unified strategy and probability profile schema with full external provenance."""
    profile_id: str
    name: str
    description: str
    source: str
    source_project: Optional[str] = None
    source_version: Optional[str] = None
    evidence_level: str = "unverified_external_hypothesis"
    parameters: Dict[str, Any] = field(default_factory=dict)
    applicable_conditions: Dict[str, Any] = field(default_factory=dict)
    experimental: bool = True
    production_eligible: bool = False
    validated_by_our_data: bool = False
    enabled_by_default: bool = False

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


class ExperimentalStrategyRegistry:
    """Registry managing experimental profiles with whitelist enforcement and generation tracking."""

    def __init__(self):
        self._profiles: Dict[str, ExperimentalStrategyProfile] = {}
        self._active_profile_ids: Set[str] = set()
        self._profile_generation: int = 0
        self._register_default_profiles()

    def _register_default_profiles(self) -> None:
        # 1. Baseline Canonical Adapter (Reference only; produces NO fake distributions)
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="baseline",
                name="Production Comparison Reference Adapter",
                description="Adapts production and shadow solver outputs as side-by-side reference; produces NO experimental distribution.",
                source="production_reference",
                source_project="yihuanpaimai_core",
                source_version="v2.0",
                evidence_level="authoritative_internal",
                parameters={"producesExperimentalDistribution": False},
                experimental=True,
                production_eligible=False,
                validated_by_our_data=True,
                enabled_by_default=True,
            )
        )

        # 2. Dafu Round Heuristic Profile (R1-R4 canonical divisors)
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="dafu_round_heuristic_v1",
                name="Dafu Round Heuristic v1 (R1-R4 Divisors)",
                description="External round-divisor progression derived from Dafu calculator (R1: 2.0, R2: 1.6, R3: 1.3, R4: 1.1).",
                source="external_reference",
                source_project="dafu_calculator",
                source_version="v2.0-v2.3",
                evidence_level="unverified_external_heuristic",
                parameters={
                    "round_divisors": copy.deepcopy(DAFU_CANONICAL_ROUND_DIVISORS),
                },
                experimental=True,
                production_eligible=False,
                validated_by_our_data=False,
                enabled_by_default=False,
            )
        )

        # 3. Dafu Color Prior Profile (Correct order: Purple:Gold:Red = 2.2:1.85:1)
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="external_color_prior_dafu_v1",
                name="Dafu Color Prior Ratios v1",
                description="External fixed quality ratio hypotheses (Purple:Gold:Red = 2.2:1.85:1) from Dafu calculator.",
                source="external_reference",
                source_project="dafu_calculator",
                source_version="v2.0-v2.3",
                evidence_level="unverified_external_prior",
                parameters={
                    "purple_weight": 2.2,
                    "gold_weight": 1.85,
                    "red_weight": 1.0,
                    "sampling_assumption": "explicit_external_ratio",
                },
                experimental=True,
                production_eligible=False,
                validated_by_our_data=False,
                enabled_by_default=False,
            )
        )

        # 4. Internal Structural Fit Profile (structural_fit_v1)
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="structural_fit_v1",
                name="Internal Structural Fit Diagnostic v1",
                description="Internal spatial inventory packing feasibility diagnostic. Never uses q as item count, never defaults totalGrid.",
                source="internal_geometric_diagnostic",
                source_project="yihuanpaimai_core",
                source_version="v1.0",
                evidence_level="internal_diagnostic",
                parameters={},
                experimental=True,
                production_eligible=False,
                validated_by_our_data=False,
                enabled_by_default=False,
            )
        )

        # 5. External Dafu CELL_FIT Reference Profile (dafu_cell_fit_reference_v1)
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="dafu_cell_fit_reference_v1",
                name="Dafu CELL_FIT Reference v1",
                description="External CELL_FIT linear sanity check (slope=3.3467, intercept=60.0425). N semantics unconfirmed.",
                source="external_reference",
                source_project="dafu_calculator",
                source_version="v2.0-v2.3",
                evidence_level="unverified_external_hypothesis",
                parameters={
                    "slope": 3.3467,
                    "intercept": 60.0425,
                },
                experimental=True,
                production_eligible=False,
                validated_by_our_data=False,
                enabled_by_default=False,
            )
        )

        # 6. Convolution / Generating Function Distribution Lab Profile
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="convolution_v1",
                name="Discrete Convolution Solver v1",
                description="Strict PMF polynomial convolution engine with state budget protection.",
                source="canonical_generating_function",
                source_project="yihuanpaimai_lab",
                source_version="v1.0",
                evidence_level="mathematical_convolution",
                parameters={
                    "max_states": DEFAULT_MAX_CONVOLUTION_STATES,
                    "tolerance": INPUT_NORMALIZATION_TOLERANCE,
                },
                experimental=True,
                production_eligible=False,
                validated_by_our_data=False,
                enabled_by_default=False,
            )
        )

        # 7. Special Rule Reference Profile (special_rule_reference_v1)
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="special_rule_reference_v1",
                name="Special Rule Reference v1",
                description="Recorded external special-rule hypotheses (e.g. shining_heart, no_pig, etc.). No verified execution effects.",
                source="external_reference",
                source_project="dafu_calculator",
                source_version="v2.0-v2.3",
                evidence_level="unverified_external_hypothesis",
                parameters={
                    "rules": ["shining_heart", "no_heart", "no_pig", "no_large_items"],
                    "effect_enabled": False,
                },
                experimental=True,
                production_eligible=False,
                validated_by_our_data=False,
                enabled_by_default=False,
            )
        )

        # Reset active profile set strictly to baseline
        self.reset_for_new_match()

    def register_profile(self, profile: ExperimentalStrategyProfile) -> None:
        self._profiles[profile.profile_id] = profile

    def get_profile(self, profile_id: str) -> Optional[ExperimentalStrategyProfile]:
        return self._profiles.get(profile_id)

    def list_profiles(self) -> List[ExperimentalStrategyProfile]:
        return list(self._profiles.values())

    def enable_profile(self, profile_id: str) -> bool:
        """Enable profile if present in whitelist. Increments generation counter."""
        if profile_id in ALLOWED_EXPERIMENTAL_PROFILES and profile_id in self._profiles:
            if profile_id not in self._active_profile_ids:
                self._active_profile_ids.add(profile_id)
                self._profile_generation += 1
            return True
        return False

    def disable_profile(self, profile_id: str) -> bool:
        """Disable profile if not baseline. Increments generation counter."""
        if profile_id == "baseline":
            return False  # baseline cannot be disabled
        if profile_id in self._active_profile_ids:
            self._active_profile_ids.remove(profile_id)
            self._profile_generation += 1
            return True
        return False

    def is_profile_enabled(self, profile_id: str) -> bool:
        return profile_id in self._active_profile_ids

    def get_active_profile_ids(self) -> List[str]:
        return sorted(list(self._active_profile_ids))

    @property
    def profile_generation(self) -> int:
        return self._profile_generation

    def reset_for_new_match(self) -> None:
        """Reset active profile set strictly to baseline for each new match."""
        if self._active_profile_ids != {"baseline"}:
            self._profile_generation += 1
        self._active_profile_ids = {"baseline"}


# Global registry instance
_GLOBAL_REGISTRY: Optional[ExperimentalStrategyRegistry] = None


def get_global_strategy_registry() -> ExperimentalStrategyRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = ExperimentalStrategyRegistry()
    return _GLOBAL_REGISTRY


# Global calculation cache: (profileGeneration, contextFingerprint, pr_b_historyGeneration) -> payload
_CALC_CACHE: Dict[Tuple[int, str, int], Dict[str, Any]] = {}


def _compute_context_fingerprint(session_ctx: Mapping[str, Any]) -> str:
    """Deterministic hash of input session context."""
    h = hashlib.sha256()
    sorted_items = sorted(
        (str(k), str(v))
        for k, v in session_ctx.items()
        if k not in ("timestamp", "now", "nowUtc")
    )
    for k, v in sorted_items:
        h.update(k.encode("utf-8"))
        h.update(v.encode("utf-8"))
    return h.hexdigest()[:16]


@dataclass
class ExperimentalProbabilityStrategyReport:
    """Contract-compliant result payload with exact schema parity."""
    schema_version: int = 1
    experimental: bool = True
    production_eligible: bool = False
    status: str = "evaluated"
    active_profiles: List[str] = field(default_factory=lambda: ["baseline"])
    profile_generation: int = 0
    sampling_assumption: str = "unknown"
    conditioning_mode: str = "observational_only"
    production_reference: Optional[Dict[str, Any]] = None
    historical_shadow_reference: Optional[Dict[str, Any]] = None
    experimental_distribution: Optional[Dict[str, Any]] = None
    p20: Optional[float] = None
    p50: Optional[float] = None
    p80: Optional[float] = None
    mean: Optional[float] = None
    experimental_reserve_price: Optional[float] = None
    experimental_conservative_price: Optional[float] = None
    structural_fit: Optional[Dict[str, Any]] = None
    dafu_cell_fit_reference: Optional[Dict[str, Any]] = None
    external_hypotheses: Optional[Dict[str, Any]] = None
    convolution_metrics: Optional[Dict[str, Any]] = None
    delta_vs_production: Optional[Dict[str, Any]] = None
    delta_vs_pr_b_red: Optional[Dict[str, Any]] = None
    sample_n: int = 0
    evaluation_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    warnings: List[str] = field(default_factory=list)
    disclaimers: List[str] = field(default_factory=lambda: ["实验结果 · 不参与正式出价"])

    def to_payload(self) -> Dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "experimental": self.experimental,
            "productionEligible": self.production_eligible,
            "status": self.status,
            "activeProfiles": list(self.active_profiles),
            "profileGeneration": self.profile_generation,
            "samplingAssumption": self.sampling_assumption,
            "conditioningMode": self.conditioning_mode,
            "productionReference": self.production_reference,
            "historicalShadowReference": self.historical_shadow_reference,
            "experimentalDistribution": self.experimental_distribution,
            "p20": round(self.p20, 2) if self.p20 is not None else None,
            "p50": round(self.p50, 2) if self.p50 is not None else None,
            "p80": round(self.p80, 2) if self.p80 is not None else None,
            "mean": round(self.mean, 2) if self.mean is not None else None,
            "experimentalReservePrice": round(self.experimental_reserve_price, 2) if self.experimental_reserve_price is not None else None,
            "experimentalConservativePrice": round(self.experimental_conservative_price, 2) if self.experimental_conservative_price is not None else None,
            "structuralFit": self.structural_fit,
            "dafuCellFitReference": self.dafu_cell_fit_reference,
            "externalHypotheses": self.external_hypotheses,
            "convolutionMetrics": self.convolution_metrics,
            "deltaVsProduction": self.delta_vs_production,
            "deltaVsPrBRed": self.delta_vs_pr_b_red,
            "sampleN": self.sample_n,
            "evaluationTimestamp": self.evaluation_timestamp,
            "warnings": list(self.warnings),
            "disclaimers": list(self.disclaimers),
        }


def evaluate_experimental_probability_strategy(
    session_ctx: Mapping[str, Any],
    production_metrics: Optional[Mapping[str, Any]] = None,
    shadow_profile: Optional[Mapping[str, Any]] = None,
    experimental_red: Optional[Mapping[str, Any]] = None,
    registry: Optional[ExperimentalStrategyRegistry] = None,
) -> ExperimentalProbabilityStrategyReport:
    """Execute experimental probability and strategy inference across active profiles."""
    reg = registry or get_global_strategy_registry()
    active_ids = reg.get_active_profile_ids()
    generation = reg.profile_generation

    warnings: List[str] = []
    disclaimers: List[str] = ["实验结果 · 不参与正式出价"]

    has_external_active = any(pid != "baseline" for pid in active_ids)
    if has_external_active:
        disclaimers.append("外部经验参数 · 未经我方真实历史验证")

    # 1. Baseline Reference Adapter: consumes passed-in references only!
    # Does NOT fabricate fake distributions (q*goldAvg PMF is strictly deleted).
    prod_ref = None
    if production_metrics and isinstance(production_metrics, dict):
        prod_ref = {
            "valP50": production_metrics.get("valP50") or production_metrics.get("medianEstimate"),
            "valRange": production_metrics.get("valRange"),
            "targetProfitLine": production_metrics.get("targetProfitLine"),
            "actionDirective": production_metrics.get("actionDirective"),
        }

    shadow_ref = None
    if shadow_profile and isinstance(shadow_profile, dict):
        shadow_ref = {
            "p20": shadow_profile.get("p20"),
            "p50": shadow_profile.get("p50"),
            "p80": shadow_profile.get("p80"),
            "conservativeEstimate": shadow_profile.get("conservativeEstimate"),
        }

    # If ONLY baseline is enabled: early return O(1) side-by-side reference payload!
    if not has_external_active:
        return ExperimentalProbabilityStrategyReport(
            schema_version=1,
            experimental=True,
            production_eligible=False,
            status="evaluated",
            active_profiles=active_ids,
            profile_generation=generation,
            sampling_assumption="unknown",
            conditioning_mode="observational_only",
            production_reference=prod_ref,
            historical_shadow_reference=shadow_ref,
            experimental_distribution=None,
            p20=None,
            p50=None,
            p80=None,
            mean=None,
            experimental_reserve_price=None,
            experimental_conservative_price=None,
            structural_fit=None,
            dafu_cell_fit_reference=None,
            external_hypotheses=None,
            convolution_metrics=None,
            delta_vs_production=None,
            delta_vs_pr_b_red=None,
            sample_n=session_ctx.get("sampleN", 0),
            warnings=warnings,
            disclaimers=disclaimers,
        )

    # 2. Discrete Convolution Component Building
    # Strict Rule: Quantiles cannot be fabricated into PMFs!
    # PR-B quantiles (p20/p50/p80) are NOT converted into {p20:0.2, p50:0.6, p80:0.2}.
    # Real independent PMFs can be provided via session_ctx["candidatePmfs"].
    components: List[DiscreteDistribution] = []
    candidate_pmfs = session_ctx.get("candidatePmfs")
    if isinstance(candidate_pmfs, list):
        for c_pmf in candidate_pmfs:
            if isinstance(c_pmf, dict):
                try:
                    d = DiscreteDistribution(c_pmf, tolerance=INPUT_NORMALIZATION_TOLERANCE)
                    if d.is_valid:
                        components.append(d)
                except Exception:
                    pass

    convolved_dist: Optional[DiscreteDistribution] = None
    conv_meta: Optional[Dict[str, Any]] = None

    if reg.is_profile_enabled("convolution_v1"):
        if components:
            convolved_dist, conv_meta = convolve_discrete_distributions(
                components, max_states=DEFAULT_MAX_CONVOLUTION_STATES
            )
            if conv_meta.get("budgetExceeded"):
                warnings.append("State-space budget exceeded: distribution downsampled to budget limit.")
        else:
            conv_meta = {
                "status": "unavailable",
                "reason": "NO_VALID_DISTRIBUTION_COMPONENTS",
                "budgetExceeded": False,
                "approximationApplied": False,
                "originalStateCount": 0,
                "finalStateCount": 0,
                "normalizationError": 0.0,
                "approximationMethod": "none",
            }
            warnings.append("Convolution unavailable: no valid discrete PMF components provided.")

    p20 = convolved_dist.quantiles.p20 if convolved_dist else None
    p50 = convolved_dist.quantiles.p50 if convolved_dist else None
    p80 = convolved_dist.quantiles.p80 if convolved_dist else None
    mean_val = convolved_dist.mean if convolved_dist else None

    # 3. Dafu Round Divisors Heuristic (R1-R4)
    # Canonical: R1 / 2.0, R2 / 1.6, R3 / 1.3, R4 / 1.1.
    # No invented constants (0.92, 0.88 deleted!).
    external_hypotheses: Dict[str, Any] = {}
    exp_reserve = None
    exp_conservative = None

    if reg.is_profile_enabled("dafu_round_heuristic_v1"):
        round_idx = session_ctx.get("round") or session_ctx.get("currentRound") or 1
        r_str = f"R{min(4, max(1, int(round_idx)))}"
        divisor = DAFU_CANONICAL_ROUND_DIVISORS.get(r_str, 1.0)
        multiplier = 1.0 / divisor

        # Base reference price for heuristic: use convolved p50 or production reference p50
        ref_p50 = p50 or (prod_ref.get("valP50") if prod_ref else None)
        calculated_bidding_price = (ref_p50 * multiplier) if ref_p50 is not None else None

        external_hypotheses["dafuRoundHeuristic"] = {
            "round": r_str,
            "canonicalDivisor": divisor,
            "calculatedMultiplier": round(multiplier, 4),
            "calculatedBiddingPrice": round(calculated_bidding_price, 2) if calculated_bidding_price is not None else None,
            "note": "Canonical Dafu divisors (R1:2.0, R2:1.6, R3:1.3, R4:1.1). Experimental only.",
        }

    # 4. Color Prior Profile (Purple:Gold:Red = 2.2:1.85:1)
    if reg.is_profile_enabled("external_color_prior_dafu_v1"):
        p_cp = reg.get_profile("external_color_prior_dafu_v1")
        external_hypotheses["colorPrior"] = {
            "profileId": "external_color_prior_dafu_v1",
            "sourceProject": p_cp.source_project if p_cp else "dafu_calculator",
            "evidenceLevel": p_cp.evidence_level if p_cp else "unverified_external_prior",
            "validatedByOurData": False,
            "samplingAssumption": "explicit_external_ratio",
            "weights": {
                "purple_weight": 2.2,
                "gold_weight": 1.85,
                "red_weight": 1.0,
            },
            "ratioString": "Purple : Gold : Red = 2.2 : 1.85 : 1.0",
        }

    # 5. Special Rule Profile
    if reg.is_profile_enabled("special_rule_reference_v1"):
        external_hypotheses["specialRuleReference"] = {
            "profileId": "special_rule_reference_v1",
            "sourceProject": "dafu_calculator",
            "evidenceLevel": "unverified_external_hypothesis",
            "validatedByOurData": False,
            "effectEnabled": False,
            "recordedRules": ["shining_heart", "no_heart", "no_pig", "no_large_items"],
            "status": "已记录外部规则假设 · 当前无已验证可执行 effect",
        }

    # 6. Structural Fit (internal structural_fit_v1)
    structural_fit_report = None
    if reg.is_profile_enabled("structural_fit_v1"):
        s_fit = compute_structural_fit(session_ctx)
        structural_fit_report = s_fit.to_payload()
        if s_fit.conflicts:
            warnings.extend([f"StructuralFit: {c}" for c in s_fit.conflicts])

    # 7. Dafu CELL_FIT Reference (external dafu_cell_fit_reference_v1)
    dafu_cell_fit_report = None
    if reg.is_profile_enabled("dafu_cell_fit_reference_v1"):
        dafu_cell_fit_report = compute_dafu_cell_fit_reference(session_ctx)

    # 8. Deltas vs Production and PR-B Red
    delta_prod = None
    if prod_ref and prod_ref.get("valP50") is not None and p50 is not None:
        delta_prod = {
            "medianDelta": round(p50 - float(prod_ref["valP50"]), 2),
        }

    delta_red = None
    if experimental_red and isinstance(experimental_red, dict) and p50 is not None:
        red_p50 = experimental_red.get("redTotalMedian")
        if isinstance(red_p50, (int, float)):
            delta_red = {
                "deltaVsRedMedian": round(p50 - float(red_p50), 2),
            }

    sample_n = session_ctx.get("sampleN", 0)

    return ExperimentalProbabilityStrategyReport(
        schema_version=1,
        experimental=True,
        production_eligible=False,
        status="evaluated",
        active_profiles=active_ids,
        profile_generation=generation,
        sampling_assumption="unknown",
        conditioning_mode="observational_only",
        production_reference=prod_ref,
        historical_shadow_reference=shadow_ref,
        experimental_distribution=convolved_dist.to_payload() if convolved_dist else None,
        p20=p20,
        p50=p50,
        p80=p80,
        mean=mean_val,
        experimental_reserve_price=exp_reserve,
        experimental_conservative_price=exp_conservative,
        structural_fit=structural_fit_report,
        dafu_cell_fit_reference=dafu_cell_fit_report,
        external_hypotheses=external_hypotheses if external_hypotheses else None,
        convolution_metrics=conv_meta,
        delta_vs_production=delta_prod,
        delta_vs_pr_b_red=delta_red,
        sample_n=sample_n,
        warnings=warnings,
        disclaimers=disclaimers,
    )


def safe_evaluate_experimental_probability_strategy(
    session_ctx: Mapping[str, Any],
    production_metrics: Optional[Mapping[str, Any]] = None,
    shadow_profile: Optional[Mapping[str, Any]] = None,
    experimental_red: Optional[Mapping[str, Any]] = None,
    registry: Optional[ExperimentalStrategyRegistry] = None,
) -> Dict[str, Any]:
    """Fail-isolated and cached wrapper around experimental probability strategy inference.

    Guarantees:
    - Never raises an unhandled exception.
    - Never mutates session_ctx, production_metrics, or shadow_profile.
    - Completely isolated from production solver execution paths.
    - Caches evaluations across (profileGeneration, contextFingerprint, pr_b_historyGeneration).
    - O(1) early return when only baseline is enabled.
    """
    global _CALC_CACHE
    reg = registry or get_global_strategy_registry()
    active_ids = reg.get_active_profile_ids()
    generation = reg.profile_generation

    # O(1) early return when all external profiles are disabled
    if active_ids == ["baseline"]:
        try:
            report = evaluate_experimental_probability_strategy(
                session_ctx=session_ctx,
                production_metrics=production_metrics,
                shadow_profile=shadow_profile,
                experimental_red=experimental_red,
                registry=reg,
            )
            return report.to_payload()
        except Exception as exc:
            _LOG.warning("Baseline adapter failure: %s", exc, exc_info=True)
            return _make_fallback_payload(generation, str(exc))

    # Check cache for complex calculations
    ctx_fp = _compute_context_fingerprint(session_ctx)
    pr_b_gen = int((experimental_red or {}).get("historyGeneration", 0))
    cache_key = (generation, ctx_fp, pr_b_gen)

    if cache_key in _CALC_CACHE:
        return copy.deepcopy(_CALC_CACHE[cache_key])

    try:
        report = evaluate_experimental_probability_strategy(
            session_ctx=session_ctx,
            production_metrics=production_metrics,
            shadow_profile=shadow_profile,
            experimental_red=experimental_red,
            registry=reg,
        )
        payload = report.to_payload()
        # Cap cache size to prevent memory leak
        if len(_CALC_CACHE) > 500:
            _CALC_CACHE.clear()
        _CALC_CACHE[cache_key] = payload
        return payload
    except Exception as exc:
        _LOG.warning("Experimental probability strategy isolated failure: %s", exc, exc_info=True)
        return _make_fallback_payload(generation, str(exc))


def _make_fallback_payload(generation: int, error_msg: str) -> Dict[str, Any]:
    """Uniform fallback error payload satisfying contract schema."""
    return {
        "schemaVersion": 1,
        "experimental": True,
        "productionEligible": False,
        "status": "error",
        "error": f"ExperimentalProbabilityStrategyFailure: {error_msg}",
        "activeProfiles": ["baseline"],
        "profileGeneration": generation,
        "samplingAssumption": "unknown",
        "conditioningMode": "observational_only",
        "productionReference": None,
        "historicalShadowReference": None,
        "experimentalDistribution": None,
        "p20": None,
        "p50": None,
        "p80": None,
        "mean": None,
        "experimentalReservePrice": None,
        "experimentalConservativePrice": None,
        "structuralFit": None,
        "dafuCellFitReference": None,
        "externalHypotheses": None,
        "convolutionMetrics": None,
        "deltaVsProduction": None,
        "deltaVsPrBRed": None,
        "sampleN": 0,
        "evaluationTimestamp": datetime.now(timezone.utc).isoformat(),
        "warnings": ["Experimental strategy calculation failed-closed; production unaffected."],
        "disclaimers": ["实验结果 · 不参与正式出价"],
    }
