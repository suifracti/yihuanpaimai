"""Stop only observed children of this isolated app, then restore via native UI."""
import argparse
import asyncio
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import re
import subprocess
import sys
import websockets
from verify_p1_real_ui import WS, eval_main, eval_overlay, wait_main_match
from verify_p3_isolated_real_app_history import run_one_launch


def stop_observed_worker(pid, executable=None):
    query = '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); ' + f'Get-CimInstance Win32_Process -Filter "ProcessId = {pid}" | Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress'
    result = subprocess.run(['powershell', '-NoProfile', '-Command', query], capture_output=True, text=True, encoding="utf-8", check=True)
    if not result.stdout.strip():
        return
    process = json.loads(result.stdout)
    assert process['ProcessId'] == pid and '--vision-worker' in process['CommandLine']
    allowed = {str(Path(path).resolve()).lower() for path in (sys.executable, getattr(sys, '_base_executable', sys.executable))}
    if executable is not None:
        allowed = {str(executable.resolve(strict=True)).lower()}
    assert str(Path(process['ExecutablePath']).resolve()).lower() in allowed
    if executable is None:
        assert str(Path(__file__).resolve().parents[1]/'app/main.py').lower() in process['CommandLine'].lower()
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100001, False, pid)
    assert handle
    try:
        assert kernel.TerminateProcess(handle, 1)
        assert kernel.WaitForSingleObject(handle, 5000) == 0
    finally:
        kernel.CloseHandle(handle)


def verify(out, executable=None):
    out = out.resolve(); out.mkdir(parents=True, exist_ok=False)
    history = out/'data/history/异环拍卖数据.json'; history.parent.mkdir(parents=True)
    history.write_text(json.dumps({'schemaVersion':7, 'records':[]}), encoding='utf-8')
    log = out/'app.log'
    def pids():
        return [int(x) for x in re.findall(r'Vision worker process started \(PID=(\d+)\)', log.read_text(encoding='utf-8', errors='replace'))]
    async def interact(_zip, _export):
        rows = []
        async with websockets.connect(WS) as ws:
            await eval_main(ws, "showView('match'); true")
            await eval_overlay(ws, 'setOverlayExpanded(true); true')
            initial = await wait_main_match(ws, lambda d: d.get('visionHealth', {}).get('status') in ('READY', 'WAITING'), timeout=45)
            for target, fn, button in [('main',eval_main,'restore-vision-btn'),('hud',eval_overlay,'restoreVisionBtn')]:
                before = pids()
                assert before
                await asyncio.to_thread(stop_observed_worker, before[-1], executable)
                await wait_main_match(ws, lambda d: d.get('visionHealth', {}).get('stage') == 'process')
                for probe, element in [(eval_main,'restore-vision-btn'), (eval_overlay,'restoreVisionBtn')]:
                    assert await probe(ws, '!document.getElementById('+json.dumps(element)+').hidden')
                assert await fn(ws, "(()=>{const el=document.getElementById("+json.dumps(button)+");if(el.hidden)return false;el.click();return true;})()")
                recovered = await wait_main_match(ws, lambda d: d.get('visionHealth', {}).get('status') in ('READY','WAITING'), timeout=45)
                after = pids()
                assert len(after) == len(before)+1 and after[-1] != before[-1]
                assert recovered['matchId'] == initial['matchId']
                rows.append({'button':target,'oldPid':before[-1],'newPid':after[-1],'sameMatch':True,'health':recovered['visionHealth']})
        return rows
    report = {'status':'RUNNING'}
    try:
        dual, rows, clean = run_one_launch('exit', out/'data', log, out, interactor=interact, vision_enabled=True, frozen_executable=executable)
        assert dual and clean
        report.update(status='PASS',dualLaunched=dual,cleanExit=clean,restarts=rows)
    except Exception as exc:
        report.update(status='FAIL',error=repr(exc));raise
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if log.exists():
            for pid in pids():
                stop_observed_worker(pid, executable)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument("--executable", type=Path)
    args = parser.parse_args()
    verify(args.output, args.executable)
