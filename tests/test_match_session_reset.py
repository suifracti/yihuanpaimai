# -*- coding: utf-8 -*-
"""Match trunk must not leak into the next lobby / next match."""
import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from auto_archiver import AutoArchiver
from live_shadow import attach_live_shadow, invalidate_match_shadow, reset_live_shadow_state
from vision_pipeline import NTEVisionPipeline, SCENE_AUCTION_LOBBY, SCENE_IN_AUCTION, SCENE_SETTLEMENT


def _lobby_info(**kwargs):
    base = {
        "inLobby": True,
        "venue": "中级场 · 珊瑚场",
        "venueKey": "shanhu",
        "venueLabel": "珊瑚场",
        "toolGroup": "高级品鉴仪器组",
        "character": "达芙蒂尔",
        "entryCost": 5000,
    }
    base.update(kwargs)
    return base


class TestMatchSessionReset(unittest.TestCase):
    def setUp(self):
        reset_live_shadow_state()
        self.pipe = NTEVisionPipeline()

    def tearDown(self):
        reset_live_shadow_state()

    def _seed_match_two(self):
        c = self.pipe.current_context
        c.update({
            "scene": SCENE_IN_AUCTION,
            "inAuction": True,
            "round": 1,
            "box": "琉璃宝箱 · 宝石类概率提升",
            "fieldCondition": "standard",
            "q": 5,
            "goldAvg": 76591,
            "avg": 76591,
            "finalBids": {"米雪儿": {"1": 555555}, "梦染の月": {"1": 90000}, "秋星祭02": {"1": 190000}},
            "historicalBids": {"米雪儿": {"1": 555555}},
            "currentLeaderBid": 555555,
            "leaderName": "米雪儿",
            "lobbyVenue": "中级场 · 珊瑚场",
            "lobbyCharacter": "达芙蒂尔",
            "lobbyToolGroup": "高级品鉴仪器组",
            "venue": "中级场 · 珊瑚场",
        })
        self.pipe._match_active = True
        self.pipe._match_gen = 2
        c["matchGeneration"] = 2

    def _assert_trunk_cleared(self, c):
        self.assertIn(c.get("box"), (None, "", "未知箱型"))
        self.assertIsNone(c.get("q"))
        self.assertIsNone(c.get("goldAvg"))
        self.assertIsNone(c.get("avg"))
        self.assertFalse(c.get("finalBids"))
        self.assertFalse(c.get("historicalBids"))
        self.assertIsNone(c.get("settlementData"))
        self.assertFalse(c.get("settlementReady"))
        self.assertEqual(c.get("currentLeaderBid") or 0, 0)
        self.assertIsNone(c.get("probabilityProfile"))

    def test_settlement_archive_then_lobby_clears_trunk_keeps_loadout(self):
        self._seed_match_two()
        self.pipe.current_context.update({
            "scene": SCENE_SETTLEMENT,
            "isSettlement": True,
            "settlementReady": True,
            "settlementData": {"isSettlement": True, "clearingPrice": 555555, "actualTotal": 227253, "profit": -328302},
        })
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "db.json")
            rec = AutoArchiver(db_paths=[db]).archive_match(self.pipe.current_context)
            self.assertIsNotNone(rec)
            self.assertEqual(self.pipe.current_context["settlementData"]["actualTotal"], 227253)
            self.pipe.mark_settlement_finalized()
            self.pipe._apply_lobby_loadout(_lobby_info())
            self.pipe._end_match_on_lobby_or_egress()
        c = self.pipe.current_context
        self._assert_trunk_cleared(c)
        self.assertEqual(c["lobbyCharacter"], "达芙蒂尔")
        self.assertEqual(c["lobbyVenue"], "中级场 · 珊瑚场")
        self.assertEqual(c["lobbyToolGroup"], "高级品鉴仪器组")
        self.assertGreater(c["matchGeneration"], 2)
        self.assertEqual(c["scene"], SCENE_AUCTION_LOBBY)

    def test_archive_not_cleared_before_finalize(self):
        self._seed_match_two()
        self.pipe.current_context.update({
            "scene": SCENE_SETTLEMENT,
            "isSettlement": True,
            "settlementReady": True,
            "settlementData": {"isSettlement": True, "clearingPrice": 555555, "actualTotal": 227253, "profit": -328302},
        })
        self.assertFalse(self.pipe.clear_match_trunk())
        self.assertEqual(self.pipe.current_context["q"], 5)
        self.assertEqual(self.pipe.current_context["settlementData"]["clearingPrice"], 555555)

    def test_abnormal_exit_to_lobby_clears(self):
        self._seed_match_two()
        self.pipe._apply_lobby_loadout(_lobby_info())
        self.pipe._end_match_on_lobby_or_egress()
        self._assert_trunk_cleared(self.pipe.current_context)
        self.assertEqual(self.pipe.current_context["lobbyCharacter"], "达芙蒂尔")

    def test_failed_loading_does_not_keep_half_match(self):
        self.pipe.current_context.update({"scene": "AUCTION_LOADING", "isLoading": True, "q": None, "box": None})
        self.pipe._apply_lobby_loadout(_lobby_info())
        self.pipe._end_match_on_lobby_or_egress()
        self._assert_trunk_cleared(self.pipe.current_context)

    def test_new_match_does_not_inherit_old_bids(self):
        self._seed_match_two()
        self.pipe._apply_lobby_loadout(_lobby_info())
        self.pipe._end_match_on_lobby_or_egress()
        self.pipe.current_context["inAuction"] = True
        self.pipe.current_context["scene"] = SCENE_IN_AUCTION
        self.pipe._match_active = False
        # simulate first in-auction promotion
        if not self.pipe._match_active:
            self.pipe._match_active = True
            self.pipe._match_gen += 1
            self.pipe.current_context["matchGeneration"] = self.pipe._match_gen
        c = self.pipe.current_context
        self.assertNotEqual(c.get("box"), "琉璃宝箱 · 宝石类概率提升")
        self.assertNotIn("米雪儿", c.get("finalBids") or {})
        self.assertIsNone(c.get("q"))

    def test_stale_shadow_cannot_overwrite_new_match(self):
        from live_shadow import _LATEST_PROFILE
        import live_shadow
        live_shadow._LATEST_PROFILE = {"shadowWhole": {"p50": 555555}, "coverageRatio": 1}
        live_shadow._LATEST_MATCH_GEN = 2
        live_shadow._LATEST_KEY = "old"
        invalidate_match_shadow(3)
        self.assertIsNone(live_shadow._LATEST_PROFILE)
        fresh = attach_live_shadow({"scene": SCENE_IN_AUCTION, "q": 11, "goldAvg": 47286, "matchGeneration": 3, "box": "皮制"})
        self.assertNotEqual((fresh.get("probabilityProfile") or {}).get("shadowWhole", {}).get("p50"), 555555)


if __name__ == "__main__":
    unittest.main()
