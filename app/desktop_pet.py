"""Lightweight native per-pixel Desktop Pet presentation host.

The Pet runs on the application's existing WinForms STA.  It owns no WebView,
business runtime, or mascot selection rules; it only renders immutable mascot
presentation snapshots produced by the native coordinator.
"""

from __future__ import annotations

import ctypes
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from ctypes import wintypes

from mascot_presentation_state import MascotPresentationSnapshot


PET_WINDOW_TITLE = "异环拍卖助手桌宠"
PET_STATE_SCHEMA_VERSION = 1
ALPHA_HIT_THRESHOLD = 8
WM_NCHITTEST = 0x0084
WM_DPICHANGED = 0x02E0
WM_SYSCOMMAND = 0x0112
WM_LBUTTONDBLCLK = 0x0203
PET_TOGGLE_SYSTEM_COMMAND = 0x1E10
HTCLIENT = 1
HTTRANSPARENT = -1
GWL_EXSTYLE = -20
GWLP_WNDPROC = -4
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
BI_RGB = 0
DIB_RGB_COLORS = 0
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_BYCOMMAND = 0x0000


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class POINT(ctypes.Structure):
    _fields_ = (("x", ctypes.c_long), ("y", ctypes.c_long))


class SIZE(ctypes.Structure):
    _fields_ = (("cx", ctypes.c_long), ("cy", ctypes.c_long))


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = (
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    )


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = (
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    )


class RGBQUAD(ctypes.Structure):
    _fields_ = (
        ("rgbBlue", ctypes.c_ubyte),
        ("rgbGreen", ctypes.c_ubyte),
        ("rgbRed", ctypes.c_ubyte),
        ("rgbReserved", ctypes.c_ubyte),
    )


class BITMAPINFO(ctypes.Structure):
    _fields_ = (("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1))


@dataclass(frozen=True)
class MonitorWorkArea:
    device_name: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class DesktopPetPositionState:
    visible: bool = False
    monitor_device_name: str = ""
    x: Optional[int] = None
    y: Optional[int] = None
    saved_dpi: int = 96


class DesktopPetPositionStore:
    """Atomic LocalAppData persistence for presentation-only Pet placement."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else self.default_path()

    @staticmethod
    def default_path() -> Path:
        from runtime_data import is_isolated_trial, resolve_runtime_data_root
        if is_isolated_trial():
            return resolve_runtime_data_root() / 'state/desktop_pet_state_v1.json'
        local_app_data = os.environ.get("LOCALAPPDATA")
        root = Path(local_app_data) if local_app_data else Path.home() / "AppData/Local"
        return root / "异环拍卖助手" / "desktop_pet_state_v1.json"

    def load(self) -> DesktopPetPositionState:
        try:
            with self.path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
                raise ValueError("unsupported Desktop Pet state")
            visible = payload.get("visible")
            x = payload.get("x")
            y = payload.get("y")
            saved_dpi = payload.get("savedDpi")
            monitor = payload.get("monitorDeviceName")
            if not isinstance(visible, bool):
                raise ValueError("invalid visibility")
            if x is not None and not isinstance(x, int):
                raise ValueError("invalid x")
            if y is not None and not isinstance(y, int):
                raise ValueError("invalid y")
            if not isinstance(saved_dpi, int) or not 72 <= saved_dpi <= 480:
                raise ValueError("invalid dpi")
            if not isinstance(monitor, str):
                raise ValueError("invalid monitor")
            return DesktopPetPositionState(visible, monitor, x, y, saved_dpi)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return DesktopPetPositionState()

    def save(self, state: DesktopPetPositionState) -> None:
        payload = {
            "schemaVersion": PET_STATE_SCHEMA_VERSION,
            "visible": bool(state.visible),
            "monitorDeviceName": str(state.monitor_device_name),
            "x": int(state.x) if state.x is not None else None,
            "y": int(state.y) if state.y is not None else None,
            "savedDpi": int(state.saved_dpi),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)


def clamp_pet_position(
    requested_x: Optional[int],
    requested_y: Optional[int],
    width: int,
    height: int,
    monitors: Iterable[MonitorWorkArea],
    preferred_monitor: str = "",
    margin: int = 12,
) -> tuple[int, int, str]:
    """Return a fully visible virtual-desktop position, preserving negatives."""
    monitor_list = tuple(monitors)
    if not monitor_list:
        raise ValueError("At least one monitor work area is required")

    preferred = next(
        (item for item in monitor_list if item.device_name == preferred_monitor), None
    )
    if preferred is None and requested_x is not None and requested_y is not None:
        preferred = next(
            (
                item
                for item in monitor_list
                if item.left <= requested_x < item.right
                and item.top <= requested_y < item.bottom
            ),
            None,
        )
    target = preferred or monitor_list[0]

    max_x = max(target.left + margin, target.right - width - margin)
    max_y = max(target.top + margin, target.bottom - height - margin)
    default_x = max_x
    default_y = max_y
    x = default_x if requested_x is None else int(requested_x)
    y = default_y if requested_y is None else int(requested_y)
    x = min(max(x, target.left + margin), max_x)
    y = min(max(y, target.top + margin), max_y)
    return x, y, target.device_name


def alpha_hit_test(
    alpha_mask: bytes,
    width: int,
    height: int,
    x: int,
    y: int,
    threshold: int = ALPHA_HIT_THRESHOLD,
) -> bool:
    """True only when a local point belongs to an authored visible pixel."""
    if x < 0 or y < 0 or x >= width or y >= height:
        return False
    index = y * width + x
    return index < len(alpha_mask) and alpha_mask[index] >= threshold


class _LayeredWindowApi:
    """Typed Win32/GDI boundary used only by the native Pet renderer."""

    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

        self.user32.GetDC.argtypes = [wintypes.HWND]
        self.user32.GetDC.restype = wintypes.HDC
        self.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.user32.ReleaseDC.restype = ctypes.c_int
        self.user32.UpdateLayeredWindow.argtypes = [
            wintypes.HWND,
            wintypes.HDC,
            ctypes.POINTER(POINT),
            ctypes.POINTER(SIZE),
            wintypes.HDC,
            ctypes.POINTER(POINT),
            wintypes.COLORREF,
            ctypes.POINTER(BLENDFUNCTION),
            wintypes.DWORD,
        ]
        self.user32.UpdateLayeredWindow.restype = wintypes.BOOL
        self.user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self.user32.SetWindowPos.restype = wintypes.BOOL
        self.user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        self.user32.GetDpiForWindow.restype = wintypes.UINT
        self.user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.CallWindowProcW.restype = ctypes.c_ssize_t
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.IsWindow.restype = wintypes.BOOL
        self.user32.GetSystemMenu.argtypes = [wintypes.HWND, wintypes.BOOL]
        self.user32.GetSystemMenu.restype = wintypes.HMENU
        self.user32.AppendMenuW.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_size_t,
            wintypes.LPCWSTR,
        ]
        self.user32.AppendMenuW.restype = wintypes.BOOL
        self.user32.DeleteMenu.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self.user32.DeleteMenu.restype = wintypes.BOOL
        self.user32.DrawMenuBar.argtypes = [wintypes.HWND]
        self.user32.DrawMenuBar.restype = wintypes.BOOL

        pointer_type = ctypes.c_ssize_t
        get_long = getattr(self.user32, "GetWindowLongPtrW", self.user32.GetWindowLongW)
        set_long = getattr(self.user32, "SetWindowLongPtrW", self.user32.SetWindowLongW)
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_long.restype = pointer_type
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, pointer_type]
        set_long.restype = pointer_type
        self._get_window_long = get_long
        self._set_window_long = set_long

        self.gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self.gdi32.DeleteDC.restype = wintypes.BOOL
        self.gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        self.gdi32.SelectObject.restype = wintypes.HANDLE
        self.gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        self.gdi32.DeleteObject.restype = wintypes.BOOL
        self.gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(BITMAPINFO),
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        self.gdi32.CreateDIBSection.restype = wintypes.HANDLE

    def add_layered_styles(self, hwnd: int) -> None:
        current = int(self._get_window_long(hwnd, GWL_EXSTYLE))
        self._set_window_long(hwnd, GWL_EXSTYLE, current | WS_EX_LAYERED | WS_EX_TOOLWINDOW)

    def install_wndproc(self, hwnd: int, callback: WNDPROC) -> int:
        ctypes.set_last_error(0)
        pointer = ctypes.cast(callback, ctypes.c_void_p).value
        previous = int(self._set_window_long(hwnd, GWLP_WNDPROC, pointer))
        error = ctypes.get_last_error()
        if previous == 0 and error:
            raise ctypes.WinError(error)
        return previous

    def restore_wndproc(self, hwnd: int, previous: int) -> None:
        if previous and self.user32.IsWindow(hwnd):
            self._set_window_long(hwnd, GWLP_WNDPROC, previous)

    def call_wndproc(
        self, previous: int, hwnd: int, message: int, wparam: int, lparam: int
    ) -> int:
        return int(
            self.user32.CallWindowProcW(previous, hwnd, message, wparam, lparam)
        )

    def install_pet_system_menu(self, hwnd: int) -> None:
        menu = self.user32.GetSystemMenu(hwnd, False)
        if not menu:
            raise ctypes.WinError(ctypes.get_last_error())
        self.user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        if not self.user32.AppendMenuW(
            menu,
            MF_STRING,
            PET_TOGGLE_SYSTEM_COMMAND,
            "显示 / 隐藏桌宠",
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        self.user32.DrawMenuBar(hwnd)

    def remove_pet_system_menu(self, hwnd: int) -> None:
        if not self.user32.IsWindow(hwnd):
            return
        menu = self.user32.GetSystemMenu(hwnd, False)
        if menu:
            self.user32.DeleteMenu(menu, PET_TOGGLE_SYSTEM_COMMAND, MF_BYCOMMAND)
            self.user32.DrawMenuBar(hwnd)

    def dpi_for_window(self, hwnd: int) -> int:
        try:
            dpi = int(self.user32.GetDpiForWindow(hwnd))
            return dpi if 72 <= dpi <= 480 else 96
        except Exception:
            return 96

    def keep_topmost(self, hwnd: int, x: int, y: int) -> None:
        self.user32.SetWindowPos(
            hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE
        )

    def update(
        self, hwnd: int, x: int, y: int, width: int, height: int, pixels: bytes
    ) -> None:
        screen_dc = self.user32.GetDC(0)
        memory_dc = self.gdi32.CreateCompatibleDC(screen_dc)
        bitmap = None
        old_bitmap = None
        try:
            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = BI_RGB
            bits = ctypes.c_void_p()
            bitmap = self.gdi32.CreateDIBSection(
                screen_dc, ctypes.byref(info), DIB_RGB_COLORS, ctypes.byref(bits), 0, 0
            )
            if not bitmap or not bits.value:
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.memmove(bits.value, pixels, len(pixels))
            old_bitmap = self.gdi32.SelectObject(memory_dc, bitmap)
            destination = POINT(x, y)
            extent = SIZE(width, height)
            source = POINT(0, 0)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            if not self.user32.UpdateLayeredWindow(
                hwnd,
                screen_dc,
                ctypes.byref(destination),
                ctypes.byref(extent),
                memory_dc,
                ctypes.byref(source),
                0,
                ctypes.byref(blend),
                ULW_ALPHA,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if old_bitmap:
                self.gdi32.SelectObject(memory_dc, old_bitmap)
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            if memory_dc:
                self.gdi32.DeleteDC(memory_dc)
            if screen_dc:
                self.user32.ReleaseDC(0, screen_dc)


def _asset_uri_to_path(uri: str) -> Path:
    parsed = urlparse(str(uri))
    if parsed.scheme != "file":
        raise ValueError("Desktop Pet assets must be verified local files")
    path_text = url2pathname(unquote(parsed.path))
    if parsed.netloc:
        path_text = f"//{parsed.netloc}{path_text}"
    return Path(path_text).resolve()


def _screen_work_areas(WinForms) -> tuple[MonitorWorkArea, ...]:
    rows = []
    for screen in WinForms.Screen.AllScreens:
        area = screen.WorkingArea
        rows.append(
            MonitorWorkArea(
                str(screen.DeviceName), area.Left, area.Top, area.Right, area.Bottom
            )
        )
    primary_name = str(WinForms.Screen.PrimaryScreen.DeviceName)
    rows.sort(key=lambda row: row.device_name != primary_name)
    return tuple(rows)


def _extract_scaled_pargb(Drawing, asset_path: Path, dpi: int) -> tuple[int, int, bytes, bytes]:
    from System.Drawing.Drawing2D import (
        CompositingMode,
        CompositingQuality,
        InterpolationMode,
        PixelOffsetMode,
        SmoothingMode,
    )
    from System.Drawing.Imaging import ImageLockMode, PixelFormat

    source = Drawing.Bitmap(str(asset_path))
    scale = max(0.75, min(5.0, float(dpi) / 96.0))
    width = max(1, int(round(source.Width * scale)))
    height = max(1, int(round(source.Height * scale)))
    rendered = Drawing.Bitmap(width, height, PixelFormat.Format32bppPArgb)
    graphics = Drawing.Graphics.FromImage(rendered)
    try:
        graphics.CompositingMode = CompositingMode.SourceCopy
        graphics.CompositingQuality = CompositingQuality.HighQuality
        graphics.InterpolationMode = InterpolationMode.HighQualityBicubic
        graphics.SmoothingMode = SmoothingMode.HighQuality
        graphics.PixelOffsetMode = PixelOffsetMode.HighQuality
        graphics.DrawImage(
            source,
            Drawing.Rectangle(0, 0, width, height),
            0,
            0,
            source.Width,
            source.Height,
            Drawing.GraphicsUnit.Pixel,
        )
    finally:
        graphics.Dispose()
        source.Dispose()

    rectangle = Drawing.Rectangle(0, 0, width, height)
    data = rendered.LockBits(
        rectangle, ImageLockMode.ReadOnly, PixelFormat.Format32bppPArgb
    )
    try:
        stride = int(data.Stride)
        row_size = width * 4
        scan0 = int(data.Scan0.ToInt64())
        rows = bytearray(row_size * height)
        for row in range(height):
            address = scan0 + row * stride
            rows[row * row_size : (row + 1) * row_size] = ctypes.string_at(
                address, row_size
            )
        alpha = bytes(rows[index] for index in range(3, len(rows), 4))
        return width, height, bytes(rows), alpha
    finally:
        rendered.UnlockBits(data)
        rendered.Dispose()


def create_desktop_pet_form_type(WinForms, Drawing):
    """Create the Form type only after the caller has initialized pythonnet."""

    class DesktopPetForm(WinForms.Form):
        def __init__(self, controller):
            WinForms.Form.__init__(self)
            self._controller = controller
            self.Text = PET_WINDOW_TITLE
            self.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
            self.ShowInTaskbar = False
            self.TopMost = True
            self.StartPosition = WinForms.FormStartPosition.Manual
            self.AutoScaleMode = getattr(WinForms.AutoScaleMode, "None")
            self.BackColor = Drawing.Color.Black

    DesktopPetForm.__name__ = "DesktopPetForm"
    return DesktopPetForm


class DesktopPetController:
    """Exactly-one Pet Form/controller living on the existing GUI STA."""

    def __init__(
        self,
        WinForms,
        Drawing,
        main_window,
        mascot_presentation: Mapping,
        mascot_state_provider: Callable[[str], MascotPresentationSnapshot],
        position_store: Optional[DesktopPetPositionStore] = None,
        logger: Optional[Callable[[str, str], None]] = None,
        poll_interval_ms: int = 750,
    ):
        self._WinForms = WinForms
        self._Drawing = Drawing
        self._main_window = main_window
        self._mascot_presentation = mascot_presentation
        self._mascot_state_provider = mascot_state_provider
        self._position_store = position_store or DesktopPetPositionStore()
        self._logger = logger
        self._poll_interval_ms = int(poll_interval_ms)
        self._api = _LayeredWindowApi()
        self._form = None
        self._form_identity = None
        self._created_once = False
        self._accepting_commands = True
        self._shutting_down = False
        self._disposed = False
        self._allow_close = False
        self._timer = None
        self._context_menu = None
        self._handlers = {}
        self._alpha_mask = b""
        self._pixel_width = 0
        self._pixel_height = 0
        self._dpi = 96
        self._current_snapshot = None
        self._drag_origin_cursor = None
        self._drag_origin_window = None
        self._dragging = False
        self._stored_visibility = False
        self._monitor_device_name = ""
        self._pet_wndproc = None
        self._pet_previous_wndproc = 0
        self._main_wndproc = None
        self._main_previous_wndproc = 0
        self._main_menu_installed = False

    @property
    def form(self):
        return self._form

    @property
    def form_identity(self):
        return self._form_identity

    @property
    def hwnd(self) -> int:
        if self._form is None or self._form.IsDisposed:
            return 0
        return int(self._form.Handle.ToInt64())

    @property
    def visible(self) -> bool:
        return bool(self._form is not None and not self._form.IsDisposed and self._form.Visible)

    @property
    def current_snapshot(self) -> Optional[MascotPresentationSnapshot]:
        return self._current_snapshot

    def create(self):
        if self._form is not None and not self._form.IsDisposed:
            return self._form
        if self._created_once:
            raise RuntimeError("Desktop Pet cannot be recreated after disposal")
        self._created_once = True

        form_type = create_desktop_pet_form_type(self._WinForms, self._Drawing)
        form = form_type(self)
        self._form = form
        self._form_identity = id(form)
        hwnd = int(form.Handle.ToInt64())
        self._api.add_layered_styles(hwnd)
        self._install_pet_wndproc()
        self._bind_handlers()
        self._build_context_menu()

        persisted = self._position_store.load()
        self._stored_visibility = persisted.visible
        self._dpi = persisted.saved_dpi
        initial = self._mascot_state_provider("ready")
        self._apply_snapshot(initial, persisted.x, persisted.y, persisted.monitor_device_name)
        if persisted.visible:
            form.Show()
            self._api.keep_topmost(hwnd, int(form.Left), int(form.Top))

        actual_dpi = self._api.dpi_for_window(hwnd)
        if actual_dpi != self._dpi:
            self.handle_dpi_changed(actual_dpi)

        timer = self._WinForms.Timer()
        timer.Interval = self._poll_interval_ms
        self._handlers["timer"] = self._on_timer_tick
        timer.Tick += self._handlers["timer"]
        timer.Start()
        self._timer = timer
        self._log(
            "STARTUP:PET",
            f"Desktop Pet ready HWND={hwnd} state={initial.state} "
            f"assetId={initial.asset_id} visible={persisted.visible}",
        )
        return form

    def install_main_window_menu(self) -> None:
        if self._main_menu_installed:
            return
        main_hwnd = int(self._main_window.Handle.ToInt64())

        @WNDPROC
        def main_wndproc(hwnd, message, wparam, lparam):
            if (
                message == WM_SYSCOMMAND
                and (int(wparam) & 0xFFF0) == PET_TOGGLE_SYSTEM_COMMAND
            ):
                self.toggle()
                return 0
            return self._api.call_wndproc(
                self._main_previous_wndproc,
                int(hwnd),
                int(message),
                int(wparam),
                int(lparam),
            )

        self._main_wndproc = main_wndproc
        self._main_previous_wndproc = self._api.install_wndproc(
            main_hwnd, self._main_wndproc
        )
        self._api.install_pet_system_menu(main_hwnd)
        self._main_menu_installed = True

    def show(self) -> bool:
        if not self._accepting_commands or self._form is None or self._form.IsDisposed:
            return self.visible
        self._form.Show()
        self._api.keep_topmost(self.hwnd, int(self._form.Left), int(self._form.Top))
        self._stored_visibility = True
        self._save_position(True)
        return self.visible

    def hide(self) -> bool:
        if not self._accepting_commands or self._form is None or self._form.IsDisposed:
            return self.visible
        self._stored_visibility = False
        self._save_position(False)
        self._form.Hide()
        return self.visible

    def toggle(self) -> bool:
        return self.hide() if self.visible else self.show()

    def begin_shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._accepting_commands = False
        self._stop_timer()
        try:
            self._apply_snapshot(self._mascot_state_provider("shutting_down"))
        except Exception as exc:
            self._log("SHUTDOWN:PET", f"sleep state publish warning: {exc}")

    def close(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._accepting_commands = False
        self._shutting_down = True
        self._stop_timer()
        self._save_position(self._stored_visibility)
        self._remove_window_hooks()
        self._unbind_handlers()
        if self._context_menu is not None:
            self._context_menu.Dispose()
            self._context_menu = None
        form = self._form
        if form is not None and not form.IsDisposed:
            self._allow_close = True
            form.Close()
            form.Dispose()
        self._alpha_mask = b""
        self._pixel_width = 0
        self._pixel_height = 0
        self._log("SHUTDOWN:PET", "Desktop Pet native resources released")

    def is_interactive_point(self, x: int, y: int) -> bool:
        return alpha_hit_test(
            self._alpha_mask,
            self._pixel_width,
            self._pixel_height,
            int(x),
            int(y),
        )

    def handle_dpi_changed(self, dpi: int) -> None:
        if self._disposed or not 72 <= int(dpi) <= 480 or int(dpi) == self._dpi:
            return
        self._dpi = int(dpi)
        if self._current_snapshot is not None:
            self._apply_snapshot(self._current_snapshot)

    def _bind_handlers(self) -> None:
        self._handlers.update(
            {
                "mouse_down": self._on_mouse_down,
                "mouse_move": self._on_mouse_move,
                "mouse_up": self._on_mouse_up,
                "form_closing": self._on_form_closing,
            }
        )
        self._form.MouseDown += self._handlers["mouse_down"]
        self._form.MouseMove += self._handlers["mouse_move"]
        self._form.MouseUp += self._handlers["mouse_up"]
        self._form.FormClosing += self._handlers["form_closing"]

    def _install_pet_wndproc(self) -> None:
        @WNDPROC
        def pet_wndproc(hwnd, message, wparam, lparam):
            if message == WM_NCHITTEST:
                packed = int(lparam)
                screen_x = ctypes.c_short(packed & 0xFFFF).value
                screen_y = ctypes.c_short((packed >> 16) & 0xFFFF).value
                if not self.is_interactive_point(
                    screen_x - int(self._form.Left),
                    screen_y - int(self._form.Top),
                ):
                    return HTTRANSPARENT
            if message == WM_LBUTTONDBLCLK and self._accepting_commands:
                self._show_main_window()
            result = self._api.call_wndproc(
                self._pet_previous_wndproc,
                int(hwnd),
                int(message),
                int(wparam),
                int(lparam),
            )
            if message == WM_DPICHANGED:
                self.handle_dpi_changed(int(wparam) & 0xFFFF)
            return result

        self._pet_wndproc = pet_wndproc
        self._pet_previous_wndproc = self._api.install_wndproc(
            self.hwnd, self._pet_wndproc
        )

    def _remove_window_hooks(self) -> None:
        if self._main_menu_installed:
            main_hwnd = int(self._main_window.Handle.ToInt64())
            self._api.remove_pet_system_menu(main_hwnd)
            self._api.restore_wndproc(main_hwnd, self._main_previous_wndproc)
            self._main_menu_installed = False
            self._main_previous_wndproc = 0
            self._main_wndproc = None
        if self.hwnd:
            self._api.restore_wndproc(self.hwnd, self._pet_previous_wndproc)
        self._pet_previous_wndproc = 0
        self._pet_wndproc = None

    def _unbind_handlers(self) -> None:
        if self._form is not None and not self._form.IsDisposed:
            for event_name, handler_name in (
                ("MouseDown", "mouse_down"),
                ("MouseMove", "mouse_move"),
                ("MouseUp", "mouse_up"),
                ("FormClosing", "form_closing"),
            ):
                handler = self._handlers.get(handler_name)
                if handler is not None:
                    try:
                        event = getattr(self._form, event_name)
                        event -= handler
                    except Exception:
                        pass
        self._handlers.clear()

    def _build_context_menu(self) -> None:
        menu = self._WinForms.ContextMenuStrip()
        open_item = menu.Items.Add("打开主窗口")
        hide_item = menu.Items.Add("隐藏桌宠")
        self._handlers["open_main"] = lambda sender, event: self._show_main_window()
        self._handlers["hide_pet"] = lambda sender, event: self.hide()
        open_item.Click += self._handlers["open_main"]
        hide_item.Click += self._handlers["hide_pet"]
        self._context_menu = menu

    def _on_timer_tick(self, sender, event) -> None:
        if self._disposed or self._shutting_down:
            return
        try:
            snapshot = self._mascot_state_provider("ready")
            if snapshot != self._current_snapshot:
                self._apply_snapshot(snapshot)
        except Exception as exc:
            self._log("ACTION:PET", f"state update warning: {exc}")

    def _on_mouse_down(self, sender, event) -> None:
        if not self._accepting_commands:
            return
        if event.Button == self._WinForms.MouseButtons.Left:
            self._drag_origin_cursor = self._WinForms.Cursor.Position
            self._drag_origin_window = self._form.Location
            self._dragging = False
            self._form.Capture = True

    def _on_mouse_move(self, sender, event) -> None:
        if self._drag_origin_cursor is None or not self._accepting_commands:
            return
        current = self._WinForms.Cursor.Position
        dx = int(current.X - self._drag_origin_cursor.X)
        dy = int(current.Y - self._drag_origin_cursor.Y)
        if not self._dragging and abs(dx) + abs(dy) < 4:
            return
        self._dragging = True
        x = int(self._drag_origin_window.X + dx)
        y = int(self._drag_origin_window.Y + dy)
        self._form.Location = self._Drawing.Point(x, y)
        self._api.keep_topmost(self.hwnd, x, y)

    def _on_mouse_up(self, sender, event) -> None:
        if event.Button == self._WinForms.MouseButtons.Right:
            self._context_menu.Show(self._WinForms.Cursor.Position)
            return
        if event.Button == self._WinForms.MouseButtons.Left:
            self._form.Capture = False
            if self._dragging:
                self._clamp_current_position()
                self._save_position(True)
            self._drag_origin_cursor = None
            self._drag_origin_window = None
            self._dragging = False

    def _on_form_closing(self, sender, event) -> None:
        if self._allow_close or self._shutting_down:
            return
        event.Cancel = True
        self.hide()

    def _show_main_window(self) -> None:
        if self._main_window.IsDisposed:
            return
        self._main_window.Show()
        if self._main_window.WindowState == self._WinForms.FormWindowState.Minimized:
            self._main_window.WindowState = self._WinForms.FormWindowState.Normal
        self._main_window.Activate()

    def _apply_snapshot(
        self,
        snapshot: MascotPresentationSnapshot,
        requested_x: Optional[int] = None,
        requested_y: Optional[int] = None,
        preferred_monitor: str = "",
    ) -> None:
        if not isinstance(snapshot, MascotPresentationSnapshot):
            raise TypeError("Desktop Pet requires an immutable mascot snapshot")
        expected_asset = self._mascot_presentation["states"].get(snapshot.state)
        if expected_asset != snapshot.asset_id:
            raise ValueError("Mascot state/asset pair does not match the verified mapping")
        asset = self._mascot_presentation["assets"].get(snapshot.asset_id)
        if not isinstance(asset, Mapping) or asset.get("role") != "chibi_state":
            raise ValueError("Desktop Pet asset is not an approved chibi state")
        asset_path = _asset_uri_to_path(asset["uri"])
        width, height, pixels, alpha = _extract_scaled_pargb(
            self._Drawing, asset_path, self._dpi
        )

        if requested_x is None and self._form is not None and self._pixel_width:
            requested_x = int(self._form.Left + self._pixel_width - width)
            requested_y = int(self._form.Top + self._pixel_height - height)
            preferred_monitor = self._monitor_device_name
        x, y, monitor = clamp_pet_position(
            requested_x,
            requested_y,
            width,
            height,
            _screen_work_areas(self._WinForms),
            preferred_monitor,
        )
        self._api.update(self.hwnd, x, y, width, height, pixels)
        self._form.Location = self._Drawing.Point(x, y)
        self._form.Size = self._Drawing.Size(width, height)
        self._pixel_width = width
        self._pixel_height = height
        self._alpha_mask = alpha
        self._monitor_device_name = monitor
        self._current_snapshot = snapshot
        self._log(
            "ACTION:PET",
            f"Desktop Pet state={snapshot.state} assetId={snapshot.asset_id} "
            f"size={width}x{height} dpi={self._dpi}",
        )

    def _clamp_current_position(self) -> None:
        x, y, monitor = clamp_pet_position(
            int(self._form.Left),
            int(self._form.Top),
            self._pixel_width,
            self._pixel_height,
            _screen_work_areas(self._WinForms),
            self._monitor_device_name,
        )
        self._form.Location = self._Drawing.Point(x, y)
        self._api.keep_topmost(self.hwnd, x, y)
        self._monitor_device_name = monitor

    def _save_position(self, visible: bool) -> None:
        if self._form is None or self._form.IsDisposed:
            return
        try:
            screen = self._WinForms.Screen.FromRectangle(
                self._Drawing.Rectangle(
                    int(self._form.Left),
                    int(self._form.Top),
                    max(1, self._pixel_width),
                    max(1, self._pixel_height),
                )
            )
            self._monitor_device_name = str(screen.DeviceName)
            self._position_store.save(
                DesktopPetPositionState(
                    visible=bool(visible),
                    monitor_device_name=self._monitor_device_name,
                    x=int(self._form.Left),
                    y=int(self._form.Top),
                    saved_dpi=int(self._dpi),
                )
            )
        except Exception as exc:
            self._log("ACTION:PET", f"position persistence warning: {exc}")

    def _stop_timer(self) -> None:
        timer = self._timer
        self._timer = None
        if timer is None:
            return
        timer.Stop()
        handler = self._handlers.get("timer")
        if handler is not None:
            try:
                timer.Tick -= handler
            except Exception:
                pass
        timer.Dispose()

    def _log(self, category: str, message: str) -> None:
        if self._logger:
            self._logger(category, message)
