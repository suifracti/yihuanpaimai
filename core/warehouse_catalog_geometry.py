"""Geometry-only catalog candidate sets for physical warehouse tracks.

Uses structured Width/Height/Cells/Shape from the project catalog. Does not
read Quality, price, files, or names for matching. Candidates are never
identities. Catalog completeness is not assumed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "warehouse-catalog-geometry.v1"
CATALOG_RELATIVE_PATH = Path("assets") / "catalog_065.json"


def application_asset_root() -> Path:
    """Source repo root, or the PyInstaller resource root when frozen."""
    frozen_root = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[1]


def default_catalog_path() -> Path:
    return application_asset_root() / CATALOG_RELATIVE_PATH


SHAPE_GRID = 5

STATUS_UNKNOWN = "UNKNOWN"
STATUS_OUT_OF_CATALOG = "OUT_OF_CATALOG"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_SINGLE_UNVERIFIED = "SINGLE_CANDIDATE_UNVERIFIED"
STATUS_UNIQUE = "UNIQUE_IN_CATALOG"

COVERAGE_VERIFIED = "VERIFIED_COMPLETE"
COVERAGE_UNVERIFIED = "UNVERIFIED"
COVERAGE_PARTIAL = "PARTIAL"

GEOM_EXACT = "EXACT"
GEOM_COMPATIBLE = "COMPATIBLE_ONLY"
GEOM_PIXEL = "PIXEL_ONLY"
GEOM_UNKNOWN = "UNKNOWN"

IDENTITY_CANDIDATE = "CANDIDATE_ONLY"

RESULT_KEYS = (
    "schemaVersion",
    "status",
    "catalogCoverageStatus",
    "geometryEvidenceStatus",
    "candidateCount",
    "candidates",
    "isolation",
)

CANDIDATE_KEYS = (
    "catalogId",
    "name",
    "identityStatus",
    "geometry",
    "matchReasons",
)


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _trim_mask(grid: Sequence[Sequence[int]]) -> Tuple[Tuple[int, ...], ...]:
    rows = [index for index, row in enumerate(grid) if any(row)]
    cols = [index for index in range(len(grid[0])) if any(row[index] for row in grid)]
    if not rows or not cols:
        return tuple()
    return tuple(
        tuple(int(grid[row][col]) for col in range(cols[0], cols[-1] + 1))
        for row in range(rows[0], rows[-1] + 1)
    )


def parse_catalog_shape(shape: Any) -> Optional[Tuple[Tuple[int, ...], ...]]:
    if not isinstance(shape, str) or len(shape) != SHAPE_GRID * SHAPE_GRID:
        return None
    if set(shape) - set("01"):
        return None
    grid = tuple(
        tuple(int(shape[row * SHAPE_GRID + col]) for col in range(SHAPE_GRID))
        for row in range(SHAPE_GRID)
    )
    trimmed = _trim_mask(grid)
    return trimmed or None


def normalize_cell_mask(mask: Any) -> Optional[Tuple[Tuple[int, ...], ...]]:
    if not isinstance(mask, list) or not mask:
        return None
    rows: List[Tuple[int, ...]] = []
    width = None
    for row in mask:
        if not isinstance(row, (list, tuple)) or not row:
            return None
        cells = tuple(1 if int(cell) else 0 for cell in row)
        if width is None:
            width = len(cells)
        elif len(cells) != width:
            return None
        rows.append(cells)
    return tuple(rows)


def _mask_ones(mask: Tuple[Tuple[int, ...], ...]) -> int:
    return sum(sum(row) for row in mask)


def _window_equal(
    catalog_mask: Tuple[Tuple[int, ...], ...],
    observed: Tuple[Tuple[int, ...], ...],
    start: int,
) -> bool:
    height = len(observed)
    if start < 0 or start + height > len(catalog_mask):
        return False
    if len(catalog_mask[0]) != len(observed[0]):
        return False
    return catalog_mask[start : start + height] == observed


class CatalogGeometryIndex:
    def __init__(
        self,
        records: Optional[Sequence[Mapping[str, Any]]] = None,
        *,
        catalog_path: Optional[Path] = None,
        catalog_coverage_status: str = COVERAGE_UNVERIFIED,
    ):
        if catalog_coverage_status not in {COVERAGE_VERIFIED, COVERAGE_UNVERIFIED, COVERAGE_PARTIAL}:
            raise ValueError("invalid catalogCoverageStatus")
        self.catalog_coverage_status = catalog_coverage_status
        raw = list(records) if records is not None else _load_catalog(catalog_path)
        self._indexed: List[Dict[str, Any]] = []
        self._isolated: List[Dict[str, Any]] = []
        self._by_mask: Dict[Tuple[Tuple[int, ...], ...], List[str]] = {}
        self._by_whc: Dict[Tuple[int, int, int], List[str]] = {}
        seen_ids: Dict[str, int] = {}
        for item in raw:
            catalog_id = str(item.get("Id") or "").strip()
            reasons = _geometry_faults(item)
            if catalog_id:
                seen_ids[catalog_id] = seen_ids.get(catalog_id, 0) + 1
            if not catalog_id:
                reasons.append("MISSING_ID")
            if reasons:
                self._isolated.append({
                    "catalogId": catalog_id or None,
                    "reasons": list(reasons),
                })
                continue
            mask = parse_catalog_shape(item.get("Shape"))
            assert mask is not None
            record = {
                "catalogId": catalog_id,
                "name": str(item.get("Name") or ""),
                "width": int(item["Width"]),
                "height": int(item["Height"]),
                "cells": int(item["Cells"]),
                "shape": str(item["Shape"]),
                "mask": mask,
            }
            self._indexed.append(record)
            self._by_mask.setdefault(mask, []).append(catalog_id)
            self._by_whc.setdefault((record["width"], record["height"], record["cells"]), []).append(catalog_id)
        self._duplicate_ids = sorted(key for key, count in seen_ids.items() if count > 1)
        self._indexed.sort(key=lambda item: item["catalogId"])
        for key in self._by_mask:
            self._by_mask[key] = sorted(set(self._by_mask[key]))
        for key in self._by_whc:
            self._by_whc[key] = sorted(set(self._by_whc[key]))
        self._by_id = {item["catalogId"]: item for item in self._indexed}

    def isolation_report(self) -> Dict[str, Any]:
        return {
            "indexedCount": len(self._indexed),
            "isolatedCount": len(self._isolated),
            "isolated": [dict(item) for item in self._isolated],
            "duplicateIds": list(self._duplicate_ids),
            "uniqueExactMasks": len(self._by_mask),
        }

    def resolve(self, track: Mapping[str, Any]) -> Dict[str, Any]:
        evidence = _geometry_evidence(track)
        if evidence == GEOM_PIXEL or evidence == GEOM_UNKNOWN:
            return self._result(STATUS_UNKNOWN, evidence, [])
        observed = _track_mask(track)
        width = _unique_int(track.get("widthCandidates"))
        height = _unique_int(track.get("heightCandidates"))
        span = _unique_int(track.get("spanCandidates"))
        clipped = bool(track.get("clipped"))
        if evidence == GEOM_EXACT:
            matches = self._exact(observed, width, height, span)
            return self._decide_exact(matches)
        matches = self._compatible(observed, width, height, span, clipped, track)
        return self._result(
            STATUS_AMBIGUOUS if matches else STATUS_UNKNOWN,
            GEOM_COMPATIBLE,
            matches,
        )

    def _exact(
        self,
        mask: Optional[Tuple[Tuple[int, ...], ...]],
        width: Optional[int],
        height: Optional[int],
        span: Optional[int],
    ) -> List[Dict[str, Any]]:
        if mask is None:
            return []
        ids = self._by_mask.get(mask, [])
        matches: List[Dict[str, Any]] = []
        for catalog_id in ids:
            record = self._by_id[catalog_id]
            if width is not None and record["width"] != width:
                continue
            if height is not None and record["height"] != height:
                continue
            if span is not None and record["cells"] != span:
                continue
            matches.append(self._candidate(record, ["EXACT_CELL_MASK", "WIDTH_HEIGHT_CELLS"]))
        return matches

    def _compatible(
        self,
        mask: Optional[Tuple[Tuple[int, ...], ...]],
        width: Optional[int],
        height: Optional[int],
        span: Optional[int],
        clipped: bool,
        track: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        clipped_top = _any_flag(track, "clippedTop")
        clipped_bottom = _any_flag(track, "clippedBottom")
        matches: List[Dict[str, Any]] = []
        for record in self._indexed:
            reasons: List[str] = []
            if width is not None and record["width"] != width:
                continue
            if height is not None:
                if clipped and (clipped_top or clipped_bottom):
                    if record["height"] < height:
                        continue
                    reasons.append("HEIGHT_AT_LEAST_VISIBLE")
                elif record["height"] != height:
                    continue
                else:
                    reasons.append("HEIGHT_EQUAL")
            if span is not None:
                if clipped:
                    if record["cells"] < span:
                        continue
                    reasons.append("CELLS_AT_LEAST_VISIBLE")
                elif record["cells"] != span:
                    continue
                else:
                    reasons.append("CELLS_EQUAL")
            if mask is not None:
                if not _compatible_mask(record["mask"], mask, clipped_top, clipped_bottom, clipped):
                    continue
                reasons.append("VISIBLE_MASK_COMPATIBLE")
            elif width is None and height is None and span is None:
                continue
            if width is not None:
                reasons.append("WIDTH_EQUAL")
            matches.append(self._candidate(record, reasons or ["COMPATIBLE_GEOMETRY"]))
        return matches

    def _decide_exact(self, matches: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not matches:
            if self.catalog_coverage_status == COVERAGE_VERIFIED:
                return self._result(STATUS_OUT_OF_CATALOG, GEOM_EXACT, [])
            return self._result(STATUS_UNKNOWN, GEOM_EXACT, [])
        if len(matches) == 1:
            if self.catalog_coverage_status == COVERAGE_VERIFIED:
                return self._result(STATUS_UNIQUE, GEOM_EXACT, matches)
            return self._result(STATUS_SINGLE_UNVERIFIED, GEOM_EXACT, matches)
        return self._result(STATUS_AMBIGUOUS, GEOM_EXACT, matches)

    def _candidate(self, record: Mapping[str, Any], reasons: Sequence[str]) -> Dict[str, Any]:
        return {
            "catalogId": record["catalogId"],
            "name": record["name"],
            "identityStatus": IDENTITY_CANDIDATE,
            "geometry": {
                "width": record["width"],
                "height": record["height"],
                "cells": record["cells"],
                "shape": record["shape"],
            },
            "matchReasons": list(reasons),
        }

    def _result(
        self,
        status: str,
        evidence: str,
        matches: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        ordered = sorted(matches, key=lambda item: str(item["catalogId"]))
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "status": status,
            "catalogCoverageStatus": self.catalog_coverage_status,
            "geometryEvidenceStatus": evidence,
            "candidateCount": len(ordered),
            "candidates": [dict(item) for item in ordered],
            "isolation": {
                "isolatedCount": len(self._isolated),
                "indexedCount": len(self._indexed),
            },
        }
        extra = set(payload) - set(RESULT_KEYS)
        for key in extra:
            payload.pop(key, None)
        return payload


def _load_catalog(path: Optional[Path]) -> List[Mapping[str, Any]]:
    source = Path(path) if path is not None else default_catalog_path()
    document = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(document, list):
        raise ValueError("catalog must be a list")
    return [item for item in document if isinstance(item, Mapping)]


def _geometry_faults(item: Mapping[str, Any]) -> List[str]:
    reasons: List[str] = []
    width = _as_int(item.get("Width"))
    height = _as_int(item.get("Height"))
    cells = _as_int(item.get("Cells"))
    shape = item.get("Shape")
    if width is None or width < 1:
        reasons.append("INVALID_WIDTH")
    if height is None or height < 1:
        reasons.append("INVALID_HEIGHT")
    if cells is None or cells < 1:
        reasons.append("INVALID_CELLS")
    mask = parse_catalog_shape(shape)
    if mask is None:
        reasons.append("INVALID_SHAPE")
        return reasons
    if width is not None and height is not None and cells is not None:
        if _mask_ones(mask) != cells:
            reasons.append("SHAPE_ONES_NE_CELLS")
        if mask and (len(mask[0]), len(mask)) != (width, height):
            reasons.append("SHAPE_BBOX_NE_WIDTH_HEIGHT")
    return reasons


def _unique_int(values: Any) -> Optional[int]:
    if not isinstance(values, list):
        return None
    ints = []
    for value in values:
        number = _as_int(value)
        if number is not None and number not in ints:
            ints.append(number)
    if len(ints) == 1:
        return ints[0]
    return None


def _track_mask(track: Mapping[str, Any]) -> Optional[Tuple[Tuple[int, ...], ...]]:
    masks = []
    for item in track.get("globalCellMaskCandidates") or []:
        if isinstance(item, Mapping):
            parsed = normalize_cell_mask(item.get("cellMask"))
            if parsed is not None and parsed not in masks:
                masks.append(parsed)
    if len(masks) == 1:
        return masks[0]
    return None


def _any_flag(track: Mapping[str, Any], key: str) -> bool:
    if track.get(key):
        return True
    for obs in track.get("observations") or []:
        if isinstance(obs, Mapping) and obs.get(key):
            return True
    return False


def _geometry_evidence(track: Mapping[str, Any]) -> str:
    reasons = {str(item) for item in (track.get("reasons") or [])}
    if "PIXEL_ONLY" in reasons:
        return GEOM_PIXEL
    if str(track.get("status") or "") == "CONFLICT":
        return GEOM_UNKNOWN
    clipped = bool(track.get("clipped"))
    anchored = "UNANCHORED" not in reasons
    mask = _track_mask(track)
    width = _unique_int(track.get("widthCandidates"))
    height = _unique_int(track.get("heightCandidates"))
    if mask is None and width is None and height is None:
        return GEOM_UNKNOWN
    exact = (
        not clipped
        and anchored
        and mask is not None
        and width is not None
        and height is not None
        and str(track.get("status") or "") == "OBSERVED"
    )
    if exact:
        return GEOM_EXACT
    if mask is not None or width is not None or height is not None:
        return GEOM_COMPATIBLE
    return GEOM_UNKNOWN


def _compatible_mask(
    catalog_mask: Tuple[Tuple[int, ...], ...],
    observed: Tuple[Tuple[int, ...], ...],
    clipped_top: bool,
    clipped_bottom: bool,
    clipped: bool,
) -> bool:
    if not catalog_mask or not observed:
        return False
    if len(catalog_mask[0]) != len(observed[0]):
        return False
    if len(catalog_mask) < len(observed):
        return False
    if not clipped and not clipped_top and not clipped_bottom:
        return catalog_mask == observed
    if clipped_top and not clipped_bottom:
        return _window_equal(catalog_mask, observed, len(catalog_mask) - len(observed))
    if clipped_bottom and not clipped_top:
        return _window_equal(catalog_mask, observed, 0)
    for start in range(0, len(catalog_mask) - len(observed) + 1):
        if _window_equal(catalog_mask, observed, start):
            return True
    return False


def resolve_catalog_candidates(
    track: Mapping[str, Any],
    *,
    index: Optional[CatalogGeometryIndex] = None,
) -> Dict[str, Any]:
    resolver = index or CatalogGeometryIndex()
    return resolver.resolve(track)
