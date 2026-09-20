"""Measures the R1 isolation and identity behaviour, emitting real numbers.

The acceptance suite asserts bounds; this script records the underlying figures so
an external reviewer can see the actual margins instead of trusting a boolean. It
drives the real harness process through the same seams the tests use.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"D:\yihuanpaimai-v2-2a")
OUT = Path(os.environ.get("V2_2A_EVIDENCE_OUT", str(REPO / "build" / "v2-2a-r2" / "evidence")))
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

    def wait_for_quiet_raw_queue(self, timeout=180.0):
        """Wait for an empty queue and two stable processed-event observations."""
        deadline = time.monotonic() + timeout
        previous_processed = None
        stable_reads = 0
        latest = {}
        while time.monotonic() < deadline:
            latest = self.monitor_cmd("statusprobe", timeout=60.0)
            processed = latest.get("processedEvents")
            if (latest.get("queueCount") == 0
                    and not latest.get("stateGateHeld", False)
                    and not latest.get("workerBusy", False)
                    and latest.get("rawIngestionInFlight", 0) == 0
                    and processed == previous_processed):
                stable_reads += 1
                if stable_reads >= 2:
                    return latest
            else:
                stable_reads = 0
            previous_processed = processed
            time.sleep(0.5)
        raise RuntimeError(f"raw queue did not reach a stable empty baseline: {latest}")

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


class MeasurementFailure(RuntimeError):
    """A failed measurement precondition or assertion, not a usable data point."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MeasurementFailure(message)


def command_result(payload: dict, label: str) -> dict:
    require(bool(payload) and payload.get("phase") == "cmd",
            f"{label} did not return a command result: {payload}")
    return payload


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
    require(session.ready is not None and session.ready.get("phase") == "monitoring",
            f"monitor did not become ready: {session.ready}")
    require(session.serve_ready is not None and session.serve_ready.get("phase") == "ready",
            f"serve harness did not become ready: {session.serve_ready}")
    state_hold_active = False
    raw_hold_active = False
    payload = None
    try:
        command_result(session.cmd("create 0", timeout=40), "create")
        foreground_applied = False
        for _ in range(10):
            if session.cmd("fg 0", timeout=40).get("tookEffect"):
                foreground_applied = True
                break
            time.sleep(0.35)
        require(foreground_applied, "controlled target never became foreground")

        # ---------------- B: confirmed raw-lock hold, independent producer, release. -
        # Run this before the Direction-A load so the exact-N baseline cannot be
        # contaminated by the deliberately slow state-path samples below.
        # `holdraw` is synchronous and returns after its lock is released. The async
        # holder/producer seams make the ordering observable instead of asserting a
        # false hold across two sequential commands.
        suppressed = command_result(session.monitor_cmd("suppress 1", timeout=30),
                                     "suppress 1")
        require(suppressed.get("suppressed") is True,
                f"Direction-B input suppression was not enabled: {suppressed}")
        probe_before = session.wait_for_quiet_raw_queue()

        pushed = 17
        held = command_result(session.monitor_cmd("holdrawstart 600", timeout=30),
                              "holdrawstart")
        require(held.get("acquired") is True,
                f"Direction-B raw lock was not acquired: {held}")
        raw_hold_active = True
        producer = command_result(session.monitor_cmd(f"rawpushstart {pushed}", timeout=30),
                                   "rawpushstart")
        require(producer.get("started") is True,
                f"Direction-B producer did not start: {producer}")
        require(producer.get("completed") is False,
                f"Direction-B producer completed before the release: {producer}")
        probe_during = command_result(session.monitor_cmd("statusprobe"), "statusprobe during raw hold")
        require(probe_during.get("processedEvents") == probe_before.get("processedEvents"),
                f"processed count changed while raw lock was held: {probe_before} -> {probe_during}")
        released = command_result(session.monitor_cmd("releaseraw", timeout=30), "releaseraw")
        raw_hold_active = False
        require(released.get("released") is True and released.get("producerCompleted") is True,
                f"Direction-B producer did not complete after release: {released}")

        target = probe_before.get("processedEvents", 0) + pushed
        deadline = time.monotonic() + 10.0
        probe_after = command_result(session.monitor_cmd("statusprobe"), "statusprobe after release")
        while (probe_after.get("processedEvents", 0) < target
               and time.monotonic() < deadline):
            time.sleep(0.25)
            probe_after = command_result(session.monitor_cmd("statusprobe"),
                                         "statusprobe after release")
        require(probe_after.get("processedEvents") == target,
                f"Direction-B processed delta was not exactly N: before={probe_before}, "
                f"after={probe_after}, N={pushed}")

        quiet_start = time.monotonic()
        time.sleep(1.2)
        probe_quiet = command_result(session.monitor_cmd("statusprobe"), "statusprobe quiet")
        quiet_seconds = time.monotonic() - quiet_start
        require(probe_quiet.get("processedEvents") == probe_after.get("processedEvents"),
                f"Direction-B quiet interval grew from a stale batch: after={probe_after}, "
                f"quiet={probe_quiet}")
        require(probe_quiet.get("queueCount") == 0,
                f"Direction-B queue was not empty in the quiet interval: {probe_quiet}")

        # ---------------- A: state lock VERIFIABLY held, then ingest. ----------------
        # Direction-B intentionally suppresses the real callback path. Restore it before
        # Direction-A; otherwise `inject` returns timing for a callback that discarded its
        # input before it reached RawEventQueue.
        restored = command_result(session.monitor_cmd("suppress 0", timeout=30), "suppress 0")
        require(restored.get("suppressed") is False,
                f"Direction-A real callback path was not restored: {restored}")

        hold_state = command_result(session.monitor_cmd("holdstate 4000", timeout=30),
                                    "holdstate")
        require(hold_state.get("acquired") is True and hold_state.get("stateGateHeld") is True,
                f"Direction-A state lock was not verified: {hold_state}")
        state_hold_active = True
        samples = []
        for _ in range(5):
            t0 = time.monotonic()
            before_a = command_result(session.monitor_cmd("statusprobe"),
                                      "statusprobe before Direction-A inject")
            result = command_result(session.monitor_cmd(f"inject {injections}"),
                                    "inject")
            after_a = command_result(session.monitor_cmd("statusprobe"),
                                     "statusprobe after Direction-A inject")
            wall_ms = (time.monotonic() - t0) * 1000.0
            raw_enqueued_delta = result.get("rawEnqueuedCountDelta")
            status_raw_enqueued_delta = (
                after_a.get("rawEnqueuedCount", 0) - before_a.get("rawEnqueuedCount", 0))
            enqueue_valid = (
                isinstance(raw_enqueued_delta, (int, float))
                and raw_enqueued_delta >= injections
                and status_raw_enqueued_delta >= injections
            )
            require(enqueue_valid,
                    "Direction-A inject did not produce the requested real queue enqueues: "
                    f"inject={result}, before={before_a}, after={after_a}")
            samples.append({"totalUs": result.get("totalUs"),
                            "perEventUs": result.get("perEventUs"),
                            "wallMs": round(wall_ms, 3),
                            "requestedCount": injections,
                            "rawEnqueuedCountBefore": result.get("rawEnqueuedCountBefore"),
                            "rawEnqueuedCountAfter": result.get("rawEnqueuedCountAfter"),
                            "rawEnqueuedCountDelta": raw_enqueued_delta,
                            "statusRawEnqueuedCountBefore": before_a.get("rawEnqueuedCount"),
                            "statusRawEnqueuedCountAfter": after_a.get("rawEnqueuedCount"),
                            "statusRawEnqueuedCountDelta": status_raw_enqueued_delta,
                            "enqueueValid": enqueue_valid})
        released_state = command_result(session.monitor_cmd("releasestate", timeout=30),
                                        "releasestate")
        state_hold_active = False
        require(released_state.get("released") is True,
                f"Direction-A state lock was not released: {released_state}")

        payload = session.stop()
    finally:
        if raw_hold_active:
            try:
                session.monitor_cmd("releaseraw", timeout=30)
            except Exception:
                pass
        if state_hold_active:
            try:
                session.monitor_cmd("releasestate", timeout=30)
            except Exception:
                pass
        if payload is None:
            try:
                payload = session.stop()
            except Exception:
                pass
        session.close()

    per_event = [s["perEventUs"] for s in samples if s["perEventUs"] is not None]
    require(len(per_event) == 5, f"Direction-A did not return five timing samples: {samples}")
    require(payload is not None and "counters" in payload,
            f"monitor did not return a final report: {payload}")
    shutdown_pass = (
        payload.get("noResidualCallback") is True
        and payload.get("hookInstalledAfterDispose") is False
        and payload.get("counters", {}).get("droppedEvents") == 0
    )
    require(shutdown_pass, f"callback measurement shutdown assertions failed: {payload}")
    direction_a_pass = bool(hold_state.get("acquired")) and all(
        sample.get("enqueueValid") is True for sample in samples)
    direction_b_pass = (
        bool(held.get("acquired"))
        and bool(producer.get("started"))
        and producer.get("completed") is False
        and bool(released.get("producerCompleted"))
        and probe_after.get("processedEvents") - probe_before.get("processedEvents") == pushed
        and probe_quiet.get("processedEvents") == probe_after.get("processedEvents")
        and probe_quiet.get("queueCount") == 0
    )
    require(direction_a_pass and direction_b_pass,
            f"callback measurement assertions failed: A={direction_a_pass}, "
            f"B={direction_b_pass}")
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
            "suppressionRestoredBeforeMeasurement": restored.get("suppressed") is False,
            "enqueueValidity": [s["enqueueValid"] for s in samples],
            "rawEnqueueDeltas": [s["rawEnqueuedCountDelta"] for s in samples],
            "rawEnqueueDeltaMin": min(s["rawEnqueuedCountDelta"] for s in samples),
            "rawEnqueueDeltaMax": max(s["rawEnqueuedCountDelta"] for s in samples),
            "pass": direction_a_pass,
            "stateLockHoldUpperBoundUs": 4_000_000,
            "serialisationWouldShowAs": ">= 4,000,000 us per event (the full state hold)",
        },
        "directionB": {
            "method": "real input is suppressed until the old queue is quiet; a known N is "
                      "produced on an independent thread after the raw lock reports acquired; "
                      "the producer is allowed to block in enqueue; a separate release signal "
                      "unblocks it; the exact processed delta and a second quiet interval are "
                      "measured.",
            "knownN": pushed,
            "realInputSuppressed": True,
            "baselineStable": True,
            "holdRawAcquired": bool(held.get("acquired")),
            "holdRawRequestedMs": held.get("requestedMs"),
            "queueCountBeforeProducer": held.get("queueCount"),
            "producerStarted": bool(producer.get("started")),
            "producerCompletedBeforeRelease": bool(producer.get("completed")),
            "processedEventsDuringHold": probe_during.get("processedEvents"),
            "queueCountDuringHold": probe_during.get("queueCount"),
            "releaseProducerCompleted": bool(released.get("producerCompleted")),
            "queueCountAfterReleaseCommand": released.get("queueCount"),
            "processedEventsBeforeRelease": probe_before.get("processedEvents"),
            "processedEventsAfterRelease": probe_after.get("processedEvents"),
            "processedDelta": (probe_after.get("processedEvents", 0)
                               - probe_before.get("processedEvents", 0)),
            "processedDeltaExactlyN": (probe_after.get("processedEvents", 0)
                                       - probe_before.get("processedEvents", 0) == pushed),
            "secondQuietIntervalSeconds": round(quiet_seconds, 3),
            "processedEventsAfterQuiet": probe_quiet.get("processedEvents"),
            "quietIntervalDelta": (probe_quiet.get("processedEvents", 0)
                                    - probe_after.get("processedEvents", 0)),
            "quietIntervalDeltaZero": (probe_quiet.get("processedEvents", 0)
                                        == probe_after.get("processedEvents", 0)),
            "queueCountAfterQuiet": probe_quiet.get("queueCount"),
            "pass": direction_b_pass,
        },
        "shutdown": {
            "noResidualCallback": payload["noResidualCallback"],
            "hookInstalledAfterDispose": payload["hookInstalledAfterDispose"],
            "disposeElapsedUs": payload["disposeElapsedUs"],
            "droppedEvents": payload["counters"]["droppedEvents"],
            "pass": shutdown_pass,
        },
        "assertions": {
            "buildAndHarnessReady": True,
            "directionARealCallbackRestored": restored.get("suppressed") is False,
            "directionAStateLockHeld": bool(hold_state.get("acquired")),
            "directionAEverySampleEnqueued": direction_a_pass,
            "directionBExactKnownDelta": direction_b_pass,
            "directionBQuietDeltaZero": probe_quiet.get("processedEvents") == probe_after.get("processedEvents"),
            "shutdownClean": shutdown_pass,
        },
        "measurementPass": direction_a_pass and direction_b_pass and shutdown_pass,
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


def measure_raw_queue_drain(work: Path) -> dict:
    """Runs the direct RawEventQueue regression probe and preserves its measurements."""
    sys.path.insert(0, str(REPO / "tests"))
    from test_v2_2a_window_focus_monitor import LIB_PROJECT, RAW_QUEUE_PROBE_SOURCE

    work.mkdir(parents=True, exist_ok=True)
    csproj = work / "RawEventQueueProbe.csproj"
    csproj.write_text(
        "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
        "  <PropertyGroup>\n"
        "    <OutputType>Exe</OutputType>\n"
        "    <TargetFramework>net8.0</TargetFramework>\n"
        "    <Nullable>enable</Nullable>\n"
        "    <ImplicitUsings>enable</ImplicitUsings>\n"
        "    <AssemblyName>RawEventQueueProbe</AssemblyName>\n"
        "    <RootNamespace>RawEventQueueProbe</RootNamespace>\n"
        "    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>\n"
        "  </PropertyGroup>\n"
        "  <ItemGroup>\n"
        "    <Compile Include=\"Program.cs\" />\n"
        "    <ProjectReference Include=\"" + str(LIB_PROJECT) + "\" />\n"
        "  </ItemGroup>\n"
        "</Project>\n", encoding="utf-8")
    (work / "Program.cs").write_text(RAW_QUEUE_PROBE_SOURCE, encoding="utf-8")

    command = ["dotnet", "run", "--project", str(csproj), "-c", "Release", "--nologo"]
    result = subprocess.run(command, cwd=str(REPO), env=build_env(), capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=900)
    probe = {"verdict": "no-json"}
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                probe = json.loads(line)
            except json.JSONDecodeError:
                continue
            break

    return {
        "method": "direct project-reference probe against the real RawEventQueue class",
        "command": command,
        "exitCode": result.returncode,
        "probe": probe,
        "stdoutTail": result.stdout[-2000:],
        "stderrTail": result.stderr[-2000:],
        "pass": result.returncode == 0 and probe.get("verdict") == "ok",
    }


if __name__ == "__main__":
    sys.path.insert(0, str(REPO / "tools" / "v2"))
    from dotnet_env import build_env
    build = subprocess.run(["dotnet", "build",
                            "architecture/v2/host/window_monitor_harness/WindowMonitorHarness.csproj",
                           "-c", "Release", "--nologo", "-v", "q"],
                           cwd=str(REPO), env=build_env(), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    print("build exit:", build.returncode)
    if build.returncode != 0:
        print(build.stdout)
        print(build.stderr, file=sys.stderr)
        raise SystemExit(build.returncode or 1)

    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(os.environ.get("V2_2A_MEASURE_WORK",
                              str(REPO / "build" / "v2-2a-r2" / "measure_work")))

    isolation = measure_isolation(work / "isolation", delay_ms=120, injections=400)
    (OUT / "callback_isolation_measured.json").write_text(
        json.dumps({"schemaVersion": "v2.2a.callback.isolation.measured.v2", **isolation},
                   indent=2) + "\n", encoding="utf-8")
    print(json.dumps(isolation, indent=2))
    if not isolation.get("measurementPass"):
        raise SystemExit(1)

    overflow = measure_overflow_policy(work / "overflow")
    (OUT / "event_queue_overflow_measured.json").write_text(
        json.dumps({"schemaVersion": "v2.2a.event.queue.overflow.measured.v1", **overflow},
                   indent=2) + "\n", encoding="utf-8")
    print(json.dumps(overflow, indent=2))

    if os.environ.get("V2_2A_R4_MINIMAL") != "1":
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

    raw_queue = measure_raw_queue_drain(work / "raw_queue")
    (OUT / "raw_queue_drain_measured.json").write_text(
        json.dumps({"schemaVersion": "v2.2a.raw.event.queue.drain.measured.v1", **raw_queue},
                   indent=2) + "\n", encoding="utf-8")
    print(json.dumps(raw_queue, indent=2))
