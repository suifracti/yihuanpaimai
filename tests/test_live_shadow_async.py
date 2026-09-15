# -*- coding: utf-8 -*-
"""Shadow must not block the capture/OCR loop; only the latest facts are computed."""
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

import live_shadow
from live_shadow import attach_live_shadow, reset_live_shadow_state, wait_for_shadow
from main import build_in_auction_hud_payload


def _seed(path, records):
    import json
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": "v0.6", "schemaVersion": 6, "records": records}, fh)


class TestLiveShadowAsync(unittest.TestCase):
    def setUp(self):
        reset_live_shadow_state()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "hist.json")
        _seed(self.db, [])
        live_shadow.load_history_snapshot(self.db)
        self.calls = []
        self.release = threading.Event()

        def fake_compute(ctx, db_path=None, persist_runtime=True):
            self.calls.append((ctx.get("q"), ctx.get("goldAvg"), ctx.get("box")))
            self.release.wait(timeout=2.0)
            profile = {
                "coverageRatio": 1,
                "isFullShadow": True,
                "supportedStateCount": 1,
                "totalStateCount": 1,
                "shadowWhole": {"p20": 1, "p50": ctx.get("goldAvg") or 0, "p80": 3},
            }
            return profile, {"cache": "miss", "exactStates": [], "expandedStates": []}

        self.patcher = mock.patch.object(live_shadow, "compute_live_probability_profile", side_effect=fake_compute)
        self.patcher.start()

    def tearDown(self):
        self.release.set()
        self.patcher.stop()
        reset_live_shadow_state()
        self.tmp.cleanup()

    def test_attach_returns_immediately_and_skips_lobby_settlement(self):
        t0 = time.perf_counter()
        pending = attach_live_shadow({
            "scene": "IN_AUCTION", "q": 5, "goldAvg": 76591, "box": "琉璃宝箱 · 宝石类概率提升"
        }, db_path=self.db)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 50)
        self.assertTrue(pending.get("shadowUpdating"))
        self.assertIsNone(pending.get("probabilityProfile"))

        lobby = attach_live_shadow({"scene": "AUCTION_LOBBY", "q": 5, "goldAvg": 76591}, db_path=self.db)
        settle = attach_live_shadow({"scene": "SETTLEMENT", "isSettlement": True, "q": 5, "goldAvg": 76591}, db_path=self.db)
        self.assertEqual(lobby["shadowMeta"]["cache"], "skip-scene")
        self.assertEqual(settle["shadowMeta"]["cache"], "skip-scene")
        self.assertFalse(lobby.get("shadowUpdating"))

    def test_only_latest_facts_are_computed(self):
        attach_live_shadow({"scene": "IN_AUCTION", "q": 5, "goldAvg": 1000, "box": "A"}, db_path=self.db)
        attach_live_shadow({"scene": "IN_AUCTION", "q": 11, "goldAvg": 2000, "box": "B"}, db_path=self.db)
        attach_live_shadow({"scene": "IN_AUCTION", "q": 11, "goldAvg": 47286, "box": "皮制宝箱 · 高级藏品概率提升"}, db_path=self.db)
        time.sleep(0.05)
        self.release.set()
        got = wait_for_shadow(timeout=3.0)
        self.assertIsNotNone(got)
        # A may start before B/C overwrite pending; after A finishes, worker must jump to C, never require B.
        computed_avgs = [c[1] for c in self.calls]
        self.assertIn(47286, computed_avgs)
        self.assertNotIn(2000, computed_avgs[1:] if computed_avgs[:1] == [1000] else computed_avgs)

    def test_timer_and_bid_do_not_enqueue(self):
        attach_live_shadow({"scene": "IN_AUCTION", "q": 12, "goldAvg": 74379, "timer": 40, "currentLeaderBid": 1}, db_path=self.db)
        time.sleep(0.02)
        n0 = len(self.calls)
        attach_live_shadow({"scene": "IN_AUCTION", "q": 12, "goldAvg": 74379, "timer": 10, "currentLeaderBid": 666666}, db_path=self.db)
        time.sleep(0.02)
        self.assertEqual(len(self.calls), n0)
        self.release.set()

    def test_payload_exposes_updating_flag_without_blocking(self):
        t0 = time.perf_counter()
        payload = build_in_auction_hud_payload({
            "scene": "IN_AUCTION", "round": 1, "q": 5, "goldAvg": 76591, "box": "琉璃宝箱 · 宝石类概率提升"
        })
        self.assertLess((time.perf_counter() - t0) * 1000, 80)
        self.assertTrue(payload.get("shadowUpdating"))
        self.assertIn("q", payload)
        self.assertEqual(payload["q"], 5)
        self.release.set()


if __name__ == "__main__":
    unittest.main()
