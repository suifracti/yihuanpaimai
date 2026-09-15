"""
Neverness to Everness (异环) - 增量情报管理与流式状态机 (Delta Intel Engine - v0.65)

核心功能：
  1. 接收 VisionObservation 流式输入
  2. 差异对比检测增量情报（轮次跳变、均价揭晓、Q揭晓、藏品形状识别）
  3. 自动生成并记录严格的 intelEvent (before / observed / after 熵变与决策漂移)
  4. 沉没成本与未来成本动态累加 (sunkCost, futureIncrementalCost)
  5. 维护当前对局全生命周期实时上下文 (Session Context)
"""

import time
import math
from typing import Dict, Any, List, Optional, Tuple
from vision_contract import VisionObservation

class DeltaIntelManager:
    def __init__(self, entry_cost: int = 5000):
        self.entry_cost = entry_cost
        self.reset_session()

    def reset_session(self):
        """重置对局上下文"""
        self.session_id = f"session_{int(time.time())}"
        self.current_round = 1
        self.venue = "shanhu"
        self.box_type = "standard"
        self.box = None
        self.field_condition = "standard"
        self.character = None
        self.lobby_tool_group = None
        self.solver_tool_group = "group1"
        
        self.q = None
        self.total_items = None
        self.avg = None
        self.gold_avg = None
        self.purple_avg = None
        self.blue_avg = None
        self.green_avg = None
        self.white_avg = None
        self.purple_count = None
        self.gold_count = None
        self.blue_count = None
        self.green_count = None
        self.white_count = None
        self.red_count = None
        self.total_grids = None
        self.gold_grid = None
        self.purple_grid = None
        self.blue_grid = None
        self.green_grid = None
        self.white_grid = None
        self.red_grid = None
        self.known_gold = []
        self.known_purple = []
        self.known_red = []

        self.my_bid = 0
        self.leader_bid = 0
        self.leader_name = None
        self.is_my_lead = False
        self.opponents = []

        self.sunk_cost = self.entry_cost
        self.future_incremental_cost = 0 # 真实事件驱动，无付费事件时不预设未来扣费
        
        self.intel_events: List[Dict[str, Any]] = []
        self.round_timeline: Dict[int, Dict[str, Any]] = {}
        self.last_observation: Optional[VisionObservation] = None
        self.is_settled = False
        self.settlement_data: Optional[Dict[str, Any]] = None

    def process_observation(self, obs: VisionObservation, solver_bridge=None) -> Dict[str, Any]:
        """
        接收一帧 VisionObservation，检测增量情报并更新 session
        :param obs: 标准化视觉观测
        :param solver_bridge: 可选的求解器适配器（用于计算熵变与决策类）
        :return: 差异与更新事件字典
        """
        delta_detected = False
        delta_details = []

        # 1. 基础局况更新
        venue = getattr(obs, "venue", None)
        if venue and venue != "unknown" and venue != self.venue:
            self.venue = venue
            delta_detected = True
            delta_details.append(f"venue -> {self.venue}")

        box = getattr(obs, "box", None)
        if box and box != "未知箱型" and box != self.box:
            self.box = box
            delta_detected = True
            delta_details.append(f"box -> {self.box}")

        box_type = getattr(obs, "boxType", getattr(obs, "box_type", None))
        if box_type and box_type != "unknown" and box_type != self.box_type:
            self.box_type = box_type
            delta_detected = True
            delta_details.append(f"box_type -> {self.box_type}")

        field_condition = getattr(obs, "fieldCondition", getattr(obs, "field_condition", None))
        if field_condition and field_condition != "unknown" and field_condition != self.field_condition:
            self.field_condition = field_condition
            delta_detected = True
            delta_details.append(f"field_condition -> {self.field_condition}")

        char = getattr(obs, "character", None)
        if char and char != self.character:
            self.character = char

        lobby_tool = getattr(obs, "lobbyToolGroup", None)
        if lobby_tool and lobby_tool != self.lobby_tool_group:
            self.lobby_tool_group = lobby_tool

        solver_tool = getattr(obs, "solverToolGroup", getattr(obs, "toolGroup", None))
        if solver_tool and solver_tool != self.solver_tool_group:
            self.solver_tool_group = solver_tool

        # 2. 轮次推进 (进入下一轮本身不收费，成本仅由真实付费事件驱动)
        if obs.round > self.current_round:
            self.current_round = obs.round
            delta_detected = True
            delta_details.append(f"round_advance -> R{self.current_round}")

        # 3. 动态公开情报检测
        intel_changed = False
        observed_delta = {}

        if obs.intel.totalItems is not None and obs.intel.totalItems != self.total_items:
            observed_delta["totalItems"] = obs.intel.totalItems
            self.total_items = obs.intel.totalItems
            intel_changed = True

        if obs.intel.q is not None and obs.intel.q != self.q:
            observed_delta["q"] = obs.intel.q
            self.q = obs.intel.q
            intel_changed = True

        if obs.intel.goldAvg is not None and obs.intel.goldAvg != self.gold_avg:
            observed_delta["goldAvg"] = obs.intel.goldAvg
            self.gold_avg = obs.intel.goldAvg
            intel_changed = True

        if obs.intel.purpleAvg is not None and obs.intel.purpleAvg != self.purple_avg:
            observed_delta["purpleAvg"] = obs.intel.purpleAvg
            self.purple_avg = obs.intel.purpleAvg
            intel_changed = True

        if obs.intel.blueAvg is not None and obs.intel.blueAvg != self.blue_avg:
            observed_delta["blueAvg"] = obs.intel.blueAvg
            self.blue_avg = obs.intel.blueAvg
            intel_changed = True

        purple_cnt = obs.intel.purpleCount if obs.intel.purpleCount is not None else obs.intel.purple
        if purple_cnt is not None and purple_cnt != self.purple_count:
            observed_delta["purple"] = purple_cnt
            self.purple_count = purple_cnt
            intel_changed = True

        if obs.intel.goldCount is not None and obs.intel.goldCount != self.gold_count:
            observed_delta["goldCount"] = obs.intel.goldCount
            self.gold_count = obs.intel.goldCount
            intel_changed = True

        if obs.intel.blueCount is not None and obs.intel.blueCount != self.blue_count:
            observed_delta["blueCount"] = obs.intel.blueCount
            self.blue_count = obs.intel.blueCount
            intel_changed = True

        if obs.intel.greenCount is not None and obs.intel.greenCount != self.green_count:
            observed_delta["greenCount"] = obs.intel.greenCount
            self.green_count = obs.intel.greenCount
            intel_changed = True

        if obs.intel.whiteCount is not None and obs.intel.whiteCount != self.white_count:
            observed_delta["whiteCount"] = obs.intel.whiteCount
            self.white_count = obs.intel.whiteCount
            intel_changed = True

        if obs.intel.redCount is not None and obs.intel.redCount != self.red_count:
            observed_delta["redCount"] = obs.intel.redCount
            self.red_count = obs.intel.redCount
            intel_changed = True

        for g_field, g_attr in [
            ("goldGrid", "gold_grid"),
            ("purpleGrid", "purple_grid"),
            ("blueGrid", "blue_grid"),
            ("greenGrid", "green_grid"),
            ("whiteGrid", "white_grid"),
            ("redGrid", "red_grid"),
        ]:
            val = getattr(obs.intel, g_field, None)
            if val is not None and val != getattr(self, g_attr):
                observed_delta[g_field] = val
                setattr(self, g_attr, val)
                intel_changed = True

        if obs.intel.totalGrids is not None and obs.intel.totalGrids != self.total_grids:
            observed_delta["totalGrids"] = obs.intel.totalGrids
            self.total_grids = obs.intel.totalGrids
            intel_changed = True

        # 新增已知藏品检测
        new_gold = [x for x in obs.intel.knownGold if x not in self.known_gold]
        if new_gold:
            self.known_gold.extend(new_gold)
            observed_delta["newGold"] = new_gold
            intel_changed = True

        new_purple = [x for x in obs.intel.knownPurple if x not in self.known_purple]
        if new_purple:
            self.known_purple.extend(new_purple)
            observed_delta["newPurple"] = new_purple
            intel_changed = True

        new_red = [x for x in obs.intel.knownRed if x not in self.known_red]
        if new_red:
            self.known_red.extend(new_red)
            observed_delta["newRed"] = new_red
            intel_changed = True

        # 如果有新情报揭晓，构建持久化 intelEvent (无付费事件时 incrementalCost 为 0)
        if intel_changed:
            delta_detected = True
            event_cost = getattr(obs.intel, "cost", 0) or 0
            if event_cost > 0:
                self.sunk_cost += event_cost
            event_record = {
                "round": self.current_round,
                "toolType": obs.intel.type,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(obs.timestamp)),
                "before": {
                    "candidateStateCount": 0,
                    "stateEntropy": 0.0,
                    "shadowWidth": 0,
                    "decisionClass": "unknown"
                },
                "observed": observed_delta,
                "after": {
                    "candidateStateCount": 0,
                    "stateEntropy": 0.0,
                    "shadowWidth": 0,
                    "decisionClass": "unknown"
                },
                "decisionChanged": False,
                "incrementalCost": event_cost
            }
            self.intel_events.append(event_record)
            delta_details.append(f"intel_event -> {list(observed_delta.keys())}")

        # 4. 出价状态更新
        self.my_bid = obs.bids.myBid
        self.leader_bid = obs.bids.leaderBid
        self.leader_name = obs.bids.leaderName
        self.is_my_lead = obs.bids.isMyLead
        self.opponents = obs.bids.opponents

        # 5. 回合时序记录
        self.round_timeline[self.current_round] = {
            "round": self.current_round,
            "timer": obs.timer,
            "intel": {
                "q": self.q,
                "totalItems": self.total_items,
                "avg": self.avg,
                "goldAvg": self.gold_avg,
                "purpleAvg": self.purple_avg,
                "blueAvg": self.blue_avg,
                "greenAvg": self.green_avg,
                "whiteAvg": self.white_avg,
                "purple": self.purple_count,
                "purpleCount": self.purple_count,
                "goldCount": self.gold_count,
                "blueCount": self.blue_count,
                "greenCount": self.green_count,
                "whiteCount": self.white_count,
                "redCount": self.red_count,
                "totalGrids": self.total_grids,
                "goldGrid": self.gold_grid,
                "purpleGrid": self.purple_grid,
                "blueGrid": self.blue_grid,
                "greenGrid": self.green_grid,
                "whiteGrid": self.white_grid,
                "redGrid": self.red_grid,
                "knownGold": list(self.known_gold),
                "knownPurple": list(self.known_purple),
                "knownRed": list(self.known_red)
            },
            "bids": {
                "myBid": self.my_bid,
                "leaderBid": self.leader_bid,
                "leaderName": self.leader_name,
                "isMyLead": self.is_my_lead
            }
        }

        # 6. 结算大屏检测
        if obs.settlement.isSettlement and not self.is_settled:
            self.is_settled = True
            self.settlement_data = {
                "isSettlement": True,
                "clearingPrice": obs.settlement.clearingPrice,
                "actualTotal": obs.settlement.actualTotal,
                "profit": obs.settlement.profit,
                "items": obs.settlement.items
            }
            delta_detected = True
            delta_details.append("settlement_triggered")

        self.last_observation = obs

        return {
            "deltaDetected": delta_detected,
            "details": delta_details,
            "sessionContext": self.get_session_context()
        }

    def get_session_context(self) -> Dict[str, Any]:
        """获取供脑核/求解器/归档器使用的完整对局上下文"""
        return {
            "sessionId": self.session_id,
            "round": self.current_round,
            "venue": self.venue,
            "boxType": self.box_type,
            "box": self.box,
            "fieldCondition": self.field_condition,
            "character": self.character,
            "lobbyToolGroup": self.lobby_tool_group,
            "solverToolGroup": self.solver_tool_group,
            "toolGroup": self.solver_tool_group,
            "q": self.q,
            "totalItems": self.total_items,
            "avg": self.avg,
            "goldAvg": self.gold_avg,
            "purpleAvg": self.purple_avg,
            "blueAvg": self.blue_avg,
            "greenAvg": self.green_avg,
            "whiteAvg": self.white_avg,
            "purple": self.purple_count,
            "purpleCount": self.purple_count,
            "goldCount": self.gold_count,
            "blueCount": self.blue_count,
            "greenCount": self.green_count,
            "whiteCount": self.white_count,
            "redCount": self.red_count,
            "totalGrids": self.total_grids,
            "goldGrid": self.gold_grid,
            "purpleGrid": self.purple_grid,
            "blueGrid": self.blue_grid,
            "greenGrid": self.green_grid,
            "whiteGrid": self.white_grid,
            "redGrid": self.red_grid,
            "knownGold": list(self.known_gold),
            "knownPurple": list(self.known_purple),
            "knownRed": list(self.known_red),
            "costs": {
                "entry": self.entry_cost,
                "intel": max(0, self.sunk_cost - self.entry_cost),
                "sunkCost": self.sunk_cost,
                "futureIncrementalCost": self.future_incremental_cost,
                "total": self.sunk_cost + self.future_incremental_cost
            },
            "myBid": self.my_bid,
            "leaderBid": self.leader_bid,
            "leaderName": self.leader_name,
            "isMyLead": self.is_my_lead,
            "opponents": self.opponents,
            "intelEvents": list(self.intel_events),
            "roundTimeline": dict(self.round_timeline),
            "isSettlement": self.is_settled,
            "settlementData": self.settlement_data
        }
