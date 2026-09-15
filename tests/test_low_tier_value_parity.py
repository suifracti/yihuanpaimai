# -*- coding: utf-8 -*-
"""
Automated Test Suite for Low-Tier Residual + HardLower Feature Parity in Shared Core.
验证：
  1. Baseline (无 low-tier facts) 使用 0.6 场地基础先验 (12000 点)，mid=12000, lower=0 (不伪装成 hardLower)
  2. blue/green/white count rates: blue=2954, green=1189, white=203 计入 lowTier.mid
  3. count + avg: 优先使用 count * avg，且该确定性金额进入 lowTier.lower 与整仓 hardLower
  4. grid: 正确使用 LOW_TIER_GRID_RATE (blue=809, green=452, white=92)
  5. totalItems residual: 当 totalItems >= Q 时，推导剩余 low-tier 件数并按 1754/件 pooled rate 累加
  6. 无 double counting: 存在 count + avg 或 totalItems 时，不重复计算整箱基础 prior
  7. hardLower 完整性: knownGold + knownPurple + knownRed + exact low-tier 真实抬高 hardLower
  8. candidate states 与 G/P/R 枚举零回归
  9. weakValuePrior 保持独立隔离，未被污染
 10. formalValue.valueScope 声明为 "full-inventory-estimate"
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


class TestLowTierValueParity(unittest.TestCase):
    def test_case_a_baseline_prior_parity(self):
        """A. 无 low-tier facts 时使用 0.6 基础 prior (12000)，且 lower=0"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190})
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 6)
        self.assertEqual(res["formalValue"]["valueScope"], "full-inventory-estimate")

        # 验证每个 state 上的 lowTier 组件
        for s in res["states"]:
            self.assertEqual(s["lowTierValue"], 12000)
            self.assertEqual(s["components"]["lowTier"]["source"], "venue_low_tier_prior")
            self.assertEqual(s["components"]["lowTier"]["lower"], 0)

        # Baseline P50 估值为 649862
        self.assertEqual(res["formalValue"]["p50"], 649862)

    def test_case_b_blue_count_rate(self):
        """B. blueCount=5 使用 0.6 blue rate (2954/件) + 未观测颜色残值 (4400)"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "blueCount": 5})
        s = res["states"][0]
        # blue: 5 * 2954 = 14770, unobserved residual: 12000 * (2/3) * 0.55 = 4400, total = 19170
        self.assertEqual(s["lowTierValue"], 19170)
        self.assertEqual(s["components"]["lowTier"]["breakdown"]["blue"], 14770)
        self.assertEqual(s["components"]["lowTier"]["breakdown"]["residual"], 4400)
        self.assertEqual(s["components"]["lowTier"]["lower"], 0)

    def test_case_c_green_count_rate(self):
        """C. greenCount=6 使用 0.6 green rate (1189/件)"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "greenCount": 6})
        s = res["states"][0]
        # green: 6 * 1189 = 7134, unobserved: 4400, total = 11534
        self.assertEqual(s["lowTierValue"], 11534)
        self.assertEqual(s["components"]["lowTier"]["breakdown"]["green"], 7134)

    def test_case_d_white_count_rate(self):
        """D. whiteCount=5 使用 0.6 white rate (203/件)"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "whiteCount": 5})
        s = res["states"][0]
        # white: 5 * 203 = 1015, unobserved: 4400, total = 5415
        self.assertEqual(s["lowTierValue"], 5415)
        self.assertEqual(s["components"]["lowTier"]["breakdown"]["white"], 1015)

    def test_case_e_count_plus_avg_enters_hard_lower(self):
        """E. blueCount=5 + blueAvg=3500 优先使用 count * avg，并进入 lowTier.lower"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "blueCount": 5, "blueAvg": 3500})
        s = res["states"][0]
        # blue: 5 * 3500 = 17500, unobserved: 4400, total = 21900
        self.assertEqual(s["lowTierValue"], 21900)
        self.assertEqual(s["components"]["lowTier"]["breakdown"]["blue"], 17500)
        self.assertEqual(s["components"]["lowTier"]["lower"], 17500)
        self.assertEqual(s["components"]["lowTier"]["source"], "low_tier_count_and_avg")

    def test_case_f_all_low_tier_counts(self):
        """F. 蓝/绿/白三色全有 count 时，3 色完全观测，无 unobserved residual"""
        res = _run_pipeline({
            "q": 18,
            "purpleCount": 9,
            "goldAvg": 71190,
            "blueCount": 5,
            "greenCount": 6,
            "whiteCount": 5
        })
        s = res["states"][0]
        # 5*2954 (14770) + 6*1189 (7134) + 5*203 (1015) = 22919, residual = 0
        self.assertEqual(s["lowTierValue"], 22919)
        self.assertEqual(s["components"]["lowTier"]["breakdown"]["residual"], 0)

    def test_case_g_total_items_residual_no_double_counting(self):
        """G. totalItems=30, Q=18 时计算剩余 12 件低品质残值池 (12 * 1754 = 21052)"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "totalItems": 30})
        s = res["states"][0]
        # remaining = 30 - 18 = 12, pooled = 1754.33, 12 * 1754.33 ≈ 21052
        self.assertEqual(s["lowTierValue"], 21052)
        self.assertEqual(s["components"]["lowTier"]["source"], "low_tier_total_items_residual")
        self.assertEqual(s["components"]["lowTier"]["breakdown"]["residual"], 21052)

    def test_case_h_grid_only(self):
        """H. 仅提供 blueGrid=15 时按 809/格计算"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "blueGrid": 15})
        s = res["states"][0]
        # 15 * 809 = 12135, unobserved: 4400, total = 16535
        self.assertEqual(s["lowTierValue"], 16535)
        self.assertEqual(s["components"]["lowTier"]["breakdown"]["blue"], 12135)

    def test_case_i_hard_lower_exact_elevations(self):
        """I. hardLower 抬升验证: knownGold, knownPurple, knownRed, exact low-tier 均抬升下限"""
        res_full_known = _run_pipeline({
            "q": 9,
            "purpleCount": 5,
            "goldAvg": 33538,
            "knownGold": "51077",
            "knownPurple": "18075+8128",
            "knownRed": "31618",
            "blueCount": 2,
            "blueAvg": 3000
        })
        self.assertEqual(res_full_known["solverStatus"], "valid")
        # goldLower: 100616 (or 134155), purpleLower: 26203, redLower: 31618, lowTierLower: 6000
        # min stateLower = 100616 + 26203 + 31618 + 6000 = 164437
        self.assertEqual(res_full_known["formalValue"]["hardLower"], 164437)
        self.assertEqual(res_full_known["formalValue"]["theoreticalMin"], 164437)

    def test_weak_value_prior_isolated_and_unchanged(self):
        """J. weakValuePrior 保持独立，未被 low-tier residual 污染"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "blueCount": 5})
        self.assertIsNotNone(res["weakValuePrior"])
        self.assertEqual(res["weakValuePrior"]["status"], "valid")
        self.assertEqual(res["weakValuePrior"]["q"], 18)
        self.assertEqual(res["weakValuePrior"]["p50"], 555534)
        self.assertEqual(res["weakValuePrior"]["source"], "historical_actual_total")

    def test_priors_do_not_raise_hard_lower(self):
        """K. 纯先验 (场地先验、紫图鉴均值先验、红图鉴中位先验) 绝不抬高 hardLower"""
        res_std = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "venueTier": "zhongji"})
        res_high_venue = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "venueTier": "gaoji"})

        # 高级场场地先验 30000 (相比中级场 12000 抬升 mid 18000)
        self.assertEqual(res_std["states"][0]["lowTierValue"], 12000)
        self.assertEqual(res_high_venue["states"][0]["lowTierValue"], 30000)
        self.assertEqual(res_high_venue["formalValue"]["p50"], res_std["formalValue"]["p50"] + 18000)

        # 但两者的 lowTier.lower 均严格为 0，hardLower 均严格保持 213571 (min state gold lower)
        self.assertEqual(res_std["states"][0]["components"]["lowTier"]["lower"], 0)
        self.assertEqual(res_high_venue["states"][0]["components"]["lowTier"]["lower"], 0)
        self.assertEqual(res_std["formalValue"]["hardLower"], 213571)
        self.assertEqual(res_high_venue["formalValue"]["hardLower"], 213571)

    def test_multi_state_hard_lower_aggregation(self):
        """L. 多状态全局 hardLower 为所有合法状态 stateLower 的最小值"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190})
        # 6 个状态: 3/9/6 (213571), 5/9/4 (355952), 6/9/3 (427142), 7/9/2 (498333), 8/9/1 (569525), 9/9/0 (640711)
        state_lowers = [s["stateLower"] for s in res["states"]]
        self.assertEqual(state_lowers, [213571, 355952, 427142, 498333, 569525, 640711])
        self.assertEqual(res["formalValue"]["hardLower"], min(state_lowers))
        self.assertEqual(res["formalValue"]["hardLower"], 213571)


if __name__ == "__main__":
    unittest.main()
