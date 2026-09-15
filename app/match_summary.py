# -*- coding: utf-8 -*-
"""Deterministic, known-facts-only Match Summary formatter for History presentation.

Phase 18 Contract:
- Pure function: record -> str | None
- Deterministic, zero IO, zero network, zero AI
- Input record is never mutated
- Only known facts are summarized; missing facts are omitted
- Forbidden: winnerCharacter, loadout.character, settlementItems candidate names
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence


def _format_int(val: Any) -> str:
    """Format an integer with comma thousands separator deterministically."""
    try:
        num = int(round(float(val)))
        return f"{num:,}"
    except (TypeError, ValueError):
        return str(val)


def format_match_summary(record: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Format a deterministic, human-readable match summary from a canonical MatchRecord."""
    if not isinstance(record, Mapping):
        return None

    sections: list[str] = []

    # -------------------------------------------------------------------------
    # 1. Intel (Q, goldAvg, purpleCount, purpleAvg)
    # -------------------------------------------------------------------------
    public_intel = record.get("publicIntel") if isinstance(record.get("publicIntel"), Mapping) else {}
    qualities = record.get("qualities") if isinstance(record.get("qualities"), Mapping) else {}
    gold_quality = qualities.get("gold") if isinstance(qualities.get("gold"), Mapping) else {}
    purple_quality = qualities.get("purple") if isinstance(qualities.get("purple"), Mapping) else {}

    q_val = public_intel.get("q") if "q" in public_intel else record.get("q")
    gold_avg_val = gold_quality.get("avg") if "avg" in gold_quality else record.get("goldAvg")
    purple_count_val = purple_quality.get("count") if "count" in purple_quality else record.get("purpleCount")
    purple_avg_val = purple_quality.get("avg") if "avg" in purple_quality else record.get("purpleAvg")

    intel_parts: list[str] = []
    if q_val is not None:
        intel_parts.append(f"Q={q_val}")
    if gold_avg_val is not None:
        intel_parts.append(f"金色均价 {_format_int(gold_avg_val)}")
    if purple_count_val is not None:
        intel_parts.append(f"紫色数量 {_format_int(purple_count_val)}")
    if purple_avg_val is not None:
        intel_parts.append(f"紫色均价 {_format_int(purple_avg_val)}")

    if intel_parts:
        sections.append("本局已识别情报：" + "，".join(intel_parts) + "。")

    # -------------------------------------------------------------------------
    # 2. Settlement (winner, clearingPrice, actualTotal, realizedProfit)
    # -------------------------------------------------------------------------
    settlement = record.get("settlement") if isinstance(record.get("settlement"), Mapping) else {}
    winner = settlement.get("winner") if "winner" in settlement else record.get("winner")
    winner_str = str(winner).strip() if winner is not None and str(winner).strip() else None

    clearing_price = (
        settlement.get("clearingPrice")
        if "clearingPrice" in settlement
        else record.get("clearingPrice")
    )
    actual_total = (
        settlement.get("actualTotal")
        if "actualTotal" in settlement
        else record.get("actualTotal")
    )
    realized_profit = (
        settlement.get("realizedProfit")
        if "realizedProfit" in settlement
        else (settlement.get("profit") if "profit" in settlement else record.get("realizedProfit"))
    )

    lead: Optional[str] = None
    if winner_str is not None:
        if clearing_price is not None:
            lead = f"最终由「{winner_str}」以 {_format_int(clearing_price)} 成交"
        else:
            lead = f"最终由「{winner_str}」成交"
    else:
        # winner unknown; check if any settlement financial fact is known
        if clearing_price is not None or actual_total is not None or realized_profit is not None:
            if clearing_price is not None:
                lead = f"成交者未识别，最终成交价 {_format_int(clearing_price)}"
            else:
                lead = "成交者未识别"

    if lead is not None:
        settlement_parts = [lead]
        if actual_total is not None:
            settlement_parts.append(f"实际价值 {_format_int(actual_total)}")
        ownership = settlement.get("acquired") if "acquired" in settlement else record.get("acquired")
        ownership_unknown = record.get("schemaVersion") == 7 and not isinstance(ownership, bool)
        if ownership_unknown:
            settlement_parts.append("本人竞得归属未知，净收益未确认")
        elif realized_profit is not None:
            settlement_parts.append(f"收益 {_format_int(realized_profit)}")
        sections.append("，".join(settlement_parts) + "。")

    # -------------------------------------------------------------------------
    # 3. Warehouse & Settlement Occupancy & Identity completeness
    # -------------------------------------------------------------------------
    warehouse = record.get("warehouse") if isinstance(record.get("warehouse"), Mapping) else {}
    raw_slots = warehouse.get("slots")
    slots = raw_slots if isinstance(raw_slots, (list, tuple)) else None

    occupancy = (
        settlement.get("warehouseOccupancy")
        if "warehouseOccupancy" in settlement
        else record.get("warehouseOccupancy")
    )
    tracks = None
    if isinstance(occupancy, Mapping):
        raw_tracks = occupancy.get("tracks")
        if isinstance(raw_tracks, (list, tuple)):
            tracks = raw_tracks
    elif isinstance(occupancy, (list, tuple)):
        tracks = occupancy

    warehouse_parts: list[str] = []
    if slots is not None:
        warehouse_parts.append(f"局内仓库记录 {len(slots)} 个槽位")

    if tracks is not None:
        warehouse_parts.append(f"结算全仓记录 {len(tracks)} 个物理占用项")

    # Identity completeness
    has_unconfirmed = False
    if slots is not None:
        for slot in slots:
            if isinstance(slot, Mapping):
                identified_name = slot.get("identifiedName")
                status = str(slot.get("status") or "").upper()
                name = slot.get("name")
                if (identified_name is None and not name) or status in ("UNKNOWN", "AMBIGUOUS", "OUTLINE"):
                    has_unconfirmed = True
                    break
                if slot.get("unknown") is True:
                    has_unconfirmed = True
                    break
    if tracks is not None and len(tracks) > 0:
        has_unconfirmed = True

    if has_unconfirmed:
        warehouse_parts.append("藏品身份仍有未确认项")

    if warehouse_parts:
        sections.append("，".join(warehouse_parts) + "。")

    if not sections:
        return None

    return "".join(sections)
