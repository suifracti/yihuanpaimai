import json
import subprocess
import unittest
from pathlib import Path
from current_match import CurrentMatch
from live_match_control import LiveMatchControl
from live_shadow import _solver_ctx, _profile_cache_key
from v06_adapter import canonical_to_v06_solver_input

ROOT = Path(__file__).resolve().parents[1]


class DarkControlTransportTests(unittest.TestCase):
    def test_saved_and_flat_both_adapters_keep_zero_unknown_and_distinct_bid(self):
        for value in (123456, 0, None):
            current = CurrentMatch()
            current.apply_facts({'fieldCondition':'dark', 'privateBidCap':value,
                                 'bidActionCount':value, 'leaderBid':900000}, intent='confirm')
            saved = json.loads(json.dumps(current.to_canonical()))
            restored = CurrentMatch()
            restored.apply_facts(saved, intent='snapshot')
            for data in (saved, dict(restored.facts)):
                js = "const fs=require('fs'),a=require('./core/v06_adapter.js');console.log(JSON.stringify(a.canonicalToV06SolverInput(JSON.parse(fs.readFileSync(0,'utf8')))));"
                results = [canonical_to_v06_solver_input(data), json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'-e',js],cwd=ROOT,input=json.dumps(data),text=True,encoding='utf-8'))]
                for adapted in results:
                    self.assertEqual(adapted['leaderBid'], 900000)
                    ctx = _solver_ctx(adapted)
                    for key in ('privateBidCap', 'bidActionCount'):
                        self.assertEqual(ctx[key], value)
                    result = json.loads(subprocess.check_output([str(ROOT/'runtime/node.exe'),'core/live_shadow_runtime.js','--once'],cwd=ROOT,input=json.dumps({'ctx':{**ctx,'q':1,'avg':60040,'knownGold':'算力面包','goldCount':1,'purple':0,'redCount':0,'blueCount':0,'greenCount':0,'whiteCount':0},'records':[]}),text=True,encoding='utf-8'))
                    frozen = result['frozenPrediction']
                    self.assertEqual(frozen['privateBidCap'], value)
                    self.assertEqual(frozen['bidActionCount'], value)
                    self.assertIsNone(frozen['decision']['expectedProfit'])

    def test_rejection_clear_override_cache_and_next_match(self):
        current = CurrentMatch()
        for key in ('privateBidCap', 'bidActionCount'):
            current.apply_facts({key:100}, intent='confirm')
            for raw in (True,-1,1.5,'1e3','1.9',2**53):
                before = current.snapshot()
                with self.assertRaises(ValueError):
                    current.apply_facts({'q':10,key:raw}, intent='confirm')
                self.assertEqual(current.snapshot(), before)
            original = {key:100,'publicInfo':{key:100}}
            control = LiveMatchControl()
            control.match_id = current.id
            control.overrides = {key:None}
            patched = control.apply_to_frame(dict(original), current)
            self.assertIsNone(_solver_ctx(patched)[key])
            self.assertNotEqual(_profile_cache_key(original,0),_profile_cache_key(patched,0))
            self.assertEqual(original['publicInfo'][key],100)
            current.apply_facts({},cleared_fields=[key])
            self.assertIsNone(current.to_canonical()['bidding'][key])
            current.apply_facts({key:0},intent='confirm')
            self.assertTrue(current.has_any_fact())
        current.begin_next_match()
        self.assertIsNone(current.snapshot()['privateBidCap'])
        self.assertIsNone(current.snapshot()['bidActionCount'])
