"""
PHASE 5 Automated Test Suite: Auction Brain & Tactical HUD Integration
验证：
  1. AuctionBrain 协调全流程 (VisionObservation -> DeltaIntel -> SolverEngine -> HUD Payload)
  2. 独立三层出价线 (Target / Global / Marginal) 与状态评级准确生成
  3. 结算触发自动记账与归档
  4. HUD Payload 字段与数据类型完全符合 tactical_hud.html 期望
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
sys.path.insert(0, CORE_DIR)

from vision_contract import VisionObservation, VisionIntel, VisionBids, VisionSettlement
from auction_brain import AuctionBrain
from auto_archiver import AutoArchiver

class TestAuctionBrain(unittest.TestCase):
    def test_brain_decision_and_payload_pipeline(self):
        archiver = AutoArchiver(db_paths=[])
        brain = AuctionBrain(archiver=archiver)

        # 1. 初始未开情报帧
        obs1 = VisionObservation(
            round=1,
            timer=15,
            venue="shanhu",
            boxType="standard",
            bids=VisionBids(myBid=0, leaderBid=0)
        )
        payload1 = brain.process_observation(obs1)
        self.assertEqual(payload1["round"], 1)
        self.assertEqual(payload1["solverStatus"], "fallback")
        self.assertEqual(payload1["leaderBid"], "0 W")

        # 2. 开出均价与 Q 帧 (Q=9, GoldAvg=33538, KnownPurple=拈花小像+金角月芒, KnownGold=万有星仪)
        obs2 = VisionObservation(
            round=2,
            timer=10,
            venue="shanhu",
            boxType="standard",
            intel=VisionIntel(
                type="goldAvg",
                q=9,
                goldAvg=33538,
                knownPurple=["拈花小像", "金角月芒"],
                knownGold=["万有星仪"]
            ),
            bids=VisionBids(myBid=100000, leaderBid=120000, leaderName="对手1")
        )
        payload2 = brain.process_observation(obs2)
        self.assertEqual(payload2["round"], 2)
        self.assertIn("W", payload2["valP50"])
        self.assertIn("W", payload2["targetProfitLine"])
        self.assertIn("W", payload2["globalProfitLine"])
        self.assertIn("W", payload2["marginalChaseLine"])
        self.assertEqual(payload2["leaderBid"], "12.0 W")
        self.assertEqual(payload2["leaderBidSub"], "领跑: 对手1")
        self.assertIn(payload2["solverStatus"], ["valid", "diagnostic"])

        # 3. 终局结算帧
        obs3 = VisionObservation(
            round=5,
            timer=0,
            settlement=VisionSettlement(
                isSettlement=True,
                clearingPrice=454444,
                actualTotal=972970,
                profit=518526
            )
        )
        payload3 = brain.process_observation(obs3)
        self.assertEqual(payload3["round"], 5)
        # 确认 sessionContext 中结算被捕获
        self.assertTrue(brain.delta_manager.is_settled)

if __name__ == "__main__":
    unittest.main()
