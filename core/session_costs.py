"""One cost breakdown for current facts, solver input and persistence."""
def costs_from_facts(facts):
    entry = facts.get("entryCost")
    intel = facts.get("intelCost") or 0
    other = facts.get("otherCost") or 0
    future = facts.get("futureIncrementalCost") or 0
    sunk = None if entry is None else entry + intel + other
    return {"entry": entry, "intel": intel, "other": other, "sunkCost": sunk,
            "futureIncrementalCost": future, "total": None if sunk is None else sunk + future}


def describe_costs(costs):
    costs = costs if isinstance(costs, dict) else {}
    def amount(key):
        value = costs.get(key)
        return f"{value:,.0f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "未知"
    return (f"入场 {amount('entry')} · 情报 {amount('intel')} · 其他已付 {amount('other')} · "
            f"已付合计 {amount('sunkCost')} · 预计后续 {amount('futureIncrementalCost')} · "
            f"含后续合计 {amount('total')}（不含拍价）")
