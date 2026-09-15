import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from live_shadow import _profile_cache_key,_solver_ctx,_PROFILE_DETAIL_FIELDS
class LiveDetailTransportTests(unittest.TestCase):
 def test_every_supported_detail_reaches_runtime_and_invalidates_cache(self):
  base={'q':12,'goldAvg':74379}
  baseline=_profile_cache_key(base,1)
  for field in (*_PROFILE_DETAIL_FIELDS,'totalGrid'):
   for value in (0,7):
    with self.subTest(field=field,value=value):
     ctx={**base,field:value};result=_solver_ctx(ctx)
     self.assertEqual(result[field],value)
     self.assertEqual(result['publicInfo'][field],value)
     self.assertNotEqual(_profile_cache_key(ctx,1),baseline)
 def test_total_grid_alias_equivalence_and_nested_values(self):
  self.assertEqual(_profile_cache_key({'totalGrid':10},1),_profile_cache_key({'totalGrids':10},1))
  result=_solver_ctx({'totalGrids':30,'publicInfo':{'totalGrid':0,'blueCount':0,'goldGrid':9}})
  self.assertEqual(result['totalGrid'],0)
  self.assertEqual(result['totalGrids'],0)
  self.assertEqual(result['blueCount'],0)
  self.assertEqual(result['goldGrid'],9)
  self.assertNotEqual(_profile_cache_key({'publicInfo':{'goldGrid':9}},1),_profile_cache_key({'publicInfo':{'goldGrid':10}},1))
 def test_forwarded_details_change_real_history_similarity(self):
  import subprocess,json
  root=Path(__file__).resolve().parents[1]
  base={'q':12,'goldAvg':74379}
  supplied=_solver_ctx({**base,'totalItems':20,'totalGrid':80,'goldGrid':12,'purpleGrid':16,'blueCount':0})
  script="const p=require('./core/shadow_profile_v06.js');const record={totalItems:20,totalGrid:80,goldGrid:12,purpleGrid:16,blueCount:0};console.log(JSON.stringify([p.similarityFor("+json.dumps(_solver_ctx(base))+",record),p.similarityFor("+json.dumps(supplied)+",record)]));"
  run=subprocess.run([str(root/'runtime/node.exe'),'-e',script],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=20)
  self.assertEqual(run.returncode,0,run.stderr)
  before,after=json.loads(run.stdout)
  self.assertGreater(after['score'],before['score'])
if __name__=='__main__':unittest.main()
