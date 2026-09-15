import unittest,json,subprocess,os
from pathlib import Path
ROOT=Path(os.environ.get('NTE_TEST_RUNTIME_ROOT',str(Path(__file__).resolve().parents[1])))
class SparkleProductionTests(unittest.TestCase):
 def test_sparkle_cannot_publish_probability_or_bid(self):
  for condition in ('sparkle','闪耀之心','shining_heart'):
   ctx={'q':1,'goldCount':1,'purple':0,'redCount':0,'avg':60040,'knownGold':'算力面包','fieldCondition':condition,'playedAt':'2026-09-13T00:00:00+08:00','leaderBid':10000,'targetProfit':0,'costs':{'entry':5000,'intel':0,'other':0,'total':5000}}
   run=subprocess.run([str(ROOT/'runtime/node.exe'),'core/live_shadow_runtime.js','--once'],cwd=ROOT,input=json.dumps({'ctx':ctx,'records':[]}),text=True,encoding='utf-8',capture_output=True,check=True)
   d=json.loads(run.stdout);p=d['predictionSnapshot'];f=d['frozenPrediction']
   self.assertEqual(p['status']['solverStatus'],'fallback')
   self.assertIsNone(d['probabilityProfile']);self.assertIsNone(d['supportCaptureEnvelope'])
   self.assertTrue(all(v is None for v in (p['forecast']['quantiles'] or {}).values()),p)
   for k in ('globalLine','targetLine','marginalLine','estimate'):self.assertIsNone(f.get(k),(k,f))
   self.assertIn('概率',f['decision']['actionReason'])
   direct=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',"const fs=require('fs'),e=require('./core/auction_engine_v06.js');console.log(JSON.stringify(e.solveAuctionPipeline(JSON.parse(fs.readFileSync(0,'utf8')))))"],cwd=ROOT,input=json.dumps(ctx),text=True,encoding='utf-8'))
   self.assertEqual(direct['solverStatus'],'fallback');self.assertIsNone(direct['formalValue']['p50'])

 def test_strict_evidence_bounds_reach_production_snapshot(self):
  cases=[({},True,None,0),({'transformedOneByOneCount':0},True,0,0),
    ({'transformedOneByOneCount':2,'verifiedGemItems':'泪滴'},True,2,1),
    ({'transformedOneByOneCount':2,'verifiedGemItems':'「泪滴」*2'},True,2,2),
    ({'verifiedGemItems':'泪滴'},True,None,1),
    ({'transformedOneByOneCount':1,'verifiedGemItems':'泪滴*2'},False,None,None),
    ({'transformedOneByOneCount':True},False,None,None),
    ({'transformedOneByOneCount':1.5},False,None,None),
    ({'transformedOneByOneCount':-1},False,None,None),
    ({'verifiedGemItems':'泪'},False,None,None),
    ({'verifiedGemItems':[{'price':1}]},False,None,None),
    ({'verifiedGemItems':[{'name':'泪滴','price':1}]},False,None,None),
    ({'verifiedGemItems':'算力面包'},False,None,None),
    ({'verifiedGemItems':'泪滴*0'},False,None,None),
    ({'verifiedGemItems':'泪滴*9007199254740991'},False,None,None)]
  for evidence,valid,count,known in cases:
   with self.subTest(evidence=evidence):
    ctx={'q':1,'avg':60040,'purple':0,'knownGold':'算力面包','fieldCondition':'sparkle','sparkle':evidence}
    d=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'core/live_shadow_runtime.js','--once'],cwd=ROOT,input=json.dumps({'ctx':ctx,'records':[]}),text=True,encoding='utf-8'))
    b=d['predictionSnapshot']['evidenceBounds'];self.assertEqual(b,d['frozenPrediction']['evidenceBounds'])
    self.assertEqual(b['status'],'valid' if valid else 'invalid');self.assertFalse(b['probabilityKnown']);self.assertFalse(b['recommendationAllowed'])
    self.assertIsNone(d['predictionSnapshot']['forecast']['quantiles']);self.assertIsNone(d['probabilityProfile'])
    if not valid:self.assertIsNone(b['lower']);self.assertIsNone(b['upper']);continue
    self.assertEqual(b['count'],count);self.assertEqual(b['knownCount'],known)
    total=50000*known
    self.assertEqual(b['lower'],total+(count-known)*99 if count is not None else total)
    self.assertEqual(b['upper'],total+(count-known)*1314520 if count is not None else None)
