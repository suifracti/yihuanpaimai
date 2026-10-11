"""Sampling predictions retain content; they never certify coverage."""
import hashlib
import json
import os
from pathlib import Path
import unittest
import zipfile

import cv2
import numpy as np

from tests.test_native_half_viewport_flow import LiveRun, viewport, ROOT
from tests.test_native_sparse_overlap import sparse_world
from warehouse_scrollbar_observation import warehouse_search_roi
from warehouse_segment_overlap import align_warehouse_segments, content_retention_limit


def sparse_frame(offset):
    frame = viewport(offset)
    x, y, r, b = warehouse_search_roi(1920, 1080)
    original = frame[y:b, x:r].copy()
    frame[y:b, x:r] = sparse_world(offset)
    frame[y:b, x+562:r] = original[:, 562:]
    return frame


class ContentStepBudgetTests(unittest.TestCase):
    def test_blank_tail_and_periodic_grid_never_supply_content_authority(self):
        a, b = sparse_world(400), sparse_world(456)
        self.assertIsNone(content_retention_limit(a))
        self.assertIsNone(content_retention_limit(b))
        self.assertNotEqual(align_warehouse_segments(a, b, required_direction='DOWN')['status'], 'VERIFIED')

    def test_minimum_notch_cannot_destroy_last_two_content_bands(self):
        f = LiveRun(output=ROOT / 'build/issue42-evidence/minimum-notch')
        try:
            frame = sparse_frame(0)
            f.deliver(frame); f.tick(); f.deliver(frame.copy())
            f.scroll_ack(); f.tick(); f.deliver(sparse_frame(300))
            f.tick(); f.deliver(sparse_frame(300))
            self.assertFalse(f.auto._active)
            self.assertEqual(f.auto._reason, 'SCROLL_CONTENT_RETENTION_UNPROVEN')
            self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 1)
            self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
        finally:
            f.close()

    def test_next_sent_request_retains_sparse_content_and_needs_fresh_proof(self):
        f = LiveRun(output=ROOT / 'build/issue42-evidence/synthetic-flow')
        try:
            top = sparse_frame(0)
            f.deliver(top); f.tick(); f.deliver(top.copy())
            f.scroll_ack(); f.tick(); f.deliver(sparse_frame(180))
            f.tick(); f.deliver(sparse_frame(180))
            self.assertEqual(f.auto._phase, 'WAIT_SCROLL', f.logs[-3:])
            delta = f.sent[-1]['wheelDelta']
            # This independent world leaves artwork only in rows 0..169.
            # A prediction beyond that cannot retain its visual anchors.
            self.assertLess(abs(delta) / 120 * f.auto._pixels_per_notch, 170)
            self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 2)
            self.assertEqual(f.finalizations, [])
            deadline = f.auto._deadline
            f.now = deadline; f.auto.poll()
            self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
        finally:
            f.close()

    @unittest.skipUnless(os.environ.get('YH_ONCE14_ZIP'), 'private once14 evidence opt-in')
    def test_real_originals_and_sent_vs_not_sent_then_safe_next_sampling(self):
        package = Path(os.environ['YH_ONCE14_ZIP'])
        self.assertEqual(package.stat().st_size, 45320619)
        self.assertEqual(hashlib.sha256(package.read_bytes()).hexdigest(),
            'c9a015922dc1a8cfd2635dbbee418811d5bcbb3cc6bdcdc35a54392dbb821d59')
        frames = []
        with zipfile.ZipFile(package) as z:
            self.assertIsNone(z.testzip())
            rows = [json.loads(l) for l in z.read(next(n for n in z.namelist()
                if n.endswith('/acceptance-events.jsonl'))).decode().splitlines()]
            pages = [e['diagnostic']['page'] for e in rows if e['kind'] == 'original-saved']
            self.assertEqual(len(pages), 12)
            originals = {hashlib.sha256(z.read(n)).hexdigest(): z.read(n)
                for n in z.namelist() if '/warehouse-sources/' in n and n.endswith('.bmp')}
            for page in pages:
                raw = originals[page['bmpSha256']]
                self.assertEqual(hashlib.sha256(raw[54:]).hexdigest(), page['pixelSha256'])
                self.assertEqual(page['bmpSha256'], page['nativeSource']['sha256'])
                self.assertEqual(page['sourceSequence'], page['deliveryProof']['acquisitionSequence'])
                self.assertTrue(page['deliveryProof']['deliveryQualified'])
                frames.append(cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR))
            diagnostics = [json.loads(l) for l in z.read(next(n for n in z.namelist()
                if n.endswith('/warehouse-scroll-diagnostics.jsonl'))).decode().splitlines()]
            sends = [e for e in diagnostics if e['stage'] == 'send-interface-returned']
            rejects = [e for e in diagnostics if e['stage'] == 'scroll-ended']
            self.assertEqual(len(sends), 2)
            self.assertTrue(all(e['sendInterfaceInvoked'] and e['returnValue'] == 1 for e in sends))
            self.assertEqual(len(rejects), 3)
            self.assertTrue(all(e['classification'] == 'NOT_SENT_CONTENT_SUPPORT_RECHECK'
                and e['sendInterfaceInvoked'] is False for e in rejects))
        x, y, r, b = warehouse_search_roi(1920, 1080)
        crops = [im[y:b, x:r] for im in frames]
        first = align_warehouse_segments(crops[8], crops[9], required_direction='DOWN')
        self.assertEqual(first['status'], 'VERIFIED')
        self.assertEqual(first['verticalOffsetPx'], -271)
        failed = align_warehouse_segments(crops[10], crops[11], required_direction='DOWN')
        self.assertEqual(failed['status'], 'UNVERIFIED')
        self.assertIsNone(failed['verticalOffsetPx'])  # The old blank transition is not repaired proof.
        # Original pixels with inert SOURCE/input envelopes check scheduling;
        # this is not a new real frame following the newly sized message.
        f = LiveRun(output=ROOT / 'build/issue42-evidence/real-pixel-flow')
        try:
            f.deliver(frames[7]); f.tick(); f.deliver(frames[8])
            f.scroll_ack(); f.tick(); f.deliver(frames[9])
            f.tick(); f.deliver(frames[10])
            self.assertEqual(f.auto._phase, 'WAIT_SCROLL', f.logs[-3:])
            delta = f.sent[-1]['wheelDelta']
            self.assertLessEqual(abs(delta) / 120 * (271 / 9), 170)
            self.assertEqual(f.finalizations, [])
            self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 2)
            f.now = f.auto._deadline; f.auto.poll()
            self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
        finally:
            f.close()
