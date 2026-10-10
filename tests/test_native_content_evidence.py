"""Evidence-only SOURCE contracts. Synthetic pixels check rules, not real accuracy."""
import copy
import asyncio
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core'), str(ROOT), str(ROOT / 'tools')]
from canonical_match_record import build_canonical_match_record_v7
from native_trial_drafts import NativeTrialDraftStore
from native_warehouse_intake import NativeWarehouseIntake
from native_warehouse_source import NativeWarehouseSourceCoordinator, SCHEMA_V2
from native_content_evidence import NativeContentEvidenceSession
from tests.test_native_delivery_contract import proof
from collect_native_content_evidence import collect


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        directory = ROOT / 'build/native-content-evidence-20261009/python-checks'
        directory.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(dir=directory, prefix='source-'))
        self.now, self.sent = [100.0], []
        self.scope = {'recordStableKey': 'match', 'observationSessionId': 'offline',
            'targetInstance': {'targetHwnd': 12}, 'matchGeneration': 1,
            'scene': 'SETTLEMENT', 'capturePolicy': 'wgc-delivery-v1'}
        self.store = NativeTrialDraftStore(self.root / 'trial/history.json')
        record = build_canonical_match_record_v7(match_id='match', played_at='2026-10-09T00:00:00Z',
            lifecycle_status='DRAFT', source='manual', settlement={})
        record['dataOrigin'] = 'live-trial'; self.store.save_draft(record)
        self.history = self.store.history_path.read_bytes()
        self.intake = NativeWarehouseIntake(draft_store=self.store, scope_provider=lambda: self.scope,
            source_provider=lambda: None, clock=lambda: self.now[0])
        self.source = NativeWarehouseSourceCoordinator(self.intake,
            send_control=lambda cmd: self.sent.append(copy.deepcopy(cmd)) or True,
            source_root_provider=lambda: self.root, timers=False, clock=lambda: self.now[0],
            qpc=lambda: round(self.now[0] * 1e9), evidence_only=True)
        self.session = NativeContentEvidenceSession(self.source, qpc=lambda: round(self.now[0] * 1e9))
        self.assertFalse(self.source.start_manual(allow_window_scroll=True)['ok'])
        self.assertEqual(self.sent, [])
        self.processor = patch.object(self.intake, 'finish_manual_capture', side_effect=AssertionError('no item processing'))
        self.processor.start(); self.addCleanup(self.processor.stop)
        title = patch('scene_anchors.settlement_title_visible', return_value=True)
        title.start(); self.addCleanup(title.stop)
        self.assertTrue(self.session.handle('begin')['ok'])
        opened = self.sent[-1]
        self.assertFalse(opened['allowWindowScroll'])
        self.assertTrue(opened['retainIndependentOriginals'])
        self.source.on_event(self.event('OPENED', details={'deadlineNs': 170_000_000_000,
            'clientWidth': 4, 'clientHeight': 3, 'remainingSourcePages': 16,
            'remainingRawBytes': 128 * 1024 * 1024, 'maxPngBytes': 64 * 1024 * 1024,
            'pngEncoding': 'opencv-bgr8-png-bound.v1', 'clientMap': 'map',
            'windowScrollSupported': False, 'retainIndependentOriginals': True}))

    def event(self, kind, **extra):
        command = self.sent[-1]
        event = {key: copy.deepcopy(command[key]) for key in ('commandId', 'nonce', 'requestOrdinal',
            'observationSessionId', 'reviewSessionId', 'reviewGeneration', 'recordStableKey', 'matchGeneration')}
        event.update(type='native_warehouse_evidence', schemaVersion=SCHEMA_V2, capturePolicy='wgc-delivery-v1',
            sourceKind='native_wgc', inputActions=False, formalHistoryWriter=False, event=kind,
            targetInstance=copy.deepcopy(self.scope['targetInstance']), leaseToken='a' * 32)
        event.update(extra)
        return event

    def admit(self):
        request = self.session.handle('page')
        self.assertTrue(request['ok'], request)
        seq = self.source.source_session_snapshot()['requestAttempts']
        p = proof(seq, request=round(self.now[0] * 1e9))
        pixels = bytes([30, 40, 50, 255] * 12)
        raw = struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54)
        raw += struct.pack('<IiiHHIIiiII', 40, 4, -3, 1, 32, 0, len(pixels), 0, 0, 0, 0) + pixels
        lease = f'{seq:032x}'
        path = self.root / 'warehouse-sources' / (lease + '.bmp')
        path.parent.mkdir(exist_ok=True); path.write_bytes(raw)
        self.now[0] = (p['readbackCompletedNs'] + 100) / 1e9
        source = {'sourceLeaseId': lease, 'path': str(path), 'width': 4, 'height': 3, 'stride': 16,
            'byteCount': len(raw), 'pixelSha256': hashlib.sha256(pixels).hexdigest(),
            'bmpSha256': hashlib.sha256(raw).hexdigest(), 'capturedAtUtc': '2026-10-09T00:00:00Z',
            'frameSequence': seq, 'sourceTimestampNs': p['sourceTimestampNs'], 'requestGateNs': p['requestNs'],
            'readbackTimestampNs': p['readbackCompletedNs'], 'clientMap': 'map', 'deliveryProof': p,
            'capturePolicy': 'wgc-delivery-v1', 'matchGeneration': 1, 'formalFactsQualified': False}
        self.source.on_event(self.event('SOURCE', source=source))
        self.assertEqual(self.sent[-1]['operation'], 'ACK_SOURCE')
        self.assertEqual(self.sent[-1]['result'], 'SAVED')
        self.assertEqual(len(self.source.pages_copy()), seq)
        return p

    def test_identical_independent_originals_14_request_plan_no_processing_or_input(self):
        self.assertFalse(self.source.request_scroll_down()['ok'])
        self.assertFalse(self.source.finish_manual_capture()['ok'])
        for ordinal in range(1, 15):
            if ordinal == 5:
                self.assertTrue(self.session.handle('visible-content-ready')['ok'])
            if ordinal == 11:
                self.assertEqual(self.session.handle('page')['reason'], 'ONE_MANUAL_SCROLL_REQUIRED')
                self.assertTrue(self.session.handle('manual-scroll-done')['ok'])
                self.assertFalse(self.session.handle('manual-scroll-done')['ok'])
            self.admit()
            if ordinal < 10:
                self.assertEqual(self.session.handle('page')['reason'], 'INDEPENDENT_REQUEST_INTERVAL_PENDING')
            self.now[0] += .251
        self.assertEqual(self.session.handle('page')['reason'], 'EVIDENCE_REQUEST_LIMIT_REACHED')
        self.assertFalse(self.source.capture_manual_page()['ok'], 'direct UI requests share the same 14 limit')
        pages = self.session.handle('status')['pages']
        self.assertEqual(len({p['deliveryProof']['captureId'] for p in pages}), 14)
        self.assertEqual(len({p['pixelSha256'] for p in pages}), 1)
        for page in pages:
            self.assertFalse(self.store.read_source_image_descriptor(page['nativeSource']).get('error'))
        self.assertTrue(self.session.handle('end')['ok'])
        self.assertFalse(self.session.handle('begin')['ok'], 'one use, no reset of settlement allowance')
        self.assertFalse(self.session.handle('page')['ok'])
        self.assertEqual(self.store.history_path.read_bytes(), self.history)
        self.assertTrue(all(c['operation'] in {'OPEN', 'REQUEST_PAGE', 'ACK_SOURCE', 'CLOSE'} for c in self.sent))
        manifests = list((self.store.root / 'warehouse-intake').glob('*.json'))
        self.assertEqual(len(json.loads(manifests[0].read_text(encoding='utf-8'))['pages']), 14)

    def test_original_deadline_and_scope_loss_stop_without_restarting(self):
        self.admit()
        self.now[0] = 170
        before = len([c for c in self.sent if c['operation'] == 'REQUEST_PAGE'])
        self.assertFalse(self.session.handle('page')['ok'])
        self.assertEqual(len([c for c in self.sent if c['operation'] == 'REQUEST_PAGE']), before)
        self.assertTrue(self.session.handle('end')['ok'])
        self.assertEqual(len(self.source.pages_copy()), 1)
        self.assertFalse(self.session.handle('begin')['ok'])

    def test_changed_window_cannot_add_an_original(self):
        self.admit(); self.now[0] += .251
        self.scope['targetInstance'] = {'targetHwnd': 99}
        self.assertFalse(self.session.handle('page')['ok'])
        self.assertEqual(len(self.source.pages_copy()), 1)
        self.assertTrue(self.session.handle('end')['ok'])
        self.assertEqual(self.store.history_path.read_bytes(), self.history)

    def test_ready_marker_pauses_after_four_and_is_bound_to_current_stage_and_scope(self):
        self.assertFalse(self.session.handle('visible-content-ready')['ok'], 'early mark must not latch')
        for _ in range(4):
            self.admit(); self.now[0] += .251
        sent = copy.deepcopy(self.sent)
        deadline = self.source.source_session_snapshot()['deadline']
        self.now[0] += 3
        self.assertEqual(self.session.handle('page')['reason'], 'USER_VISIBLE_CONTENT_READY_REQUIRED')
        self.assertEqual(self.sent, sent, 'waiting creates no fifth SOURCE request')
        self.assertFalse(self.session.handle('manual-scroll-done')['ok'])
        self.scope['targetInstance'] = {'targetHwnd': 99}
        self.assertEqual(self.session.handle('visible-content-ready')['reason'], 'SOURCE_SCOPE_CHANGED')
        self.scope['targetInstance'] = {'targetHwnd': 12}
        marked = self.session.handle('visible-content-ready')
        self.assertTrue(marked['ok'])
        self.assertEqual(marked['marker'], 'USER_VISIBLE_CONTENT_READY')
        self.assertFalse(marked['formalFactsQualified'])
        self.assertFalse(marked['coverageQualified'])
        self.assertFalse(self.session.handle('visible-content-ready')['ok'], 'duplicate mark cannot grant another stage')
        self.assertEqual(self.source.source_session_snapshot()['deadline'], deadline)
        self.admit()
        self.assertEqual(self.source.source_session_snapshot()['requestAttempts'], 5)
        self.assertFalse(self.session.handle('visible-content-ready')['ok'], 'old stage marker is no longer accepted')
        self.assertIsNone(self.session.manual_scroll_ns)
        self.assertTrue(self.session.handle('end')['ok'])

    def test_ready_wait_keeps_original_deadline_and_retains_four_on_expiry(self):
        for _ in range(4):
            self.admit(); self.now[0] += .251
        deadline = self.source.source_session_snapshot()['deadline']
        self.now[0] = deadline
        self.assertFalse(self.session.handle('visible-content-ready')['ok'])
        self.assertFalse(self.session.handle('page')['ok'])
        self.assertEqual(self.source.source_session_snapshot()['deadline'], deadline)
        self.assertEqual(self.source.source_session_snapshot()['requestAttempts'], 4)
        self.assertEqual(len(self.session.handle('status')['pages']), 4)
        self.assertTrue(self.session.handle('end')['ok'])
        self.assertFalse(self.session.handle('begin')['ok'])


class LauncherProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_stage_prompts_14_requests_expiry_and_cancel_preserve_partial(self):
        # Exercise the actual scheduler against inert bus replies. No start(), windows or IO input.
        for fail_at in (None, 3, 'ready-deadline', 'ready-cancel'):
            with self.subTest(fail_at=fail_at):
                directory = ROOT / 'build/native-content-evidence-20261009/python-checks'
                directory.mkdir(parents=True, exist_ok=True)
                output = Path(tempfile.mkdtemp(dir=directory, prefix='launcher-'))
                events = []
                class Bus:
                    def __init__(self):
                        self.requests, self.pages, self.manual, self.ended = 0, [], None, False
                        self.visible = None
                        self.deadline = time.monotonic() + 70
                        self.ready_waits = self.scroll_waits = 0
                    async def send(self, raw):
                        self.command = json.loads(raw)
                    async def recv(self):
                        command = self.command
                        operation = command['operation']
                        reply = {'type': 'native_content_evidence_receipt', 'requestId': command['requestId'], 'ok': True}
                        if operation == 'status':
                            if self.requests == 4 and self.visible is None:
                                self.ready_waits += 1
                                if fail_at == 'ready-deadline' and self.ready_waits >= 3:
                                    self.deadline = time.monotonic() - 1
                            if self.requests == 10 and self.manual is None:
                                self.scroll_waits += 1
                            reply.update(snapshot={'state': 'OPEN', 'deadline': self.deadline,
                                'requestAttempts': self.requests, 'reason': None}, pages=copy.deepcopy(self.pages),
                                userVisibleContentReadyNs=self.visible,
                                manualScrollAcknowledgedNs=self.manual)
                        elif operation == 'page':
                            if self.requests >= 4:
                                self_test.assertIsNotNone(self.visible, 'no fifth request before user mark')
                            if self.requests >= 10:
                                self_test.assertIsNotNone(self.manual, 'ready mark is not a scroll mark')
                            self.requests += 1
                            if self.requests == fail_at:
                                reply.update(ok=False, reason='SOURCE_SEND_FAILED')
                            else:
                                self.pages.append({'deliveryProof': {'captureId': str(self.requests),
                                    'readbackCompletedNs': self.requests * 300_000_000}})
                        elif operation == 'visible-content-ready':
                            self_test.assertEqual(self.requests, 4)
                            self_test.assertGreaterEqual(self.ready_waits, 4, 'premature/buffered Enter was discarded')
                            self.visible = 1
                            reply.update(marker='USER_VISIBLE_CONTENT_READY', acknowledgedNs=1,
                                formalFactsQualified=False, coverageQualified=False)
                        elif operation == 'manual-scroll-done':
                            self_test.assertEqual(self.requests, 10)
                            self_test.assertGreaterEqual(self.scroll_waits, 3, 'first-stage Enter was not reused')
                            self.manual = 1
                        elif operation == 'end':
                            self.ended = True
                        return json.dumps(reply)
                bus = Bus()
                self_test = self
                def record(kind, **details): events.append((kind, details))
                def signal(_):
                    if bus.requests == 4 and bus.visible is None:
                        if fail_at == 'ready-cancel' and bus.ready_waits >= 3:
                            raise RuntimeError('USER_STOP')
                        return bus.ready_waits == 0 or bus.ready_waits >= 3
                    if bus.requests == 10 and bus.manual is None:
                        return bus.scroll_waits == 0 or bus.scroll_waits >= 2
                    return False
                with patch('collect_native_content_evidence.user_signal', side_effect=signal):
                    completed = await collect(bus, output, record)
                result = json.loads((output / 'evidence-result.json').read_text(encoding='utf-8'))
                self.assertTrue(bus.ended)
                self.assertFalse(result['automaticCaptureComplete'])
                self.assertEqual(completed, fail_at is None)
                if fail_at is None:
                    self.assertEqual(bus.requests, 14)
                    self.assertEqual(len(result['pages']), 14)
                    self.assertEqual(sum(kind == 'one-manual-scroll-now' for kind, _ in events), 1)
                    self.assertEqual(sum(kind == 'visible-content-ready-now' for kind, _ in events), 1)
                    self.assertEqual(sum(kind == 'USER_VISIBLE_CONTENT_READY' for kind, _ in events), 1)
                    self.assertEqual(sum(kind == 'manual-scroll-user-acknowledged' for kind, _ in events), 1)
                elif fail_at == 3:
                    self.assertEqual(bus.requests, 3)
                    self.assertEqual(len(result['pages']), 2)
                    self.assertEqual(result['terminationReason'], 'SOURCE_SEND_FAILED')
                else:
                    self.assertEqual(bus.requests, 4)
                    self.assertEqual(len(result['pages']), 4)
                    self.assertIsNone(bus.visible)
                    self.assertEqual(result['terminationReason'], 'USER_STOP' if fail_at == 'ready-cancel'
                        else 'ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')


if __name__ == '__main__':
    unittest.main()
