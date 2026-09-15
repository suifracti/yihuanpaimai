import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from warehouse_placement_resolver import WarehousePlacementResolver


class RotatedIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolver = WarehousePlacementResolver()
        cls.root = Path(__file__).parent / 'fixtures' / 'warehouse_rotated_identity'
        cls.frames = json.loads((cls.root / 'provenance.json').read_text(encoding='utf-8'))['frames']
        cls.reference = cls.resolver._ref_cache['visual-liuliwei-4x1']['img']

    def image(self, frame):
        raw = (self.root / frame['file']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), frame['sha256'])
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def test_seven_real_frames_match_after_orientation_normalization(self):
        self.assertEqual(len({f['sourceSha256'] for f in self.frames}), 7)
        for frame in self.frames:
            with self.subTest(frame=frame['file']):
                crop = self.image(frame)
                result = self.resolver._compute_foreground_alignment(crop, self.reference)
                self.assertIsNotNone(result)
                self.assertTrue(result['axisNormalized'])
                self.assertGreaterEqual(result['iou'], .75)
                self.assertGreaterEqual(result['correlation'], .85)
                self.assertLessEqual(result['error'], 22)
                _, candidates, _ = self.resolver.match_catalog_candidates(crop, 4, 1)
                self.assertEqual([c['catalogId'] for c in candidates], ['visual-liuliwei-4x1'])
                self.assertGreaterEqual(candidates[0]['bestFgScore'], .90)

    def test_every_other_catalog_foreground_is_rejected(self):
        crop = self.image(self.frames[0])
        for cid, ref in self.resolver._ref_cache.items():
            if cid != 'visual-liuliwei-4x1':
                with self.subTest(catalogId=cid):
                    self.assertIsNone(self.resolver._compute_foreground_alignment(crop, ref['img']))

    def test_blank_recolored_and_occluded_regions_do_not_supply_foreground_evidence(self):
        crop = self.image(self.frames[0])
        occluded = crop.copy()
        occluded[:, :crop.shape[1] // 2] = 20
        recolored = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        recolored[:, :, 0] = (recolored[:, :, 0].astype(int) + 70) % 180
        recolored = cv2.cvtColor(recolored, cv2.COLOR_HSV2BGR)
        for image in [np.full_like(crop, 20), occluded, recolored]:
            self.assertIsNone(self.resolver._compute_foreground_alignment(image, self.reference))

    def test_weak_sift_does_not_hide_agreeing_foreground_evidence(self):
        crop = self.image(self.frames[0])
        def weak_sift(roi, reference, **kwargs):
            return 6 if reference['entry']['catalogId'] == 'visual-liuliwei-4x1' else 0
        with patch.object(self.resolver, '_compute_sift_inliers', side_effect=weak_sift):
            _, candidates, _ = self.resolver.match_catalog_candidates(crop, 4, 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['inliers'], 6)
        self.assertGreaterEqual(candidates[0]['bestFgScore'], .90)

    def test_round_mask_has_no_reliable_orientation(self):
        mask = np.zeros((50, 50), np.uint8)
        cv2.circle(mask, (25, 25), 15, 255, -1)
        self.assertIsNone(self.resolver._normalize_foreground_axis((np.zeros((50, 50, 3), np.uint8), mask)))

    def test_disagreeing_sift_and_foreground_identities_fail_closed(self):
        crop = self.image(self.frames[0])
        def conflicting_sift(roi, reference, **kwargs):
            return 6 if reference['entry']['catalogId'] == 'image26-1-0' else 0
        with patch.object(self.resolver, '_compute_sift_inliers', side_effect=conflicting_sift):
            score, candidates, _ = self.resolver.match_catalog_candidates(crop, 4, 1)
        self.assertEqual(candidates, [])
        self.assertEqual(score, 0)
