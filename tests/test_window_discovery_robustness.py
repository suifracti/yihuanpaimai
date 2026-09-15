import os
import sys
import unittest
from unittest.mock import Mock, patch

# Ensure core and app are in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app")))

import window_tracker
from window_tracker import (
    GameWindowTracker,
    is_real_game_window,
    score_window_candidate,
    ensure_default_desktop,
)
from window_capture import WindowCaptureManager
from warehouse_capture_host import (
    WarehouseCaptureHost,
    DISABLED_REASON_GAME_NOT_DETECTED,
    DISABLED_REASON_SETTLEMENT_NOT_DETECTED,
)


class WindowDiscoveryRobustnessTests(unittest.TestCase):
    def test_ensure_default_desktop_does_not_crash(self):
        res = ensure_default_desktop()
        self.assertIsInstance(res, bool)

    def test_game_scoring_high_confidence(self):
        # Simulate HTGame.exe / UnrealWindow / 异环
        with patch.object(window_tracker.win32gui, "IsWindow", return_value=True), \
             patch.object(window_tracker.win32gui, "IsWindowVisible", return_value=True), \
             patch.object(window_tracker.win32gui, "IsIconic", return_value=False), \
             patch.object(window_tracker.win32process, "GetWindowThreadProcessId", return_value=(999, 37324)), \
             patch.object(window_tracker.win32gui, "GetWindowText", return_value="异环  "), \
             patch.object(window_tracker.win32gui, "GetClassName", return_value="UnrealWindow"), \
             patch.object(window_tracker.win32gui, "GetWindowRect", return_value=(0, 0, 1920, 1080)), \
             patch.object(window_tracker, "_process_basename", return_value="htgame.exe"):

            score, reject_reason, meta = score_window_candidate(12345)
            self.assertIsNone(reject_reason)
            self.assertGreaterEqual(score, 100)
            self.assertEqual(meta["process"], "htgame.exe")
            self.assertEqual(meta["class"], "UnrealWindow")
            self.assertTrue(is_real_game_window(12345))

    def test_launcher_rejected(self):
        with patch.object(window_tracker.win32gui, "IsWindow", return_value=True), \
             patch.object(window_tracker.win32gui, "IsWindowVisible", return_value=True), \
             patch.object(window_tracker.win32gui, "IsIconic", return_value=False), \
             patch.object(window_tracker.win32process, "GetWindowThreadProcessId", return_value=(999, 1234)), \
             patch.object(window_tracker.win32gui, "GetWindowText", return_value="异环启动器"), \
             patch.object(window_tracker.win32gui, "GetClassName", return_value="Qt5QWindowIcon"), \
             patch.object(window_tracker.win32gui, "GetWindowRect", return_value=(0, 0, 1280, 720)), \
             patch.object(window_tracker, "_process_basename", return_value="launcher.exe"):

            score, reject_reason, meta = score_window_candidate(12345)
            self.assertEqual(reject_reason, "LAUNCHER_TITLE")
            self.assertFalse(is_real_game_window(12345))

    def test_hud_assistant_rejected(self):
        with patch.object(window_tracker.win32gui, "IsWindow", return_value=True), \
             patch.object(window_tracker.win32gui, "IsWindowVisible", return_value=True), \
             patch.object(window_tracker.win32gui, "IsIconic", return_value=False), \
             patch.object(window_tracker.win32process, "GetWindowThreadProcessId", return_value=(999, 5678)), \
             patch.object(window_tracker.win32gui, "GetWindowText", return_value="⚡ 异环拍卖战术助手 HUD"), \
             patch.object(window_tracker.win32gui, "GetClassName", return_value="WindowsForms10.Window.8"), \
             patch.object(window_tracker.win32gui, "GetWindowRect", return_value=(0, 0, 400, 500)), \
             patch.object(window_tracker, "_process_basename", return_value="异环拍卖助手.exe"):

            score, reject_reason, meta = score_window_candidate(12345)
            self.assertEqual(reject_reason, "HUD_OR_ASSISTANT_TITLE")
            self.assertFalse(is_real_game_window(12345))

    def test_own_process_rejected_without_reading_title(self):
        with patch.object(window_tracker.win32gui, "IsWindow", return_value=True), \
             patch.object(window_tracker.win32gui, "IsWindowVisible", return_value=True), \
             patch.object(window_tracker.win32gui, "IsIconic", return_value=False), \
             patch.object(window_tracker.win32process, "GetWindowThreadProcessId", return_value=(123, os.getpid())), \
             patch.object(window_tracker.win32gui, "GetWindowText", side_effect=AssertionError("deadlock")):

            score, reject_reason, meta = score_window_candidate(99999)
            self.assertEqual(reject_reason, "OWN_PROCESS")
            self.assertFalse(is_real_game_window(99999))

    def test_warehouse_host_evaluates_game_presence_with_dynamic_fallback(self):
        # Host with driver available, but snap has no hwnd
        host = WarehouseCaptureHost(session_factory=Mock(), driver_available=True)

        with patch.object(WindowCaptureManager, "find_game_hwnd", return_value=11014006):
            # snap is None, but game exists dynamically -> should NOT report GAME_NOT_DETECTED
            reason, msg = host._evaluate_disabled_reason()
            self.assertNotEqual(reason, DISABLED_REASON_GAME_NOT_DETECTED)
            self.assertEqual(reason, DISABLED_REASON_SETTLEMENT_NOT_DETECTED)

        with patch.object(WindowCaptureManager, "find_game_hwnd", return_value=0):
            # snap is None, game does not exist -> reports GAME_NOT_DETECTED
            reason, msg = host._evaluate_disabled_reason()
            self.assertEqual(reason, DISABLED_REASON_GAME_NOT_DETECTED)

    def test_live_game_discovery_if_running(self):
        tracker = GameWindowTracker()
        hwnd = tracker.find_game_window()
        if hwnd:
            score, reject_reason, meta = score_window_candidate(hwnd)
            self.assertIsNone(reject_reason)
            self.assertGreaterEqual(score, 50)
            mgr = WindowCaptureManager()
            pixels = mgr.capture_hwnd_pixels(hwnd)
            if pixels is not None:
                self.assertEqual(len(pixels.shape), 3)
                self.assertGreater(pixels.shape[0], 500)
                self.assertGreater(pixels.shape[1], 800)


if __name__ == "__main__":
    unittest.main()
