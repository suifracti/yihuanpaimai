"""Source/package smoke for the native per-pixel Desktop Pet boundary."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_TITLE = "异环拍卖助手"
OVERLAY_TITLE = "⚡ 异环拍卖战术助手 HUD"
PET_TITLE = "异环拍卖助手桌宠"
WM_CLOSE = 0x0010
WM_NCHITTEST = 0x0084
WM_SYSCOMMAND = 0x0112
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
PET_TOGGLE_COMMAND = 0x1E10
MK_LBUTTON = 0x0001
SW_HIDE = 0
HTTRANSPARENT = -1
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000


class RECT(ctypes.Structure):
    _fields_ = (
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    )


class WindowProbe:
    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.enum_proc_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        self.user32.EnumWindows.argtypes = [self.enum_proc_type, wintypes.LPARAM]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        self.user32.GetWindowRect.restype = wintypes.BOOL
        self.user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.SendMessageW.restype = ctypes.c_ssize_t
        self.user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.PostMessageW.restype = wintypes.BOOL
        self.user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        self.user32.GetDpiForWindow.restype = wintypes.UINT
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.user32.GetCursorPos.restype = wintypes.BOOL
        self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user32.SetCursorPos.restype = wintypes.BOOL
        self.user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.ShowWindow.restype = wintypes.BOOL
        get_long = getattr(
            self.user32, "GetWindowLongPtrW", self.user32.GetWindowLongW
        )
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_long.restype = ctypes.c_ssize_t
        self._get_window_long = get_long

    def text(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def windows(self, pid: int) -> list[dict]:
        rows = []

        @self.enum_proc_type
        def callback(hwnd, _lparam):
            owner_pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            if owner_pid.value == pid:
                rows.append(
                    {
                        "hwnd": int(hwnd),
                        "title": self.text(hwnd),
                        "visible": bool(self.user32.IsWindowVisible(hwnd)),
                    }
                )
            return True

        self.user32.EnumWindows(callback, 0)
        return rows

    def by_title(self, pid: int, title: str) -> list[dict]:
        return [row for row in self.windows(pid) if row["title"] == title]

    def styles(self, hwnd: int) -> int:
        return int(self._get_window_long(hwnd, GWL_EXSTYLE))

    def rect(self, hwnd: int) -> RECT:
        result = RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    @staticmethod
    def _lparam(x: int, y: int) -> int:
        return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)

    def hit_test(self, hwnd: int, screen_x: int, screen_y: int) -> int:
        return int(
            self.user32.SendMessageW(
                hwnd, WM_NCHITTEST, 0, self._lparam(screen_x, screen_y)
            )
        )

    def toggle_pet_from_main(self, main_hwnd: int) -> None:
        self.user32.SendMessageW(
            main_hwnd, WM_SYSCOMMAND, PET_TOGGLE_COMMAND, 0
        )

    def drag(self, hwnd: int, local_x: int, local_y: int, dx: int, dy: int) -> None:
        original = wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(original))
        rectangle = self.rect(hwnd)
        start_x = rectangle.left + local_x
        start_y = rectangle.top + local_y
        try:
            self.user32.SetCursorPos(start_x, start_y)
            self.user32.SendMessageW(
                hwnd,
                WM_LBUTTONDOWN,
                MK_LBUTTON,
                self._lparam(local_x, local_y),
            )
            self.user32.SetCursorPos(start_x + dx, start_y + dy)
            self.user32.SendMessageW(
                hwnd,
                WM_MOUSEMOVE,
                MK_LBUTTON,
                self._lparam(local_x + dx, local_y + dy),
            )
            self.user32.SendMessageW(
                hwnd,
                WM_LBUTTONUP,
                0,
                self._lparam(local_x + dx, local_y + dy),
            )
        finally:
            self.user32.SetCursorPos(original.x, original.y)

    def double_click(self, hwnd: int, local_x: int, local_y: int) -> None:
        self.user32.SendMessageW(
            hwnd,
            WM_LBUTTONDBLCLK,
            MK_LBUTTON,
            self._lparam(local_x, local_y),
        )

    def close(self, hwnd: int) -> None:
        self.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def wait_until(predicate, description: str, timeout: float = 35.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {description}")


def run_smoke(command: list[str], mode: str) -> dict:
    probe = WindowProbe()
    environment = os.environ.copy()
    environment["NTE_DISABLE_VISION"] = "1"
    environment["NTE_DISABLE_ICON"] = "1"
    environment["NTE_MAIN_UI_SMOKE"] = "1"

    with tempfile.TemporaryDirectory(prefix="nte-pet-smoke-") as temp_dir:
        runtime_dir = Path(temp_dir)
        log_path = runtime_dir / "runtime.log"
        environment["NTE_LOG_FILE"] = str(log_path)
        environment["LOCALAPPDATA"] = str(runtime_dir / "local-app-data")
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        main_hwnd = None
        try:
            def expected_windows():
                rows = probe.windows(process.pid)
                expected = {}
                for title in (MAIN_TITLE, OVERLAY_TITLE, PET_TITLE):
                    matches = [row for row in rows if row["title"] == title]
                    if len(matches) != 1 or not matches[0]["visible"]:
                        return None
                    expected[title] = matches[0]
                return expected

            windows = wait_until(expected_windows, "Main, Overlay, and one visible Pet")
            main_hwnd = windows[MAIN_TITLE]["hwnd"]
            overlay_hwnd = windows[OVERLAY_TITLE]["hwnd"]
            pet_hwnd = windows[PET_TITLE]["hwnd"]

            def runtime_ready():
                if not log_path.exists():
                    return False
                log = log_path.read_text(encoding="utf-8", errors="strict")
                return (
                    "Desktop Pet ready HWND=" in log
                    and "Main presentation page ready" in log
                    and "auction_engine_v06.js loaded: True" in log
                    and "15:53 regression result: PASS" in log
                )

            wait_until(runtime_ready, "Pet, Main, and Overlay Solver readiness")

            styles = probe.styles(pet_hwnd)
            assert styles & WS_EX_LAYERED, hex(styles)
            assert styles & WS_EX_TOOLWINDOW, hex(styles)
            assert styles & WS_EX_TOPMOST, hex(styles)
            assert not styles & WS_EX_TRANSPARENT, hex(styles)

            rect = probe.rect(pet_hwnd)
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            assert width > 0 and height > 0, (width, height)
            transparent_result = probe.hit_test(
                pet_hwnd, rect.left + 1, rect.top + 1
            )
            assert transparent_result == HTTRANSPARENT, transparent_result

            opaque_result = None
            opaque_point = None
            for y in range(rect.top + 2, rect.bottom - 1, max(1, height // 20)):
                for x in range(rect.left + 2, rect.right - 1, max(1, width // 20)):
                    result = probe.hit_test(pet_hwnd, x, y)
                    if result != HTTRANSPARENT:
                        opaque_result = result
                        opaque_point = [x - rect.left, y - rect.top]
                        break
                if opaque_result is not None:
                    break
            assert opaque_result is not None, "no interactive authored pixel found"

            original_rect = probe.rect(pet_hwnd)
            probe.drag(pet_hwnd, opaque_point[0], opaque_point[1], -24, -16)
            moved_rect = wait_until(
                lambda: (
                    current
                    if (
                        (current := probe.rect(pet_hwnd)).left != original_rect.left
                        or current.top != original_rect.top
                    )
                    else None
                ),
                "opaque-pixel native drag",
            )
            drag_delta = [
                moved_rect.left - original_rect.left,
                moved_rect.top - original_rect.top,
            ]
            assert drag_delta == [-24, -16], drag_delta

            probe.user32.ShowWindow(main_hwnd, SW_HIDE)
            wait_until(
                lambda: not bool(probe.user32.IsWindowVisible(main_hwnd)),
                "Main hidden for Pet double-click smoke",
            )
            probe.double_click(pet_hwnd, opaque_point[0], opaque_point[1])
            wait_until(
                lambda: bool(probe.user32.IsWindowVisible(main_hwnd)),
                "existing Main restored by Pet double-click",
            )

            probe.toggle_pet_from_main(main_hwnd)
            wait_until(
                lambda: len(probe.by_title(process.pid, PET_TITLE)) == 1
                and not probe.by_title(process.pid, PET_TITLE)[0]["visible"],
                "Pet hide through native Main system command",
            )
            probe.toggle_pet_from_main(main_hwnd)
            shown = wait_until(
                lambda: (
                    probe.by_title(process.pid, PET_TITLE)[0]
                    if len(probe.by_title(process.pid, PET_TITLE)) == 1
                    and probe.by_title(process.pid, PET_TITLE)[0]["visible"]
                    else None
                ),
                "same Pet show through native Main system command",
            )
            assert shown["hwnd"] == pet_hwnd, (shown, pet_hwnd)
            assert len(probe.by_title(process.pid, PET_TITLE)) == 1
            assert probe.user32.IsWindowVisible(overlay_hwnd)

            probe.close(pet_hwnd)
            wait_until(
                lambda: len(probe.by_title(process.pid, PET_TITLE)) == 1
                and not probe.by_title(process.pid, PET_TITLE)[0]["visible"],
                "Pet WM_CLOSE redirected to Hide",
            )
            probe.toggle_pet_from_main(main_hwnd)
            reshown = wait_until(
                lambda: (
                    probe.by_title(process.pid, PET_TITLE)[0]
                    if len(probe.by_title(process.pid, PET_TITLE)) == 1
                    and probe.by_title(process.pid, PET_TITLE)[0]["visible"]
                    else None
                ),
                "Pet restore after WM_CLOSE",
            )
            assert reshown["hwnd"] == pet_hwnd

            state_path = (
                Path(environment["LOCALAPPDATA"])
                / "异环拍卖助手"
                / "desktop_pet_state_v1.json"
            )
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            assert persisted["schemaVersion"] == 1
            assert persisted["visible"] is True
            assert isinstance(persisted["x"], int)
            assert isinstance(persisted["y"], int)
            assert 72 <= persisted["savedDpi"] <= 480

            pet_dpi = int(probe.user32.GetDpiForWindow(pet_hwnd))
            assert 72 <= pet_dpi <= 480, pet_dpi

            probe.close(main_hwnd)
            process.wait(timeout=20)
            assert process.returncode == 0, process.returncode
            return {
                "mode": mode,
                "petHwnd": pet_hwnd,
                "exactlyOnePet": "PASS",
                "samePetHideShow": "PASS",
                "layeredTopmostToolWindow": "PASS",
                "fullWindowClickThroughDisabled": "PASS",
                "transparentPixelPassThrough": "PASS",
                "opaquePixelInteractive": "PASS",
                "opaquePoint": opaque_point,
                "dragDelta": drag_delta,
                "opaquePixelDrag": "PASS",
                "doubleClickExistingMain": "PASS",
                "petCloseRedirectedToHide": "PASS",
                "positionPersistence": "PASS",
                "dpi": pet_dpi,
                "overlayUnaffected": "PASS",
                "solverOwnerRegression": "PASS",
                "cleanExit": "PASS",
            }
        finally:
            if process.poll() is None:
                if main_hwnd:
                    probe.close(main_hwnd)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                else:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source", action="store_true")
    source.add_argument("--exe", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.source:
        command = [sys.executable, str(PROJECT_ROOT / "app" / "main.py")]
        mode = "source"
    else:
        executable = args.exe.resolve()
        if not executable.is_file():
            raise FileNotFoundError(executable)
        command = [str(executable)]
        mode = "package"
    result = run_smoke(command, mode)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
