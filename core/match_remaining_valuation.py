"""Remaining warehouse value for one saved match.

Confirmed catalog prices stay point values. Anything not confirmed contributes
only a lower–upper range from candidate prices. No probability, no single point.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence


# 梦中萤 has no source card of its own. 梦中茧 keeps the 1.4 source
# (green 1x2, price 918) and is not merged onto the solver name.
CATALOG_DISPOSITIONS = (
    {
        "name": "梦中萤",
        "disposition": "缺素材",
        "reason": "solver 名绿色 1x2 与 catalog_065 的梦中茧共用 image7-1-2，没有独立源卡。",
    },
    {
        "name": "梦中茧",
        "disposition": "METADATA",
        "reason": "1.4 源卡为绿色 1x2、价 918；catalog_065 几何是 2x2。不把梦中萤并成同一 ID。",
    },
)


def _number(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _candidate_prices(unit: Mapping[str, Any], lookup: Optional[Callable[[str], Any]]) -> list[int]:
    prices: list[int] = []
    for candidate in unit.get("candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        value = _number(candidate.get("value"))
        if value is None and lookup is not None:
            catalog_id = candidate.get("catalogId")
            if isinstance(catalog_id, str) and catalog_id:
                value = _number(lookup(catalog_id))
        if value is not None:
            prices.append(value)
    return prices


def build_remaining_valuation(
    record: Mapping[str, Any],
    *,
    lookup: Optional[Callable[[str], Any]] = None,
    dispositions: Sequence[Mapping[str, str]] = CATALOG_DISPOSITIONS,
) -> dict[str, Any]:
    settlement = record.get("settlement") if isinstance(record.get("settlement"), Mapping) else {}
    review = settlement.get("warehouseIdentityReview") if isinstance(settlement.get("warehouseIdentityReview"), Mapping) else {}
    resolved = [item for item in (review.get("resolvedItems") or []) if isinstance(item, Mapping)]
    confirmed_items = []
    subtotal = 0
    for item in resolved:
        value = _number(item.get("catalogValue"))
        if value is None:
            continue
        subtotal += value
        confirmed_items.append({
            "reviewUnitId": item.get("reviewUnitId"),
            "name": item.get("name"),
            "catalogId": item.get("catalogId"),
            "catalogValue": value,
        })

    lower = 0
    upper = 0
    reasons: list[dict[str, str]] = []
    for unit in settlement.get("reviewUnits") or []:
        if not isinstance(unit, Mapping) or unit.get("confirmationStatus") == "CONFIRMED":
            continue
        prices = _candidate_prices(unit, lookup)
        if not prices:
            reasons.append({
                "reviewUnitId": str(unit.get("reviewUnitId") or ""),
                "disposition": "NO_CANDIDATE_PRICE",
                "reason": "未确认区域没有候选目录价，不报点值。",
            })
            continue
        lower += min(prices)
        upper += max(prices)
    for item in dispositions:
        reasons.append({
            "name": item["name"],
            "disposition": item["disposition"],
            "reason": item["reason"],
        })
    return {
        "confirmedItems": {
            "count": len(confirmed_items),
            "catalogSubtotal": subtotal,
            "items": confirmed_items,
        },
        "remainingRange": {"lower": lower, "upper": upper},
        "unrecognizedReasons": reasons,
        "wholeWarehouse": {"lower": subtotal + lower, "upper": subtotal + upper},
    }


def apply_remaining_valuation(
    record: MutableMapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    settlement = record.get("settlement")
    if not isinstance(settlement, MutableMapping):
        settlement = {}
        record["settlement"] = settlement
    valuation = build_remaining_valuation(record, **kwargs)
    settlement["remainingValuation"] = valuation
    return valuation


def write_remaining_valuation(path: str, **kwargs: Any) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    records = document.get("records") if isinstance(document, MutableMapping) else None
    if not isinstance(records, list) or not records:
        raise ValueError(f"no records in {path}")
    first = apply_remaining_valuation(records[0], **kwargs)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    with open(path, encoding="utf-8") as handle:
        reread = json.load(handle)
    second = reread["records"][0]["settlement"]["remainingValuation"]
    if second != first:
        raise ValueError("remaining valuation changed on re-read")
    return second
