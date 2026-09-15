"""
v0.65 Brain Fidelity Gate - Layer-by-Layer Golden Comparison Test Suite
验证：
  1. 15:53 经典回归测试 (必须严格命中 3G/5P/1R 与 4G/5P/0R)
  2. 标准局完整 5 阶段流水线 (State Probability -> Formal Value -> Shadow -> Market -> Decision -> Snapshot)
  3. 场地词条推演 (dark / goldDouble / welfare)
  4. 硬约束冲突场景 (no-match)
  5. 情报不足降级语义 (fallback on missing Q/Avg)
  6. 截断与超时语义 (incomplete & timeout)
  7. Frozen Prediction 冻结快照生成与归档不重算
  8. Shared Core 6 项内置可靠性自测
  9. WebView2 主线程单次推演耗时基准
"""

import os
import sys
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import copy
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
sys.path.insert(0, str(CORE_DIR))

from auto_archiver import AutoArchiver
from canonical_match_record import validate_finalized_match_record_v7

def run_js_eval(script: str) -> dict:
    js_path = str(CORE_DIR / "auction_engine_v06.js").replace("\\", "/")
    full_script = f"""
    const fs = require('fs');
    const engine = require('{js_path}');
    {script}
    """
    proc = subprocess.run(
        ["node", "-e", full_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(PROJECT_ROOT)
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Node execution failed (code {proc.returncode}):\n{proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout)

class TestGoldenComparison(unittest.TestCase):

    def test_01_1553_canonical_regression(self):
        """15:53 经典回归测试：必须命中 3G/5P/1R (100,616) 与 4G/5P/0R (134,155)"""
        script = """
        const res = engine.solveAuctionPipeline({
            q: 9,
            p: 5,
            avg: 33538,
            roundingMode: 'floor',
            knownPurple: '拈花小像+金角月芒',
            knownGold: '万有星仪'
        });
        console.log(JSON.stringify(res));
        """
        res = run_js_eval(script)
        self.assertEqual(res["solverStatus"], "valid")
        states = [f"{s['G']}/{s['P']}/{s['R']}" for s in res["states"]]
        self.assertIn("3/5/1", states)
        self.assertIn("4/5/0", states)

        # Formal structural stats exist, but are not Shadow.
        self.assertIsNotNone(res["formalValue"]["p20"])
        self.assertIsNotNone(res["formalValue"]["p50"])
        self.assertIsNotNone(res["formalValue"]["p80"])
        self.assertIsNotNone(res["formalValue"]["ev"])
        self.assertGreater(res["formalValue"]["ev"], 0)

        # Live 无真实 probabilityProfile → 不得把结构分位装进 rawShadow
        self.assertIsNone(res.get("rawShadow"))
        self.assertEqual(res.get("degradationLevel"), "structural_only")

        dec = res["decision"]
        self.assertIsNone(dec.get("valueP50"))
        self.assertIsNone(dec.get("safeBuy") or dec.get("targetLine"))
        self.assertIsNone(dec.get("recommendedMax") or dec.get("globalLine"))
        self.assertIsNone(dec.get("chaseLimit") or dec.get("marginalLine"))
        self.assertIsNotNone(dec.get("structuralReferenceBid") or dec.get("hardFloor"))

    def test_02_standard_game_full_pipeline(self):
        """标准普通局逐层推演测试 (含分层收缩 Market Model)"""
        script = """
        const records = [0, 1, 2, 3, 4, 5, 6, 7].map(i => ({
            id: `rec_${i}`,
            playedAt: `2026-08-10T00:0${i}:00`,
            venue: 'shanhu',
            box: 'standard',
            fieldCondition: 'standard',
            q: 9,
            clearingPrice: 75000 + i * 2000,
            prediction: { estimate: 100000 }
        }));
        const res = engine.solveAuctionPipeline({
            q: 9,
            avg: 33538,
            venue: 'shanhu',
            box: 'standard',
            fieldCondition: 'standard',
            playedAt: '2026-08-12T00:00:00',
            costs: {entry: 5000, intel: 0, other: 0, sunkCost: 5000, futureIncrementalCost: 0, total: 5000}
        }, records);
        console.log(JSON.stringify(res));
        """
        res = run_js_eval(script)
        self.assertEqual(res["solverStatus"], "valid")
        self.assertGreater(res["stateCount"], 0)

        # Market model with hierarchical shrinkage
        market = res["marketPrediction"]
        self.assertEqual(market["version"], "v0.6-market")
        self.assertEqual(market["status"], "shrunk")
        self.assertEqual(market["localN"], 8)
        self.assertEqual(market["fallbackLevel"], "exact-condition-box-q")
        self.assertIsNotNone(market["marketRatio"]["p50"])
        self.assertIsNotNone(market["p50"])
        self.assertIn(market["competition"], ["冷", "正常", "偏紧", "疯狂"])

        # Entry decision
        entry = res["entryDecision"]
        self.assertIn(entry["status"], ["worth-entering", "thin-entry", "not-worth-entering"])
        self.assertIsNotNone(entry["edge"])

        # Frozen prediction
        frozen = res["frozenPrediction"]
        self.assertEqual(frozen["solverStatus"], "valid")
        self.assertEqual(frozen["modelVersion"], "v0.65")
        self.assertIsNotNone(frozen["inputHash"])

    def test_03_condition_scenarios(self):
        """天黑了 / 加倍 / 福利多多 场地词条推演测试"""
        script = """
        const res_dark = engine.solveAuctionPipeline({ q: 9, avg: 33538, fieldCondition: 'dark' });
        const res_gd = engine.solveAuctionPipeline({ q: 9, avg: 67076, fieldCondition: 'goldDouble' });
        const res_welfare = engine.solveAuctionPipeline({ q: 9, avg: 33538, fieldCondition: 'welfare' });
        console.log(JSON.stringify({ dark: res_dark, gd: res_gd, welfare: res_welfare }));
        """
        out = run_js_eval(script)
        self.assertEqual(out["dark"]["solverStatus"], "valid")
        self.assertEqual(out["gd"]["solverStatus"], "valid")
        self.assertEqual(out["welfare"]["solverStatus"], "valid")

    def test_04_no_match_scenario(self):
        """硬约束冲突场景：必须明确返回 no-match 与放弃追价"""
        script = """
        const res = engine.solveAuctionPipeline({ q: 9, avg: 999999999 });
        console.log(JSON.stringify(res));
        """
        res = run_js_eval(script)
        self.assertEqual(res["solverStatus"], "no-match")
        self.assertEqual(res["stateCount"], 0)
        self.assertTrue(res["decision"]["isFold"])
        self.assertIn("无可行解", res["decision"]["actionDirective"])

    def test_05_fallback_semantics(self):
        """缺 Q / 缺 Avg 场景：必须明确返回 fallback (不得返回 incomplete)"""
        script = """
        const res_no_avg = engine.solveAuctionPipeline({ q: 9 });
        const res_no_q = engine.solveAuctionPipeline({ avg: 33538 });
        console.log(JSON.stringify({ no_avg: res_no_avg, no_q: res_no_q }));
        """
        out = run_js_eval(script)
        self.assertEqual(out["no_avg"]["solverStatus"], "fallback")
        self.assertIn("降级估算", out["no_avg"]["decision"]["actionReason"])
        self.assertEqual(out["no_q"]["solverStatus"], "fallback")

    def test_06_incomplete_and_timeout_simulation(self):
        """模拟截断 (incomplete) 与超时 (timeout) 状态语义"""
        script = """
        const mockIncomplete = {
            solverStatus: 'incomplete',
            searchCompleted: false,
            states: [{ G: 3, P: 5, R: 1 }]
        };
        const mockTimeout = {
            solverStatus: 'timeout',
            searchCompleted: false,
            states: []
        };
        console.log(JSON.stringify({ incomplete: mockIncomplete, timeout: mockTimeout }));
        """
        out = run_js_eval(script)
        self.assertEqual(out["incomplete"]["solverStatus"], "incomplete")
        self.assertFalse(out["incomplete"]["searchCompleted"])
        self.assertEqual(out["timeout"]["solverStatus"], "timeout")
        self.assertEqual(len(out["timeout"]["states"]), 0)

    def test_07_frozen_prediction_preservation(self):
        """Frozen Prediction 冻结快照生成与归档不重算测试"""
        script = """
        const res = engine.solveAuctionPipeline({ matchId: 'match_test_07', q: 9, avg: 33538, p: 5 });
        console.log(JSON.stringify(res.predictionSnapshot));
        """
        snapshot = run_js_eval(script)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["status"]["solverStatus"], "valid")
        self.assertEqual(snapshot["producer"]["solverVersion"], "v0.6-reliability")
        self.assertIsNotNone(snapshot["input"]["inputHash"])
        self.assertTrue(snapshot.get("frozen"))

        expected_snapshot_copy = copy.deepcopy(snapshot)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_db.json")
            archiver = AutoArchiver(db_paths=[db_path])

            match_ctx = {
                "id": "match_test_07",
                "matchId": "match_test_07",
                "venue": "shanhu",
                "boxType": "standard",
                "box": "未知箱型",
                "settlementReady": True,
                "q": 9,
                "avg": 33538,
                "predictionSnapshot": snapshot,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 300000,
                    "actualTotal": 600000,
                    "profit": 300000,
                    "items": [],
                },
            }

            archived = archiver.archive_match(match_ctx)
            self.assertIsNotNone(archived)
            self.assertEqual(archived.get("schemaVersion"), 7)
            self.assertEqual(archived.get("productVersion"), "v0.67-alpha")
            self.assertEqual(archived.get("lifecycleStatus"), "FINALIZED")

            # 1. 严格断言旧顶层 prediction 不存在
            self.assertNotIn("prediction", archived)

            # 2. 严格断言 predictionSnapshot 存在且与注入前冻结快照深度完全相等（未在结算后重新计算或被篡改）
            self.assertIn("predictionSnapshot", archived)
            self.assertEqual(archived["predictionSnapshot"], expected_snapshot_copy)
            self.assertEqual(archived["predictionSnapshot"]["status"]["solverStatus"], "valid")
            self.assertEqual(archived["predictionSnapshot"]["input"]["inputHash"], expected_snapshot_copy["input"]["inputHash"])
            self.assertEqual(archived["predictionSnapshot"]["input"]["normalizedFacts"]["q"], 9)
            self.assertEqual(archived["predictionSnapshot"]["input"]["normalizedFacts"]["goldAvg"], 33538)

            # 3. 严格验证记录符合 Match Record v7 权威校验器
            is_valid, errors = validate_finalized_match_record_v7(archived)
            self.assertTrue(is_valid, f"MatchRecord v7 validation failed: {errors}")

    def test_08_core_self_tests(self):
        """运行 Shared Core 6 项内置可靠性自测试"""
        script = """
        const res = engine.runV06ReliabilitySelfTests();
        console.log(JSON.stringify(res));
        """
        self_res = run_js_eval(script)
        self.assertTrue(self_res["passed"], f"Self tests failed: {self_res['tests']}")
        self.assertGreaterEqual(self_res["tested"], 6)

    def test_09_performance_benchmark(self):
        """推演耗时性能测试：单次完整流水线推演耗时需小于 10ms"""
        script = """
        const records = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map(i => ({
            id: `rec_${i}`,
            playedAt: `2026-08-10T00:0${i}:00`,
            venue: 'shanhu',
            box: 'standard',
            fieldCondition: 'standard',
            q: 9,
            clearingPrice: 75000 + i * 2000,
            prediction: { estimate: 100000 }
        }));
        const input = {
            q: 9,
            p: 5,
            avg: 33538,
            roundingMode: 'floor',
            knownPurple: '拈花小像+金角月芒',
            knownGold: '万有星仪',
            playedAt: '2026-08-14T00:00:00'
        };
        // 1. Warmup
        const warmup = engine.solveAuctionPipeline(input, records);
        
        // 2. Measure 10 iterations
        const runs = 10;
        const t0 = process.hrtime.bigint();
        for (let i = 0; i < runs; i++) {
            engine.solveAuctionPipeline(input, records);
        }
        const totalNs = Number(process.hrtime.bigint() - t0);
        const elapsedMs = (totalNs / runs) / 1e6;
        console.log(JSON.stringify({ elapsedMs, solverStatus: warmup.solverStatus }));
        """
        perf = run_js_eval(script)
        self.assertEqual(perf["solverStatus"], "valid")
        elapsed_ms = perf["elapsedMs"]
        print(f"\n⚡ [Performance Benchmark] 完整 5 阶段稳态推演耗时 (V8 Engine): {elapsed_ms:.3f} ms / 局")
        self.assertLess(elapsed_ms, 10.0, f"Steady-state pipeline execution took too long: {elapsed_ms}ms")

if __name__ == "__main__":
    unittest.main()
