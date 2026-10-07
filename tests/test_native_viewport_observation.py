"""Directed Engine admission/stop behavior; no OCR, window or formal history."""
import copy
import importlib.util
from pathlib import Path
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'core'), str(ROOT / 'app'),
               str(ROOT / 'architecture/v2/host/engine_v22')]
from nte_engine_v22 import RealEngine, qpc_ns
from warehouse_viewport_scope import WarehouseViewportScope
from current_match import CurrentMatch


class NativeViewportObservationTests(unittest.TestCase):
    def test_same_view_is_retained_but_scrolled_local_rows_do_not_add_counts(self):
        rng = np.random.default_rng(7)
        original = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        scrolled = np.roll(original, -57, axis=0)
        bar = {'scrollState': 'TOP', 'thumbPosition': 0.0, 'thumbLength': .2,
               'trackBox': [1800, 200, 1806, 900], 'thumbBox': [1800, 200, 1806, 340]}
        moved = dict(bar, scrollState='MIDDLE', thumbPosition=.2, thumbBox=[1800, 340, 1806, 480])
        viewport = WarehouseViewportScope()
        self.assertIsNone(viewport.observe('match-a', original, scrollbar=bar))
        key = viewport.observe('match-a', original, scrollbar=bar)
        self.assertTrue(viewport.permits(key))
        slot = {'row': 0, 'col': 0, 'w': 1, 'h': 1, 'rarity': 'gold',
                'identityStatus': 'EXACT', 'identityReferenceKind': 'DIRECT',
                'identifiedName': 'known-item', 'candidates': []}
        facts = RealEngine._merge_warehouse_fact_slots(None, {'viewportScope': key, 'slots': [slot]})
        # Another frame/track of the SAME view must retain one instance.
        same = RealEngine._merge_warehouse_fact_slots(facts, {'viewportScope': key, 'slots': [dict(slot, trackId=99)]})
        self.assertEqual(len(same['slots']), 1)
        self.assertIsNone(viewport.observe('match-a', scrolled, scrollbar=moved))
        self.assertFalse(viewport.permits(key), 'late pre-scroll callback must be rejected')
        shifted_slot = dict(slot, row=2)
        self.assertEqual(RealEngine._merge_warehouse_fact_slots(same, {'slots': [shifted_slot]}), same)
        self.assertEqual(RealEngine._merge_warehouse_fact_slots(same, {'viewportScope': 'unrelated-view', 'slots': [shifted_slot]}), same)
        self.assertEqual(viewport.observe('match-a', original, scrollbar=bar), key)
        self.assertTrue(viewport.permits(key), 'returning to the same proved view remains valid')
        self.assertIsNone(viewport.observe('match-b', original, scrollbar=bar))
        self.assertFalse(viewport.permits(key), 'match boundary retires the viewport proof')

    def engine(self):
        engine = RealEngine.__new__(RealEngine)
        engine.stop_event = threading.Event()
        engine.session_id, engine.generation_id = 'session', 1
        engine._wall_minus_qpc_ns = 0
        engine.fault = ''
        engine._identity_generation_lock = threading.Lock()
        engine._identity_invalidation_generation = 0
        engine._identity_last_committed_sequence = {}
        engine.current_match = CurrentMatch()
        engine.current_match.apply_facts({'roundNo': 1}, source='vision', intent='observe')
        engine.pipeline = SimpleNamespace(_match_gen=1, _session_generation=1, catalog=[], current_context={})
        engine.last_context = {'scene': 'IN_AUCTION', 'round': 1}
        engine._warehouse_viewport_scope = WarehouseViewportScope()
        engine._warehouse_viewport_scope.key = 'anchor'
        engine._warehouse_viewport_scope.current_key = None
        engine.log = Mock()
        engine._persist_history = Mock()
        engine._persist_state = Mock()
        engine._activity_evidence_for_slot = Mock(return_value=None)
        return engine

    def test_actual_commit_withholds_unknown_view_without_changing_facts_or_history(self):
        engine = self.engine()
        result = {'kind': 'warehouse', 'sessionId': 'session', 'generationId': 1,
                  'matchId': engine.current_match.id, 'matchSequence': int(engine.current_match._seq),
                  'pipelineMatchGeneration': 1, 'pipelineSessionGeneration': 1,
                  'invalidationGeneration': 0, 'recognitionMode': 'auto', 'scene': 'IN_AUCTION',
                  'round': 1, 'frameSequence': 5, 'factsRevisionAtDispatch': engine.current_match.facts_revision,
                  'captureTimestampNs': 10, 'viewportScope': 'anchor',
                  'warehouseVision': {'slots': [{'row': 2, 'col': 0, 'identifiedName': 'same-item'}]}}
        before = copy.deepcopy(engine.current_match.facts)
        self.assertFalse(engine._commit_deferred_identity(result))
        self.assertEqual(engine.current_match.facts, before)
        self.assertEqual(engine.last_context['warehouseViewportObservation']['vision'], result['warehouseVision'])
        engine._persist_history.assert_not_called()
        engine._activity_evidence_for_slot.assert_not_called()
        # Same descriptor after a match/generation boundary must fail even if
        # its old viewport happens to be visually similar.
        engine._warehouse_viewport_scope.current_key = 'anchor'
        engine.current_match.id = 'next-match'
        self.assertFalse(engine._commit_deferred_identity(result))
        self.assertEqual(engine.current_match.facts, before)

    def test_slow_observe_cancel_or_invalidated_generation_cannot_commit_or_send(self):
        for boundary in ('stop', 'generation'):
            engine = self.engine()
            entered, release = threading.Event(), threading.Event()
            def observe(*args):
                entered.set()
                release.wait(2)
                return {'scene': 'IN_AUCTION'}, False
            engine._observe_frame_context = observe
            engine._apply_observation_context = Mock()
            engine.send = Mock()
            engine.processing_errors = []
            item = {'header': {'sequence': 7, 'captureTimestampNs': qpc_ns()},
                    'identityInvalidationGeneration': 0, 'bgr': np.zeros((4, 4, 3), dtype=np.uint8)}
            worker = threading.Thread(target=engine._process_frame, args=(item,))
            worker.start()
            self.assertTrue(entered.wait(1))
            if boundary == 'stop':
                engine.stop_event.set()
            else:
                engine._identity_invalidation_generation += 1
            release.set(); worker.join(1)
            self.assertFalse(worker.is_alive())
            engine._apply_observation_context.assert_not_called()
            engine._persist_history.assert_not_called()
            engine.send.assert_not_called()
            self.assertEqual(engine.processing_errors, [])


if __name__ == '__main__':
    unittest.main()
