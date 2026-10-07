"""Offline Main behavior for explicitly confirmed Native background observation.

Load production functions without executing Main's configuration/history/GUI
initializers. Frames and clocks are fixtures; no window or capture API is used.
"""
import ast
import copy
import io
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "core"), str(ROOT / "app")]
from native_capture_delivery import STRICT, DELIVERY, POLICIES, validate_delivery
from current_match import CurrentMatch


_MAIN_FUNCTIONS = {
    "_native_use_age_ms", "native_capture_policy", "handle_capture_freshness_policy",
    "_native_target_instance", "_native_observation_target_instance",
    "native_observation_window_mode", "_native_confirm_window_mode",
    "_native_source_frame_rejection", "_native_observation_event",
    "_native_background_source_current", "handle_observation_window_mode",
    "_native_accept_observation_locked", "_native_solver_lease_matches_locked",
    "_native_solver_lease_matches", "_native_health_from_event",
    "_native_publish_health", "_native_warehouse_intake_scope",
    "_native_report_ui_ready",
    "_stop_vision_worker_locked",
    "_send_native_manual_control", "_game_input_execution_allowed",
    "_native_profile_selected_before_config_load",
    "_native_warehouse_source_scope", "_native_source_observation_notice",
    "maybe_trigger_auto_warehouse_capture", "_maybe_trigger_native_warehouse_capture",
    "_arm_native_postclose_trigger_watch", "_native_source_evidence_event",
    "_native_auto_trigger_notice",
    "_native_claim_warehouse_attempt", "handle_native_auto_warehouse_capture",
}


def _isolated_main(mode="foreground"):
    """Run actual receiving/authorization functions with inert output adapters."""
    tree = ast.parse((ROOT / "app/main.py").read_text(encoding="utf-8"))
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in _MAIN_FUNCTIONS]
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[
        ast.alias(name="annotations")], level=0), *functions], type_ignores=[])
    current = CurrentMatch()
    current.id = "background-match"
    current.apply_facts({"q": 17, "roundNo": 1}, source="vision", intent="observe")
    clock = [100_000_000_000]
    bridge = SimpleNamespace(running=True, session_dir=None, send_control=Mock(return_value=True))
    ns = {
        "__name__": "isolated_native_main", "os": os, "copy": copy,
        "STRICT": STRICT, "DELIVERY": DELIVERY, "POLICIES": POLICIES, "validate_delivery": validate_delivery,
        "_NATIVE_CAPTURE_POLICY": STRICT, "_NATIVE_DELIVERY_ANCHORED_MATCH": None,
        "_NATIVE_AUTO_TRIGGER_STATUS": {},
        "time": SimpleNamespace(monotonic_ns=lambda: clock[0],
                                perf_counter_ns=lambda: clock[0],
                                monotonic=lambda: clock[0] / 1_000_000_000),
        "CONFIG": {"app": {"observationProfile": "native-readonly-v1",
                           "observationWindowMode": mode}},
        "CURRENT_MATCH": current, "LATEST_PAYLOAD": {}, "LATEST_VISION_PAYLOAD": {},
        "_MANUAL_STATE_LOCK": threading.RLock(), "_NATIVE_OBSERVATION_LOCK": threading.RLock(),
        "_VISION_PROCESS_LOCK": threading.RLock(),
        "_NATIVE_WINDOW_MODE": mode, "_NATIVE_WINDOW_MODE_CONFIRMED": False,
        "_NATIVE_AUTO_WAREHOUSE_ENABLED": False, "_NATIVE_SOURCE_CAPTURE_CAPABILITY": False,
        "_NATIVE_WAREHOUSE_SOURCE_COORDINATOR": None, "_AUTO_CAPTURE_ATTEMPTED_KEYS": set(),
        "_NATIVE_WINDOW_TARGET_INSTANCE": None,
        "_NATIVE_EXPECTED_SESSION": None, "_NATIVE_OBSERVATION_SESSION": None,
        "_NATIVE_OBSERVATION_SOURCE_NS": None, "_NATIVE_OBSERVATION_RECEIVER": None,
        "_NATIVE_OBSERVATION_SEQUENCE": 0, "_NATIVE_OBSERVATION_LAST_FRAME_NS": None,
        "_NATIVE_FRAME_TIMEOUT_SECONDS": 31.0,
        "_NATIVE_SOLVER_INVALIDATION_GENERATION": 0, "_NATIVE_SOLVER_LEASE": None,
        "_NATIVE_INSTANCE_DECISION_GENERATION": 0, "_NATIVE_INSTANCE_DECISION_SCOPE": None,
        "_NATIVE_WAREHOUSE_FRAME_LEASE": None, "_NATIVE_CONTROL_BINDINGS": {},
        "_NATIVE_TRIAL_SOURCE_FRAMES": [], "_NATIVE_TRIAL_FRAME_MATCH_ID": None,
        "_NATIVE_TRIAL_WAREHOUSE_SOURCES": {}, "_NATIVE_TRIAL_WAREHOUSE_DECISIONS": {},
        "_NATIVE_WAREHOUSE_DECISION_RECEIPT": {}, "_LIVE_MANUAL_OVERRIDES": {},
        "_LIVE_VISION_ACTIVE": False, "_LIVE_VISION_MATCH_ID": None,
        "_LIVE_CONTROL_WAITING_EXIT": False, "_LIVE_CONTROL_REVISION": 0,
        "_LAST_DRAFT_WRITE": (current.id, current.facts_revision),
        "NATIVE_OBSERVATION_BRIDGE": bridge, "WS_EVENT_LOOP": None,
        "PRESENTATION_RUNTIME": SimpleNamespace(set_vision_process_state=Mock(), observe_transport=Mock()),
        "ACTIVE_SETTLEMENT_TRUTH_HOLDER": SimpleNamespace(clear=Mock()),
        "native_observation_enabled": lambda: True,
        "get_recognition_mode": lambda: "live",
        "get_current_match_presentation_summary": lambda: {"matchId": current.id},
        "costs_from_facts": lambda facts: {}, "bids_hidden_now": lambda facts: False,
        "free_intel_status": lambda facts: {}, "_native_unverified_cost_summary": lambda facts: "",
        "_native_unverified_accounting": lambda facts: {},
        "_native_solver_admission": lambda facts: (None, "fixture lacks venue rules"),
        "_next_match_preparation_frame_gate": lambda data, lease: False,
        "build_canonical_overlay_state": lambda match, data: {},
        "build_manual_alpha_payload": lambda **kwargs: {},
        "_native_capture_warehouse_sources_locked": lambda: False,
        "_native_capture_intel_source_locked": lambda *args: False,
        "_persist_current_draft_now": lambda: None,
    }
    # These are output adapters, not the gates under test. They cannot save
    # images, write DRAFT/history, launch threads, or publish to GUI/network.
    for name in (
        "_native_invalidate_solver_locked", "_native_reject_pending_instance_decisions_locked",
        "_native_start_frame_watchdog_locked", "_native_post_main_status",
        "_native_update_instance_decision_scope_locked", "_native_capture_trial_frame_locked",
        "_native_project_current_quote", "_sync_payload_with_canonical_facts",
        "schedule_draft_save", "flush_draft_save_sync", "publish_manual_payload", "log_stage",
    ):
        ns[name] = Mock()
    exec(compile(ast.fix_missing_locations(module), str(ROOT / "app/main.py"), "exec"), ns)
    return ns, clock, bridge


def _target():
    return {"targetHwnd": 123, "targetPid": 456, "generation": 7,
            "identity": {"ProcessInstanceToken": 99}, "isTargetAlive": True,
            "isTargetForeground": False, "isTargetVisible": True,
            "isTargetMinimized": False, "clientAreaAvailable": True,
            "clientWidth": 1920, "clientHeight": 1080}


def _status(ns, status="STARTING", *, mode="background-readonly", session="background-session"):
    event = {"sourceKind": "native_wgc", "inputActions": False,
             "formalHistoryWriter": False, "status": status,
             "observationSessionId": session, "details": {"target": _target()}}
    if mode is not None:
        event["observationWindowMode"] = mode
    ns["_native_observation_event"](event)


def _confirmed_start(ns, *, mode="background-readonly"):
    _status(ns, mode=mode)
    _status(ns, "READY", mode=mode)


def _frame(ns, *, session="background-session", sequence=1):
    return {"type": "native_observation", "schemaVersion": "native-observation-v1",
            "status": "FRAME", "observationSessionId": session,
            "observationWindowMode": "background-readonly", "sourceKind": "native_wgc",
            "inputActions": False, "formalHistoryWriter": False, "target": _target(),
            "frame": {"sequence": sequence, "capturedAtNs": 99_750_000_000,
                      "sourceTimestampNs": 99_500_000_000, "freshnessMs": 250},
            "currentMatch": ns["CURRENT_MATCH"].snapshot(),
            "perception": {"scene": "IN_AUCTION", "inAuction": True, "bids": [], "intel": []},
            "pipelineContext": {"scene": "IN_AUCTION", "inAuction": True, "round": 1,
                                "seats": [], "intel": []}}


class NativeBackgroundObservationTests(unittest.TestCase):
    def test_stop_retains_host_ownership_until_exit_is_confirmed(self):
        ns, _, bridge = _isolated_main("background-readonly")
        ns.update({"VISION_PROCESS": None, "log_stage": Mock()})
        bridge.stop = Mock()
        ns["LATEST_PAYLOAD"]["visionHealth"] = {"observationStopped": True,
            "reason": "source-clock-future-at-selection", "error": "aheadNs=985900"}
        ns["_stop_vision_worker_locked"]()
        self.assertIs(ns["NATIVE_OBSERVATION_BRIDGE"], bridge)
        self.assertFalse(ns["LATEST_PAYLOAD"]["visionHealth"]["processExitConfirmed"])
        self.assertEqual(ns["LATEST_PAYLOAD"]["visionHealth"]["reason"], "source-clock-future-at-selection")
        bridge.running = False
        ns["_stop_vision_worker_locked"]()
        self.assertIsNone(ns["NATIVE_OBSERVATION_BRIDGE"])

    def test_late_ui_ready_preserves_active_and_first_failed_health(self):
        ns, _, bridge = _isolated_main("background-readonly")
        publish = Mock()
        ns["_native_publish_health"] = publish
        for health, running in (({}, True), ({"profile": "native-readonly-v1", "stage": "native-error",
                "reason": "source-clock-future-at-selection"}, False)):
            ns["LATEST_PAYLOAD"]["visionHealth"] = copy.deepcopy(health)
            bridge.running = running
            ns["_native_report_ui_ready"]()
            self.assertEqual(ns["LATEST_PAYLOAD"]["visionHealth"], health)
            publish.assert_not_called()
        ns["LATEST_PAYLOAD"].clear()
        ns["_native_report_ui_ready"]()
        self.assertEqual(publish.call_args.args[0]["reason"], "explicit-start-required")

    def test_terminal_status_keeps_last_success_and_never_revives_facts(self):
        ns, _, bridge = _isolated_main("background-readonly")
        # Include the actual revocation here; the broad existing fixture replaces
        # it with an inert output adapter and cannot prove lease revocation.
        tree = ast.parse((ROOT / "app/main.py").read_text(encoding="utf-8"))
        revoke = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_native_invalidate_solver_locked")
        ns.update({"ACTIVE_SNAPSHOT_HOLDER": Mock(), "_SHADOW_PRESENTATION_LOCK": threading.RLock(),
                   "_SHADOW_PRESENTATION_KEYS": {}, "_native_reject_pending_controls_locked": Mock()})
        exec(compile(ast.fix_missing_locations(ast.Module(body=[revoke], type_ignores=[])),
                     str(ROOT / "app/main.py"), "exec"), ns)
        with patch.dict(sys.modules, {"live_shadow": SimpleNamespace(invalidate_match_shadow=Mock())}):
            _confirmed_start(ns)
        frame = _frame(ns)
        frame["frame"]["capturedAtUtc"] = "2026-10-04T12:56:21.7745133+00:00"
        ns["_native_observation_event"](frame)
        before = copy.deepcopy(ns["CURRENT_MATCH"].snapshot())
        with patch.dict(sys.modules, {"live_shadow": SimpleNamespace(invalidate_match_shadow=Mock())}):
            _status(ns, "PAUSED")
        health = ns["LATEST_PAYLOAD"]["visionHealth"]
        self.assertTrue(health["observationStopped"])
        self.assertEqual(health["lastSuccessfulObservation"]["frameSequence"], 1)
        self.assertEqual(health["lastSuccessfulObservation"]["matchId"], "background-match")
        self.assertEqual(health["lastSuccessfulObservation"]["capturedAtUtc"], frame["frame"]["capturedAtUtc"])
        self.assertFalse(ns["_LIVE_VISION_ACTIVE"])
        self.assertIsNone(ns["_NATIVE_SOLVER_LEASE"])
        self.assertEqual(ns["CURRENT_MATCH"].snapshot(), before)
        bridge.send_control.assert_called_once_with({"type": "native_stop"})

    def test_same_unfocused_frame_requires_explicit_matching_mode_confirmation(self):
        # The actual foreground failure is accepted only by the explicitly
        # selected background session; safety flags and identity remain intact.
        cases = (
            ("default-foreground", "foreground", "foreground", "foreground", False),
            ("confirmed-background", "background-readonly", "background-readonly", "background-readonly", True),
            ("missing-host-mode", "background-readonly", None, None, False),
            ("wrong-host-mode", "background-readonly", "foreground", "foreground", False),
            ("wrong-frame-mode", "background-readonly", "background-readonly", "foreground", False),
        )
        for label, launch_mode, ack_mode, frame_mode, accepted in cases:
            with self.subTest(label=label):
                ns, _, _ = _isolated_main(launch_mode)
                _confirmed_start(ns, mode=ack_mode)
                event = _frame(ns)
                if frame_mode is None:
                    event.pop("observationWindowMode")
                else:
                    event["observationWindowMode"] = frame_mode
                before = copy.deepcopy(ns["CURRENT_MATCH"].snapshot())
                ns["_native_observation_event"](event)
                self.assertEqual(ns["LATEST_PAYLOAD"].get("observationStatus") == "FRAME", accepted)
                if accepted:
                    self.assertFalse(ns["LATEST_PAYLOAD"]["target"]["isTargetForeground"])
                    self.assertIsNone(ns["_native_target_instance"](event["target"]))
                    self.assertEqual(ns["LATEST_PAYLOAD"]["sourceTimestampNs"], 99_500_000_000)
                    self.assertTrue(ns["_native_solver_lease_matches"](ns["LATEST_PAYLOAD"]))
                else:
                    self.assertEqual(ns["CURRENT_MATCH"].snapshot(), before)
                    self.assertIsNone(ns["_NATIVE_SOLVER_LEASE"])

    def test_background_rejects_unconfirmed_old_session_and_invalid_source_or_target(self):
        cases = ("no-confirmation", "old-session", "missing-source", "expired-source",
                 "future-source", "minimized", "dead-target", "wrong-process-instance")
        for failure in cases:
            with self.subTest(failure=failure):
                ns, _, _ = _isolated_main("background-readonly")
                if failure != "no-confirmation":
                    _confirmed_start(ns)
                else:
                    _status(ns)  # STARTING alone cannot authorize a FRAME.
                event = _frame(ns)
                if failure == "old-session":
                    event["observationSessionId"] = "retired-session"
                elif failure == "missing-source":
                    event["frame"].pop("sourceTimestampNs")
                elif failure == "expired-source":
                    event["frame"]["sourceTimestampNs"] = 68_000_000_000
                elif failure == "future-source":
                    event["frame"]["sourceTimestampNs"] = 100_000_000_001
                elif failure == "minimized":
                    event["target"]["isTargetMinimized"] = True
                elif failure == "dead-target":
                    event["target"]["isTargetAlive"] = False
                elif failure == "wrong-process-instance":
                    event["target"]["identity"]["ProcessInstanceToken"] = 100
                before = copy.deepcopy(ns["CURRENT_MATCH"].snapshot())
                ns["_native_observation_event"](event)
                self.assertNotEqual(ns["LATEST_PAYLOAD"].get("observationStatus"), "FRAME")
                self.assertIsNone(ns["_NATIVE_SOLVER_LEASE"])
                self.assertEqual(ns["CURRENT_MATCH"].snapshot(), before)

    def test_background_internal_command_and_source_scope_preserve_target_and_deadline(self):
        ns, clock, bridge = _isolated_main("background-readonly")
        _confirmed_start(ns)
        event = _frame(ns)
        ns["_native_observation_event"](event)
        payload = copy.deepcopy(ns["LATEST_PAYLOAD"])
        target_instance = {"targetHwnd": 123, "targetPid": 456, "generation": 7,
                           "processInstanceToken": 99}
        self.assertEqual(ns["_native_warehouse_intake_scope"]()["targetInstance"], target_instance)
        command = {"expectedMatchId": "background-match", "revision": 1,
                   "expectedObservationSessionId": "background-session",
                   "expectedFactsRevision": payload["factsRevision"], "expectedRound": 1,
                   "expectedTargetInstance": target_instance,
                   "expectedInvalidationGeneration": ns["_NATIVE_SOLVER_INVALIDATION_GENERATION"],
                   "facts": {"q": 19}, "reset": False}
        result = ns["_send_native_manual_control"](command, validated_observation_scope=payload)
        self.assertEqual(result["status"], "PENDING")
        sent = copy.deepcopy(bridge.send_control.call_args.args[0])
        self.assertEqual(sent["command"]["expectedTargetInstance"], target_instance)
        ns["_NATIVE_CONTROL_BINDINGS"].clear()
        ns["LATEST_PAYLOAD"]["target"]["targetHwnd"] = 999
        rejected = ns["_send_native_manual_control"](command, validated_observation_scope=payload)
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(bridge.send_control.call_count, 1,
                         "a replaced target must never receive the old internal command")
        ns["LATEST_PAYLOAD"] = payload
        clock[0] = 130_600_000_000
        self.assertFalse(ns["_native_solver_lease_matches"](payload),
                         "late handling cannot renew the original source timestamp")
        expired = ns["_send_native_manual_control"](command, validated_observation_scope=payload)
        self.assertEqual(expired["status"], "REJECTED")
        self.assertEqual(bridge.send_control.call_count, 1)
        self.assertEqual(ns["_native_warehouse_intake_scope"]()["scene"], "UNKNOWN")
        # Native input prohibition is independent of foreground/background mode.
        with patch.dict(os.environ, {"NTE_OBSERVATION_PROFILE": "native-readonly-v1"}):
            for mode in ("foreground", "background-readonly"):
                ns["_NATIVE_WINDOW_MODE"] = mode
                self.assertFalse(ns["_game_input_execution_allowed"]())

        repeated, _, _ = _isolated_main("background-readonly")
        _confirmed_start(repeated)
        repeated["_native_observation_event"](_frame(repeated))
        second = _frame(repeated, sequence=2)
        second["frame"]["capturedAtNs"] = 99_900_000_000
        repeated["_native_observation_event"](second)
        self.assertNotEqual(repeated["LATEST_PAYLOAD"].get("frameSequence"), 2,
                            "a newer result envelope cannot create a newer compositor frame")

    def test_mode_choice_is_default_off_and_cannot_change_running_session(self):
        ns, _, bridge = _isolated_main()
        ns["CONFIG"]["app"].pop("observationWindowMode")
        self.assertEqual(ns["native_observation_window_mode"](), "foreground")
        before = copy.deepcopy(ns["CONFIG"])
        result = ns["handle_observation_window_mode"]("background-readonly")
        self.assertFalse(result["ok"])
        self.assertEqual(ns["CONFIG"], before)
        self.assertEqual(ns["_NATIVE_WINDOW_MODE"], "foreground")
        self.assertFalse(ns["handle_observation_window_mode"]("unknown")["ok"])


class NativeHostExitReceiptTests(unittest.TestCase):
    def make_bridge(self, events, code, *, terminal=False):
        sys.path.insert(0, str(ROOT / "app"))
        from native_observation import NativeObservationBridge
        frame = {"type": "native_observation", "status": "FRAME", "observationSessionId": "exit-session"}
        messages = [frame]
        if terminal:
            messages.append({**frame, "status": "PAUSED", "reason": "source-clock-stale-at-readback"})
        child = SimpleNamespace(stdout=io.StringIO("\n".join(json.dumps(x) for x in messages)),
                                poll=lambda: code)
        bridge = NativeObservationBridge(str(ROOT), events.append, Mock())
        bridge.process = child
        bridge._record_frame_event = Mock()
        bridge._record_status_event = Mock()
        return bridge, child

    def test_zero_exit_after_frame_is_not_left_recording(self):
        events = []
        bridge, child = self.make_bridge(events, 0)
        bridge._read_stdout(child)
        self.assertEqual(events[-1]["status"], "ERROR")
        self.assertEqual(events[-1]["reason"], "host-exited:0")
        self.assertEqual(events[-1]["observationSessionId"], "exit-session")
        self.assertTrue(events[-1]["details"]["processExitConfirmed"])
        self.assertFalse(bridge.running)

    def test_paused_exit_keeps_actual_reason(self):
        events = []
        bridge, child = self.make_bridge(events, 3, terminal=True)
        bridge._read_stdout(child)
        self.assertEqual(events[-1]["status"], "PAUSED")
        self.assertEqual(events[-1]["reason"], "source-clock-stale-at-readback")
        self.assertTrue(events[-1]["details"]["processExitConfirmed"])
        self.assertFalse(bridge.running)

    def test_first_failure_survives_later_mapping_stop_and_unconfirmed_eof(self):
        events = []
        bridge, child = self.make_bridge(events, None)
        messages = [{"type": "native_observation", "status": "ERROR", "reason": "source-clock-future-at-selection",
                     "details": {"error": "aheadNs=985900"}},
                    {"type": "native_observation", "status": "PAUSED", "reason": "client-area-mapping-changed"},
                    {"type": "native_observation", "status": "STOPPED", "reason": "explicit-stop"}]
        child.stdout = io.StringIO("\n".join(json.dumps(x) for x in messages))
        bridge.stop = Mock()
        bridge._read_stdout(child)
        self.assertTrue(all(e["reason"] == "source-clock-future-at-selection" for e in events))
        self.assertEqual(events[-1]["details"]["error"], "aheadNs=985900")
        self.assertFalse(events[-1]["details"]["processExitConfirmed"])
        ns, _, _ = _isolated_main()
        health = ns["_native_health_from_event"](events[-1])
        self.assertFalse(health["processExitConfirmed"])
        self.assertTrue(health["observationStopped"])

    def test_eof_before_process_exit_reports_unknown_and_keeps_ownership(self):
        events = []
        bridge, child = self.make_bridge(events, None)
        bridge.stop = Mock()
        bridge._read_stdout(child)
        self.assertEqual(events[-1]["reason"], "host-output-closed")
        self.assertFalse(events[-1]["details"]["processExitConfirmed"])
        self.assertIs(bridge.process, child)
        bridge.stop.assert_called_once()

    def test_old_reader_cannot_stop_new_host(self):
        events = []
        bridge, child = self.make_bridge(events, 3)
        replacement = SimpleNamespace(poll=lambda: None)
        bridge.process = replacement
        bridge._read_stdout(child)
        self.assertEqual(events, [])
        self.assertIs(bridge.process, replacement)


if __name__ == "__main__":
    unittest.main()
