# -*- coding: utf-8 -*-
"""Focused correctness gates for Manual Terminal Lifecycle v1."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for path in (APP_DIR, CORE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from canonical_history_store import CanonicalHistoryStore, FinalizedRecordConflictError
from current_match import CurrentMatch
from evaluation_eligibility import build_input_sha256
from manual_terminal import ManualTerminalCoordinator, ManualTerminalError


def _prediction(match_id: str) -> dict:
    facts = {"q": 9, "goldAvg": 33538, "fieldCondition": "standard"}
    return {
        "schemaVersion": "prediction-snapshot.v1",
        "predictionId": f"prediction-{match_id}",
        "matchId": match_id,
        "solvedAt": "2026-08-22T10:00:00+08:00",
        "informationCutoffAt": "2026-08-22T09:59:00+08:00",
        "snapshotRole": "latest_valid_pre_settlement",
        "producer": {
            "runtime": "overlay_runtime",
            "solverName": "auction_engine_v06",
            "solverVersion": "v0.6",
            "modelVersion": "v0.6",
            "catalogVersion": "catalog-1",
            "codeRevision": "fixture-revision",
        },
        "input": {
            "contractVersion": 1,
            "normalizedFacts": facts,
            "hashAlgorithm": "sha256",
            "inputHash": build_input_sha256(facts),
            "datasetRevision": {
                "sourceId": "canonical_match_history",
                "sha256": "b" * 64,
                "recordCount": 0,
                "admissionPolicyVersion": 1,
                "cutoffExclusive": "2026-08-22T09:59:00+08:00",
                "eligibleRecordIdsSha256": "a" * 64,
            },
        },
        "mode": {
            "informationMode": "full_shadow",
            "coverageRatio": 1.0,
            "supportedStateCount": 2,
            "totalStateCount": 2,
        },
        "status": {"solverStatus": "valid", "provisional": False, "diagnosticOnly": False},
        "forecast": {
            "target": "full_inventory_actual_total",
            "scope": "full_inventory",
            "quantiles": {"p20": 400000, "p50": 500000, "p80": 600000},
        },
        "frozen": True,
    }


def _draft() -> tuple[CurrentMatch, dict]:
    match = CurrentMatch()
    match.apply_facts({
        "venueId": "venue-shanhu",
        "venue": "珊瑚场",
        "boxId": "box-shanhu-glass",
        "box": "琉璃宝箱",
        "fieldCondition": "standard",
        "q": 9,
        "goldAvg": 33538,
        "purpleCount": 5,
        "knownGold": "万有星仪",
        "entryCost": 5000,
        "catalogVersion": "venue-box-catalog.v1",
        "catalogApprovalStatus": "APPROVED_FOR_ALPHA",
        "catalogSha256": "c" * 64,
        "gameEvidenceCohort": "current-venue-plus-alpha-box-bootstrap",
        "venueEvidenceClass": "CURRENT_GAME_VALID",
        "boxEvidenceClass": "OPERATOR_ASSERTED_CURRENT",
    })
    return match, match.to_canonical()


class TestManualTerminalCoordinator(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "history.json"
        self.coordinator = ManualTerminalCoordinator(self.path)
        self.match, self.draft = _draft()
        self.snapshot = _prediction(self.match.id)
        self.draft["predictionSnapshot"] = self.snapshot
        CanonicalHistoryStore(self.path).persist_record_transactional(self.draft, is_finalized=False)
        self.settlement = {
            "clearingPrice": 100000,
            "actualTotal": 160000,
            "acquired": True,
            "winner": "FixturePlayer",
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_generic_winner_labels_are_rejected_without_writing(self):
        before = self.path.read_bytes()
        for acquired in (True, False):
            for winner in ("本人拍下", "其他人拍下", "玩家本人", "未知", " "):
                with self.subTest(acquired=acquired, winner=winner), self.assertRaises(ManualTerminalError):
                    self.coordinator.finalize(self.draft, {**self.settlement, "acquired": acquired, "winner": winner})
        self.assertEqual(self.path.read_bytes(), before)

    def test_named_opponent_is_independent_of_acquired(self):
        result = self.coordinator.finalize(self.draft, {**self.settlement, "acquired": False, "winner": "FixtureOpponent"})
        saved = self.coordinator.lookup(self.match.id)
        self.assertEqual(result["status"], "FINALIZED")
        self.assertEqual(saved["settlement"]["winner"], "FixtureOpponent")
        self.assertIs(saved["settlement"]["acquired"], False)

    def test_draft_to_finalized_preserves_facts_and_is_exactly_once(self):
        result = self.coordinator.finalize(
            self.draft,
            self.settlement,
            prediction_snapshot=self.snapshot,
            played_at=self.match.created_at,
        )
        self.assertEqual(result["status"], "FINALIZED")
        first = self.coordinator.lookup(self.match.id)
        self.assertEqual(first["lifecycleStatus"], "FINALIZED")
        self.assertEqual(first["environment"]["catalogSha256"], "c" * 64)
        self.assertEqual(first["environment"]["boxEvidenceClass"], "OPERATOR_ASSERTED_CURRENT")
        self.assertEqual(first["predictionSnapshot"], self.snapshot)
        self.assertEqual(first["settlement"]["actualTotal"], 160000.0)
        self.assertEqual(first["settlement"]["realizedProfit"], 55000.0)
        self.assertNotIn("truthEvidence", first["settlement"])

        second = self.coordinator.finalize(
            self.draft,
            self.settlement,
            prediction_snapshot=self.snapshot,
            played_at=self.match.created_at,
        )
        self.assertEqual(second["status"], "FINALIZED")
        rows = CanonicalHistoryStore(self.path).read_database()["records"]
        self.assertEqual(len(rows), 1)

        changed = copy.deepcopy(self.draft)
        with self.assertRaises(FinalizedRecordConflictError):
            CanonicalHistoryStore(self.path).persist_record_transactional(changed, is_finalized=False)

    def test_stale_retry_reports_already_finalized(self):
        self.coordinator.finalize(
            self.draft, self.settlement, prediction_snapshot=self.snapshot,
            played_at=self.match.created_at,
        )
        result = self.coordinator.stale_result(self.match.id, "new-match")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ALREADY_FINALIZED")

    def test_keep_draft_and_discard_are_distinct(self):
        kept = self.coordinator.keep_draft(self.draft)
        self.assertEqual(kept["status"], "DRAFT_KEPT")
        self.assertEqual(self.coordinator.lookup(self.match.id)["lifecycleStatus"], "DRAFT")

        discarded = self.coordinator.discard(self.draft)
        self.assertEqual(discarded["status"], "DRAFT_DISCARDED")
        self.assertEqual(self.coordinator.lookup(self.match.id)["lifecycleStatus"], "CANCELLED")

    def test_incomplete_or_conflicting_settlement_fails_without_mutation(self):
        before = self.path.read_bytes()
        with self.assertRaises(ManualTerminalError):
            self.coordinator.finalize(self.draft, {"clearingPrice": 1})
        with self.assertRaises(ManualTerminalError):
            self.coordinator.finalize(
                self.draft,
                {"clearingPrice": 1, "actualTotal": 2, "acquired": True, "winner": "其他人拍下"},
            )
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.coordinator.lookup(self.match.id)["lifecycleStatus"], "DRAFT")

    def test_write_failure_preserves_draft(self):
        before = self.path.read_bytes()
        with mock.patch.object(
            CanonicalHistoryStore, "persist_record_transactional", side_effect=OSError("disk")
        ):
            with self.assertRaises(ManualTerminalError) as ctx:
                self.coordinator.finalize(
                    self.draft, self.settlement, prediction_snapshot=self.snapshot,
                    played_at=self.match.created_at,
                )
        self.assertEqual(ctx.exception.code, "FINALIZE_WRITE_FAILED")
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_prediction_snapshot_fails_closed(self):
        corrupt = copy.deepcopy(self.snapshot)
        corrupt["matchId"] = "other"
        before = self.path.read_bytes()
        with self.assertRaises(ManualTerminalError) as ctx:
            self.coordinator.finalize(
                self.draft, self.settlement, prediction_snapshot=corrupt,
                played_at=self.match.created_at,
            )
        self.assertEqual(ctx.exception.code, "PREDICTION_SNAPSHOT_INVALID")
        self.assertEqual(self.path.read_bytes(), before)

    def test_real_fallback_prediction_does_not_block_settlement(self):
        from test_prediction_snapshot_persistence_v1 import run_js_solver
        snapshot = run_js_solver({"matchId": self.match.id, "venue": "shanhu",
                                  "box": "实木宝箱", "fieldCondition": "standard"},
                                 options={"datasetRevision": self.snapshot["input"]["datasetRevision"],
                                          "codeRevision": "fixture-revision"})["predictionSnapshot"]
        self.assertEqual(snapshot["status"]["solverStatus"], "fallback")
        result = self.coordinator.finalize(self.draft, self.settlement,
                                           prediction_snapshot=snapshot)
        self.assertTrue(result["ok"])
        self.assertEqual(self.coordinator.lookup(self.match.id)["predictionSnapshot"], snapshot)
        from evaluation_eligibility import validate_prediction_snapshot
        self.assertFalse(validate_prediction_snapshot(snapshot, match_id=self.match.id)[0])

    def test_fallback_status_does_not_bypass_prediction_integrity(self):
        for field in ("matchId", "inputHash"):
            with self.subTest(field=field):
                corrupt = copy.deepcopy(self.snapshot)
                corrupt["status"].update(solverStatus="fallback", provisional=True)
                if field == "matchId":
                    corrupt["matchId"] = "other-match"
                else:
                    corrupt["input"]["inputHash"] = "0" * 64
                before = self.path.read_bytes()
                with self.assertRaises(ManualTerminalError):
                    self.coordinator.finalize(self.draft, self.settlement, prediction_snapshot=corrupt)
                self.assertEqual(self.path.read_bytes(), before)

    def test_missing_environment_has_actionable_message(self):
        draft = copy.deepcopy(self.draft)
        draft["environment"] = {}
        with self.assertRaises(ManualTerminalError) as ctx:
            self.coordinator.finalize(draft, self.settlement)
        self.assertIn("宝箱", ctx.exception.message)
        self.assertIn("规则", ctx.exception.message)
        self.assertNotIn("FINALIZED_PROFILE", ctx.exception.message)

    def test_match_ids_do_not_collide_across_fresh_owners(self):
        ids = {CurrentMatch().id for _ in range(200)}
        self.assertEqual(len(ids), 200)
        self.assertTrue(all(match_id.startswith("draft_") for match_id in ids))


if __name__ == "__main__":
    unittest.main()
