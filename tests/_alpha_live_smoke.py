# -*- coding: utf-8 -*-
"""Live Alpha HUD smoke helper. Not part of the unittest suite."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import ctypes
from ctypes import wintypes

import mss
import numpy as np
import websockets

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
OUT_DIR = PROJECT_ROOT / "tests" / "alpha_live_shots"
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = OUT_DIR / "hud_launch.log"
WS_URL = "ws://127.0.0.1:8766"


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible
GetWindowRect = user32.GetWindowRect
PrintWindow = user32.PrintWindow
GetDC = user32.GetDC
ReleaseDC = user32.ReleaseDC
CreateCompatibleDC = gdi32.CreateCompatibleDC
CreateCompatibleBitmap = gdi32.CreateCompatibleBitmap
SelectObject = gdi32.SelectObject
DeleteObject = gdi32.DeleteObject
DeleteDC = gdi32.DeleteDC
GetDIBits = gdi32.GetDIBits
BitBlt = gdi32.BitBlt
SRCCOPY = 0x00CC0020


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
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
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def window_title(hwnd: int) -> str:
    n = GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def find_hud_windows() -> list[tuple[int, str, tuple[int, int, int, int]]]:
    found: list[tuple[int, str, tuple[int, int, int, int]]] = []

    def cb(hwnd, _lp):
        if not IsWindowVisible(hwnd):
            return True
        title = window_title(hwnd)
        if "异环" in title and "HUD" in title:
            rect = RECT()
            GetWindowRect(hwnd, ctypes.byref(rect))
            found.append((int(hwnd), title, (rect.left, rect.top, rect.right, rect.bottom)))
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    return found


def port_open(host: str = "127.0.0.1", port: int = 8766) -> bool:
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def save_bmp(path: Path, width: int, height: int, pixels: bytes) -> None:
    # pixels are BGRA bottom-up
    row_stride = ((width * 3 + 3) // 4) * 4
    raw = bytearray(row_stride * height)
    for y in range(height):
        src = y * width * 4
        dst = y * row_stride
        for x in range(width):
            b, g, r, _a = pixels[src + x * 4: src + x * 4 + 4]
            raw[dst + x * 3: dst + x * 3 + 3] = bytes((b, g, r))
    file_size = 54 + len(raw)
    header = bytearray(54)
    header[0:2] = b"BM"
    header[2:6] = file_size.to_bytes(4, "little")
    header[10:14] = (54).to_bytes(4, "little")
    header[14:18] = (40).to_bytes(4, "little")
    header[18:22] = width.to_bytes(4, "little", signed=True)
    header[22:26] = height.to_bytes(4, "little", signed=True)
    header[26:28] = (1).to_bytes(2, "little")
    header[28:30] = (24).to_bytes(2, "little")
    header[34:38] = len(raw).to_bytes(4, "little")
    path.write_bytes(bytes(header) + raw)


def capture_hwnd(hwnd: int, path: Path) -> tuple[int, int]:
    rect = RECT()
    GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 1 or height <= 1:
        raise RuntimeError(f"invalid hwnd size {width}x{height}")
    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = CreateCompatibleDC(hwnd_dc)
    bmp = CreateCompatibleBitmap(hwnd_dc, width, height)
    old = SelectObject(mem_dc, bmp)
    ok = PrintWindow(hwnd, mem_dc, 2)
    if not ok:
        ok = PrintWindow(hwnd, mem_dc, 0)
    if not ok:
        BitBlt(mem_dc, 0, 0, width, height, hwnd_dc, 0, 0, SRCCOPY)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(width * height * 4)
    got = GetDIBits(mem_dc, bmp, 0, height, buf, ctypes.byref(bmi), 0)
    SelectObject(mem_dc, old)
    DeleteObject(bmp)
    DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)
    if got == 0:
        raise RuntimeError("GetDIBits failed")
    save_bmp(path, width, height, buf.raw)
    return width, height


def launch_hud() -> subprocess.Popen:
    env = os.environ.copy()
    env["NTE_DISABLE_VISION"] = "1"
    env["NTE_ALLOW_HUD_CAPTURE"] = "1"
    env["NTE_DEBUG"] = "1"
    env["NTE_LOG_FILE"] = str(LOG_PATH)
    env["PYTHONUNBUFFERED"] = "1"
    log_fh = open(LOG_PATH, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(APP_DIR / "main.py"), "--debug"],
        cwd=str(APP_DIR),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    return proc


def wait_ready(timeout: float = 40.0) -> tuple[int, str, tuple[int, int, int, int]]:
    deadline = time.time() + timeout
    last = []
    while time.time() < deadline:
        last = find_hud_windows()
        if last and port_open():
            return last[0]
        time.sleep(0.4)
    raise RuntimeError(f"HUD not ready. windows={last} port={port_open()} log={LOG_PATH.read_text(encoding='utf-8', errors='ignore')[-2000:]}")


async def recv_until(ws, pred, timeout=6.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.2, deadline - time.time()))
        except Exception:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        last = data
        if pred(data):
            return data
    return last


async def send_facts(ws, facts):
    await ws.send(json.dumps({"type": "manual_facts", "action": "manual_facts", "facts": facts}, ensure_ascii=False))
    return await recv_until(ws, lambda d: d.get("type") == "manual_alpha_state" or d.get("manualMode"))


def dump_json(name: str, payload) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_ws_smoke(hwnd, stamp, report):
    async with websockets.connect(WS_URL) as ws:
        boot = await recv_until(ws, lambda d: True, timeout=3)
        report["bootstrap"] = {k: boot.get(k) for k in ("type", "manualMode", "lifecycleStatus", "matchId", "q", "box") } if boot else None

        empty = await send_facts(ws, {})
        await asyncio.sleep(0.4)
        w, h = capture_hwnd(hwnd, OUT_DIR / f"{stamp}_02_empty.bmp")
        report["shots"].append({"file": f"{stamp}_02_empty.bmp", "size": [w, h]})
        dump_json(f"{stamp}_empty.json", empty)

        partial = await send_facts(ws, {"q": 9})
        await asyncio.sleep(0.4)
        w, h = capture_hwnd(hwnd, OUT_DIR / f"{stamp}_03_partial_q.bmp")
        report["shots"].append({"file": f"{stamp}_03_partial_q.bmp", "size": [w, h]})
        dump_json(f"{stamp}_partial.json", partial)

        full = await send_facts(ws, {
            "box": "琉璃宝箱 · 宝石类概率提升",
            "fieldCondition": "standard",
            "q": 9,
            "goldAvg": 33538,
            "purpleCount": 5,
            "knownGold": "4546/48648+185165",
            "knownRed": "454654*2",
            "knownPurple": "454654+489498",
        })
        await asyncio.sleep(0.5)
        w, h = capture_hwnd(hwnd, OUT_DIR / f"{stamp}_04_full.bmp")
        report["shots"].append({"file": f"{stamp}_04_full.bmp", "size": [w, h]})
        dump_json(f"{stamp}_full.json", full)

        await ws.send(json.dumps({"type": "manual_next_match", "action": "manual_next_match"}))
        next_state = await recv_until(ws, lambda d: d.get("type") == "manual_alpha_state" or d.get("manualMode"))
        await asyncio.sleep(0.4)
        w, h = capture_hwnd(hwnd, OUT_DIR / f"{stamp}_05_next.bmp")
        report["shots"].append({"file": f"{stamp}_05_next.bmp", "size": [w, h]})
        dump_json(f"{stamp}_next.json", next_state)
        return empty, partial, full, next_state


def main() -> int:
    stamp = datetime.now().strftime("%H%M%S")
    report = {"stamp": stamp, "visionDisabled": True, "shots": [], "steps": []}
    existing = find_hud_windows()
    started = None
    if existing:
        hwnd, title, box = existing[0]
        report["steps"].append({"note": "reused existing HUD", "title": title, "box": box})
    else:
        started = launch_hud()
        hwnd, title, box = wait_ready()
        report["steps"].append({"note": "launched HUD", "pid": started.pid, "title": title, "box": box})

    w, h = capture_hwnd(hwnd, OUT_DIR / f"{stamp}_01_startup.bmp")
    report["shots"].append({"file": f"{stamp}_01_startup.bmp", "size": [w, h], "window": box, "title": title})
    report["window"] = {"title": title, "rect": box, "w": box[2] - box[0], "h": box[3] - box[1], "capture": [w, h]}

    empty, partial, full, next_state = asyncio.run(run_ws_smoke(hwnd, stamp, report))

    report["full"] = {
        "matchId": (full or {}).get("matchId"),
        "lifecycleStatus": (full or {}).get("lifecycleStatus"),
        "box": (full or {}).get("box"),
        "fieldCondition": (full or {}).get("fieldCondition"),
        "q": (full or {}).get("q"),
        "goldAvg": (full or {}).get("goldAvg"),
        "purpleCount": (full or {}).get("purpleCount"),
        "knownGold": (full or {}).get("knownGold"),
        "knownRed": (full or {}).get("knownRed"),
        "knownPurple": (full or {}).get("knownPurple"),
        "draftSaved": (full or {}).get("draftSaved"),
    }
    report["next"] = {
        "matchId": (next_state or {}).get("matchId"),
        "box": (next_state or {}).get("box"),
        "fieldCondition": (next_state or {}).get("fieldCondition"),
        "q": (next_state or {}).get("q"),
        "knownGold": (next_state or {}).get("knownGold"),
        "knownRed": (next_state or {}).get("knownRed"),
        "lifecycleStatus": (next_state or {}).get("lifecycleStatus"),
    }
    dump_json(f"{stamp}_report.json", report)
    print(json.dumps({"stamp": stamp, "ok": True, "w": report.get("window", {}).get("w"), "h": report.get("window", {}).get("h"), "matchFull": (report.get("full") or {}).get("matchId"), "matchNext": (report.get("next") or {}).get("matchId")}, ensure_ascii=True))
    if started is not None:
        report["leftRunning"] = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
