"""Bounded re-stability through the actual production collector; inert source IO."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import gc
import weakref
import struct
import tempfile
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/native-bounded-restability-production-20261007'
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core'), str(ROOT), str(OUT)]
from native_warehouse_auto_capture import NativeWarehouseAutoCapture
from native_warehouse_reveal_marker import RevealMarker
from tests.test_native_warehouse_content_stability import DeliverySource, visible_content
from tests.test_native_delivery_contract import proof

CASE_TRACES = []


class FakeSource(DeliverySource):
    def __init__(self):
        super().__init__()
        self.deadline = 170.0
        self.scope.update(recordStableKey='r1', matchGeneration=1, observationSessionId='fixture')
        self.fail_request = None
        self._ordinal = 0

    def source_session_snapshot(self):
        result = super().source_session_snapshot()
        result['requestAttempts'] = self._ordinal
        return result

    def capture_manual_page(self):
        if self.fail_request:
            self._ordinal += 1  # Failed explicit sends still spend a request.
            self.actions.append(('FAILED_REQUEST', self.fail_request))
            return {'ok': False, 'reason': self.fail_request}
        return super().capture_manual_page()

    def on_event(self, event):
        # Inert SOURCE authority refuses late packets after lease termination.
        # Real coordinator admission is checked by the additional integration case.
        if self.state == 'CLOSED' and event.get('reason') in ('PAGE_ACCEPTED', 'DUPLICATE_PAGE'):
            return
        super().on_event(event)


def silhouette():
    frame = visible_content()
    cv2.rectangle(frame, (300, 40), (355, 150), (210, 210, 210), 2)
    return frame


class RecheckTests(unittest.TestCase):
    def start(self):
        self.now, self.source, self.logs, self.images = [100.0], FakeSource(), [], {}
        self.auto = NativeWarehouseAutoCapture(self.source, clock=lambda: self.now[0], timers=False,
            diagnostic_log=lambda text: self.logs.append(json.loads(text)))
        self.assertTrue(self.auto.confirm(self.auto.prepare()['armingToken'])['ok'])
        self.auto.on_event({'state': 'OPEN', 'reason': 'SOURCE_READY'})
        def preserve_trace(source=self.source, auto=self.auto, logs=self.logs, clock=self.now):
            CASE_TRACES.append({'test': self.id(), 'actions': copy.deepcopy(source.actions),
                'requestAttempts': source._ordinal, 'savedOriginals': len(source.pages),
                'deadline': auto._deadline, 'clockAtEnd': clock[0], 'phase': auto._phase, 'reason': auto._reason,
                'diagnostics': copy.deepcopy(logs)})
        self.addCleanup(preserve_trace)
        def buffers_released(auto=self.auto):
            if auto._active:
                auto.stop()
            self.assertIsNone(auto._anchor)
            self.assertIsNone(auto._observation)
            self.assertIsNone(auto._timer)
        self.addCleanup(buffers_released)
        reader = patch.object(self.auto, '_read_page', side_effect=lambda p: (self.images[p['n']].copy(), {
            'scrollState': 'TOP', 'trackBox': [590, 0, 596, 240], 'thumbBox': [590, 10, 596, 80],
            'thumbPosition': .05, 'capturePolicy': p['capturePolicy'], 'deliveryProof': p['deliveryProof'],
            'revealMarker': {'status': p['marker'], 'captureId': p['deliveryProof']['captureId']}}))
        reader.start(); self.addCleanup(reader.stop)
        self.n = 0

    def tick_request(self, seconds=None):
        self.now[0] = max(self.now[0] + .001, self.auto._due + .05) if seconds is None else self.now[0] + seconds
        self.auto.poll()

    def frame(self, pixels, marker='NOT_DETECTED', duplicate=False, repeated_proof=None, late=False):
        if not late:
            self.assertEqual(self.source.state, 'REQUEST_PENDING', 'only an actual outstanding request may produce a frame')
        self.n += 1
        p = repeated_proof or proof(self.n, request=round(self.now[0] * 1e9), session='fixture')
        if duplicate:
            self.auto.on_event({'state': 'OPEN', 'reason': 'DUPLICATE_PAGE',
                'proof': {'pixelSha256': 'hash', 'deliveryProof': p}})
        else:
            self.images[self.n] = pixels.copy()
            self.auto.on_event({'state': 'OPEN', 'reason': 'PAGE_ACCEPTED', 'page': {
                'n': self.n, 'capturePolicy': 'wgc-delivery-v1', 'marker': marker, 'deliveryProof': p}})
        return p

    def wheels(self):
        return sum(a[0] == 'SCROLL_DOWN' for a in self.source.actions)

    def invariant_wait(self):
        self.assertTrue(self.auto._active)
        self.assertEqual(self.auto._phase, 'WAIT_STABLE')
        self.assertEqual(self.wheels(), 0)
        self.assertEqual(self.auto._deadline, 170.0)
        self.assertFalse(any(a[0] == 'PROCESS' for a in self.source.actions))
        self.assertFalse(any(r['kind'] == 'stable-page' for r in self.logs))

    def test_text_and_independent_pixels_do_not_prove_completion(self):
        self.start(); image = silhouette()
        self.frame(image, 'PRESENT')
        self.tick_request(); self.frame(image, 'PRESENT', duplicate=True)
        self.invariant_wait()  # paused reveal: identical pixels are insufficient
        self.tick_request(); changing = image.copy(); changing[45:49, 45:49] = (240, 120, 40)
        self.frame(changing, 'PRESENT'); self.invariant_wait()
        self.tick_request(); self.frame(visible_content(), 'NOT_DETECTED'); self.invariant_wait()
        requests_before = self.auto._request_attempts
        self.tick_request(); self.frame(visible_content(), 'NOT_DETECTED', duplicate=True)
        self.invariant_wait()
        self.assertEqual(self.auto._observation['contentCompletionState'], 'UNKNOWN')
        self.assertEqual(self.auto._deadline, 170.0)
        self.assertEqual(self.auto._request_attempts, requests_before + 1)
        self.assertEqual(self.auto._generation, 1, 'rechecks are the same task, not rearming')
        self.assertTrue(all(r['scrollAllowed'] is False and r['coverageQualified'] is False
            for r in self.logs if r['kind'] == 'stability-recheck'))

    def test_marker_disappearance_alone_does_not_grant_stability(self):
        self.start(); image = visible_content()
        self.frame(image, 'PRESENT')
        self.tick_request(); self.frame(image, 'NOT_DETECTED')
        self.invariant_wait()
        self.tick_request(); self.frame(image, duplicate=True)
        self.invariant_wait()
        self.assertEqual(self.auto._observation['contentCompletionState'], 'UNKNOWN')

    def test_perpetual_paused_reveal_stops_at_32_requests_no_counter_reset(self):
        self.start(); image = silhouette(); self.frame(image, 'PRESENT')
        while self.auto._active:
            self.tick_request(); self.frame(image, 'PRESENT', duplicate=True)
        self.assertEqual(self.auto._request_attempts, 32)
        self.assertEqual(sum(a[0] == 'REQUEST_PAGE' for a in self.source.actions), 32)
        self.assertEqual(len(self.source.pages), 1)
        self.assertEqual(self.auto._reason, 'SOURCE_REQUEST_LIMIT_REACHED')
        self.assertEqual(self.wheels(), 0)
        self.assertEqual(self.source.actions[-1], ('PROCESS', 'INCOMPLETE'))
        # Even valid visible support on the final request cannot authorize an extra wheel.
        self.start(); image = visible_content(); self.frame(image, 'PRESENT')
        for _ in range(29):
            self.tick_request(); self.frame(image, 'PRESENT', duplicate=True)
        self.tick_request(); self.frame(image, 'NOT_DETECTED')
        self.invariant_wait()
        self.tick_request(); self.frame(image, 'NOT_DETECTED', duplicate=True)
        self.assertEqual(self.auto._request_attempts, 32)
        self.assertEqual(self.auto._reason, 'SOURCE_REQUEST_LIMIT_REACHED')
        self.assertEqual(self.wheels(), 0)

    def test_changing_originals_stop_at_16_saved_sources(self):
        self.start(); self.frame(visible_content())
        for n in range(1, 16):
            self.tick_request(); image = visible_content(); image[45:49, 45:49] = (n + 100, 100, 30)
            self.frame(image)
        self.assertFalse(self.auto._active)
        self.assertEqual(len(self.source.pages), 16)
        self.assertEqual(self.auto._request_attempts, 16)
        self.assertEqual(self.auto._reason, 'SOURCE_LIMIT_REACHED')
        self.assertEqual(self.wheels(), 0)

    def test_70_second_deadline_and_elapsed_time_alone_never_grant_stability(self):
        self.start(); image = silhouette(); self.frame(image, 'PRESENT')
        self.tick_request(); self.frame(image, 'PRESENT', duplicate=True)
        original_generation = self.auto._generation
        self.now[0] = 169.0; self.auto.poll()
        attempts = self.auto._request_attempts
        self.now[0] = 170.0; self.auto.poll()
        self.assertEqual(self.auto._reason, 'ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
        self.assertEqual(self.auto._request_attempts, attempts)
        self.assertEqual(self.wheels(), 0)
        actions = copy.deepcopy(self.source.actions)
        self.auto.poll(original_generation)
        self.assertEqual(self.source.actions, actions)

    def test_cancel_or_authority_loss_terminates_pending_rechecks_and_late_events(self):
        for reason in ('USER_STOP', 'SOURCE_TARGET_CHANGED', 'SOURCE_GEOMETRY_CHANGED',
                'SOURCE_SCOPE_CHANGED', 'OBSERVATION_ENDED'):
            with self.subTest(reason=reason):
                self.start(); image = silhouette(); self.frame(image, 'PRESENT')
                self.tick_request(); self.frame(image, 'PRESENT', duplicate=True)
                generation = self.auto._generation
                if reason == 'USER_STOP':
                    self.auto.stop()
                else:
                    if reason == 'SOURCE_SCOPE_CHANGED':
                        self.source.scope.update(recordStableKey='r2', matchGeneration=2)
                    self.auto.on_event({'state': 'CLOSED', 'reason': reason})
                self.assertFalse(self.auto._active)
                self.assertEqual(self.auto._reason, reason)
                actions, saved = copy.deepcopy(self.source.actions), copy.deepcopy(self.source.pages)
                self.now[0] += 100; self.auto.poll(generation)
                self.frame(visible_content(), late=True)
                self.assertEqual(self.source.actions, actions)
                self.assertEqual(self.source.pages, saved)
                self.assertEqual(self.wheels(), 0)

    def test_errors_stop_but_static_unknown_content_stays_unknown(self):
        for reason in ('SOURCE_WRITE_FAILED', 'PAGE_PROOF_REJECTED:SOURCE_HASH_CHANGED', 'UNKNOWN_FAILURE'):
            with self.subTest(reason=reason):
                self.start(); self.frame(silhouette(), 'PRESENT')
                self.auto.on_event({'state': 'OPEN', 'reason': reason})
                self.assertEqual(self.auto._reason, reason)
                self.assertFalse(self.auto._active)
                self.assertEqual(self.wheels(), 0)
        self.start(); self.frame(silhouette()); self.tick_request(); self.frame(silhouette(), duplicate=True)
        self.invariant_wait()

    def test_replayed_support_and_failed_requests_never_retry_or_rearm(self):
        self.start(); image = silhouette(); self.frame(image, 'PRESENT')
        self.tick_request(); previous = self.frame(image, 'PRESENT', duplicate=True)
        self.tick_request(); self.frame(image, 'PRESENT', duplicate=True, repeated_proof=previous)
        self.assertEqual(self.auto._reason, 'INDEPENDENT_STABILITY_UNPROVEN')
        self.assertEqual(self.wheels(), 0)
        self.start(); self.frame(image, 'PRESENT')
        self.source.fail_request = 'NATIVE_SOURCE_HOST_UNAVAILABLE'
        self.tick_request()
        self.assertEqual(self.auto._request_attempts, 2, 'failed explicit request is charged')
        self.assertEqual(self.auto._reason, 'NATIVE_SOURCE_HOST_UNAVAILABLE')
        self.assertFalse(self.auto._active)

    def test_unproven_marker_counter_or_changed_scope_cannot_schedule_another_request(self):
        self.start(); self.frame(visible_content(), 'UNPROVEN')
        self.assertEqual(self.auto._reason, 'REVEAL_MARKER_READ_UNPROVEN')
        self.assertEqual(self.wheels(), 0)
        self.start(); self.frame(silhouette(), 'PRESENT')
        self.tick_request(); self.frame(silhouette(), 'PRESENT', duplicate=True)
        before = self.auto._request_attempts
        snapshot = self.source.source_session_snapshot(); snapshot['requestAttempts'] = 'unknown'
        with patch.object(self.source, 'source_session_snapshot', return_value=snapshot):
            self.tick_request()
        self.assertEqual(self.auto._reason, 'SOURCE_REQUEST_COUNTER_UNPROVEN')
        self.assertEqual(self.source._ordinal, before)
        self.start(); self.frame(silhouette(), 'PRESENT')
        self.tick_request(); self.frame(silhouette(), 'PRESENT', duplicate=True)
        before = self.auto._request_attempts
        self.source.scope['targetInstance'] = {'targetHwnd': 99}
        self.tick_request()
        self.assertEqual(self.auto._reason, 'SOURCE_SCOPE_CHANGED')
        self.assertEqual(self.source._ordinal, before)

    def test_duplicate_callback_is_consumed_once_pending_request_does_not_stack_and_stop_releases(self):
        self.start(); image = silhouette(); self.frame(image, 'PRESENT')
        self.auto._timers = True
        self.tick_request(); previous = self.frame(image, 'PRESENT', duplicate=True)
        timer = self.auto._timer
        due, deadline = self.auto._due, self.auto._deadline
        actions = copy.deepcopy(self.source.actions)
        evt = {'state': 'OPEN', 'reason': 'DUPLICATE_PAGE',
            'proof': {'pixelSha256': 'hash', 'deliveryProof': previous}}
        self.auto.on_event(evt); self.auto._advance()
        self.assertEqual(self.source.actions, actions)
        self.assertEqual((self.auto._due, self.auto._deadline), (due, deadline))
        self.tick_request(); actions = copy.deepcopy(self.source.actions)
        self.auto.poll(); self.auto.poll()
        self.assertEqual(self.source.actions, actions, 'a pending request cannot be stacked')
        anchor = weakref.ref(self.auto._anchor)
        generation = self.auto._generation
        self.auto.stop(); gc.collect()
        timer.join(timeout=1)
        self.assertFalse(timer.is_alive(), 'cancelled wait timer must actually exit')
        self.assertIsNone(anchor(), 'stop must release the retained image buffer')
        actions = copy.deepcopy(self.source.actions)
        self.auto.poll(generation); self.auto.on_event(evt)
        self.assertEqual(self.source.actions, actions)
        self.assertEqual(sum(a[0] == 'PROCESS' for a in actions), 1)

    def test_final_support_receipt_cannot_issue_two_scroll_requests(self):
        self.start(); image = visible_content(); self.frame(image)
        self.tick_request(); previous = self.frame(image, duplicate=True)
        self.invariant_wait()
        due = self.auto._due
        self.auto.on_event({'state': 'OPEN', 'reason': 'DUPLICATE_PAGE',
            'proof': {'pixelSha256': 'hash', 'deliveryProof': previous}})
        self.invariant_wait()
        self.assertEqual(self.auto._due, due)


class CoordinatorIntegrationTests(unittest.TestCase):
    def test_original_hash_bound_read_duplicate_callbacks_scope_change_and_resource_release(self):
        from native_trial_drafts import NativeTrialDraftStore
        from native_warehouse_intake import NativeWarehouseIntake
        from native_warehouse_source import NativeWarehouseSourceCoordinator, SCHEMA_V2
        from canonical_match_record import build_canonical_match_record_v7
        from warehouse_scrollbar_observation import warehouse_search_roi

        OUT.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(dir=OUT, prefix='source-integration-'))
        store = NativeTrialDraftStore(root / 'trial/history.json')
        scope = {'recordStableKey': 'match', 'observationSessionId': 'fixture',
            'targetInstance': {'targetHwnd': 12}, 'matchGeneration': 1,
            'scene': 'SETTLEMENT', 'capturePolicy': 'wgc-delivery-v1'}
        record = build_canonical_match_record_v7(match_id='match', played_at='2026-10-07T00:00:00Z',
            lifecycle_status='DRAFT', source='manual', settlement={})
        record['dataOrigin'] = 'live-trial'; store.save_draft(record)
        history = store.history_path.read_bytes()
        now, sent, logs = [100.0], [], []
        intake = NativeWarehouseIntake(draft_store=store, scope_provider=lambda: copy.deepcopy(scope),
            source_provider=lambda: None, clock=lambda: now[0])
        source = NativeWarehouseSourceCoordinator(intake, send_control=lambda c: sent.append(copy.deepcopy(c)) or True,
            source_root_provider=lambda: root, timers=False, clock=lambda: now[0], qpc=lambda: round(now[0] * 1e9))
        auto = NativeWarehouseAutoCapture(source, timers=False, clock=lambda: now[0],
            diagnostic_log=lambda text: logs.append(json.loads(text)))
        self.assertTrue(auto.confirm(auto.prepare()['armingToken'])['ok'])

        def event(kind, command=None, **extra):
            cmd = command or sent[-1]
            evt = {k: copy.deepcopy(cmd[k]) for k in ('commandId', 'nonce', 'requestOrdinal',
                'observationSessionId', 'reviewSessionId', 'reviewGeneration', 'recordStableKey', 'matchGeneration')}
            evt.update(type='native_warehouse_evidence', schemaVersion=SCHEMA_V2, capturePolicy='wgc-delivery-v1',
                sourceKind='native_wgc', inputActions=False, formalHistoryWriter=False,
                event=kind, targetInstance=copy.deepcopy(scope['targetInstance']), leaseToken='a' * 32)
            evt.update(extra); return evt

        auto.on_event(event('OPENED', details={'deadlineNs': 170_000_000_000,
            'clientWidth': 1920, 'clientHeight': 1080, 'remainingSourcePages': 16,
            'remainingRawBytes': 128 * 1024 * 1024, 'maxPngBytes': 64 * 1024 * 1024,
            'pngEncoding': 'opencv-bgr8-png-bound.v1', 'clientMap': 'map', 'windowScrollSupported': True}))
        frame = np.full((1080, 1920, 3), 20, np.uint8)
        x1, y1, x2, y2 = warehouse_search_roi(1920, 1080)
        frame[y1:y1+240, x1:x1+600] = silhouette()
        x1, y1, x2, y2 = RevealMarker.ROI
        frame[y1:y2, x1:x2] = cv2.imread(str(ROOT / 'tests/fixtures/native_reveal/independent_skip_animation_text.png'))
        pixels = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA).tobytes()
        raw = struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54)
        raw += struct.pack('<IiiHHIIiiII', 40, 1920, -1080, 1, 32, 0, len(pixels), 0, 0, 0, 0) + pixels
        path = root / 'warehouse-sources' / ('b'*32 + '.bmp'); path.parent.mkdir(); path.write_bytes(raw)
        p = proof(1, request=99_900_000_000, session='fixture')
        src = {'sourceLeaseId': 'b'*32, 'path': str(path), 'width': 1920, 'height': 1080, 'stride': 7680,
            'byteCount': len(raw), 'pixelSha256': hashlib.sha256(pixels).hexdigest(),
            'bmpSha256': hashlib.sha256(raw).hexdigest(), 'capturedAtUtc': '2026-10-07T00:00:00Z',
            'frameSequence': 1, 'sourceTimestampNs': p['sourceTimestampNs'], 'requestGateNs': p['requestNs'],
            'readbackTimestampNs': p['readbackCompletedNs'], 'clientMap': 'map', 'deliveryProof': p,
            'capturePolicy': 'wgc-delivery-v1', 'matchGeneration': 1, 'formalFactsQualified': False}
        with patch('scene_anchors.settlement_title_visible', return_value=True), \
                patch('native_warehouse_auto_capture.settlement_title_visible', return_value=True), \
                patch.object(auto._observer, 'observe', return_value={'scrollState': 'TOP',
                    'trackBox': [1884, 211, 1890, 771], 'thumbBox': [1884, 226, 1890, 445], 'thumbPosition': .0267}), \
                patch.object(intake, 'finish_manual_capture', return_value={'ok': True}):
            saved_event = event('SOURCE', source=src)
            auto.on_event(saved_event)
            self.assertEqual(len(source.pages_copy()), 1, (auto._reason, intake._reason, sent, logs))
            marker = auto._observation['revealMarker']
            self.assertEqual(marker['status'], 'PRESENT')
            self.assertEqual(marker['originalSha256'], source.pages_copy()[0]['descriptor']['sha256'])
            self.assertEqual(marker['captureId'], p['captureId'])
            self.assertIsNone(source._source, 'SOURCE pixels released after original save/ACK')
            before = copy.deepcopy(sent); auto.on_event(saved_event)
            self.assertEqual(sent, before, 'nonce admission rejects repeated original callback')
            now[0] = auto._due + .05; auto.poll()
            self.assertEqual(source.source_session_snapshot()['requestAttempts'], 2)
            p2 = proof(2, request=round((now[0] - .001) * 1e9), session='fixture')
            duplicate = event('RESULT', reason='DUPLICATE_PAGE', details={
                'pixelSha256': src['pixelSha256'], 'clientMap': 'map', 'frameSequence': 2,
                'requestGateNs': p2['requestNs'], 'sourceTimestampNs': p2['sourceTimestampNs'], 'deliveryProof': p2})
            auto.on_event(duplicate)
            self.assertEqual(auto._phase, 'WAIT_STABLE')
            before, due = copy.deepcopy(sent), auto._due
            auto.on_event(duplicate); auto._advance()
            self.assertEqual(sent, before); self.assertEqual(auto._due, due)
            anchor = weakref.ref(auto._anchor)
            generation = auto._generation
            now[0] = auto._due + .05; auto.poll()
            self.assertIsNotNone(source._pending)
            scope.update(recordStableKey='next', matchGeneration=2)
            auto.check_business_boundary({'status': 'FRAME', 'observationSessionId': 'fixture'})
            self.assertEqual(auto._reason, 'SOURCE_SCOPE_CHANGED')
            self.assertIsNone(source._pending); self.assertIsNone(source._source); self.assertIsNone(source._timer)
            self.assertIsNone(auto._timer); gc.collect(); self.assertIsNone(anchor())
            before = copy.deepcopy(sent)
            auto.on_event(duplicate); auto.on_event(saved_event); auto.poll(generation)
            self.assertEqual(sent, before)
            self.assertEqual(len(source.pages_copy()), 1)
            self.assertEqual(store.history_path.read_bytes(), history)
            self.assertFalse(any(c['operation'] == 'SCROLL_DOWN' for c in sent))
            view = auto.presentation_payload()
            self.assertEqual(view['automaticTerminationReason'], 'SOURCE_SCOPE_CHANGED')
            self.assertIn('已停止', view['message'])
        (root / 'trace.json').write_text(json.dumps({'sent': sent, 'diagnostics': logs,
            'newGameCapture': False, 'formalHistoryUnchanged': True}, indent=2), encoding='utf-8')


class MarkerTests(unittest.TestCase):
    def test_retained_positive_marker_negative_and_missing_asset(self):
        marker = RevealMarker(ROOT / 'assets/scene_anchors/skip_animation_text.png')
        raw = json.loads((ROOT / 'assets/scene_anchors/skip_animation_text.provenance.json').read_text(encoding='utf-8'))
        independent = ROOT / 'tests/fixtures/native_reveal/independent_skip_animation_text.png'
        self.assertEqual(hashlib.sha256(independent.read_bytes()).hexdigest(), raw['independentCropSha256'])
        image = np.full((1080, 1920, 3), 20, np.uint8)
        x1, y1, x2, y2 = RevealMarker.ROI
        image[y1:y2, x1:x2] = cv2.imread(str(independent))
        self.assertEqual(marker.observe(image)['status'], 'PRESENT')
        absent = image.copy(); x1, y1, x2, y2 = RevealMarker.ROI
        absent[y1:y2, x1:x2] = 20
        self.assertEqual(marker.observe(absent)['status'], 'NOT_DETECTED')
        with self.assertRaises(FileNotFoundError): RevealMarker(OUT / 'missing.png')
        with self.assertRaises(ValueError): marker.observe(np.zeros((300, 300, 3), np.uint8))
        with self.assertRaises(ValueError): marker.observe(np.zeros((9, 16, 3), np.uint8))


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    (OUT / 'test-results.json').write_text(json.dumps({'testMethods': result.testsRun,
        'passed': result.wasSuccessful(), 'failures': len(result.failures), 'errors': len(result.errors),
        'offlinePrototypeOnly': False, 'productionConnected': True, 'newGameCapture': False,
        'realScroll': False, 'normalWindowsExperiment': False, 'caseTraces': CASE_TRACES}, indent=2), encoding='utf-8')
    sys.exit(not result.wasSuccessful())
