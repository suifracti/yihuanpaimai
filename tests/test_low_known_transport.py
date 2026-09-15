import json,subprocess,unittest
from pathlib import Path
from current_match import CurrentMatch
from v06_adapter import canonical_to_v06_solver_input
from live_shadow import _solver_ctx,_profile_cache_key
from live_match_control import LiveMatchControl
ROOT=Path(__file__).resolve().parents[1]

class LowKnownTransportTests(unittest.TestCase):
    def test_both_adapters_preserve_real_names_candidates_and_clear(self):
        catalog=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',"console.log(JSON.stringify(require('./core/auction_engine_v06.js').effectiveCatalog({})))"],cwd=ROOT,text=True,encoding='utf-8'))
        fields={'known'+c.title():catalog[c][0][0]+'/'+catalog[c][1][0]+'+'+catalog[c][0][0] for c in ('blue','green','white')}
        match=CurrentMatch();match.apply_facts(fields,source='manual',intent='confirm')
        for data in (match.to_canonical(),fields):
            py=canonical_to_v06_solver_input(data)
            script="const fs=require('fs'),a=require('./core/v06_adapter.js');console.log(JSON.stringify(a.canonicalToV06SolverInput(JSON.parse(fs.readFileSync(0,'utf8')))));"
            run=subprocess.run([str(ROOT/'runtime/node.exe'),'-e',script],cwd=ROOT,input=json.dumps(data),capture_output=True,text=True,encoding='utf-8',check=True)
            js=json.loads(run.stdout)
            for key,value in fields.items():
                self.assertEqual(py[key],value);self.assertEqual(js[key],value)
                self.assertEqual(_solver_ctx(py)[key],value)
        control=LiveMatchControl();control.match_id=match.id
        original={**fields,'publicInfo':dict(fields)}
        before=_profile_cache_key(original,0)
        for key in fields:
            control.overrides={key:''}
            ctx=control.apply_to_frame(dict(original),match)
            self.assertEqual(_solver_ctx(ctx)[key],'')
            self.assertEqual(_solver_ctx(ctx)['publicInfo'][key],'')
            self.assertNotEqual(_profile_cache_key(ctx,0),before)
            self.assertEqual(original['publicInfo'][key],fields[key])

    def test_red_grid_canonical_flat_zero_and_clear(self):
        script="const fs=require('fs'),a=require('./core/v06_adapter.js');console.log(JSON.stringify(a.canonicalToV06SolverInput(JSON.parse(fs.readFileSync(0,'utf8')))));"
        for value in (4,0,None):
            match=CurrentMatch();match.apply_facts({'redGrid':value},source='manual',intent='confirm')
            for data in (match.to_canonical(),{'redGrid':value}):
                py=canonical_to_v06_solver_input(data)
                js=json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',script],cwd=ROOT,input=json.dumps(data),text=True,encoding='utf-8'))
                for result in (py,js):
                    self.assertEqual(result['redGrid'],value)
                    self.assertEqual(result['publicInfo']['redGrid'],value)
                    self.assertEqual(_solver_ctx(result)['redGrid'],value)
