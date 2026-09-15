# -*- coding: utf-8 -*-
"""
PHASE 2 Automated Test Suite: v0.6 Solver Adapter Contract Tests
验证：
  1. Synthetic Canonical Fixture -> v0.6 Solver Input (字段映射、类型、toolGroup解耦、unknown=null)
  2. Real 14:12 Live Fixture (Q=39, totalItems=66, goldAvg=61944, purpleAvg=3904, purpleCount=25, box=琉璃)
  3. Historical Round-Trip (0.6 Historical -> Canonical v7 -> v0.6 Adapter -> 0.6 Solver Input)
  4. Node.js 0.6 Solver 约束恢复对照 (证明 Adapter 恢复已知藏品约束与候选空间收敛，保留完整 explainability)
"""

import json
import os
import subprocess
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
sys.path.insert(0, CORE_DIR)

from v06_adapter import (
    canonical_to_v06_solver_input,
    v06_record_to_canonical,
    v065_record_to_canonical,
    format_known_items,
    canonicalize_venue_name,
    canonicalize_field_condition_id
)


class TestV06AdapterContract(unittest.TestCase):
    def test_synthetic_canonical_fixture_mapping(self):
        """A. 验证 Synthetic Canonical v7 完整结构向 0.6 求解器输入的无损转换"""
        canonical_v7 = {
            "schemaVersion": 7,
            "productVersion": "v0.65",
            "id": "match_synth_001",
            "playedAt": "2026-08-16T15:30:00.000Z",
            "environment": {
                "venue": "shanhu",
                "venueName": "中级场 · 珊瑚场",
                "box": "实木宝箱 · 中级藏品概率提升",
                "boxType": "wood",
                "fieldCondition": "standard"
            },
            "loadout": {
                "character": "达芙蒂尔",
                "lobbyToolGroup": "特供大型藏品的仪器组",
                "solverToolGroup": "group1"
            },
            "costs": {
                "entry": 5000,
                "intel": 45000,
                "other": 0,
                "sunkCost": 50000,
                "futureIncrementalCost": 10000,
                "total": 60000
            },
            "publicIntel": {
                "q": 15,
                "totalItems": 66,
                "totalGrid": 84,
                "avgValueBasis": "all_inclusive"
            },
            "qualities": {
                "white": {"count": None, "avg": None, "grid": None, "knownItems": []},
                "green": {"count": None, "avg": None, "grid": None, "knownItems": []},
                "blue": {"count": 4, "avg": 3462, "grid": 6, "knownItems": []},
                "purple": {
                    "count": 5,
                    "minCount": 2,
                    "avg": 2007,
                    "grid": 21,
                    "knownItems": [
                        {"name": "拈花小像", "price": 18075},
                        {"name": "金角月芒", "price": 8128}
                    ]
                },
                "gold": {
                    "count": 4,
                    "minCount": 1,
                    "avg": 33538,
                    "total": None,
                    "grid": 16,
                    "knownItems": [
                        {"name": "万有星仪", "price": 51077}
                    ]
                },
                "red": {
                    "count": 2,
                    "minCount": 1,
                    "maxCount": 2,
                    "knownItems": [
                        {"name": "创生之柱", "price": 81088}
                    ],
                    "redInventoryComplete": True,
                    "settlementVerifiedRedItems": "81088"
                }
            },
            "bidding": {
                "round": 3,
                "leaderBid": 450000,
                "myName": "秋星祭02"
            }
        }

        solver_in = canonical_to_v06_solver_input(canonical_v7)

        # 1. 核心约束字段
        self.assertEqual(solver_in["q"], 15)
        self.assertEqual(solver_in["goldAvg"], 33538)
        self.assertEqual(solver_in["avg"], 33538, "0.6 internal avg must equal goldAvg")
        self.assertEqual(solver_in["purpleAvg"], 2007)
        self.assertEqual(solver_in["p"], 5, "p must be set for native 0.6 solveExactStatesSync")
        self.assertEqual(solver_in["purple"], 5)
        self.assertEqual(solver_in["purpleCount"], 5)
        self.assertEqual(solver_in["goldCount"], 4)
        self.assertEqual(solver_in["redCount"], 2)
        self.assertEqual(solver_in["blueAvg"], 3462)
        self.assertEqual(solver_in["blueCount"], 4)
        self.assertEqual(solver_in["minGold"], 1)
        self.assertEqual(solver_in["minPurple"], 2)
        self.assertEqual(solver_in["minRed"], 1)

        # 2. 未知字段严格为 None，绝不用 0 填充
        self.assertIsNone(solver_in["greenAvg"])
        self.assertIsNone(solver_in["greenCount"])
        self.assertIsNone(solver_in["whiteAvg"])
        self.assertIsNone(solver_in["whiteCount"])
        self.assertIsNone(solver_in["goldTotal"])

        # 3. 已知藏品格式化为 0.6 字符串
        self.assertEqual(solver_in["knownGold"], "万有星仪")
        self.assertEqual(solver_in["knownPurple"], "拈花小像+金角月芒")
        self.assertEqual(solver_in["knownRed"], "创生之柱")

        # 4. 仪器与环境解耦
        self.assertEqual(solver_in["toolGroup"], "group1", "solverToolGroup must be group1, ignoring lobbyToolGroup")
        self.assertEqual(solver_in["venue"], "中级场 · 珊瑚场")
        self.assertEqual(solver_in["fieldCondition"], "standard")
        self.assertEqual(solver_in["character"], "达芙蒂尔")

        # 5. 成本与出价
        self.assertEqual(solver_in["cost"], 60000)
        self.assertEqual(solver_in["round"], 3)
        self.assertEqual(solver_in["leaderBid"], 450000)

        # 6. publicInfo 嵌套
        self.assertEqual(solver_in["publicInfo"]["totalItems"], 66)
        self.assertEqual(solver_in["publicInfo"]["totalGrid"], 84)

    def test_real_1412_fixture_adapter_output(self):
        """B. 验证 14:12 真人局事实在 Adapter 转换后的精准性 (包括 minCount unknown 保持 None)"""
        real_1412_canonical = {
            "schemaVersion": 7,
            "environment": {
                "venue": "shanhu",
                "venueName": "中级场 · 珊瑚场",
                "box": "琉璃宝箱（宝石类概率提升）",
                "boxType": "glass",
                "fieldCondition": "standard"
            },
            "loadout": {
                "character": "达芙蒂尔",
                "lobbyToolGroup": "特供大型藏品的仪器组",
                "solverToolGroup": "group1"
            },
            "costs": {
                "entry": 5000,
                "intel": 45000,
                "other": 0,
                "sunkCost": 50000,
                "futureIncrementalCost": 0,
                "total": 50000
            },
            "publicIntel": {
                "q": 39,
                "totalItems": 66,
                "totalGrid": None,
                "avgValueBasis": "unknown"
            },
            "qualities": {
                "gold": {
                    "avg": 61944,
                    "count": None,
                    "minCount": None,
                    "total": None,
                    "grid": None,
                    "knownItems": []
                },
                "purple": {
                    "avg": 3904,
                    "count": 25,
                    "minCount": None,
                    "grid": None,
                    "knownItems": []
                },
                "red": {
                    "count": None,
                    "minCount": None,
                    "knownItems": []
                },
                "blue": {"count": None, "avg": None, "grid": None},
                "green": {"count": None, "avg": None, "grid": None},
                "white": {"count": None, "avg": None, "grid": None}
            },
            "bidding": {
                "round": 4,
                "leaderBid": 1099998,
                "myName": "秋星祭02"
            }
        }

        solver_in = canonical_to_v06_solver_input(real_1412_canonical)

        self.assertEqual(solver_in["q"], 39)
        self.assertEqual(solver_in["goldAvg"], 61944)
        self.assertEqual(solver_in["avg"], 61944)
        self.assertEqual(solver_in["purpleAvg"], 3904)
        self.assertEqual(solver_in["p"], 25)
        self.assertEqual(solver_in["purple"], 25)
        self.assertEqual(solver_in["purpleCount"], 25)
        self.assertEqual(solver_in["box"], "琉璃宝箱（宝石类概率提升）")
        self.assertEqual(solver_in["fieldCondition"], "standard")
        self.assertEqual(solver_in["toolGroup"], "group1")
        self.assertEqual(solver_in["character"], "达芙蒂尔")
        self.assertEqual(solver_in["publicInfo"]["totalItems"], 66)
        self.assertEqual(solver_in["knownGold"], "")
        self.assertEqual(solver_in["knownPurple"], "")
        self.assertEqual(solver_in["knownRed"], "")

        # 重点：unknown 字段严格为 None
        self.assertIsNone(solver_in["minGold"], "Canonical unknown minCount must stay None, not 0")
        self.assertIsNone(solver_in["minPurple"], "Canonical unknown minCount must stay None, not 0")
        self.assertIsNone(solver_in["minRed"], "Canonical unknown minCount must stay None, not 0")
        self.assertIsNone(solver_in["blueAvg"])
        self.assertIsNone(solver_in["greenAvg"])
        self.assertIsNone(solver_in["whiteAvg"])
        self.assertIsNone(solver_in["goldTotal"])

    def test_single_sample_historical_round_trip(self):
        """C1. 验证单条 15:53 经典样本的双向升降级与语义完整性"""
        legacy_sample = {
            "id": "legacy-test-1553",
            "productVersion": "v0.6",
            "playedAt": "2026-08-13T15:53:00+08:00",
            "venue": "中级场 · 珊瑚场",
            "box": "实木宝箱 · 中级藏品概率提升",
            "fieldCondition": "standard",
            "character": "达芙蒂尔",
            "toolGroup": "group1",
            "q": 9,
            "goldAvg": 33538,
            "purpleCount": 5,
            "knownGold": "51077",
            "knownPurple": "18075+8128",
            "cost": 50000,
            "costs": {"entry": 5000, "intel": 45000, "other": 0, "sunkCost": 50000, "total": 50000}
        }

        # Step 1: 升级为 Canonical v7
        canonical = v06_record_to_canonical(legacy_sample)
        self.assertEqual(canonical["schemaVersion"], 7)
        self.assertEqual(canonical["environment"]["venue"], "shanhu")
        self.assertEqual(canonical["qualities"]["gold"]["avg"], 33538)
        self.assertEqual(canonical["qualities"]["purple"]["count"], 5)
        self.assertEqual(len(canonical["qualities"]["gold"]["knownItems"]), 1)
        self.assertEqual(len(canonical["qualities"]["purple"]["knownItems"]), 2)

        # Step 2: 降级回 0.6 Solver Input
        adapted_solver_in = canonical_to_v06_solver_input(canonical)
        self.assertEqual(adapted_solver_in["q"], 9)
        self.assertEqual(adapted_solver_in["goldAvg"], 33538)
        self.assertEqual(adapted_solver_in["avg"], 33538)
        self.assertEqual(adapted_solver_in["p"], 5)
        self.assertEqual(adapted_solver_in["purple"], 5)
        self.assertEqual(adapted_solver_in["purpleCount"], 5)
        self.assertEqual(adapted_solver_in["knownGold"], "51077")
        self.assertEqual(adapted_solver_in["knownPurple"], "18075+8128")
        self.assertEqual(adapted_solver_in["toolGroup"], "group1")
        self.assertEqual(adapted_solver_in["venue"], "中级场 · 珊瑚场")

    def test_database_version_split_round_trip(self):
        """C. 分流测试：验证 142 条 v0.6 历史记录与 9 条 v0.65 记录的独立无损转换"""
        db_path = os.path.join(PROJECT_ROOT, "异环拍卖数据.json")
        if not os.path.exists(db_path):
            self.skipTest("Database file missing")

        with open(db_path, "r", encoding="utf-8") as f:
            db = json.load(f)
        records = db.get("records", [])

        v06_records = [r for r in records if r.get("productVersion") == "v0.6" or not str(r.get("productVersion", "")).startswith("v0.65")]
        v065_records = [r for r in records if str(r.get("productVersion", "")).startswith("v0.65")]

        self.assertGreaterEqual(len(v06_records), 142, "Should have at least 142 v0.6 historical records")
        if v065_records:
            self.assertGreaterEqual(len(v065_records), 1, "Should have v0.65 records if present")

        # 1. 142 条 v0.6 记录验证
        for rec in v06_records:
            canonical = v06_record_to_canonical(rec)
            self.assertEqual(canonical["schemaVersion"], 7)
            solver_in = canonical_to_v06_solver_input(canonical)
            if rec.get("q") is not None:
                self.assertEqual(solver_in["q"], rec["q"])
            if rec.get("goldAvg") is not None:
                self.assertEqual(solver_in["goldAvg"], rec["goldAvg"])
                self.assertEqual(solver_in["avg"], rec["goldAvg"])
            if rec.get("purpleAvg") is not None:
                self.assertEqual(solver_in["purpleAvg"], rec["purpleAvg"])

        # 2. 9 条 v0.65 记录验证
        for rec in v065_records:
            canonical = v065_record_to_canonical(rec)
            self.assertEqual(canonical["schemaVersion"], 7)
            solver_in = canonical_to_v06_solver_input(canonical)
            if rec.get("q") is not None:
                self.assertEqual(solver_in["q"], rec["q"])
            if rec.get("goldAvg") is not None:
                self.assertEqual(solver_in["goldAvg"], rec["goldAvg"])
                self.assertEqual(solver_in["avg"], rec["goldAvg"])
            if rec.get("purpleAvg") is not None:
                self.assertEqual(solver_in["purpleAvg"], rec["purpleAvg"])

    def test_js_solver_constraint_recovery_comparison(self):
        """D. 对比实验：证明 Adapter 恢复 0.6 原生约束与候选空间收敛，并输出完整 explainability"""
        node_script = """
        const engine = require('./core/auction_engine_v06.js');
        const adapter = require('./core/v06_adapter.js');

        // 15:53 经典场景输入
        // 场景：Q=9, GoldAvg=33538, Purple=5, 已知金色=万有星仪(51077), 已知紫色=拈花小像(18075)+金角月芒(8128)
        const canonical1553 = {
          schemaVersion: 7,
          environment: { venue: "shanhu", box: "实木宝箱 · 中级藏品概率提升", fieldCondition: "standard" },
          loadout: { character: "达芙蒂尔", solverToolGroup: "group1", lobbyToolGroup: "特供大型藏品的仪器组" },
          publicIntel: { q: 9 },
          qualities: {
            gold: { avg: 33538, knownItems: [{ name: "万有星仪", price: 51077 }] },
            purple: { count: 5, knownItems: [{ name: "拈花小像", price: 18075 }, { name: "金角月芒", price: 8128 }] }
          },
          costs: { total: 50000 }
        };

        // A. 错误场景：未经过 Adapter 的 0.65 扁平 Record (knownGold 为空或嵌套在 identifiedShapes 中，未扁平化)
        const unadaptedPayload = {
          q: 9,
          avg: 33538,
          purple: 5,
          identifiedShapes: { knownGold: ["万有星仪"], knownPurple: ["拈花小像", "金角月芒"] },
          toolGroup: "特供大型藏品的仪器组" // 错误的大厅仪器名
        };
        const unadaptedResult = engine.solveExactStatesSync(unadaptedPayload);

        // B. 正确场景：经过 Adapter 转换
        const adaptedPayload = adapter.canonicalToV06SolverInput(canonical1553);
        const adaptedResult = engine.solveExactStatesSync(adaptedPayload);
        const pipelineResult = engine.solveAuctionPipeline(adaptedPayload, []);

        const candidateGs = [...new Set(adaptedResult.states.map(s => s.G))].sort((a, b) => a - b);
        const candidatePs = [...new Set(adaptedResult.states.map(s => s.P))].sort((a, b) => a - b);

        const resultJson = {
          unadapted: {
            solverStatus: unadaptedResult.solverStatus,
            stateCount: unadaptedResult.states ? unadaptedResult.states.length : 0,
            knownGoldParsed: unadaptedPayload.knownGold || ""
          },
          adapted: {
            solverStatus: adaptedResult.solverStatus,
            pipelineStatus: pipelineResult.solverStatus,
            candidateGs,
            candidatePs,
            stateCount: adaptedResult.states ? adaptedResult.states.length : 0,
            knownGoldInput: adaptedPayload.knownGold,
            knownPurpleInput: adaptedPayload.knownPurple,
            statesSample: (adaptedResult.states || []).map(s => `${s.G}/${s.P}/${s.R}`),
            formalValue: pipelineResult.formalValue,
            decision: pipelineResult.decision
          }
        };

        console.log(JSON.stringify(resultJson));
        """

        res = subprocess.run(["node", "-e", node_script], cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res.returncode, 0, f"Node script failed: {res.stderr}")

        data = json.loads(res.stdout.strip())
        adapted = data["adapted"]
        unadapted = data["unadapted"]

        # 1. 未适配时：0.6 收到的 knownGold 为空字符串
        self.assertEqual(unadapted["knownGoldParsed"], "")

        # 2. 适配后：0.6 收到格式化的 '万有星仪' 与 '拈花小像+金角月芒'
        self.assertEqual(adapted["knownGoldInput"], "万有星仪")
        self.assertEqual(adapted["knownPurpleInput"], "拈花小像+金角月芒")

        # 3. 适配后状态求解完全合法并收敛
        self.assertEqual(adapted["solverStatus"], "valid")
        self.assertEqual(adapted["pipelineStatus"], "valid")
        self.assertIn("3/5/1", adapted["statesSample"], "Classic 15:53 state G3/P5/R1 must be present")
        self.assertIn("4/5/0", adapted["statesSample"], "Classic 15:53 state G4/P5/R0 must be present")
        self.assertEqual(set(adapted["candidateGs"]), {3, 4}, "Candidate Gs must strictly constrain to 3 and 4")
        self.assertEqual(adapted["candidatePs"], [5], "Candidate Ps must strictly constrain to 5")

        # 4. 可解释性与决策输出完整保留
        self.assertIsNotNone(adapted["formalValue"])
        self.assertIsNotNone(adapted["decision"])
        self.assertIn("targetLine", adapted["decision"])
        self.assertIn("globalLine", adapted["decision"])
        self.assertIn("marginalLine", adapted["decision"])


if __name__ == "__main__":
    unittest.main()
