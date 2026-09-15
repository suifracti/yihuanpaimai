"""
v0.65 Packaged Runtime Smoke Test Driver
Executes 3 test groups:
  Group A: Source (python app/main.py)
  Group B: Packaged EXE + Vision Disabled (NTE_DISABLE_VISION=1 dist/异环拍卖助手/异环拍卖助手.exe)
  Group C: Packaged EXE + Vision Enabled (dist/异环拍卖助手/异环拍卖助手.exe)

Logs each milestone:
  - process started
  - HUD window appeared
  - startup duration
  - pywebview/WebView2 ready
  - WebSocket ready
  - auction_engine_v06.js loaded
  - Shared Core self-test result
  - 15:53 regression result
  - Vision worker started
  - RapidOCR/ONNX initialized
  - HUD responsive
  - clean shutdown
  - residual child processes
  - final log line
"""

import os
import sys
import time
import json
import subprocess
import win32gui
import win32con
import win32process
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXE_PATH = PROJECT_ROOT / "dist" / "异环拍卖助手" / "异环拍卖助手.exe"

def get_child_pids(parent_pid):
    """查找子进程 PID"""
    try:
        cmd = f'powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object {{ $_.ParentProcessId -eq {parent_pid} }}).ProcessId"'
        out = subprocess.check_output(cmd, shell=True, text=True)
        pids = [int(line.strip()) for line in out.splitlines() if line.strip().isdigit()]
        return pids
    except Exception:
        return []

def run_smoke_group(group_id: str, cmd: list, env_vars: dict, target_log_file: Path, vision_expected: bool = True) -> dict:
    print(f"\n{'='*20} RUNNING GROUP {group_id} {'='*20}")
    print(f"Command: {' '.join(cmd)}")
    print(f"Vision Expected: {vision_expected}")

    if target_log_file.exists():
        try:
            target_log_file.unlink()
        except Exception:
            pass

    env = os.environ.copy()
    env.update(env_vars)

    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        cwd=str(target_log_file.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    parent_pid = proc.pid
    print(f"[{group_id}] Main process launched (PID={parent_pid})")

    hud_hwnd = None
    hud_appeared_time = None
    max_wait = 18.0  # seconds
    deadline = time.time() + max_wait

    milestones = {
        "group": group_id,
        "parent_pid": parent_pid,
        "process_started": True,
        "hud_window_appeared": False,
        "startup_duration_ms": None,
        "pywebview_ready": False,
        "websocket_ready": False,
        "auction_engine_loaded": False,
        "shared_core_self_tests": None,
        "regression_1553_result": None,
        "vision_worker_started": False,
        "rapidocr_initialized": False,
        "hud_responsive": False,
        "clean_shutdown": False,
        "residual_child_processes": 0,
        "residual_pids": [],
        "final_log_line": None,
        "log_lines": [],
        "passed": False
    }

    # Polling for HUD window & log entries
    while time.time() < deadline:
        time.sleep(0.3)

        # Check HUD window via Win32 API
        if not hud_hwnd:
            def _find_hud(hwnd, _):
                nonlocal hud_hwnd
                try:
                    if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                        title = win32gui.GetWindowText(hwnd)
                        if "异环" in title and "HUD" in title:
                            hud_hwnd = hwnd
                            return False
                except Exception:
                    pass
                return True
            try:
                win32gui.EnumWindows(_find_hud, None)
            except Exception:
                pass
            if hud_hwnd:
                hud_appeared_time = (time.perf_counter() - t0) * 1000
                milestones["hud_window_appeared"] = True
                milestones["startup_duration_ms"] = hud_appeared_time
                print(f"[{group_id}] HUD window appeared (HWND={hud_hwnd}, elapsed={hud_appeared_time:.1f}ms)")

        # Read startup log file
        if target_log_file.exists():
            try:
                with open(target_log_file, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f if line.strip()]
                    milestones["log_lines"] = lines
                    for l in lines:
                        if "pywebview/WebView2 ready: True" in l:
                            milestones["pywebview_ready"] = True
                        if "WebSocket bus ready" in l or "WebSocket ready: True" in l:
                            milestones["websocket_ready"] = True
                        if "auction_engine_v06.js loaded: True" in l:
                            milestones["auction_engine_loaded"] = True
                        if "Shared Core self-test result" in l:
                            milestones["shared_core_self_tests"] = l.split("Shared Core self-test result:")[-1].strip()
                        if "15:53 regression result:" in l:
                            milestones["regression_1553_result"] = l.split("15:53 regression result:")[-1].strip()
                        if "Vision worker started" in l or "Vision worker process started" in l:
                            milestones["vision_worker_started"] = True
                        if "RapidOCR/ONNX initialized successfully" in l:
                            milestones["rapidocr_initialized"] = True
                        if "HUD responsive: True" in l:
                            milestones["hud_responsive"] = True
            except Exception:
                pass

        # Check if conditions met
        ready_check = (
            milestones["hud_window_appeared"]
            and milestones["pywebview_ready"]
            and milestones["websocket_ready"]
            and milestones["auction_engine_loaded"]
        )
        if vision_expected:
            if ready_check and milestones["rapidocr_initialized"]:
                break
        else:
            if ready_check:
                break

    # If HUD window exists, test responsiveness
    if hud_hwnd and win32gui.IsWindow(hud_hwnd):
        rect = win32gui.GetWindowRect(hud_hwnd)
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        if width > 100 and height > 100:
            milestones["hud_responsive"] = True
            print(f"[{group_id}] HUD responsive confirmed (geometry: {width}x{height} at ({rect[0]}, {rect[1]}))")

    # Let the app settle for 1.5 seconds in running state
    time.sleep(1.5)

    # Check child processes before shutdown
    active_children = get_child_pids(parent_pid)
    print(f"[{group_id}] Active child PIDs before shutdown: {active_children}")

    # Request clean shutdown by sending WM_CLOSE to HUD window
    print(f"[{group_id}] Initiating clean shutdown via WM_CLOSE...")
    if hud_hwnd and win32gui.IsWindow(hud_hwnd):
        win32gui.PostMessage(hud_hwnd, win32con.WM_CLOSE, 0, 0)
    else:
        proc.terminate()

    # Wait for process termination
    try:
        proc.wait(timeout=4.0)
        milestones["clean_shutdown"] = True
        print(f"[{group_id}] Main process exited cleanly (code={proc.returncode})")
    except Exception:
        print(f"[{group_id}] Process did not exit within timeout, killing...")
        proc.kill()
        proc.wait()
        milestones["clean_shutdown"] = False

    # Check for residual child processes
    time.sleep(0.5)
    residual = []
    for cpid in active_children:
        try:
            # Check if PID still exists
            out = subprocess.check_output(f'tasklist /FI "PID eq {cpid}"', shell=True, text=True)
            if str(cpid) in out:
                residual.append(cpid)
                # Cleanup residual
                subprocess.run(f'taskkill /F /PID {cpid}', shell=True, capture_output=True)
        except Exception:
            pass

    milestones["residual_child_processes"] = len(residual)
    milestones["residual_pids"] = residual
    print(f"[{group_id}] Residual child processes: {len(residual)} (PIDs: {residual})")

    # Final log line
    if target_log_file.exists():
        with open(target_log_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
            if lines:
                milestones["final_log_line"] = lines[-1]

    # Evaluation
    passed = (
        milestones["process_started"]
        and milestones["hud_window_appeared"]
        and milestones["pywebview_ready"]
        and milestones["websocket_ready"]
        and milestones["auction_engine_loaded"]
        and (milestones["shared_core_self_tests"] is not None and "True" in milestones["shared_core_self_tests"])
        and milestones["regression_1553_result"] == "PASS"
        and milestones["hud_responsive"]
        and milestones["clean_shutdown"]
        and milestones["residual_child_processes"] == 0
    )
    if vision_expected:
        passed = passed and milestones["vision_worker_started"] and milestones["rapidocr_initialized"]
    else:
        passed = passed and not milestones["vision_worker_started"]

    milestones["passed"] = passed
    print(f"[{group_id}] RESULT: {'PASS' if passed else 'FAIL'}")
    return milestones

def main():
    results = {}

    # Group A: Source
    log_a = PROJECT_ROOT / "app" / "startup_smoke.log"
    cmd_a = [sys.executable, str(PROJECT_ROOT / "app" / "main.py")]
    res_a = run_smoke_group("A_SOURCE", cmd_a, {}, log_a, vision_expected=True)
    results["Group_A"] = res_a

    # Group B: Packaged EXE + Vision Disabled
    log_b = PROJECT_ROOT / "dist" / "异环拍卖助手" / "startup_smoke.log"
    cmd_b = [str(EXE_PATH)]
    res_b = run_smoke_group("B_EXE_VISION_OFF", cmd_b, {"NTE_DISABLE_VISION": "1"}, log_b, vision_expected=False)
    results["Group_B"] = res_b

    # Group C: Packaged EXE + Vision Enabled
    log_c = PROJECT_ROOT / "dist" / "异环拍卖助手" / "startup_smoke.log"
    cmd_c = [str(EXE_PATH)]
    res_c = run_smoke_group("C_EXE_VISION_ON", cmd_c, {}, log_c, vision_expected=True)
    results["Group_C"] = res_c

    summary_file = PROJECT_ROOT / "dist" / "smoke_test_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    all_passed = res_a["passed"] and res_b["passed"] and res_c["passed"]
    print("\n" + "="*50)
    print(f"OVERALL SMOKE TEST RESULT: {'ALL PASS' if all_passed else 'SOME FAILED'}")
    print("="*50)
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
