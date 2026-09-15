"""Native acceptance must close its application's Main window, not a browser."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from verify_p1_real_ui import MAIN_TITLE, OVERLAY_TITLE, source_window_pair


class SourceWindowSelectionTests(unittest.TestCase):
    def test_browser_title_does_not_replace_native_main(self):
        rows = {
            10: [{'hwnd': 100, 'title': MAIN_TITLE}],
            20: [{'hwnd': 200, 'title': MAIN_TITLE}, {'hwnd': 201, 'title': OVERLAY_TITLE}],
        }
        probe = Mock()
        probe.top_windows.side_effect = lambda pid, **kwargs: rows[pid]
        main, hud = source_window_pair(probe, {10, 20})
        self.assertEqual((main['hwnd'], hud['hwnd']), (200, 201))
        self.assertEqual(main['ownerPid'], hud['ownerPid'])

    def test_windows_from_different_processes_are_not_a_pair(self):
        rows = {10: [{'hwnd': 100, 'title': MAIN_TITLE}],
                20: [{'hwnd': 201, 'title': OVERLAY_TITLE}]}
        probe = Mock()
        probe.top_windows.side_effect = lambda pid, **kwargs: rows[pid]
        self.assertIsNone(source_window_pair(probe, {10, 20}))
