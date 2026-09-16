# -*- coding: utf-8 -*-
"""Strategy UX Metrics & User Strategy State Management.

Independent re-implementation for PR-A (feature/reference-ux-metrics):
1. Fast / Precise dual-mode interface (evaluation budget/presentation mode; retains
   identical canonical constraints and solver logic).
2. Mean / Median / Conservative triple-metric presentation summary (strictly traceable
   from our own models; never fabricating values; clearly marked conservativeSource).
3. Strategy / Analysis Panel Shell view-model (collapsible, experimental placeholder default collapsed).
4. Undo / Redo engine strictly limited to user-editable strategy/analysis inputs
   (capacity limited, reset on new match, never rolling back OCR, canonical facts, or archives).
5. Unified Round / Venue / Profile Strategy Interface (no external multipliers or formulas).
6. Clear Data Contract separating productionEligible=True from experimental=False.
"""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


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


@dataclass(frozen=True)
class StrategyMetricsSummary:
    """Authoritative summary presentation of valuation metrics.
    
    Data Contract Guarantees:
    - meanEstimate: strictly based on our model's expectation or center point.
    - medianEstimate: strictly based on our model's median/p50.
    - conservativeEstimate: strictly based on a legally traceable lower quantile
      (e.g. p20). If unavailable, MUST BE None. Never fabricate values!
    - conservativeSource: explicit provenance label (e.g. 'p20_point', 'unavailable').
    - productionEligible: True for official production models.
    - experimental: False for official production models.
    """
    estimateMode: str
    meanEstimate: Optional[float]
    medianEstimate: Optional[float]
    conservativeEstimate: Optional[float]
    conservativeSource: str
    productionEligible: bool = True
    experimental: bool = False

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


def compute_strategy_metrics_summary(
    mode: EstimateMode = EstimateMode.PRECISE,
    *,
    val_p50: Optional[float] = None,
    val_p20: Optional[float] = None,
    val_p80: Optional[float] = None,
    mean_val: Optional[float] = None,
    median_val: Optional[float] = None,
    conservative_val: Optional[float] = None,
    conservative_source: Optional[str] = None,
    prediction_snapshot: Optional[Dict[str, Any]] = None,
) -> StrategyMetricsSummary:
    """Compute strictly traceable metrics summary from our own model/solver outputs.
    
    Guarantees:
    - Never fabricates a conservative estimate if no traceable source exists.
    - If val_p20 is available from our production forecast/quantiles, conservativeEstimate is set
      to val_p20 with conservativeSource="p20_point".
    - Otherwise, conservativeEstimate is None with conservativeSource="unavailable".
    - productionEligible is always True, experimental is False for these outputs.
    """
    mode_str = mode.value if isinstance(mode, EstimateMode) else str(mode)

    # 1. Resolve from prediction_snapshot if provided and individual values are not given
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

        # Also inspect workingDecision or formalValue if present
        dec = prediction_snapshot.get("workingDecision") or {}
        if val_p50 is None and dec.get("center") is not None:
            try:
                val_p50 = float(dec["center"])
            except (ValueError, TypeError):
                pass

    # 2. Mean
    effective_mean: Optional[float] = None
    if mean_val is not None:
        effective_mean = float(mean_val)
    elif val_p50 is not None:
        effective_mean = float(val_p50)

    # 3. Median
    effective_median: Optional[float] = None
    if median_val is not None:
        effective_median = float(median_val)
    elif val_p50 is not None:
        effective_median = float(val_p50)

    # 4. Conservative (strictly traceable, no fabrication)
    effective_conservative: Optional[float] = None
    effective_source: str = "unavailable"

    if conservative_val is not None:
        effective_conservative = float(conservative_val)
        effective_source = str(conservative_source or "custom_traceable")
    elif val_p20 is not None:
        effective_conservative = float(val_p20)
        effective_source = "p20_point"
    else:
        effective_conservative = None
        effective_source = "unavailable"

    return StrategyMetricsSummary(
        estimateMode=mode_str,
        meanEstimate=round(effective_mean, 2) if effective_mean is not None else None,
        medianEstimate=round(effective_median, 2) if effective_median is not None else None,
        conservativeEstimate=round(effective_conservative, 2) if effective_conservative is not None else None,
        conservativeSource=effective_source,
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
    
    Does NOT contain or modify Canonical Match facts, OCR evidence, or archives.
    """
    round: int = 1
    venue: str = "standard"
    estimate_mode: EstimateMode = EstimateMode.PRECISE
    strategy_profile: StrategyProfile = StrategyProfile.DEFAULT
    custom_filters: Dict[str, bool] = field(default_factory=dict)
    is_panel_expanded: bool = True
    is_experimental_expanded: bool = False

    def copy(self) -> UserStrategyState:
        return copy.deepcopy(self)


class UserStrategyEditHistory:
    """Undo / Redo manager strictly for user-editable strategy inputs.
    
    Invariants:
    1. Only covers user-editable strategy fields (round, venue, mode, profile, filters).
    2. Capacity limited (default 50).
    3. New edit clears redo stack.
    4. Automatically clears across matches (never leaks cross-match history).
    5. Never touches OCR history, Canonical MatchRecord, or FINALIZED archives.
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
        """Clear all undo/redo history for a new match to avoid cross-match leakage."""
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.state = UserStrategyState()
        self._active_match_id = str(match_id).strip() if match_id else None

    def edit(self, field_name: str, new_value: Any) -> bool:
        """Apply a user strategy edit and record it onto the undo stack."""
        if not hasattr(self.state, field_name):
            return False

        old_val = getattr(self.state, field_name)
        if old_val == new_value:
            return False

        cmd = UserEditCommand(field=field_name, old_value=copy.deepcopy(old_val), new_value=copy.deepcopy(new_value))
        setattr(self.state, field_name, new_value)
        self.undo_stack.append(cmd)
        if len(self.undo_stack) > self.capacity:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        return True

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
    round: int = 1
    venue: str = "standard"
    strategy_profile: str = StrategyProfile.DEFAULT.value
    metrics_summary: Optional[StrategyMetricsSummary] = None
    production_estimate: Optional[float] = None
    # Experimental area placeholder: must default to collapsed and experimental=False
    is_experimental_expanded: bool = False
    experimental_available: bool = False
    experimental_notes: str = "Experimental modules (Red PMF, CELL_FIT, R1-R4) pending in future PRs."
    can_undo: bool = False
    can_redo: bool = False

    def to_payload(self) -> Dict[str, Any]:
        return {
            "isPanelExpanded": self.is_panel_expanded,
            "estimateMode": self.estimate_mode,
            "round": self.round,
            "venue": self.venue,
            "strategyProfile": self.strategy_profile,
            "metricsSummary": self.metrics_summary.to_payload() if self.metrics_summary else None,
            "productionEstimate": self.production_estimate,
            "isExperimentalExpanded": self.is_experimental_expanded,
            "experimentalAvailable": self.experimental_available,
            "experimentalNotes": self.experimental_notes,
            "canUndo": self.can_undo,
            "canRedo": self.can_redo,
        }


# Global singleton instance for runtime session tracking
GLOBAL_USER_STRATEGY_HISTORY = UserStrategyEditHistory()
