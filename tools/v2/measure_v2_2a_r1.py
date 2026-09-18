"""Measures the R1 isolation and identity behaviour, emitting real numbers.

The acceptance suite asserts bounds; this script records the underlying figures so
an external reviewer can see the actual margins instead of trusting a boolean. It
drives the real harness process through the same seams the tests use.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"D:\yihuanpaimai-v2-2a")
OUT = REPO / "build" / "v2-2a-r1" / "evidence"
HARNESS_EXE = REPO / "architecture" / "v2" / "host" / "window_monitor_harness" / "bin" / "Release" / "net8.0" / "WindowMonitorHarness.exe"
TARGET_CLASS = "NteV22ControlledWindow"
OTHER_CLASS = "NteV22ControlledWindowOther"
HARNESS_IMAGE = "WindowMonitorHarness.exe"


class Session:
    def __init__(self, work: Path, spec_image: str, spec_class: str, identity_delay_ms: int = 0):
        work.mkdir(parents=True, exist_ok=True)
        args = [str(HARNESS_EXE), "--mode", "monitor",
                "--spec-image", spec_image, "--spec-class", spec_class,
                "--duration-ms", "120000", "--out", str(work / "monitor.json")]
        if identity_delay_ms:
            args += ["--identity-delay-ms", str(identity_delay_ms)]
        self.monitor = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        text=True, encoding="utf-8")
        self.ready = self._read(self.monitor, "monitoring", 40)
        self.serve = subprocess.Popen(
            [str(HARNESS_EXE), "--mode", "serve", "--class", TARGET_CLASS,
             "--other-class", OTHER_CLASS, "--title-prefix", "nte", "--count", "1",
             "--grab-foreground"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
        self.serve_ready = self._read(self.serve, "ready", 40)

    @staticmethod
    def _read(proc, phase, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            line = proc.stdout.readline()
            if not line:
                return None
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("phase") == phase:
                return payload
        return None

    def cmd(self, text, timeout=30.0):
        expected = text.split(" ", 1)[0]
        self.serve.stdin.write(text + "\n")
        self.serve.stdin.flush()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            line = self.serve.stdout.readline()
            if not line:
                return {}
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("phase") == "cmd" and payload.get("cmd") == expected:
                return payload
        return {}

    def monitor_cmd(self, text, timeout=60.0):
        expected = text.split(" ", 1)[0]
        self.monitor.stdin.write(text + "\n")
        self.monitor.stdin.flush()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            line = self.monitor.stdout.readline()
            if not line:
                return {}
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("phase") == "cmd" and payload.get("cmd") == expected:
                return payload
        return {}

    def stop(self):
        self.monitor.stdin.write("stop\n")
        self.monitor.stdin.flush()
        self._read(self.monitor, "disposed", 60)
        for _ in range(6):
            self.cmd("createother 90")
            self.cmd("destroy 90")
        time.sleep(0.6)
        self.monitor.stdin.write("report\n")
        self.monitor.stdin.flush()
        rest = self.monitor.stdout.read()
        self.monitor.wait(timeout=40)
        return json.loads(rest[rest.index("{"):])

    def close(self):
        for proc in (self.serve, self.monitor):
            try:
                if proc.poll() is None:
                    proc.stdin.write("exit\n")
                    proc.stdin.flush()
                    proc.wait(timeout=8)
            except Exception:
                proc.kill()


def measure_isolation(work: Path, delay_ms: int, injections: int) -> dict:
    session = Session(work, HARNESS_IMAGE, TARGET_CLASS, identity_delay_ms=delay_ms)
    try:
        session.cmd("create 0", timeout=40)
        session.cmd("fg 0")
        session.cmd("createother 1", timeout=40)
        session.cmd("fg 1", timeout=40)

        samples = []
        for _ in range(5):
            t0 = time.monotonic()
            result = session.monitor_cmd(f"inject {injections}")
            wall_ms = (time.monotonic() - t0) * 1000.0
            samples.append({"totalUs": result.get("totalUs"),
                            "perEventUs": result.get("perEventUs"),
                            "wallMs": round(wall_ms, 3)})

        probe_before = session.monitor_cmd("identityprobe")
        held = session.monitor_cmd("holdraw 300")
        time.sleep(0.5)
        probe_after = session.monitor_cmd("identityprobe")

        payload = session.stop()
    finally:
        session.close()

    per_event = [s["perEventUs"] for s in samples if s["perEventUs"] is not None]
    return {
        "identityDelayMs": delay_ms,
        "injectionsPerSample": injections,
        "ingestionSamples": samples,
        "perEventUsMin": min(per_event) if per_event else None,
        "perEventUsMax": max(per_event) if per_event else None,
        "stateLockHoldUpperBoundUs": delay_ms * 1000,
        "serialisationWouldShowAs": f">= {delay_ms * 1000} us per event",
        "holdRawRequestedMs": held.get("requestedMs"),
        "holdRawActualUs": held.get("actualUs"),
        "workerProgressDuringHold": {
            "before": probe_before.get("processedEvents"),
            "after": probe_after.get("processedEvents"),
        },
        "shutdown": {
            "noResidualCallback": payload["noResidualCallback"],
            "hookInstalledAfterDispose": payload["hookInstalledAfterDispose"],
            "disposeElapsedUs": payload["disposeElapsedUs"],
            "droppedEvents": payload["counters"]["droppedEvents"],
        },
    }


def measure_identity_boundaries(work: Path) -> dict:
    session = Session(work, HARNESS_IMAGE, TARGET_CLASS)
    observed = {}
    try:
        # Mirror the acceptance fixture's sequence exactly: the destroy must be
        # observed by the hook for the loss/boundary path to fire, so foreground is
        # moved deliberately around each step rather than assumed.
        for attempt in range(6):
            if session.cmd("fg 0", timeout=40).get("tookEffect"):
                break
            time.sleep(0.35)
        session.cmd("createother 1", timeout=40)
        for attempt in range(6):
            if session.cmd("fg 1", timeout=40).get("tookEffect"):
                break
            time.sleep(0.35)
        for attempt in range(6):
            if session.cmd("fg 0", timeout=40).get("tookEffect"):
                break
            time.sleep(0.35)
        time.sleep(0.5)

        initial_hwnd = int((session.serve_ready.get("windows") or {}).get("0", 0))
        observed["beforeLoss"] = session.monitor_cmd("identityprobe")

        session.cmd("destroy 0", timeout=40)
        time.sleep(1.0)
        observed["afterDestroy"] = session.monitor_cmd("identityprobe")

        recreate = session.cmd("recreate 0", timeout=40)
        time.sleep(1.0)
        for attempt in range(6):
            if session.cmd("fg 0", timeout=40).get("tookEffect"):
                break
            time.sleep(0.35)
        time.sleep(0.5)
        observed["afterReacquire"] = session.monitor_cmd("identityprobe")

        payload = session.stop()
    finally:
        session.close()

    gen_before = observed["beforeLoss"].get("cacheGeneration", 0)
    gen_after = observed["afterReacquire"].get("cacheGeneration", 0)
    return {
        "initialHwnd": initial_hwnd,
        "recreatedHwnd": int(recreate.get("hwnd") or 0),
        "identityProbes": {
            "beforeLoss": observed["beforeLoss"],
            "afterDestroy": observed["afterDestroy"],
            "afterReacquire": observed["afterReacquire"],
        },
        "cacheGenerationDelta": gen_after - gen_before,
        "imageNameResolutions": observed["afterReacquire"].get("imageNameResolutions"),
        "eventKinds": [e["kind"] for e in payload["events"]],
        "staleRejectionReasons": [e["reason"] for e in payload["events"]
                                  if e["kind"] == "StaleHandleRejected"],
        "acquiredIdentity": next(({"image": e["targetImageName"], "class": e["targetClassName"],
                                   "hwnd": e["targetHwnd"]}
                                  for e in payload["events"] if e["kind"] == "TargetAcquired"), None),
        "reacquiredIdentity": next(({"image": e["targetImageName"], "class": e["targetClassName"],
                                     "hwnd": e["targetHwnd"]}
                                    for e in payload["events"] if e["kind"] == "TargetReacquired"), None),
        "finalSnapshot": payload["finalSnapshot"],
    }


if __name__ == "__main__":
    sys.path.insert(0, str(REPO / "tools" / "v2"))
    from dotnet_env import build_env
    build = subprocess.run(["dotnet", "build",
                            "architecture/v2/host/window_monitor_harness/WindowMonitorHarness.csproj",
                            "-c", "Release", "--nologo", "-v", "q"],
                           cwd=str(REPO), env=build_env(), capture_output=True, text=True)
    print("build exit:", build.returncode)

    OUT.mkdir(parents=True, exist_ok=True)
    work = REPO / "build" / "v2-2a-r1" / "measure_work"

    isolation = measure_isolation(work / "isolation", delay_ms=120, injections=400)
    (OUT / "callback_isolation_measured.json").write_text(
        json.dumps({"schemaVersion": "v2.2a.callback.isolation.measured.v1", **isolation},
                   indent=2) + "\n", encoding="utf-8")
    print(json.dumps(isolation, indent=2))

    identity = measure_identity_boundaries(work / "identity")
    (OUT / "identity_boundaries_measured.json").write_text(
        json.dumps({"schemaVersion": "v2.2a.identity.boundaries.measured.v1", **identity},
                   indent=2) + "\n", encoding="utf-8")
    print(json.dumps(identity, indent=2))
