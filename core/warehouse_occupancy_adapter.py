# -*- coding: utf-8 -*-
"""Deterministic fail-closed adapter for Settlement Warehouse Occupancy (Phase 12).

Transforms cross-viewport physical tracks from review packets into canonical
settlement.warehouseOccupancy facts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "settlement-warehouse-occupancy.v1"
EVIDENCE_LEVEL = "OUTLINE_ONLY"
IDENTITY_STATUS = "unresolved"

FORBIDDEN_TRACK_KEYS = frozenset({
    "identifiedName",
    "candidates",
    "selectedCatalogId",
    "bbox",
    "observations",
    "segments",
    "coverage",
    "coverageStatus",
    "warehouseCoverage",
    "warnings",
    "diagnostics",
    "review",
    "price",
    "valuation",
})

ALLOWED_TRACK_KEYS = frozenset({
    "trackId",
    "geometryStatus",
    "width",
    "height",
    "evidenceLevel",
    "identityStatus",
})


def _as_positive_int(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int) and val > 0:
        return val
    if isinstance(val, float) and val.is_integer() and int(val) > 0:
        return int(val)
    try:
        n = int(val)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _extract_unique_int_candidate(values: Any) -> Optional[int]:
    """Extract a single unique positive integer if exactly one exists."""
    if values is None:
        return None
    if isinstance(values, (int, float)) and not isinstance(values, bool):
        return _as_positive_int(values)
    if isinstance(values, (list, tuple, set)):
        ints: List[int] = []
        for v in values:
            n = _as_positive_int(v)
            if n is not None and n not in ints:
                ints.append(n)
        if len(ints) == 1:
            return ints[0]
    return None


def _has_multiple_candidates(values: Any) -> bool:
    """Return True if multiple distinct integer candidates exist."""
    if isinstance(values, (list, tuple, set)):
        ints: List[int] = []
        for v in values:
            n = _as_positive_int(v)
            if n is not None and n not in ints:
                ints.append(n)
        return len(ints) > 1
    return False


def adapt_track_to_occupancy_track(raw_track: Any) -> Optional[Dict[str, Any]]:
    """Adapt a single review packet / physical track into a minimal occupancy track.

    Fail-closed:
    - Missing or invalid trackId -> None (track skipped)
    - PIXEL_ONLY / CONFLICT / unanchored / no geometry -> UNKNOWN, width=null, height=null
    - EXACT + unique width + unique height -> RESOLVED, width=int, height=int
    - Any multiple candidate or non-EXACT geometry evidence -> AMBIGUOUS, width=null, height=null
    - No forbidden fields, identityStatus always 'unresolved', evidenceLevel always 'OUTLINE_ONLY'
    """
    if not isinstance(raw_track, Mapping):
        return None

    raw_id = (
        raw_track.get("trackId")
        or raw_track.get("reviewUnitId")
        or raw_track.get("unitId")
        or raw_track.get("physicalId")
    )
    if raw_id is None or isinstance(raw_id, bool):
        return None
    track_id = str(raw_id).strip()
    if not track_id:
        return None

    status = str(raw_track.get("status") or "").strip().upper()
    placement_status = str(raw_track.get("placementStatus") or "").strip().upper()
    geom_ev = str(
        raw_track.get("geometryEvidenceStatus")
        or raw_track.get("geometryStatus")
        or ""
    ).strip().upper()
    reasons = {str(r).upper() for r in (raw_track.get("reasons") or [])}

    pixel_only = (
        bool(raw_track.get("pixelOnly"))
        or geom_ev == "PIXEL_ONLY"
        or "PIXEL_ONLY" in reasons
    )
    is_conflict = (
        status == "CONFLICT"
        or geom_ev == "CONFLICT"
        or "CONFLICT" in reasons
    )

    width_cands = raw_track.get("widthCandidates")
    if width_cands is None and raw_track.get("width") is not None:
        width_cands = raw_track.get("width")
    if width_cands is None and isinstance(raw_track.get("footprint"), Mapping):
        width_cands = raw_track["footprint"].get("widthCells")
    if width_cands is None and isinstance(raw_track.get("grid"), Mapping):
        width_cands = raw_track["grid"].get("w")

    height_cands = raw_track.get("heightCandidates")
    if height_cands is None and raw_track.get("height") is not None:
        height_cands = raw_track.get("height")
    if height_cands is None and isinstance(raw_track.get("footprint"), Mapping):
        height_cands = raw_track["footprint"].get("heightCells")
    if height_cands is None and isinstance(raw_track.get("grid"), Mapping):
        height_cands = raw_track["grid"].get("h")

    w_unique = _extract_unique_int_candidate(width_cands)
    h_unique = _extract_unique_int_candidate(height_cands)
    w_multiple = _has_multiple_candidates(width_cands)
    h_multiple = _has_multiple_candidates(height_cands)

    has_any_geom_evidence = (
        w_unique is not None
        or h_unique is not None
        or w_multiple
        or h_multiple
        or geom_ev in ("EXACT", "COMPATIBLE", "COMPATIBLE_ONLY", "AMBIGUOUS")
        or placement_status in ("RESOLVED", "AMBIGUOUS_REGION")
    )

    if pixel_only or is_conflict or not has_any_geom_evidence:
        geometry_status = "UNKNOWN"
        width = None
        height = None
    elif placement_status == "RESOLVED" and w_unique is not None and h_unique is not None:
        geometry_status = "RESOLVED"
        width = w_unique
        height = h_unique
    elif placement_status == "AMBIGUOUS_REGION":
        geometry_status = "AMBIGUOUS"
        width = None
        height = None
    elif geom_ev == "EXACT":
        if w_unique is not None and h_unique is not None and not w_multiple and not h_multiple:
            geometry_status = "RESOLVED"
            width = w_unique
            height = h_unique
        else:
            geometry_status = "AMBIGUOUS"
            width = None
            height = None
    elif w_multiple or h_multiple or has_any_geom_evidence:
        geometry_status = "AMBIGUOUS"
        width = None
        height = None
    else:
        geometry_status = "UNKNOWN"
        width = None
        height = None

    return {
        "trackId": track_id,
        "geometryStatus": geometry_status,
        "width": width,
        "height": height,
        "evidenceLevel": EVIDENCE_LEVEL,
        "identityStatus": IDENTITY_STATUS,
    }


def adapt_review_packet_to_warehouse_occupancy(
    packet_or_tracks: Any,
) -> Optional[Dict[str, Any]]:
    """Adapt review packet or raw tracks list to settlement.warehouseOccupancy.

    Returns None if packet_or_tracks is empty, invalid, or yields zero tracks (fail-closed).
    """
    if packet_or_tracks is None:
        return None

    raw_tracks = None
    if isinstance(packet_or_tracks, Mapping):
        raw_tracks = packet_or_tracks.get("tracks")
        if raw_tracks is None:
            raw_tracks = packet_or_tracks.get("reviewUnits")
    elif isinstance(packet_or_tracks, (list, tuple)):
        raw_tracks = packet_or_tracks

    if not isinstance(raw_tracks, (list, tuple)):
        return None

    tracks: List[Dict[str, Any]] = []
    for raw in raw_tracks:
        adapted = adapt_track_to_occupancy_track(raw)
        if adapted is not None:
            tracks.append(adapted)

    if not tracks:
        return None

    return {
        "schemaVersion": SCHEMA_VERSION,
        "tracks": tracks,
    }


def validate_warehouse_occupancy(occupancy: Any) -> Tuple[bool, List[str]]:
    """Validate that an occupancy structure conforms to settlement-warehouse-occupancy.v1."""
    reasons: List[str] = []
    if not isinstance(occupancy, Mapping):
        return False, ["NOT_A_DICT"]

    if occupancy.get("schemaVersion") != SCHEMA_VERSION:
        reasons.append("INVALID_SCHEMA_VERSION")

    tracks = occupancy.get("tracks")
    if not isinstance(tracks, list):
        reasons.append("TRACKS_NOT_A_LIST")
        return False, reasons

    for idx, t in enumerate(tracks):
        if not isinstance(t, Mapping):
            reasons.append(f"TRACK_{idx}_NOT_A_DICT")
            continue

        for k in t.keys():
            if k in FORBIDDEN_TRACK_KEYS or k not in ALLOWED_TRACK_KEYS:
                reasons.append(f"TRACK_{idx}_FORBIDDEN_OR_EXTRA_KEY_{k.upper()}")

        for req_k in ("trackId", "geometryStatus", "width", "height", "evidenceLevel", "identityStatus"):
            if req_k not in t:
                reasons.append(f"TRACK_{idx}_MISSING_{req_k.upper()}")

        tid = t.get("trackId")
        if not isinstance(tid, str) or not tid.strip():
            reasons.append(f"TRACK_{idx}_INVALID_TRACK_ID")

        geom = t.get("geometryStatus")
        if geom not in ("RESOLVED", "AMBIGUOUS", "UNKNOWN"):
            reasons.append(f"TRACK_{idx}_INVALID_GEOMETRY_STATUS")
        elif geom == "RESOLVED":
            w = t.get("width")
            h = t.get("height")
            if not isinstance(w, int) or isinstance(w, bool) or w <= 0:
                reasons.append(f"TRACK_{idx}_RESOLVED_WIDTH_NOT_POSITIVE_INT")
            if not isinstance(h, int) or isinstance(h, bool) or h <= 0:
                reasons.append(f"TRACK_{idx}_RESOLVED_HEIGHT_NOT_POSITIVE_INT")
        else:
            if t.get("width") is not None or t.get("height") is not None:
                reasons.append(f"TRACK_{idx}_UNRESOLVED_GEOMETRY_MUST_HAVE_NULL_DIMS")

        if t.get("evidenceLevel") != EVIDENCE_LEVEL:
            reasons.append(f"TRACK_{idx}_INVALID_EVIDENCE_LEVEL")

        if t.get("identityStatus") != IDENTITY_STATUS:
            reasons.append(f"TRACK_{idx}_INVALID_IDENTITY_STATUS")

    return len(reasons) == 0, reasons
