"""The visible profit amount must change both engines' actual decision cap."""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TargetProfitEffectiveTests(unittest.TestCase):
    def test_profit_zero_combined_roi_and_partial_coverage(self):
        script = r'''
function el(){return {value:'',options:[],children:[],dataset:{},style:{},classList:{add(){},remove(){},toggle(){},contains(){return false}},addEventListener(){},appendChild(){},closest(){return null},reset(){}};}
global.window=global; global.addEventListener=()=>{};
global.localStorage={getItem:()=>null,setItem(){},removeItem(){}};
global.document={documentElement:{dataset:{}},addEventListener(){},querySelector(){return el()},getElementById(){return el()},querySelectorAll(){return []}};
require('./core/solver_core_v06.js');
const engine=require('./core/auction_engine_v06.js');
const data={solverStatus:'valid',coverageRatio:1,rawShadow:{p20:300000,p50:400000,p80:500000},states:[{}]};
const costs={entry:5000,intel:5000,other:0,sunkCost:10000,futureIncrementalCost:0,total:10000};
const cases=[{}, {targetProfit:0}, {targetProfit:100000}, {targetProfit:0,targetROI:0.2},
 {targetProfit:100000,targetROI:0.2}, {targetProfit:0,targetROI:0}, {targetProfit:500000}];
let results=[];
for(const fn of [engine.calculateV06DecisionLines,global.calculateV06DecisionLines]){
 results.push(cases.map(c=>{const d=fn({costs,...c},data);return {safe:d.safeBuy,profit:d.targetProfit,roi:d.targetROI,p50:d.valueP50,global:d.globalLine,chase:d.marginalLine};}));
 results.push(fn({costs,targetProfit:0},{...data,coverageRatio:0.5}).safeBuy);
}
const full=engine.solveAuctionPipeline({q:12,goldAvg:74379,purple:7,costs,targetProfit:100000,leaderBid:350000,
 probabilityProfile:{coverageRatio:1,supportedStateCount:2,totalStateCount:2,supportedWeight:1,totalWeight:1,shadowWhole:{p20:300000,p50:400000,p80:500000}}});
results.push(full);
const live={q:12,goldAvg:74379,purple:7,costs,targetProfit:0,
 probabilityProfile:{coverageRatio:1,supportedStateCount:2,totalStateCount:2,supportedWeight:1,totalWeight:1,shadowWhole:{p20:300000,p50:400000,p80:500000}}};
results.push([389999,390000,390001,null].map(leaderBid=>engine.solveAuctionPipeline({...live,leaderBid}).decision));
console.log(JSON.stringify(results));
'''
        node = ROOT/'runtime/node.exe'
        result = subprocess.run([str(node) if node.exists() else 'node', '-e', script],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout[result.stdout.find('[[{'):])
        for rows in (values[0], values[2]):
            self.assertEqual([row['safe'] for row in rows], [360000,390000,290000,323333,290000,390000,0])
            self.assertEqual(rows[1]['profit'], 0)
            self.assertIsNone(rows[0]['roi'])
            self.assertEqual(rows[5]['roi'], 0)
            self.assertTrue(all(row['p50']==400000 and row['global']==390000 and row['chase']==400000 for row in rows))
        self.assertIsNone(values[1])
        self.assertIsNone(values[3])
        self.assertIn('已超目标利润价', str(values[4]))
        self.assertEqual([row['expectedProfit'] for row in values[5]], [1, 0, -1, None])
        self.assertIn('盈余', values[5][0]['actionDirective'])
        self.assertIn('刚好保本', values[5][1]['actionDirective'])
        self.assertIn('等待当前叫价', values[5][3]['actionDirective'])


if __name__ == '__main__':
    unittest.main()
