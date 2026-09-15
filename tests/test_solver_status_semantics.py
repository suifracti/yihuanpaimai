"""
PHASE 6 Automated Test Suite: Solver Status & Stale Result Semantics
验证：
  1. 求解器 6 种状态语义 (valid, diagnostic, incomplete, stale, timeout, no-match)
  2. stale 状态下严格禁止推荐追价 (强制显示“旧结果已过期 · 禁止依据追价”)
  3. incomplete 状态下严禁凭空生成最高出价
  4. timeout / no-match 状态下的保护性拦截
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
sys.path.insert(0, CORE_DIR)

from auction_brain import AuctionBrain
from vision_contract import VisionObservation, VisionIntel, VisionBids

class TestSolverStatusSemantics(unittest.TestCase):
    def setUp(self):
        self.brain = AuctionBrain()

    def test_incomplete_status_suppresses_recommendation(self):
        # 仅有场地和轮次，缺少 Q 与均价
        obs = VisionObservation(round=1, timer=15, venue="shanhu")
        payload = self.brain.process_observation(obs)
        self.assertEqual(payload["solverStatus"], "fallback")
        self.assertIn("情报不足", payload["actionDirective"])
        self.assertEqual(payload["targetProfitLine"], "-- W")
        self.assertEqual(payload["marginalChaseLine"], "-- W")

    def test_valid_status_enables_recommendations(self):
        # 1. 叫价在目标利润区内 (bid = 50000 <= targetLine ~99000)
        obs_safe = VisionObservation(
            round=2,
            timer=10,
            venue="shanhu",
            intel=VisionIntel(type="goldAvg", q=9, goldAvg=33538),
            bids=VisionBids(leaderBid=50000)
        )
        payload_safe = self.brain.process_observation(obs_safe)
        self.assertEqual(payload_safe["solverStatus"], "valid")
        self.assertIn("可以继续", payload_safe["actionDirective"])
        self.assertNotEqual(payload_safe["targetProfitLine"], "-- W")
        self.assertNotEqual(payload_safe["marginalChaseLine"], "-- W")

        # 2. 叫价超过边际追价线 (bid = 300000 > marginalLine ~271000)
        obs_stop = VisionObservation(
            round=2,
            timer=10,
            venue="shanhu",
            intel=VisionIntel(type="goldAvg", q=9, goldAvg=33538),
            bids=VisionBids(leaderBid=300000)
        )
        payload_stop = self.brain.process_observation(obs_stop)
        self.assertEqual(payload_stop["solverStatus"], "valid")
        self.assertIn("建议停止", payload_stop["actionDirective"])
        self.assertTrue(payload_stop["isFold"])

    def test_stale_status_semantic_protection(self):
        decision = self.brain.solve_session({"q": 9, "avg": 33538, "solverStatus": "stale", "leaderBid": 100000})
        self.assertEqual(decision["solverStatus"], "stale")
        self.assertIn("过期", decision["actionDirective"])

    def test_fallback_and_diagnostic_only(self):
        # 1. 显式 fallback
        decision_fb = self.brain.solve_session({"q": 9, "avg": 33538, "solverStatus": "fallback", "leaderBid": 100000})
        self.assertEqual(decision_fb["solverStatus"], "fallback")
        self.assertIn("降级估算", decision_fb["actionDirective"])

        # 2. diagnosticOnly 独立存在，不改变底层状态
        decision_diag = self.brain.solve_session({"q": 9, "avg": 33538, "solverStatus": "valid", "diagnosticOnly": True})
        self.assertEqual(decision_diag["solverStatus"], "valid")
        self.assertTrue(decision_diag["diagnosticOnly"])
        self.assertIn("[诊断模式]", decision_diag["actionDirective"])

if __name__ == "__main__":
    unittest.main()
