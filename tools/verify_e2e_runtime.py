import os, sys, time, json, subprocess, pefile, win32gui, win32con, win32process
from pathlib import Path

PROJECT_ROOT = Path(r"D:\yihuanpaimai")
EXE_PATH = PROJECT_ROOT / "dist" / "异环拍卖助手" / "异环拍卖助手.exe"
LOG_PATH = PROJECT_ROOT / "dist" / "异环拍卖助手" / "startup_smoke.log"

def verify_manifest():
    print("\n--- 1. MANIFEST & ASINVOKER AUDIT ---")
    pe = pefile.PE(str(EXE_PATH))
    manifest_xml = ""
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.id == pefile.RESOURCE_TYPE['RT_MANIFEST']:
            for sub_entry in entry.directory.entries:
                for sub_sub_entry in sub_entry.directory.entries:
                    data = pe.get_data(sub_sub_entry.data.struct.OffsetToData, sub_sub_entry.data.struct.Size)
                    manifest_xml = data.decode('utf-8', errors='ignore')
                    
    is_as_invoker = 'requestedExecutionLevel level="asInvoker"' in manifest_xml
    print(f"Manifest found: {bool(manifest_xml)}")
    print(f"requestedExecutionLevel level=\"asInvoker\": {is_as_invoker}")
    assert is_as_invoker, "Manifest does not contain asInvoker!"
    print(">>> Manifest Check PASSED.")

def verify_admin_rejection():
    print("\n--- 2. ADMIN / HIGH INTEGRITY GUARD AUDIT ---")
    if LOG_PATH.exists():
        LOG_PATH.unlink()
        
    p = subprocess.Popen([str(EXE_PATH)], cwd=str(EXE_PATH.parent))
    time.sleep(2.0)
    
    lines = []
    if LOG_PATH.exists():
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f if l.strip()]
            
    p.kill()
    
    print("Admin launch logs:")
    for l in lines:
        print("  " + l)
        
    refused = any("REFUSED: Process is running with Administrator" in l for l in lines)
    print(f"Admin elevated process correctly detected & refused: {refused}")
    assert refused, "Admin guard failed to reject elevated execution!"
    print(">>> Admin Guard Check PASSED.")

def verify_standard_user_full_flow():
    print("\n--- 3. STANDARD USER (MEDIUM INTEGRITY) FULL FLOW RUN ---")
    if LOG_PATH.exists():
        LOG_PATH.unlink()
        
    # Clean up old port 8766 users if any
    try:
        cmd_pids = 'powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort 8766 -ErrorAction SilentlyContinue).OwningProcess"'
        out = subprocess.check_output(cmd_pids, shell=True, text=True)
        for pid_str in out.splitlines():
            if pid_str.strip().isdigit():
                subprocess.run(f"taskkill /F /PID {pid_str.strip()}", shell=True, capture_output=True)
    except Exception:
        pass

    # Launch under standard trust level
    cmd = f'runas /trustlevel:0x20000 "{str(EXE_PATH)}"'
    print(f"Launching command: {cmd}")
    subprocess.Popen(cmd, shell=True)
    
    deadline = time.time() + 15.0
    hud_hwnd = None
    milestones = {
        "process_started": False,
        "websocket_ready": False,
        "hud_window_appeared": False,
        "pywebview_ready": False,
        "auction_engine_loaded": False,
        "shared_core_tests_passed": False,
        "regression_1553_passed": False,
        "vision_worker_started": False,
        "rapidocr_initialized": False,
        "hud_responsive": False,
    }
    
    parent_pid = None

    while time.time() < deadline:
        time.sleep(0.5)
        
        # Check window
        if not hud_hwnd:
            def _find_hud(h, _):
                nonlocal hud_hwnd, parent_pid
                try:
                    if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h):
                        title = win32gui.GetWindowText(h)
                        if "异环" in title and "HUD" in title:
                            hud_hwnd = h
                            _, p = win32process.GetWindowThreadProcessId(h)
                            parent_pid = p
                            return False
                except Exception:
                    pass
                return True
            try:
                win32gui.EnumWindows(_find_hud, None)
            except Exception:
                pass
            if hud_hwnd:
                milestones["hud_window_appeared"] = True
                
        # Check log lines
        if LOG_PATH.exists():
            try:
                with open(LOG_PATH, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if "process started" in content:
                        milestones["process_started"] = True
                    if "WebSocket bus ready" in content or "WebSocket ready: True" in content:
                        milestones["websocket_ready"] = True
                    if "pywebview/WebView2 ready: True" in content:
                        milestones["pywebview_ready"] = True
                    if "auction_engine_v06.js loaded: True" in content:
                        milestones["auction_engine_loaded"] = True
                    if "passed=True" in content or "passed=true" in content or "passed= True" in content:
                        milestones["shared_core_tests_passed"] = True
                    if "15:53 regression result: PASS" in content:
                        milestones["regression_1553_passed"] = True
                    if "Vision worker started" in content or "Vision worker process started" in content:
                        milestones["vision_worker_started"] = True
                    if "RapidOCR/ONNX initialized successfully" in content:
                        milestones["rapidocr_initialized"] = True
            except Exception:
                pass
                
        if all(milestones.values()):
            break

    if hud_hwnd and win32gui.IsWindow(hud_hwnd):
        rect = win32gui.GetWindowRect(hud_hwnd)
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w > 100 and h > 100:
            milestones["hud_responsive"] = True

    print("\nMilestone Results:")
    for k, v in milestones.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}: {v}")

    # Read all logs
    print("\nFull Execution Log:")
    if LOG_PATH.exists():
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            print(f.read())

    # Clean shutdown via WM_CLOSE
    print("Initiating clean shutdown...")
    if hud_hwnd and win32gui.IsWindow(hud_hwnd):
        win32gui.PostMessage(hud_hwnd, win32con.WM_CLOSE, 0, 0)
    time.sleep(2.0)

    # Check residuals
    residual_pids = []
    if parent_pid:
        try:
            cmd_c = f'powershell -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object {{ $_.ParentProcessId -eq {parent_pid} -or $_.ProcessId -eq {parent_pid} }}).ProcessId"'
            out_c = subprocess.check_output(cmd_c, shell=True, text=True)
            residual_pids = [int(l.strip()) for l in out_c.splitlines() if l.strip().isdigit()]
            for cpid in residual_pids:
                subprocess.run(f"taskkill /F /PID {cpid}", shell=True, capture_output=True)
        except Exception:
            pass

    print(f"Residual processes: {len(residual_pids)} (PIDs: {residual_pids})")
    assert len(residual_pids) == 0, f"Residual processes detected: {residual_pids}"
    assert all(milestones.values()), f"Some milestones failed: {milestones}"
    print(">>> Standard User Full Flow PASSED.")

if __name__ == "__main__":
    verify_manifest()
    verify_admin_rejection()
    verify_standard_user_full_flow()
    print("\n" + "="*50)
    print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY (100% PASS)!")
    print("="*50)
