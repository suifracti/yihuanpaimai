"""
Neverness to Everness (异环) - 共享战术决策大脑 (Shared Tactical Auction Brain - v0.65)

核心职责：
  1. 协调 VisionPipeline -> DeltaIntelManager -> SessionFSM -> TacticalHUD -> AutoArchiver
  2. 组织流式对局上下文 (Session Context) 并实时推流至 Tactical HUD
  3. 彻底消除 Node.js 子进程依赖；高精度组合求解由 HUD (WebView2) 加载的 Shared JS Core 实时运行
  4. 终局结算自动持久化记账
"""

import os
import sys
import time
import json
from typing import Dict, Any, Optional, List, Tuple
import numpy as np

from vision_contract import VisionObservation
from delta_intel import DeltaIntelManager
from auto_archiver import AutoArchiver
from session_fsm import AuctionSessionFSM, SessionState

class AuctionBrain:
    def __init__(self, node_engine_path: Optional[str] = None, archiver: Optional[AutoArchiver] = None):
        core_dir = os.path.dirname(os.path.abspath(__file__))
        self.engine_path = node_engine_path or os.path.join(core_dir, "auction_engine_v06.js")
        self.delta_manager = DeltaIntelManager()
        self.archiver = archiver or AutoArchiver()
        self.fsm = AuctionSessionFSM()
        self.last_solver_status = "incomplete"
        self.last_decision = {}

    def format_w(self, val: Optional[int]) -> str:
        if val is None or not isinstance(val, (int, float)) or math_isnan(val):
            return "-- W"
        return f"{val / 10000.0:.1f} W"

    def solve_session(self, session_ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        求解当前对局状态并计算决策出价线 (零外部 Node.js 进程依赖)
        注：完整高精度组合推演由前端 WebView2 / Tactical HUD 加载的 Shared JS Core 实时执行。
        """
        q = session_ctx.get("q")
        gold_avg = session_ctx.get("goldAvg") or session_ctx.get("avg")
        diagnostic_only = bool(session_ctx.get("diagnosticOnly", False))
        explicit_status = session_ctx.get("solverStatus")

        # 1. 情报不足判定
        if not q or not gold_avg:
            status = explicit_status or "fallback"
            return {
                "solverStatus": status,
                "diagnosticOnly": diagnostic_only,
                "valP50": None,
                "valRange": ("--", "--"),
                "targetProfitLine": None,
                "globalProfitLine": None,
                "marginalChaseLine": None,
                "marketRatioEst": "-- W (等待情报)",
                "actionDirective": "🟡 情报不足",
                "actionReason": "等待拍卖师揭晓箱体件数 Q 与均价",
                "entryGrade": "— 待定",
                "isFold": False
            }

        # 2. 状态与基础成本解析
        status = explicit_status or "valid"
        costs = session_ctx.get("costs", {})
        sunk_cost = costs.get("sunkCost", costs.get("entry", 5000))
        future_cost = costs.get("futureIncrementalCost", 0)
        all_costs = sunk_cost + future_cost
        target_profit = session_ctx.get("targetProfit", 30000)

        # 3. 基础估值与风险出价线
        center = q * gold_avg
        p20 = int(center * 0.9)
        p50 = center
        p80 = int(center * 1.1)

        target_line = max(0, p20 - all_costs - target_profit)
        global_line = max(0, p20 - all_costs)
        marginal_line = max(0, p20 - future_cost)
        cur_bid = session_ctx.get("leaderBid", 0)

        is_fold = cur_bid > marginal_line if (marginal_line is not None and cur_bid > 0) else False
        is_thin = cur_bid > global_line if (global_line is not None and cur_bid > 0) else False

        # 4. 状态语义与行动指令决策
        if status == "stale":
            action = "⏳ 旧结果已过期 · 禁止依据追价"
            reason = "输入条件已发生改变，正在等待重新推演"
            grade = "— 过期"
        elif status == "incomplete":
            action = "🟡 等待完整求解 · 不生成正式推荐"
            reason = "箱体件数 Q 或均价仍未揭晓，不满足严格求解前提"
            grade = "— 待定"
        elif status == "timeout":
            action = "⏸️ 求解超时 · 暂停追价"
            reason = "组合空间搜索超时；这不等于输入矛盾，建议先恢复输入"
            grade = "— 超时"
        elif status == "no-match":
            action = "⚠️ 输入无可行解 · 暂停追价"
            reason = "当前输入条件与图鉴/场地倍率存在严格冲突，请核对抄录"
            grade = "— 冲突"
        elif status == "fallback":
            action = "⚠️ 降级估算中 · 谨慎参考"
            reason = "精确求解未命中，已启用粗略估算"
            grade = "C 降级"
        elif is_fold:
            action = "🔴 超过边际追价线 · 建议停止"
            reason = "当前叫价已超过边际保本线，继续跟价将产生纯亏损"
            grade = "D 放弃"
        elif is_thin:
            action = "🟡 已进入薄利区 · 谨慎跟价"
            reason = "当前叫价已超出全局全成本线，仅剩边际利润"
            grade = "B 薄利"
        else:
            action = "🟢 仍在目标利润区 · 可以继续"
            reason = "估值空间充足，预期投资回报率满足目标"
            grade = "A+ 推荐"

        if diagnostic_only:
            action = f"[诊断模式] {action}"

        # 5. 计算 ROI
        roi_total = (p50 - (cur_bid + all_costs)) / (cur_bid + all_costs) if (cur_bid > 0 and (cur_bid + all_costs) > 0) else None
        roi_purchase = (p50 - (cur_bid + all_costs)) / cur_bid if cur_bid > 0 else None

        return {
            "solverStatus": status,
            "diagnosticOnly": diagnostic_only,
            "valP50": p50,
            "valRange": (p20, p80),
            "targetProfitLine": target_line,
            "globalProfitLine": global_line,
            "marginalChaseLine": marginal_line,
            "marketRatioEst": f"{self.format_w(int(p50 * 0.52))} (正常竞争)",
            "actionDirective": action,
            "actionReason": reason,
            "entryGrade": grade,
            "isFold": is_fold,
            "roiOnTotalSpend": roi_total,
            "roiOnPurchase": roi_purchase
        }

    def process_observation(self, obs: VisionObservation) -> Dict[str, Any]:
        """
        处理单帧视觉观测并生成完整的 HUD 战术广播数据包
        """
        # 1. 驱动有限状态机 (FSM)
        fsm_res = self.fsm.handle_observation(obs)

        # 2. 增量更新流
        delta_res = self.delta_manager.process_observation(obs)
        session_ctx = delta_res["sessionContext"]

        # 3. 求解并评估决策
        decision = self.solve_session(session_ctx)
        self.last_decision = decision
        self.last_solver_status = decision.get("solverStatus", "incomplete")

        # 4. 自动归档判定
        if obs.settlement.isSettlement:
            session_ctx["settlementReady"] = True
            saved_record = self.archiver.archive_match(session_ctx)
            if saved_record:
                self.fsm.mark_archived()
                try:
                    settlement = saved_record.get("settlement") if isinstance(saved_record, dict) else {}
                    if not isinstance(settlement, dict):
                        settlement = {}
                    clearing = settlement.get("clearingPrice") if "clearingPrice" in settlement else (saved_record.get("clearingPrice") if isinstance(saved_record, dict) else "未知")
                    actual = settlement.get("actualTotal") if "actualTotal" in settlement else (saved_record.get("actualTotal") if isinstance(saved_record, dict) else "未知")
                    print(f"💾 [Brain归档成功] 成交价={clearing} | 实际价值={actual}")
                except Exception:
                    pass

        # 5. 组装 Tactical HUD 规范数据包
        p20, p80 = decision["valRange"]
        p20_str = self.format_w(p20) if isinstance(p20, (int, float)) else str(p20)
        p80_str = self.format_w(p80) if isinstance(p80, (int, float)) else str(p80)

        payload = {
            "round": session_ctx["round"],
            "timer": obs.timer,
            "sessionState": fsm_res["state"],
            "solverStatus": decision["solverStatus"],
            "diagnosticOnly": decision.get("diagnosticOnly", False),
            "valP50": self.format_w(decision["valP50"]),
            "valRange": f"区间: {p20_str} ~ {p80_str}",
            "leaderBid": self.format_w(session_ctx["leaderBid"]) if session_ctx["leaderBid"] > 0 else "0 W",
            "leaderBidSub": f"领跑: {session_ctx['leaderName'] or '暂无'}" if session_ctx["leaderBid"] > 0 else "等待出价...",
            "targetProfitLine": self.format_w(decision["targetProfitLine"]),
            "globalProfitLine": self.format_w(decision["globalProfitLine"]),
            "marginalChaseLine": self.format_w(decision["marginalChaseLine"]),
            "marketRatioEst": decision["marketRatioEst"],
            "actionDirective": decision["actionDirective"],
            "actionReason": decision["actionReason"],
            "entryGrade": decision["entryGrade"],
            "isFold": decision.get("isFold", False),
            "myName": session_ctx.get("myName", "玩家本人"),
            "myBid": self.format_w(session_ctx.get("myBid", 0)),
            "opponents": session_ctx.get("opponents", []),
            "roundTimeline": session_ctx.get("roundTimeline", {}),
            "costs": session_ctx.get("costs", {}),
            # 附带完整原始推演与物理事实字段供前端 Shared JS Core 实时精算
            "q": session_ctx.get("q"),
            "totalItems": session_ctx.get("totalItems"),
            "avg": session_ctx.get("avg"),
            "goldAvg": session_ctx.get("goldAvg"),
            "purpleAvg": session_ctx.get("purpleAvg"),
            "blueAvg": session_ctx.get("blueAvg"),
            "greenAvg": session_ctx.get("greenAvg"),
            "whiteAvg": session_ctx.get("whiteAvg"),
            "redAvg": session_ctx.get("redAvg"),
            "purple": session_ctx.get("purple"),
            "purpleCount": session_ctx.get("purpleCount"),
            "goldCount": session_ctx.get("goldCount"),
            "blueCount": session_ctx.get("blueCount"),
            "knownGold": session_ctx.get("knownGold", []),
            "knownPurple": session_ctx.get("knownPurple", []),
            "knownRed": session_ctx.get("knownRed", []),
            "totalGrids": session_ctx.get("totalGrids"),
            "venue": session_ctx.get("venue"),
            "boxType": session_ctx.get("boxType"),
            "box": session_ctx.get("box"),
            "fieldCondition": session_ctx.get("fieldCondition"),
            "character": session_ctx.get("character"),
            "lobbyToolGroup": session_ctx.get("lobbyToolGroup"),
            "solverToolGroup": session_ctx.get("solverToolGroup") or "group1"
        }

        return payload

def math_isnan(v):
    return v != v
