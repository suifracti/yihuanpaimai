"""Targeted unit and mock tests for 4D2D1B1: Win32 Input Abort Adapter Only.

Tests Win32InputActivityAdapter lifecycle, dedicated-thread message loop,
classification of Esc, keys, mouse buttons, unmarked/marked wheels, partial-hook
rollback, idempotent stop/cleanup, and zero hook installation prior to explicit start.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(CORE_DIR),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from warehouse_input_abort_guard import (
    KIND_ESCAPE,
    KIND_HORIZONTAL_WHEEL,
    KIND_KEY_DOWN,
    KIND_MARKED_WHEEL,
    KIND_MOUSE_BUTTON,
    KIND_MOUSE_MOVE,
    KIND_WHEEL,
    REASON_ESCAPE,
    REASON_USER_INPUT,
    VK_ESCAPE,
    WH_KEYBOARD_LL,
    WH_MOUSE_LL,
    WM_KEYDOWN,
    WM_LBUTTONDOWN,
    WM_MBUTTONDOWN,
    WM_MOUSEHWHEEL,
    WM_MOUSEWHEEL,
    WM_RBUTTONDOWN,
    WM_SYSKEYDOWN,
    WM_XBUTTONDOWN,
    WarehouseInputAbortGuard,
    WarehouseInputAbortGuardError,
    Win32InputActivityAdapter,
)
from warehouse_wheel_driver import WAREHOUSE_WHEEL_EXTRA_INFO


class _FakeCancelToken:
    def __init__(self):
        self.cancelled = False
        self.reason = None

    def cancel(self, reason=None):
        self.cancelled = True
        self.reason = reason


class _MockKbdStruct:
    def __init__(self, vk_code: int, dw_extra_info: int = 0):
        self.vkCode = vk_code
        self.dwExtraInfo = dw_extra_info


class _MockMsStruct:
    def __init__(self, dw_extra_info: int = 0):
        self.dwExtraInfo = dw_extra_info


class _MockWin32HookApi:
    def __init__(
        self,
        *,
        fail_kb: bool = False,
        fail_ms: bool = False,
    ):
        self.fail_kb = fail_kb
        self.fail_ms = fail_ms
        self.kb_hook = None
        self.ms_hook = None
        self.unhooked: List[Any] = []
        self.posted_messages: List[Tuple[int, int]] = []
        self.kb_proc = None
        self.ms_proc = None
        self.HOOKPROC = lambda fn: fn
        self.loop_running = threading.Event()
        self.loop_stop = threading.Event()

        class _MockCtypes:
            def cast(self, struct_obj, _target_type):
                class _Holder:
                    contents = struct_obj
                return _Holder()

            def POINTER(self, cls):
                return cls

        self.ctypes = _MockCtypes()
        self.KBDLLHOOKSTRUCT = _MockKbdStruct
        self.MSLLHOOKSTRUCT = _MockMsStruct

    def GetCurrentThreadId(self) -> int:
        return 9999

    def SetWindowsHookExW(self, idHook: int, lpfn: Any, hmod: Any, dwThreadId: int):
        if idHook == WH_KEYBOARD_LL:
            if self.fail_kb:
                return None
            self.kb_hook = 1001
            self.kb_proc = lpfn
            return 1001
        elif idHook == WH_MOUSE_LL:
            if self.fail_ms:
                return None
            self.ms_hook = 2002
            self.ms_proc = lpfn
            return 2002
        return None

    def UnhookWindowsHookEx(self, hhk: Any) -> bool:
        self.unhooked.append(hhk)
        if hhk == self.kb_hook:
            self.kb_hook = None
        if hhk == self.ms_hook:
            self.ms_hook = None
        return True

    def CallNextHookEx(self, hhk: Any, nCode: int, wParam: int, lParam: int) -> int:
        return 0

    def PostThreadMessageW(self, idThread: int, msg: int, wParam: int, lParam: int) -> bool:
        self.posted_messages.append((idThread, msg))
        if msg == 0x0012:  # WM_QUIT
            self.loop_stop.set()
        return True

    def run_message_loop(self) -> None:
        self.loop_running.set()
        self.loop_stop.wait(timeout=2.0)


class TestWin32InputAbortAdapterV1(unittest.TestCase):
    def test_import_and_instantiation_has_zero_hooks(self):
        adapter = Win32InputActivityAdapter()
        self.assertFalse(adapter.running)
        self.assertIsNone(adapter._thread)
        self.assertIsNone(adapter._hook_kb)
        self.assertIsNone(adapter._hook_ms)

    def test_mock_classification_and_events(self):
        api = _MockWin32HookApi()
        adapter = Win32InputActivityAdapter(win32_api=api)
        events: List[Tuple[str, int]] = []
        token = _FakeCancelToken()
        guard = WarehouseInputAbortGuard(adapter=adapter, cancel_token=token)

        self.assertTrue(guard.install())
        self.assertTrue(guard.arm())
        self.assertTrue(adapter.running)
        self.assertEqual(api.kb_hook, 1001)
        self.assertEqual(api.ms_hook, 2002)

        # 1. Non-Esc Key Down -> USER_INPUT
        api.kb_proc(0, WM_KEYDOWN, _MockKbdStruct(vk_code=0x41, dw_extra_info=0))
        self.assertEqual(guard.abort_reason(), REASON_USER_INPUT)
        self.assertTrue(token.cancelled)
        self.assertEqual(token.reason, REASON_USER_INPUT)

        # 2. Reset and test Esc -> ESCAPE
        token.cancelled = False
        token.reason = None
        guard.arm()
        api.kb_proc(0, WM_KEYDOWN, _MockKbdStruct(vk_code=VK_ESCAPE, dw_extra_info=0))
        self.assertEqual(guard.abort_reason(), REASON_ESCAPE)
        self.assertEqual(token.reason, REASON_ESCAPE)

        # 3. Mouse buttons -> USER_INPUT
        for btn_msg in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_XBUTTONDOWN):
            token.cancelled = False
            token.reason = None
            guard.arm()
            api.ms_proc(0, btn_msg, _MockMsStruct(dw_extra_info=0))
            self.assertEqual(guard.abort_reason(), REASON_USER_INPUT)
            self.assertEqual(token.reason, REASON_USER_INPUT)

        # 4. Programmatic wheel with marker -> Ignored (no abort)
        token.cancelled = False
        token.reason = None
        guard.arm()
        api.ms_proc(0, WM_MOUSEWHEEL, _MockMsStruct(dw_extra_info=WAREHOUSE_WHEEL_EXTRA_INFO))
        self.assertFalse(token.cancelled)
        self.assertIsNone(token.reason)
        self.assertTrue(guard.armed)

        # 5. User physical wheel -> USER_INPUT
        api.ms_proc(0, WM_MOUSEWHEEL, _MockMsStruct(dw_extra_info=0))
        self.assertEqual(guard.abort_reason(), REASON_USER_INPUT)
        self.assertEqual(token.reason, REASON_USER_INPUT)

        # 6. Horizontal wheel -> USER_INPUT
        token.cancelled = False
        token.reason = None
        guard.arm()
        api.ms_proc(0, WM_MOUSEHWHEEL, _MockMsStruct(dw_extra_info=0))
        self.assertEqual(guard.abort_reason(), REASON_USER_INPUT)
        self.assertEqual(token.reason, REASON_USER_INPUT)

        # 7. Clean uninstallation & idempotent stop
        guard.uninstall()
        self.assertFalse(adapter.running)
        self.assertIn(1001, api.unhooked)
        self.assertIn(2002, api.unhooked)
        # Duplicate stops
        adapter.stop()
        adapter.stop()
        guard.uninstall()

    def test_mock_partial_failure_rollback_when_ms_hook_fails(self):
        api = _MockWin32HookApi(fail_ms=True)
        adapter = Win32InputActivityAdapter(win32_api=api)

        with self.assertRaises(WarehouseInputAbortGuardError):
            adapter.start(lambda *args: None)

        self.assertFalse(adapter.running)
        # KB hook was rolled back immediately
        self.assertIn(1001, api.unhooked)
        self.assertIsNone(api.kb_hook)
        self.assertIsNone(api.ms_hook)

    def test_mock_partial_failure_when_kb_hook_fails(self):
        api = _MockWin32HookApi(fail_kb=True)
        adapter = Win32InputActivityAdapter(win32_api=api)

        with self.assertRaises(WarehouseInputAbortGuardError):
            adapter.start(lambda *args: None)

        self.assertFalse(adapter.running)
        self.assertIsNone(api.kb_hook)
        self.assertIsNone(api.ms_hook)

    @unittest.skipUnless(sys.platform == "win32", "Requires native Windows OS")
    def test_native_windows_smoke_install_then_immediate_uninstall(self):
        adapter = Win32InputActivityAdapter()
        events = []
        adapter.start(lambda kind, extra: events.append((kind, extra)))
        self.assertTrue(adapter.running)
        self.assertIsNotNone(adapter._hook_kb)
        self.assertIsNotNone(adapter._hook_ms)

        # Immediately uninstall without collecting any input
        adapter.stop()
        self.assertFalse(adapter.running)
        self.assertIsNone(adapter._hook_kb)
        self.assertIsNone(adapter._hook_ms)
        self.assertEqual(len(events), 0)


if __name__ == "__main__":
    unittest.main()
