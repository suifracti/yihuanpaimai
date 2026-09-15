"""Injected-adapter tests for the warehouse wheel-driver safety shell."""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(CORE_DIR),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from warehouse_capture_session import (
    PRODUCTION_SCROLL_DRIVER_ENABLED,
    get_production_scroll_driver,
)
from warehouse_scrollbar_observation import warehouse_search_roi
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
    REASON_NOT_FOREGROUND,
    REASON_NOT_STABLE_SETTLEMENT,
    REASON_SAFETY_POINT_OUTSIDE,
    REASON_STABLE_KEY_MISMATCH,
    REASON_TOKEN_REUSED,
    WAREHOUSE_WHEEL_EXTRA_INFO,
    WHEEL_DELTA_NOTCH,
    WarehouseWheelContext,
    WarehouseWheelDriver,
    Win32WarehouseOsAdapter,
    is_warehouse_wheel_input,
    issue_warehouse_wheel_session_token,
)

HWND = 0x4B2B
ORIGIN = (120, 80)
CLIENT = (0, 0, 1920, 1080)
CURSOR = (11, 22)
KEY = "recWHWheel01"

FORBIDDEN_INPUT = (
    "SendInput",
    "mouse_event",
    "MOUSEEVENTF_LEFT",
    "MOUSEEVENTF_RIGHT",
    "MOUSEEVENTF_HWHEEL",
    "SetForegroundWindow",
    "PostMessage",
    "SendMessage",
    "keybd_event",
    "KEYEVENTF",
    "pyautogui",
    "pydirectinput",
)


class RecordingOsAdapter:
    def __init__(
        self,
        *,
        hwnd=HWND,
        foreground=HWND,
        exists=True,
        visible=True,
        iconic=False,
        client=CLIENT,
        origin=ORIGIN,
        cursor=CURSOR,
        lose_focus_after_move=False,
        fail_on=None,
    ):
        self.hwnd = hwnd
        self.foreground = foreground
        self.exists = exists
        self.visible = visible
        self.iconic = iconic
        self.client = client
        self.origin = origin
        self.cursor = tuple(cursor)
        self.original_cursor = tuple(cursor)
        self.lose_focus_after_move = lose_focus_after_move
        self.fail_on = fail_on
        self.calls = []

    def _record(self, name, *args):
        self.calls.append((name,) + args)

    def get_cursor_pos(self):
        self._record("get_cursor_pos")
        if self.fail_on == "get_cursor_pos":
            raise OSError("injected get_cursor_pos")
        return self.cursor

    def set_cursor_pos(self, x, y):
        self._record("set_cursor_pos", int(x), int(y))
        if self.fail_on == "set_cursor_pos" and (int(x), int(y)) != self.original_cursor:
            raise OSError("injected set_cursor_pos")
        self.cursor = (int(x), int(y))
        if self.lose_focus_after_move and self.cursor != self.original_cursor:
            self.foreground = 0

    def send_mouse_wheel(self, delta, extra_info):
        if self.fail_on == "send_mouse_wheel":
            raise OSError("injected send_mouse_wheel")
        self._record("send_mouse_wheel", int(delta), int(extra_info))

    def get_foreground_window(self):
        self._record("get_foreground_window")
        return self.foreground

    def is_window(self, hwnd):
        self._record("is_window", hwnd)
        return bool(self.exists and int(hwnd) == int(self.hwnd))

    def is_window_visible(self, hwnd):
        self._record("is_window_visible", hwnd)
        return bool(self.visible)

    def is_iconic(self, hwnd):
        self._record("is_iconic", hwnd)
        return bool(self.iconic)

    def get_client_rect(self, hwnd):
        self._record("get_client_rect", hwnd)
        return self.client

    def client_to_screen(self, hwnd, x, y):
        self._record("client_to_screen", hwnd, x, y)
        return int(self.origin[0] + x), int(self.origin[1] + y)


class CancelToken:
    def __init__(self, cancelled=False):
        self._cancelled = cancelled

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled


def _roi():
    return warehouse_search_roi(CLIENT[2], CLIENT[3])


def _safety(roi=None):
    x1, y1, x2, y2 = roi or _roi()
    return (x1 + x2) // 2, (y1 + y2) // 2


def _context(**overrides):
    values = dict(
        session_token=issue_warehouse_wheel_session_token(),
        record_stable_key=KEY,
        expected_stable_key=KEY,
        hwnd=HWND,
        tracked_hwnd=HWND,
        settlement_stable=True,
        safety_point=_safety(),
        warehouse_roi=_roi(),
        cancellation_token=None,
    )
    values.update(overrides)
    return WarehouseWheelContext(**values)


def _input_calls(adapter):
    return [call for call in adapter.calls if call[0] in {"set_cursor_pos", "send_mouse_wheel"}]


def _wheels(adapter):
    return [call for call in adapter.calls if call[0] == "send_mouse_wheel"]


class WarehouseWheelDriverV1Tests(unittest.TestCase):
    def test_legal_context_saves_moves_rechecks_wheels_and_restores(self):
        adapter = RecordingOsAdapter()
        driver = WarehouseWheelDriver(os_adapter=adapter)
        ctx = _context()
        sx, sy = ctx.safety_point
        screen = (ORIGIN[0] + sx, ORIGIN[1] + sy)
        began = driver.begin(ctx)
        self.assertTrue(began["ok"], began)
        self.assertTrue(driver.armed)
        self.assertFalse(began["wheelSent"])
        scrolled = driver.scroll_once()
        self.assertTrue(scrolled["ok"], scrolled)
        self.assertTrue(scrolled["wheelSent"])
        self.assertTrue(scrolled["cursorMoved"])
        ended = driver.end()
        self.assertTrue(ended["ok"], ended)
        self.assertTrue(ended["cursorRestored"])
        self.assertFalse(driver.armed)
        self.assertEqual(
            _input_calls(adapter),
            [
                ("set_cursor_pos", screen[0], screen[1]),
                ("send_mouse_wheel", DEFAULT_WHEEL_DELTA, WAREHOUSE_WHEEL_EXTRA_INFO),
                ("set_cursor_pos", CURSOR[0], CURSOR[1]),
            ],
        )
        self.assertLess(adapter.calls.index(("get_cursor_pos",)), adapter.calls.index(("set_cursor_pos", screen[0], screen[1])))
        move_at = adapter.calls.index(("set_cursor_pos", screen[0], screen[1]))
        wheel_at = adapter.calls.index(("send_mouse_wheel", DEFAULT_WHEEL_DELTA, WAREHOUSE_WHEEL_EXTRA_INFO))
        self.assertGreater(wheel_at, move_at)
        self.assertIn(("get_foreground_window",), adapter.calls[move_at:wheel_at])

    def test_fail_closed_cases_send_zero_wheel(self):
        roi = _roi()
        cases = {
            REASON_MISSING_TOKEN: dict(session_token=None),
            REASON_CANCELLED: dict(cancellation_token=CancelToken(True)),
            REASON_STABLE_KEY_MISMATCH: dict(record_stable_key="otherKey"),
            REASON_HWND_MISMATCH: dict(hwnd=HWND, tracked_hwnd=HWND + 1),
            REASON_HWND_INVALID: dict(hwnd=0, tracked_hwnd=0),
            REASON_NOT_STABLE_SETTLEMENT: dict(settlement_stable=False),
            REASON_SAFETY_POINT_OUTSIDE: dict(safety_point=(roi[0], roi[1])),
            REASON_INVALID_ROI: dict(warehouse_roi=(0, 0, 1, 1)),
        }
        adapter_tweaks = {
            REASON_HWND_HIDDEN: dict(visible=False),
            REASON_HWND_MINIMIZED: dict(iconic=True),
            REASON_NOT_FOREGROUND: dict(foreground=0),
            REASON_HWND_INVALID + ":gone": dict(exists=False),
        }
        for reason, overrides in cases.items():
            with self.subTest(reason=reason):
                adapter = RecordingOsAdapter()
                driver = WarehouseWheelDriver(os_adapter=adapter)
                result = driver.begin(_context(**overrides))
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["reason"], reason)
                self.assertEqual(_wheels(adapter), [])
                self.assertEqual(_input_calls(adapter), [])
                self.assertFalse(driver.armed)
        for reason, tweak in adapter_tweaks.items():
            with self.subTest(reason=reason):
                adapter = RecordingOsAdapter(**tweak)
                driver = WarehouseWheelDriver(os_adapter=adapter)
                result = driver.begin(_context())
                self.assertFalse(result["ok"], result)
                self.assertEqual(_wheels(adapter), [])
                self.assertEqual(_input_calls(adapter), [])

        reused = RecordingOsAdapter()
        token = issue_warehouse_wheel_session_token()
        driver = WarehouseWheelDriver(os_adapter=reused)
        first = driver.begin(_context(session_token=token))
        self.assertTrue(first["ok"], first)
        driver.end()
        again = driver.begin(_context(session_token=token))
        self.assertFalse(again["ok"])
        self.assertEqual(again["reason"], REASON_TOKEN_REUSED)
        self.assertEqual(_wheels(reused), [])

    def test_focus_lost_after_move_sends_zero_wheel_and_restores(self):
        adapter = RecordingOsAdapter(lose_focus_after_move=True)
        driver = WarehouseWheelDriver(os_adapter=adapter)
        ctx = _context()
        self.assertTrue(driver.begin(ctx)["ok"])
        result = driver.scroll_once()
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], REASON_NOT_FOREGROUND)
        self.assertFalse(result["wheelSent"])
        self.assertTrue(result["cursorMoved"])
        self.assertTrue(result["cursorRestored"])
        self.assertFalse(driver.armed)
        self.assertEqual(_wheels(adapter), [])
        self.assertEqual(adapter.cursor, CURSOR)
        self.assertIn(("set_cursor_pos", CURSOR[0], CURSOR[1]), _input_calls(adapter))

    def test_wheel_delta_is_bounded_negative_and_marked(self):
        adapter = RecordingOsAdapter()
        driver = WarehouseWheelDriver(os_adapter=adapter, wheel_delta=-999)
        self.assertTrue(driver.begin(_context())["ok"])
        self.assertTrue(driver.scroll_once()["ok"])
        driver.end()
        wheels = _wheels(adapter)
        self.assertEqual(len(wheels), 1)
        _, delta, extra = wheels[0]
        self.assertLess(delta, 0)
        self.assertGreaterEqual(delta, -WHEEL_DELTA_NOTCH)
        self.assertEqual(delta, DEFAULT_WHEEL_DELTA)
        self.assertEqual(extra, WAREHOUSE_WHEEL_EXTRA_INFO)
        self.assertTrue(is_warehouse_wheel_input(extra))
        self.assertFalse(is_warehouse_wheel_input(0))
        self.assertFalse(is_warehouse_wheel_input(12345))
        self.assertFalse(is_warehouse_wheel_input(None))

    def test_only_move_and_wheel_no_click_or_key(self):
        adapter = RecordingOsAdapter()
        driver = WarehouseWheelDriver(os_adapter=adapter)
        self.assertTrue(driver.begin(_context())["ok"])
        self.assertTrue(driver.scroll_once()["ok"])
        self.assertEqual(driver.scroll_once()["reason"], REASON_ALREADY_SCROLLED)
        driver.end()
        names = [call[0] for call in adapter.calls]
        self.assertEqual(names.count("send_mouse_wheel"), 1)
        self.assertNotIn("send_click", names)
        self.assertNotIn("send_key", names)
        self.assertNotIn("send_hwheel", names)
        self.assertNotIn("set_foreground_window", names)
        self.assertNotIn("post_message", names)
        self.assertNotIn("send_message", names)

    def test_adapter_error_restores_cursor_and_clears_armed(self):
        adapter = RecordingOsAdapter(fail_on="send_mouse_wheel")
        driver = WarehouseWheelDriver(os_adapter=adapter)
        self.assertTrue(driver.begin(_context())["ok"])
        result = driver.scroll_once()
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], REASON_ADAPTER_ERROR)
        self.assertFalse(result["wheelSent"])
        self.assertTrue(result["cursorMoved"])
        self.assertTrue(result["cursorRestored"])
        self.assertFalse(driver.armed)
        self.assertEqual(_wheels(adapter), [])
        self.assertEqual(adapter.cursor, CURSOR)

    def test_production_driver_stays_disabled(self):
        self.assertTrue(PRODUCTION_SCROLL_DRIVER_ENABLED)
        factory = get_production_scroll_driver()
        self.assertIsNotNone(factory)
        self.assertFalse(hasattr(factory, "send_mouse_wheel"))
        session_src = (CORE_DIR / "warehouse_capture_session.py").read_text(encoding="utf-8")
        driver_src = (CORE_DIR / "warehouse_wheel_driver.py").read_text(encoding="utf-8")
        test_src = Path(__file__).read_text(encoding="utf-8")
        self.assertNotIn("warehouse_wheel_driver", session_src)
        self.assertTrue(inspect.isclass(Win32WarehouseOsAdapter))
        self.assertNotIn(".".join(("ctypes", "windll")), test_src)
        self.assertNotIn(".".join(("user32", "SendInput")), test_src)
        self.assertNotIn(".".join(("user32", "SetCursorPos")), test_src)
        self.assertNotRegex(test_src, r"Win32WarehouseOsAdapter\s*\(")
        shell_src = driver_src.split("class Win32WarehouseOsAdapter", 1)[0]
        driver_cls = driver_src.split("class WarehouseWheelDriver", 1)[1]
        for token in FORBIDDEN_INPUT:
            self.assertNotIn(token, shell_src)
            self.assertNotIn(token, driver_cls)
        self.assertNotIn("settlement_evidence_store", driver_src)
        self.assertNotIn("warehouse_coverage_ledger", driver_src)
        self.assertNotIn("canonical_history", driver_src)
        self.assertNotIn("warehouse_vision", driver_src)

    def test_missing_adapter_and_unarmed_scroll_are_zero_input(self):
        driver = WarehouseWheelDriver(os_adapter=None)
        result = driver.begin(_context())
        self.assertFalse(result["ok"])
        self.assertFalse(result["wheelSent"])
        armed = WarehouseWheelDriver(os_adapter=RecordingOsAdapter())
        self.assertEqual(armed.scroll_once()["reason"], "NOT_ARMED")
        self.assertEqual(_wheels(armed._adapter), [])


if __name__ == "__main__":
    unittest.main()
