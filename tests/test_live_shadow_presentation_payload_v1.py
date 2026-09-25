# -*- coding: utf-8 -*-
"""Completed Shadow events must update the nested Overlay Solver input."""
import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

import main as app_main
import live_shadow
from current_match import CurrentMatch
from prediction_snapshot_holder import ActivePredictionSnapshotHolder


class TestLiveShadowPresentationPayloadV1(unittest.TestCase):
    @staticmethod
    def _target():
        return {
            "targetHwnd": 123,
            "targetPid": 456,
            "generation": 7,
            "identity": {"ProcessInstanceToken": 99},
            "isTargetAlive": True,
            "isTargetForeground": True,
        }

    def _native_lease_patch(self, *, match_id, session, target, round_no, facts_revision,
                            engine_facts_revision, match_generation, generation):
        target_instance = app_main._native_target_instance(target)
        lease = {
            "generation": generation,
            "sessionId": session,
            "targetInstance": target_instance,
            "matchId": match_id,
            "round": round_no,
            "factsRevision": facts_revision,
            "engineFactsRevision": engine_facts_revision,
            "matchGeneration": match_generation,
            "frameSequence": 1,
            "acceptedAtMonotonicNs": time.monotonic_ns(),
        }
        return mock.patch.multiple(
            app_main,
            _NATIVE_SOLVER_INVALIDATION_GENERATION=generation,
            _NATIVE_SOLVER_LEASE=lease,
            _NATIVE_EXPECTED_SESSION=session,
            _NATIVE_OBSERVATION_SESSION=session,
            _LIVE_VISION_ACTIVE=True,
            _LIVE_VISION_MATCH_ID=match_id,
        )

    def test_warehouse_instance_command_carries_host_target_and_rejects_replaced_match(self):
        class _Bridge:
            running = True

            def __init__(self):
                self.commands = []

            def send_control(self, message):
                self.commands.append(message)
                return True

        class _DraftStore:
            @staticmethod
            def read_source_image_descriptor(_descriptor):
                return {"data": b"activity-crop"}

        target = self._target()
        target_instance = app_main._native_target_instance(target)
        slot = {
            "row": 2, "col": 1, "w": 1, "h": 2, "rarity": "purple",
            "identityStatus": "CANDIDATE",
            "candidates": [{"catalogId": "candidate-one", "name": "候选一"}],
            "activityEvidence": {
                "evidenceId": "activity-evidence-one", "sessionId": "decision-session",
                "generationId": 14, "matchId": "decision-match",
            },
            "instanceDecisionToken": "decision-token-one",
            "instanceDecisionGeneration": 3,
        }
        match = CurrentMatch()
        match.id = "decision-match"
        match.facts["warehouse"] = {"slots": [slot]}
        payload = {
            "scene": "IN_AUCTION", "inAuction": True, "observationStatus": "FRAME",
            "nativeInvalidated": False, "observationSessionId": "decision-session",
            "matchId": match.id, "round": 4, "target": target,
        }
        bridge = _Bridge()
        with mock.patch.multiple(
            app_main,
            CURRENT_MATCH=match,
            LATEST_PAYLOAD=payload,
            _NATIVE_EXPECTED_SESSION="decision-session",
            _NATIVE_OBSERVATION_SESSION="decision-session",
            _NATIVE_INSTANCE_DECISION_GENERATION=8,
            _NATIVE_INSTANCE_DECISION_SCOPE=None,
            _NATIVE_CONTROL_BINDINGS={},
            _LIVE_CONTROL_REVISION=30,
            NATIVE_OBSERVATION_BRIDGE=bridge,
            NATIVE_TRIAL_DRAFT_STORE=_DraftStore(),
            _NATIVE_TRIAL_WAREHOUSE_SOURCES={
                "activity-evidence-one": {
                    "evidenceId": "activity-evidence-one", "matchId": "decision-match",
                    "sessionId": "decision-session", "generationId": 14,
                    "sourceKind": "native_wgc", "box": [10, 20, 30, 40],
                }
            },
            _WAREHOUSE_REVIEW_GUIDEBOOK_ITEMS={
                "candidate-one": {"sourceImages": [{"available": True, "uri": "file:///catalog.png"}]}
            },
        ), mock.patch.object(app_main, "native_observation_enabled", return_value=True):
            scope = app_main._native_instance_decision_scope_key(payload)
            self.assertIsNotNone(scope)
            app_main._NATIVE_INSTANCE_DECISION_SCOPE = scope
            evidence = app_main.handle_request_warehouse_slot_evidence({
                "matchId": match.id, "sessionId": "decision-session", "round": 4,
                "targetInstance": target, "mainDecisionGeneration": 8,
                "instanceAnchor": {key: slot[key] for key in ("row", "col", "w", "h", "rarity")},
                "activityEvidenceId": "activity-evidence-one",
                "instanceDecisionToken": "decision-token-one", "candidateIds": ["candidate-one"],
            })
            self.assertTrue(evidence["ok"])
            self.assertTrue(evidence["decisionAllowed"])
            self.assertEqual(evidence["candidates"][0]["sourceImages"][0]["uri"], "file:///catalog.png")
            solver_item = {
                "inputName": "候选一", "name": "候选一", "quality": "purple", "price": 10000,
                "width": 1, "height": 2, "catalogVersion": "2026-08-13",
            }
            decision_payload = {
                "sessionId": "decision-session", "matchId": match.id, "round": 4,
                "targetInstance": target, "mainDecisionGeneration": 8,
                "instanceAnchor": {key: slot[key] for key in ("row", "col", "w", "h", "rarity")},
                "activityEvidenceId": "activity-evidence-one",
                "instanceDecisionToken": "decision-token-one", "expectedGenerationId": 14,
                "expectedInvalidationGeneration": 3,
                "decision": "CONFIRM_CANDIDATE", "catalogId": "candidate-one",
            }
            with mock.patch(
                "live_shadow.resolve_solver_catalog_identity",
                return_value={"ok": True, "available": False, "item": None},
            ):
                unavailable = app_main.handle_warehouse_instance_decision(decision_payload)
            self.assertEqual(unavailable["status"], "REJECTED")
            self.assertEqual(len(bridge.commands), 0)
            with mock.patch(
                "live_shadow.resolve_solver_catalog_identity",
                return_value={"ok": True, "available": True, "item": solver_item},
            ):
                result = app_main.handle_warehouse_instance_decision(decision_payload)
            self.assertEqual(result["status"], "PENDING", result)
            self.assertEqual(bridge.commands[0]["command"]["expectedTargetInstance"], target_instance)
            expected_solver_proof = {
                **solver_item, "catalogId": "candidate-one",
            }
            self.assertEqual(bridge.commands[0]["command"]["solverCatalogProof"], expected_solver_proof)

            command = bridge.commands[0]["command"]
            decision = {
                "action": "CONFIRM_CANDIDATE", "catalogId": "candidate-one",
                "name": "候选一", "source": "HUMAN_INSTANCE_REVIEW",
                "manualIdentity": {
                    "catalogId": "candidate-one", "name": "候选一", "rarity": "purple",
                    "status": "MANUAL_CONFIRMED", "source": "HUMAN_INSTANCE_REVIEW",
                    "solverCatalogProof": expected_solver_proof,
                },
            }
            result_data = {
                "echo": "warehouse.instance_decision", "status": "APPLIED",
                "sessionId": "decision-session", "matchId": "decision-match", "round": 4,
                "factsRevision": 21, "knownFacts": {"knownPurple": "候选一"},
                "valuationInputChanged": True,
                "instanceDecisionToken": "decision-token-one",
                "activityEvidenceId": "activity-evidence-one",
                "instanceAnchor": {key: slot[key] for key in ("row", "col", "w", "h", "rarity")},
                "decision": decision,
                "warehouse": {"slots": [{**slot, "manualDecision": decision}]},
            }
            with mock.patch.multiple(
                app_main,
                _native_invalidate_solver_locked=mock.DEFAULT,
                schedule_draft_save=mock.DEFAULT,
                draft_write_status=mock.DEFAULT,
                get_current_match_presentation_summary=mock.DEFAULT,
                build_manual_alpha_payload=mock.DEFAULT,
                publish_manual_payload=mock.DEFAULT,
                _native_post_main_status=mock.DEFAULT,
                WS_EVENT_LOOP=None,
            ) as patched:
                patched["_native_invalidate_solver_locked"].return_value = None
                patched["schedule_draft_save"].return_value = None
                patched["draft_write_status"].return_value = "SAVED"
                patched["get_current_match_presentation_summary"].return_value = {
                    "matchId": "decision-match", "warehouse": result_data["warehouse"],
                }
                patched["build_manual_alpha_payload"].return_value = {}
                patched["publish_manual_payload"].return_value = None
                patched["_native_post_main_status"].return_value = None
                app_main._native_observation_event({
                    "type": "native_observation", "schemaVersion": "native-observation-v1",
                    "status": "CONTROL", "observationSessionId": "decision-session",
                    "sourceKind": "native_wgc", "inputActions": False,
                    "formalHistoryWriter": False,
                    "details": {
                        "controlRevision": command["revision"],
                        "commandId": f"native-control-{command['revision']}",
                        "commandStatus": "ACK",
                        "commandResult": {"status": "ACK", "resultData": result_data},
                    },
                })
            self.assertEqual(app_main.LATEST_PAYLOAD["warehouseInstanceDecisionResult"]["status"], "ACK")
            self.assertEqual(
                match.facts["warehouse"]["slots"][0]["manualDecision"]["source"],
                "HUMAN_INSTANCE_REVIEW",
            )
            self.assertEqual(match.facts["knownPurple"], "候选一")
            self.assertTrue(patched["_native_invalidate_solver_locked"].called)
            self.assertEqual(
                patched["_native_invalidate_solver_locked"].call_args.args[0],
                "warehouse-identity-valuation-input-changed",
            )
            self.assertEqual(
                app_main.LATEST_PAYLOAD["warehouseInstanceDecisionResult"]["solverRefreshStatus"],
                "WAITING_FOR_FRESH_OBSERVATION",
            )

            app_main._NATIVE_CONTROL_BINDINGS.clear()
            match.id = "next-match"
            rejected = app_main.handle_warehouse_instance_decision({
                "sessionId": "decision-session", "matchId": "decision-match", "round": 4,
                "targetInstance": target, "mainDecisionGeneration": 8,
                "instanceAnchor": {key: slot[key] for key in ("row", "col", "w", "h", "rarity")},
                "activityEvidenceId": "activity-evidence-one",
                "instanceDecisionToken": "decision-token-one", "expectedGenerationId": 14,
                "expectedInvalidationGeneration": 3,
                "decision": "CONFIRM_CANDIDATE", "catalogId": "candidate-one",
            })
            self.assertEqual(rejected["status"], "REJECTED")
            self.assertEqual(len(bridge.commands), 1)

    def _native_frame(self, match, *, session, sequence, match_id, facts_revision,
                      round_no, target, leader_bid=None, venue_id=None):
        snapshot = match.snapshot()
        snapshot.update({
            "id": match_id,
            "schemaVersion": 7,
            "lifecycleStatus": "DRAFT",
            "factsRevision": facts_revision,
        })
        if leader_bid is not None:
            snapshot["leaderBid"] = leader_bid
        if venue_id is not None:
            snapshot["venueId"] = venue_id
        return {
            "type": "native_observation",
            "schemaVersion": "native-observation-v1",
            "status": "FRAME",
            "observationSessionId": session,
            "sourceKind": "native_wgc",
            "inputActions": False,
            "formalHistoryWriter": False,
            "target": target,
            "frame": {
                "sequence": sequence,
                "capturedAtNs": sequence * 1_000_000_000,
                "freshnessMs": 8,
            },
            "currentMatch": snapshot,
            "perception": {
                "scene": "IN_AUCTION",
                "inAuction": True,
                "bids": [],
                "intel": [],
            },
            "pipelineContext": {
                "scene": "IN_AUCTION",
                "inAuction": True,
                "round": round_no,
                "seats": [],
                "intel": [],
            },
        }

    def test_pause_recovery_and_new_match_revoke_old_work(self):
        original_payload = dict(app_main.LATEST_PAYLOAD)
        original_vision_payload = dict(app_main.LATEST_VISION_PAYLOAD)
        original_holder = (
            app_main.ACTIVE_SNAPSHOT_HOLDER.match_id,
            app_main.ACTIVE_SNAPSHOT_HOLDER.snapshot,
            app_main.ACTIVE_SNAPSHOT_HOLDER.frozen_prediction,
        )
        original_keys = dict(app_main._SHADOW_PRESENTATION_KEYS)
        original_controls = dict(app_main._NATIVE_CONTROL_BINDINGS)
        original_manual_overrides = dict(app_main._LIVE_MANUAL_OVERRIDES)
        original_native_state = {
            name: getattr(app_main, name)
            for name in (
                "_NATIVE_OBSERVATION_RECEIVER", "_NATIVE_OBSERVATION_SESSION",
                "_NATIVE_EXPECTED_SESSION", "_NATIVE_OBSERVATION_SEQUENCE",
                "_NATIVE_OBSERVATION_LAST_FRAME_NS", "_NATIVE_SOLVER_INVALIDATION_GENERATION",
                "_NATIVE_SOLVER_LEASE", "_LIVE_VISION_ACTIVE", "_LIVE_VISION_MATCH_ID",
            )
        }
        match = CurrentMatch()
        match.id = "p3-match-a"
        match.apply_facts({
            "venueId": "venue-shanhu", "venue": "珊瑚海湾",
            "boxId": "box-shanhu-glass", "box": "琉璃宝箱 · 宝石类概率提升",
            "fieldCondition": "standard", "q": 12, "goldAvg": 74379,
            "entryCost": 5000, "roundNo": 3, "leaderBid": 700,
        }, source="manual", intent="confirm")
        target = self._target()
        requests = []
        control_messages = []
        control_bridge = mock.Mock()
        control_bridge.running = True
        control_bridge.send_control.side_effect = lambda message: control_messages.append(message) or True

        def pending_shadow(ctx, db_path=None):
            requests.append(dict(ctx))
            return {
                "predictionSnapshot": None,
                "frozenPrediction": None,
                "probabilityProfile": None,
                "shadowUpdating": True,
                "shadowMeta": {"cache": "pending"},
            }

        def completed_event(ctx, prediction_id):
            return {
                **{key: ctx.get(key) for key in (
                    "matchId", "matchGeneration", "scene", "observationSessionId",
                    "nativeSolverGeneration", "target", "round", "factsRevision",
                    "engineFactsRevision", "presentationSource",
                )},
                "predictionSnapshot": {
                    "matchId": ctx["matchId"],
                    "predictionId": prediction_id,
                    "status": {"solverStatus": "valid"},
                },
                "probabilityProfile": {"coverageRatio": 0.5},
                "frozenPrediction": {"recommendedMax": 180},
            }

        try:
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_VISION_PAYLOAD.clear()
            app_main.ACTIVE_SNAPSHOT_HOLDER.clear()
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main._NATIVE_CONTROL_BINDINGS.clear()
            app_main._LIVE_MANUAL_OVERRIDES.clear()
            app_main._NATIVE_OBSERVATION_RECEIVER = None
            app_main._NATIVE_OBSERVATION_SESSION = None
            app_main._NATIVE_EXPECTED_SESSION = None
            app_main._NATIVE_OBSERVATION_SEQUENCE = 0
            app_main._NATIVE_OBSERVATION_LAST_FRAME_NS = None
            app_main._NATIVE_SOLVER_INVALIDATION_GENERATION = 0
            app_main._NATIVE_SOLVER_LEASE = None
            app_main._LIVE_VISION_ACTIVE = False
            app_main._LIVE_VISION_MATCH_ID = None
            with mock.patch.object(app_main, "CURRENT_MATCH", match), \
                 mock.patch.object(app_main, "ACTIVE_SNAPSHOT_HOLDER", ActivePredictionSnapshotHolder()), \
                 mock.patch.object(app_main, "ACTIVE_SETTLEMENT_TRUTH_HOLDER", mock.Mock()), \
                 mock.patch.object(app_main, "native_observation_enabled", return_value=True), \
                 mock.patch.object(app_main, "_native_start_frame_watchdog_locked"), \
                 mock.patch.object(app_main, "_native_post_main_status"), \
                 mock.patch.object(app_main, "NATIVE_OBSERVATION_BRIDGE", control_bridge), \
                 mock.patch.object(app_main, "schedule_draft_save"), \
                 mock.patch.object(app_main.PRESENTATION_RUNTIME, "set_vision_process_state"), \
                 mock.patch.object(app_main.PRESENTATION_RUNTIME, "observe_transport"), \
                 mock.patch.object(live_shadow, "invalidate_match_shadow", return_value=0), \
                 mock.patch.object(live_shadow, "attach_live_shadow", side_effect=pending_shadow):
                app_main._native_observation_event({
                    "type": "native_observation", "schemaVersion": "native-observation-v1",
                    "status": "STARTING", "observationSessionId": "session-a",
                    "sourceKind": "native_wgc", "inputActions": False,
                    "formalHistoryWriter": False,
                })
                app_main._native_observation_event(self._native_frame(
                    match, session="session-a", sequence=1, match_id="p3-match-a",
                    facts_revision=11, round_no=3, target=target, leader_bid=650,
                    venue_id="venue-other",
                ))
                self.assertEqual(len(requests), 1)
                first_job = requests[0]
                self.assertEqual(app_main.LATEST_PAYLOAD["solverStatus"], "pending")

                first_result = completed_event(first_job, "before-pause")
                app_main._publish_live_shadow_event(first_result)
                self.assertEqual(
                    app_main.ACTIVE_SNAPSHOT_HOLDER.get_snapshot_for_match("p3-match-a")["predictionId"],
                    "before-pause",
                )
                kept_facts = dict(match.facts)
                self.assertEqual(match.facts["venueId"], "venue-shanhu")
                self.assertTrue(match.field_states["venueId"].protected)

                app_main._native_observation_event({
                    "type": "native_observation", "schemaVersion": "native-observation-v1",
                    "status": "PAUSED", "observationSessionId": "session-a",
                    "sourceKind": "native_wgc", "reason": "focus-lost",
                    "inputActions": False, "formalHistoryWriter": False,
                })
                self.assertIsNone(app_main._NATIVE_SOLVER_LEASE)
                self.assertIsNone(app_main.ACTIVE_SNAPSHOT_HOLDER.get_snapshot_for_match("p3-match-a"))
                self.assertEqual(match.facts, kept_facts)
                self.assertTrue(match.field_states["venueId"].protected)
                app_main._publish_live_shadow_event(first_result)
                self.assertIsNone(app_main.LATEST_PAYLOAD.get("predictionSnapshot"))

                app_main._native_observation_event({
                    "type": "native_observation", "schemaVersion": "native-observation-v1",
                    "status": "STARTING", "observationSessionId": "session-b",
                    "sourceKind": "native_wgc", "inputActions": False,
                    "formalHistoryWriter": False,
                })
                app_main._native_observation_event({
                    "type": "native_observation", "schemaVersion": "native-observation-v1",
                    "status": "READY", "observationSessionId": "session-b",
                    "sourceKind": "native_wgc", "inputActions": False,
                    "formalHistoryWriter": False,
                })
                self.assertIsNone(app_main._NATIVE_SOLVER_LEASE)
                app_main._publish_live_shadow_event(first_result)
                self.assertEqual(len(requests), 1)

                app_main._native_observation_event(self._native_frame(
                    match, session="session-b", sequence=1, match_id="p3-match-a",
                    facts_revision=11, round_no=3, target=target, leader_bid=600,
                    venue_id="venue-other",
                ))
                self.assertEqual(len(requests), 2)
                second_job = requests[1]
                self.assertEqual(second_job["factsRevision"], first_job["factsRevision"])
                self.assertGreater(second_job["nativeSolverGeneration"], first_job["nativeSolverGeneration"])
                self.assertEqual(match.facts["venueId"], "venue-shanhu")
                self.assertTrue(match.field_states["venueId"].protected)
                app_main._publish_live_shadow_event(first_result)
                self.assertIsNone(app_main.LATEST_PAYLOAD.get("predictionSnapshot"))
                second_result = completed_event(second_job, "after-resume")
                app_main._publish_live_shadow_event(second_result)
                self.assertEqual(app_main.LATEST_PAYLOAD["predictionSnapshot"]["predictionId"], "after-resume")

                app_main._native_observation_event({
                    "type": "native_observation", "schemaVersion": "native-observation-v1",
                    "status": "PAUSED", "observationSessionId": "session-b",
                    "sourceKind": "native_wgc", "reason": "scene-boundary:SETTLEMENT",
                    "inputActions": False, "formalHistoryWriter": False,
                })
                next_match = CurrentMatch()
                next_match.id = "p3-match-b"
                app_main._native_observation_event({
                    "type": "native_observation", "schemaVersion": "native-observation-v1",
                    "status": "STARTING", "observationSessionId": "session-c",
                    "sourceKind": "native_wgc", "inputActions": False,
                    "formalHistoryWriter": False,
                })
                app_main._native_observation_event({
                    "type": "native_observation", "schemaVersion": "native-observation-v1",
                    "status": "READY", "observationSessionId": "session-c",
                    "sourceKind": "native_wgc", "inputActions": False,
                    "formalHistoryWriter": False,
                })
                app_main._native_observation_event(self._native_frame(
                    next_match, session="session-c", sequence=1, match_id="p3-match-b",
                    facts_revision=1, round_no=1, target=target,
                ))
                self.assertEqual(match.id, "p3-match-b")
                self.assertIsNone(match.facts["venueId"])
                self.assertIsNone(match.facts["q"])
                self.assertIsNone(match.facts["leaderBid"])
                self.assertFalse(any(state.protected for state in match.field_states.values()))
                self.assertIsNone(app_main.LATEST_PAYLOAD.get("predictionSnapshot"))
                self.assertEqual(app_main.LATEST_PAYLOAD["solverMissingReason"], "缺失会场")

                latest_frame_sequence = app_main.LATEST_PAYLOAD["frameSequence"]
                app_main._native_observation_event(self._native_frame(
                    next_match, session="session-c", sequence=99, match_id="p3-match-a",
                    facts_revision=11, round_no=3, target=target, leader_bid=999,
                ))
                self.assertEqual(match.id, "p3-match-b")
                self.assertEqual(app_main.LATEST_PAYLOAD["frameSequence"], latest_frame_sequence)
                self.assertIsNone(match.facts["leaderBid"])
                app_main._native_observation_event(self._native_frame(
                    next_match, session="session-b", sequence=99, match_id="p3-match-a",
                    facts_revision=11, round_no=3, target=target,
                ))
                self.assertEqual(match.id, "p3-match-b")
                self.assertEqual(app_main.LATEST_PAYLOAD["frameSequence"], latest_frame_sequence)
                stale_session_command = app_main.apply_manual_facts({
                    "expectedMatchId": "p3-match-b",
                    "expectedFactsRevision": 1,
                    "expectedObservationSessionId": "session-b",
                    "facts": {"leaderBid": 999},
                })
                self.assertEqual(stale_session_command["manualCommandResult"]["status"], "REJECTED")
                self.assertIsNone(match.facts["leaderBid"])
                stale_command = app_main.apply_manual_facts({
                    "expectedMatchId": "p3-match-a",
                    "expectedFactsRevision": 11,
                    "expectedObservationSessionId": "session-b",
                    "facts": {"leaderBid": 999},
                })
                self.assertEqual(stale_command["manualCommandResult"]["status"], "REJECTED")
                self.assertIsNone(match.facts["leaderBid"])

                accepted_command = app_main.apply_manual_facts({
                    "expectedMatchId": "p3-match-b",
                    "expectedFactsRevision": 1,
                    "expectedObservationSessionId": "session-c",
                    "expectedRound": 1,
                    "expectedTargetInstance": target,
                    "facts": {"q": 9},
                })
                self.assertEqual(accepted_command["manualCommandResult"]["status"], "PENDING")
                self.assertEqual(match.facts["q"], 9)
                accepted_wire_command = control_messages[-1]["command"]
                accepted_result = {
                    "matchId": "p3-match-b",
                    "expectedMatchId": "p3-match-b",
                    "expectedFactsRevision": 1,
                    "expectedRound": 1,
                    "expectedObservationSessionId": "session-c",
                }
                app_main._native_observation_event({
                    "type": "native_observation", "schemaVersion": "native-observation-v1",
                    "status": "CONTROL", "observationSessionId": "session-c",
                    "sourceKind": "native_wgc", "inputActions": False,
                    "formalHistoryWriter": False,
                    "details": {
                        "controlRevision": accepted_wire_command["revision"],
                        "commandStatus": "ACK",
                        "commandResult": {"status": "ACK", "resultData": accepted_result},
                    },
                })
                self.assertEqual(app_main.LATEST_PAYLOAD["manualCommandResult"]["status"], "ACK")
                self.assertTrue(match.field_states["q"].protected)

                app_main.LATEST_PAYLOAD.update({
                    "observationStatus": "FRAME", "nativeInvalidated": False,
                    "scene": "IN_AUCTION", "matchId": "p3-match-b",
                    "observationSessionId": "session-c", "factsRevision": 2,
                    "round": 1, "frameSequence": 2, "freshnessMs": 8, "target": target,
                })
                rejected_command = app_main.apply_manual_facts({
                    "expectedMatchId": "p3-match-b",
                    "expectedFactsRevision": 2,
                    "expectedObservationSessionId": "session-c",
                    "expectedRound": 1,
                    "expectedTargetInstance": target,
                    "facts": {"q": 8},
                })
                self.assertEqual(rejected_command["manualCommandResult"]["status"], "PENDING")
                rejected_wire_command = control_messages[-1]["command"]
                app_main._native_observation_event({
                    "type": "native_observation", "schemaVersion": "native-observation-v1",
                    "status": "CONTROL", "observationSessionId": "session-c",
                    "sourceKind": "native_wgc", "inputActions": False,
                    "formalHistoryWriter": False,
                    "details": {
                        "controlRevision": rejected_wire_command["revision"],
                        "commandStatus": "REJECT",
                        "commandResult": {"status": "REJECT", "errorDetails": "STALE_FACTS_REVISION"},
                    },
                })
                self.assertEqual(app_main.LATEST_PAYLOAD["manualCommandResult"]["status"], "REJECTED")
                self.assertEqual(match.facts["q"], 9)
        finally:
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update(original_payload)
            app_main.LATEST_VISION_PAYLOAD.clear()
            app_main.LATEST_VISION_PAYLOAD.update(original_vision_payload)
            app_main.ACTIVE_SNAPSHOT_HOLDER.clear()
            old_match, old_snapshot, old_frozen = original_holder
            if old_match:
                app_main.ACTIVE_SNAPSHOT_HOLDER.update(old_match, snapshot=old_snapshot, frozen_prediction=old_frozen)
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main._SHADOW_PRESENTATION_KEYS.update(original_keys)
            app_main._NATIVE_CONTROL_BINDINGS.clear()
            app_main._NATIVE_CONTROL_BINDINGS.update(original_controls)
            app_main._LIVE_MANUAL_OVERRIDES.clear()
            app_main._LIVE_MANUAL_OVERRIDES.update(original_manual_overrides)
            for name, value in original_native_state.items():
                setattr(app_main, name, value)

    def test_qualified_node_prediction_reaches_native_owner(self):
        history_path = Path(PROJECT_ROOT) / "异环拍卖数据.json"
        if not history_path.is_file() or not shutil.which("node"):
            self.skipTest("read-only solver history or Node unavailable")
        facts = {
            "venueId": "venue-shanhu", "boxId": "box-shanhu-glass",
            "box": "琉璃宝箱 · 宝石类概率提升",
            "fieldCondition": "standard", "q": 12, "goldAvg": 74379,
            "entryCost": 5000,
        }
        self.assertEqual(app_main._native_solver_admission({**facts, "goldAvg": None})[1], "缺失金色均价")
        self.assertEqual(app_main._native_solver_admission({**facts, "entryCost": None})[1], "缺失入场费")
        mapped, reason = app_main._native_solver_admission(facts)
        self.assertIsNone(reason)
        match_id = "p2-qualified-node-owner"
        context = {
            "scene": "IN_AUCTION", "round": 3, "matchId": match_id,
            "factsRevision": 26, "matchGeneration": 1,
            "observationSessionId": "qualified-session",
            "target": self._target(),
            "nativeSolverGeneration": 31,
            "q": 12, "goldAvg": 74379, "purple": 7,
            "entryCost": 5000,
            "costs": {"entry": 5000, "intel": 0, "other": 0, "sunkCost": 5000,
                      "futureIncrementalCost": 0, "total": 5000},
            "fieldCondition": "standard", "playedAt": "2026-08-17T14:15:59.030277",
            "venue": mapped["venue"], "box": mapped["box"],
        }
        original_payload = dict(app_main.LATEST_PAYLOAD)
        original_keys = dict(app_main._SHADOW_PRESENTATION_KEYS)
        try:
            live_shadow.reset_live_shadow_state()
            with mock.patch.dict(os.environ, {
                "YIHUAN_UPPER_TAIL_CAPTURE_DIR": str(Path(PROJECT_ROOT) / "build" / "p2-targeted-data" / "support-captures")
            }):
                profile, meta = live_shadow.compute_live_probability_profile(
                    context, db_path=str(history_path), persist_runtime=True
                )
            snapshot = meta.get("predictionSnapshot")
            self.assertEqual(meta.get("computeHost"), "node")
            self.assertIsNotNone(profile)
            self.assertEqual((snapshot or {}).get("status", {}).get("solverStatus"), "valid")
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update({
                "scene": "IN_AUCTION", "matchId": match_id,
                "observationProfile": "native-readonly-v1",
                "observationSessionId": "qualified-session",
                "target": context["target"], "round": 3, "factsRevision": 26,
                "engineFactsRevision": 26, "nativeSolverGeneration": 31,
                "matchGeneration": 1, "predictionSnapshot": None,
                "solverStatus": "pending",
            })
            with mock.patch.object(app_main, "CURRENT_MATCH", mock.Mock(id=match_id)), \
                 mock.patch.object(app_main, "get_current_match_presentation_summary", return_value={"id": match_id}), \
                 mock.patch.object(app_main, "ACTIVE_SNAPSHOT_HOLDER"), \
                 self._native_lease_patch(
                     match_id=match_id, session="qualified-session", target=context["target"],
                     round_no=3, facts_revision=26, engine_facts_revision=26,
                     match_generation=1, generation=31,
                 ):
                app_main._publish_live_shadow_event({
                    "matchId": match_id, "presentationSource": "live_vision",
                    "scene": "IN_AUCTION",
                    "observationSessionId": "qualified-session",
                    "target": context["target"], "round": 3, "factsRevision": 26,
                    "engineFactsRevision": 26, "nativeSolverGeneration": 31,
                    "matchGeneration": 1, "probabilityProfile": profile,
                    "predictionSnapshot": snapshot,
                    "frozenPrediction": meta.get("frozenPrediction"),
                })
                self.assertEqual(app_main.LATEST_PAYLOAD["solverStatus"], "valid")
                self.assertEqual(app_main.LATEST_PAYLOAD["predictionSnapshot"], snapshot)
        finally:
            live_shadow.reset_live_shadow_state()
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update(original_payload)
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main._SHADOW_PRESENTATION_KEYS.update(original_keys)

    def test_native_result_requires_current_round_revision_and_target(self):
        original_payload = dict(app_main.LATEST_PAYLOAD)
        original_keys = dict(app_main._SHADOW_PRESENTATION_KEYS)
        match_id = "p2-native-result-owner"
        target = self._target()
        payload = {
            "scene": "IN_AUCTION", "matchId": match_id,
            "observationProfile": "native-readonly-v1",
            "observationSessionId": "session-current",
            "target": target,
            "round": 5, "factsRevision": 26, "matchGeneration": 1,
            "engineFactsRevision": 26, "nativeSolverGeneration": 44,
            "predictionSnapshot": None, "solverStatus": "pending",
        }
        event = {
            "matchId": match_id, "presentationSource": "live_vision", "scene": "IN_AUCTION",
            "observationSessionId": "session-current",
            "target": target,
            "round": 5, "factsRevision": 26, "matchGeneration": 1,
            "engineFactsRevision": 26, "nativeSolverGeneration": 44,
            "predictionSnapshot": {
                "matchId": match_id, "predictionId": "current-p2",
                "status": {"solverStatus": "valid"},
            },
            "probabilityProfile": {"coverageRatio": 0.5},
        }
        try:
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update(payload)
            with mock.patch.object(app_main, "CURRENT_MATCH", mock.Mock(id=match_id)), \
                 mock.patch.object(app_main, "get_current_match_presentation_summary", return_value={"id": match_id}), \
                 mock.patch.object(app_main, "ACTIVE_SNAPSHOT_HOLDER"), \
                 self._native_lease_patch(
                     match_id=match_id, session="session-current", target=target,
                     round_no=5, facts_revision=26, engine_facts_revision=26,
                     match_generation=1, generation=44,
                 ):
                for mismatch in (
                    {"factsRevision": 25}, {"round": 4},
                    {"target": {"targetHwnd": 123, "targetPid": 999}},
                ):
                    app_main._publish_live_shadow_event({**event, **mismatch})
                    self.assertIsNone(app_main.LATEST_PAYLOAD["predictionSnapshot"])
                    self.assertEqual(app_main.LATEST_PAYLOAD["solverStatus"], "pending")
                app_main._publish_live_shadow_event(event)
                self.assertEqual(app_main.LATEST_PAYLOAD["predictionSnapshot"]["predictionId"], "current-p2")
                self.assertEqual(app_main.LATEST_PAYLOAD["solverStatus"], "valid")
        finally:
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update(original_payload)
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main._SHADOW_PRESENTATION_KEYS.update(original_keys)

    def test_completed_event_replaces_nested_pending_solver_input(self):
        current = app_main.CURRENT_MATCH
        original_payload = dict(app_main.LATEST_PAYLOAD)
        original_keys = dict(getattr(app_main, "_SHADOW_PRESENTATION_KEYS", {}))
        try:
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            match_id = current.id
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update({
                "type": "manual_alpha_state",
                "scene": "IN_AUCTION",
                "matchId": match_id,
                "shadowUpdating": True,
                "solverInput": {
                    "matchId": match_id,
                    "q": 12,
                    "goldAvg": 74379,
                    "probabilityProfile": None,
                    "shadowUpdating": True,
                },
                "shadowSupport": {
                    "status": "SUPPORT_UPDATING",
                    "reasonCodes": ["HISTORICAL_PROFILE_PENDING"],
                    "historyN": 290,
                    "coverageRatio": 0.0,
                },
            })
            profile = {
                "coverageRatio": 1,
                "shadowWhole": {"p20": 100, "p50": 200, "p80": 300},
            }
            snapshot = {"matchId": match_id, "predictionId": "presentation-test"}
            app_main._publish_live_shadow_event({
                "matchId": match_id,
                "shadowGen": 2,
                "probabilityProfile": profile,
                "predictionSnapshot": snapshot,
                "frozenPrediction": {"recommendedMax": 180},
                "shadowMeta": {"cache": "miss", "historyN": 290, "shadowUpdating": False},
                "shadowStates": {"exact": [], "expanded": []},
            })
            payload = app_main.LATEST_PAYLOAD
            self.assertFalse(payload["shadowUpdating"])
            self.assertEqual(payload["solverInput"]["probabilityProfile"], profile)
            self.assertEqual(payload["solverInput"]["predictionSnapshot"], snapshot)
            self.assertFalse(payload["solverInput"]["shadowUpdating"])
            self.assertEqual(payload["shadowSupport"]["status"], "HISTORICAL_SUPPORTED")
            self.assertEqual(payload["shadowSupport"]["coverageRatio"], 1)
            self.assertNotIn("HISTORICAL_PROFILE_PENDING", payload["shadowSupport"]["reasonCodes"])
        finally:
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update(original_payload)
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main._SHADOW_PRESENTATION_KEYS.update(original_keys)


if __name__ == "__main__":
    unittest.main()
