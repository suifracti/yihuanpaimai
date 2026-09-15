"""Source/fresh-package smoke for Manual Terminal Lifecycle v1."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import websockets

from native_window_title_smoke import MAIN_TITLE, UnicodeWindowProbe, wait_until


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from history_admission import build_duplicate_index, evaluate_history_admission  # noqa: E402
from runtime_data import runtime_data_paths  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_fingerprint(path: Path) -> str:
    rows = []
    for file in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        stat = file.stat()
        rows.append((file.relative_to(path).as_posix(), stat.st_size, stat.st_mtime_ns, _sha256(file)))
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def _records(path: Path) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document if isinstance(document, list) else document.get("records", [])
    return [row for row in rows if isinstance(row, dict)]


async def _recv_until(socket, predicate, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = await asyncio.wait_for(socket.recv(), timeout=max(0.2, deadline - time.time()))
        data = json.loads(raw)
        if predicate(data):
            return data
    raise AssertionError("WebSocket response timeout")


async def _terminal_flow() -> dict:
    async with websockets.connect("ws://127.0.0.1:8766") as socket:
        await socket.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
        boot = await _recv_until(socket, lambda row: row.get("type") == "manual_alpha_state")
        match_a = boot["matchId"]
        await socket.send(json.dumps({
            "type": "manual_facts",
            "action": "manual_facts",
            "facts": {
                "venueId": "venue-shanhu",
                "boxId": "box-shanhu-glass",
                "fieldCondition": "standard",
                "q": 9,
                "goldAvg": 33538,
                "purpleCount": 5,
                "knownGold": "万有星仪",
            },
        }, ensure_ascii=False))
        await _recv_until(socket, lambda row: row.get("matchId") == match_a and row.get("q") == 9)
        await socket.send(json.dumps({
            "type": "manual_finalize",
            "action": "manual_finalize",
            "expectedMatchId": match_a,
            "settlement": {
                "clearingPrice": 100000,
                "actualTotal": 160000,
                "acquired": True,
                "winner": "FixturePlayer",
            },
        }, ensure_ascii=False))
        finalized = await _recv_until(
            socket,
            lambda row: (row.get("terminalResult") or {}).get("status") == "FINALIZED",
        )
        match_b = finalized["matchId"]
        await socket.send(json.dumps({
            "type": "manual_finalize",
            "action": "manual_finalize",
            "expectedMatchId": match_a,
            "settlement": {
                "clearingPrice": 100000,
                "actualTotal": 160000,
                "acquired": True,
                "winner": "FixturePlayer",
            },
        }, ensure_ascii=False))
        retry = await _recv_until(
            socket,
            lambda row: (row.get("terminalResult") or {}).get("status") == "ALREADY_FINALIZED",
        )
        return {
            "matchA": match_a,
            "matchB": match_b,
            "newMatch": match_a != match_b,
            "retryStatus": retry["terminalResult"]["status"],
        }


async def _draft_only() -> str:
    async with websockets.connect("ws://127.0.0.1:8766") as socket:
        await socket.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
        boot = await _recv_until(socket, lambda row: row.get("type") == "manual_alpha_state")
        match_id = boot["matchId"]
        await socket.send(json.dumps({
            "type": "manual_facts", "action": "manual_facts", "facts": {"q": 7}
        }))
        await _recv_until(socket, lambda row: row.get("matchId") == match_id and row.get("q") == 7)
        return match_id


async def _bootstrap_match_id() -> str:
    async with websockets.connect("ws://127.0.0.1:8766") as socket:
        await socket.send(json.dumps({"type": "manual_bootstrap", "action": "manual_bootstrap"}))
        boot = await _recv_until(socket, lambda row: row.get("type") == "manual_alpha_state")
        return boot["matchId"]


def _start(command: list[str], env: dict, log_path: Path) -> tuple[subprocess.Popen, UnicodeWindowProbe, dict, list[dict]]:
    probe = UnicodeWindowProbe()
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    def ready():
        windows = probe.top_windows(process.pid, visible_only=True)
        main = next((row for row in windows if row["title"] == MAIN_TITLE), None)
        if process.poll() is not None:
            raise AssertionError(f"app exited before ready: {process.returncode}")
        if not main or not log_path.exists():
            return None
        log = log_path.read_text(encoding="utf-8", errors="strict")
        return (main, windows) if "Main presentation page ready" in log else None

    main, windows = wait_until(ready, "Manual terminal smoke readiness", timeout=50)
    hud = [row for row in windows if "HUD" in row["title"]]
    if len(hud) != 1:
        raise AssertionError(f"expected exactly one Overlay HUD, got {hud}")
    return process, probe, main, hud


def _stop(process, probe, main) -> None:
    probe.close(main["hwnd"])
    process.wait(timeout=25)
    if process.returncode != 0:
        raise AssertionError(f"unclean exit: {process.returncode}")


def _run_flow(command: list[str], env: dict, log_path: Path, history_path: Path) -> dict:
    process, probe, main, hud_before = _start(command, env, log_path)
    try:
        flow = asyncio.run(_terminal_flow())

        def finalized_on_disk():
            if not history_path.exists():
                return None
            rows = _records(history_path)
            matches = [row for row in rows if row.get("id") == flow["matchA"]]
            return rows if len(matches) == 1 and matches[0].get("lifecycleStatus") == "FINALIZED" else None

        rows = wait_until(finalized_on_disk, "FINALIZED persistence", timeout=10)
        hud_after = [row for row in probe.top_windows(process.pid, visible_only=True) if "HUD" in row["title"]]
        if len(hud_after) != 1 or hud_after[0]["hwnd"] != hud_before[0]["hwnd"]:
            raise AssertionError("Overlay HWND changed during Manual terminal transition")
        _stop(process, probe, main)
        duplicate_index = build_duplicate_index(rows)
        decision = evaluate_history_admission(
            next(row for row in rows if row["id"] == flow["matchA"]), duplicate_index
        )
        return {
            **flow,
            "historySha256": _sha256(history_path),
            "recordCount": len(rows),
            "finalizedCount": sum(row.get("lifecycleStatus") == "FINALIZED" for row in rows),
            "admitted": decision.admitted,
            "overlayHwndStable": True,
            "cleanExit": True,
        }
    finally:
        if process.poll() is None:
            try:
                _stop(process, probe, main)
            except Exception:
                process.kill()
                process.wait(timeout=5)


def _run_readback(command: list[str], env: dict, log_path: Path, history_path: Path, match_id: str) -> dict:
    process, probe, main, _ = _start(command, env, log_path)
    try:
        rows = _records(history_path)
        matches = [row for row in rows if row.get("id") == match_id]
        _stop(process, probe, main)
        return {
            "recordCount": len(rows),
            "matchCount": len(matches),
            "matchLifecycle": matches[0].get("lifecycleStatus") if len(matches) == 1 else None,
            "historySha256": _sha256(history_path),
            "cleanExit": True,
        }
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def _run_draft_restart(command: list[str], env: dict, first_log: Path, second_log: Path, history_path: Path) -> dict:
    process, probe, main, _ = _start(command, env, first_log)
    try:
        draft_id = asyncio.run(_draft_only())

        def draft_on_disk():
            if not history_path.exists():
                return None
            rows = _records(history_path)
            return rows if any(
                row.get("id") == draft_id and row.get("lifecycleStatus") == "DRAFT"
                for row in rows
            ) else None

        wait_until(draft_on_disk, "DRAFT persistence before restart", timeout=10)
        _stop(process, probe, main)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    env["NTE_LOG_FILE"] = str(second_log)
    process, probe, main, _ = _start(command, env, second_log)
    try:
        active_after_restart = asyncio.run(_bootstrap_match_id())
        rows = _records(history_path)
        old = [row for row in rows if row.get("id") == draft_id]
        _stop(process, probe, main)
        if active_after_restart == draft_id:
            raise AssertionError("old persisted DRAFT was incorrectly resumed as active CurrentMatch")
        if len(old) != 1 or old[0].get("lifecycleStatus") != "DRAFT":
            raise AssertionError("persisted DRAFT did not survive restart unchanged")
        return {
            "draftId": draft_id,
            "activeAfterRestart": active_after_restart,
            "oldDraftPreserved": True,
            "oldDraftNotAutoResumed": True,
            "cleanExit": True,
        }
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    args = parser.parse_args()
    executable = args.exe.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)

    with tempfile.TemporaryDirectory(prefix="nte-manual-terminal-smoke-") as temp_dir:
        temp = Path(temp_dir)
        package_dir = executable.parent
        package_before = _package_fingerprint(package_dir)

        def environment(root: Path, log: Path) -> tuple[dict, Path]:
            data_root = root / "data-root"
            env = os.environ.copy()
            env.update({
                "YIHUAN_DATA_ROOT": str(data_root),
                "LOCALAPPDATA": str(root / "local-app-data"),
                "NTE_DISABLE_VISION": "1",
                "NTE_DISABLE_ICON": "1",
                "NTE_MAIN_UI_SMOKE": "1",
                "NTE_LOG_FILE": str(log),
            })
            return env, runtime_data_paths({"YIHUAN_DATA_ROOT": str(data_root)}).history_path

        source_root = temp / "source"
        source_log = source_root / "source.log"
        source_root.mkdir(parents=True)
        source_env, source_history = environment(source_root, source_log)
        source = _run_flow(
            [sys.executable, str(APP_DIR / "main.py")], source_env, source_log, source_history
        )

        draft_root = temp / "draft-restart"
        draft_root.mkdir(parents=True)
        draft_first_log = draft_root / "draft-first.log"
        draft_env, draft_history = environment(draft_root, draft_first_log)
        draft_restart = _run_draft_restart(
            [sys.executable, str(APP_DIR / "main.py")],
            draft_env,
            draft_first_log,
            draft_root / "draft-second.log",
            draft_history,
        )

        package_root = temp / "package"
        package_log = package_root / "package.log"
        package_root.mkdir(parents=True)
        package_env, package_history = environment(package_root, package_log)
        package = _run_flow([str(executable)], package_env, package_log, package_history)
        package_bytes = package_history.read_bytes()

        restart_log = package_root / "package-restart.log"
        package_env["NTE_LOG_FILE"] = str(restart_log)
        restart = _run_readback(
            [str(executable)], package_env, restart_log, package_history, package["matchA"]
        )
        if package_history.read_bytes() != package_bytes:
            raise AssertionError("restart mutated finalized history")

        parity_log = package_root / "source-parity.log"
        package_env["NTE_LOG_FILE"] = str(parity_log)
        parity = _run_readback(
            [sys.executable, str(APP_DIR / "main.py")],
            package_env,
            parity_log,
            package_history,
            package["matchA"],
        )
        if restart != parity:
            raise AssertionError(f"source/package parity mismatch: {restart} != {parity}")
        package_after = _package_fingerprint(package_dir)
        if package_before != package_after:
            raise AssertionError("package directory changed during Manual history writes")

        result = {
            "smoke": "manual_terminal_lifecycle_v1",
            "source": source,
            "draftRestart": draft_restart,
            "package": package,
            "packageRestart": restart,
            "sourcePackageParity": restart == parity,
            "packageDirectoryUnchanged": package_before == package_after,
            "restartExactlyOnce": restart["matchCount"] == 1 and restart["matchLifecycle"] == "FINALIZED",
            "cleanExit": all(row["cleanExit"] for row in (source, package, restart, parity)),
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
