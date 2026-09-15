"""0.6 业务闭集：venue / box / fieldCondition / toolGroup 的唯一 Python 入口。"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

UNKNOWN_VENUE = "未知场地"
UNKNOWN_BOX = "未知箱型"
UNKNOWN_FIELD = "unknown"

_SOT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "business_sot_v06.json"))


@lru_cache(maxsize=1)
def load_sot() -> Dict[str, Any]:
    with open(_SOT_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def sot_path() -> str:
    return _SOT_PATH


def _compact(text: Optional[str]) -> str:
    return "".join((text or "").split())


def venues() -> List[Dict[str, Any]]:
    return list(load_sot().get("venues") or [])


def field_conditions() -> List[Dict[str, Any]]:
    return list(load_sot().get("fieldConditions") or [])


def boxes_by_venue() -> Dict[str, List[str]]:
    return dict(load_sot().get("boxesByVenue") or {})


def all_boxes() -> List[str]:
    out: List[str] = []
    for items in boxes_by_venue().values():
        for item in items:
            if item not in out:
                out.append(item)
    return out


def tool_groups() -> List[Dict[str, Any]]:
    return list(load_sot().get("toolGroups") or [])


def observed_boxes() -> Dict[str, List[Dict[str, Any]]]:
    return dict(load_sot().get("observedBoxes") or {})


def _alias_table(items: List[Dict[str, Any]], id_key: str = "id") -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    for item in items:
        canonical = item.get(id_key) or item.get("label")
        if not canonical:
            continue
        aliases = list(item.get("aliases") or [])
        aliases.append(str(canonical))
        if item.get("name"):
            aliases.append(str(item["name"]))
        if item.get("label"):
            aliases.append(str(item["label"]))
        for alias in aliases:
            compact = _compact(str(alias))
            if compact:
                rows.append((compact, str(canonical)))
    rows.sort(key=lambda x: len(x[0]), reverse=True)
    return rows


def _match_alias(text: Optional[str], table: List[Tuple[str, str]]) -> Optional[str]:
    compact = _compact(text)
    if not compact:
        return None
    for alias, canonical in table:
        if alias and alias in compact:
            return canonical
    return None


def canonicalize_venue(text: Optional[str]) -> str:
    hit = _match_alias(text, _alias_table(venues()))
    return hit or UNKNOWN_VENUE


def venue_entry_cost(text: Optional[str]) -> Optional[int]:
    """已知会场返回门票；0 是合法免费。未知会场返回 None，禁止假装 5000。"""
    venue_id = canonicalize_venue(text)
    for item in venues():
        if item.get("id") == venue_id:
            cost = item.get("entryCost", None)
            if cost is None:
                return None
            try:
                return int(cost)
            except (TypeError, ValueError):
                return None
    return None


def canonicalize_field_condition(text: Optional[str]) -> str:
    hit = _match_alias(text, _alias_table(field_conditions()))
    return hit or UNKNOWN_FIELD


def canonicalize_box(text: Optional[str]) -> str:
    compact = _compact(text)
    if not compact:
        return UNKNOWN_BOX
    aliases = load_sot().get("boxAliases") or {}
    # 1. 先精确匹配 official aliases
    if compact in {_compact(k): v for k, v in aliases.items()}:
        return {_compact(k): v for k, v in aliases.items()}[compact]
    # 2. 匹配 observed boxes (reference passthrough)
    for items in observed_boxes().values():
        for it in items:
            name = it.get("name") if isinstance(it, dict) else str(it)
            if name and (_compact(name) == compact or _compact(name) in compact):
                return name
    # 3. 按 alias 长度包含匹配 official aliases
    ranked = sorted(((_compact(k), v) for k, v in aliases.items() if _compact(k)), key=lambda x: len(x[0]), reverse=True)
    for alias, canonical in ranked:
        if alias and alias in compact:
            return canonical
    for box in all_boxes():
        if _compact(box) and _compact(box) in compact:
            return box
    return UNKNOWN_BOX


def canonicalize_tool_group(text: Optional[str]) -> Optional[str]:
    return _match_alias(text, _alias_table(tool_groups()))


def extract_from_text(text: Optional[str]) -> Dict[str, Optional[str]]:
    """从一段画面文字里抽出已出现的闭集字段。未出现保持 None，不填默认会场。"""
    compact = _compact(text)
    out: Dict[str, Optional[str]] = {
        "venue": None,
        "box": None,
        "fieldCondition": None,
        "toolGroup": None,
    }
    if not compact:
        return out
    venue = _match_alias(compact, _alias_table(venues()))
    if venue and venue != UNKNOWN_VENUE:
        out["venue"] = venue
    box = canonicalize_box(compact)
    if box != UNKNOWN_BOX:
        out["box"] = box
    field = _match_alias(compact, _alias_table(field_conditions()))
    if field and field != UNKNOWN_FIELD:
        out["fieldCondition"] = field
    out["toolGroup"] = canonicalize_tool_group(compact)
    return out


def live_defaults() -> Dict[str, Optional[str]]:
    unknown = load_sot().get("unknown") or {}
    return {
        "venue": unknown.get("venue") or UNKNOWN_VENUE,
        "box": unknown.get("box") or UNKNOWN_BOX,
        "fieldCondition": unknown.get("fieldCondition") or UNKNOWN_FIELD,
        "toolGroup": unknown.get("toolGroup"),
    }
