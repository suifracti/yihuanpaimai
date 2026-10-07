"""One bounded synthetic-window WGC/ABI experiment; production gate unchanged."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid

from run_qa import OwnedJob

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "build/native-timestamp-contract-20261006"
PROBE = EVIDENCE / "out/TimestampProbe.exe"
HOST = ROOT / "build/native-observation"


def prepare(executable=PROBE):
    manifest = json.loads((ROOT / "build/native-clock-startup-20261005/candidate.json").read_text(encoding="utf-8"))
    for name, expected in manifest["hostHashes"].items():
        if hashlib.sha256((HOST / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError("Production candidate binary mismatch: " + name)
    for name in ("Microsoft.Windows.SDK.NET.dll", "WinRT.Runtime.dll"):
        if hashlib.sha256((HOST / name).read_bytes()).digest() != hashlib.sha256((executable.parent / name).read_bytes()).digest():
            raise RuntimeError("Probe must use exact production projection binary: " + name)
    return {"productionCandidate": manifest["candidate"], "probeSha256": hashlib.sha256(executable.with_suffix(".dll").read_bytes()).hexdigest(),
            "projectionHashes": {name: hashlib.sha256((HOST / name).read_bytes()).hexdigest()
                                 for name in ("Microsoft.Windows.SDK.NET.dll", "WinRT.Runtime.dll")}}


def run_once(prepared, *, executable=PROBE, target=None):
    self_dxgi = prepared.get("experimentKind") == "self-dxgi"
    output = EVIDENCE / (("game-abi-" if target is not None else "dxgi-" if self_dxgi else "controlled-") + uuid.uuid4().hex[:10])
    output.mkdir()
    messages = queue.Queue(maxsize=128)
    from collections import deque
    events = deque(maxlen=128)
    began = time.perf_counter_ns()
    work_deadline, total_deadline = began + 8_000_000_000, began + 10_000_000_000
    child = job = None
    assigned = go_sent = False
    observed_exit = stop_at = None
    error = None
    reason = None
    first_gate_failure = None
    readers = []

    def collect(stream, filename, parse):
        with (output / filename).open("w", encoding="utf-8") as log:
            for line in stream:
                log.write(line); log.flush()
                if parse:
                    try:
                        item = json.loads(line)
                    except ValueError:
                        item = {"kind": "bad-output", "raw": line[:1000]}
                    # Raw evidence is always written above. Keep IPC memory bounded;
                    # retain terminal/failure messages if transient progress overflows.
                    try:
                        messages.put_nowait(item)
                    except queue.Full:
                        if item.get("kind") in ("result", "bad-output") or item.get("rejection"):
                            try:
                                messages.get_nowait()
                            except queue.Empty:
                                pass
                            messages.put_nowait(item)

    try:
        job = OwnedJob()
        child = subprocess.Popen([str(executable), str(HOST)], cwd=ROOT, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
        job.assign(child.pid); assigned = True
        for stream, filename, parse in ((child.stdout, "raw.jsonl", True), (child.stderr, "stderr.txt", False)):
            reader = threading.Thread(target=collect, args=(stream, filename, parse), daemon=True)
            reader.start(); readers.append(reader)
        print(json.dumps({"phase": "game-abi-probe-started" if target is not None else "synthetic-probe-started", "pid": child.pid}), flush=True)
        while time.perf_counter_ns() < work_deadline:
            if child.poll() is not None:
                observed_exit = time.perf_counter_ns(); reason = "worker-exited"; break
            try:
                event = messages.get(timeout=min(.02, max(0, (work_deadline - time.perf_counter_ns()) / 1e9)))
            except queue.Empty:
                continue
            events.append(event)
            if event.get("kind") == "ready":
                if go_sent:
                    raise RuntimeError("duplicate-ready")
                child.stdin.write(json.dumps({"command": "GO", "workDeadlineNs": work_deadline, **(target or {})}) + "\n")
                child.stdin.flush(); go_sent = True
            elif event.get("kind") == "construct":
                print(json.dumps({"phase": "specified-game-window-only" if target is not None else "synthetic-window-only",
                                  "hwnd": event.get("targetHwnd", event.get("ownHwnd"))}), flush=True)
            elif event.get("kind") in ("original-decision", "accepted-diagnostic-frame"):
                if event.get("rejection") and first_gate_failure is None:
                    first_gate_failure = event
                print(json.dumps({"phase": event["kind"], "attempt": event["attempt"],
                                  "rejection": event.get("rejection"), "aheadNs": event.get("aheadNs")}), flush=True)
            elif event.get("kind") == "same-frame-getters":
                print(json.dumps({"phase": "same-frame-read", "attempt": event["attempt"],
                    "sameIdentity": event["sameFrameIdentity"], "sameValue": event["sameValue"], "aheadNs": event["aheadNs"]}), flush=True)
            elif event.get("kind") == "bad-output":
                raise RuntimeError("non-json-worker-output")
        if observed_exit is None:
            stop_at = time.perf_counter_ns(); reason = "work-deadline"
            if assigned:
                job.terminate()
            else:
                child.terminate()
            child.wait(timeout=max(0, (total_deadline - time.perf_counter_ns()) / 1e9))
            observed_exit = time.perf_counter_ns()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        reason = reason or "controller-error"
        if child is not None and child.poll() is None:
            stop_at = time.perf_counter_ns()
            if assigned:
                job.terminate()
            else:
                child.terminate()
            try:
                child.wait(timeout=max(0, (total_deadline - time.perf_counter_ns()) / 1e9))
                observed_exit = time.perf_counter_ns()
            except subprocess.TimeoutExpired:
                pass
    finally:
        if job is not None:
            job.close()
        if child is not None and observed_exit is None and child.poll() is not None:
            observed_exit = time.perf_counter_ns()
        for reader in readers:
            reader.join(.2)
        while not messages.empty():
            event = messages.get_nowait()
            events.append(event)
            if event.get("kind") == "original-decision" and event.get("rejection") and first_gate_failure is None:
                first_gate_failure = event
    worker = next((event for event in events if event.get("kind") == "result"), None)
    completion = (worker or {}).get("completed", (worker or {}).get("completedClock", {}))
    completed_ns = completion.get("nanoseconds", completion.get("ns"))
    summary = {**prepared, "output": str(output), "startedNs": began, "workDeadlineNs": work_deadline,
        "totalDeadlineNs": total_deadline, "stopNs": stop_at, "observedExitNs": observed_exit,
        "observedDurationMs": None if observed_exit is None else (observed_exit - began) / 1e6,
        "exitConfirmedWithin10Seconds": observed_exit is not None and observed_exit <= total_deadline,
        "workerCompletedNs": completed_ns,
        "workCompletedWithin8Seconds": completed_ns is not None and began <= completed_ns <= work_deadline,
        "childPid": None if child is None else child.pid, "exitCode": None if child is None else child.poll(),
        "jobAssigned": assigned, "goSent": go_sent, "exitReason": reason, "controllerError": error,
        "workerResult": worker, "firstGateFailure": first_gate_failure or (worker or {}).get("firstGateFailure"),
        "gameCaptureRequested": target is not None,
        "gameCapture": worker.get("gameCapture") if worker is not None else (None if target is not None else False),
        "desktopCapture": False, "gameInput": False,
        "secondRunPerformed": False, "productionGateChanged": False}
    (output / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (EVIDENCE / ("last-game-abi-run.json" if target is not None else "last-dxgi-run.json" if self_dxgi else "last-controlled-run.json")).write_text(json.dumps({"path": str(output)}, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "exitConfirmed": summary["exitConfirmedWithin10Seconds"],
                      "durationMs": summary["observedDurationMs"], "controllerError": error}), flush=True)
    return 0 if (worker and worker["failure"] is None and worker.get("cleanupFailure") is None
                 and summary["exitCode"] == 0 and summary["workCompletedWithin8Seconds"]
                 and summary["exitConfirmedWithin10Seconds"]) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-once", action="store_true")
    args = parser.parse_args()
    prepared = prepare()
    if args.run_once:
        raise SystemExit(run_once(prepared))
    print(json.dumps({"preparedOnly": True, **prepared}, indent=2))
