#!/usr/bin/env python3
"""Run one read-only capture against the project-controlled Win32 window.

The probe never sends keyboard or mouse input to a game.  It starts the local
test window, captures its client pixels through WindowCaptureManager, and
stores one PNG plus a machine-readable result under build/goal-luna.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HARNESS = (
    REPO_ROOT
    / "build"
    / "goal-luna"
    / "native-bridge"
    / "harness"
    / "Release"
    / "net8.0"
    / "WindowMonitorHarness.exe"
)
DEFAULT_OUTPUT = REPO_ROOT / "build" / "goal-luna" / "native-bridge" / "readonly-capture"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", type=Path, default=DEFAULT_HARNESS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = out_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(REPO_ROOT))
    from core.window_capture import WindowCaptureManager  # noqa: E402

    env = os.environ.copy()
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    env["YIHUAN_DATA_ROOT"] = str(out_dir / "data")
    env["YIHUAN_CAPTURE_ROOT"] = str(out_dir / "captures")

    harness_path = args.harness.resolve()
    command = ([str(harness_path)] if harness_path.suffix.lower() == ".exe" else [
        shutil.which("dotnet.exe") or shutil.which("dotnet") or "dotnet.exe",
        str(harness_path),
    ]) + [
        "--mode",
        "serve",
        "--count",
        "2",
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--grab-foreground",
    ]
    process = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    ready: dict = {}
    harness_error = ""
    try:
        first_line = process.stdout.readline() if process.stdout else ""
        if first_line:
            try:
                ready = json.loads(first_line)
            except json.JSONDecodeError as exc:
                harness_error = f"invalid ready JSON: {exc}"
        else:
            harness_error = "controlled window exited before ready"

        windows = ready.get("windows") if isinstance(ready, dict) else None
        handles = [int(value) for value in windows.values()] if isinstance(windows, dict) else []
        hwnd = handles[0] if handles else 0
        unfocused_hwnd = handles[1] if len(handles) > 1 else 0
        time.sleep(0.25)

        image = None
        capture_method = "none"
        diagnosis = {"safe": False, "reason": "capture_not_attempted"}
        pixel_sha256 = None
        image_path = out_dir / "controlled-window-capture.png"
        manager = WindowCaptureManager(game_title_keywords=["nte-controlled"])
        import numpy as np

        safety_cases = {
            "empty": manager.diagnose_frame_safety(None),
            "resolutionTooSmall": manager.diagnose_frame_safety(np.zeros((120, 200, 3), dtype=np.uint8)),
            "blackScreen": manager.diagnose_frame_safety(np.zeros((720, 1280, 3), dtype=np.uint8)),
            "lowContrast": manager.diagnose_frame_safety(np.full((720, 1280, 3), 100, dtype=np.uint8)),
            "invalidHandle": {
                "captureMethod": manager.capture_game_client(0, None)[1],
                "safe": False,
            },
        }
        unfocused_capture = None
        if hwnd:
            try:
                import mss

                with (getattr(mss, "MSS", mss.mss))() as screen:
                    image, capture_method = manager.capture_game_client(hwnd, screen)
            except Exception:
                image, capture_method = manager.capture_game_client(hwnd, None)
            diagnosis = manager.diagnose_frame_safety(image)
            if unfocused_hwnd:
                unfocused_capture = manager.capture_foreground_client(unfocused_hwnd)

        if image is not None:
            import cv2

            if not cv2.imwrite(str(image_path), image):
                harness_error = harness_error or "cv2.imwrite returned false"
            pixel_sha256 = hashlib.sha256(image.tobytes()).hexdigest()

        result = {
            "ok": not bool(harness_error)
            and hwnd != 0
            and image is not None
            and capture_method in {"printwindow", "mss"}
            and bool(diagnosis.get("safe")),
            "scope": "controlled_window_read_only",
            "realGame": False,
            "automaticInputActions": 0,
            "harnessReady": bool(ready),
            "harnessPid": process.pid,
            "hwnd": hwnd,
            "unfocusedHwnd": unfocused_hwnd,
            "foregroundGateConfirmed": bool((ready.get("grabForeground") or {}).get("tookEffect")),
            "unfocusedCaptureRejected": unfocused_hwnd != 0 and unfocused_capture is None,
            "requestedSize": {"width": args.width, "height": args.height},
            "captureMethod": capture_method,
            "capturedShape": list(image.shape) if image is not None else None,
            "pixelSha256": pixel_sha256,
            "capturePath": str(image_path) if image is not None else None,
            "diagnosis": diagnosis,
            "failureDiagnostics": safety_cases,
            "error": harness_error or None,
        }
        (out_dir / "capture-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return 0 if result["ok"] else 1
    finally:
        if process.poll() is None and process.stdin:
            try:
                process.stdin.write("exit\n")
                process.stdin.flush()
            except BrokenPipeError:
                pass
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
        stdout = stdout or ""
        stderr = stderr or ""
        (out_dir / "harness-stdout-tail.log").write_text(stdout[-12000:], encoding="utf-8")
        (out_dir / "harness-stderr.log").write_text(stderr[-12000:], encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
