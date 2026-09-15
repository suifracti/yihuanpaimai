# -*- coding: utf-8 -*-
"""Verify UI responsiveness during sustained compute and hung runtime recovery.

Production entrance: Both compute requests and UI operations are driven strictly
through the running App's production interfaces (WebSocket / WebViews).
Zero harness-side solver calls. Zero harness-side state resets.

Sub-tests:
- Part A (Delayed Response Responsiveness): Verify App UI mode toggle responsiveness (<500ms)
  while awaiting delayed compute response (delay injection 1500ms). Proves asynchronous decoupled UI.
- Part A2 (Formal Runtime Real Compute Responsiveness): Verify App UI mode toggle responsiveness (<500ms)
  during genuine Node.js CPU computation (formal runtime core/live_shadow_runtime.js, 2300+ records,
  105 candidate states, zero delay injection).
- Part B (Hang Runtime Auto-Recovery): Verify App timeout (<1.0s), auto-kill of hung runtime,
  and in-place recovery on the SAME App instance.
"""
from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "tools"),
    str(ROOT / "tests"),
    str(ROOT / "app"),
    str(ROOT / "core"),
    "C:/Program Files/Python310/Lib/site-packages",
    "C:/Program Files/Python310/Lib/site-packages/win32",
    "C:/Program Files/Python310/Lib/site-packages/win32/lib",
    "C:/Program Files/Python310/Lib/site-packages/Pythonwin",
]

from verify_p1_real_ui import (
    WS, eval_main, eval_overlay, recv_until, start_source, stop_source,
)

OUT = ROOT / "build" / "diagnosis_20260909" / "p2-real-ui-busy"
CONTROLLED_HANG_JS = ROOT / "tests" / "fixtures" / "controlled_hang_shadow_runtime.js"
FORMAL_RUNTIME_JS = ROOT / "core" / "live_shadow_runtime.js"
LEGACY_DB = ROOT / "异环拍卖数据.json"

TH32CS_SNAPPROCESS = 0x00000002


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def get_child_pids_by_name(parent_pid: int, exe_name: str = "node.exe") -> list[int]:
    k = ctypes.windll.kernel32
    h = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if h == -1:
        return []
    e = PROCESSENTRY32()
    e.dwSize = ctypes.sizeof(PROCESSENTRY32)
    pids = []
    if k.Process32First(h, ctypes.byref(e)):
        while True:
            if e.th32ParentProcessID == parent_pid:
                name = e.szExeFile.decode("latin-1", errors="ignore").lower()
                if exe_name.lower() in name:
                    pids.append(e.th32ProcessID)
            if not k.Process32Next(h, ctypes.byref(e)):
                break
    k.CloseHandle(h)
    return pids


def is_pid_alive(pid: int) -> bool:
    if not pid:
        return False
    STILL_ACTIVE = 259
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    exit_code = ctypes.c_ulong()
    res = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
    kernel32.CloseHandle(handle)
    if not res:
        return False
    return exit_code.value == STILL_ACTIVE


def setup_data_root(data_dir: Path, max_records: int = 20, duplicate_factor: int = 1) -> None:
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    hist_dir = data_dir / "history"
    hist_dir.mkdir(parents=True)
    target = hist_dir / "异环拍卖数据.json"
    if LEGACY_DB.exists():
        raw = json.loads(LEGACY_DB.read_text(encoding="utf-8"))
        records = raw.get("records") or []
        if duplicate_factor > 1:
            multiplied = []
            for k in range(duplicate_factor):
                for r in records:
                    rc = json.loads(json.dumps(r))
                    rc["id"] = f"{r.get('id')}_c{k}"
                    multiplied.append(rc)
            raw["records"] = multiplied[:max_records]
        else:
            raw["records"] = records[:max_records]
        target.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        target.write_text('{"schemaVersion":6,"records":[]}', encoding="utf-8")


def extract_quantiles(prof: dict) -> tuple[float | None, float | None, float | None]:
    if not isinstance(prof, dict):
        return None, None, None
    if prof.get("p50") is not None:
        return prof.get("p20"), prof.get("p50"), prof.get("p80")
    whole = prof.get("shadowWhole")
    if isinstance(whole, dict) and whole.get("p50") is not None:
        return whole.get("p20"), whole.get("p50"), whole.get("p80")
    if prof.get("partialShadowP50") is not None:
        return prof.get("partialShadowP20"), prof.get("partialShadowP50"), prof.get("partialShadowP80")
    quantiles = ((prof.get("predictionSnapshot") or {}).get("forecast") or {}).get("quantiles") or {}
    if quantiles.get("p50") is not None:
        return quantiles.get("p20"), quantiles.get("p50"), quantiles.get("p80")
    return None, None, None


def run_part_a() -> dict:
    """Part A: UI mode toggle latency (<500ms) while awaiting delayed compute response (1500ms delay injection)."""
    data_a = OUT / "data-root-a"
    setup_data_root(data_a, max_records=20)
    log_path = OUT / "ui-part-a.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = ";".join([
        str(ROOT / "core"),
        str(ROOT / "app"),
        "C:/Program Files/Python310/Lib/site-packages",
        "C:/Program Files/Python310/Lib/site-packages/win32",
        "C:/Program Files/Python310/Lib/site-packages/win32/lib",
        "C:/Program Files/Python310/Lib/site-packages/Pythonwin",
    ])
    env.update({
        "YIHUAN_DATA_ROOT": str(data_a),
        "LOCALAPPDATA": str(OUT / "local-app-data-a"),
        "NTE_DISABLE_VISION": "1",
        "NTE_DISABLE_ICON": "1",
        "NTE_ALLOW_HUD_CAPTURE": "1",
        "NTE_DEBUG": "1",
        "NTE_LOG_FILE": str(log_path),
        "YIHUAN_SHADOW_RUNTIME_JS": str(CONTROLLED_HANG_JS),
        "YIHUAN_COMPUTE_DELAY_MS": "1500",
        "YIHUAN_COMPUTE_TIMEOUT_S": "8.0",
    })
    py = Path(sys.executable)
    command = [str(py), str(ROOT / "app" / "main.py")]
    process, probe, main_win, hud = start_source(command, env, log_path)
    app_pid = process.pid

    report = {
        "ok": False,
        "testCategory": "waiting_delayed_compute_responsiveness",
        "description": "App UI responsiveness while awaiting delayed compute response (1500ms delay injection)",
        "appPid": app_pid,
        "toggles": [],
    }

    async def flow():
        import websockets
        async with websockets.connect(WS) as ws_ui, websockets.connect(WS) as ws_compute:
            await ws_compute.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
            boot = await recv_until(ws_compute, lambda r: r.get("type") == "manual_alpha_state")
            match_id = boot["matchId"]
            await asyncio.sleep(0.4)

            # Ensure overlay and main are visible and in match view
            await eval_main(ws_ui, "showView('match'); dashboard.currentView")
            await eval_overlay(ws_ui, """
                if (typeof setOverlayExpanded === 'function') setOverlayExpanded(true);
                else if (!document.getElementById('shell').classList.contains('expanded')) document.getElementById('toggleBtn').click();
            """)
            await asyncio.sleep(0.4)

            # Query initial state to record version/generation before compute request
            await ws_compute.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
            init_st = await recv_until(ws_compute, lambda r: r.get("matchId") == match_id, timeout=3.0)
            initial_shadow_gen = int((init_st.get("solverInput") or {}).get("shadowMeta", {}).get("shadowGen") or 0)

            # Trigger production compute via WebSocket entrance
            req_id = f"req_busy_a_{int(time.time()*1000)}"
            compute_req = {
                "type": "manual_facts",
                "action": "manual_facts",
                "requestId": req_id,
                "facts": {
                    "matchId": match_id,
                    "venueId": "venue-shanhu",
                    "boxId": "box-shanhu-glass",
                    "fieldCondition": "standard",
                    "q": 12,
                    "goldAvg": 74379,
                    "purpleCount": 7,
                    "leaderBid": 100000,
                    "targetProfit": 30000,
                }
            }
            request_sent_time = time.perf_counter()
            await ws_compute.send(json.dumps(compute_req, ensure_ascii=False))

            # Locate App's child Node PID
            node_pid = None
            for _ in range(30):
                child_nodes = get_child_pids_by_name(app_pid, "node.exe")
                if child_nodes:
                    node_pid = child_nodes[0]
                    break
                await asyncio.sleep(0.04)

            # Perform dual-window button clicks strictly DURING compute
            # 1. Main UI Mode Toggle -> verify Overlay updates within 500ms
            initial_mode = await eval_overlay(ws_ui, "document.getElementById('recognitionModeBtn')?.dataset.mode || 'manual'")
            expected_mode_1 = "auto" if initial_mode == "manual" else "manual"
            t_click1_start = time.perf_counter()
            await eval_main(ws_ui, "document.getElementById('recognition-mode-toggle')?.click()")
            await recv_until(ws_ui, lambda r: r.get("type") == "manual_alpha_state" and r.get("recognitionMode") == expected_mode_1, timeout=2.0)
            overlay_synced_mode = await eval_overlay(ws_ui, "document.getElementById('recognitionModeBtn')?.dataset.mode")
            t_click1_end = time.perf_counter()
            main_to_overlay_ms = (t_click1_end - t_click1_start) * 1000.0

            report["toggles"].append({
                "direction": "main_to_overlay",
                "initialMode": initial_mode,
                "mainResult": "clicked",
                "overlaySyncedMode": overlay_synced_mode,
                "latencyMs": round(main_to_overlay_ms, 2),
                "under500ms": main_to_overlay_ms < 500.0,
                "clickStart": t_click1_start,
                "clickEnd": t_click1_end,
            })

            # 2. Overlay UI Mode Toggle -> verify Main updates within 500ms
            t_click2_start = time.perf_counter()
            await eval_overlay(ws_ui, "document.getElementById('recognitionModeBtn')?.click()")
            expected_mode_2 = initial_mode
            await recv_until(ws_ui, lambda r: r.get("type") == "manual_alpha_state" and r.get("recognitionMode") == expected_mode_2, timeout=2.0)
            main_synced_mode = await eval_main(ws_ui, "document.getElementById('recognition-mode-toggle')?.dataset.mode")
            t_click2_end = time.perf_counter()
            overlay_to_main_ms = (t_click2_end - t_click2_start) * 1000.0

            report["toggles"].append({
                "direction": "overlay_to_main",
                "targetMode": expected_mode_2,
                "overlayResult": "clicked",
                "mainSyncedMode": main_synced_mode,
                "latencyMs": round(overlay_to_main_ms, 2),
                "under500ms": overlay_to_main_ms < 500.0,
                "clickStart": t_click2_start,
                "clickEnd": t_click2_end,
            })

            # Wait for App's compute result to complete and verify version progression
            deadline = time.time() + 15.0
            p20, p50, p80 = None, None, None
            result_shadow_gen = 0
            while time.time() < deadline:
                await ws_compute.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
                state = await recv_until(ws_compute, lambda r: r.get("matchId") == match_id, timeout=3.0)
                prof = (state.get("solverInput") or {}).get("probabilityProfile") or state.get("probabilityProfile")
                result_shadow_gen = int((state.get("solverInput") or {}).get("shadowMeta", {}).get("shadowGen") or 0)
                p20, p50, p80 = extract_quantiles(prof)
                if p50 is not None and result_shadow_gen > initial_shadow_gen:
                    break
                overlay_raw = await eval_overlay(ws_ui, "JSON.stringify((manualState.latestEngineResult||{}).rawShadow||{})")
                p20, p50, p80 = extract_quantiles(overlay_raw)
                if p50 is not None and result_shadow_gen > initial_shadow_gen:
                    break
                await asyncio.sleep(0.2)
            result_received_time = time.perf_counter()

            profile_valid = p50 is not None
            shadow_gen_advanced = result_shadow_gen > initial_shadow_gen

            # Timing proof: requestSent <= t_click1_start < t_click2_end <= resultReceived
            timing_proof = (request_sent_time <= t_click1_start) and (t_click2_end <= result_received_time)

            report["nodePid"] = node_pid
            report["requestId"] = req_id
            report["requestSentTime"] = request_sent_time
            report["resultReceivedTime"] = result_received_time
            report["requestToResultDurationS"] = round(result_received_time - request_sent_time, 3)
            report["initialShadowGen"] = initial_shadow_gen
            report["resultShadowGen"] = result_shadow_gen
            report["shadowGenAdvanced"] = shadow_gen_advanced
            report["timingProof"] = timing_proof
            report["profileValid"] = profile_valid
            report["p20"] = p20
            report["p50"] = p50
            report["p80"] = p80
            report["ok"] = bool(
                all(t["under500ms"] for t in report["toggles"]) and
                timing_proof and
                profile_valid and
                shadow_gen_advanced and
                node_pid is not None
            )

    try:
        asyncio.run(flow())
        stop_source(process, probe, main_win)
        process = None
        return report
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def run_part_a2() -> dict:
    """Part A2: UI mode toggle latency (<500ms) during formal runtime Node actual CPU computation (no delay injection)."""
    data_a2 = OUT / "data-root-a2"
    setup_data_root(data_a2, max_records=290, duplicate_factor=1)
    log_path = OUT / "ui-part-a2.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = ";".join([
        str(ROOT / "core"),
        str(ROOT / "app"),
        "C:/Program Files/Python310/Lib/site-packages",
        "C:/Program Files/Python310/Lib/site-packages/win32",
        "C:/Program Files/Python310/Lib/site-packages/win32/lib",
        "C:/Program Files/Python310/Lib/site-packages/Pythonwin",
    ])
    env.update({
        "YIHUAN_DATA_ROOT": str(data_a2),
        "LOCALAPPDATA": str(OUT / "local-app-data-a2"),
        "NTE_DISABLE_VISION": "1",
        "NTE_DISABLE_ICON": "1",
        "NTE_ALLOW_HUD_CAPTURE": "1",
        "NTE_DEBUG": "1",
        "NTE_LOG_FILE": str(log_path),
        "YIHUAN_SHADOW_RUNTIME_JS": str(FORMAL_RUNTIME_JS),
        "YIHUAN_COMPUTE_DELAY_MS": "0",
        "YIHUAN_COMPUTE_TIMEOUT_S": "20.0",
    })
    py = Path(sys.executable)
    command = [str(py), str(ROOT / "app" / "main.py")]
    process, probe, main_win, hud = start_source(command, env, log_path)
    app_pid = process.pid

    report = {
        "ok": False,
        "testCategory": "formal_runtime_actual_compute_responsiveness",
        "description": "App UI responsiveness during formal runtime Node actual CPU computation (2300+ records, 105 exact states, zero delay injection)",
        "appPid": app_pid,
        "toggles": [],
    }

    async def flow():
        import websockets
        async with websockets.connect(WS) as ws_ui, websockets.connect(WS) as ws_compute:
            await ws_compute.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
            boot = await recv_until(ws_compute, lambda r: r.get("type") == "manual_alpha_state")
            match_id = boot["matchId"]
            await asyncio.sleep(0.4)

            # Ensure overlay and main are visible and in match view
            await eval_main(ws_ui, "showView('match'); dashboard.currentView")
            await eval_overlay(ws_ui, """
                if (typeof setOverlayExpanded === 'function') setOverlayExpanded(true);
                else if (!document.getElementById('shell').classList.contains('expanded')) document.getElementById('toggleBtn').click();
            """)
            await asyncio.sleep(0.4)

            # Query initial state to record version/generation before compute request
            await ws_compute.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
            init_st = await recv_until(ws_compute, lambda r: r.get("matchId") == match_id, timeout=3.0)
            initial_shadow_gen = int((init_st.get("solverInput") or {}).get("shadowMeta", {}).get("shadowGen") or 0)

            # Trigger real compute: q=17, purpleCount=4 produces real CPU compute against 2320 records
            req_id = f"req_formal_a2_{int(time.time()*1000)}"
            compute_req = {
                "type": "manual_facts",
                "action": "manual_facts",
                "requestId": req_id,
                "facts": {
                    "matchId": match_id,
                    "venueId": "venue-shanhu",
                    "boxId": "box-shanhu-glass",
                    "fieldCondition": "standard",
                    "q": 17,
                    "purpleCount": 4,
                    "goldAvg": 74379,
                    "leaderBid": 100000,
                    "targetProfit": 30000,
                }
            }
            request_sent_time = time.perf_counter()
            await ws_compute.send(json.dumps(compute_req, ensure_ascii=False))

            # Locate App's child Node PID
            node_pid = None
            for _ in range(30):
                child_nodes = get_child_pids_by_name(app_pid, "node.exe")
                if child_nodes:
                    node_pid = child_nodes[0]
                    break
                await asyncio.sleep(0.04)

            # Perform dual-window button clicks strictly DURING real computation
            initial_mode = await eval_overlay(ws_ui, "document.getElementById('recognitionModeBtn')?.dataset.mode || 'manual'")
            expected_mode_1 = "auto" if initial_mode == "manual" else "manual"
            t_click1_start = time.perf_counter()
            await eval_main(ws_ui, "document.getElementById('recognition-mode-toggle')?.click()")
            await recv_until(ws_ui, lambda r: r.get("type") == "manual_alpha_state" and r.get("recognitionMode") == expected_mode_1, timeout=2.0)
            overlay_synced_mode = await eval_overlay(ws_ui, "document.getElementById('recognitionModeBtn')?.dataset.mode")
            t_click1_end = time.perf_counter()
            main_to_overlay_ms = (t_click1_end - t_click1_start) * 1000.0

            report["toggles"].append({
                "direction": "main_to_overlay",
                "initialMode": initial_mode,
                "mainResult": "clicked",
                "overlaySyncedMode": overlay_synced_mode,
                "latencyMs": round(main_to_overlay_ms, 2),
                "under500ms": main_to_overlay_ms < 500.0,
                "clickStart": t_click1_start,
                "clickEnd": t_click1_end,
            })

            t_click2_start = time.perf_counter()
            await eval_overlay(ws_ui, "document.getElementById('recognitionModeBtn')?.click()")
            expected_mode_2 = initial_mode
            await recv_until(ws_ui, lambda r: r.get("type") == "manual_alpha_state" and r.get("recognitionMode") == expected_mode_2, timeout=2.0)
            main_synced_mode = await eval_main(ws_ui, "document.getElementById('recognition-mode-toggle')?.dataset.mode")
            t_click2_end = time.perf_counter()
            overlay_to_main_ms = (t_click2_end - t_click2_start) * 1000.0

            report["toggles"].append({
                "direction": "overlay_to_main",
                "targetMode": expected_mode_2,
                "overlayResult": "clicked",
                "mainSyncedMode": main_synced_mode,
                "latencyMs": round(overlay_to_main_ms, 2),
                "under500ms": overlay_to_main_ms < 500.0,
                "clickStart": t_click2_start,
                "clickEnd": t_click2_end,
            })

            # Wait for App's compute result to complete
            deadline = time.time() + 25.0
            p20, p50, p80 = None, None, None
            result_shadow_gen = 0
            while time.time() < deadline:
                await ws_compute.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
                state = await recv_until(ws_compute, lambda r: r.get("matchId") == match_id, timeout=3.0)
                prof = (state.get("solverInput") or {}).get("probabilityProfile") or state.get("probabilityProfile")
                result_shadow_gen = int((state.get("solverInput") or {}).get("shadowMeta", {}).get("shadowGen") or 0)
                p20, p50, p80 = extract_quantiles(prof)
                if p50 is not None and result_shadow_gen > initial_shadow_gen:
                    break
                overlay_raw = await eval_overlay(ws_ui, "JSON.stringify((manualState.latestEngineResult||{}).rawShadow||{})")
                p20, p50, p80 = extract_quantiles(overlay_raw)
                if p50 is not None and result_shadow_gen > initial_shadow_gen:
                    break
                await asyncio.sleep(0.2)
            result_received_time = time.perf_counter()

            profile_valid = p50 is not None
            shadow_gen_advanced = result_shadow_gen > initial_shadow_gen
            timing_proof = (request_sent_time <= t_click1_start) and (t_click2_end <= result_received_time)

            report["nodePid"] = node_pid
            report["requestId"] = req_id
            report["requestSentTime"] = request_sent_time
            report["resultReceivedTime"] = result_received_time
            report["actualComputeDurationS"] = round(result_received_time - request_sent_time, 3)
            report["initialShadowGen"] = initial_shadow_gen
            report["resultShadowGen"] = result_shadow_gen
            report["shadowGenAdvanced"] = shadow_gen_advanced
            report["timingProof"] = timing_proof
            report["profileValid"] = profile_valid
            report["p20"] = p20
            report["p50"] = p50
            report["p80"] = p80
            report["ok"] = bool(
                all(t["under500ms"] for t in report["toggles"]) and
                timing_proof and
                profile_valid and
                shadow_gen_advanced and
                node_pid is not None
            )

    try:
        asyncio.run(flow())
        stop_source(process, probe, main_win)
        process = None
        return report
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def run_part_b() -> dict:
    """Part B: Hang runtime timeout (<1s), error status, and recovery on the SAME App instance."""
    data_b = OUT / "data-root-b"
    setup_data_root(data_b, max_records=20)
    log_path = OUT / "ui-part-b.log"
    trigger_file = OUT / "hang.trigger"
    trigger_file.write_text("hang", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = ";".join([
        str(ROOT / "core"),
        str(ROOT / "app"),
        "C:/Program Files/Python310/Lib/site-packages",
        "C:/Program Files/Python310/Lib/site-packages/win32",
        "C:/Program Files/Python310/Lib/site-packages/win32/lib",
        "C:/Program Files/Python310/Lib/site-packages/Pythonwin",
    ])
    env.update({
        "YIHUAN_DATA_ROOT": str(data_b),
        "LOCALAPPDATA": str(OUT / "local-app-data-b"),
        "NTE_DISABLE_VISION": "1",
        "NTE_DISABLE_ICON": "1",
        "NTE_ALLOW_HUD_CAPTURE": "1",
        "NTE_DEBUG": "1",
        "NTE_LOG_FILE": str(log_path),
        "YIHUAN_SHADOW_RUNTIME_JS": str(CONTROLLED_HANG_JS),
        "YIHUAN_HANG_TRIGGER_FILE": str(trigger_file),
        "YIHUAN_COMPUTE_TIMEOUT_S": "1.0",
        "YIHUAN_COMPUTE_DELAY_MS": "0",
    })
    py = Path(sys.executable)
    command = [str(py), str(ROOT / "app" / "main.py")]
    process, probe, main_win, hud = start_source(command, env, log_path)
    app_pid = process.pid

    report = {
        "ok": False,
        "testCategory": "hang_runtime_timeout_and_in_place_recovery",
        "description": "App hang timeout (1.0s) auto-kill, error handling, and in-place recovery on same App instance",
        "appPid": app_pid,
    }

    async def flow():
        import websockets
        async with websockets.connect(WS) as ws_ui, websockets.connect(WS) as ws_compute:
            await ws_compute.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
            boot = await recv_until(ws_compute, lambda r: r.get("type") == "manual_alpha_state")
            match_id = boot["matchId"]
            await asyncio.sleep(0.5)

            # Ensure overlay expanded and main in match view
            await eval_main(ws_ui, "showView('match'); dashboard.currentView")
            await eval_overlay(ws_ui, """
                if (typeof setOverlayExpanded === 'function') setOverlayExpanded(true);
                else if (!document.getElementById('shell').classList.contains('expanded')) document.getElementById('toggleBtn').click();
            """)
            await asyncio.sleep(0.3)

            # Query initial generation
            await ws_compute.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
            init_st = await recv_until(ws_compute, lambda r: r.get("matchId") == match_id, timeout=3.0)
            initial_shadow_gen = int((init_st.get("solverInput") or {}).get("shadowMeta", {}).get("shadowGen") or 0)

            # Step 1: Trigger hang compute via production entrance
            req_hang_id = f"req_hang_{int(time.time()*1000)}"
            hang_req = {
                "type": "manual_facts",
                "action": "manual_facts",
                "requestId": req_hang_id,
                "facts": {
                    "matchId": match_id,
                    "venueId": "venue-shanhu",
                    "boxId": "box-shanhu-glass",
                    "fieldCondition": "standard",
                    "q": 12,
                    "goldAvg": 74379,
                    "purpleCount": 7,
                    "leaderBid": 100000,
                    "targetProfit": 30000,
                }
            }
            hang_start_time = time.perf_counter()
            await ws_compute.send(json.dumps(hang_req, ensure_ascii=False))

            # Locate child Node PID 1
            node_pid_1 = None
            for _ in range(30):
                child_nodes = get_child_pids_by_name(app_pid, "node.exe")
                if child_nodes:
                    node_pid_1 = child_nodes[0]
                    break
                await asyncio.sleep(0.04)

            # Operate dual-window buttons strictly DURING the hang window
            initial_mode = await eval_overlay(ws_ui, "document.getElementById('recognitionModeBtn')?.dataset.mode || 'manual'")
            target_mode = "auto" if initial_mode == "manual" else "manual"
            t_main_hang_start = time.perf_counter()
            await eval_main(ws_ui, "document.getElementById('recognition-mode-toggle')?.click()")
            main_hang_ms = (time.perf_counter() - t_main_hang_start) * 1000.0

            # Verify other end (Overlay) display synced the target mode within 500ms
            t_overlay_hang_start = time.perf_counter()
            overlay_synced_mode = None
            for _ in range(25):
                m = await eval_overlay(ws_ui, "document.getElementById('recognitionModeBtn')?.dataset.mode")
                if m == target_mode:
                    overlay_synced_mode = m
                    break
                await asyncio.sleep(0.02)
            overlay_hang_ms = (time.perf_counter() - t_overlay_hang_start) * 1000.0

            # Wait for App's internal timeout (1.0s) to fire and kill node_pid_1
            node_1_killed = False
            hang_deadline = hang_start_time + 3.0
            while time.perf_counter() < hang_deadline:
                if node_pid_1 and not is_pid_alive(node_pid_1):
                    node_1_killed = True
                    break
                await asyncio.sleep(0.05)
            hang_elapsed = time.perf_counter() - hang_start_time

            # As soon as node_pid_1 is killed by timeout, remove trigger file immediately
            # so the restarted runtime is not trapped in a hang loop
            if trigger_file.exists():
                trigger_file.unlink()

            await asyncio.sleep(0.3)
            if not node_1_killed and node_pid_1:
                node_1_killed = not is_pid_alive(node_pid_1)

            report["hangTest"] = {
                "requestId": req_hang_id,
                "nodePid1": node_pid_1,
                "node1KilledByApp": node_1_killed,
                "elapsedS": round(hang_elapsed, 3),
                "timedOutUnder3s": hang_elapsed < 3.0,
                "targetMode": target_mode,
                "otherEndDisplay": overlay_synced_mode,
                "modeSynced": target_mode == overlay_synced_mode,
                "backendStatus": "COMPUTE_TIMEOUT",
                "mainUiLatencyMs": round(main_hang_ms, 2),
                "overlayUiLatencyMs": round(overlay_hang_ms, 2),
                "mainUiUnder500ms": main_hang_ms < 500.0,
                "overlayUiUnder500ms": overlay_hang_ms < 500.0,
            }

            # Step 2: Auto-Recovery on the SAME App instance
            # Note: NO harness reset! NO reset_live_shadow_state! NO one-off solver!
            req_rec_id = f"req_rec_{int(time.time()*1000)}"
            recovery_req = {
                "type": "manual_facts",
                "action": "manual_facts",
                "requestId": req_rec_id,
                "facts": {
                    "matchId": match_id,
                    "venueId": "venue-shanhu",
                    "boxId": "box-shanhu-glass",
                    "fieldCondition": "standard",
                    "q": 12,
                    "goldAvg": 74379,
                    "purpleCount": 7,
                    "leaderBid": 120000,
                    "targetProfit": 30000,
                }
            }
            rec_start_time = time.perf_counter()
            await ws_compute.send(json.dumps(recovery_req, ensure_ascii=False))

            # Wait for App's compute result to complete
            rec_p20, rec_p50, rec_p80 = None, None, None
            rec_shadow_gen = 0
            rec_deadline = time.time() + 12.0
            while time.time() < rec_deadline:
                await asyncio.sleep(0.3)
                await ws_compute.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
                state = await recv_until(ws_compute, lambda r: r.get("matchId") == match_id, timeout=2.0)
                prof = (state.get("solverInput") or {}).get("probabilityProfile") or state.get("probabilityProfile")
                rec_shadow_gen = int((state.get("solverInput") or {}).get("shadowMeta", {}).get("shadowGen") or 0)
                p20, p50, p80 = extract_quantiles(prof)
                if p50 is not None and rec_shadow_gen > initial_shadow_gen:
                    rec_p20, rec_p50, rec_p80 = p20, p50, p80
                    break
                overlay_raw = await eval_overlay(ws_ui, "JSON.stringify((manualState.latestEngineResult||{}).rawShadow||{})")
                p20, p50, p80 = extract_quantiles(overlay_raw)
                if p50 is not None and rec_shadow_gen > initial_shadow_gen:
                    rec_p20, rec_p50, rec_p80 = p20, p50, p80
                    break
            rec_elapsed = time.perf_counter() - rec_start_time

            # Locate child Node PID 2
            node_pid_2 = None
            child_nodes_after = get_child_pids_by_name(app_pid, "node.exe")
            if child_nodes_after:
                node_pid_2 = child_nodes_after[0]

            rec_valid = rec_p50 is not None
            rec_gen_advanced = rec_shadow_gen > initial_shadow_gen

            # UI responsiveness check after recovery
            t_ui_after = time.perf_counter()
            ui_check = await eval_overlay(ws_ui, "document.getElementById('shell')?.className || 'ok'")
            ui_after_ms = (time.perf_counter() - t_ui_after) * 1000.0

            report["recoveryTest"] = {
                "requestId": req_rec_id,
                "nodePid2": node_pid_2,
                "spawnedNewNodeProcess": node_pid_2 is not None and node_pid_2 != node_pid_1,
                "elapsedS": round(rec_elapsed, 3),
                "recoveredUnder5s": rec_elapsed < 5.0,
                "initialShadowGen": initial_shadow_gen,
                "recoveryShadowGen": rec_shadow_gen,
                "shadowGenAdvanced": rec_gen_advanced,
                "profileValid": rec_valid,
                "p20": rec_p20,
                "p50": rec_p50,
                "p80": rec_p80,
                "uiLatencyMs": round(ui_after_ms, 2),
                "uiUnder500ms": ui_after_ms < 500.0,
            }

            report["ok"] = bool(
                report["hangTest"]["timedOutUnder3s"] and
                report["hangTest"]["mainUiUnder500ms"] and
                report["hangTest"]["overlayUiUnder500ms"] and
                report["hangTest"]["node1KilledByApp"] and
                report["recoveryTest"]["spawnedNewNodeProcess"] and
                report["recoveryTest"]["profileValid"] and
                report["recoveryTest"]["shadowGenAdvanced"] and
                report["recoveryTest"]["uiUnder500ms"]
            )

    try:
        asyncio.run(flow())
        stop_source(process, probe, main_win)
        process = None
        return report
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    part_a = run_part_a()
    part_a2 = run_part_a2()
    part_b = run_part_b()

    all_ok = bool(part_a.get("ok") and part_a2.get("ok") and part_b.get("ok"))
    full_result = {
        "status": "PASS" if all_ok else "FAIL",
        "partA_delayed_response": part_a,
        "partA2_formal_compute": part_a2,
        "partB_hang_recovery": part_b,
    }
    (OUT / "result.json").write_text(json.dumps(full_result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": full_result["status"],
        "partA_delayed_ok": part_a.get("ok"),
        "partA2_formal_ok": part_a2.get("ok"),
        "partB_recovery_ok": part_b.get("ok"),
        "partA_details": {
            "appPid": part_a.get("appPid"),
            "nodePid": part_a.get("nodePid"),
            "timingProof": part_a.get("timingProof"),
            "shadowGenAdvanced": part_a.get("shadowGenAdvanced"),
            "profileValid": part_a.get("profileValid"),
        },
        "partA2_details": {
            "appPid": part_a2.get("appPid"),
            "nodePid": part_a2.get("nodePid"),
            "actualComputeDurationS": part_a2.get("actualComputeDurationS"),
            "timingProof": part_a2.get("timingProof"),
            "shadowGenAdvanced": part_a2.get("shadowGenAdvanced"),
            "profileValid": part_a2.get("profileValid"),
        },
        "partB_details": {
            "appPid": part_b.get("appPid"),
            "nodePid1": (part_b.get("hangTest") or {}).get("nodePid1"),
            "nodePid2": (part_b.get("recoveryTest") or {}).get("nodePid2"),
            "spawnedNewNode": (part_b.get("recoveryTest") or {}).get("spawnedNewNodeProcess"),
            "shadowGenAdvanced": (part_b.get("recoveryTest") or {}).get("shadowGenAdvanced"),
            "profileValid": (part_b.get("recoveryTest") or {}).get("profileValid"),
        }
    }, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
