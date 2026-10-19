"""Affected live collector paths with inert delivery/input; no identity work.

The default continuous-canvas cases use deterministic synthetic pixels and
check control rules, not real-game accuracy. Retained SOURCE images are only
read by the explicit tools/native_qa/check_real_terminal_continuity.py command.
"""
import copy
import hashlib
import json
import os
import struct
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
    def __init__(self, output=OUT, capture_first=False):
        super().__init__(content_gate=VisibleContentGate(), output=output, capture_first=capture_first)
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


@unittest.skipUnless((ROOT/'build/t1-20261012/real-once-10/runtime-data/native-live-trial/warehouse-intake').is_dir(),
    'requires the retained private once-10 SOURCE archive')
class RealOnceTenCoverageTests(unittest.TestCase):
    def test_saved_top_to_bottom_coverage_does_not_promote_animated_pixels_to_item_facts(self):
        store = ROOT/'build/t1-20261012/real-once-10/runtime-data/native-live-trial'
        manifest = next((store/'warehouse-intake').glob('*.json'))
        pages = json.loads(manifest.read_text(encoding='utf-8'))['pages']
        frames = {}
        for n in range(26,40):
            source = pages[n-1]['nativeSource']
            raw = (store/source['relativePath']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),source['sha256'])
            frames[n] = cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
        f = LiveRun(output=ROOT/'build/t1-20261012/once10-coverage-replay',capture_first=True)
        try:
            f.deliver(frames[26]); f.tick(); f.deliver(frames[27])
            for i in range(28,40,2):
                f.scroll_ack(); f.tick(); f.deliver(frames[i])
                f.tick(); f.deliver(frames[i+1])
            self.assertEqual(f.auto._reason,'COMPLETE')
            final = f.finalizations[-1]
            self.assertEqual(len(final['coverage_evidence_ids']),7)
            self.assertEqual(len(final['qualified_evidence_ids']),2,
                             'background motion must not grant item identity support')
            f.finish.stop()
            f.source.offline_test_adapter = False
            self.assertTrue(f.source.finish_manual_capture(**final)['ok'])
            f.intake.wait_processing(30)
            packet = f.intake.review_packet_copy()
            self.assertEqual(packet['warehouseCoverage']['status'],'COMPLETE')
            self.assertEqual(packet['warehouseCoverage']['segmentCount'],7)
            # The five background-changing views cover pixels but add no item
            # observations; missing the middle cannot become a complete chain.
            unqualified = set(final['coverage_evidence_ids'])-set(final['qualified_evidence_ids'])
            self.assertTrue(packet['tracks'])
            for unit in packet['tracks']:
                self.assertFalse(unqualified & {o['evidenceId'] for o in unit.get('observations',[])})
            from native_warehouse_intake import NativeWarehouseIntake
            fresh = NativeWarehouseIntake(draft_store=f.store,scope_provider=lambda:None,
                source_provider=lambda:None,auto_refine=False)
            before = f.store.history_path.read_bytes()
            with patch.object(WarehouseCaptureHost,'_process_saved_pages',
                    side_effect=AssertionError('reopening must reuse the saved result')):
                self.assertTrue(fresh.recover_saved_capture(f.intake._session_id)['ok'])
            self.assertEqual(fresh.review_packet_copy(),packet)
            self.assertEqual(f.store.history_path.read_bytes(),before)
            descriptors = [p['descriptor'] for p in f.source.pages_copy()
                           if p['descriptor']['evidenceId'] in final['coverage_evidence_ids']]
            class History:
                def persist_warehouse_evidence(self, key, **kwargs): return {'id':key}
            host = WarehouseCaptureHost(store_factory=lambda:f.intake.evidence_store,driver_available=False)
            for chosen in (descriptors[:2],descriptors[1:],descriptors[:1]+descriptors[3:]):
                result = host._process_saved_pages('match',chosen,history_store=History(),
                    resolve_placements=False,identity_evidence_ids=[])
                self.assertEqual(result['coverageStatus'],'PARTIAL')
            f.saved_trace('real-once10-geometry-and-facts')
        finally:
            f.close()


def viewport(offset, *, settlement_finished=True):
    """Independent physics: crop one fixed world, advance a physical scrollbar."""
    x, y, r, b = GRID
    top, bottom = scene(0, settlement_finished=settlement_finished), scene(2)
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
    def test_hint_uses_business_domain_without_becoming_source(self):
        from warehouse_scrollbar_observation import warehouse_content_roi
        f = LiveRun(output=ROOT/'build/t1-20261012/content-hint-domain', capture_first=True)
        try:
            f.source._state, f.source._pending = 'OPEN', None
            x,y,r,b = warehouse_content_roi(1920,1080)
            crop = viewport(0)[y:b,x:r]
            h,w = crop.shape[:2]
            self.assertEqual((w,h),(600,566))
            pixels = cv2.cvtColor(crop,cv2.COLOR_BGR2BGRA).tobytes()
            raw = struct.pack('<2sIHHI',b'BM',54+len(pixels),0,0,54)
            raw += struct.pack('<IiiHHIIiiII',40,w,-h,1,32,0,len(pixels),0,0,0,0)+pixels
            path = f.root/'warehouse-sources/content-observation.bmp'
            path.parent.mkdir(exist_ok=True); path.write_bytes(raw)
            event = f.event('CONTENT_HINT',details={'sourceAuthority':False,'formalFactsQualified':False,
                'clientMap':'map','captureId':'fixture/1/2','readbackNs':round(f.now*1e9),
                'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'width':w,'height':h})
            self.assertTrue(np.array_equal(f.source.read_content_hint(event),crop))
            event['details']['height'] = 636
            self.assertIsNone(f.source.read_content_hint(event))
            self.assertEqual(f.source.pages_copy(),[])
            self.assertEqual(f.gate.representatives(),[])
            self.assertFalse(any(c['operation']=='SCROLL_DOWN' for c in f.sent))
        finally:
            f.close()

    def test_finished_layout_missing_and_no_reveal_progress_stops_with_saved_originals(self):
        f = LiveRun(output=ROOT/'build/t1-20261012/final-controls-no-progress', capture_first=True)
        try:
            f.source._host_limits['skipAnimationSupported'] = True
            for i in range(7):
                f.deliver(viewport(0, settlement_finished=False))
                if i == 6:
                    break
                self.assertEqual(f.auto._phase, 'WAIT_STABLE')
                f.tick()
            self.assertFalse(f.auto._active)
            self.assertEqual(f.auto._reason, 'SETTLEMENT_REVEAL_NO_PROGRESS')
            self.assertFalse(any(c['operation']=='SCROLL_DOWN' for c in f.sent))
            self.assertEqual(len(f.source.pages_copy()),7)
        finally:
            f.close()

    def test_skip_animation_retries_unknown_on_fresh_source_then_collects(self):
        from native_warehouse_reveal_marker import RevealMarker
        f = LiveRun(output=ROOT/'build/t1-20261012/skip-animation-python', capture_first=True)
        try:
            f.source._host_limits['skipAnimationSupported'] = True
            marker = Mock(spec=RevealMarker)
            marker.observe.return_value = {'status': 'PRESENT', 'animationState': 'UNKNOWN'}
            marker.skip_button.side_effect = [{'clickable': False}, {'clickable': True}, {'clickable': True},
                                              {'clickable': False}, {'clickable': False}]
            f.auto._marker = marker
            f.deliver(scene(0, revealing=True))
            self.assertEqual(f.auto._phase, 'WAIT_STABLE')
            f.tick()
            for outcome in ('UNKNOWN', 'SENT'):
                f.deliver(scene(0, revealing=True))
                self.assertEqual(f.auto._phase, 'WAIT_SKIP_ANIMATION')
                self.assertEqual(f.sent[-1]['operation'], 'SKIP_ANIMATION')
                old = copy.deepcopy(f.source._pending)
                ack = f.event('SKIP_ANIMATION_RESULT', old, inputActions=True,
                    reason='SKIP_ANIMATION_'+outcome, details={'classification': outcome,
                        'sendInterfaceInvoked': True, 'messageCompletedNs': round(f.now*1e9),
                        'sourceLeaseId': old['sourceLeaseId'], 'animationCompletionProven': False})
                f.auto.on_event(ack)
                self.assertEqual(f.auto._phase, 'WAIT_INITIAL')
                f.auto.on_event(ack)  # old receipt does not authorize another click
                f.auto.poll()
                self.assertTrue(f.auto._active)
                f.tick()
                self.assertEqual(f.sent[-1]['operation'], 'REQUEST_PAGE')
            f.deliver(viewport(0)); f.tick(); f.deliver(viewport(0))
            clicks = [c for c in f.sent if c['operation'] == 'SKIP_ANIMATION']
            self.assertEqual(len(clicks), 2)
            self.assertNotEqual(clicks[0]['sourceLeaseId'], clicks[1]['sourceLeaseId'])
            self.assertEqual(f.sent[-1]['operation'], 'SCROLL_DOWN')
        finally:
            f.close()

    def test_skip_animation_stable_top_continues_despite_pink_button(self):
        from native_warehouse_reveal_marker import RevealMarker
        f = LiveRun(output=ROOT/'build/t1-20261012/skip-animation-python', capture_first=True)
        try:
            f.source._host_limits['skipAnimationSupported'] = True
            marker = Mock(spec=RevealMarker)
            marker.observe.return_value = {'status': 'NOT_DETECTED', 'animationState': 'UNKNOWN'}
            marker.skip_button.return_value = {'clickable': True, 'pinkFraction': .86}
            f.auto._marker = marker
            f.deliver(viewport(0, settlement_finished=False))
            command = copy.deepcopy(f.source._pending)
            f.auto.on_event(f.event('SKIP_ANIMATION_RESULT', command, inputActions=True,
                reason='SKIP_ANIMATION_SENT', details={'classification': 'SENT',
                    'sendInterfaceInvoked': True, 'messageCompletedNs': round(f.now*1e9),
                    'sourceLeaseId': command['sourceLeaseId'], 'animationCompletionProven': False}))
            f.tick(); f.deliver(viewport(0, settlement_finished=False))
            self.assertEqual(f.auto._phase, 'WAIT_SKIP_ANIMATION')
            self.assertFalse(any(c['operation']=='SCROLL_DOWN' for c in f.sent))
            command = copy.deepcopy(f.source._pending)
            f.auto.on_event(f.event('SKIP_ANIMATION_RESULT', command, inputActions=True,
                reason='SKIP_ANIMATION_SENT', details={'classification':'SENT',
                    'sendInterfaceInvoked':True, 'messageCompletedNs':round(f.now*1e9),
                    'sourceLeaseId':command['sourceLeaseId'], 'animationCompletionProven':False}))
            f.tick(); f.deliver(viewport(0))
            self.assertEqual(f.auto._phase, 'WAIT_STABLE')
            supported = f.source.pages_copy()[-1]['descriptor']['evidenceId']
            self.assertIn(supported, f.gate.representatives())
            changed = viewport(0)
            changed[GRID[1]+70, GRID[0]+80] = (35, 200, 60)
            f.tick(); f.deliver(changed)
            self.assertIn(supported, f.gate.representatives())
            self.assertFalse(f.auto._observation['contentStability']['qualified'])
            self.assertNotIn(f.source.pages_copy()[-1]['descriptor']['evidenceId'], f.gate.representatives())
            self.assertEqual(sum(c['operation'] == 'SKIP_ANIMATION' for c in f.sent), 2)
            self.assertEqual(f.sent[-1]['operation'], 'SCROLL_DOWN')
        finally:
            f.close()

    def test_skip_animation_receipt_cannot_cross_match_or_claim_completion(self):
        from native_warehouse_reveal_marker import RevealMarker
        f = LiveRun(output=ROOT/'build/t1-20261012/skip-animation-python', capture_first=True)
        try:
            f.source._host_limits['skipAnimationSupported'] = True
            marker = Mock(spec=RevealMarker)
            marker.observe.return_value = {'status': 'PRESENT', 'animationState': 'UNKNOWN'}
            marker.skip_button.side_effect = [{'clickable': False}, {'clickable': True}]
            f.auto._marker = marker
            f.deliver(scene(0, revealing=True))
            self.assertEqual(f.auto._phase, 'WAIT_STABLE')
            f.tick()
            f.deliver(scene(0, revealing=True))
            self.assertEqual(f.sent[-1]['operation'], 'SKIP_ANIMATION')
            command = copy.deepcopy(f.source._pending)
            ack = f.event('SKIP_ANIMATION_RESULT', command, inputActions=True,
                reason='SKIP_ANIMATION_SENT', details={'classification': 'SENT',
                    'sendInterfaceInvoked': True, 'messageCompletedNs': round(f.now*1e9),
                    'sourceLeaseId': command['sourceLeaseId'], 'animationCompletionProven': False})
            ack['matchGeneration'] = 2
            f.auto.on_event(ack)
            self.assertEqual(f.source.source_session_snapshot()['state'], 'SKIP_PENDING')
            ack['matchGeneration'] = 1
            ack['details']['animationCompletionProven'] = True
            f.auto.on_event(ack)
            self.assertFalse(f.auto._active)
            self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 0)
        finally:
            f.close()

    def test_capture_first_content_changes_and_missing_overlap_do_not_block_collection(self):
        f = LiveRun(output=ROOT / 'build/t1-20261012/capture-first-python', capture_first=True)
        self.addCleanup(f.close)
        first = viewport(0)
        changed = first.copy()
        x, y, r, b = GRID
        changed[y+65:y+90, x+80:x+105] = (230, 50, 140)
        f.deliver(first); f.tick(); f.deliver(changed)
        self.assertEqual(f.auto._phase, 'WAIT_SCROLL')
        self.assertFalse(f.auto._observation['contentStability']['qualified'])
        self.assertEqual(f.gate.representatives(), [])  # no invented content certificate
        f.scroll_ack(); f.tick()
        moved = viewport(180)
        moved[y:b, x:r] = np.roll(moved[y:b, x:r], 25, axis=1)
        f.deliver(moved)
        self.assertEqual(f.auto._phase, 'WAIT_STABLE')
        overlap = next(p for p in reversed(f.logs) if p['kind'] == 'image-overlap')['alignment']
        self.assertNotEqual(overlap['status'], 'VERIFIED')
        f.tick(); f.deliver(moved.copy())
        self.assertEqual(f.auto._phase, 'WAIT_SCROLL')
        self.assertEqual(len(f.intake.pages_copy()), 4)
        self.assertTrue(f.auto._coverage_pending)
        f.scope['matchGeneration'] = 2
        f.auto.presentation_payload()
        self.assertFalse(f.auto._active)
        self.assertEqual(f.auto._reason, 'SOURCE_SCOPE_CHANGED')
        self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
        f.saved_trace('capture-despite-unmatched-content')

    def test_top_placeholders_wait_without_button_then_middle_keeps_collecting(self):
        f = LiveRun(output=ROOT/'build/t1-20261012/top-reveal-flow', capture_first=True)
        try:
            # A missing skip control must not lose visibly unrevealed TOP items.
            f.deliver(scene(0, revealing=True)); f.tick(); f.deliver(scene(0, revealing=True))
            self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 0)
            self.assertEqual(len(f.source.pages_copy()), 2)
            f.tick(); f.deliver(scene(0, revealing=True))
            self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 0)
            # First filled image becomes the anchor; another independent image
            # is required. Waiting itself never grants a page certificate.
            f.tick(); f.deliver(scene(0))
            self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 0)
            f.tick(); f.deliver(scene(0))
            self.assertEqual(f.sent[-1]['operation'], 'SCROLL_DOWN')
            f.scroll_ack(); f.tick(); f.deliver(scene(1, revealing=True))
            f.tick(); f.deliver(scene(1, revealing=True))
            self.assertEqual(f.sent[-1]['operation'], 'SCROLL_DOWN')
            self.assertTrue(f.auto._active)
            self.assertFalse(any(p['kind'] == 'bottom-collected' for p in f.logs))
        finally:
            f.close()

    def test_capture_first_bottom_microchanges_finish_but_middle_noop_is_bounded(self):
        for bottom in (True, False):
            f = LiveRun(output=ROOT / 'build/t1-20261012/capture-first-python', capture_first=True)
            try:
                def pair(frame):
                    f.deliver(frame); f.tick(); f.deliver(frame.copy())
                pair(viewport(0))
                f.scroll_ack(); f.tick(); pair(viewport(360 if bottom else 180))
                if bottom:
                    f.scroll_ack(); f.tick()
                    frame = viewport(360)
                    frame[GRID[1]+80:GRID[1]+110, GRID[0]+100:GRID[0]+130] = (60, 80, 120)
                    f.deliver(frame)
                    self.assertTrue(f.auto._tail_stationary)
                    f.tick(); f.deliver(frame.copy())
                    self.assertFalse(f.auto._active)
                    self.assertTrue(any(p['kind'] == 'bottom-collected' for p in f.logs))
                    # A skipped synthetic section was intentionally not proven;
                    # physical bottom never fabricates continuous pixel coverage.
                    self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
                else:
                    for attempt in range(3):
                        f.scroll_ack(); f.tick(); f.deliver(viewport(180))
                        if attempt < 2:
                            f.tick(); f.deliver(viewport(180))
                            self.assertEqual(f.auto._phase, 'WAIT_SCROLL')
                    self.assertFalse(f.auto._active)
                    self.assertEqual(f.auto._reason, 'WINDOW_SCROLL_NO_PROGRESS')
                    self.assertFalse(any(p['kind'] == 'bottom-collected' for p in f.logs))
                    self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
                f.saved_trace('capture-first-bottom' if bottom else 'capture-first-noop')
            finally:
                f.close()

    def test_capture_first_step_stays_inside_retained_content_bands(self):
        """A half-viewport wheel must not be sent when the anchor cannot retain it.

        The saved 2026-10-20 settlement anchor still shows the last item row.
        Its retention limit is below the 280px half-viewport prediction, and a
        271px shift of that same anchor does not verify. The wheel that
        production sends has to stay inside the limit the anchor actually has.
        """
        from warehouse_scrollbar_observation import WarehouseScrollbarObserver
        from warehouse_segment_overlap import content_retention_limit

        def assert_capped(auto, anchor, observation, unit):
            limit = content_retention_limit(anchor)
            self.assertIsInstance(limit, (int, float))
            self.assertGreater(limit, 0)
            visible = observation['trackBox'][3] - observation['trackBox'][1]
            half = 0.5 * visible
            self.assertLess(limit, half)
            auto._anchor = anchor
            auto._observation = observation
            auto._pixels_per_notch = unit
            uncapped = -120 * max(1, min(12, int(half / unit)))
            delta = auto._scroll_delta()
            predicted = abs(delta) / 120 * unit
            self.assertLess(delta, 0)
            self.assertEqual(delta % 120, 0)
            self.assertGreater(abs(uncapped), abs(delta))
            if limit >= unit:
                self.assertLessEqual(predicted, limit)
            else:
                self.assertEqual(delta, -120)
            again = auto._scroll_delta()
            self.assertEqual(again, delta)

        f = LiveRun(output=ROOT / 'build/t1-20261012/capture-first-retention', capture_first=True)
        self.addCleanup(f.close)
        anchor = np.zeros((636, 600, 3), np.uint8)
        anchor[:] = (18, 22, 20)
        rng = np.random.default_rng(4)
        for index, y0 in enumerate((6, 44, 82, 120, 158)):
            patch = np.zeros((32, 90, 3), np.uint8)
            patch[:, :, index % 3] = 220
            patch += rng.integers(0, 35, patch.shape, dtype=np.uint8)
            anchor[y0:y0 + 32, 70:160] = np.clip(patch, 0, 255)
        observation = {
            'trackBox': [580, 10, 596, 570],
            'thumbBox': [580, 40, 596, 160],
            'scrollState': 'MIDDLE',
        }
        assert_capped(f.auto, anchor, observation, 30)
        saved = (ROOT / 'build/goal-20261019-b/match-1/runtime-data/native-live-trial'
                 / 'evidence/settlement_v2/blobs/9d'
                 / '9d84fb8b4955bd42abb52e9c0d11551a59f61d0d8e1a50a3e996d57da5ad582c.png')
        if not saved.is_file():
            return
        frame = cv2.imdecode(np.frombuffer(saved.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        x, y, r, b = warehouse_search_roi(1920, 1080)
        crop = frame[y:b, x:r]
        observed = WarehouseScrollbarObserver().observe(frame, source_id='goal-20261019-b-page4')
        self.assertEqual(observed['scrollState'], 'MIDDLE')
        assert_capped(f.auto, crop, observed, 271 / 9)
        shifted = crop.copy()
        content_h, content_w = int(crop.shape[0] * 0.88), int(crop.shape[1] * 0.88)
        band = crop[:content_h, :content_w]
        moved = np.zeros_like(band)
        shift = 271
        moved[:-shift] = band[shift:]
        moved[-shift:] = band[-1]
        shifted[:content_h, :content_w] = moved
        unverified = align_warehouse_segments(crop, shifted, required_direction='DOWN', prev_id='p4', next_id='jump')
        self.assertNotEqual(unverified['status'], 'VERIFIED', unverified)

    def test_capture_first_empty_page_repeats_one_notch(self):
        """No localizable band cannot be given a half-viewport wheel.

        The 2026-10-20 empty tail sent -1080. The thumb moved as far as the
        270px content calibration while the grid moved about 45px, so the
        pair is not a continuity proof. One notch stays inside the smaller
        calibration and is allowed to repeat.
        """
        from native_capture_delivery import DELIVERY
        from tests.test_native_sparse_overlap import sparse_world
        from warehouse_segment_overlap import content_retention_limit
        anchor = sparse_world(400)
        self.assertIsNone(content_retention_limit(anchor))
        f = LiveRun(output=ROOT / 'build/t1-20261012/capture-first-empty-notch', capture_first=True)
        self.addCleanup(f.close)
        f.auto._retry_scope = {'capturePolicy': DELIVERY}
        f.auto._anchor = anchor
        f.auto._observation = {
            'trackBox': [569, 0, 575, 560],
            'thumbBox': [569, 127, 575, 346],
            'scrollState': 'MIDDLE',
        }
        f.auto._pixels_per_notch = 30
        self.assertTrue(f.auto._collect_first())
        self.assertEqual(f.auto._scroll_delta(), -120)
        self.assertEqual(f.auto._scroll_delta(), -120)

    def test_capture_first_zero_retention_repeats_one_notch(self):
        """A top-edge-only icon reports retention 0 and must not take a half viewport.

        Match-4 page 36 returned 0. The following -840 wheel moved the thumb
        79px and the pixels about 41px, then the ledger stayed incomplete.
        """
        from native_capture_delivery import DELIVERY
        from warehouse_segment_overlap import content_retention_limit
        anchor = np.full((636, 600, 3), (18, 16, 14), np.uint8)
        rng = np.random.RandomState(7)
        anchor[0:36, 40:88] = rng.randint(80, 230, (36, 48, 3), np.uint8)
        self.assertEqual(content_retention_limit(anchor), 0)
        f = LiveRun(output=ROOT / 'build/t1-20261012/capture-first-zero-notch', capture_first=True)
        self.addCleanup(f.close)
        f.auto._retry_scope = {'capturePolicy': DELIVERY}
        f.auto._anchor = anchor
        f.auto._observation = {
            'trackBox': [569, 0, 575, 560],
            'thumbBox': [569, 251, 575, 469],
            'scrollState': 'MIDDLE',
        }
        f.auto._pixels_per_notch = 30
        self.assertTrue(f.auto._collect_first())
        self.assertEqual(f.auto._scroll_delta(), -120)
        self.assertEqual(f.auto._scroll_delta(), -120)

    def test_match4_zero_limit_pair_is_not_a_certified_skip(self):
        """The real -840 pair stays unverified, and the same anchor now steps one notch."""
        before = (ROOT / 'build/goal-20261019-b/match-4/runtime-data/native-live-trial'
                  / 'evidence/settlement_v2/blobs/d5'
                  / 'd51fe9bcd5681908e3108364c5f294d85b43f194933eadcdd27ad747fd8ba027.png')
        after = (ROOT / 'build/goal-20261019-b/match-4/runtime-data/native-live-trial'
                 / 'evidence/settlement_v2/blobs/05'
                 / '058954acd090becbb5f3618161939efd863c9b42de5afbb98d616101e6481177.png')
        if not before.is_file() or not after.is_file():
            return
        from native_capture_delivery import DELIVERY
        from warehouse_scrollbar_observation import WarehouseScrollbarObserver
        from warehouse_segment_overlap import content_retention_limit
        x, y, r, b = warehouse_search_roi(1920, 1080)
        frame_a = cv2.imdecode(np.frombuffer(before.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        frame_b = cv2.imdecode(np.frombuffer(after.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        crop_a, crop_b = frame_a[y:b, x:r], frame_b[y:b, x:r]
        self.assertEqual(content_retention_limit(crop_a), 0)
        observed = WarehouseScrollbarObserver().observe(frame_a, source_id='match4-36')
        self.assertEqual(observed['scrollState'], 'MIDDLE')
        motion = align_warehouse_segments(crop_a, crop_b, prev_id='36', next_id='37',
            required_direction='DOWN')
        self.assertNotEqual(motion['status'], 'VERIFIED', motion)
        self.assertNotEqual(motion.get('verticalOffsetPx'), -271)
        f = LiveRun(output=ROOT / 'build/t1-20261012/capture-first-match4-zero', capture_first=True)
        self.addCleanup(f.close)
        f.auto._retry_scope = {'capturePolicy': DELIVERY}
        f.auto._anchor = crop_a
        f.auto._observation = observed
        f.auto._pixels_per_notch = 30
        self.assertEqual(f.auto._scroll_delta(), -120)
        self.assertEqual(f.auto._scroll_delta(), -120)

    def test_empty_tail_large_thumb_step_is_not_continuity(self):
        """Match-3 crops 19→20 are a real -1080 whose pixels moved about 45px.

        Certifying that pair as the calibrated -271px content step would
        record a skipped viewport that the originals do not contain.
        """
        evidence = (ROOT / 'build/goal-20261019-b/match-3/runtime-data/native-live-trial'
                    / 'evidence/settlement_v2/index/replayfile_d574151acb169b0a1b9d.json')
        if not evidence.is_file():
            return
        from warehouse_scrollbar_observation import WarehouseScrollbarObserver
        from warehouse_segment_overlap import TerminalContinuity, content_retention_limit
        payload = json.loads(evidence.read_text(encoding='utf-8'))
        trial = evidence.parents[3]
        x, y, r, b = warehouse_search_roi(1920, 1080)
        frames, crops = [], []
        for item in payload['items']:
            frame = cv2.imdecode(np.frombuffer((trial / item['relativePath']).read_bytes(), np.uint8),
                                 cv2.IMREAD_COLOR)
            frames.append(frame)
            crops.append(frame[y:b, x:r])
        self.assertIsNone(content_retention_limit(crops[19]))
        observed = WarehouseScrollbarObserver().observe(frames[19], source_id='match3-19')
        self.assertEqual(observed['scrollState'], 'MIDDLE')
        context = TerminalContinuity()
        for left, right, offset in ((15, 16, -270), (17, 18, -30)):
            calibrated = align_warehouse_segments(crops[left], crops[right], prev_id=str(left),
                next_id=str(right), required_direction='DOWN', terminal_continuity=context)
            self.assertEqual(calibrated['status'], 'VERIFIED', calibrated)
            self.assertEqual(calibrated['verticalOffsetPx'], offset)
        empty = align_warehouse_segments(crops[19], crops[20], prev_id='19', next_id='20',
            required_direction='DOWN', terminal_continuity=context)
        self.assertNotEqual(empty['status'], 'VERIFIED', empty)
        self.assertNotEqual(empty.get('verticalOffsetPx'), -271)
        skipped = align_warehouse_segments(crops[19], crops[22], prev_id='19', next_id='22',
            required_direction='DOWN', terminal_continuity=context)
        self.assertNotEqual(skipped['status'], 'VERIFIED', skipped)

    def test_stationary_bottom_jitter_is_not_a_coverage_hole(self):
        """A one-pixel thumb move with the same pixels is not a skipped view."""
        f = LiveRun(output=ROOT / 'build/t1-20261012/capture-first-stationary', capture_first=True)
        self.addCleanup(f.close)

        def pair(frame):
            f.deliver(frame)
            f.tick()
            f.deliver(frame.copy())

        pair(viewport(0))
        f.scroll_ack()
        f.tick()
        pair(viewport(180))
        self.assertEqual(f.auto._phase, 'WAIT_SCROLL', f.logs[-2:])
        self.assertFalse(f.auto._coverage_pending)
        base = viewport(180)
        jitter = base.copy()
        jitter[214:776, 1882:1894] = 45
        thumb = 214 + round(362 * 180 / 360) + 1
        jitter[thumb:thumb + 200, 1882:1894] = 210
        f.scroll_ack()
        f.tick()
        f.deliver(jitter)
        overlap = next(p for p in reversed(f.logs) if p['kind'] == 'image-overlap')['alignment']
        self.assertEqual(overlap['reason'], 'NO_MOVEMENT', overlap)
        self.assertFalse(f.auto._coverage_pending, f.auto._coverage_pending)

    @unittest.skipUnless(os.environ.get('YH_T1_CAPTURE_ROOT'), 'private T1 SOURCE opt-in')
    def test_capture_first_real_sparse_page_keeps_useful_step(self):
        root = Path(os.environ['YH_T1_CAPTURE_ROOT'])
        manifest = json.loads(next((root / 'warehouse-intake').glob('*.json')).read_text(encoding='utf-8'))
        self.assertEqual(manifest['scope']['recordStableKey'], 'replayfile_8ab2b18128ffceaba0e5')
        src = manifest['pages'][-1]['nativeSource']
        raw = (root / src['relativePath']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), src['sha256'])
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        from warehouse_scrollbar_observation import WarehouseScrollbarObserver
        from warehouse_segment_overlap import content_retention_limit
        x, y, r, b = warehouse_search_roi(1920, 1080)
        crop = frame[y:b, x:r]
        self.assertEqual(content_retention_limit(crop), 0)
        for capture_first in (False, True):
            f = LiveRun(output=ROOT / 'build/t1-20261012/capture-first-python', capture_first=capture_first)
            try:
                if capture_first:
                    from native_capture_delivery import DELIVERY
                    f.auto._retry_scope = {'capturePolicy': DELIVERY}
                f.auto._anchor = crop
                f.auto._observation = WarehouseScrollbarObserver().observe(frame, source_id='real-last')
                self.assertEqual(f.auto._observation['scrollState'], 'MIDDLE')
                f.auto._pixels_per_notch = 30  # measured real -120 receipt and -30px correspondence
                steps = [f.auto._scroll_delta(), f.auto._scroll_delta()]
                if capture_first:
                    # Limit 0 used to keep a half-viewport wheel. Match-4 showed
                    # that wheel is not a certifiable content step, so capture-first
                    # now repeats one notch instead of stalling or jumping.
                    self.assertEqual(steps, [-120, -120], steps)
                else:
                    self.assertEqual(steps, [-120, 0])  # preserved actual old stop cause
            finally:
                f.close()

    def test_not_sent_expired_support_rechecks_without_resending_old_scroll(self):
        for invoked in (False, True):
            f = LiveRun(output=ROOT / 'build/t1-20261012/support-expiry-python')
            try:
                frame = viewport(0)
                f.deliver(frame); f.tick(); f.deliver(frame.copy())
                old = copy.deepcopy(f.source._pending)
                self.assertEqual(old['operation'], 'SCROLL_DOWN')
                deadline = f.auto._deadline
                event = f.event('REJECTED', old, reason='SCROLL_SUPPORT_EXPIRED_BEFORE_SEND', details={
                    'classification': 'NOT_SENT_CONTENT_SUPPORT_RECHECK', 'sendInterfaceInvoked': invoked,
                    'sourceLeaseId': old['sourceLeaseId'], 'failedChecks': ['deliveryProofQualified'],
                    'supportFailure': 'DELIVERY_LOCAL_USE_EXPIRED'})
                f.auto.on_event(event)
                # Production status reads repeat the OPEN operation reason
                # before the scheduled independent SOURCE request owns it.
                f.auto.presentation_payload()
                f.auto.on_event(copy.deepcopy(event))
                self.assertEqual(f.auto._active, not invoked)
                if not invoked:
                    self.assertEqual(f.auto._phase, 'WAIT_STABLE')
                    self.assertEqual(f.source.source_session_snapshot()['state'], 'OPEN')
                    self.assertEqual(f.finalizations, [])
                    x, y, r, b = warehouse_search_roi(1920, 1080)
                    with patch('native_warehouse_visible_content_gate.time.perf_counter_ns',
                            side_effect=lambda: round(f.now * 1e9)):
                        for i in (1, 2):
                            f.now += .65
                            f.gate.sampling_hint(frame[y:b, x:r], capture_id=f'expiry-hint/{i}',
                                readback_ns=round(f.now * 1e9))
                        f.auto.poll()
                    self.assertEqual(f.sent[-1]['operation'], 'REQUEST_PAGE')
                self.assertEqual(f.auto._deadline, deadline)
                self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 1)
            finally:
                f.close()

    def test_request_thirty_three_after_seventy_seconds_keeps_scope_guard(self):
        f = LiveRun(output=OUT / 'coverage-driven')
        try:
            # The Host's active scene owns the lifetime; no elapsed-time or count quota.
            f.source._deadline = f.auto._deadline = (2**63 - 1) / 1e9
            f.source._pending = None
            f.source._state = 'OPEN'
            f.source._ordinal = 32
            f.now = 180.
            self.assertTrue(f.auto._guard())
            self.assertTrue(f.source.capture_manual_page()['ok'])
            self.assertEqual(f.sent[-1]['requestOrdinal'], 33)
            self.assertEqual(f.sent[-1]['operation'], 'REQUEST_PAGE')
            f.scope['matchGeneration'] = 2
            self.assertFalse(f.auto._guard())
            self.assertFalse(f.auto._active)
        finally:
            f.close()

    def test_second_scroll_failure_after_verified_move_is_bounded(self):
        # Synthetic viewport physics checks scheduling, not real-game accuracy.
        # Receipt semantics are independently pinned to the Host contract.
        receipts = json.loads(PRESEND_RECEIPTS.read_text(encoding='utf-8'))
        sent_receipt = json.loads((ROOT / 'tests/fixtures/native_adapter_postsend_receipt.json').read_text(encoding='utf-8'))
        for kind in ('before-target', 'before-send', 'post-send', 'send-unknown', 'send-exception', 'user-stop',
                'sent-moved', 'sent-stationary', 'sent-timeout', 'sent-cross-match', 'sent-stop'):
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
                        receipt = sent_receipt if kind.startswith('sent-') else receipts[kind]
                        details = copy.deepcopy(receipt.get('details'))
                        if details and 'sourceLeaseId' in details:
                            details['sourceLeaseId'] = command['sourceLeaseId']
                        if kind.startswith('sent-'):
                            # Separate inert clocks and synthetic wheel sizing;
                            # preserve the C# send/qualification semantics.
                            details['messageCompletedNs'] = round(f.now * 1e9)
                            details['delta'] = command['wheelDelta']
                        event = f.event(receipt['event'], command, reason=receipt['reason'], details=details,
                            inputActions=kind.startswith('sent-'))
                    f.auto.on_event(event)
                    f.auto.on_event(copy.deepcopy(event))
                    for _ in range(3):
                        f.auto.poll()
                    safe = kind in ('before-target', 'before-send')
                    self.assertEqual(f.auto._active, safe or kind.startswith('sent-'))
                    self.assertEqual(f.auto._deadline, deadline)
                    self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 2)
                    self.assertFalse(f.auto._post_scroll_frame_received)
                    if kind.startswith('sent-'):
                        self.assertTrue(f.auto._active)
                        self.assertEqual(f.auto._phase, 'WAIT_MOVED')
                        self.assertEqual(f.finalizations, [])
                        if kind == 'sent-timeout':
                            f.now = deadline; f.auto.poll()
                        elif kind == 'sent-stop':
                            f.auto.stop()
                        elif kind == 'sent-cross-match':
                            stale = copy.deepcopy(event); stale['matchGeneration'] += 1
                            f.auto.on_event(stale)
                            self.assertEqual(f.auto._phase, 'WAIT_MOVED')
                            f.now = deadline; f.auto.poll()
                        else:
                            f.tick()
                            self.assertEqual(f.sent[-1]['operation'], 'REQUEST_PAGE')
                            self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 2)
                            f.deliver(viewport(180 if kind == 'sent-moved' else 90))
                            if kind == 'sent-moved':
                                self.assertEqual(f.auto._phase, 'WAIT_STABLE')
                                self.assertEqual(f.finalizations, [])
                                overlap = next(e['alignment'] for e in reversed(f.logs) if e['kind'] == 'image-overlap')
                                self.assertEqual(overlap['status'], 'VERIFIED')
                                self.assertTrue(f.auto._post_scroll_frame_received)
                                self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 2)
                                f.auto.stop()
                            else:
                                self.assertEqual(f.auto._reason, 'WINDOW_SCROLL_NO_PROGRESS')
                        self.assertFalse(f.auto._active)
                        self.assertEqual(len(f.finalizations), 1)
                        self.assertNotEqual(f.finalizations[0]['termination_reason'], 'COMPLETE')
                        continue
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


@unittest.skipUnless(os.environ.get('YIHUAN_REAL_SOURCE_QA') == '1', 'retained SOURCE opt-in')
class RecentRealTerminalContinuityQATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store = Path(os.environ.get('YIHUAN_RECENT_SOURCE_ROOT',
            str(ROOT/'build/t1-20261012/real-once-08/runtime-data/native-live-trial')))
        manifest = next((store/'warehouse-intake').glob('*.json'))
        pages = json.loads(manifest.read_text(encoding='utf-8'))['pages']
        cls.crops, cls.frames = {}, {}
        x,y,r,b = warehouse_search_roi(1920,1080)
        for n in range(1,33):
            source = pages[n-1]['nativeSource']; raw = (store/source['relativePath']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != source['sha256']:
                raise AssertionError('Retained original changed')
            cls.frames[n] = cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            cls.crops[n] = cls.frames[n][y:b,x:r].copy()

    def test_real_final_layout_and_footer_changes_are_distinct_from_reveal(self):
        from scene_anchors import settlement_controls_visible
        from native_warehouse_content_stability import content_stability
        from warehouse_scrollbar_observation import warehouse_content_roi
        self.assertTrue(all(not settlement_controls_visible(self.frames[n]) for n in range(1,22)))
        self.assertTrue(all(settlement_controls_visible(self.frames[n]) for n in range(22,33)))
        x,y,r,b = warehouse_content_roi(1920,1080)
        for i,j in ((29,30),(31,32)):
            self.assertTrue(content_stability(self.frames[i][y:b,x:r],self.frames[j][y:b,x:r])['qualified'])
        self.assertFalse(content_stability(self.frames[21][y:b,x:r],self.frames[22][y:b,x:r])['qualified'])
        for px,py in ((1388,279),(1334,230),(1848,745),(1350,775),(1887,440)):
            changed = self.frames[24].copy(); changed[py,px] ^= 16
            self.assertFalse(content_stability(self.frames[24][y:b,x:r],changed[y:b,x:r])['qualified'])

    def test_real_top_visible_support_does_not_leave_while_hidden_items_reveal(self):
        f = LiveRun(output=ROOT/'build/t1-20261012/real-initial-layout-replay', capture_first=True)
        try:
            f.source._host_limits['skipAnimationSupported'] = True
            for n in range(1,21):
                f.deliver(self.frames[n])
                self.assertTrue(f.auto._active, (n,f.auto._reason))
                self.assertFalse(any(c['operation']=='SCROLL_DOWN' for c in f.sent))
                command = copy.deepcopy(f.source._pending)
                self.assertEqual(command['operation'],'SKIP_ANIMATION')
                f.auto.on_event(f.event('SKIP_ANIMATION_RESULT',command,inputActions=True,
                    reason='SKIP_ANIMATION_SENT',details={'classification':'SENT',
                        'sendInterfaceInvoked':True,'messageCompletedNs':round(f.now*1e9),
                        'sourceLeaseId':command['sourceLeaseId'],'animationCompletionProven':False}))
                f.tick()
            self.assertGreater(len(f.gate.representatives()),0)
        finally:
            f.close()

    def test_real_tail_runs_through_fresh_support_and_bottom_probe(self):
        # Re-enter at the already recorded second scroll; this tests the tail
        # state machine, not a reconstruction of the earlier unrevealed TOP.
        from warehouse_scrollbar_observation import WarehouseScrollbarObserver
        f = LiveRun(output=ROOT/'build/t1-20261012/real-tail-flow', capture_first=True)
        try:
            context = TerminalContinuity()
            self.match(self.crops[20],self.crops[21],context,20,21)
            f.auto._terminal_continuity = context
            f.auto._scroll_count = 2
            f.auto._last_wheel_delta = -1080
            f.auto._phase = 'WAIT_MOVED'
            f.auto._anchor = self.crops[22].copy()
            f.auto._observation = WarehouseScrollbarObserver().observe(self.frames[22],source_id='seed-22')
            f.deliver(self.frames[23]); f.tick(); f.deliver(self.frames[24])
            self.assertEqual(f.auto._phase,'WAIT_SCROLL')
            for i,j in ((25,26),(27,28),(29,30),(31,32)):
                f.scroll_ack(); f.tick(); f.deliver(self.frames[i])
                self.assertTrue(f.auto._active,(i,f.auto._reason))
                f.tick(); f.deliver(self.frames[j])
                if j < 32:
                    self.assertEqual(f.auto._phase,'WAIT_SCROLL',(j,f.auto._reason))
            self.assertFalse(f.auto._active)
            self.assertEqual(f.auto._reason,'COMPLETE')
            motions=[e['alignment']['verticalOffsetPx'] for e in f.logs if e['kind']=='image-overlap']
            self.assertEqual(motions,[-271,-271,-30,-5])
            self.assertTrue(any(e['kind']=='bottom-collected' and e['bottomConfirmed'] for e in f.logs))
            self.assertEqual(len(f.gate.representatives()),5)
            f.saved_trace('real-tail')
        finally:
            f.close()

    def calibrated(self):
        context = TerminalContinuity()
        for i,j,offset in ((20,21,-270),(22,23,-271)):
            result = self.match(self.crops[i],self.crops[j],context,i,j)
            self.assertEqual(result['status'],'VERIFIED',result)
            self.assertEqual(result['verticalOffsetPx'],offset)
        return context

    @staticmethod
    def match(a,b,context,i=24,j=25):
        return align_warehouse_segments(a,b,prev_id=str(i),next_id=str(j),
            required_direction='DOWN',terminal_continuity=context)

    def test_connected_empty_tail_and_small_final_motion(self):
        context = self.calibrated()
        for i,j,offset in ((24,25,-271),(26,27,-30),(28,29,-5)):
            result = self.match(self.crops[i],self.crops[j],context,i,j)
            self.assertEqual(result['status'],'VERIFIED',result)
            self.assertEqual(result['verticalOffsetPx'],offset)
            self.assertFalse(result['bottomConfirmed'])
        self.assertNotEqual(self.match(self.crops[24],self.crops[25],TerminalContinuity())['status'],'VERIFIED')

    def test_grid_alias_skipped_view_and_stationary_thumb_noise_are_rejected(self):
        a,b = self.crops[24],self.crops[25]
        false_bottom = b.copy();false_bottom[:,565:580] = a[:,565:580]
        phase = b.copy();phase[:559,:562] = np.roll(b[:559,:562],-28,axis=0)
        drift = b.copy();drift[:559,:562] = np.roll(b[:559,:562],25,axis=1)
        occupied = b.copy();occupied[120:230,60:170] = (45,160,215)
        for label,before,after in [('false-bottom',a,false_bottom),('wrong-phase',a,phase),
                ('horizontal-drift',a,drift),('new-occupied-tail',a,occupied),
                ('skipped-real-view',self.crops[22],b)]:
            with self.subTest(label=label):
                self.assertNotEqual(self.match(before,after,self.calibrated())['status'],'VERIFIED')
        context = self.calibrated()
        self.match(a,b,context)
        self.match(self.crops[26],self.crops[27],context,26,27)
        stationary = self.crops[28].copy()
        stationary[:,565:580] = self.crops[29][:,565:580]
        self.assertNotEqual(self.match(self.crops[28],stationary,context,28,29)['status'],'VERIFIED')


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
