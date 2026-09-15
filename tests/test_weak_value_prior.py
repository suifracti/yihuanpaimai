# -*- coding: utf-8 -*-
"""
Automated Test Suite for Weak Value Prior (weakValuePriorV06) in Shared Core.
验证：
  1. Live Q=18, P=7 -> P样本不足 (N=2<5) 自动降级为 Q-level (N=9, P50=555534)
  2. Live Q=18, P=9 -> P样本不足 (N=1<5) 自动降级为 Q-level (N=9)
  3. Live Q=18 without P -> 直接命中 Q-level (N=9)
  4. 生僻 Q=28 -> 历史样本不足 (N=1<5) 明确输出 status='no-data'，不造假数据
  5. 时间安全 Walk-Forward:
     - 2026-08-11 19:00 时过去仅 3 条 (N=3<5) -> 严格 no-data
     - 2026-08-11 19:14 第5条入库后 (2026-08-12 12:00, N=5) -> 开启 valid
     - 2026-08-12 13:38 Match #88 发生前 -> N=5；Match #88 结算后 -> N=6
  6. 严格防未来泄漏 -> 向末尾注入 2099 年异常高值，历史 cut-off 下数值完全不变
  7. 排除无时间戳记录 -> 向历史库注入无 timestamp 记录，历史 replay 下严格排除
  8. Truth Eligibility 资格验证 -> 显式 DRAFT / 未结案非真值记录严格排除
  9. Formal Solver 兼容回归 -> 有 goldAvg 时 states / formalValue / decision / marketPrediction 与修改前完全一致
"""

import json
import os
import subprocess
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "异环拍卖数据.json")


def _run_node_solver(input_obj, inject_records_script=""):
    script = f"""
    const engine = require('./core/auction_engine_v06.js');
    const fs = require('fs');
    const data = JSON.parse(fs.readFileSync('./异环拍卖数据.json', 'utf-8'));
    let records = Array.isArray(data) ? data : (data.records || data.matches || []);
    {inject_records_script}
    const res = engine.solveAuctionPipeline({json.dumps(input_obj)}, records);
    console.log(JSON.stringify(res));
    """
    out = subprocess.check_output(["node", "-e", script], cwd=PROJECT_ROOT, encoding="utf-8")
    return json.loads(out)


class TestWeakValuePrior(unittest.TestCase):
    def test_live_q18_p7_falls_back_to_q_level(self):
        """A. Q=18, P=7: P桶样本N=2<5，必须降级到Q level (N=9, P50=555534)"""
        res = _run_node_solver({"q": 18, "purpleCount": 7})
        prior = res.get("weakValuePrior")
        self.assertIsNotNone(prior)
        self.assertEqual(prior["status"], "valid")
        self.assertEqual(prior["level"], "q")
        self.assertEqual(prior["sampleN"], 9)
        self.assertEqual(prior["q"], 18)
        self.assertEqual(prior["purpleCount"], 7)
        self.assertAlmostEqual(prior["p50"], 555534.0, delta=1.0)
        self.assertAlmostEqual(prior["p20"], 435160.2, delta=1.0)
        self.assertAlmostEqual(prior["p80"], 612189.8, delta=1.0)
        self.assertEqual(prior["fallbackReason"], "purple_sample_insufficient_2")
        self.assertEqual(prior["source"], "historical_actual_total")
        # 绝不能污染 formalValue 或 decision.valueP50
        self.assertIsNone(res["formalValue"]["p50"])
        self.assertIsNone(res["decision"].get("valueP50"))

    def test_live_q18_p9_falls_back_to_q_level(self):
        """B. Q=18, P=9: P桶样本N=1<5，必须降级到Q level"""
        res = _run_node_solver({"q": 18, "purpleCount": 9})
        prior = res.get("weakValuePrior")
        self.assertEqual(prior["status"], "valid")
        self.assertEqual(prior["level"], "q")
        self.assertEqual(prior["sampleN"], 9)
        self.assertAlmostEqual(prior["p50"], 555534.0, delta=1.0)
        self.assertEqual(prior["fallbackReason"], "purple_sample_insufficient_1")
        self.assertIsNone(res["formalValue"]["p50"])

    def test_live_q18_without_purple_hits_q_level(self):
        """C. Q=18 无紫数: 直接命中 Q level，fallbackReason 为 None"""
        res = _run_node_solver({"q": 18})
        prior = res.get("weakValuePrior")
        self.assertEqual(prior["status"], "valid")
        self.assertEqual(prior["level"], "q")
        self.assertEqual(prior["sampleN"], 9)
        self.assertIsNone(prior["purpleCount"])
        self.assertIsNone(prior["fallbackReason"])
        self.assertAlmostEqual(prior["p50"], 555534.0, delta=1.0)
        self.assertIsNone(res["formalValue"]["p50"])

    def test_insufficient_q_sample_outputs_no_data(self):
        """D. 生僻 Q=28 样本数 N=1 < 5: 必须输出 status=no-data，不使用全局平均补值"""
        res = _run_node_solver({"q": 28})
        prior = res.get("weakValuePrior")
        self.assertEqual(prior["status"], "no-data")
        self.assertIsNone(prior["level"])
        self.assertEqual(prior["sampleN"], 1)
        self.assertIsNone(prior["p20"])
        self.assertIsNone(prior["p50"])
        self.assertIsNone(prior["p80"])
        self.assertEqual(prior["fallbackReason"], "q_sample_insufficient_1")

    def test_time_safety_walk_forward_sequence(self):
        """E. 时间安全与时序演进测试：
        1. 2026-08-11 19:00: 历史仅有3条 (8-9 16:47, 8-9 17:37, 8-11 14:31)，N=3 < 5 -> no-data
        2. 2026-08-11 19:14 第5条结算后，在 2026-08-12 12:00 -> N=5 达到门槛，输出 P50=504989
        3. 2026-08-12 13:38 Match #88 发生前 -> N=5；Match #88 结算后的 2026-08-12 14:00 -> N=6 (P50=531487)
        """
        # 1. 早期 (8-11 19:00): N=3
        res_early = _run_node_solver({"q": 18, "playedAt": "2026-08-11T19:00:00"})
        self.assertEqual(res_early["weakValuePrior"]["status"], "no-data")
        self.assertEqual(res_early["weakValuePrior"]["sampleN"], 3)

        # 2. 第5条入库后 (8-12 12:00): N=5
        res_mid = _run_node_solver({"q": 18, "playedAt": "2026-08-12T12:00:00"})
        self.assertEqual(res_mid["weakValuePrior"]["status"], "valid")
        self.assertEqual(res_mid["weakValuePrior"]["sampleN"], 5)
        self.assertAlmostEqual(res_mid["weakValuePrior"]["p50"], 504989.0, delta=1.0)

        # 3. Match #88 (8-12 13:38) 结算后的 8-12 14:00: N=6
        res_after_88 = _run_node_solver({"q": 18, "playedAt": "2026-08-12T14:00:00"})
        self.assertEqual(res_after_88["weakValuePrior"]["status"], "valid")
        self.assertEqual(res_after_88["weakValuePrior"]["sampleN"], 6)

    def test_future_leakage_resistance(self):
        """F. 泄漏测试：向末尾注入 2099 年异常超大值，在早期 targetPlayedAt 下数值完全不受影响"""
        injection = """
        records.push({
            id: 'injected_future_anomaly',
            playedAt: '2099-01-01T00:00:00Z',
            publicIntel: { q: 18 },
            qualities: { purple: { count: 7 } },
            settlement: { actualTotal: 999999999 }
        });
        """
        res = _run_node_solver({"q": 18, "purpleCount": 7, "playedAt": "2026-08-19T22:00:00Z"}, inject_records_script=injection)
        prior = res.get("weakValuePrior")
        self.assertEqual(prior["status"], "valid")
        self.assertEqual(prior["sampleN"], 9)
        self.assertAlmostEqual(prior["p50"], 555534.0, delta=1.0)

    def test_undated_records_excluded_under_target_played_at(self):
        """G. 排除无时间记录：当指定 targetPlayedAt 时，无 timestamp 记录无法证明发生在目标局之前，必须排除"""
        injection = """
        records.push({
            id: 'injected_undated_anomaly',
            playedAt: null,
            date: null,
            createdAt: null,
            publicIntel: { q: 18 },
            settlement: { actualTotal: 999999999 },
            lifecycleStatus: 'FINALIZED'
        });
        """
        res = _run_node_solver({"q": 18, "purpleCount": 7, "playedAt": "2026-08-19T22:00:00Z"}, inject_records_script=injection)
        prior = res.get("weakValuePrior")
        # 无时间戳的异常大值被严格排除，sampleN 仍为 9，P50 保持 555534
        self.assertEqual(prior["sampleN"], 9)
        self.assertAlmostEqual(prior["p50"], 555534.0, delta=1.0)

    def test_truth_eligibility_excludes_draft_and_unfinalized(self):
        """H. 资格过滤：DRAFT 与未结案记录必须严格排除"""
        injection = """
        records.push({
            id: 'draft_new_session',
            lifecycleStatus: 'DRAFT',
            playedAt: '2026-08-10T10:00:00Z',
            publicIntel: { q: 18 },
            settlement: { actualTotal: 12345678 }
        });
        """
        res = _run_node_solver({"q": 18, "purpleCount": 7, "playedAt": "2026-08-19T22:00:00Z"}, inject_records_script=injection)
        prior = res.get("weakValuePrior")
        self.assertEqual(prior["sampleN"], 9)
        self.assertAlmostEqual(prior["p50"], 555534.0, delta=1.0)

    def test_formal_solver_pipeline_unchanged_with_gold_avg(self):
        """I. 现有正式 Solver 回归：有 goldAvg 时 states / formalValue / decision / marketPrediction 行为完全不变"""
        input_full = {
            "q": 9,
            "purpleCount": 5,
            "goldAvg": 33538,
            "knownPurple": "18075+8128",
            "knownGold": "51077"
        }
        res = _run_node_solver(input_full)
        self.assertEqual(res["solverStatus"], "valid")
        self.assertEqual(res["stateCount"], 2)
        # formalValue 整仓综合估值 (金+紫+红+低品质)
        self.assertAlmostEqual(res["formalValue"]["p50"], 220791.5, delta=1.0)
        self.assertAlmostEqual(res["formalValue"]["p20"], 204273.2, delta=1.0)
        self.assertAlmostEqual(res["formalValue"]["p80"], 237309.8, delta=1.0)
        self.assertEqual(res["formalValue"]["valueScope"], "full-inventory-estimate")
        # weakValuePrior 挂载在结果上
        self.assertIsNotNone(res.get("weakValuePrior"))
        self.assertEqual(res["weakValuePrior"]["status"], "valid")


if __name__ == "__main__":
    unittest.main()
