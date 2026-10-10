"""Replay one retained auction snapshot through Host qualification and real Main/solver.

No capture, game input, GUI launch or durable history writes. QPC is replayed on
the recorded timeline; receipt explicitly distinguishes replay from live safety.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def replay(session: Path, history: Path, output: Path, contract_dll: Path):
    if not output.resolve().is_relative_to((ROOT / "build").resolve()):
        raise ValueError("Replay output must be inside build/")
    output.mkdir(parents=True, exist_ok=True)
    state_file = session / "latest-business-state.json"
    saved = read_json(state_file)
    state, sequence = saved["state"], saved["frameSequence"]
    source = state["lastFrame"]
    if source["scene"] != "IN_AUCTION" or source["frameSequence"] != sequence:
        raise ValueError("Retained source is not this auction snapshot")
    ui_row = next(row for row in map(json.loads, (session / "ui-frame-events.jsonl").read_text(encoding="utf-8").splitlines())
        if row.get("stage") == "bridge-received" and row.get("frame", {}).get("sequence") == sequence)
    frame = copy.deepcopy(ui_row["frame"])
    raw = (session / "latest-business-frame.bmp").read_bytes()
    pixels = raw[struct.unpack_from("<I", raw, 10)[0]:]
    if hashlib.sha256(pixels).hexdigest() != source["pixelSha256"]:
        raise ValueError("Retained original does not match the saved engine state")
    if source["captureProof"]["deliveryProof"] != frame["deliveryProof"]:
        raise ValueError("Retained original and delivered observation disagree")
    if source["stateFactsRevision"] != state["currentMatch"]["factsRevision"]:
        raise ValueError("Saved fact version is not the retained original's version")
    width, height, stride = frame["width"], frame["height"], frame["stride"]

    def roi_hash(left, top, right, bottom):
        digest = hashlib.sha256()
        for y in range(top, bottom):
            digest.update(pixels[y * stride + left * 4:y * stride + right * 4])
        return digest.hexdigest()

    if (width, height) != (1920, 1080):
        raise ValueError("This retained-run replay expects its recorded 1920x1080 map")
    # Use the recorded publication age; do not rewrite proof/source timestamps.
    evaluation_ns = frame["capturedAtNs"] + round(frame["deliveryAgeMs"] * 1_000_000)
    qualification_input = {
        "proof": frame["deliveryProof"], "evaluationNs": evaluation_ns,
        "sceneHash": roi_hash(60, 125, 355, 220),
        "warehouseHash": roi_hash(1280, 200, width, height),
        "observationHash": roi_hash(0, 0, 1280, height),
    }
    input_file = output / "qualification-input.json"
    input_file.write_text(json.dumps(qualification_input, ensure_ascii=False, indent=2), encoding="utf-8")
    computed = subprocess.run(["dotnet", str(contract_dll), str(input_file), "--advice-replay"],
        check=True, capture_output=True, text=True, encoding="utf-8")
    qualification = json.loads(computed.stdout)
    frame.update(currentAdviceQualified=qualification["qualified"], currentAdviceQualification=qualification,
                 currentSupportCaptureId=qualification["supportCaptureId"])

    # Every writable runtime location is isolated; history is read in place.
    os.environ.update(YIHUAN_DATA_ROOT=str(output / "runtime-data"), NTE_LOG_FILE=str(output / "main.log"),
        NTE_OBSERVATION_PROFILE="native-readonly-v1", NTE_DISABLE_VISION="1",
        YIHUAN_UPPER_TAIL_CAPTURE_DIR=str(output / "support-captures"))
    sys.path[:0] = [str(ROOT / "app"), str(ROOT / "core")]
    import main
    import live_shadow
    main.CANONICAL_DATABASE = str(history.resolve())
    live_shadow.load_history_snapshot(str(history.resolve()), force=True)
    statuses = list(map(json.loads, (session / "host-status.jsonl").read_text(encoding="utf-8").splitlines()))
    ready = next(row for row in statuses if row["status"] == "READY")
    target = ready["details"]["target"]
    if main._native_observation_target_instance(target) != {
        "targetHwnd": source["captureProof"]["targetInstance"]["targetHwnd"],
        "targetPid": source["captureProof"]["targetInstance"]["targetPid"],
        "generation": source["captureProof"]["targetInstance"]["targetGeneration"],
        "processInstanceToken": source["captureProof"]["targetInstance"]["processInstanceToken"],
    }:
        raise ValueError("Saved window identities do not agree")
    event = {
        "type": "native_observation", "schemaVersion": "native-observation-v1", "status": "FRAME",
        "observationSessionId": ui_row["observationSessionId"], "sourceKind": "native_wgc",
        "observationWindowMode": ready["observationWindowMode"],
        "captureFreshnessPolicy": ready["captureFreshnessPolicy"], "inputActions": False, "formalHistoryWriter": False,
        "target": target, "frame": frame, "lastFrame": source,
        "currentMatch": state["currentMatch"], "pipelineContext": state["pipelineContext"],
        "perception": {"scene": source["scene"], "inAuction": True, "bids": [],
                       "intel": state["pipelineContext"].get("intelCardReadings", [])},
    }
    publications = []
    class Recipient:
        async def send(self, message):
            publications.append(json.loads(message))
    recipient = Recipient()
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    real_start = time.perf_counter_ns()
    virtual_now = lambda: evaluation_ns + time.perf_counter_ns() - real_start
    clock = SimpleNamespace(perf_counter_ns=virtual_now, monotonic_ns=virtual_now,
        monotonic=lambda: virtual_now() / 1_000_000_000, time=time.time, sleep=time.sleep)
    before_history = hashlib.sha256(history.read_bytes()).hexdigest()
    live_shadow.register_prediction_listener(main._publish_live_shadow_event)
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(main, "time", clock))
            stack.enter_context(patch.object(main, "WS_EVENT_LOOP", loop))
            stack.enter_context(patch.object(main, "CONNECTED_CLIENTS", {recipient}))
            stack.enter_context(patch.object(main, "NATIVE_OBSERVATION_BRIDGE", SimpleNamespace(running=True, session_dir=None)))
            # Only I/O adapters are suppressed; actual gates, math, callback,
            # CurrentMatch projection and broadcast_ws are executed.
            for name in ("schedule_draft_save", "_native_start_frame_watchdog_locked", "_native_post_main_status",
                         "_native_capture_trial_frame_locked", "_native_capture_intel_source_locked",
                         "_native_capture_warehouse_sources_locked"):
                stack.enter_context(patch.object(main, name, return_value=False))
            main.CONFIG["app"]["captureFreshnessPolicy"] = ready["captureFreshnessPolicy"]
            main._NATIVE_CAPTURE_POLICY = ready["captureFreshnessPolicy"]
            main._NATIVE_WINDOW_MODE = ready["observationWindowMode"]
            main._native_observation_event(next(row for row in statuses if row["status"] == "STARTING"))
            main._native_observation_event(ready)
            main._native_observation_event(event)
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if any(row.get("predictionSnapshot") for row in publications):
                    break
                time.sleep(.02)
            published = next((row for row in reversed(publications) if row.get("predictionSnapshot")), None)
            if published is None:
                raise RuntimeError("Main did not publish a solver result: " + json.dumps({
                    key: main.LATEST_PAYLOAD.get(key) for key in ("solverStatus", "solverMissingReason", "shadowMeta")}, ensure_ascii=False))
            if main.LATEST_VISION_PAYLOAD.get("predictionSnapshot") != published["predictionSnapshot"]:
                raise RuntimeError("Native transport does not contain the published snapshot")
            result = {
                "verificationMode": "saved-offline-replay", "gameCapture": False, "gameInput": False,
                "retainedOriginal": str((session / "latest-business-frame.bmp").resolve()),
                "stateFile": str(state_file.resolve()), "frameSequence": sequence,
                "pixelSha256": source["pixelSha256"], "qualification": qualification,
                "historyPath": str(history.resolve()), "historySha256": before_history,
                "historyN": live_shadow.snapshot_size(), "mainPublished": True,
                "originalFactsRevision": source["stateFactsRevision"],
                "inputFacts": {k: main.CURRENT_MATCH.facts.get(k) for k in
                    ("q", "goldAvg", "purpleCount", "totalItems", "totalGrid", "goldGrid", "knownGold", "knownPurple", "knownRed")},
                "mainPayload": published,
            }
            if hashlib.sha256(history.read_bytes()).hexdigest() != before_history:
                raise RuntimeError("Read-only history changed")
            (output / "replay-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"mainPublished": True, "status": published.get("solverStatus"),
                "mode": (published["predictionSnapshot"].get("mode") or {}).get("informationMode"),
                "output": str(output / "replay-result.json")}, ensure_ascii=False))
    finally:
        live_shadow.register_prediction_listener(None)
        live_shadow.reset_live_shadow_state()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract-dll", type=Path, default=ROOT / "build/native-observation-pipeline-contracts/out/pipeline-contracts.dll")
    args = parser.parse_args()
    replay(args.session, args.history, args.output, args.contract_dll)
