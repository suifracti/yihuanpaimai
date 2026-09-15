import os
import sys
import unittest
from pathlib import Path
import cv2
import numpy as np

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
sys.path.insert(0, str(CORE_DIR))

from vision_pipeline import NTEVisionPipeline, parse_money_amount
from current_match import CurrentMatch
from canonical_match_record import validate_canonical_match_record_v7, validate_finalized_match_record_v7


from character_matcher import CANONICAL_ROSTER


class TestSettlementWinnerAssistantFacts(unittest.TestCase):
    def test_money_amount_parsing_with_apostrophe(self):
        self.assertEqual(parse_money_amount("666'999"), 666999)
        self.assertEqual(parse_money_amount("666’999"), 666999)
        self.assertEqual(parse_money_amount("651,142"), 651142)
        self.assertEqual(parse_money_amount("-15,857"), 15857)
        self.assertEqual(parse_money_amount("1,585"), 1585)

    def test_real_settlement_fixture_facts(self):
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        trial_dir = None
        for item in local_app_data.iterdir():
            if item.is_dir() and "异环" in item.name and "试用" in item.name:
                trial_dir = item
                break
        if not trial_dir:
            self.skipTest("Trial dir not found on current machine")

        img_path = (
            trial_dir
            / "data"
            / "evidence"
            / "settlement_v2"
            / "blobs"
            / "1e"
            / "1eeed15c71493f6ed60ebee9f107063487158f598885bc80434c9c5c0327061d.png"
        )
        if not img_path.exists():
            self.skipTest("Real settlement image fixture not found")

        img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        vp = NTEVisionPipeline()
        ocr_res, _ = vp.ocr(img)
        parsed = vp._parse_settlement(ocr_res, 1920, 1080, frame=img)

        # 1. Fact assertions
        self.assertTrue(parsed.get("isSettlement"))
        self.assertEqual(parsed.get("winner"), "AsunaDaisuki")
        self.assertEqual(parsed.get("settlementWinnerName"), "AsunaDaisuki")
        self.assertEqual(parsed.get("clearingPrice"), 666999)
        self.assertEqual(parsed.get("actualTotal"), 651142)
        self.assertEqual(parsed.get("profit"), -15857)

        # Assistant identity must strictly belong to known roster and reject "小哎"
        self.assertNotEqual(parsed.get("settlementAuctionAssistantName"), "小哎")
        self.assertNotEqual(parsed.get("auctionAssistant"), "小哎")
        self.assertIn(parsed.get("settlementAuctionAssistantName"), CANONICAL_ROSTER)
        self.assertEqual(parsed.get("settlementAuctionAssistantName"), "小吱")
        self.assertEqual(parsed.get("auctionAssistant"), "小吱")
        self.assertEqual(parsed.get("assistantIdentityStatus"), "CONFIRMED")

        self.assertIsNone(parsed.get("welfareReceived"))
        self.assertFalse(parsed.get("isSelfWinner"))
        self.assertNotEqual(parsed.get("winner"), parsed.get("auctionAssistant"))

        # 2. Projection to CurrentMatch and Canonical v7
        cm = CurrentMatch()
        cm.apply_facts(
            {
                "box": "皮制宝箱",
                "fieldCondition": "standard",
                "settlement": parsed,
                "settlementReady": True,
            },
            source="manual",
        )
        canonical = cm.to_canonical()
        st = canonical["settlement"]
        self.assertEqual(st.get("winner"), "AsunaDaisuki")
        self.assertEqual(st.get("settlementWinnerName"), "AsunaDaisuki")
        self.assertNotEqual(st.get("settlementAuctionAssistantName"), "小哎")
        self.assertIn(st.get("settlementAuctionAssistantName"), CANONICAL_ROSTER)
        self.assertEqual(st.get("settlementAuctionAssistantName"), "小吱")
        self.assertEqual(st.get("auctionAssistant"), "小吱")
        self.assertEqual(st.get("clearingPrice"), 666999)
        self.assertEqual(st.get("actualTotal"), 651142)
        self.assertEqual(st.get("realizedProfit"), -15857)
        self.assertFalse(st.get("isSelfWinner"))
        self.assertIsNone(st.get("welfare", {}).get("received"))

        # 3. Canonical validation
        valid, reasons = validate_canonical_match_record_v7(canonical, match_id=cm.id)
        self.assertTrue(valid, f"Canonical validation failed: {reasons}")

    def test_unregistered_assistant_ocr_rejected_when_no_reliable_match(self):
        """When OCR produces non-existent '小哎' and visual match has no reliable match, it must be rejected."""
        vp = NTEVisionPipeline()
        fake_ocr = [
            [[[78, 143], [324, 143], [324, 210], [78, 210]], "竞拍结束", 1.0],
            [[[880, 353], [979, 360], [976, 391], [877, 383]], "竞拍帮手：", 0.99],
            [[[1090, 369], [1143, 372], [1142, 400], [1089, 398]], "小哎", 0.66],
        ]
        parsed = vp._parse_settlement(fake_ocr, 1920, 1080, frame=None)
        self.assertIsNone(parsed.get("settlementAuctionAssistantName"))
        self.assertIsNone(parsed.get("auctionAssistant"))
        self.assertEqual(parsed.get("assistantIdentityStatus"), "UNKNOWN")

        # Even with a blank image frame, non-roster OCR must still be rejected
        blank_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        parsed_blank = vp._parse_settlement(fake_ocr, 1920, 1080, frame=blank_frame)
        self.assertIsNone(parsed_blank.get("settlementAuctionAssistantName"))
        self.assertIsNone(parsed_blank.get("auctionAssistant"))
        self.assertEqual(parsed_blank.get("assistantIdentityStatus"), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
