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
OUT = REPO / "build" / "v2-2a-r2" / "evidence"
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
    """Measures lock isolation with the CORRECTED claims.

    The previous version of this measurement explicitly built `workerProgressDuringHold`
    and compared `processedEvents` before/after a `holdraw`, which was presented as proof
    that the worker "still progresses". That claim is wrong twice over: the worker
    legitimately needs the raw lock in order to drain, so waiting there is correct
    behaviour; and `before == after` satisfied the comparison while proving nothing
    (measured 425 -> 425). What is measured now is what actually matters:

      * direction A with a TEST-CONTROLLED state-lock hold (the hold is proven, not
        inferred from a widened identity path), reporting ingestion latency under it;
      * direction B: work queued while the raw lock is held must be delivered AFTER the
        release, so processing genuinely RESUMES (a strict increase, asserted by the test);
      * teardown: Dispose completes and leaks no callback.
    """
    session = Session(work, HARNESS_IMAGE, TARGET_CLASS, identity_delay_ms=delay_ms)
    try:
        session.cmd("create 0", timeout=40)
        for _ in range(10):
            if session.cmd("fg 0", timeout=40).get("tookEffect"):
                break
            time.sleep(0.35)

        # ---------------- A: state lock VERIFIABLY held, then ingest. ----------------
        hold_state = session.monitor_cmd("holdstate 4000", timeout=30)
        samples = []
        for _ in range(5):
            t0 = time.monotonic()
            result = session.monitor_cmd(f"inject {injections}")
            wall_ms = (time.monotonic() - t0) * 1000.0
            samples.append({"totalUs": result.get("totalUs"),
                            "perEventUs": result.get("perEventUs"),
                            "wallMs": round(wall_ms, 3)})
        session.monitor_cmd("releasestate", timeout=30)

        # ---------------- B: queue work under the raw hold, then resume. --------------
        probe_before = session.monitor_cmd("statusprobe")
        held = session.monitor_cmd("holdraw 600", timeout=30)
        session.monitor_cmd("rawpush 400", timeout=30)
        time.sleep(1.2)

        deadline = time.monotonic() + 10.0
        probe_after = session.monitor_cmd("statusprobe")
        while (probe_after.get("processedEvents", 0) <= probe_before.get("processedEvents", 0)
               and time.monotonic() < deadline):
            time.sleep(0.25)
            probe_after = session.monitor_cmd("statusprobe")

        payload = session.stop()
    finally:
        session.close()

    per_event = [s["perEventUs"] for s in samples if s["perEventUs"] is not None]
    return {
        "identityDelayMs": delay_ms,
        "injectionsPerSample": injections,
        "directionA": {
            "method": "the harness takes the STATE lock from a thread the test controls and "
                      "reports it acquired it; ingestion then runs while the lock is provably "
                      "held. This replaces the previous inference from a widened identity path, "
                      "which could not distinguish 'not serialised' from 'state path was idle'.",
            "stateLockHeldVerified": bool(hold_state.get("acquired")),
            "stateLockHoldRequestedMs": hold_state.get("requestedMs"),
            "ingestionSamples": samples,
            "perEventUsMin": min(per_event) if per_event else None,
            "perEventUsMax": max(per_event) if per_event else None,
            "stateLockHoldUpperBoundUs": 4_000_000,
            "serialisationWouldShowAs": ">= 4,000,000 us per event (the full state hold)",
        },
        "directionB": {
            "method": "the raw lock is held, work is queued during the hold, and processing "
                      "must genuinely RESUME after the release.",
            "previousDefect": "the old check was `processedEvents after >= before`, which "
                              "permits zero progress; it was measured at 425 -> 425 and "
                              "therefore proved nothing. It also claimed progress WHILE the "
                              "raw lock was held, which is not a valid property: the worker "
                              "needs that lock to drain, so waiting there is correct.",
            "holdRawRequestedMs": held.get("requestedMs"),
            "holdRawActualUs": held.get("actualUs"),
            "processedEventsBeforeRelease": probe_before.get("processedEvents"),
            "processedEventsAfterRelease": probe_after.get("processedEvents"),
            "resumed": (probe_after.get("processedEvents", 0)
                        > probe_before.get("processedEvents", 0)),
        },
        "shutdown": {
            "noResidualCallback": payload["noResidualCallback"],
            "hookInstalledAfterDispose": payload["hookInstalledAfterDispose"],
            "disposeElapsedUs": payload["disposeElapsedUs"],
            "droppedEvents": payload["counters"]["droppedEvents"],
        },
    }


def measure_overflow_policy(work: Path, capacity: int = 256) -> dict:
    """Measures that one overflow produces ONE recovery decision, not a permanent latch.

    The latched implementation tested the CUMULATIVE `DroppedCount > 0`, so after the
    first drop every worker iteration considered the queue overflowing. With no target
    present, the 200 ms rate limit turned that into a continuous EnumWindows recovery
    loop. The figures below record the quiet-window scan growth, which is the direct
    observable of the defect.
    """
    work.mkdir(parents=True, exist_ok=True)
    args = [str(HARNESS_EXE), "--mode", "monitor",
            "--spec-image", HARNESS_IMAGE, "--spec-class", TARGET_CLASS,
            "--duration-ms", "120000", "--out", str(work / "monitor.json"),
            "--queue-capacity", str(capacity)]
    monitor = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               text=True, encoding="utf-8")

    def mc(text, timeout=60.0):
        expected = text.split(" ", 1)[0]
        monitor.stdin.write(text + "\n")
        monitor.stdin.flush()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            line = monitor.stdout.readline()
            if not line:
                return {}
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("phase") == "cmd" and payload.get("cmd") == expected:
                return payload
        return {}

    try:
        # Wait for readiness, then stop real ingestion so the induced overflow is the only
        # source of drops.
        mc("suppress 1", timeout=40)
        time.sleep(0.6)

        baseline = mc("statusprobe")
        pushed = mc(f"overflow {capacity * 4}", timeout=40)
        time.sleep(1.0)
        after_overflow = mc("statusprobe")

        quiet_start = time.monotonic()
        time.sleep(3.0)
        quiet = mc("statusprobe")
        quiet_seconds = time.monotonic() - quiet_start
    finally:
        try:
            monitor.stdin.write("stop\n")
            monitor.stdin.flush()
            monitor.wait(timeout=30)
        except Exception:
            monitor.kill()

    return {
        "capacity": capacity,
        "baselineDroppedEvents": baseline.get("droppedEvents"),
        "baselineOverflowObservations": baseline.get("overflowObservations"),
        "baselineRecoveryScans": baseline.get("recoveryScans"),
        "dropsInduced": (pushed.get("droppedEvents", 0) or 0) - (baseline.get("droppedEvents", 0) or 0),
        "overflowObservationsAfterBurst": after_overflow.get("overflowObservations"),
        "recoveryScansAtOverflow": after_overflow.get("recoveryScans"),
        "quietWindowSeconds": round(quiet_seconds, 2),
        "recoveryScansAfterQuiet": quiet.get("recoveryScans"),
        "extraRecoveryScansDuringQuiet": ((quiet.get("recoveryScans", 0) or 0)
                                          - (after_overflow.get("recoveryScans", 0) or 0)),
        "extraOverflowObservationsDuringQuiet": ((quiet.get("overflowObservations", 0) or 0)
                                                 - (after_overflow.get("overflowObservations", 0) or 0)),
        "droppedEventsAfterQuiet": quiet.get("droppedEvents"),
        "latchedImpliedScanRatePerSecond": 1000.0 / 200.0,
        "note": "A latched implementation would keep issuing recovery scans at the 200 ms "
                "rate limit (5/s) indefinitely after the single overflow; the measured "
                "extraRecoveryScansDuringQuiet is the direct observable of the fix.",
    }


def measure_identity_authority(work: Path) -> dict:
    """Runs the reader-level same-generation recycle probe and records its verdict.

    This is the measurement behind blocker 1. It does NOT rely on Windows recycling a pid
    on cue: the probe primes the discovery cache, then asks `Revalidate` to check an
    identity whose authority query reports a recycled pid while the cache GENERATION IS
    UNCHANGED (no `LoseTarget`, no `InvalidatePid`). That is exactly the window a
    cache-reading trust path would answer from the dead process's entry.
    """
    sys.path.insert(0, str(REPO / "tests"))
    from test_v2_2a_window_focus_monitor import IDENTITY_PROBE_SOURCE, LIB_PROJECT

    work.mkdir(parents=True, exist_ok=True)
    (work / "IdentityRecycleProbe.csproj").write_text(
        "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
        "  <PropertyGroup>\n"
        "    <OutputType>Exe</OutputType>\n"
        "    <TargetFramework>net8.0</TargetFramework>\n"
        "    <Nullable>enable</Nullable>\n"
        "    <ImplicitUsings>enable</ImplicitUsings>\n"
        "    <AssemblyName>IdentityRecycleProbe</AssemblyName>\n"
        "    <RootNamespace>IdentityRecycleProbe</RootNamespace>\n"
        "    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>\n"
        "  </PropertyGroup>\n"
        "  <ItemGroup>\n"
        "    <Compile Include=\"Program.cs\" />\n"
        "    <ProjectReference Include=\"" + str(LIB_PROJECT) + "\" />\n"
        "  </ItemGroup>\n"
        "</Project>\n", encoding="utf-8")
    (work / "Program.cs").write_text(IDENTITY_PROBE_SOURCE, encoding="utf-8")

    from dotnet_env import build_env
    result = subprocess.run(["dotnet", "run", "--project",
                             str(work / "IdentityRecycleProbe.csproj"),
                             "-c", "Release", "--nologo"],
                            cwd=str(REPO), env=build_env(), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=900)
    probe = {"verdict": "no-json", "stdout": result.stdout[-2000:],
             "stderr": result.stderr[-2000:]}
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                probe = json.loads(line)
            except json.JSONDecodeError:
                continue
            break

    return {
        "method": "reader-level probe: the discovery cache is primed for a real pid, then "
                  "Revalidate is driven with a FreshProcessQuery seam reporting what the "
                  "authority query would return if the pid had been recycled. No LoseTarget and "
                  "no InvalidatePid is performed, so the cache generation does NOT move - this "
                  "is the same-generation window.",
        "probe": probe,
        "rejectedSameImageDifferentInstance": not probe.get("sameImageDifferentInstanceAccepted", True),
        "rejectedDifferentImage": not probe.get("differentImageAccepted", True),
        "rejectedUnprovableInstance": not probe.get("zeroInstanceTokenAccepted", True),
        "acceptedUnchangedIdentity": bool(probe.get("unchangedIdentityAccepted")),
        "generationBefore": probe.get("generationBefore"),
        "generationAfter": probe.get("generationAfter"),
        "generationMoved": probe.get("generationBefore") != probe.get("generationAfter"),
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
    work = REPO / "build" / "v2-2a-r2" / "measure_work"

    isolation = measure_isolation(work / "isolation", delay_ms=120, injections=400)
    (OUT / "callback_isolation_measured.json").write_text(
        json.dumps({"schemaVersion": "v2.2a.callback.isolation.measured.v2", **isolation},
                   indent=2) + "\n", encoding="utf-8")
    print(json.dumps(isolation, indent=2))

    overflow = measure_overflow_policy(work / "overflow")
    (OUT / "event_queue_overflow_measured.json").write_text(
        json.dumps({"schemaVersion": "v2.2a.event.queue.overflow.measured.v1", **overflow},
                   indent=2) + "\n", encoding="utf-8")
    print(json.dumps(overflow, indent=2))

    authority = measure_identity_authority(work / "identity_authority")
    (OUT / "identity_same_generation_measured.json").write_text(
        json.dumps({"schemaVersion": "v2.2a.identity.same.generation.measured.v1", **authority},
                   indent=2) + "\n", encoding="utf-8")
    print(json.dumps(authority, indent=2))

    identity = measure_identity_boundaries(work / "identity")
    (OUT / "identity_boundaries_measured.json").write_text(
        json.dumps({"schemaVersion": "v2.2a.identity.boundaries.measured.v1", **identity},
                   indent=2) + "\n", encoding="utf-8")
    print(json.dumps(identity, indent=2))
