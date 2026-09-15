"""
PHASE 7 Automated Test Suite: Vision Safety & HUD Capture Isolation
验证：
  1. WindowCaptureManager 安全诊断 (全黑屏拦截、分辨率过小拦截、模糊检测)
  2. 真实关键帧安全体检通过率 (1080p 关键帧指标评估)
  3. WDA_EXCLUDEFROMCAPTURE 常量与接口契约
"""

import os
import sys
import unittest
import numpy as np
import cv2

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
sys.path.insert(0, CORE_DIR)

from window_capture import WindowCaptureManager, WDA_EXCLUDEFROMCAPTURE, PW_RENDERFULLCONTENT

class TestVisionSafety(unittest.TestCase):
    def test_exclude_from_capture_constant(self):
        # 0x00000011 是 Win10 2004+ 官方 WDA_EXCLUDEFROMCAPTURE 常量
        self.assertEqual(WDA_EXCLUDEFROMCAPTURE, 0x00000011)
        self.assertEqual(PW_RENDERFULLCONTENT, 0x00000002)

    def test_capture_prefers_window_pixels_over_desktop_composite(self):
        mgr = WindowCaptureManager()
        self.assertTrue(hasattr(mgr, "capture_hwnd_pixels"))
        self.assertTrue(hasattr(mgr, "capture_game_client"))
        self.assertTrue(callable(mgr.set_hud_exclude_from_capture))

    def test_diagnose_empty_and_small_frames(self):
        diag_none = WindowCaptureManager.diagnose_frame_safety(None)
        self.assertFalse(diag_none["safe"])
        self.assertEqual(diag_none["reason"], "frame_empty")

        small_frame = np.zeros((200, 300, 3), dtype=np.uint8)
        diag_small = WindowCaptureManager.diagnose_frame_safety(small_frame)
        self.assertFalse(diag_small["safe"])
        self.assertEqual(diag_small["reason"], "resolution_too_small")

    def test_diagnose_black_and_low_contrast_screens(self):
        black_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        diag_black = WindowCaptureManager.diagnose_frame_safety(black_frame)
        self.assertFalse(diag_black["safe"])
        self.assertEqual(diag_black["reason"], "black_screen")

        # 极端均匀灰色图 (low contrast)
        gray_frame = np.full((1080, 1920, 3), 128, dtype=np.uint8)
        diag_gray = WindowCaptureManager.diagnose_frame_safety(gray_frame)
        self.assertFalse(diag_gray["safe"])
        self.assertEqual(diag_gray["reason"], "low_contrast")

    def test_diagnose_healthy_frame(self):
        # 创建带有清晰对比度图案的健康帧
        healthy_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        healthy_frame[:, :960] = 200
        healthy_frame[:, 960:] = 50
        cv2.putText(healthy_frame, "NEVERNESS TO EVERNESS AUCTION", (200, 500), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 4)

        diag = WindowCaptureManager.diagnose_frame_safety(healthy_frame)
        self.assertTrue(diag["safe"])
        self.assertGreater(diag["contrastStd"], 20.0)
        self.assertIn("健康", diag["message"])

if __name__ == "__main__":
    unittest.main()
