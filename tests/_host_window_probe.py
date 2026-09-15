# -*- coding: utf-8 -*-
"""Runtime probe for Overlay Win32 styles. Not a product entrypoint."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import ctypes
from ctypes import wintypes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
OUT = PROJECT_ROOT / "tests" / "alpha_live_shots"
OUT.mkdir(parents=True, exist_ok=True)

user32 = ctypes.windll.user32
GWL_STYLE = -16
GWL_EXSTYLE = -20
GW_OWNER = 4
EnumWindows = user32.EnumWindows
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible
IsIconic = user32.IsIconic
GetClassNameW = user32.GetClassNameW
GetWindowRect = user32.GetWindowRect
GetForegroundWindow = user32.GetForegroundWindow
GetWindow = user32.GetWindow
GetParent = user32.GetParent
GetWindowLongW = user32.GetWindowLongW
GetDpiForWindow = getattr(user32, "GetDpiForWindow", None)
MonitorFromWindow = user32.MonitorFromWindow
EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]


EX = {
    "WS_EX_TOPMOST": 0x8,
    "WS_EX_TRANSPARENT": 0x20,
    "WS_EX_TOOLWINDOW": 0x80,
    "WS_EX_APPWINDOW": 0x40000,
    "WS_EX_LAYERED": 0x80000,
    "WS_EX_NOACTIVATE": 0x8000000,
}


def _text(hwnd: int) -> str:
    n = GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _cls(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value


def _rect(hwnd: int) -> list[int]:
    r = RECT()
    GetWindowRect(hwnd, ctypes.byref(r))
    return [r.l, r.t, r.r, r.b, r.r - r.l, r.b - r.t]


def snapshot() -> list[dict]:
    rows: list[dict] = []

    def cb(hwnd, _lp):
        title = _text(hwnd)
        if ("HUD" in title and "异环" in title) or "Overlay Alpha" in title or "异环启动器" in title:
            style = GetWindowLongW(hwnd, GWL_STYLE) & 0xFFFFFFFF
            ex = GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
            owner = GetWindow(hwnd, GW_OWNER)
            parent = GetParent(hwnd)
            fg = GetForegroundWindow()
            rows.append({
                "hwnd": int(hwnd),
                "title": title,
                "cls": _cls(hwnd),
                "visible": bool(IsWindowVisible(hwnd)),
                "iconic": bool(IsIconic(hwnd)),
                "rect": _rect(hwnd),
                "style": hex(style),
                "exStyle": hex(ex),
                "exFlags": {k: bool(ex & v) for k, v in EX.items()},
                "owner": int(owner) if owner else 0,
                "ownerTitle": _text(owner) if owner else "",
                "parent": int(parent) if parent else 0,
                "foreground": int(fg),
                "isForeground": int(hwnd) == int(fg),
                "dpi": int(GetDpiForWindow(hwnd)) if GetDpiForWindow else None,
                "monitor": int(MonitorFromWindow(hwnd, 2)) if MonitorFromWindow else None,
            })
        return True

    EnumWindows(EnumProc(cb), 0)
    return rows


def main() -> int:
    existing = snapshot()
    started = None
    if not any("HUD" in (r.get("title") or "") for r in existing):
        env = os.environ.copy()
        env["NTE_DISABLE_VISION"] = "1"
        env["NTE_DEBUG"] = "1"
        env["NTE_ALLOW_HUD_CAPTURE"] = "1"
        env["NTE_LOG_FILE"] = str(OUT / "host_probe.log")
        started = subprocess.Popen(
            [sys.executable, str(APP_DIR / "main.py"), "--debug"],
            cwd=str(APP_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 25
        while time.time() < deadline:
            existing = snapshot()
            if any("HUD" in (r.get("title") or "") for r in existing):
                break
            time.sleep(0.3)
        time.sleep(1.2)
        existing = snapshot()
    (OUT / "host_runtime.json").write_text(json.dumps({
        "startedPid": started.pid if started else None,
        "windows": existing,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT / "host_runtime.json", "n=", len(existing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
