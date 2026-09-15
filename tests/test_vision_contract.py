"""
PHASE 3 Automated Test Suite: Vision Observation Contract
验证：
  1. VisionObservation 数据契约模型规范与序列化/反序列化
  2. from_pipeline_context 转换完整性 (Round, Timer, Intel, 4-player Bids, Settlement)
  3. 契约校验器 validate() 对异常数据的拦截
  4. NTEVisionPipeline.process_frame_observation 对真实关键帧的契约输出
"""

import os
import sys
import unittest
import numpy as np
import cv2

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
sys.path.insert(0, CORE_DIR)

from vision_contract import VisionObservation, VisionIntel, VisionBids, VisionSettlement
from vision_pipeline import NTEVisionPipeline

class TestVisionContract(unittest.TestCase):
    def test_vision_observation_defaults_and_serialization(self):
        obs = VisionObservation(
            round=2,
            timer=12,
            venue="中级场 · 珊瑚场",
            box="琉璃宝箱 · 宝石类概率提升",
            fieldCondition="dark"
        )
        d = obs.to_dict()
        self.assertEqual(d["round"], 2)
        self.assertEqual(d["timer"], 12)
        self.assertEqual(d["venue"], "中级场 · 珊瑚场")
        self.assertEqual(d["box"], "琉璃宝箱 · 宝石类概率提升")
        self.assertEqual(d["fieldCondition"], "dark")
        self.assertIn("intel", d)
        self.assertIn("bids", d)
        self.assertIn("settlement", d)

        valid, errs = obs.validate()
        self.assertTrue(valid, f"Validation failed: {errs}")

    def test_from_pipeline_context_conversion(self):
        mock_ctx = {
            "round": 3,
            "timer": 8,
            "venue": "中级场 · 珊瑚场",
            "box": "未知箱型",
            "fieldCondition": "extraIntel",
            "goldAvg": 33538,
            "q": 9,
            "myBid": 300000,
            "myName": "玩家本人",
            "currentLeaderBid": 350000,
            "leaderName": "对手1",
            "isMyLead": False,
            "opponents": [
                {"slot": 2, "name": "对手1", "bid": 350000},
                {"slot": 3, "name": "对手2", "bid": 200000},
                {"slot": 4, "name": "对手3", "bid": 150000}
            ],
            "knownPurple": ["拈花小像", "金角月芒"],
            "knownGold": ["万有星仪"]
        }

        obs = VisionObservation.from_pipeline_context(mock_ctx, frame_index=42, resolution=(1920, 1080))
        self.assertEqual(obs.frameIndex, 42)
        self.assertEqual(obs.sourceResolution, (1920, 1080))
        self.assertEqual(obs.round, 3)
        self.assertEqual(obs.intel.type, "goldAvg")
        self.assertEqual(obs.intel.goldAvg, 33538)
        self.assertEqual(obs.intel.q, 9)
        self.assertEqual(obs.intel.knownPurple, ["拈花小像", "金角月芒"])
        self.assertEqual(obs.intel.knownGold, ["万有星仪"])
        self.assertEqual(obs.bids.myBid, 300000)
        self.assertEqual(obs.bids.leaderBid, 350000)
        self.assertEqual(obs.bids.leaderName, "对手1")
        self.assertFalse(obs.bids.isMyLead)
        self.assertEqual(len(obs.bids.opponents), 3)

        valid, errs = obs.validate()
        self.assertTrue(valid, f"Validation failed: {errs}")

    def test_validation_errors_detection(self):
        # 错误轮次与负数出价拦截
        invalid_obs = VisionObservation(
            round=6,
            timer=-5,
            bids=VisionBids(myBid=-100, leaderBid=-500)
        )
        valid, errs = invalid_obs.validate()
        self.assertFalse(valid)
        self.assertIn("Invalid round: 6", errs)
        self.assertIn("Invalid timer: -5", errs)
        self.assertIn("Invalid myBid: -100", errs)
        self.assertIn("Invalid leaderBid: -500", errs)

    def test_pipeline_produces_contract_observation(self):
        pipeline = NTEVisionPipeline()
        # 创建空白测试图 (1080p)
        dummy_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        obs = pipeline.process_frame_observation(dummy_frame, frame_index=1)
        self.assertIsInstance(obs, VisionObservation)
        self.assertEqual(obs.sourceResolution, (1920, 1080))
        self.assertTrue(1 <= obs.round <= 5)
        valid, errs = obs.validate()
        self.assertTrue(valid, f"Validation errors: {errs}")

if __name__ == "__main__":
    unittest.main()
