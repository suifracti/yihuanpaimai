"""Independent rendered boundary contracts, not real-game generalization."""
import sys
from pathlib import Path
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from warehouse_vision import WarehouseVisionV1


class TestClosedFrameSeparators(unittest.TestCase):
    def test_known_gameplay_outer_frames_and_square_spacing(self):
        image = cv2.imread(str(ROOT / 'tests/fixtures/warehouse_closed_frame_v2/necklace-cart-board.png'))
        self.assertIsNotNone(image)
        vision = WarehouseVisionV1.__new__(WarehouseVisionV1)
        grid = vision._measure_board_grid(image, 0, 0)
        self.assertEqual((grid['cell_w'], grid['cell_h']), (56, 56))
        slots = vision._extract_viewport_slots(image, 0, 0, grid)
        # Two independently reviewed complete frames; four other colour
        # patches have no icon and do not establish physical item footprints.
        multi = {(s['row'], s['col'], s['w_cells'], s['h_cells'], s['rarity'])
                 for s in slots if s['w_cells'] * s['h_cells'] > 1}
        self.assertEqual(multi, {(3, 0, 2, 2, 'purple'), (4, 2, 4, 4, 'red')})

    def render(self, adjacent):
        # One object: a single closed frame around two dark blue cells.
        # Two objects: two individually closed frames with a black gap; their
        # top/bottom glow touches, so colour connectivity alone is insufficient.
        image = np.full((64, 128, 3), (65, 40, 10), dtype=np.uint8)
        rim = (255, 180, 20)
        cv2.rectangle(image, (0, 0), (127, 63), rim, 4)
        if adjacent:
            cv2.rectangle(image, (0, 0), (61, 63), rim, 4)
            cv2.rectangle(image, (66, 0), (127, 63), rim, 4)
            # OpenCV centres strokes on the rectangle edge; paint the gap
            # afterwards so their outward halves do not erase the authored gap.
            image[:, 62:66] = (10, 10, 10)
            image[:4, 62:66] = rim
            image[-4:, 62:66] = rim
        return image

    def geometry(self, image, vertical, scale):
        if vertical:
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        if scale != 1:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        cell = 64 * scale
        grid = dict(origin=(0, 0), cell_w=cell, cell_h=cell,
                    cols=1 if vertical else 2, rows=2 if vertical else 1)
        # Only pixel geometry runs: no catalog, identity, quantity or valuation.
        vision = WarehouseVisionV1.__new__(WarehouseVisionV1)
        return vision._extract_viewport_slots(image, 0, 0, grid)

    def test_flat_dark_fill_inside_one_frame_stays_one_object(self):
        for vertical in (False, True):
            for scale in (1, .5):
                with self.subTest(vertical=vertical, scale=scale):
                    slots = self.geometry(self.render(False), vertical, scale)
                    self.assertEqual(len(slots), 1)
                    self.assertEqual((slots[0]['w_cells'], slots[0]['h_cells']),
                                     (1, 2) if vertical else (2, 1))

    def test_two_closed_frames_with_touching_glow_stay_separate(self):
        for vertical in (False, True):
            for scale in (1, .5):
                with self.subTest(vertical=vertical, scale=scale):
                    slots = self.geometry(self.render(True), vertical, scale)
                    self.assertEqual(len(slots), 2)
                    self.assertEqual([(s['w_cells'], s['h_cells']) for s in slots], [(1, 1), (1, 1)])

    def test_four_closed_frames_keep_both_seam_directions(self):
        image = np.vstack([self.render(True), self.render(True)])
        image[62:66, :] = (10, 10, 10)
        image[62:66, :4] = (255, 180, 20)
        image[62:66, -4:] = (255, 180, 20)
        for scale in (1, .5):
            with self.subTest(scale=scale):
                rendered = image if scale == 1 else cv2.resize(
                    image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                vision = WarehouseVisionV1.__new__(WarehouseVisionV1)
                grid = dict(origin=(0, 0), cell_w=64*scale, cell_h=64*scale, cols=2, rows=2)
                slots = vision._extract_viewport_slots(rendered, 0, 0, grid)
                self.assertEqual(len(slots), 4)
                self.assertTrue(all((s['w_cells'], s['h_cells']) == (1, 1) for s in slots))


if __name__ == '__main__':
    unittest.main()
