"""Host source contract/bridge integration; fake compositor, saved real development pixels."""
import copy
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core'), str(ROOT / 'tests')]
import test_native_warehouse_intake as fixture_setup
from native_warehouse_source import (NativeWarehouseSourceCoordinator, SCHEMA,
    MAX_TRIGGER_PROBES, MIN_TRIGGER_PROBE_INTERVAL_NS)
from native_capture_delivery import STRICT
from native_observation import NativeObservationBridge


class NativeWarehouseSourceTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing fixture provenance/store setup without rerunning its six tests.
        base = fixture_setup.NativeWarehouseIntakeTests('test_scope_duplicate_and_limits_fail_closed')
        base.setUp()
        self.base = base
        self.root, self.intake, self.scope = base.root, base.intake, base.scope
        self.scope['targetInstance']['processInstanceToken'] = 789
        self.sent, self.events, self.child = [], [], None
        self.coordinator = NativeWarehouseSourceCoordinator(self.intake,
            send_control=lambda cmd: self.sent.append(copy.deepcopy(cmd)) or True,
            source_root_provider=lambda: self.root, timers=False)

    def tearDown(self):
        self.coordinator.cancel_manual_capture()
        if self.child:
            try:
                if self.child.poll() is None:
                    self.child.stdin.write('{"type":"native_stop"}\n'); self.child.stdin.flush()
                    self.child.wait(timeout=3)
            finally:
                if self.child.poll() is None:
                    self.child.terminate(); self.child.wait(timeout=3)
                for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
                    if stream:
                        try: stream.close()
                        except OSError: pass

    def opened(self):
        cmd = self.sent[-1]
        event = {k: copy.deepcopy(cmd[k]) for k in ('commandId', 'nonce', 'requestOrdinal',
            'observationSessionId', 'reviewSessionId', 'reviewGeneration', 'recordStableKey')}
        event.update(type='native_warehouse_evidence', schemaVersion=SCHEMA, event='OPENED',
            leaseToken='a' * 32, sourceKind='native_wgc', inputActions=False, formalHistoryWriter=False,
            targetInstance=copy.deepcopy(self.scope['targetInstance']), details={
                'deadlineNs': time.perf_counter_ns() + 69_000_000_000,
                'clientWidth': 1920, 'clientHeight': 1080, 'remainingSourcePages': 16,
                'remainingRawBytes': 128 * 1024 * 1024, 'maxPngBytes': 64 * 1024 * 1024,
                'pngEncoding': 'opencv-bgr8-png-bound.v1', 'clientMap': 'fixture:1920x1080'})
        self.coordinator.on_event(event)
        return event

    def test_trigger_probe_events_are_single_pending_ordered_and_scope_bound(self):
        qpc = [time.perf_counter_ns()]
        coordinator = NativeWarehouseSourceCoordinator(self.intake,
            send_control=lambda cmd: self.sent.append(copy.deepcopy(cmd)) or True,
            source_root_provider=lambda: self.root, clock=lambda: qpc[0] / 1_000_000_000,
            qpc=lambda: qpc[0], timers=False)
        scope = self.intake.source_contract()['scope']
        deadline = qpc[0] + 70_000_000_000
        armed = coordinator.arm_trigger_watch(scope, deadline_ns=deadline, client_map='1920x1080:0,0:1920x1080')
        self.assertTrue(armed['ok'])
        self.assertEqual(armed['probeLimit'], MAX_TRIGGER_PROBES)
        self.assertEqual(armed['minimumIntervalNs'], MIN_TRIGGER_PROBE_INTERVAL_NS)
        command = self.sent[-1]
        coordinator.on_event({
            'type': 'native_warehouse_evidence', 'schemaVersion': SCHEMA,
            'event': 'TRIGGER_WATCH_ARMED', 'watchId': armed['watchId'],
            'observationSessionId': scope['observationSessionId'], 'recordStableKey': scope['recordStableKey'],
            'matchGeneration': scope['matchGeneration'], 'targetInstance': scope['targetInstance'],
            'clientMap': command['clientMap'], 'deadlineNs': deadline,
            'sourceKind': 'native_wgc', 'inputActions': False, 'formalHistoryWriter': False,
        })
        def probe(ordinal, sequence, suffix):
            return {'type': 'native_warehouse_evidence', 'schemaVersion': SCHEMA,
                'event': 'TRIGGER_PROBE', 'scene': 'UNCLASSIFIED_CURRENT_PROBE',
                'watchId': armed['watchId'], 'capturePolicy': STRICT,
                'observationSessionId': scope['observationSessionId'],
                'recordStableKey': scope['recordStableKey'], 'matchGeneration': scope['matchGeneration'],
                'targetInstance': copy.deepcopy(scope['targetInstance']), 'clientMap': command['clientMap'],
                'deadlineNs': deadline, 'sourceKind': 'native_wgc', 'inputActions': False,
                'formalHistoryWriter': False, 'details': {'probeId': suffix * 32,
                    'probeOrdinal': ordinal, 'frameSequence': sequence}}
        first = probe(1, 10, 'a')
        self.assertTrue(coordinator.accept_trigger_probe(first)['ok'])
        duplicate = coordinator.accept_trigger_probe(copy.deepcopy(first))
        self.assertEqual(duplicate['reason'], 'TRIGGER_PROBE_DUPLICATE_OR_OUT_OF_ORDER')
        self.assertEqual(coordinator._trigger_watch['pendingProbeId'], 'a' * 32)
        reordered = coordinator.accept_trigger_probe(probe(2, 11, 'b'))
        self.assertEqual(reordered['reason'], 'TRIGGER_PROBE_DUPLICATE_OR_OUT_OF_ORDER')
        self.assertEqual(coordinator._trigger_watch['pendingProbeId'], 'a' * 32)
        self.assertTrue(coordinator.acknowledge_trigger_probe(first, result='REJECTED',
            reason_codes=['WAREHOUSE_NOT_TOP']))
        self.assertEqual(self.sent[-1]['operation'], 'ACK_TRIGGER_PROBE')
        self.assertEqual(self.sent[-1]['probeId'], 'a' * 32)
        self.assertIsNone(coordinator._trigger_watch['pendingProbeId'])
        second = probe(2, 11, 'b')
        self.assertTrue(coordinator.accept_trigger_probe(second)['ok'])
        self.assertTrue(coordinator.acknowledge_trigger_probe(second, result='REJECTED',
            reason_codes=['WAREHOUSE_GRID_MISSING']))
        skipped = coordinator.accept_trigger_probe(probe(4, 13, 'd'))
        self.assertEqual(skipped['reason'], 'TRIGGER_PROBE_DUPLICATE_OR_OUT_OF_ORDER')
        coordinator.observation_ended('STOPPED')
        self.assertIsNone(coordinator._trigger_watch)
        self.assertFalse(coordinator.accept_trigger_probe(probe(3, 12, 'c'))['ok'],
            'late callback from a stopped settlement cannot restart the watch')

    def test_trigger_probe_deadline_and_match_change_revoke_pending_frame(self):
        qpc = [time.perf_counter_ns()]
        coordinator = NativeWarehouseSourceCoordinator(self.intake,
            send_control=lambda cmd: self.sent.append(copy.deepcopy(cmd)) or True,
            source_root_provider=lambda: self.root, clock=lambda: qpc[0] / 1_000_000_000,
            qpc=lambda: qpc[0], timers=False)
        scope = self.intake.source_contract()['scope']
        deadline = qpc[0] + 70_000_000_000
        armed = coordinator.arm_trigger_watch(scope, deadline_ns=deadline, client_map='map')
        self.assertTrue(armed['ok'])
        self.scope['recordStableKey'] = 'next-match'
        coordinator.check_business_boundary({'status': 'FRAME', 'observationSessionId': scope['observationSessionId']})
        self.assertIsNone(coordinator._trigger_watch)
        self.assertEqual(self.sent[-1]['operation'], 'CANCEL_TRIGGER_WATCH')
        self.assertEqual(self.sent[-1]['reason'], 'TRIGGER_SCOPE_CHANGED')

        # A separately armed fixed deadline expires even if the caller's local clock moves on.
        self.scope['recordStableKey'] = scope['recordStableKey']
        self.intake._scope_provider = lambda: {**copy.deepcopy(self.scope), 'scene': 'SETTLEMENT'}
        coordinator = NativeWarehouseSourceCoordinator(self.intake,
            send_control=lambda cmd: self.sent.append(copy.deepcopy(cmd)) or True,
            source_root_provider=lambda: self.root, clock=lambda: qpc[0] / 1_000_000_000,
            qpc=lambda: qpc[0], timers=False)
        deadline = qpc[0] + 70_000_000_000
        armed = coordinator.arm_trigger_watch(self.intake.source_contract()['scope'], deadline_ns=deadline, client_map='map')
        self.assertTrue(armed['ok'])
        qpc[0] = deadline + 1
        coordinator.check_timeout()
        self.assertIsNone(coordinator._trigger_watch)
        self.assertEqual(coordinator.presentation_payload()['sourceReason'], 'ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')

    def test_scope_timeout_late_open_and_budget_are_upstream(self):
        self.assertTrue(self.coordinator.start_manual()['ok'])
        late = self.opened()
        with patch('native_warehouse_intake.MAX_ENCODED_BYTES', 1):
            with patch.object(self.intake.draft_store, 'capture_frame', side_effect=AssertionError('must not save')):
                result = self.coordinator.capture_manual_page()
        self.assertEqual(result['reason'], 'PNG_BUDGET_INSUFFICIENT')
        self.assertFalse(any(s['operation'] == 'REQUEST_PAGE' for s in self.sent))
        self.coordinator.cancel_manual_capture()
        self.assertTrue(self.coordinator.start_manual()['ok'])
        self.coordinator.on_event(late)
        self.assertEqual(self.sent[-1]['operation'], 'CLOSE')
        self.assertEqual(self.sent[-1]['reviewSessionId'], late['reviewSessionId'])
        self.assertEqual(self.coordinator.presentation_payload()['sourceState'], 'OPEN_PENDING')
        self.coordinator._pending_until = time.monotonic() - 1
        self.coordinator.check_timeout()
        self.assertEqual(self.coordinator.presentation_payload()['sourceReason'], 'SOURCE_PUBLISH_UNSUPPORTED_OR_TIMEOUT')
        self.assertEqual(self.intake.pages_copy(), [])

    def fixture(self, seconds, sequence):
        frame = self.base.frame(seconds, sequence)
        # Isolated top-left client-shaped crop, not a claimed full Native capture or 1440p support.
        crop = frame[:1080, :1920]
        self.assertEqual(crop.shape[:2], (1080, 1920))
        pixels = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA).tobytes()
        header = struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54)
        header += struct.pack('<IiiHHIIiiII', 40, 1920, -1080, 1, 32, 0, len(pixels), 0, 0, 0, 0)
        path = self.root / f'protocol-fixture-{sequence}.bmp'
        path.write_bytes(header + pixels)
        return path

    def test_sessionless_host_exit_ends_current_source_scope(self):
        self.assertTrue(self.coordinator.start_manual()['ok'])
        self.opened()
        self.scope['scene'] = 'UNKNOWN'  # Same post-error authority as Main's existing health gate.
        self.coordinator.check_business_boundary({'status': 'ERROR', 'reason': 'host-exited:1'})
        self.assertEqual(self.coordinator.presentation_payload()['sourceState'], 'CLOSED')
        self.assertEqual(self.intake.presentation_payload()['state'], 'CANCELLED')
        self.assertEqual(self.intake.pages_copy(), [])

    def test_scope_loss_keeps_saved_original_and_partial_manifest_without_billing(self):
        self.assertTrue(self.coordinator.start_manual()['ok'])
        self.opened()
        pixels = bytes(range(48))
        raw = struct.pack('<2sIHHI', b'BM', 102, 0, 0, 54)
        raw += struct.pack('<IiiHHIIiiII', 40, 4, -3, 1, 32, 0, 48, 0, 0, 0, 0) + pixels
        path = self.root / 'inert-cancel.bmp'; path.write_bytes(raw)
        # Exercise the real intake/store with inert pixels; no SOURCE publication or WGC is claimed.
        self.intake._source_provider = lambda: {'path': str(path), 'sourceRoot': str(self.root),
            'width': 4, 'height': 3, 'frameSequence': 1, 'capturedAt': '2026-10-04T00:00:00Z',
            'pixelSha256': hashlib.sha256(pixels).hexdigest(), 'receivedAt': time.monotonic(),
            'scope': copy.deepcopy(self.scope)}
        self.intake._source_validator = None
        self.assertTrue(self.intake.capture_manual_page()['ok'])
        pages = self.intake.pages_copy()
        manifest = self.base.store.root / 'warehouse-intake' / (self.intake._session_id + '.json')
        self.scope['recordStableKey'] = 'next-match'
        self.coordinator.check_business_boundary({'status': 'FRAME',
            'observationSessionId': self.scope['observationSessionId']})
        self.intake.wait_processing(15)
        self.assertEqual(self.coordinator.source_session_snapshot()['state'], 'CLOSED')
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        self.assertEqual(saved['scope']['recordStableKey'], 'native_intake_development')
        self.assertEqual(saved['terminationReason'], 'INCOMPLETE')
        self.assertEqual(saved['state'], 'PARTIAL')
        self.assertEqual(self.intake.pages_copy(), pages)
        evidence = self.base.store.read_source_image_descriptor(pages[0]['nativeSource'])
        self.assertEqual(evidence['data'], raw)
        record = self.base.store.lookup('native_intake_development')
        self.assertEqual(record['lifecycleStatus'], 'DRAFT')
        self.assertEqual(record['settlement']['warehouseReviewPacket']['recordStableKey'], 'native_intake_development')
        self.assertIsNone(self.base.store.lookup('next-match'))
        self.assertFalse(self.intake.capture_manual_page()['ok'])

    def test_window_scroll_result_is_correlated_and_cannot_impersonate_a_source(self):
        self.assertTrue(self.coordinator.start_manual(allow_window_scroll=True)['ok'])
        self.assertTrue(self.sent[-1]['allowWindowScroll'])
        event = self.opened()
        self.coordinator._host_limits['windowScrollSupported'] = True
        self.assertFalse(self.coordinator.request_scroll_down()['ok'])  # no saved-source grant yet
        self.coordinator._saved_source = {'sourceLeaseId': 'b' * 32, 'pixelSha256': 'c' * 64,
                                          'frameSequence': 1}
        for delta in (0,120,-121,-1560,True):
            self.assertFalse(self.coordinator.request_scroll_down(wheel_delta=delta)['ok'])
        self.assertTrue(self.coordinator.request_scroll_down(wheel_delta=-1080)['ok'])
        cmd = self.sent[-1]
        event.update({key: copy.deepcopy(cmd[key]) for key in ('commandId', 'nonce', 'requestOrdinal')})
        event.update(event='SCROLLED', reason='WINDOW_WHEEL_MESSAGE_SENT', inputActions=True,
                     details={'direction': 'DOWN', 'delta': -1080, 'sourceLeaseId': 'b' * 32})
        wrong = copy.deepcopy(event); wrong['nonce'] = 'stale'
        self.coordinator.on_event(wrong)
        self.assertEqual(self.coordinator.source_session_snapshot()['state'], 'SCROLL_PENDING')
        wrong = copy.deepcopy(event); wrong['event'] = 'SOURCE'
        self.coordinator.on_event(wrong)
        self.assertEqual(self.intake.pages_copy(), [])
        self.coordinator.on_event(event)
        self.assertEqual(self.coordinator.source_session_snapshot()['reason'], 'WINDOW_WHEEL_MESSAGE_SENT')
        self.assertEqual(self.coordinator.source_session_snapshot()['state'], 'OPEN')
        self.assertEqual(self.intake.pages_copy(), [])

        self.assertTrue(self.coordinator.request_scroll_down(wheel_delta=-720)['ok'])
        bad = copy.deepcopy(event)
        bad.update({key:copy.deepcopy(self.sent[-1][key]) for key in ('commandId','nonce','requestOrdinal')})
        bad['details']['delta'] = -120
        self.coordinator.on_event(bad)
        self.assertEqual(self.coordinator.source_session_snapshot()['reason'], 'WINDOW_SCROLL_PROOF_REJECTED')

    def wait_for(self, condition, seconds=8):
        end = time.monotonic() + seconds
        while not condition() and time.monotonic() < end:
            if self.child and self.child.poll() is not None:
                self.fail(self.child.stderr.read())
            time.sleep(.02)
        self.assertTrue(condition(), self.coordinator.presentation_payload())

    def test_compiled_host_to_reader_to_real_store_and_failure_ack(self):
        paths = [self.fixture(163, 1), self.fixture(164, 2)]
        dll = ROOT / 'build/native-source-contracts/out/evidence-contracts.dll'
        if not dll.is_file():
            subprocess.run(['dotnet', 'build', str(ROOT / 'tests/native_source_contracts/evidence-contracts.csproj'),
                '-c', 'Release'], check=True, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertTrue(dll.is_file(), 'build only the isolated contract harness first')
        source_frames_before = self.intake.draft_store.lookup(self.scope['recordStableKey'])['auctionEvidence']['nativeObservation']['sourceFrames']
        from main_window import MainWindowBridge, OverlayVisibilityController
        from native_warehouse_intake import WarehouseCaptureRouter
        from warehouse_capture_host import WarehouseCaptureHost
        class Overlay:
            Visible = True
            def Show(self): self.Visible = True
            def Hide(self): self.Visible = False
        legacy = WarehouseCaptureHost(input_execution_allowed=lambda: False)
        router = WarehouseCaptureRouter(legacy, self.coordinator, lambda: True)
        ui = MainWindowBridge(OverlayVisibilityController(Overlay()), warehouse_capture_host=router)
        ordinary = []
        self.child = subprocess.Popen(['dotnet', str(dll), str(self.root), '--protocol-fixture', *map(str, paths)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        bridge = NativeObservationBridge(str(ROOT), ordinary.append, lambda *_: None,
            on_evidence=lambda event: self.events.append(copy.deepcopy(event)) or self.coordinator.on_event(event))
        bridge.process, bridge.session_dir, bridge.last_status = self.child, self.root, 'READY'
        self.coordinator._send_control = lambda cmd: self.sent.append(copy.deepcopy(cmd)) or bridge.send_control(cmd)
        reader = threading.Thread(target=bridge._read_stdout, args=(self.child,), daemon=True)
        reader.start()
        self.assertTrue(ui.dispatch({'action': 'start_warehouse_manual_takeover'})['warehouseCaptureCommand']['ok'])
        self.wait_for(lambda: self.coordinator.presentation_payload()['sourceState'] == 'OPEN')
        with patch.object(legacy, 'capture_manual_page', side_effect=AssertionError('legacy capture forbidden')):
            requested = ui.dispatch({'action': 'capture_warehouse_manual_page', 'path': 'untrusted', 'descriptor': {}})
        self.assertTrue(requested['warehouseCaptureCommand']['ok'])
        self.wait_for(lambda: len(self.intake.pages_copy()) == 1 and any(c.get('result') == 'SAVED' for c in self.sent))
        first = self.intake.pages_copy()[0]
        self.assertTrue(self.intake.evidence_store.verify(first['descriptor'])['ok'])
        manifest = next((self.intake.draft_store.root / 'warehouse-intake').glob('*.json'))
        self.assertEqual(json.loads(manifest.read_text(encoding='utf-8'))['pages'], [first])
        self.assertEqual(self.sent[-1]['result'], 'SAVED')
        saved_source = next(e['source'] for e in self.events if e.get('event') == 'SOURCE')
        self.assertEqual(hashlib.sha256(Path(saved_source['path']).read_bytes()).hexdigest(), saved_source['bmpSha256'])
        self.assertGreater(saved_source['sourceTimestampNs'], saved_source['requestGateNs'])
        real_replace = os.replace
        def fail_manifest(src, dst):
            if Path(dst).parent.name == 'warehouse-intake':
                raise OSError('actual manifest failure')
            return real_replace(src, dst)
        with patch('native_warehouse_intake.os.replace', side_effect=fail_manifest):
            self.assertTrue(self.coordinator.capture_manual_page()['ok'])
            self.wait_for(lambda: any(c.get('result') == 'REJECTED' for c in self.sent))
        self.assertEqual(len(self.intake.pages_copy()), 1)
        self.assertEqual(self.coordinator.presentation_payload()['sourceReason'], 'STORE_FAILED')
        original_save = self.intake.evidence_store.save_original
        original_qpc = self.coordinator._qpc
        def expire_after_real_store(**kwargs):
            descriptor = original_save(**kwargs)
            self.coordinator._qpc = lambda: original_qpc() + 3_000_000_000
            return descriptor
        rejected_before = sum(c.get('result') == 'REJECTED' for c in self.sent)
        try:
            with patch.object(self.intake.evidence_store, 'save_original', side_effect=expire_after_real_store):
                self.assertTrue(ui.dispatch({'action': 'capture_warehouse_manual_page'})['warehouseCaptureCommand']['ok'])
                self.wait_for(lambda: sum(c.get('result') == 'REJECTED' for c in self.sent) > rejected_before)
        finally:
            self.coordinator._qpc = original_qpc
        self.assertEqual(len(self.intake.pages_copy()), 1)
        self.assertEqual(self.coordinator.presentation_payload()['sourceReason'], 'SOURCE_LEASE_EXPIRED')
        self.assertEqual(ui.dispatch({'action': 'request_app_status'})['warehouseCapture']['segmentCount'], 1)
        self.assertEqual(source_frames_before,
            self.intake.draft_store.lookup(self.scope['recordStableKey'])['auctionEvidence']['nativeObservation']['sourceFrames'])
        self.assertEqual(ordinary, [])
        self.assertEqual(bridge.last_status, 'READY')
        self.assertEqual(self.intake.draft_store.lookup(self.scope['recordStableKey'])['lifecycleStatus'], 'DRAFT')
        self.coordinator.cancel_manual_capture()
        bridge.send_control({'type': 'native_stop'})
        self.child.wait(timeout=3); reader.join(timeout=3)
        self.assertFalse(reader.is_alive())


if __name__ == '__main__':
    unittest.main()
