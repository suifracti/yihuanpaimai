# -*- coding: utf-8 -*-
"""Targeted contract and verification tests for warehouse evidence-backed auto-confirmation
and same-match history persistence.

Covers:
1. Multi-dimensional evidence gate (geometry, multi-frame hash deduplication, inliers, margin).
2. Anti-overcounting: same image hash across multiple sequence indices counts as only 1 vote.
3. Cross-frame identity conflict rejection.
4. Prohibition of confirming merely because candidate count == 1.
5. Absolute protection of human review decisions against background auto-confirmation overwrite.
6. Match ID isolation: late-arriving results for non-existent or mismatched matches fail closed.
7. Transactional persistence idempotency and restart read-back completeness.
8. Raw crop export and provenance manifest generation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (str(PROJECT_ROOT / "core"), str(PROJECT_ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

from canonical_history_store import CanonicalHistoryStore, HistoryStoreError
from canonical_match_record import build_canonical_match_record_v7
from catalog_validator import get_official_name
from warehouse_identity_review import (
    CatalogAuthority,
    artifact_fingerprint_for,
    build_auto_identity_review_artifact,
)
from warehouse_identity_review_persist import summarize_persisted_identity_review
from warehouse_auto_confirmation import (
    CONFIRMATION_STATUS_CANDIDATE,
    CONFIRMATION_STATUS_CONFIRMED,
    STATUS_CONFIRMED,
    STATUS_UNCONFIRMED,
    evaluate_auto_confirmation,
    export_warehouse_evidence_crops,
    extract_human_decisions,
)


def _make_dummy_image(color=(100, 150, 200), size=(300, 300)) -> np.ndarray:
    img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    img[:] = color
    return img


class TestWarehouseAutoConfirmationAndPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)
        self.db_path = self.test_dir / "test_history.json"
        self.store = CanonicalHistoryStore(self.db_path)

        # Content-addressed fixtures must use the actual encoded image digest.
        self.blob_hashes = []
        for index in range(2):
            mock_img = np.zeros((400, 400, 3), dtype=np.uint8)
            mock_img[10:130, 10:90] = [50 + index, 100, 150]
            ok, buf = cv2.imencode(".png", mock_img)
            self.assertTrue(ok)
            raw = buf.tobytes()
            sha = hashlib.sha256(raw).hexdigest()
            self.blob_hashes.append(sha)
            bdir = self.test_dir / "evidence" / "settlement_v2" / "blobs" / sha[:2]
            bdir.mkdir(parents=True, exist_ok=True)
            (bdir / f"{sha}.png").write_bytes(raw)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _sample_unit(
        self,
        uid: str = "unit-world-5-0-2x3",
        placement_status: str = "RESOLVED",
        catalog_id: str = "image1-0-0",
        name: Optional[str] = None,
        inliers: int = 15,
        margin: int = 8,
        observations: list = None,
    ) -> dict:
        if name is None:
            name = get_official_name(catalog_id)
        if not name:
            raise ValueError(f"Unknown catalogId in test: {catalog_id}")
        if observations is None:
            observations = [
                {
                    "observationId": f"obs-{uid}-0",
                    "evidenceId": "ev_seg_0",
                    "sequenceIndex": 0,
                    "sha256": self.blob_hashes[0],
                    "bbox": [10.0, 10.0, 80.0, 120.0],
                    "status": "FULL",
                    "matchedCandidateId": catalog_id,
                    "inliers": inliers,
                    "margin": margin,
                },
                {
                    "observationId": f"obs-{uid}-1",
                    "evidenceId": "ev_seg_1",
                    "sequenceIndex": 1,
                    "sha256": self.blob_hashes[1],
                    "bbox": [10.0, 10.0, 80.0, 120.0],
                    "status": "FULL",
                    "matchedCandidateId": catalog_id,
                    "inliers": inliers,
                    "margin": margin,
                },
            ]
        return {
            "reviewUnitId": uid,
            "placementStatus": placement_status,
            "visibility": "FULL",
            "worldAnchor": {"row": 5, "col": 0},
            "footprint": {"widthCells": 2, "heightCells": 3},
            "physicalGroupId": "group-world-5-0",
            "geometryEvidenceStatus": "EXACT",
            "identityStatus": "REVIEW_REQUIRED",
            "selectedCatalogId": None,
            "bestObservationId": observations[0]["observationId"] if observations else None,
            "supportingTrackIds": ["track-1"],
            "observations": observations,
            "candidateStatus": "UNIQUE_IN_CATALOG",
            "candidates": [
                {
                    "catalogId": catalog_id,
                    "name": name,
                    "identityStatus": "CANDIDATE_ONLY",
                    "geometry": {"width": 2, "height": 3, "cells": 6, "shape": "2x3"},
                    "matchReasons": ["WHOLE_CARD_MATCH", f"SIFT_INLIERS_{inliers}"],
                    "score": 0.85,
                    "inliers": inliers,
                    "margin": margin,
                }
            ],
            "widthCandidates": [2],
            "heightCandidates": [3],
            "spanCandidates": [6],
        }

    # --------------------------------------------------------------------------
    # 1. Strong evidence confirmation
    # --------------------------------------------------------------------------
    def test_auto_confirmation_strong_evidence_passes(self):
        """Unit with RESOLVED placement, inliers >= 7, margin >= 5, and >= 2 independent frames confirms."""
        unit = self._sample_unit(inliers=18, margin=9)
        evaluated = evaluate_auto_confirmation([unit])
        self.assertEqual(len(evaluated), 1)
        res = evaluated[0]
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CONFIRMED)
        self.assertEqual(res["identityStatus"], STATUS_CONFIRMED)
        self.assertEqual(res["selectedCatalogId"], "image1-0-0")
        self.assertEqual(res["canonicalName"], get_official_name("image1-0-0"))
        self.assertTrue(any("EVIDENCE_BACKED_AUTO_CONFIRMATION" in str(r) for r in res["confirmationReasons"]))

    # --------------------------------------------------------------------------
    # 2. Geometric Ambiguity Rejection
    # --------------------------------------------------------------------------
    def test_auto_confirmation_ambiguous_region_rejected(self):
        """Unit in AMBIGUOUS_REGION must remain CANDIDATE_ONLY even with high inliers."""
        unit = self._sample_unit(placement_status="AMBIGUOUS_REGION", inliers=25, margin=15)
        evaluated = evaluate_auto_confirmation([unit])
        res = evaluated[0]
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertEqual(res["identityStatus"], STATUS_UNCONFIRMED)
        self.assertIsNone(res["selectedCatalogId"])
        self.assertIn("PLACEMENT_AMBIGUOUS_REGION", res["unconfirmedReasons"])

    # --------------------------------------------------------------------------
    # 3. Weak Evidence Rejections
    # --------------------------------------------------------------------------
    def test_auto_confirmation_low_inliers_rejected(self):
        """Unit with inliers < 7 is rejected from auto-confirmation."""
        unit = self._sample_unit(inliers=6, margin=6)
        evaluated = evaluate_auto_confirmation([unit])
        res = evaluated[0]
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("INSUFFICIENT_INLIERS_6_MIN_7", res["unconfirmedReasons"])

    def test_auto_confirmation_low_margin_rejected(self):
        """Unit with competition margin < 5 is rejected from auto-confirmation."""
        unit = self._sample_unit(inliers=15, margin=3)
        evaluated = evaluate_auto_confirmation([unit])
        res = evaluated[0]
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("LOW_COMPETITION_MARGIN_3_MIN_5", res["unconfirmedReasons"])

    # --------------------------------------------------------------------------
    # 4. Single candidate does NOT bypass evidence gate
    # --------------------------------------------------------------------------
    def test_single_candidate_insufficient_evidence_rejected(self):
        """Having len(candidates) == 1 does NOT entitle an item to confirmation."""
        # Only 1 candidate, but only 1 observation frame
        obs_single = [
            {
                "observationId": "obs-1",
                "evidenceId": "ev-1",
                "sequenceIndex": 0,
                "sha256": "aaaa" * 16,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
                "inliers": 15,
                "margin": 15,
            }
        ]
        unit = self._sample_unit(inliers=15, margin=15, observations=obs_single)
        evaluated = evaluate_auto_confirmation([unit])
        res = evaluated[0]
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("INSUFFICIENT_INDEPENDENT_FRAMES_1", res["unconfirmedReasons"])

    # --------------------------------------------------------------------------
    # 5. Anti-Overcounting: Same image hash across multiple sequences
    # --------------------------------------------------------------------------
    def test_same_image_hash_reindexed_does_not_add_votes(self):
        """Multiple observations with identical source image hash count as ONE frame."""
        identical_hex_hash = "a" * 64
        obs_duplicate_shas = [
            {
                "observationId": "obs-seq0",
                "evidenceId": "ev-0",
                "sequenceIndex": 0,
                "sha256": identical_hex_hash,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
                "inliers": 15,
                "margin": 10,
            },
            {
                "observationId": "obs-seq1",
                "evidenceId": "ev-1",
                "sequenceIndex": 1,  # Different sequence index!
                "sha256": identical_hex_hash,  # Same source image hash!
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
                "inliers": 15,
                "margin": 10,
            },
            {
                "observationId": "obs-seq2",
                "evidenceId": "ev-2",
                "sequenceIndex": 2,  # Another sequence index!
                "sha256": identical_hex_hash,  # Still same image hash!
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
                "inliers": 15,
                "margin": 10,
            },
        ]
        unit = self._sample_unit(inliers=20, margin=10, observations=obs_duplicate_shas)
        evaluated = evaluate_auto_confirmation([unit])
        res = evaluated[0]
        # Must be rejected because effectively only 1 independent frame exists!
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("INSUFFICIENT_INDEPENDENT_FRAMES_1", res["unconfirmedReasons"])

    # --------------------------------------------------------------------------
    # 6. Cross-Frame Identity Conflict
    # --------------------------------------------------------------------------
    def test_cross_frame_identity_conflict_rejected(self):
        """If Frame 1 supports candidate A and Frame 2 supports candidate B, reject confirmation."""
        obs_conflict = [
            {
                "observationId": "obs-seq0",
                "evidenceId": "ev-0",
                "sequenceIndex": 0,
                "sha256": "1" * 64,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
                "inliers": 15,
                "margin": 10,
            },
            {
                "observationId": "obs-seq1",
                "evidenceId": "ev-1",
                "sequenceIndex": 1,
                "sha256": "2" * 64,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image2-1-0",  # Different candidate!
                "inliers": 14,
                "margin": 10,
            },
        ]
        unit = self._sample_unit(inliers=15, margin=10, observations=obs_conflict)
        evaluated = evaluate_auto_confirmation([unit])
        res = evaluated[0]
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("CROSS_FRAME_IDENTITY_CONFLICT", res["unconfirmedReasons"])

    # --------------------------------------------------------------------------
    # 7. Protection of Human Decisions
    # --------------------------------------------------------------------------
    def test_protect_human_decisions_concurrency(self):
        """Human review decision on a unit must never be overwritten by auto-confirmation."""
        match_id = "match_human_protect_001"
        initial_record = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-31T14:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(initial_record, is_finalized=False)

        # Human reviews unit 'unit-world-5-0-2x3' to be 'image12-0-0' (销魂挠挠爪)
        expected_h_name = get_official_name("image12-0-0")
        human_reviewed_units = [
            {
                "reviewUnitId": "unit-world-5-0-2x3",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "image12-0-0",
                "canonicalName": expected_h_name,
                "confirmedByHuman": True,
            }
        ]
        self.store.persist_warehouse_evidence(match_id, review_units=human_reviewed_units)

        # Later, background auto-confirmation runs and proposes 'image1-0-0' (方盒随身听)
        machine_unit = self._sample_unit(uid="unit-world-5-0-2x3", catalog_id="image1-0-0", inliers=30, margin=20)
        
        # Lock-protected persist_warehouse_evidence should protect the human decision
        updated_record = self.store.persist_warehouse_evidence(match_id, review_units=[machine_unit])
        self.assertIsNotNone(updated_record)

        persisted_units = updated_record["settlement"]["reviewUnits"]
        persisted_unit = next(u for u in persisted_units if u["reviewUnitId"] == "unit-world-5-0-2x3")
        
        # Must retain human decision 'image12-0-0' instead of machine 'image1-0-0'!
        self.assertEqual(persisted_unit["selectedCatalogId"], "image12-0-0")
        self.assertEqual(persisted_unit["canonicalName"], expected_h_name)
        self.assertTrue(persisted_unit.get("confirmedByHuman"))

    # --------------------------------------------------------------------------
    # 8. Match ID Isolation & Cross-Match Conflict Rejection
    # --------------------------------------------------------------------------
    def test_match_id_isolation_late_arriving_fails_closed(self):
        """Late-arriving results for a non-existent match fail closed and return None."""
        res = self.store.persist_warehouse_evidence("non_existent_match_999", review_units=[self._sample_unit()])
        self.assertIsNone(res)

    def test_cross_match_id_conflict_rejected(self):
        """persist_warehouse_evidence('audit-A', match_id='audit-B') must strictly fail-closed and return None."""
        rec_a = build_canonical_match_record_v7(match_id="audit-A", played_at="2026-08-31T14:00:00Z", lifecycle_status="DRAFT", source="test")
        rec_b = build_canonical_match_record_v7(match_id="audit-B", played_at="2026-08-31T14:01:00Z", lifecycle_status="DRAFT", source="test")
        self.store.persist_record_transactional(rec_a, is_finalized=False)
        self.store.persist_record_transactional(rec_b, is_finalized=False)

        # Conflicting identifiers pointing to different records must return None!
        res = self.store.persist_warehouse_evidence("audit-A", match_id="audit-B", review_units=[])
        self.assertIsNone(res)

    # --------------------------------------------------------------------------
    # 8b. Production Entrance Negative Tests: Raw Identity, Observations & Margins
    # --------------------------------------------------------------------------
    def test_raw_candidate_name_mismatch_rejected(self):
        """Pairing image1-0-0 with wrong name (e.g. 奇异引火石) must be rejected fail-closed, not auto-corrected."""
        wrong_name = get_official_name("image19-1-1")  # Real catalog name, but for a different item!
        unit = self._sample_unit(catalog_id="image1-0-0", name=wrong_name, inliers=20, margin=10)
        evaluated = evaluate_auto_confirmation([unit])
        res = evaluated[0]
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIsNone(res["selectedCatalogId"])
        self.assertTrue(any("NAME_MISMATCH" in str(r) for r in res["unconfirmedReasons"]))

    def test_missing_matched_candidate_id_does_not_count_as_supporting(self):
        """Observations without explicit matchedCandidateId must NOT inherit unit candidate or vote."""
        obs_no_id = [
            {
                "observationId": "obs-1",
                "evidenceId": "ev-1",
                "sequenceIndex": 0,
                "sha256": "1111" * 16,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": None,  # Missing per-frame candidate ID!
                "inliers": 15,
            },
            {
                "observationId": "obs-2",
                "evidenceId": "ev-2",
                "sequenceIndex": 1,
                "sha256": "2222" * 16,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": None,
                "inliers": 15,
            },
        ]
        unit = self._sample_unit(inliers=15, margin=10, observations=obs_no_id)
        evaluated = evaluate_auto_confirmation([unit])
        res = evaluated[0]
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("INSUFFICIENT_INDEPENDENT_FRAMES_0", res["unconfirmedReasons"])

    def test_missing_or_non_hash_sha256_ignored(self):
        """EvidenceId like 'ev_seg_0' is NOT an image hash; observations without 64-hex sha256 are rejected."""
        obs_fake_sha = [
            {
                "observationId": "obs-1",
                "evidenceId": "sev2_sample_ev_0",
                "sequenceIndex": 0,
                "sha256": "sev2_sample_ev_0",  # Not a 64-character hex hash!
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
                "inliers": 15,
            },
            {
                "observationId": "obs-2",
                "evidenceId": "sev2_sample_ev_1",
                "sequenceIndex": 1,
                "sha256": "",  # Empty hash
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
                "inliers": 15,
            },
        ]
        unit = self._sample_unit(inliers=15, margin=10, observations=obs_fake_sha)
        evaluated = evaluate_auto_confirmation([unit])
        res = evaluated[0]
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("INSUFFICIENT_INDEPENDENT_FRAMES_0", res["unconfirmedReasons"])

    def test_zero_or_missing_margin_rejected(self):
        """Candidate with high inliers but zero competition margin cannot be confirmed and cannot extrapolate margin."""
        unit = self._sample_unit(inliers=15, margin=0)
        evaluated = evaluate_auto_confirmation([unit])
        res = evaluated[0]
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("LOW_COMPETITION_MARGIN_0_MIN_5", res["unconfirmedReasons"])

    def test_zero_or_missing_fg_margin_rejected(self):
        """Candidate with high foreground score (0.99) but zero fgMargin must be rejected."""
        unit = self._sample_unit(inliers=0, margin=0)
        unit["candidates"][0]["inliers"] = 0
        unit["candidates"][0]["margin"] = 0
        unit["candidates"][0]["bestFgScore"] = 0.99
        unit["candidates"][0]["fgMargin"] = 0.0  # Zero margin!
        evaluated = evaluate_auto_confirmation([unit])
        res = evaluated[0]
        self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("LOW_FG_MARGIN_0.0000_MIN_0.0500", res["unconfirmedReasons"])

    def test_partial_update_preserves_unpassed_human_decisions(self):
        """Passing a partial list of reviewUnits must not drop existing units or their prior human decisions."""
        match_id = "match_partial_update_001"
        rec = build_canonical_match_record_v7(match_id=match_id, played_at="2026-08-31T14:00:00Z", lifecycle_status="DRAFT", source="test")
        self.store.persist_record_transactional(rec, is_finalized=False)

        # Seed two human confirmed units
        u1_name = get_official_name("image1-0-0")
        u2_name = get_official_name("image12-0-0")
        seed_units = [
            {"reviewUnitId": "unit-1", "confirmationStatus": "CONFIRMED", "identityStatus": "EXACT_IDENTIFIED", "selectedCatalogId": "image1-0-0", "canonicalName": u1_name, "confirmedByHuman": True},
            {"reviewUnitId": "unit-2", "confirmationStatus": "CONFIRMED", "identityStatus": "EXACT_IDENTIFIED", "selectedCatalogId": "image12-0-0", "canonicalName": u2_name, "confirmedByHuman": True},
        ]
        self.store.persist_warehouse_evidence(match_id, review_units=seed_units)

        # Later, an update arrives that ONLY passes unit-1
        u1_update = self._sample_unit(uid="unit-1", catalog_id="image1-0-0")
        updated = self.store.persist_warehouse_evidence(match_id, review_units=[u1_update])
        self.assertIsNotNone(updated)

        persisted = updated["settlement"]["reviewUnits"]
        self.assertEqual(len(persisted), 2)  # unit-2 must NOT be dropped!
        p2 = next(u for u in persisted if u["reviewUnitId"] == "unit-2")
        self.assertEqual(p2["selectedCatalogId"], "image12-0-0")
        self.assertTrue(p2["confirmedByHuman"])

    def test_synchronize_occupancy_and_identity_review_with_human_decisions(self):
        """Saving warehouse evidence synchronizes warehouseOccupancy and warehouseIdentityReview projections."""
        match_id = "match_proj_sync_001"
        rec = build_canonical_match_record_v7(match_id=match_id, played_at="2026-08-31T14:00:00Z", lifecycle_status="DRAFT", source="test")
        self.store.persist_record_transactional(rec, is_finalized=False)

        u1_name = get_official_name("image1-0-0")
        units = [
            {
                "reviewUnitId": "unit-1",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "image1-0-0",
                "canonicalName": u1_name,
                "worldAnchor": {"row": 0, "col": 0},
                "footprint": {"widthCells": 2, "heightCells": 3},
                "confirmedByHuman": True,
            },
        ]
        updated = self.store.persist_warehouse_evidence(match_id, review_units=units)
        self.assertIsNotNone(updated)

        st = updated["settlement"]
        self.assertIn("reviewUnits", st)
        self.assertEqual(st["reviewUnits"][0]["selectedCatalogId"], "image1-0-0")
        self.assertIn("warehouseOccupancy", st)
        self.assertEqual(st["warehouseOccupancy"].get("schemaVersion"), "settlement-warehouse-occupancy.v1")
        self.assertEqual(len(st["warehouseOccupancy"].get("tracks", [])), 1)

    def test_actual_capture_host_human_decision_protection_and_projection_consistency(self):
        """Actual WarehouseCaptureHost submitting occupancy, identity_review, and review_units
        simultaneously NEVER overwrites prior human confirm/defer decisions, and keeps projections consistent.
        """
        from warehouse_capture_host import WarehouseCaptureHost

        match_id = "match_host_human_protect_001"
        initial_rec = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-31T14:30:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        h_name_1 = get_official_name("image12-0-0")
        initial_rec["settlement"]["reviewUnits"] = [
            {
                "reviewUnitId": "unit-h1",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "image12-0-0",
                "canonicalName": h_name_1,
                "worldAnchor": {"row": 0, "col": 0},
                "footprint": {"widthCells": 2, "heightCells": 3},
                "confirmedByHuman": True,
            },
            {
                "reviewUnitId": "unit-h2",
                "confirmationStatus": "CANDIDATE_ONLY",
                "identityStatus": "REVIEW_REQUIRED",
                "selectedCatalogId": None,
                "canonicalName": None,
                "worldAnchor": {"row": 4, "col": 0},
                "footprint": {"widthCells": 1, "heightCells": 1},
                "confirmedByHuman": True,
            },
        ]
        from warehouse_identity_review import artifact_fingerprint_for

        ir_initial = {
            "schemaVersion": "warehouse-identity-review.v1",
            "recordStableKey": match_id,
            "packetFingerprint": "0" * 64,
            "reviewedAt": "2026-08-31T14:31:00Z",
            "reviewerType": "HUMAN",
            "warehouseCoverageStatus": "COMPLETE",
            "reviewCompletion": "COMPLETE",
            "identityResolution": "RESOLVED",
            "resolvedItems": [
                {
                    "trackId": "unit-h1",
                    "catalogId": "image12-0-0",
                    "name": h_name_1,
                    "confirmedByHuman": True,
                    "reviewerType": "HUMAN",
                    "recordStableKey": match_id,
                    "packetFingerprint": "0" * 64,
                    "evidenceId": "ev-h1",
                    "sha256": "a" * 64,
                    "bbox": [10.0, 10.0, 80.0, 120.0],
                }
            ],
            "unresolvedTracks": [
                {
                    "trackId": "unit-h2",
                    "action": "DEFER",
                    "identityStatus": "UNRESOLVED",
                }
            ],
            "excludedTracks": [],
            "decisions": [
                {
                    "decisionId": "dec-1",
                    "trackId": "unit-h1",
                    "action": "CONFIRM_CANDIDATE",
                    "selectedCatalogId": "image12-0-0",
                    "confirmedByHuman": True,
                },
                {
                    "decisionId": "dec-2",
                    "trackId": "unit-h2",
                    "action": "DEFER",
                    "selectedCatalogId": None,
                    "confirmedByHuman": True,
                },
            ],
            "summary": {
                "trackCount": 2,
                "resolvedItemCount": 1,
                "unresolvedTrackCount": 1,
                "excludedTrackCount": 0,
                "decisionCount": 2,
            },
            "artifactFingerprint": "0" * 64,
        }
        ir_initial["artifactFingerprint"] = artifact_fingerprint_for(ir_initial)
        initial_rec["settlement"]["warehouseIdentityReview"] = ir_initial
        self.store.persist_record_transactional(initial_rec, is_finalized=False)

        # Build production WarehouseCaptureHost pointing to test store
        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)

        # Late-arriving auto-capture packet proposing DIFFERENT identities (machine predicts image1-0-0 and image5-0-0)
        ir_late = {
            "schemaVersion": "warehouse-identity-review.v1",
            "recordStableKey": match_id,
            "packetFingerprint": "0" * 64,
            "reviewedAt": "2026-08-31T14:32:00Z",
            "reviewerType": "AUTO",
            "warehouseCoverageStatus": "COMPLETE",
            "reviewCompletion": "COMPLETE",
            "identityResolution": "RESOLVED",
            "resolvedItems": [
                {
                    "trackId": "unit-h1",
                    "catalogId": "image1-0-0",  # Machine predicts image1-0-0
                    "name": get_official_name("image1-0-0"),
                    "confirmedByHuman": False,
                    "reviewerType": "AUTO",
                    "recordStableKey": match_id,
                    "packetFingerprint": "0" * 64,
                    "evidenceId": "ev-h1",
                    "sha256": "a" * 64,
                    "bbox": [10.0, 10.0, 80.0, 120.0],
                },
                {
                    "trackId": "unit-h2",
                    "catalogId": "image5-0-0",  # Machine predicts image5-0-0
                    "name": get_official_name("image5-0-0"),
                    "confirmedByHuman": False,
                    "reviewerType": "AUTO",
                    "recordStableKey": match_id,
                    "packetFingerprint": "0" * 64,
                    "evidenceId": "ev-h2",
                    "sha256": "b" * 64,
                    "bbox": [10.0, 10.0, 80.0, 120.0],
                },
            ],
            "unresolvedTracks": [],
            "excludedTracks": [],
            "decisions": [
                {
                    "decisionId": "dec-auto-1",
                    "trackId": "unit-h1",
                    "action": "CONFIRM_CANDIDATE",
                    "selectedCatalogId": "image1-0-0",
                    "confirmedByHuman": False,
                },
                {
                    "decisionId": "dec-auto-2",
                    "trackId": "unit-h2",
                    "action": "CONFIRM_CANDIDATE",
                    "selectedCatalogId": "image5-0-0",
                    "confirmedByHuman": False,
                },
            ],
            "summary": {
                "trackCount": 2,
                "resolvedItemCount": 2,
                "unresolvedTrackCount": 0,
                "excludedTrackCount": 0,
                "decisionCount": 2,
            },
            "artifactFingerprint": "0" * 64,
        }
        ir_late["artifactFingerprint"] = artifact_fingerprint_for(ir_late)

        from warehouse_occupancy_adapter import adapt_review_packet_to_warehouse_occupancy

        review_units_late = [
            self._sample_unit("unit-h1", catalog_id="image1-0-0", inliers=20, margin=15),
            self._sample_unit("unit-h2", catalog_id="image5-0-0", inliers=20, margin=15),
        ]
        late_packet = {
            "recordStableKey": match_id,
            "warehouseOccupancy": adapt_review_packet_to_warehouse_occupancy({"reviewUnits": review_units_late}),
            "warehouseIdentityReview": ir_late,
            "reviewUnits": review_units_late,
        }

        persisted = host.persist_warehouse_occupancy_and_review(late_packet)
        self.assertIsNotNone(persisted)

        # Check projections
        st = persisted["settlement"]
        u1 = next(u for u in st["reviewUnits"] if u["reviewUnitId"] == "unit-h1")
        u2 = next(u for u in st["reviewUnits"] if u["reviewUnitId"] == "unit-h2")

        # 1. reviewUnits projection must preserve human decisions
        self.assertEqual(u1["selectedCatalogId"], "image12-0-0")
        self.assertEqual(u1["canonicalName"], h_name_1)
        self.assertTrue(u1["confirmedByHuman"])
        self.assertEqual(u2["confirmationStatus"], "CANDIDATE_ONLY")
        self.assertIsNone(u2["selectedCatalogId"])
        self.assertTrue(u2["confirmedByHuman"])

        # 2. warehouseIdentityReview projection must preserve human decisions
        ir_decisions = {d.get("reviewUnitId") or d.get("trackId"): d for d in st["warehouseIdentityReview"]["decisions"]}
        d1 = ir_decisions["unit-h1"]
        d2 = ir_decisions["unit-h2"]
        self.assertEqual(d1.get("selectedCatalogId") or d1.get("catalogId"), "image12-0-0")
        self.assertEqual(d1["reviewerType"], "HUMAN")
        self.assertEqual(d2["action"], "DEFER")
        self.assertIsNone(d2.get("selectedCatalogId") or d2.get("catalogId"))
        self.assertEqual(d2["reviewerType"], "HUMAN")

        # Check resolvedItems and unresolvedTracks
        res_items = {r.get("trackId") or r.get("reviewUnitId"): r for r in st["warehouseIdentityReview"].get("resolvedItems", [])}
        self.assertIn("unit-h1", res_items)
        self.assertEqual(res_items["unit-h1"]["catalogId"], "image12-0-0")
        unres_items = {u.get("trackId") or u.get("reviewUnitId"): u for u in st["warehouseIdentityReview"].get("unresolvedTracks", [])}
        self.assertIn("unit-h2", unres_items)
        self.assertEqual(unres_items["unit-h2"]["action"], "DEFER")

        # 3. warehouseOccupancy projection must exist and have valid schema
        self.assertEqual(st["warehouseOccupancy"]["schemaVersion"], "settlement-warehouse-occupancy.v1")
        self.assertEqual(len(st["warehouseOccupancy"]["tracks"]), 2)

    def test_actual_capture_host_partial_update_preserves_human_decisions(self):
        """WarehouseCaptureHost partial update does not drop prior human decisions or unpassed units."""
        from warehouse_capture_host import WarehouseCaptureHost

        match_id = "match_host_partial_001"
        rec = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-31T14:40:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        h_name = get_official_name("image12-0-0")
        rec["settlement"]["reviewUnits"] = [
            {"reviewUnitId": "u-stay", "selectedCatalogId": "image12-0-0", "canonicalName": h_name, "confirmedByHuman": True, "confirmationStatus": "CONFIRMED", "identityStatus": "EXACT_IDENTIFIED"},
            {"reviewUnitId": "u-drop-candidate", "selectedCatalogId": "image1-0-0", "canonicalName": get_official_name("image1-0-0"), "confirmedByHuman": False, "confirmationStatus": "CONFIRMED", "identityStatus": "EXACT_IDENTIFIED"},
        ]
        self.store.persist_record_transactional(rec, is_finalized=False)

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        # Pass packet containing only an update for u-drop-candidate, omitting u-stay
        partial_packet = {
            "recordStableKey": match_id,
            "reviewUnits": [self._sample_unit("u-drop-candidate", catalog_id="image1-0-0", inliers=20, margin=15)],
        }
        res = host.persist_warehouse_occupancy_and_review(partial_packet)
        self.assertIsNotNone(res)

        persisted = res["settlement"]["reviewUnits"]
        self.assertEqual(len(persisted), 2)
        u_stay = next(u for u in persisted if u["reviewUnitId"] == "u-stay")
        self.assertEqual(u_stay["selectedCatalogId"], "image12-0-0")
        self.assertTrue(u_stay["confirmedByHuman"])

    def test_actual_capture_host_late_arriving_unknown_match_fails_closed(self):
        """WarehouseCaptureHost fails closed when packet refers to a non-existent match."""
        from warehouse_capture_host import WarehouseCaptureHost

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        res = host.persist_warehouse_occupancy_and_review({
            "recordStableKey": "unknown_match_404",
            "reviewUnits": [self._sample_unit()],
        })
        self.assertIsNone(res)

    # --------------------------------------------------------------------------
    # 9. Persistence Idempotency and Restart Read-Back
    # --------------------------------------------------------------------------
    def test_persistence_idempotency_and_restart(self):
        """Repeated saves are idempotent; reopening store reads back complete data."""
        match_id = "match_idempotent_001"
        draft = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-31T15:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft, is_finalized=False)

        units = [
            self._sample_unit("unit-1", inliers=15, margin=8),
            self._sample_unit("unit-2", inliers=5, margin=2),  # unconfirmed
        ]
        evaluated = evaluate_auto_confirmation(units)

        # 1. First save
        res1 = self.store.persist_warehouse_evidence(match_id, review_units=evaluated)
        self.assertIsNotNone(res1)
        self.assertEqual(len(res1["settlement"]["reviewUnits"]), 2)

        # 2. Second idempotent save
        res2 = self.store.persist_warehouse_evidence(match_id, review_units=evaluated)
        self.assertIsNotNone(res2)
        self.assertEqual(res1, res2)

        # 3. Simulate process restart by creating a brand new store instance pointing to same file
        reopened_store = CanonicalHistoryStore(self.db_path)
        loaded = reopened_store.lookup(match_id)
        self.assertIsNotNone(loaded)
        loaded_units = loaded["settlement"]["reviewUnits"]
        self.assertEqual(len(loaded_units), 2)
        
        u1 = next(u for u in loaded_units if u["reviewUnitId"] == "unit-1")
        self.assertEqual(u1["confirmationStatus"], CONFIRMATION_STATUS_CONFIRMED)
        self.assertEqual(u1["identityStatus"], STATUS_CONFIRMED)
        self.assertEqual(u1["selectedCatalogId"], "image1-0-0")

        u2 = next(u for u in loaded_units if u["reviewUnitId"] == "unit-2")
        self.assertEqual(u2["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertEqual(u2["identityStatus"], STATUS_UNCONFIRMED)

    # --------------------------------------------------------------------------
    # 10. Raw Crops Export and Reviewability
    # --------------------------------------------------------------------------
    def test_raw_crops_export_and_review(self):
        """Export generates PNG files and JSON manifest for all review units."""
        match_id = "match_export_001"
        out_dir = self.test_dir / "crop_export"
        
        dummy_frame = _make_dummy_image(color=(50, 100, 150), size=(640, 480))
        frames = [dummy_frame, dummy_frame]

        unit = self._sample_unit("unit-exp-1", inliers=15, margin=8)
        evaluated = evaluate_auto_confirmation([unit])

        manifest = export_warehouse_evidence_crops(
            record_id=match_id,
            review_units=evaluated,
            store=None,
            output_dir=out_dir,
            frames=frames,
        )

        self.assertEqual(manifest["sampleCount"], 1)
        sample = manifest["samples"][0]
        self.assertIsNotNone(sample["cropPath"])
        self.assertTrue((out_dir / sample["cropPath"]).is_file())
        self.assertIsNotNone(sample["cropSha256"])

    # --------------------------------------------------------------------------
    # 11. Main Window Bridge Restart, History Review, and Export Verification
    # --------------------------------------------------------------------------
    def test_main_window_bridge_restart_history_review_and_bundle_export(self):
        """Simulated window restart, history read-back of review units, and bridge export execution.
        Explicitly asserts headless automated contract; interactive physical display is marked NOT_EXECUTED.
        """
        from main_window import MainWindowBridge

        match_id = "match_bridge_restart_001"
        draft = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-31T15:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft, is_finalized=False)

        units = [
            self._sample_unit("unit-b1", catalog_id="image1-0-0", inliers=15, margin=8),
            self._sample_unit("unit-b2", catalog_id="image2-1-0", inliers=6, margin=1),  # unconfirmed
        ]
        evaluated = evaluate_auto_confirmation(units)
        self.store.persist_warehouse_evidence(match_id, review_units=evaluated)

        # 1. Simulate process restart: drop store reference and create fresh bridge & store
        fresh_store = CanonicalHistoryStore(self.db_path)
        class _DummyOverlayController:
            visible = True

        bridge = MainWindowBridge(
            overlay_controller=_DummyOverlayController(),
            history_path_provider=lambda: self.db_path,
        )

        # 2. History read-back of all review units
        rec = fresh_store.lookup(match_id)
        self.assertIsNotNone(rec)
        persisted_units = rec["settlement"]["reviewUnits"]
        self.assertEqual(len(persisted_units), 2)
        u1 = next(u for u in persisted_units if u["reviewUnitId"] == "unit-b1")
        self.assertEqual(u1["confirmationStatus"], CONFIRMATION_STATUS_CONFIRMED)
        self.assertEqual(u1["selectedCatalogId"], "image1-0-0")
        u2 = next(u for u in persisted_units if u["reviewUnitId"] == "unit-b2")
        self.assertEqual(u2["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)

        # 3. MainWindowBridge JSON export dispatch
        export_json_path = self.test_dir / "exported_history.json"
        resp = bridge.dispatch({
            "action": "export_history_records",
            "outputPath": str(export_json_path),
            "recordIds": [match_id],
        })
        self.assertTrue(resp.get("exportResult", {}).get("ok"))
        self.assertTrue(export_json_path.is_file())
        exported_data = json.loads(export_json_path.read_text(encoding="utf-8"))
        self.assertEqual(exported_data.get("recordCount"), 1)
        self.assertEqual(exported_data["records"][0]["id"], match_id)
        self.assertEqual(len(exported_data["records"][0]["settlement"]["reviewUnits"]), 2)

        # 4. Explicit verification contract marker
        execution_audit = {
            "HEADLESS_BRIDGE_DISPATCH_AND_RESTART": "EXECUTED",
            "PER_ITEM_HISTORY_RECONSTRUCTION": "EXECUTED",
            "HISTORY_EXPORT_DISPATCH": "EXECUTED",
            "REAL_GUI_INTERACTIVE_WINDOW_DISPLAY": "NOT_EXECUTED",
        }
        self.assertEqual(execution_audit["REAL_GUI_INTERACTIVE_WINDOW_DISPLAY"], "NOT_EXECUTED")

    # --------------------------------------------------------------------------
    # 12. Strict Per-Frame Gate & Order-Independent Conflict Check
    # --------------------------------------------------------------------------
    def test_per_frame_thresholds_missing_score_or_weak_second_frame_rejected(self):
        """Every supporting frame must independently satisfy FULL status, identity, and feature thresholds.
        Whole-unit candidate score CANNOT substitute for weak or missing per-frame scores.
        """
        # Case A: Strong frame 1 (inliers=15, margin=10) + Weak frame 2 (inliers=5, margin=2)
        obs_weak_f2 = [
            {
                "observationId": "obs-1",
                "evidenceId": "ev-1",
                "sequenceIndex": 0,
                "sha256": "1" * 64,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
                "inliers": 15,
                "margin": 10,
            },
            {
                "observationId": "obs-2",
                "evidenceId": "ev-2",
                "sequenceIndex": 1,
                "sha256": "2" * 64,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
                "inliers": 5,  # WEAK inliers (< 7)!
                "margin": 2,  # WEAK margin (< 5)!
            },
        ]
        unit = self._sample_unit(inliers=15, margin=10, observations=obs_weak_f2)
        evaluated = evaluate_auto_confirmation([unit])
        self.assertEqual(evaluated[0]["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("INSUFFICIENT_INDEPENDENT_FRAMES_1", evaluated[0]["unconfirmedReasons"])

        # Case B: Frame 2 is CLIPPED (even with matched identity and numbers)
        obs_clipped_f2 = [
            copy.deepcopy(obs_weak_f2[0]),
            {
                "observationId": "obs-2",
                "evidenceId": "ev-2",
                "sequenceIndex": 1,
                "sha256": "2" * 64,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "CLIPPED",  # Not FULL!
                "matchedCandidateId": "image1-0-0",
                "inliers": 15,
                "margin": 10,
            },
        ]
        unit = self._sample_unit(inliers=15, margin=10, observations=obs_clipped_f2)
        evaluated = evaluate_auto_confirmation([unit])
        self.assertEqual(evaluated[0]["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("INSUFFICIENT_INDEPENDENT_FRAMES_1", evaluated[0]["unconfirmedReasons"])

        # Case C: Frame 2 missing margin (margin=None)
        obs_no_margin_f2 = [
            copy.deepcopy(obs_weak_f2[0]),
            {
                "observationId": "obs-2",
                "evidenceId": "ev-2",
                "sequenceIndex": 1,
                "sha256": "2" * 64,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
                "inliers": 15,
                "margin": None,  # Missing margin!
            },
        ]
        unit = self._sample_unit(inliers=15, margin=10, observations=obs_no_margin_f2)
        evaluated = evaluate_auto_confirmation([unit])
        self.assertEqual(evaluated[0]["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("INSUFFICIENT_INDEPENDENT_FRAMES_1", evaluated[0]["unconfirmedReasons"])

        # Case D: All observation feature metrics deleted
        obs_stripped = [
            {
                "observationId": "obs-1",
                "evidenceId": "ev-1",
                "sequenceIndex": 0,
                "sha256": "1" * 64,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
            },
            {
                "observationId": "obs-2",
                "evidenceId": "ev-2",
                "sequenceIndex": 1,
                "sha256": "2" * 64,
                "bbox": [10.0, 10.0, 80.0, 120.0],
                "status": "FULL",
                "matchedCandidateId": "image1-0-0",
            },
        ]
        unit = self._sample_unit(inliers=15, margin=10, observations=obs_stripped)
        evaluated = evaluate_auto_confirmation([unit])
        self.assertEqual(evaluated[0]["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE)
        self.assertIn("INSUFFICIENT_INDEPENDENT_FRAMES_0", evaluated[0]["unconfirmedReasons"])

    def test_same_hash_identity_conflict_order_independence(self):
        """Identity conflict must be detected across all observations before deduplication;
        result must be strictly invariant under different observation permutations.
        """
        import itertools

        obs_sha1_good = {
            "observationId": "obs-1",
            "evidenceId": "ev-1",
            "sequenceIndex": 0,
            "sha256": "1" * 64,
            "bbox": [10.0, 10.0, 80.0, 120.0],
            "status": "FULL",
            "matchedCandidateId": "image1-0-0",
            "inliers": 15,
            "margin": 10,
        }
        obs_sha1_conflict = {
            "observationId": "obs-1-dup",
            "evidenceId": "ev-1-dup",
            "sequenceIndex": 1,
            "sha256": "1" * 64,  # SAME SHA-256!
            "bbox": [10.0, 10.0, 80.0, 120.0],
            "status": "FULL",
            "matchedCandidateId": "image2-1-0",  # CONFLICTING identity!
            "inliers": 14,
            "margin": 10,
        }
        obs_sha2_good = {
            "observationId": "obs-2",
            "evidenceId": "ev-2",
            "sequenceIndex": 2,
            "sha256": "2" * 64,
            "bbox": [10.0, 10.0, 80.0, 120.0],
            "status": "FULL",
            "matchedCandidateId": "image1-0-0",
            "inliers": 15,
            "margin": 10,
        }

        base_list = [obs_sha1_good, obs_sha1_conflict, obs_sha2_good]
        permutations = list(itertools.permutations(base_list))
        self.assertEqual(len(permutations), 6)

        reference_reasons = None
        for p_idx, perm in enumerate(permutations):
            unit = self._sample_unit(inliers=15, margin=10, observations=list(perm))
            evaluated = evaluate_auto_confirmation([unit])
            res = evaluated[0]
            self.assertEqual(res["confirmationStatus"], CONFIRMATION_STATUS_CANDIDATE, f"Failed on permutation {p_idx}")
            self.assertIsNone(res["selectedCatalogId"], f"Failed on permutation {p_idx}")
            self.assertIn("CROSS_FRAME_IDENTITY_CONFLICT", res["unconfirmedReasons"], f"Failed on permutation {p_idx}")
            reasons_sorted = sorted(res["unconfirmedReasons"])
            if reference_reasons is None:
                reference_reasons = reasons_sorted
            else:
                self.assertEqual(reasons_sorted, reference_reasons, f"Permutation {p_idx} gave different reasons!")

    # --------------------------------------------------------------------------
    # 13. Strict Read/Write Parity on Warehouse Identity Review Persistence
    # --------------------------------------------------------------------------
    def test_invalid_identity_review_persistence_rejected_fail_closed(self):
        """persist_warehouse_evidence must strictly reject invalid identity_review artifacts fail-closed."""
        match_id = "match_invalid_ir_fail_closed_001"
        draft = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-31T15:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft, is_finalized=False)

        base_valid_ir = {
            "schemaVersion": "warehouse-identity-review.v1",
            "recordStableKey": match_id,
            "packetFingerprint": "a" * 64,
            "reviewedAt": "2026-08-31T14:32:00Z",
            "reviewerType": "AUTO",
            "warehouseCoverageStatus": "COMPLETE",
            "reviewCompletion": "COMPLETE",
            "identityResolution": "RESOLVED",
            "resolvedItems": [
                {
                    "trackId": "unit-1",
                    "catalogId": "image1-0-0",
                    "name": get_official_name("image1-0-0"),
                    "confirmedByHuman": False,
                    "reviewerType": "AUTO",
                    "recordStableKey": match_id,
                    "packetFingerprint": "a" * 64,
                    "evidenceId": "ev-1",
                    "sha256": "1" * 64,
                    "bbox": [10.0, 10.0, 80.0, 120.0],
                }
            ],
            "unresolvedTracks": [],
            "excludedTracks": [],
            "decisions": [
                {
                    "decisionId": "dec-1",
                    "trackId": "unit-1",
                    "action": "CONFIRM_CANDIDATE",
                    "selectedCatalogId": "image1-0-0",
                    "confirmedByHuman": False,
                }
            ],
            "summary": {
                "trackCount": 1,
                "resolvedItemCount": 1,
                "unresolvedTrackCount": 0,
                "excludedTrackCount": 0,
                "decisionCount": 1,
            },
            "artifactFingerprint": "0" * 64,
        }
        base_valid_ir["artifactFingerprint"] = artifact_fingerprint_for(base_valid_ir)

        # 1. Non-mapping object
        with self.assertRaises(HistoryStoreError):
            self.store.persist_warehouse_evidence(match_id, identity_review="not_a_mapping")

        # 2. Missing recordStableKey
        bad_ir = copy.deepcopy(base_valid_ir)
        bad_ir.pop("recordStableKey")
        with self.assertRaises(HistoryStoreError):
            self.store.persist_warehouse_evidence(match_id, identity_review=bad_ir)

        # 3. Mismatched recordStableKey
        bad_ir = copy.deepcopy(base_valid_ir)
        bad_ir["recordStableKey"] = "other_match_999"
        bad_ir["artifactFingerprint"] = artifact_fingerprint_for(bad_ir)
        with self.assertRaises(HistoryStoreError):
            self.store.persist_warehouse_evidence(match_id, identity_review=bad_ir)

        # 4. Missing packetFingerprint
        bad_ir = copy.deepcopy(base_valid_ir)
        bad_ir.pop("packetFingerprint")
        with self.assertRaises(HistoryStoreError):
            self.store.persist_warehouse_evidence(match_id, identity_review=bad_ir)

        # 5. Invalid sha256 in resolvedItem
        bad_ir = copy.deepcopy(base_valid_ir)
        bad_ir["resolvedItems"][0]["sha256"] = "not_a_valid_sha256"
        bad_ir["artifactFingerprint"] = artifact_fingerprint_for(bad_ir)
        with self.assertRaises(HistoryStoreError):
            self.store.persist_warehouse_evidence(match_id, identity_review=bad_ir)

        # 6. Missing evidenceId in resolvedItem
        bad_ir = copy.deepcopy(base_valid_ir)
        bad_ir["resolvedItems"][0].pop("evidenceId")
        bad_ir["artifactFingerprint"] = artifact_fingerprint_for(bad_ir)
        with self.assertRaises(HistoryStoreError):
            self.store.persist_warehouse_evidence(match_id, identity_review=bad_ir)

        # 7. Invalid bbox (not 4 elements)
        bad_ir = copy.deepcopy(base_valid_ir)
        bad_ir["resolvedItems"][0]["bbox"] = [1.0, 2.0, 3.0]
        bad_ir["artifactFingerprint"] = artifact_fingerprint_for(bad_ir)
        with self.assertRaises(HistoryStoreError):
            self.store.persist_warehouse_evidence(match_id, identity_review=bad_ir)

        # 8. Mismatched evidence recordStableKey
        bad_ir = copy.deepcopy(base_valid_ir)
        bad_ir["resolvedItems"][0]["recordStableKey"] = "mismatched_key"
        bad_ir["artifactFingerprint"] = artifact_fingerprint_for(bad_ir)
        with self.assertRaises(HistoryStoreError):
            self.store.persist_warehouse_evidence(match_id, identity_review=bad_ir)

        # 9. Forbidden client field
        bad_ir = copy.deepcopy(base_valid_ir)
        bad_ir["relativePath"] = "crops/forbidden.png"
        bad_ir["artifactFingerprint"] = artifact_fingerprint_for(bad_ir)
        with self.assertRaises(HistoryStoreError):
            self.store.persist_warehouse_evidence(match_id, identity_review=bad_ir)

        # 10. Artifact fingerprint mismatch
        bad_ir = copy.deepcopy(base_valid_ir)
        bad_ir["artifactFingerprint"] = "0" * 64
        with self.assertRaises(HistoryStoreError):
            self.store.persist_warehouse_evidence(match_id, identity_review=bad_ir)

        # Confirm store record was NOT corrupted
        rec = self.store.lookup(match_id)
        self.assertIsNotNone(rec)
        self.assertNotIn("warehouseIdentityReview", rec.get("settlement", {}))

    def test_valid_identity_review_persisted_immediately_yields_saved_and_readable(self):
        """Persisting a compliant v1 or v2 review artifact immediately yields saved=True, readable=True."""
        # --- Test v1 artifact ---
        match_id_v1 = "match_valid_ir_v1_001"
        draft_v1 = build_canonical_match_record_v7(
            match_id=match_id_v1,
            played_at="2026-08-31T15:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft_v1, is_finalized=False)

        valid_v1_ir = {
            "schemaVersion": "warehouse-identity-review.v1",
            "recordStableKey": match_id_v1,
            "packetFingerprint": "b" * 64,
            "reviewedAt": "2026-08-31T14:32:00Z",
            "reviewerType": "AUTO",
            "warehouseCoverageStatus": "COMPLETE",
            "reviewCompletion": "PARTIAL",
            "identityResolution": "PARTIAL",
            "resolvedItems": [
                {
                    "trackId": "unit-v1-1",
                    "catalogId": "image1-0-0",
                    "name": get_official_name("image1-0-0"),
                    "confirmedByHuman": False,
                    "reviewerType": "AUTO",
                    "recordStableKey": match_id_v1,
                    "packetFingerprint": "b" * 64,
                    "evidenceId": "ev-v1-1",
                    "sha256": "1" * 64,
                    "bbox": [10.0, 10.0, 80.0, 120.0],
                }
            ],
            "unresolvedTracks": [
                {
                    "trackId": "unit-v1-2",
                    "action": "DEFER",
                    "identityStatus": "UNRESOLVED",
                }
            ],
            "excludedTracks": [],
            "decisions": [
                {
                    "decisionId": "dec-v1-1",
                    "trackId": "unit-v1-1",
                    "action": "CONFIRM_CANDIDATE",
                    "selectedCatalogId": "image1-0-0",
                    "confirmedByHuman": False,
                },
                {
                    "decisionId": "dec-v1-2",
                    "trackId": "unit-v1-2",
                    "action": "DEFER",
                    "selectedCatalogId": None,
                    "confirmedByHuman": False,
                },
            ],
            "summary": {
                "trackCount": 2,
                "resolvedItemCount": 1,
                "unresolvedTrackCount": 1,
                "excludedTrackCount": 0,
                "decisionCount": 2,
            },
            "artifactFingerprint": "0" * 64,
        }
        valid_v1_ir["artifactFingerprint"] = artifact_fingerprint_for(valid_v1_ir)

        updated_v1 = self.store.persist_warehouse_evidence(match_id_v1, identity_review=valid_v1_ir)
        self.assertIsNotNone(updated_v1)
        summary_v1 = summarize_persisted_identity_review(updated_v1)
        self.assertTrue(summary_v1["saved"])
        self.assertTrue(summary_v1["readable"])
        self.assertEqual(summary_v1["caption"], "已写入本局记录")
        self.assertEqual(summary_v1["resolvedCount"], 1)
        self.assertEqual(summary_v1["unresolvedCount"], 1)
        self.assertEqual(summary_v1["excludedCount"], 0)

        # --- Test v2 artifact ---
        match_id_v2 = "match_valid_ir_v2_002"
        draft_v2 = build_canonical_match_record_v7(
            match_id=match_id_v2,
            played_at="2026-08-31T15:05:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft_v2, is_finalized=False)

        valid_v2_ir = {
            "schemaVersion": "warehouse-identity-review.v2",
            "recordStableKey": match_id_v2,
            "packetFingerprint": "c" * 64,
            "reviewedAt": "2026-08-31T14:35:00Z",
            "reviewerType": "HUMAN",
            "warehouseCoverageStatus": "COMPLETE",
            "reviewCompletion": "COMPLETE",
            "identityResolution": "FULLY_RESOLVED",
            "resolvedItems": [
                {
                    "reviewUnitId": "unit-v2-1",
                    "catalogId": "image1-0-0",
                    "name": get_official_name("image1-0-0"),
                    "confirmedByHuman": True,
                    "action": "CONFIRM_CANDIDATE",
                    "recordStableKey": match_id_v2,
                    "packetFingerprint": "c" * 64,
                    "evidenceId": "ev-v2-1",
                    "sha256": "2" * 64,
                    "bbox": [15.0, 15.0, 85.0, 125.0],
                }
            ],
            "unresolvedUnits": [],
            "excludedUnits": [],
            "decisions": [
                {
                    "decisionId": "dec-v2-1",
                    "reviewUnitId": "unit-v2-1",
                    "action": "CONFIRM_CANDIDATE",
                    "selectedCatalogId": "image1-0-0",
                    "confirmedByHuman": True,
                }
            ],
            "summary": {
                "reviewUnitCount": 1,
                "resolvedItemCount": 1,
                "unresolvedUnitCount": 0,
                "excludedUnitCount": 0,
                "decisionCount": 1,
            },
            "artifactFingerprint": "0" * 64,
        }
        valid_v2_ir["artifactFingerprint"] = artifact_fingerprint_for(valid_v2_ir)

        updated_v2 = self.store.persist_warehouse_evidence(match_id_v2, identity_review=valid_v2_ir)
        self.assertIsNotNone(updated_v2)
        summary_v2 = summarize_persisted_identity_review(updated_v2)
        self.assertTrue(summary_v2["saved"])
        self.assertTrue(summary_v2["readable"])
        self.assertEqual(summary_v2["caption"], "已写入本局记录")
        self.assertEqual(summary_v2["resolvedCount"], 1)
        self.assertEqual(summary_v2["unresolvedCount"], 0)

    def test_persist_warehouse_evidence_preserves_human_decisions_and_maintains_readable_summary(self):
        """Late-arriving evidence persistence preserves human decisions and keeps summary readable."""
        match_id = "match_human_dec_parity_001"
        draft = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-31T15:10:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft, is_finalized=False)

        # Seed record with human confirmed unit-1 and human deferred unit-2
        human_units = [
            {
                "reviewUnitId": "unit-1",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "image1-0-0",
                "canonicalName": get_official_name("image1-0-0"),
                "confirmedByHuman": True,
                "observations": [
                    {
                        "evidenceId": "ev-1",
                        "sha256": "1" * 64,
                        "bbox": [10.0, 10.0, 80.0, 120.0],
                    }
                ],
            },
            {
                "reviewUnitId": "unit-2",
                "confirmationStatus": "CANDIDATE_ONLY",
                "identityStatus": "REVIEW_REQUIRED",
                "selectedCatalogId": None,
                "confirmedByHuman": True,
                "observations": [
                    {
                        "evidenceId": "ev-2",
                        "sha256": "2" * 64,
                        "bbox": [20.0, 20.0, 90.0, 130.0],
                    }
                ],
            },
        ]
        self.store.persist_warehouse_evidence(match_id, review_units=human_units)

        # Late-arriving auto-confirmation proposing machine predictions
        machine_units = [
            {
                "reviewUnitId": "unit-1",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "image12-0-0",  # Different from human image1-0-0
                "canonicalName": get_official_name("image12-0-0"),
                "confirmedByHuman": False,
                "observations": [
                    {
                        "evidenceId": "ev-1",
                        "sha256": "1" * 64,
                        "bbox": [10.0, 10.0, 80.0, 120.0],
                    }
                ],
            },
            {
                "reviewUnitId": "unit-2",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "image2-1-0",  # Different from human deferred
                "canonicalName": get_official_name("image2-1-0"),
                "confirmedByHuman": False,
                "observations": [
                    {
                        "evidenceId": "ev-2",
                        "sha256": "2" * 64,
                        "bbox": [20.0, 20.0, 90.0, 130.0],
                    }
                ],
            },
        ]
        ir_auto = {
            "schemaVersion": "warehouse-identity-review.v1",
            "recordStableKey": match_id,
            "packetFingerprint": "d" * 64,
            "reviewedAt": "2026-08-31T15:15:00Z",
            "reviewerType": "AUTO",
            "warehouseCoverageStatus": "COMPLETE",
            "reviewCompletion": "COMPLETE",
            "identityResolution": "RESOLVED",
            "resolvedItems": [
                {
                    "trackId": "unit-1",
                    "catalogId": "image12-0-0",
                    "name": get_official_name("image12-0-0"),
                    "confirmedByHuman": False,
                    "reviewerType": "AUTO",
                    "recordStableKey": match_id,
                    "packetFingerprint": "d" * 64,
                    "evidenceId": "ev-1",
                    "sha256": "1" * 64,
                    "bbox": [10.0, 10.0, 80.0, 120.0],
                },
                {
                    "trackId": "unit-2",
                    "catalogId": "image2-1-0",
                    "name": get_official_name("image2-1-0"),
                    "confirmedByHuman": False,
                    "reviewerType": "AUTO",
                    "recordStableKey": match_id,
                    "packetFingerprint": "d" * 64,
                    "evidenceId": "ev-2",
                    "sha256": "2" * 64,
                    "bbox": [20.0, 20.0, 90.0, 130.0],
                },
            ],
            "unresolvedTracks": [],
            "excludedTracks": [],
            "decisions": [
                {
                    "decisionId": "dec-auto-1",
                    "trackId": "unit-1",
                    "action": "CONFIRM_CANDIDATE",
                    "selectedCatalogId": "image12-0-0",
                    "confirmedByHuman": False,
                },
                {
                    "decisionId": "dec-auto-2",
                    "trackId": "unit-2",
                    "action": "CONFIRM_CANDIDATE",
                    "selectedCatalogId": "image2-1-0",
                    "confirmedByHuman": False,
                },
            ],
            "summary": {
                "trackCount": 2,
                "resolvedItemCount": 2,
                "unresolvedTrackCount": 0,
                "excludedTrackCount": 0,
                "decisionCount": 2,
            },
            "artifactFingerprint": "0" * 64,
        }
        ir_auto["artifactFingerprint"] = artifact_fingerprint_for(ir_auto)

        updated = self.store.persist_warehouse_evidence(
            match_id,
            review_units=machine_units,
            identity_review=ir_auto,
        )
        self.assertIsNotNone(updated)

        # Human decision protection checks
        st = updated["settlement"]
        u1 = next(u for u in st["reviewUnits"] if u["reviewUnitId"] == "unit-1")
        u2 = next(u for u in st["reviewUnits"] if u["reviewUnitId"] == "unit-2")
        self.assertEqual(u1["selectedCatalogId"], "image1-0-0")
        self.assertTrue(u1["confirmedByHuman"])
        self.assertEqual(u2["confirmationStatus"], "CANDIDATE_ONLY")
        self.assertIsNone(u2["selectedCatalogId"])
        self.assertTrue(u2["confirmedByHuman"])

        # warehouseIdentityReview must remain readable and reflect human decisions
        summary = summarize_persisted_identity_review(updated)
        self.assertTrue(summary["saved"])
        self.assertTrue(summary["readable"])
        self.assertEqual(summary["caption"], "已写入本局记录")
        self.assertEqual(summary["resolvedCount"], 1)
        self.assertEqual(summary["unresolvedCount"], 1)

        ir = st["warehouseIdentityReview"]
        res_map = {r["trackId"]: r for r in ir["resolvedItems"]}
        self.assertIn("unit-1", res_map)
        self.assertEqual(res_map["unit-1"]["catalogId"], "image1-0-0")
        self.assertTrue(res_map["unit-1"]["confirmedByHuman"])

        unres_map = {u["trackId"]: u for u in ir["unresolvedTracks"]}
        self.assertIn("unit-2", unres_map)
        self.assertEqual(unres_map["unit-2"]["action"], "DEFER")

    def test_capture_host_fail_closed_when_identity_review_invalid_leaves_record_unchanged(self):
        """WarehouseCaptureHost._persist_draft_occupancy must fail closed and leave disk record untouched
        when packet contains an invalid warehouseIdentityReview."""
        from warehouse_capture_host import WarehouseCaptureHost

        match_id = "match_host_fail_closed_ir_001"
        draft = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-31T15:20:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft, is_finalized=False)
        rec_before = copy.deepcopy(self.store.lookup(match_id))

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)

        # Invalid identity review: bad sha256 hash
        invalid_ir = {
            "schemaVersion": "warehouse-identity-review.v2",
            "recordStableKey": match_id,
            "packetFingerprint": "f" * 64,
            "reviewedAt": "2026-08-31T15:20:00Z",
            "reviewerType": "AUTO",
            "resolvedItems": [
                {
                    "reviewUnitId": "u-bad",
                    "catalogId": "image1-0-0",
                    "name": get_official_name("image1-0-0"),
                    "sha256": "invalid_hash",
                    "bbox": [10.0, 10.0, 80.0, 120.0],
                }
            ],
            "unresolvedUnits": [],
            "excludedUnits": [],
            "decisions": [],
            "summary": {},
            "artifactFingerprint": "0" * 64,
        }

        packet = {
            "recordStableKey": match_id,
            "warehouseOccupancy": {"tracks": [{"trackId": "trk-1"}]},
            "warehouseIdentityReview": invalid_ir,
        }

        result = host.persist_warehouse_occupancy_and_review(packet)
        self.assertIsNone(result, "Host must return None on invalid identity review")

        # Record on disk must be completely unchanged
        rec_after = self.store.lookup(match_id)
        self.assertEqual(rec_after, rec_before)
        self.assertNotIn("warehouseOccupancy", rec_after.get("settlement", {}))
        self.assertNotIn("warehouseIdentityReview", rec_after.get("settlement", {}))

    def test_human_decision_catalog_name_validation_three_negative_modes(self):
        """Human decision item name validation must strictly reject:
        1. Missing canonicalName
        2. Mismatched canonicalName (e.g. wrong candidate name)
        3. Unknown catalogId
        and must never allow canonicalName to equal catalogId.
        """
        # Negative Mode 1: Missing canonicalName (or empty)
        match_id_1 = "match_human_name_neg_001"
        draft_1 = build_canonical_match_record_v7(
            match_id=match_id_1,
            played_at="2026-08-31T15:30:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft_1, is_finalized=False)
        units_missing_name = [
            {
                "reviewUnitId": "u-human-1",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "image1-0-0",
                "canonicalName": None,
                "confirmedByHuman": True,
            }
        ]
        self.store.persist_warehouse_evidence(match_id_1, review_units=units_missing_name)
        with self.assertRaises(HistoryStoreError) as cm1:
            self.store.persist_warehouse_evidence(
                match_id_1,
                review_units=[self._sample_unit("u-human-1", inliers=15, margin=8)],
            )
        self.assertIn("lacks canonicalName", str(cm1.exception))

        # Negative Mode 2: Mismatched canonicalName (wrong name)
        match_id_2 = "match_human_name_neg_002"
        draft_2 = build_canonical_match_record_v7(
            match_id=match_id_2,
            played_at="2026-08-31T15:30:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft_2, is_finalized=False)
        units_wrong_name = [
            {
                "reviewUnitId": "u-human-2",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "image1-0-0",
                "canonicalName": "假藏品名称",
                "confirmedByHuman": True,
            }
        ]
        self.store.persist_warehouse_evidence(match_id_2, review_units=units_wrong_name)
        with self.assertRaises(HistoryStoreError) as cm2:
            self.store.persist_warehouse_evidence(
                match_id_2,
                review_units=[self._sample_unit("u-human-2", inliers=15, margin=8)],
            )
        self.assertIn("candidate name mismatch", str(cm2.exception))

        # Negative Mode 3: Unknown catalogId
        match_id_3 = "match_human_name_neg_003"
        draft_3 = build_canonical_match_record_v7(
            match_id=match_id_3,
            played_at="2026-08-31T15:30:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft_3, is_finalized=False)
        units_unknown_cat = [
            {
                "reviewUnitId": "u-human-3",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "unknown-cat-999",
                "canonicalName": "未知藏品",
                "confirmedByHuman": True,
            }
        ]
        self.store.persist_warehouse_evidence(match_id_3, review_units=units_unknown_cat)
        with self.assertRaises(HistoryStoreError) as cm3:
            self.store.persist_warehouse_evidence(
                match_id_3,
                review_units=[self._sample_unit("u-human-3", inliers=15, margin=8)],
            )
        self.assertIn("unknown catalogId", str(cm3.exception))

        # Negative Mode 4: canonicalName equals catalogId
        match_id_4 = "match_human_name_neg_004"
        draft_4 = build_canonical_match_record_v7(
            match_id=match_id_4,
            played_at="2026-08-31T15:30:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft_4, is_finalized=False)
        units_id_as_name = [
            {
                "reviewUnitId": "u-human-4",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "image1-0-0",
                "canonicalName": "image1-0-0",
                "confirmedByHuman": True,
            }
        ]
        self.store.persist_warehouse_evidence(match_id_4, review_units=units_id_as_name)
        with self.assertRaises(HistoryStoreError) as cm4:
            self.store.persist_warehouse_evidence(
                match_id_4,
                review_units=[self._sample_unit("u-human-4", inliers=15, margin=8)],
            )
        self.assertIn("canonicalName cannot be catalogId", str(cm4.exception))

    def test_production_host_auto_transaction_without_prefabricated_review(self):
        """When a packet lacks warehouseIdentityReview, WarehouseCaptureHost must automatically
        run evaluate_auto_confirmation -> build_auto_identity_review_artifact -> persist_warehouse_evidence
        as a single atomic transaction with dynamic timestamp and authoritative catalog."""
        from warehouse_capture_host import WarehouseCaptureHost
        from warehouse_occupancy_adapter import adapt_review_packet_to_warehouse_occupancy

        match_id = "match_host_auto_prod_001"
        draft = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-09-01T08:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft, is_finalized=False)

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)

        unit = self._sample_unit(
            uid="unit-auto-host-1",
            catalog_id="image1-0-0",
            inliers=15,
            margin=8,
        )
        packet = {
            "recordStableKey": match_id,
            "capturedAt": "2026-09-01T08:05:00Z",
            "sourceFingerprint": "a" * 64,
            "warehouseOccupancy": adapt_review_packet_to_warehouse_occupancy({"reviewUnits": [unit]}),
            "reviewUnits": [unit],
        }

        result = host.persist_warehouse_occupancy_and_review(packet)
        self.assertIsNotNone(result, "Host should successfully persist auto review")

        rec = self.store.lookup(match_id)
        settlement = rec.get("settlement", {})
        self.assertIn("warehouseOccupancy", settlement)
        self.assertIn("warehouseIdentityReview", settlement)

        ir = settlement["warehouseIdentityReview"]
        self.assertEqual(ir["reviewerType"], "AUTO")
        self.assertEqual(ir["reviewedAt"], "2026-09-01T08:05:00Z")
        self.assertNotEqual(ir["reviewedAt"], "2026-09-11T12:00:00Z")
        self.assertEqual(len(ir.get("resolvedItems", [])), 1)
        self.assertEqual(ir["resolvedItems"][0]["catalogId"], "image1-0-0")
        self.assertEqual(ir["resolvedItems"][0]["name"], get_official_name("image1-0-0"))

    def test_forged_auto_artifact_name_rejected_fail_closed_disk_unchanged(self):
        """Even if an AUTO identity review artifact has a validly recomputed artifactFingerprint,
        CanonicalHistoryStore.persist_warehouse_evidence must strictly reject any forged item name
        and leave the on-disk record byte-for-byte unchanged."""
        match_id = "match_forged_auto_001"
        draft = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-09-01T09:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft, is_finalized=False)
        rec_before = copy.deepcopy(self.store.lookup(match_id))

        unit = self._sample_unit(
            uid="unit-forged-auto-1",
            catalog_id="image1-0-0",
            inliers=15,
            margin=8,
        )
        packet = {
            "recordStableKey": match_id,
            "capturedAt": "2026-09-01T09:01:00Z",
            "sourceFingerprint": "b" * 64,
            "reviewUnits": [unit],
        }
        eval_units = evaluate_auto_confirmation([unit])
        cat = CatalogAuthority()
        artifact = build_auto_identity_review_artifact(
            packet,
            eval_units,
            catalog=cat,
            reviewed_at="2026-09-01T09:02:00Z",
        )
        self.assertEqual(len(artifact.get("resolvedItems", [])), 1)

        # Forged item name
        artifact["resolvedItems"][0]["name"] = "黑客伪造藏品"
        # Recompute artifactFingerprint to pass low-level artifact check
        artifact["artifactFingerprint"] = artifact_fingerprint_for(artifact)

        with self.assertRaises(HistoryStoreError) as cm:
            self.store.persist_warehouse_evidence(
                match_id,
                identity_review=artifact,
            )
        self.assertIn("candidate name mismatch", str(cm.exception))

        # Assert disk record untouched
        rec_after = self.store.lookup(match_id)
        self.assertEqual(rec_after, rec_before)
        self.assertNotIn("warehouseIdentityReview", rec_after.get("settlement", {}))

    def test_verified_registry_visual_liuliwei_accepted_and_negative_modes(self):
        """Visual item 'visual-liuliwei-4x1' (琉璃尾) from verified_source_card_registry.json
        must be accepted when using its authoritative name, and rejected in negative modes."""
        cat = CatalogAuthority()
        self.assertTrue(cat.is_valid_catalog_id("visual-liuliwei-4x1"))
        self.assertEqual(cat.get_canonical_name("visual-liuliwei-4x1"), "琉璃尾")

        # Positive case: authoritative name '琉璃尾'
        match_id_pos = "match_liuliwei_pos_001"
        draft_pos = build_canonical_match_record_v7(
            match_id=match_id_pos,
            played_at="2026-09-01T10:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft_pos, is_finalized=False)
        units_pos = [
            {
                "reviewUnitId": "u-llw-pos",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "visual-liuliwei-4x1",
                "canonicalName": "琉璃尾",
                "confirmedByHuman": True,
            }
        ]
        self.store.persist_warehouse_evidence(match_id_pos, review_units=units_pos)
        rec_pos = self.store.lookup(match_id_pos)
        saved_units = rec_pos.get("settlement", {}).get("reviewUnits", [])
        self.assertEqual(len(saved_units), 1)
        self.assertEqual(saved_units[0]["canonicalName"], "琉璃尾")
        self.assertEqual(saved_units[0]["selectedCatalogId"], "visual-liuliwei-4x1")

        # Negative Mode 1: Wrong/forged name '琉璃尾-伪'
        match_id_neg1 = "match_liuliwei_neg_001"
        draft_neg1 = build_canonical_match_record_v7(
            match_id=match_id_neg1,
            played_at="2026-09-01T10:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft_neg1, is_finalized=False)
        units_neg1 = [
            {
                "reviewUnitId": "u-llw-neg1",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "visual-liuliwei-4x1",
                "canonicalName": "琉璃尾-伪",
                "confirmedByHuman": True,
            }
        ]
        self.store.persist_warehouse_evidence(match_id_neg1, review_units=units_neg1)
        rec_neg1_before = copy.deepcopy(self.store.lookup(match_id_neg1))
        with self.assertRaises(HistoryStoreError) as cm1:
            self.store.persist_warehouse_evidence(
                match_id_neg1,
                review_units=[self._sample_unit("u-llw-neg1", inliers=15, margin=8)],
            )
        self.assertIn("candidate name mismatch", str(cm1.exception))
        self.assertEqual(self.store.lookup(match_id_neg1), rec_neg1_before)

        # Negative Mode 2: catalogId as canonicalName ('visual-liuliwei-4x1')
        match_id_neg2 = "match_liuliwei_neg_002"
        draft_neg2 = build_canonical_match_record_v7(
            match_id=match_id_neg2,
            played_at="2026-09-01T10:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft_neg2, is_finalized=False)
        units_neg2 = [
            {
                "reviewUnitId": "u-llw-neg2",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "visual-liuliwei-4x1",
                "canonicalName": "visual-liuliwei-4x1",
                "confirmedByHuman": True,
            }
        ]
        self.store.persist_warehouse_evidence(match_id_neg2, review_units=units_neg2)
        rec_neg2_before = copy.deepcopy(self.store.lookup(match_id_neg2))
        with self.assertRaises(HistoryStoreError) as cm2:
            self.store.persist_warehouse_evidence(
                match_id_neg2,
                review_units=[self._sample_unit("u-llw-neg2", inliers=15, margin=8)],
            )
        self.assertIn("canonicalName cannot be catalogId", str(cm2.exception))
        self.assertEqual(self.store.lookup(match_id_neg2), rec_neg2_before)

        # Negative Mode 3: Direct auto reviewUnit with forged name fails immediately leaving draft untouched
        match_id_neg3 = "match_liuliwei_neg_003"
        draft_neg3 = build_canonical_match_record_v7(
            match_id=match_id_neg3,
            played_at="2026-09-01T10:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
        )
        self.store.persist_record_transactional(draft_neg3, is_finalized=False)
        rec_neg3_before = copy.deepcopy(self.store.lookup(match_id_neg3))
        units_neg3 = [
            {
                "reviewUnitId": "u-llw-neg3",
                "confirmationStatus": "CONFIRMED",
                "identityStatus": "EXACT_IDENTIFIED",
                "selectedCatalogId": "visual-liuliwei-4x1",
                "canonicalName": "琉璃尾-伪",
                "confirmedByHuman": False,
            }
        ]
        with self.assertRaises(HistoryStoreError) as cm3:
            self.store.persist_warehouse_evidence(match_id_neg3, review_units=units_neg3)
        self.assertIn("candidate name mismatch", str(cm3.exception))
        self.assertEqual(self.store.lookup(match_id_neg3), rec_neg3_before)

    def test_catalog_authority_registry_admission_strict_validation(self):
        """CatalogAuthority must enforce validate_verified_registry_card and reject broken/tampered cards."""
        from catalog_validator import validate_verified_registry_card

        # Valid card from real registry
        registry_file = PROJECT_ROOT / "assets" / "items" / "verified_source_card_registry.json"
        real_cards = json.loads(registry_file.read_text(encoding="utf-8"))["cards"]
        valid_card = copy.deepcopy(next(c for c in real_cards if c["catalogId"] == "visual-liuliwei-4x1"))
        ok, reason = validate_verified_registry_card(valid_card, root=PROJECT_ROOT)
        self.assertTrue(ok, f"Expected valid card to pass, got: {reason}")

        # Negative 1: Missing image file
        card_bad_file = dict(valid_card, sourceScreenshot="assets/items/does_not_exist.png")
        ok, reason = validate_verified_registry_card(card_bad_file, root=PROJECT_ROOT)
        self.assertFalse(ok)
        self.assertIn("not found", reason)

        # Negative 2: Bad screenshot SHA-256
        card_bad_sha = dict(valid_card, sourceScreenshotSha256="0000000000000000000000000000000000000000000000000000000000000000")
        ok, reason = validate_verified_registry_card(card_bad_sha, root=PROJECT_ROOT)
        self.assertFalse(ok)
        self.assertIn("SHA256 mismatch", reason)

        # Negative 3: Out-of-bounds bbox
        card_oob = dict(valid_card, bbox=[55, 30, 99999, 99999])
        ok, reason = validate_verified_registry_card(card_oob, root=PROJECT_ROOT)
        self.assertFalse(ok)
        self.assertIn("extends beyond", reason)

        # Negative 4: Empty/negative bbox
        card_empty = dict(valid_card, bbox=[55, 30, 0, 60])
        ok, reason = validate_verified_registry_card(card_empty, root=PROJECT_ROOT)
        self.assertFalse(ok)
        self.assertIn("strictly positive", reason)

        # Negative 5: Unknown ID
        card_unk_id = dict(valid_card, catalogId="")
        ok, reason = validate_verified_registry_card(card_unk_id, root=PROJECT_ROOT)
        self.assertFalse(ok)

        # Negative 6: Name mismatch with catalog_065 official name
        card_name_mismatch = dict(valid_card, catalogId="image1-0-0", name="伪造名字")
        ok, reason = validate_verified_registry_card(card_name_mismatch, root=PROJECT_ROOT)
        self.assertFalse(ok)
        self.assertIn("matches official catalog_065 ID", reason)

        # Negative 7: Adversarial unofficial fake ID and fabricated name with genuine screenshot and valid bbox
        card_adversarial_fake = dict(valid_card, catalogId="visual-fake-999", name="编造名称")
        ok, reason = validate_verified_registry_card(card_adversarial_fake, root=PROJECT_ROOT)
        self.assertFalse(ok)
        self.assertIn("not registered in immutable verified registry", reason)

        # Negative 8: Cross-binding attack - legitimate ID & authentic name paired with another authentic card's screenshot & bbox
        other_card = next(c for c in real_cards if c["catalogId"] != valid_card["catalogId"])
        card_cross_binding = dict(
            valid_card,
            sourceScreenshot=other_card["sourceScreenshot"],
            sourceScreenshotSha256=other_card["sourceScreenshotSha256"],
            bbox=other_card["bbox"],
        )
        ok, reason = validate_verified_registry_card(card_cross_binding, root=PROJECT_ROOT)
        self.assertFalse(ok)
        self.assertIn("cross-binding rejected", reason)

        # Admission test: CatalogAuthority rejects invalid card in custom registry
        fake_reg = self.test_dir / "fake_reg.json"
        fake_reg.write_text(json.dumps({
            "cards": [
                valid_card,
                card_bad_file,
                card_bad_sha,
                card_oob,
                card_empty,
                card_name_mismatch,
                card_adversarial_fake,
                card_cross_binding,
            ]
        }), encoding="utf-8")

        cat = CatalogAuthority(registry_path=fake_reg, root=PROJECT_ROOT)
        self.assertTrue(cat.is_valid_catalog_id("visual-liuliwei-4x1"))
        self.assertEqual(cat.get_canonical_name("visual-liuliwei-4x1"), "琉璃尾")
        self.assertFalse(cat.is_valid_name("伪造名字"))
        self.assertFalse(cat.is_valid_catalog_id("visual-fake-999"))
        self.assertFalse(cat.is_valid_name("编造名称"))

    def test_warehouse_capture_host_crops_rollback_on_persistence_failure(self):
        """When persist_warehouse_evidence fails, all staged/created crop files are rolled back immediately."""
        import cv2
        import numpy as np
        from warehouse_capture_host import WarehouseCaptureHost

        match_id = "test_rollback_match_001"
        data_root = self.test_dir / "rollback_env"
        data_root.mkdir(parents=True, exist_ok=True)
        crops_dir = data_root / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)

        # Create dummy evidence blob
        dummy_img = np.zeros((300, 300, 3), dtype=np.uint8)
        dummy_img[50:150, 50:150] = [100, 150, 200]
        ok, buf = cv2.imencode(".png", dummy_img)
        self.assertTrue(ok)
        blob_bytes = buf.tobytes()
        blob_sha = hashlib.sha256(blob_bytes).hexdigest()

        blob_dir = data_root / "evidence" / "settlement_v2" / "blobs" / blob_sha[:2]
        blob_dir.mkdir(parents=True, exist_ok=True)
        (blob_dir / f"{blob_sha}.png").write_bytes(blob_bytes)

        # Base record in store
        store_path = data_root / "history" / "history.json"
        store = CanonicalHistoryStore(str(store_path))
        base_rec = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-09-12T10:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
            environment={"venue": "test_venue", "box": "test_box"},
        )
        base_rec["settlement"]["isSettled"] = True
        store.persist_record_transactional(base_rec, is_finalized=False)

        # Faulty store that raises error during persist_warehouse_evidence
        class FailingHistoryStore(CanonicalHistoryStore):
            def persist_warehouse_evidence(self, *args, **kwargs):
                raise RuntimeError("Simulated database write error")

        faulty_store = FailingHistoryStore(str(store_path))

        packet = {
            "recordStableKey": match_id,
            "capturedAt": "2026-09-12T10:00:00Z",
            "segments": [{"evidenceId": "ev-1", "sha256": blob_sha}],
            "reviewUnits": [
                {
                    "reviewUnitId": "unit_rollback_1",
                    "bbox": [50.0, 50.0, 100.0, 100.0],
                    "observations": [
                        {
                            "evidenceId": "ev-1",
                            "sha256": blob_sha,
                            "bbox": [50.0, 50.0, 100.0, 100.0],
                            "status": "FULL",
                        }
                    ],
                }
            ],
        }

        host = WarehouseCaptureHost(history_store_factory=lambda: faulty_store)
        result = host.persist_warehouse_occupancy_and_review(packet)

        # Assert fail-closed: returned None
        self.assertIsNone(result)

        # Assert ZERO crops on disk! Rolled back completely!
        crops_on_disk = list(crops_dir.glob("*.png"))
        self.assertEqual(len(crops_on_disk), 0, f"Expected 0 crops on disk after rollback, found: {crops_on_disk}")

        # Assert store record was not modified with review units
        rec_after = store.get_record(match_id)
        self.assertNotIn("reviewUnits", rec_after.get("settlement", {}))

    def test_warehouse_capture_host_crops_missing_evidence_fail_closed(self):
        """When required evidence image is missing, crop generation fails-closed and saves nothing."""
        from warehouse_capture_host import WarehouseCaptureHost

        match_id = "test_missing_ev_match_002"
        data_root = self.test_dir / "missing_ev_env"
        data_root.mkdir(parents=True, exist_ok=True)
        crops_dir = data_root / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)

        store_path = data_root / "history" / "history.json"
        store = CanonicalHistoryStore(str(store_path))
        base_rec = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-09-12T10:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
            environment={"venue": "test_venue", "box": "test_box"},
        )
        base_rec["settlement"]["isSettled"] = True
        store.persist_record_transactional(base_rec, is_finalized=False)

        packet = {
            "recordStableKey": match_id,
            "capturedAt": "2026-09-12T10:00:00Z",
            "segments": [],
            "reviewUnits": [
                {
                    "reviewUnitId": "unit_missing_ev_1",
                    "bbox": [10.0, 10.0, 50.0, 50.0],
                    # Missing observation sha256 and segment sha256
                    "observations": [],
                }
            ],
        }

        host = WarehouseCaptureHost(history_store_factory=lambda: store)
        result = host.persist_warehouse_occupancy_and_review(packet)

        # Assert fail-closed: returned None
        self.assertIsNone(result)
        # Assert ZERO crops on disk
        self.assertEqual(len(list(crops_dir.glob("*.png"))), 0)

    def test_warehouse_capture_host_crops_strict_bbox_validation(self):
        """Strictly reject zero-area, inverted, out-of-bound, and non-finite bboxes without 1x1 clamping."""
        import cv2
        import numpy as np
        from warehouse_capture_host import WarehouseCaptureHost

        match_id = "test_strict_bbox_match"
        data_root = self.test_dir / "strict_bbox_env"
        data_root.mkdir(parents=True, exist_ok=True)
        crops_dir = data_root / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)

        # Create dummy evidence blob 200x200
        dummy_img = np.zeros((200, 200, 3), dtype=np.uint8)
        dummy_img[20:80, 20:80] = [120, 180, 240]
        ok, buf = cv2.imencode(".png", dummy_img)
        self.assertTrue(ok)
        blob_bytes = buf.tobytes()
        blob_sha = hashlib.sha256(blob_bytes).hexdigest()

        blob_dir = data_root / "evidence" / "settlement_v2" / "blobs" / blob_sha[:2]
        blob_dir.mkdir(parents=True, exist_ok=True)
        (blob_dir / f"{blob_sha}.png").write_bytes(blob_bytes)

        store_path = data_root / "history" / "history.json"
        store = CanonicalHistoryStore(str(store_path))
        base_rec = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-09-12T10:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
            environment={"venue": "test_venue", "box": "test_box"},
        )
        base_rec["settlement"]["isSettled"] = True
        store.persist_record_transactional(base_rec, is_finalized=False)

        bad_bboxes = [
            ("zero_area", [50.0, 50.0, 50.0, 50.0]),
            ("zero_width", [50.0, 50.0, 50.0, 80.0]),
            ("zero_height", [50.0, 50.0, 80.0, 50.0]),
            ("inverted_x", [80.0, 50.0, 50.0, 80.0]),
            ("inverted_y", [50.0, 80.0, 80.0, 50.0]),
            ("out_of_bound_x", [0.0, 0.0, 99999.0, 100.0]),
            ("out_of_bound_y", [0.0, 0.0, 100.0, 99999.0]),
            ("negative_x", [-10.0, 0.0, 50.0, 50.0]),
            ("boolean_elem", [10.0, 10.0, True, 50.0]),
            ("nan_elem", [10.0, 10.0, float("nan"), 50.0]),
        ]

        host = WarehouseCaptureHost(history_store_factory=lambda: store)
        for label, bad_bbox in bad_bboxes:
            packet = {
                "recordStableKey": match_id,
                "capturedAt": "2026-09-12T10:00:00Z",
                "segments": [{"evidenceId": "ev-strict", "sha256": blob_sha}],
                "reviewUnits": [
                    {
                        "reviewUnitId": f"unit_{label}",
                        "bbox": bad_bbox,
                        "observations": [
                            {
                                "evidenceId": "ev-strict",
                                "sha256": blob_sha,
                                "bbox": bad_bbox,
                                "status": "FULL",
                            }
                        ],
                    }
                ],
            }
            res = host.persist_warehouse_occupancy_and_review(packet)
            self.assertIsNone(res, f"Expected None for invalid bbox {label}, got {res}")
            # Assert NO crops were written to disk, specifically no 1x1 forced crop!
            disk_crops = list(crops_dir.glob("*.png"))
            self.assertEqual(len(disk_crops), 0, f"Expected 0 crops on disk for {label}, found {disk_crops}")

    def test_warehouse_capture_host_crop_update_and_failure_restoration(self):
        """Crop cache binds blob_sha + bbox. Updates recut crops; transaction failure restores original bytes."""
        import cv2
        import numpy as np
        from warehouse_capture_host import WarehouseCaptureHost

        match_id = "test_update_restore_match"
        data_root = self.test_dir / "update_restore_env"
        data_root.mkdir(parents=True, exist_ok=True)
        crops_dir = data_root / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)

        # Blob 1: Red square
        img1 = np.zeros((300, 300, 3), dtype=np.uint8)
        img1[50:150, 50:150] = [0, 0, 255]
        ok, buf1 = cv2.imencode(".png", img1)
        self.assertTrue(ok)
        blob1_bytes = buf1.tobytes()
        blob1_sha = hashlib.sha256(blob1_bytes).hexdigest()
        b1_dir = data_root / "evidence" / "settlement_v2" / "blobs" / blob1_sha[:2]
        b1_dir.mkdir(parents=True, exist_ok=True)
        (b1_dir / f"{blob1_sha}.png").write_bytes(blob1_bytes)

        # Blob 2: Green square
        img2 = np.zeros((300, 300, 3), dtype=np.uint8)
        img2[160:260, 160:260] = [0, 255, 0]
        ok, buf2 = cv2.imencode(".png", img2)
        self.assertTrue(ok)
        blob2_bytes = buf2.tobytes()
        blob2_sha = hashlib.sha256(blob2_bytes).hexdigest()
        b2_dir = data_root / "evidence" / "settlement_v2" / "blobs" / blob2_sha[:2]
        b2_dir.mkdir(parents=True, exist_ok=True)
        (b2_dir / f"{blob2_sha}.png").write_bytes(blob2_bytes)

        store_path = data_root / "history" / "history.json"
        store = CanonicalHistoryStore(str(store_path))
        base_rec = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-09-12T10:00:00Z",
            lifecycle_status="DRAFT",
            source="live_capture",
            environment={"venue": "test_venue", "box": "test_box"},
        )
        base_rec["settlement"]["isSettled"] = True
        store.persist_record_transactional(base_rec, is_finalized=False)

        # Step 1: Initial persist
        host = WarehouseCaptureHost(history_store_factory=lambda: store)
        packet_init = {
            "recordStableKey": match_id,
            "capturedAt": "2026-09-12T10:00:00Z",
            "segments": [{"evidenceId": "ev-1", "sha256": blob1_sha}],
            "reviewUnits": [
                {
                    "reviewUnitId": "unit_repl_1",
                    "bbox": [50.0, 50.0, 150.0, 150.0],
                    "observations": [
                        {
                            "evidenceId": "ev-1",
                            "sha256": blob1_sha,
                            "bbox": [50.0, 50.0, 150.0, 150.0],
                            "status": "FULL",
                        }
                    ],
                }
            ],
        }
        res1 = host.persist_warehouse_occupancy_and_review(packet_init)
        self.assertIsNotNone(res1)
        crop_file = crops_dir / f"{match_id}_unit_repl_1.png"
        self.assertTrue(crop_file.is_file())
        initial_crop_bytes = crop_file.read_bytes()
        initial_crop_sha = hashlib.sha256(initial_crop_bytes).hexdigest()

        # Step 2: Update unit with replacement evidence (Blob 2) and new bbox, but store persistence fails!
        class FailingUpdateStore(CanonicalHistoryStore):
            def persist_warehouse_evidence(self, *args, **kwargs):
                raise RuntimeError("Simulated mid-transaction failure during update")

        failing_store = FailingUpdateStore(str(store_path))
        failing_host = WarehouseCaptureHost(history_store_factory=lambda: failing_store)

        packet_update_fail = {
            "recordStableKey": match_id,
            "capturedAt": "2026-09-12T10:01:00Z",
            "segments": [{"evidenceId": "ev-2", "sha256": blob2_sha}],
            "reviewUnits": [
                {
                    "reviewUnitId": "unit_repl_1",
                    "bbox": [160.0, 160.0, 260.0, 260.0],
                    "observations": [
                        {
                            "evidenceId": "ev-2",
                            "sha256": blob2_sha,
                            "bbox": [160.0, 160.0, 260.0, 260.0],
                            "status": "FULL",
                        }
                    ],
                }
            ],
        }
        res_fail = failing_host.persist_warehouse_occupancy_and_review(packet_update_fail)
        self.assertIsNone(res_fail)

        # Assert disk restoration: original image is PRESERVED exactly as it was!
        self.assertTrue(crop_file.is_file())
        self.assertEqual(crop_file.read_bytes(), initial_crop_bytes)

        # Assert store record is untouched
        rec_after_fail = store.get_record(match_id)
        unit_after_fail = rec_after_fail["settlement"]["reviewUnits"][0]
        self.assertEqual(unit_after_fail["cropSha256"], initial_crop_sha)
        self.assertEqual(unit_after_fail["bbox"], [50.0, 50.0, 150.0, 150.0])

        # Step 3: Now successfully update with working store
        res_ok = host.persist_warehouse_occupancy_and_review(packet_update_fail)
        self.assertIsNotNone(res_ok)
        updated_crop_bytes = crop_file.read_bytes()
        updated_crop_sha = hashlib.sha256(updated_crop_bytes).hexdigest()
        self.assertNotEqual(updated_crop_bytes, initial_crop_bytes)

        # Cache file must reflect new version, new blobSha256 and new bbox
        cache_file = crops_dir / ".crop_cache.json"
        self.assertTrue(cache_file.is_file())
        cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
        entry = cache_data.get(f"{match_id}_unit_repl_1")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["blobSha256"], blob2_sha)
        self.assertEqual(entry["bbox"], [160, 160, 260, 260])
        self.assertEqual(entry["cropSha256"], updated_crop_sha)

        # Step 4: Idempotent call with identical evidence & bbox must hit crop cache
        mtime_before = crop_file.stat().st_mtime_ns
        res_cached = host.persist_warehouse_occupancy_and_review(packet_update_fail)
        self.assertIsNotNone(res_cached)
        mtime_after = crop_file.stat().st_mtime_ns
        self.assertEqual(mtime_before, mtime_after, "Expected crop file not to be overwritten on cache hit")


if __name__ == "__main__":
    unittest.main()
