# -*- coding: utf-8 -*-
"""Unit and regression tests for Settlement Truth Evidence Persistence v1.

Verifies:
1. Truth Tier qualification: Tier 1 (machine_stabilized, medium confidence) fails closed on formal high-confidence gate; Tier 3 (audited screenshot) passes; Tier 2 (pure numbers) fails closed.
2. Lossless PNG evidence encoding, exact byte SHA-256 calculation, atomic write, and 1:1 disk byte verification.
3. settlementObservedAt strictly uses the exact capture timestamp of the 5th stabilizing frame.
4. ActiveSettlementTruthHolder strict matchId binding and lifecycle isolation.
5. AutoArchiver full validator gate: persists valid truth, rejects tampered/corrupted evidence, and never fabricates truth.
6. Truth persistence is independent of prediction existence.
7. Parent record schema version is preserved (not bumped to 7).
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
CORE_DIR = ROOT_DIR / "core"
APP_DIR = ROOT_DIR / "app"
for p in (str(CORE_DIR), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from evidence_storage import get_canonical_data_dir, get_evidence_dir, save_evidence_png, verify_evidence_file
from settlement_truth_holder import (
    ACTIVE_SETTLEMENT_TRUTH_HOLDER,
    build_settlement_truth_evidence_v1,
    build_truth_payload_sha256,
    validate_settlement_truth_evidence,
)
from auto_archiver import AutoArchiver
from vision_pipeline import NTEVisionPipeline
from evaluation_eligibility import EligibilityReason, _validate_truth_evidence
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from version import APP_PRODUCT_VERSION


class TestSettlementTruthEvidencePersistenceV1(unittest.TestCase):
    def setUp(self):
        ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()
        self._v2_tmp = tempfile.TemporaryDirectory()
        self._v2_store = SettlementEvidenceStoreV2(Path(self._v2_tmp.name).resolve())

    def tearDown(self):
        ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()
        self._v2_tmp.cleanup()

    def test_evidence_storage_lossless_png_and_hash_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a 200x200 synthetic BGR image with distinct patterns
            img = np.zeros((200, 200, 3), dtype=np.uint8)
            img[10:50, 10:50] = [255, 128, 0]
            img[60:120, 60:120] = [0, 255, 128]

            rel_uri, digest = save_evidence_png(img, "match_storage_test", data_dir=tmp_dir)
            self.assertTrue(rel_uri.startswith("evidence/settlement/match_storage_test_"))
            self.assertTrue(rel_uri.endswith(".png"))
            self.assertEqual(len(digest), 64)

            # Re-read raw bytes from disk and assert byte-level hash matches
            full_path = Path(tmp_dir) / rel_uri
            self.assertTrue(full_path.is_file())
            disk_bytes = full_path.read_bytes()
            computed_sha256 = hashlib.sha256(disk_bytes).hexdigest()
            self.assertEqual(computed_sha256, digest)

            # verify_evidence_file helper
            self.assertTrue(verify_evidence_file(rel_uri, digest, data_dir=tmp_dir))
            self.assertFalse(verify_evidence_file(rel_uri, "0" * 64, data_dir=tmp_dir))
            self.assertFalse(verify_evidence_file("evidence/settlement/non_existent.png", digest, data_dir=tmp_dir))

    def test_tier1_machine_stabilized_truth_evidence_structure_and_medium_confidence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            rel_uri, digest = save_evidence_png(img, "match_tier1", data_dir=tmp_dir)

            captured_at = "2026-08-21T21:40:00.000000+08:00"
            evidence = build_settlement_truth_evidence_v1(
                match_id="match_tier1",
                actual_total=1013120,
                settlement_observed_at=captured_at,
                truth_source="live_vision_stabilized_settlement",
                truth_confidence="medium",
                evidence_uri=rel_uri,
                evidence_sha256=digest,
                verification_method="vision_multiframe_stabilization_v1",
                verification_version="settlement-stabilization.v1",
                verifier_type="deterministic_verifier",
                verifier_id="rapidocr_stabilizer_v1",
            )

            # 1. Valid according to SettlementTruthHolder validator
            is_valid, reasons = validate_settlement_truth_evidence(evidence, match_id="match_tier1", data_dir=tmp_dir)
            self.assertTrue(is_valid, f"Validation failed with reasons: {reasons}")

            # 2. Inspected by Evaluation Eligibility Gate
            mock_record = {
                "id": "match_tier1",
                "settlement": {
                    "status": "verified",
                    "verified": True,
                    "actualTotal": 1013120,
                    "truthEvidence": evidence,
                },
            }
            gate_reasons, _ = _validate_truth_evidence(mock_record, target_kind="full_actual")
            # Must strictly fail closed because truthConfidence is medium, NOT high
            self.assertIn(EligibilityReason.TRUTH_CONFIDENCE_NOT_HIGH, gate_reasons)

    def test_tier3_manual_confirmed_against_screenshot_passes_truth_gate(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            rel_uri, digest = save_evidence_png(img, "match_tier3", data_dir=tmp_dir)

            captured_at = "2026-08-21T21:40:00.000000+08:00"
            evidence = build_settlement_truth_evidence_v1(
                match_id="match_tier3",
                actual_total=1013120,
                settlement_observed_at=captured_at,
                truth_source="manual_operator_entry",
                truth_confidence="high",
                evidence_uri=rel_uri,
                evidence_sha256=digest,
                verification_method="human_screenshot_audit_v1",
                verification_version="1.0",
                verifier_type="reviewer",
                verifier_id="operator",
            )

            # Valid in internal validator
            is_valid, reasons = validate_settlement_truth_evidence(evidence, match_id="match_tier3", data_dir=tmp_dir)
            self.assertTrue(is_valid, f"Validation failed with reasons: {reasons}")

            # Evaluation eligibility check
            mock_record = {
                "id": "match_tier3",
                "settlement": {
                    "status": "verified",
                    "verified": True,
                    "actualTotal": 1013120,
                    "truthEvidence": evidence,
                },
            }
            gate_reasons, meta = _validate_truth_evidence(mock_record, target_kind="full_actual")
            self.assertEqual(gate_reasons, [], f"Expected no gate rejection, got: {gate_reasons}")
            self.assertEqual(meta["schemaVersion"], "settlement-truth-evidence.v1")

    def test_tier2_manual_entry_without_screenshot_fails_closed(self):
        captured_at = "2026-08-21T21:40:00.000000+08:00"
        evidence = build_settlement_truth_evidence_v1(
            match_id="match_tier2",
            actual_total=500000,
            settlement_observed_at=captured_at,
            truth_source="manual_operator_entry",
            truth_confidence="medium",
            evidence_uri=None,
            evidence_sha256=None,
            verification_method="manual_unverified_entry_v1",
            verification_version="1.0",
            verifier_type="reviewer",
            verifier_id="operator",
        )

        mock_record = {
            "id": "match_tier2",
            "settlement": {
                "status": "verified",
                "verified": True,
                "actualTotal": 500000,
                "truthEvidence": evidence,
            },
        }
        gate_reasons, _ = _validate_truth_evidence(mock_record, target_kind="full_actual")
        self.assertIn(EligibilityReason.TRUTH_CONFIDENCE_NOT_HIGH, gate_reasons)
        self.assertIn(EligibilityReason.TRUTH_EVIDENCE_REFERENCE_MISSING, gate_reasons)

    def test_settlement_observed_at_exact_capture_timestamp_and_fail_closed_if_missing(self):
        pipe = NTEVisionPipeline()
        pipe._settlement_evidence_store = self._v2_store
        pipe.current_context["id"] = "match_time_test"
        pipe.current_context["matchId"] = "match_time_test"

        settle_data = {
            "isSettlement": True,
            "clearingPrice": 100000,
            "actualTotal": 150000,
            "profit": 50000,
        }
        dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

        # 1. Missing captured_at -> must NOT create Truth Evidence (fails closed)
        for _ in range(5):
            pipe._stabilize_settlement(settle_data, frame=dummy_frame, captured_at=None)
        self.assertTrue(pipe.current_context.get("settlementReady"))
        self.assertIsNone(ACTIVE_SETTLEMENT_TRUTH_HOLDER.get_truth_for_match("match_time_test"))

        # Reset
        pipe.clear_match_trunk()
        ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()

        # 2. Explicit captured_at -> freezes Truth Evidence with EXACT timestamp
        target_timestamp = "2026-08-21T21:44:12.345678+08:00"
        pipe.current_context["id"] = "match_time_test"
        pipe.current_context["matchId"] = "match_time_test"
        for _ in range(5):
            pipe._stabilize_settlement(settle_data, frame=dummy_frame, captured_at=target_timestamp)

        self.assertTrue(pipe.current_context.get("settlementReady"))
        snap = ACTIVE_SETTLEMENT_TRUTH_HOLDER.get_truth_for_match("match_time_test")
        self.assertIsNotNone(snap)
        self.assertEqual(snap["settlementObservedAt"], target_timestamp)
        self.assertEqual(snap["matchId"], "match_time_test")

    def test_truth_holder_match_id_binding_and_cross_match_isolation(self):
        evidence_a = build_settlement_truth_evidence_v1(
            match_id="match_AAA",
            actual_total=100000,
            settlement_observed_at="2026-08-21T21:40:00+08:00",
            truth_source="test",
            truth_confidence="medium",
            evidence_uri="evidence/settlement/dummy.png",
            evidence_sha256="a" * 64,
        )

        ACTIVE_SETTLEMENT_TRUTH_HOLDER.set_truth("match_AAA", evidence_a)
        self.assertIsNotNone(ACTIVE_SETTLEMENT_TRUTH_HOLDER.get_truth_for_match("match_AAA"))
        # Cross-match access fails
        self.assertIsNone(ACTIVE_SETTLEMENT_TRUTH_HOLDER.get_truth_for_match("match_BBB"))

        ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()
        self.assertIsNone(ACTIVE_SETTLEMENT_TRUTH_HOLDER.get_truth_for_match("match_AAA"))

    def test_auto_archiver_persists_truth_and_fails_closed_on_corruption(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_root = os.environ.get("YIHUAN_DATA_ROOT")
            os.environ["YIHUAN_DATA_ROOT"] = tmp_dir
            try:
                db_path = os.path.join(tmp_dir, "test_data.json")
                archiver = AutoArchiver(db_paths=[db_path])

                img = np.zeros((50, 50, 3), dtype=np.uint8)
                rel_uri, digest = save_evidence_png(img, "match_arch_test", data_dir=tmp_dir)

                valid_truth = build_settlement_truth_evidence_v1(
                    match_id="match_arch_test",
                    actual_total=150000,
                    settlement_observed_at="2026-08-21T21:40:00+08:00",
                    truth_source="live_vision_stabilized_settlement",
                    truth_confidence="medium",
                    evidence_uri=rel_uri,
                    evidence_sha256=digest,
                )

                ACTIVE_SETTLEMENT_TRUTH_HOLDER.set_truth("match_arch_test", valid_truth)

                ctx = {
                    "id": "match_arch_test",
                    "matchId": "match_arch_test",
                    "settlementReady": True,
                    "settlementData": {"isSettlement": True, "clearingPrice": 100000, "actualTotal": 150000, "profit": 50000},
                }
                record = archiver.archive_match(ctx)
                self.assertIsNotNone(record)
                self.assertIn("settlement", record)
                self.assertIn("truthEvidence", record["settlement"])
                self.assertEqual(record["settlement"]["truthEvidence"]["matchId"], "match_arch_test")

                # Holder must be cleared after archiving
                self.assertIsNone(ACTIVE_SETTLEMENT_TRUTH_HOLDER.get_truth_for_match("match_arch_test"))

                # Test corrupted truth (e.g. wrong digest) fails closed:
                corrupted_truth = dict(valid_truth)
                corrupted_truth["matchId"] = "match_corrupt"
                corrupted_truth["evidenceReferences"] = [{"uri": rel_uri, "sha256": "f" * 64}]
                corrupted_truth["truthPayloadSha256"] = build_truth_payload_sha256(
                    match_id="match_corrupt",
                    actual_total=160000,
                    settlement_observed_at="2026-08-21T21:40:00+08:00",
                    truth_source="live_vision_stabilized_settlement",
                )
                # Register in holder manually
                ACTIVE_SETTLEMENT_TRUTH_HOLDER._active_match_id = "match_corrupt"
                ACTIVE_SETTLEMENT_TRUTH_HOLDER._truth_evidence = corrupted_truth

                ctx_corrupt = {
                    "id": "match_corrupt",
                    "matchId": "match_corrupt",
                    "settlementReady": True,
                    "settlementData": {"isSettlement": True, "clearingPrice": 110000, "actualTotal": 160000, "profit": 50000},
                }
                rec_corrupt = archiver.archive_match(ctx_corrupt)
                self.assertIsNotNone(rec_corrupt)
                # Fails closed: truthEvidence is omitted
                self.assertNotIn("truthEvidence", rec_corrupt["settlement"])
            finally:
                if old_root is not None:
                    os.environ["YIHUAN_DATA_ROOT"] = old_root
                else:
                    os.environ.pop("YIHUAN_DATA_ROOT", None)

    def test_truth_persistence_independent_of_prediction(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_root = os.environ.get("YIHUAN_DATA_ROOT")
            os.environ["YIHUAN_DATA_ROOT"] = tmp_dir
            try:
                db_path = os.path.join(tmp_dir, "test_data.json")
                archiver = AutoArchiver(db_paths=[db_path])

                img = np.zeros((50, 50, 3), dtype=np.uint8)
                rel_uri, digest = save_evidence_png(img, "match_no_pred", data_dir=tmp_dir)

                valid_truth = build_settlement_truth_evidence_v1(
                    match_id="match_no_pred",
                    actual_total=200000,
                    settlement_observed_at="2026-08-21T21:40:00+08:00",
                    truth_source="live_vision_stabilized_settlement",
                    truth_confidence="medium",
                    evidence_uri=rel_uri,
                    evidence_sha256=digest,
                )
                ACTIVE_SETTLEMENT_TRUTH_HOLDER.set_truth("match_no_pred", valid_truth)

                # No predictionSnapshot in ctx
                ctx = {
                    "id": "match_no_pred",
                    "matchId": "match_no_pred",
                    "predictionSnapshot": None,
                    "frozenPrediction": None,
                    "settlementReady": True,
                    "settlementData": {"isSettlement": True, "clearingPrice": 120000, "actualTotal": 200000, "profit": 80000},
                }
                record = archiver.archive_match(ctx)
                self.assertIsNotNone(record)
                self.assertNotIn("predictionSnapshot", record)
                self.assertIn("settlement", record)
                self.assertIn("truthEvidence", record["settlement"])
                self.assertEqual(record["settlement"]["truthEvidence"]["actualTotal"], 200000)
            finally:
                if old_root is not None:
                    os.environ["YIHUAN_DATA_ROOT"] = old_root
                else:
                    os.environ.pop("YIHUAN_DATA_ROOT", None)

    def test_parent_record_schema_preserved(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test_data.json")
            archiver = AutoArchiver(db_paths=[db_path])

            ctx = {
                "id": "match_schema_test",
                "matchId": "match_schema_test",
                "settlementReady": True,
                "winner": "秋星祭02",
                "settlementData": {"isSettlement": True, "clearingPrice": 100000, "actualTotal": 150000, "profit": 50000},
            }
            record = archiver.archive_match(ctx)
            self.assertIsNotNone(record)
            self.assertEqual(record["productVersion"], APP_PRODUCT_VERSION)
            self.assertEqual(record.get("schemaVersion"), 7)
            self.assertEqual(record.get("lifecycleStatus"), "FINALIZED")

    def test_evidence_canonical_data_dir_resolution(self):
        # Evidence must live under the RuntimeDataRoot, never the repo root.
        # In dev (non-frozen) it resolves to the runtime data root and respects
        # the YIHUAN_DATA_ROOT override.
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.environ["YIHUAN_DATA_ROOT"] = tmp_dir
            try:
                data_dir = get_canonical_data_dir()
                self.assertEqual(data_dir, Path(tmp_dir).resolve())
                ev_dir = get_evidence_dir("settlement")
                self.assertEqual(ev_dir, data_dir / "evidence" / "settlement")
                self.assertTrue(ev_dir.is_dir())
            finally:
                os.environ.pop("YIHUAN_DATA_ROOT", None)

    def test_packaged_exe_evidence_storage_and_hash_roundtrip_if_built(self):
        exe_path = ROOT_DIR / "dist" / "异环拍卖助手" / "异环拍卖助手.exe"
        if not exe_path.is_file():
            self.skipTest("Packaged executable not found in dist/")

        import subprocess
        # 1. Test packaged revision
        rev_proc = subprocess.run([str(exe_path), "--print-code-revision"], capture_output=True, text=True, check=True)
        self.assertTrue(len(rev_proc.stdout.strip()) > 0)

        # 2. Test packaged evidence storage real path
        smoke_proc = subprocess.run([str(exe_path), "--smoke-evidence-storage"], capture_output=True, text=True)
        self.assertEqual(smoke_proc.returncode, 0, f"Packaged smoke failed: {smoke_proc.stderr}")
        data = json.loads(smoke_proc.stdout.strip())
        self.assertTrue(data.get("frozen"), "Expected packaged execution to report frozen=True")
        self.assertTrue(data.get("reReadVerified"), "Expected packaged evidence to re-read and verify hash")
        self.assertEqual(data.get("sha256"), data.get("diskSha256"))
        self.assertTrue(data.get("verifyEvidenceFile"))
        self.assertTrue(data.get("relativeUri").startswith("evidence/settlement/packaged_smoke_probe_"))

    def test_phase3_auto_archiver_truth_evidence_canonical_root_and_real_evidence(self):
        """Phase 3 targeted test (AC1 - AC5):
        AC1: AutoArchiver truth evidence validation data root = runtime_data_paths().root.
        AC2: Real settlement PNG in canonical root passes disk existence / sha256 verification.
        AC3: Old buggy history/ prefix is proven to trigger TRUTH_EVIDENCE_DISK_FILE_CORRUPTED_OR_MISSING.
        AC4: Actual AutoArchiver.archive_match call chain uses canonical root and successfully attaches settlement.truthEvidence.
        AC5: Missing/corrupt evidence continues to fail-closed.
        """
        from runtime_data import runtime_data_paths

        real_evidence_rel = "evidence/settlement/draft_cedfd5dc812144a6b6b17a064a3db511_a60d61c429f0490f.png"
        real_match_id = "draft_cedfd5dc812144a6b6b17a064a3db511"
        real_sha256 = "a60d61c429f0490fd20f5bfa177d24a7929ad25ffb1ec519a3f1abba242bf035"

        uat_root = (ROOT_DIR / "build" / "uat_4ae5fbb_human" / "data-root").resolve()
        if not (uat_root / real_evidence_rel).is_file():
            self.skipTest(f"Real evidence file not found at {uat_root / real_evidence_rel}")

        old_root = os.environ.get("YIHUAN_DATA_ROOT")
        os.environ["YIHUAN_DATA_ROOT"] = str(uat_root)
        try:
            # AC1 & AC2: Real evidence verification passes with runtime_data_paths().root
            canonical_root = runtime_data_paths().root
            self.assertEqual(canonical_root, uat_root)
            self.assertTrue(verify_evidence_file(real_evidence_rel, real_sha256, data_dir=canonical_root))

            truth_evidence = build_settlement_truth_evidence_v1(
                match_id=real_match_id,
                actual_total=322236,
                settlement_observed_at="2026-09-02T16:15:14+08:00",
                truth_source="live_vision_stabilized_settlement",
                truth_confidence="medium",
                evidence_uri=real_evidence_rel,
                evidence_sha256=real_sha256,
            )

            # AC3: Contrast with old buggy logic (dirname of history db path -> data-root/history)
            old_buggy_data_dir = str(uat_root / "history")
            is_valid_old, reasons_old = validate_settlement_truth_evidence(
                truth_evidence,
                match_id=real_match_id,
                data_dir=old_buggy_data_dir,
                check_disk_bytes=True,
            )
            self.assertFalse(is_valid_old)
            self.assertIn("TRUTH_EVIDENCE_DISK_FILE_CORRUPTED_OR_MISSING", reasons_old)

            # AC4: Actual AutoArchiver.archive_match uses canonical root and attaches settlement.truthEvidence
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_history = os.path.join(tmp_dir, "test_data.json")
                archiver = AutoArchiver(db_paths=[tmp_history])
                ACTIVE_SETTLEMENT_TRUTH_HOLDER.set_truth(real_match_id, truth_evidence)

                ctx = {
                    "id": real_match_id,
                    "matchId": real_match_id,
                    "settlementReady": True,
                    "settlementData": {
                        "isSettlement": True,
                        "clearingPrice": 400000,
                        "actualTotal": 322236,
                        "profit": -77764,
                    },
                }
                record = archiver.archive_match(ctx)
                self.assertIsNotNone(record)
                self.assertIn("settlement", record)
                self.assertIn("truthEvidence", record["settlement"])
                attached = record["settlement"]["truthEvidence"]
                self.assertEqual(attached["matchId"], real_match_id)
                self.assertEqual(attached["evidenceReferences"][0]["uri"], real_evidence_rel)
                self.assertEqual(attached["evidenceReferences"][0]["sha256"], real_sha256)

            # AC5: missing/corrupt evidence continues to fail-closed
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_history = os.path.join(tmp_dir, "test_data.json")
                archiver_corrupt = AutoArchiver(db_paths=[tmp_history])

                # 5a. Corrupt sha256
                corrupt_truth = dict(truth_evidence)
                corrupt_truth["matchId"] = "draft_corrupt_test"
                corrupt_truth["evidenceReferences"] = [{"uri": real_evidence_rel, "sha256": "0" * 64}]
                corrupt_truth["truthPayloadSha256"] = build_truth_payload_sha256(
                    match_id="draft_corrupt_test",
                    actual_total=322236,
                    settlement_observed_at="2026-09-02T16:15:14+08:00",
                    truth_source="live_vision_stabilized_settlement",
                )
                ACTIVE_SETTLEMENT_TRUTH_HOLDER.set_truth("draft_corrupt_test", corrupt_truth)
                ctx_corrupt = {
                    "id": "draft_corrupt_test",
                    "matchId": "draft_corrupt_test",
                    "settlementReady": True,
                    "settlementData": {"isSettlement": True, "clearingPrice": 400000, "actualTotal": 322236, "profit": -77764},
                }
                rec_corrupt = archiver_corrupt.archive_match(ctx_corrupt)
                self.assertIsNotNone(rec_corrupt)
                self.assertNotIn("truthEvidence", rec_corrupt["settlement"])

                # 5b. Missing file (fresh archiver to prevent debounce on identical metrics)
                archiver_missing = AutoArchiver(db_paths=[tmp_history])
                missing_truth = dict(truth_evidence)
                missing_truth["matchId"] = "draft_missing_test"
                missing_truth["evidenceReferences"] = [{"uri": "evidence/settlement/nonexistent.png", "sha256": real_sha256}]
                missing_truth["truthPayloadSha256"] = build_truth_payload_sha256(
                    match_id="draft_missing_test",
                    actual_total=322236,
                    settlement_observed_at="2026-09-02T16:15:14+08:00",
                    truth_source="live_vision_stabilized_settlement",
                )
                ACTIVE_SETTLEMENT_TRUTH_HOLDER.set_truth("draft_missing_test", missing_truth)
                ctx_missing = {
                    "id": "draft_missing_test",
                    "matchId": "draft_missing_test",
                    "settlementReady": True,
                    "settlementData": {"isSettlement": True, "clearingPrice": 400000, "actualTotal": 322236, "profit": -77764},
                }
                rec_missing = archiver_missing.archive_match(ctx_missing)
                self.assertIsNotNone(rec_missing)
                self.assertNotIn("truthEvidence", rec_missing["settlement"])
        finally:
            if old_root is not None:
                os.environ["YIHUAN_DATA_ROOT"] = old_root
            else:
                os.environ.pop("YIHUAN_DATA_ROOT", None)


if __name__ == "__main__":
    unittest.main()
