"""Win32 warehouse wheel-driver safety shell.

Injectable, fail-closed, single-pulse downward wheel only. Does not click,
type, h-scroll, post background window messages, steal focus, or wire 4B2A production.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from warehouse_scrollbar_observation import warehouse_search_roi

SCHEMA_VERSION = "warehouse-wheel-driver.v1"

WHEEL_DELTA_NOTCH = 120
DEFAULT_WHEEL_DELTA = -WHEEL_DELTA_NOTCH
WAREHOUSE_WHEEL_EXTRA_INFO = 0x59485057  # YH PW

REASON_OK = "OK"
REASON_MISSING_TOKEN = "MISSING_TOKEN"
REASON_TOKEN_REUSED = "TOKEN_REUSED"
REASON_CANCELLED = "CANCELLED"
REASON_NOT_STABLE_SETTLEMENT = "NOT_STABLE_SETTLEMENT"
REASON_WAREHOUSE_NOT_PRESENT = "WAREHOUSE_NOT_PRESENT"
REASON_STABLE_KEY_MISMATCH = "STABLE_KEY_MISMATCH"
REASON_HWND_MISMATCH = "HWND_MISMATCH"
REASON_HWND_INVALID = "HWND_INVALID"
REASON_HWND_HIDDEN = "HWND_HIDDEN"
REASON_HWND_MINIMIZED = "HWND_MINIMIZED"
REASON_NOT_FOREGROUND = "NOT_FOREGROUND"
REASON_INVALID_ROI = "INVALID_ROI"
REASON_SAFETY_POINT_OUTSIDE = "SAFETY_POINT_OUTSIDE"
REASON_NOT_ARMED = "NOT_ARMED"
REASON_ALREADY_SCROLLED = "ALREADY_SCROLLED"
REASON_ADAPTER_MISSING = "ADAPTER_MISSING"
REASON_ADAPTER_ERROR = "ADAPTER_ERROR"
REASON_ALREADY_ARMED = "ALREADY_ARMED"

RESULT_KEYS = (
    "schemaVersion",
    "ok",
    "reason",
    "armed",
    "wheelSent",
    "cursorMoved",
    "cursorRestored",
)


def is_warehouse_wheel_input(dw_extra_info: Any) -> bool:
    """Read-only marker check. True only for this driver's injected events."""
    try:
        return int(dw_extra_info) == WAREHOUSE_WHEEL_EXTRA_INFO
    except (TypeError, ValueError):
        return False


def issue_warehouse_wheel_session_token() -> "WarehouseWheelSessionToken":
    return WarehouseWheelSessionToken()


def _bounded_down_delta(delta: Any) -> int:
    try:
        value = int(delta)
    except (TypeError, ValueError):
        return DEFAULT_WHEEL_DELTA
    if value >= 0:
        return DEFAULT_WHEEL_DELTA
    if value < -WHEEL_DELTA_NOTCH:
        return DEFAULT_WHEEL_DELTA
    return value


def _as_hwnd(value: Any) -> Optional[int]:
    try:
        hwnd = int(value)
    except (TypeError, ValueError):
        return None
    return hwnd if hwnd else None


def _cancelled(token: Any) -> bool:
    if token is None:
        return False
    if hasattr(token, "is_cancelled"):
        return bool(token.is_cancelled())
    if hasattr(token, "cancelled"):
        cancelled = token.cancelled
        return bool(cancelled() if callable(cancelled) else cancelled)
    if callable(token):
        return bool(token())
    return False


class WarehouseWheelSessionToken:
    """Explicit, single-use session token. Reuse is always rejected."""

    def __init__(self):
        self.id = uuid.uuid4().hex
        self._consumed = False

    @property
    def consumed(self) -> bool:
        return self._consumed

    def consume(self) -> bool:
        if self._consumed:
            return False
        self._consumed = True
        return True


@dataclass
class WarehouseWheelContext:
    session_token: Any
    record_stable_key: str
    expected_stable_key: str
    hwnd: Any
    tracked_hwnd: Any
    settlement_stable: bool
    safety_point: Optional[Tuple[int, int]] = None
    warehouse_roi: Optional[Tuple[int, int, int, int]] = None
    cancellation_token: Any = None
    # New production path: warehouse visual authority is independent from the
    # settlement amount/identity stability gate. None preserves legacy direct
    # test-context semantics, where settlement_stable is still the safety bit.
    warehouse_authorized: Optional[bool] = None


class Win32WarehouseOsAdapter:
    """Real user32 adapter. Instantiating it does not enable production."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._user32 = ctypes.windll.user32
        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self._user32.GetCursorPos.restype = wintypes.BOOL
        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = wintypes.BOOL
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self._user32.IsWindowVisible.restype = wintypes.BOOL
        self._user32.IsIconic.argtypes = [wintypes.HWND]
        self._user32.IsIconic.restype = wintypes.BOOL
        self._user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self._user32.GetClientRect.restype = wintypes.BOOL
        self._user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self._user32.ClientToScreen.restype = wintypes.BOOL

    def get_cursor_pos(self) -> Tuple[int, int]:
        point = self._wintypes.POINT()
        if not self._user32.GetCursorPos(self._ctypes.byref(point)):
            raise OSError("GetCursorPos failed")
        return int(point.x), int(point.y)

    def set_cursor_pos(self, x: int, y: int) -> None:
        if not self._user32.SetCursorPos(int(x), int(y)):
            raise OSError("SetCursorPos failed")

    def send_mouse_wheel(self, delta: int, extra_info: int) -> None:
        ctypes = self._ctypes
        wintypes = self._wintypes
        ulong_ptr = ctypes.c_size_t

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = (
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            )

        class _INPUTUNION(ctypes.Union):
            _fields_ = (("mi", MOUSEINPUT),)

        class INPUT(ctypes.Structure):
            _fields_ = (("type", wintypes.DWORD), ("union", _INPUTUNION))

        mouse_data = ctypes.c_int32(int(delta)).value
        if mouse_data < 0:
            mouse_data = mouse_data & 0xFFFFFFFF
        payload = INPUT()
        payload.type = 0  # INPUT_MOUSE
        payload.union.mi.dx = 0
        payload.union.mi.dy = 0
        payload.union.mi.mouseData = mouse_data
        payload.union.mi.dwFlags = 0x0800  # MOUSEEVENTF_WHEEL
        payload.union.mi.time = 0
        payload.union.mi.dwExtraInfo = int(extra_info)
        sent = self._user32.SendInput(1, ctypes.byref(payload), ctypes.sizeof(INPUT))
        if sent != 1:
            raise OSError("SendInput wheel failed")

    def get_foreground_window(self) -> int:
        return int(self._user32.GetForegroundWindow() or 0)

    def is_window(self, hwnd: int) -> bool:
        return bool(self._user32.IsWindow(int(hwnd)))

    def is_window_visible(self, hwnd: int) -> bool:
        return bool(self._user32.IsWindowVisible(int(hwnd)))

    def is_iconic(self, hwnd: int) -> bool:
        return bool(self._user32.IsIconic(int(hwnd)))

    def get_client_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        rect = self._wintypes.RECT()
        if not self._user32.GetClientRect(int(hwnd), self._ctypes.byref(rect)):
            raise OSError("GetClientRect failed")
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)

    def client_to_screen(self, hwnd: int, x: int, y: int) -> Tuple[int, int]:
        point = self._wintypes.POINT(int(x), int(y))
        if not self._user32.ClientToScreen(int(hwnd), self._ctypes.byref(point)):
            raise OSError("ClientToScreen failed")
        return int(point.x), int(point.y)


class WarehouseWheelDriver:
    """begin / scroll_once / end safety shell. Adapter must be injected."""

    def __init__(self, os_adapter: Any = None, wheel_delta: int = DEFAULT_WHEEL_DELTA):
        self._adapter = os_adapter
        self._wheel_delta = _bounded_down_delta(wheel_delta)
        self._armed = False
        self._wheel_sent = False
        self._cursor_moved = False
        self._cursor_restored = False
        self._saved_cursor: Optional[Tuple[int, int]] = None
        self._context: Optional[WarehouseWheelContext] = None
        self._safety_screen: Optional[Tuple[int, int]] = None

    @property
    def armed(self) -> bool:
        return self._armed

    def begin(self, context: Any) -> Dict[str, Any]:
        if self._armed:
            return self._result(False, REASON_ALREADY_ARMED)
        self._reset_progress()
        try:
            reason = self._precheck(context, require_token_fresh=True)
            if reason:
                return self._result(False, reason)
            if self._adapter is None:
                return self._result(False, REASON_ADAPTER_MISSING)
            pos = self._adapter.get_cursor_pos()
            self._saved_cursor = (int(pos[0]), int(pos[1]))
            token = context.session_token
            if not token.consume():
                self._saved_cursor = None
                return self._result(False, REASON_TOKEN_REUSED)
            self._context = context
            self._armed = True
            return self._result(True, REASON_OK)
        except Exception:
            self._cleanup()
            return self._result(False, REASON_ADAPTER_ERROR)

    def scroll_once(self) -> Dict[str, Any]:
        if not self._armed or self._context is None:
            return self._result(False, REASON_NOT_ARMED)
        if self._wheel_sent:
            return self._result(False, REASON_ALREADY_SCROLLED)
        try:
            reason = self._precheck(self._context, require_token_fresh=False)
            if reason:
                self._cleanup()
                return self._result(False, reason)
            sx, sy = self._safety_screen or (None, None)
            if sx is None or sy is None:
                self._cleanup()
                return self._result(False, REASON_INVALID_ROI)
            self._adapter.set_cursor_pos(int(sx), int(sy))
            self._cursor_moved = True
            reason = self._precheck(self._context, require_token_fresh=False)
            if reason:
                self._cleanup()
                return self._result(False, reason)
            delta = _bounded_down_delta(self._wheel_delta)
            self._adapter.send_mouse_wheel(delta, WAREHOUSE_WHEEL_EXTRA_INFO)
            self._wheel_sent = True
            return self._result(True, REASON_OK)
        except Exception:
            self._cleanup()
            return self._result(False, REASON_ADAPTER_ERROR)

    def end(self) -> Dict[str, Any]:
        try:
            self._cleanup()
            return self._result(True, REASON_OK)
        except Exception:
            self._armed = False
            self._context = None
            return self._result(False, REASON_ADAPTER_ERROR)

    def _reset_progress(self) -> None:
        self._wheel_sent = False
        self._cursor_moved = False
        self._cursor_restored = False
        self._saved_cursor = None
        self._context = None
        self._safety_screen = None

    def _cleanup(self) -> None:
        saved = self._saved_cursor
        self._armed = False
        self._context = None
        self._safety_screen = None
        self._saved_cursor = None
        if saved is None or self._adapter is None:
            return
        try:
            self._adapter.set_cursor_pos(int(saved[0]), int(saved[1]))
            self._cursor_restored = True
        except Exception:
            self._cursor_restored = False

    def _result(self, ok: bool, reason: str) -> Dict[str, Any]:
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "ok": bool(ok),
            "reason": reason,
            "armed": self._armed,
            "wheelSent": self._wheel_sent,
            "cursorMoved": self._cursor_moved,
            "cursorRestored": self._cursor_restored,
        }
        extra = set(payload) - set(RESULT_KEYS)
        for key in extra:
            payload.pop(key, None)
        return payload

    def _precheck(self, context: Any, *, require_token_fresh: bool) -> Optional[str]:
        if self._adapter is None:
            return REASON_ADAPTER_MISSING
        if not isinstance(context, WarehouseWheelContext):
            return REASON_NOT_STABLE_SETTLEMENT
        token = context.session_token
        if not isinstance(token, WarehouseWheelSessionToken):
            return REASON_MISSING_TOKEN
        if require_token_fresh and token.consumed:
            return REASON_TOKEN_REUSED
        if _cancelled(context.cancellation_token):
            return REASON_CANCELLED
        if context.warehouse_authorized is None:
            if not context.settlement_stable:
                return REASON_NOT_STABLE_SETTLEMENT
        elif not context.warehouse_authorized:
            return REASON_WAREHOUSE_NOT_PRESENT
        record_key = str(context.record_stable_key or "").strip()
        expected_key = str(context.expected_stable_key or "").strip()
        if not record_key or not expected_key or record_key != expected_key:
            return REASON_STABLE_KEY_MISMATCH
        hwnd = _as_hwnd(context.hwnd)
        tracked = _as_hwnd(context.tracked_hwnd)
        if hwnd is None or tracked is None:
            return REASON_HWND_INVALID
        if hwnd != tracked:
            return REASON_HWND_MISMATCH
        try:
            if not self._adapter.is_window(hwnd):
                return REASON_HWND_INVALID
            if not self._adapter.is_window_visible(hwnd):
                return REASON_HWND_HIDDEN
            if self._adapter.is_iconic(hwnd):
                return REASON_HWND_MINIMIZED
            foreground = int(self._adapter.get_foreground_window() or 0)
            if foreground != hwnd:
                return REASON_NOT_FOREGROUND
            rect = self._adapter.get_client_rect(hwnd)
            mapped = self._resolve_geometry(context, hwnd, rect)
        except Exception:
            return REASON_ADAPTER_ERROR
        if mapped is None:
            return getattr(self, "_geometry_reason", REASON_INVALID_ROI)
        self._safety_screen = mapped
        return None

    def _resolve_geometry(
        self,
        context: WarehouseWheelContext,
        hwnd: int,
        rect: Sequence[int],
    ) -> Optional[Tuple[int, int]]:
        self._geometry_reason = REASON_INVALID_ROI
        if rect is None or len(rect) != 4:
            return None
        left, top, right, bottom = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
        width = right - left
        height = bottom - top
        if width < 2 or height < 2:
            return None
        if context.warehouse_roi is None:
            x1, y1, x2, y2 = warehouse_search_roi(width, height)
            x1 += left
            y1 += top
            x2 += left
            y2 += top
        else:
            x1, y1, x2, y2 = (int(v) for v in context.warehouse_roi)
        if not (left <= x1 < x2 <= right and top <= y1 < y2 <= bottom):
            return None
        if (x2 - x1) < 2 or (y2 - y1) < 2:
            return None
        if context.safety_point is None:
            sx, sy = (x1 + x2) // 2, (y1 + y2) // 2
        else:
            sx, sy = int(context.safety_point[0]), int(context.safety_point[1])
        if not (x1 < sx < x2 and y1 < sy < y2):
            self._geometry_reason = REASON_SAFETY_POINT_OUTSIDE
            return None
        origin = self._adapter.client_to_screen(hwnd, left, top)
        far = self._adapter.client_to_screen(hwnd, right, bottom)
        safety = self._adapter.client_to_screen(hwnd, sx, sy)
        if origin is None or far is None or safety is None:
            return None
        ox, oy = int(origin[0]), int(origin[1])
        fx, fy = int(far[0]), int(far[1])
        psx, psy = int(safety[0]), int(safety[1])
        if fx <= ox or fy <= oy:
            return None
        if not (ox < psx < fx and oy < psy < fy):
            self._geometry_reason = REASON_SAFETY_POINT_OUTSIDE
            return None
        return psx, psy
