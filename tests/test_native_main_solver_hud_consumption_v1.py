# -*- coding: utf-8 -*-
"""Issue #21: Native Engine facts reaching Main / Solver / HUD consumers.

Production chain (not a hand-built canonical dict):
  TrackedSlotBlob.to_dict
  → RealEngine._warehouse_fact_projection
  → Engine CurrentMatch.snapshot  (Host clones this onto FRAME.currentMatch)
  → LiveMatchReceiver.apply onto Main CURRENT_MATCH
  → CurrentMatch.to_canonical → canonical_to_v06_solver_input  (Main solverInput)
  → _native_observation_event → attach_live_shadow ctx        (HUD live solver)
  → overlay / presentation summary

PR #18 already closed the projection/to_canonical flag drop. This file checks
the consumers after that mirror.
"""

from __future__ import annotations

import copy
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "core"))

from current_match import CurrentMatch  # noqa: E402
from live_match_transport import LiveMatchReceiver  # noqa: E402
from v06_adapter import canonical_to_v06_solver_input, known_token_entries  # noqa: E402

import tests.test_solver_warehouse_candidate_contract_v1 as warehouse_contract  # noqa: E402


def _install_main_gui_stubs():
    """This interpreter has no mss/win32/cv2. Import Main with bounded GUI stubs."""
    import types
    warehouse_contract._install_optional_vision_stubs()
    numpy = sys.modules["numpy"]
    if not hasattr(numpy, "frombuffer"):
        numpy.frombuffer = lambda *a, **k: None
        numpy.array = lambda *a, **k: None
        numpy.zeros = lambda *a, **k: None
    cv2 = sys.modules["cv2"]
    if not hasattr(cv2, "imdecode"):
        cv2.imdecode = lambda *a, **k: None
        cv2.IMREAD_UNCHANGED = -1
    for name in (
        "mss", "websockets", "win32gui", "win32con", "win32process",
        "win32api", "win32ui", "pythoncom", "pywintypes",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))


def _load_main():
    _install_main_gui_stubs()
    import main as app_main
    return app_main

CANDIDATE_A = warehouse_contract.CANDIDATE_A
CANDIDATE_B = warehouse_contract.CANDIDATE_B
OR_TOKEN = warehouse_contract.OR_TOKEN
CONFIRMED_GOLD = warehouse_contract.CONFIRMED_GOLD

_NATIVE_STATE_NAMES = (
    "_NATIVE_OBSERVATION_RECEIVER", "_NATIVE_OBSERVATION_SESSION",
    "_NATIVE_EXPECTED_SESSION", "_NATIVE_OBSERVATION_SEQUENCE",
    "_NATIVE_OBSERVATION_LAST_FRAME_NS", "_NATIVE_SOLVER_INVALIDATION_GENERATION",
    "_NATIVE_SOLVER_LEASE", "_LIVE_VISION_ACTIVE", "_LIVE_VISION_MATCH_ID",
    "_NATIVE_WINDOW_MODE_CONFIRMED",
)



def _known_gold_text(value):
    if isinstance(value, list):
        return "+".join(str(part) for part in value if part)
    return str(value or "")


def _engine_projected_slots(stable=True, unstable=False):
    project = warehouse_contract._warehouse_fact_projection()
    slots = []
    if stable:
        slots.append(warehouse_contract._tracked_vision_slot(
            col=0, row=0, w=4, h=1, rarity="gold",
            evidence="CANDIDATE_SET", confirmed=True, shape_locked=True,
            names=[CANDIDATE_A, CANDIDATE_B],
        ))
    if unstable:
        slots.append(warehouse_contract._tracked_vision_slot(
            col=6, row=0, w=4, h=1, rarity="gold",
            evidence="RARITY_AND_SHAPE", confirmed=False, shape_locked=True,
            names=[CANDIDATE_A, CANDIDATE_B], track_id=2,
        ))
    return project({"slots": slots})["slots"]


def _engine_snapshot(*, match_id, facts_revision, round_no, warehouse_slots, extra_facts=None):
    engine = CurrentMatch()
    engine.id = match_id
    engine.source = "vision_v22"
    patch = {
        "venueId": "venue-shanhu",
        "venue": "中级场 · 珊瑚场",
        "boxId": "box-shanhu-glass",
        "box": "琉璃宝箱 · 宝石类概率提升",
        "fieldCondition": "standard",
        "q": 18,
        "goldAvg": 71190,
        "purpleCount": 9,
        "entryCost": 5000,
        "roundNo": round_no,
        "warehouse": {"slots": warehouse_slots},
    }
    if extra_facts:
        patch.update(extra_facts)
    engine.apply_facts(patch, source="vision", intent="observe")
    snapshot = engine.snapshot()
    snapshot["id"] = match_id
    snapshot["schemaVersion"] = 7
    snapshot["lifecycleStatus"] = "DRAFT"
    snapshot["factsRevision"] = facts_revision
    return snapshot


def _vision_state(snapshot, *, session="native:issue-21", sequence=1):
    return {
        "version": 1,
        "session": session,
        "sequence": sequence,
        "controlRevision": 0,
        "controlPendingExit": False,
        "snapshot": snapshot,
    }


class NativeMainSolverHudConsumptionV1Tests(unittest.TestCase):
    def test_engine_snapshot_mirror_gives_main_adapter_stable_or(self):
        """Host clones Engine snapshot; Main receiver + adapter must emit one OR."""
        slots = _engine_projected_slots(stable=True, unstable=True)
        snapshot = _engine_snapshot(
            match_id="issue-21-or", facts_revision=4, round_no=2, warehouse_slots=slots,
        )
        self.assertTrue(snapshot["warehouse"]["slots"][0].get("shapeLocked") is True
                        or snapshot["warehouse"]["slots"][0].get("isConfirmed") is True)

        main_match = CurrentMatch()
        accepted = LiveMatchReceiver().apply(_vision_state(snapshot), main_match)
        self.assertTrue(accepted)
        self.assertEqual(main_match.id, "issue-21-or")
        mirrored = main_match.facts["warehouse"]["slots"][0]
        self.assertEqual(mirrored["evidenceLevel"], "CANDIDATE_SET")
        self.assertTrue(mirrored.get("shapeLocked") is True or mirrored.get("isConfirmed") is True)

        canonical = main_match.to_canonical()
        py = canonical_to_v06_solver_input(canonical)
        js = warehouse_contract._js_adapter(canonical)
        self.assertEqual(py["knownGold"], OR_TOKEN)
        self.assertEqual(js["knownGold"], OR_TOKEN)
        self.assertEqual(known_token_entries(py["knownGold"]), [OR_TOKEN])

        app_main = _load_main()
        overlay = app_main.build_canonical_overlay_state(main_match)
        self.assertNotIn(CANDIDATE_A, str(overlay.get("knownGold") or "").split("+"))
        self.assertNotIn(CANDIDATE_B, str(overlay.get("knownGold") or "").split("+"))

        with mock.patch.object(app_main, "CURRENT_MATCH", main_match), \
             mock.patch.object(app_main, "native_observation_enabled", return_value=True):
            payload = app_main.build_manual_alpha_payload()
        self.assertEqual(payload["solverInput"]["knownGold"], OR_TOKEN)
        self.assertNotEqual(payload.get("knownGold") or "", OR_TOKEN)
        self.assertNotIn(CANDIDATE_A, str(payload.get("knownGold") or "").split("+"))
        self.assertNotIn(CANDIDATE_B, str(payload.get("knownGold") or "").split("+"))

        solved = warehouse_contract._run_pipeline(py)
        self.assertEqual(solved["solverStatus"], "valid")
        self.assertIsNone(solved.get("recommendedMax"))
        self.assertIsNone(solved.get("valueP50"))
        self.assertEqual(solved["degradationLevel"], "structural_only")

    def test_unstable_candidate_does_not_become_overlay_or_solver_known(self):
        slots = _engine_projected_slots(stable=False, unstable=True)
        snapshot = _engine_snapshot(
            match_id="issue-21-weak", facts_revision=2, round_no=1, warehouse_slots=slots,
        )
        main_match = CurrentMatch()
        self.assertTrue(LiveMatchReceiver().apply(_vision_state(snapshot), main_match))
        py = canonical_to_v06_solver_input(main_match.to_canonical())
        self.assertEqual(py["knownGold"], "")
        overlay = _load_main().build_canonical_overlay_state(main_match)
        self.assertEqual(overlay.get("knownGold") or "", "")

    def test_retired_match_snapshot_does_not_replace_current_warehouse(self):
        current_slots = _engine_projected_slots(stable=True)
        current = CurrentMatch()
        receiver = LiveMatchReceiver()
        first = _engine_snapshot(
            match_id="issue-21-live", facts_revision=3, round_no=2, warehouse_slots=current_slots,
        )
        self.assertTrue(receiver.apply(_vision_state(first, sequence=1), current))
        receiver.retired.add("issue-21-old")
        late = _engine_snapshot(
            match_id="issue-21-old", facts_revision=9, round_no=4,
            warehouse_slots=_engine_projected_slots(stable=False, unstable=True),
        )
        self.assertFalse(receiver.apply(_vision_state(late, session="native:other", sequence=2), current))
        py = canonical_to_v06_solver_input(current.to_canonical())
        self.assertEqual(py["knownGold"], OR_TOKEN)
        self.assertEqual(current.id, "issue-21-live")

    def test_structural_only_presentation_does_not_publish_p50_or_recommended_max(self):
        app_main = _load_main()
        match = CurrentMatch()
        match.id = "issue-21-struct"
        prediction = {
            "status": {"solverStatus": "valid"},
            "mode": {"informationMode": "structural_only"},
            "forecast": {"quantiles": {}, "structural": {"center": 640000}},
            "formalValue": {"ev": 640000},
            "decision": {
                "recommendedMax": None,
                "valueP50": None,
                "degradationLevel": "structural_only",
            },
            "supportStatus": "STRUCTURAL_ONLY",
        }
        with mock.patch.object(app_main, "CURRENT_MATCH", match), mock.patch.object(
            app_main, "_current_match_solver_sidecar", return_value=(prediction, {}),
        ), mock.patch.object(app_main, "native_observation_enabled", return_value=False):
            summary = app_main.get_current_match_presentation_summary()
        pred = summary["prediction"]
        self.assertEqual(pred["mode"], "structural_only")
        self.assertIsNone(pred["recommendedMax"])
        self.assertIsNone(pred["p50"])
        self.assertNotEqual(pred["estimateLabel"], "整仓预测中位 (P50)")

    def test_optional_vision_stubs_same_process_do_not_break_adapter_or_receiver(self):
        warehouse_contract._warehouse_fact_projection()
        imported = sys.modules.get("cv2")
        self.assertIsNotNone(imported)
        from v06_adapter import canonical_to_v06_solver_input as again
        from live_match_transport import LiveMatchReceiver as ReceiverAgain
        record = warehouse_contract._canonical(warehouse={"slots": [
            warehouse_contract._stable_or_slot(0, 0, 4, 1, "gold", [CANDIDATE_A, CANDIDATE_B]),
        ]})
        self.assertEqual(again(record)["knownGold"], OR_TOKEN)
        self.assertTrue(callable(ReceiverAgain().apply))

    def _drive_native_hud_frame(self, app_main, match, snapshot):
        import live_shadow

        target = {
            "targetHwnd": 123, "targetPid": 456, "generation": 7,
            "identity": {"ProcessInstanceToken": 99},
            "isTargetAlive": True, "isTargetForeground": True,
        }
        captured = []

        def capture_shadow(ctx, db_path=None):
            captured.append(copy.deepcopy(ctx))
            return {
                "predictionSnapshot": None,
                "frozenPrediction": None,
                "probabilityProfile": None,
                "shadowUpdating": True,
                "shadowMeta": {"cache": "pending"},
            }

        original = {
            "LATEST_PAYLOAD": dict(app_main.LATEST_PAYLOAD),
            "LATEST_VISION_PAYLOAD": dict(app_main.LATEST_VISION_PAYLOAD),
        }
        native_state = {name: getattr(app_main, name) for name in _NATIVE_STATE_NAMES}
        try:
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_VISION_PAYLOAD.clear()
            app_main._NATIVE_OBSERVATION_RECEIVER = None
            app_main._NATIVE_OBSERVATION_SESSION = None
            app_main._NATIVE_EXPECTED_SESSION = None
            app_main._NATIVE_OBSERVATION_SEQUENCE = 0
            app_main._NATIVE_OBSERVATION_LAST_FRAME_NS = None
            app_main._NATIVE_SOLVER_INVALIDATION_GENERATION = 0
            app_main._NATIVE_SOLVER_LEASE = None
            app_main._LIVE_VISION_ACTIVE = False
            app_main._LIVE_VISION_MATCH_ID = None
            frame = {
                "type": "native_observation",
                "schemaVersion": "native-observation-v1",
                "status": "FRAME",
                "observationSessionId": "session-21",
                "sourceKind": "native_wgc",
                "inputActions": False,
                "formalHistoryWriter": False,
                "target": target,
                "frame": {
                    "sequence": 1,
                    "capturedAtNs": 1_000_000_000,
                    "freshnessMs": 8,
                },
                "currentMatch": snapshot,
                "perception": {"scene": "IN_AUCTION", "inAuction": True, "bids": [], "intel": []},
                "pipelineContext": {
                    "scene": "IN_AUCTION", "inAuction": True, "round": 2, "seats": [], "intel": [],
                },
            }
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(app_main, "CURRENT_MATCH", match))
                stack.enter_context(mock.patch.object(app_main, "native_observation_enabled", return_value=True))
                stack.enter_context(mock.patch.object(app_main, "_native_start_frame_watchdog_locked"))
                stack.enter_context(mock.patch.object(app_main, "_native_post_main_status"))
                stack.enter_context(mock.patch.object(app_main, "schedule_draft_save"))
                stack.enter_context(mock.patch.object(app_main.PRESENTATION_RUNTIME, "set_vision_process_state"))
                stack.enter_context(mock.patch.object(app_main.PRESENTATION_RUNTIME, "observe_transport"))
                stack.enter_context(mock.patch.object(live_shadow, "attach_live_shadow", side_effect=capture_shadow))
                app_main._native_observation_event({
                    "type": "native_observation", "schemaVersion": "native-observation-v1",
                    "status": "STARTING", "observationSessionId": "session-21",
                    "sourceKind": "native_wgc", "inputActions": False,
                    "formalHistoryWriter": False,
                })
                app_main._native_observation_event(frame)
            return captured, dict(app_main.LATEST_PAYLOAD)
        finally:
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update(original["LATEST_PAYLOAD"])
            app_main.LATEST_VISION_PAYLOAD.clear()
            app_main.LATEST_VISION_PAYLOAD.update(original["LATEST_VISION_PAYLOAD"])
            for name, value in native_state.items():
                setattr(app_main, name, value)

    def test_native_observation_frame_mirrors_warehouse_into_main_and_hud_solver(self):
        """Engine snapshot FRAME updates Main CURRENT_MATCH and schedules HUD solver."""
        app_main = _load_main()
        slots = _engine_projected_slots(stable=True, unstable=True)
        match = CurrentMatch()
        match.id = "issue-21-hud"
        snapshot = _engine_snapshot(
            match_id="issue-21-hud", facts_revision=5, round_no=2, warehouse_slots=slots,
        )
        captured, payload = self._drive_native_hud_frame(app_main, match, snapshot)

        self.assertTrue(match.facts["warehouse"]["slots"][0].get("shapeLocked") is True
                        or match.facts["warehouse"]["slots"][0].get("isConfirmed") is True)
        adapter_known = canonical_to_v06_solver_input(match.to_canonical())["knownGold"]
        self.assertEqual(adapter_known, OR_TOKEN)
        overlay = app_main.build_canonical_overlay_state(match)
        self.assertEqual(len(captured), 1, "native IN_AUCTION frame must schedule HUD live solver")
        overlay_known = str(overlay.get("knownGold") or "")
        payload_known = _known_gold_text(payload.get("knownGold"))
        self.assertNotIn(CANDIDATE_A, overlay_known.split("+"))
        self.assertNotIn(CANDIDATE_B, overlay_known.split("+"))
        self.assertNotIn(CANDIDATE_A, payload_known.split("+"))
        self.assertNotIn(CANDIDATE_B, payload_known.split("+"))

    def test_native_observation_live_solver_ctx_receives_adapter_or(self):
        """HUD attach_live_shadow ctx must consume the adapter warehouse OR.

        Native admission and catalog compatibility stay live; only the HUD solver
        consumer is observed. Warehouse OR must reach solver_ctx without promoting
        the two candidates into the authority facts or Overlay payload.
        """
        app_main = _load_main()
        slots = _engine_projected_slots(stable=True, unstable=True)
        match = CurrentMatch()
        match.id = "issue-21-hud-or"
        snapshot = _engine_snapshot(
            match_id="issue-21-hud-or", facts_revision=5, round_no=2, warehouse_slots=slots,
        )
        captured, _payload = self._drive_native_hud_frame(app_main, match, snapshot)
        self.assertEqual(len(captured), 1, "native IN_AUCTION frame must schedule HUD live solver")
        adapter_known = canonical_to_v06_solver_input(match.to_canonical())["knownGold"]
        self.assertEqual(adapter_known, OR_TOKEN)
        self.assertEqual(_known_gold_text(captured[0].get("knownGold")), OR_TOKEN)
