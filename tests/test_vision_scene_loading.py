import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core")))

from vision_pipeline import NTEVisionPipeline, SCENE_AUCTION_LOADING, SCENE_IN_AUCTION


class TestVisionSceneLoading(unittest.TestCase):
    def setUp(self):
        self.pipe = NTEVisionPipeline()

    def test_teardrop_item_does_not_trigger_loading(self):
        """「泪滴」 is an item name, never a valid loading venue."""
        ocr_results = [
            ([[100, 100], [200, 100], [200, 130], [100, 130]], "获得物品「泪滴」", 0.95),
            ([[100, 200], [200, 200], [200, 230], [100, 230]], "红色品质藏品", 0.90),
        ]
        parsed = self.pipe._parse_loading(ocr_results)
        self.assertFalse(parsed["isLoading"], "「泪滴」 must not trigger isLoading=True")
        self.assertIsNone(parsed.get("venue"))

    def test_kaleidoscope_item_does_not_trigger_loading(self):
        """「万花筒」 is an item name, never a valid loading venue."""
        ocr_results = [
            ([[100, 100], [200, 100], [200, 130], [100, 130]], "「万花筒」", 0.98),
            ([[100, 200], [200, 200], [200, 230], [100, 230]], "金色品质", 0.92),
        ]
        parsed = self.pipe._parse_loading(ocr_results)
        self.assertFalse(parsed["isLoading"], "「万花筒」 must not trigger isLoading=True")
        self.assertIsNone(parsed.get("venue"))

    def test_other_catalog_items_do_not_trigger_loading(self):
        """Catalog item names in quotes must not be parsed as loading venues."""
        items = ["「机械怀表」", "「星夜之泪」", "「黄金雕像」", "「纯白之羽」"]
        for item in items:
            ocr_results = [([[100, 100], [250, 100], [250, 130], [100, 130]], item, 0.95)]
            parsed = self.pipe._parse_loading(ocr_results)
            self.assertFalse(parsed["isLoading"], f"{item} must not trigger isLoading")
            self.assertIsNone(parsed.get("venue"))

    def test_valid_loading_venue_with_progress_triggers_loading(self):
        """Valid venue whitelist + progress triggers loading."""
        ocr_results = [
            ([[100, 100], [300, 100], [300, 130], [100, 130]], "正在进入对局「粉爪银行」", 0.95),
            ([[1500, 800], [1600, 800], [1600, 850], [1500, 850]], "45%", 0.98),
        ]
        parsed = self.pipe._parse_loading(ocr_results, 1920, 1080)
        self.assertTrue(parsed["isLoading"], "Real loading screen must trigger isLoading=True")
        self.assertEqual(parsed.get("venue"), "粉爪银行")
        self.assertEqual(parsed.get("percent"), 45)

    def test_auction_strong_signals_veto_loading(self):
        """Round indicator, timer, and HUD elements must veto loading even if quotes or keywords appear."""
        ocr_results = [
            ([[100, 100], [300, 100], [300, 130], [100, 130]], "正在进入对局「粉爪银行」", 0.95),
            ([[800, 50], [900, 50], [900, 80], [800, 80]], "第 1 回合", 0.98),
            ([[900, 100], [1000, 100], [1000, 140], [900, 140]], "00:15", 0.95),
            ([[100, 300], [200, 300], [200, 340], [100, 340]], "公开情报", 0.92),
        ]
        parsed = self.pipe._parse_loading(ocr_results, 1920, 1080)
        self.assertFalse(parsed["isLoading"], "Auction strong signals must strictly veto AUCTION_LOADING")
        self.assertIsNone(parsed.get("venue"))


if __name__ == "__main__":
    unittest.main()
