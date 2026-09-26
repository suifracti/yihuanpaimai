"""Worker process -> real WebSocket handler -> Main current match."""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "app", ROOT / "core"):
    sys.path.insert(0, str(path))

import main
from current_match import CurrentMatch
from live_match_transport import LiveMatchPublisher, LiveMatchReceiver, LiveMatchSession


class LiveMatchTransportTests(unittest.TestCase):
    def test_box_name_supplies_scoped_venue_and_keeps_conflicts_blocked(self):
        import importlib.util
        from venue_box_catalog import load_catalog, canonical_catalog_provenance, normalize_venue_from_box
        spec = importlib.util.spec_from_file_location(
            "box_venue_engine", ROOT / "architecture/v2/host/engine_v22/nte_engine_v22.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        engine = module.RealEngine.__new__(module.RealEngine)
        engine.current_match = CurrentMatch()
        engine.session_id = "box-test-session"
        engine.venue_catalog = load_catalog()
        engine.venue_catalog_provenance = canonical_catalog_provenance(engine.venue_catalog)
        self.assertEqual(normalize_venue_from_box(engine.venue_catalog, "完整的包裹")["venueId"], "venue-haibei")
        self.assertEqual(normalize_venue_from_box(engine.venue_catalog, "完整的保险箱")["venueId"], "venue-zhenzhu")
        self.assertIsNone(normalize_venue_from_box(engine.venue_catalog, "宝箱")["venueId"])
        self.assertEqual(normalize_venue_from_box(engine.venue_catalog,
            "实木宝箱 (中级藏品概率提升)")["venueId"], "venue-shanhu")
        self.assertIsNone(normalize_venue_from_box(engine.venue_catalog,
            "实木宝箱（未知效果）")["venueId"])
        ambiguous = copy.deepcopy(engine.venue_catalog)
        ambiguous["venues"][0]["boxes"].append(copy.deepcopy(ambiguous["venues"][1]["boxes"][0]))
        self.assertIsNone(normalize_venue_from_box(ambiguous, "机械宝箱")["venueId"])

        def observe(second, scene="IN_AUCTION", raw="机械宝箱"):
            stamp = f"2026-09-26T12:00:{second:02d}+00:00"
            ctx = {"scene": scene, "inAuction": scene == "IN_AUCTION", "round": 1,
                   "boxObservation": {"text": raw, "confidence": 0.99, "capturedAt": stamp}}
            engine._apply_pipeline_context(ctx, stamp)

        observe(1, "AUCTION_LOADING")
        observe(2)
        observe(2)  # Re-reading the same OCR evidence cannot confirm it.
        self.assertIsNone(engine.current_match.facts["venueId"])
        observe(3)
        facts = engine.current_match.facts
        self.assertEqual(facts["venueId"], "venue-shanhu")
        self.assertEqual(facts["entryCost"], 5000)
        self.assertEqual(facts["boxId"], "box-shanhu-mechanical")
        self.assertIsNone(facts["fieldCondition"])
        self.assertEqual(engine.current_match.field_states["venueId"].evidence_refs["sourceKind"], "observed_box_catalog_membership")
        engine.current_match.apply_facts({"q": 17, "goldAvg": 55444}, source="vision", intent="observe")
        self.assertEqual(main._native_solver_admission(engine.current_match.facts)[1], "缺失场地规则")
        engine.current_match.apply_facts({"box": "机械宝箱 · 科技类概率提升"}, source="manual", intent="confirm")
        observe(4)
        self.assertEqual(engine.current_match.facts["auctionEvidence"]["venueFromBox"]["status"], "RESOLVED")
        engine.current_match.apply_facts({"venueId": "venue-haibei", "venue": "海贝场", "entryCost": 0}, source="manual", intent="confirm")
        observe(5)
        facts = engine.current_match.facts
        self.assertEqual(facts["venueId"], "venue-haibei")
        self.assertEqual(facts["entryCost"], 0)
        self.assertIn("冲突", main._native_solver_admission(facts)[1])
        engine.current_match = CurrentMatch()
        observe(6)
        self.assertIsNone(engine.current_match.facts["venueId"])
        engine.session_id = "another-session"
        observe(7)
        self.assertIsNone(engine.current_match.facts["venueId"])

    def test_native_match_summary_explains_gate_and_never_defaults_unknown_rule(self):
        current = CurrentMatch()
        current.apply_facts({"q": 17, "goldAvg": 55444, "purpleCount": 9}, source="vision", intent="observe")
        event = {
            "observationProfile": "native-readonly-v1",
            "observationStatus": "FRAME",
            "scene": "IN_AUCTION",
            "inAuction": True,
            "solverStatus": "incomplete",
            "solverMissingReason": "缺失会场",
            "visionHealth": {"status": "READY", "profile": "native-readonly-v1", "stage": "native-ready", "freshnessMs": 40},
        }
        with patch.object(main, "CURRENT_MATCH", current), \
             patch.object(main, "LATEST_PAYLOAD", event), \
             patch.object(main, "native_observation_enabled", return_value=True), \
             patch.object(main, "_native_solver_lease_matches", return_value=True), \
             patch.object(main, "_current_match_solver_sidecar", return_value=(None, None)):
            payload = main.get_current_match_presentation_summary()

        self.assertEqual(payload["solverStatus"], "incomplete")
        self.assertEqual(payload["solverAdmission"]["blockingReasons"], ["缺失会场", "缺失入场费", "缺失场地规则"])
        self.assertIsNone(payload["environment"]["fieldCondition"])
        self.assertEqual(payload["environment"]["fieldConditionName"], "待确认规则")
        self.assertEqual(payload["facts"]["purpleCount"], 9)

        settled_event = {**event, "scene": "SETTLEMENT", "inAuction": False, "solverStatus": "valid"}
        with patch.object(main, "CURRENT_MATCH", current), \
             patch.object(main, "LATEST_PAYLOAD", settled_event), \
             patch.object(main, "native_observation_enabled", return_value=True), \
             patch.object(main, "_native_solver_lease_matches", return_value=True), \
             patch.object(main, "_current_match_solver_sidecar", return_value=(None, None)):
            settled = main.get_current_match_presentation_summary()
        self.assertEqual(settled["solverStatus"], "paused")
        self.assertTrue(settled["nativeInvalidated"])
        self.assertEqual(settled["solverMissingReason"], "本局已结算，实时建议已停止")

    def test_native_match_summary_error_fallback_never_invents_rule_or_fee(self):
        current = CurrentMatch()
        with patch.object(main, "CURRENT_MATCH", current), \
             patch.object(main, "native_observation_enabled", return_value=True), \
             patch.object(main, "_current_match_solver_sidecar", side_effect=RuntimeError("projection failure")):
            payload = main.get_current_match_presentation_summary()

        self.assertEqual(payload["solverStatus"], "paused")
        self.assertIn("建议已暂停", payload["solverMissingReason"])
        self.assertIsNone(payload["environment"]["fieldCondition"])
        self.assertEqual(payload["environment"]["fieldConditionName"], "待确认规则")
        self.assertIsNone(payload["environment"]["entryCost"])
        self.assertIsNone(payload["lobby"]["entryCost"])
        self.assertEqual(payload["lobby"]["lobbyToolGroup"], "未知/待识别")
        self.assertIsNone(payload["facts"]["fieldCondition"])
        self.assertIsNone(payload["facts"]["entryCost"])
        self.assertIsNone(payload["prediction"])

    def test_native_restart_seeds_only_temporary_pause(self):
        from unittest.mock import Mock
        current = CurrentMatch()
        current.apply_facts({"q": 19}, source="manual", intent="confirm")
        target = {"identity": {"Hwnd": 11, "Pid": 22, "ProcessInstanceToken": 33}}
        for reason, should_resume in (
            ("focus-lost", True),
            ("observation-frame-timeout", True),
            ("scene-boundary:SETTLEMENT", False),
        ):
            bridge = Mock()
            with patch.object(main, "CURRENT_MATCH", current), \
                 patch.object(main, "NATIVE_OBSERVATION_BRIDGE", None), \
                 patch.object(main, "NativeObservationBridge", return_value=bridge), \
                 patch.object(main, "_native_publish_health"), \
                 patch.object(main, "LATEST_PAYLOAD", {"visionHealth": {"reason": reason, "pausedMatchId": current.id}, "target": target}), \
                 patch.dict(os.environ, {"NTE_DISABLE_VISION": "0"}):
                main._start_native_observation_locked(resume_same_match=should_resume)
                seed = bridge.start.call_args.kwargs["resume_state"]
                if should_resume:
                    self.assertEqual(seed["currentMatch"]["id"], current.id)
                    self.assertEqual(seed["currentMatch"]["q"], 19)
                    self.assertTrue(seed["currentMatch"]["fieldStates"]["q"]["protected"])
                    self.assertEqual(seed["target"], target)
                else:
                    self.assertIsNone(seed)

        bridge = Mock()
        with patch.object(main, "CURRENT_MATCH", current), \
             patch.object(main, "NATIVE_OBSERVATION_BRIDGE", None), \
             patch.object(main, "NativeObservationBridge", return_value=bridge), \
             patch.object(main, "_native_publish_health"), \
             patch.object(main, "LATEST_PAYLOAD", {"visionHealth": {"reason": "focus-lost", "pausedMatchId": current.id}, "target": target}), \
             patch.dict(os.environ, {"NTE_DISABLE_VISION": "0"}):
            main._start_native_observation_locked()
            self.assertIsNone(bridge.start.call_args.kwargs["resume_state"])

        bridge = Mock()
        with patch.object(main, "CURRENT_MATCH", current), \
             patch.object(main, "NATIVE_OBSERVATION_BRIDGE", None), \
             patch.object(main, "NativeObservationBridge", return_value=bridge), \
             patch.object(main, "_native_publish_health"), \
             patch.object(main, "LATEST_PAYLOAD", {"visionHealth": {"reason": "focus-lost", "pausedMatchId": "previous-match"}, "target": target}), \
             patch.dict(os.environ, {"NTE_DISABLE_VISION": "0"}):
            main._start_native_observation_locked(resume_same_match=True)
            self.assertIsNone(bridge.start.call_args.kwargs["resume_state"])

    def test_native_resume_seed_restores_manual_protection_in_engine(self):
        import importlib.util
        import tempfile
        from types import SimpleNamespace
        spec = importlib.util.spec_from_file_location(
            "native_resume_engine", ROOT / "architecture/v2/host/engine_v22/nte_engine_v22.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        current = CurrentMatch()
        current.apply_facts({"box": "琉璃宝箱", "q": 17}, source="vision", intent="observe")
        current.apply_facts({"q": 19}, source="manual", intent="confirm")
        with tempfile.TemporaryDirectory() as directory:
            engine = module.RealEngine.__new__(module.RealEngine)
            engine.state_path = Path(directory) / "engine_state.json"
            engine.state_path.write_text(json.dumps({
                "currentMatch": current.snapshot(), "controlRevision": 4,
            }, ensure_ascii=False), encoding="utf-8")
            engine.current_match = CurrentMatch()
            engine.pipeline = SimpleNamespace(current_context={})
            engine.log = lambda *args, **kwargs: None
            engine.data_origin = "live-trial"
            engine.awaiting_exit = False
            engine._restore_state_if_present()
            self.assertEqual(engine.current_match.id, current.id)
            self.assertEqual(engine.current_match.facts["box"], "琉璃宝箱")
            self.assertTrue(engine.current_match.field_states["q"].protected)
            self.assertEqual(engine._apply_manual_overrides({"q": 3})["q"], 19)
            self.assertEqual(engine.control_revision, 4)

    def test_native_worker_hands_off_sourced_lobby_venue_only_to_clean_entered_match(self):
        import importlib.util
        from types import SimpleNamespace
        from venue_box_catalog import canonical_catalog_provenance, load_catalog

        spec = importlib.util.spec_from_file_location(
            "native_venue_projection_engine", ROOT / "architecture/v2/host/engine_v22/nte_engine_v22.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        observed_intel_only = {"q": 17, "goldAvg": 55444, "purpleCount": 9}
        self.assertEqual(main._native_solver_admission(observed_intel_only)[1], "缺失会场")
        _, reason, explanation = main._native_solver_admission_details(observed_intel_only)
        self.assertEqual(reason, "缺失会场")
        self.assertEqual(explanation["blockingReasons"], ["缺失会场", "缺失入场费", "缺失场地规则"])
        requirement_status = {item["key"]: item["status"] for item in explanation["requirements"]}
        self.assertEqual(requirement_status["q"], "available")
        self.assertEqual(requirement_status["goldAvg"], "available")
        self.assertEqual(requirement_status["venueId"], "missing")
        self.assertEqual(requirement_status["entryCost"], "missing")
        self.assertEqual(requirement_status["fieldCondition"], "missing")

        engine = module.RealEngine.__new__(module.RealEngine)
        engine.current_match = CurrentMatch()
        engine.current_match.source = "vision_v22"
        engine.current_match.apply_facts(
            {
                "q": 17, "goldAvg": 55444, "purpleCount": 9,
                "venueId": "venue-shanhu", "venue": "珊瑚场", "entryCost": 5000,
                "box": "旧局箱型", "fieldCondition": "standard", "knownGold": "旧局藏品",
            },
            source="manual", intent="confirm",
        )
        old_match_id = engine.current_match.id
        engine.venue_catalog = load_catalog()
        engine.venue_catalog_provenance = canonical_catalog_provenance(engine.venue_catalog)
        engine.session_id = "native-live-lobby-session"
        engine.data_origin = "live-trial"
        engine.observation_target_identity = {
            "targetHwnd": 101, "targetPid": 202, "targetGeneration": 0,
            "processInstanceToken": 303,
        }
        engine.manual_overrides = {"q": 17, "box": "旧局箱型"}
        engine.awaiting_exit = False
        engine._active_pipeline_match_generation = 1
        engine._pending_lobby_venue = None
        engine._identity_scope_key = (old_match_id, 1, 1, 0, "warehouse", 5, "auto")
        engine._identity_last_committed_sequence = {}
        engine._identity_generation_lock = __import__("threading").Lock()
        engine._identity_invalidation_generation = 0
        engine._identity_analyzer = None
        engine._warehouse_activity_sources = {("old",): {"matchId": old_match_id}}
        engine._warehouse_review_vision = {"old": True}
        engine._warehouse_review_scope = {"old": True}
        engine.pipeline = SimpleNamespace(
            _match_gen=1, _session_generation=0, current_context={}
        )
        engine.last_context = {"scene": "IN_AUCTION", "matchGeneration": 1}
        engine._persist_history = lambda: "PERSISTED_DRAFT"
        invalidations = []
        engine._invalidate_deferred_identity = lambda reason: invalidations.append(reason) or 1
        engine.log = lambda *args, **kwargs: None

        lobby_time = "2026-09-24T11:40:22.140000+00:00"
        engine.pipeline._match_gen = 2
        engine._apply_observation_context(
            {
                "scene": "AUCTION_LOBBY", "inAuction": False, "inLobby": True,
                "round": 0, "matchGeneration": 2,
                "lobbyVenueKey": "shanhu", "lobbyVenue": "珊瑚场",
                "lobbyVenueLabel": "中级场 · 珊瑚场", "lobbyEntryCost": 5000,
                "lobbyVenueSource": "template", "lobbyVenueScore": 0.99760913848877,
                "lobbyVenueObservedAt": lobby_time,
                # A lobby output must not project stale/unsupported business fields.
                "q": 17, "goldAvg": 55444, "purpleCount": 9,
                "box": "旧局箱型", "fieldCondition": "standard", "knownGold": "旧局藏品",
            },
            {"header": {"sequence": 6}},
            lobby_time,
        )
        self.assertNotEqual(engine.current_match.id, old_match_id)
        self.assertIsNone(engine.current_match.facts["q"])
        self.assertIsNone(engine.current_match.facts["goldAvg"])
        self.assertIsNone(engine.current_match.facts["purpleCount"])
        self.assertIsNone(engine.current_match.facts["box"])
        self.assertIsNone(engine.current_match.facts["fieldCondition"])
        self.assertEqual(engine.current_match.facts["knownGold"], "")
        self.assertEqual(engine.manual_overrides, {})
        self.assertEqual(engine._pending_lobby_venue["facts"]["venueId"], "venue-shanhu")
        self.assertEqual(engine._pending_lobby_venue["facts"]["entryCost"], 5000)
        self.assertEqual(engine._pending_lobby_venue["frameSequence"], 6)
        self.assertEqual(engine._pending_lobby_venue["observationSessionId"], engine.session_id)
        self.assertEqual(engine._pending_lobby_venue["targetIdentity"], engine.observation_target_identity)
        self.assertTrue(invalidations)
        self.assertIsNone(main._native_accept_observation_locked({
            "scene": "AUCTION_LOBBY", "inAuction": False, "freshnessMs": 0,
            "target": {"targetHwnd": 101, "targetPid": 202},
        }))

        # A failed fresh recognition must retire a previously staged venue;
        # another accepted lobby recognition may stage it again.
        engine._apply_observation_context(
            {
                "scene": "AUCTION_LOBBY", "inAuction": False, "inLobby": True,
                "round": 0, "matchGeneration": 2,
                "lobbyVenueKey": None, "lobbyVenue": None,
                "lobbyVenueSource": "unrecognized", "lobbyVenueObservedAt": None,
            },
            {"header": {"sequence": 7}},
            "2026-09-24T11:40:23.000000+00:00",
        )
        self.assertIsNone(engine._pending_lobby_venue)
        lobby_time = "2026-09-24T11:40:24.000000+00:00"
        engine._apply_observation_context(
            {
                "scene": "AUCTION_LOBBY", "inAuction": False, "inLobby": True,
                "round": 0, "matchGeneration": 2,
                "lobbyVenueKey": "shanhu", "lobbyVenue": "珊瑚场",
                "lobbyVenueLabel": "中级场 · 珊瑚场", "lobbyEntryCost": 5000,
                "lobbyVenueSource": "template", "lobbyVenueScore": 0.99760913848877,
                "lobbyVenueObservedAt": lobby_time,
            },
            {"header": {"sequence": 8}},
            lobby_time,
        )
        pending_lobby_venue = copy.deepcopy(engine._pending_lobby_venue)
        self.assertEqual(pending_lobby_venue["frameSequence"], 8)

        engine.pipeline._match_gen = 2
        engine._apply_observation_context(
            {
                "scene": "AUCTION_LOADING", "inAuction": False, "isLoading": True,
                "loadingDirection": "to_auction", "matchGeneration": 2,
            },
            {"header": {"sequence": 9}},
            "2026-09-24T11:40:25.000000+00:00",
        )
        self.assertIsNotNone(engine._pending_lobby_venue)

        # An ambiguous entry frame withdraws eligibility without turning cached
        # data into new facts or losing a still-scoped lobby candidate.
        with patch.object(module.time, "monotonic", return_value=100.0):
            engine._apply_observation_context(
                {"scene": "UNKNOWN", "inAuction": False, "q": 999, "matchGeneration": 2},
                {"header": {"sequence": 10}}, "2026-09-24T11:40:26+00:00")
        self.assertIsNotNone(engine._pending_lobby_venue)
        self.assertIsNone(engine.current_match.facts["q"])
        self.assertIsNone(main._native_accept_observation_locked({
            "scene": "UNKNOWN", "inAuction": False, "freshnessMs": 0,
            "target": {"targetHwnd": 101, "targetPid": 202}}))
        expired = copy.copy(engine)
        expired._pending_lobby_venue = copy.deepcopy(engine._pending_lobby_venue)
        with patch.object(module.time, "monotonic", return_value=110.0):
            expired._advance_match_lifecycle({"scene": "UNKNOWN"}, frame_sequence=11,
                                            captured_at="2026-09-24T11:40:36+00:00")
        self.assertIsNone(expired._pending_lobby_venue)
        # Finish the existing real-entry handoff checks inside the grace window.
        engine._entry_unknown_since = module.time.monotonic()

        # The box value is from a saved active-frame result; rule is explicitly
        # unknown in that source and must remain absent. Lobby values survive
        # only when session, target, match id, and pipeline entry generation link.
        active_time = "2026-09-24T11:40:30.000000+00:00"
        engine.pipeline._match_gen = 3
        engine._apply_observation_context(
            {
                "scene": "IN_AUCTION", "inAuction": True, "round": 5,
                "matchGeneration": 3, "q": 22, "goldAvg": 85410,
                "purpleCount": None, "box": "螺钿宝箱 · 古董类概率提升",
                "fieldCondition": "unknown", "entryCost": 0,
            },
            {"header": {"sequence": 10}},
            active_time,
        )
        facts = engine.current_match.facts
        self.assertEqual(facts["venueId"], "venue-shanhu")
        self.assertEqual(facts["venue"], "珊瑚场")
        self.assertEqual(facts["entryCost"], 5000)
        self.assertEqual(facts["q"], 22)
        self.assertEqual(facts["goldAvg"], 85410)
        self.assertEqual(facts["box"], "螺钿宝箱 · 古董类概率提升")
        self.assertIsNone(facts["fieldCondition"])
        self.assertIsNone(facts["purpleCount"])
        self.assertEqual(facts["knownGold"], "")
        self.assertIsNone(engine._pending_lobby_venue)
        venue_state = engine.current_match.field_states["venueId"]
        self.assertEqual(venue_state.source, "vision")
        self.assertEqual(venue_state.evidence_refs["sourceKind"], "lobby_venue_observation")
        self.assertEqual(venue_state.evidence_refs["lobbyFrameSequence"], 8)
        self.assertEqual(venue_state.evidence_refs["entryFrameSequence"], 10)
        self.assertEqual(venue_state.evidence_refs["matchId"], engine.current_match.id)
        self.assertEqual(venue_state.observed_at, lobby_time)
        self.assertEqual(main._native_solver_admission(facts)[1], "缺失场地规则")

        stale_session = module.RealEngine.__new__(module.RealEngine)
        stale_session.current_match = CurrentMatch()
        stale_session.current_match.id = pending_lobby_venue["matchId"]
        stale_session.session_id = "a-reconnected-observation-session"
        stale_session.observation_target_identity = copy.deepcopy(engine.observation_target_identity)
        stale_session._pending_lobby_venue = copy.deepcopy(pending_lobby_venue)
        stale_session._active_pipeline_match_generation = None
        stale_session.manual_overrides = {}
        stale_session.last_context = {"scene": "AUCTION_LOADING"}
        stale_session.log = lambda *args, **kwargs: None
        self.assertIsNone(stale_session._advance_match_lifecycle(
            {"scene": "IN_AUCTION", "matchGeneration": 3},
            frame_sequence=11,
            captured_at=active_time,
        ))
        self.assertIsNone(stale_session.current_match.facts["venueId"])

        stale_entry = module.RealEngine.__new__(module.RealEngine)
        stale_entry.current_match = CurrentMatch()
        stale_entry.current_match.id = pending_lobby_venue["matchId"]
        stale_entry.session_id = pending_lobby_venue["observationSessionId"]
        stale_entry.observation_target_identity = copy.deepcopy(pending_lobby_venue["targetIdentity"])
        stale_entry._pending_lobby_venue = copy.deepcopy(pending_lobby_venue)
        stale_entry._active_pipeline_match_generation = None
        stale_entry.manual_overrides = {}
        stale_entry.last_context = {"scene": "AUCTION_LOADING"}
        stale_entry.log = lambda *args, **kwargs: None
        self.assertIsNone(stale_entry._advance_match_lifecycle(
            {
                "scene": "IN_AUCTION",
                "matchGeneration": pending_lobby_venue["expectedEntryMatchGeneration"] + 1,
            },
            frame_sequence=12,
            captured_at=active_time,
        ))
        self.assertIsNone(stale_entry.current_match.facts["venueId"])

        unknown_engine = module.RealEngine.__new__(module.RealEngine)
        unknown_engine.current_match = CurrentMatch()
        unknown_engine.venue_catalog = engine.venue_catalog
        unknown_engine.venue_catalog_provenance = engine.venue_catalog_provenance
        self.assertEqual(
            unknown_engine._lobby_venue_handoff_facts({
                "scene": "AUCTION_LOBBY", "lobbyVenueKey": "shanhu",
                "lobbyVenueSource": "unrecognized",
            }),
            {},
        )
        unknown_engine._apply_pipeline_context(
            {
                "scene": "IN_AUCTION", "lobbyVenueKey": "shanhu",
                "lobbyVenue": "中级场 · 珊瑚场", "lobbyVenueLabel": "珊瑚场",
                "lobbyEntryCost": 5000, "lobbyVenueSource": "template",
                # A cached lobby recognition is not itself proof that this
                # active frame entered the corresponding match.
                "venue": "珊瑚场",
            },
            active_time,
        )
        self.assertIsNone(unknown_engine.current_match.facts["venueId"])
        self.assertIsNone(unknown_engine.current_match.facts["entryCost"])

        valid_instance = {
            "q": 12, "goldAvg": 74379, "purpleCount": 7,
            "venueId": "venue-shanhu", "venue": "珊瑚场", "entryCost": 5000,
            "fieldCondition": "standard",
        }
        mapped, reason = main._native_solver_admission(valid_instance)
        self.assertIsNone(reason)
        self.assertEqual(mapped["status"], "COMPATIBILITY_TRANSLATION")

    def test_native_pause_preserves_facts_and_rejects_late_session(self):
        current = CurrentMatch()
        current.apply_facts({"q": 17}, source="manual", intent="confirm")
        before = copy.deepcopy(current.snapshot())
        def event(status, session):
            return {"sourceKind": "native_wgc", "inputActions": False,
                    "formalHistoryWriter": False, "status": status,
                    "observationSessionId": session}
        with patch.object(main, "CURRENT_MATCH", current), \
             patch.object(main, "LATEST_PAYLOAD", {}), \
             patch.object(main, "LATEST_VISION_PAYLOAD", {}), \
             patch.object(main, "_NATIVE_EXPECTED_SESSION", "old"), \
             patch.object(main, "_LIVE_VISION_ACTIVE", True), \
             patch.object(main, "_LIVE_VISION_MATCH_ID", current.id), \
             patch.object(main, "_native_post_main_status"), \
             patch.object(main, "WS_EVENT_LOOP", None):
            main._native_observation_event(event("PAUSED", "old"))
            self.assertEqual(current.snapshot(), before)
            self.assertTrue(main.LATEST_PAYLOAD["nativeInvalidated"])
            paused = copy.deepcopy(main.LATEST_PAYLOAD)
            main._native_observation_event(event("FRAME", "old"))
            self.assertEqual(main.LATEST_PAYLOAD, paused)
            main._native_observation_event(event("STARTING", "new"))
            started = copy.deepcopy(main.LATEST_PAYLOAD)
            main._native_observation_event(event("PAUSED", "old"))
            self.assertEqual(main.LATEST_PAYLOAD, started)
            self.assertEqual(main._NATIVE_EXPECTED_SESSION, "new")

    def test_reconnect_handshake_restores_gui_corrections_and_retires_old_socket(self):
        async def run():
            current = CurrentMatch()
            current.apply_facts({"q": 9})
            with patch.object(main, "CURRENT_MATCH", current), \
                 patch.object(main, "_LIVE_CONTROL_REVISION", 3), \
                 patch.object(main, "_LIVE_CONTROL_WAITING_EXIT", True), \
                 patch.object(main, "_LIVE_MANUAL_OVERRIDES", {"q": 9}), \
                 patch.object(main, "LATEST_PAYLOAD", {}):
                async with main.websockets.serve(main.ws_handler, "127.0.0.1", 0) as server:
                    url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                    async with main.websockets.connect(url) as old:
                        await old.send(json.dumps({"type": "vision_worker_hello"}))
                        first = json.loads(await asyncio.wait_for(old.recv(), 3))
                        self.assertEqual(first["revision"], 3)
                        async with main.websockets.connect(url) as replacement:
                            await replacement.send(json.dumps({"type": "vision_worker_hello"}))
                            resumed = json.loads(await asyncio.wait_for(replacement.recv(), 3))
                            self.assertEqual(resumed["snapshot"]["id"], current.id)
                            self.assertEqual(resumed["facts"], {"q": 9})
                            self.assertTrue(resumed["reset"])
                            with self.assertRaises(main.websockets.exceptions.ConnectionClosed):
                                await asyncio.wait_for(old.recv(), 3)
        asyncio.run(run())

    def test_worker_frame_does_not_start_native_capture(self):
        import numpy as np
        with patch.object(main, "maybe_trigger_auto_warehouse_capture") as capture:
            main.process_live_game_frame(
                np.zeros((2, 2, 3), dtype=np.uint8), game_hwnd=1,
                ctx={"scene": "UNKNOWN"}, run_capture_orchestration=False)
            capture.assert_not_called()

    def test_settlement_scene_alone_does_not_prove_capture_stability(self):
        before = copy.deepcopy(main.LATEST_PAYLOAD)
        vision_before = copy.deepcopy(main.LATEST_VISION_PAYLOAD)
        try:
            main.LATEST_VISION_PAYLOAD.clear()
            main.LATEST_PAYLOAD.clear()
            main.LATEST_PAYLOAD.update({"scene": "SETTLEMENT", "isSettlement": True,
                                        "hadSettlement": True, "gameHwnd": 1})
            self.assertFalse(main.get_production_warehouse_bindings()["stable"])
            main.LATEST_PAYLOAD["settlementStable"] = True
            self.assertTrue(main.get_production_warehouse_bindings()["stable"])
        finally:
            main.LATEST_VISION_PAYLOAD.clear()
            main.LATEST_VISION_PAYLOAD.update(vision_before)
            main.LATEST_PAYLOAD.clear()
            main.LATEST_PAYLOAD.update(before)

    def test_session_exit_changes_id_but_temporary_window_loss_does_not(self):
        current, session = CurrentMatch(), LiveMatchSession()
        original = current.id
        current.apply_facts({"q": 12})
        for scene in ("IN_AUCTION", "UNKNOWN", "IN_AUCTION", "SETTLEMENT"):
            session.observe({"scene": scene}, current)
            self.assertEqual(current.id, original)
        ctx = {"scene": "AUCTION_LOBBY"}
        session.observe(ctx, current)
        self.assertNotEqual(current.id, original)
        self.assertIsNone(current.facts["q"])
        self.assertEqual(ctx["matchId"], current.id)
        second = current.id
        for scene in ("AUCTION_LOBBY", "AUCTION_LOADING", "IN_AUCTION"):
            session.observe({"scene": scene}, current)
            self.assertEqual(current.id, second)
    def test_ordering_retired_ids_and_local_capture_preservation(self):
        publisher, receiver = LiveMatchPublisher(), LiveMatchReceiver()
        worker, mirror = CurrentMatch(), CurrentMatch()
        worker.apply_facts({"q": 12, "isAcquired": False})
        first = publisher.attach({}, worker)["visionState"]
        self.assertTrue(receiver.apply(first, mirror))
        self.assertEqual(mirror.id, worker.id)
        self.assertEqual(mirror.facts["q"], 12)
        self.assertIs(mirror.facts["isAcquired"], False)
        mirror.facts["warehouseOccupancy"] = {"local": "capture"}
        self.assertTrue(receiver.apply(publisher.attach({}, worker)["visionState"], mirror))
        self.assertEqual(mirror.facts["warehouseOccupancy"], {"local": "capture"})
        self.assertFalse(receiver.apply(first, mirror))
        worker.begin_next_match()
        self.assertTrue(receiver.apply(publisher.attach({}, worker)["visionState"], mirror))
        self.assertIsNone(mirror.facts["q"])
        self.assertIsNone(mirror.facts["warehouseOccupancy"])
        first["sequence"] = 100
        self.assertFalse(receiver.apply(first, mirror))

    def test_separate_process_delivers_two_matches_through_real_ws_handler(self):
        async def run():
            current = CurrentMatch()
            saved_payload = copy.deepcopy(main.LATEST_PAYLOAD)
            main.LATEST_PAYLOAD.clear()
            child = None
            try:
                with patch.object(main, "CURRENT_MATCH", current), patch.object(main, "_LIVE_CONTROL_REVISION", 0):
                    async with main.websockets.serve(main.ws_handler, "127.0.0.1", 0) as server:
                        port = server.sockets[0].getsockname()[1]
                        url = f"ws://127.0.0.1:{port}"
                        async with main.websockets.connect(url) as observer:
                            script = '''
import asyncio, json, sys
import websockets
from current_match import CurrentMatch
from live_match_transport import LiveMatchPublisher
async def run():
    publisher = LiveMatchPublisher()
    current = CurrentMatch()
    async with websockets.connect(sys.argv[1]) as ws:
        await ws.send(json.dumps({"type": "vision_worker_hello"}))
        while json.loads(await ws.recv()).get("action") != "worker_resume":
            pass
        current.id = "worker_first"
        current.apply_facts({"q": 12, "goldCount": 4, "isAcquired": False})
        old = publisher.attach({"scene": "IN_AUCTION"}, current)
        await ws.send(json.dumps(old))
        current.begin_next_match()
        current.id = "worker_second"
        current.apply_facts({"q": 9})
        await ws.send(json.dumps(publisher.attach({"scene": "IN_AUCTION"}, current)))
        old["visionState"]["sequence"] = 100
        await ws.send(json.dumps(old))
        await asyncio.sleep(0.1)
asyncio.run(run())
'''
                            env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
                            child = await asyncio.create_subprocess_exec(
                                sys.executable, "-c", script, url, env=env,
                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                            first = json.loads(await asyncio.wait_for(observer.recv(), 15))
                            second = json.loads(await asyncio.wait_for(observer.recv(), 15))
                            self.assertEqual(first["visionState"]["snapshot"]["id"], "worker_first")
                            self.assertEqual(second["visionState"]["snapshot"]["id"], "worker_second")
                            stdout, stderr = await asyncio.wait_for(child.communicate(), 15)
                            self.assertEqual(child.returncode, 0, stderr.decode(errors="replace"))
                            self.assertEqual(current.id, "worker_second")
                            self.assertEqual(current.facts["q"], 9)
                            self.assertIsNone(current.facts["goldCount"])
                            self.assertIsNone(current.facts["isAcquired"])
                            with self.assertRaises(asyncio.TimeoutError):
                                await asyncio.wait_for(observer.recv(), 0.05)
            finally:
                if child is not None and child.returncode is None:
                    child.kill()
                    await child.communicate()
                main.LATEST_PAYLOAD.clear()
                main.LATEST_PAYLOAD.update(saved_payload)
        asyncio.run(run())
