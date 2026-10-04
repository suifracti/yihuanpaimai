"""Physical geometry established from real visible frames, not machine identities."""
from pathlib import Path
import sys
import unittest

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from warehouse_vision import WarehouseVisionV1


class TestCompleteWarehouseFrame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision = WarehouseVisionV1()
        cls.board = cv2.imread(str(ROOT / 'tests/fixtures/warehouse_complete_frame_v1/armour-board.png'))
        if cls.board is None:
            raise RuntimeError('Real armour fixture unavailable')

    def recognize(self, image):
        self.vision.reset()
        return self.vision.process_frame(image, grid_roi_norm=(0, 0, 1, 1))

    def test_one_closed_armour_frame_stays_one_physical_item(self):
        # The original visibly contains a gold clock 2x3, gold ticket 1x2,
        # and blue armour 3x3. The source card independently shows 3x3 armour.
        for scale in (1, 0.5):
            with self.subTest(scale=scale):
                image = self.board if scale == 1 else cv2.resize(
                    self.board, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                result = self.recognize(image)
                geometry = {(s['row'], s['col'], s['w'], s['h'], s['rarity']) for s in result['slots']}
                self.assertEqual(geometry, {(0, 0, 2, 3, 'gold'), (0, 7, 1, 2, 'gold'), (5, 0, 3, 3, 'blue')})
                self.assertEqual(len(result['slots']), 3)
                self.assertTrue(all(s['identityStatus'] != 'EXACT' for s in result['slots']))

    def test_partial_viewport_keeps_visible_ticket_spacing(self):
        # Cropping the empty right edge does not change the visible 56x112
        # ticket frame or the physical 56px gaps between its neighbouring cells.
        result = self.recognize(self.board[:, :505])
        ticket = [s for s in result['slots'] if s['row'] == 0 and s['col'] == 7]
        self.assertEqual(len(ticket), 1)
        self.assertEqual((ticket[0]['w'], ticket[0]['h']), (1, 2))
        self.assertEqual(tuple(ticket[0]['box'][2:]), (56, 112))
        # Eight full columns and a near-complete clipped ninth are visible;
        # the existing one-pixel edge observation must not invent a tenth.
        self.assertGreaterEqual(result['grid']['cols'], 8)
        self.assertLessEqual(result['grid']['cols'], 9)
        self.assertEqual(result['grid']['cellW'], 56)
        self.assertEqual(result['grid']['cellH'], 56)


if __name__ == '__main__':
    unittest.main()
