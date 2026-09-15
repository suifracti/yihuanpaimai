"""Strict Unicode smoke test for the native Main and Overlay windows.

This is intentionally an executable smoke helper rather than an auto-collected
unit test: it starts the real source app or packaged executable and exercises
the Win32 window boundary.  Every ctypes call declares its Unicode signature so
Python never falls back to implicit C ``int`` argument conversion for HWNDs.
"""

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
WM_CLOSE = 0x0010


class UnicodeWindowProbe:
    """Small, explicitly typed wrapper around the required Win32 W APIs."""

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.enum_proc_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        self.user32.EnumWindows.argtypes = [self.enum_proc_type, wintypes.LPARAM]
        self.user32.EnumWindows.restype = wintypes.BOOL
        self.user32.EnumChildWindows.argtypes = [
            wintypes.HWND,
            self.enum_proc_type,
            wintypes.LPARAM,
        ]
        self.user32.EnumChildWindows.restype = wintypes.BOOL
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
        self.user32.GetClassNameW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self.user32.GetClassNameW.restype = ctypes.c_int
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.PostMessageW.restype = wintypes.BOOL

    def text(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(max(length + 1, 1))
        self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def class_name(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value

    def top_windows(self, pid: int, visible_only: bool = False) -> list[dict]:
        windows: list[dict] = []

        @self.enum_proc_type
        def callback(hwnd, _lparam):
            owner_pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            visible = bool(self.user32.IsWindowVisible(hwnd))
            if owner_pid.value == pid and (visible or not visible_only):
                windows.append(
                    {
                        "hwnd": int(hwnd),
                        "title": self.text(hwnd),
                        "visible": visible,
                    }
                )
            return True

        self.user32.EnumWindows(callback, 0)
        return windows

    def children(self, parent: int) -> list[dict]:
        children: list[dict] = []

        @self.enum_proc_type
        def callback(hwnd, _lparam):
            children.append(
                {
                    "hwnd": int(hwnd),
                    "title": self.text(hwnd),
                    "class": self.class_name(hwnd),
                }
            )
            return True

        self.user32.EnumChildWindows(parent, callback, 0)
        return children

    def close(self, hwnd: int) -> None:
        self.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

def wait_until(predicate, description: str, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {description}")


def run_smoke(command: list[str], mode: str) -> dict:
    probe = UnicodeWindowProbe()
    environment = os.environ.copy()
    environment["NTE_DISABLE_VISION"] = "1"
    environment["NTE_DISABLE_ICON"] = "1"
    environment["NTE_MAIN_UI_SMOKE"] = "1"

    with tempfile.TemporaryDirectory(prefix="nte-title-smoke-") as temp_dir:
        log_path = Path(temp_dir) / "runtime.log"
        environment["NTE_LOG_FILE"] = str(log_path)
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        main_hwnd = None
        try:
            def find_expected_windows():
                rows = probe.top_windows(process.pid, visible_only=True)
                by_title = {row["title"]: row for row in rows}
                if MAIN_TITLE in by_title and OVERLAY_TITLE in by_title:
                    return by_title
                if process.poll() is not None:
                    raise AssertionError(
                        f"app exited before windows appeared: exit={process.returncode}, "
                        f"windows={json.dumps(rows, ensure_ascii=True)}"
                    )
                return None

            windows = wait_until(find_expected_windows, "Unicode Main and Overlay titles")
            main_hwnd = windows[MAIN_TITLE]["hwnd"]
            overlay_hwnd = windows[OVERLAY_TITLE]["hwnd"]
            children = probe.children(main_hwnd)
            assert any(
                child["class"].startswith("Chrome_WidgetWin") for child in children
            ), children

            def runtime_ready():
                if not log_path.exists():
                    return False
                log = log_path.read_text(encoding="utf-8", errors="strict")
                return (
                    "Main presentation page ready" in log
                    and "auction_engine_v06.js loaded: True" in log
                    and "15:53 regression result: PASS" in log
                )

            wait_until(runtime_ready, "Main presentation and Overlay Solver readiness")

            def dashboard_bridge_roundtrip():
                log = log_path.read_text(encoding="utf-8", errors="strict")
                return (
                    "Main bridge action=toggle_overlay overlayVisible=False" in log
                    and "Main bridge action=toggle_overlay overlayVisible=True" in log
                )

            wait_until(dashboard_bridge_roundtrip, "Dashboard bridge hide/show roundtrip")
            assert probe.user32.IsWindowVisible(overlay_hwnd)
            assert probe.text(overlay_hwnd) == OVERLAY_TITLE

            probe.close(main_hwnd)
            process.wait(timeout=20)
            assert process.returncode == 0, process.returncode
            return {
                "mode": mode,
                "mainTitle": MAIN_TITLE,
                "overlayTitle": OVERLAY_TITLE,
                "mainPresentation": "PASS",
                "dashboardOverlayBridge": "PASS",
                "sameOverlayHwnd": overlay_hwnd,
                "solverStartup": "PASS",
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
