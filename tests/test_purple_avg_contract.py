# -*- coding: utf-8 -*-
"""purpleAvg is a live contract field, not a goldAvg substitute."""
import json
import os
import subprocess
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from live_shadow import _facts_ready, _solver_ctx
from main import build_in_auction_hud_payload


CTX_T327 = {
    "scene": "IN_AUCTION",
    "round": 1,
    "q": 11,
    "purpleAvg": 4357,
    "goldAvg": None,
    "avg": None,
    "purple": None,
    "box": "皮制宝箱 · 高级藏品概率提升",
    "venue": "中级场 · 珊瑚场",
    "fieldCondition": "standard",
}


class TestPurpleAvgContract(unittest.TestCase):
    def test_payload_and_solver_ctx_keep_purple_avg(self):
        payload = build_in_auction_hud_payload(CTX_T327)
        self.assertEqual(payload["q"], 11)
        self.assertEqual(payload["purpleAvg"], 4357)
        self.assertIsNone(payload.get("goldAvg"))
        solver = _solver_ctx(CTX_T327)
        self.assertEqual(solver["purpleAvg"], 4357)
        self.assertIsNone(solver["goldAvg"])
        self.assertFalse(_facts_ready(CTX_T327))

    def test_q_plus_purple_avg_is_not_full_shadow(self):
        script = (
            "const engine=require('./core/auction_engine_v06.js');"
            "const res=engine.solveAuctionPipeline("
            + json.dumps({"q": 11, "purpleAvg": 4357, "goldAvg": None, "avg": None, "costs": {"entry": 5000}}, ensure_ascii=False)
            + ");"
            "console.log(JSON.stringify({status:res.solverStatus,mode:res.degradationLevel,"
            "p50:res.decision&&res.decision.valueP50,safe:res.decision&&res.decision.safeBuy,"
            "rec:res.decision&&res.decision.recommendedMax,chase:res.decision&&res.decision.chaseLimit}));"
        )
        out = subprocess.check_output(["node", "-e", script], cwd=PROJECT_ROOT, encoding="utf-8")
        dec = json.loads(out[out.find("{"):])
        self.assertEqual(dec["status"], "fallback")
        self.assertIsNone(dec.get("p50"))
        self.assertIsNone(dec.get("safe"))
        self.assertIsNone(dec.get("rec"))
        self.assertIsNone(dec.get("chase"))

    def test_gold_avg_does_not_overwrite_purple_avg(self):
        later = dict(CTX_T327)
        later["goldAvg"] = 47286
        later["avg"] = 47286
        later["purple"] = 3
        payload = build_in_auction_hud_payload(later)
        self.assertEqual(payload["goldAvg"], 47286)
        self.assertEqual(payload["purpleAvg"], 4357)
        solver = _solver_ctx(later)
        self.assertEqual(solver["goldAvg"], 47286)
        self.assertEqual(solver["purpleAvg"], 4357)
        self.assertTrue(_facts_ready(later))

    def test_hud_mentions_missing_gold_not_fake_p50(self):
        with open(os.path.join(PROJECT_ROOT, "core", "tactical_hud.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("已知紫色均价，仍缺金色价格证据", html)
        self.assertIn("d.purpleAvg", html)


if __name__ == "__main__":
    unittest.main()
