"""Affected live collector paths with inert delivery/input; no identity work.

The default continuous-canvas cases use deterministic synthetic pixels and
check control rules, not real-game accuracy. Retained SOURCE images are only
read by the explicit tools/native_qa/check_real_terminal_continuity.py command.
"""
import copy
import hashlib
import json
import os
import threading
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

import numpy as np
import cv2

from tests.test_native_content_flow import Run, ROOT
from native_content_fixture import GRID, scene
from native_warehouse_visible_content_gate import VisibleContentGate
from native_warehouse_auto_capture import NativeWarehouseAutoCapture
from warehouse_segment_overlap import align_warehouse_segments, TerminalContinuity
from warehouse_scrollbar_observation import warehouse_search_roi
from warehouse_capture_host import WarehouseCaptureHost

OUT = ROOT / 'build/native-half-viewport-20261009'
PRESEND_RECEIPTS = ROOT / 'tests/fixtures/native_adapter_presend_receipts.json'


class LiveRun(Run):
    def __init__(self, output=OUT):
        super().__init__(content_gate=VisibleContentGate(), output=output)
        # Stop at the analysis handoff. No old recognition/identity suite runs.
        self.finalizations = []
        self.finish = patch.object(self.source, 'finish_manual_capture',
            side_effect=lambda **kw: self.finalizations.append(kw) or {'ok': True, 'reason': 'STAGED'})
        self.finish.start()

    def close(self):
        if self.auto._active:
            self.auto.stop()
        self.finish.stop()

    def saved_trace(self, name):
        path = self.root / (name + '.json')
        path.write_text(json.dumps({'mode': 'inert-delivery-and-input', 'sent': self.sent,
            'diagnostics': self.logs, 'finalizations': self.finalizations}, indent=2), encoding='utf-8')


def viewport(offset):
    """Independent physics: crop one fixed world, advance a physical scrollbar."""
    x, y, r, b = GRID
    top, bottom = scene(0), scene(2)
    world = np.empty((922, r-x, 3), np.uint8)
    world[:b-y] = top[y:b, x:r]
    world[360:] = bottom[y:b, x:r]
    # Distinct artwork provides observable correspondences. The original
    # procedural cards mostly repeat; repeated-texture rejection is tested
    # separately and must not be loosened to make a control fixture pass.
    rng = np.random.RandomState(812)
    for row in range(7):
        for col in range(3):
            xx, yy = 26 + col * 166, 24 + row * 120
            world[yy:yy+44, xx:xx+76] = rng.randint(25, 230, (44, 76, 3), dtype=np.uint8)
    frame = top.copy()
    frame[y:b, x:r] = world[offset:offset+b-y]
    frame[214:776, 1882:1894] = 45
    thumb = 214 + round(362 * offset / 360)
    frame[thumb:thumb+200, 1882:1894] = 210
    return frame


class HalfViewportFlowTests(unittest.TestCase):
    def test_second_scroll_failure_after_verified_move_is_bounded(self):
        # Synthetic viewport physics checks scheduling, not real-game accuracy.
        # Receipt semantics are independently pinned to the Host contract.
        receipts = json.loads(PRESEND_RECEIPTS.read_text(encoding='utf-8'))
        for kind in ('before-target', 'before-send', 'post-send', 'send-unknown', 'send-exception', 'user-stop'):
            with self.subTest(kind=kind):
                f = LiveRun(output=OUT / 'second-scroll-python')
                try:
                    # Retain an unsupported first SOURCE, then obtain normal
                    # viewport hints through the existing sampling contract.
                    f.deliver(scene(0, revealing=True))
                    frame = viewport(0)
                    x, y, r, b = warehouse_search_roi(1920, 1080)
                    def request_with_hints(prefix):
                        with patch('native_warehouse_visible_content_gate.time.perf_counter_ns',
                                side_effect=lambda: round(f.now * 1e9)):
                            for ordinal in (1, 2):
                                f.now += .65
                                f.gate.sampling_hint(frame[y:b, x:r], capture_id=f'{prefix}/{ordinal}',
                                    readback_ns=round(f.now * 1e9))
                            f.tick()
                    request_with_hints('first')
                    f.deliver(frame)
                    request_with_hints('support')
                    f.deliver(frame.copy())
                    self.assertEqual(f.auto._phase, 'WAIT_SCROLL')
                    deadline = f.auto._deadline
                    f.scroll_ack(); f.tick(); f.deliver(viewport(90))
                    self.assertEqual(f.auto._phase, 'WAIT_STABLE')
                    overlap = next(e['alignment'] for e in reversed(f.logs) if e['kind'] == 'image-overlap')
                    self.assertEqual(overlap['status'], 'VERIFIED')
                    self.assertLess(overlap['verticalOffsetPx'], 0)
                    self.assertGreater(overlap['overlapRatio'], 0)
                    frame = viewport(90)
                    request_with_hints('moved-support')
                    f.deliver(frame.copy())
                    self.assertEqual(len(f.intake.pages_copy()), 5)
                    self.assertEqual(f.auto._phase, 'WAIT_SCROLL')
                    command = copy.deepcopy(f.source._pending)
                    self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 2)
                    before = len(f.sent)
                    if kind == 'user-stop':
                        f.auto.stop()
                        event = f.event('CLOSED', command, reason='MANUAL_SOURCE_CLOSED')
                    else:
                        receipt = receipts[kind]
                        details = copy.deepcopy(receipt.get('details'))
                        if details and 'sourceLeaseId' in details:
                            details['sourceLeaseId'] = command['sourceLeaseId']
                        event = f.event(receipt['event'], command, reason=receipt['reason'], details=details)
                    f.auto.on_event(event)
                    f.auto.on_event(copy.deepcopy(event))
                    for _ in range(3):
                        f.auto.poll()
                    safe = kind in ('before-target', 'before-send')
                    self.assertEqual(f.auto._active, safe)
                    self.assertEqual(f.auto._deadline, deadline)
                    self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 2)
                    self.assertFalse(f.auto._post_scroll_frame_received)
                    if safe:
                        self.assertEqual(f.auto._phase, 'WAIT_STABLE')
                        f.tick()
                        self.assertEqual(sum(c['operation'] == 'REQUEST_PAGE' for c in f.sent), 5)
                        self.assertEqual(f.finalizations, [])
                        f.now = deadline; f.auto.poll()
                        self.assertFalse(f.auto._active)
                    else:
                        self.assertFalse(any(c['operation'] == 'REQUEST_PAGE' for c in f.sent[before:]))
                    self.assertEqual(len(f.finalizations), 1)
                    self.assertNotEqual(f.finalizations[0]['termination_reason'], 'COMPLETE')
                    f.auto.on_event(copy.deepcopy(event)); f.auto.poll()
                    self.assertEqual(len(f.finalizations), 1)
                finally:
                    f.close()

    def test_adapter_receipts_recheck_or_stop_without_resending(self):
        # These sanitized production Host contract examples are committed so a
        # clean checkout never depends on ignored build/ output or local logs.
        receipts = json.loads(PRESEND_RECEIPTS.read_text(encoding='utf-8'))
        for kind in ('before-target', 'before-send', 'send-exception', 'send-unknown', 'post-send'):
            with self.subTest(kind=kind):
                receipt = receipts[kind]
                f = LiveRun(output=OUT / 'adapter-receipt-python')
                try:
                    frame = viewport(0)
                    f.deliver(frame); f.tick(); f.deliver(frame.copy())
                    command = copy.deepcopy(f.source._pending)
                    deadline = f.auto._deadline
                    details = copy.deepcopy(receipt.get('details'))
                    # C# and Python use separate isolated SOURCE stores. Rebind
                    # the transport envelope/source ID, retain actual semantics.
                    if details and 'sourceLeaseId' in details:
                        details['sourceLeaseId'] = command['sourceLeaseId']
                    event = f.event(receipt['event'], command, reason=receipt['reason'], details=details)
                    f.auto.on_event(event)
                    safe = kind in ('before-target', 'before-send')
                    if not safe:
                        self.assertFalse(f.auto._active)
                        self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
                        f.auto.poll()
                        self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 1)
                        continue
                    self.assertTrue(f.auto._active)
                    self.assertEqual(f.auto._phase, 'WAIT_STABLE')
                    self.assertEqual(f.auto._deadline, deadline)
                    self.assertFalse(f.auto._post_scroll_frame_received)
                    f.tick()
                    self.assertEqual(sum(c['operation'] == 'REQUEST_PAGE' for c in f.sent), 2)
                    self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 1)
                    x, y, r, b = warehouse_search_roi(1920, 1080)
                    with patch('native_warehouse_visible_content_gate.time.perf_counter_ns',
                            side_effect=lambda: round(f.now * 1e9)):
                        f.now += .1
                        f.gate.sampling_hint(frame[y:b, x:r], capture_id='hint/1', readback_ns=round(f.now * 1e9))
                        f.now += .65
                        f.gate.sampling_hint(frame[y:b, x:r], capture_id='hint/2', readback_ns=round(f.now * 1e9))
                        f.tick()
                    self.assertEqual(f.sent[-1]['operation'], 'REQUEST_PAGE')
                    f.deliver(frame.copy())
                    self.assertEqual(f.auto._phase, 'WAIT_SCROLL')
                    self.assertNotEqual(f.source._pending['sourceLeaseId'], command['sourceLeaseId'])
                    self.assertEqual(f.source._pending['savedCaptureId'], command['stableCaptureId'])
                    self.assertEqual(f.auto._deadline, deadline)
                    f.now = deadline; f.auto.poll()
                    self.assertFalse(f.auto._active)
                    self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
                finally:
                    f.close()

    def test_not_sent_content_recheck_requires_new_support_and_original_budget(self):
        # Receipts are an explicit Host contract, not inferred from elapsed
        # time or a generic failure reason. Pixels here test scheduling only.
        safe_receipt = json.loads(PRESEND_RECEIPTS.read_text(encoding='utf-8'))['before-send']
        for variant in ('safe', 'unknown-send', 'other-guard'):
            with self.subTest(variant=variant):
                f = LiveRun()
                try:
                    frame = viewport(0)
                    f.deliver(frame); f.tick(); f.deliver(frame.copy())
                    command = copy.deepcopy(f.source._pending)
                    deadline = f.auto._deadline
                    details = copy.deepcopy(safe_receipt['details'])
                    details['sourceLeaseId'] = command['sourceLeaseId']
                    if variant == 'unknown-send':
                        details['sendInterfaceInvoked'] = None
                    elif variant == 'other-guard':
                        details['failedChecks'].append('targetUsable')
                    rejected = f.event(safe_receipt['event'], command,
                        reason=safe_receipt['reason'], details=details)
                    stale = copy.deepcopy(rejected); stale['nonce'] = 'previous-command'
                    f.auto.on_event(stale)
                    self.assertEqual(f.auto._phase, 'WAIT_SCROLL')
                    f.auto.on_event(rejected)
                    if variant != 'safe':
                        self.assertFalse(f.auto._active)
                        self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
                        continue
                    self.assertTrue(f.auto._active)
                    self.assertEqual(f.auto._phase, 'WAIT_STABLE')
                    self.assertFalse(f.auto._post_scroll_frame_received)
                    self.assertEqual(f.auto._deadline, deadline)
                    self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 1)
                    # A repeated coordinator advance still sees the receipt's
                    # old reason. Once its safe recheck has been consumed it
                    # must keep waiting for independent SOURCE, not stop.
                    pages_before_repeat = len(f.source.pages_copy())
                    requests_before_repeat = sum(c['operation'] == 'REQUEST_PAGE' for c in f.sent)
                    f.auto._advance()
                    self.assertTrue(f.auto._active)
                    self.assertEqual(f.auto._phase, 'WAIT_STABLE')
                    self.assertEqual(len(f.source.pages_copy()), pages_before_repeat)
                    self.assertEqual(sum(c['operation'] == 'REQUEST_PAGE' for c in f.sent), requests_before_repeat)
                    self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 1)
                    f.tick()  # No hints: no new SOURCE and no resend.
                    self.assertEqual(sum(c['operation'] == 'REQUEST_PAGE' for c in f.sent), 2)
                    x, y, r, b = warehouse_search_roi(1920, 1080)
                    with patch('native_warehouse_visible_content_gate.time.perf_counter_ns',
                            side_effect=lambda: round(f.now * 1e9)):
                        f.now += .1
                        f.gate.sampling_hint(frame[y:b, x:r], capture_id='hint/1', readback_ns=round(f.now * 1e9))
                        f.now += .65
                        f.gate.sampling_hint(frame[y:b, x:r], capture_id='hint/2', readback_ns=round(f.now * 1e9))
                        f.tick()
                    self.assertEqual(f.sent[-1]['operation'], 'REQUEST_PAGE')
                    f.deliver(frame.copy())
                    self.assertEqual(f.auto._phase, 'WAIT_SCROLL')
                    self.assertNotEqual(f.source._pending['sourceLeaseId'], command['sourceLeaseId'])
                    self.assertEqual(f.source._pending['savedCaptureId'], command['stableCaptureId'])
                    self.assertEqual(f.auto._deadline, deadline)
                    f.now = deadline
                    f.auto.poll()
                    self.assertFalse(f.auto._active)
                    self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
                finally:
                    f.close()

    def test_live_gate_binds_armed_policy_after_main_initialization(self):
        # Before observation, Main has no live policy authority. Each armed
        # scope chooses the gate; Strict must keep its existing source contract.
        for policy, retained in (('wgc-origin-strict-v1', False), ('wgc-delivery-v1', True)):
            with self.subTest(policy=policy):
                source = Mock()
                source.intake._scope_lock = threading.RLock()
                scope = {'recordStableKey': 'match', 'capturePolicy': policy}
                source.prepare_manual.return_value = {'ok': True}
                source.intake.source_contract.return_value = {'scope': scope}
                source.start_manual.return_value = {'ok': True}
                gate = VisibleContentGate()
                collector = NativeWarehouseAutoCapture(source, timers=False, content_gate=gate)
                self.assertTrue(collector.confirm(collector.prepare()['armingToken'])['ok'])
                options = source.start_manual.call_args.kwargs
                self.assertEqual(options.get('retain_independent_originals', False), retained)
                self.assertEqual(isinstance(collector._content_gate, VisibleContentGate), retained)

    def test_equal_pixels_keep_independent_capture_binding(self):
        f = LiveRun(); self.addCleanup(f.close)
        frame = viewport(0)
        f.deliver(frame); f.tick(); f.deliver(frame)
        a, b = f.intake.pages_copy()
        self.assertEqual(a['descriptor']['evidenceId'], b['descriptor']['evidenceId'])
        self.assertNotEqual(a['deliveryProof']['captureId'], b['deliveryProof']['captureId'])
        self.assertEqual((a['contentRole'], b['contentRole']), ('STABLE_ANCHOR', 'STABLE_SUPPORT'))
        replaced = copy.deepcopy(f.auto._observation)
        replaced['contentProfile']['captureId'] = a['deliveryProof']['captureId']
        self.assertFalse(f.gate.final_support(replaced)['qualified'])
        self.assertFalse(f.gate.compare(f.auto._observation, f.auto._observation)['qualified'])

    def test_continuous_views_and_near_bottom_move_then_stationary_tail(self):
        f = LiveRun()
        self.addCleanup(f.close)
        for i, offset in enumerate((0, 90, 180, 270, 340, 360)):
            if i:
                f.scroll_ack(); f.tick()
            frame = viewport(offset)
            f.deliver(frame)
            self.assertEqual(f.auto._phase, 'WAIT_STABLE', f.logs[-3:])
            # One original never grants the next wheel, including at the end.
            self.assertEqual(len(f.finalizations), 0)
            f.tick(); f.deliver(frame.copy())
            self.assertEqual(f.auto._phase, 'WAIT_SCROLL', f.logs[-3:])
            if offset >= 340:
                self.assertTrue(f.logs[-1]['kind'] == 'scroll-step')
                self.assertEqual(f.sent[-1]['wheelDelta'], -120)
        # The first BOTTOM-classified viewport still advanced to the physical
        # endpoint. Now the successfully sent tail message leaves it unchanged.
        f.scroll_ack(); f.tick(); f.deliver(viewport(360))
        self.assertEqual(f.auto._phase, 'WAIT_STABLE')
        self.assertTrue(f.auto._tail_stationary)
        self.assertEqual(f.finalizations, [])
        f.tick(); f.deliver(viewport(360))
        self.assertFalse(f.auto._active)
        self.assertEqual(f.auto._reason, 'COMPLETE')
        self.assertEqual(f.finalizations[-1]['termination_reason'], 'COMPLETE')
        self.assertEqual(len(f.gate.representatives()), 6)
        self.assertEqual(f.auto._deadline, 170)
        self.assertEqual(len(f.intake.pages_copy()), 14)
        self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 6)
        # Consume the selected originals through the same production Host
        # matching/observer/coverage ledger. Only reconstruction and identity
        # consumers are inert, so this does not rerun closed identification.
        selected = f.finalizations[-1]['qualified_evidence_ids']
        descriptors = [p['descriptor'] for p in f.intake.pages_copy()
                       if p['descriptor']['evidenceId'] in selected]
        host = WarehouseCaptureHost(store_factory=lambda: f.intake.evidence_store, driver_available=False)
        history = Mock()
        history.persist_warehouse_evidence.return_value = {'settlement': {}}
        with patch('warehouse_reconstruction.WarehouseReconstructionProcessor') as factory, \
                patch('warehouse_identity_review.build_auto_identity_review_artifact', return_value={}):
            factory.return_value.accept_segment.return_value = {'accepted': True}
            factory.return_value.packet_copy.return_value = {'reviewUnits': []}
            result = host._process_saved_pages('match', descriptors, history_store=history, resolve_placements=False)
            disconnected = [p for p in descriptors if p['evidenceId'] in (selected[0], selected[-1])]
            gap = host._process_saved_pages('match', disconnected, history_store=history, resolve_placements=False)
        self.assertEqual(result['coverageStatus'], 'COMPLETE', result['coverage'])
        self.assertEqual(len(result['coverage']['overlapProofs']), 5)
        self.assertEqual(result['coverage']['gaps'], [])
        self.assertEqual(gap['coverageStatus'], 'PARTIAL', gap['coverage'])
        self.assertIsNotNone(gap['coverage']['bottomEndpoint'])
        self.assertTrue(gap['coverage']['gaps'])
        (f.root / 'production-coverage.json').write_text(json.dumps(result['coverage'], indent=2), encoding='utf-8')
        f.saved_trace('continuous-tail')

    def test_middle_message_without_movement_is_partial(self):
        f = LiveRun(); self.addCleanup(f.close)
        f.deliver(viewport(0)); f.tick(); f.deliver(viewport(0))
        f.scroll_ack(); f.tick(); f.deliver(viewport(90))
        f.tick(); f.deliver(viewport(90))
        f.scroll_ack(); f.tick(); f.deliver(viewport(90))
        self.assertFalse(f.auto._active)
        self.assertEqual(f.auto._reason, 'WINDOW_SCROLL_NO_PROGRESS')
        self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
        f.saved_trace('middle-no-progress')

    def test_repeated_grid_and_horizontal_drift_do_not_grant_overlap(self):
        a = np.zeros((560, 560, 3), np.uint8)
        for y in range(0, 560, 56):
            a[y:y+2] = 150
        for x in range(0, 560, 56):
            a[:, x:x+2] = 150
        repeated = align_warehouse_segments(a, np.roll(a, -280, axis=0), required_direction='DOWN')
        self.assertNotEqual(repeated['status'], 'VERIFIED', repeated)
        x, y, r, b = warehouse_search_roi(1920, 1080)
        a = viewport(0)[y:b, x:r]
        drifted = np.roll(viewport(180)[y:b, x:r], 25, axis=1)
        result = align_warehouse_segments(a, drifted, required_direction='DOWN')
        self.assertNotEqual(result['status'], 'VERIFIED', result)


@unittest.skipUnless(os.environ.get('YIHUAN_REAL_SOURCE_QA') == '1',
    'uses retained local SOURCE images; run tools/native_qa/check_real_terminal_continuity.py explicitly')
class RealSourceTerminalContinuityQATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = json.loads((ROOT / 'build/native-auto-pages-20261010/real-once-08/run-result.json')
                            .read_text(encoding='utf-8'))
        cls.frames = []
        for original in result['originals']:
            payload = (ROOT / Path(original['path']).relative_to(ROOT)).read_bytes()
            if hashlib.sha256(payload).hexdigest() != original['sha256']:
                raise AssertionError('Retained original changed')
            cls.frames.append(cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR))
        x, y, r, b = warehouse_search_roi(1920, 1080)
        cls.crops = [im[y:b, x:r] for im in cls.frames]
        cls.output = ROOT / 'build/native-terminal-continuity-20261010'
        cls.output.mkdir(exist_ok=True)

    def calibrated(self):
        context = TerminalContinuity()
        for i, j, expected in ((1, 2, -270), (3, 4, -271)):
            result = self.match(self.crops[i], self.crops[j], context, i, j)
            self.assertEqual(result['status'], 'VERIFIED', result)
            self.assertEqual(result['verticalOffsetPx'], expected)
        return context

    @staticmethod
    def match(a, b, context, i=5, j=6):
        return align_warehouse_segments(a, b, prev_id=f'original-{i+1}', next_id=f'original-{j+1}',
            required_direction='DOWN', terminal_continuity=context)

    def test_real_terminal_grid_needs_two_connected_content_calibrations(self):
        a, b = self.crops[5:7]
        result = self.match(a, b, self.calibrated())
        self.assertEqual(result['reason'], 'TERMINAL_SCROLLBAR_GRID_CONTINUITY', result)
        self.assertEqual(result['status'], 'VERIFIED')
        self.assertLess(result['verticalOffsetPx'], -260)
        self.assertGreater(result['verticalOffsetPx'], -280)
        self.assertGreater(result['overlapRatio'], .5)
        self.assertFalse(result['bottomConfirmed'])
        for context in (None, TerminalContinuity()):
            self.assertNotEqual(self.match(a, b, context)['status'], 'VERIFIED')
        one = TerminalContinuity()
        self.match(self.crops[1], self.crops[2], one, 1, 2)
        self.assertNotEqual(self.match(a, b, one)['status'], 'VERIFIED')
        (self.output / 'real-terminal-match.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

    def test_false_bottom_wrong_grid_phase_and_skipped_real_view_are_rejected(self):
        a, b = self.crops[5:7]
        middle = b.copy()
        # The actual terminal grid, with the preceding real scrollbar: a
        # non-moving/middle thumb cannot turn this into a bottom proof.
        middle[:, 565:580] = a[:, 565:580]
        wrong_phase = b.copy()
        wrong_phase[:559, :562] = np.roll(b[:559, :562], -28, axis=0)
        drift = b.copy()
        drift[:559, :562] = np.roll(b[:559, :562], 25, axis=1)
        negatives = [('false-bottom', a, middle, 5, 6),
            ('grid-phase-disagrees-with-thumb', a, wrong_phase, 5, 6),
            ('horizontal-drift', a, drift, 5, 6),
            # Real originals, skipping the already-observed middle viewport.
            ('skipped-real-page', self.crops[3], b, 3, 6)]
        results = []
        for name, before, after, i, j in negatives:
            with self.subTest(name=name):
                result = self.match(before, after, self.calibrated(), i, j)
                self.assertNotEqual(result['status'], 'VERIFIED', result)
                results.append({'case': name, 'result': result})
        (self.output / 'terminal-counterexamples.json').write_text(json.dumps(results, indent=2), encoding='utf-8')

    def test_retained_sequence_requests_independent_support_and_host_rechecks_chain(self):
        f = LiveRun(output=self.output)
        self.addCleanup(f.close)
        for pair in range(3):
            if pair:
                f.scroll_ack(); f.tick()
            f.deliver(self.frames[pair * 2]); f.tick(); f.deliver(self.frames[pair * 2 + 1])
            self.assertEqual(f.auto._phase, 'WAIT_SCROLL', f.logs[-3:])
        f.scroll_ack(); f.tick(); f.deliver(self.frames[6])
        self.assertTrue(f.auto._active)
        self.assertEqual(f.auto._phase, 'WAIT_STABLE', f.logs[-3:])
        self.assertEqual(f.finalizations, [])
        self.assertEqual(len(f.gate.representatives()), 3)  # Saved #7 is not qualified.
        deadline = f.auto._deadline
        f.tick()
        self.assertEqual(f.sent[-1]['operation'], 'REQUEST_PAGE')
        self.assertEqual(f.auto._request_attempts, 8)

        def archived(selected, termination):
            descriptors = [p['descriptor'] for p in f.intake.pages_copy()
                           if p['descriptor']['evidenceId'] in selected]
            host = WarehouseCaptureHost(store_factory=lambda: f.intake.evidence_store, driver_available=False)
            history = Mock()
            history.persist_warehouse_evidence.return_value = {'settlement': {}}
            with patch('warehouse_reconstruction.WarehouseReconstructionProcessor') as factory, \
                    patch('warehouse_identity_review.build_auto_identity_review_artifact', return_value={}):
                factory.return_value.accept_segment.return_value = {'accepted': True}
                factory.return_value.packet_copy.return_value = {'reviewUnits': []}
                return host._process_saved_pages('match', descriptors, history_store=history,
                    resolve_placements=False, finalization_reason=termination)

        actual = archived(f.gate.representatives(), 'INCOMPLETE')
        self.assertEqual(actual['coverageStatus'], 'PARTIAL', actual['coverage'])
        self.assertIsNone(actual['coverage']['bottomEndpoint'])
        # Inert contract simulation ONLY: no real independent #8 or stationary
        # endpoint originals exist. Reusing #7 pixels below checks the required
        # scheduling/ledger gates, not actual bottom or real accuracy.
        f.deliver(self.frames[6].copy())
        self.assertEqual(f.auto._phase, 'WAIT_SCROLL')
        self.assertEqual(f.sent[-1]['wheelDelta'], -120)
        self.assertEqual(f.finalizations, [])
        f.scroll_ack(); f.tick(); f.deliver(self.frames[6].copy())
        self.assertTrue(f.auto._tail_stationary)
        self.assertEqual(f.finalizations, [])
        f.tick(); f.deliver(self.frames[6].copy())
        self.assertEqual(f.auto._reason, 'COMPLETE')
        simulated = archived(f.finalizations[-1]['qualified_evidence_ids'], 'COMPLETE')
        self.assertEqual(simulated['coverageStatus'], 'COMPLETE', simulated['coverage'])
        self.assertEqual(len(simulated['coverage']['overlapProofs']), 3)
        selected = f.finalizations[-1]['qualified_evidence_ids']
        disconnected = archived([selected[0], selected[-1]], 'COMPLETE')
        self.assertEqual(disconnected['coverageStatus'], 'PARTIAL', disconnected['coverage'])
        self.assertTrue(disconnected['coverage']['gaps'])
        self.assertEqual(f.auto._deadline, deadline)
        (self.output / 'terminal-flow-boundaries.json').write_text(json.dumps({
            'retainedRealCoverage': actual['coverage'], 'inertEndpointSimulation': simulated['coverage'],
            'disconnectedRetainedViews': disconnected['coverage'],
            'realLastPageSupportMissing': True, 'deadlineUnchanged': True,
            'realCapture': False, 'realInput': False}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
