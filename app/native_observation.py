"""Launcher for the opt-in native-readonly observation profile.

The GUI owns this child process.  The child owns WGC/MMF and the single
``engine_v22`` business worker; this module only transports versioned JSON
observation lines back to ``main.py`` and never captures a second frame.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Optional


class NativeObservationBridge:
    def __init__(
        self,
        repo_root: str,
        on_event: Callable[[dict[str, Any]], None],
        log: Callable[[str, str], None],
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.on_event = on_event
        self.log = log
        self.process: Optional[subprocess.Popen[str]] = None
        self._lock = threading.RLock()
        self._reader: Optional[threading.Thread] = None
        self._stderr_reader: Optional[threading.Thread] = None
        self.session_dir: Optional[Path] = None
        self.last_status = "STOPPED"

    @property
    def running(self) -> bool:
        with self._lock:
            return self.process is not None and self.process.poll() is None

    def start(self, *, resume_state: Optional[dict[str, Any]] = None) -> Optional[subprocess.Popen[str]]:
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                return self.process

            command = self._resolve_command()
            session_dir = (
                self.repo_root
                / "build"
                / "native-observation"
                / f"session-{uuid.uuid4().hex}"
            )
            session_dir.mkdir(parents=True, exist_ok=True)
            self.session_dir = session_dir
            if resume_state is not None:
                (session_dir / "resume-state.json").write_text(
                    json.dumps(resume_state, ensure_ascii=False), encoding="utf-8"
                )
            command.extend(
                [
                    "--mode",
                    "live",
                    "--repo",
                    str(self.repo_root),
                    "--python",
                    self._python_executable(),
                    "--engine",
                    str(self.repo_root / "architecture" / "v2" / "host" / "engine_v22" / "nte_engine_v22.py"),
                    "--work-dir",
                    str(session_dir),
                    "--spec-image",
                    "htgame.exe",
                    "--spec-class",
                    "UnrealWindow",
                ]
            )
            self.log("STARTUP:NATIVE", f"starting native observation host: {' '.join(command)}")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            try:
                child = subprocess.Popen(
                    command,
                    cwd=str(self.repo_root),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=flags,
                )
            except Exception as exc:
                self.log("STARTUP:NATIVE", f"native observation start failed: {type(exc).__name__}: {exc}")
                self.last_status = "ERROR"
                return None

            self.process = child
            self.last_status = "STARTING"
            self._reader = threading.Thread(
                target=self._read_stdout,
                args=(child,),
                name="native-observation-output",
                daemon=True,
            )
            self._stderr_reader = threading.Thread(
                target=self._read_stderr,
                args=(child,),
                name="native-observation-errors",
                daemon=True,
            )
            self._reader.start()
            self._stderr_reader.start()
            return child

    def stop(self, timeout: float = 3.0) -> None:
        with self._lock:
            child = self.process
        if child is None:
            return
        try:
            self.send_control({"type": "native_stop"})
        except Exception:
            pass
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                child.terminate()
                child.wait(timeout=1.0)
            except Exception:
                try:
                    child.kill()
                except Exception:
                    pass
        with self._lock:
            if self.process is child:
                self.process = None
                self.last_status = "STOPPED"

    def send_control(self, message: dict[str, Any]) -> bool:
        """Send one JSON control envelope to the single native Host.

        The GUI never sends protocol messages directly.  This small stdin
        channel is only the Host-control boundary; the Host still owns the
        Named Pipe/MMF session and sends the actual command through the frozen
        SupervisorSession protocol.
        """
        if not isinstance(message, dict):
            return False
        with self._lock:
            child = self.process
            if child is None or child.poll() is not None or child.stdin is None:
                return False
            try:
                child.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
                child.stdin.flush()
                return True
            except Exception as exc:
                self.log("STARTUP:NATIVE", f"native control send failed: {type(exc).__name__}: {exc}")
                return False

    def _read_stdout(self, child: subprocess.Popen[str]) -> None:
        try:
            if child.stdout is None:
                return
            for raw in child.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    self.log("STARTUP:NATIVE", f"ignored non-json native output: {line[:300]}")
                    continue
                if not isinstance(event, dict) or event.get("type") != "native_observation":
                    continue
                status = str(event.get("status") or "").upper()
                if status != "FRAME":
                    self._record_status_event(event)
                    self.log(
                        "OBSERVATION:NATIVE",
                        json.dumps(event, ensure_ascii=False, separators=(",", ":"))[:4000],
                    )
                else:
                    # Preserve the actual handoff, not just engine counters.
                    # The session is isolated under build/; no formal history.
                    self._record_frame_event(event)
                self.last_status = str(event.get("status") or self.last_status)
                try:
                    self.on_event(event)
                except Exception as exc:
                    self.log("STARTUP:NATIVE", f"native event callback failed: {type(exc).__name__}: {exc}")
        finally:
            code = child.poll()
            with self._lock:
                if self.process is child:
                    self.process = None
            if code not in (None, 0) and self.last_status not in {"PAUSED", "STOPPED"}:
                self.last_status = "ERROR"
                try:
                    self.on_event(
                        {
                            "type": "native_observation",
                            "schemaVersion": "native-observation-v1",
                            "status": "ERROR",
                            "sourceKind": "native_wgc",
                            "reason": f"host-exited:{code}",
                            "inputActions": False,
                            "formalHistoryWriter": False,
                        }
                    )
                except Exception:
                    pass

    def _record_frame_event(self, event: dict[str, Any]) -> None:
        if self.session_dir is None:
            return
        try:
            with (self.session_dir / "ui-frame-events.jsonl").open(
                "a", encoding="utf-8", newline="\n"
            ) as stream:
                match = event.get("currentMatch") or {}
                summary = {
                    "stage": "bridge-received",
                    "observationSessionId": event.get("observationSessionId"),
                    "frame": event.get("frame"),
                    "matchId": match.get("id"),
                    "factsRevision": match.get("factsRevision"),
                    "q": match.get("q"),
                    "historicalBids": match.get("historicalBids"),
                }
                stream.write(json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n")
            (self.session_dir / "ui-last-frame.json").write_text(
                json.dumps(event, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:
            self.log("OBSERVATION:NATIVE", f"frame evidence write failed: {exc}")

    def _record_status_event(self, event: dict[str, Any]) -> None:
        """Keep a bounded status/error trail beside the isolated session.

        FRAME payloads already carry the selected raw frame and engine state;
        status lines are the important evidence when startup or a safety fence
        fails before the Host creates its protocol trace.
        """
        session_dir = self.session_dir
        if session_dir is None:
            return
        try:
            path = session_dir / "host-status.jsonl"
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception as exc:
            self.log("OBSERVATION:NATIVE", f"status evidence write failed: {type(exc).__name__}: {exc}")

    def _read_stderr(self, child: subprocess.Popen[str]) -> None:
        if child.stderr is None:
            return
        for raw in child.stderr:
            line = raw.strip()
            if line:
                self.log("STARTUP:NATIVE", line[:1000])

    def _python_executable(self) -> str:
        configured = str(os.environ.get("NTE_PYTHON_EXE") or "").strip()
        if configured and Path(configured).is_file():
            return configured
        return sys.executable

    def _resolve_command(self) -> list[str]:
        configured = str(os.environ.get("NTE_NATIVE_HOST_EXE") or "").strip()
        candidates = [
            Path(configured) if configured else None,
            self.repo_root / "build" / "native-observation" / "WgcLiveHarness.exe",
            self.repo_root / "architecture" / "v2" / "host" / "wgc_live_harness" / "bin" / "Release" / "net8.0-windows10.0.19041.0" / "WgcLiveHarness.exe",
            self.repo_root / "architecture" / "v2" / "host" / "wgc_live_harness" / "bin" / "Debug" / "net8.0-windows10.0.19041.0" / "WgcLiveHarness.exe",
        ]
        for candidate in candidates:
            if candidate is not None and candidate.is_file():
                return [str(candidate)]

        dotnet = shutil.which("dotnet") or "dotnet"
        project = self.repo_root / "architecture" / "v2" / "host" / "wgc_live_harness" / "WgcLiveHarness.csproj"
        return [dotnet, "run", "--project", str(project), "--no-restore", "--"]
