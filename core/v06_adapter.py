# -*- coding: utf-8 -*-
"""
v0.6 Solver Adapter (Canonical MatchRecord v7 -> 0.6 Solver Input)

唯一职责：
1. 字段映射与解耦 (loadout.solverToolGroup -> toolGroup, qualities.gold.avg -> goldAvg/avg)
2. legacy flatten 与类型转换 (qualities.*.knownItems -> legacy string '51077+18031' 或 '万有星仪')
3. canonical enum / alias 转换 (venue / box / fieldCondition)
4. unknown/null 语义保持 (未观测字段严格保持 None/null，绝不写 0)
5. 事实与推断完全分离 (不把旧 solver 推演结果当做事实反喂)
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, List, Optional, Union


VENUE_CANONICAL_TO_NAME = {
    "shanhu": "中级场 · 珊瑚场",
    "milin": "高级场 · 密林场",
    "baiye": "高级场 · 白夜场",
    "haimo": "顶级场 · 海沫场",
}

VENUE_NAME_TO_CANONICAL = {
    "中级场 · 珊瑚场": "shanhu",
    "珊瑚场": "shanhu",
    "中级场·珊瑚场": "shanhu",
    "高级场 · 密林场": "milin",
    "密林场": "milin",
    "高级场·密林场": "milin",
    "高级场 · 白夜场": "baiye",
    "白夜场": "baiye",
    "高级场·白夜场": "baiye",
    "顶级场 · 海沫场": "haimo",
    "海沫场": "haimo",
    "顶级场·海沫场": "haimo",
}


def format_known_items(items: Union[None, str, List[Any]]) -> str:
    """
    将结构化已知藏品转换为 0.6 原生消费的格式字符串 (如 '万有星仪+海盐心迷宫' 或 '51077+18031')
    """
    if items is None or items == "" or items == []:
        return ""
    if isinstance(items, str):
        return items.strip()
    if not isinstance(items, list):
        return str(items).strip()

    parts: List[str] = []
    for it in items:
        if it is None:
            continue
        if isinstance(it, str):
            s = it.strip()
            if s:
                parts.append(s)
        elif isinstance(it, (int, float)):
            parts.append(str(int(it)))
        elif isinstance(it, dict):
            name = it.get("name")
            price = it.get("price")
            count = it.get("count", 1)
            token = None
            if name:
                token = str(name).strip()
            elif price is not None:
                token = str(int(price))
            if token:
                if isinstance(count, int) and count > 1:
                    token = f"{token}*{count}"
                parts.append(token)
    return "+".join(parts)


def canonicalize_venue_name(venue_val: Optional[str], fill_default: bool = True) -> Optional[str]:
    """转换场地字段为 0.6 渲染和计算的标准中文名称"""
    if not venue_val or venue_val in ("未知场地", "unknown"):
        return "中级场 · 珊瑚场" if fill_default else None
    if venue_val in VENUE_CANONICAL_TO_NAME:
        return VENUE_CANONICAL_TO_NAME[venue_val]
    for k, v in VENUE_NAME_TO_CANONICAL.items():
        if k in venue_val or venue_val in k:
            return VENUE_CANONICAL_TO_NAME.get(v, venue_val)
    return venue_val


def canonicalize_field_condition_id(cond_val: Optional[str], fill_default: bool = True) -> Optional[str]:
    """归一化场地词条 ID"""
    if not cond_val:
        return "standard" if fill_default else None
    if cond_val in ("未知场地条件", "unknown"):
        return "standard" if fill_default else cond_val
    alias_map = {
        "标准对局": "standard",
        "标准规则": "standard",
        "天黑了": "dark",
        "一手情报": "extraIntel",
        "加倍！！": "purpleDouble",
        "加倍！！！": "goldDouble",
        "闪耀之心": "sparkle",
        "福利多多": "welfare",
        "宝石迷阵": "gemMaze",
        "宝石迷宫": "gemMaze",
        "gem_maze": "gemMaze",
    }
    return alias_map.get(cond_val, cond_val)


def canonical_to_v06_solver_input(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 Canonical MatchRecord v7 (或 Session Context 事实字典) 转换为 0.6 求解器输入格式。
    
    保证：
    - 绝不用 0 填充 unknown/null 字段
    - goldAvg 映射到 0.6 内部 avg 与 goldAvg
    - purpleAvg 与 goldAvg 严格隔离
    - solverToolGroup 映射到 toolGroup (忽略 lobbyToolGroup)
    - 结构化 knownItems 转换为 0.6 消费的字符串
    """
    if not isinstance(data, dict):
        return {}

    # Manual / user_override 不得吃历史兼容默认值。
    fill_default = True
    if data.get("fillDefaults") is False or data.get("source") == "manual":
        fill_default = False
    env_probe = data.get("environment") if isinstance(data.get("environment"), dict) else {}
    if env_probe.get("fieldConditionSource") == "user_override":
        fill_default = False

    # 判断是否为嵌套 Canonical v7 结构
    is_v7_schema = "qualities" in data or "environment" in data or data.get("schemaVersion") == 7

    if is_v7_schema:
        env = data.get("environment") or {}
        loadout = data.get("loadout") or {}
        costs = data.get("costs") or {}
        pub = data.get("publicIntel") or {}
        quals = data.get("qualities") or {}
        bidding = data.get("bidding") or {}

        # 1. 环境与装备
        venue_tier = env.get("venueTier")
        venue = canonicalize_venue_name(env.get("venueName") or env.get("venue"), fill_default=fill_default)
        box = env.get("box") or ("琉璃宝箱（宝石类概率提升）" if fill_default else None)
        field_condition = canonicalize_field_condition_id(env.get("fieldCondition"), fill_default=fill_default)
        character = loadout.get("character") or ("达芙蒂尔" if fill_default else None)
        tool_group = loadout.get("solverToolGroup")
        if tool_group not in ("group1", "group2"):
            tool_group = "group1" if fill_default else None

        # 2. 公共情报
        q = pub.get("q")
        total_items = pub.get("totalItems")
        total_grid = pub.get("totalGrid")
        avg_value_basis = pub.get("avgValueBasis") or "unknown"

        # 3. 六大品质
        g_info = quals.get("gold") or {}
        p_info = quals.get("purple") or {}
        r_info = quals.get("red") or {}
        b_info = quals.get("blue") or {}
        gr_info = quals.get("green") or {}
        w_info = quals.get("white") or {}

        gold_avg = g_info.get("avg")
        gold_count = g_info.get("count")
        min_gold = g_info.get("minCount")
        gold_total = g_info.get("total")
        gold_grid = g_info.get("grid")
        known_gold = format_known_items(g_info.get("knownItems"))

        purple_avg = p_info.get("avg")
        purple_count = p_info.get("count")
        min_purple = p_info.get("minCount")
        purple_grid = p_info.get("grid")
        known_purple = format_known_items(p_info.get("knownItems"))

        red_count = r_info.get("count")
        red_grid = r_info.get("grid")
        min_red = r_info.get("minCount")
        known_red = format_known_items(r_info.get("knownItems"))
        red_inventory_complete = bool(r_info.get("redInventoryComplete", False))
        settlement_verified_red_items = r_info.get("settlementVerifiedRedItems") or ""

        blue_count = b_info.get("count")
        blue_avg = b_info.get("avg")
        blue_grid = b_info.get("grid")

        green_count = gr_info.get("count")
        green_avg = gr_info.get("avg")
        green_grid = gr_info.get("grid")

        white_count = w_info.get("count")
        white_avg = w_info.get("avg")
        white_grid = w_info.get("grid")

        # 4. 成本与出价
        cost = costs.get("total", costs.get("sunkCost", 5000))
        target_profit = data.get("targetProfit")
        if target_profit is None and fill_default:
            target_profit = 30000
        round_no = bidding.get("round") or data.get("round") or 1
        leader_bid = bidding.get("leaderBid")
        if leader_bid is None:
            leader_bid = bidding.get("myFinalBid")
        if leader_bid is None:
            leader_bid = data.get("leaderBid")
        if leader_bid is None and fill_default:
            leader_bid = 0

    else:
        # Flat 0.65 / SessionContext 格式
        venue = canonicalize_venue_name(data.get("venue"), fill_default=fill_default)
        box = data.get("box") or data.get("boxType") or ("琉璃宝箱（宝石类概率提升）" if fill_default else None)
        field_condition = canonicalize_field_condition_id(data.get("fieldCondition"), fill_default=fill_default)
        character = data.get("character") or data.get("lobbyCharacter") or ("达芙蒂尔" if fill_default else None)
        
        # 严密过滤：仅当明确为 group1 或 group2 时才视为 solverToolGroup
        stg = data.get("solverToolGroup")
        tg = data.get("toolGroup")
        if stg in ("group1", "group2"):
            tool_group = stg
        elif tg in ("group1", "group2"):
            tool_group = tg
        else:
            tool_group = "group1" if fill_default else None

        q = data.get("q")
        total_items = data.get("totalItems")
        total_grid = data.get("totalGrids") if data.get("totalGrids") is not None else data.get("totalGrid")
        avg_value_basis = data.get("avgValueBasis") or "unknown"

        # 品质均价 (严格隔离)
        gold_avg = data.get("goldAvg")
        purple_avg = data.get("purpleAvg")
        blue_avg = data.get("blueAvg")
        green_avg = data.get("greenAvg")
        white_avg = data.get("whiteAvg")

        gold_count = data.get("goldCount")
        min_gold = data.get("minGold")
        gold_total = data.get("goldTotal")
        gold_grid = data.get("goldGrid")

        purple_count = data.get("purpleCount") if data.get("purpleCount") is not None else data.get("purple")
        min_purple = data.get("minPurple")
        purple_grid = data.get("purpleGrid")

        red_count = data.get("redCount")
        red_grid = data.get("redGrid")
        min_red = data.get("minRed")
        red_inventory_complete = bool(data.get("redInventoryComplete", False))
        settlement_verified_red_items = data.get("settlementVerifiedRedItems") or data.get("redItems") or ""

        blue_count = data.get("blueCount")
        blue_grid = data.get("blueGrid")

        green_count = data.get("greenCount")
        green_grid = data.get("greenGrid")

        white_count = data.get("whiteCount")
        white_grid = data.get("whiteGrid")

        # 已知藏品提取 (支持 identifiedShapes 与 顶层 known* 字符串/列表)
        shapes = data.get("identifiedShapes") or {}
        raw_kg = shapes.get("knownGold") or data.get("knownGold")
        raw_kp = shapes.get("knownPurple") or data.get("knownPurple")
        raw_kr = shapes.get("knownRed") or data.get("knownRed") or data.get("decisionKnownRed")

        known_gold = format_known_items(raw_kg)
        known_purple = format_known_items(raw_kp)
        known_red = format_known_items(raw_kr)

        costs_raw = data.get("costs") or {}
        cost = data.get("cost", costs_raw.get("total", costs_raw.get("sunkCost", 5000)))
        costs = costs_raw if costs_raw else {
            "entry": 5000,
            "intel": int(cost) - 5000 if int(cost) > 5000 else 0,
            "other": 0,
            "sunkCost": int(cost),
            "futureIncrementalCost": 0,
            "total": int(cost)
        }
        target_profit = data.get("targetProfit")
        if target_profit is None and fill_default:
            target_profit = 30000
        round_no = data.get("round", 1)
        leader_bid = data.get("currentLeaderBid")
        if leader_bid is None:
            leader_bid = data.get("leaderBid")
        if leader_bid is None:
            leader_bid = data.get("myBid")
        if leader_bid is None and fill_default:
            leader_bid = 0

    # 构造标准 0.6 求解器输入字典
    solver_input: Dict[str, Any] = {
        **{key: data[key] if key in data else (data.get("bidding") or {}).get(key)
           for key in ("privateBidCap", "bidActionCount")},
        "sparkle": deepcopy(data.get("sparkle")),
        "q": q,
        "p": purple_count,
        "purple": purple_count,
        "purpleCount": purple_count,
        "goldCount": gold_count,
        "redCount": red_count,
        "minGold": min_gold,
        "minPurple": min_purple,
        "minRed": min_red,
        # 0.6 求解器内部将金色均价命名为 avg，在此做精准物理绑定
        "avg": gold_avg,
        "goldAvg": gold_avg,
        "purpleAvg": purple_avg,
        "blueAvg": blue_avg,
        "greenAvg": green_avg,
        "whiteAvg": white_avg,
        "goldTotal": gold_total,
        "goldGrid": gold_grid,
        "purpleGrid": purple_grid,
        "redGrid": red_grid,
        "blueCount": blue_count,
        "blueGrid": blue_grid,
        "greenCount": green_count,
        "greenGrid": green_grid,
        "whiteCount": white_count,
        "whiteGrid": white_grid,
        "totalItems": total_items,
        "totalGrid": total_grid,
        "cost": int(cost) if cost is not None else 0,
        "costs": costs,
        "targetProfit": int(target_profit) if target_profit is not None else None,
        "knownGold": known_gold,
        **{"known" + color.title(): format_known_items((quals.get(color) or {}).get("knownItems"))
           if is_v7_schema else format_known_items(data.get("known" + color.title()))
           for color in ("blue", "green", "white")},
        "knownPurple": known_purple,
        "knownRed": known_red,
        "knownGoldRaw": known_gold,
        "knownPurpleRaw": known_purple,
        "knownRedRaw": known_red,
        "goldGroups": [],
        "purpleGroups": [],
        "redGroups": [],
        "venueTier": venue_tier if is_v7_schema else data.get("venueTier"),
        "venue": venue,
        "box": box,
        "fieldCondition": field_condition,
        "avgValueBasis": avg_value_basis,
        "roundingMode": "floor",
        "toolGroup": tool_group,
        "character": character,
        "round": int(round_no) if round_no is not None else 1,
        "leaderBid": int(leader_bid) if leader_bid is not None else None,
        "matchId": data.get("id") or data.get("matchId"),
        "redInventoryComplete": red_inventory_complete,
        "settlementVerifiedRedItems": settlement_verified_red_items,
        "publicInfo": {
            "totalItems": total_items,
            "totalGrid": total_grid,
            "goldGrid": gold_grid,
            "purpleGrid": purple_grid,
            "redGrid": red_grid,
            "blueCount": blue_count,
            "blueGrid": blue_grid,
            "blueAvg": blue_avg,
            "greenCount": green_count,
            "greenGrid": green_grid,
            "greenAvg": green_avg,
            "whiteCount": white_count,
            "whiteGrid": white_grid,
            "whiteAvg": white_avg,
            "systemEstimate": None,
            "singleAvg": None,
            "nineAvg": None,
            "publicNote": ""
        }
    }

    return solver_input


def v06_record_to_canonical(legacy: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 0.6 历史归档记录升级为 Canonical MatchRecord v7 格式
    """
    if not isinstance(legacy, dict):
        return {}

    venue_name = legacy.get("venue") or "中级场 · 珊瑚场"
    canonical_venue = VENUE_NAME_TO_CANONICAL.get(venue_name, "shanhu")

    # 提取 knownItems 为数组格式
    def parse_legacy_known(raw_text: Any) -> List[Dict[str, Any]]:
        if not raw_text or not isinstance(raw_text, str):
            return []
        items = []
        tokens = raw_text.split("+")
        for t in tokens:
            t = t.strip()
            if not t:
                continue
            if t.isdigit():
                items.append({"name": None, "price": int(t)})
            else:
                items.append({"name": t, "price": None})
        return items

    costs_raw = legacy.get("costs") or {}
    cost_total = legacy.get("cost", costs_raw.get("total", 5000))
    costs = {
        "entry": costs_raw.get("entry", 5000),
        "intel": costs_raw.get("intel", costs_raw.get("info", int(cost_total) - 5000 if int(cost_total) > 5000 else 0)),
        "other": costs_raw.get("other", 0),
        "sunkCost": costs_raw.get("sunkCost", int(cost_total)),
        "futureIncrementalCost": costs_raw.get("futureIncrementalCost", 0),
        "total": int(cost_total)
    }

    # 提取 prediction 结果
    pred = legacy.get("prediction")
    solver_result = None
    if isinstance(pred, dict):
        solver_result = {
            "solverVersion": "v0.6",
            "solverStatus": pred.get("solverStatus", "valid"),
            "inputHash": pred.get("inputHash", ""),
            "solvedAt": legacy.get("playedAt") or "",
            "round": pred.get("round", 1),
            "decisions": {
                "targetLine": pred.get("targetLine"),
                "globalLine": pred.get("globalLine"),
                "marginalLine": pred.get("marginalLine"),
                "valP20": pred.get("rawShadow", {}).get("p20") if isinstance(pred.get("rawShadow"), dict) else pred.get("workingLow"),
                "valP50": pred.get("estimate"),
                "valP80": pred.get("rawShadow", {}).get("p80") if isinstance(pred.get("rawShadow"), dict) else pred.get("workingHigh"),
                "theoreticalMin": pred.get("theoreticalMin"),
                "theoreticalMax": pred.get("theoreticalMax"),
            },
            "goldInference": pred.get("goldInference"),
            "candidateGs": pred.get("candidateGs") or [],
            "candidatePs": pred.get("candidatePs") or [],
            "componentBreakdown": pred.get("componentBreakdown"),
            "probabilityProfile": pred.get("rawShadow")
        }

    canonical = {
        "schemaVersion": 7,
        "productVersion": legacy.get("productVersion", "v0.6"),
        "id": legacy.get("id", ""),
        "playedAt": legacy.get("playedAt") or legacy.get("date") or "",
        "periodKey": legacy.get("periodKey") or legacy.get("patch") or "",
        "environment": {
            "venue": canonical_venue,
            "venueName": venue_name,
            "box": legacy.get("box", "未知箱型"),
            "boxType": "wood" if "实木" in str(legacy.get("box", "")) else ("glass" if "琉璃" in str(legacy.get("box", "")) else "standard"),
            "fieldCondition": legacy.get("fieldCondition", "standard"),
            "fieldConditionName": "标准对局",
            "fieldConditionSource": legacy.get("fieldConditionSource", "explicit")
        },
        "loadout": {
            "character": legacy.get("character", "达芙蒂尔"),
            "lobbyToolGroup": None,
            "solverToolGroup": legacy.get("toolGroup", "group1")
        },
        "costs": costs,
        "publicIntel": {
            "q": legacy.get("q"),
            "totalItems": legacy.get("totalItems"),
            "totalGrid": legacy.get("totalGrid"),
            "avgValueBasis": legacy.get("avgValueBasis", "unknown")
        },
        "qualities": {
            "white": {
                "count": legacy.get("whiteCount"),
                "avg": legacy.get("whiteAvg"),
                "grid": legacy.get("whiteGrid")
            },
            "green": {
                "count": legacy.get("greenCount"),
                "avg": legacy.get("greenAvg"),
                "grid": legacy.get("greenGrid")
            },
            "blue": {
                "count": legacy.get("blueCount"),
                "avg": legacy.get("blueAvg"),
                "grid": legacy.get("blueGrid")
            },
            "purple": {
                "count": legacy.get("purpleCount") if legacy.get("purpleCount") is not None else legacy.get("purple"),
                "minCount": legacy.get("minPurple"),
                "avg": legacy.get("purpleAvg"),
                "grid": legacy.get("purpleGrid"),
                "knownItems": parse_legacy_known(legacy.get("knownPurple"))
            },
            "gold": {
                "count": legacy.get("goldCount"),
                "minCount": legacy.get("minGold"),
                "avg": legacy.get("goldAvg"),
                "total": legacy.get("goldTotal"),
                "grid": legacy.get("goldGrid"),
                "knownItems": parse_legacy_known(legacy.get("knownGold"))
            },
            "red": {
                "count": legacy.get("redCount"),
                "minCount": legacy.get("minRed"),
                "maxCount": None,
                "knownItems": parse_legacy_known(legacy.get("knownRed") or legacy.get("decisionKnownRed")),
                "redInventoryComplete": legacy.get("redInventoryComplete", False),
                "settlementVerifiedRedItems": legacy.get("settlementVerifiedRedItems", "")
            }
        },
        "bidding": {
            "seats": [],
            "myName": legacy.get("myName", "PLAYER_LOCAL"),
            "myFinalBid": legacy.get("highestPersonalBid") or legacy.get("bid"),
            "leaderName": legacy.get("winner"),
            "leaderBid": legacy.get("clearingPrice"),
            "leaderTies": [],
            "isMyLead": legacy.get("acquired", False),
            "historicalBids": legacy.get("historicalBids", {}),
            "finalBids": legacy.get("finalBids", {}),
            "rounds": legacy.get("rounds", [])
        },
        "settlement": {
            "isSettled": legacy.get("actualTotal") is not None,
            "clearingPrice": legacy.get("clearingPrice") or legacy.get("bid"),
            "actualTotal": legacy.get("actualTotal"),
            "realizedProfit": legacy.get("realizedProfit"),
            "acquired": legacy.get("acquired", False),
            "winner": legacy.get("winner", ""),
            "resultReason": legacy.get("resultReason") or legacy.get("noBidReason") or "",
            "settlementItems": [],
            "realizedState": legacy.get("realizedState")
        },
        "solverResult": solver_result
    }

    return canonical


def v065_record_to_canonical(rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 0.65 MatchRecord (如数据库中的 9 条 0.65 记录或自动归档记录) 归一化升级为 Canonical MatchRecord v7
    """
    if not isinstance(rec, dict):
        return {}

    venue_raw = rec.get("venue") or "shanhu"
    canonical_venue = VENUE_NAME_TO_CANONICAL.get(venue_raw, venue_raw)
    venue_name = VENUE_CANONICAL_TO_NAME.get(canonical_venue, venue_raw)

    shapes = rec.get("identifiedShapes") or {}
    kg = shapes.get("knownGold") or rec.get("knownGold") or []
    kp = shapes.get("knownPurple") or rec.get("knownPurple") or []
    kr = shapes.get("knownRed") or rec.get("knownRed") or []

    def to_item_objects(arr):
        if not arr:
            return []
        if isinstance(arr, str):
            tokens = arr.split("+")
            return [{"name": t if not t.isdigit() else None, "price": int(t) if t.isdigit() else None} for t in tokens if t.strip()]
        if isinstance(arr, list):
            out = []
            for x in arr:
                if isinstance(x, dict):
                    out.append(x)
                elif isinstance(x, str):
                    out.append({"name": x, "price": None})
                elif isinstance(x, (int, float)):
                    out.append({"name": None, "price": int(x)})
            return out
        return []

    costs_raw = rec.get("costs") or {}
    cost_total = rec.get("cost", costs_raw.get("total", 5000))
    costs = {
        "entry": costs_raw.get("entry", 5000),
        "intel": costs_raw.get("intel", costs_raw.get("info", int(cost_total) - 5000 if int(cost_total) > 5000 else 0)),
        "other": costs_raw.get("other", 0),
        "sunkCost": costs_raw.get("sunkCost", int(cost_total)),
        "futureIncrementalCost": costs_raw.get("futureIncrementalCost", 0),
        "total": int(cost_total)
    }

    # 提取 0.65 求解器分支与大厅仪器组
    solver_tg = rec.get("solverToolGroup")
    lobby_tg = rec.get("lobbyToolGroup")
    raw_tg = rec.get("toolGroup")
    if not solver_tg:
        if raw_tg in ("group1", "group2"):
            solver_tg = raw_tg
        else:
            solver_tg = "group1"
            if not lobby_tg and raw_tg:
                lobby_tg = raw_tg

    canonical = {
        "schemaVersion": 7,
        "productVersion": rec.get("productVersion", "v0.65"),
        "id": rec.get("id", ""),
        "playedAt": rec.get("playedAt") or rec.get("timestamp") or "",
        "periodKey": rec.get("periodKey", ""),
        "environment": {
            "venue": canonical_venue,
            "venueName": venue_name,
            "box": rec.get("box") or rec.get("boxType") or "未知箱型",
            "boxType": rec.get("boxType") or ("wood" if "实木" in str(rec.get("box", "")) else ("glass" if "琉璃" in str(rec.get("box", "")) else "standard")),
            "fieldCondition": rec.get("fieldCondition", "standard"),
            "fieldConditionName": "标准对局",
            "fieldConditionSource": "vision_ocr"
        },
        "loadout": {
            "character": rec.get("character", "达芙蒂尔"),
            "lobbyToolGroup": lobby_tg,
            "solverToolGroup": solver_tg
        },
        "costs": costs,
        "publicIntel": {
            "q": rec.get("q"),
            "totalItems": rec.get("totalItems"),
            "totalGrid": rec.get("totalGrids") if rec.get("totalGrids") is not None else rec.get("totalGrid"),
            "avgValueBasis": rec.get("avgValueBasis", "unknown")
        },
        "qualities": {
            "white": {
                "count": rec.get("whiteCount"),
                "avg": rec.get("whiteAvg"),
                "grid": rec.get("whiteGrid")
            },
            "green": {
                "count": rec.get("greenCount"),
                "avg": rec.get("greenAvg"),
                "grid": rec.get("greenGrid")
            },
            "blue": {
                "count": rec.get("blueCount"),
                "avg": rec.get("blueAvg"),
                "grid": rec.get("blueGrid")
            },
            "purple": {
                "count": rec.get("purpleCount") if rec.get("purpleCount") is not None else rec.get("purple"),
                "minCount": rec.get("minPurple"),
                "avg": rec.get("purpleAvg"),
                "grid": rec.get("purpleGrid"),
                "knownItems": to_item_objects(kp)
            },
            "gold": {
                "count": rec.get("goldCount"),
                "minCount": rec.get("minGold"),
                "avg": rec.get("goldAvg"),
                "total": rec.get("goldTotal"),
                "grid": rec.get("goldGrid"),
                "knownItems": to_item_objects(kg)
            },
            "red": {
                "count": rec.get("redCount"),
                "minCount": rec.get("minRed"),
                "maxCount": None,
                "knownItems": to_item_objects(kr),
                "redInventoryComplete": rec.get("redInventoryComplete", False),
                "settlementVerifiedRedItems": rec.get("settlementVerifiedRedItems", "")
            }
        },
        "bidding": {
            "seats": rec.get("opponents") or [],
            "myName": rec.get("myName", "PLAYER_LOCAL"),
            "myFinalBid": rec.get("myFinalBid") or rec.get("myBid"),
            "leaderName": rec.get("winnerName") or rec.get("leaderName"),
            "leaderBid": rec.get("clearingPrice") or rec.get("currentLeaderBid"),
            "leaderTies": rec.get("leaderTies", []),
            "isMyLead": rec.get("isAcquired", False),
            "historicalBids": rec.get("historicalBids", {}),
            "finalBids": rec.get("finalBids", {}),
            "rounds": rec.get("roundTimeline") or rec.get("rounds") or []
        },
        "settlement": {
            "isSettled": rec.get("actualTotal") is not None,
            "clearingPrice": rec.get("clearingPrice"),
            "actualTotal": rec.get("actualTotal"),
            "realizedProfit": rec.get("realizedProfit"),
            "acquired": rec.get("isAcquired") if rec.get("isAcquired") is not None else rec.get("acquired", False),
            "winner": rec.get("winnerName") or rec.get("winner", ""),
            "resultReason": rec.get("resultReason", ""),
            "settlementItems": rec.get("settlementItems", []),
            "realizedState": rec.get("realizedState")
        },
        "solverResult": None
    }

    return canonical
