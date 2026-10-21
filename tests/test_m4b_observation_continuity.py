"""Retained M4b observation match: sparse steps are measured, not assumed.

Opt-in; no game input and no edits to the archived record. The archived live
result stays PARTIAL. This replay reads the same originals through the
production aligner and the Host coverage path.
"""
import hashlib
import json
import unittest
from pathlib import Path

import cv2
import numpy as np

from tests.test_native_half_viewport_flow import ROOT
from warehouse_capture_host import WarehouseCaptureHost
from warehouse_grid_geometry import observe_warehouse_grid
from warehouse_scrollbar_observation import warehouse_search_roi
from warehouse_segment_overlap import TerminalContinuity, align_warehouse_segments
from warehouse_support_frame import same_viewport_proof

DATA = ROOT / 'build/m4b-20261021/run-5/runtime-data/native-live-trial'
MANIFEST = DATA / 'warehouse-intake/22ed2ef203d5444da80267af8109615a.json'
MOTIONS = [(18, 19), (20, 21), (22, 23), (24, 25), (26, 27), (28, 29), (30, 31),
           (32, 33), (34, 35), (36, 37), (38, 39), (40, 41), (42, 43), (44, 45), (46, 47)]


class _Store:
    def load_original(self, descriptor):
        return (DATA / descriptor['relativePath']).read_bytes()


class _History:
    def persist_warehouse_evidence(self, key, **kwargs):
        return {'id': key}


@unittest.skipUnless(MANIFEST.is_file(), 'requires retained private M4b observation originals')
class ObservationContinuityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(MANIFEST.read_text(encoding='utf-8'))
        cls.crops = []
        for page in cls.document['pages']:
            raw = (DATA / page['nativeSource']['relativePath']).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == page['nativeSource']['sha256']
            frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            x, y, r, b = warehouse_search_roi(frame.shape[1], frame.shape[0])
            cls.crops.append(frame[y:b, x:r])

    def test_every_retained_step_is_measured_at_the_unchanged_floor(self):
        chain = TerminalContinuity()
        offsets = []
        for prev, nxt in MOTIONS:
            result = align_warehouse_segments(
                self.crops[prev], self.crops[nxt], prev_id=str(prev), next_id=str(nxt),
                required_direction='DOWN', max_shift_px=320, terminal_continuity=chain)
            self.assertEqual(result['status'], 'VERIFIED', (prev, nxt, result))
            self.assertTrue(result['progressionVerified'])
            self.assertIsNotNone(result['verticalOffsetPx'])
            self.assertLess(result['verticalOffsetPx'], 0)
            self.assertGreaterEqual(result['confidence'], .80, (prev, nxt, result))
            offsets.append(result['verticalOffsetPx'])
        # Retained physics: two reveal-time jumps, twelve small notches, one tail.
        self.assertEqual(offsets[0], -271)
        self.assertAlmostEqual(offsets[1], -210.5, delta=1)
        for offset in offsets[2:-1]:
            self.assertAlmostEqual(offset, -30, delta=1)
        self.assertAlmostEqual(offsets[-1], -4.5, delta=1)

    def test_reveal_frames_join_coverage_without_identity(self):
        proof = same_viewport_proof(self.crops[0], self.crops[1])
        self.assertIsNotNone(proof)
        self.assertTrue(proof['sameViewportVerified'])
        self.assertFalse(proof['identitySupportVerified'])
        self.assertFalse(proof['progressionVerified'])
        self.assertEqual(proof['verticalOffsetPx'], 0)
        grids = [observe_warehouse_grid(c, already_cropped=True)['grid'] for c in self.crops[:2]]
        self.assertEqual(grids[0]['columnCount'], grids[1]['columnCount'])

    def test_saved_host_coverage_is_complete_and_a_skipped_range_is_not(self):
        descriptors = [page['descriptor'] for page in self.document['pages']]
        host = WarehouseCaptureHost(store_factory=lambda: _Store(), driver_available=False)
        key = self.document['scope']['recordStableKey']
        complete = host._process_saved_pages(key, descriptors, history_store=_History(),
                                             resolve_placements=False, identity_evidence_ids=[])
        self.assertEqual(complete['coverageStatus'], 'COMPLETE',
                         (complete.get('coverage') or {}).get('gaps'))
        # 20 retained views span more than the search viewport; dropping them
        # cannot borrow the small-step proof.
        skipped = host._process_saved_pages(key, descriptors[:20] + descriptors[40:],
                                            history_store=_History(), resolve_placements=False,
                                            identity_evidence_ids=[])
        self.assertEqual(skipped['coverageStatus'], 'PARTIAL')
        self.assertTrue((skipped.get('coverage') or {}).get('gaps'))


if __name__ == '__main__':
    unittest.main()
