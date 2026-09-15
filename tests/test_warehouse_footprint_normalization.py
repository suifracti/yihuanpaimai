import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from warehouse_placement_resolver import WarehousePlacementResolver


class FootprintNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolver = WarehousePlacementResolver()
        cls.root = Path(__file__).parent / 'fixtures/warehouse_neutral_identity'
        cls.frames = [f for f in json.loads((cls.root / 'provenance.json').read_text(encoding='utf-8'))['frames']
                      if f['catalogId'] == 'image12-1-0']
        cls.references = [r for r in cls.resolver._ref_cache.values()
                          if (r['widthCells'], r['heightCells']) == (1, 2)]

    def image(self, frame):
        raw = (self.root / frame['file']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), frame['sha256'])
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def test_three_real_frames_identify_same_card_against_all_same_footprints(self):
        self.assertEqual(len({f['sourceSha256'] for f in self.frames}), 3)
        for frame in self.frames:
            with self.subTest(frame=frame['file']):
                crop = self.image(frame)
                before = crop.copy()
                _, candidates, _ = self.resolver.match_catalog_candidates(crop, 1, 2)
                self.assertEqual([c['catalogId'] for c in candidates], ['image12-1-0'])
                self.assertIn('FOOTPRINT_NORMALIZED_SIFT', candidates[0]['matchReasons'])
                self.assertGreaterEqual(candidates[0]['inliers'], 7)
                self.assertGreaterEqual(candidates[0]['margin'], 5)
                self.assertEqual(candidates[0]['geometry']['shape'], '1x2')
                self.assertTrue(np.array_equal(crop, before))

    def test_normalization_only_shrinks_and_rejects_inconsistent_or_clipped_tiles(self):
        crop = self.image(self.frames[0])
        resize = cv2.resize
        sizes = []
        def checked_resize(image, size, *args, **kwargs):
            sizes.append(size)
            self.assertLessEqual(size[0], image.shape[1])
            self.assertLessEqual(size[1], image.shape[0])
            return resize(image, size, *args, **kwargs)
        with patch('warehouse_placement_resolver.cv2.resize', side_effect=checked_resize):
            self.assertIsNotNone(self.resolver._match_footprint_normalized_icon(crop, 1, 2, self.references))
        self.assertEqual(len(sizes), 1)
        for image, width, height in [(crop[:56], 1, 2), (crop, 2, 1), (crop, 1, 1), (crop, 0, 2), (crop[:20, :10], 1, 2)]:
            self.assertIsNone(self.resolver._match_footprint_normalized_icon(image, width, height, self.references))

    def test_recolored_occluded_shuffled_and_blank_regions_are_rejected(self):
        for frame in self.frames:
            crop = self.image(frame)
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            hsv[:, :, 0] = (hsv[:, :, 0].astype(int) + 70) % 180
            occluded = crop.copy()
            occluded[:crop.shape[0] // 2] = 40
            shuffled = crop.copy().reshape(-1, 3)
            np.random.default_rng(18).shuffle(shuffled)
            bad_images = [cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR), occluded,
                          shuffled.reshape(crop.shape), np.full_like(crop, 40)]
            for bad in bad_images:
                with self.subTest(frame=frame['file']):
                    self.assertIsNone(self.resolver._match_footprint_normalized_icon(bad, 1, 2, self.references))

    def test_conflicting_admitted_identity_is_not_replaced(self):
        crop = self.image(self.frames[0])
        # Existing weak-but-admitted SIFT evidence points to a different real
        # card. The new view must reject the conflict rather than overwrite it.
        def weak(image, ref, **kwargs):
            return 5 if ref['entry']['catalogId'] == 'image12-1-2' else 0
        normalized = self.resolver._match_footprint_normalized_icon(crop, 1, 2, self.references)
        with patch.object(self.resolver, '_compute_sift_inliers', side_effect=weak), \
             patch.object(self.resolver, '_compute_foreground_alignment', return_value=None), \
             patch.object(self.resolver, '_match_footprint_normalized_icon', return_value=normalized):
            _, candidates, _ = self.resolver.match_catalog_candidates(crop, 1, 2)
        self.assertEqual(candidates, [])
