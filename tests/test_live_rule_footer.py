"""Live fast-path rule wiring; optional replay uses run-u's actual saved pixels."""
import ast
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from current_match import CurrentMatch
from live_shadow import compute_live_probability_profile
from session_costs import costs_from_facts
from venue_box_catalog import load_catalog, solver_context_translation
from vision_pipeline import NTEVisionPipeline

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'tests/fixtures/match_u_solver_input.json').read_text(encoding='utf-8'))


def admission(facts):
    tree = ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in {'_native_solver_admission', '_native_solver_admission_details'}]
    ns = {'solver_context_translation': solver_context_translation, 'VENUE_BOX_CATALOG': load_catalog()}
    module = ast.Module(body=[ast.ImportFrom(module='__future__',
                       names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROOT / 'app/main.py'), 'exec'), ns)
    return ns['_native_solver_admission'](facts)


class LiveRuleFooterTests(unittest.TestCase):
    def test_fast_path_reads_rule_line_with_box_without_canvas(self):
        frame = np.full((1080, 1920, 3), 100, np.uint8)
        for text, expected in [('标准对局', 'standard'), ('天黑了', 'dark'), ('看不清', 'unknown')]:
            with self.subTest(text=text):
                pipe = NTEVisionPipeline()
                pipe.fast_live_intel = True
                pipe.current_context.update(scene='IN_AUCTION', inAuction=True, round=3)
                def recognize(crops):
                    return [(text, .99) if c.shape[:2] == (44, 154)
                            else ('皮制宝箱（高级藏品概率提升）', .99) if c.shape[:2] == (50, 538)
                            else ('', 0.) for c in crops], None
                ocr = Mock(return_value=([], None))
                ocr.text_rec.side_effect = recognize
                pipe._ocr_engine = ocr
                timings = {}
                with patch.object(pipe, '_classify_scene_fast', return_value={'scene': 'UNKNOWN'}), \
                     patch.object(pipe, '_read_df_auction_round_title', return_value=3):
                    result = pipe.process_frame(frame, prioritize_live_facts=True, captured_at='offline-frame',
                                                stage_timings=timings)
                self.assertEqual(result['fieldCondition'], expected)
                self.assertEqual(result['boxObservation']['text'], FIXTURE['rawBoxObservation'])
                # No full-canvas OCR was needed to obtain the rule.
                self.assertNotIn('fullCanvasOcr', timings)

    def test_run_u_box_mapping_is_present_rule_is_the_actual_missing_input(self):
        facts = FIXTURE['facts']
        mapped = solver_context_translation(load_catalog(), venue_id=facts['venueId'], box_id=facts['boxId'])
        self.assertEqual(mapped['box'], '皮制宝箱 · 高级藏品概率提升')
        self.assertEqual(admission(facts)[1], '缺失场地规则')
        self.assertIsNone(admission(dict(facts, fieldCondition='standard'))[1])

    @unittest.skipUnless(os.environ.get('NTE_REAL_AUCTION_REPLAY'), 'private saved image is opt-in')
    def test_run_u_actual_pixels_through_live_pipeline_main_and_real_solver(self):
        path = Path(os.environ['NTE_REAL_AUCTION_REPLAY'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), FIXTURE['imageSha256'])
        frame = cv2.imread(str(path))
        self.assertIsNotNone(frame)
        pipe = NTEVisionPipeline()
        pipe.fast_live_intel = True
        pipe._ensure_ocr()
        pipe.current_context.update(scene='IN_AUCTION', inAuction=True, round=3)
        context = pipe.process_frame(frame, prioritize_live_facts=True,
                                     captured_at='2026-10-20T13:59:08.497725+00:00')
        self.assertEqual(context['fieldCondition'], 'standard')
        self.assertEqual(context['boxObservation']['text'], FIXTURE['rawBoxObservation'])
        # Production engine projects this observed rule, not a box/default rule.
        from test_native_viewport_observation import NativeViewportObservationTests
        engine = NativeViewportObservationTests().engine()
        engine.current_match = CurrentMatch()
        engine.current_match.apply_facts(FIXTURE['facts'], source='vision', intent='observe')
        engine.venue_catalog = load_catalog()
        from venue_box_catalog import canonical_catalog_provenance
        engine.venue_catalog_provenance = canonical_catalog_provenance(engine.venue_catalog)
        engine._apply_pipeline_context(context, '2026-10-20T13:59:08.497725+00:00')
        facts = engine.current_match.facts
        mapped, reason = admission(facts)
        self.assertIsNone(reason)
        solver_ctx = dict(facts, matchId=FIXTURE['facts']['id'], round=3,
                          scene='IN_AUCTION', venue=mapped['venue'], box=mapped['box'],
                          costs=costs_from_facts(facts), targetProfit=0)
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory) / 'history.json'
            history.write_text('{"version":"v0.6","schemaVersion":6,"records":[]}', encoding='utf-8')
            _, meta = compute_live_probability_profile(solver_ctx, str(history), persist_runtime=False)
        self.assertIsNone(meta.get('error'), meta)
        snap = meta['predictionSnapshot']
        self.assertEqual(snap['status']['solverStatus'], 'valid')
        self.assertEqual(snap['input']['normalizedFacts']['box'], mapped['box'])
        self.assertGreater(snap['forecast']['structural']['feasibleRange'][0], 0)
        print('REAL run-u rule/box -> engine -> Main -> Solver PASS',
              snap['forecast']['structural']['feasibleRange'])


if __name__ == '__main__':
    unittest.main()
