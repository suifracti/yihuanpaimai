"""Pre-fix demonstration tests for Boundary 3 input takeover breakpoints.

Proves:
1. Case A: Current production code ignores physical mouse move when armed (cancellation remains False -> FAIL).
2. Case B: A naive fix treating all mouse moves as user takeover causes self-abort on program's own SetCursorPos (proves why naive fix fails).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from warehouse_capture_host import CaptureCancelToken
from warehouse_input_abort_guard import (
    KIND_MOUSE_MOVE,
    REASON_USER_MOUSE_MOVE,
    WarehouseInputAbortGuard,
)
from warehouse_wheel_driver import (
    DEFAULT_WHEEL_DELTA,
    WarehouseWheelContext,
    WarehouseWheelDriver,
    issue_warehouse_wheel_session_token,
)


class MockEventAdapter:
    def __init__(self):
        self.started = False
        self.stopped = False
        self._on_event = None

    def start(self, on_event):
        self.started = True
        self._on_event = on_event

    def stop(self):
        self.stopped = True
        self._on_event = None

    def emit(self, kind, dw_extra_info=None, pt=None):
        if self._on_event:
            self._on_event(kind, dw_extra_info, pt)


class MockOsAdapterWithCursorTracking:
    def __init__(self):
        self.cursor = (500, 500)
        self.moves = []
        self.wheels = []
        self.foreground = 0x1001

    def get_cursor_pos(self):
        return self.cursor

    def set_cursor_pos(self, x, y):
        self.cursor = (int(x), int(y))
        self.moves.append((int(x), int(y)))
        return True

    def send_mouse_wheel(self, delta, extra_info):
        self.wheels.append((int(delta), int(extra_info)))

    def get_foreground_window(self):
        return self.foreground

    def is_window(self, hwnd):
        return int(hwnd) == 0x1001

    def is_window_visible(self, hwnd):
        return True

    def is_iconic(self, hwnd):
        return False

    def get_client_rect(self, hwnd):
        return (0, 0, 1920, 1080)

    def client_to_screen(self, hwnd, x, y):
        return (int(x), int(y))


class TestBoundary3PreFix(unittest.TestCase):
    def test_case_a_unpatched_vs_patched_mouse_move_behavior(self):
        """Case A: Compare unpatched behavior (ignores mouse move) vs patched behavior.
        Proves the safety vulnerability in unpatched design and the fix in patched guard.
        """
        # 1. Unpatched simulation (ignores KIND_MOUSE_MOVE)
        class UnpatchedGuard(WarehouseInputAbortGuard):
            def _on_event(self, kind, dw_extra_info=None, pt=None):
                if kind == KIND_MOUSE_MOVE:
                    return  # Unpatched behavior: ignore mouse move
                super()._on_event(kind, dw_extra_info, pt)

        adapter_unpatched = MockEventAdapter()
        token_unpatched = CaptureCancelToken()
        guard_unpatched = UnpatchedGuard(adapter=adapter_unpatched, cancel_token=token_unpatched)
        self.assertTrue(guard_unpatched.install())
        self.assertTrue(guard_unpatched.arm())
        adapter_unpatched.emit(KIND_MOUSE_MOVE, pt=(500, 500))
        # Unpatched flaw: mouse move does NOT cancel
        self.assertFalse(token_unpatched.is_cancelled(), "Unpatched guard failed to cancel on MOUSE_MOVE")
        self.assertIsNone(guard_unpatched.abort_reason())
        guard_unpatched.uninstall()

        # 2. Patched production behavior: unexpected user mouse move DOES cancel!
        adapter_patched = MockEventAdapter()
        token_patched = CaptureCancelToken()
        guard_patched = WarehouseInputAbortGuard(adapter=adapter_patched, cancel_token=token_patched)
        self.assertTrue(guard_patched.install())
        self.assertTrue(guard_patched.arm())
        adapter_patched.emit(KIND_MOUSE_MOVE, pt=(500, 500))
        self.assertTrue(token_patched.is_cancelled(), "Patched guard must cancel on unexpected user MOUSE_MOVE")
        self.assertEqual(guard_patched.abort_reason(), "USER_MOUSE_MOVE")
        guard_patched.uninstall()

    def test_case_b_naive_fix_vs_oneshot_expected_move(self):
        """Case B: Compare naive fix (blind abort on all moves) vs one-shot expected move.
        Proves why naive abort breaks program's own SetCursorPos, and one-shot expected move succeeds.
        """
        class NaiveGuard(WarehouseInputAbortGuard):
            def _on_event(self, kind, dw_extra_info=None, pt=None):
                if kind == KIND_MOUSE_MOVE:
                    self._abort_reason = REASON_USER_MOUSE_MOVE
                    self._armed = False
                    if self._cancel_token:
                        self._cancel_token.cancel(REASON_USER_MOUSE_MOVE)
                else:
                    super()._on_event(kind, dw_extra_info, pt)

        adapter_naive = MockEventAdapter()
        token_naive = CaptureCancelToken()
        guard_naive = NaiveGuard(adapter=adapter_naive, cancel_token=token_naive)
        self.assertTrue(guard_naive.install())
        self.assertTrue(guard_naive.arm())

        os_adapter_naive = MockOsAdapterWithCursorTracking()
        driver_naive = WarehouseWheelDriver(os_adapter=os_adapter_naive)
        orig_set_cursor_pos = os_adapter_naive.set_cursor_pos

        def hook_set_cursor_pos(x, y):
            orig_set_cursor_pos(x, y)
            adapter_naive.emit(KIND_MOUSE_MOVE, pt=(x, y))

        os_adapter_naive.set_cursor_pos = hook_set_cursor_pos

        ctx_naive = WarehouseWheelContext(
            session_token=issue_warehouse_wheel_session_token(),
            record_stable_key="testPreFix01",
            expected_stable_key="testPreFix01",
            hwnd=0x1001,
            tracked_hwnd=0x1001,
            settlement_stable=True,
            warehouse_roi=(100, 100, 800, 800),
            safety_point=(450, 450),
            cancellation_token=token_naive,
        )
        self.assertTrue(driver_naive.begin(ctx_naive)["ok"])
        result_naive = driver_naive.scroll_once()
        self.assertFalse(result_naive["ok"])
        self.assertEqual(result_naive["reason"], "CANCELLED")
        self.assertEqual(len(os_adapter_naive.wheels), 0)
        self.assertTrue(token_naive.is_cancelled())

        # 2. Patched production behavior with one-shot expected move: succeeds without self-abort!
        adapter_prod = MockEventAdapter()
        token_prod = CaptureCancelToken()
        guard_prod = WarehouseInputAbortGuard(adapter=adapter_prod, cancel_token=token_prod)
        self.assertTrue(guard_prod.install())
        self.assertTrue(guard_prod.arm())

        os_adapter_prod = MockOsAdapterWithCursorTracking()
        driver_prod = WarehouseWheelDriver(os_adapter=os_adapter_prod)
        orig_set_cursor_pos_prod = os_adapter_prod.set_cursor_pos

        def hook_set_cursor_pos_prod(x, y):
            orig_set_cursor_pos_prod(x, y)
            adapter_prod.emit(KIND_MOUSE_MOVE, pt=(x, y))

        os_adapter_prod.set_cursor_pos = hook_set_cursor_pos_prod

        ctx_prod = WarehouseWheelContext(
            session_token=issue_warehouse_wheel_session_token(),
            record_stable_key="testPreFix02",
            expected_stable_key="testPreFix02",
            hwnd=0x1001,
            tracked_hwnd=0x1001,
            settlement_stable=True,
            warehouse_roi=(100, 100, 800, 800),
            safety_point=(450, 450),
            cancellation_token=token_prod,
            input_guard=guard_prod,
        )
        self.assertTrue(driver_prod.begin(ctx_prod)["ok"])
        result_prod = driver_prod.scroll_once()
        self.assertTrue(result_prod["ok"])
        self.assertEqual(len(os_adapter_prod.wheels), 1)
        self.assertFalse(token_prod.is_cancelled())
        guard_prod.uninstall()


if __name__ == "__main__":
    unittest.main()
