"""Explicit one-shot launch through Main's existing observation command.

Default is preparation only. No app, window, capture or input is opened until
--start-authorized is supplied. This is startup orchestration, not a lifecycle.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    for module in ("websockets", "cv2", "numpy", "onnxruntime", "rapidocr_onnxruntime", "clr", "win32gui"):
        if importlib.util.find_spec(module) is None:
            raise RuntimeError(f"Prepare Python dependency before starting: {module}")
    config = json.loads((ROOT / "app/config.json").read_text(encoding="utf-8"))
    app = config["app"]
    if (app.get("mode") != "live" or app.get("observationProfile") != "native-readonly-v1"
            or app.get("observationWindowMode") != "background-readonly"):
        raise ValueError("Select live Native background observation before preparing")
    host = Path(os.environ.get('NTE_NATIVE_HOST_EXE', str(ROOT / 'build/native-observation/WgcLiveHarness.exe'))).resolve()
    names = ["app/main.py", "app/DirectCompositionHost.dll",
             str(host), str(host.with_suffix(".dll")),
             "architecture/v2/host/engine_v22/nte_engine_v22.py", "core/warehouse_vision.py", "assets/catalog_065.json"]
    files = {}
    for name in names:
        file = ROOT / name
        if not file.is_file():
            raise FileNotFoundError(f"Prepare dependency before starting: {name}")
        files[name] = hashlib.sha256(file.read_bytes()).hexdigest()
    return {"files": files, "hostExe": str(host), "captureFreshnessPolicy": app.get("captureFreshnessPolicy", "wgc-origin-strict-v1"), "port": int(config.get("network", {}).get("wsPort", 8766)),
            "autoWarehouseCapture": app.get("nativeAutoWarehouseCapture") is True,
            "python": sys.executable, "preparationDoesNotLoadModelsOrCapture": True}


async def request_once(ws, record, timeout=10):
    await ws.send(json.dumps({"type": "start_live_vision", "resumeSameMatch": False}))
    record("observation-request-sent")
    deadline = time.monotonic() + timeout
    starting = False
    while time.monotonic() < deadline:
        event = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.monotonic()))
        health = event.get("visionHealth") or {}
        stage = health.get("stage")
        if stage == "native-starting":
            starting = True
            record("host-starting", health=health)
        elif starting and stage == "native-ready":
            record("engine-ready-awaiting-first-frame", health=health)
        elif starting and stage in {"native-frame", "native-paused", "native-error", "native-stopped"}:
            record("host-startup-result", health=health)
            return stage == "native-frame"
    raise TimeoutError("Host startup acknowledgement deadline")


async def start(prepared, output, *, environment=None, on_launch=None):
    import websockets
    # Refuse an occupied bus: do not start or command an unknown old process.
    with socket.socket() as probe:
        probe.settimeout(.2)
        if probe.connect_ex(("127.0.0.1", prepared["port"])) == 0:
            raise RuntimeError("Existing assistant bus is occupied; close that assistant explicitly first")
    output.mkdir(parents=True, exist_ok=False)
    begun = time.perf_counter_ns()

    def record(stage, **fields):
        item = {"stage": stage, "utc": time.time_ns(), "perfCounterNs": time.perf_counter_ns(),
                "elapsedMs": (time.perf_counter_ns() - begun) / 1e6, **fields}
        with (output / "startup.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(json.dumps(item, ensure_ascii=False), flush=True)

    (output / "prepared.json").write_text(json.dumps(prepared, indent=2), encoding="utf-8")
    env = {**os.environ, "NTE_LOG_FILE": str(output / "main.log"),
           "YIHUAN_DATA_ROOT": str(output / "runtime-data"), "NTE_OBSERVATION_PROFILE": "native-readonly-v1",
           "NTE_NATIVE_HOST_EXE": prepared["hostExe"]}
    env.update(environment or {})
    with (output / "stdout.log").open("w", encoding="utf-8") as out, (output / "stderr.log").open("w", encoding="utf-8") as err:
        child = subprocess.Popen([sys.executable, str(ROOT / "app/main.py")], cwd=ROOT,
                                 env=env, stdout=out, stderr=err,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if on_launch is not None:
        on_launch(child)  # Retain ownership for the one-shot wrapper's bounded cleanup.
    record("assistant-launched", wrapperPid=child.pid)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError(f"Assistant exited before bus ready: {child.returncode}")
        log = output / "main.log"
        if log.is_file() and "WebSocket bus ready on" in log.read_text(encoding="utf-8", errors="replace"):
            record("bus-ready")
            async with websockets.connect(f"ws://127.0.0.1:{prepared['port']}", open_timeout=2) as ws:
                try:
                    return await request_once(ws, record)
                except Exception as exc:
                    # No retry/restart. Request an existing bounded stop and
                    # report unknown exit rather than claiming success.
                    confirmed = False
                    try:
                        await ws.send(json.dumps({"type": "stop_live_vision"}))
                        stop_deadline = time.monotonic() + 6
                        while time.monotonic() < stop_deadline:
                            receipt = json.loads(await asyncio.wait_for(ws.recv(), stop_deadline - time.monotonic()))
                            if receipt.get("type") == "native_stop_receipt":
                                confirmed = receipt.get("processExitConfirmed") is True
                                break
                    except Exception:
                        pass
                    record("startup-failed", error=f"{type(exc).__name__}: {exc}", exitConfirmed=confirmed)
                    return False
        await asyncio.sleep(.05)
    record("bus-ready-timeout", exitConfirmed=False)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-authorized", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    prepared = prepare()
    if not args.start_authorized:
        print(json.dumps({"preparedOnly": True, **prepared}, ensure_ascii=False, indent=2))
        return 0
    if args.output is None:
        parser.error("Authorized start requires a fresh --output inside build/")
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "build").resolve()):
        parser.error("Output must be inside this project's build directory")
    return 0 if asyncio.run(start(prepared, output)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
