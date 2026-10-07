"""Session-control invariants, with an injected source and compositor facts; no OS/game IO."""
import copy
import ast
import hashlib
import json
import struct
import tempfile
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core')]
from native_warehouse_auto_capture import NativeWarehouseAutoCapture
from native_warehouse_intake import WarehouseCaptureRouter


class Source:
    def __init__(self):
        self.intake = self
        self._scope_lock = threading.RLock()
        self.actions, self.pages = [], []
        self.scope = {'recordStableKey': 'r', 'scene': 'SETTLEMENT', 'targetInstance': {'targetHwnd': 12}}
        self.state, self.reason, self.intake_state = 'IDLE', None, 'IDLE'
        self.deadline, self.proof = 105.0, None
    def source_contract(self):
        return {'scope': copy.deepcopy(self.scope), 'state': self.intake_state}
    def prepare_manual(self):
        return {'ok': self.intake_state != 'ALIGNING', 'recordStableKey': 'r'}
    def start_manual(self, key, *, allow_window_scroll=False):
        self.actions.append(('OPEN', allow_window_scroll))
        self.state, self.reason, self.intake_state = 'OPEN_PENDING', None, 'MANUAL_CAPTURING'
        if hasattr(self, '_trigger_watch'):
            self._trigger_watch = None
        return {'ok': True}
    def on_event(self, event):
        self.state, self.reason = event['state'], event['reason']
        if event.get('page'):
            self.pages.append(event['page'])
        self.proof = event.get('proof')
    def source_session_snapshot(self):
        return {'state': self.state, 'reason': self.reason, 'deadline': self.deadline,
                'limits': {'windowScrollSupported': True}, 'duplicateProof': self.proof,
                'savedSource': {'pixelSha256': 'hash'}}
    def pages_copy(self):
        return copy.deepcopy(self.pages)
    def capture_manual_page(self):
        self.actions.append(('REQUEST_PAGE', len(self.pages)))
        self.state = 'REQUEST_PENDING'
        return {'ok': True}
    def request_scroll_down(self):
        self.actions.append(('SCROLL_DOWN', len(self.pages)))
        self.state = 'SCROLL_PENDING'
        return {'ok': True}
    def close_source(self, reason):
        self.actions.append(('CLOSE', reason))
        self.state, self.reason = 'CLOSED', reason
    def finish_manual_capture(self, *, termination_reason):
        self.actions.append(('PROCESS', termination_reason))
        self.intake_state = 'ALIGNING'
        return {'ok': True}
    def cancel_manual_capture(self):
        self.actions.append(('CANCEL',))
        return {'ok': True}


class NativeAutoTests(unittest.TestCase):
    def test_saved_non_settlement_original_stops_before_any_wheel(self):
        from types import SimpleNamespace
        self.now, self.source = [100.0], Source()
        self.auto = NativeWarehouseAutoCapture(self.source, clock=lambda: self.now[0], timers=False)
        self.assertTrue(self.auto.confirm(self.auto.prepare()['armingToken'])['ok'])
        self.auto.on_event({'state': 'OPEN', 'reason': 'SOURCE_READY'})
        ok, encoded = cv2.imencode('.png', np.zeros((240, 320, 3), dtype=np.uint8))
        self.assertTrue(ok)
        raw = encoded.tobytes()
        self.source.evidence_store = SimpleNamespace(load_original=lambda desc: raw)
        page = {'descriptor': {'evidenceId': 'blank-non-settlement', 'sha256': hashlib.sha256(raw).hexdigest(),
                               'width': 320, 'height': 240}}
        self.auto.on_event({'state': 'OPEN', 'reason': 'PAGE_ACCEPTED', 'page': page})
        self.assertFalse(self.auto._active)
        self.assertEqual(self.auto._reason, 'PAGE_PROOF_REJECTED:FRESH_PAGE_NOT_SETTLEMENT')
        self.assertFalse(any(action[0] == 'SCROLL_DOWN' for action in self.source.actions))
        self.assertEqual(self.source.pages, [page], 'saved original must remain as partial evidence')

    def start(self):
        self.now, self.source = [100.0], Source()
        self.auto = NativeWarehouseAutoCapture(self.source, clock=lambda: self.now[0], timers=False)
        self.assertTrue(self.auto.confirm(self.auto.prepare()['armingToken'])['ok'])
        self.auto.on_event({'state': 'OPEN', 'reason': 'SOURCE_READY'})
        # Inject pixels/observer facts, not the session-control decisions under test.
        image = (np.arange(1200).reshape(20, 20, 3) % 255).astype(np.uint8)
        positions = {'TOP': 10, 'MIDDLE': 35, 'BOTTOM': 70}
        self.read = patch.object(self.auto, '_read_page', side_effect=lambda page: (image, {
            'scrollState': page['scrollState'], 'trackBox': [90, 0, 96, 100],
            'thumbBox': [90, positions.get(page['scrollState'], 10), 96,
                         positions.get(page['scrollState'], 10) + 20],
            'thumbPosition': positions.get(page['scrollState'], 10) / 100}))
        self.read.start(); self.addCleanup(self.read.stop)
    def page(self, state):
        self.auto.on_event({'state': 'OPEN', 'reason': 'PAGE_ACCEPTED', 'page': {'scrollState': state}})
    def stable_duplicate(self):
        self.now[0] += .3
        self.auto.poll()
        self.auto.on_event({'state': 'OPEN', 'reason': 'DUPLICATE_PAGE', 'proof': {'pixelSha256': 'hash'}})

    def test_save_and_stability_precede_each_wheel_and_bottom_only_finishes(self):
        self.start(); self.page('TOP')
        self.assertFalse(any(x[0] == 'SCROLL_DOWN' for x in self.source.actions))
        self.stable_duplicate()
        self.assertEqual(self.source.actions[-1], ('SCROLL_DOWN', 1))
        self.auto.on_event({'state': 'OPEN', 'reason': 'WINDOW_WHEEL_MESSAGE_SENT'})
        self.auto._advance()  # an ordinary status/UI refresh while the settle timer is pending
        self.assertTrue(self.auto._running)
        self.now[0] += .4; self.auto.poll()
        with patch('native_warehouse_auto_capture.align_warehouse_segments', return_value={
                'status': 'VERIFIED', 'direction': 'DOWN', 'verticalOffsetPx': -56}):
            self.page('BOTTOM')
        self.assertFalse(any(x[0] == 'PROCESS' for x in self.source.actions))
        self.stable_duplicate()
        self.assertEqual(self.source.actions[-1], ('PROCESS', 'COMPLETE'))
        self.assertEqual(sum(x[0] == 'SCROLL_DOWN' for x in self.source.actions), 1)
        self.assertFalse(self.auto._running)

    def test_ignored_wheel_stop_and_deadline_do_not_retry_or_extend(self):
        for failure in ('ignored-wheel', 'deadline', 'user-stop'):
            with self.subTest(failure=failure):
                self.start(); self.page('TOP'); self.stable_duplicate()
                self.auto.on_event({'state': 'OPEN', 'reason': 'WINDOW_WHEEL_MESSAGE_SENT'})
                generation = self.auto._generation
                if failure == 'deadline':
                    self.now[0] = 105.0; self.auto.poll()
                elif failure == 'user-stop':
                    self.auto.stop()
                else:
                    self.now[0] += .4; self.auto.poll()
                    self.auto.on_event({'state': 'OPEN', 'reason': 'DUPLICATE_PAGE', 'proof': {'pixelSha256': 'hash'}})
                actions = copy.deepcopy(self.source.actions)
                self.now[0] += 90; self.auto.poll(generation)
                self.assertEqual(self.source.actions, actions)
                self.assertEqual(self.source.actions[-1], ('PROCESS', 'INCOMPLETE'))
                self.assertEqual(sum(x[0] == 'SCROLL_DOWN' for x in actions), 1)

    def test_native_route_never_calls_legacy_and_changed_scope_rejects_confirmation(self):
        source = Source(); auto = NativeWarehouseAutoCapture(source, clock=lambda: 100, timers=False)
        class Legacy:
            def __getattr__(self, name):
                raise AssertionError('legacy access: ' + name)
        router = WarehouseCaptureRouter(Legacy(), auto, lambda: True)
        token = router.prepare()['armingToken']
        source.scope['targetInstance'] = {'targetHwnd': 99}
        self.assertFalse(router.confirm(token)['ok'])
        self.assertEqual(source.actions, [])
        router.stop()
        self.assertEqual(source.actions, [('CANCEL',)])
        from main_window import MainWindowBridge
        from types import SimpleNamespace
        changes = []
        bridge = MainWindowBridge(None, warehouse_capture_host=router, topmost_controller=changes.append)
        with patch.dict(sys.modules, {'main': SimpleNamespace()}):
            self.assertFalse(bridge.set_capture_safety_override(True))
        self.assertTrue(bridge.effective_topmost)
        self.assertNotIn(False, changes)

    def test_host_exception_and_mapping_loss_cancel_timers_and_preserve_saved_pages(self):
        for reason in ('capture-failed', 'client-area-mapping-changed', 'SOURCE_SCOPE_CHANGED'):
            with self.subTest(reason=reason):
                self.start(); self.page('TOP')
                generation = self.auto._generation
                saved = copy.deepcopy(self.source.pages)
                self.auto.on_event({'state': 'CLOSED', 'reason': reason})
                self.assertFalse(self.auto._running)
                self.assertEqual(self.auto._reason, reason)
                self.assertEqual(self.source.pages, saved)
                self.assertEqual(self.source.actions[-1], ('PROCESS', 'INCOMPLETE'))
                actions = copy.deepcopy(self.source.actions)
                self.now[0] += 90; self.auto.poll(generation)
                self.assertEqual(self.source.actions, actions)

    def test_image_motion_alone_unknown_and_reverse_thumb_stop_partial(self):
        for kind, reason in [('stationary', 'WINDOW_SCROLL_NO_PROGRESS'),
                             ('unknown', 'SCROLLBAR_PROGRESS_UNKNOWN'),
                             ('reversed', 'SCROLLBAR_REVERSED')]:
            with self.subTest(kind=kind):
                self.start(); self.page('TOP'); self.stable_duplicate()
                self.auto.on_event({'state': 'OPEN', 'reason': 'WINDOW_WHEEL_MESSAGE_SENT'})
                self.now[0] += .4; self.auto.poll()
                observation = copy.deepcopy(self.auto._observation)
                observation['scrollState'] = 'MIDDLE'
                if kind == 'unknown':
                    observation['thumbBox'] = None
                elif kind == 'reversed':
                    observation.update(thumbBox=[90, 5, 96, 25], thumbPosition=.05)
                with patch.object(self.auto, '_read_page', return_value=(np.ones((20, 20, 3)), observation)), \
                     patch('native_warehouse_auto_capture.align_warehouse_segments', return_value={
                         'status': 'VERIFIED', 'direction': 'DOWN', 'verticalOffsetPx': -56}):
                    self.page('MIDDLE')
                self.assertFalse(self.auto._running)
                self.assertEqual(self.auto._reason, reason)
                self.assertEqual(self.source.actions[-1], ('PROCESS', 'INCOMPLETE'))
                self.assertEqual(sum(x[0] == 'SCROLL_DOWN' for x in self.source.actions), 1)

    def test_thumb_motion_without_image_motion_stops_and_no_scroll_finishes_without_wheel(self):
        self.start(); self.page('TOP'); self.stable_duplicate()
        self.auto.on_event({'state': 'OPEN', 'reason': 'WINDOW_WHEEL_MESSAGE_SENT'})
        self.now[0] += .4; self.auto.poll()
        with patch('native_warehouse_auto_capture.align_warehouse_segments', return_value={
                'status': 'UNVERIFIED', 'direction': 'DOWN', 'verticalOffsetPx': 0}):
            self.page('MIDDLE')
        self.assertEqual(self.auto._reason, 'OVERLAP_OR_SCROLL_PROGRESS_UNVERIFIED')
        self.assertEqual(self.source.actions[-1], ('PROCESS', 'INCOMPLETE'))
        self.start(); self.page('NO_SCROLL'); self.stable_duplicate()
        self.assertEqual(self.source.actions[-1], ('PROCESS', 'COMPLETE'))
        self.assertFalse(any(a[0] == 'SCROLL_DOWN' for a in self.source.actions))

    def test_frozen_source_authority_does_not_refresh_business_frame_health(self):
        from tests.test_native_background_observation import _isolated_main, _confirmed_start, _frame
        ns, clock, _ = _isolated_main('background-readonly')
        _confirmed_start(ns)
        ns['_native_observation_event'](_frame(ns))
        ns['LATEST_PAYLOAD']['scene'] = 'SETTLEMENT'
        clock[0] += 40_000_000_000
        before = copy.deepcopy(ns['LATEST_PAYLOAD'])
        tree = ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8'))
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == '_native_warehouse_source_scope')
        deferred = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        module = ast.fix_missing_locations(ast.Module(body=[deferred, fn], type_ignores=[]))
        exec(compile(module, str(ROOT / 'app/main.py'), 'exec'), ns)
        from types import SimpleNamespace
        ns['_NATIVE_WAREHOUSE_SOURCE_COORDINATOR'] = SimpleNamespace(lease_scope_is_current=lambda scope: True)
        self.assertEqual(ns['_native_warehouse_intake_scope']()['scene'], 'UNKNOWN')
        self.assertEqual(ns['_native_warehouse_source_scope']()['scene'], 'SETTLEMENT')
        self.assertEqual(ns['LATEST_PAYLOAD'], before)
        ns['_NATIVE_WAREHOUSE_SOURCE_COORDINATOR'] = SimpleNamespace(lease_scope_is_current=lambda scope: False)
        self.assertEqual(ns['_native_warehouse_source_scope']()['scene'], 'UNKNOWN')


class NativeAutomaticTriggerTests(unittest.TestCase):
    def setUp(self):
        from tests.test_native_background_observation import _isolated_main, _confirmed_start
        from native_trial_drafts import NativeTrialDraftStore
        self.ns, self.clock, bridge = _isolated_main('background-readonly')
        self.root = Path(tempfile.mkdtemp(prefix='native-trigger-', dir=ROOT / 'build'))
        bridge.session_dir = self.root
        self.store = NativeTrialDraftStore(self.root / 'trial/canonical-history.json')
        self.ns.update(Path=Path, json=json, np=np, cv2=cv2,
            NATIVE_TRIAL_DRAFT_STORE=self.store, _NATIVE_AUTO_WAREHOUSE_ENABLED=True)
        self.source = Source()
        self.source.source_contract = lambda: {'scope': self.ns['_native_warehouse_source_scope'](),
                                               'state': self.source.intake_state}
        self.source.lease_scope_is_current = lambda scope: False
        self.source.check_business_boundary = lambda event: None
        self.auto = NativeWarehouseAutoCapture(self.source, timers=False,
            claim_attempt=self.ns['_native_claim_warehouse_attempt'])
        self.ns['_NATIVE_WAREHOUSE_SOURCE_COORDINATOR'] = self.auto
        _confirmed_start(self.ns)
        self.ns['_NATIVE_SOURCE_CAPTURE_CAPABILITY'] = True
        self.ns['_persist_current_draft_now'] = self.save_draft
        self.grid_patch = patch('warehouse_grid_geometry.observe_warehouse_grid',
                                return_value={'grid': {'status': 'OK'}})
        self.scroll_patch = patch('warehouse_scrollbar_observation.observe_warehouse_scrollbar',
                                  return_value={'scrollState': 'TOP'})
        self.grid = self.grid_patch.start(); self.scroll = self.scroll_patch.start()
        self.addCleanup(self.grid_patch.stop); self.addCleanup(self.scroll_patch.stop)

    def save_draft(self):
        from canonical_match_record import build_canonical_match_record_v7
        record = build_canonical_match_record_v7(match_id=self.ns['CURRENT_MATCH'].id,
            played_at='2026-10-04T00:00:00Z', lifecycle_status='DRAFT', source='manual', settlement={})
        record['dataOrigin'] = 'live-trial'
        return self.store.save_draft(record)

    def frame(self, sequence=1):
        from tests.test_native_background_observation import _frame
        event = _frame(self.ns, sequence=sequence)
        event['perception']['scene'] = event['pipelineContext']['scene'] = 'SETTLEMENT'
        event['perception']['inAuction'] = event['pipelineContext']['inAuction'] = False
        event['frame'].update(capturedAtNs=99_700_000_000 + sequence * 10_000_000,
            sourceTimestampNs=99_500_000_000 + sequence * 10_000_000, width=4, height=3,
            captureItemWidth=4, captureItemHeight=3, clientOffsetX=0, clientOffsetY=0)
        pixels = bytes(range(48))
        raw = struct.pack('<2sIHHI', b'BM', 102, 0, 0, 54)
        raw += struct.pack('<IiiHHIIiiII', 40, 4, -3, 1, 32, 0, 48, 0, 0, 0, 0) + pixels
        path = self.root / 'inert-pixels.bmp'; path.write_bytes(raw)
        event['frame']['rawFramePath'] = str(path)
        event['lastFrame'] = {'frameSequence': sequence, 'pixelSha256': hashlib.sha256(pixels).hexdigest()}
        return event

    def install_trigger_watch_adapter(self):
        self.watch_id = 'a' * 32
        self.watch = None
        self.acks, self.cancellations = [], []
        def arm(scope, *, deadline_ns, client_map):
            self.watch = {'watchId': self.watch_id, 'scope': copy.deepcopy(scope),
                'deadlineNs': deadline_ns, 'clientMap': client_map, 'armed': True,
                'lastOrdinal': 0, 'lastSequence': 0, 'pendingProbeId': None, 'pendingOrdinal': None}
            self.source._trigger_watch = self.watch
            return {'ok': True, 'watchId': self.watch_id, 'probeLimit': 32,
                'minimumIntervalNs': 600_000_000}
        self.source.arm_trigger_watch = Mock(side_effect=arm)
        self.source.trigger_watch_scope_is_current = lambda scope: bool(self.watch and scope == self.watch['scope'])
        def accept(event):
            details = event.get('details') or {}
            if (not self.watch or event.get('watchId') != self.watch_id
                    or self.watch['pendingProbeId'] is not None
                    or details.get('probeOrdinal') != self.watch['lastOrdinal'] + 1
                    or details.get('frameSequence', 0) <= self.watch['lastSequence']):
                return {'ok': False, 'reason': 'TRIGGER_PROBE_DUPLICATE_OR_OUT_OF_ORDER'}
            self.watch.update(pendingProbeId=details['probeId'], pendingOrdinal=details['probeOrdinal'],
                lastOrdinal=details['probeOrdinal'], lastSequence=details['frameSequence'])
            return {'ok': True}
        self.source.accept_trigger_probe = accept
        def file_for(event):
            d = event['details']
            path = (self.root / d['relativePath']).resolve()
            return {'path': path, 'sourceRoot': path.parent, 'scope': copy.deepcopy(self.watch['scope']),
                'frameSequence': d['frameSequence'], 'width': d['width'], 'height': d['height'],
                'bmpSha256': d['bmpSha256'], 'pixelSha256': d['pixelSha256']}
        self.source.trigger_probe_file = file_for
        def acknowledge(event, *, result, reason_codes=()):
            self.acks.append((event['details']['probeId'], result, list(reason_codes)))
            self.watch['pendingProbeId'] = self.watch['pendingOrdinal'] = None
            return True
        self.source.acknowledge_trigger_probe = acknowledge
        def cancel(reason, *, notify=True):
            self.cancellations.append(reason)
            self.watch = None
            self.source._trigger_watch = None
            return True
        self.source.cancel_trigger_watch = cancel

    def closed_frame(self, sequence=1):
        event = self.frame(sequence)
        event['frame']['settlementBusinessClosed'] = True
        event['frame']['settlementDeadlineNs'] = self.clock[0] + 70_000_000_000
        event['frame']['currentAdviceQualified'] = False
        event['frame']['currentAdviceQualification'] = {
            'qualified': False, 'failureReasons': ['ADVICE_UNQUALIFIED', 'UNRELATED_ADVICE_DETAIL']}
        return event

    def trigger_probe_event(self, sequence=2):
        from native_capture_delivery import STRICT
        self.assertIsNotNone(self.watch)
        watch = self.watch
        probe_id = 'b' * 32
        relative = f"warehouse-trigger-probes/{self.watch_id}/{probe_id}.bmp"
        original = (self.root / 'inert-pixels.bmp').read_bytes()
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original)
        readback = self.clock[0] - 100_000_000
        return {'type': 'native_warehouse_evidence', 'schemaVersion': 'native-warehouse-source.v1',
            'event': 'TRIGGER_PROBE', 'scene': 'UNCLASSIFIED_CURRENT_PROBE', 'watchId': self.watch_id,
            'capturePolicy': STRICT, 'observationSessionId': watch['scope']['observationSessionId'],
            'recordStableKey': watch['scope']['recordStableKey'], 'matchGeneration': watch['scope']['matchGeneration'],
            'targetInstance': copy.deepcopy(watch['scope']['targetInstance']), 'clientMap': watch['clientMap'],
            'deadlineNs': watch['deadlineNs'], 'sourceKind': 'native_wgc', 'inputActions': False,
            'formalHistoryWriter': False, 'details': {'probeId': probe_id, 'probeOrdinal': 1,
                'probeLimit': 32, 'remainingProbeAttempts': 31, 'relativePath': relative,
                'bmpSha256': hashlib.sha256(original).hexdigest(),
                'pixelSha256': hashlib.sha256(original[54:]).hexdigest(), 'frameSequence': sequence,
                'sourceTimestampNs': readback - 1_000_000, 'readbackTimestampNs': readback,
                'width': 4, 'height': 3, 'stride': 16, 'deadlineNs': watch['deadlineNs'],
                'sourcePagesWritten': 0, 'sourceRequestAttempts': 0}}

    def test_accepted_frame_triggers_once_restored_marker_blocks_and_new_match_can_start(self):
        self.ns['_native_source_observation_notice'](self.frame())
        self.assertEqual(self.source.actions, [('OPEN', True)])
        old_key = self.ns['CURRENT_MATCH'].id
        self.auto.stop()
        self.ns['_native_source_observation_notice'](self.frame(2))
        self.assertEqual(sum(a[0] == 'OPEN' for a in self.source.actions), 1)
        self.ns['_AUTO_CAPTURE_ATTEMPTED_KEYS'].clear()  # Simulate same-match process recovery.
        self.ns['_native_source_observation_notice'](self.frame(3))
        self.assertEqual(sum(a[0] == 'OPEN' for a in self.source.actions), 1)
        old_event = self.frame(4)
        next_event = self.frame(5)
        next_event['currentMatch']['id'] = 'next-worker-match'
        self.ns['_native_source_observation_notice'](next_event)
        self.assertEqual(sum(a[0] == 'OPEN' for a in self.source.actions), 2)
        self.assertNotEqual(self.ns['CURRENT_MATCH'].id, old_key)
        actions = copy.deepcopy(self.source.actions)
        self.ns['_native_source_observation_notice'](old_event)
        self.assertEqual(self.source.actions, actions)
        record = self.store.lookup(old_key)
        self.assertEqual(record['lifecycleStatus'], 'DRAFT')
        self.assertIsNone(record.get('settlement', {}).get('acquired'))
        self.assertNotIn('warehouseIdentityReview', record.get('settlement', {}))

    def test_postclose_probe_ignores_advice_and_starts_only_on_current_settlement_grid_top(self):
        self.install_trigger_watch_adapter()
        self.scroll.side_effect = [{'scrollState': 'MIDDLE'}, {'scrollState': 'TOP'}]
        close = self.closed_frame()
        self.ns['_native_source_observation_notice'](close)
        self.assertTrue(self.source.arm_trigger_watch.called)
        self.assertEqual(self.source.arm_trigger_watch.call_args.kwargs['deadline_ns'],
            close['frame']['settlementDeadlineNs'])
        self.assertFalse(self.store.warehouse_capture_attempted(self.ns['CURRENT_MATCH'].id))
        with patch('scene_anchors.settlement_title_visible', return_value=True):
            self.ns['_native_source_evidence_event'](self.trigger_probe_event())
        self.assertEqual(self.source.actions, [('OPEN', True)])
        self.assertTrue(self.store.warehouse_capture_attempted(self.ns['CURRENT_MATCH'].id))
        record = self.store.lookup(self.ns['CURRENT_MATCH'].id)
        self.assertEqual(record['lifecycleStatus'], 'DRAFT')
        self.assertIsNone(record.get('settlement', {}).get('acquired'))
        self.assertEqual(self.acks, [])  # Host OPEN retires the consumed probe.

    def test_postclose_probe_current_scene_grid_and_top_failures_are_logged_and_not_started(self):
        for rejection in ('scene', 'grid', 'top'):
            with self.subTest(rejection=rejection):
                self.setUp()
                self.install_trigger_watch_adapter()
                self.scroll.side_effect = [{'scrollState': 'MIDDLE'},
                    {'scrollState': 'MIDDLE' if rejection == 'top' else 'TOP'}]
                if rejection == 'grid':
                    self.grid.side_effect = [{'grid': {'status': 'OK'}}, {'grid': {'status': 'MISSING'}}]
                self.ns['_native_source_observation_notice'](self.closed_frame())
                event = self.trigger_probe_event()
                with patch('scene_anchors.settlement_title_visible', return_value=rejection != 'scene'):
                    self.ns['_native_source_evidence_event'](event)
                self.assertEqual(self.source.actions, [])
                if rejection == 'scene':
                    self.assertEqual(self.cancellations, ['TRIGGER_CURRENT_SCENE_NOT_SETTLEMENT'])
                    self.assertEqual(self.acks, [])
                else:
                    expected = 'WAREHOUSE_GRID_MISSING' if rejection == 'grid' else 'WAREHOUSE_NOT_TOP'
                    self.assertEqual(self.acks[0][2], [expected])
                    self.assertIn(expected, self.ns['_NATIVE_AUTO_TRIGGER_STATUS']['reasonCodes'])

    def test_postclose_probe_rechecks_file_hash_and_scope_after_read(self):
        for mutation in ('file', 'scope'):
            with self.subTest(mutation=mutation):
                self.setUp()
                self.install_trigger_watch_adapter()
                self.scroll.side_effect = [{'scrollState': 'MIDDLE'}, {'scrollState': 'TOP'}]
                self.ns['_native_source_observation_notice'](self.closed_frame())
                event = self.trigger_probe_event()
                path = self.root / event['details']['relativePath']

                def mutate_during_geometry(*_args, **_kwargs):
                    if mutation == 'file':
                        path.write_bytes(b'replaced after the initial read')
                    else:
                        self.ns['CURRENT_MATCH'].id = 'retired-during-probe-read'
                    return {'grid': {'status': 'OK'}}

                self.grid.side_effect = mutate_during_geometry
                with patch('scene_anchors.settlement_title_visible', return_value=True):
                    self.ns['_native_source_evidence_event'](event)
                self.assertEqual(self.source.actions, [])
                expected = ('TRIGGER_PROBE_REPLACED_DURING_READ' if mutation == 'file'
                            else 'TRIGGER_SCOPE_STALE')
                self.assertIn(expected, self.ns['_NATIVE_AUTO_TRIGGER_STATUS']['reasonCodes'])

    def test_postclose_delivery_watch_requires_the_existing_same_match_auction_anchor(self):
        self.ns['_native_observation_event'](self.frame())
        self.ns['_NATIVE_CAPTURE_POLICY'] = 'wgc-delivery-v1'
        self.ns['_NATIVE_DELIVERY_ANCHORED_MATCH'] = None
        self.install_trigger_watch_adapter()
        accepted = self.ns['LATEST_PAYLOAD']
        event = self.closed_frame()
        event['frame']['settlementDeadlineNs'] = self.clock[0] + 70_000_000_000
        self.ns['_arm_native_postclose_trigger_watch'](event, accepted, self.auto)
        self.assertFalse(self.source.arm_trigger_watch.called)
        self.assertIn('TRIGGER_SAME_MATCH_ANCHOR_MISSING',
            self.ns['_NATIVE_AUTO_TRIGGER_STATUS']['reasonCodes'])

    def test_unconfirmed_capability_disabled_option_and_non_top_do_not_open(self):
        for rejection in ('capability', 'disabled', 'not-top', 'future', 'old-session'):
            with self.subTest(rejection=rejection):
                self.setUp()
                event = self.frame()
                if rejection == 'capability': self.ns['_NATIVE_SOURCE_CAPTURE_CAPABILITY'] = False
                if rejection == 'disabled': self.ns['_NATIVE_AUTO_WAREHOUSE_ENABLED'] = False
                if rejection == 'not-top':
                    with patch('warehouse_scrollbar_observation.observe_warehouse_scrollbar', return_value={'scrollState': 'MIDDLE'}):
                        self.ns['_native_source_observation_notice'](event)
                        self.assertEqual(self.source.actions, [])
                    continue
                if rejection == 'future': event['frame']['sourceTimestampNs'] = self.clock[0] + 1
                if rejection == 'old-session': event['observationSessionId'] = 'retired-session'
                self.ns['_native_source_observation_notice'](event)
                self.assertEqual(self.source.actions, [])

    def test_disable_running_session_stops_and_persistent_claim_does_not_edit_draft(self):
        self.ns['_native_source_observation_notice'](self.frame())
        before = self.store.history_path.read_bytes()
        self.assertFalse(self.store.claim_warehouse_capture(self.ns['_native_warehouse_source_scope']()))
        self.assertEqual(self.store.history_path.read_bytes(), before)
        self.ns['BASE_DIR'] = str(self.root)
        self.assertFalse(self.ns['handle_native_auto_warehouse_capture'](True)['ok'])
        self.assertTrue(self.ns['handle_native_auto_warehouse_capture'](False)['ok'])
        self.assertFalse(self.auto._running)
        self.assertFalse(self.ns['_NATIVE_AUTO_WAREHOUSE_ENABLED'])
        actions = copy.deepcopy(self.source.actions)
        self.ns['_native_source_observation_notice'](self.frame(2))
        self.assertEqual(self.source.actions, actions)

    def test_failed_source_start_consumes_once_and_never_retries_next_frame(self):
        self.source.start_manual = lambda *args, **kwargs: {'ok': False, 'reason': 'HOST_UNAVAILABLE'}
        self.ns['_native_source_observation_notice'](self.frame())
        key = self.ns['CURRENT_MATCH'].id
        self.assertTrue(self.store.warehouse_capture_attempted(key))
        self.assertFalse(self.auto._running)
        self.ns['_native_source_observation_notice'](self.frame(2))
        self.assertEqual(self.source.actions, [])

    def test_attempt_persistence_failure_never_opens_source_or_retries_next_frame(self):
        with patch.object(self.store, 'claim_warehouse_capture', side_effect=OSError('disk unavailable')):
            self.ns['_native_source_observation_notice'](self.frame())
        # Even after storage recovers, this same match must not silently restart.
        self.ns['_native_source_observation_notice'](self.frame(2))
        self.assertEqual(self.source.actions, [])
        self.assertFalse(self.auto._running)

    def test_stale_same_session_timeout_cannot_revoke_trigger_capability(self):
        self.ns['_native_source_observation_notice'](self.frame())
        self.source.check_business_boundary = lambda event: (
            self.source.close_source('STALE_TIMEOUT') if event.get('status') == 'PAUSED' else None)
        actions = copy.deepcopy(self.source.actions)
        self.ns['_native_source_observation_notice']({'sourceKind': 'native_wgc',
            'inputActions': False, 'formalHistoryWriter': False, 'status': 'PAUSED',
            'observationSessionId': 'background-session', 'reason': 'observation-frame-timeout',
            'details': {'generation': 999, 'frameSequence': 999}})
        self.assertTrue(self.ns['_NATIVE_SOURCE_CAPTURE_CAPABILITY'])
        self.assertTrue(self.auto._running)
        self.assertEqual(self.source.actions, actions)
        self.ns['_native_source_observation_notice'](self.frame(2))
        self.assertEqual(self.source.actions, [('OPEN', True)])

    def test_host_exit_receipt_stops_active_collection_and_resume_does_not_retry_same_match(self):
        from tests.test_native_background_observation import _confirmed_start
        self.ns['_native_source_observation_notice'](self.frame())
        self.source.check_business_boundary = lambda event: (
            self.source.close_source(event['reason']) if event.get('status') == 'ERROR' else None)
        self.ns['_native_source_observation_notice']({'sourceKind': 'native_wgc',
            'inputActions': False, 'formalHistoryWriter': False,
            'status': 'ERROR', 'reason': 'host-exited:1'})
        self.assertFalse(self.auto._running)
        self.assertEqual(self.auto._reason, 'host-exited:1')
        self.assertFalse(self.ns['_NATIVE_SOURCE_CAPTURE_CAPABILITY'])
        _confirmed_start(self.ns)
        self.ns['_NATIVE_SOURCE_CAPTURE_CAPABILITY'] = True
        self.ns['_native_source_observation_notice'](self.frame(2))
        self.assertEqual(sum(action[0] == 'OPEN' for action in self.source.actions), 1)


if __name__ == '__main__':
    unittest.main()
