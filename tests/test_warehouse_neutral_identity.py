import hashlib
import json
from pathlib import Path
import unittest

import cv2
import numpy as np
from warehouse_placement_resolver import WarehousePlacementResolver
from warehouse_neutral_foreground import match_neutral_foreground
from visual_catalog import _catalog_reference_body


class NeutralIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolver = WarehousePlacementResolver()
        cls.root = Path(__file__).parent / 'fixtures/warehouse_neutral_identity'
        cls.frames = json.loads((cls.root / 'provenance.json').read_text(encoding='utf-8'))['frames']

    def image(self, frame):
        raw = (self.root / frame['file']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), frame['sha256'])
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def test_six_real_neutral_frames_meet_unchanged_final_gates(self):
        frames = [f for f in self.frames if f['heightCells'] == 1]
        self.assertEqual(len(frames), 6)
        self.assertEqual(len({f['sourceSha256'] for f in frames}), 3)
        for frame in frames:
            with self.subTest(frame=frame['file']):
                crop = self.image(frame)
                ref = self.resolver._ref_cache[frame['catalogId']]['img']
                result = self.resolver._compute_foreground_alignment(crop, ref)
                self.assertIsNotNone(result)
                self.assertTrue(result['neutralBackground'])
                self.assertGreaterEqual(result['iou'], .75)
                self.assertGreaterEqual(result['correlation'], .85)
                self.assertLessEqual(result['error'], 22)
                self.assertTrue(all(abs(v) <= 3 for v in result['translation96']))
                _, candidates, _ = self.resolver.match_catalog_candidates(crop, 1, 1)
                self.assertEqual([c['catalogId'] for c in candidates], [frame['catalogId']])
                self.assertGreaterEqual(candidates[0]['bestFgScore'], .90)
                self.assertGreaterEqual(candidates[0]['fgMargin'], .05)

    def test_all_competing_single_cell_cards_are_rejected(self):
        for frame in self.frames:
            if frame['heightCells'] != 1:
                continue
            crop = self.image(frame)
            for cid, ref in self.resolver._ref_cache.items():
                if cid == frame['catalogId'] or (ref['widthCells'], ref['heightCells']) != (1, 1):
                    continue
                with self.subTest(frame=frame['file'], catalogId=cid):
                    self.assertIsNone(self.resolver._compute_foreground_alignment(crop, ref['img']))

    def test_blank_recolored_and_occluded_icons_do_not_confirm(self):
        for cid in ('image3-0-0', 'image2-1-2'):
            frame = next(f for f in self.frames if f['catalogId'] == cid)
            crop = self.image(frame)
            ref = self.resolver._ref_cache[cid]['img']
            occluded = crop.copy()
            occluded[:, :crop.shape[1] // 2] = 60
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            hsv[:, :, 0] = (hsv[:, :, 0].astype(int) + 70) % 180
            recolored = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
            for bad in (np.full_like(crop, 80), recolored, occluded):
                with self.subTest(catalogId=cid):
                    self.assertIsNone(self.resolver._compute_foreground_alignment(bad, ref))

    def test_colored_background_does_not_enter_neutral_fallback(self):
        for frame in self.frames:
            if frame['heightCells'] != 2:
                continue
            crop = self.image(frame)
            ref = self.resolver._ref_cache[frame['catalogId']]['img']
            self.assertIsNone(match_neutral_foreground(crop, _catalog_reference_body(ref)))
