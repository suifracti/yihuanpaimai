"""
PHASE 8 Automated Test Suite: Multi-Resolution & DPI ROI Normalization
验证：
  1. 1080p (1920x1080), 1440p (2560x1440), 4K (3840x2160) 归一化等比缩放
  2. 21:9 带鱼屏 (3440x1440) Pillarbox 居中视口补偿
  3. 16:10 生产力屏 (1920x1200) Letterbox 上下视口补偿
  4. ROIScaler.crop_roi 图像切片边界有效性
"""

import os
import sys
import unittest
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
sys.path.insert(0, CORE_DIR)

from roi_scaler import ROIScaler, NORMALIZED_ROIS
from vision_pipeline import NTEVisionPipeline

class TestROIScaling(unittest.TestCase):
    def test_standard_1080p_and_1440p_scaling(self):
        # 1080p
        box_1080 = ROIScaler.scale_roi("header_round_timer", 1920, 1080)
        self.assertEqual(len(box_1080), 4)
        x1_1080, y1_1080, x2_1080, y2_1080 = box_1080
        self.assertGreater(x2_1080, x1_1080)
        self.assertGreater(y2_1080, y1_1080)

        # 1440p (2560x1440, exactly 1.333x of 1080p)
        box_1440 = ROIScaler.scale_roi("header_round_timer", 2560, 1440)
        x1_1440, y1_1440, x2_1440, y2_1440 = box_1440
        self.assertAlmostEqual(x1_1440 / 2560.0, x1_1080 / 1920.0, delta=0.01)
        self.assertAlmostEqual(y1_1440 / 1440.0, y1_1080 / 1080.0, delta=0.01)

    def test_production_seat_batch_uses_compensated_viewport(self):
        from unittest.mock import Mock
        import cv2
        frame = np.random.default_rng(42).integers(0, 256, (1080, 1920, 3), dtype=np.uint8)
        expected = [frame[int(1080*y):int(1080*b), int(1920*.120):int(1920*.215)]
                    for y,b in ((.225,.272),(.372,.419),(.520,.567),(.668,.715))]
        for padded in (frame, cv2.copyMakeBorder(frame,0,0,240,240,cv2.BORDER_CONSTANT),
                       cv2.copyMakeBorder(frame,60,60,0,0,cv2.BORDER_CONSTANT)):
            pipe = NTEVisionPipeline()
            engine = Mock()
            engine.text_rec.return_value = ([("0", .99)] * 4, 0)
            pipe._ocr_engine = engine
            pipe._ensure_ocr = lambda: engine
            self.assertEqual(pipe._run_df_seat_bids_shadow(padded), [0]*4)
            actual = engine.text_rec.call_args.args[0]
            self.assertEqual(len(actual), 4)
            for crop, original in zip(actual, expected):
                self.assertTrue(np.array_equal(crop, original))

    def test_ultrawide_21_9_viewport_compensation(self):
        # 3440 x 1440 (21:9) -> 内容区宽度应为 1440 * (16/9) = 2560, 左右各黑边 (3440-2560)//2 = 440
        vx, vy, vw, vh = ROIScaler.get_viewport_rect(3440, 1440)
        self.assertEqual(vx, 440)
        self.assertEqual(vy, 0)
        self.assertEqual(vw, 2560)
        self.assertEqual(vh, 1440)

        # 切片应位于视口内
        x1, y1, x2, y2 = ROIScaler.scale_roi("header_round_timer", 3440, 1440)
        self.assertGreaterEqual(x1, 440)
        self.assertLessEqual(x2, 440 + 2560)

    def test_16_10_viewport_compensation(self):
        # 1920 x 1200 (16:10) -> 内容区高度应为 1920 / (16/9) = 1080, 上下各黑边 (1200-1080)//2 = 60
        vx, vy, vw, vh = ROIScaler.get_viewport_rect(1920, 1200)
        self.assertEqual(vx, 0)
        self.assertEqual(vy, 60)
        self.assertEqual(vw, 1920)
        self.assertEqual(vh, 1080)

    def test_crop_roi_execution(self):
        frame_1440 = np.zeros((1440, 2560, 3), dtype=np.uint8)
        cropped = ROIScaler.crop_roi(frame_1440, "bid_slot_1_player")
        self.assertGreater(cropped.shape[0], 0)
        self.assertGreater(cropped.shape[1], 0)
        stack = NORMALIZED_ROIS["intel_card_stack"]
        board = NORMALIZED_ROIS["intel_board"]
        self.assertGreater(stack[3] - stack[1], board[3] - board[1])
        self.assertGreater(stack[3] - stack[1], 0.45)
        self.assertLess(stack[0], 0.40)
        self.assertGreater(stack[2], 0.64)
        for key in ("intel_card_stack", "lobby_venue_chip", "lobby_venue_search", "lobby_character_chip", "lobby_character_search", "lobby_tool_chip", "lobby_tool_search"):
            chip = ROIScaler.crop_roi(frame_1440, key)
            self.assertGreater(chip.shape[0], 0)
            self.assertGreater(chip.shape[1], 0)

if __name__ == "__main__":
    unittest.main()
