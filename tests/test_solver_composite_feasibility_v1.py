"""Issue #34: hand-checkable composite constraints, using the 2026-08-13 catalog.

Synthetic current facts, not settlement labels. Q counts purple/gold/red items;
totalGrid is observed occupied area, not a guessed warehouse capacity.
Bread (60040, 2 cells) + fish (111111, 4 cells) have total 171151:
floor average 85575, nearest average 85576. Mud (124816, 12 cells)
is the other unresolved gold identity. A confirmed vase (5997, 2 cells)
must not be replaced by same-price headphones (5997, 4 cells).
With one red tear (50000, 1 cell) and one 1-cell item in each low tier,
the legal seven-item inventory occupies 12 cells. 14 cells is impossible
with the vase, but legal with headphones or an unresolved price-only clue.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = str(ROOT / "runtime/node.exe") if (ROOT / "runtime/node.exe").exists() else shutil.which("node")
FACTS = {
    "matchId": "synthetic-issue34", "catalogVersion": "2026-08-13",
    "fieldCondition": "standard", "avgValueBasis": "base", "roundingMode": "floor",
    "q": 4, "goldCount": 2, "purpleCount": 1, "redCount": 1,
    "avg": 85575, "purpleAvg": 5997,
    "knownGold": "算力面包+金龙鱼/罐装随心泥", "knownPurple": "红釉花瓶",
    "knownRed": "「泪滴」", "blueCount": 1, "greenCount": 1, "whiteCount": 1,
    "blueAvg": 1012, "greenAvg": 610, "whiteAvg": 110,
    "knownBlue": "无梦果核", "knownGreen": "金月", "knownWhite": "花雕碗",
    "totalItems": 7, "totalGrid": 12,
    "warehouse": {"coverageStatus": "PARTIAL"},
}


def run_node(script, payload):
    result = subprocess.run([NODE, "-e", script], input=json.dumps(payload), cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class CompositeFeasibilityTests(unittest.TestCase):
    def test_confirmed_identity_price_and_area_must_share_one_witness(self):
        cases = [
            ({}, "valid"),
            ({"totalGrid": 14}, "no-match"),
            ({"totalGrid": None}, "valid"),
            ({"totalGrid": 14, "knownPurple": ""}, "valid"),
            ({"totalGrid": 14, "knownPurple": "5997"}, "valid"),
            ({"totalGrid": 14, "knownPurple": "红釉花瓶/青釉花瓶"}, "no-match"),
            ({"totalGrid": 14, "knownPurple": "红釉花瓶/「方盒科技」耳机"}, "valid"),
            ({"totalGrid": 14, "knownPurple": "「方盒科技」耳机"}, "valid"),
            ({"goldGrid": 14}, "no-match"),  # mud fits area but fails the average
            ({"avg": 85576}, "no-match"),
            ({"avg": 85576, "roundingMode": "nearest"}, "valid"),
            ({"fieldCondition": "purple_double", "purpleAvg": 11994}, "valid"),
            ({"fieldCondition": "purple_double", "purpleAvg": 11994, "totalGrid": 14}, "no-match"),
        ]
        output = run_node("""
          const fs=require('fs'),e=require('./core/auction_engine_v06.js');
          const {base,cases}=JSON.parse(fs.readFileSync(0,'utf8'));
          console.log(JSON.stringify(cases.map(([patch])=>{
            const raw={...base,...patch};
            return [e.solveAuctionPipeline(raw,[]),e.solveAuctionPipeline(e.normalizeKnownContext(raw),[])];
          })));
        """, {"base": FACTS, "cases": cases})
        for (patch, expected), paths in zip(cases, output):
            for result in paths:
                with self.subTest(patch=patch):
                    self.assertEqual(result["solverStatus"], expected)
                    self.assertEqual(result["stateCount"], int(expected == "valid"))
                    if expected == "valid":
                        self.assertEqual(result["states"][0]["sampleCombo"], [60040, 111111])
                        self.assertEqual(result["degradationLevel"], "structural_only")
                    self.assertIsNone(result["decision"].get("recommendedMax"))
                    self.assertIsNone(result["decision"].get("valueP50"))

    def test_production_runtime_rejects_impossible_and_keeps_legal_inventory(self):
        for grid, expected in ((12, "valid"), (14, "no-match")):
            result = subprocess.run([NODE, str(ROOT / "core/live_shadow_runtime.js"), "--once"],
                                    input=json.dumps({"ctx": {**FACTS, "totalGrid": grid}, "records": []}),
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            out = json.loads(result.stdout)
            self.assertEqual(bool(out["exactStates"]), expected == "valid")
            self.assertEqual(bool(out["expandedStates"]), expected == "valid")
            snapshot = out["predictionSnapshot"]
            self.assertEqual(snapshot["status"]["solverStatus"], expected)

    def test_missing_average_stays_fallback_even_with_partial_candidates(self):
        out = run_node("""
          const fs=require('fs'),e=require('./core/auction_engine_v06.js');
          const ctx=JSON.parse(fs.readFileSync(0,'utf8'));ctx.avg=null;ctx.goldAvg=null;
          console.log(JSON.stringify(e.solveAuctionPipeline(ctx,[])));
        """, FACTS)
        self.assertEqual(out["solverStatus"], "fallback")
        self.assertEqual(out["stateCount"], 0)
        self.assertIsNone(out["formalValue"]["p50"])
        self.assertIsNone(out["decision"]["targetLine"])

    def test_real_worker_budget_exhaustion_is_not_strict_no_match(self):
        # Execute the existing Worker, replacing only its monotonic clock. This
        # forces the first deadline check past its budget without a slow/flaky
        # wall-clock benchmark or a mocked Solver result.
        out = run_node(r"""
          const fs=require('fs'),vm=require('vm'),e=require('./core/auction_engine_v06.js');
          const source=fs.readFileSync('core/solver_core_v06.js','utf8')
            .match(/const WORKER_SOURCE = `([\s\S]*?)`;/)[1];
          const results=[33538,60040].map(goldAvg=>{
            let calls=0;const messages=[];
            const host={performance:{now:()=> (++calls===1?0:10000)},
              postMessage:message=>messages.push(message)};
            host.self=host;vm.runInNewContext(source,host);
            host.onmessage({data:{goldPrices:e.GOLD_ITEMS.map(x=>x[1]),
              goldGrids:e.GOLD_ITEMS.map(x=>x[2].split('x').reduce((a,b)=>a*Number(b),1)),
              purplePrices:e.PURPLE_ITEMS.map(x=>x[1]),redPrices:e.RED_ITEMS.map(x=>x[1]),
              q:4,goldAvg,goldTotal:null,goldGrid:null,purpleAvg:null,
              fixedGold:null,fixedPurple:null,fixedRed:null,minGold:1,minPurple:0,minRed:0,
              mode:'floor',groups:[],purpleGroups:[],redGroups:[],repeat:2,limit:10,
              goldOnly:false,timeBudgetMs:250}});
            return messages.findLast(message=>message.type==='done');
          });console.log(JSON.stringify(results));
        """, None)
        for result, expected in zip(out, ("timeout", "incomplete")):
            self.assertFalse(result["searchCompleted"])
            self.assertEqual(result["solverStatus"], expected)
            self.assertEqual(bool(result["states"]), expected == "incomplete")


if __name__ == "__main__":
    unittest.main()
