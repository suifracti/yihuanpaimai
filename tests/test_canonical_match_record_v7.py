# -*- coding: utf-8 -*-
"""Comprehensive tests for Canonical MatchRecord v7, Layered Validators, and Review Projection."""

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
TOOLS_DIR = PROJECT_ROOT / "tools"
TESTS_DIR = PROJECT_ROOT / "tests"

for p in (str(PROJECT_ROOT), str(APP_DIR), str(CORE_DIR), str(TOOLS_DIR), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from auto_archiver import AutoArchiver
from canonical_history_store import CanonicalHistoryStore, FinalizedRecordConflictError
from canonical_match_record import (
    build_canonical_match_record_v7,
    validate_canonical_match_record_v7,
    validate_finalized_match_record_v7,
)
from effective_truth_resolver import resolve_effective_record_truth
from evaluation_eligibility import (
    build_duplicate_index,
    evaluate_record_eligibility,
    scan_history_file,
    EligibilityReason,
)
from evidence_storage import save_evidence_png
from runtime_revision import get_code_revision
from settlement_truth_holder import (
    ACTIVE_SETTLEMENT_TRUTH_HOLDER,
    build_settlement_truth_evidence_v1,
)
from settlement_truth_reviewer import (
    ReviewStoreManager,
    build_settlement_truth_review_v1,
)
from test_prediction_snapshot_persistence_v1 import (
    get_live_dataset_revision,
    run_js_solver,
)


class TestCanonicalMatchRecordV7(unittest.TestCase):
    def setUp(self):
        ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()

    def tearDown(self):
        ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()

    def test_layered_validators_draft_vs_finalized(self):
        """Test layered validation: base validator accepts DRAFT, finalized validator strictly rejects DRAFT."""
        match_id = "test_draft_layer_001"
        draft_record = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-08-21T22:00:00+08:00",
            lifecycle_status="DRAFT",
            source="manual",
            environment={
                "venueTier": "zhongji",
                "venue": "shanhu",
                "box": "实木宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
            },
            public_intel={"q": 15, "totalItems": 66, "totalGrid": 84},
            qualities={
                "purple": {"count": 5, "avg": 2007, "knownItems": [{"name": "拈花小像"}]},
                "gold": {"count": 4, "avg": 33538, "knownItems": [{"name": "万有星仪"}]},
            },
            settlement={
                "status": "pending",
                "verified": False,
                "clearingPrice": None,
                "actualTotal": None,
                "realizedProfit": None,
                "acquired": False,
                "winner": None,
                "settlementItems": [],
            },
        )

        # 1. Base validator must PASS on valid v7 DRAFT
        is_base_valid, base_reasons = validate_canonical_match_record_v7(draft_record)
        self.assertTrue(is_base_valid, f"Base validator failed on DRAFT: {base_reasons}")
        self.assertEqual(base_reasons, [])

        # 2. FINALIZED validator must FAIL on DRAFT
        is_final_valid, final_reasons = validate_finalized_match_record_v7(draft_record)
        self.assertFalse(is_final_valid)
        self.assertIn("FINALIZED_PROFILE_LIFECYCLE_NOT_FINALIZED", final_reasons)
        self.assertIn("FINALIZED_PROFILE_SETTLEMENT_NOT_VERIFIED", final_reasons)

    def test_fake_v7_legacy_flat_record_fails_base_validation(self):
        """Test negative anti-counterfeiting: legacy flat records with only schemaVersion=7 fail base validation."""
        fake_v7_legacy = {
            "id": "fake_v7_001",
            "schemaVersion": 7,
            "productVersion": "v0.65",
            "playedAt": "2026-08-21T22:00:00+08:00",
            "lifecycleStatus": "FINALIZED",
            "source": "0.65-vision-auto-archiver",
            "venue": "shanhu",
            "box": "皮制宝箱",
            "goldAvg": 33538,
            "purpleAvg": 2007,
            "actualTotal": 1013120.0,
            "clearingPrice": 1099998.0,
            "settlement": {
                "status": "verified",
                "verified": True,
                "clearingPrice": 1099998.0,
                "actualTotal": 1013120.0,
            },
        }

        is_base_valid, base_reasons = validate_canonical_match_record_v7(fake_v7_legacy)
        self.assertFalse(is_base_valid)
        self.assertIn("NAMESPACE_MISSING_ENVIRONMENT", base_reasons)
        self.assertIn("NAMESPACE_MISSING_QUALITIES", base_reasons)

        is_final_valid, final_reasons = validate_finalized_match_record_v7(fake_v7_legacy)
        self.assertFalse(is_final_valid)
        self.assertIn("FORBIDDEN_LEGACY_FLAT_FIELD_VENUE", final_reasons)
        self.assertIn("FORBIDDEN_LEGACY_FLAT_FIELD_BOX", final_reasons)
        self.assertIn("FORBIDDEN_LEGACY_FLAT_FIELD_GOLDAVG", final_reasons)

        dup_idx = build_duplicate_index([fake_v7_legacy])
        res = evaluate_record_eligibility(fake_v7_legacy, dup_idx)
        self.assertFalse(res.formally_eligible)
        self.assertIn(EligibilityReason.RECORD_SCHEMA_VERSION_UNSUPPORTED, res.reasons)

    def test_history_store_idempotency_and_finalized_conflict(self):
        """Test shared history store idempotency and conflict prevention."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_history.json"
            store = CanonicalHistoryStore(db_path)

            match_id = "test_idempotency_001"
            final_record = build_canonical_match_record_v7(
                match_id=match_id,
                played_at="2026-08-21T22:00:00+08:00",
                lifecycle_status="FINALIZED",
                environment={
                    "venueTier": "zhongji",
                    "venue": "shanhu",
                    "box": "实木宝箱",
                    "boxType": "wood",
                    "fieldCondition": "standard",
                },
                settlement={
                    "status": "verified",
                    "verified": True,
                    "clearingPrice": 100000.0,
                    "actualTotal": 120000.0,
                    "realizedProfit": 20000.0,
                    "acquired": True,
                    "winner": "玩家本人",
                    "settlementItems": [],
                },
            )

            # 1. Initial write
            saved1 = store.persist_record_transactional(final_record, is_finalized=True)
            self.assertEqual(saved1["id"], match_id)

            # 2. Idempotent re-save of exact same record succeeds
            saved2 = store.persist_record_transactional(final_record, is_finalized=True)
            self.assertEqual(saved2["id"], match_id)

            # 3. Differing overwrite of already finalized record raises FinalizedRecordConflictError
            mutated_record = copy.deepcopy(final_record)
            mutated_record["settlement"]["actualTotal"] = 999999.0
            with self.assertRaises(FinalizedRecordConflictError):
                store.persist_record_transactional(mutated_record, is_finalized=True)

    def test_two_phase_effective_truth_resolution_and_invariance(self):
        """Two-phase test: Phase A Tier1 -> Truth rejected; Phase B + Review sidecar -> eligible.
        Proves database file is 100% byte-for-byte unchanged between Phase A and Phase B.
        """
        c_rev = get_code_revision(force_refresh=True)
        d_rev = get_live_dataset_revision()

        with tempfile.TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            db_path = data_root / "异环拍卖数据.json"
            archiver = AutoArchiver(db_paths=[str(db_path)])

            match_id = "test_match_two_phase_001"

            # 1. Run real JS solver to generate frozen Prediction Snapshot v1
            ctx_solver = {
                "matchId": match_id,
                "q": 9,
                "goldAvg": 33538,
                "purpleCount": 5,
                "knownGold": "万有星仪",
                "venue": "shanhu",
                "box": "皮制宝箱",
                "fieldCondition": "standard",
                "probabilityProfile": {
                    "coverageRatio": 1.0,
                    "supportedStateCount": 2,
                    "totalStateCount": 2,
                    "shadowWhole": {"p20": 950000, "p50": 1013120, "p80": 1080000},
                },
            }
            res_solver = run_js_solver(ctx_solver, options={"datasetRevision": d_rev, "codeRevision": c_rev, "runtime": "test_runner"})
            pred_snap = res_solver["predictionSnapshot"]

            # 2. Generate real evidence PNG + Tier 1 Settlement Truth Evidence
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            rel_uri, digest = save_evidence_png(img, match_id, data_dir=str(data_root))

            solved_dt = datetime.fromisoformat(pred_snap["solvedAt"].replace("Z", "+00:00"))
            t_obs = (solved_dt + timedelta(seconds=10)).isoformat()

            tier1_truth = build_settlement_truth_evidence_v1(
                match_id=match_id,
                actual_total=1013120.0,
                settlement_observed_at=t_obs,
                truth_source="live_vision_stabilized_settlement",
                truth_confidence="medium",
                evidence_uri=rel_uri,
                evidence_sha256=digest,
            )

            # 3. Archive match via production AutoArchiver
            archive_ctx = {
                "id": match_id,
                "matchId": match_id,
                "venue": "shanhu",
                "box": "皮制宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
                "q": 9,
                "avg": 33538,
                "goldAvg": 33538,
                "purpleCount": 5,
                "identifiedShapes": {"knownGold": [{"name": "万有星仪", "price": 51077, "size": "2x3"}]},
                "myBid": 1099998,
                "myName": "PLAYER_LOCAL",
                "winner": "PLAYER_LOCAL",
                "opponents": [],
                "settlementReady": True,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 1099998,
                    "actualTotal": 1013120,
                    "profit": -136878,
                    "items": [],
                },
                "predictionSnapshot": pred_snap,
                "settlementTruthEvidence": tier1_truth,
            }

            archived_rec = archiver.archive_match(archive_ctx)
            self.assertIsNotNone(archived_rec)
            self.assertEqual(archived_rec["schemaVersion"], 7)
            self.assertEqual(archived_rec["lifecycleStatus"], "FINALIZED")

            # Phase A: Scan history with Tier 1 only
            bytes_phase_a = db_path.read_bytes()
            hash_phase_a = hashlib.sha256(bytes_phase_a).hexdigest()

            scan_a = scan_history_file(db_path, data_root=data_root)
            self.assertEqual(scan_a.record_count, 1)
            self.assertEqual(scan_a.history_admitted_count, 1)
            self.assertEqual(scan_a.formally_eligible_count, 0)
            self.assertEqual(dict(scan_a.primary_rejection_reason_counts).get("TRUTH_CONFIDENCE_NOT_HIGH"), 1)

            # Phase B: Create confirmed Review Sidecar (without modifying database)
            review_store = ReviewStoreManager(data_root=data_root)
            review_artifact = build_settlement_truth_review_v1(
                match_id=match_id,
                action="confirmed",
                original_actual_total=1013120.0,
                reviewed_actual_total=1013120.0,
                source_truth_payload_sha256=tier1_truth["truthPayloadSha256"],
                evidence_uri=rel_uri,
                evidence_sha256=digest,
                reviewer_id="auditor_e2e_001",
                reviewed_at=(datetime.fromisoformat(t_obs.replace("Z", "+00:00")) + timedelta(minutes=5)).isoformat(),
                code_revision=c_rev,
            )
            saved_sidecar_path = review_store.save_review_artifact(review_artifact)
            self.assertTrue(saved_sidecar_path.is_file())

            # Verify database file is 100% byte-for-byte unchanged
            bytes_phase_b = db_path.read_bytes()
            hash_phase_b = hashlib.sha256(bytes_phase_b).hexdigest()
            self.assertEqual(bytes_phase_a, bytes_phase_b)
            self.assertEqual(hash_phase_a, hash_phase_b)

            # Phase B Scan: Effective truth resolves Tier 3 projection -> Formally Eligible!
            scan_b = scan_history_file(db_path, data_root=data_root)
            self.assertEqual(scan_b.record_count, 1)
            self.assertEqual(scan_b.history_admitted_count, 1)
            self.assertEqual(scan_b.formally_eligible_count, 1)
            self.assertEqual(scan_b.primary_rejection_reason_counts, ())


if __name__ == "__main__":
    unittest.main()
