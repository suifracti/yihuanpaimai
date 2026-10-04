"""Bounded, window-only QA. Offline is the default; live requires explicit readiness.

Owns only its newly created worker. No desktop capture, hooks, input, activation,
Engine, SOURCE lease, history or label writes are reachable from this controller.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(__file__).resolve().parent
QA_ROOT = ROOT / "build" / "native_qa"
WORKER = QA_ROOT / "out" / "BoundedWgcQaWorker.dll"
HOST = ROOT / "build" / "native-observation"
WORK_NS = 8_000_000_000
TOTAL_NS = 10_000_000_000
OBSERVATION_WINDOW_MODES = ("foreground", "background-readonly")


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class OwnedJob:
    """A fresh unnamed Job; kill-on-close, without either breakaway flag."""
    def __init__(self):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                          wintypes.DWORD], wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                            wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "IsProcessInJob": ([wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)],
                               wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, restype) in signatures.items():
            fn = getattr(self.api, name)
            fn.argtypes, fn.restype = args, restype
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        try:
            if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits),
                                                    ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            observed = _ExtendedLimits()
            if not self.api.QueryInformationJobObject(self.handle, 9, ctypes.byref(observed),
                                                      ctypes.sizeof(observed), None):
                raise ctypes.WinError(ctypes.get_last_error())
            flags = observed.BasicLimitInformation.LimitFlags
            if not flags & 0x2000 or flags & (0x800 | 0x1000):
                raise RuntimeError("Job is not kill-on-close without breakaway")
        except BaseException:
            self.close()
            raise

    def assign(self, pid: int):
        handle = self.api.OpenProcess(0x0100 | 0x0001 | 0x1000, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.api.AssignProcessToJobObject(self.handle, handle):
                raise ctypes.WinError(ctypes.get_last_error())
            in_job = wintypes.BOOL()
            if not self.api.IsProcessInJob(handle, self.handle, ctypes.byref(in_job)) or not in_job:
                raise RuntimeError("Worker membership in owned Job could not be proven")
        finally:
            self.api.CloseHandle(handle)

    def terminate(self) -> bool:
        return bool(self.handle and self.api.TerminateJobObject(self.handle, 124))

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def exit_within_budget(start_ns: int, observed_exit_ns: int | None) -> bool:
    return observed_exit_ns is not None and start_ns <= observed_exit_ns <= start_ns + TOTAL_NS


def _count(result: dict, name: str) -> int:
    value = result.get(name, 0)
    return len(value) if isinstance(value, list) else int(value or 0)


def run_worker(mode: str, output: Path, target: dict | None = None, *,
               observation_window_mode: str = "foreground") -> dict:
    if observation_window_mode not in OBSERVATION_WINDOW_MODES:
        raise ValueError("Unknown observation window mode")
    output = output.resolve()
    if not output.is_relative_to(QA_ROOT):
        raise ValueError("QA output must remain inside its project build directory")
    output.mkdir(parents=True, exist_ok=False)
    events: list[dict] = []
    messages: queue.Queue = queue.Queue()
    child = None
    job = None
    assigned = False
    go_sent = False
    stop_request_ns = None
    termination_requested_ns = None
    termination_api_succeeded = None
    observed_exit_ns = None
    controller_error = None
    reason = None
    stdout_thread = None
    stderr_thread = None
    # Absolute QPC budgets include Job preparation, process creation and handshake.
    started_ns = time.perf_counter_ns()
    deadline_ns = started_ns + WORK_NS
    total_deadline_ns = started_ns + TOTAL_NS

    def remaining_seconds(until: int) -> float:
        return max(0.0, (until - time.perf_counter_ns()) / 1e9)

    def write_control(message: dict):
        assert child is not None and child.stdin is not None
        child.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        child.stdin.flush()

    def collect_stdout():
        with (output / "child-output.jsonl").open("w", encoding="utf-8") as raw:
            assert child is not None and child.stdout is not None
            while True:
                line = child.stdout.readline(64 * 1024 + 1)
                if not line:
                    break
                observed = time.perf_counter_ns()
                raw.write(line)
                raw.flush()
                if len(line.encode("utf-8")) > 64 * 1024 or not line.endswith("\n"):
                    messages.put(({"kind": "output-error", "reason": "oversized-worker-line"}, observed))
                    break
                try:
                    parsed = json.loads(line)
                    if not isinstance(parsed, dict):
                        raise ValueError("worker event is not an object")
                except (ValueError, TypeError) as exc:
                    parsed = {"kind": "output-error", "reason": str(exc)}
                if mode == "live":
                    if parsed.get("kind") == "phase" and parsed.get("phase") == "go-accepted":
                        print(json.dumps({"kind": "qa-progress", "phase": "started",
                                          "savedAcceptedFrames": 0}, ensure_ascii=False), flush=True)
                    elif parsed.get("kind") == "accepted":
                        print(json.dumps({"kind": "qa-progress", "phase": "original-saved-and-accepted",
                                          "attempt": parsed.get("frame", {}).get("attempt"),
                                          "path": parsed.get("frame", {}).get("path")},
                                         ensure_ascii=False), flush=True)
                messages.put((parsed, observed))

    def collect_stderr():
        assert child is not None and child.stderr is not None
        with (output / "child-stderr.txt").open("w", encoding="utf-8") as raw:
            for line in child.stderr:
                raw.write(line)
                raw.flush()

    def stop_owned(reason_text: str):
        nonlocal stop_request_ns, termination_requested_ns, termination_api_succeeded, reason
        reason = reason_text
        stop_request_ns = time.perf_counter_ns()
        if child is not None:
            try:
                write_control({"command": "STOP"})
            except (OSError, ValueError, AssertionError):
                pass
            termination_requested_ns = time.perf_counter_ns()
            if assigned and job is not None:
                termination_api_succeeded = job.terminate()
            else:
                # No GO has been sent, so an unassigned worker cannot capture.
                try:
                    child.terminate()
                    termination_api_succeeded = True
                except OSError:
                    termination_api_succeeded = False

    try:
        if sys.platform != "win32":
            raise RuntimeError("The bounded QA controller requires Windows")
        if not WORKER.is_file():
            raise RuntimeError("Compile the isolated QA worker first")
        dotnet = shutil.which("dotnet")
        if dotnet is None:
            raise RuntimeError("dotnet runtime was not found")
        job = OwnedJob()
        if time.perf_counter_ns() >= deadline_ns:
            raise TimeoutError("work deadline reached before process creation")
        child = subprocess.Popen(
            [dotnet, str(WORKER)], cwd=str(ROOT), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        job.assign(child.pid)
        assigned = True
        stdout_thread = threading.Thread(target=collect_stdout, daemon=True)
        stderr_thread = threading.Thread(target=collect_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        while time.perf_counter_ns() < deadline_ns:
            try:
                event, observed = messages.get(timeout=min(0.02, remaining_seconds(deadline_ns)))
                events.append(event)
                kind = str(event.get("kind", "")).lower()
                if kind == "output-error":
                    raise RuntimeError(event["reason"])
                if kind == "ready":
                    ready_ns = int(event.get("nowNs", 0))
                    if not started_ns <= ready_ns <= observed:
                        raise RuntimeError("Worker and controller QPC clocks are not comparable")
                    if time.perf_counter_ns() >= deadline_ns:
                        break
                    if go_sent:
                        raise RuntimeError("Duplicate READY")
                    controls = {
                        "command": "GO", "mode": mode, "hostDir": str(HOST),
                        "observationWindowMode": observation_window_mode,
                        "outputDir": str(output), "deadlineNs": deadline_ns,
                        "totalDeadlineNs": total_deadline_ns,
                        **(target or {"hwnd": 0, "pid": 0, "instance": 0}),
                    }
                    write_control(controls)
                    go_sent = True
            except queue.Empty:
                pass
            if child.poll() is not None:
                observed_exit_ns = time.perf_counter_ns()
                reason = "worker-exited"
                break
        if observed_exit_ns is None:
            stop_owned("work-deadline")
            try:
                child.wait(timeout=remaining_seconds(total_deadline_ns))
                observed_exit_ns = time.perf_counter_ns()
            except subprocess.TimeoutExpired:
                reason = "exit-not-confirmed-within-total-deadline"
    except BaseException as exc:
        controller_error = f"{type(exc).__name__}: {exc}"
        if child is not None and child.poll() is None:
            stop_owned("controller-error")
            try:
                child.wait(timeout=remaining_seconds(total_deadline_ns))
                observed_exit_ns = time.perf_counter_ns()
            except subprocess.TimeoutExpired:
                reason = "exit-not-confirmed-within-total-deadline"
        elif child is not None:
            observed_exit_ns = time.perf_counter_ns()
        reason = reason or "controller-error-before-child"
    finally:
        if job is not None:
            job.close()  # Kill-on-close remains an independent final owner fence.
        if child is not None:
            if observed_exit_ns is None and child.poll() is not None:
                # A late observation stays late; it cannot turn a timeout into a pass.
                observed_exit_ns = time.perf_counter_ns()
            if child.stdin is not None:
                try:
                    child.stdin.close()
                except OSError:
                    pass
        for thread in (stdout_thread, stderr_thread):
            if thread is not None:
                thread.join(timeout=0.2)
        while not messages.empty():
            events.append(messages.get_nowait()[0])

    result_path = output / "result.json"
    worker_result = None
    if result_path.is_file():
        try:
            worker_result = json.loads(result_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            controller_error = controller_error or f"Invalid worker result: {exc}"
    event_attempts = max((int(event.get("attempt", 0)) for event in events
                          if str(event.get("kind", "")).lower() == "attempt"), default=0)
    def event_count(kind: str) -> int:
        return sum(str(event.get("kind", "")).lower() == kind for event in events)

    counts = {
        "attempts": max(event_attempts, _count(worker_result or {}, "attempts")),
        "readbacks": max(event_count("readback"), _count(worker_result or {}, "readbacks")),
        "candidateRecords": max(event_count("candidate"), _count(worker_result or {}, "candidateFiles")),
        "acceptedFrames": max(event_count("accepted"), _count(worker_result or {}, "acceptedFrames")),
    }
    files = sorted(str(path.relative_to(output)) for path in output.rglob("*.bmp"))
    counts["candidateFiles"] = len(files)
    # selftest contains separate independent fake cases; each has its own cap.
    if mode == "selftest":
        counts_within_cap = bool(worker_result) and all(
            all(_count(case["actual"]["result"], field) <= 3 for field in
                ("attempts", "readbacks", "candidateFiles", "acceptedFrames"))
            for case in worker_result.get("cases", []))
        for output_name, worker_name in (("attempts", "attempts"), ("readbacks", "readbacks"),
                                         ("candidateRecords", "candidateFiles"),
                                         ("acceptedFrames", "acceptedFrames")):
            counts[output_name] = sum(_count(case["actual"]["result"], worker_name)
                                      for case in (worker_result or {}).get("cases", []))
        fake_files = sorted(str(path.relative_to(output)) for path in output.rglob("*.fake"))
        counts["candidateFiles"] = len(fake_files)
    else:
        counts_within_cap = all(value <= 3 for value in counts.values())
    constructor_attempted = mode == "live" and any(
        str(event.get("kind", "")).lower() == "phase" and event.get("phase") == "construct"
        for event in events)
    construction_confirmed = mode == "live" and any(
        str(event.get("kind", "")).lower() == "gate"
        and event.get("check", {}).get("stage") == "after-construct" for event in events)
    within_time = exit_within_budget(started_ns, observed_exit_ns)
    manifest = {
        "schemaVersion": "bounded-wgc-qa-controller-v1", "mode": mode,
        "requestedMode": observation_window_mode,
        "passed": bool(worker_result and worker_result.get("passed") and within_time
                       and counts_within_cap and go_sent and controller_error is None
                       and reason == "worker-exited"),
        "startedNs": started_ns, "workDeadlineNs": deadline_ns,
        "totalDeadlineNs": total_deadline_ns, "stopRequestNs": stop_request_ns,
        "terminationRequestedNs": termination_requested_ns,
        "terminationApiSucceeded": termination_api_succeeded,
        "observedExitNs": observed_exit_ns, "exitConfirmedWithin10Seconds": within_time,
        "observedDurationMs": None if observed_exit_ns is None else
            round((observed_exit_ns - started_ns) / 1e6, 3),
        "exitCode": None if child is None else child.poll(),
        "childPid": None if child is None else child.pid,
        "ownedJobAssigned": assigned, "goSent": go_sent, "exitReason": reason,
        "controllerError": controller_error, "counts": counts,
        "countsScope": "all-independent-fake-cases" if mode == "selftest" else "one-worker-session",
        "countsWithinCap": counts_within_cap, "candidateBmpFiles": files,
        "workerResult": worker_result,
        "discardedQueuedFramesBeforeReadback": max(
            sum(int(event.get("discardedQueuedFrames", 0)) for event in events
                if event.get("kind") == "frame-selection"),
            _count(worker_result or {}, "discardedQueuedFrames")),
        "wgcConstructionAttempted": constructor_attempted,
        "realWgcInvoked": True if construction_confirmed else None if constructor_attempted else False,
        "fullDesktopCapture": False, "gameInputOrActivation": False,
        "formalHistoryOrLabelsWritten": False,
        "backgroundFrameArrivalsAreNotCountedAsExplicitAttempts": True,
    }
    (output / "controller-result.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def run_offline(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    # One package: deterministic capture cases, then the two real owned fake-child exits.
    for mode in ("selftest", "fake-hang-constructor", "fake-hang-readback"):
        results[mode] = run_worker(mode, output / mode)
    tests = [{"name": "fake-capture-loop", "passed": results["selftest"]["passed"]}]
    for mode, expected_attempts in (("fake-hang-constructor", 0), ("fake-hang-readback", 1)):
        result = results[mode]
        tests.append({
            "name": mode,
            "passed": result["ownedJobAssigned"] and result["goSent"]
                and result["exitReason"] == "work-deadline"
                and result["terminationApiSucceeded"] is True
                and result["exitConfirmedWithin10Seconds"]
                and result["counts"]["attempts"] == expected_attempts
                and result["counts"]["candidateFiles"] == 0
                and result["counts"]["acceptedFrames"] == 0
                and result["controllerError"] is None,
            "observedDurationMs": result["observedDurationMs"],
        })
    # Independent contract examples: exact deadline is admissible; a later observation is not.
    tests.append({"name": "late-exit-is-failure", "passed":
                  exit_within_budget(100, 10_000_000_100)
                  and not exit_within_budget(100, 10_000_000_101)
                  and not exit_within_budget(100, None)})
    summary = {
        "schemaVersion": "bounded-wgc-qa-offline-v1",
        "diagnosticEntryPassed": all(test["passed"] for test in tests),
        "realWgcStatus": "NOT_RUN_WAITING_FOR_USER_READINESS",
        "warehouseRecognitionStatus": "NOT_RUN",
        "tests": tests, "realWgcFrames": 0,
        "fakePixelSourcesAreNotGameFrames": True,
        "existingProductionMatricesRerun": False,
        "version": {"product": "v0.68-alpha", "sourceIdentity": "sourceFiles/workerSha256/hostSha256"},
        "sourceFiles": {name: hashlib.sha256((SOURCE_ROOT / name).read_bytes()).hexdigest()
                        for name in ("run_qa.py", "Worker.cs", "Worker.csproj")},
        "workerSha256": hashlib.sha256(WORKER.read_bytes()).hexdigest(),
        "hostSha256": hashlib.sha256((HOST / "WgcLiveHarness.dll").read_bytes()).hexdigest(),
        "results": {mode: str((output / mode / "controller-result.json").relative_to(ROOT))
                    for mode in results},
    }
    (output / "offline-result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "live", "eligibility"), default="offline")
    parser.add_argument("--observation-window-mode", choices=OBSERVATION_WINDOW_MODES,
                        default="foreground", help="Fixed for this bounded QA worker session")
    parser.add_argument("--game-ready", action="store_true",
                        help="Only use after the user explicitly says the game is ready")
    parser.add_argument("--hwnd", type=lambda text: int(text, 0))
    parser.add_argument("--pid", type=int)
    parser.add_argument("--instance", type=int, help="Target process creation FILETIME")
    args = parser.parse_args()
    if args.mode == "offline" and args.observation_window_mode != "foreground":
        parser.error("The existing offline package remains foreground; use --mode eligibility for the new policy check")
    if args.mode == "live" and (not args.game_ready or not args.hwnd or not args.pid or not args.instance):
        parser.error("Live requires explicit user readiness and a pinned HWND/PID/process instance")
    output = QA_ROOT / (args.mode + "-" + uuid.uuid4().hex[:10])
    if args.mode == "offline":
        result = run_offline(output)
        passed = result["diagnosticEntryPassed"]
    else:
        result = run_worker(args.mode, output,
                            {"hwnd": args.hwnd, "pid": args.pid, "instance": args.instance}
                            if args.mode == "live" else None,
                            observation_window_mode=args.observation_window_mode)
        passed = result["passed"]
    print(json.dumps({"output": str(output), "passed": passed,
                      "result": str(output / ("offline-result.json" if args.mode == "offline"
                                               else "controller-result.json"))}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
