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
import tempfile
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
    "_native_domain_action_dispatch_rejected",
    "_advance_authorized_live_domain_loop",
    "_stop_authorized_live_domain_loop",
    "_native_domain_planning_view",
    "_live_loop_view",
    "_live_domain_mode",
    "_auto_auction_settings", "_auto_auction_enabled", "_auto_auction_approval_id",
    "_auto_auction_public",
    "_game_is_foreground",
    "_native_observed_solver_facts",
    "_native_domain_action_session_observe_locked",
    "_native_background_source_current", "handle_observation_window_mode",
    "_native_accept_observation_locked", "_native_solver_lease_matches_locked",
    "_native_fact_computation_rejection",
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
                                monotonic=lambda: clock[0] / 1_000_000_000,
                                strftime=lambda fmt: "20261022T000000"),
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
        "_AUTO_AUCTION_APPROVAL_ID": None,
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
    def test_mapping_suspension_revokes_old_admission_without_stopping_host(self):
        ns, _, bridge = _isolated_main("background-readonly")
        _confirmed_start(ns)
        ns["_native_observation_event"](_frame(ns))
        old_lease = copy.deepcopy(ns["_NATIVE_SOLVER_LEASE"])
        ns["_NATIVE_WAREHOUSE_FRAME_LEASE"] = {"captureId": "old"}
        # Execute the actual revocation, without configuration/history/GUI initialization.
        tree = ast.parse((ROOT / "app/main.py").read_text(encoding="utf-8"))
        revoke = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_native_invalidate_solver_locked")
        ns.update({"ACTIVE_SNAPSHOT_HOLDER": Mock(), "_SHADOW_PRESENTATION_LOCK": threading.RLock(),
                   "_SHADOW_PRESENTATION_KEYS": {}, "_native_reject_pending_controls_locked": Mock()})
        exec(compile(ast.fix_missing_locations(ast.Module(body=[revoke], type_ignores=[])),
                     str(ROOT / "app/main.py"), "exec"), ns)
        before = copy.deepcopy(ns["CURRENT_MATCH"].snapshot())
        with patch.dict(sys.modules, {"live_shadow": SimpleNamespace(invalidate_match_shadow=Mock())}):
            _status(ns, "SUSPENDED")
        self.assertIsNone(ns["_NATIVE_SOLVER_LEASE"])
        self.assertIsNone(ns["_NATIVE_WAREHOUSE_FRAME_LEASE"])
        self.assertFalse(ns["_native_solver_lease_matches"](old_lease or {}))
        self.assertEqual(ns["_NATIVE_EXPECTED_SESSION"], "background-session")
        self.assertTrue(ns["LATEST_PAYLOAD"]["visionHealth"]["observationSuspended"])
        self.assertFalse(ns["LATEST_PAYLOAD"]["visionHealth"]["observationStopped"])
        bridge.send_control.assert_not_called()
        with patch.dict(sys.modules, {"live_shadow": SimpleNamespace(invalidate_match_shadow=Mock())}):
            _status(ns, "READY")
        self.assertIsNone(ns["_NATIVE_WAREHOUSE_FRAME_LEASE"])
        self.assertIsNone(ns["_NATIVE_SOLVER_LEASE"])
        fresh = _frame(ns, sequence=2)
        fresh["frame"].update(sourceTimestampNs=99_600_000_000, capturedAtNs=99_800_000_000)
        ns["_native_observation_event"](fresh)
        self.assertEqual(ns["LATEST_PAYLOAD"]["observationStatus"], "FRAME")
        self.assertEqual(ns["CURRENT_MATCH"].id, before["id"])

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

    def test_live_domain_loop_runs_after_the_manual_lock_is_released(self):
        # The UI thread takes this lock to paint status. Focusing or sampling
        # while the observation thread still holds it stops both threads.
        ns, _, _ = _isolated_main("background-readonly")
        _confirmed_start(ns)
        seen = {}

        def probe(data, frame):
            del data, frame
            lock = ns["_MANUAL_STATE_LOCK"]
            acquired = []

            def ui_thread():
                got = lock.acquire(timeout=0.4)
                acquired.append(got)
                if got:
                    lock.release()

            thread = threading.Thread(target=ui_thread)
            thread.start()
            thread.join(1.0)
            seen["called"] = True
            seen["ui_acquired_lock"] = bool(acquired and acquired[0] and not thread.is_alive())

        ns["_advance_authorized_live_domain_loop"] = probe
        ns["_native_observation_event"](_frame(ns))
        self.assertTrue(seen.get("called"))
        self.assertTrue(seen.get("ui_acquired_lock"))

    def test_live_loop_frame_does_not_open_the_host_bmp(self):
        ns, _, _ = _isolated_main("background-readonly")
        # Host metadata replaces both opening the live BMP and desktop capture.
        # No window, capture, ImageGrab or foreground-moving API is needed.
        data = dict(observationStatus='FRAME', frameSequence=1, capturedAtNs=99_000_000_000,
                    matchId='live', sourceMatchGeneration=1, round=1, engineFactsRevision=7)
        view = dict(schemaVersion='domain-planning-view.v1', planningOnly=True, inputActions=False,
                    frameSequence=1, readbackNs=data['capturedAtNs'], matchId='live',
                    matchGeneration=1, round=1, factsRevision=7, scene='AUCTION_READY', funds=200000)
        data['domainObservation'] = view
        self.assertEqual(ns['_native_domain_planning_view'](data), view)
        for key in ('frameSequence', 'readbackNs'):
            invalid = copy.deepcopy(data)
            invalid['domainObservation'][key] = 'other'
            self.assertIsNone(ns['_native_domain_planning_view'](invalid))
        data['observationStatus']='WAITING_FOR_FRESH_FRAME'
        self.assertEqual(ns['_native_domain_planning_view'](data),view,
                         'pixel/control metadata is not a qualified Solver fact')
        tree = ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
        names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertFalse(names & {'_live_loop_frame_image', '_park_assistant_and_focus_game',
                                 '_send_foreground_client_click', '_live_fee_confirm_if_visible'})

    def test_live_loop_uses_the_observed_frame_round(self):
        ns, _, _ = _isolated_main("background-readonly")
        fresh = CurrentMatch()
        fresh.id = "live-match"
        ns["CURRENT_MATCH"] = fresh
        ns["_NATIVE_DOMAIN_ACTION_BOOT_ID"] = "boot-live"
        ns["time"].time = lambda: 1_000
        ns["LATEST_PAYLOAD"] = {}
        data = {
            "round": 2,
            "sourceMatchGeneration": 3,
            "factsRevision": 4,
            "matchId": "live-match",
            "observationSessionId": "sess-live",
            "observationStatus": "FRAME",
            "scene": "IN_AUCTION",
            "target": {
                "targetHwnd": 7,
                "targetPid": 8,
                "identity": {"ProcessInstanceToken": 9},
            },
            "predictionSnapshot": None,
            "frozenPrediction": {},
        }
        view = ns["_live_loop_view"](data, "AUCTION", 2432426)
        self.assertIsNotNone(view)
        self.assertEqual(view["engine"]["round"], 2)
        self.assertIsNone(fresh.facts.get("roundNo"))

    def test_solver_admission_reads_the_engine_snapshot(self):
        from venue_box_catalog import load_catalog, solver_context_translation
        ns, _, _ = _isolated_main("background-readonly")
        tree = ast.parse((ROOT / "app/main.py").read_text(encoding="utf-8"))
        nodes = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef)
                 and node.name in {"_native_solver_admission", "_native_solver_admission_details"}]
        module = ast.Module(body=[ast.ImportFrom(
            module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
        admission_ns = {
            "solver_context_translation": solver_context_translation,
            "VENUE_BOX_CATALOG": load_catalog(None),
        }
        exec(compile(ast.fix_missing_locations(module), str(ROOT / "app/main.py"), "exec"), admission_ns)
        snapshot = {
            "schemaVersion": 7,
            "venueId": "venue-shanhu",
            "venue": "中级场 · 珊瑚场",
            "boxId": "box-shanhu-mother-of-pearl",
            "box": "螺钿宝箱",
            "entryCost": 5000,
            "fieldCondition": "standard",
            "q": 23,
            "goldAvg": 44317,
            "roundNo": 2,
        }
        merged = ns["_native_observed_solver_facts"]({}, snapshot)
        mapped, reason = admission_ns["_native_solver_admission"](merged)
        self.assertIsNone(reason)
        self.assertEqual(mapped.get("status"), "COMPATIBILITY_TRANSLATION")
        self.assertEqual(merged["q"], 23)
        self.assertEqual(merged["goldAvg"], 44317)
        self.assertEqual(merged["box"], "螺钿宝箱")
        kept = ns["_native_observed_solver_facts"]({"q": 17}, snapshot)
        self.assertEqual(kept["q"], 17)
        self.assertEqual(kept["goldAvg"], 44317)
        missing_average = dict(merged)
        missing_average["goldAvg"] = None
        _, blocked = admission_ns["_native_solver_admission"](missing_average)
        self.assertEqual(blocked, "缺失金色均价")


class NativeHostExitReceiptTests(unittest.TestCase):
    def test_committed_confirmation_survives_missing_host_repeat_and_rejection_is_forwarded(self):
        from native_observation import NativeObservationBridge
        receipt = dict(intentId='real-round-3', kind='Bid', status='CONFIRMED')
        commit = dict(type='domain.action.receipt.commit.request', observationSessionId='obs', receipt=receipt)
        rejected = dict(type='domain.action.dispatch.rejected', observationSessionId='obs',
                        intentId='real-round-3', reason='DURABLE_RECEIPT_COMMIT_FAILED:VISIBLE_RESULT_CONFIRMED')
        for accepted in (True, False):
            with self.subTest(accepted=accepted):
                events = []
                child = SimpleNamespace(stdout=io.StringIO('\n'.join(json.dumps(x) for x in (commit,rejected))), poll=lambda:0)
                bridge = NativeObservationBridge(str(ROOT),events.append,Mock(),
                    on_obligation_request=lambda _:dict(type='domain.action.receipt.ack',accepted=accepted))
                bridge.process=child
                bridge.send_control=Mock(return_value=True)
                bridge._record_status_event=Mock()
                bridge._read_stdout(child,None)
                confirmations=[x for x in events if x.get('type')=='domain.action.receipt']
                self.assertEqual(len(confirmations),int(accepted))
                if accepted: self.assertEqual(confirmations[0]['receipt'],receipt)
                self.assertIn(rejected,events)

    def test_real_diagnostics_delivers_receipt_and_following_frame(self):
        from native_observation import NativeObservationBridge
        from native_diagnostic_log import NativeDiagnosticLog
        receipt = {"type": "domain.action.receipt", "channel": "preparation",
                   "receipt": {"intentId": "prepare-fixture", "kind": "OpenInstrument", "status": "NOT_SENT"}}
        frame = {"type": "native_observation", "status": "FRAME", "observationSessionId": "fixture-session"}
        child = SimpleNamespace(stdout=io.StringIO("\n".join(json.dumps(x) for x in (receipt, frame))),
                                poll=lambda: 0)
        events = []
        with tempfile.TemporaryDirectory() as folder:
            bridge = NativeObservationBridge(str(ROOT), events.append, Mock())
            bridge.session_dir = Path(folder)
            bridge.process = child
            diagnostics = NativeDiagnosticLog(bridge.session_dir)
            try:
                bridge._read_stdout(child, diagnostics)
            finally:
                diagnostics.close()
            self.assertEqual(events[:2], [receipt, frame])
            self.assertEqual(json.loads((Path(folder) / 'domain-action-receipts.jsonl').read_text()), receipt)
            self.assertEqual(diagnostics.write_failures, 0)

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
