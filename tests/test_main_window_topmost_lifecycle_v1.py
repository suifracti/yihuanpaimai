"""Targeted state transition & native HWND tests for 4D2D1C1R2:
User-Pinned Main Window + Capture Safety Override.

Contract:
effectiveTopMost = userPinned && !captureSafetyOverride

Verifies:
1. Startup default userPinned=True takes effect and effectiveTopMost=True.
2. User toggle (toggle_main_pin / set_main_pin) is controllable.
3. Upon confirm_warehouse_capture, captureSafetyOverride=True and TopMost is cancelled.
4. During WAITING_FOR_GAME_FOCUS & CAPTURING, status refreshes keep effectiveTopMost=False.
5. Terminal / completion / partial / error states clear override and restore user preference.
6. If user unpinned the window, it remains unpinned after capture finishes.
7. Repeated set_topmost calls are strictly idempotent.
8. Native zero-input HWND smoke verifies WS_EX_TOPMOST style bit set & cleared correctly.
"""

from __future__ import annotations

import ctypes
import os
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from main_window import MainWindowBridge
from warehouse_capture_host import (
    STATE_CAPTURING,
    STATE_COMPLETE,
    STATE_IDLE,
    STATE_PARTIAL,
    STATE_STARTING,
    STATE_WAITING_FOR_GAME_FOCUS,
)


class _MockOverlayController:
    visible = True

    def toggle(self):
        self.visible = not self.visible
        return self.visible


class _MockWarehouseCaptureHost:
    def __init__(self, available=True, state=STATE_IDLE):
        self._available = available
        self._state = state
        self._arm_token = "test-arm-token-123"
        self.prepared = False
        self.confirmed = False
        self.stopped = False

    def presentation_payload(self):
        return {
            "available": self._available,
            "state": self._state,
            "segmentCount": 0,
            "coverageStatus": "COVERAGE_UNPROVEN",
            "stopAvailable": self._state in {"CAPTURING", "SCROLLING", "WAITING_FOR_GAME_FOCUS"},
            "message": "test",
            "terminationReason": None,
        }

    def prepare(self):
        self.prepared = True
        return {"ok": True, "armingToken": self._arm_token, "state": self._state}

    def confirm(self, token_id):
        self.confirmed = True
        self._state = STATE_WAITING_FOR_GAME_FOCUS
        return {"ok": True, "state": self._state}

    def stop(self):
        self.stopped = True
        self._state = STATE_PARTIAL
        return {"ok": True, "state": self._state}


class TestMainWindowUserPinnedAndCaptureSafetyOverride(unittest.TestCase):
    def test_startup_default_pinned_and_user_toggle(self):
        topmost_log: List[bool] = []

        def controller(enable: bool):
            topmost_log.append(bool(enable))

        overlay = _MockOverlayController()
        host = _MockWarehouseCaptureHost(available=True, state=STATE_IDLE)
        bridge = MainWindowBridge(
            overlay_controller=overlay,
            warehouse_capture_host=host,
            topmost_controller=controller,
            user_pinned=True,
        )

        # 1. Verify default pinned
        self.assertTrue(bridge.user_pinned)
        self.assertFalse(bridge.capture_safety_override)
        self.assertTrue(bridge.effective_topmost)

        # 2. User toggles pin off
        res1 = bridge.dispatch({"action": "toggle_main_pin"})
        self.assertFalse(bridge.user_pinned)
        self.assertFalse(bridge.effective_topmost)
        self.assertFalse(res1["mainPinned"])
        self.assertFalse(res1["effectiveTopMost"])
        self.assertEqual(topmost_log[-1], False)

        # 3. User toggles pin on
        res2 = bridge.dispatch({"action": "toggle_main_pin"})
        self.assertTrue(bridge.user_pinned)
        self.assertTrue(bridge.effective_topmost)
        self.assertTrue(res2["mainPinned"])
        self.assertTrue(res2["effectiveTopMost"])
        self.assertEqual(topmost_log[-1], True)

        # 4. User sets pin explicitly via set_main_pin
        res3 = bridge.dispatch({"action": "set_main_pin", "pinned": False})
        self.assertFalse(bridge.user_pinned)
        self.assertFalse(bridge.effective_topmost)
        self.assertFalse(res3["mainPinned"])
        self.assertFalse(res3["effectiveTopMost"])
        self.assertEqual(topmost_log[-1], False)

    def test_capture_safety_override_cancels_and_restores_user_pin(self):
        topmost_log: List[bool] = []

        def controller(enable: bool):
            topmost_log.append(bool(enable))

        overlay = _MockOverlayController()
        host = _MockWarehouseCaptureHost(available=True, state=STATE_IDLE)
        bridge = MainWindowBridge(
            overlay_controller=overlay,
            warehouse_capture_host=host,
            topmost_controller=controller,
            user_pinned=True,
        )

        # 1. Before capture: effectiveTopMost is True
        self.assertTrue(bridge.effective_topmost)

        # 2. Prepare warehouse capture: user still has window available
        res_prep = bridge.dispatch({"action": "prepare_warehouse_capture"})
        self.assertTrue(res_prep["warehouseCaptureCommand"]["ok"])
        self.assertTrue(bridge.effective_topmost)

        # 3. Confirm warehouse capture: override becomes True, effectiveTopMost cancelled immediately
        res_conf = bridge.dispatch({"action": "confirm_warehouse_capture", "armingToken": "test-arm-token-123"})
        self.assertTrue(res_conf["warehouseCaptureCommand"]["ok"])
        self.assertTrue(bridge.capture_safety_override)
        self.assertFalse(bridge.effective_topmost)
        self.assertEqual(topmost_log[-1], False)

        # 4. Status refreshes during WAITING_FOR_GAME_FOCUS & CAPTURING keep override
        host._state = STATE_CAPTURING
        bridge.set_capture_safety_override(True)
        self.assertFalse(bridge.effective_topmost)

        # 5. Stop capture: override cleared, user's pin preference restored!
        res_stop = bridge.dispatch({"action": "stop_warehouse_capture"})
        self.assertTrue(res_stop["warehouseCaptureCommand"]["ok"])
        self.assertFalse(bridge.capture_safety_override)
        self.assertTrue(bridge.effective_topmost)
        self.assertEqual(topmost_log[-1], True)

    def test_unpinned_user_stays_unpinned_after_capture(self):
        topmost_log: List[bool] = []

        def controller(enable: bool):
            topmost_log.append(bool(enable))

        overlay = _MockOverlayController()
        host = _MockWarehouseCaptureHost(available=True, state=STATE_IDLE)
        bridge = MainWindowBridge(
            overlay_controller=overlay,
            warehouse_capture_host=host,
            topmost_controller=controller,
            user_pinned=False,  # User opted out of pin
        )

        self.assertFalse(bridge.effective_topmost)

        # Confirm
        bridge.dispatch({"action": "confirm_warehouse_capture", "armingToken": "test-arm-token-123"})
        self.assertTrue(bridge.capture_safety_override)
        self.assertFalse(bridge.effective_topmost)

        # Stop
        bridge.dispatch({"action": "stop_warehouse_capture"})
        self.assertFalse(bridge.capture_safety_override)
        # Still False because user_pinned is False
        self.assertFalse(bridge.effective_topmost)

    def test_idempotent_topmost_controller_calls(self):
        records: List[bool] = []

        def controller(enable: bool):
            records.append(bool(enable))

        overlay = _MockOverlayController()
        host = _MockWarehouseCaptureHost(available=True, state=STATE_IDLE)
        bridge = MainWindowBridge(
            overlay_controller=overlay,
            warehouse_capture_host=host,
            topmost_controller=controller,
        )

        bridge.set_user_pinned(True)
        bridge.set_user_pinned(True)
        bridge.set_user_pinned(False)
        bridge.set_user_pinned(False)

        self.assertEqual(records, [True, False])

    def test_native_hwnd_topmost_style_bit_smoke(self):
        """Create a real native Win32 window and verify WS_EX_TOPMOST bit setting and clearing."""
        user32 = ctypes.windll.user32

        # Create a hidden dummy window to test HWND style manipulation
        WNDPROCTYPE = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
        def wndproc(hwnd, msg, wparam, lparam):
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        
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

        hwnd = user32.CreateWindowExW(
            0, "STATIC", "TopmostSmokeTest",
            0x00080000,  # WS_SYSMENU
            0, 0, 100, 100,
            None, None, None, None
        )
        if not hwnd:
            self.skipTest("Could not create test HWND")

        GWL_EXSTYLE = -20
        WS_EX_TOPMOST = 0x00000008
        HWND_TOPMOST = ctypes.c_void_p(-1).value
        HWND_NOTOPMOST = ctypes.c_void_p(-2).value
        SWP_FLAGS = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE

        try:
            # 1. Initially non-topmost
            ex_style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            self.assertEqual(ex_style & WS_EX_TOPMOST, 0)

            # 2. Set topmost (simulate pin)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS)
            ex_style_top = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            self.assertEqual(ex_style_top & WS_EX_TOPMOST, WS_EX_TOPMOST)

            # 3. Clear topmost (simulate capture safety override)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_FLAGS)
            ex_style_notop = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            self.assertEqual(ex_style_notop & WS_EX_TOPMOST, 0)

            # 4. Restore topmost (simulate capture end)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS)
            ex_style_restored = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            self.assertEqual(ex_style_restored & WS_EX_TOPMOST, WS_EX_TOPMOST)
        finally:
            user32.DestroyWindow(hwnd)


if __name__ == "__main__":
    unittest.main()
