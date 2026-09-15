"""
Neverness to Everness (异环) - 对局全生命周期有限状态机 (Session Lifecycle FSM - v0.65 Event Contract)

定位：
  本模块为对局宏观生命周期状态机，严格基于真实玩法流程与 FSM Event Contract 实现：
  [PREPARING] -> [LOADING] -> [AUCTION_R1] -> [AUCTION_ACTIVE] -> [SETTLEMENT] -> [POST_MATCH] -> [ARCHIVED] -> [PREPARING]

核心规则：
  1. 真实流程中结算界面仅有【退出】，退出后回到首页(PREPARING)，必须在首页重新开始游戏才能进入新对局。
  2. 严禁任何从 POST_MATCH / ARCHIVED 直接跳入 LOADING / 新对局的假设分支。
  3. R2~R5 仅由 round_changed 事件驱动，禁止与任何具体道具绑定。
  4. 成本模型严格事件驱动，不在此阶段硬编码 50k 或 45k。
  5. 低置信度情报放入 pending_evidence 缓冲区，不直接丢弃，待后续确认。
  6. SETTLEMENT 仅生成快照草稿，POST_MATCH 明确结束后通过 archive_ready 执行原子归档，归档后回到 PREPARING。
"""

import time
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from vision_contract import VisionObservation

class SessionState(str, Enum):
    PREPARING = "PREPARING"
    LOADING = "LOADING"
    AUCTION_R1 = "AUCTION_R1"
    AUCTION_ACTIVE = "AUCTION_ACTIVE"
    SETTLEMENT = "SETTLEMENT"
    POST_MATCH = "POST_MATCH"
    ARCHIVED = "ARCHIVED"

    # 兼容历史别名
    IDLE = "PREPARING"
    BIDDING_ROUND = "AUCTION_ACTIVE"

class AuctionSessionFSM:
    def __init__(self):
        self.state: SessionState = SessionState.PREPARING
        self.current_round: int = 0
        self.session_id: Optional[str] = None
        self._session_seq: int = 0
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.state_history: List[Tuple[float, SessionState, str]] = []
        
        # 增量情报与证据缓存
        self.pending_evidence: List[Dict[str, Any]] = []
        self.confirmed_intel: List[Dict[str, Any]] = []
        
        # 结算草稿快照
        self.match_snapshot: Optional[Dict[str, Any]] = None
        self.realized_cost_event: Optional[Dict[str, Any]] = None

    def _transition(self, to_state: SessionState, reason: str):
        prev = self.state
        self.state = to_state
        now = time.time()
        self.state_history.append((now, to_state, reason))

    def trigger_match_start(self, venue: str = "shanhu"):
        """用户在首页/大厅点击开始游戏 (PREPARING -> LOADING)"""
        if self.state == SessionState.PREPARING:
            now = time.time()
            self._session_seq += 1
            self.session_id = f"session_{int(now)}_{self._session_seq}"
            self.start_time = now
            self.current_round = 0
            self.pending_evidence.clear()
            self.confirmed_intel.clear()
            self.match_snapshot = None
            self.realized_cost_event = None
            self._transition(SessionState.LOADING, f"match_start_clicked (venue={venue})")

    def handle_cost_event(self, cost_payload: Dict[str, Any]):
        """接口保留：处理赛后真实支付/消耗事件 (POST_MATCH)"""
        if self.state == SessionState.POST_MATCH:
            self.realized_cost_event = cost_payload
            if self.match_snapshot is not None:
                self.match_snapshot["realizedCost"] = cost_payload

    def mark_archive_ready(self, write_success: bool = True) -> bool:
        """
        POST_MATCH / SETTLEMENT 阶段尝试原子归档
        成功 -> 跃迁至 ARCHIVED
        失败 -> 保持当前状态等待重试
        """
        if self.state in [SessionState.SETTLEMENT, SessionState.POST_MATCH]:
            if write_success:
                self._transition(SessionState.ARCHIVED, "archive_committed_success")
                return True
            else:
                # 写入失败保持当前状态重试
                return False
        return False

    def mark_archived(self):
        """向后兼容归档接口"""
        if self.state in [SessionState.SETTLEMENT, SessionState.POST_MATCH]:
            self.mark_archive_ready(True)

    def handle_observation(self, obs: VisionObservation) -> Dict[str, Any]:
        """
        根据视觉观测驱动状态机流转 (Event Contract)
        严格保证单向生命周期：
        PREPARING -> LOADING -> AUCTION_R1 -> AUCTION_ACTIVE -> SETTLEMENT -> POST_MATCH -> ARCHIVED -> PREPARING
        """
        now = time.time()

        # -------------------------------------------------------------
        # 1. 终局结算大屏事件判定 (SETTLEMENT)
        # -------------------------------------------------------------
        if obs.settlement.isSettlement:
            if self.state in [SessionState.PREPARING, SessionState.LOADING, SessionState.AUCTION_R1, SessionState.AUCTION_ACTIVE]:
                # 捕获并生成对局真值快照草稿
                self.end_time = now
                self.match_snapshot = {
                    "sessionId": self.session_id,
                    "clearingPrice": obs.settlement.clearingPrice,
                    "actualTotal": obs.settlement.actualTotal,
                    "profit": obs.settlement.profit,
                    "items": list(obs.settlement.items),
                    "confidence": obs.settlement.confidence,
                    "timestamp": now,
                    "realizedCost": self.realized_cost_event
                }
                self._transition(SessionState.SETTLEMENT, "settlement_detected")
            elif self.state == SessionState.SETTLEMENT and self.match_snapshot is not None:
                # 持续补充更新快照字段 (如后续帧提取到更完整的 items)
                if obs.settlement.clearingPrice is not None:
                    self.match_snapshot["clearingPrice"] = obs.settlement.clearingPrice
                if obs.settlement.actualTotal is not None:
                    self.match_snapshot["actualTotal"] = obs.settlement.actualTotal
                if obs.settlement.items:
                    self.match_snapshot["items"] = list(obs.settlement.items)

            return self._build_status_payload(is_settlement=True)

        # -------------------------------------------------------------
        # 2. 结算退出 -> 进入 POST_MATCH 阶段
        # -------------------------------------------------------------
        if self.state == SessionState.SETTLEMENT and not obs.settlement.isSettlement:
            self._transition(SessionState.POST_MATCH, "settlement_dismissed_to_post_match")
            return self._build_status_payload(is_settlement=False)

        # -------------------------------------------------------------
        # 3. 归档后回到首页/大厅 (ARCHIVED -> PREPARING)
        # -------------------------------------------------------------
        obs_round = obs.round if (1 <= obs.round <= 5) else 0

        if self.state == SessionState.ARCHIVED:
            # 结算归档后检测到大厅/空闲画面，自动重置回 PREPARING
            self._transition(SessionState.PREPARING, "session_reset_to_preparing")

        # -------------------------------------------------------------
        # 4. 局中竞拍轮次流转 (仅在 PREPARING / LOADING / R1 / ACTIVE 下推进)
        # -------------------------------------------------------------
        if obs_round >= 1:
            # 4.1 从首页 PREPARING 启动匹配进入 LOADING，并推进至 AUCTION_R1
            if self.state == SessionState.PREPARING:
                self.trigger_match_start(venue=obs.venue)
                if obs_round == 1:
                    self.current_round = 1
                    self._transition(SessionState.AUCTION_R1, "r1_detected")
                else:
                    self.current_round = obs_round
                    self._transition(SessionState.AUCTION_ACTIVE, f"advance_round_{obs_round}")

            elif self.state == SessionState.LOADING:
                if obs_round == 1:
                    self.current_round = 1
                    self._transition(SessionState.AUCTION_R1, "r1_detected")
                else:
                    self.current_round = obs_round
                    self._transition(SessionState.AUCTION_ACTIVE, f"advance_round_{obs_round}")

            # 4.2 从 AUCTION_R1 推进至 AUCTION_ACTIVE
            elif self.state == SessionState.AUCTION_R1:
                if obs_round >= 2:
                    self.current_round = obs_round
                    self._transition(SessionState.AUCTION_ACTIVE, f"round_changed_to_{obs_round}")

            # 4.3 AUCTION_ACTIVE 内部轮次推进 (R2..R5)
            elif self.state == SessionState.AUCTION_ACTIVE:
                if obs_round > self.current_round:
                    self.current_round = obs_round
                    self._transition(SessionState.AUCTION_ACTIVE, f"round_changed_to_{obs_round}")

            # 4.4 接收单轮内的新增情报 (AUCTION_R1 和 AUCTION_ACTIVE 均可接收)
            if self.state in [SessionState.AUCTION_R1, SessionState.AUCTION_ACTIVE]:
                self._process_intel_observation(obs)

        return self._build_status_payload(is_settlement=(self.state == SessionState.SETTLEMENT))

    def _process_intel_observation(self, obs: VisionObservation):
        """处理局内增量情报观测并管理 pending_evidence 缓冲区"""
        intel = obs.intel
        if not intel or intel.type == "none":
            return

        intel_record = {
            "round": self.current_round,
            "type": intel.type,
            "q": intel.q,
            "totalItems": intel.totalItems,
            "goldAvg": intel.goldAvg,
            "purpleAvg": intel.purpleAvg,
            "blueAvg": intel.blueAvg,
            "purple": intel.purple or getattr(intel, "purpleCount", None),
            "purpleCount": getattr(intel, "purpleCount", None) or intel.purple,
            "goldCount": getattr(intel, "goldCount", None),
            "blueCount": getattr(intel, "blueCount", None),
            "totalGrids": intel.totalGrids,
            "knownGold": list(intel.knownGold),
            "knownPurple": list(intel.knownPurple),
            "knownRed": list(intel.knownRed),
            "rawText": intel.rawText,
            "confidence": getattr(intel, "confidence", 1.0)
        }

        # 若置信度偏低，暂存至 pending_evidence 缓冲区供后续帧复核
        if intel_record["confidence"] < 0.7:
            self.pending_evidence.append(intel_record)
        else:
            self.confirmed_intel.append(intel_record)

    def reset(self):
        """显式重置状态机至 PREPARING (首页)"""
        self._transition(SessionState.PREPARING, "manual_reset")
        self.current_round = 0
        self.session_id = None
        self.start_time = 0.0
        self.end_time = 0.0
        self.pending_evidence.clear()
        self.confirmed_intel.clear()
        self.match_snapshot = None
        self.realized_cost_event = None

    def _build_status_payload(self, is_settlement: bool) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "round": self.current_round,
            "isSettlement": is_settlement,
            "sessionId": self.session_id,
            "pendingEvidenceCount": len(self.pending_evidence),
            "confirmedIntelCount": len(self.confirmed_intel),
            "hasSnapshot": self.match_snapshot is not None
        }
