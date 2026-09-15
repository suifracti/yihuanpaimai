# -*- coding: utf-8 -*-
"""Node require() solver_core must match frozen 14:15 shared-core fixture."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "core")]

FIXTURE = ROOT / "tests" / "fixtures" / "shadow_1415_legacy.json"
DB_PATH = ROOT / "异环拍卖数据.json"


class TestP2ComputeParity(unittest.TestCase):
    def test_runtime_js_has_no_eval_or_string_replace_export(self):
        text = (ROOT / "core" / "live_shadow_runtime.js").read_text(encoding="utf-8")
        self.assertNotIn("eval(code)", text)
        self.assertNotIn("window.redProbabilityProfile=function", text)
        self.assertIn("require(path.join(__dirname, \"solver_core_v06.js\"))", text)
        core = (ROOT / "core" / "solver_core_v06.js").read_text(encoding="utf-8")
        self.assertIn("exportSolverCoreApi", core)
        self.assertIn("module.exports = api", core)

    def test_solver_core_exports_without_eval(self):
        script = r"""
function el(){return {value:'',options:[],children:[],dataset:{},style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},addEventListener(){},appendChild(){},closest(){return null},reset(){}};}
global.window=global; global.addEventListener=()=>{};
global.localStorage={getItem:()=>null,setItem(){},removeItem(){}};
global.document={documentElement:{dataset:{}},addEventListener(){},querySelector(){return el()},getElementById(){return el()},querySelectorAll(){return []}};
const core = require('./core/solver_core_v06.js');
if (typeof core.expandStatesForValuation !== 'function') process.exit(2);
if (typeof core.stateComponents !== 'function') process.exit(3);
if (typeof core.candidateStateWeight !== 'function') process.exit(4);
if (typeof core.redProbabilityProfile !== 'function') process.exit(5);
console.log(JSON.stringify({ok:true, via:'module.exports'}));
"""
        bundled = ROOT / "runtime" / "node.exe"
        node = str(bundled) if bundled.is_file() else "node"
        proc = subprocess.run([node, "-e", script], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout[proc.stdout.find("{"):])["ok"])

    def test_1415_profile_matches_fixture_via_node_runtime(self):
        if not DB_PATH.is_file() or not FIXTURE.is_file():
            self.skipTest("14:15 history or fixture missing")
        os.environ.setdefault("YIHUAN_DATA_ROOT", str(ROOT / "build" / "diagnosis_20260909" / "p2-parity-data"))
        from live_shadow import compute_live_probability_profile, reset_live_shadow_state
        reset_live_shadow_state()
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        ctx = {
            "scene": "IN_AUCTION", "round": 3, "q": 12, "goldAvg": 74379, "avg": 74379,
            "purple": 7, "box": "琉璃宝箱 · 宝石类概率提升", "venue": "中级场 · 珊瑚场",
            "lobbyVenue": "中级场 · 珊瑚场", "fieldCondition": "standard",
            "playedAt": "2026-08-17T14:15:59.030277", "lobbyEntryCost": 5000,
        }
        profile, meta = compute_live_probability_profile(ctx, db_path=str(DB_PATH), persist_runtime=True)
        reset_live_shadow_state()
        self.assertIsNotNone(profile)
        self.assertEqual(meta.get("computeHost"), "node")
        self.assertEqual(profile["supportedStateCount"], fixture["supportedStateCount"])
        self.assertAlmostEqual(profile["shadowWhole"]["p50"], fixture["shadowWhole"]["p50"], places=4)
        self.assertAlmostEqual(profile["shadowWhole"]["p20"], fixture["shadowWhole"]["p20"], places=4)
        self.assertAlmostEqual(profile["shadowWhole"]["p80"], fixture["shadowWhole"]["p80"], places=4)


if __name__ == "__main__":
    unittest.main()
