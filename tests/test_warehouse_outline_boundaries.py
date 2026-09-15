"""Object-level ground truth from the visible 75s/90s outline frames."""
from pathlib import Path
import unittest
import cv2
import numpy as np
from warehouse_vision import WarehouseVisionV1

FIXTURES = Path(__file__).parent / 'fixtures' / 'warehouse_outline_v1'
# Left-top two independently bordered squares, then four larger outlines.
EXPECTED = {(2, 0, 1, 1), (2, 1, 1, 1), (6, 0, 3, 2),
            (4, 3, 2, 1), (5, 4, 1, 2), (6, 7, 1, 3)}


class WarehouseOutlineBoundaryTests(unittest.TestCase):
    def test_recorded_outlines_keep_separate_items_and_exclude_board_exterior(self):
        engine = WarehouseVisionV1()
        previous_ids = None
        for sec in (75, 90):
            with self.subTest(second=sec):
                frame = cv2.imdecode(np.fromfile(FIXTURES / f'frame_{sec}s.jpg', dtype=np.uint8), cv2.IMREAD_COLOR)
                self.assertIsNotNone(frame)
                slots = engine.process_frame(frame)['slots']
                self.assertEqual({tuple(s[k] for k in ('col', 'row', 'w', 'h')) for s in slots}, EXPECTED)
                self.assertEqual(len(slots), len(EXPECTED))
                for slot in slots:
                    self.assertEqual(slot['rarity'], 'unknown')
                    self.assertEqual(slot['evidenceLevel'], 'OUTLINE_ONLY')
                    self.assertIsNone(slot['identifiedName'])
                    self.assertLessEqual(slot['box'][1] + slot['box'][3], 776)
                ids = {s['trackId'] for s in slots}
                if previous_ids is not None:
                    self.assertEqual(ids, previous_ids)
                previous_ids = ids

    def test_bright_outline_borders_do_not_hide_a_dark_separator(self):
        engine = WarehouseVisionV1()
        crop = np.full((112, 56, 3), 90, dtype=np.uint8)
        crop[52:61] = 112
        crop[54:57] = 22
        self.assertTrue(engine._has_item_gutter(crop, 0, 0, 0, 0, 56, 56, 0, 0, 0, 1))
        crop[54:57] = 112
        self.assertFalse(engine._has_item_gutter(crop, 0, 0, 0, 0, 56, 56, 0, 0, 0, 1))
