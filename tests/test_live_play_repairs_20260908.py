import unittest
from unittest.mock import Mock, patch
import numpy as np

from window_capture import WindowCaptureManager
from warehouse_capture_production import production_reconstruction_factory


class LivePlayRepairs(unittest.TestCase):
    def test_capture_uses_desktop_without_printwindow_and_rechecks_focus(self):
        manager = WindowCaptureManager()
        manager.user32 = Mock()
        manager.user32.GetForegroundWindow.side_effect = [123, 123, 123, 456]
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        manager._grab_client_mss = Mock(return_value=frame)
        manager.capture_hwnd_pixels = Mock(side_effect=AssertionError('PrintWindow must not run'))
        with patch('mss.mss'):
            self.assertIs(manager.capture_foreground_client(123), frame)
            self.assertIsNone(manager.capture_foreground_client(123))
        manager.capture_hwnd_pixels.assert_not_called()

    def test_capture_never_reads_background_window(self):
        manager = WindowCaptureManager()
        manager.user32 = Mock()
        manager.user32.GetForegroundWindow.return_value = 456
        with patch('mss.mss') as capture:
            self.assertIsNone(manager.capture_foreground_client(123))
            capture.assert_not_called()

    def test_catalog_features_are_deferred_until_reconstruction(self):
        with patch('warehouse_capture_production.get_production_placement_resolver') as factory:
            processor = production_reconstruction_factory('test-match')
            factory.assert_not_called()
            processor._placement_resolver.resolve(physical_ledger={}, descriptors=[], frames={})
            factory.assert_called_once()
