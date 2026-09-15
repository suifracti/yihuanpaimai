# -*- coding: utf-8 -*-
"""Shared Item Identity Resolver for warehouse and settlement observations.

Phase 19 Contract:
- Pure metadata resolver: dimensions (w, h) + optional rarity -> candidates.
- Zero screen capture, zero OCR, zero scroll, zero network, zero AI.
- Deterministic catalogId ordering.
- Dimension-only compatibility when rarity is unknown or missing.
- Monotonic candidate shrinkage (old ∩ new); no unjustified expansion.
- EXACT monotonicity: existing EXACT is never downgraded to CANDIDATE.
- UNIQUE != EXACT: even if candidates == [A], identityStatus remains CANDIDATE and identifiedName is None.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

RARITY_CN_TO_CANONICAL: Dict[str, str] = {
    "白": "white",
    "灰": "white",
    "绿": "green",
    "蓝": "blue",
    "紫": "purple",
    "金": "gold",
    "红": "red",
}


def _asset_root() -> Path:
    frozen_root = getattr(os.sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[1]


def default_catalog_path() -> Path:
    direct = _asset_root() / "assets" / "catalog_065.json"
    if direct.is_file():
        return direct
    fallback = Path(__file__).resolve().parents[1] / "assets" / "catalog_065.json"
    return fallback


@dataclass(frozen=True)
class IdentityResolution:
    identity_status: str  # "UNKNOWN" | "CANDIDATE" | "EXACT"
    candidates: Tuple[Dict[str, Any], ...]
    identified_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identityStatus": self.identity_status,
            "candidates": [
                {
                    "catalogId": str(c.get("catalogId") or c.get("Id") or ""),
                    "name": str(c.get("name") or c.get("Name") or ""),
                }
                for c in self.candidates
            ],
            "identifiedName": self.identified_name,
        }


class ItemIdentityResolver:
    def __init__(self, catalog_path: Optional[Union[str, Path]] = None):
        path = Path(catalog_path).resolve() if catalog_path else default_catalog_path()
        self.catalog_path = path
        self.catalog_items: List[Dict[str, Any]] = []
        self._by_shape_rarity: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._by_shape_all: Dict[str, List[Dict[str, Any]]] = {}
        self._load_catalog(path)

    def _load_catalog(self, path: Path) -> None:
        if not path.is_file():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return

        if not isinstance(raw, list):
            return

        for item in raw:
            if not isinstance(item, dict):
                continue
            cat_id = str(item.get("Id") or item.get("catalogId") or "").strip()
            name = str(item.get("Name") or item.get("name") or "").strip()
            cn_qual = str(item.get("Quality") or item.get("quality") or "").strip()
            rarity = RARITY_CN_TO_CANONICAL.get(cn_qual, cn_qual.lower() if cn_qual else "unknown")
            w = int(item.get("Width") or item.get("width") or 0)
            h = int(item.get("Height") or item.get("height") or 0)
            cells = int(item.get("Cells") or item.get("cells") or (w * h))
            val = int(item.get("Value") or item.get("value") or 0)
            shape = str(item.get("Shape") or item.get("shape") or "")

            entry: Dict[str, Any] = {
                "catalogId": cat_id,
                "name": name,
                "quality": cn_qual,
                "rarity": rarity,
                "width": w,
                "height": h,
                "cells": cells,
                "value": val,
                "shape": shape,
                "file": str(item.get("File") or item.get("file") or "").strip(),
                "liveFiles": list(item.get("LiveFiles") or item.get("liveFiles") or []),
                # Legacy uppercase aliases for compatibility with old matchers
                "Id": cat_id,
                "Name": name,
                "Quality": cn_qual,
                "Width": w,
                "Height": h,
                "Value": val,
                "File": str(item.get("File") or item.get("file") or "").strip(),
            }
            self.catalog_items.append(entry)

            sz1 = f"{w}x{h}"
            sz2 = f"{h}x{w}"
            for sz in (sz1, sz2):
                self._by_shape_all.setdefault(sz, []).append(entry)
                self._by_shape_rarity.setdefault((sz, rarity), []).append(entry)

    def resolve_candidates(
        self,
        width: int,
        height: int,
        rarity: Optional[str] = None,
        shape: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Filter catalog candidates by dimensions and optional rarity deterministically."""
        w_val = int(width or 1)
        h_val = int(height or 1)
        shape_str = str(shape or f"{w_val}x{h_val}").strip().lower()
        rev_shape = f"{h_val}x{w_val}"

        raw_rarity = str(rarity or "unknown").strip().lower()
        canon_rarity = RARITY_CN_TO_CANONICAL.get(raw_rarity, raw_rarity)

        matched: List[Dict[str, Any]] = []
        if canon_rarity in RARITY_CN_TO_CANONICAL.values():
            # Rarity is known: search by shape + rarity
            matched.extend(self._by_shape_rarity.get((shape_str, canon_rarity), []))
            if shape_str != rev_shape:
                matched.extend(self._by_shape_rarity.get((rev_shape, canon_rarity), []))
        else:
            # Rarity unknown or missing: dimension-only search (SilhouetteCandidates)
            matched.extend(self._by_shape_all.get(shape_str, []))
            if shape_str != rev_shape:
                matched.extend(self._by_shape_all.get(rev_shape, []))

        # Deduplicate and sort deterministically by catalogId
        dedup_map: Dict[str, Dict[str, Any]] = {}
        for it in matched:
            cid = it["catalogId"]
            if cid not in dedup_map:
                dedup_map[cid] = it

        return [dedup_map[cid] for cid in sorted(dedup_map.keys())]

    def resolve_item_identity(
        self,
        observation: Mapping[str, Any],
    ) -> IdentityResolution:
        """Resolve item identity from observation metadata.
        
        Strict Phase 19 Rules:
        - Candidates: filtered by dimension and optional rarity.
        - If candidates exist: identityStatus is CANDIDATE, identifiedName is None.
          NEVER upgrades to EXACT, even if len(candidates) == 1.
        - If no candidates: identityStatus is UNKNOWN, identifiedName is None.
        """
        w = int(
            observation.get("width")
            or observation.get("width_cells")
            or observation.get("widthCells")
            or observation.get("w")
            or 1
        )
        h = int(
            observation.get("height")
            or observation.get("height_cells")
            or observation.get("heightCells")
            or observation.get("h")
            or 1
        )
        rarity = (
            observation.get("rarity")
            or observation.get("quality")
            or observation.get("rarityObservation")
            or observation.get("qualityObservation")
        )
        shape = observation.get("shape") or observation.get("gridShape")

        candidates = self.resolve_candidates(w, h, rarity, shape)
        if candidates:
            return IdentityResolution(
                identity_status="CANDIDATE",
                candidates=tuple(candidates),
                identified_name=None,
            )
        return IdentityResolution(
            identity_status="UNKNOWN",
            candidates=(),
            identified_name=None,
        )


_GLOBAL_RESOLVER: Optional[ItemIdentityResolver] = None


def get_global_item_identity_resolver(
    catalog_path: Optional[Union[str, Path]] = None,
) -> ItemIdentityResolver:
    global _GLOBAL_RESOLVER
    if _GLOBAL_RESOLVER is None or (catalog_path and Path(catalog_path).resolve() != _GLOBAL_RESOLVER.catalog_path):
        _GLOBAL_RESOLVER = ItemIdentityResolver(catalog_path=catalog_path)
    return _GLOBAL_RESOLVER


def resolve_item_identity(
    observation: Mapping[str, Any],
    catalog_path: Optional[Union[str, Path]] = None,
) -> IdentityResolution:
    """Convenience pure entrypoint for resolving item identity."""
    resolver = get_global_item_identity_resolver(catalog_path=catalog_path)
    return resolver.resolve_item_identity(observation)


def merge_candidates(
    old_candidates: Sequence[Mapping[str, Any]],
    new_candidates: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Monotonically shrink candidates via intersection: old ∩ new.
    
    If old is empty, returns new. If new has matches in old, returns the intersection
    ordered deterministically by catalogId. If intersection is empty, retains old.
    """
    if not old_candidates:
        return list(new_candidates)
    if not new_candidates:
        return list(old_candidates)

    old_ids = {
        str(c.get("catalogId") or c.get("Id") or "")
        for c in old_candidates
        if isinstance(c, Mapping)
    }
    intersected = [
        dict(c)
        for c in new_candidates
        if str(c.get("catalogId") or c.get("Id") or "") in old_ids
    ]
    if not intersected:
        return list(old_candidates)
    return sorted(intersected, key=lambda x: str(x.get("catalogId") or x.get("Id") or ""))


def merge_slot_identity(
    old_slot: Optional[Mapping[str, Any]],
    new_resolution: IdentityResolution,
    reset: bool = False,
) -> Dict[str, Any]:
    """Merge new identity resolution into slot monotonically.
    
    Rules:
    - If reset is True: resets candidates to new_resolution.
    - If old_slot is EXACT: retains EXACT status and identifiedName (EXACT monotonicity).
    - If old_slot had candidates: shrinks via intersection (old ∩ new), preventing expansion.
    - UNIQUE != EXACT: identityStatus is always CANDIDATE when candidates are present.
    """
    new_dict = new_resolution.to_dict()
    if reset or not old_slot:
        return new_dict

    old_status = old_slot.get("identityStatus")
    if old_status == "EXACT":
        return {
            "identityStatus": "EXACT",
            "candidates": list(old_slot.get("candidates") or []),
            "identifiedName": old_slot.get("identifiedName"),
        }

    old_cands = list(old_slot.get("candidates") or [])
    if not old_cands:
        return new_dict

    old_ids = {
        str(c.get("catalogId") or c.get("Id") or "")
        for c in old_cands
        if isinstance(c, Mapping)
    }
    new_cands = new_dict.get("candidates") or []
    intersected = [c for c in new_cands if c.get("catalogId") in old_ids]

    if not intersected:
        # Avoid total loss on transient conflict; preserve existing candidates
        intersected = old_cands

    intersected_sorted = sorted(intersected, key=lambda x: str(x.get("catalogId") or ""))
    return {
        "identityStatus": "CANDIDATE" if intersected_sorted else "UNKNOWN",
        "candidates": intersected_sorted,
        "identifiedName": None,
    }
