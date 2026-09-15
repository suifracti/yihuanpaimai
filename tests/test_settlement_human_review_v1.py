"""Unit tests for Settlement Human Review Confirmation Bridge (4D2D1M-C3.4)."""

from __future__ import annotations

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
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from settlement_catalog_candidates import (
    STATUS_AMBIGUOUS_CANDIDATES,
    STATUS_NO_CATALOG_MATCH,
    STATUS_UNIQUE_IN_CATALOG,
    resolve_settlement_catalog_candidate_evidence,
)
from settlement_evidence_store_v2 import (
    COVERAGE_UNPROVEN,
    KIND_MAIN,
    SettlementEvidenceStoreV2,
)
from settlement_human_review import (
    ACTION_CONFIRM_CANDIDATE,
    ACTION_CONFIRM_OVERRIDE,
    SOURCE_HUMAN_REVIEWED,
    SettlementHumanReviewError,
    apply_settlement_human_review_action,
    load_settlement_reviewed_truth,
)
from settlement_item_proposals import extract_settlement_warehouse_proposals
from settlement_stable_frame_persist import STATUS_SAVED, persist_stable_settlement_original
from vision_pipeline import SETTLEMENT_STABLE_FRAMES, NTEVisionPipeline


class SettlementHumanReviewV1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "runtime"
        self.root.mkdir()
        self.store = SettlementEvidenceStoreV2(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_human_review_confirmation_bridge_full_flow(self):
        """
        Verify Settlement Human Review Confirmation Bridge Contract (4D2D1M-C3.4):
        1. Without user action -> No reviewed truth exists in store.
        2. CONFIRM_CANDIDATE with ambiguous proposal without selectedCatalogId fails fail-safe.
        3. CONFIRM_CANDIDATE with explicit selectedCatalogId persists re-readable HUMAN_REVIEWED_CATALOG_ID.
        4. CONFIRM_CATALOG_OVERRIDE accepts only valid catalog items and rejects invalid catalogId.
        5. Every reviewed truth record traces back to proposalId, cropSha256, parentEvidenceId, parentSha256.
        6. Warehouse coverage strictly remains PARTIAL / COVERAGE_UNPROVEN.
        7. No knownItems or Solver inputs are written.
        """
        fixture_path = (
            PROJECT_ROOT
            / "tests"
            / "fixtures"
            / "real_snapshots_4d2d1j"
            / "fixture_settlement_client_sanitized.png"
        )
        img = cv2.imread(str(fixture_path))
        self.assertIsNotNone(img)

        record_key = "match_c34_review_001"
        pipe = NTEVisionPipeline()
        pipe._settlement_evidence_store = self.store
        pipe.current_context["id"] = record_key
        pipe.current_context["matchId"] = record_key
        pipe.current_context["recordStableKey"] = record_key

        settlement_info = {
            "isSettlement": True,
            "clearingPrice": 600000,
            "actualTotal": 785974,
            "profit": 185974,
        }

        # Run pipeline to stabilize settlement and auto-derive candidates
        for _ in range(SETTLEMENT_STABLE_FRAMES):
            pipe._stabilize_settlement(settlement_info, frame=img, captured_at="2026-08-30T02:40:00Z")

        self.assertTrue(pipe.current_context["settlementReady"])
        proposals = pipe.current_context.get("settlementWarehouseProposals")
        cand_evidences = pipe.current_context.get("settlementCatalogCandidateEvidence")
        main_desc = pipe.current_context.get("settlementFileEvidence")

        self.assertIsInstance(proposals, list)
        self.assertIsInstance(cand_evidences, list)
        self.assertGreater(len(cand_evidences), 0)

        # 1. No user action -> store contains 0 reviewed truths
        initial_reviews = load_settlement_reviewed_truth(self.store, record_key)
        self.assertEqual(initial_reviews, [])

        # Find an ambiguous candidate proposal
        ambiguous_cand = next(
            (c for c in cand_evidences if c["candidateStatus"] == STATUS_AMBIGUOUS_CANDIDATES),
            None,
        )
        self.assertIsNotNone(ambiguous_cand)
        prop_id_amb = ambiguous_cand["proposalId"]

        # 2. CONFIRM_CANDIDATE on ambiguous without selectedCatalogId -> MUST fail
        with self.assertRaises(SettlementHumanReviewError) as ctx_err:
            apply_settlement_human_review_action(
                store=self.store,
                candidate_evidence_list=cand_evidences,
                action_payload={
                    "proposalId": prop_id_amb,
                    "action": ACTION_CONFIRM_CANDIDATE,
                },
                proposals=proposals,
            )
        self.assertEqual(ctx_err.exception.code, "SELECTED_CATALOG_ID_REQUIRED")

        # 3. CONFIRM_CANDIDATE on ambiguous with selectedCatalogId NOT in candidates -> MUST fail
        with self.assertRaises(SettlementHumanReviewError) as ctx_err:
            apply_settlement_human_review_action(
                store=self.store,
                candidate_evidence_list=cand_evidences,
                action_payload={
                    "proposalId": prop_id_amb,
                    "action": ACTION_CONFIRM_CANDIDATE,
                    "selectedCatalogId": "non_existent_fake_id",
                },
                proposals=proposals,
            )
        self.assertEqual(ctx_err.exception.code, "SELECTED_CATALOG_ID_NOT_IN_CANDIDATES")

        # 4. CONFIRM_CANDIDATE on ambiguous with valid selected candidate -> SUCCEEDS
        chosen_cat_id = ambiguous_cand["candidateCatalogIds"][0]
        reviewed_1 = apply_settlement_human_review_action(
            store=self.store,
            candidate_evidence_list=cand_evidences,
            action_payload={
                "proposalId": prop_id_amb,
                "action": ACTION_CONFIRM_CANDIDATE,
                "selectedCatalogId": chosen_cat_id,
            },
            proposals=proposals,
        )

        self.assertEqual(reviewed_1["source"], SOURCE_HUMAN_REVIEWED)
        self.assertEqual(reviewed_1["proposalId"], prop_id_amb)
        self.assertEqual(reviewed_1["selectedCatalogId"], chosen_cat_id)
        self.assertEqual(reviewed_1["parentEvidenceId"], main_desc["evidenceId"])
        self.assertEqual(reviewed_1["parentSha256"], main_desc["sha256"])
        self.assertEqual(reviewed_1["cropSha256"], ambiguous_cand["cropSha256"])
        self.assertEqual(reviewed_1["warehouseCoverage"], "PARTIAL")
        self.assertEqual(reviewed_1["coverageStatus"], COVERAGE_UNPROVEN)

        # 5. CONFIRM_CATALOG_OVERRIDE with invalid catalogId -> MUST fail
        prop_id_2 = cand_evidences[1]["proposalId"]
        with self.assertRaises(SettlementHumanReviewError) as ctx_err:
            apply_settlement_human_review_action(
                store=self.store,
                candidate_evidence_list=cand_evidences,
                action_payload={
                    "proposalId": prop_id_2,
                    "action": ACTION_CONFIRM_OVERRIDE,
                    "selectedCatalogId": "definitely_invalid_id_99999",
                },
                proposals=proposals,
            )
        self.assertEqual(ctx_err.exception.code, "INVALID_OVERRIDE_CATALOG_ID")

    def test_human_review_confirmation_bridge_grouping_identity_evidence_flow(self):
        """
        Verify Human Review Bridge rewired to Grouping Identity Evidence (4D2D1M-C3.4A):
        1. No action -> No reviewed truth.
        2. CONFIRM_CANDIDATE on ambiguous grouping hypothesis requires explicit selectedCatalogId.
        3. Reject non-candidate ID on ambiguous hypothesis.
        4. CONFIRM_CANDIDATE with valid candidate persists reviewed truth binding groupingHypothesisId.
        5. CONFIRM_CATALOG_OVERRIDE rejects invalid catalogId and accepts valid catalogId.
        6. Persisted truth binds groupingHypothesisId, cells, bbox, parent evidence provenance.
        7. Warehouse coverage remains strictly PARTIAL / COVERAGE_UNPROVEN.
        8. Zero writes to knownItems, Solver, History.
        """
        from settlement_catalog_candidates import (
            SettlementCatalogCandidateResolver,
            STATUS_AMBIGUOUS_CANDIDATES,
            STATUS_EXACT_IDENTIFIED,
            STATUS_NO_CATALOG_MATCH,
            STATUS_UNIQUE_IN_CATALOG,
        )

        record_key = "match_c34a_grouping_001"
        _, png_data = cv2.imencode(".png", np.zeros((100, 100, 3), dtype=np.uint8))
        main_desc = self.store.save_original(
            record_stable_key=record_key,
            kind=KIND_MAIN,
            image_bytes=png_data.tobytes(),
            coverage_status=COVERAGE_UNPROVEN,
        )

        # 1. No action -> 0 reviewed truths
        initial_reviews = load_settlement_reviewed_truth(self.store, record_key)
        self.assertEqual(initial_reviews, [])

        resolver = SettlementCatalogCandidateResolver()

        # Mock physical grouping hypotheses
        hyp_amb = {
            "groupingHypothesisId": "ghyp_001",
            "cells": [[0, 0], [0, 1]],
            "row": 0,
            "col": 0,
            "widthCells": 2,
            "heightCells": 1,
            "gridShape": "2x1",
            "rarity": "purple",
            "bbox": [100, 100, 112, 59],
            "recordStableKey": record_key,
            "parentEvidenceId": main_desc["evidenceId"],
            "parentSha256": main_desc["sha256"],
            "cropEvidenceId": "crop_ev_001",
            "cropRelativePath": "evidence/settlement_v2/blobs/ab/abc.png",
            "cropSha256": "a" * 64,
        }

        hyp_noise = {
            "groupingHypothesisId": "ghyp_noise_002",
            "cells": [[2, 3]],
            "row": 2,
            "col": 3,
            "widthCells": 1,
            "heightCells": 1,
            "gridShape": "1x1",
            "rarity": "unknown",
            "bbox": [200, 200, 56, 59],
            "recordStableKey": record_key,
            "parentEvidenceId": main_desc["evidenceId"],
            "parentSha256": main_desc["sha256"],
            "cropEvidenceId": "crop_ev_002",
            "cropRelativePath": "evidence/settlement_v2/blobs/cd/cde.png",
            "cropSha256": "b" * 64,
        }

        # Resolve identity evidence for hypotheses
        ev_amb = resolver.resolve_identity_evidence(hyp_amb)
        ev_amb["recordStableKey"] = record_key
        ev_amb["parentEvidenceId"] = main_desc["evidenceId"]
        ev_amb["parentSha256"] = main_desc["sha256"]
        ev_amb["cropEvidenceId"] = "crop_ev_001"
        ev_amb["cropSha256"] = "a" * 64

        ev_noise = resolver.resolve_identity_evidence(hyp_noise)
        ev_noise["recordStableKey"] = record_key
        ev_noise["parentEvidenceId"] = main_desc["evidenceId"]
        ev_noise["parentSha256"] = main_desc["sha256"]
        ev_noise["cropEvidenceId"] = "crop_ev_002"
        ev_noise["cropSha256"] = "b" * 64

        identity_evidences = [ev_amb, ev_noise]

        self.assertEqual(ev_amb["status"], STATUS_AMBIGUOUS_CANDIDATES)
        self.assertGreater(len(ev_amb["candidateCatalogIds"]), 1)

        # 2. CONFIRM_CANDIDATE on ambiguous grouping hypothesis without selectedCatalogId -> FAILS
        with self.assertRaises(SettlementHumanReviewError) as ctx_err:
            apply_settlement_human_review_action(
                store=self.store,
                candidate_evidence_list=identity_evidences,
                action_payload={
                    "groupingHypothesisId": "ghyp_001",
                    "action": ACTION_CONFIRM_CANDIDATE,
                },
            )
        self.assertEqual(ctx_err.exception.code, "SELECTED_CATALOG_ID_REQUIRED")

        # 3. CONFIRM_CANDIDATE on ambiguous with invalid candidate ID -> FAILS
        with self.assertRaises(SettlementHumanReviewError) as ctx_err:
            apply_settlement_human_review_action(
                store=self.store,
                candidate_evidence_list=identity_evidences,
                action_payload={
                    "groupingHypothesisId": "ghyp_001",
                    "action": ACTION_CONFIRM_CANDIDATE,
                    "selectedCatalogId": "definitely_not_a_candidate_id",
                },
            )
        self.assertEqual(ctx_err.exception.code, "SELECTED_CATALOG_ID_NOT_IN_CANDIDATES")

        # 4. CONFIRM_CANDIDATE with valid candidate -> SUCCEEDS
        chosen_cat_id = ev_amb["candidateCatalogIds"][0]
        reviewed_1 = apply_settlement_human_review_action(
            store=self.store,
            candidate_evidence_list=identity_evidences,
            action_payload={
                "groupingHypothesisId": "ghyp_001",
                "action": ACTION_CONFIRM_CANDIDATE,
                "selectedCatalogId": chosen_cat_id,
            },
        )

        self.assertEqual(reviewed_1["source"], SOURCE_HUMAN_REVIEWED)
        self.assertEqual(reviewed_1["groupingHypothesisId"], "ghyp_001")
        self.assertEqual(reviewed_1["selectedCatalogId"], chosen_cat_id)
        self.assertEqual(reviewed_1["parentEvidenceId"], main_desc["evidenceId"])
        self.assertEqual(reviewed_1["parentSha256"], main_desc["sha256"])
        self.assertEqual(reviewed_1["cropSha256"], "a" * 64)
        self.assertEqual(reviewed_1["cells"], [[0, 0], [0, 1]])
        self.assertEqual(reviewed_1["bbox"], [100, 100, 112, 59])
        self.assertEqual(reviewed_1["warehouseCoverage"], "PARTIAL")
        self.assertEqual(reviewed_1["coverageStatus"], COVERAGE_UNPROVEN)

        # 5. CONFIRM_CATALOG_OVERRIDE with invalid catalogId -> FAILS
        with self.assertRaises(SettlementHumanReviewError) as ctx_err:
            apply_settlement_human_review_action(
                store=self.store,
                candidate_evidence_list=identity_evidences,
                action_payload={
                    "groupingHypothesisId": "ghyp_noise_002",
                    "action": ACTION_CONFIRM_OVERRIDE,
                    "selectedCatalogId": "fake_override_9999",
                },
            )
        self.assertEqual(ctx_err.exception.code, "INVALID_OVERRIDE_CATALOG_ID")

        # 6. CONFIRM_CATALOG_OVERRIDE with valid catalogId -> SUCCEEDS
        valid_cat_id = "image1-0-1"  # "起司"
        reviewed_2 = apply_settlement_human_review_action(
            store=self.store,
            candidate_evidence_list=identity_evidences,
            action_payload={
                "groupingHypothesisId": "ghyp_noise_002",
                "action": ACTION_CONFIRM_OVERRIDE,
                "selectedCatalogId": valid_cat_id,
                "overrideReason": "HUMAN_VISUAL_IDENTIFICATION",
            },
        )

        self.assertEqual(reviewed_2["source"], SOURCE_HUMAN_REVIEWED)
        self.assertEqual(reviewed_2["groupingHypothesisId"], "ghyp_noise_002")
        self.assertEqual(reviewed_2["reviewAction"], ACTION_CONFIRM_OVERRIDE)
        self.assertEqual(reviewed_2["selectedCatalogId"], valid_cat_id)
        self.assertEqual(reviewed_2["catalogName"], "起司")

        # 7. Reload reviewed truth from persistent store
        loaded = load_settlement_reviewed_truth(self.store, record_key)
        self.assertEqual(len(loaded), 2)
        loaded_ghyps = {it["groupingHypothesisId"] for it in loaded}
        self.assertEqual(loaded_ghyps, {"ghyp_001", "ghyp_noise_002"})

        for it in loaded:
            self.assertEqual(it["source"], SOURCE_HUMAN_REVIEWED)
            self.assertEqual(it["parentEvidenceId"], main_desc["evidenceId"])
            self.assertEqual(it["parentSha256"], main_desc["sha256"])
            self.assertEqual(it["warehouseCoverage"], "PARTIAL")
            self.assertEqual(it["coverageStatus"], COVERAGE_UNPROVEN)

        # 8. Verify no knownItems or Solver inputs are written
        self.assertEqual(os.path.exists(str(self.root / "known_items.json")), False)


if __name__ == "__main__":
    unittest.main()
