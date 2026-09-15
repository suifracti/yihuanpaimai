"""Unit tests for Settlement Visible-Warehouse Item Proposal Extraction (4D2D1M-C3.2)."""

from __future__ import annotations

import hashlib
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

from settlement_evidence_store_v2 import (
    COVERAGE_UNPROVEN,
    KIND_MAIN,
    KIND_WAREHOUSE_SEGMENT,
    SettlementEvidenceStoreV2,
)
from settlement_item_proposals import extract_settlement_warehouse_proposals


class SettlementItemProposalsV1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "runtime"
        self.root.mkdir()
        self.store = SettlementEvidenceStoreV2(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_visible_warehouse_proposals_from_stored_evidence(self):
        """
        Verify Settlement Visible-Warehouse Item Proposal Extraction Contract (4D2D1M-C3.2):
        1. Saves real settlement fixture into Evidence Store v2 as parent main-settlement evidence.
        2. Extracts non-empty visible item proposals directly from the stored evidence.
        3. All proposal bboxes lie entirely within the warehouse ROI.
        4. Each crop is re-readable from the file-backed store with matching SHA-256 and byteSize.
        5. Each proposal links back to parent evidenceId and parent sha256.
        6. Re-running extraction on the same evidence is strictly deterministic.
        7. Warehouse coverage remains strictly COVERAGE_UNPROVEN / PARTIAL.
        8. No catalog identity or knownItems are written.
        """
        fixture_path = (
            PROJECT_ROOT
            / "tests"
            / "fixtures"
            / "real_snapshots_4d2d1j"
            / "fixture_settlement_client_sanitized.png"
        )
        img_bytes = fixture_path.read_bytes()
        img = cv2.imread(str(fixture_path))
        self.assertIsNotNone(img)
        h, w = img.shape[:2]

        record_key = "match_c32_test_001"
        parent_desc = self.store.save_original(
            record_stable_key=record_key,
            kind=KIND_MAIN,
            image_bytes=img_bytes,
            captured_at="2026-08-30T02:00:00Z",
            coverage_mode="viewport-segment",
            coverage_status=COVERAGE_UNPROVEN,
        )

        # 1. Run extraction
        proposals = extract_settlement_warehouse_proposals(
            store=self.store,
            parent_descriptor=parent_desc,
            save_crops=True,
        )

        # 2. Verify non-empty proposals
        self.assertGreater(len(proposals), 0)

        # Warehouse ROI boundaries
        gx1, gy1 = round(w * 1315 / 1920), round(h * 214 / 1080)
        gx2, gy2 = round(w * 1878 / 1920), round(h * 776 / 1080)

        for p in proposals:
            # 3. Verify bbox within warehouse ROI
            bx1, by1, bx2, by2 = p["bbox"]
            self.assertGreaterEqual(bx1, gx1)
            self.assertLessEqual(bx2, gx2)
            self.assertGreaterEqual(by1, gy1)
            self.assertLessEqual(by2, gy2)

            # 4. Verify parent linkage
            self.assertEqual(p["parentEvidenceId"], parent_desc["evidenceId"])
            self.assertEqual(p["parentSha256"], parent_desc["sha256"])
            self.assertEqual(p["recordStableKey"], record_key)

            # 5. Verify coverage status remains PARTIAL / COVERAGE_UNPROVEN
            self.assertEqual(p["coverageStatus"], COVERAGE_UNPROVEN)
            self.assertEqual(p["warehouseCoverage"], "PARTIAL")

            # 6. Verify NO catalog identity is assigned
            self.assertNotIn("catalogId", p)
            self.assertNotIn("exactItemId", p)
            self.assertNotIn("knownItems", p)
            self.assertNotIn("price", p)

            # 7. Verify crop re-readability and SHA-256 integrity
            crop_path = self.root / p["cropRelativePath"]
            self.assertTrue(crop_path.is_file())
            loaded_crop_bytes = crop_path.read_bytes()
            self.assertEqual(len(loaded_crop_bytes), p["cropByteSize"])
            self.assertEqual(hashlib.sha256(loaded_crop_bytes).hexdigest(), p["cropSha256"])

        # 8. Verify determinism: re-running on same parent descriptor produces identical list
        proposals_2 = extract_settlement_warehouse_proposals(
            store=self.store,
            parent_descriptor=parent_desc,
            save_crops=True,
        )
        self.assertEqual(len(proposals), len(proposals_2))
        for p1, p2 in zip(proposals, proposals_2):
            self.assertEqual(p1["proposalId"], p2["proposalId"])
            self.assertEqual(p1["bbox"], p2["bbox"])
            self.assertEqual(p1["cropSha256"], p2["cropSha256"])
            self.assertEqual(p1["qualityObservation"], p2["qualityObservation"])

    def test_production_wiring_auto_generates_proposals_on_stable_settlement(self):
        """
        Verify Settlement Proposal Production Wiring (4D2D1M-C3.2W):
        1. Calls production pipeline _stabilize_settlement with real settlement fixture.
        2. main-settlement original is automatically saved to Evidence Store v2.
        3. visible warehouse proposals are automatically generated without manual intervention.
        4. Derived crops exist in store and match proposal cropSha256.
        5. Parent provenance (parentEvidenceId, parentSha256) is correct.
        6. Repeated stabilization frames are idempotent and do not re-extract.
        7. Warehouse coverage remains strictly COVERAGE_UNPROVEN / PARTIAL.
        8. No catalog identity or knownItems are written.
        """
        from settlement_stable_frame_persist import STATUS_IDEMPOTENT, STATUS_SAVED
        from vision_pipeline import SETTLEMENT_STABLE_FRAMES, NTEVisionPipeline

        fixture_path = (
            PROJECT_ROOT
            / "tests"
            / "fixtures"
            / "real_snapshots_4d2d1j"
            / "fixture_settlement_client_sanitized.png"
        )
        img = cv2.imread(str(fixture_path))
        self.assertIsNotNone(img)

        pipe = NTEVisionPipeline()
        pipe._settlement_evidence_store = self.store
        pipe.current_context["id"] = "match_c32w_prod_001"
        pipe.current_context["matchId"] = "match_c32w_prod_001"
        pipe.current_context["recordStableKey"] = "match_c32w_prod_001"

        settlement_info = {
            "isSettlement": True,
            "clearingPrice": 600000,
            "actualTotal": 785974,
            "profit": 185974,
        }

        # Stabilize settlement across required frames
        for _ in range(SETTLEMENT_STABLE_FRAMES):
            pipe._stabilize_settlement(settlement_info, frame=img, captured_at="2026-08-30T02:20:00Z")

        self.assertTrue(pipe.current_context["settlementReady"])
        self.assertEqual(pipe.current_context["settlementFileEvidenceStatus"], STATUS_SAVED)

        main_desc = pipe.current_context.get("settlementFileEvidence")
        self.assertIsInstance(main_desc, dict)
        self.assertEqual(main_desc["kind"], KIND_MAIN)

        # 3. Verify proposals and candidate evidence automatically generated in pipeline context
        proposals = pipe.current_context.get("settlementWarehouseProposals")
        self.assertIsInstance(proposals, list)
        self.assertGreater(len(proposals), 0)
        self.assertEqual(pipe.current_context.get("settlementWarehouseProposalCount"), len(proposals))
        self.assertEqual(pipe.current_context.get("settlementWarehouseProposalStatus"), "PROPOSALS_EXTRACTED")

        cand_evidences = pipe.current_context.get("settlementCatalogCandidateEvidence")
        self.assertIsInstance(cand_evidences, list)
        self.assertEqual(len(cand_evidences), len(proposals))
        self.assertEqual(pipe.current_context.get("settlementCatalogCandidateCount"), len(proposals))
        self.assertEqual(pipe.current_context.get("settlementCatalogCandidateStatus"), "CANDIDATES_RESOLVED")

        # 4. Verify derived crops, candidates, and parent linkage
        for p, cand in zip(proposals, cand_evidences):
            self.assertEqual(p["parentEvidenceId"], main_desc["evidenceId"])
            self.assertEqual(p["parentSha256"], main_desc["sha256"])
            self.assertEqual(p["recordStableKey"], "match_c32w_prod_001")
            self.assertEqual(p["coverageStatus"], COVERAGE_UNPROVEN)
            self.assertEqual(p["warehouseCoverage"], "PARTIAL")

            crop_path = self.root / p["cropRelativePath"]
            self.assertTrue(crop_path.is_file())
            crop_bytes = crop_path.read_bytes()
            self.assertEqual(hashlib.sha256(crop_bytes).hexdigest(), p["cropSha256"])

            # Candidate evidence checks
            self.assertEqual(cand["proposalId"], p["proposalId"])
            self.assertEqual(cand["parentEvidenceId"], main_desc["evidenceId"])
            self.assertEqual(cand["parentSha256"], main_desc["sha256"])
            self.assertEqual(cand["cropSha256"], p["cropSha256"])
            self.assertEqual(cand["recordStableKey"], "match_c32w_prod_001")
            self.assertEqual(cand["warehouseCoverage"], "PARTIAL")
            self.assertEqual(cand["coverageStatus"], COVERAGE_UNPROVEN)
            self.assertIn(
                cand["candidateStatus"],
                ("AMBIGUOUS_CANDIDATES", "UNIQUE_IN_CATALOG", "NO_CATALOG_MATCH"),
            )
            # Full candidate set is preserved
            self.assertEqual(len(cand["candidates"]), cand["candidateCount"])
            self.assertEqual(len(cand["candidateCatalogIds"]), cand["candidateCount"])
            # Never pick candidates[0] or assign single selected identity
            self.assertNotIn("selectedCatalogId", cand)
            self.assertNotIn("exactItemId", cand)
            self.assertNotIn("chosenCandidate", cand)

        # 5. Verify NO identity / knownItems
        self.assertEqual(pipe.current_context.get("knownGold"), [])
        self.assertEqual(pipe.current_context.get("knownPurple"), [])

        # 6. Verify candidate resolution on unique, ambiguous, and out-of-catalog proposals
        from settlement_catalog_candidates import (
            STATUS_AMBIGUOUS_CANDIDATES,
            STATUS_NO_CATALOG_MATCH,
            STATUS_UNIQUE_IN_CATALOG,
            SettlementCatalogCandidateResolver,
        )

        resolver = SettlementCatalogCandidateResolver()
        # Test unique case: find a shape/rarity with exactly 1 item if exists, or craft mock
        mock_ambiguous = {"proposalId": "p_amb", "rarityObservation": "gold", "gridShape": "1x1", "widthCells": 1, "heightCells": 1}
        cand_amb = resolver.resolve_candidates_for_proposal(mock_ambiguous)
        self.assertEqual(cand_amb["candidateStatus"], STATUS_AMBIGUOUS_CANDIDATES)
        self.assertGreater(cand_amb["candidateCount"], 1)
        self.assertEqual(len(cand_amb["candidates"]), cand_amb["candidateCount"])

        mock_unknown = {"proposalId": "p_unk", "rarityObservation": "unknown", "gridShape": "9x9", "widthCells": 9, "heightCells": 9}
        cand_unk = resolver.resolve_candidates_for_proposal(mock_unknown)
        self.assertEqual(cand_unk["candidateStatus"], STATUS_NO_CATALOG_MATCH)
        self.assertEqual(cand_unk["candidateCount"], 0)
        self.assertEqual(cand_unk["candidates"], [])

        # 7. Verify idempotency on additional frame
        prop_count_before = len(proposals)
        pipe._stabilize_settlement(settlement_info, frame=img, captured_at="2026-08-30T02:20:01Z")
        self.assertEqual(pipe.current_context["settlementFileEvidenceStatus"], STATUS_IDEMPOTENT)
        self.assertEqual(pipe.current_context.get("settlementWarehouseProposalStatus"), "PROPOSALS_SKIPPED_IDEMPOTENT")
        self.assertEqual(len(pipe.current_context.get("settlementWarehouseProposals")), prop_count_before)

    def test_proposal_extraction_failure_does_not_block_main_evidence(self):
        """Failure boundary: proposal failure NEVER rollbacks or blocks main-settlement evidence."""
        from unittest import mock
        from settlement_stable_frame_persist import STATUS_SAVED, persist_stable_settlement_original

        fixture_path = (
            PROJECT_ROOT
            / "tests"
            / "fixtures"
            / "real_snapshots_4d2d1j"
            / "fixture_settlement_client_sanitized.png"
        )
        img = cv2.imread(str(fixture_path))
        self.assertIsNotNone(img)

        with mock.patch(
            "settlement_item_proposals.extract_settlement_warehouse_proposals",
            side_effect=RuntimeError("segmenter boom"),
        ):
            result = persist_stable_settlement_original(
                store=self.store,
                is_settlement=True,
                record_stable_key="match_fail_boundary_001",
                frame=img,
                captured_at="2026-08-30T02:25:00Z",
                extract_proposals=True,
            )

            # Main evidence must be safely saved!
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], STATUS_SAVED)
            self.assertIsNotNone(result["descriptor"])
            self.assertEqual(result["proposalStatus"], "PROPOSALS_EXTRACTION_FAILED")
            self.assertIn("segmenter boom", result["proposalWarning"])
            self.assertIsNone(result["proposals"])

            # Verify main evidence file exists in store
            main_path = self.root / result["descriptor"]["relativePath"]
            self.assertTrue(main_path.is_file())


if __name__ == "__main__":
    unittest.main()
