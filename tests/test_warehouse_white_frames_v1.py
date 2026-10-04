"""User-confirmed real white borders and independently drawn boundary cases."""
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from warehouse_vision import WarehouseVisionV1


class TestWhiteFrames(unittest.TestCase):
    def test_known_settlement_narrow_frame_and_upper_right_square(self):
        image = cv2.imread(str(ROOT / "tests/fixtures/warehouse_white_frames_v1/settlement-board.png"))
        self.assertIsNotNone(image)
        vision = WarehouseVisionV1.__new__(WarehouseVisionV1)
        grid = vision._measure_board_grid(image, 1315, 211)
        self.assertEqual((grid["cell_w"], grid["cell_h"]), (56, 56))
        slots = vision._extract_viewport_slots(image, 1315, 211, grid)
        cells = {(5, 5), (5, 6), (6, 5)}
        nearby = [s for s in slots if cells.intersection(s["cells"])]
        self.assertEqual({(s["col"], s["row"], s["w_cells"], s["h_cells"], s["rarity"])
                          for s in nearby}, {(5, 5, 1, 2, "white"), (6, 5, 1, 1, "white")})

    def render(self, adjacent):
        image = np.full((64, 128, 3), 86, dtype=np.uint8)
        rim = (210, 210, 210)
        cv2.rectangle(image, (0, 0), (127, 63), rim, 4)
        if adjacent:
            cv2.rectangle(image, (0, 0), (61, 63), rim, 4)
            cv2.rectangle(image, (66, 0), (127, 63), rim, 4)
            # Draw the gap after centred strokes, retaining touching end glow.
            image[:, 62:66] = 10
            image[:4, 62:66] = rim
            image[-4:, 62:66] = rim
        return image

    def geometry(self, adjacent, vertical, scale):
        image = self.render(adjacent)
        if vertical:
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        if scale != 1:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        grid = dict(origin=(0, 0), cell_w=64*scale, cell_h=64*scale,
                    cols=1 if vertical else 2, rows=2 if vertical else 1)
        vision = WarehouseVisionV1.__new__(WarehouseVisionV1)
        return vision._extract_viewport_slots(image, 0, 0, grid)

    def test_one_closed_white_frame_keeps_dark_body_together(self):
        for vertical in (False, True):
            for scale in (1, .5):
                with self.subTest(vertical=vertical, scale=scale):
                    slots = self.geometry(False, vertical, scale)
                    self.assertEqual(len(slots), 1)
                    self.assertEqual((slots[0]["w_cells"], slots[0]["h_cells"], slots[0]["rarity"]),
                                     (1, 2, "white") if vertical else (2, 1, "white"))

    def test_touching_white_glow_does_not_merge_independent_frames(self):
        for vertical in (False, True):
            for scale in (1, .5):
                with self.subTest(vertical=vertical, scale=scale):
                    slots = self.geometry(True, vertical, scale)
                    self.assertEqual(len(slots), 2)
                    self.assertTrue(all((s["w_cells"], s["h_cells"], s["rarity"]) == (1, 1, "white")
                                        for s in slots))


if __name__ == "__main__":
    unittest.main()
