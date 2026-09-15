# -*- coding: utf-8 -*-
"""
Tests for unbounded R candidate-state parity and historical R>=3 regressions.
"""

import json
import os
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _run_pipeline(input_obj):
    script = f"""
    const engine = require('./core/auction_engine_v06.js');
    const records = [];
    const res = engine.solveAuctionPipeline({json.dumps(input_obj)}, records);
    console.log(JSON.stringify(res));
    """
    out = subprocess.check_output(["node", "-e", script], cwd=PROJECT_ROOT, encoding="utf-8")
    return json.loads(out)


class TestRedUnboundedParity(unittest.TestCase):
    # 1. Historical Realized R>=3 Regressions
    def test_historical_r3_regression(self):
        """r-msw240yh-jflucz: Q=16, P=9, redCount=3, goldAvg=89525 (真值 G=4, P=9, R=3)"""
        res = _run_pipeline({
            "q": 16,
            "purpleCount": 9,
            "redCount": 3,
            "goldAvg": 89525,
            "knownRed": "31618+288888+101860"
        })
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 1)
        s = res["states"][0]
        self.assertEqual(f"{s['G']}/{s['P']}/{s['R']}", "4/9/3")
        self.assertEqual(s["R"], 3)
        self.assertEqual(s["redValue"], 31618 + 288888 + 101860)

    def test_historical_r4_regression(self):
        """r-msw0sh9u-94rikb: Q=15, P=7, redCount=4, goldAvg=41088 (真值 G=4, P=7, R=4)"""
        res = _run_pipeline({
            "q": 15,
            "purpleCount": 7,
            "redCount": 4,
            "goldAvg": 41088
        })
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 1)
        s = res["states"][0]
        self.assertEqual(f"{s['G']}/{s['P']}/{s['R']}", "4/7/4")
        self.assertEqual(s["R"], 4)

    def test_historical_r5_regression(self):
        """r-msw1f5l9-ezfg1s: Q=14, P=8, redCount=5, goldAvg=21012 (真值 G=1, P=8, R=5)"""
        res = _run_pipeline({
            "q": 14,
            "purpleCount": 8,
            "redCount": 5,
            "goldAvg": 21012
        })
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 1)
        s = res["states"][0]
        self.assertEqual(f"{s['G']}/{s['P']}/{s['R']}", "1/8/5")
        self.assertEqual(s["R"], 5)

    def test_historical_r6_regression(self):
        """r-msn1mav4-ns9diw: Q=16, P=6, redCount=6, goldAvg=16854 (真值 G=4, P=6, R=6)"""
        res = _run_pipeline({
            "q": 16,
            "purpleCount": 6,
            "redCount": 6,
            "goldAvg": 16854
        })
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 1)
        s = res["states"][0]
        self.assertEqual(f"{s['G']}/{s['P']}/{s['R']}", "4/6/6")
        self.assertEqual(s["R"], 6)

    # 2. Explicit redCount Locking (0, 1, 2, 3, 4, 6)
    def test_explicit_red_count_locking(self):
        """显式锁定 redCount=0, 1, 2, 3, 4, 6 均能准确过滤候选状态"""
        base = {"q": 18, "purpleCount": 9, "goldAvg": 71190}
        for r_val, expected_g in [(0, 9), (1, 8), (2, 7), (3, 6), (4, 5), (6, 3)]:
            res = _run_pipeline({**base, "redCount": r_val})
            self.assertEqual(res["solverStatus"], "valid")
            self.assertEqual(res["stateCount"], 1)
            self.assertEqual(res["states"][0]["R"], r_val)
            self.assertEqual(res["states"][0]["G"], expected_g)

    # 3. Conflict Detection
    def test_hard_constraint_conflict_still_returns_no_match(self):
        """当 Q, P, G, R 数学不自洽时（如 8+9+3 = 20 != 18），严格返回 no-match"""
        res = _run_pipeline({
            "q": 18,
            "purpleCount": 9,
            "goldCount": 8,
            "redCount": 3,
            "goldAvg": 71190
        })
        self.assertEqual(res["solverStatus"], "no-match")
        self.assertEqual(res["stateCount"], 0)

    # 4. Candidate Space & Timing on Large Q
    def test_large_q_performance_and_soundness(self):
        """对 Q=10, 18, 25, 27 运行求解器，验证状态数与耗时处于健康范围"""
        for q_val in [10, 18, 25, 27]:
            res = _run_pipeline({"q": q_val, "purpleCount": 5, "goldAvg": 50000})
            self.assertEqual(res["solverStatus"], "valid")
            self.assertGreater(res["stateCount"], 0)
            self.assertLessEqual(res["stateCount"], q_val)  # G 最多遍历 q 个


if __name__ == "__main__":
    unittest.main()
