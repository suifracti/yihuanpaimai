# -*- coding: utf-8 -*-
"""Strategy UX Metrics & User Strategy State Management.

Independent re-implementation for PR-A (feature/reference-ux-metrics):
1. Fast / Precise dual-mode interface (Fast mode shell marked fastModeAvailable=False
   until true compute-budget solver is implemented in future PR; PRECISE is production baseline).
2. Mean / Median / Conservative triple-metric presentation summary (strictly traceable:
   Mean requires real distribution mean/expectation and NEVER impersonates P50;
   Median maps to P50; Conservative maps to P20 lower quantile without fabrication).
3. Strategy / Analysis Panel Shell view-model (collapsible, experimental placeholder default collapsed).
4. Authoritative single-store architecture (SSOT) guaranteeing zero state-drift across
   HUD, WebView JS bridge, AuctionBrain, and payload builders.
5. Typed, fail-closed WebView action reducer preventing AttributeError and invalid states.
6. Strategy round/venue clearly labeled as user_strategy to prevent confusion with Canonical facts.
"""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class EstimateMode(str, Enum):
    """Evaluation presentation and budget mode."""
    FAST = "fast"
    PRECISE = "precise"


class StrategyProfile(str, Enum):
    """Tactical strategy profile."""
    DEFAULT = "default"
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


LEGAL_STRATEGY_VENUES: Set[str] = frozenset({"standard", "haibei", "zhenzhu", "shanhu"})
LEGAL_STRATEGY_ROUNDS: Set[int] = frozenset({1, 2, 3, 4, 5})

FAST_MODE_AVAILABLE: bool = False


def validate_estimate_mode_request(value: Any) -> Tuple[bool, Optional[EstimateMode], Optional[str]]:
    """Validate and coerce estimate mode request across all entry points.
    
    Guarantees:
    - PRECISE -> accepted
    - FAST -> rejected if not FAST_MODE_AVAILABLE (Option 2 fail-closed)
    - All other values/types -> rejected fail-closed
    
    Returns:
        (is_valid: bool, coerced_mode: Optional[EstimateMode], error_message: Optional[str])
    """
    mode: Optional[EstimateMode] = None
    if isinstance(value, EstimateMode):
        mode = value
    elif isinstance(value, str):
        val_lower = value.strip().lower()
        if val_lower == "precise":
            mode = EstimateMode.PRECISE
        elif val_lower == "fast":
            mode = EstimateMode.FAST
        else:
            return False, None, f"Invalid estimate_mode '{value}'. Allowed: 'precise', 'fast'."
    else:
        return False, None, f"Invalid estimate_mode type: {type(value).__name__}"

    if mode == EstimateMode.FAST and not FAST_MODE_AVAILABLE:
        return False, None, "Fast mode compute-budget solver is currently unavailable (fastModeAvailable=False); system remains in PRECISE mode."

    return True, mode, None


@dataclass(frozen=True)
class StrategyMetricsSummary:
    """Authoritative summary presentation of valuation metrics.
    
    Data Contract Guarantees:
    - meanEstimate: strictly based on traceable expectation/mean. If unavailable, MUST be None.
    - meanSource: provenance label (e.g. 'distribution_mean', 'explicit_mean', 'unavailable').
    - medianEstimate: strictly based on model median / p50.
    - medianSource: provenance label (e.g. 'p50_point', 'explicit_median', 'unavailable').
    - conservativeEstimate: strictly based on legally traceable lower quantile (e.g. p20).
      If unavailable, MUST be None. Never fabricate fallback numbers!
    - conservativeSource: explicit provenance label (e.g. 'p20_point', 'unavailable').
    - productionEligible: True for official production models.
    - experimental: False for official production models.
    """
    estimateMode: str
    meanEstimate: Optional[float]
    meanSource: str
    medianEstimate: Optional[float]
    medianSource: str
    conservativeEstimate: Optional[float]
    conservativeSource: str
    productionEligible: bool = True
    experimental: bool = False

    def to_payload(self) -> Dict[str, Any]:
        return {
            "estimateMode": self.estimateMode,
            "meanEstimate": self.meanEstimate,
            "meanSource": self.meanSource,
            "medianEstimate": self.medianEstimate,
            "medianSource": self.medianSource,
            "conservativeEstimate": self.conservativeEstimate,
            "conservativeSource": self.conservativeSource,
            "productionEligible": self.productionEligible,
            "experimental": self.experimental,
        }


def compute_strategy_metrics_summary(
    mode: EstimateMode = EstimateMode.PRECISE,
    *,
    val_p50: Optional[float] = None,
    val_p20: Optional[float] = None,
    val_p80: Optional[float] = None,
    mean_val: Optional[float] = None,
    mean_source_override: Optional[str] = None,
    median_val: Optional[float] = None,
    median_source_override: Optional[str] = None,
    conservative_val: Optional[float] = None,
    conservative_source: Optional[str] = None,
    prediction_snapshot: Optional[Dict[str, Any]] = None,
) -> StrategyMetricsSummary:
    """Compute strictly traceable metrics summary.
    
    Guarantees:
    - P50 is NEVER used to impersonate meanEstimate. Mean requires true expectation/mean.
    - If no true mean is available, meanEstimate is None with meanSource="unavailable".
    - Median legitimately reflects val_p50 or explicit median_val.
    - Conservative strictly reflects val_p20 or explicit lower quantile; if missing, returns None.
    """
    valid, validated_mode, err = validate_estimate_mode_request(mode)
    if not valid:
        raise ValueError(f"compute_strategy_metrics_summary rejected: {err}")
    mode_str = validated_mode.value

    # 1. Resolve from prediction_snapshot if provided and individual values are not given
    dist_mean: Optional[float] = None
    if isinstance(prediction_snapshot, dict):
        forecast = prediction_snapshot.get("forecast") or {}
        quantiles = forecast.get("quantiles") or {}
        if val_p50 is None and quantiles.get("p50") is not None:
            try:
                val_p50 = float(quantiles["p50"])
            except (ValueError, TypeError):
                pass
        if val_p20 is None and quantiles.get("p20") is not None:
            try:
                val_p20 = float(quantiles["p20"])
            except (ValueError, TypeError):
                pass
        if val_p80 is None and quantiles.get("p80") is not None:
            try:
                val_p80 = float(quantiles["p80"])
            except (ValueError, TypeError):
                pass

        # Check explicit mean/expectation in distribution snapshot
        raw_mean = forecast.get("mean") if "mean" in forecast else prediction_snapshot.get("mean")
        if raw_mean is not None:
            try:
                dist_mean = float(raw_mean)
            except (ValueError, TypeError):
                dist_mean = None

        # Also inspect workingDecision center for p50 fallback
        dec = prediction_snapshot.get("workingDecision") or {}
        if val_p50 is None and dec.get("center") is not None:
            try:
                val_p50 = float(dec["center"])
            except (ValueError, TypeError):
                pass

    # 2. Mean (Strict provenance, NEVER impersonate from P50)
    effective_mean: Optional[float] = None
    effective_mean_source: str = "unavailable"
    if mean_val is not None:
        effective_mean = float(mean_val)
        effective_mean_source = str(mean_source_override or "explicit_mean")
    elif dist_mean is not None:
        effective_mean = float(dist_mean)
        effective_mean_source = "distribution_mean"
    else:
        effective_mean = None
        effective_mean_source = "unavailable"

    # 3. Median (Legitimately sourced from P50 or median_val)
    effective_median: Optional[float] = None
    effective_median_source: str = "unavailable"
    if median_val is not None:
        effective_median = float(median_val)
        effective_median_source = str(median_source_override or "explicit_median")
    elif val_p50 is not None:
        effective_median = float(val_p50)
        effective_median_source = "p50_point"
    else:
        effective_median = None
        effective_median_source = "unavailable"

    # 4. Conservative (strictly traceable lower quantile, no fabrication)
    effective_conservative: Optional[float] = None
    effective_cons_source: str = "unavailable"
    if conservative_val is not None:
        effective_conservative = float(conservative_val)
        effective_cons_source = str(conservative_source or "custom_traceable")
    elif val_p20 is not None:
        effective_conservative = float(val_p20)
        effective_cons_source = "p20_point"
    else:
        effective_conservative = None
        effective_cons_source = "unavailable"

    return StrategyMetricsSummary(
        estimateMode=mode_str,
        meanEstimate=round(effective_mean, 2) if effective_mean is not None else None,
        meanSource=effective_mean_source,
        medianEstimate=round(effective_median, 2) if effective_median is not None else None,
        medianSource=effective_median_source,
        conservativeEstimate=round(effective_conservative, 2) if effective_conservative is not None else None,
        conservativeSource=effective_cons_source,
        productionEligible=True,
        experimental=False,
    )


@dataclass(frozen=True)
class UserEditCommand:
    """Individual reversible user strategy edit."""
    field: str
    old_value: Any
    new_value: Any
    timestamp: float = field(default_factory=time.time)


@dataclass
class UserStrategyState:
    """Mutable container strictly for user-editable tactical/strategy inputs.
    
    Fields strategy_round and strategy_venue are strictly strategy inputs and
    never overwrite Canonical facts (CurrentMatch.round, CurrentMatch.venue).
    """
    strategy_round: int = 1
    strategy_venue: str = "standard"
    estimate_mode: EstimateMode = EstimateMode.PRECISE
    strategy_profile: StrategyProfile = StrategyProfile.DEFAULT
    custom_filters: Dict[str, bool] = field(default_factory=dict)
    is_panel_expanded: bool = True
    is_experimental_expanded: bool = False

    # Backwards-compatible aliases
    @property
    def round(self) -> int:
        return self.strategy_round

    @round.setter
    def round(self, val: int) -> None:
        self.strategy_round = int(val)

    @property
    def venue(self) -> str:
        return self.strategy_venue

    @venue.setter
    def venue(self, val: str) -> None:
        self.strategy_venue = str(val)

    def copy(self) -> UserStrategyState:
        return copy.deepcopy(self)


class UserStrategyEditHistory:
    """Undo / Redo manager strictly for user-editable strategy inputs.
    
    Invariants:
    1. Only covers user-editable strategy fields.
    2. Capacity limited (default 50).
    3. New edit clears redo stack.
    4. Automatically clears across matches (never leaks cross-match history).
    5. Never touches OCR history, Canonical MatchRecord, or FINALIZED archives.
    6. Typed, fail-closed validation reducer for all WebView/API inputs.
    """

    DEFAULT_CAPACITY = 50

    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        self.capacity = max(1, capacity)
        self.state = UserStrategyState()
        self.undo_stack: List[UserEditCommand] = []
        self.redo_stack: List[UserEditCommand] = []
        self._active_match_id: Optional[str] = None

    @property
    def can_undo(self) -> bool:
        return len(self.undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0

    def reset_for_new_match(self, match_id: Optional[str] = None) -> None:
        """Clear all undo/redo history when a new match lifecycle begins."""
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.state = UserStrategyState()
        self._active_match_id = str(match_id).strip() if match_id else None

    def edit_typed(self, field_name: str, new_value: Any) -> Tuple[bool, Optional[str]]:
        """Typed, fail-closed validation reducer for user strategy mutations.
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        if not isinstance(field_name, str):
            return False, "field_name must be a string"

        field_key = field_name.strip()
        # Canonicalize aliases
        if field_key == "round":
            field_key = "strategy_round"
        elif field_key == "venue":
            field_key = "strategy_venue"

        # Field whitelist check
        allowed_fields = {
            "strategy_round",
            "strategy_venue",
            "estimate_mode",
            "strategy_profile",
            "is_panel_expanded",
            "is_experimental_expanded",
            "custom_filters",
        }
        if field_key not in allowed_fields:
            return False, f"Unknown or disallowed strategy field: '{field_name}'"

        # Typed validation & coercion
        coerced_value: Any = None
        if field_key == "estimate_mode":
            valid, validated_mode, err = validate_estimate_mode_request(new_value)
            if not valid:
                return False, err
            coerced_value = validated_mode

        elif field_key == "strategy_profile":
            if isinstance(new_value, StrategyProfile):
                coerced_value = new_value
            elif isinstance(new_value, str):
                val_lower = new_value.strip().lower()
                try:
                    coerced_value = StrategyProfile(val_lower)
                except ValueError:
                    allowed = [p.value for p in StrategyProfile]
                    return False, f"Invalid strategy_profile '{new_value}'. Allowed: {allowed}."
            else:
                return False, f"Invalid strategy_profile type: {type(new_value).__name__}"

        elif field_key == "strategy_round":
            try:
                coerced_int = int(new_value)
            except (ValueError, TypeError):
                return False, f"strategy_round must be an integer: {new_value}"
            if coerced_int not in LEGAL_STRATEGY_ROUNDS:
                return False, f"strategy_round out of range [1..5]: {coerced_int}"
            coerced_value = coerced_int

        elif field_key == "strategy_venue":
            if not isinstance(new_value, str):
                return False, f"strategy_venue must be a string: {new_value}"
            val_lower = new_value.strip().lower()
            if val_lower not in LEGAL_STRATEGY_VENUES:
                allowed_v = sorted(list(LEGAL_STRATEGY_VENUES))
                return False, f"strategy_venue '{new_value}' is invalid. Allowed: {allowed_v}."
            coerced_value = val_lower

        elif field_key in {"is_panel_expanded", "is_experimental_expanded"}:
            if not isinstance(new_value, bool):
                if isinstance(new_value, (int, str)):
                    if str(new_value).lower() in ("true", "1"):
                        coerced_value = True
                    elif str(new_value).lower() in ("false", "0"):
                        coerced_value = False
                    else:
                        return False, f"{field_key} must be boolean: {new_value}"
                else:
                    return False, f"{field_key} must be boolean"
            else:
                coerced_value = new_value

        elif field_key == "custom_filters":
            if not isinstance(new_value, dict):
                return False, "custom_filters must be a dict"
            coerced_value = dict(new_value)

        # Fail-closed check passed. If value unchanged, no-op without creating dirty undo entry
        old_val = getattr(self.state, field_key)
        if old_val == coerced_value:
            return True, None

        cmd = UserEditCommand(
            field=field_key,
            old_value=copy.deepcopy(old_val),
            new_value=copy.deepcopy(coerced_value),
        )
        setattr(self.state, field_key, coerced_value)
        self.undo_stack.append(cmd)
        if len(self.undo_stack) > self.capacity:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        return True, None

    def edit(self, field_name: str, new_value: Any) -> bool:
        """Backwards compatible edit method returning boolean."""
        success, _ = self.edit_typed(field_name, new_value)
        return success

    def undo(self) -> Optional[UserEditCommand]:
        """Revert the most recent user strategy edit."""
        if not self.undo_stack:
            return None
        cmd = self.undo_stack.pop()
        setattr(self.state, cmd.field, cmd.old_value)
        self.redo_stack.append(cmd)
        return cmd

    def redo(self) -> Optional[UserEditCommand]:
        """Reapply the most recently undone user strategy edit."""
        if not self.redo_stack:
            return None
        cmd = self.redo_stack.pop()
        setattr(self.state, cmd.field, cmd.new_value)
        self.undo_stack.append(cmd)
        return cmd


@dataclass
class StrategyPanelShellState:
    """Collapsible Strategy & Analysis Panel shell representation."""
    is_panel_expanded: bool = True
    estimate_mode: str = EstimateMode.PRECISE.value
    fast_mode_available: bool = FAST_MODE_AVAILABLE
    fast_mode_notes: str = "Fast mode compute-budget solver is reserved for future PR; PRECISE is active."
    strategy_round: int = 1
    strategy_venue: str = "standard"
    strategy_profile: str = StrategyProfile.DEFAULT.value
    strategy_source: str = "user_strategy"
    metrics_summary: Optional[StrategyMetricsSummary] = None
    production_estimate: Optional[float] = None
    is_experimental_expanded: bool = False
    experimental_available: bool = False
    experimental_notes: str = "Experimental modules (Red PMF, CELL_FIT, R1-R4) pending in future PRs."
    can_undo: bool = False
    can_redo: bool = False

    # Backwards-compatibility properties
    @property
    def round(self) -> int:
        return self.strategy_round

    @property
    def venue(self) -> str:
        return self.strategy_venue

    def to_payload(self) -> Dict[str, Any]:
        return {
            "isPanelExpanded": self.is_panel_expanded,
            "estimateMode": self.estimate_mode,
            "fastModeAvailable": self.fast_mode_available,
            "fastModeNotes": self.fast_mode_notes,
            "strategyRound": self.strategy_round,
            "strategyVenue": self.strategy_venue,
            "strategySource": self.strategy_source,
            # Legacy fields for UI binding with source clearly isolated
            "round": self.strategy_round,
            "venue": self.strategy_venue,
            "strategyProfile": self.strategy_profile,
            "metricsSummary": self.metrics_summary.to_payload() if self.metrics_summary else None,
            "productionEstimate": self.production_estimate,
            "isExperimentalExpanded": self.is_experimental_expanded,
            "experimentalAvailable": self.experimental_available,
            "experimentalNotes": self.experimental_notes,
            "canUndo": self.can_undo,
            "canRedo": self.can_redo,
        }


# Authoritative Single Source of Truth (SSOT) store
_AUTHORITATIVE_STRATEGY_STORE: Optional[UserStrategyEditHistory] = None


def get_authoritative_strategy_store() -> UserStrategyEditHistory:
    """Retrieve the single authoritative runtime strategy store."""
    global _AUTHORITATIVE_STRATEGY_STORE
    if _AUTHORITATIVE_STRATEGY_STORE is None:
        _AUTHORITATIVE_STRATEGY_STORE = UserStrategyEditHistory()
    return _AUTHORITATIVE_STRATEGY_STORE


def set_authoritative_strategy_store(store: UserStrategyEditHistory) -> None:
    """Set or replace the authoritative strategy store (e.g. for testing isolation)."""
    global _AUTHORITATIVE_STRATEGY_STORE
    _AUTHORITATIVE_STRATEGY_STORE = store


class _GlobalStoreProxy:
    """Proxy object ensuring GLOBAL_USER_STRATEGY_HISTORY always routes to authoritative store."""
    def __getattr__(self, name: str) -> Any:
        return getattr(get_authoritative_strategy_store(), name)


GLOBAL_USER_STRATEGY_HISTORY = _GlobalStoreProxy()
