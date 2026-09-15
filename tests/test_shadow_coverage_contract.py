# -*- coding: utf-8 -*-
"""Live pipeline 不得把 Structural 分位伪装成 Full Shadow。"""
import json
import os
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def run_js(script: str):
    prelude = (
        "const engine = require('./core/auction_engine_v06.js');\n"
        + script
    )
    proc = subprocess.run(
        ["node", "-e", prelude],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr + "\n" + proc.stdout)
    return json.loads(proc.stdout)


class TestShadowCoverageContract(unittest.TestCase):
    LIVE_1415 = {
        "q": 12,
        "goldAvg": 74379,
        "purple": 7,
        "venue": "中级场 · 珊瑚场",
        "box": "琉璃宝箱 · 宝石类概率提升",
        "fieldCondition": "standard",
        "leaderBid": 666666,
        "costs": {"entry": 5000, "intel": 0, "other": 0, "sunkCost": 5000, "futureIncrementalCost": 0, "total": 5000},
    }

    def test_live_1415_is_structural_only(self):
        res = run_js(
            "const res = engine.solveAuctionPipeline("
            + json.dumps(self.LIVE_1415, ensure_ascii=False)
            + "); console.log(JSON.stringify(res));"
        )
        dec = res["decision"]
        self.assertEqual(res["degradationLevel"], "structural_only")
        self.assertIsNone(res.get("rawShadow"))
        self.assertIsNone(dec.get("valueP50"))
        self.assertIsNone(dec.get("safeBuy"))
        self.assertIsNone(dec.get("recommendedMax"))
        self.assertIsNone(dec.get("chaseLimit"))
        self.assertIsNone(dec.get("targetLine"))
        self.assertIsNone(dec.get("globalLine"))
        self.assertIsNone(dec.get("marginalLine"))
        self.assertIsNotNone(dec.get("structuralCenter") or res["formalValue"]["ev"])
        self.assertNotIn("建议停止", dec.get("actionDirective") or "")
        self.assertIn("结构", dec.get("actionDirective") or "")

    def test_full_shadow_still_emits_official_lines(self):
        res = run_js(
            """
            const res = engine.solveAuctionPipeline({
              q: 12, goldAvg: 74379, purple: 7,
              costs: {entry: 5000, intel: 0, other: 0, sunkCost: 5000, futureIncrementalCost: 0, total: 5000},
              coverageRatio: 1,
              probabilityProfile: {
                coverageRatio: 1,
                supportedStateCount: 2,
                totalStateCount: 2,
                supportedWeight: 1,
                totalWeight: 1,
                shadowWhole: {p20: 300000, p50: 400000, p80: 500000}
              }
            });
            console.log(JSON.stringify(res));
            """
        )
        dec = res["decision"]
        self.assertEqual(res["degradationLevel"], "full_shadow")
        self.assertEqual(dec["valueP50"], 400000)
        self.assertIsNotNone(dec["safeBuy"])
        self.assertIsNotNone(dec["recommendedMax"])
        self.assertIsNotNone(dec["chaseLimit"])
        self.assertEqual(dec["recommendedMax"], 395000)
        self.assertEqual(dec["chaseLimit"], 400000)

    def test_partial_shadow_keeps_conditional_only(self):
        res = run_js(
            """
            const res = engine.solveAuctionPipeline({
              q: 12, goldAvg: 74379, purple: 7,
              coverageRatio: 0.7,
              probabilityProfile: {
                coverageRatio: 0.7,
                supportedStateCount: 1,
                totalStateCount: 2,
                supportedWeight: 0.7,
                totalWeight: 1,
                shadowWhole: {p20: 280000, p50: 360000, p80: 440000},
                partialShadowP20: 280000,
                partialShadowP50: 360000,
                partialShadowP80: 440000
              }
            });
            console.log(JSON.stringify(res));
            """
        )
        dec = res["decision"]
        self.assertEqual(res["degradationLevel"], "partial_shadow")
        self.assertIsNone(dec.get("valueP50"))
        self.assertIsNone(dec.get("safeBuy"))
        self.assertIsNone(dec.get("recommendedMax"))
        self.assertIsNone(dec.get("chaseLimit"))
        self.assertEqual(dec.get("partialShadowP50"), 360000)
        self.assertEqual(dec.get("partialShadowP20"), 280000)

    def test_coverage_zero_is_structural(self):
        lines = run_js(
            """
            const lines = engine.calculateV06DecisionLines(
              {costs:{entry:5000}},
              {solverStatus:'valid', states:[{G:3,P:7,R:2}], formalValue:{ev:334707,theoreticalMin:312393,theoreticalMax:357021}, coverageRatio:0}
            );
            console.log(JSON.stringify(lines));
            """
        )
        self.assertEqual(lines["degradationLevel"], "structural_only")
        self.assertIsNone(lines["valueP50"])
        self.assertIsNone(lines["safeBuy"])
        self.assertIsNone(lines["recommendedMax"])

    def test_insufficient_when_incomplete(self):
        lines = run_js(
            """
            const lines = engine.calculateV06DecisionLines({costs:{entry:5000}}, {solverStatus:'incomplete'});
            console.log(JSON.stringify(lines));
            """
        )
        self.assertEqual(lines["degradationLevel"], "insufficient")
        self.assertTrue(lines["isSuppressed"])
        self.assertIsNone(lines["valueP50"])

    def test_hud_contract_does_not_paint_structural_as_p50(self):
        html_path = os.path.join(PROJECT_ROOT, "core", "tactical_hud.html")
        with open(html_path, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('mode === "full_shadow"', html)
        self.assertIn("isFullShadow", html)
        self.assertIn("条件分布", html)
        self.assertIn("结构参考", html)
        self.assertNotIn("if(fv.ev || fv.p50)", html)


if __name__ == "__main__":
    unittest.main()
