import copy
import json
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "architecture" / "v2" / "host" / "engine_v22"))

from current_match import CurrentMatch
from deferred_identity_analyzer import deferred_identity_result_is_current
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

    def test_verified_gameplay_crop_uses_existing_strict_direct_gate(self):
        check_path = ROOT / "assets/items/video_ground_truth_reference_144037.json"
        check = json.loads(check_path.read_text(encoding="utf-8"))
        item = next(row for row in check["items"] if row["referenceId"] == "ref_144037_05")
        geometry = item["gridBoundingBox"]
        roi = cv2.imdecode(np.fromfile(str(ROOT / item["localCropPath"]), np.uint8), cv2.IMREAD_COLOR)
        matcher = WarehouseTemplateMatcher()
        references = load_verified_warehouse_gameplay_templates(root=ROOT)

        best, _score, _margin, evidence = matcher.match_candidate_evidence(
            roi,
            matcher.get_candidates(item["quality"], geometry["width"], geometry["height"]),
            WarehouseVisionConfig(),
        )

        self.assertEqual(best["Id"], item["catalogId"])
        self.assertTrue(evidence["accepted"])
        self.assertEqual(evidence["referenceSource"], "VERIFIED_GAMEPLAY_REFERENCE")
        self.assertTrue(references)
        self.assertTrue(all(
            reference["metadata"]["groupId"] in {
                "video_audit_20260908_134043",
                "video_audit_20260908_134436_match2",
            }
            for group in references.values() for reference in group
        ))

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
    def _result(engine, warehouse_vision):
        return {
            "kind": "warehouse", "sessionId": engine.session_id, "generationId": engine.generation_id,
            "matchId": engine.current_match.id, "matchSequence": engine.current_match._seq,
            "pipelineMatchGeneration": engine.pipeline._match_gen,
            "pipelineSessionGeneration": engine.pipeline._session_generation,
            "factsRevisionAtDispatch": engine.current_match.facts_revision,
            "invalidationGeneration": 0, "round": 1, "scene": "IN_AUCTION",
            "recognitionMode": "auto",
            "frameSequence": 10, "captureTimestampNs": 2000, "capturedAt": "2026-09-24T00:00:00+00:00",
            "pixelSha256": "a" * 64, "warehouseVision": copy.deepcopy(warehouse_vision),
        }


if __name__ == "__main__":
    unittest.main()
