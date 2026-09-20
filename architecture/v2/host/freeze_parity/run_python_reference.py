# -*- coding: utf-8 -*-
"""V2-2C differential harness — Python reference side.

Executes architecture/v2/host/freeze_parity/scenarios.json against the REAL PRD-F
component (core/warehouse_active_scan_freeze.py) and emits python_results.json.

Nothing here re-implements the coordinator: it only drives the shipped class and records
what it actually does. Steps the Python component cannot express are recorded as
unsupported instead of being faked.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

UNSUPPORTED_STEP_KINDS = {
    "ReasonCleared",
    "SessionChanged",
    "SnapshotResync",
    "IssueRearmToken",
    "RestartCoordinator",
    "ExplicitFreeze",
}


def load_component(repo_root: Path):
    src = repo_root / "core" / "warehouse_active_scan_freeze.py"
    spec = importlib.util.spec_from_file_location("wfreeze_ref", src)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, src


def make_guard(module, halt_mode: str):
    if halt_mode == "THROWING":
        def boom(_reason):
            raise RuntimeError("halt sink down")

        return module.WarehouseActiveScanFreezeGuard(on_freeze_callback=boom)
    return module.WarehouseActiveScanFreezeGuard()


def counters(guard) -> dict:
    return {
        "blockedCount": int(guard.scroll_requests_blocked),
        "executedCount": int(guard.scroll_requests_executed),
    }


class FakeActuator:
    """Records invocation before calling the real Python guard callback."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, delta: int) -> None:
        self.calls.append({"delta": delta})
        # Returning None is intentional: it is still a real call.
        return None


def snapshot(guard, actuator: FakeActuator) -> dict:
    active = [guard.freeze_reason] if guard.is_frozen and guard.freeze_reason else []
    return {
        "isFrozen": bool(guard.is_frozen),
        "scanPermitted": bool(guard.scroll_permitted),
        "progressFrozen": bool(guard.progress_frozen),
        "activeReasons": active,
        "primaryReason": guard.freeze_reason,
        "blockedCount": int(guard.scroll_requests_blocked),
        "executedCount": int(guard.scroll_requests_executed),
        "wheelEmissionCount": len(actuator.calls),
        "actuatorCallCount": len(actuator.calls),
        "rearmAppliedCount": int(guard.to_payload()["rearmCount"]),
        "haltCallbackFailed": bool(guard.halt_callback_failed),
        "traceCount": int(guard.to_payload()["eventCount"]) + int(guard.to_payload()["rearmCount"]),
    }


def run_scenario(module, scenario: dict) -> dict:
    halt_mode = scenario.get("haltCallback", "NONE")
    guard = make_guard(module, halt_mode)
    actuator = FakeActuator()
    unsupported: list = []
    step_results: list = []
    baseline = None

    for index, step in enumerate(scenario["steps"]):
        kind = step["kind"]
        result: dict = {"index": index, "kind": kind}

        if kind in UNSUPPORTED_STEP_KINDS:
            unsupported.append({"index": index, "kind": kind})
            result["supported"] = False
            result["note"] = "the Python PRD-F component cannot express this event"
            step_results.append(result)
            continue

        result["supported"] = True

        if kind == "SyncToAllow":
            # Python starts ALLOW, so this is a no-op here. It exists so the native side
            # can leave its fail-closed bootstrap state and both sides share a baseline.
            result["note"] = "python already ALLOW; no-op"

        elif kind == "ScanRequest":
            before_calls = len(actuator.calls)
            return_value = guard.execute_scroll_request(actuator, 120)
            result["actuatorCalled"] = len(actuator.calls) > before_calls
            result["returnValueWasNone"] = return_value is None
            # The call log, not the callback return value, is the execution proof.
            result["executed"] = len(actuator.calls) > before_calls
            result["actuatorCallCount"] = len(actuator.calls)

        elif kind == "PrecheckOnly":
            result["permitted"] = bool(guard.precheck_scroll_permitted())

        elif kind == "AssertScanPermitted":
            try:
                guard.assert_scroll_permitted()
                result["raised"] = False
            except Exception as exc:  # noqa: BLE001
                result["raised"] = True
                result["errorType"] = type(exc).__name__
                result["reason"] = getattr(exc, "reason", None)

        elif kind == "SoftKeyboardActive":
            result["applied"] = bool(guard.on_input_abort_signal("KEY_DOWN", {"key": "typing"}))

        elif kind == "ForegroundLost":
            result["applied"] = bool(guard.on_focus_lost({"hwnd": 4242}))

        elif kind == "BidActive":
            result["applied"] = bool(guard.on_game_conflict({"round": 2, "state": "BIDDING"}))

        elif kind == "UserTakeover":
            result["applied"] = bool(
                guard.trigger_freeze(module.FREEZE_REASON_TAKEOVER, {"source": "mouse"})
            )

        elif kind == "RearmRequest":
            result["outcome"] = bool(
                guard.attempt_rearm(
                    manual_rearm_confirmed=bool(step.get("manualRearmConfirmed", False)),
                    target_focus_valid=bool(step.get("targetFocusValid", False)),
                    no_game_conflict=bool(step.get("noGameConflict", False)),
                    no_user_takeover_active=bool(step.get("noUserTakeoverActive", False)),
                )
            )

        elif kind == "LegacyToken":
            result["accepted"] = bool(guard.unfreeze_rearmed(step.get("token", "")))

        else:
            result["supported"] = False
            result["note"] = f"unknown step kind {kind}"
            unsupported.append({"index": index, "kind": kind})

        result["state"] = snapshot(guard, actuator)
        step_results.append(result)

        if step.get("syncStep"):
            baseline = counters(guard)

    final = snapshot(guard, actuator)
    if baseline is None:
        baseline = {"blockedCount": 0, "executedCount": 0}

    final["blockedCount"] = final["blockedCount"] - baseline["blockedCount"]
    final["executedCount"] = final["executedCount"] - baseline["executedCount"]

    return {
        "scenarioId": scenario["id"],
        "surface": scenario["surface"],
        "supportedByPython": len(unsupported) == 0,
        "unsupportedSteps": unsupported,
        "steps": step_results,
        "final": final,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--scenarios", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--raw-out")
    args = parser.parse_args()

    repo_root = Path(args.repo)
    module, src = load_component(repo_root)
    scenario_doc = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))

    results = [run_scenario(module, s) for s in scenario_doc["scenarios"]]

    import hashlib

    payload = {
        "schemaVersion": "v2.2c.freeze.parity.python.results.v1",
        "side": "PYTHON_REFERENCE",
        "sourceFile": str(src),
        "sourceSha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "scenarioSchemaVersion": scenario_doc["schemaVersion"],
        "safetySurface": scenario_doc["safetySurface"],
        "scenarioCount": len(results),
        "results": results,
    }

    Path(args.out).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if args.raw_out:
        raw_path = Path(args.raw_out)
        with raw_path.open("w", encoding="utf-8", newline="\n") as raw:
            raw.write(json.dumps({
                "kind": "python_reference_header",
                "scenarioCount": len(results),
                "sourceFile": str(src),
                "sourceSha256": payload["sourceSha256"],
            }, ensure_ascii=False) + "\n")
            for result in results:
                raw.write(json.dumps({"kind": "python_scenario", **result}, ensure_ascii=False) + "\n")
    print(f"python reference: {len(results)} scenarios -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
