import sys
import threading
from typing import Any, Callable, Optional

from warehouse_wheel_driver import WAREHOUSE_WHEEL_EXTRA_INFO, is_warehouse_wheel_input

KIND_KEY_DOWN = "KEY_DOWN"
KIND_ESCAPE = "ESCAPE"
KIND_MOUSE_BUTTON = "MOUSE_BUTTON"
KIND_WHEEL = "WHEEL"
KIND_HORIZONTAL_WHEEL = "HORIZONTAL_WHEEL"
KIND_MOUSE_MOVE = "MOUSE_MOVE"
KIND_MARKED_WHEEL = "MARKED_WHEEL"

ABORT_KINDS = frozenset({
    KIND_KEY_DOWN,
    KIND_ESCAPE,
    KIND_MOUSE_BUTTON,
    KIND_WHEEL,
    KIND_HORIZONTAL_WHEEL,
})
IGNORE_KINDS = frozenset({KIND_MOUSE_MOVE, KIND_MARKED_WHEEL})
REASON_ESCAPE = "ESCAPE"
REASON_USER_INPUT = "USER_INPUT"
REASON_INPUT_GUARD_FAILED = "INPUT_GUARD_FAILED"

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_XBUTTONDOWN = 0x020B
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
VK_ESCAPE = 0x1B


class WarehouseInputAbortGuardError(RuntimeError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class UnavailableInputActivityAdapter:
    """Fail-closed stand-in. Production hook is not available this cut."""

    def start(self, on_event: Callable[[str, Any], None]) -> None:
        raise WarehouseInputAbortGuardError("ADAPTER_UNAVAILABLE")

    def stop(self) -> None:
        return None


class _DefaultWin32HookApi:
    """Encapsulates ctypes user32/kernel32 calls with strict signatures."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

        self.HOOKPROC = ctypes.WINFUNCTYPE(
            ctypes.c_longlong,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        self.user32.SetWindowsHookExW.restype = wintypes.HHOOK
        self.user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            self.HOOKPROC,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        self.user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        self.user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        self.user32.CallNextHookEx.restype = ctypes.c_longlong
        self.user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.PostThreadMessageW.restype = wintypes.BOOL
        self.user32.PostThreadMessageW.argtypes = [
            wintypes.DWORD,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t),
            ]

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("pt", wintypes.POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t),
            ]

        self.KBDLLHOOKSTRUCT = KBDLLHOOKSTRUCT
        self.MSLLHOOKSTRUCT = MSLLHOOKSTRUCT

    def GetCurrentThreadId(self) -> int:
        return int(self.kernel32.GetCurrentThreadId())

    def SetWindowsHookExW(self, idHook: int, lpfn: Any, hmod: Any, dwThreadId: int):
        return self.user32.SetWindowsHookExW(idHook, lpfn, hmod, dwThreadId)

    def UnhookWindowsHookEx(self, hhk: Any) -> bool:
        return bool(self.user32.UnhookWindowsHookEx(hhk))

    def CallNextHookEx(self, hhk: Any, nCode: int, wParam: int, lParam: int) -> int:
        return int(self.user32.CallNextHookEx(hhk, nCode, wParam, lParam))

    def PostThreadMessageW(self, idThread: int, msg: int, wParam: int, lParam: int) -> bool:
        return bool(self.user32.PostThreadMessageW(idThread, msg, wParam, lParam))

    def run_message_loop(self) -> None:
        msg = self.wintypes.MSG()
        while self.user32.GetMessageW(self.ctypes.byref(msg), None, 0, 0) > 0:
            self.user32.TranslateMessage(self.ctypes.byref(msg))
            self.user32.DispatchMessageW(self.ctypes.byref(msg))


class Win32InputActivityAdapter:
    """Dedicated-thread Windows low-level keyboard and mouse activity listener.

    Never records key values, typed text, mouse coordinates, or input history.
    """

    def __init__(self, *, win32_api: Optional[Any] = None):
        self._win32_api = win32_api
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._hook_kb = None
        self._hook_ms = None
        self._on_event: Optional[Callable[[str, Any], None]] = None
        self._started_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._error: Optional[str] = None
        self._c_kb_proc = None
        self._c_ms_proc = None

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._running)

    def start(self, on_event: Callable[[str, Any], None]) -> None:
        if sys.platform != "win32" and self._win32_api is None:
            raise WarehouseInputAbortGuardError("PLATFORM_NOT_SUPPORTED")
        with self._lock:
            if self._running:
                return
            self._on_event = on_event
            self._started_event.clear()
            self._error = None
            self._thread = threading.Thread(
                target=self._msg_loop,
                daemon=True,
                name="win32-input-abort-guard",
            )
            self._thread.start()

        if not self._started_event.wait(timeout=2.0):
            self.stop()
            raise WarehouseInputAbortGuardError("HOOK_START_TIMEOUT")

        with self._lock:
            if self._error or not self._hook_kb or not self._hook_ms:
                err = self._error or "HOOK_INSTALL_FAILED"
                self._running = False
            else:
                self._running = True
                err = None

        if err:
            self.stop()
            raise WarehouseInputAbortGuardError(err)

    def stop(self) -> None:
        with self._lock:
            tid = self._thread_id
            api = self._win32_api
            if tid and api is not None:
                try:
                    api.PostThreadMessageW(tid, 0x0012, 0, 0)
                except Exception:
                    pass
            thread = self._thread
            self._running = False

        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

        with self._lock:
            self._thread = None
            self._thread_id = 0
            self._on_event = None
            self._hook_kb = None
            self._hook_ms = None
            self._c_kb_proc = None
            self._c_ms_proc = None

    def _msg_loop(self) -> None:
        api = self._win32_api
        if api is None:
            try:
                api = _DefaultWin32HookApi()
                self._win32_api = api
            except Exception as e:
                self._error = f"API_INIT_FAILED: {e}"
                self._started_event.set()
                return

        def _kb_callback(nCode, wParam, lParam):
            if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                try:
                    kb = api.ctypes.cast(lParam, api.ctypes.POINTER(api.KBDLLHOOKSTRUCT)).contents
                    kind = KIND_ESCAPE if kb.vkCode == VK_ESCAPE else KIND_KEY_DOWN
                    cb = self._on_event
                    if cb is not None:
                        cb(kind, kb.dwExtraInfo)
                except Exception:
                    pass
            return api.CallNextHookEx(self._hook_kb, nCode, wParam, lParam)

        def _ms_callback(nCode, wParam, lParam):
            if nCode >= 0:
                try:
                    ms = api.ctypes.cast(lParam, api.ctypes.POINTER(api.MSLLHOOKSTRUCT)).contents
                    kind = None
                    if wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_XBUTTONDOWN):
                        kind = KIND_MOUSE_BUTTON
                    elif wParam == WM_MOUSEWHEEL:
                        kind = KIND_WHEEL
                    elif wParam == WM_MOUSEHWHEEL:
                        kind = KIND_HORIZONTAL_WHEEL
                    if kind is not None:
                        cb = self._on_event
                        if cb is not None:
                            cb(kind, ms.dwExtraInfo)
                except Exception:
                    pass
            return api.CallNextHookEx(self._hook_ms, nCode, wParam, lParam)

        try:
            self._c_kb_proc = api.HOOKPROC(_kb_callback)
            self._c_ms_proc = api.HOOKPROC(_ms_callback)
            self._thread_id = api.GetCurrentThreadId()
            self._hook_kb = api.SetWindowsHookExW(WH_KEYBOARD_LL, self._c_kb_proc, None, 0)
            if not self._hook_kb:
                self._error = "HOOK_KB_FAILED"
                self._started_event.set()
                return

            self._hook_ms = api.SetWindowsHookExW(WH_MOUSE_LL, self._c_ms_proc, None, 0)
            if not self._hook_ms:
                self._error = "HOOK_MS_FAILED"
                try:
                    api.UnhookWindowsHookEx(self._hook_kb)
                except Exception:
                    pass
                self._hook_kb = None
                self._started_event.set()
                return
        except Exception as e:
            self._error = f"HOOK_INSTALL_EXCEPTION: {e}"
            if self._hook_kb:
                try:
                    api.UnhookWindowsHookEx(self._hook_kb)
                except Exception:
                    pass
                self._hook_kb = None
            if self._hook_ms:
                try:
                    api.UnhookWindowsHookEx(self._hook_ms)
                except Exception:
                    pass
                self._hook_ms = None
            self._started_event.set()
            return

        self._started_event.set()

        try:
            api.run_message_loop()
        except Exception:
            pass
        finally:
            if self._hook_kb:
                try:
                    api.UnhookWindowsHookEx(self._hook_kb)
                except Exception:
                    pass
                self._hook_kb = None
            if self._hook_ms:
                try:
                    api.UnhookWindowsHookEx(self._hook_ms)
                except Exception:
                    pass
                self._hook_ms = None
            self._c_kb_proc = None
            self._c_ms_proc = None


def classify_input_kind(kind: Any, *, dw_extra_info: Any = None) -> Optional[str]:
    """Map a closed event kind. Never stores extra_info or coordinates."""
    if dw_extra_info is not None and is_warehouse_wheel_input(dw_extra_info):
        return KIND_MARKED_WHEEL
    text = str(kind or "").strip().upper()
    if text in {KIND_KEY_DOWN, KIND_ESCAPE, KIND_MOUSE_BUTTON, KIND_WHEEL, KIND_HORIZONTAL_WHEEL, KIND_MOUSE_MOVE, KIND_MARKED_WHEEL}:
        return text
    if text in {"LBUTTON", "RBUTTON", "MBUTTON", "XBUTTON", "MOUSEDOWN", "MOUSE_DOWN"}:
        return KIND_MOUSE_BUTTON
    if text in {"HWHEEL", "MOUSEHWHEEL"}:
        return KIND_HORIZONTAL_WHEEL
    if text in {"ESC", "VK_ESCAPE"}:
        return KIND_ESCAPE
    if text in {"MOVE", "MOUSEMOVE"}:
        return KIND_MOUSE_MOVE
    return None


class WarehouseInputAbortGuard:
    def __init__(
        self,
        *,
        adapter: Any,
        cancel_token: Any = None,
        extra_info_marker: int = WAREHOUSE_WHEEL_EXTRA_INFO,
    ):
        self._adapter = adapter
        self._cancel_token = cancel_token
        self._marker = int(extra_info_marker)
        self._installed = False
        self._armed = False
        self._cleaned = False
        self._abort_reason: Optional[str] = None

    @property
    def installed(self) -> bool:
        return self._installed

    @property
    def armed(self) -> bool:
        return self._armed

    def abort_reason(self) -> Optional[str]:
        return self._abort_reason

    def install(self) -> bool:
        if self._cleaned:
            return False
        if self._installed:
            return True
        adapter = self._adapter
        if adapter is None or not hasattr(adapter, "start"):
            return False
        try:
            adapter.start(self._on_event)
        except Exception:
            return False
        self._installed = True
        return True

    def arm(self) -> bool:
        if self._cleaned or not self._installed:
            return False
        self._armed = True
        return True

    def disarm(self) -> None:
        self._armed = False

    def uninstall(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        self._armed = False
        was_installed = self._installed
        self._installed = False
        adapter = self._adapter
        if not was_installed or adapter is None or not hasattr(adapter, "stop"):
            return
        try:
            adapter.stop()
        except Exception:
            return

    def _on_event(self, kind: Any, dw_extra_info: Any = None) -> None:
        if self._cleaned or not self._armed:
            return
        classified = classify_input_kind(kind, dw_extra_info=dw_extra_info)
        if classified is None or classified in IGNORE_KINDS:
            return
        if classified not in ABORT_KINDS:
            return
        reason = REASON_ESCAPE if classified == KIND_ESCAPE else REASON_USER_INPUT
        self._abort_reason = reason
        self._armed = False
        token = self._cancel_token
        if token is None:
            return
        try:
            if hasattr(token, "cancel") and callable(token.cancel):
                try:
                    token.cancel(reason)
                except TypeError:
                    token.cancel()
        except Exception:
            return
