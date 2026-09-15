import os
import unittest
from unittest.mock import Mock, patch
import window_tracker
from window_capture import WindowCaptureManager

class WindowDiscoveryDeadlockTests(unittest.TestCase):
    def test_own_ui_is_rejected_before_a_synchronous_title_read(self):
        with patch.object(window_tracker.win32gui,'IsWindow',return_value=True), \
             patch.object(window_tracker.win32gui,'IsWindowVisible',return_value=True), \
             patch.object(window_tracker.win32process,'GetWindowThreadProcessId',return_value=(123,os.getpid())), \
             patch.object(window_tracker.win32gui,'GetWindowText',side_effect=AssertionError('would block on UI thread')) as title:
            self.assertFalse(window_tracker.is_real_game_window(7))
            title.assert_not_called()

    def test_capture_discovery_uses_real_game_gate_not_a_matching_app_title(self):
        manager=WindowCaptureManager()
        manager.user32=Mock()
        with patch.object(window_tracker.GameWindowTracker,'find_game_window',return_value=None) as finder:
            self.assertIsNone(manager.find_game_hwnd())
        finder.assert_called_once()
        manager.user32.EnumWindows.assert_not_called()
