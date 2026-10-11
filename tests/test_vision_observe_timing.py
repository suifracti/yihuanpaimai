"""Offline diagnostic attribution; synthetic delays never sleep or capture."""
import copy
from contextlib import ExitStack
import unittest
from unittest.mock import Mock, PropertyMock, patch

import numpy as np
from vision_pipeline import NTEVisionPipeline, SCENE_AUCTION_LOBBY, SCENE_AUCTION_LOADING
import test_native_viewport_observation as engine_contracts


class Clock:
    ns = 0

    def __call__(self):
        return self.ns

    def delayed(self, milliseconds, result=None):
        def action(*args, **kwargs):
            self.ns += int(milliseconds * 1_000_000)
            return result
        return action


class ObserveTimingTests(unittest.TestCase):
    def setUp(self):
        self.pipe = NTEVisionPipeline()
        self.frame = np.full((1080, 1920, 3), 100, dtype=np.uint8)

    def test_black_loading_early_return_and_disabled_clock(self):
        self.pipe.current_context.update(scene=SCENE_AUCTION_LOADING, loadingDirection='to_auction')
        clock = Clock()
        metrics = {'previousFrame': {}}
        with patch.object(self.pipe, '_handle_loading_black_frame', clock.delayed(7, True)), \
             patch('vision_pipeline.time.perf_counter_ns', clock):
            context = self.pipe.process_frame(self.frame, stage_timings=metrics)
        self.assertEqual(metrics, {'loadingTransition': {'calls': 1, 'elapsedMs': 7.0}})
        self.assertEqual(context['scene'], SCENE_AUCTION_LOADING)
        self.assertNotIn('stage_timings', context)
        with patch.object(self.pipe, '_handle_loading_black_frame', return_value=True), \
             patch('vision_pipeline.time.perf_counter_ns', side_effect=AssertionError('disabled timer')):
            self.assertEqual(self.pipe.process_frame(self.frame), context)

    def test_navigation_warmup_dispatch_does_not_change_facts(self):
        clock = Clock()
        with patch.object(self.pipe, '_handle_loading_black_frame', return_value=False), \
             patch.object(self.pipe, '_classify_scene_fast', clock.delayed(2, {'scene': SCENE_AUCTION_LOBBY})), \
             patch.object(self.pipe, '_warm_ocr_async', clock.delayed(3)), \
             patch.object(self.pipe, '_refresh_lobby_loadout', clock.delayed(5)), \
             patch('vision_pipeline.time.perf_counter_ns', clock):
            metrics = {}
            measured = copy.deepcopy(self.pipe.process_frame(self.frame, stage_timings=metrics))
            ordinary = copy.deepcopy(self.pipe.process_frame(self.frame))
        self.assertEqual(measured, ordinary)
        self.assertEqual(metrics['sceneNavigation']['elapsedMs'], 2)
        self.assertEqual(metrics['ocrWarmupDispatch']['elapsedMs'], 3)
        self.assertEqual(metrics['lobbyLoadout']['elapsedMs'], 5)
        self.assertNotIn('fullCanvasOcr', metrics)

    def canvas_setup(self, stack, clock, ocr):
        self.pipe._ocr_engine = object()  # No model initialization or worker.
        stack.enter_context(patch.object(self.pipe, '_handle_loading_black_frame', return_value=False))
        stack.enter_context(patch.object(self.pipe, '_classify_scene_fast', return_value={'scene': 'UNKNOWN'}))
        stack.enter_context(patch.object(self.pipe, '_read_df_auction_round_title', clock.delayed(10)))
        stack.enter_context(patch.object(type(self.pipe), 'ocr', new_callable=PropertyMock, return_value=ocr))
        stack.enter_context(patch('vision_pipeline.time.perf_counter_ns', clock))

    def test_full_canvas_delay_is_distinct_from_preflight_and_keeps_loading(self):
        clock = Clock()
        # The existing loading-caption parser determines the business result.
        rows = [([[850, 955], [1100, 955], [1100, 990], [850, 990]], '随机拍品抽选中..', .99)]
        with ExitStack() as stack:
            self.canvas_setup(stack, clock, clock.delayed(4200, (rows, None)))
            metrics = {}
            measured = copy.deepcopy(self.pipe.process_frame(self.frame, prioritize_live_facts=True,
                                                            stage_timings=metrics))
        self.assertEqual(measured['scene'], SCENE_AUCTION_LOADING)
        self.assertFalse(measured['inAuction'])
        self.assertEqual(metrics['roundTitlePreflight'], {'calls': 1, 'elapsedMs': 10.0})
        self.assertEqual(metrics['fullCanvasOcr'], {'calls': 1, 'elapsedMs': 4200.0})
        self.assertIn('loadingCaptionParsing', metrics)
        self.assertFalse(self.pipe._ocr_busy)

    def test_canvas_failure_keeps_timing_and_releases_existing_busy_flag(self):
        clock = Clock()
        def broken(*args):
            clock.ns += 2_000_000_000
            raise ValueError('offline OCR failure')
        with ExitStack() as stack:
            self.canvas_setup(stack, clock, broken)
            metrics = {}
            with self.assertRaisesRegex(ValueError, 'offline OCR failure'):
                self.pipe.process_frame(self.frame, stage_timings=metrics)
        self.assertEqual(metrics['fullCanvasOcr'], {'calls': 1, 'elapsedMs': 2000.0})
        self.assertFalse(self.pipe._ocr_busy)

    def test_focused_opening_fallback_has_independent_duration(self):
        self.pipe.current_context.update(scene=SCENE_AUCTION_LOADING, loadingDirection='to_auction')
        clock = Clock()
        remaining = iter([20, 300])
        def empty_ocr(*args):
            clock.ns += next(remaining) * 1_000_000
            return [], None
        with ExitStack() as stack:
            self.canvas_setup(stack, clock, empty_ocr)
            metrics = {}
            result = self.pipe.process_frame(self.frame, stage_timings=metrics)
        self.assertEqual(metrics['fullCanvasOcr'], {'calls': 1, 'elapsedMs': 20.0})
        self.assertEqual(metrics['fullCanvasFallbackOcr'], {'calls': 1, 'elapsedMs': 300.0})
        self.assertFalse(self.pipe._ocr_busy)
        self.assertFalse(result['inAuction'])

    def test_engine_emits_timings_on_existing_frame_trace_without_business_projection(self):
        engine = engine_contracts.NativeViewportObservationTests().engine()
        engine._settlement_collection_closed = False
        engine.capture_policy = 'strict-source-v1'
        engine.processing_errors = []
        engine.send = Mock()
        engine._append_frame_record = Mock()
        engine._apply_observation_context = lambda context, *args: context
        engine._perception_payload = lambda item, context, *args: {'scene': context['scene']}
        engine._submit_deferred_identity = Mock()
        def observe(frame, **kwargs):
            kwargs['stage_timings']['fullCanvasOcr'] = {'calls': 1, 'elapsedMs': 4200.0}
            return {'scene': SCENE_AUCTION_LOADING}
        engine.pipeline.process_frame = observe
        item = {'header': {'sequence': 23, 'captureTimestampNs': 1, 'cornerChecksum': 0},
                'identityInvalidationGeneration': 0, 'bgr': self.frame,
                'bufferIndex': 0, 'rawSha256': 'offline', 'ackSent': True}
        engine._process_frame(item)
        self.assertEqual(engine.processing_errors, [])
        events = [(args, kwargs) for args, kwargs in engine.log.call_args_list if args[0] == 'frame.processed']
        self.assertEqual(len(events), 1)
        trace = events[0][1]
        self.assertEqual(trace['frameSequence'], 23)
        self.assertEqual(trace['observeStagesMs']['fullCanvasOcr']['elapsedMs'], 4200.0)
        self.assertNotIn('observeStagesMs', engine.last_frame)
        self.assertNotIn('observeStagesMs', engine.send.call_args.args[1])
        engine.pipeline.process_frame = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError('offline'))
        engine._process_frame(item)
        self.assertEqual(engine.log.call_args.args[0], 'frame.processing_failed')
        self.assertEqual(engine.log.call_args.kwargs['frameSequence'], 23)
        self.assertEqual(engine.log.call_args.kwargs['observeStagesMs'], {})


if __name__ == '__main__':
    unittest.main()
