# -*- coding: utf-8 -*-
"""Unit tests for Prediction Snapshot Persistence v1.

Verifies:
1. Pure JS solveAuctionPipeline produces valid prediction-snapshot.v1 objects.
2. Exact JS -> Python SHA-256 hash parity and forbidden field exclusion.
3. InformationMode to forecast target/scope semantic mapping.
4. Content-addressed predictionId uniqueness and format.
5. Exactly-one ActivePredictionSnapshotHolder bound to matchId.
6. Cross-match isolation (Match A snapshot -> reset -> Match B without snapshot -> archive B => B has no snapshot).
7. AutoArchiver fail-closed validation and non-reconstruction.
8. Parent record schema preservation.
9. Dynamic codeRevision resolution with frozen package vs dev runtime provenance guarantees.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "app"
CORE_DIR = ROOT_DIR / "core"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(CORE_DIR))

from auto_archiver import AutoArchiver
from evaluation_eligibility import (
    PREDICTION_SNAPSHOT_SCHEMA_VERSION,
    EligibilityReason,
    build_input_sha256,
    validate_prediction_snapshot,
)
from live_shadow import get_live_dataset_revision, load_history_snapshot, reset_live_shadow_state
from prediction_snapshot_holder import ACTIVE_SNAPSHOT_HOLDER, ActivePredictionSnapshotHolder
from runtime_revision import get_code_revision, get_build_info
from version import APP_PRODUCT_VERSION


def run_js_solver(ctx: dict, records: list | None = None, options: dict | None = None) -> dict:
    """Run pure JS solveAuctionPipeline in Node.js."""
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


class TestPredictionSnapshotPersistenceV1(unittest.TestCase):
    def setUp(self):
        ACTIVE_SNAPSHOT_HOLDER.clear()
        reset_live_shadow_state()

    def tearDown(self):
        ACTIVE_SNAPSHOT_HOLDER.clear()
        reset_live_shadow_state()

    def test_code_revision_dynamic_and_honest(self):
        rev = get_code_revision(force_refresh=True)
        self.assertIsInstance(rev, str)
        self.assertTrue(len(rev) > 0)
        self.assertNotEqual(rev, "6ec6f9893f1de31c292e768c970ee3c83b5d6fde")

    def test_frozen_package_revision_immutable_and_ignores_git_changes(self):
        """Frozen packaged runtime must read from build metadata and NEVER run git rev-parse."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            build_info = {
                "codeRevision": "abc123frozencommit",
                "buildCommit": "abc123frozencommit",
                "isDirty": False,
                "builtAt": "2026-08-21T00:00:00Z"
            }
            (tmp_path / "build_info.json").write_text(json.dumps(build_info), encoding="utf-8")

            # Mock sys.frozen = True and sys._MEIPASS = tmp_dir
            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "_MEIPASS", str(tmp_path), create=True), \
                 patch.dict(os.environ, {}, clear=True):
                # Even if subprocess git would return a different commit, frozen mode must ignore git
                with patch("subprocess.run") as mock_git:
                    rev = get_code_revision(force_refresh=True)
                    self.assertEqual(rev, "abc123frozencommit")
                    # Assert git was never called
                    mock_git.assert_not_called()

    def test_frozen_package_missing_build_info_fails_closed_to_frozen_unversioned(self):
        """If build metadata is missing in frozen package, must NOT fallback to repo git."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "_MEIPASS", str(tmp_dir), create=True), \
                 patch.dict(os.environ, {}, clear=True):
                with patch("subprocess.run") as mock_git:
                    rev = get_code_revision(force_refresh=True)
                    self.assertEqual(rev, "frozen-unversioned")
                    mock_git.assert_not_called()

    def test_js_solver_produces_contract_compliant_v1_snapshot(self):
        d_rev = get_live_dataset_revision()
        c_rev = get_code_revision(force_refresh=True)
        match_id = "test_match_valid_001"
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
        res = run_js_solver(ctx, options={"datasetRevision": d_rev, "codeRevision": c_rev, "runtime": "test_runner"})
        snap = res.get("predictionSnapshot")
        self.assertIsNotNone(snap)
        self.assertEqual(snap["schemaVersion"], PREDICTION_SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(snap["matchId"], match_id)
        self.assertEqual(snap["producer"]["solverName"], "auction_engine_v06")
        self.assertEqual(snap["producer"]["solverVersion"], "v0.6-reliability")
        self.assertEqual(snap["producer"]["modelVersion"], "v0.6-shadow")
        self.assertEqual(snap["producer"]["codeRevision"], c_rev)
        self.assertEqual(snap["mode"]["informationMode"], "full_shadow")
        self.assertEqual(snap["forecast"]["target"], "full_inventory_actual_total")
        self.assertEqual(snap["forecast"]["scope"], "full_inventory")
        self.assertIsNotNone(snap["forecast"]["quantiles"])
        self.assertEqual(snap["forecast"]["quantiles"]["p50"], 420000)

        # Validate with formal Python validator
        is_valid, reasons = validate_prediction_snapshot(snap, match_id=match_id)
        self.assertTrue(is_valid, f"Validation failed with reasons: {reasons}")
        self.assertEqual(reasons, [])

    def test_sha256_input_hash_parity_between_js_and_python(self):
        ctx = {
            "matchId": "test_hash_parity",
            "q": 9,
            "goldAvg": 33538,
            "purpleCount": 5,
            "knownGold": "万有星仪",
            "box": "完整的保险箱",
            "character": "达芙蒂尔",
            "fieldCondition": "dark",
        }
        res = run_js_solver(ctx)
        snap = res["predictionSnapshot"]
        normalized_facts = snap["input"]["normalizedFacts"]
        py_hash = build_input_sha256(normalized_facts)
        self.assertEqual(snap["input"]["inputHash"], py_hash)
        self.assertEqual(len(py_hash), 64)

    def test_mode_and_target_mapping(self):
        d_rev = get_live_dataset_revision()
        c_rev = get_code_revision(force_refresh=True)

        # 1. Structural Only (coverageRatio == 0)
        ctx_struct = {"matchId": "m_struct", "q": 9, "goldAvg": 33538, "purpleCount": 5}
        res_struct = run_js_solver(ctx_struct, options={"datasetRevision": d_rev, "codeRevision": c_rev})
        snap_struct = res_struct["predictionSnapshot"]
        self.assertEqual(snap_struct["mode"]["informationMode"], "structural_only")
        self.assertEqual(snap_struct["forecast"]["target"], "structural_feasible_range")
        self.assertEqual(snap_struct["forecast"]["scope"], "structural_inventory")
        self.assertIsNone(snap_struct["forecast"]["quantiles"])
        is_valid, reasons = validate_prediction_snapshot(snap_struct, match_id="m_struct")
        self.assertTrue(is_valid, f"Structural validation failed: {reasons}")

        # 2. Partial Shadow (0 < coverageRatio < 1)
        ctx_partial = {
            "matchId": "m_partial",
            "q": 9,
            "goldAvg": 33538,
            "purpleCount": 5,
            "probabilityProfile": {
                "coverageRatio": 0.5,
                "supportedStateCount": 1,
                "totalStateCount": 2,
                "shadowWhole": {"p20": 200000, "p50": 250000, "p80": 300000},
            },
        }
        res_partial = run_js_solver(ctx_partial, options={"datasetRevision": d_rev, "codeRevision": c_rev})
        snap_partial = res_partial["predictionSnapshot"]
        self.assertEqual(snap_partial["mode"]["informationMode"], "partial_shadow")
        self.assertEqual(snap_partial["forecast"]["target"], "partial_inventory_conditional_total")
        self.assertEqual(snap_partial["forecast"]["scope"], "partial_inventory_conditional")
        self.assertIsNone(snap_partial["forecast"]["quantiles"])
        is_valid, reasons = validate_prediction_snapshot(snap_partial, match_id="m_partial")
        self.assertTrue(is_valid, f"Partial validation failed: {reasons}")

    def test_content_addressed_prediction_id(self):
        d_rev = get_live_dataset_revision()
        c_rev = get_code_revision(force_refresh=True)
        ctx_a = {"matchId": "m_id_1", "q": 9, "goldAvg": 33538}
        ctx_b = {"matchId": "m_id_1", "q": 10, "goldAvg": 33538}
        res_a = run_js_solver(ctx_a, options={"datasetRevision": d_rev, "codeRevision": c_rev})
        res_b = run_js_solver(ctx_b, options={"datasetRevision": d_rev, "codeRevision": c_rev})
        id_a = res_a["predictionSnapshot"]["predictionId"]
        id_b = res_b["predictionSnapshot"]["predictionId"]
        self.assertTrue(id_a.startswith("pred_"))
        self.assertTrue(id_b.startswith("pred_"))
        self.assertEqual(len(id_a), 5 + 64)
        self.assertNotEqual(id_a, id_b)

    def test_active_snapshot_holder_match_id_binding(self):
        holder = ActivePredictionSnapshotHolder()
        self.assertIsNone(holder.get_snapshot_for_match("match_1"))

        snap_1 = {"matchId": "match_1", "schemaVersion": "prediction-snapshot.v1"}
        holder.update("match_1", snapshot=snap_1)
        self.assertEqual(holder.get_snapshot_for_match("match_1"), snap_1)
        self.assertIsNone(holder.get_snapshot_for_match("match_2"))

        # Mismatched matchId update rejected
        snap_mismatch = {"matchId": "match_wrong", "schemaVersion": "prediction-snapshot.v1"}
        ok = holder.update("match_1", snapshot=snap_mismatch)
        self.assertFalse(ok)
        self.assertEqual(holder.get_snapshot_for_match("match_1"), snap_1)

        holder.clear()
        self.assertIsNone(holder.get_snapshot_for_match("match_1"))

    def test_cross_match_isolation_regression(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test_data.json")
            archiver = AutoArchiver(db_paths=[db_path])

            d_rev = get_live_dataset_revision()
            c_rev = get_code_revision(force_refresh=True)

            # Match A: has valid snapshot
            res_a = run_js_solver(
                {"matchId": "match_A", "q": 9, "goldAvg": 33538, "purpleCount": 5},
                options={"datasetRevision": d_rev, "codeRevision": c_rev},
            )
            snap_a = res_a["predictionSnapshot"]
            ACTIVE_SNAPSHOT_HOLDER.update("match_A", snapshot=snap_a)

            # Match A archived
            ctx_a = {
                "id": "match_A",
                "matchId": "match_A",
                "predictionSnapshot": snap_a,
                "settlementReady": True,
                "settlementData": {"isSettlement": True, "clearingPrice": 100000, "actualTotal": 150000, "profit": 50000},
            }
            record_a = archiver.archive_match(ctx_a)
            self.assertIsNotNone(record_a)
            self.assertIn("predictionSnapshot", record_a)
            self.assertEqual(record_a["predictionSnapshot"]["matchId"], "match_A")

            # Holder is cleared after archive
            self.assertIsNone(ACTIVE_SNAPSHOT_HOLDER.get_snapshot_for_match("match_A"))

            # Match B: reset, NO prediction snapshot generated
            ACTIVE_SNAPSHOT_HOLDER.clear()
            ctx_b = {
                "id": "match_B",
                "matchId": "match_B",
                "settlementReady": True,
                "settlementData": {"isSettlement": True, "clearingPrice": 200000, "actualTotal": 250000, "profit": 50000},
            }
            record_b = archiver.archive_match(ctx_b)
            self.assertIsNotNone(record_b)
            # Crucial invariant: Match B must NEVER inherit Match A snapshot
            self.assertNotIn("predictionSnapshot", record_b)

    def test_auto_archiver_never_synthesizes_snapshot_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test_data.json")
            archiver = AutoArchiver(db_paths=[db_path])

            # 1. Invalid snapshot with forged hash
            ctx_invalid = {
                "id": "match_corrupt",
                "matchId": "match_corrupt",
                "predictionSnapshot": {
                    "schemaVersion": "prediction-snapshot.v1",
                    "matchId": "match_corrupt",
                    "input": {"contractVersion": 1, "normalizedFacts": {"q": 9}, "inputHash": "badhash"},
                },
                "settlementReady": True,
                "settlementData": {"isSettlement": True, "clearingPrice": 100000, "actualTotal": 150000, "profit": 50000},
            }
            record_invalid = archiver.archive_match(ctx_invalid)
            self.assertIsNotNone(record_invalid)
            # Fails closed: corrupted snapshot is not persisted
            self.assertNotIn("predictionSnapshot", record_invalid)

    def test_parent_record_schema_preserved(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "test_data.json")
            archiver = AutoArchiver(db_paths=[db_path])

            d_rev = get_live_dataset_revision()
            c_rev = get_code_revision(force_refresh=True)
            res = run_js_solver(
                {"matchId": "match_p", "q": 9, "goldAvg": 33538, "purpleCount": 5},
                options={"datasetRevision": d_rev, "codeRevision": c_rev},
            )
            snap = res["predictionSnapshot"]

            ctx = {
                "id": "match_p",
                "matchId": "match_p",
                "box": "实木宝箱",
                "fieldCondition": "standard",
                "winner": "FixtureWinner",
                "acquired": False,
                "predictionSnapshot": snap,
                "settlementReady": True,
                "settlementData": {"isSettlement": True, "clearingPrice": 100000, "actualTotal": 150000, "profit": 50000},
            }
            record = archiver.archive_match(ctx)
            self.assertIsNotNone(record)
            self.assertEqual(record["productVersion"], APP_PRODUCT_VERSION)
            self.assertEqual(record.get("schemaVersion"), 7)
            self.assertEqual(record.get("lifecycleStatus"), "FINALIZED")
            self.assertIn("predictionSnapshot", record)
            self.assertEqual(record["predictionSnapshot"]["schemaVersion"], "prediction-snapshot.v1")

    def test_live_packaged_exe_provenance_if_built(self):
        """If dist/异环拍卖助手/异环拍卖助手.exe exists, test its live provenance isolation."""
        exe_path = ROOT_DIR / "dist" / "异环拍卖助手" / "异环拍卖助手.exe"
        if not exe_path.is_file():
            self.skipTest("Packaged executable not found in dist/")

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Initialize a foreign git repo in tmp_dir with a different commit
            subprocess.run(["git", "init"], cwd=tmp_dir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_dir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_dir, capture_output=True, check=True)
            (Path(tmp_dir) / "dummy.txt").write_text("foreign commit", encoding="utf-8")
            subprocess.run(["git", "add", "dummy.txt"], cwd=tmp_dir, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "foreign commit"], cwd=tmp_dir, capture_output=True, check=True)
            foreign_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=tmp_dir, capture_output=True, text=True, check=True
            ).stdout.strip()

            # Execute the packaged EXE inside foreign git working directory
            proc = subprocess.run(
                [str(exe_path), "--print-code-revision"],
                cwd=tmp_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            printed_rev = proc.stdout.strip()
            self.assertTrue(len(printed_rev) > 0)
            self.assertNotEqual(printed_rev, "dev-unversioned")
            self.assertNotEqual(printed_rev, "frozen-unversioned")
            self.assertNotEqual(printed_rev, foreign_commit, "Packaged EXE must not read foreign git repo in CWD")


if __name__ == "__main__":
    unittest.main()
