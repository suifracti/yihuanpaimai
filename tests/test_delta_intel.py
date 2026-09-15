"""
PHASE 4 Automated Test Suite: Delta Intel Engine
验证：
  1. DeltaIntelManager 流式状态累积与轮次推进
  2. 增量情报 (Q, GoldAvg, Grids, Shapes) 差异捕获与 intelEvents 结构化记录
  3. Sunk Cost 随轮次递增与 Future Incremental Cost 动态更新
  4. 结算事件捕获与完整 sessionContext 构造
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
sys.path.insert(0, CORE_DIR)

from vision_contract import VisionObservation, VisionIntel, VisionBids, VisionSettlement
from delta_intel import DeltaIntelManager

class TestDeltaIntel(unittest.TestCase):
    def test_streaming_round_and_intel_progression(self):
        manager = DeltaIntelManager(entry_cost=5000)
        
        # Frame 1 (Round 1: 发现 Q=9)
        obs1 = VisionObservation(
            round=1,
            timer=14,
            venue="shanhu",
            boxType="standard",
            intel=VisionIntel(type="q", q=9)
        )
        res1 = manager.process_observation(obs1)
        self.assertTrue(res1["deltaDetected"])
        ctx1 = res1["sessionContext"]
        self.assertEqual(ctx1["q"], 9)
        self.assertEqual(ctx1["costs"]["sunkCost"], 5000)
        self.assertEqual(len(ctx1["intelEvents"]), 1)
        self.assertEqual(ctx1["intelEvents"][0]["round"], 1)
        self.assertEqual(ctx1["intelEvents"][0]["toolType"], "q")
        self.assertEqual(ctx1["intelEvents"][0]["incrementalCost"], 0)

        # Frame 2 (Round 2: 发现均价 33538，轮次推进但无额外付费)
        obs2 = VisionObservation(
            round=2,
            timer=10,
            venue="shanhu",
            boxType="standard",
            intel=VisionIntel(type="goldAvg", q=9, goldAvg=33538)
        )
        res2 = manager.process_observation(obs2)
        self.assertTrue(res2["deltaDetected"])
        ctx2 = res2["sessionContext"]
        self.assertEqual(ctx2["round"], 2)
        self.assertEqual(ctx2["goldAvg"], 33538)
        self.assertIsNone(ctx2["avg"])
        # Sunk cost 保持 5000 (轮次推进不自动收费)
        self.assertEqual(ctx2["costs"]["sunkCost"], 5000)
        self.assertEqual(len(ctx2["intelEvents"]), 2)
        self.assertEqual(ctx2["intelEvents"][1]["round"], 2)
        self.assertEqual(ctx2["intelEvents"][1]["toolType"], "goldAvg")
        self.assertEqual(ctx2["intelEvents"][1]["incrementalCost"], 0)

        # Frame 3 (Round 3: 识别已知藏品)
        obs3 = VisionObservation(
            round=3,
            timer=8,
            venue="shanhu",
            boxType="standard",
            intel=VisionIntel(
                type="shape",
                q=9,
                goldAvg=33538,
                knownPurple=["拈花小像", "金角月芒"],
                knownGold=["万有星仪"]
            )
        )
        res3 = manager.process_observation(obs3)
        self.assertTrue(res3["deltaDetected"])
        ctx3 = res3["sessionContext"]
        self.assertEqual(ctx3["round"], 3)
        self.assertEqual(ctx3["costs"]["sunkCost"], 5000)
        self.assertEqual(ctx3["knownPurple"], ["拈花小像", "金角月芒"])
        self.assertEqual(ctx3["knownGold"], ["万有星仪"])
        self.assertEqual(len(ctx3["intelEvents"]), 3)
        self.assertEqual(ctx3["intelEvents"][2]["incrementalCost"], 0)

    def test_settlement_detection(self):
        manager = DeltaIntelManager()
        obs_settle = VisionObservation(
            round=5,
            settlement=VisionSettlement(
                isSettlement=True,
                clearingPrice=450000,
                actualTotal=880000,
                profit=430000,
                items=[{"name": "乔望尼金雕像", "price": 271827}]
            )
        )
        res = manager.process_observation(obs_settle)
        self.assertTrue(res["deltaDetected"])
        ctx = res["sessionContext"]
        self.assertTrue(ctx["isSettlement"])
        self.assertEqual(ctx["settlementData"]["clearingPrice"], 450000)
        self.assertEqual(ctx["settlementData"]["actualTotal"], 880000)
        self.assertEqual(ctx["settlementData"]["profit"], 430000)

    def test_multi_tier_averages_and_total_items_separation(self):
        """验证 DeltaIntelManager 独立维护 goldAvg, purpleAvg, totalItems, 且不互相覆盖"""
        manager = DeltaIntelManager(entry_cost=5000)
        
        # 1. 发现全场总数量 totalItems=66, 高阶总件数 Q=39, 金色均价 61944
        obs1 = VisionObservation(
            round=1,
            venue="shanhu",
            character="达芙蒂尔",
            lobbyToolGroup="特供大型藏品的仪器组",
            solverToolGroup="group1",
            intel=VisionIntel(type="goldAvg", totalItems=66, q=39, goldAvg=61944)
        )
        res1 = manager.process_observation(obs1)
        ctx1 = res1["sessionContext"]
        self.assertEqual(ctx1["totalItems"], 66)
        self.assertEqual(ctx1["q"], 39)
        self.assertEqual(ctx1["goldAvg"], 61944)
        self.assertIsNone(ctx1["avg"])
        self.assertIsNone(ctx1["purpleAvg"])
        self.assertEqual(ctx1["character"], "达芙蒂尔")
        self.assertEqual(ctx1["lobbyToolGroup"], "特供大型藏品的仪器组")
        self.assertEqual(ctx1["solverToolGroup"], "group1")

        # 2. 发现紫色均价 3904 与紫色件数 25 (金色均价与 Q 必须保持，不得被覆盖)
        obs2 = VisionObservation(
            round=2,
            intel=VisionIntel(type="purpleAvg", purpleAvg=3904, purpleCount=25)
        )
        res2 = manager.process_observation(obs2)
        ctx2 = res2["sessionContext"]
        self.assertEqual(ctx2["totalItems"], 66, "totalItems must not be cleared")
        self.assertEqual(ctx2["q"], 39, "q must not be cleared")
        self.assertEqual(ctx2["goldAvg"], 61944, "goldAvg must NOT be overwritten by purpleAvg")
        self.assertEqual(ctx2["purpleAvg"], 3904, "purpleAvg must be correctly captured")
        self.assertEqual(ctx2["purpleCount"], 25, "purpleCount must be 25")
        self.assertIsNone(ctx2["blueAvg"], "unknown quality avg must remain None")


if __name__ == "__main__":
    unittest.main()
