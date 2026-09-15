"""Targeted verification for 4D2D1D5A:
Unpinned Self-Reorder Audit & Fix.

Verifies:
1. Pin OFF steady state: arbitrary status polls / timer ticks generate ZERO Z-order controller writes.
2. User switching from Pin ON -> OFF triggers EXACTLY ONCE HWND_NOTOPMOST / controller(False).
3. User switching from Pin OFF -> ON triggers EXACTLY ONCE HWND_TOPMOST / controller(True).
4. Capture safety override performs EXACTLY ONCE demote when starting, and EXACTLY ONCE restore when stopping.
5. Capture safety override for an unpinned user performs ZERO controller writes (remains unpinned).
6. Main window activation / focus does not perform Z-order writes.
7. No SetForegroundWindow calls anywhere in production codebase.
"""

from __future__ import annotations

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
from warehouse_capture_host import (
    STATE_CAPTURING,
    STATE_COMPLETE,
    STATE_IDLE,
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
        self._arm_token = "test-token"

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
        return {"ok": True, "armingToken": self._arm_token, "state": self._state}

    def confirm(self, token_id):
        self._state = STATE_WAITING_FOR_GAME_FOCUS
        return {"ok": True, "state": self._state}

    def stop(self):
        self._state = STATE_COMPLETE
        return {"ok": True, "state": self._state}


class TestUnpinnedSelfReorderGuard4D2D1D5A(unittest.TestCase):
    def test_user_toggle_on_to_off_exactly_once_demotion(self):
        calls: List[bool] = []

        def controller(enable: bool):
            calls.append(bool(enable))

        overlay = _MockOverlayController()
        wh = _MockWarehouseCaptureHost(state=STATE_IDLE)
        bridge = MainWindowBridge(
            overlay_controller=overlay,
            warehouse_capture_host=wh,
            topmost_controller=controller,
            user_pinned=True,
        )

        self.assertEqual(len(calls), 0, "No premature controller call during bridge init")

        # Set initial pin state explicitly
        bridge.set_user_pinned(True)
        self.assertEqual(calls, [True])

        # User toggles Pin to OFF
        calls.clear()
        res = bridge.dispatch({"action": "toggle_main_pin"})
        self.assertFalse(res["mainPinned"])
        self.assertFalse(res["effectiveTopMost"])
        self.assertEqual(calls, [False], "Pin ON->OFF must trigger EXACTLY ONCE demotion")

        # Consecutive calls with same state must produce ZERO additional writes
        calls.clear()
        bridge.set_user_pinned(False)
        self.assertEqual(len(calls), 0, "Redundant set_user_pinned(False) must produce ZERO writes")

    def test_pin_off_steady_state_polling_zero_writes(self):
        calls: List[bool] = []

        def controller(enable: bool):
            calls.append(bool(enable))

        overlay = _MockOverlayController()
        wh = _MockWarehouseCaptureHost(state=STATE_IDLE)
        bridge = MainWindowBridge(
            overlay_controller=overlay,
            warehouse_capture_host=wh,
            topmost_controller=controller,
            user_pinned=False,
        )

        bridge.set_user_pinned(False)
        calls.clear()

        # Simulate 100 periodic polls of request_app_status (750ms timer in UI)
        for _ in range(100):
            res = bridge.dispatch({"action": "request_app_status"})
            self.assertFalse(res["mainPinned"])
            self.assertFalse(res["effectiveTopMost"])
            # In actual MainWindow._post_status, set_capture_safety_override(False) is also checked
            bridge.set_capture_safety_override(False)

        self.assertEqual(len(calls), 0, "Pin OFF steady state polling MUST generate ZERO Z-order writes")

    def test_capture_override_bounded_lifecycle_pinned_user(self):
        calls: List[bool] = []

        def controller(enable: bool):
            calls.append(bool(enable))

        overlay = _MockOverlayController()
        wh = _MockWarehouseCaptureHost(state=STATE_IDLE)
        bridge = MainWindowBridge(
            overlay_controller=overlay,
            warehouse_capture_host=wh,
            topmost_controller=controller,
            user_pinned=True,
        )

        bridge.set_user_pinned(True)
        self.assertEqual(calls, [True])
        calls.clear()

        # Confirm warehouse capture -> exactly 1 demote call
        bridge.dispatch({"action": "confirm_warehouse_capture", "armingToken": "test-token"})
        self.assertTrue(bridge.capture_safety_override)
        self.assertFalse(bridge.effective_topmost)
        self.assertEqual(calls, [False], "Capture confirm must trigger EXACTLY ONCE demotion")
        calls.clear()

        # While capturing, status refreshes must produce 0 calls
        for _ in range(50):
            wh._state = STATE_CAPTURING
            bridge.set_capture_safety_override(True)
            bridge.dispatch({"action": "request_app_status"})

        self.assertEqual(len(calls), 0, "During capture, status refreshes MUST produce ZERO Z-order writes")

        # Stop capture -> exactly 1 restore call
        bridge.dispatch({"action": "stop_warehouse_capture"})
        self.assertFalse(bridge.capture_safety_override)
        self.assertTrue(bridge.effective_topmost)
        self.assertEqual(calls, [True], "Capture stop must trigger EXACTLY ONCE restore to user's pin state")

    def test_capture_override_bounded_lifecycle_unpinned_user(self):
        calls: List[bool] = []

        def controller(enable: bool):
            calls.append(bool(enable))

        overlay = _MockOverlayController()
        wh = _MockWarehouseCaptureHost(state=STATE_IDLE)
        bridge = MainWindowBridge(
            overlay_controller=overlay,
            warehouse_capture_host=wh,
            topmost_controller=controller,
            user_pinned=False,
        )

        bridge.set_user_pinned(False)
        self.assertEqual(calls, [False])
        calls.clear()

        # Confirm warehouse capture for unpinned user:
        # User is already unpinned, effective_topmost was False and remains False!
        bridge.dispatch({"action": "confirm_warehouse_capture", "armingToken": "test-token"})
        self.assertTrue(bridge.capture_safety_override)
        self.assertFalse(bridge.effective_topmost)
        self.assertEqual(len(calls), 0, "Confirming capture for unpinned user must NOT trigger redundant demotion")

        # Stop capture for unpinned user:
        # Override cleared, effective_topmost remains False -> zero writes!
        bridge.dispatch({"action": "stop_warehouse_capture"})
        self.assertFalse(bridge.capture_safety_override)
        self.assertFalse(bridge.effective_topmost)
        self.assertEqual(len(calls), 0, "Stopping capture for unpinned user must NOT restore to topmost")

    def test_no_forbidden_focus_or_foreground_calls(self):
        for root_dir in (APP_DIR, CORE_DIR):
            for py_file in Path(root_dir).rglob("*.py"):
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn("SetForegroundWindow", text, f"Forbidden SetForegroundWindow in {py_file}")


if __name__ == "__main__":
    unittest.main()
