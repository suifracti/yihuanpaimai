# -*- coding: utf-8 -*-
"""Unit and regression tests for Settlement Truth Review v1 and Tier 3 Projection.

Verifies:
1. External / packaged-style data-root location and evidence verification.
2. Confirmed review artifact generation and Tier 3 Truth Evidence projection.
3. Corrected review artifact preserves original machine value while projecting corrected truth.
4. Rejected review produces review artifact but strictly NO Tier 3 Truth projection.
5. Stable reviewer ID enforcement (no silent OS username fallback).
6. Deterministic reviewPayloadSha256 and content-addressed reviewId.
7. Terminal review non-overwritable constraint (fail closed on duplicate).
8. Canonical history database and source Tier 1 record byte-for-byte unchanged.
9. Tier 3 projection validity under frozen Settlement Truth Evidence validator.
10. Full eligibility probe on Schema 6 parent rejects ONLY RECORD_SCHEMA_VERSION_UNSUPPORTED.
11. Diagnostic probe on Schema 7 fixture passes all gates.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
CORE_DIR = ROOT_DIR / "core"
APP_DIR = ROOT_DIR / "app"
TOOLS_DIR = ROOT_DIR / "tools"
for p in (str(CORE_DIR), str(APP_DIR), str(TOOLS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from canonical_match_record import build_canonical_match_record_v7
from evidence_storage import save_evidence_png, verify_evidence_file
from runtime_revision import get_code_revision
from settlement_truth_holder import (
    build_settlement_truth_evidence_v1,
    build_truth_payload_sha256,
    validate_settlement_truth_evidence,
)
from settlement_truth_reviewer import (
    ReviewConflictError,
    ReviewStoreManager,
    build_settlement_truth_review_v1,
    project_tier3_truth_evidence,
    validate_settlement_truth_review,
)
from evaluation_eligibility import (
    EligibilityReason,
    build_duplicate_index,
    evaluate_record_eligibility,
)
from prediction_snapshot_holder import ActivePredictionSnapshotHolder


from live_shadow import get_live_dataset_revision


def run_js_solver(ctx: dict, records: list | None = None, options: dict | None = None) -> dict:
    records = records or []
    options = options or {}
    script = f"""
    const engine = require({json.dumps(str(CORE_DIR / "auction_engine_v06.js"))});
    const ctx = {json.dumps(ctx)};
    const records = {json.dumps(records)};
    const options = {json.dumps(options)};
    const res = engine.solveAuctionPipeline(ctx, records, options);
    console.log(JSON.stringify(res));
    """
    proc = subprocess.run(
        ["node"],
        input=script,
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout.strip())


class TestSettlementTruthReviewV1(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def _create_mock_tier1_record_and_png(self, tmp_dir: str, match_id: str, actual_total: float = 1013120.0):
        data_dir = Path(tmp_dir)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[10:50, 10:50] = [200, 100, 50]
        rel_uri, digest = save_evidence_png(img, match_id, data_dir=str(data_dir))

        observed_at = "2026-08-21T21:40:00.123456+08:00"
        truth_tier1 = build_settlement_truth_evidence_v1(
            match_id=match_id,
            actual_total=actual_total,
            settlement_observed_at=observed_at,
            truth_source="live_vision_stabilized_settlement",
            truth_confidence="medium",
            evidence_uri=rel_uri,
            evidence_sha256=digest,
            verification_method="vision_multiframe_stabilization_v1",
            verification_version="settlement-stabilization.v1",
            verifier_type="deterministic_verifier",
            verifier_id="rapidocr_stabilizer_v1",
        )

        record = {
            "id": match_id,
            "productVersion": "v0.65",
            "playedAt": "2026-08-21T21:35:00.000000+08:00",
            "timestamp": "2026-08-21T21:35:00.000000+08:00",
            "venue": "shanhu",
            "box": "实木宝箱",
            "clearingPrice": 800000,
            "actualTotal": actual_total,
            "realizedProfit": 213120,
            "settlement": {
                "status": "verified",
                "verified": True,
                "clearingPrice": 800000,
                "actualTotal": actual_total,
                "realizedProfit": 213120,
                "truthEvidence": truth_tier1,
            },
        }

        db_path = data_dir / "异环拍卖数据.json"
        db_path.write_text(json.dumps([record], ensure_ascii=False, indent=2), encoding="utf-8")
        return record, truth_tier1, db_path

    def test_external_packaged_data_root_resolution_and_png_verification(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            match_id = "match_external_001"
            record, tier1, db_path = self._create_mock_tier1_record_and_png(tmp_dir, match_id)

            store = ReviewStoreManager(data_root=tmp_dir)
            self.assertEqual(store.data_root, Path(tmp_dir).resolve())

            rel_uri = tier1["evidenceReferences"][0]["uri"]
            ev_sha = tier1["evidenceReferences"][0]["sha256"]
            self.assertTrue(verify_evidence_file(rel_uri, ev_sha, data_dir=tmp_dir))

    def test_confirmed_review_artifact_creation_and_tier3_projection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            match_id = "match_confirm_001"
            record, tier1, db_path = self._create_mock_tier1_record_and_png(tmp_dir, match_id, actual_total=1013120)

            store = ReviewStoreManager(data_root=tmp_dir)
            source_sha = tier1["truthPayloadSha256"]
            rel_uri = tier1["evidenceReferences"][0]["uri"]
            ev_sha = tier1["evidenceReferences"][0]["sha256"]

            reviewed_at = "2026-08-21T22:20:00.000000+08:00"
            artifact = build_settlement_truth_review_v1(
                match_id=match_id,
                action="confirmed",
                original_actual_total=1013120,
                reviewed_actual_total=1013120,
                source_truth_payload_sha256=source_sha,
                evidence_uri=rel_uri,
                evidence_sha256=ev_sha,
                reviewer_id="reviewer_alice",
                reviewed_at=reviewed_at,
            )

            is_valid, reasons = validate_settlement_truth_review(artifact)
            self.assertTrue(is_valid, f"Review validation failed: {reasons}")
            self.assertEqual(artifact["reviewId"], artifact["reviewPayloadSha256"])

            saved_file = store.save_review_artifact(artifact)
            self.assertTrue(saved_file.is_file())
            self.assertEqual(saved_file.name, f"{artifact['reviewId']}.json")

            # Project Tier 3
            tier3 = project_tier3_truth_evidence(tier1, artifact, data_dir=tmp_dir)
            self.assertIsNotNone(tier3)
            self.assertEqual(tier3["schemaVersion"], "settlement-truth-evidence.v1")
            self.assertEqual(tier3["truthConfidence"], "high")
            self.assertEqual(tier3["truthSource"], "manual_confirmed_against_screenshot")
            self.assertEqual(tier3["actualTotal"], 1013120.0)
            self.assertEqual(tier3["settlementObservedAt"], tier1["settlementObservedAt"])
            self.assertEqual(tier3["verification"]["verifier"]["id"], "reviewer_alice")

            # Check under official truth validator
            is_truth_valid, truth_reasons = validate_settlement_truth_evidence(tier3, match_id=match_id, data_dir=tmp_dir)
            self.assertTrue(is_truth_valid, f"Projected Tier 3 truth failed: {truth_reasons}")

    def test_corrected_review_artifact_preserves_original_machine_value(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            match_id = "match_correct_001"
            # Machine got 81284, human corrects to 81234
            record, tier1, db_path = self._create_mock_tier1_record_and_png(tmp_dir, match_id, actual_total=81284)

            store = ReviewStoreManager(data_root=tmp_dir)
            source_sha = tier1["truthPayloadSha256"]
            rel_uri = tier1["evidenceReferences"][0]["uri"]
            ev_sha = tier1["evidenceReferences"][0]["sha256"]

            reviewed_at = "2026-08-21T22:20:00.000000+08:00"
            artifact = build_settlement_truth_review_v1(
                match_id=match_id,
                action="corrected",
                original_actual_total=81284,
                reviewed_actual_total=81234,
                source_truth_payload_sha256=source_sha,
                evidence_uri=rel_uri,
                evidence_sha256=ev_sha,
                reviewer_id="reviewer_bob",
                reviewed_at=reviewed_at,
            )

            self.assertEqual(artifact["originalActualTotal"], 81284.0)
            self.assertEqual(artifact["reviewedActualTotal"], 81234.0)
            self.assertEqual(artifact["action"], "corrected")

            saved_file = store.save_review_artifact(artifact)
            self.assertTrue(saved_file.is_file())

            # Tier 3 Projection uses corrected value
            tier3 = project_tier3_truth_evidence(tier1, artifact, data_dir=tmp_dir)
            self.assertIsNotNone(tier3)
            self.assertEqual(tier3["actualTotal"], 81234.0)
            self.assertEqual(tier3["truthConfidence"], "high")

            # Validate under official truth validator
            is_truth_valid, truth_reasons = validate_settlement_truth_evidence(tier3, match_id=match_id, data_dir=tmp_dir)
            self.assertTrue(is_truth_valid, f"Projected Tier 3 truth failed: {truth_reasons}")

    def test_rejected_review_does_not_generate_tier3_projection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            match_id = "match_reject_001"
            record, tier1, db_path = self._create_mock_tier1_record_and_png(tmp_dir, match_id, actual_total=500000)

            store = ReviewStoreManager(data_root=tmp_dir)
            source_sha = tier1["truthPayloadSha256"]
            rel_uri = tier1["evidenceReferences"][0]["uri"]
            ev_sha = tier1["evidenceReferences"][0]["sha256"]

            artifact = build_settlement_truth_review_v1(
                match_id=match_id,
                action="rejected",
                original_actual_total=500000,
                reviewed_actual_total=None,
                source_truth_payload_sha256=source_sha,
                evidence_uri=rel_uri,
                evidence_sha256=ev_sha,
                reviewer_id="reviewer_charlie",
                reviewed_at="2026-08-21T22:20:00.000000+08:00",
            )

            self.assertIsNone(artifact["reviewedActualTotal"])
            store.save_review_artifact(artifact)

            # Strictly returns None
            tier3 = project_tier3_truth_evidence(tier1, artifact, data_dir=tmp_dir)
            self.assertIsNone(tier3)

    def test_stable_reviewer_id_required(self):
        with self.assertRaises(ValueError):
            build_settlement_truth_review_v1(
                match_id="match_test",
                action="confirmed",
                original_actual_total=100,
                reviewed_actual_total=100,
                source_truth_payload_sha256="a" * 64,
                evidence_uri="evidence/test.png",
                evidence_sha256="b" * 64,
                reviewer_id="   ",  # Invalid
                reviewed_at="2026-08-21T22:20:00.000000+08:00",
            )

    def test_terminal_review_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            match_id = "match_dup_001"
            record, tier1, db_path = self._create_mock_tier1_record_and_png(tmp_dir, match_id, actual_total=100000)

            store = ReviewStoreManager(data_root=tmp_dir)
            source_sha = tier1["truthPayloadSha256"]
            rel_uri = tier1["evidenceReferences"][0]["uri"]
            ev_sha = tier1["evidenceReferences"][0]["sha256"]

            artifact1 = build_settlement_truth_review_v1(
                match_id=match_id,
                action="confirmed",
                original_actual_total=100000,
                reviewed_actual_total=100000,
                source_truth_payload_sha256=source_sha,
                evidence_uri=rel_uri,
                evidence_sha256=ev_sha,
                reviewer_id="reviewer_1",
                reviewed_at="2026-08-21T22:20:00.000000+08:00",
            )
            store.save_review_artifact(artifact1)

            # Second attempt must fail closed
            artifact2 = build_settlement_truth_review_v1(
                match_id=match_id,
                action="corrected",
                original_actual_total=100000,
                reviewed_actual_total=105000,
                source_truth_payload_sha256=source_sha,
                evidence_uri=rel_uri,
                evidence_sha256=ev_sha,
                reviewer_id="reviewer_2",
                reviewed_at="2026-08-21T22:21:00.000000+08:00",
            )
            with self.assertRaises(ReviewConflictError):
                store.save_review_artifact(artifact2)

    def test_canonical_database_and_source_tier1_byte_for_byte_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            match_id = "match_unchanged_001"
            record, tier1, db_path = self._create_mock_tier1_record_and_png(tmp_dir, match_id, actual_total=200000)

            initial_bytes = db_path.read_bytes()
            initial_hash = hashlib.sha256(initial_bytes).hexdigest()

            # Execute CLI confirm command
            cmd = [
                sys.executable,
                str(TOOLS_DIR / "review_settlement_truth.py"),
                "--database",
                str(db_path),
                "--reviewer-id",
                "test_reviewer_suite",
                "confirm",
                match_id,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
            self.assertIn("Review artifact saved", res.stdout)

            # Assert database file is byte-for-byte 100% UNCHANGED
            after_bytes = db_path.read_bytes()
            after_hash = hashlib.sha256(after_bytes).hexdigest()
            self.assertEqual(after_hash, initial_hash)
            self.assertEqual(after_bytes, initial_bytes)

    def test_schema6_parent_full_eligibility_probe_rejects_only_unsupported_schema(self):
        """Regression probe verifying Schema 6 parent + Prediction v1 + Tier 3 Truth.

        Must pass all other gates (Prediction, Truth, Temporal cutoff, Forecast target, Duplicate)
        and fail closed ONLY on RECORD_SCHEMA_VERSION_UNSUPPORTED.
        """
        d_rev = get_live_dataset_revision()
        c_rev = get_code_revision(force_refresh=True)
        match_id = "test_match_full_probe_001"
        ctx = {
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
                "shadowWhole": {"p20": 380000, "p50": 420000, "p80": 460000},
            },
        }
        res_js = run_js_solver(ctx, options={"datasetRevision": d_rev, "codeRevision": c_rev})
        pred_snap = res_js["predictionSnapshot"]

        t_solve = pred_snap["solvedAt"]
        dt_solve = datetime.fromisoformat(t_solve.replace("Z", "+00:00"))
        dt_settle = dt_solve + timedelta(minutes=5)
        t_settle = dt_settle.isoformat()

        truth_tier3 = build_settlement_truth_evidence_v1(
            match_id=match_id,
            actual_total=420000,
            settlement_observed_at=t_settle,
            truth_source="manual_confirmed_against_screenshot",
            truth_confidence="high",
            evidence_uri="evidence/settlement/test_match_full_probe_001_abc.png",
            evidence_sha256="a" * 64,
            verification_method="human_screenshot_audit_v1",
            verification_version="settlement-truth-review.v1",
            verifier_type="reviewer",
            verifier_id="reviewer_alice",
        )

        rec_schema6 = {
            "id": match_id,
            "productVersion": "v0.65",
            "playedAt": t_solve,
            "timestamp": t_solve,
            "settlement": {
                "status": "verified",
                "verified": True,
                "actualTotal": 420000,
                "truthEvidence": truth_tier3,
            },
            "predictionSnapshot": pred_snap,
        }

        dup_idx6 = build_duplicate_index([rec_schema6])
        eval_res6 = evaluate_record_eligibility(rec_schema6, dup_idx6)
        self.assertFalse(eval_res6.formally_eligible)
        self.assertEqual(list(eval_res6.reasons), [EligibilityReason.RECORD_SCHEMA_VERSION_UNSUPPORTED])
        self.assertEqual(eval_res6.primary_reason, EligibilityReason.RECORD_SCHEMA_VERSION_UNSUPPORTED)

    def test_schema7_diagnostic_probe_passes_all_gates(self):
        """Diagnostic-only probe verifying that with schemaVersion=7, all gates are satisfied.

        NOTE: This test is a diagnostic proof that our Prediction Snapshot v1 + Tier 3 Truth Evidence
        contracts are 100% complete and valid under formal evaluation rules.
        It is NOT a Canonical v7 migration (which is a separate future cut).
        """
        d_rev = get_live_dataset_revision()
        c_rev = get_code_revision(force_refresh=True)
        match_id = "test_match_schema7_diag_001"
        ctx = {
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
                "shadowWhole": {"p20": 380000, "p50": 420000, "p80": 460000},
            },
        }
        res_js = run_js_solver(ctx, options={"datasetRevision": d_rev, "codeRevision": c_rev})
        pred_snap = res_js["predictionSnapshot"]

        t_solve = pred_snap["solvedAt"]
        dt_solve = datetime.fromisoformat(t_solve.replace("Z", "+00:00"))
        dt_settle = dt_solve + timedelta(minutes=5)
        t_settle = dt_settle.isoformat()

        truth_tier3 = build_settlement_truth_evidence_v1(
            match_id=match_id,
            actual_total=420000,
            settlement_observed_at=t_settle,
            truth_source="manual_confirmed_against_screenshot",
            truth_confidence="high",
            evidence_uri="evidence/settlement/test_match_schema7_diag_001_abc.png",
            evidence_sha256="a" * 64,
            verification_method="human_screenshot_audit_v1",
            verification_version="settlement-truth-review.v1",
            verifier_type="reviewer",
            verifier_id="reviewer_alice",
        )

        rec_schema7 = build_canonical_match_record_v7(
            match_id=match_id,
            played_at=t_solve,
            lifecycle_status="FINALIZED",
            source="vision-auto-archiver",
            environment={
                "venueTier": "zhongji",
                "venue": "shanhu",
                "box": "实木宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
            },
            public_intel={"q": 15, "totalItems": 66, "totalGrid": 84},
            qualities={
                "purple": {"count": 5, "avg": 2007, "knownItems": []},
                "gold": {"count": 4, "avg": 33538, "knownItems": []},
            },
            settlement={
                "status": "verified",
                "verified": True,
                "clearingPrice": 300000.0,
                "actualTotal": 420000.0,
                "realizedProfit": 120000.0,
                "acquired": True,
                "winner": "玩家本人",
                "settlementItems": [],
                "truthEvidence": truth_tier3,
            },
            prediction_snapshot=pred_snap,
        )

        dup_idx7 = build_duplicate_index([rec_schema7])
        eval_res7 = evaluate_record_eligibility(rec_schema7, dup_idx7)
        self.assertTrue(eval_res7.formally_eligible)
        self.assertEqual(len(eval_res7.reasons), 0)
        self.assertIsNone(eval_res7.primary_reason)

    def test_cli_correct_and_reject_commands(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            match_id_corr = "match_cli_correct_001"
            _, _, db_path = self._create_mock_tier1_record_and_png(tmp_dir, match_id_corr, actual_total=80000)

            # Test CLI correct command
            cmd_corr = [
                sys.executable,
                str(TOOLS_DIR / "review_settlement_truth.py"),
                "--database",
                str(db_path),
                "--reviewer-id",
                "reviewer_tester_1",
                "correct",
                match_id_corr,
                "85000",
            ]
            res_corr = subprocess.run(cmd_corr, capture_output=True, text=True, encoding="utf-8", check=True)
            self.assertIn("Review artifact saved", res_corr.stdout)
            self.assertIn("Reviewed Total:  85000.0", res_corr.stdout)
            self.assertIn("Tier 3 Truth Evidence Projection Generated", res_corr.stdout)

            # Verify saved file in review store
            store = ReviewStoreManager(data_root=tmp_dir)
            review_dir = store.get_review_dir(match_id_corr)
            saved_files = list(review_dir.glob("*.json"))
            self.assertEqual(len(saved_files), 1)
            rev_data = json.loads(saved_files[0].read_text(encoding="utf-8"))
            self.assertEqual(rev_data["action"], "corrected")
            self.assertEqual(rev_data["originalActualTotal"], 80000.0)
            self.assertEqual(rev_data["reviewedActualTotal"], 85000.0)

            # Test CLI reject command on second match
            match_id_rej = "match_cli_reject_001"
            self._create_mock_tier1_record_and_png(tmp_dir, match_id_rej, actual_total=90000)
            cmd_rej = [
                sys.executable,
                str(TOOLS_DIR / "review_settlement_truth.py"),
                "--database",
                str(db_path),
                "--reviewer-id",
                "reviewer_tester_2",
                "reject",
                match_id_rej,
            ]
            res_rej = subprocess.run(cmd_rej, capture_output=True, text=True, encoding="utf-8", check=True)
            self.assertIn("Review artifact saved", res_rej.stdout)
            self.assertIn("Tier 3 Truth Evidence Projection is UNAVAILABLE", res_rej.stdout)

    def test_cli_list_command(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            match_id = "match_list_001"
            _, _, db_path = self._create_mock_tier1_record_and_png(tmp_dir, match_id, actual_total=123456)

            cmd_list = [
                sys.executable,
                str(TOOLS_DIR / "review_settlement_truth.py"),
                "--database",
                str(db_path),
                "list",
            ]
            res = subprocess.run(cmd_list, capture_output=True, text=True, encoding="utf-8", check=True)
            self.assertIn("match_list_001", res.stdout)
            self.assertIn("123456", res.stdout)
            self.assertIn("Found 1 record(s)", res.stdout)

    def test_corrupted_png_causes_review_to_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            match_id = "match_corrupt_png_001"
            record, tier1, db_path = self._create_mock_tier1_record_and_png(tmp_dir, match_id, actual_total=200000)

            # Corrupt the PNG file on disk
            rel_uri = tier1["evidenceReferences"][0]["uri"]
            png_path = Path(tmp_dir) / rel_uri.replace("/", os.sep)
            png_path.write_bytes(b"corrupted_png_bytes")

            cmd = [
                sys.executable,
                str(TOOLS_DIR / "review_settlement_truth.py"),
                "--database",
                str(db_path),
                "--reviewer-id",
                "reviewer_fail",
                "confirm",
                match_id,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(res.returncode, 1)
            self.assertIn("failed contract/disk validation", res.stdout)


if __name__ == "__main__":
    unittest.main()
