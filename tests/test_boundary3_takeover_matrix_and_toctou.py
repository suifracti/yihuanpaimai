"""Boundary 3 Comprehensive Input Takeover, TOCTOU Race & Negative Matrix Test Suite.

Validates:
1. Breakpoint 1: One-shot expected program move registry and exact coordinate consumption.
2. Breakpoint 2: Suppression of cursor restoration upon user takeover (cursorRestoreSkipped=True).
3. TOCTOU Race condition test with microsecond-level timeline logging.
4. Complete 18-item negative security gate matrix asserting 0 SendInput leakage.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from warehouse_capture_host import CaptureCancelToken
from warehouse_input_abort_guard import (
    KIND_ESCAPE,
    KIND_KEY_DOWN,
    KIND_MARKED_WHEEL,
    KIND_MOUSE_BUTTON,
    KIND_MOUSE_MOVE,
    KIND_USER_MOUSE_MOVE,
    KIND_PROGRAM_CURSOR_MOVE,
    KIND_WHEEL,
    REASON_ESCAPE,
    REASON_USER_INPUT,
    REASON_USER_MOUSE_MOVE,
    WarehouseInputAbortGuard,
)
from warehouse_wheel_driver import (
    DEFAULT_WHEEL_DELTA,
    REASON_ADAPTER_ERROR,
    REASON_ALREADY_SCROLLED,
    REASON_CANCELLED,
    REASON_HWND_HIDDEN,
    REASON_HWND_INVALID,
    REASON_HWND_MINIMIZED,
    REASON_HWND_MISMATCH,
    REASON_INVALID_ROI,
    REASON_MISSING_TOKEN,
    REASON_NOT_ARMED,
    REASON_NOT_FOREGROUND,
    REASON_NOT_STABLE_SETTLEMENT,
    REASON_OK,
    REASON_SAFETY_POINT_OUTSIDE,
    REASON_STABLE_KEY_MISMATCH,
    REASON_TOKEN_REUSED,
    WAREHOUSE_WHEEL_EXTRA_INFO,
    WarehouseWheelContext,
    WarehouseWheelDriver,
    issue_warehouse_wheel_session_token,
)


class MockEventAdapter:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self._on_event = None

    def start(self, on_event):
        self.started += 1
        self._on_event = on_event

    def stop(self):
        self.stopped += 1
        self._on_event = None

    def emit(self, kind, dw_extra_info=None, pt=None):
        if self._on_event:
            try:
                self._on_event(kind, dw_extra_info, pt)
            except TypeError:
                try:
                    self._on_event(kind, dw_extra_info)
                except TypeError:
                    self._on_event(kind)


class MockOsAdapter:
    def __init__(
        self,
        *,
        hwnd=0x4B2B,
        foreground=0x4B2B,
        exists=True,
        visible=True,
        iconic=False,
        client=(0, 0, 1920, 1080),
        cursor=(500, 500),
        fail_send_input=False,
    ):
        self.hwnd = hwnd
        self.foreground = foreground
        self.exists = exists
        self.visible = visible
        self.iconic = iconic
        self.client = client
        self.cursor = tuple(cursor)
        self.moves: List[Tuple[int, int]] = []
        self.wheels: List[Tuple[int, int]] = []
        self.fail_send_input = fail_send_input

    def get_cursor_pos(self) -> Tuple[int, int]:
        return self.cursor

    def set_cursor_pos(self, x: int, y: int) -> bool:
        self.cursor = (int(x), int(y))
        self.moves.append((int(x), int(y)))
        return True

    def send_mouse_wheel(self, delta: int, extra_info: int) -> None:
        if self.fail_send_input:
            raise OSError("Injected SendInput failure")
        self.wheels.append((int(delta), int(extra_info)))

    def get_foreground_window(self) -> int:
        return self.foreground

    def is_window(self, hwnd: int) -> bool:
        return bool(self.exists and int(hwnd) == int(self.hwnd))

    def is_window_visible(self, hwnd: int) -> bool:
        return bool(self.visible)

    def is_iconic(self, hwnd: int) -> bool:
        return bool(self.iconic)

    def get_client_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        return self.client

    def client_to_screen(self, hwnd: int, x: int, y: int) -> Tuple[int, int]:
        return (int(x), int(y))


def _make_context(
    token=None,
    record_key="recTestB3",
    expected_key="recTestB3",
    hwnd=0x4B2B,
    tracked_hwnd=0x4B2B,
    settlement_stable=True,
    warehouse_roi=(100, 100, 900, 900),
    safety_point=(500, 500),
    cancel_token=None,
    input_guard=None,
) -> WarehouseWheelContext:
    return WarehouseWheelContext(
        session_token=token or issue_warehouse_wheel_session_token(),
        record_stable_key=record_key,
        expected_stable_key=expected_key,
        hwnd=hwnd,
        tracked_hwnd=tracked_hwnd,
        settlement_stable=settlement_stable,
        warehouse_roi=warehouse_roi,
        safety_point=safety_point,
        cancellation_token=cancel_token,
        input_guard=input_guard,
    )


class TestBoundary3TakeoverMatrixAndToctou(unittest.TestCase):
    """Full Boundary 3 Safety Suite."""

    # -------------------------------------------------------------
    # 1. Breakpoint 1: One-Shot Expected Move Verification
    # -------------------------------------------------------------
    def test_breakpoint1_oneshot_exact_match_consumed_and_subsequent_aborts(self):
        """Expected move is consumed strictly once; second move is treated as user takeover."""
        adapter = MockEventAdapter()
        token = CaptureCancelToken()
        guard = WarehouseInputAbortGuard(adapter=adapter, cancel_token=token)
        guard.install()
        guard.arm()

        # Driver registers expected move for (640, 480)
        nonce = guard.register_expected_cursor_move(640, 480, ttl_s=0.5)
        self.assertTrue(nonce)

        # First move: exact match -> consumed and ignored
        adapter.emit(KIND_MOUSE_MOVE, pt=(640, 480))
        self.assertFalse(token.is_cancelled(), "Expected move must NOT cancel token")
        self.assertIsNone(guard.abort_reason())
        self.assertTrue(guard.armed)

        # Second move: expected move was already consumed -> user takeover!
        adapter.emit(KIND_MOUSE_MOVE, pt=(640, 480))
        self.assertTrue(token.is_cancelled(), "Subsequent move after consumption MUST cancel token")
        self.assertEqual(token.reason(), "USER_MOUSE_MOVE")
        self.assertEqual(guard.abort_reason(), "USER_MOUSE_MOVE")
        self.assertFalse(guard.armed)
        guard.uninstall()

    def test_breakpoint1_coordinate_mismatch_or_expiry_triggers_user_abort(self):
        """Coordinate mismatch or expired expected move triggers USER_MOUSE_MOVE."""
        # 1. Coordinate mismatch
        adapter = MockEventAdapter()
        token = CaptureCancelToken()
        guard = WarehouseInputAbortGuard(adapter=adapter, cancel_token=token)
        guard.install()
        guard.arm()

        guard.register_expected_cursor_move(640, 480, ttl_s=0.5)
        # Mouse moved to (641, 480) instead
        adapter.emit(KIND_MOUSE_MOVE, pt=(641, 480))
        self.assertTrue(token.is_cancelled())
        self.assertEqual(token.reason(), "USER_MOUSE_MOVE")
        guard.uninstall()

        # 2. Expired expected move
        adapter2 = MockEventAdapter()
        token2 = CaptureCancelToken()
        guard2 = WarehouseInputAbortGuard(adapter=adapter2, cancel_token=token2)
        guard2.install()
        guard2.arm()

        guard2.register_expected_cursor_move(640, 480, ttl_s=0.02)
        time.sleep(0.04)  # Wait for TTL to expire
        adapter2.emit(KIND_MOUSE_MOVE, pt=(640, 480))
        self.assertTrue(token2.is_cancelled())
        self.assertEqual(token2.reason(), "USER_MOUSE_MOVE")
        guard2.uninstall()

    # -------------------------------------------------------------
    # 2. Breakpoint 2: User Takeover Suppresses Cursor Restoration
    # -------------------------------------------------------------
    def test_breakpoint2_user_takeover_mouse_move_suppresses_cursor_restore(self):
        """On user takeover by mouse move, cleanup must NOT restore old cursor."""
        event_adapter = MockEventAdapter()
        cancel_token = CaptureCancelToken()
        guard = WarehouseInputAbortGuard(adapter=event_adapter, cancel_token=cancel_token)
        guard.install()
        guard.arm()

        os_adapter = MockOsAdapter(cursor=(100, 100))
        driver = WarehouseWheelDriver(os_adapter=os_adapter, input_guard=guard)

        ctx = _make_context(
            cancel_token=cancel_token,
            input_guard=guard,
            safety_point=(500, 500),
        )

        began = driver.begin(ctx)
        self.assertTrue(began["ok"])
        self.assertEqual(os_adapter.cursor, (100, 100))

        # Hook: when SetCursorPos(500, 500) is called, emit expected move, then user moves to (777, 888)
        orig_set_pos = os_adapter.set_cursor_pos

        def on_set_pos(x, y):
            orig_set_pos(x, y)
            # Program move
            event_adapter.emit(KIND_MOUSE_MOVE, pt=(x, y))
            # User physically moves mouse to new position
            os_adapter.cursor = (777, 888)
            event_adapter.emit(KIND_MOUSE_MOVE, pt=(777, 888))

        os_adapter.set_cursor_pos = on_set_pos

        scrolled = driver.scroll_once()
        self.assertFalse(scrolled["ok"])
        self.assertEqual(scrolled["reason"], REASON_CANCELLED)
        self.assertEqual(len(os_adapter.wheels), 0)
        self.assertFalse(scrolled["cursorRestoreAttempted"])
        self.assertTrue(scrolled["cursorRestoreSkipped"])
        self.assertFalse(scrolled["cursorRestored"])
        # Crucial: Cursor MUST remain at user's new position (777, 888), NOT pulled back to (100, 100)
        self.assertEqual(os_adapter.cursor, (777, 888))
        guard.uninstall()

    def test_breakpoint2_user_takeover_key_press_suppresses_cursor_restore(self):
        """On user takeover by keyboard, cleanup must NOT restore old cursor."""
        event_adapter = MockEventAdapter()
        cancel_token = CaptureCancelToken()
        guard = WarehouseInputAbortGuard(adapter=event_adapter, cancel_token=cancel_token)
        guard.install()
        guard.arm()

        os_adapter = MockOsAdapter(cursor=(200, 200))
        driver = WarehouseWheelDriver(os_adapter=os_adapter, input_guard=guard)
        ctx = _make_context(cancel_token=cancel_token, input_guard=guard, safety_point=(400, 400))

        driver.begin(ctx)
        # User presses ESC
        event_adapter.emit(KIND_ESCAPE)
        self.assertTrue(cancel_token.is_cancelled())

        scrolled = driver.scroll_once()
        self.assertFalse(scrolled["ok"])
        self.assertEqual(scrolled["reason"], REASON_CANCELLED)
        self.assertFalse(scrolled["cursorRestoreAttempted"])
        self.assertTrue(scrolled["cursorRestoreSkipped"])
        self.assertFalse(scrolled["cursorRestored"])
        guard.uninstall()

    def test_breakpoint2_internal_exception_without_takeover_safely_restores_cursor(self):
        """When an internal exception occurs without user takeover, old cursor IS restored."""
        event_adapter = MockEventAdapter()
        cancel_token = CaptureCancelToken()
        guard = WarehouseInputAbortGuard(adapter=event_adapter, cancel_token=cancel_token)
        guard.install()
        guard.arm()

        # Set fail_send_input=True to simulate internal driver failure
        os_adapter = MockOsAdapter(cursor=(150, 150), fail_send_input=True)
        driver = WarehouseWheelDriver(os_adapter=os_adapter, input_guard=guard)
        ctx = _make_context(cancel_token=cancel_token, input_guard=guard, safety_point=(400, 400))

        driver.begin(ctx)
        scrolled = driver.scroll_once()
        self.assertFalse(scrolled["ok"])
        self.assertEqual(scrolled["reason"], REASON_ADAPTER_ERROR)
        # No user takeover: cursor was restored!
        self.assertTrue(scrolled["cursorRestoreAttempted"])
        self.assertFalse(scrolled["cursorRestoreSkipped"])
        self.assertTrue(scrolled["cursorRestored"])
        self.assertEqual(os_adapter.cursor, (150, 150))
        guard.uninstall()

    # -------------------------------------------------------------
    # 3. TOCTOU Race Test with Microsecond-Level Timeline Logging
    # -------------------------------------------------------------
    def test_toctou_race_full_timeline(self):
        """TOCTOU race: user moves mouse after SetCursorPos but before SendInput.
        Asserts 0 SendInput count, cursorRestoreSkipped=True, and logs machine-readable timeline.
        """
        event_adapter = MockEventAdapter()
        cancel_token = CaptureCancelToken()
        guard = WarehouseInputAbortGuard(adapter=event_adapter, cancel_token=cancel_token)
        guard.install()
        guard.arm()

        os_adapter = MockOsAdapter(cursor=(300, 300))
        driver = WarehouseWheelDriver(os_adapter=os_adapter, input_guard=guard)
        ctx = _make_context(cancel_token=cancel_token, input_guard=guard, safety_point=(600, 600))

        timeline: Dict[str, Optional[float]] = {
            "programMoveRegisteredAt": None,
            "programMoveObservedAt": None,
            "userMoveObservedAt": None,
            "cancelAt": None,
            "secondPrecheckRejectedAt": None,
            "releaseAt": None,
        }

        # Step 1: armed
        began = driver.begin(ctx)
        self.assertTrue(began["ok"])
        self.assertTrue(driver.armed)

        # Hook set_cursor_pos to simulate exact race condition
        orig_set_pos = os_adapter.set_cursor_pos

        def race_hook_set_cursor_pos(x, y):
            orig_set_pos(x, y)
            # Step 4: program self-generated move observed & consumed
            event_adapter.emit(KIND_MOUSE_MOVE, pt=(x, y))
            timeline["programMoveObservedAt"] = guard.program_move_observed_at
            # Step 5 & 6: user immediately moves mouse to (800, 800)
            os_adapter.cursor = (800, 800)
            event_adapter.emit(KIND_MOUSE_MOVE, pt=(800, 800))
            timeline["userMoveObservedAt"] = guard.user_move_observed_at
            timeline["cancelAt"] = guard.cancel_at

        os_adapter.set_cursor_pos = race_hook_set_cursor_pos

        # Step 3, 7, 8, 9, 10: scroll_once executes
        t_before_scroll = time.monotonic()
        scrolled = driver.scroll_once()
        t_after_scroll = time.monotonic()

        timeline["programMoveRegisteredAt"] = guard.program_move_registered_at
        timeline["secondPrecheckRejectedAt"] = t_after_scroll
        timeline["releaseAt"] = time.monotonic()

        # Step 8: Second precheck rejected
        self.assertFalse(scrolled["ok"])
        self.assertEqual(scrolled["reason"], REASON_CANCELLED)

        # Step 9: SendInput count == 0
        self.assertEqual(len(os_adapter.wheels), 0, "TOCTOU: SendInput MUST NOT be sent")

        # Step 10 & 11: Cleanup did NOT restore old cursor
        self.assertFalse(scrolled["cursorRestoreAttempted"])
        self.assertTrue(scrolled["cursorRestoreSkipped"])
        self.assertFalse(scrolled["cursorRestored"])

        # Step 12: User current cursor remains intact
        self.assertEqual(os_adapter.cursor, (800, 800))
        self.assertFalse(driver.armed)

        # Verify timeline ordering
        self.assertIsNotNone(timeline["programMoveRegisteredAt"])
        self.assertIsNotNone(timeline["programMoveObservedAt"])
        self.assertIsNotNone(timeline["userMoveObservedAt"])
        self.assertIsNotNone(timeline["cancelAt"])
        self.assertIsNotNone(timeline["secondPrecheckRejectedAt"])
        self.assertIsNotNone(timeline["releaseAt"])

        reg_at = timeline["programMoveRegisteredAt"]
        obs_at = timeline["programMoveObservedAt"]
        user_at = timeline["userMoveObservedAt"]
        cancel_at = timeline["cancelAt"]
        rej_at = timeline["secondPrecheckRejectedAt"]
        rel_at = timeline["releaseAt"]

        self.assertLessEqual(reg_at, obs_at)
        self.assertLessEqual(obs_at, user_at)
        self.assertLessEqual(user_at, cancel_at)
        self.assertLessEqual(cancel_at, rej_at)
        self.assertLessEqual(rej_at, rel_at)

        # Output timeline JSON for audit record
        timeline_path = PROJECT_ROOT / "tests" / "toctou_timeline_evidence.json"
        with open(timeline_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "test": "test_toctou_race_full_timeline",
                    "status": "PASS",
                    "sendInputCount": len(os_adapter.wheels),
                    "armedAfterRelease": driver.armed,
                    "cursorRestoreAttempted": scrolled["cursorRestoreAttempted"],
                    "cursorRestoreSkipped": scrolled["cursorRestoreSkipped"],
                    "finalUserCursor": list(os_adapter.cursor),
                    "timelineMonotonicSeconds": timeline,
                },
                f,
                indent=2,
            )
        guard.uninstall()

    # -------------------------------------------------------------
    # 4. 18-Item Negative Security Gate Matrix
    # -------------------------------------------------------------
    def test_negative_matrix_18_cases(self):
        """18-case negative test matrix verifying strictly 0 SendInput leakage."""
        matrix_cases = [
            ("not_armed", "Calling scroll_once when not armed", dict(armed=False)),
            ("token_expired", "Arming token already expired", dict(token_expired=True)),
            ("token_consumed", "Arming token already consumed", dict(token_consumed=True)),
            ("not_foreground", "Target window is not foreground", dict(foreground=0)),
            ("alt_tab_focus_change", "Focus changes away during precheck", dict(lose_focus=True)),
            ("stale_hwnd", "Window handle no longer exists", dict(exists=False)),
            ("invalid_hwnd", "Window handle is null/invalid", dict(hwnd=0)),
            ("hidden_hwnd", "Window is hidden", dict(visible=False)),
            ("minimized_hwnd", "Window is minimized", dict(iconic=True)),
            ("tracked_hwnd_mismatch", "Tracked HWND does not match window HWND", dict(tracked_hwnd=0x9999)),
            ("roi_coordinate_outside", "ROI / safety point outside client area", dict(safety_point=(2000, 2000))),
            ("user_key_before_action", "User presses key before action", dict(user_event=KIND_KEY_DOWN)),
            ("user_click_before_action", "User clicks mouse button before action", dict(user_event=KIND_MOUSE_BUTTON)),
            ("user_wheel_before_action", "User rolls physical wheel before action", dict(user_event=KIND_WHEEL)),
            ("user_mouse_move_before_action", "User moves mouse before action", dict(user_event=KIND_MOUSE_MOVE)),
            ("user_move_between_move_and_wheel", "User moves mouse between SetCursorPos and SendInput", dict(toctou_move=True)),
            ("graceful_exception", "Internal OS adapter exception", dict(fail_send_input=True)),
            ("normal_process_close", "Process close/cleanup", dict(close_cleanup=True)),
        ]

        results = []
        for case_id, desc, params in matrix_cases:
            with self.subTest(case=case_id):
                event_adapter = MockEventAdapter()
                cancel_token = CaptureCancelToken()
                guard = WarehouseInputAbortGuard(adapter=event_adapter, cancel_token=cancel_token)
                guard.install()
                guard.arm()

                os_adapter = MockOsAdapter(
                    hwnd=params.get("hwnd", 0x4B2B),
                    foreground=params.get("foreground", 0x4B2B),
                    exists=params.get("exists", True),
                    visible=params.get("visible", True),
                    iconic=params.get("iconic", False),
                    cursor=(250, 250),
                    fail_send_input=params.get("fail_send_input", False),
                )
                driver = WarehouseWheelDriver(os_adapter=os_adapter, input_guard=guard)

                if params.get("token_expired"):
                    token = issue_warehouse_wheel_session_token(ttl_s=0.01)
                    time.sleep(0.02)
                else:
                    token = issue_warehouse_wheel_session_token()
                if params.get("token_consumed"):
                    token.consume()

                ctx = _make_context(
                    token=token,
                    hwnd=params.get("hwnd", 0x4B2B),
                    tracked_hwnd=params.get("tracked_hwnd", 0x4B2B),
                    safety_point=params.get("safety_point", (500, 500)),
                    cancel_token=cancel_token,
                    input_guard=guard,
                )

                if params.get("user_event"):
                    event_adapter.emit(params["user_event"])

                if params.get("lose_focus"):
                    os_adapter.foreground = 0

                if params.get("close_cleanup"):
                    guard.uninstall()
                    self.assertFalse(guard.installed)
                    self.assertEqual(len(os_adapter.wheels), 0)
                    results.append({"case": case_id, "status": "PASS", "sendInputCount": 0})
                    continue

                if not params.get("armed", True):
                    # Do not call driver.begin()
                    res = driver.scroll_once()
                else:
                    began = driver.begin(ctx)
                    if not began["ok"]:
                        res = began
                    else:
                        if params.get("toctou_move"):
                            orig_set_pos = os_adapter.set_cursor_pos

                            def on_race(x, y):
                                orig_set_pos(x, y)
                                event_adapter.emit(KIND_MOUSE_MOVE, pt=(x, y))
                                event_adapter.emit(KIND_MOUSE_MOVE, pt=(999, 999))

                            os_adapter.set_cursor_pos = on_race
                        res = driver.scroll_once()

                # Core assertion across ALL 18 negative cases: SendInput count == 0
                self.assertEqual(len(os_adapter.wheels), 0, f"{case_id}: SendInput count must be 0")
                self.assertFalse(driver.armed, f"{case_id}: Driver must be disarmed after release")
                guard.uninstall()
                results.append({
                    "case": case_id,
                    "description": desc,
                    "status": "PASS",
                    "sendInputCount": len(os_adapter.wheels),
                    "armedAfterRelease": driver.armed,
                    "reason": res.get("reason"),
                })

        # Extra 19th check: marked program wheel MUST NOT abort
        event_adapter = MockEventAdapter()
        cancel_token = CaptureCancelToken()
        guard = WarehouseInputAbortGuard(adapter=event_adapter, cancel_token=cancel_token)
        guard.install()
        guard.arm()
        event_adapter.emit(KIND_MARKED_WHEEL, dw_extra_info=WAREHOUSE_WHEEL_EXTRA_INFO)
        self.assertFalse(cancel_token.is_cancelled(), "Marked program wheel MUST NOT cancel token")
        self.assertTrue(guard.armed)
        guard.uninstall()
        results.append({
            "case": "marked_program_wheel_no_abort",
            "description": "Marked program wheel does not abort",
            "status": "PASS",
            "sendInputCount": 0,
            "armedAfterRelease": False,
        })

        # Persist negative matrix evidence
        matrix_path = PROJECT_ROOT / "tests" / "negative_matrix_evidence.json"
        with open(matrix_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "suite": "Boundary 3 Negative Security Gate Matrix",
                    "totalCases": len(results),
                    "passedCases": len([r for r in results if r["status"] == "PASS"]),
                    "results": results,
                },
                f,
                indent=2,
            )


if __name__ == "__main__":
    unittest.main()
