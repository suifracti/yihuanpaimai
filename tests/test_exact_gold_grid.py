import json,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'core'))
class ExactGoldGridTests(unittest.TestCase):
 def test_real_catalog_gold_area_and_reserved_known_items(self):
  script="""const e=require('./core/auction_engine_v06.js');const rows=[];
  for(const item of e.effectiveCatalog({}).gold.slice(-10)){
   const [w,h]=item[2].split('x').map(Number),area=w*h;
   const ctx={q:1,avg:item[1],purple:0,redCount:0,knownGold:item[0]};
   rows.push([e.solveExactStatesSync({...ctx,goldGrid:area}).states.length,
    e.solveExactStatesSync({...ctx,goldGrid:area+100}).states.length,
    e.solveExactStatesSync({...ctx,totalGrid:area-1}).states.length]);
  }console.log(JSON.stringify(rows));"""
  run=subprocess.run([str(ROOT/'runtime/node.exe'),'-e',script],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
  self.assertEqual(run.returncode,0,run.stderr)
  for good,wrong,too_small in json.loads(run.stdout):
   self.assertGreater(good,0);self.assertEqual(wrong,0);self.assertEqual(too_small,0)
 def test_production_runtime_honors_gold_grid(self):
  for grid,expected in ((2,True),(3,False)):
   request={'ctx':{'matchId':'grid-runtime','q':1,'avg':60040,'goldAvg':60040,'purple':0,'goldCount':1,'redCount':0,'knownGold':'算力面包','goldGrid':grid,'publicInfo':{'goldGrid':grid}},'records':[]}
   run=subprocess.run([str(ROOT/'runtime/node.exe'),str(ROOT/'core/live_shadow_runtime.js'),'--once'],input=json.dumps(request),capture_output=True,text=True,encoding='utf-8',timeout=30)
   self.assertEqual(run.returncode,0,run.stderr)
   result=json.loads(run.stdout)
   self.assertEqual(bool(result['exactStates']),expected)
   self.assertEqual(bool(result['expandedStates']),expected)
 def test_purple_real_catalog_area_known_slots_and_total_lower_bound(self):
  script="""const e=require('./core/auction_engine_v06.js');const out=[];
  for(const item of e.effectiveCatalog({}).purple.slice(0,8)){
   const [w,h]=item[2].split('x').map(Number),area=w*h;
   const base={q:2,avg:60040,goldCount:1,purple:1,redCount:0,knownGold:'算力面包',knownPurpleGroups:[[[item[1]],1]]};
   out.push([e.solveExactStatesSync({...base,purpleGrid:area,totalGrid:2+area}).states.length,
    e.solveExactStatesSync({...base,purpleGrid:area+100}).states.length,
    e.solveExactStatesSync({...base,purpleGrid:area,totalGrid:area+1}).states.length,
    e.solveExactStatesSync({...base,q:4,purple:3,purpleGrid:area*3,knownPurpleGroups:[[[item[1]],3]]}).states.length]);
  }console.log(JSON.stringify(out));"""
  run=subprocess.run([str(ROOT/'runtime/node.exe'),'-e',script],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
  self.assertEqual(run.returncode,0,run.stderr)
  for valid,wrong,small,reused in json.loads(run.stdout):
   self.assertGreater(valid,0);self.assertEqual((wrong,small,reused),(0,0,0))
 def test_production_runtime_purple_grid(self):
  script="const e=require('./core/auction_engine_v06.js');console.log(JSON.stringify(e.effectiveCatalog({}).purple[0]));"
  item=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',script],cwd=ROOT,text=True,encoding='utf-8'))
  area=1
  for size in item[2].split('x'):area*=int(size)
  for grid,expected in ((area,True),(area+100,False)):
   request={'ctx':{'matchId':'purple-grid-runtime','q':2,'avg':60040,'goldAvg':60040,'purple':1,'goldCount':1,'redCount':0,'knownGold':'算力面包','knownPurple':item[0],'publicInfo':{'purpleGrid':grid}},'records':[]}
   run=subprocess.run([str(ROOT/'runtime/node.exe'),str(ROOT/'core/live_shadow_runtime.js'),'--once'],input=json.dumps(request),capture_output=True,text=True,encoding='utf-8',timeout=30)
   self.assertEqual(run.returncode,0,run.stderr)
   result=json.loads(run.stdout)
   self.assertEqual(bool(result['exactStates']),expected)
   self.assertEqual(bool(result['expandedStates']),expected)
 def test_whole_quantity_and_area_consistency_in_runtime(self):
  base={'matchId':'whole-grid','q':1,'avg':60040,'goldAvg':60040,'purple':0,'goldCount':1,'redCount':0,'knownGold':'算力面包'}
  cases=[({'totalItems':1,'totalGrid':2},True),
         ({'totalItems':1,'totalGrid':3},False),
         ({'blueCount':0,'blueGrid':1},False),
         ({'blueCount':2,'blueGrid':1},False),
         ({'blueCount':2,'totalItems':2},False),
         ({'blueCount':1,'blueGrid':2,'greenCount':0,'whiteCount':0,'totalItems':2,'totalGrid':4},True),
         ({'blueCount':1,'blueGrid':2,'greenCount':0,'whiteCount':0,'totalItems':2,'totalGrid':5},False),
         ({'redGrid':1},False),
         ({'blueCount':True},False),
         ({'totalGrid':10},True)]
  for fields,expected in cases:
   with self.subTest(fields=fields):
    run=subprocess.run([str(ROOT/'runtime/node.exe'),str(ROOT/'core/live_shadow_runtime.js'),'--once'],input=json.dumps({'ctx':{**base,**fields},'records':[]}),capture_output=True,text=True,encoding='utf-8',timeout=30)
    self.assertEqual(run.returncode,0,run.stderr)
    result=json.loads(run.stdout)
    self.assertEqual(bool(result['exactStates']),expected)
    self.assertEqual(bool(result['expandedStates']),expected)
 def test_purple_price_area_joint_runtime(self):
  items=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',"const e=require('./core/auction_engine_v06.js');console.log(JSON.stringify(e.effectiveCatalog({}).purple));"],cwd=ROOT,text=True,encoding='utf-8'))
  def area(item):
   w,h=map(int,item[2].split('x'));return w*h
  first=next(item for item in items if sum(x[1]==item[1] for x in items)==1)
  other=next(item for item in items if area(item)!=area(first))
  base={'matchId':'price-grid','q':2,'avg':60040,'goldAvg':60040,'purple':1,'goldCount':1,'redCount':0,'knownGold':'算力面包'}
  cases=[({'purpleGrid':area(other)},True),({'purpleAvg':first[1]},True),
         ({'purpleGrid':area(other),'purpleAvg':first[1]},False),
         ({'purpleGrid':area(first),'purpleAvg':first[1]},True),
         ({'purpleGrid':area(first),'purpleAvg':first[1],'knownPurple':first[0]},True),
         ({'purpleGrid':area(first),'purpleAvg':max(x[1] for x in items)+1},False)]
  for fields,expected in cases:
   with self.subTest(fields=fields):
    run=subprocess.run([str(ROOT/'runtime/node.exe'),str(ROOT/'core/live_shadow_runtime.js'),'--once'],input=json.dumps({'ctx':{**base,**fields},'records':[]}),capture_output=True,text=True,encoding='utf-8',timeout=30)
    self.assertEqual(run.returncode,0,run.stderr)
    result=json.loads(run.stdout)
    self.assertEqual(bool(result['exactStates']),expected)
    self.assertEqual(bool(result['expandedStates']),expected)
 def test_manual_nested_correction_and_clear(self):
  from live_match_control import LiveMatchControl
  from current_match import CurrentMatch
  from live_shadow import _solver_ctx
  cm=CurrentMatch();control=LiveMatchControl();control.match_id=cm.id
  for value in (0,12,None):
   control.overrides={'goldGrid':value,'totalGrid':value}
   old={'goldGrid':99,'totalGrid':99}
   result=control.apply_to_frame({'publicInfo':old,'totalGrids':99},cm)
   self.assertEqual(_solver_ctx(result)['goldGrid'],value)
   self.assertEqual(_solver_ctx(result)['totalGrid'],value)
   self.assertEqual(old['goldGrid'],99)
if __name__=='__main__':unittest.main()
