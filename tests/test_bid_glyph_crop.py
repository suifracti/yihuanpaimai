import unittest
import numpy as np
import cv2
from bid_glyph_crop import compact_bid_glyph

class BidGlyphCropTests(unittest.TestCase):
    def test_blank_edges_wide_and_offcenter_remain_unchanged(self):
        for box in (None,(0,10,10,40),(90,0,115,40),(20,10,180,45),(10,10,25,45)):
            crop=np.zeros((68,244,3),dtype=np.uint8)
            if box: cv2.rectangle(crop,box[:2],box[2:],(0,200,255),-1)
            self.assertIsNone(compact_bid_glyph(crop))
    def test_compact_keeps_all_colored_pixels_and_padding(self):
        crop=np.zeros((68,244,3),dtype=np.uint8)
        cv2.ellipse(crop,(122,34),(10,14),0,0,360,(0,200,255),3)
        compact=compact_bid_glyph(crop)
        self.assertIsNotNone(compact)
        self.assertLess(compact.shape[1],crop.shape[1])
        self.assertEqual(np.count_nonzero(compact),np.count_nonzero(crop))
    def test_separate_digit_fragment_prevents_single_digit_selection(self):
        crop=np.zeros((68,244,3),dtype=np.uint8)
        cv2.ellipse(crop,(122,34),(10,14),0,0,360,(0,200,255),3)
        cv2.rectangle(crop,(40,20),(45,45),(0,200,255),-1)
        self.assertIsNone(compact_bid_glyph(crop))
