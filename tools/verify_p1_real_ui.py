# -*- coding: utf-8 -*-
"""Launch source Main + Overlay and exercise real inputs/buttons.

Isolated YIHUAN_DATA_ROOT. Does not call apply_manual_facts from the harness.
"""
from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "app"), str(ROOT / "core")]
pywin32_dir = r"C:\Program Files\Python310\Lib\site-packages\pywin32_system32"
if os.path.isdir(pywin32_dir) and hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(pywin32_dir)
    except Exception:
        pass
from manual_advice_smoke import decode_script_result  # noqa: E402
from native_window_title_smoke import MAIN_TITLE, OVERLAY_TITLE, UnicodeWindowProbe, wait_until, WM_CLOSE  # noqa: E402

OUT = ROOT / "build" / "diagnosis_20260909" / "p1-real-ui"
WS = "ws://127.0.0.1:8766"


async def recv_until(socket, predicate, timeout=20):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        raw = await asyncio.wait_for(socket.recv(), timeout=max(0.2, deadline - time.time()))
        data = json.loads(raw)
        last = data
        if predicate(data):
            return data
    raise AssertionError(f"timeout last={last}")


async def eval_overlay(socket, script, timeout=40):
    await socket.send(json.dumps({"type": "eval_overlay_js", "action": "eval_overlay_js", "script": script}))
    response = await recv_until(socket, lambda row: row.get("type") == "overlay_js_result", timeout=timeout)
    return decode_script_result(response.get("result"))


async def eval_main(socket, script, timeout=40):
    await socket.send(json.dumps({"type": "eval_main_js", "action": "eval_main_js", "script": script}))
    response = await recv_until(socket, lambda row: row.get("type") == "main_js_result", timeout=timeout)
    return decode_script_result(response.get("result"))


async def wait_overlay_payload(socket, predicate, timeout=20):
    await asyncio.sleep(0.4)
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = await eval_overlay(socket, "JSON.stringify(manualState.latestNativePayload||{})")
        if isinstance(last, dict) and predicate(last):
            return last
        await asyncio.sleep(0.35)
    raise AssertionError(f"overlay payload timeout last={last}")


async def wait_main_match(socket, predicate, timeout=12):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = await eval_main(socket, "JSON.stringify(dashboard.lastCurrentMatch||{})")
        if isinstance(last, dict) and predicate(last):
            return last
        await asyncio.sleep(0.2)
    raise AssertionError(f"main match timeout last={last}")


def capture_hwnd(hwnd: int, path: Path) -> None:
    import win32gui
    import win32ui
    import win32con
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = max(1, right - left), max(1, bottom - top)
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hwnd_dc)
    dst = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, width, height)
    dst.SelectObject(bmp)
    dst.BitBlt((0, 0), (width, height), src, (0, 0), win32con.SRCCOPY)
    bmp.SaveBitmapFile(dst, str(path))
    win32gui.DeleteObject(bmp.GetHandle())
    dst.DeleteDC()
    src.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_process_ids(parent_pid: int) -> set[int]:
    """Include Windows venv launcher children, never unrelated titled windows."""
    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    parents = {}
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    owned = {parent_pid}
    while True:
        children = {pid for pid, parent in parents.items() if parent in owned}
        if children <= owned:
            return owned
        owned.update(children)


def source_window_pair(probe: UnicodeWindowProbe, pids: set[int]):
    for pid in sorted(pids):
        windows = probe.top_windows(pid, visible_only=True)
        main = next((row for row in windows if row["title"] == MAIN_TITLE), None)
        hud = next((row for row in windows if row["title"] == OVERLAY_TITLE), None)
        if main and hud:
            return dict(main, ownerPid=pid), dict(hud, ownerPid=pid)
    return None


def start_source(command: list[str], env: dict, log_path: Path, cwd: Path = ROOT):
    probe = UnicodeWindowProbe()
    process = subprocess.Popen(command, cwd=str(cwd), env=env)

    def ready():
        if process.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:] if log_path.exists() else ""
            raise AssertionError(f"app exited before ready: {process.returncode}\n{tail}")
        if not log_path.exists():
            return None
        log = log_path.read_text(encoding="utf-8", errors="replace")
        if "Main presentation page ready" not in log:
            return None
        return source_window_pair(probe, source_process_ids(process.pid))

    main, hud = wait_until(ready, "source Main+Overlay ready", timeout=70)
    return process, probe, main, hud


def stop_source(process, probe, main):
    probe.close(main["hwnd"])
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


async def flow(shots: Path) -> dict:
    evidence = {"steps": []}
    async with websockets.connect(WS) as socket:
        await socket.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
        boot = await recv_until(socket, lambda row: row.get("type") == "manual_alpha_state")
        match_id = boot["matchId"]
        await asyncio.sleep(0.8)
        venues = await eval_overlay(socket, "JSON.stringify((manualState.options.venues||[]).map(v=>v.displayName||v.venueId))")
        if not venues:
            raise AssertionError("overlay venue options empty")

        await eval_overlay(socket, """
            if (typeof setOverlayExpanded === 'function') setOverlayExpanded(true);
            else if (!document.getElementById('shell').classList.contains('expanded')) document.getElementById('toggleBtn').click();
            document.getElementById('shell').classList.contains('expanded')
        """)
        await eval_main(socket, "showView('match'); dashboard.currentView")
        await asyncio.sleep(0.4)

        await eval_overlay(socket, """
            document.getElementById('venueChip').click();
            const item=[...document.querySelectorAll('#popoverList .popover-item')].find(el=>el.textContent.includes('珊瑚'));
            if(!item) throw 'no coral venue';
            item.click();
            'venue-clicked'
        """)
        state = await wait_overlay_payload(socket, lambda row: row.get("venueId") == "venue-shanhu")
        await asyncio.sleep(0.3)
        clicked = await eval_overlay(socket, """
            JSON.stringify((()=>{
              document.getElementById('boxChip').click();
              const items=[...document.querySelectorAll('#popoverList .popover-item')].map(el=>({val:el.getAttribute('data-val'), text:el.textContent.trim()}));
              const item=[...document.querySelectorAll('#popoverList .popover-item')].find(el=> (el.textContent||'').includes('琉璃') || (el.getAttribute('data-val')||'').includes('glass'));
              if(!item) return {error:'no glass', items, list:document.getElementById('popoverList').innerText, venueId:manualState.venueId};
              item.dispatchEvent(new MouseEvent('click',{bubbles:true}));
              return {clicked:item.getAttribute('data-val'), box:manualState.box, boxId:manualState.boxId, items};
            })())
        """)
        if isinstance(clicked, dict) and clicked.get("error"):
            raise AssertionError(f"box click failed: {clicked}")
        state = await wait_overlay_payload(
            socket,
            lambda row: row.get("boxId") == "box-shanhu-glass" or "琉璃" in str(row.get("box") or ""),
        )
        evidence["steps"].append({"step": "box-click", "clicked": clicked})
        box_after_select = state.get("box")
        evidence["steps"].append({"step": "select-venue-box", "box": box_after_select, "q": state.get("q"), "venueId": state.get("venueId")})

        await eval_overlay(socket, """
            const el=document.getElementById('goldAvgInput');
            el.focus(); el.value='64836';
            el.dispatchEvent(new Event('input',{bubbles:true}));
            el.dispatchEvent(new Event('change',{bubbles:true}));
            handleLocalInput(el);
            el.value
        """)
        await asyncio.sleep(0.5)

        q_typed = await eval_main(socket, """
            const el=document.getElementById('match-input-q');
            el.focus(); el.value='21';
            el.dispatchEvent(new Event('input',{bubbles:true}));
            el.dispatchEvent(new Event('change',{bubbles:true}));
            el.value
        """)
        state = await wait_overlay_payload(socket, lambda row: row.get("q") == 21)
        await asyncio.sleep(0.3)
        overlay_view = await eval_overlay(socket, """JSON.stringify({
            q: document.getElementById('qInput').value,
            box: document.getElementById('boxChipText').textContent,
            gold: document.getElementById('goldAvgInput').value,
            protected: !!(manualState.fieldStates||{}).box && manualState.fieldStates.box.protected,
            payloadBox: (manualState.latestNativePayload||{}).box,
            payloadQ: (manualState.latestNativePayload||{}).q
        })""")
        main_view = await eval_main(socket, """JSON.stringify({
            q: document.getElementById('match-input-q').value,
            box: document.getElementById('match-box-display').textContent,
            view: dashboard.currentView,
            payloadBox: (dashboard.lastCurrentMatch||{}).facts?.box || (dashboard.lastCurrentMatch||{}).environment?.box,
            payloadQ: (dashboard.lastCurrentMatch||{}).facts?.q
        })""")
        if state.get("box") != box_after_select:
            raise AssertionError(f"Q-only cleared box: {state.get('box')} vs {box_after_select}")
        if overlay_view.get("payloadQ") != 21 or main_view.get("payloadQ") not in (21, "21"):
            raise AssertionError(f"Q not synced both ends overlay={overlay_view} main={main_view}")
        evidence["steps"].append({"step": "main-q-only", "typed": q_typed, "overlay": overlay_view, "main": main_view, "receiptBox": state.get("box"), "receiptQ": state.get("q")})

        await eval_overlay(socket, """
            document.getElementById('boxChip').click();
            const item=[...document.querySelectorAll('#popoverList .popover-item')].find(el=>el.textContent.includes('琉璃'));
            if(!item) throw 'confirm box missing';
            item.click();
            'confirmed'
        """)
        state = await wait_overlay_payload(socket, lambda row: bool(((row.get("fieldStates") or {}).get("box") or {}).get("protected")))
        evidence["steps"].append({"step": "overlay-confirm", "protected": True, "box": state.get("box"), "fieldStates": (state.get("fieldStates") or {}).get("box")})

        cleared = await eval_overlay(socket, """
            JSON.stringify((()=>{
              document.getElementById('boxChip').click();
              const item=document.querySelector('#popoverList .popover-item[data-val="__unknown__"]')
                || [...document.querySelectorAll('#popoverList .popover-item')].find(el=> (el.textContent||'').includes('未知'));
              if(!item) return {error:'clear option missing', html:document.getElementById('popoverList').innerHTML};
              item.dispatchEvent(new MouseEvent('click',{bubbles:true}));
              return {val:item.getAttribute('data-val'), box:manualState.box, explicit:manualState.boxUnknownExplicit};
            })())
        """)
        if isinstance(cleared, dict) and cleared.get("error"):
            raise AssertionError(f"clear click failed: {cleared}")
        evidence["steps"].append({"step": "overlay-clear-click", "cleared": cleared})
        state = await wait_overlay_payload(
            socket,
            lambda row: row.get("box") in (None, "", "未选择") or ((row.get("fieldStates") or {}).get("box") or {}).get("status") == "cleared",
        )
        evidence["steps"].append({"step": "overlay-clear", "box": state.get("box"), "fieldStates": (state.get("fieldStates") or {}).get("box")})

        restored = await eval_overlay(socket, """
            JSON.stringify((()=>{
              document.getElementById('boxChip').click();
              const item=document.querySelector('#popoverList .popover-item[data-val="__restore_auto__"]')
                || [...document.querySelectorAll('#popoverList .popover-item')].find(el=>(el.textContent||'').includes('恢复自动'));
              if(!item) return {error:'restore auto missing', html:document.getElementById('popoverList').innerHTML, protected:!!(manualState.fieldStates||{}).box?.protected};
              item.dispatchEvent(new MouseEvent('click',{bubbles:true}));
              return {clicked:true};
            })())
        """)
        if isinstance(restored, dict) and restored.get("error"):
            raise AssertionError(f"restore click failed: {restored}")
        evidence["steps"].append({"step": "overlay-restore-click", "restored": restored})
        state = await wait_overlay_payload(socket, lambda row: not ((row.get("fieldStates") or {}).get("box") or {}).get("protected", True))
        evidence["steps"].append({"step": "overlay-restore-auto", "protected": ((state.get("fieldStates") or {}).get("box") or {}).get("protected"), "box": state.get("box")})

        before_mode = await eval_overlay(socket, "document.getElementById('recognitionModeBtn').dataset.mode")
        await eval_overlay(socket, "document.getElementById('recognitionModeBtn').click(); document.getElementById('recognitionModeBtn').dataset.mode")
        state = await wait_overlay_payload(socket, lambda row: row.get("recognitionMode") and row.get("recognitionMode") != before_mode)
        overlay_mode = await eval_overlay(socket, "document.getElementById('recognitionModeBtn').dataset.mode")
        await eval_main(socket, "document.getElementById('recognition-mode-toggle').click(); document.getElementById('recognition-mode-toggle').dataset.mode")
        state2 = await wait_overlay_payload(socket, lambda row: row.get("recognitionMode") and row.get("recognitionMode") != state.get("recognitionMode"))
        main_mode = await eval_main(socket, "document.getElementById('recognition-mode-toggle').dataset.mode")
        evidence["steps"].append({
            "step": "mode-toggle-both-ends",
            "overlayClickedTo": overlay_mode,
            "mainClickedTo": main_mode,
            "receipt1": state.get("recognitionMode"),
            "receipt2": state2.get("recognitionMode"),
        })
        if overlay_mode != state.get("recognitionMode"):
            raise AssertionError(f"overlay mode display {overlay_mode} != receipt {state.get('recognitionMode')}")

        busy = await eval_overlay(socket, """
            JSON.stringify((()=>{
              const input = Object.assign({q:21,goldAvg:64836,purpleCount:5,box:'琉璃宝箱',fieldCondition:'standard'}, (manualState.latestNativePayload||{}).solverInput||{});
              window.__p1Busy = {started: Date.now(), done:false, modeAtClick:null, elapsed:null};
              setTimeout(()=>{
                const t0 = Date.now();
                for (let i=0;i<12;i++) AuctionEngineV06.solveAuctionPipeline(input);
                window.__p1Busy.done = true;
                window.__p1Busy.elapsed = Date.now()-t0;
              }, 0);
              document.getElementById('recognitionModeBtn').click();
              window.__p1Busy.modeAtClick = document.getElementById('recognitionModeBtn').dataset.mode;
              window.__p1Busy.clickLag = Date.now()-window.__p1Busy.started;
              window.__p1Busy.doneAtClick = window.__p1Busy.done;
              return window.__p1Busy;
            })())
        """, timeout=30)
        deadline = time.time() + 8
        while time.time() < deadline:
            status = await eval_overlay(socket, "JSON.stringify(window.__p1Busy||{})")
            if status.get("done"):
                busy = status
                break
            await asyncio.sleep(0.05)
        if not busy.get("elapsed") or busy["elapsed"] < 5:
            raise AssertionError(f"busy task was not actually expensive: {busy}")
        if busy.get("doneAtClick"):
            raise AssertionError(f"mode click waited for solver: {busy}")
        if busy.get("clickLag", 9999) > busy["elapsed"]:
            raise AssertionError(f"mode click lagged behind solver {busy}")
        evidence["steps"].append({"step": "busy-real-solver", "busy": busy})
        evidence["ok"] = True
        evidence["matchId"] = match_id
        return evidence


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    shots = OUT / "shots"
    shots.mkdir(exist_ok=True)
    data_root = OUT / "data-root"
    if data_root.exists():
        import shutil
        shutil.rmtree(data_root)
    data_root.mkdir(parents=True)
    (data_root / "history").mkdir(parents=True, exist_ok=True)
    (data_root / "history" / "异环拍卖数据.json").write_text(
        '{"schemaVersion":6,"records":[]}', encoding="utf-8"
    )
    log_path = OUT / "app.log"
    if log_path.exists():
        log_path.unlink()
    py = Path(sys.executable)
    env = os.environ.copy()
    python_path_parts = [
        str(ROOT / "core"),
        str(ROOT / "app"),
        "C:/Program Files/Python310/Lib/site-packages",
        "C:/Program Files/Python310/Lib/site-packages/win32",
        "C:/Program Files/Python310/Lib/site-packages/win32/lib",
        "C:/Program Files/Python310/Lib/site-packages/Pythonwin",
    ]
    env["PYTHONPATH"] = ";".join(python_path_parts)
    env.update({
        "YIHUAN_DATA_ROOT": str(data_root),
        "LOCALAPPDATA": str(OUT / "local-app-data"),
        "YIHUAN_UPPER_TAIL_CAPTURE_DIR": str(OUT / "captures"),
        "NTE_DISABLE_VISION": "1",
        "NTE_DISABLE_ICON": "1",
        "NTE_ALLOW_HUD_CAPTURE": "1",
        "NTE_DEBUG": "1",
        "NTE_LOG_FILE": str(log_path),
    })
    command = [str(py), str(ROOT / "app" / "main.py")]
    process, probe, main_win, hud = start_source(command, env, log_path)
    result = {"status": "FAIL"}
    try:
        capture_hwnd(main_win["hwnd"], shots / "01-main-ready.bmp")
        capture_hwnd(hud["hwnd"], shots / "02-overlay-ready.bmp")
        evidence = asyncio.run(flow(shots))
        capture_hwnd(main_win["hwnd"], shots / "03-main-after.bmp")
        capture_hwnd(hud["hwnd"], shots / "04-overlay-after.bmp")
        evidence["shots"] = {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(shots.glob("*"))
        }
        evidence["logSha256"] = sha256(log_path) if log_path.exists() else None
        result = {"status": "PASS", **evidence}
        stop_source(process, probe, main_win)
        process = None
    except Exception as exc:
        result = {
            "status": "FAIL",
            "error": repr(exc),
            "logTail": log_path.read_text(encoding="utf-8", errors="replace")[-12000:] if log_path.exists() else None,
        }
        raise
    finally:
        (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    print(json.dumps({"status": result["status"], "steps": [s["step"] for s in result.get("steps") or []]}, ensure_ascii=False))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
