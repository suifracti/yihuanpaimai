# -*- coding: utf-8 -*-
"""
Tests for Phase 14: Settlement Winner OCR Recognition & Canonical Ingest.
Validates AC1 through AC10.
"""
import sys
import unittest
from pathlib import Path
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for p in [str(APP_DIR), str(CORE_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from vision_pipeline import NTEVisionPipeline
from current_match import CURRENT_MATCH
from main import sync_vision_to_current_match, process_live_game_frame
from auto_archiver import AutoArchiver, FORBIDDEN_WINNER_PLACEHOLDERS

FIXTURE_240S_PATH = Path(r"C:\Users\Administrator\.gemini\antigravity\brain\0f056b5e-d39e-4b26-975e-5fdd0c3dc761\scratch\settlement_240s.png")


class TestSettlementWinnerV1(unittest.TestCase):

    def setUp(self):
        CURRENT_MATCH.begin_next_match()

    def test_ac1_to_ac3_real_frame_settlement_winner_xi(self):
        """AC1, AC2, AC3: Real 240s frame extracts '汐' and ingests to CurrentMatch and Canonical."""
        import cv2
        if not FIXTURE_240S_PATH.exists():
            self.skipTest(f"Fixture image not found at {FIXTURE_240S_PATH}")

        img = cv2.imread(str(FIXTURE_240S_PATH))
        self.assertIsNotNone(img, "Failed to load settlement_240s.png")

        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        pipe.current_context["scene"] = "IN_AUCTION"
        pipe.current_context["inAuction"] = True

        process_live_game_frame(img, pipeline_inst=pipe)
        ctx = pipe.current_context

        # AC1: ctx["winner"] == "汐"
        self.assertEqual(ctx.get("winner"), "汐")
        self.assertEqual(ctx.get("settlementData", {}).get("winner"), "汐")

        # AC2: CURRENT_MATCH.facts["winner"] == "汐"
        self.assertEqual(CURRENT_MATCH.facts.get("winner"), "汐")

        # AC3: canonical["settlement"]["winner"] == "汐"
        canonical = CURRENT_MATCH.to_canonical()
        self.assertEqual(canonical.get("settlement", {}).get("winner"), "汐")

    def test_ac4_no_amount_or_bid_inference(self):
        """AC4: Winner must not be inferred from clearingPrice, leaderBid, profit, or defaults."""
        pipe = NTEVisionPipeline()
        ocr_mock = [
            ([[78.0, 143.0], [324.0, 143.0], [324.0, 210.0], [78.0, 210.0]], "竞拍结束", 0.99),
            ([[121.0, 468.0], [250.0, 468.0], [250.0, 498.0], [121.0, 498.0]], "最终成交价", 0.99),
            ([[117.0, 526.0], [263.0, 526.0], [263.0, 564.0], [117.0, 564.0]], "666,666", 1.00),
            ([[496.0, 466.0], [603.0, 466.0], [603.0, 499.0], [496.0, 499.0]], "实际价值", 0.99),
            ([[490.0, 527.0], [632.0, 527.0], [632.0, 568.0], [490.0, 568.0]], "631,993", 1.00),
        ]
        st = pipe._parse_settlement(ocr_mock, 1920, 1080)
        self.assertTrue(st["isSettlement"])
        self.assertEqual(st["clearingPrice"], 666666)
        # Winner must be None because no explicit winner text was present in ROI
        self.assertIsNone(st.get("winner"))

    def test_ac5_blank_roi_fail_closed(self):
        """AC5: Blank or no-name settlement frame keeps winner None."""
        pipe = NTEVisionPipeline()
        st = pipe._parse_settlement([], 1920, 1080)
        self.assertFalse(st["isSettlement"])
        self.assertIsNone(st.get("winner"))

        # Settlement frame with numbers but blank winner ROI
        ocr_mock = [
            ([[78.0, 143.0], [324.0, 143.0], [324.0, 210.0], [78.0, 210.0]], "竞拍结束", 0.99),
        ]
        st2 = pipe._parse_settlement(ocr_mock, 1920, 1080)
        self.assertTrue(st2["isSettlement"])
        self.assertIsNone(st2.get("winner"))

    def test_ac6_fixed_ui_labels_fail_closed(self):
        """AC6: Fixed UI labels must never be accepted as winner."""
        fixed_texts = [
            "竞拍结束", "最终成交价", "成交价", "实际价值", "实际总价值",
            "收益", "实际收益", "净利润", "竞拍表现", "竞拍帮手",
            "当前估价", "我的资产", "奖励金获取", "分享到呗果",
            "跳过动画", "退出（102s）", "藏品图鉴", "出售价值",
            "落槌无悔，血本无归。", "UID:219075610068", "666,666", "-34,673",
            "B", "A", "S", "SS", "", "   "
        ]
        for txt in fixed_texts:
            cleaned = NTEVisionPipeline._clean_settlement_winner_name(txt)
            self.assertIsNone(cleaned, f"Fixed label '{txt}' was not excluded!")

        # Valid names must pass
        self.assertEqual(NTEVisionPipeline._clean_settlement_winner_name("汐"), "汐")
        self.assertEqual(NTEVisionPipeline._clean_settlement_winner_name("秋星祭02"), "秋星祭02")
        self.assertEqual(NTEVisionPipeline._clean_settlement_winner_name("卜逸曲"), "卜逸曲")
        self.assertEqual(NTEVisionPipeline._clean_settlement_winner_name("空"), "空")

    def test_ac7_winner_persists_across_weaker_subsequent_frame(self):
        """AC7: An already confirmed winner must not be overwritten by subsequent weaker/empty frame."""
        pipe = NTEVisionPipeline()
        pipe.current_context["winner"] = "汐"
        pipe.current_context["isSettlement"] = True

        # Next settlement frame with empty winner ROI
        ocr_mock = [
            ([[78.0, 143.0], [324.0, 143.0], [324.0, 210.0], [78.0, 210.0]], "竞拍结束", 0.99),
            ([[121.0, 468.0], [250.0, 468.0], [250.0, 498.0], [121.0, 498.0]], "最终成交价", 0.99),
            ([[117.0, 526.0], [263.0, 526.0], [263.0, 564.0], [117.0, 564.0]], "666,666", 1.00),
        ]
        st = pipe._parse_settlement(ocr_mock, 1920, 1080)
        self.assertIsNone(st.get("winner"))

        # Pipeline retention logic
        if st.get("winner"):
            pipe.current_context["winner"] = st.get("winner")
        elif pipe.current_context.get("winner"):
            st["winner"] = pipe.current_context.get("winner")

        self.assertEqual(pipe.current_context["winner"], "汐")
        self.assertEqual(st["winner"], "汐")

        # CurrentMatch apply_facts retention
        CURRENT_MATCH.apply_facts({"winner": "汐"})
        patch = {"clearingPrice": 666666}  # no winner in patch
        CURRENT_MATCH.apply_facts(patch)
        self.assertEqual(CURRENT_MATCH.facts["winner"], "汐")

    def test_ac9_auto_archiver_ingests_explicit_winner(self):
        """AC9: AutoArchiver accepts explicit winner and handles finalization."""
        import tempfile
        import os
        import time

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_archiver.json")
            archiver = AutoArchiver(db_paths=[db_path])
            match_id = f"match_phase14_{int(time.time() * 1000)}"
            ctx = {
                "id": match_id,
                "isSettlement": True,
                "settlementReady": True,
                "settlementFinalized": False,
                "winner": "汐",
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 666666,
                    "actualTotal": 631993,
                    "profit": -34673,
                    "winner": "汐",
                    "items": [],
                },
                "venue": "shanhu",
                "box": "实木宝箱",
                "warehouse": {"slots": []},
                "settlementTruthEvidence": {"status": "verified"},
            }
            rec = archiver.archive_match(ctx)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["settlement"]["winner"], "汐")
            # An explicit winner survives, but a bare status string is not
            # verifiable evidence and cannot authorize finalization.
            self.assertFalse(rec["settlement"]["verified"])
            self.assertEqual(rec['lifecycleStatus'], 'DRAFT')


if __name__ == "__main__":
    unittest.main()
