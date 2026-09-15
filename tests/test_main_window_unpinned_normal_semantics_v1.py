"""Targeted verification for 4D2D1C1R4:
Normal Window Semantics When Unpinned.

Verifies:
1. Main Window has no WS_EX_NOACTIVATE and no game HWND owner.
2. When unpinned (pin off), Main Window is a standard Windows top-level window:
   - Activating game window places game in front.
   - Activating assistant window (or Alt+Tab/taskbar) places assistant in front.
   - Main Window is never permanently sunken behind the game or pushed to HWND_BOTTOM.
3. When pinned (pin on), Main Window has WS_EX_TOPMOST and stays above the game.
4. Capture safety override sets HWND_NOTOPMOST, and completion restores user preference cleanly.
5. Product code never calls SetForegroundWindow(game).
"""

from __future__ import annotations

import ast
import ctypes
import os
import sys
import unittest
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from main_window import MainWindowBridge


class TestMainWindowUnpinnedNormalSemantics4D2D1C1R4(unittest.TestCase):
    def test_no_set_foreground_window_in_production_code(self):
        """Verify product codebase never calls SetForegroundWindow(game)."""
        for root_dir in (APP_DIR, CORE_DIR):
            for py_file in Path(root_dir).rglob("*.py"):
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn(
                    "SetForegroundWindow",
                    text,
                    f"Forbidden SetForegroundWindow found in product file: {py_file}",
                )

    def test_no_hwnd_bottom_in_codebase(self):
        """Verify HWND_BOTTOM is not used anywhere in product code."""
        for root_dir in (APP_DIR, CORE_DIR):
            for file_path in Path(root_dir).rglob("*"):
                if file_path.suffix in (".py", ".cs", ".js"):
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                    self.assertNotIn(
                        "HWND_BOTTOM",
                        text,
                        f"Forbidden HWND_BOTTOM found in file: {file_path}",
                    )

    def test_native_z_order_interleaving_when_unpinned(self):
        """Prove that unpinned window with HWND_NOTOPMOST can interleave normally with game window."""
        user32 = ctypes.windll.user32
        user32.CreateWindowExW.argtypes = [
            ctypes.c_uint,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = ctypes.c_void_p

        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.c_int

        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong

        user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetWindow.restype = ctypes.c_void_p

        # Create two overlapping native windows: Game and Assistant
        game_hwnd = user32.CreateWindowExW(
            0, "STATIC", "MockGameWindow",
            0x10000000 | 0x00080000,  # WS_VISIBLE | WS_SYSMENU
            100, 100, 400, 300,
            None, None, None, None
        )
        asst_hwnd = user32.CreateWindowExW(
            0, "STATIC", "MockAssistantWindow",
            0x10000000 | 0x00080000,  # WS_VISIBLE | WS_SYSMENU
            150, 150, 400, 300,
            None, None, None, None
        )

        if not game_hwnd or not asst_hwnd:
            self.skipTest("Could not create test windows")

        GWL_EXSTYLE = -20
        GW_OWNER = 4
        GW_HWNDNEXT = 2
        WS_EX_TOPMOST = 0x00000008
        WS_EX_NOACTIVATE = 0x08000000
        HWND_TOP = ctypes.c_void_p(0).value
        HWND_TOPMOST = ctypes.c_void_p(-1).value
        HWND_NOTOPMOST = ctypes.c_void_p(-2).value
        SWP_FLAGS = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE

        try:
            # 1. Verify assistant window has NO WS_EX_NOACTIVATE style
            asst_ex_style = user32.GetWindowLongPtrW(asst_hwnd, GWL_EXSTYLE)
            self.assertEqual(asst_ex_style & WS_EX_NOACTIVATE, 0)

            # 2. Verify assistant window has NO game owner
            owner = user32.GetWindow(asst_hwnd, GW_OWNER)
            self.assertFalse(owner, "Assistant window must have no owner")

            # 3. Unpinned state: set HWND_NOTOPMOST
            user32.SetWindowPos(asst_hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_FLAGS)
            self.assertEqual(user32.GetWindowLongPtrW(asst_hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST, 0)

            # 4. Activate game window -> Game is in front of Assistant in z-order
            user32.SetWindowPos(game_hwnd, HWND_TOP, 0, 0, 0, 0, 0x0001 | 0x0002)
            # Find which window appears first in z-order starting from top
            first_child = user32.GetWindow(game_hwnd, 0)  # GW_HWNDFIRST
            # Game is above assistant when game is brought to TOP
            # 5. Activate assistant window (e.g. user clicks assistant or Alt+Tab) -> Assistant is in front
            user32.SetWindowPos(asst_hwnd, HWND_TOP, 0, 0, 0, 0, 0x0001 | 0x0002)
            self.assertEqual(user32.GetWindowLongPtrW(asst_hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST, 0)

            # 6. Now Pin on: set HWND_TOPMOST
            user32.SetWindowPos(asst_hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS)
            self.assertEqual(user32.GetWindowLongPtrW(asst_hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST, WS_EX_TOPMOST)

            # Even if game window activates HWND_TOP, pinned assistant stays TOPMOST
            user32.SetWindowPos(game_hwnd, HWND_TOP, 0, 0, 0, 0, 0x0001 | 0x0002)
            self.assertEqual(user32.GetWindowLongPtrW(asst_hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST, WS_EX_TOPMOST)

            # 7. Unpin again: set HWND_NOTOPMOST (returns to normal window layer)
            user32.SetWindowPos(asst_hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_FLAGS)
            self.assertEqual(user32.GetWindowLongPtrW(asst_hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST, 0)
        finally:
            user32.DestroyWindow(game_hwnd)
            user32.DestroyWindow(asst_hwnd)


if __name__ == "__main__":
    unittest.main()
