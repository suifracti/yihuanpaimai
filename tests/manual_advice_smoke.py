"""Source/fresh-package smoke for Formal Manual Estimate / Advice v2."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import websockets

from native_window_title_smoke import MAIN_TITLE, UnicodeWindowProbe, wait_until


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
CORE = ROOT / "core"
for entry in (str(APP), str(CORE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from runtime_data import runtime_data_paths  # noqa: E402
from evaluation_eligibility import validate_prediction_snapshot  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_fingerprint(path: Path) -> str:
    rows = []
    for file in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        stat = file.stat()
        rows.append((file.relative_to(path).as_posix(), stat.st_size, stat.st_mtime_ns, sha256(file)))
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def write_compact_supported_history(destination: Path) -> None:
    """Seed the real research cohort without bulky replay/debug blobs."""
    source = json.loads((ROOT / "异环拍卖数据.json").read_text(encoding="utf-8"))
    rows = []
    for record in source.get("records") or []:
        if isinstance(record, dict):
            rows.append({
                key: value
                for key, value in record.items()
                if key not in {"rounds", "prediction", "screenshots"}
            })
    destination.write_text(json.dumps({
        "version": source.get("version"),
        "schemaVersion": source.get("schemaVersion"),
        "records": rows,
    }, ensure_ascii=False), encoding="utf-8")


async def recv_until(socket, predicate, timeout=12):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        raw = await asyncio.wait_for(socket.recv(), timeout=max(0.2, deadline - time.time()))
        data = json.loads(raw)
        last = data
        if predicate(data):
            return data
    raise AssertionError(f"WebSocket response timeout; last={last}")


def decode_script_result(value):
    current = value
    for _ in range(3):
        if not isinstance(current, str):
            break
        try:
            current = json.loads(current)
        except json.JSONDecodeError:
            break
    return current


async def eval_overlay(socket) -> dict:
    script = """JSON.stringify((()=>{const r=manualState.latestEngineResult||{};const d=r.decision||{};const raw=r.rawShadow||{};const s=r.predictionSnapshot||null;const base=(manualState.latestNativePayload||{}).solverInput||{};const high=AuctionEngineV06.solveAuctionPipeline({...base,leaderBid:600000});const hd=high.decision||{};const hr=high.rawShadow||{};return {matchId:manualState.matchId,mode:r.degradationLevel||null,p20:raw.p20??null,p50:raw.p50??null,p80:raw.p80??null,recommendedMax:d.recommendedMax??null,action:d.actionDirective||null,highP20:hr.p20??null,highP50:hr.p50??null,highP80:hr.p80??null,highRecommendedMax:hd.recommendedMax??null,highAction:hd.actionDirective||null,predictionId:(s||{}).predictionId||null,predictionMatchId:(s||{}).matchId||null,predictionSnapshot:s,recomputedHash:s?AuctionEngineV06.sha256Json(s.input.normalizedFacts):null,displayP50:document.getElementById('p50Label').textContent,displayRecommended:document.getElementById('recommendedMax').textContent,displayMode:document.getElementById('supportMode').textContent};})())"""
    await socket.send(json.dumps({"type": "eval_overlay_js", "action": "eval_overlay_js", "script": script}))
    response = await recv_until(
        socket, lambda row: row.get("type") == "overlay_js_result", timeout=30
    )
    decoded = decode_script_result(response.get("result"))
    if not isinstance(decoded, dict):
        raise AssertionError(f"invalid Overlay eval result: {response!r}")
    return decoded


async def advice_flow() -> dict:
    async with websockets.connect("ws://127.0.0.1:8766") as socket:
        await socket.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
        boot = await recv_until(socket, lambda row: row.get("type") == "manual_alpha_state")
        match_a = boot["matchId"]
        facts = {
            "venueId": "venue-shanhu",
            "boxId": "box-shanhu-glass",
            "fieldCondition": "standard",
            "q": 12,
            "goldAvg": 74379,
            "purpleCount": 7,
            "leaderBid": 100000,
            "targetProfit": 30000,
        }
        await socket.send(json.dumps({"type": "manual_facts", "action": "manual_facts", "facts": facts}, ensure_ascii=False))
        state = await recv_until(socket, lambda row: row.get("matchId") == match_a and row.get("q") == 12)
        deadline = time.time() + 25
        while state.get("shadowUpdating") and time.time() < deadline:
            await asyncio.sleep(0.25)
            await socket.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
            state = await recv_until(socket, lambda row: row.get("matchId") == match_a)
        if state.get("shadowSupport", {}).get("status") != "HISTORICAL_SUPPORTED":
            raise AssertionError(f"historical support unavailable: {state.get('shadowSupport')}")
        await asyncio.sleep(1.2)
        low = await eval_overlay(socket)
        if low["mode"] != "full_shadow" or low["recommendedMax"] is None:
            raise AssertionError(f"formal advice unavailable: {low}")
        if low["predictionMatchId"] != match_a:
            raise AssertionError(f"prediction snapshot match mismatch: {low}")

        if [low[k] for k in ("p20", "p50", "p80")] != [low[k] for k in ("highP20", "highP50", "highP80")]:
            raise AssertionError("current bid changed intrinsic quantiles")
        if low["recommendedMax"] != low["highRecommendedMax"]:
            raise AssertionError("current bid changed recommendedMax definition")
        if low["action"] == low["highAction"]:
            raise AssertionError("current bid did not change v0.6 action")
        snapshot_valid, snapshot_reasons = validate_prediction_snapshot(
            low.get("predictionSnapshot") or {}, match_id=match_a
        )
        if not snapshot_valid:
            facts = low.get("predictionSnapshot", {}).get("input", {}).get("normalizedFacts") or {}
            canonical = json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            raise AssertionError(
                "prediction snapshot invalid before finalize: "
                f"{snapshot_reasons}; actualHash={hashlib.sha256(canonical.encode('utf-8')).hexdigest()}; "
                f"webviewRecomputedHash={low.get('recomputedHash')}; "
                f"canonicalAscii={canonical.encode('unicode_escape')!r}; snapshot={low.get('predictionSnapshot')}"
            )

        await socket.send(json.dumps({
            "type": "manual_facts", "action": "manual_facts", "facts": {"leaderBid": 600000}
        }))
        await recv_until(socket, lambda row: row.get("matchId") == match_a and row.get("leaderBid") == 600000)

        await asyncio.sleep(0.8)
        await socket.send(json.dumps({
            "type": "manual_finalize",
            "action": "manual_finalize",
            "expectedMatchId": match_a,
            "settlement": {
                "clearingPrice": 100000,
                "actualTotal": 500000,
                "acquired": True,
                "winner": "FixturePlayer",
            },
        }, ensure_ascii=False))
        finalized = await recv_until(
            socket,
            lambda row: bool(row.get("terminalResult")),
            timeout=60,
        )
        if finalized["terminalResult"].get("status") != "FINALIZED":
            raise AssertionError(f"finalize failed: {finalized['terminalResult']}")
        match_b = finalized["matchId"]
        if (
            match_b == match_a
            or finalized.get("solverAvailability") != "UNAVAILABLE"
            or finalized.get("q") is not None
            or finalized.get("leaderBid") is not None
        ):
            raise AssertionError(f"next-match native presentation was not cleared: {finalized}")
        return {
            "matchA": match_a,
            "matchB": match_b,
            "effectiveVenue": state["solverInput"]["venue"],
            "effectiveBox": state["solverInput"]["box"],
            "support": state["shadowSupport"]["status"],
            "mode": low["mode"],
            "p20": low["p20"],
            "p50": low["p50"],
            "p80": low["p80"],
            "recommendedMax": low["recommendedMax"],
            "lowAction": low["action"],
            "highAction": low["highAction"],
            "predictionId": low["predictionId"],
            "nextMatchCleared": True,
        }


async def empty_history_flow() -> dict:
    async with websockets.connect("ws://127.0.0.1:8766") as socket:
        await socket.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
        boot = await recv_until(socket, lambda row: row.get("type") == "manual_alpha_state")
        match_id = boot["matchId"]
        await socket.send(json.dumps({
            "type": "manual_facts",
            "action": "manual_facts",
            "facts": {
                "venueId": "venue-shanhu",
                "boxId": "box-shanhu-glass",
                "fieldCondition": "standard",
                "q": 12,
                "goldAvg": 74379,
                "purpleCount": 7,
                "leaderBid": 100000,
                "targetProfit": 30000,
            },
        }, ensure_ascii=False))
        state = await recv_until(
            socket, lambda row: row.get("matchId") == match_id and row.get("q") == 12
        )
        support = state.get("shadowSupport") or {}
        if (
            support.get("status") != "STRUCTURAL_ONLY"
            or "INSUFFICIENT_HISTORY" not in (support.get("reasonCodes") or [])
            or state.get("solverInput", {}).get("probabilityProfile") is not None
        ):
            raise AssertionError(f"empty history was not fail-honest: {support}")
        await asyncio.sleep(1.0)
        result = await eval_overlay(socket)
        if result.get("mode") != "structural_only" or result.get("recommendedMax") is not None:
            raise AssertionError(f"empty history produced formal advice: {result}")
        return {
            "support": support.get("status"),
            "reasonCodes": support.get("reasonCodes"),
            "mode": result.get("mode"),
            "recommendedMax": result.get("recommendedMax"),
            "noFakeHistoricalSupport": True,
        }


def start(command: list[str], env: dict, log_path: Path):
    probe = UnicodeWindowProbe()
    process = subprocess.Popen(command, cwd=ROOT, env=env, creationflags=subprocess.CREATE_NO_WINDOW)

    def ready():
        if process.poll() is not None:
            raise AssertionError(f"app exited before ready: {process.returncode}")
        windows = probe.top_windows(process.pid, visible_only=True)
        main = next((row for row in windows if row["title"] == MAIN_TITLE), None)
        if not main or not log_path.exists():
            return None
        log = log_path.read_text(encoding="utf-8", errors="strict")
        return (main, windows) if "Main presentation page ready" in log else None

    main, windows = wait_until(ready, "Manual advice smoke readiness", timeout=55)
    hud = [row for row in windows if "HUD" in row["title"]]
    if len(hud) != 1:
        raise AssertionError(f"expected exactly one Overlay, got {hud}")
    return process, probe, main, hud[0]


def stop(process, probe, main):
    probe.close(main["hwnd"])
    process.wait(timeout=30)
    if process.returncode != 0:
        raise AssertionError(f"unclean exit: {process.returncode}")


def check_forbidden_descendants(parent_pid: int) -> list[str]:
    TH32CS_SNAPPROCESS = 0x00000002
    import ctypes
    from ctypes import wintypes
    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.POINTER(wintypes.ULONG)),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', ctypes.c_char * 260)
        ]
    snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    children_map = {}
    if ctypes.windll.kernel32.Process32First(snapshot, ctypes.byref(entry)):
        while True:
            pid = entry.th32ProcessID
            ppid = entry.th32ParentProcessID
            name = entry.szExeFile.decode('gbk', errors='ignore')
            children_map.setdefault(ppid, []).append((pid, name))
            if not ctypes.windll.kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                break
    ctypes.windll.kernel32.CloseHandle(snapshot)
    descendants = []
    queue = [parent_pid]
    while queue:
        curr = queue.pop(0)
        for child_pid, child_name in children_map.get(curr, []):
            descendants.append(child_name)
            queue.append(child_pid)
    return [n for n in descendants if n.lower() in ('node.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe')]


def run_one(command: list[str], root: Path) -> dict:
    data_root = root / "data-root"
    log_path = root / "app.log"
    paths = runtime_data_paths({"YIHUAN_DATA_ROOT": str(data_root)})
    paths.history_path.parent.mkdir(parents=True, exist_ok=True)
    write_compact_supported_history(paths.history_path)
    env = os.environ.copy()
    env.update({
        "YIHUAN_DATA_ROOT": str(data_root),
        "LOCALAPPDATA": str(root / "local-app-data"),
        "YIHUAN_UPPER_TAIL_CAPTURE_DIR": str(root / "captures"),
        "NTE_DISABLE_VISION": "1",
        "NTE_DISABLE_ICON": "1",
        "NTE_MAIN_UI_SMOKE": "1",
        "NTE_ALLOW_HUD_CAPTURE": "1",
        "NTE_LOG_FILE": str(log_path),
    })
    process, probe, main, hud_before = start(command, env, log_path)
    try:
        try:
            result = asyncio.run(advice_flow())
        except Exception as exc:
            log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-24000:] if log_path.exists() else "<missing>"
            raise AssertionError(f"Manual advice flow failed: {exc!r}\nAPP LOG TAIL:\n{log_tail}") from exc
        forbidden = check_forbidden_descendants(process.pid)
        if forbidden:
            raise AssertionError(f"Forbidden subprocesses found in descendant tree: {forbidden}")
        rows = json.loads(paths.history_path.read_text(encoding="utf-8"))["records"]
        saved = [row for row in rows if row.get("id") == result["matchA"]]
        if len(saved) != 1 or saved[0].get("lifecycleStatus") != "FINALIZED":
            raise AssertionError("FINALIZED exactly-once record missing")
        snapshot = saved[0].get("predictionSnapshot") or {}
        if snapshot.get("predictionId") != result["predictionId"]:
            raise AssertionError("prediction snapshot was not preserved at finalize")
        hud_after = [row for row in probe.top_windows(process.pid, visible_only=True) if "HUD" in row["title"]]
        if len(hud_after) != 1 or hud_after[0]["hwnd"] != hud_before["hwnd"]:
            raise AssertionError("Overlay HWND changed")
        stop(process, probe, main)
        return {
            **result,
            "historySha256": sha256(paths.history_path),
            "recordCount": len(rows),
            "finalizedExactlyOnce": True,
            "predictionPreserved": True,
            "overlayHwndStable": True,
            "cleanExit": True,
        }
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def run_empty_one(command: list[str], root: Path) -> dict:
    data_root = root / "data-root"
    log_path = root / "app.log"
    paths = runtime_data_paths({"YIHUAN_DATA_ROOT": str(data_root)})
    paths.history_path.parent.mkdir(parents=True, exist_ok=True)
    paths.history_path.write_text('{"schemaVersion":6,"records":[]}', encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "YIHUAN_DATA_ROOT": str(data_root),
        "LOCALAPPDATA": str(root / "local-app-data"),
        "YIHUAN_UPPER_TAIL_CAPTURE_DIR": str(root / "captures"),
        "NTE_DISABLE_VISION": "1",
        "NTE_DISABLE_ICON": "1",
        "NTE_MAIN_UI_SMOKE": "1",
        "NTE_ALLOW_HUD_CAPTURE": "1",
        "NTE_LOG_FILE": str(log_path),
    })
    process, probe, main, _hud = start(command, env, log_path)
    try:
        result = asyncio.run(empty_history_flow())
        forbidden = check_forbidden_descendants(process.pid)
        if forbidden:
            raise AssertionError(f"Forbidden subprocesses found in descendant tree: {forbidden}")
        stop(process, probe, main)
        return {**result, "cleanExit": True}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def parity_signature(result: dict) -> dict:
    keys = (
        "effectiveVenue", "effectiveBox", "support", "mode", "p20", "p50", "p80",
        "recommendedMax", "lowAction", "highAction", "nextMatchCleared",
        "finalizedExactlyOnce", "predictionPreserved", "overlayHwndStable", "cleanExit",
    )
    return {key: result[key] for key in keys}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    args = parser.parse_args()
    executable = args.exe.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    with tempfile.TemporaryDirectory(prefix="nte-manual-advice-smoke-") as temp_dir:
        temp = Path(temp_dir)
        package_before = package_fingerprint(executable.parent)
        source_root = temp / "source"
        package_root = temp / "package"
        source_root.mkdir()
        package_root.mkdir()
        source = run_one([sys.executable, str(APP / "main.py")], source_root)
        package = run_one([str(executable)], package_root)
        empty_source_root = temp / "empty-source"
        empty_package_root = temp / "empty-package"
        empty_source_root.mkdir()
        empty_package_root.mkdir()
        empty_source = run_empty_one([sys.executable, str(APP / "main.py")], empty_source_root)
        empty_package = run_empty_one([str(executable)], empty_package_root)
        package_after = package_fingerprint(executable.parent)
        source_sig = parity_signature(source)
        package_sig = parity_signature(package)
        if source_sig != package_sig:
            raise AssertionError(f"source/package advice parity mismatch: {source_sig} != {package_sig}")
        if empty_source != empty_package:
            raise AssertionError(f"source/package empty-history parity mismatch: {empty_source} != {empty_package}")
        if package_before != package_after:
            raise AssertionError("package directory changed during smoke")
        print(json.dumps({
            "smoke": "manual_estimate_advice_v2",
            "source": source,
            "package": package,
            "emptyHistorySource": empty_source,
            "emptyHistoryPackage": empty_package,
            "sourcePackageParity": True,
            "packageDirectoryUnchanged": True,
        }, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
