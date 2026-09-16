# -*- coding: utf-8 -*-
"""Quality Sell Selection Model and Rules (Fourteen Unfinished Boundaries Item 2).

Canonical Business Semantics:
1. Bottom quality colors are 'sell selection controls' (出售选择控制), NOT item existence or reveal status.
2. When the user acquires the lot themselves (acquired=True), the game defaults to:
   - white: 'selected'
   - green: 'selected'
   - blue: 'selected'
   - purple: 'selected'
   - gold: 'selected'
   - red: 'unselected'
3. When acquired is False or unknown (None), do NOT force the self-acquired default (defaults to 'unknown').
4. Existing visual or interactive evidence takes precedence over defaults.
5. Deselecting/toggling a color updates ONLY that color's selection state.
6. A new match re-initializes; NEVER inherit from previous match (no cross-match permanent preference memory).
7. Red being 'unselected' NEVER implies red items do not exist.
8. Capture, geometry, and identity recognition do not require user to uncheck first, nor wait for marks to disappear.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, Optional, Tuple
import cv2
import numpy as np

CANONICAL_QUALITIES: Tuple[str, ...] = ("white", "green", "blue", "purple", "gold", "red")

SELECTION_SELECTED = "selected"
SELECTION_UNSELECTED = "unselected"
SELECTION_UNKNOWN = "unknown"

VALID_SELECTION_STATES = frozenset({
    SELECTION_SELECTED,
    SELECTION_UNSELECTED,
    SELECTION_UNKNOWN,
})

SOURCE_DEFAULT_SELF_ACQUIRED = "default_self_acquired"
SOURCE_VISUAL_OBSERVED = "visual_observed"
SOURCE_MANUAL_OVERRIDE = "manual_override"
SOURCE_UNKNOWN = "unknown"

VALID_SELECTION_SOURCES = frozenset({
    SOURCE_DEFAULT_SELF_ACQUIRED,
    SOURCE_VISUAL_OBSERVED,
    SOURCE_MANUAL_OVERRIDE,
    SOURCE_UNKNOWN,
})

DEFAULT_SELF_ACQUIRED_SELECTION: Dict[str, str] = {
    "white": SELECTION_SELECTED,
    "green": SELECTION_SELECTED,
    "blue": SELECTION_SELECTED,
    "purple": SELECTION_SELECTED,
    "gold": SELECTION_SELECTED,
    "red": SELECTION_UNSELECTED,
}

DEFAULT_UNKNOWN_SELECTION: Dict[str, str] = {
    q: SELECTION_UNKNOWN for q in CANONICAL_QUALITIES
}


def resolve_default_quality_sell_selection(acquired: Optional[bool]) -> Dict[str, str]:
    """Resolve default sell selection based on credible acquisition authority evidence.
    
    Returns selection_dict mapping each canonical quality to its selection state.
    Only applies 'all-except-red' default when acquired is strictly True.
    """
    if acquired is True:
        return copy.deepcopy(DEFAULT_SELF_ACQUIRED_SELECTION)
    return copy.deepcopy(DEFAULT_UNKNOWN_SELECTION)


def resolve_default_quality_sell_selection_with_source(acquired: Optional[bool]) -> Tuple[Dict[str, str], str]:
    """Resolve default sell selection along with source string."""
    if acquired is True:
        return copy.deepcopy(DEFAULT_SELF_ACQUIRED_SELECTION), SOURCE_DEFAULT_SELF_ACQUIRED
    return copy.deepcopy(DEFAULT_UNKNOWN_SELECTION), SOURCE_UNKNOWN


def normalize_quality_sell_selection(raw: Any) -> Optional[Dict[str, str]]:
    """Validate and normalize a quality sell selection mapping.
    
    Guarantees all 6 canonical qualities exist with valid states.
    Returns None if raw is invalid.
    """
    if not isinstance(raw, Mapping):
        return None
    normalized: Dict[str, str] = {}
    for q in CANONICAL_QUALITIES:
        val = raw.get(q)
        if val is None:
            normalized[q] = SELECTION_UNKNOWN
        elif isinstance(val, str) and val.strip().lower() in VALID_SELECTION_STATES:
            normalized[q] = val.strip().lower()
        elif isinstance(val, bool):
            normalized[q] = SELECTION_SELECTED if val else SELECTION_UNSELECTED
        else:
            normalized[q] = SELECTION_UNKNOWN
    return normalized


def update_single_quality_sell_selection(
    current: Optional[Mapping[str, str]],
    quality: str,
    new_state: str,
) -> Dict[str, str]:
    """Update a single quality's sell selection state without affecting any other color.
    
    Returns updated selection dict.
    """
    quality_norm = str(quality).strip().lower()
    if quality_norm not in CANONICAL_QUALITIES:
        raise ValueError(f"Invalid canonical quality name: {quality}")
    state_norm = str(new_state).strip().lower()
    if state_norm not in VALID_SELECTION_STATES:
        raise ValueError(f"Invalid selection state: {new_state}")

    base = dict(normalize_quality_sell_selection(current) or DEFAULT_UNKNOWN_SELECTION)
    base[quality_norm] = state_norm
    return base


# ---------------------------------------------------------------------------
# Per-color provenance (Boundary 2, external review 2026-09-16)
#
# The original model stored ONE aggregate string for all six colors.  That made
# a single manual toggle lock the entire dict, so a later visual observation
# could never update the other five colors.  Provenance is therefore tracked
# per color; the aggregate string is only a derived summary for legacy readers.
# ---------------------------------------------------------------------------

def normalize_quality_sell_selection_sources(raw: Any) -> Dict[str, str]:
    """Validate and normalize a per-color provenance mapping.

    Guarantees all 6 canonical qualities exist. Unknown/invalid entries become
    SOURCE_UNKNOWN so provenance is never silently invented.
    """
    sources: Dict[str, str] = {}
    mapping = raw if isinstance(raw, Mapping) else {}
    for q in CANONICAL_QUALITIES:
        val = mapping.get(q)
        if isinstance(val, str) and val.strip().lower() in VALID_SELECTION_SOURCES:
            sources[q] = val.strip().lower()
        else:
            sources[q] = SOURCE_UNKNOWN
    return sources


def sources_from_aggregate(aggregate_source: Any) -> Dict[str, str]:
    """Legacy bridge: expand one aggregate source string into per-color sources."""
    if isinstance(aggregate_source, str) and aggregate_source.strip().lower() in VALID_SELECTION_SOURCES:
        src = aggregate_source.strip().lower()
    else:
        src = SOURCE_UNKNOWN
    return {q: src for q in CANONICAL_QUALITIES}


def manual_override_colors(sources: Optional[Mapping[str, str]]) -> Tuple[str, ...]:
    """Colors the user explicitly overrode.  These are the ONLY protected colors."""
    norm = normalize_quality_sell_selection_sources(sources)
    return tuple(q for q in CANONICAL_QUALITIES if norm[q] == SOURCE_MANUAL_OVERRIDE)


def aggregate_selection_source(sources: Optional[Mapping[str, str]]) -> str:
    """Derive the legacy aggregate source string from per-color provenance."""
    norm = normalize_quality_sell_selection_sources(sources)
    values = set(norm.values())
    if SOURCE_MANUAL_OVERRIDE in values:
        return SOURCE_MANUAL_OVERRIDE
    if SOURCE_VISUAL_OBSERVED in values:
        return SOURCE_VISUAL_OBSERVED
    if values == {SOURCE_DEFAULT_SELF_ACQUIRED}:
        return SOURCE_DEFAULT_SELF_ACQUIRED
    return SOURCE_UNKNOWN


def has_concrete_quality_sell_evidence(
    sources: Optional[Mapping[str, str]] = None,
    source: Optional[str] = None,
) -> bool:
    """Check if quality sell selection has concrete evidence (manual override or visual observation).

    Default self-acquired and unknown states are derived defaults, not concrete evidence.
    """
    if isinstance(sources, Mapping):
        norm = normalize_quality_sell_selection_sources(sources)
        if any(v in (SOURCE_MANUAL_OVERRIDE, SOURCE_VISUAL_OBSERVED) for v in norm.values()):
            return True
    if isinstance(source, str) and source.strip().lower() in (SOURCE_MANUAL_OVERRIDE, SOURCE_VISUAL_OBSERVED):
        return True
    return False


def merge_quality_sell_selection(
    current_selection: Any,
    current_sources: Any,
    incoming_selection: Any,
    *,
    intent: str = "observe",
    explicit_manual_colors: Tuple[str, ...] = (),
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Merge an incoming selection patch with per-color provenance.

    intent == "observe" (vision / replay / capture / snapshot):
        Colors the user manually overrode keep their current value; every other
        color accepts the incoming observed value.

    intent == "confirm" (manual user edit):
        Only colors whose incoming value differs from the current value, plus
        explicitly declared manual colors, become manual_override.  Untouched
        colors keep their previous provenance and are never relabelled.

    Returns (selection, sources).
    """
    cur = normalize_quality_sell_selection(current_selection) or dict(DEFAULT_UNKNOWN_SELECTION)
    src = normalize_quality_sell_selection_sources(current_sources)
    inc = normalize_quality_sell_selection(incoming_selection)
    if inc is None:
        return cur, src

    manual = set(explicit_manual_colors) | {
        q for q in CANONICAL_QUALITIES if src[q] == SOURCE_MANUAL_OVERRIDE
    }

    out_selection: Dict[str, str] = {}
    out_sources: Dict[str, str] = {}
    for q in CANONICAL_QUALITIES:
        if intent == "observe":
            if q in manual:
                out_selection[q] = cur[q]
                out_sources[q] = SOURCE_MANUAL_OVERRIDE
            else:
                out_selection[q] = inc[q]
                if inc[q] != cur[q] or src[q] == SOURCE_VISUAL_OBSERVED:
                    out_sources[q] = SOURCE_VISUAL_OBSERVED
                else:
                    out_sources[q] = src[q]
        else:
            if inc[q] != cur[q] or q in manual:
                out_selection[q] = inc[q]
                out_sources[q] = SOURCE_MANUAL_OVERRIDE
            else:
                out_selection[q] = cur[q]
                out_sources[q] = src[q]
    return out_selection, out_sources


def apply_single_color_override(
    current_selection: Any,
    current_sources: Any,
    quality: str,
    new_state: str,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """User toggles one color.  Only that color's provenance becomes manual."""
    updated = update_single_quality_sell_selection(current_selection, quality, new_state)
    sources = normalize_quality_sell_selection_sources(current_sources)
    sources[str(quality).strip().lower()] = SOURCE_MANUAL_OVERRIDE
    return updated, sources


def merge_quality_sell_sidecar_bundle(prior_settlement: Any, rec_settlement: Dict[str, Any]) -> None:
    """Merge quality sell selection coupled bundle from prior settlement into rec_settlement.

    Rule: Real visual/user interaction facts > acquisition-derived default selection.
    (qualitySellSelection, qualitySellSelectionSource, qualitySellSelectionSources)
    is treated as an atomic coupled bundle.
    """
    if not isinstance(prior_settlement, Mapping):
        return
    prior_has_qs = any(k in prior_settlement for k in ("qualitySellSelection", "qualitySellSelectionSource", "qualitySellSelectionSources"))
    if not prior_has_qs:
        return

    incoming_has_qs = any(k in rec_settlement for k in ("qualitySellSelection", "qualitySellSelectionSource", "qualitySellSelectionSources"))
    prior_has_evidence = has_concrete_quality_sell_evidence(
        prior_settlement.get("qualitySellSelectionSources"),
        prior_settlement.get("qualitySellSelectionSource"),
    )
    incoming_has_evidence = has_concrete_quality_sell_evidence(
        rec_settlement.get("qualitySellSelectionSources"),
        rec_settlement.get("qualitySellSelectionSource"),
    )

    if (not incoming_has_qs) or (prior_has_evidence and not incoming_has_evidence):
        for k in ("qualitySellSelection", "qualitySellSelectionSource", "qualitySellSelectionSources"):
            if k in prior_settlement:
                rec_settlement[k] = copy.deepcopy(prior_settlement[k])
            elif k in rec_settlement:
                del rec_settlement[k]
    else:
        if "qualitySellSelection" in rec_settlement:
            rec_settlement["qualitySellSelection"] = normalize_quality_sell_selection(rec_settlement["qualitySellSelection"])
            if "qualitySellSelectionSources" in rec_settlement:
                rec_settlement["qualitySellSelectionSources"] = normalize_quality_sell_selection_sources(rec_settlement["qualitySellSelectionSources"])
            else:
                rec_settlement["qualitySellSelectionSources"] = sources_from_aggregate(rec_settlement.get("qualitySellSelectionSource"))
            rec_settlement["qualitySellSelectionSource"] = aggregate_selection_source(rec_settlement["qualitySellSelectionSources"])


def detect_quality_sell_selection_from_frame(frame: Optional[np.ndarray]) -> Optional[Dict[str, str]]:
    """Detect quality sell selection control states directly from a game frame.
    
    Examines the 6 bottom quality circles below the settlement warehouse grid.
    If the circles are visible, checks for the presence of the magenta/pink selection ring.
    Returns normalized {quality: 'selected' | 'unselected'} or None if not detected.
    """
    if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
        return None
    try:
        from settlement_grid import settlement_grid_bounds
        gx1, gy1, gx2, gy2 = settlement_grid_bounds(frame)
        grid_w = gx2 - gx1
        grid_h = gy2 - gy1
        if grid_w < 50 or grid_h < 50:
            return None

        # Normalized relative X centers of the 6 colors relative to grid width
        rel_x = [
            ("white", 0.081),
            ("green", 0.251),
            ("blue", 0.422),
            ("purple", 0.588),
            ("gold", 0.758),
            ("red", 0.929),
        ]
        rel_y = 0.052
        r_inner = round(0.021 * grid_w)
        r_outer = round(0.035 * grid_w)

        bar_y = gy2 + round(rel_y * grid_h)
        if bar_y + r_outer >= frame.shape[0]:
            return None

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        results: Dict[str, str] = {}
        detected_valid = 0

        for name, rx in rel_x:
            cx = gx1 + round(rx * grid_w)
            cy = bar_y

            # Check if inner circle has meaningful color (not pitch black background)
            if 0 <= cy < frame.shape[0] and 0 <= cx < frame.shape[1]:
                b, g, r = frame[cy, cx]
                if max(r, g, b) > 50:
                    detected_valid += 1

            # Count magenta/pink ring pixels in the ring zone [r_inner*1.15, r_outer*1.25]
            pink_count = 0
            search_r = round(r_outer * 1.25)
            for dy in range(-search_r, search_r + 1):
                for dx in range(-search_r, search_r + 1):
                    dist = np.hypot(dx, dy)
                    if r_inner * 1.15 <= dist <= r_outer * 1.25:
                        y, x = cy + dy, cx + dx
                        if 0 <= y < frame.shape[0] and 0 <= x < frame.shape[1]:
                            h, s, v = hsv[y, x]
                            b, g, r = frame[y, x]
                            # Magenta / pink ring characteristic
                            if r > 150 and b > 110 and g < 115 and s > 65:
                                pink_count += 1
            threshold = max(5, int(r_outer * 0.8))
            results[name] = SELECTION_SELECTED if pink_count >= threshold else SELECTION_UNSELECTED

        # Require at least 4 circles to have valid circle centers detected to confirm settlement bar presence
        if detected_valid < 4:
            return None

        return results
    except Exception:
        return None
