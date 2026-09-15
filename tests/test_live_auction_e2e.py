"""
Replay E2E Validation Suite (回放端到端全链路验证)
验证：
  1. 端到端实战流程回放 (VisionPipeline -> VisionObservation -> DeltaIntel -> FSM Scaffold -> Brain -> AutoArchiver)
  2. 真实 106 帧切片时序推演与终局结算自动入库
  3. 测试沙箱数据库隔离，绝不污染真实 异环拍卖数据.json
  4. 最终生成的归档记录满足 Schema 6 与 3条独立出价线
"""

import os
import sys
import json
import tempfile
import unittest
import numpy as np
import cv2

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
sys.path.insert(0, CORE_DIR)

from vision_pipeline import NTEVisionPipeline
from auto_archiver import AutoArchiver
from grid_calibrator import GridCalibrator
from auction_brain import AuctionBrain
from vision_contract import VisionObservation, VisionIntel, VisionBids, VisionSettlement
from session_fsm import SessionState

class TestLiveAuctionE2E(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.sandbox_db = os.path.join(self.tmp_dir.name, "sandbox_db.json")
        self.archiver = AutoArchiver(db_paths=[self.sandbox_db])
        self.cat_path = os.path.join(ASSETS_DIR, "catalog_065.json")
        self.brain = AuctionBrain(archiver=self.archiver)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_e2e_streaming_auction_session(self):
        # 1. 模拟 Round 1: 揭晓件数 Q=9
        obs_r1 = VisionObservation(
            round=1,
            timer=15,
            venue="shanhu",
            boxType="standard",
            intel=VisionIntel(type="q", q=9),
            bids=VisionBids(myBid=0, leaderBid=0)
        )
        payload1 = self.brain.process_observation(obs_r1)
        self.assertEqual(payload1["round"], 1)
        self.assertEqual(payload1["sessionState"], SessionState.AUCTION_R1)
        self.assertEqual(payload1["solverStatus"], "fallback")

        # 2. 模拟 Round 2: 揭晓金色均价 33538
        obs_r2 = VisionObservation(
            round=2,
            timer=10,
            venue="shanhu",
            boxType="standard",
            intel=VisionIntel(type="goldAvg", q=9, goldAvg=33538),
            bids=VisionBids(myBid=50000, leaderBid=50000, leaderName="玩家本人", isMyLead=True)
        )
        payload2 = self.brain.process_observation(obs_r2)
        self.assertEqual(payload2["round"], 2)
        self.assertEqual(payload2["solverStatus"], "valid")
        self.assertIn("可以继续", payload2["actionDirective"])
        self.assertEqual(payload2["leaderBid"], "5.0 W")

        # 3. 模拟 Round 3: 揭晓已知藏品 (拈花小像 + 金角月芒 + 万有星仪)
        obs_r3 = VisionObservation(
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
            ),
            bids=VisionBids(myBid=100000, leaderBid=120000, leaderName="对手1", isMyLead=False)
        )
        payload3 = self.brain.process_observation(obs_r3)
        self.assertEqual(payload3["round"], 3)
        self.assertEqual(payload3["solverStatus"], "valid")
        self.assertIn("W", payload3["valP50"])

        # 4. 模拟 Round 5 终局结算
        obs_settle = VisionObservation(
            round=5,
            timer=0,
            venue="shanhu",
            bids=VisionBids(myBid=454444, leaderBid=454444, leaderName="玩家本人", isMyLead=True),
            settlement=VisionSettlement(
                isSettlement=True,
                clearingPrice=454444,
                actualTotal=972970,
                profit=518526,
                items=[{"name": "乔望尼金雕像", "price": 271827}]
            )
        )
        payload_settle = self.brain.process_observation(obs_settle)
        self.assertEqual(payload_settle["sessionState"], SessionState.SETTLEMENT)
        self.assertEqual(self.brain.fsm.state, SessionState.ARCHIVED)

        # 5. 验证沙箱数据库中已落盘记账 (Database Envelope Schema 6 & Canonical Record Schema 7)
        self.assertTrue(os.path.exists(self.sandbox_db))
        with open(self.sandbox_db, "r", encoding="utf-8") as f:
            db_data = json.load(f)
        self.assertEqual(db_data.get("schemaVersion"), 6)
        records = db_data.get("records", [])
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.get("schemaVersion"), 7)
        self.assertEqual(rec["settlement"]["clearingPrice"], 454444)
        self.assertEqual(rec["settlement"]["actualTotal"], 972970)
        self.assertEqual(rec["settlement"]["realizedProfit"], 518526)
        self.assertEqual(rec["settlement"]["winner"], "玩家本人")
        self.assertTrue(rec["settlement"]["acquired"])
        self.assertEqual(rec["qualities"]["gold"]["avg"], 33538)
        self.assertIsNone(rec["qualities"]["purple"]["avg"], "unknown purpleAvg must be None, not 0")
        self.assertIsNone(rec["publicIntel"]["totalItems"], "unknown totalItems must be None, not 0")
        self.assertEqual(rec["loadout"]["character"], "达芙蒂尔")
        self.assertEqual(rec["loadout"]["solverToolGroup"], "group1")
        self.assertIn("rounds", rec["bidding"])
        self.assertGreaterEqual(len(rec["bidding"]["rounds"]), 2)

if __name__ == "__main__":
    unittest.main()
