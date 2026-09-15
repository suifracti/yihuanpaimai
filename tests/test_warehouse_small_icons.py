import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from warehouse_placement_resolver import WarehousePlacementResolver


class SmallIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).parent / 'fixtures/warehouse_small_icons'
        cls.frames = json.loads((cls.root / 'provenance.json').read_text(encoding='utf-8'))['frames']
        cls.resolver = WarehousePlacementResolver()

    def image(self, frame):
        raw = (self.root / frame['file']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), frame['sha256'])
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def match(self, image, frame):
        w, h = frame['widthCells'], frame['heightCells']
        refs = [r for r in self.resolver._ref_cache.values()
                if (r['widthCells'], r['heightCells']) == (w, h)]
        return self.resolver._match_small_icon(image, w, h, refs)

    def test_real_frames_compete_against_all_same_size_cards(self):
        accepted = {}
        for frame in self.frames:
            crop = self.image(frame)
            before = crop.copy()
            result = self.match(crop, frame)
            self.assertTrue(np.array_equal(crop, before))
            if result is None:
                continue
            self.assertEqual(result['catalogId'], frame['catalogId'])
            self.assertEqual(result['name'], frame['name'])
            self.assertGreaterEqual(result['inliers'], 7)
            self.assertGreaterEqual(result['margin'], 5)
            self.assertLessEqual(result['registration']['error'], 22)
            self.assertGreaterEqual(result['registration']['correlation'], .85)
            accepted.setdefault(frame['catalogId'], set()).add(frame['sourceSha256'])
        # Five independently annotated objects have two or more real sources.
        for cid in ('image22-1-1', 'image2-0-0', 'image22-1-2', 'image6-1-0', 'image29-0-0'):
            self.assertGreaterEqual(len(accepted.get(cid, set())), 2)

    def test_thin_object_sampling_retains_native_structure_and_hue_checks(self):
        for frame in self.frames:
            if frame['catalogId'] != 'image29-0-0':
                continue
            result = self.match(self.image(frame), frame)
            self.assertIsNotNone(result)
            proof = result['registration']
            self.assertEqual(proof['samplingModel'], 'SYMMETRIC_NATIVE_3X3')
            self.assertGreater(proof['nativeError'], 22)
            self.assertGreaterEqual(proof['nativeCorrelation'], .85)
            self.assertLessEqual(proof['hueError'], 12)

    def test_recolored_occluded_shuffled_and_blank_icons_are_rejected(self):
        for frame in self.frames:
            crop = self.image(frame)
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            hsv[:, :, 0] = (hsv[:, :, 0].astype(int) + 70) % 180
            occluded = crop.copy()
            occluded[:crop.shape[0] // 2] = 40
            shuffled = crop.copy().reshape(-1, 3)
            np.random.default_rng(18).shuffle(shuffled)
            for name, image in [('recolored', cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)),
                                ('occluded', occluded), ('shuffled', shuffled.reshape(crop.shape)),
                                ('blank', np.full_like(crop, 40))]:
                with self.subTest(frame=frame['file'], variant=name):
                    self.assertIsNone(self.match(image, frame))

    def test_only_complete_small_tiles_use_fine_scale(self):
        frame = self.frames[0]
        crop = self.image(frame)
        for image, w, h in [(crop[:42], 1, 2), (crop, 2, 1), (crop, 0, 2),
                            (np.zeros((112, 56, 3), np.uint8), 1, 2),
                            (np.zeros((40, 20, 3), np.uint8), 1, 2)]:
            with self.subTest(shape=image.shape, w=w, h=h):
                self.assertIsNone(self.resolver._match_small_icon(image, w, h, []))

    def test_existing_conflicting_candidate_is_rejected(self):
        frame = self.frames[0]
        crop = self.image(frame)
        small = self.match(crop, frame)
        self.assertIsNotNone(small)
        def weak(image, ref, **kwargs):
            return 5 if ref.get('entry', {}).get('catalogId') == 'image22-1-2' else 0
        with patch.object(self.resolver, '_compute_sift_inliers', side_effect=weak), \
             patch.object(self.resolver, '_compute_foreground_alignment', return_value=None), \
             patch.object(self.resolver, '_match_footprint_normalized_icon', return_value=None), \
             patch.object(self.resolver, '_match_small_icon', return_value=small):
            self.assertEqual(self.resolver.match_catalog_candidates(crop, 1, 2)[1], [])

    def test_never_resizes_query(self):
        frame = self.frames[0]
        crop = self.image(frame)
        with patch('warehouse_placement_resolver.cv2.resize', side_effect=AssertionError('Unexpected resize')):
            self.assertIsNotNone(self.match(crop, frame))
