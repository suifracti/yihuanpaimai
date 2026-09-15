"""The live worker must never substitute desktop coordinates for client ROIs."""
import unittest
from unittest.mock import Mock, patch

import numpy as np
from game_frame_capture import capture_tracked_game_frame
from window_capture import WindowCaptureManager


class GameFrameCaptureTests(unittest.TestCase):
    def test_failed_client_capture_never_reads_desktop(self):
        sct = Mock()
        tracker = Mock()
        tracker.find_game_window.return_value = 123
        manager = Mock()
        manager.capture_game_client.return_value = (None, "none")
        hwnd, frame, timestamp, source = capture_tracked_game_frame(tracker, manager, sct, lambda _: True)
        self.assertEqual(hwnd, 123)
        self.assertIsNone(frame)
        self.assertEqual(source, "none")
        self.assertTrue(timestamp.endswith("+08:00"))
        sct.grab.assert_not_called()

    def test_missing_game_does_not_capture(self):
        tracker, manager, sct = Mock(), Mock(), Mock()
        tracker.find_game_window.return_value = None
        self.assertIsNone(capture_tracked_game_frame(tracker, manager, sct, lambda _: False)[0])
        manager.capture_game_client.assert_not_called()
        sct.grab.assert_not_called()

    def test_client_frame_is_returned_without_resize_or_crop(self):
        tracker, manager, sct = Mock(), Mock(), Mock()
        tracker.find_game_window.return_value = 123
        original = np.zeros((720, 1280, 3), dtype=np.uint8)
        manager.capture_game_client.return_value = (original, "mss")
        result = capture_tracked_game_frame(tracker, manager, sct, lambda _: True)
        self.assertIs(result[1], original)
        self.assertEqual(result[3], "mss")

    def test_invalid_printwindow_and_mss_frames_are_not_returned(self):
        manager = WindowCaptureManager()
        black = np.zeros((720, 1280, 3), dtype=np.uint8)
        for fallback in (None, black, np.zeros((10, 10, 3), dtype=np.uint8)):
            with self.subTest(shape=getattr(fallback, "shape", None)), \
                    patch.object(manager, "capture_hwnd_pixels", return_value=black), \
                    patch.object(manager, "_grab_client_mss", return_value=fallback):
                self.assertEqual(manager.capture_game_client(123, sct=Mock()), (None, "none"))

    def test_client_mss_fallback_remains_available(self):
        manager = WindowCaptureManager()
        black = np.zeros((720, 1280, 3), dtype=np.uint8)
        good = np.zeros_like(black)
        good[:, 640:] = 255
        with patch.object(manager, "capture_hwnd_pixels", return_value=black), \
                patch.object(manager, "_grab_client_mss", return_value=good):
            result, source = manager.capture_game_client(123, sct=Mock())
        self.assertIs(result, good)
        self.assertEqual(source, "mss")
