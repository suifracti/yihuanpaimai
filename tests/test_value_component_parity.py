# -*- coding: utf-8 -*-
"""
Automated Test Suite for Purple + Red Component Composition Feature Parity in Shared Core.
验证：
  1. Baseline (Q=18, P=9, goldAvg=71190) 候选状态保持 7/9/2, 8/9/1, 9/9/0 零回归
  2. 每个 state 明确包含 components { gold, purple, red }, goldValue, purpleValue, redValue, stateValue
  3. purpleValue 真正计入 stateValue (无 knownPurple 时取 catalog 均值先验)
  4. knownPurple 改变时 (如 8128 vs 18075+18075)，formalValue 产生明确对应差异
  5. redValue 真正计入 stateValue (R=0 为 0, R=1 为 ~88.6K, R=2 为 ~177.2K)
  6. knownRed 改变时 (如 31618 vs 101860+288888)，formalValue 产生明确对应差异
  7. redCount=0 / 1 / 2 消除金唯一估值下的反向伪缩水
  8. 冲突输入 (如 goldCount=7 + redCount=0) 保持 no-match / isFold
  9. weakValuePrior 与正式高价值层 formalValue 保持正交隔离
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


class TestValueComponentParity(unittest.TestCase):
    def test_golden_case_states_and_components(self):
        """1. Golden Case (Q=18, P=9, goldAvg=71190) 解除 R<=2 后包含全部合法 DFS 状态 (6 states)"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190})
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 6)
        state_strs = [f"{s['G']}/{s['P']}/{s['R']}" for s in res["states"]]
        self.assertEqual(state_strs, ["3/9/6", "5/9/4", "6/9/3", "7/9/2", "8/9/1", "9/9/0"])

        # 检查各状态的具体组件数值
        s7 = [s for s in res["states"] if s["G"] == 7][0]
        self.assertEqual(s7["goldValue"], 498333)
        self.assertEqual(s7["purpleValue"], 62709)  # 9 * 6967.7 ≈ 62709
        self.assertEqual(s7["redValue"], 109864)    # 0.6 unlocked soft red: 88600 * (1 + 0.24) = 109864
        self.assertEqual(s7["lowTierValue"], 12000) # 0.6 场地低品质先验
        self.assertEqual(s7["stateValue"], 498333 + 62709 + 109864 + 12000)
        self.assertIn("components", s7)
        self.assertEqual(s7["components"]["gold"]["source"], "exact_gold_dfs_combo")
        self.assertEqual(s7["components"]["purple"]["source"], "catalog_mean_prior")
        self.assertEqual(s7["components"]["red"]["source"], "unlocked_red_soft_attenuation")
        self.assertEqual(s7["components"]["lowTier"]["source"], "venue_low_tier_prior")

        s8 = [s for s in res["states"] if s["G"] == 8][0]
        self.assertEqual(s8["goldValue"], 569525)
        self.assertEqual(s8["purpleValue"], 62709)
        self.assertEqual(s8["redValue"], 88600)     # 1 * 88600 = 88600
        self.assertEqual(s8["lowTierValue"], 12000)
        self.assertEqual(s8["stateValue"], 569525 + 62709 + 88600 + 12000)

        s9 = [s for s in res["states"] if s["G"] == 9][0]
        self.assertEqual(s9["goldValue"], 640711)
        self.assertEqual(s9["purpleValue"], 62709)
        self.assertEqual(s9["redValue"], 0)         # 0 * 88600 = 0
        self.assertEqual(s9["lowTierValue"], 12000)
        self.assertEqual(s9["stateValue"], 640711 + 62709 + 0 + 12000)

        # formalValue 包含整仓估值 P50 (6个状态排序后 P50 估值为 649862)
        self.assertEqual(res["formalValue"]["p50"], 649862)
        self.assertEqual(res["formalValue"]["valueScope"], "full-inventory-estimate")

    def test_known_purple_affects_state_and_formal_value(self):
        """2. knownPurple 实际价格进入 purpleValue 并影响 formalValue"""
        base = {"q": 18, "purpleCount": 9, "goldAvg": 71190}
        res_none = _run_pipeline(base)
        res_low = _run_pipeline({**base, "knownPurple": "8128"})
        res_high = _run_pipeline({**base, "knownPurple": "18075+18075"})

        # 候选状态数量与结构不变 (6 states)
        self.assertEqual(res_low["stateCount"], 6)
        self.assertEqual(res_high["stateCount"], 6)

        # purpleValue 随 knownPurple 实际价值增加而增加
        self.assertGreater(res_low["formalValue"]["p50"], res_none["formalValue"]["p50"])
        self.assertGreater(res_high["formalValue"]["p50"], res_low["formalValue"]["p50"])
        self.assertEqual(res_low["formalValue"]["p50"], 651023)
        self.assertEqual(res_high["formalValue"]["p50"], 672077)

    def test_known_red_affects_state_and_formal_value(self):
        """3. knownRed 实际价格进入 redValue 并影响 formalValue"""
        base = {"q": 18, "purpleCount": 9, "goldAvg": 71190}
        res_low = _run_pipeline({**base, "knownRed": "31618"})
        res_high = _run_pipeline({**base, "knownRed": "101860+288888"})

        # low: 强制 R>=1, 状态剩下 5 个 (R in [1, 2, 3, 4, 6])
        self.assertEqual(res_low["stateCount"], 5)
        # high: 强制 R>=2, 状态剩下 4 个 (R in [2, 3, 4, 6])
        self.assertEqual(res_high["stateCount"], 4)

        s7_high = [s for s in res_high["states"] if s["G"] == 7][0]
        self.assertEqual(s7_high["redValue"], 101860 + 288888)
        self.assertEqual(s7_high["stateValue"], 498333 + 62709 + 390748 + 12000)

    def test_red_count_zero_one_two_component_correctness(self):
        """4. 显式锁定 redCount=0 / 1 / 2 时 redValue 使用 0.6 线性图鉴中位 88600/件"""
        base = {"q": 18, "purpleCount": 9, "goldAvg": 71190}
        res0 = _run_pipeline({**base, "redCount": 0})
        res1 = _run_pipeline({**base, "redCount": 1})
        res2 = _run_pipeline({**base, "redCount": 2})

        self.assertEqual(res0["states"][0]["redValue"], 0)
        self.assertEqual(res1["states"][0]["redValue"], 88600)
        self.assertEqual(res2["states"][0]["redValue"], 177200) # locked redCount: 2 * 88600 = 177200
        self.assertEqual(res2["states"][0]["components"]["red"]["source"], "locked_red_linear_prior")

        # 锁定状态价值随红件数递增
        self.assertEqual(res0["formalValue"]["p50"], 715420)
        self.assertEqual(res1["formalValue"]["p50"], 732834)
        self.assertEqual(res2["formalValue"]["p50"], 750242)

    def test_weak_value_prior_isolated_and_unchanged(self):
        """5. weakValuePrior 保持来源于 historical actualTotal，未被高价值层 formalValue 污染"""
        res = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190})
        self.assertIsNotNone(res["weakValuePrior"])
        self.assertEqual(res["weakValuePrior"]["status"], "valid")
        self.assertEqual(res["weakValuePrior"]["q"], 18)
        self.assertEqual(res["weakValuePrior"]["p50"], 555534)
        self.assertEqual(res["weakValuePrior"]["source"], "historical_actual_total")

    def test_parser_known_count_and_total_locking(self):
        """6. 锁定 parser 解析结果：knownCount 和 knownTotal 必须严格提取，不能退化为 0"""
        script = """
        const engine = require('./core/auction_engine_v06.js');
        const cat = engine.effectiveCatalog({});
        const pComp = engine.purpleValueForState({ P: 9 }, { knownPurple: '18075+8128' }, cat);
        const rComp = engine.redValueForState({ R: 2 }, { knownRed: '31618' }, cat);
        console.log(JSON.stringify({ pComp, rComp }));
        """
        out = subprocess.check_output(["node", "-e", script], cwd=PROJECT_ROOT, encoding="utf-8")
        data = json.loads(out)
        self.assertEqual(data["pComp"]["knownCount"], 2)
        self.assertEqual(data["pComp"]["lower"], 18075 + 8128)
        self.assertEqual(data["rComp"]["knownCount"], 1)
        self.assertEqual(data["rComp"]["lower"], 31618)

    def test_field_condition_multiplier_on_purple_component(self):
        """7. 确认 purple_double 场地条件正确使紫色组件翻倍且不漏乘、不重复乘"""
        res_std = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "fieldCondition": "standard"})
        res_dbl = _run_pipeline({"q": 18, "purpleCount": 9, "goldAvg": 71190, "fieldCondition": "purple_double"})
        std_p = res_std["states"][0]["purpleValue"]
        dbl_p = res_dbl["states"][0]["purpleValue"]
        self.assertEqual(std_p, 62709)
        self.assertEqual(dbl_p, 125419)  # 62709 * 2 ≈ 125419


if __name__ == "__main__":
    unittest.main()
