import json
import subprocess
import unittest
from pathlib import Path

from current_match import CurrentMatch
from live_match_control import LiveMatchControl
from live_shadow import _facts_ready, _profile_cache_key, _solver_ctx
from v06_adapter import canonical_to_v06_solver_input

ROOT = Path(__file__).resolve().parents[1]


def node(script, payload):
    return json.loads(subprocess.check_output(
        [str(ROOT / 'runtime/node.exe'), '-e', script], cwd=ROOT,
        input=json.dumps(payload), text=True, encoding='utf-8'))


class SparkleTransportTests(unittest.TestCase):
    def test_saved_facts_both_adapters_and_production_keep_bounds_and_hash(self):
        previous_hash = None
        for evidence, status, lower, upper in (
            ({'transformedOneByOneCount': 2, 'verifiedGemItems': '泪滴'}, 'valid', 50099, 1364520),
            ({'transformedOneByOneCount': 0}, 'valid', 0, 0),
            ({'verifiedGemItems': '泪滴'}, 'valid', 50000, None),
            ({'transformedOneByOneCount': 1.5}, 'invalid', None, None),
            ({'transformedOneByOneCount': 1, 'verifiedGemItems': '泪滴*2'}, 'invalid', None, None),
            (None, 'valid', 0, None),
        ):
            with self.subTest(evidence=evidence):
                match = CurrentMatch()
                match.apply_facts({'fieldCondition': 'sparkle', 'sparkle': evidence}, intent='confirm')
                # Exercise the canonical JSON boundary used by saved records.
                saved = json.loads(json.dumps(match.to_canonical()))
                restored = CurrentMatch()
                restored.apply_facts(saved, intent='snapshot')
                self.assertEqual(restored.snapshot()['sparkle'], evidence)
                for data in (saved, restored.to_canonical(), dict(restored.facts)):
                    py = canonical_to_v06_solver_input(data)
                    js = node("const fs=require('fs'),a=require('./core/v06_adapter.js');console.log(JSON.stringify(a.canonicalToV06SolverInput(JSON.parse(fs.readFileSync(0,'utf8')))));", data)
                    for adapted in (py, js):
                        ctx = _solver_ctx(adapted)
                        self.assertTrue(_facts_ready(ctx))
                        self.assertEqual(ctx['sparkle'], evidence)
                        result = json.loads(subprocess.check_output(
                            [str(ROOT/'runtime/node.exe'), 'core/live_shadow_runtime.js', '--once'],
                            cwd=ROOT, input=json.dumps({'ctx': ctx, 'records': []}),
                            text=True, encoding='utf-8'))
                        self.assertIn('frozenPrediction', result, (ctx, result))
                        frozen = result['frozenPrediction']
                        bounds = frozen['evidenceBounds']
                        self.assertEqual((bounds['status'], bounds['lower'], bounds['upper']), (status, lower, upper))
                        self.assertIsNone(frozen['estimate'])
                self.assertNotEqual(frozen['inputHash'], previous_hash)
                previous_hash = frozen['inputHash']

    def test_manual_clear_invalidates_cache_and_evidence_is_detached(self):
        evidence = {'transformedOneByOneCount': 2, 'verifiedGemItems': [{'name': '泪滴', 'count': 1}]}
        match = CurrentMatch()
        match.apply_facts({'sparkle': evidence}, intent='confirm')
        self.assertTrue(match.has_any_fact())
        evidence['verifiedGemItems'][0]['count'] = 9
        snapshot = match.snapshot()
        self.assertEqual(snapshot['sparkle']['verifiedGemItems'][0]['count'], 1)
        snapshot['sparkle']['verifiedGemItems'][0]['count'] = 8
        self.assertEqual(match.snapshot()['sparkle']['verifiedGemItems'][0]['count'], 1)
        original = {'sparkle': match.snapshot()['sparkle'], 'publicInfo': {'sparkle': match.snapshot()['sparkle']}}
        before = _profile_cache_key(original, 0)
        control = LiveMatchControl()
        control.match_id = match.id
        control.overrides = {'sparkle': None}
        frame = control.apply_to_frame(dict(original), match)
        self.assertIsNone(_solver_ctx(frame)['sparkle'])
        self.assertNotEqual(before, _profile_cache_key(frame, 0))
        self.assertIsNotNone(original['publicInfo']['sparkle'])
        match.apply_facts({}, cleared_fields=['sparkle'])
        self.assertIsNone(match.to_canonical()['sparkle'])
        self.assertFalse(match.has_any_fact())
        match.begin_next_match()
        self.assertIsNone(match.snapshot()['sparkle'])
        self.assertFalse(_facts_ready({'sparkle': evidence}))
