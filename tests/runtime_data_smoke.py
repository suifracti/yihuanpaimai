"""Source/fresh-package smoke for RuntimeDataRoot v1.

This helper uses an isolated data root, creates one real Manual DRAFT through
the existing WebSocket path, restarts the package, and then opens the source
app against the same authority.  It never touches the user's real profile.
"""

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

from main_view_state import MainViewStateProvider  # noqa: E402
from runtime_data import runtime_data_paths  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_fingerprint(package_dir: Path) -> dict:
    rows = []
    for path in sorted((p for p in package_dir.rglob("*") if p.is_file())):
        stat = path.stat()
        rows.append(
            {
                "path": path.relative_to(package_dir).as_posix(),
                "size": stat.st_size,
                "mtimeNs": stat.st_mtime_ns,
                "sha256": _sha256(path),
            }
        )
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"fileCount": len(rows), "sha256": hashlib.sha256(encoded).hexdigest()}


async def _send_manual_draft() -> None:
    async with websockets.connect("ws://127.0.0.1:8766") as socket:
        await socket.send(
            json.dumps(
                {
                    "type": "manual_facts",
                    "action": "manual_facts",
                    "facts": {"q": 9},
                },
                ensure_ascii=False,
            )
        )
        try:
            await asyncio.wait_for(socket.recv(), timeout=3)
        except asyncio.TimeoutError:
            pass


def _records(path: Path) -> list:
    document = json.loads(path.read_text(encoding="utf-8"))
    return document if isinstance(document, list) else document.get("records", [])


def _run_once(
    command: list[str],
    environment: dict,
    log_path: Path,
    history_path: Path,
    *,
    create_draft: bool,
) -> dict:
    probe = UnicodeWindowProbe()
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    main_hwnd = None
    try:
        def ready_window():
            rows = probe.top_windows(process.pid, visible_only=True)
            match = next((row for row in rows if row["title"] == MAIN_TITLE), None)
            if process.poll() is not None:
                raise AssertionError(f"app exited before ready: {process.returncode}")
            if not match or not log_path.exists():
                return None
            log = log_path.read_text(encoding="utf-8", errors="strict")
            return match if "Main presentation page ready" in log else None

        main = wait_until(ready_window, "runtime-data smoke Main readiness", timeout=45)
        main_hwnd = main["hwnd"]
        initial_signature = MainViewStateProvider(history_path).snapshot().to_payload()
        if create_draft:
            asyncio.run(_send_manual_draft())

            def draft_written():
                if not history_path.exists():
                    return False
                rows = _records(history_path)
                return rows if any(row.get("lifecycleStatus") == "DRAFT" for row in rows) else False

            wait_until(draft_written, "Manual DRAFT persistence", timeout=10)

        signature = MainViewStateProvider(history_path).snapshot().to_payload()
        probe.close(main_hwnd)
        process.wait(timeout=20)
        if process.returncode != 0:
            raise AssertionError(f"unclean exit: {process.returncode}")
        return {
            "initialRecordCount": initial_signature["sourceRevisions"]["history"]["recordCount"],
            "recordCount": signature["sourceRevisions"]["history"]["recordCount"],
            "historySha256": signature["sourceRevisions"]["history"]["sha256"],
            "availability": signature["history"]["availability"],
            "admittedCount": signature["history"]["admittedCount"],
            "excludedCount": signature["history"]["excludedCount"],
            "cleanExit": True,
        }
    finally:
        if process.poll() is None:
            if main_hwnd:
                probe.close(main_hwnd)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    args = parser.parse_args()
    executable = args.exe.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)

    with tempfile.TemporaryDirectory(prefix="nte-runtime-data-smoke-") as temp:
        isolated = Path(temp)
        data_root = isolated / "data-root"
        paths = runtime_data_paths({"YIHUAN_DATA_ROOT": str(data_root)})
        environment = os.environ.copy()
        environment.update(
            {
                "YIHUAN_DATA_ROOT": str(data_root),
                "LOCALAPPDATA": str(isolated / "local-app-data"),
                "NTE_DISABLE_VISION": "1",
                "NTE_DISABLE_ICON": "1",
                "NTE_MAIN_UI_SMOKE": "1",
            }
        )
        package_dir = executable.parent
        bundled_history = package_dir / "_internal" / "异环拍卖数据.json"
        if bundled_history.exists():
            raise AssertionError("fresh package still bundles a live-looking history file")
        package_before = _package_fingerprint(package_dir)

        package_first_log = isolated / "package-first.log"
        environment["NTE_LOG_FILE"] = str(package_first_log)
        first = _run_once(
            [str(executable)],
            environment,
            package_first_log,
            paths.history_path,
            create_draft=True,
        )
        first_bytes = paths.history_path.read_bytes()

        package_restart_log = isolated / "package-restart.log"
        environment["NTE_LOG_FILE"] = str(package_restart_log)
        restart = _run_once(
            [str(executable)],
            environment,
            package_restart_log,
            paths.history_path,
            create_draft=False,
        )
        if paths.history_path.read_bytes() != first_bytes:
            raise AssertionError("package restart mutated history unexpectedly")

        source_log = isolated / "source.log"
        environment["NTE_LOG_FILE"] = str(source_log)
        source = _run_once(
            [sys.executable, str(APP_DIR / "main.py")],
            environment,
            source_log,
            paths.history_path,
            create_draft=False,
        )
        package_after = _package_fingerprint(package_dir)

        for current in (restart, source):
            for key in (
                "recordCount",
                "historySha256",
                "availability",
                "admittedCount",
                "excludedCount",
            ):
                if current[key] != first[key]:
                    raise AssertionError(f"source/package parity mismatch for {key}")
        if package_before != package_after:
            raise AssertionError("package directory changed during runtime history writes")

        parity_keys = (
            "recordCount",
            "historySha256",
            "availability",
            "admittedCount",
            "excludedCount",
        )
        parity = all(
            source[key] == restart[key] == first[key] for key in parity_keys
        )
        result = {
            "smoke": "runtime_data_authority_v1",
            "historyOutsidePackage": not str(paths.history_path).casefold().startswith(
                str(package_dir).casefold()
            ),
            "bundledHistoryAbsent": not bundled_history.exists(),
            "firstRunEmpty": first["initialRecordCount"] == 0,
            "draftPersistedAcrossRestart": restart["recordCount"] == 1,
            "sourcePackageParity": parity,
            "packageDirectoryUnchanged": package_before == package_after,
            "package": restart,
            "source": source,
            "cleanExit": all(row["cleanExit"] for row in (first, restart, source)),
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
