import copy
import json
import sys
import time
import tempfile
import types
import unittest
from unittest.mock import patch
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "architecture" / "v2" / "host" / "engine_v22"))

from current_match import CurrentMatch
from deferred_identity_analyzer import DeferredIdentityAnalyzer, deferred_identity_result_is_current
from nte_engine_v22 import RealEngine
from visual_catalog import load_derived_warehouse_templates, load_verified_warehouse_gameplay_templates
from warehouse_vision import WarehouseTemplateMatcher, WarehouseVisionConfig
from vision_pipeline import NTEVisionPipeline


class _Pipeline:
    def __init__(self, catalog):
        self.catalog = catalog
        self._match_gen = 7
        self._session_generation = 3
        self.current_context = {}

    def _apply_warehouse_state(self, state):
        self.current_context["warehouseVision"] = state


def _engine(current_match, catalog):
    engine = RealEngine.__new__(RealEngine)
    engine.session_id = "session-current"
    engine.generation_id = 9
    engine._identity_generation_lock = __import__("threading").Lock()
    engine._identity_invalidation_generation = 0
    engine._identity_analyzer = None
    engine._identity_last_committed_sequence = {}
    engine.current_match = current_match
    engine.pipeline = _Pipeline(catalog)
    engine.last_context = {"scene": "IN_AUCTION", "inAuction": True, "round": 1}
    engine.log = lambda *_args, **_kwargs: None
    engine._persist_history = lambda: "PERSISTED_DRAFT"
    engine._persist_state = lambda **_kwargs: None
    return engine


class DerivedWarehouseIdentityBoundaryTests(unittest.TestCase):
    def test_deferred_identity_reuses_static_matcher_but_resets_tracks_on_round_change(self):
        instances = []

        class _FakeWarehouseVision:
            def __init__(self):
                self.track_id = 0
                self.reset_count = 0
                instances.append(self)

            def reset(self):
                self.track_id = 0
                self.reset_count += 1

            def process_frame(self, _frame):
                self.track_id += 1
                return {"slots": [{"trackId": self.track_id}]}

        fake_module = types.ModuleType("warehouse_vision")
        fake_module.WarehouseVisionV1 = _FakeWarehouseVision
        analyzer = DeferredIdentityAnalyzer()
        frame = np.zeros((2, 2, 3), dtype=np.uint8)

        def wait_result():
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                results = analyzer.poll()
                if results:
                    return results[0]
                time.sleep(0.001)
            self.fail("deferred identity result did not arrive")

        def submit(round_no, sequence):
            self.assertTrue(analyzer.submit({
                "kind": "warehouse", "sessionId": "session", "generationId": 1,
                "matchId": "match", "matchSequence": 1, "pipelineMatchGeneration": 1,
                "invalidationGeneration": 0, "round": round_no, "frameSequence": sequence,
            }, frame))
            return wait_result()

        try:
            with patch.dict(sys.modules, {"warehouse_vision": fake_module}):
                first = submit(1, 1)
                second = submit(1, 2)
                next_round = submit(2, 3)
        finally:
            analyzer.close()

        self.assertEqual(len(instances), 1)
        self.assertEqual(
            [first["warehouseVision"]["slots"][0]["trackId"],
             second["warehouseVision"]["slots"][0]["trackId"],
             next_round["warehouseVision"]["slots"][0]["trackId"]],
            [1, 2, 1],
        )
        self.assertEqual(instances[0].reset_count, 1)

    def test_activity_slot_crop_is_the_exact_scoped_source_and_instance_decisions_stay_local(self):
        catalog = json.loads((ROOT / "assets/catalog_065.json").read_text(encoding="utf-8-sig"))
        item = next(row for row in catalog if row.get("Id") == "image31-0-1")
        alternate = next(row for row in catalog if row.get("Id") == "image31-0-2")
        current = CurrentMatch()
        current.id = "match-review"
        current.apply_facts({"roundNo": 1, "knownGold": "人工保护值"}, source="manual", intent="confirm")
        current.apply_facts({"warehouse": {"slots": []}}, source="vision", intent="observe")
        engine = _engine(current, [item, alternate])
        engine.data_origin = "offline-replay"

        with tempfile.TemporaryDirectory(dir=str(ROOT / "build")) as folder:
            engine.work_dir = Path(folder)
            engine._warehouse_activity_sources = {}
            frame = np.arange(8 * 9 * 3, dtype=np.uint8).reshape((8, 9, 3))
            source_result = {
                "sessionId": "session-review", "generationId": 22, "matchId": current.id,
                "capturedAt": "2026-09-25T03:00:00Z", "captureTimestampNs": 12345,
                "frameSequence": 81, "pixelSha256": "f" * 64, "dataOrigin": "offline-replay",
            }
            visual_slot = {
                "row": 1, "col": 2, "w": 1, "h": 1, "rarity": "gold",
                "box": [2, 1, 3, 2], "identityStatus": "CANDIDATE",
                "candidates": [{"catalogId": item["Id"], "name": item["Name"]}],
            }
            evidence = engine._activity_evidence_for_slot(source_result, frame, visual_slot)
            crop = cv2.imdecode(
                np.fromfile(str(engine.work_dir / evidence["relativePath"]), dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            self.assertEqual(evidence["sourceKind"], "offline-replay")
            self.assertEqual(evidence["sessionId"], "session-review")
            self.assertEqual(evidence["matchId"], "match-review")
            self.assertEqual(evidence["frameSequence"], 81)
            self.assertEqual(evidence["box"], [2, 1, 3, 2])
            np.testing.assert_array_equal(crop, frame[1:3, 2:5])

        scope = {
            "sessionId": "session-current", "generationId": 9, "matchId": current.id,
            "round": 1, "scene": "IN_AUCTION", "invalidationGeneration": 0,
        }
        base_slots = []
        for col in (0, 1):
            slot = {
                "row": 0, "col": col, "w": 1, "h": 1, "rarity": "gold",
                "trackId": 7, "identityStatus": "CANDIDATE", "evidenceLevel": "CANDIDATE_SET",
                "candidates": [
                    {"catalogId": item["Id"], "name": item["Name"], "quality": "gold", "width": 1, "height": 1},
                    {"catalogId": alternate["Id"], "name": alternate["Name"], "quality": "gold", "width": 1, "height": 1},
                ] if col == 0 else [
                    {"catalogId": item["Id"], "name": item["Name"], "quality": "gold", "width": 1, "height": 1},
                ],
                "activityEvidence": {"evidenceId": f"evidence-{col}", "sessionId": "session-current", "generationId": 9},
            }
            slot["instanceDecisionToken"] = engine._warehouse_instance_decision_token(scope, slot)
            slot["instanceDecisionGeneration"] = 0
            base_slots.append(slot)
        current.facts["warehouse"] = {"slots": copy.deepcopy(base_slots)}
        engine._warehouse_review_scope = copy.deepcopy(scope)
        engine._warehouse_review_vision = {"slots": copy.deepcopy(base_slots)}

        def proof(official):
            return {
                "catalogId": official["Id"], "inputName": official["Name"],
                "name": official["Name"], "quality": "gold", "price": official["Value"],
                "width": official["Width"], "height": official["Height"],
                "catalogVersion": "2026-08-13",
            }

        def command(slot, action, command_id, catalog_id=None):
            return engine._apply_warehouse_instance_decision(command_id, {
                "decision": action, "catalogId": catalog_id,
                "solverCatalogProof": proof(item if catalog_id == item["Id"] else alternate)
                    if action == "CONFIRM_CANDIDATE" else None,
                "expectedObservationSessionId": "session-current", "expectedMatchId": current.id,
                "expectedRound": 1, "expectedGenerationId": 9,
                "expectedInvalidationGeneration": 0,
                "instanceAnchor": {key: slot[key] for key in ("row", "col", "w", "h", "rarity")},
                "instanceDecisionToken": slot["instanceDecisionToken"],
                "activityEvidenceId": slot["activityEvidence"]["evidenceId"],
            })

        status, error, confirmed = command(base_slots[0], "CONFIRM_CANDIDATE", "confirm-one", item["Id"])
        self.assertEqual((status, error), ("ACK", None))
        self.assertEqual(confirmed["status"], "APPLIED")
        self.assertEqual(confirmed["knownFacts"], {"knownGold": f"人工保护值+{item['Name']}"})
        self.assertTrue(confirmed["valuationInputChanged"])
        slots_after_confirm = current.facts["warehouse"]["slots"]
        self.assertEqual(slots_after_confirm[0]["manualDecision"]["source"], "HUMAN_INSTANCE_REVIEW")
        self.assertEqual(slots_after_confirm[0]["manualDecision"]["manualIdentity"]["status"], "MANUAL_CONFIRMED")
        self.assertEqual(slots_after_confirm[0]["manualDecision"]["manualIdentity"]["source"], "HUMAN_INSTANCE_REVIEW")
        self.assertEqual(slots_after_confirm[0]["identityStatus"], "CANDIDATE")
        self.assertNotIn("manualDecision", slots_after_confirm[1])
        self.assertEqual(current.facts["knownGold"], f"人工保护值+{item['Name']}")
        self.assertTrue(current.field_states["knownGold"].protected)
        self.assertEqual(current.field_states["knownGold"].source, "warehouse_identity_ledger")
        canonical = current.to_canonical()
        self.assertEqual(canonical["warehouse"]["slots"][0]["identityStatus"], "CANDIDATE")
        self.assertEqual(canonical["warehouse"]["slots"][0]["manualDecision"]["source"], "HUMAN_INSTANCE_REVIEW")
        self.assertEqual(
            [row["name"] for row in canonical["qualities"]["gold"]["knownItems"]].count(item["Name"]), 1,
        )

        status, error, confirmed_second = command(base_slots[1], "CONFIRM_CANDIDATE", "confirm-second", item["Id"])
        self.assertEqual((status, error), ("ACK", None))
        self.assertEqual(confirmed_second["knownFacts"], {"knownGold": f"人工保护值+{item['Name']}+{item['Name']}"})
        self.assertEqual(current.facts["knownGold"], f"人工保护值+{item['Name']}+{item['Name']}")
        self.assertEqual(
            [row["name"] for row in current.to_canonical()["qualities"]["gold"]["knownItems"]].count(item["Name"]), 2,
        )

        status, error, retried = command(base_slots[0], "CONFIRM_CANDIDATE", "confirm-retry", item["Id"])
        self.assertEqual((status, error), ("ACK", None))
        self.assertTrue(retried["idempotent"])
        self.assertFalse(retried["valuationInputChanged"])
        self.assertEqual(retried["knownFacts"], {})
        self.assertEqual(len(current.facts["warehouse"]["slots"]), 2)

        status, error, reidentified = command(base_slots[0], "CONFIRM_CANDIDATE", "reidentify-one", alternate["Id"])
        self.assertEqual((status, error), ("ACK", None))
        self.assertEqual(current.facts["knownGold"], f"人工保护值+{alternate['Name']}+{item['Name']}")
        self.assertEqual(reidentified["knownFacts"], {"knownGold": f"人工保护值+{alternate['Name']}+{item['Name']}"})

        status, error, rejected = command(base_slots[1], "REJECT_CANDIDATE", "reject-second", item["Id"])
        self.assertEqual((status, error), ("ACK", None))
        self.assertEqual(rejected["status"], "APPLIED")
        self.assertEqual(rejected["knownFacts"], {"knownGold": f"人工保护值+{alternate['Name']}"})
        self.assertFalse(rejected["decision"].get("manualIdentity"))
        self.assertEqual(len(current.facts["warehouse"]["slots"]), 2)
        self.assertEqual(current.facts["warehouse"]["slots"][1]["manualDecision"]["action"], "REJECT_CANDIDATE")

        status, error, restored = command(base_slots[1], "RESTORE_AUTOMATIC", "restore-second")
        self.assertEqual((status, error), ("ACK", None))
        self.assertEqual(restored["status"], "APPLIED")
        self.assertNotIn("manualDecision", current.facts["warehouse"]["slots"][1])
        self.assertEqual(restored["knownFacts"], {})
        self.assertFalse(restored["valuationInputChanged"])
        self.assertEqual(current.facts["knownGold"], f"人工保护值+{alternate['Name']}")

        status, error, restored_first = command(base_slots[0], "RESTORE_AUTOMATIC", "restore-first")
        self.assertEqual((status, error), ("ACK", None))
        self.assertEqual(restored_first["knownFacts"], {"knownGold": "人工保护值"})
        self.assertTrue(restored_first["valuationInputChanged"])
        self.assertNotIn("manualDecision", current.facts["warehouse"]["slots"][0])
        self.assertEqual(current.facts["knownGold"], "人工保护值")

        engine.last_context["round"] = 2
        status, error, _late = command(base_slots[0], "REJECT_CANDIDATE", "old-round", item["Id"])
        self.assertEqual(status, "REJECT")
        self.assertEqual(error, "STALE_ROUND_OR_SCENE")

    def test_automatic_frames_preserve_one_instance_decision_without_promoting_it(self):
        current = CurrentMatch()
        current.id = "match-review"
        engine = _engine(current, [])
        old = {
            "row": 0, "col": 1, "w": 1, "h": 1, "rarity": "gold",
            "identityStatus": "CANDIDATE", "evidenceLevel": "CANDIDATE_SET",
            "candidates": [{"catalogId": "candidate-a", "name": "A"}],
            "manualDecision": {"action": "CONFIRM_CANDIDATE", "catalogId": "candidate-a", "source": "HUMAN_INSTANCE_REVIEW"},
        }
        incoming = {**old, "identityStatus": "EXACT", "identifiedName": "其他身份", "identifiedCatalogId": "candidate-b"}
        merged = engine._merge_warehouse_fact_slots({"slots": [old]}, {"slots": [incoming]})
        slot = merged["slots"][0]
        self.assertEqual(slot["identityStatus"], "CANDIDATE")
        self.assertTrue(slot["identityConflict"])
        self.assertEqual(slot["manualDecision"]["catalogId"], "candidate-a")

    def test_manual_valuation_rejects_display_only_ids_and_catalog_size_conflicts(self):
        catalog = json.loads((ROOT / "assets/catalog_065.json").read_text(encoding="utf-8-sig"))
        official = next(row for row in catalog if row.get("Id") == "image31-0-1")
        proof = {
            "catalogId": official["Id"], "inputName": official["Name"], "name": official["Name"],
            "quality": "gold", "price": official["Value"], "width": official["Width"],
            "height": official["Height"], "catalogVersion": "2026-08-13",
        }

        def run_decision(*, selected_id, row, candidate, official_rows, proof_name=None):
            current = CurrentMatch()
            current.id = "match-manual-eligibility"
            current.apply_facts({"roundNo": 1}, source="vision", intent="observe")
            engine = _engine(current, official_rows)
            scope = {
                "sessionId": "session-current", "generationId": 9, "matchId": current.id,
                "round": 1, "scene": "IN_AUCTION", "invalidationGeneration": 0,
            }
            slot = {
                "row": 0, "col": 0, "w": row["w"], "h": row["h"], "rarity": "gold",
                "identityStatus": "CANDIDATE", "evidenceLevel": "CANDIDATE_SET",
                "candidates": [candidate],
                "activityEvidence": {"evidenceId": "eligibility-evidence", "sessionId": "session-current", "generationId": 9},
            }
            slot["instanceDecisionToken"] = engine._warehouse_instance_decision_token(scope, slot)
            current.facts["warehouse"] = {"slots": [copy.deepcopy(slot)]}
            engine._warehouse_review_scope = copy.deepcopy(scope)
            engine._warehouse_review_vision = {"slots": [copy.deepcopy(slot)]}
            return engine._apply_warehouse_instance_decision("eligibility-command", {
                "decision": "CONFIRM_CANDIDATE", "catalogId": selected_id,
                "solverCatalogProof": {**proof, "catalogId": selected_id,
                                        **({"name": proof_name} if proof_name is not None else {})},
                "expectedObservationSessionId": "session-current", "expectedMatchId": current.id,
                "expectedRound": 1, "expectedGenerationId": 9, "expectedInvalidationGeneration": 0,
                "instanceAnchor": {key: slot[key] for key in ("row", "col", "w", "h", "rarity")},
                "instanceDecisionToken": slot["instanceDecisionToken"],
                "activityEvidenceId": "eligibility-evidence",
            }), current

        (status, error, _result), current = run_decision(
            selected_id="display-only-id", row={"w": 1, "h": 1},
            candidate={"catalogId": "display-only-id", "name": official["Name"], "quality": "gold"},
            official_rows=[official],
        )
        self.assertEqual(status, "REJECT")
        self.assertEqual(error, "CANDIDATE_CONFLICTS_WITH_OFFICIAL_CATALOG")
        self.assertEqual(current.facts["knownGold"], "")
        self.assertNotIn("manualDecision", current.facts["warehouse"]["slots"][0])

        (status, error, _result), current = run_decision(
            selected_id=official["Id"], row={"w": official["Width"], "h": official["Height"]},
            candidate={"catalogId": official["Id"], "name": official["Name"], "quality": "gold"},
            official_rows=[official], proof_name="unrelated solver name",
        )
        self.assertEqual(status, "REJECT")
        self.assertEqual(error, "IDENTITY_NOT_AVAILABLE_IN_CURRENT_SOLVER_CATALOG")
        self.assertEqual(current.facts["knownGold"], "")
        self.assertNotIn("manualDecision", current.facts["warehouse"]["slots"][0])

        (status, error, _result), current = run_decision(
            selected_id=official["Id"], row={"w": 2, "h": 1},
            candidate={"catalogId": official["Id"], "name": official["Name"], "quality": "gold", "width": 1, "height": 1},
            official_rows=[official],
        )
        self.assertEqual(status, "REJECT")
        self.assertEqual(error, "CANDIDATE_HAS_UNRESOLVED_QUALITY_SIZE_OR_CATALOG_CONFLICT")
        self.assertEqual(current.facts["knownGold"], "")
        self.assertNotIn("manualDecision", current.facts["warehouse"]["slots"][0])

    def test_restoring_manual_confirmation_reuses_same_valid_automatic_identity_once(self):
        catalog = json.loads((ROOT / "assets/catalog_065.json").read_text(encoding="utf-8-sig"))
        item = next(row for row in catalog if row.get("Id") == "image31-0-1")
        current = CurrentMatch()
        current.id = "match-restore-auto"
        current.apply_facts({"roundNo": 1}, source="vision", intent="observe")
        engine = _engine(current, [item])
        scope = {
            "sessionId": "session-current", "generationId": 9, "matchId": current.id,
            "round": 1, "scene": "IN_AUCTION", "invalidationGeneration": 0,
        }
        slot = {
            "row": 0, "col": 0, "w": 1, "h": 1, "rarity": "gold",
            "identityStatus": "CANDIDATE", "evidenceLevel": "CANDIDATE_SET",
            "candidates": [{"catalogId": item["Id"], "name": item["Name"]}],
            "activityEvidence": {"evidenceId": "restore-evidence", "sessionId": "session-current", "generationId": 9},
        }
        slot["instanceDecisionToken"] = engine._warehouse_instance_decision_token(scope, slot)
        current.facts["warehouse"] = {"slots": [copy.deepcopy(slot)]}
        engine._warehouse_review_scope = copy.deepcopy(scope)
        engine._warehouse_review_vision = {"slots": [copy.deepcopy(slot)]}
        command_base = {
            "expectedObservationSessionId": "session-current", "expectedMatchId": current.id,
            "expectedRound": 1, "expectedGenerationId": 9, "expectedInvalidationGeneration": 0,
            "instanceAnchor": {key: slot[key] for key in ("row", "col", "w", "h", "rarity")},
            "instanceDecisionToken": slot["instanceDecisionToken"], "activityEvidenceId": "restore-evidence",
        }
        proof = {
            "catalogId": item["Id"], "inputName": item["Name"], "name": item["Name"],
            "quality": "gold", "price": item["Value"], "width": item["Width"],
            "height": item["Height"], "catalogVersion": "2026-08-13",
        }
        status, error, confirmed = engine._apply_warehouse_instance_decision(
            "confirm-auto-backed", {**command_base, "decision": "CONFIRM_CANDIDATE", "catalogId": item["Id"], "solverCatalogProof": proof},
        )
        self.assertEqual((status, error), ("ACK", None))
        self.assertEqual(confirmed["knownFacts"]["knownGold"], item["Name"])

        automatic_slot = copy.deepcopy(current.facts["warehouse"]["slots"][0])
        automatic_slot.update({
            "identityStatus": "EXACT", "evidenceLevel": "EXACT_IDENTIFIED",
            "identifiedCatalogId": item["Id"], "identifiedName": item["Name"],
            "identityReferenceKind": "DIRECT",
        })
        current.apply_facts({"warehouse": {"slots": [automatic_slot]}}, source="vision", intent="observe")
        status, error, restored = engine._apply_warehouse_instance_decision(
            "restore-auto-backed", {**command_base, "decision": "RESTORE_AUTOMATIC"},
        )
        self.assertEqual((status, error), ("ACK", None))
        self.assertEqual(restored["knownFacts"], {})
        self.assertFalse(restored["valuationInputChanged"])
        self.assertEqual(current.facts["knownGold"], item["Name"])
        self.assertEqual(current.facts["warehouse"]["slots"][0]["identityStatus"], "EXACT")
        self.assertNotIn("manualDecision", current.facts["warehouse"]["slots"][0])

    def test_rejected_candidate_cannot_reappear_as_an_automatic_exact_identity(self):
        old = {
            "row": 0, "col": 1, "w": 1, "h": 1, "rarity": "gold",
            "identityStatus": "CANDIDATE", "evidenceLevel": "CANDIDATE_SET",
            "candidates": [{"catalogId": "candidate-a", "name": "A"}],
            "manualDecision": {
                "action": "REJECT_CANDIDATE", "catalogId": "candidate-a",
                "source": "HUMAN_INSTANCE_REVIEW",
            },
        }
        incoming = {
            **old, "identityStatus": "EXACT", "evidenceLevel": "EXACT_IDENTIFIED",
            "identifiedCatalogId": "candidate-a", "identifiedName": "A",
        }

        merged = RealEngine._merge_warehouse_fact_slots({"slots": [old]}, {"slots": [incoming]})
        slot = merged["slots"][0]

        self.assertEqual(slot["identityStatus"], "CANDIDATE")
        self.assertNotIn("identifiedCatalogId", slot)
        self.assertNotIn("identifiedName", slot)
        self.assertEqual(slot["manualDecision"]["action"], "REJECT_CANDIDATE")

    def test_deferred_take_transfers_frame_descriptor_without_mutating_context(self):
        pipeline = NTEVisionPipeline.__new__(NTEVisionPipeline)
        marker = {"scene": "IN_AUCTION", "round": 5, "warehouseVision": {"slots": []}}
        pending = {"kind": "warehouse", "frame": np.zeros((2, 2, 3), dtype=np.uint8), "round": 5}
        pipeline.current_context = copy.deepcopy(marker)
        pipeline._pending_heavy_identity = pending

        taken = pipeline.take_deferred_identity()
        self.assertIsNot(taken, pending)
        self.assertIs(taken["frame"], pending["frame"])
        self.assertEqual(pipeline.current_context, marker)
        self.assertIsNone(pipeline._pending_heavy_identity)

    def test_generated_references_are_hash_checked_and_unverified(self):
        loaded = load_derived_warehouse_templates(root=ROOT)
        self.assertTrue(loaded)
        self.assertTrue(all(
            row["metadata"]["status"] == "DERIVED_UNVERIFIED"
            and row["metadata"]["isGameplayEvidence"] is False
            and row["metadata"]["solverIdentityEligible"] is False
            for row in loaded.values()
        ))

    def test_derived_match_can_rank_but_cannot_be_exact(self):
        roi = np.random.default_rng(22).integers(0, 256, (40, 40, 3), dtype=np.uint8)
        matcher = WarehouseTemplateMatcher.__new__(WarehouseTemplateMatcher)
        matcher.templates = {}
        matcher.derived_templates_by_id = {"truth": {"image": roi.copy()}}
        candidates = [{"Id": "other", "Name": "Other"}, {"Id": "truth", "Name": "Truth"}]

        best, score, _margin, evidence = matcher.match_candidate_evidence(
            roi, candidates, WarehouseVisionConfig()
        )
        self.assertEqual(best["Id"], "truth")
        self.assertEqual(score, 1.0)
        self.assertEqual(evidence["referenceKind"], "DERIVED_UNVERIFIED")
        self.assertTrue(evidence["accepted"])
        self.assertIsNone(matcher.match_candidates(roi, candidates, WarehouseVisionConfig())[0])

    def test_settlement_reference_matches_labeled_crop_from_another_match(self):
        settlement_path = ROOT / "assets/items/video_ground_truth_reference_144037.json"
        settlement = json.loads(settlement_path.read_text(encoding="utf-8"))
        reference_row = next(row for row in settlement["items"] if row["referenceId"] == "ref_144037_38")
        other_match_path = ROOT / "assets/items/video_ground_truth_reference_134043_visible.json"
        other_match = json.loads(other_match_path.read_text(encoding="utf-8"))
        other_match_row = next(row for row in other_match["items"] if row["catalogId"] == reference_row["catalogId"])

        roi = cv2.imdecode(np.fromfile(str(ROOT / other_match_row["localCropPath"]), np.uint8), cv2.IMREAD_COLOR)
        matcher = WarehouseTemplateMatcher()
        references = load_verified_warehouse_gameplay_templates(root=ROOT)
        settlement_reference = next(
            item for item in references[reference_row["catalogId"]]
            if item["metadata"]["referenceId"] == reference_row["referenceId"]
        )
        self.assertEqual(settlement_reference["metadata"]["sourceSceneKind"], "SETTLEMENT")
        self.assertEqual(settlement_reference["metadata"]["referenceRole"], "VISUAL_TEMPLATE_ONLY")
        self.assertEqual(settlement_reference["metadata"]["sourceFrameTimeSec"], 168.0)
        self.assertEqual(other_match["metadata"]["sourceSceneKind"], "SETTLEMENT")
        self.assertEqual(other_match["metadata"]["sourceFrameTimeSec"], 150)
        self.assertFalse(any(
            item["metadata"]["referenceId"] == "ref_144037_23"
            for group in references.values() for item in group
        ))

        matcher.templates = {}
        matcher.derived_templates_by_id = {}
        matcher.gameplay_templates_by_id = {reference_row["catalogId"]: [settlement_reference]}
        geometry = other_match_row["gridBoundingBox"]
        candidates = matcher.get_candidates(
            other_match_row["quality"], geometry["width"], geometry["height"]
        )

        best, _score, _margin, evidence = matcher.match_candidate_evidence(
            roi, candidates, WarehouseVisionConfig()
        )

        self.assertEqual(best["Id"], other_match_row["catalogId"])
        self.assertTrue(evidence["accepted"])
        self.assertEqual(evidence["referenceSource"], "VERIFIED_SETTLEMENT_REFERENCE")

    def test_feature_evidence_resolves_low_pixel_score_across_matches_with_lookalike(self):
        query_path = ROOT / "assets/items/video_ground_truth_reference_134043_visible.json"
        query_group = json.loads(query_path.read_text(encoding="utf-8"))
        query_row = next(row for row in query_group["items"] if row["catalogId"] == "image9-1-2")
        reference_path = ROOT / "assets/items/video_ground_truth_reference_134436_match2_visible.json"
        reference_group = json.loads(reference_path.read_text(encoding="utf-8"))
        reference_row = next(row for row in reference_group["items"] if row["catalogId"] == query_row["catalogId"])
        roi = cv2.imdecode(np.fromfile(str(ROOT / query_row["localCropPath"]), np.uint8), cv2.IMREAD_COLOR)

        matcher = WarehouseTemplateMatcher()
        references = load_verified_warehouse_gameplay_templates(root=ROOT)
        query_reference = next(
            item for group in references.values() for item in group
            if item["metadata"]["referenceId"] == query_row["referenceId"]
        )
        query_match_id = query_reference["metadata"]["groupId"]
        matcher.templates = {}
        matcher.derived_templates_by_id = {}
        matcher.gameplay_templates_by_id = {
            catalog_id: [item for item in group if item["metadata"].get("groupId") != query_match_id]
            for catalog_id, group in references.items()
        }
        geometry = query_row["gridBoundingBox"]
        candidates = matcher.get_candidates(query_row["quality"], geometry["width"], geometry["height"])
        truth = next(item for item in candidates if item["Id"] == query_row["catalogId"])
        lookalike_id = "image9-0-2"
        lookalike = next(item for item in candidates if item["Id"] == lookalike_id)
        raw_score, _ = matcher.score_direct_reference(roi, truth)
        lookalike_raw_score, _ = matcher.score_direct_reference(roi, lookalike)

        best, score, margin, evidence = matcher.match_candidate_evidence(
            roi, candidates, WarehouseVisionConfig()
        )

        self.assertEqual(reference_group["metadata"]["sourceSceneKind"], "SETTLEMENT")
        self.assertLess(raw_score, WarehouseVisionConfig.MATCH_CONFIDENCE_THRESHOLD)
        self.assertLess(lookalike_raw_score, WarehouseVisionConfig.MATCH_CONFIDENCE_THRESHOLD)
        self.assertEqual(best["Id"], query_row["catalogId"])
        self.assertGreaterEqual(score, WarehouseVisionConfig.MATCH_CONFIDENCE_THRESHOLD)
        self.assertGreaterEqual(margin, WarehouseVisionConfig.MATCH_MARGIN_THRESHOLD)
        self.assertTrue(evidence["accepted"])
        self.assertEqual(evidence["referenceKind"], "DIRECT")
        self.assertEqual(evidence["matchingMethod"], "RECIPROCAL_FEATURE_GEOMETRY")

    def test_direct_exact_result_keeps_legacy_priority_over_derived_image(self):
        roi = np.random.default_rng(41).integers(0, 256, (36, 36, 3), dtype=np.uint8)
        matcher = WarehouseTemplateMatcher.__new__(WarehouseTemplateMatcher)
        matcher.templates = {"trusted.png": roi.copy()}
        matcher.derived_templates_by_id = {"derived-rival": {"image": roi.copy()}}
        candidates = [
            {"Id": "trusted", "Name": "Trusted", "File": "trusted.png"},
            {"Id": "derived-rival", "Name": "Rival"},
        ]
        best, _score, _margin = matcher.match_candidates(roi, candidates, WarehouseVisionConfig())
        self.assertEqual(best["Id"], "trusted")
        self.assertEqual(best, candidates[0])

    def test_native_commit_projects_direct_identity_to_existing_facts_only(self):
        catalog = json.loads((ROOT / "assets/catalog_065.json").read_text(encoding="utf-8-sig"))
        item = next(row for row in catalog if row.get("Quality") == "金" and row.get("Width") == 1 and row.get("Height") == 1)
        current = CurrentMatch()
        current.id = "match-current"
        current.apply_facts({"roundNo": 1}, source="vision", intent="observe")
        engine = _engine(current, [item])
        slot = {
            "col": 0, "row": 0, "w": 1, "h": 1, "rarity": "gold",
            "evidenceLevel": "EXACT_IDENTIFIED", "identityStatus": "EXACT",
            "identifiedCatalogId": item["Id"], "identifiedName": item["Name"],
            "identityReferenceKind": "DIRECT",
            "candidates": [{"catalogId": item["Id"], "name": item["Name"]}],
        }
        result = self._result(engine, {"slots": [slot], "totalExpectedVal": 100, "valRange": [100, 100]})

        self.assertTrue(engine._commit_deferred_identity(result))
        self.assertEqual(current.facts["warehouse"]["slots"][0]["identityStatus"], "EXACT")
        self.assertEqual(current.facts["knownGold"], item["Name"])
        self.assertEqual(current.to_canonical()["warehouse"]["slots"][0]["identifiedName"], item["Name"])

    def test_native_commit_counts_repeated_catalog_items_by_grid_instance_across_track_resets(self):
        catalog = json.loads((ROOT / "assets/catalog_065.json").read_text(encoding="utf-8-sig"))
        item = next(row for row in catalog if row.get("Id") == "image30-1-2")
        manifest = json.loads((ROOT / "assets/items/video_ground_truth_reference_134436_match2_visible.json").read_text(encoding="utf-8"))
        repeated = [row for row in manifest["items"] if row.get("catalogId") == item["Id"]]
        self.assertEqual(item["Quality"], "金")
        self.assertEqual(len(repeated), 2)
        positions = [
            (int(row["gridBoundingBox"]["row"]), int(row["gridBoundingBox"]["col"]))
            for row in repeated
        ]
        self.assertEqual(len(set(positions)), 2)

        current = CurrentMatch()
        current.id = "match-current"
        current.apply_facts({"roundNo": 1}, source="vision", intent="observe")
        engine = _engine(current, [item])

        def slots(track_ids):
            return [
                {
                    "col": int(row["gridBoundingBox"]["col"]),
                    "row": int(row["gridBoundingBox"]["row"]),
                    "w": int(row["gridBoundingBox"]["width"]),
                    "h": int(row["gridBoundingBox"]["height"]),
                    "rarity": "gold",
                    "evidenceLevel": "EXACT_IDENTIFIED",
                    "identityStatus": "EXACT",
                    "identifiedCatalogId": item["Id"],
                    "identifiedName": item["Name"],
                    "identityReferenceKind": "DIRECT",
                    "candidates": [{"catalogId": item["Id"], "name": item["Name"]}],
                    "trackId": track_id,
                }
                for row, track_id in zip(repeated, track_ids)
            ]

        first = self._result(engine, {"slots": slots([3, 8])}, frame_sequence=10, round_value=1)
        self.assertTrue(engine._commit_deferred_identity(first))
        expected = f"{item['Name']}+{item['Name']}"
        self.assertEqual(current.facts["knownGold"], expected)
        self.assertEqual(len(current.facts["warehouse"]["slots"]), 2)
        self.assertEqual(
            current.to_canonical()["qualities"]["gold"]["knownItems"],
            [{"name": item["Name"]}, {"name": item["Name"]}],
        )

        # The temporal track numbers are worker-local. Reobserving the same
        # physical grid cells must keep the same two constraints.
        second = self._result(engine, {"slots": slots([31, 84])}, frame_sequence=11, round_value=1)
        self.assertTrue(engine._commit_deferred_identity(second))
        self.assertEqual(current.facts["knownGold"], expected)

        # A round-scoped recognizer restarts its track numbering; the match's
        # canonical warehouse grid remains the instance ledger.
        current.apply_facts({"roundNo": 2}, source="vision", intent="observe")
        engine.last_context = {"scene": "IN_AUCTION", "inAuction": True, "round": 2}
        third = self._result(engine, {"slots": slots([1, 2])}, frame_sequence=12, round_value=2)
        self.assertTrue(engine._commit_deferred_identity(third))
        self.assertEqual(current.facts["knownGold"], expected)

        # A resumed observation session gets a fresh temporal tracker too.
        resumed = _engine(current, [item])
        resumed.session_id = "session-resumed"
        resumed.last_context = {"scene": "IN_AUCTION", "inAuction": True, "round": 2}
        resumed_result = self._result(resumed, {"slots": slots([201, 202])}, frame_sequence=13, round_value=2)
        self.assertTrue(resumed._commit_deferred_identity(resumed_result))
        self.assertEqual(current.facts["knownGold"], expected)

        current.begin_next_match()
        current.id = "match-next"
        self.assertEqual(current.facts["knownGold"], "")
        self.assertIsNone(current.facts["warehouse"])

    def test_native_identity_observation_cannot_replace_manually_protected_known_items(self):
        catalog = json.loads((ROOT / "assets/catalog_065.json").read_text(encoding="utf-8-sig"))
        item = next(row for row in catalog if row.get("Quality") == "金" and row.get("Width") == 1 and row.get("Height") == 1)
        current = CurrentMatch()
        current.id = "match-current"
        current.apply_facts({"roundNo": 1}, source="vision", intent="observe")
        current.apply_facts({"knownGold": "手动保护值"}, source="manual", intent="confirm")
        engine = _engine(current, [item])
        slot = {
            "col": 0, "row": 0, "w": 1, "h": 1, "rarity": "gold",
            "evidenceLevel": "EXACT_IDENTIFIED", "identityStatus": "EXACT",
            "identifiedCatalogId": item["Id"], "identifiedName": item["Name"],
            "identityReferenceKind": "DIRECT",
            "candidates": [{"catalogId": item["Id"], "name": item["Name"]}],
        }
        result = self._result(engine, {"slots": [slot]})

        self.assertTrue(engine._commit_deferred_identity(result))
        self.assertEqual(current.facts["knownGold"], "手动保护值")
        self.assertEqual(current.field_states["knownGold"].source, "manual")
        self.assertTrue(current.field_states["knownGold"].protected)

    def test_derived_candidate_is_not_promoted_to_solver_known_fact(self):
        current = CurrentMatch()
        current.id = "match-current"
        current.apply_facts({"roundNo": 1}, source="vision", intent="observe")
        engine = _engine(current, [])
        slot = {
            "col": 1, "row": 2, "w": 1, "h": 1, "rarity": "gold",
            "evidenceLevel": "CANDIDATE_SET", "identityStatus": "CANDIDATE",
            "bestCandidateId": "derived-only", "bestCandidateName": "Unverified",
            "identityReferenceKind": "DERIVED_UNVERIFIED", "candidates": [],
        }
        result = self._result(engine, {"slots": [slot], "totalExpectedVal": 0, "valRange": [0, 0]})

        self.assertTrue(engine._commit_deferred_identity(result))
        self.assertEqual(current.facts["knownGold"], "")
        self.assertIsNone(current.to_canonical()["warehouse"]["slots"][0]["identifiedName"])

    def test_settlement_identity_stays_out_of_preauction_known_facts(self):
        current = CurrentMatch()
        current.id = "match-current"
        current.apply_facts({"roundNo": 1}, source="vision", intent="observe")
        engine = _engine(current, [])
        engine.last_context = {"scene": "SETTLEMENT", "isSettlement": True, "round": 1}
        result = self._result(engine, {})
        result.update({
            "kind": "settlement", "scene": "SETTLEMENT", "settlementItems": [
                {"status": "exact", "exactItemId": "revealed-after-auction", "name": "结算揭示藏品"}
            ],
            "settlementLedgerVerified": True, "settlementLedgerStatus": "verified",
            "settlementLedgerDelta": 0,
        })
        result.pop("warehouseVision")

        self.assertTrue(engine._commit_deferred_identity(result))
        self.assertEqual(current.facts["settlementItems"][0]["exactItemId"], "revealed-after-auction")
        self.assertEqual(current.facts["knownGold"], "")

    def test_settlement_deferred_pixels_do_not_enter_durable_ledger(self):
        current = CurrentMatch()
        current.id = "match-current"
        current.apply_facts({"roundNo": 1}, source="vision", intent="observe")
        engine = _engine(current, [])
        engine.last_context = {"scene": "SETTLEMENT", "isSettlement": True, "round": 1,
                               "settlementData": {"clearingPrice": 666666}}
        result = self._result(engine, {})
        result.update({
            "kind": "settlement", "scene": "SETTLEMENT",
            "settlementItems": [{"status": "unknown", "price": None}],
            "settlementLedgerStatus": "partial",
            "sourceFrameBgr": np.zeros((2, 2, 3), dtype=np.uint8),
        })
        result.pop("warehouseVision")

        self.assertTrue(engine._commit_deferred_identity(result))
        ledger = engine.last_context["settlementData"]["ledger"]
        self.assertEqual(ledger["settlementItems"][0]["status"], "unknown")
        self.assertNotIn("sourceFrameBgr", ledger)
        json.dumps(engine.last_context)

    def test_result_from_old_session_or_invalidation_generation_is_rejected(self):
        result = {
            "sessionId": "session-current", "generationId": 9, "matchId": "match-current",
            "matchSequence": 2, "pipelineMatchGeneration": 7, "pipelineSessionGeneration": 3,
            "invalidationGeneration": 4, "factsRevisionAtDispatch": 5,
            "frameSequence": 40, "kind": "warehouse", "round": 2,
            "scene": "IN_AUCTION", "recognitionMode": "auto",
        }
        current = {
            "sessionId": "session-current", "generationId": 9, "matchId": "match-current",
            "matchSequence": 2, "pipelineMatchGeneration": 7, "pipelineSessionGeneration": 3,
            "invalidationGeneration": 5, "factsRevision": 6, "lastCommittedFrameSequence": 39,
            "scene": "IN_AUCTION", "round": 2, "recognitionMode": "auto",
        }
        self.assertFalse(deferred_identity_result_is_current(result, current))
        current["invalidationGeneration"] = 4
        self.assertTrue(deferred_identity_result_is_current(result, current))
        current["matchId"] = "next-match"
        self.assertFalse(deferred_identity_result_is_current(result, current))
        current["matchId"] = "match-current"
        current["sessionId"] = "old-session"
        self.assertFalse(deferred_identity_result_is_current(result, current))

    def test_deferred_sequence_guard_stays_bounded_to_active_scope(self):
        current = CurrentMatch()
        current.id = "match-0"
        engine = _engine(current, [])
        engine._identity_scope_key = None

        for index in range(12):
            current.id = f"match-{index}"
            engine._identity_scope_kind({"scene": "IN_AUCTION", "round": index + 1})
            active_key = ("warehouse", current.id, index + 1)
            engine._identity_last_committed_sequence[active_key] = index

        self.assertEqual(engine._identity_last_committed_sequence, {active_key: 11})

    @staticmethod
    def _result(engine, warehouse_vision, *, frame_sequence=10, round_value=1):
        return {
            "kind": "warehouse", "sessionId": engine.session_id, "generationId": engine.generation_id,
            "matchId": engine.current_match.id, "matchSequence": engine.current_match._seq,
            "pipelineMatchGeneration": engine.pipeline._match_gen,
            "pipelineSessionGeneration": engine.pipeline._session_generation,
            "factsRevisionAtDispatch": engine.current_match.facts_revision,
            "invalidationGeneration": 0, "round": round_value, "scene": "IN_AUCTION",
            "recognitionMode": "auto",
            "frameSequence": frame_sequence, "captureTimestampNs": 2000, "capturedAt": "2026-09-24T00:00:00+00:00",
            "pixelSha256": "a" * 64, "warehouseVision": copy.deepcopy(warehouse_vision),
        }


if __name__ == "__main__":
    unittest.main()
