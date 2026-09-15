# -*- coding: utf-8 -*-
"""Stage 1: Live consumes Shared Historical Shadow; HUD never reads the DB."""
import json
import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from live_shadow import (
    attach_live_shadow,
    compute_live_probability_profile,
    history_generation,
    load_history_snapshot,
    reset_live_shadow_state,
    wait_for_shadow,
)
from main import build_in_auction_hud_payload


DB_PATH = os.path.join(PROJECT_ROOT, "异环拍卖数据.json")
FIXTURE_PATH = os.path.join(PROJECT_ROOT, "tests", "fixtures", "shadow_1415_legacy.json")
HUD_HTML = os.path.join(PROJECT_ROOT, "core", "tactical_hud.html")


CTX_1415 = {
    "scene": "IN_AUCTION",
    "round": 3,
    "timer": 12,
    "playedAt": "2026-08-17T14:15:59.030277",
    "venue": "中级场 · 珊瑚场",
    "lobbyVenue": "中级场 · 珊瑚场",
    "box": "琉璃宝箱 · 宝石类概率提升",
    "fieldCondition": "standard",
    "q": 12,
    "goldAvg": 74379,
    "avg": 74379,
    "purple": 7,
    "lobbyEntryCost": 5000,
    "currentLeaderBid": 666666,
}


class TestLiveHistoricalShadow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_live_shadow_state()
        if os.path.exists(DB_PATH):
            load_history_snapshot(DB_PATH)

    @classmethod
    def tearDownClass(cls):
        reset_live_shadow_state()

    def test_hud_does_not_load_history_or_shadow_runtime(self):
        with open(HUD_HTML, encoding="utf-8") as fh:
            html = fh.read()
        self.assertNotIn("异环拍卖数据.json", html)
        self.assertNotIn("shadow_profile_v06.js", html)
        self.assertNotIn("live_shadow_runtime.js", html)
        self.assertNotIn("buildProbabilityProfile", html)
        self.assertIn("solveAuctionPipeline(d)", html)

    def test_14_15_live_matches_shared_core(self):
        if not os.path.exists(DB_PATH):
            self.skipTest("history db missing")
        with open(FIXTURE_PATH, encoding="utf-8") as fh:
            fixture = json.load(fh)
        profile, meta = compute_live_probability_profile(CTX_1415, db_path=DB_PATH)
        self.assertIsNotNone(profile)
        self.assertGreaterEqual(meta["historyN"], 178)
        self.assertEqual(profile["supportedStateCount"], 2)
        self.assertEqual(profile["totalStateCount"], 2)
        self.assertAlmostEqual(profile["coverageRatio"], 1.0, places=10)
        self.assertTrue(profile["isFullShadow"])
        self.assertAlmostEqual(profile["shadowWhole"]["p20"], fixture["shadowWhole"]["p20"], places=4)
        self.assertAlmostEqual(profile["shadowWhole"]["p50"], fixture["shadowWhole"]["p50"], places=4)
        self.assertAlmostEqual(profile["shadowWhole"]["p80"], fixture["shadowWhole"]["p80"], places=4)
        self.assertEqual(meta["exactStates"], fixture["exactStates"])
        self.assertEqual(meta["expandedStates"], fixture["expandedStates"])

        wait_for_shadow(timeout=12.0)
        payload = build_in_auction_hud_payload(CTX_1415)
        if payload.get("probabilityProfile") is None:
            wait_for_shadow(timeout=12.0)
            payload = build_in_auction_hud_payload(CTX_1415)
        self.assertNotIn("records", payload)
        self.assertEqual(payload["probabilityProfile"]["coverageRatio"], 1)
        self.assertAlmostEqual(payload["probabilityProfile"]["shadowWhole"]["p50"], fixture["shadowWhole"]["p50"], places=4)
        self.assertEqual(payload["costs"]["entry"], 5000)

        import subprocess
        script = (
            "const engine=require('./core/auction_engine_v06.js');"
            "const d=" + json.dumps({
                "q": 12, "goldAvg": 74379, "purple": 7,
                "costs": payload["costs"],
                "probabilityProfile": payload["probabilityProfile"],
                "leaderBid": 666666
            }, ensure_ascii=False) + ";"
            "const res=engine.solveAuctionPipeline(d);"
            "console.log(JSON.stringify({mode:res.degradationLevel,p50:res.decision.valueP50,"
            "safe:res.decision.safeBuy,rec:res.decision.recommendedMax,chase:res.decision.chaseLimit}));"
        )
        out = subprocess.check_output(["node", "-e", script], cwd=PROJECT_ROOT, encoding="utf-8")
        dec = json.loads(out[out.find("{"):])
        self.assertEqual(dec["mode"], "full_shadow")
        self.assertAlmostEqual(dec["p50"], fixture["shadowWhole"]["p50"], places=4)
        self.assertIsNotNone(dec["safe"])
        self.assertIsNotNone(dec["rec"])
        self.assertIsNotNone(dec["chase"])
        # entry=5000 must actually move official lines
        self.assertEqual(dec["rec"], int(fixture["shadowWhole"]["p50"] - 5000))
        self.assertEqual(dec["chase"], int(fixture["shadowWhole"]["p50"]))

    def test_timer_and_bid_do_not_recompute_profile(self):
        if not os.path.exists(DB_PATH):
            self.skipTest("history db missing")
        first = compute_live_probability_profile(CTX_1415, db_path=DB_PATH)[1]
        self.assertIn(first["cache"], ("hit", "miss"))
        again = compute_live_probability_profile(
            {**CTX_1415, "timer": 3, "currentLeaderBid": 700000, "round": 4},
            db_path=DB_PATH,
        )[1]
        self.assertEqual(again["cache"], "hit")

    def test_structural_facts_recompute_profile(self):
        if not os.path.exists(DB_PATH):
            self.skipTest("history db missing")
        compute_live_probability_profile(CTX_1415, db_path=DB_PATH)
        changed = compute_live_probability_profile({**CTX_1415, "q": 11}, db_path=DB_PATH)[1]
        self.assertEqual(changed["cache"], "miss")

    def test_empty_history_still_uses_shared_profile(self):
        reset_live_shadow_state()
        empty = os.path.join(PROJECT_ROOT, "tests", "fixtures", "empty_shadow_history.json")
        with open(empty, "w", encoding="utf-8") as fh:
            json.dump({"records": []}, fh)
        try:
            profile, meta = compute_live_probability_profile(
                {**CTX_1415, "playedAt": "2099-01-01T00:00:00"},
                db_path=empty,
            )
            self.assertIsNotNone(profile)
            self.assertEqual(meta["historyN"], 0)
            self.assertEqual(profile["totalStateCount"], 2)
            self.assertIn(profile["isFullShadow"], (True, False))
        finally:
            os.remove(empty)
            reset_live_shadow_state()
            if os.path.exists(DB_PATH):
                load_history_snapshot(DB_PATH)

    def test_insufficient_without_q_or_avg(self):
        profile, meta = compute_live_probability_profile(
            {"venue": "中级场 · 珊瑚场", "q": 12, "goldAvg": None},
            db_path=DB_PATH if os.path.exists(DB_PATH) else None,
        )
        self.assertIsNone(profile)
        self.assertEqual(meta["cache"], "insufficient")
        payload = build_in_auction_hud_payload({
            "scene": "IN_AUCTION",
            "round": 1,
            "q": 12,
            "venue": "中级场 · 珊瑚场",
        })
        self.assertIsNone(payload.get("probabilityProfile"))

    def test_partial_and_full_gate_via_payload_profile(self):
        import subprocess
        script = r"""
        const engine = require('./core/auction_engine_v06.js');
        const full = engine.solveAuctionPipeline({
          q:12, goldAvg:74379, purple:7,
          costs:{entry:5000,intel:0,other:0,sunkCost:5000,futureIncrementalCost:0,total:5000},
          probabilityProfile:{
            coverageRatio:1, supportedStateCount:2, totalStateCount:2,
            supportedWeight:1, totalWeight:1,
            shadowWhole:{p20:415124.01,p50:437503.01,p80:513175.01}
          }
        });
        const partial = engine.solveAuctionPipeline({
          q:12, goldAvg:74379, purple:7,
          costs:{entry:5000},
          probabilityProfile:{
            coverageRatio:0.39, supportedStateCount:1, totalStateCount:2,
            supportedWeight:0.07, totalWeight:0.18,
            shadowWhole:null,
            partialShadowP20:432668.9, partialShadowP50:432668.9, partialShadowP80:432668.9
          }
        });
        const structural = engine.solveAuctionPipeline({
          q:12, goldAvg:74379, purple:7, costs:{entry:5000}
        });
        const insufficient = engine.solveAuctionPipeline({q:12, costs:{entry:5000}});
        console.log(JSON.stringify({
          full: full.degradationLevel,
          fullP50: full.decision.valueP50,
          fullSafe: full.decision.safeBuy,
          partial: partial.degradationLevel,
          partialP50: partial.decision.valueP50,
          structural: structural.degradationLevel,
          structuralP50: structural.decision.valueP50,
          insufficient: insufficient.solverStatus
        }));
        """
        out = subprocess.check_output(["node", "-e", script], cwd=PROJECT_ROOT, encoding="utf-8")
        res = json.loads(out[out.find("{"):])
        self.assertEqual(res["full"], "full_shadow")
        self.assertAlmostEqual(res["fullP50"], 437503.01, places=2)
        self.assertIsNotNone(res["fullSafe"])
        self.assertEqual(res["partial"], "partial_shadow")
        self.assertIsNone(res["partialP50"])
        self.assertEqual(res["structural"], "structural_only")
        self.assertIsNone(res["structuralP50"])
        self.assertEqual(res["insufficient"], "fallback")


if __name__ == "__main__":
    unittest.main()
