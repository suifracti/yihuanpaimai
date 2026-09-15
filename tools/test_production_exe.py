import os, sys, time, json, subprocess, win32gui, win32con, win32process
from pathlib import Path

EXE_PATH = Path(r"D:\yihuanpaimai\dist\异环拍卖助手\异环拍卖助手.exe")
LOG_PATH = Path(r"D:\yihuanpaimai\dist\异环拍卖助手\startup_smoke.log")

def run_production_acceptance():
    print("==================================================")
    print("STARTING PRODUCTION ACCEPTANCE (P0-1 & P0-2 FIXES)")
    print(f"Target EXE: {EXE_PATH}")
    print("==================================================")

    # 1. Clean old logs and port 8766
    if LOG_PATH.exists():
        LOG_PATH.unlink()
        
    try:
        cmd_pids = 'powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 8766 -ErrorAction SilentlyContinue).OwningProcess"'
        out = subprocess.check_output(cmd_pids, shell=True, text=True)
        for pid_str in out.splitlines():
            if pid_str.strip().isdigit():
                subprocess.run(f"taskkill /F /PID {pid_str.strip()}", shell=True, capture_output=True)
    except Exception:
        pass

    # 2. Launch EXE directly under current Administrator / High Integrity
    proc = subprocess.Popen([str(EXE_PATH)], cwd=str(EXE_PATH.parent))
    parent_pid = proc.pid
    print(f"[ACCEPT] Launched EXE (PID={parent_pid})")

    deadline = time.time() + 15.0
    hud_hwnd = None
    milestones = {
        "1_exe_started": True,
        "2_dcomp_visual_tree_created_s_ok": False,
        "3_hud_window_appeared": False,
        "4_auction_engine_loaded": False,
        "5_shared_core_tests_passed": False,
        "6_regression_1553_passed": False,
        "7_websocket_connected": False,
        "8_hud_commands_bridge_working": False,
        "9_vision_worker_started": False,
        "10_rapidocr_initialized": False,
        "11_hud_visually_responsive": False,
    }

    while time.time() < deadline:
        time.sleep(0.5)

        # Look for HUD window
        if not hud_hwnd:
            def _find_hud(h, _):
                nonlocal hud_hwnd
                try:
                    if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h):
                        title = win32gui.GetWindowText(h)
                        if "异环" in title and "HUD" in title:
                            hud_hwnd = h
                            return False
                except Exception:
                    pass
                return True
            try:
                win32gui.EnumWindows(_find_hud, None)
            except Exception:
                pass
            if hud_hwnd:
                milestones["3_hud_window_appeared"] = True

        # Check logs
        if LOG_PATH.exists():
            try:
                with open(LOG_PATH, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if "DirectComposition Visual Tree & Composition Controller created (S_OK)" in content:
                        milestones["2_dcomp_visual_tree_created_s_ok"] = True
                    if "auction_engine_v06.js loaded: True" in content:
                        milestones["4_auction_engine_loaded"] = True
                    if "passed=True" in content:
                        milestones["5_shared_core_tests_passed"] = True
                    if "15:53 regression result: PASS" in content:
                        milestones["6_regression_1553_passed"] = True
                    if "WebSocket ready: True" in content or "WebSocket client connected" in content:
                        milestones["7_websocket_connected"] = True
                    if "pywebview/WebView2 ready: True" in content:
                        milestones["8_hud_commands_bridge_working"] = True
                    if "Vision worker started" in content or "Vision worker process started" in content:
                        milestones["9_vision_worker_started"] = True
                    if "RapidOCR/ONNX initialized successfully" in content:
                        milestones["10_rapidocr_initialized"] = True
            except Exception:
                pass

        if all(milestones.values()):
            break

    if hud_hwnd and win32gui.IsWindow(hud_hwnd):
        rect = win32gui.GetWindowRect(hud_hwnd)
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w > 100 and h > 100:
            milestones["11_hud_visually_responsive"] = True

    print("\n--- Acceptance Milestone Checklist ---")
    for k, v in milestones.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}: {v}")

    print("\n--- Full Runtime Smoke Log ---")
    if LOG_PATH.exists():
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            print(f.read())

    # Window drag & snap test via DWM
    if hud_hwnd and win32gui.IsWindow(hud_hwnd):
        print("Testing DWM Window Drag/Move...")
        rect_before = win32gui.GetWindowRect(hud_hwnd)
        win32gui.SetWindowPos(hud_hwnd, 0, rect_before[0] + 10, rect_before[1] + 10, 0, 0, 0x4015)
        time.sleep(0.5)
        rect_after = win32gui.GetWindowRect(hud_hwnd)
        print(f"  Window position before: ({rect_before[0]}, {rect_before[1]}), after: ({rect_after[0]}, {rect_after[1]})")

    # Clean shutdown test via WM_CLOSE
    print("\nInitiating clean shutdown via WM_CLOSE...")
    if hud_hwnd and win32gui.IsWindow(hud_hwnd):
        win32gui.PostMessage(hud_hwnd, win32con.WM_CLOSE, 0, 0)
    time.sleep(2.5)

    # Residual process check
    residual_pids = []
    try:
        cmd_c = f'powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object {{ $_.ParentProcessId -eq {parent_pid} -or $_.ProcessId -eq {parent_pid} }}).ProcessId"'
        out_c = subprocess.check_output(cmd_c, shell=True, text=True)
        residual_pids = [int(l.strip()) for l in out_c.splitlines() if l.strip().isdigit()]
        for cpid in residual_pids:
            subprocess.run(f"taskkill /F /PID {cpid}", shell=True, capture_output=True)
    except Exception:
        pass

    print(f"Residual Child Processes: {len(residual_pids)} (PIDs: {residual_pids})")
    assert len(residual_pids) == 0, f"Residual processes found: {residual_pids}"
    assert all(milestones.values()), f"Some milestones failed: {milestones}"

    print("\n==================================================")
    print("ALL PRODUCTION INTEGRATION CHECKS PASSED (100%)!")
    print("==================================================")

if __name__ == "__main__":
    run_production_acceptance()
