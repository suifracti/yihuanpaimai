# -*- coding: utf-8 -*-
"""
Automated Test Suite for GoldCount & RedCount Strong Constraints Feature Parity in Shared Core.
验证：
  1. A. Baseline (Q=18, P=9, avg=71190): 无 goldCount/redCount 保持原 3 个候选状态 (7/9/2, 8/9/1, 9/9/0)
  2. B. goldCount=7: 强锁定 G=7，候选精准收敛至 7/9/2
  3. C. goldCount=8: 强锁定 G=8，候选精准收敛至 8/9/1
  4. D. redCount=0: 强锁定 R=0，候选精准收敛至 9/9/0
  5. E. redCount=1: 强锁定 R=1，候选精准收敛至 8/9/1
  6. F. goldCount=7 + redCount=2: 双重强锁定，候选精准收敛至 7/9/2
  7. G. goldCount=7 + redCount=0: 不可满足冲突 (Q=18, P=9, G=7 强制要求 R=2)，必须返回 no-match / 暂停追价
  8. H. minGold / minRed 超界冲突: 例如已知 2 件金货但 goldCount=1，必须返回 no-match
  9. I. 零回归验证: 不传入 goldCount/redCount 时，现有 Solver pipeline 状态、分位数、决策完全不变
"""

import json
import os
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _run_pipeline(input_obj):
    script = f"""
    const engine = require('./core/auction_engine_v06.js');
    const fs = require('fs');
    const data = JSON.parse(fs.readFileSync('./异环拍卖数据.json', 'utf-8'));
    const records = Array.isArray(data) ? data : (data.records || data.matches || []);
    const res = engine.solveAuctionPipeline({json.dumps(input_obj)}, records);
    console.log(JSON.stringify(res));
    """
    out = subprocess.check_output(["node", "-e", script], cwd=PROJECT_ROOT, encoding="utf-8")
    return json.loads(out)


class TestFeatureParityCounts(unittest.TestCase):
    def test_case_a_baseline(self):
        """A. baseline: 不提供 goldCount/redCount，包含所有合法 DFS 状态 (6 states)"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190})
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 6)
        state_strs = [f"{s['G']}/{s['P']}/{s['R']}" for s in res["states"]]
        self.assertEqual(state_strs, ["3/9/6", "5/9/4", "6/9/3", "7/9/2", "8/9/1", "9/9/0"])
        self.assertEqual(res["candidateGs"], [3, 5, 6, 7, 8, 9])
        self.assertEqual(res["candidatePs"], [9])

    def test_case_b_gold_count_7(self):
        """B. goldCount=7: 必须只剩 7/9/2"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "goldCount": 7})
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 1)
        self.assertEqual(f"{res['states'][0]['G']}/{res['states'][0]['P']}/{res['states'][0]['R']}", "7/9/2")
        self.assertEqual(res["candidateGs"], [7])

    def test_case_c_gold_count_8(self):
        """C. goldCount=8: 必须只剩 8/9/1"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "goldCount": 8})
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 1)
        self.assertEqual(f"{res['states'][0]['G']}/{res['states'][0]['P']}/{res['states'][0]['R']}", "8/9/1")
        self.assertEqual(res["candidateGs"], [8])

    def test_case_d_red_count_0(self):
        """D. redCount=0: 必须只剩 9/9/0"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "redCount": 0})
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 1)
        self.assertEqual(f"{res['states'][0]['G']}/{res['states'][0]['P']}/{res['states'][0]['R']}", "9/9/0")
        self.assertEqual(res["candidateGs"], [9])

    def test_case_e_red_count_1(self):
        """E. redCount=1: 必须只剩 8/9/1"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "redCount": 1})
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 1)
        self.assertEqual(f"{res['states'][0]['G']}/{res['states'][0]['P']}/{res['states'][0]['R']}", "8/9/1")
        self.assertEqual(res["candidateGs"], [8])

    def test_case_f_both_locks_consistent(self):
        """F. goldCount=7 + redCount=2: 必须只剩 7/9/2"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "goldCount": 7, "redCount": 2})
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 1)
        self.assertEqual(f"{res['states'][0]['G']}/{res['states'][0]['P']}/{res['states'][0]['R']}", "7/9/2")
        self.assertEqual(res["candidateGs"], [7])

    def test_case_g_both_locks_conflict(self):
        """G. goldCount=7 + redCount=0: 与 Q=18, P=9 冲突，必须无合法 state，返回 no-match / isFold: true"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "goldCount": 7, "redCount": 0})
        self.assertEqual(res["solverStatus"], "no-match")
        self.assertEqual(res["stateCount"], 0)
        self.assertEqual(res["states"], [])
        self.assertEqual(res["candidateGs"], [])
        self.assertTrue(res["decision"]["isFold"])
        self.assertIn("输入无可行解", res["decision"]["actionDirective"])
        self.assertIn("冲突", res["decision"]["entryGrade"])

    def test_known_gold_group_capacity_conflict(self):
        """H. 已知金色件数与 goldCount 冲突: 已知 2 件金色，但 goldCount=1，必须返回 no-match"""
        res = _run_pipeline({
            "q": 9,
            "purpleCount": 5,
            "goldAvg": 33538,
            "knownGold": "万有星仪+海盐心迷宫", # 2 件
            "goldCount": 1
        })
        self.assertEqual(res["solverStatus"], "no-match")
        self.assertEqual(res["stateCount"], 0)

    def test_zero_regression_classic_1553(self):
        """I. 经典 15:53 零回归: 不传 goldCount 时状态和估值与原版完全一致"""
        res = _run_pipeline({
            "q": 9,
            "purpleCount": 5,
            "goldAvg": 33538,
            "knownPurple": "18075+8128",
            "knownGold": "51077"
        })
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 2)
        self.assertAlmostEqual(res["formalValue"]["p50"], 220791.5, delta=1.0)
        self.assertEqual(res["formalValue"]["valueScope"], "full-inventory-estimate")


if __name__ == "__main__":
    unittest.main()
