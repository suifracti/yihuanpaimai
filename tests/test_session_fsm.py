"""
Neverness to Everness (异环) - 有限状态机 (FSM) 自动化测试套件
验证项目：
  1. 完整 7 阶段生命周期流转 (PREPARING -> LOADING -> AUCTION_R1 -> AUCTION_ACTIVE -> SETTLEMENT -> POST_MATCH -> ARCHIVED -> PREPARING)
  2. R1 阶段接收 intel_observed (如达芙蒂尔 Q 事件)
  3. R2~R5 仅由 round_changed 推进，禁止绑定具体道具
  4. 低置信度情报暂存至 pending_evidence 机制
  5. SETTLEMENT 生成对局真值快照并在 POST_MATCH 阶段保留
  6. POST_MATCH 接收 cost_event 并通过 mark_archive_ready 触发原子归档 (成功与重试分支)
  7. 退出结算必须回到首页 PREPARING，禁止从 POST_MATCH / ARCHIVED 直接跳入新对局
  8. 多局连续流转与历史跃迁链条完整性
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
sys.path.insert(0, CORE_DIR)

from vision_contract import VisionObservation, VisionIntel, VisionBids, VisionSettlement
from session_fsm import AuctionSessionFSM, SessionState

class TestSessionFSM(unittest.TestCase):
    def setUp(self):
        self.fsm = AuctionSessionFSM()

    def test_initial_state(self):
        """验证初始状态为 PREPARING (兼容 IDLE)"""
        self.assertEqual(self.fsm.state, SessionState.PREPARING)
        self.assertEqual(self.fsm.state, SessionState.IDLE)
        self.assertEqual(self.fsm.current_round, 0)
        self.assertIsNone(self.fsm.session_id)

    def test_full_7_stage_lifecycle(self):
        """验证标准 7 阶段全生命周期流转 (SETTLEMENT -> exit -> POST_MATCH -> archive -> PREPARING -> user starts match -> LOADING)"""
        # 1. 首页 PREPARING -> LOADING (用户在首页点击开始游戏)
        self.fsm.trigger_match_start(venue="shanhu")
        self.assertEqual(self.fsm.state, SessionState.LOADING)
        self.assertIsNotNone(self.fsm.session_id)

        # 2. LOADING -> AUCTION_R1 (收到 R1 画面)
        obs_r1 = VisionObservation(round=1, timer=15, venue="shanhu")
        res_r1 = self.fsm.handle_observation(obs_r1)
        self.assertEqual(self.fsm.state, SessionState.AUCTION_R1)
        self.assertEqual(self.fsm.current_round, 1)

        # 3. AUCTION_R1 -> AUCTION_ACTIVE (轮次跃迁至 R2)
        obs_r2 = VisionObservation(round=2, timer=14, venue="shanhu")
        self.fsm.handle_observation(obs_r2)
        self.assertEqual(self.fsm.state, SessionState.AUCTION_ACTIVE)
        self.assertEqual(self.fsm.current_round, 2)

        # 4. AUCTION_ACTIVE 内部推进 (R3 -> R4 -> R5)
        for r in [3, 4, 5]:
            obs_rx = VisionObservation(round=r, timer=10, venue="shanhu")
            self.fsm.handle_observation(obs_rx)
            self.assertEqual(self.fsm.state, SessionState.AUCTION_ACTIVE)
            self.assertEqual(self.fsm.current_round, r)

        # 5. AUCTION_ACTIVE -> SETTLEMENT (检测到结算大屏)
        obs_settle = VisionObservation(
            round=5,
            settlement=VisionSettlement(
                isSettlement=True,
                clearingPrice=454444,
                actualTotal=972970,
                profit=518526,
                items=[{"name": "万有星仪", "quality": "gold", "price": 67571}]
            )
        )
        res_settle = self.fsm.handle_observation(obs_settle)
        self.assertEqual(self.fsm.state, SessionState.SETTLEMENT)
        self.assertTrue(res_settle["isSettlement"])
        self.assertTrue(res_settle["hasSnapshot"])
        self.assertIsNotNone(self.fsm.match_snapshot)
        self.assertEqual(self.fsm.match_snapshot["clearingPrice"], 454444)

        # 6. SETTLEMENT -> POST_MATCH (用户点击退出结算)
        obs_post = VisionObservation(
            round=0,
            settlement=VisionSettlement(isSettlement=False)
        )
        self.fsm.handle_observation(obs_post)
        self.assertEqual(self.fsm.state, SessionState.POST_MATCH)
        # 验证快照草稿依然完整保留在内存中
        self.assertIsNotNone(self.fsm.match_snapshot)
        self.assertEqual(self.fsm.match_snapshot["actualTotal"], 972970)

        # 7. POST_MATCH 阶段处理真实扣费事件 (接口保留)
        cost_event = {"restockFee": 45000, "itemsRestocked": 3}
        self.fsm.handle_cost_event(cost_event)
        self.assertEqual(self.fsm.realized_cost_event, cost_event)
        self.assertEqual(self.fsm.match_snapshot["realizedCost"], cost_event)
        self.assertEqual(self.fsm.state, SessionState.POST_MATCH)

        # 8. POST_MATCH -> ARCHIVED (写入成功)
        archived_ok = self.fsm.mark_archive_ready(write_success=True)
        self.assertTrue(archived_ok)
        self.assertEqual(self.fsm.state, SessionState.ARCHIVED)

        # 9. ARCHIVED -> PREPARING (返回首页大厅就绪)
        obs_lobby = VisionObservation(round=0, settlement=VisionSettlement(isSettlement=False))
        self.fsm.handle_observation(obs_lobby)
        self.assertEqual(self.fsm.state, SessionState.PREPARING)

    def test_strict_home_screen_loop(self):
        """验证结算后必须回到首页 PREPARING，禁止跳过首页直接进入新对局"""
        # 对局进行中并结算
        self.fsm.handle_observation(VisionObservation(round=1, venue="shanhu"))
        self.fsm.handle_observation(VisionObservation(round=5, settlement=VisionSettlement(isSettlement=True)))
        self.assertEqual(self.fsm.state, SessionState.SETTLEMENT)

        # 点击退出 -> POST_MATCH
        self.fsm.handle_observation(VisionObservation(round=0, settlement=VisionSettlement(isSettlement=False)))
        self.assertEqual(self.fsm.state, SessionState.POST_MATCH)

        # 归档成功 -> ARCHIVED
        self.fsm.mark_archive_ready(True)
        self.assertEqual(self.fsm.state, SessionState.ARCHIVED)

        # 归档后回到首页大厅 -> PREPARING
        self.fsm.handle_observation(VisionObservation(round=0, settlement=VisionSettlement(isSettlement=False)))
        self.assertEqual(self.fsm.state, SessionState.PREPARING)

        # 必须在 PREPARING 下用户点击开始匹配才能进入 LOADING
        self.fsm.trigger_match_start(venue="haiwan")
        self.assertEqual(self.fsm.state, SessionState.LOADING)

    def test_r1_intel_observation(self):
        """验证 R1 阶段能够正确接收 intel_observed (如达芙蒂尔开局 Q)"""
        obs_r1_init = VisionObservation(round=1, timer=15, venue="shanhu")
        self.fsm.handle_observation(obs_r1_init)
        self.assertEqual(self.fsm.state, SessionState.AUCTION_R1)

        # R1 中途捕获达芙蒂尔 Q=15
        obs_r1_intel = VisionObservation(
            round=1,
            timer=12,
            intel=VisionIntel(type="q", q=15, confidence=0.95, rawText="高价值总件数15")
        )
        res = self.fsm.handle_observation(obs_r1_intel)
        self.assertEqual(self.fsm.state, SessionState.AUCTION_R1)
        self.assertEqual(self.fsm.current_round, 1)
        self.assertEqual(res["confirmedIntelCount"], 1)
        self.assertEqual(self.fsm.confirmed_intel[0]["q"], 15)

    def test_low_confidence_intel_buffering(self):
        """验证低置信度情报存入 pending_evidence 缓冲区，不直接丢弃"""
        obs_r2 = VisionObservation(round=2, timer=14)
        self.fsm.handle_observation(obs_r2)

        # 模糊识别 (置信度 0.5)
        obs_blur = VisionObservation(
            round=2,
            timer=10,
            intel=VisionIntel(type="goldAvg", goldAvg=67571, confidence=0.5, rawText="均价模糊")
        )
        res = self.fsm.handle_observation(obs_blur)
        self.assertEqual(res["pendingEvidenceCount"], 1)
        self.assertEqual(res["confirmedIntelCount"], 0)
        self.assertEqual(len(self.fsm.pending_evidence), 1)
        self.assertEqual(self.fsm.pending_evidence[0]["goldAvg"], 67571)

        # 随后清晰帧确认 (置信度 0.9)
        obs_clear = VisionObservation(
            round=2,
            timer=8,
            intel=VisionIntel(type="goldAvg", goldAvg=67571, confidence=0.95, rawText="均价67571")
        )
        res2 = self.fsm.handle_observation(obs_clear)
        self.assertEqual(res2["confirmedIntelCount"], 1)

    def test_archive_retry_in_post_match(self):
        """验证 POST_MATCH 阶段归档失败时不发生错误跃迁，允许安全重试"""
        # 进入结算并退出
        self.fsm.handle_observation(VisionObservation(round=5, settlement=VisionSettlement(isSettlement=True)))
        self.assertEqual(self.fsm.state, SessionState.SETTLEMENT)
        self.fsm.handle_observation(VisionObservation(round=0, settlement=VisionSettlement(isSettlement=False)))
        self.assertEqual(self.fsm.state, SessionState.POST_MATCH)

        # 模拟磁盘写入失败 (write_success=False)
        retry_res = self.fsm.mark_archive_ready(write_success=False)
        self.assertFalse(retry_res)
        self.assertEqual(self.fsm.state, SessionState.POST_MATCH)

        # 重试成功
        success_res = self.fsm.mark_archive_ready(write_success=True)
        self.assertTrue(success_res)
        self.assertEqual(self.fsm.state, SessionState.ARCHIVED)

    def test_consecutive_sessions(self):
        """验证连续多局对局的 session_id 隔离与首页回到 PREPARING 流程"""
        # 第 1 局
        obs1 = VisionObservation(round=1, venue="shanhu")
        self.fsm.handle_observation(obs1)
        sid1 = self.fsm.session_id
        self.assertEqual(self.fsm.state, SessionState.AUCTION_R1)

        # 结算并归档 -> 回到首页 PREPARING
        self.fsm.handle_observation(VisionObservation(round=5, settlement=VisionSettlement(isSettlement=True)))
        self.fsm.handle_observation(VisionObservation(round=0, settlement=VisionSettlement(isSettlement=False)))
        self.fsm.mark_archive_ready(True)
        self.assertEqual(self.fsm.state, SessionState.ARCHIVED)
        self.fsm.handle_observation(VisionObservation(round=0, settlement=VisionSettlement(isSettlement=False)))
        self.assertEqual(self.fsm.state, SessionState.PREPARING)

        # 第 2 局开启 (在首页开始新游戏并收到新 R1 观测)
        obs2 = VisionObservation(round=1, venue="haiwan")
        self.fsm.handle_observation(obs2)
        sid2 = self.fsm.session_id
        self.assertEqual(self.fsm.state, SessionState.AUCTION_R1)
        self.assertNotEqual(sid1, sid2)

if __name__ == "__main__":
    unittest.main()
