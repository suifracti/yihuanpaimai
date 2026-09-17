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
6. Discrete convolution engine enforces probability normalization and quantile monotonicity.
7. State-space budget limits prevent memory/CPU explosion; budget exceedance triggers fail-safe.
8. CELL_FIT performs structural feasibility diagnostics only and NEVER deletes production states.
9. Runtime calls are fail-isolated: experimental exceptions never crash production solve or HUD.
10. Cross-match reset returns active profiles strictly to baseline.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

_LOG = logging.getLogger(__name__)

# State-space budget limit for discrete convolution
DEFAULT_MAX_CONVOLUTION_STATES = 2000


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
        tolerance: float = 1e-3,
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

        if clean_pmf and self._norm_error > tolerance:
            # Re-normalize if within reasonable bounds, otherwise flag invalid
            if prob_sum > 0.0 and self._norm_error <= 0.05:
                self._pmf = {k: v / prob_sum for k, v in clean_pmf.items()}
                self._norm_error = 0.0
                self._is_valid = True
            else:
                self._is_valid = False
        elif clean_pmf:
            self._is_valid = True
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
            "normalizationError": round(self._norm_error, 6),
            "mean": round(self._mean, 2) if self._mean is not None else None,
            "median": round(self.median, 2) if self.median is not None else None,
            "quantiles": self._quantiles.to_dict(),
            "pmfSample": {f"{k:.2f}": round(v, 4) for k, v in sorted(self._pmf.items())[:20]},
        }


def convolve_discrete_distributions(
    distributions: Sequence[DiscreteDistribution],
    max_states: int = DEFAULT_MAX_CONVOLUTION_STATES,
) -> Tuple[DiscreteDistribution, bool]:
    """Compute discrete convolution D_total = D1 * D2 * ... * Dn with budget safety.

    Returns:
        Tuple of (convolved_distribution, budget_exceeded).
    """
    valid_dists = [d for d in distributions if isinstance(d, DiscreteDistribution) and d.is_valid and d.support_size > 0]
    if not valid_dists:
        return DiscreteDistribution({0.0: 1.0}), False

    current_pmf: Dict[float, float] = {0.0: 1.0}
    budget_exceeded = False

    for d in valid_dists:
        next_pmf: Dict[float, float] = {}
        for x1, p1 in current_pmf.items():
            for x2, p2 in d.pmf.items():
                tot_x = round(x1 + x2, 2)
                next_pmf[tot_x] = next_pmf.get(tot_x, 0.0) + (p1 * p2)

        # Budget check: if states exceed max_states, compress bins
        if len(next_pmf) > max_states:
            budget_exceeded = True
            sorted_items = sorted(next_pmf.items(), key=lambda p: p[0])
            min_val, max_val = sorted_items[0][0], sorted_items[-1][0]
            bin_size = max(1.0, (max_val - min_val) / max_states)
            binned_pmf: Dict[float, float] = {}
            for val, prob in sorted_items:
                binned_val = round(min_val + math.floor((val - min_val) / bin_size) * bin_size, 2)
                binned_pmf[binned_val] = binned_pmf.get(binned_val, 0.0) + prob
            current_pmf = binned_pmf
        else:
            current_pmf = next_pmf

    return DiscreteDistribution(current_pmf), budget_exceeded


@dataclass(frozen=True)
class CellFitDiagnostic:
    """Structural fit and grid capacity diagnostic (independent re-implementation of CELL_FIT).

    Non-intrusive: does NOT delete production solver states or modify production probabilities.
    """
    fit_score: float = 1.0
    feasible: bool = True
    conflicts: Tuple[str, ...] = ()
    evidence_used: Tuple[str, ...] = ()
    experimental_rejected: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "fitScore": round(self.fit_score, 4),
            "feasible": self.feasible,
            "conflicts": list(self.conflicts),
            "evidenceUsed": list(self.evidence_used),
            "experimentalRejected": self.experimental_rejected,
            "details": self.details,
        }


def compute_cell_fit(
    session_ctx: Mapping[str, Any],
    total_grid: int = 54,
) -> CellFitDiagnostic:
    """Evaluate structural grid feasibility using item count, grid dimensions, and footprints."""
    conflicts: List[str] = []
    evidence_used: List[str] = []

    q = session_ctx.get("q")
    if isinstance(q, (int, float)) and q > 0:
        evidence_used.append("q")
        if q > total_grid:
            conflicts.append("ITEM_COUNT_EXCEEDS_GRID_CAPACITY")

    known_items = session_ctx.get("knownItems", [])
    known_cells_total = 0
    if isinstance(known_items, list) and known_items:
        evidence_used.append("knownItems")
        for item in known_items:
            if isinstance(item, dict):
                cells = item.get("cells") or item.get("gridFootprint") or item.get("size", 1)
                if isinstance(cells, (int, float)) and cells > 0:
                    known_cells_total += int(cells)
        if known_cells_total > total_grid:
            conflicts.append("KNOWN_ITEM_FOOTPRINTS_EXCEED_TOTAL_GRID")

    quality_grids = session_ctx.get("qualityGrids", {})
    quality_counts = session_ctx.get("qualityCounts", {})
    if isinstance(quality_grids, dict) and isinstance(quality_counts, dict):
        evidence_used.append("qualityGrids")
        evidence_used.append("qualityCounts")
        for q_name, grid_cells in quality_grids.items():
            cnt = quality_counts.get(q_name)
            if isinstance(grid_cells, (int, float)) and isinstance(cnt, (int, float)):
                if cnt > 0 and grid_cells < cnt:
                    conflicts.append(f"{q_name.upper()}_GRID_LESS_THAN_ITEM_COUNT")

    feasible = (len(conflicts) == 0)
    if not feasible:
        fit_score = 0.0
        experimental_rejected = True
    else:
        used_ratio = min(1.0, known_cells_total / max(1, total_grid))
        fit_score = max(0.01, 1.0 - (0.5 * used_ratio))
        experimental_rejected = False

    return CellFitDiagnostic(
        fit_score=fit_score,
        feasible=feasible,
        conflicts=tuple(conflicts),
        evidence_used=tuple(evidence_used),
        experimental_rejected=experimental_rejected,
        details={
            "totalGrid": total_grid,
            "knownCellsTotal": known_cells_total,
            "itemCountQ": q,
        },
    )


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
    """Registry managing experimental profiles. Defaults strictly to baseline only."""

    def __init__(self):
        self._profiles: Dict[str, ExperimentalStrategyProfile] = {}
        self._active_profile_ids: Set[str] = set()
        self._register_default_profiles()

    def _register_default_profiles(self) -> None:
        # 1. Baseline Canonical Profile
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="baseline",
                name="Canonical Baseline",
                description="Authoritative production and historical shadow baseline model.",
                source="canonical_baseline",
                source_project="yihuanpaimai_core",
                source_version="v2.0",
                evidence_level="canonical",
                parameters={},
                experimental=True,
                production_eligible=False,
                validated_by_our_data=True,
                enabled_by_default=True,
            )
        )

        # 2. Dafu Round Heuristic Profile (R1-R4)
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="dafu_round_heuristic_v1",
                name="Dafu Round Heuristic v1 (R1-R4)",
                description="External round-discount and reserve scaling hypotheses from Dafu calculator.",
                source="external_reference",
                source_project="dafu_calculator",
                source_version="v2.0-v2.3",
                evidence_level="unverified_external_hypothesis",
                parameters={
                    "r1_discount": 0.85,
                    "r2_discount": 0.90,
                    "r3_discount": 0.95,
                    "r4_discount": 1.00,
                    "reserve_multiplier": 0.92,
                    "conservative_multiplier": 0.88,
                },
                experimental=True,
                production_eligible=False,
                validated_by_our_data=False,
                enabled_by_default=False,
            )
        )

        # 3. Dafu Color Prior Profile
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="external_color_prior_dafu_v1",
                name="Dafu Color Prior Ratios v1",
                description="External fixed quality ratio hypotheses (2.2:1.85:1) from Dafu calculator.",
                source="external_reference",
                source_project="dafu_calculator",
                source_version="v2.0-v2.3",
                evidence_level="unverified_external_hypothesis",
                parameters={
                    "gold_weight": 2.2,
                    "purple_weight": 1.85,
                    "blue_weight": 1.0,
                    "sampling_assumption": "explicit_external_ratio",
                },
                experimental=True,
                production_eligible=False,
                validated_by_our_data=False,
                enabled_by_default=False,
            )
        )

        # 4. CELL_FIT Structural Diagnostic Profile
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="cell_fit_v1",
                name="CELL_FIT Structural Diagnostic v1",
                description="Experimental packing constraint check on warehouse inventory and item footprints.",
                source="external_reference_adapted",
                source_project="dafu_calculator",
                source_version="v2.0-v2.3",
                evidence_level="experimental_structural_heuristic",
                parameters={
                    "default_total_grid": 54,
                    "strict_footprint_gate": True,
                },
                experimental=True,
                production_eligible=False,
                validated_by_our_data=False,
                enabled_by_default=False,
            )
        )

        # 5. Convolution / Generating Function Distribution Lab Profile
        self.register_profile(
            ExperimentalStrategyProfile(
                profile_id="convolution_v1",
                name="Generating Function / Convolution v1",
                description="Discrete polynomial convolution for component probability distributions.",
                source="canonical_generating_function",
                source_project="yihuanpaimai_lab",
                source_version="v1.0",
                evidence_level="mathematical_convolution",
                parameters={
                    "max_states": DEFAULT_MAX_CONVOLUTION_STATES,
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
        if profile_id in self._profiles:
            self._active_profile_ids.add(profile_id)
            return True
        return False

    def disable_profile(self, profile_id: str) -> bool:
        if profile_id == "baseline":
            return False  # baseline cannot be disabled
        if profile_id in self._active_profile_ids:
            self._active_profile_ids.remove(profile_id)
            return True
        return False

    def is_profile_enabled(self, profile_id: str) -> bool:
        return profile_id in self._active_profile_ids

    def get_active_profile_ids(self) -> List[str]:
        return sorted(list(self._active_profile_ids))

    def reset_for_new_match(self) -> None:
        """Reset active profile set strictly to baseline for each new match."""
        self._active_profile_ids = {"baseline"}


# Global registry instance
_GLOBAL_REGISTRY: Optional[ExperimentalStrategyRegistry] = None


def get_global_strategy_registry() -> ExperimentalStrategyRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = ExperimentalStrategyRegistry()
    return _GLOBAL_REGISTRY


@dataclass
class ExperimentalProbabilityStrategyReport:
    """Contract-compliant result payload from the Probability and Strategy Lab."""
    experimental: bool = True
    production_eligible: bool = False
    status: str = "evaluated"
    active_profiles: List[str] = field(default_factory=lambda: ["baseline"])
    baseline_distribution: Optional[DiscreteDistribution] = None
    convolved_distribution: Optional[DiscreteDistribution] = None
    p20: Optional[float] = None
    p50: Optional[float] = None
    p80: Optional[float] = None
    mean: Optional[float] = None
    experimental_reserve_price: Optional[float] = None
    experimental_conservative_price: Optional[float] = None
    cell_fit: Optional[CellFitDiagnostic] = None
    external_color_prior: Optional[Dict[str, Any]] = None
    delta_vs_production: Optional[Dict[str, Any]] = None
    delta_vs_pr_b_red: Optional[Dict[str, Any]] = None
    sample_n: int = 0
    warnings: List[str] = field(default_factory=list)
    disclaimers: List[str] = field(default_factory=lambda: ["实验结果 · 不参与正式出价"])
    budget_exceeded: bool = False

    def to_payload(self) -> Dict[str, Any]:
        return {
            "experimental": self.experimental,
            "productionEligible": self.production_eligible,
            "status": self.status,
            "activeProfiles": self.active_profiles,
            "baselineDistribution": self.baseline_distribution.to_payload() if self.baseline_distribution else None,
            "convolvedDistribution": self.convolved_distribution.to_payload() if self.convolved_distribution else None,
            "p20": round(self.p20, 2) if self.p20 is not None else None,
            "p50": round(self.p50, 2) if self.p50 is not None else None,
            "p80": round(self.p80, 2) if self.p80 is not None else None,
            "mean": round(self.mean, 2) if self.mean is not None else None,
            "experimentalReservePrice": round(self.experimental_reserve_price, 2) if self.experimental_reserve_price is not None else None,
            "experimentalConservativePrice": round(self.experimental_conservative_price, 2) if self.experimental_conservative_price is not None else None,
            "cellFit": self.cell_fit.to_payload() if self.cell_fit else None,
            "externalColorPrior": self.external_color_prior,
            "deltaVsProduction": self.delta_vs_production,
            "deltaVsPrBRed": self.delta_vs_pr_b_red,
            "sampleN": self.sample_n,
            "warnings": self.warnings,
            "disclaimers": self.disclaimers,
            "budgetExceeded": self.budget_exceeded,
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

    warnings: List[str] = []
    disclaimers: List[str] = ["实验结果 · 不参与正式出价"]

    has_external_active = any(pid != "baseline" for pid in active_ids)
    if has_external_active:
        disclaimers.append("外部经验参数 · 未经我方真实历史验证")

    q = session_ctx.get("q")
    gold_avg = session_ctx.get("goldAvg")
    has_basic_intel = (
        isinstance(q, (int, float)) and q > 0 and isinstance(gold_avg, (int, float)) and gold_avg > 0
    )

    # 1. Baseline Discrete Distribution
    base_dist = None
    if has_basic_intel:
        center = float(q) * float(gold_avg)
        base_pmf = {
            round(center * 0.9, 2): 0.2,
            round(center * 1.0, 2): 0.6,
            round(center * 1.1, 2): 0.2,
        }
        base_dist = DiscreteDistribution(base_pmf)

    # 2. Convolution Component Building
    components: List[DiscreteDistribution] = []
    if base_dist:
        components.append(base_dist)

    # If PR-B experimental red is present, incorporate its value quantiles into experimental convolution
    if experimental_red and isinstance(experimental_red, dict):
        rq = experimental_red.get("redTotalQuantiles")
        if isinstance(rq, dict) and rq.get("p50") is not None and rq.get("p50", 0) > 0:
            red_pmf = {
                float(rq.get("p20", 0.0)): 0.2,
                float(rq.get("p50", 0.0)): 0.6,
                float(rq.get("p80", 0.0)): 0.2,
            }
            try:
                components.append(DiscreteDistribution(red_pmf))
            except Exception:
                pass

    budget_exceeded = False
    convolved_dist: Optional[DiscreteDistribution] = None
    if reg.is_profile_enabled("convolution_v1") and components:
        convolved_dist, budget_exceeded = convolve_discrete_distributions(components)
        if budget_exceeded:
            warnings.append("State-space budget exceeded: distribution downsampled to budget limit.")
    elif base_dist:
        convolved_dist = base_dist

    # 3. Quantile and Price Estimates
    p20 = convolved_dist.quantiles.p20 if convolved_dist else None
    p50 = convolved_dist.quantiles.p50 if convolved_dist else None
    p80 = convolved_dist.quantiles.p80 if convolved_dist else None
    mean_val = convolved_dist.mean if convolved_dist else None

    exp_reserve = None
    exp_conservative = None

    if p50 is not None:
        if reg.is_profile_enabled("dafu_round_heuristic_v1"):
            p_dafu = reg.get_profile("dafu_round_heuristic_v1")
            params = p_dafu.parameters if p_dafu else {}
            res_mul = float(params.get("reserve_multiplier", 0.92))
            con_mul = float(params.get("conservative_multiplier", 0.88))
            round_idx = int(session_ctx.get("round", 1))
            r_key = f"r{min(4, max(1, round_idx))}_discount"
            r_disc = float(params.get(r_key, 1.0))

            exp_reserve = p50 * res_mul * r_disc
            exp_conservative = (p20 if p20 is not None else p50) * con_mul * r_disc
        else:
            exp_reserve = p50 * 0.90
            exp_conservative = p20 if p20 is not None else (p50 * 0.85)

    # 4. CELL_FIT Structural Diagnostic
    cell_fit = None
    if reg.is_profile_enabled("cell_fit_v1"):
        cell_fit = compute_cell_fit(session_ctx)
        if cell_fit.conflicts:
            warnings.append(f"CELL_FIT conflicts: {', '.join(cell_fit.conflicts)}")

    # 5. External Color Prior Report
    color_prior_info = None
    if reg.is_profile_enabled("external_color_prior_dafu_v1"):
        p_cp = reg.get_profile("external_color_prior_dafu_v1")
        color_prior_info = {
            "profileId": "external_color_prior_dafu_v1",
            "sourceProject": p_cp.source_project if p_cp else None,
            "sourceVersion": p_cp.source_version if p_cp else None,
            "evidenceLevel": p_cp.evidence_level if p_cp else None,
            "validatedByOurData": False,
            "samplingAssumption": "explicit_external_ratio",
            "ratios": p_cp.parameters if p_cp else {},
            "comparison": {
                "externalHypothesis": "Gold:Purple:Blue = 2.2:1.85:1",
                "prBEmpiricalRedCountAvailable": bool(experimental_red and experimental_red.get("eligibleMatchCount", 0) > 0),
                "productionShadowState": "six_quality_independent",
            }
        }

    # 6. Deltas vs Production and PR-B Red
    delta_prod = None
    if production_metrics and p50 is not None:
        prod_med = production_metrics.get("medianEstimate") or production_metrics.get("valP50")
        if isinstance(prod_med, (int, float)):
            delta_prod = {
                "medianDelta": round(p50 - float(prod_med), 2),
                "reserveVsTargetLine": round(exp_reserve - float(production_metrics.get("targetProfitLine", 0)), 2) if exp_reserve is not None and production_metrics.get("targetProfitLine") is not None else None,
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
        experimental=True,
        production_eligible=False,
        active_profiles=active_ids,
        baseline_distribution=base_dist,
        convolved_distribution=convolved_dist,
        status="evaluated" if has_basic_intel else "insufficient_data",
        p20=p20,
        p50=p50,
        p80=p80,
        mean=mean_val,
        experimental_reserve_price=exp_reserve,
        experimental_conservative_price=exp_conservative,
        cell_fit=cell_fit,
        external_color_prior=color_prior_info,
        delta_vs_production=delta_prod,
        delta_vs_pr_b_red=delta_red,
        sample_n=sample_n,
        warnings=warnings,
        disclaimers=disclaimers,
        budget_exceeded=budget_exceeded,
    )


def safe_evaluate_experimental_probability_strategy(
    session_ctx: Mapping[str, Any],
    production_metrics: Optional[Mapping[str, Any]] = None,
    shadow_profile: Optional[Mapping[str, Any]] = None,
    experimental_red: Optional[Mapping[str, Any]] = None,
    registry: Optional[ExperimentalStrategyRegistry] = None,
) -> Dict[str, Any]:
    """Fail-isolated wrapper around experimental probability strategy inference.

    Guarantees:
    - Never raises an unhandled exception.
    - Never mutates session_ctx, production_metrics, or shadow_profile.
    - Completely isolated from production solver execution paths.
    """
    try:
        report = evaluate_experimental_probability_strategy(
            session_ctx=session_ctx,
            production_metrics=production_metrics,
            shadow_profile=shadow_profile,
            experimental_red=experimental_red,
            registry=registry,
        )
        return report.to_payload()
    except Exception as exc:
        _LOG.warning("Experimental probability strategy isolated failure: %s", exc, exc_info=True)
        return {
            "experimental": True,
            "productionEligible": False,
            "status": "error",
            "error": f"ExperimentalProbabilityStrategyFailure: {exc}",
            "activeProfiles": ["baseline"],
            "warnings": ["Experimental strategy calculation failed-closed; production unaffected."],
            "disclaimers": ["实验结果 · 不参与正式出价"],
            "p20": None,
            "p50": None,
            "p80": None,
            "mean": None,
            "experimentalReservePrice": None,
            "experimentalConservativePrice": None,
            "cellFit": None,
            "budgetExceeded": False,
        }
