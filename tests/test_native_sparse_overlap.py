"""Clipped sparse artwork must prove overlap; periodic grid never suffices.

The private opt-in replay reads the exact Issue #31 ZIP without extracting it
or running capture/input. Synthetic worlds check rejection rules, not accuracy.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
import zipfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from warehouse_segment_overlap import align_warehouse_segments, TerminalContinuity
from warehouse_scrollbar_observation import warehouse_search_roi

ZIP_SHA = '2af88d284dcdef2fc2406667e9cbf5081c08d16c59ff91ae06204314a451627b'


def sparse_world(offset, *, artwork=True):
    world = np.full((1400, 600, 3), 18, np.uint8)
    for y in range(0, 1400, 56):
        cv2.line(world, (0, y), (559, y), (46, 46, 46), 3)
    for x in range(0, 560, 56):
        cv2.line(world, (x, 0), (x, 1399), (46, 46, 46), 3)
    if artwork:
        rng = np.random.RandomState(314)
        world[125:350, 226:338] = rng.randint(60, 220, (225, 112, 3), dtype=np.uint8)
    return world[offset:offset + 636].copy()


class SparseOverlapTests(unittest.TestCase):
    def test_clipped_artwork_keeps_disjoint_unique_pixel_support(self):
        motion = align_warehouse_segments(sparse_world(0), sparse_world(271), required_direction='DOWN')
        self.assertEqual(motion['status'], 'VERIFIED', motion)
        self.assertEqual(motion['verticalOffsetPx'], -271)
        self.assertGreaterEqual(motion['supportCount'], 2)
        self.assertGreater(motion['overlapRatio'], 0)

    def test_periodic_grid_jump_and_reverse_do_not_grant_downward_coverage(self):
        repeated = sparse_world(0, artwork=False)
        repeated[:, 226:338] = (65, 110, 140)  # foreground without unique content
        for a, b in ((sparse_world(0, artwork=False), sparse_world(271, artwork=False)),
                     (repeated, np.roll(repeated, -56, axis=0)),
                     (sparse_world(0), sparse_world(700)),
                     (sparse_world(271), sparse_world(0))):
            with self.subTest():
                motion = align_warehouse_segments(a, b, required_direction='DOWN')
                self.assertNotEqual(motion['status'], 'VERIFIED', motion)
                self.assertFalse(motion['progressionVerified'])

    @unittest.skipUnless(os.environ.get('YH_ONCE12_ZIP'), 'private Issue #31 SOURCE package opt-in')
    def test_identity_checked_real_sequence_has_pixel_continuity(self):
        package = Path(os.environ['YH_ONCE12_ZIP'])
        self.assertEqual(package.stat().st_size, 67916568)
        self.assertEqual(hashlib.sha256(package.read_bytes()).hexdigest(), ZIP_SHA)
        images, frames = [], []
        with zipfile.ZipFile(package) as z:
            self.assertEqual(len(z.infolist()), 70)
            self.assertIsNone(z.testzip())
            intake = json.loads(z.read(next(n for n in z.namelist()
                if '/warehouse-intake/' in n and '/attempts/' not in n)))
            self.assertEqual(len(intake['pages']), 7)
            previous_sequence = 0
            for page in intake['pages']:
                native, desc, proof = page['nativeSource'], page['descriptor'], page['deliveryProof']
                raw = z.read(next(n for n in z.namelist() if n.endswith('/' + native['relativePath'])))
                self.assertEqual(len(raw), native['byteSize'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), page['bmpSha256'])
                self.assertEqual(page['bmpSha256'], native['sha256'])
                self.assertEqual(hashlib.sha256(raw[54:]).hexdigest(), page['pixelSha256'])
                png = z.read(next(n for n in z.namelist() if n.endswith('/' + desc['relativePath'])))
                self.assertEqual(hashlib.sha256(png).hexdigest(), desc['sha256'])
                frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                self.assertTrue(np.array_equal(frame, cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)))
                self.assertTrue(proof['deliveryQualified'] and proof['sourceMarkerProgress'])
                self.assertEqual(proof['acquisitionSequence'], native['frameSequence'])
                self.assertGreater(proof['acquisitionSequence'], previous_sequence)
                previous_sequence = proof['acquisitionSequence']
                x, y, r, b = warehouse_search_roi(frame.shape[1], frame.shape[0])
                images.append(frame[y:b, x:r].copy())
                frames.append(frame)
        chain, motions = TerminalContinuity(), []
        for a, b in ((3, 4), (5, 6)):
            motion = align_warehouse_segments(images[a], images[b], prev_id=str(a+1), next_id=str(b+1),
                required_direction='DOWN', terminal_continuity=chain)
            self.assertEqual(motion['status'], 'VERIFIED', motion)
            self.assertEqual(motion['verticalOffsetPx'], -271)
            self.assertGreaterEqual(motion['supportCount'], 2)
            motions.append(motion)
        self.assertEqual(len(chain.samples), 2)
        from warehouse_coverage_ledger import WarehouseCoverageLedger
        ledger = WarehouseCoverageLedger(intake['scope']['recordStableKey'])
        first, second = (intake['pages'][i]['descriptor'] for i in (3, 5))
        ledger.add_segment(first, sequence_index=1,
            top_proof={'trusted': True, 'proofId': 'retained-top-4'})
        ledger.add_segment(second, sequence_index=2, overlap_proof={
            'trusted': True, 'aligned': True, 'proofId': motions[0]['progressionProofId'],
            'previousEvidenceId': first['evidenceId']})
        self.assertEqual(ledger.snapshot()['coverageStatus'], 'PARTIAL')
        self.assertIsNone(ledger.snapshot()['bottomEndpoint'])
        # Real saved pixels, inert delivery/input envelope. This verifies the
        # actual collector transition, not freshness of a new live SOURCE.
        from tests.test_native_half_viewport_flow import LiveRun
        f = LiveRun(output=ROOT / 'build/issue31-evidence/flow')
        try:
            f.deliver(frames[2]); f.tick(); f.deliver(frames[3])
            self.assertEqual(f.auto._phase, 'WAIT_SCROLL')
            deadline = f.auto._deadline
            f.scroll_ack(); f.tick(); f.deliver(frames[4])
            f.tick(); f.deliver(frames[5])
            self.assertEqual(f.auto._phase, 'WAIT_SCROLL')
            sent_command = dict(f.source._pending)
            f.scroll_ack()
            duplicate = f.event('SCROLLED', sent_command, inputActions=True,
                reason='WINDOW_WHEEL_MESSAGE_SENT', details={'direction': 'DOWN',
                    'delta': sent_command['wheelDelta'], 'sourceLeaseId': sent_command['sourceLeaseId'],
                    'messageCompletedNs': round(f.now * 1e9)})
            f.auto.on_event(duplicate); f.auto.poll()
            self.assertEqual(f.auto._phase, 'WAIT_MOVED')
            f.tick(); f.deliver(frames[6])
            self.assertEqual(f.auto._phase, 'WAIT_STABLE', f.logs[-3:])
            self.assertEqual(f.finalizations, [])
            self.assertEqual(len(f.gate.representatives()), 2)  # #7 lacks a stable support original.
            self.assertEqual(f.auto._deadline, deadline)
            f.tick()
            self.assertEqual(f.sent[-1]['operation'], 'REQUEST_PAGE')
            self.assertEqual(sum(c['operation'] == 'SCROLL_DOWN' for c in f.sent), 2)
            self.assertEqual(f.auto._deadline, deadline)
            f.now = deadline; f.auto.poll()
            self.assertFalse(f.auto._active)
            self.assertEqual(f.finalizations[-1]['termination_reason'], 'INCOMPLETE')
        finally:
            f.close()


if __name__ == '__main__':
    unittest.main()
