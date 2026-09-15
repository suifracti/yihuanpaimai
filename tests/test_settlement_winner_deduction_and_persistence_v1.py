# -*- coding: utf-8 -*-
"""Targeted unit tests for AutoArchiver winner authority narrowing, DRAFT fallback, and bounded persistence."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
TESTS_DIR = PROJECT_ROOT / "tests"

for p in (str(PROJECT_ROOT), str(APP_DIR), str(CORE_DIR), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from auto_archiver import AutoArchiver
from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import validate_canonical_match_record_v7, validate_finalized_match_record_v7
from settlement_truth_holder import ACTIVE_SETTLEMENT_TRUTH_HOLDER


class TestSettlementWinnerDeductionAndPersistenceV1(unittest.TestCase):
    def setUp(self):
        ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()

    def tearDown(self):
        ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()

    def test_uat24_unproven_winner_persists_safely_as_draft_without_placeholders(self):
        """AC1: UAT24 match with 300000 / 181156 / -118844 and no independent winner authority persists as DRAFT without placeholders."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "异环拍卖数据.json"
            archiver = AutoArchiver(db_paths=[str(db_path)])

            match_id = "draft_3e5432bbea5748faba2ade544bc3f030"
            ctx = {
                "id": match_id,
                "matchId": match_id,
                "venue": "shanhu",
                "box": "实木宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
                "q": 6,
                "myName": "玩家本人",
                "myBid": 0,
                "leaderName": None,
                "opponents": [],
                "settlementReady": True,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 300000,
                    "actualTotal": 181156,
                    "profit": -118844,
                    "items": [],
                },
            }

            saved = archiver.archive_match(ctx)
            self.assertIsNotNone(saved, "Archive should succeed and return saved draft record")
            self.assertEqual(saved["schemaVersion"], 7)
            # AC1: Must be DRAFT because winner is unproven
            self.assertEqual(saved["lifecycleStatus"], "DRAFT")
            self.assertIsNone(saved["settlement"]["winner"])
            self.assertEqual(saved["settlement"]["clearingPrice"], 300000.0)
            self.assertEqual(saved["settlement"]["actualTotal"], 181156.0)
            self.assertEqual(saved["settlement"]["realizedProfit"], -118844.0)
            self.assertEqual(saved["settlement"]["acquired"], False)
            self.assertEqual(saved["settlement"]["verified"], False)

            # Contract validation: must pass base v7 validation
            is_valid, reasons = validate_canonical_match_record_v7(saved)
            self.assertTrue(is_valid, f"Base v7 validation failed on draft: {reasons}")
            self.assertEqual(reasons, [])

            # Database file verification
            store = CanonicalHistoryStore(db_path)
            persisted = store.lookup(match_id)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted["lifecycleStatus"], "DRAFT")
            self.assertIsNone(persisted["settlement"]["winner"])

            # Verify NO forbidden placeholders in winner
            rec_str = json.dumps(saved, ensure_ascii=False)
            self.assertNotIn('"winner": "玩家本人"', rec_str)
            self.assertNotIn("本人拍下", rec_str)
            self.assertNotIn("他人拍下", rec_str)
            self.assertNotIn("未知竞得者", rec_str)

    def test_authorized_real_winner_persists_as_finalized(self):
        """AC2: Explicit authorized real winner string persists as FINALIZED."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "异环拍卖数据.json"
            archiver = AutoArchiver(db_paths=[str(db_path)])

            match_id = "test_auth_winner_001"
            ctx = {
                "id": match_id,
                "matchId": match_id,
                "venue": "shanhu",
                "box": "实木宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
                "q": 10,
                "myName": "PLAYER_LOCAL",
                "winner": "PLAYER_LOCAL",
                "settlementReady": True,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 600000,
                    "actualTotal": 850000,
                    "profit": 245000,
                    "items": [],
                },
            }

            saved = archiver.archive_match(ctx)
            self.assertIsNotNone(saved)
            self.assertEqual(saved["lifecycleStatus"], "FINALIZED")
            self.assertEqual(saved["settlement"]["winner"], "PLAYER_LOCAL")
            self.assertEqual(saved["settlement"]["acquired"], True)
            self.assertEqual(saved["settlement"]["verified"], True)
            self.assertEqual(saved["settlement"]["clearingPrice"], 600000.0)

            is_valid, reasons = validate_finalized_match_record_v7(saved)
            self.assertTrue(is_valid, f"FINALIZED validation failed: {reasons}")

    def test_authorized_opponent_winner_persists_as_finalized(self):
        """AC2: Explicit authorized opponent winner string persists as FINALIZED."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "异环拍卖数据.json"
            archiver = AutoArchiver(db_paths=[str(db_path)])

            match_id = "test_opp_winner_001"
            ctx = {
                "id": match_id,
                "matchId": match_id,
                "venue": "shanhu",
                "box": "实木宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
                "q": 10,
                "myName": "PLAYER_LOCAL",
                "winner": "达芙蒂尔",
                "settlementReady": True,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 600000,
                    "actualTotal": 550000,
                    "profit": None,
                    "items": [],
                },
            }

            saved = archiver.archive_match(ctx)
            self.assertIsNotNone(saved)
            self.assertEqual(saved["lifecycleStatus"], "FINALIZED")
            self.assertEqual(saved["settlement"]["winner"], "达芙蒂尔")
            self.assertEqual(saved["settlement"]["acquired"], False)
            self.assertEqual(saved["settlement"]["verified"], True)

            is_valid, reasons = validate_finalized_match_record_v7(saved)
            self.assertTrue(is_valid, f"FINALIZED validation failed: {reasons}")

    def test_forbidden_placeholders_rejected_to_draft(self):
        """AC1/AC2: Forbidden placeholders like '玩家本人', '未知竞得者' fall back to winner=None and DRAFT."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "异环拍卖数据.json"
            archiver = AutoArchiver(db_paths=[str(db_path)])

            match_id = "test_placeholder_reject_001"
            ctx = {
                "id": match_id,
                "matchId": match_id,
                "venue": "shanhu",
                "box": "实木宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
                "q": 6,
                "winner": "玩家本人",  # Forbidden placeholder
                "settlementReady": True,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 300000,
                    "actualTotal": 181156,
                    "profit": -118844,
                    "items": [],
                },
            }

            saved = archiver.archive_match(ctx)
            self.assertIsNotNone(saved)
            self.assertEqual(saved["lifecycleStatus"], "DRAFT")
            self.assertIsNone(saved["settlement"]["winner"])

    def test_leader_name_does_not_promote_to_winner_and_falls_back_to_draft(self):
        """AC1: leaderName='PLAYER_LOCAL' without explicit winner field must NOT promote to winner, falls back to DRAFT."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "异环拍卖数据.json"
            archiver = AutoArchiver(db_paths=[str(db_path)])

            match_id = "test_leader_no_winner_001"
            ctx = {
                "id": match_id,
                "matchId": match_id,
                "venue": "shanhu",
                "box": "实木宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
                "q": 10,
                "myName": "PLAYER_LOCAL",
                "leaderName": "PLAYER_LOCAL",  # leaderName present, but winner absent
                "settlementReady": True,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 600000,
                    "actualTotal": 850000,
                    "profit": 245000,
                    "items": [],
                },
            }

            saved = archiver.archive_match(ctx)
            self.assertIsNotNone(saved)
            self.assertEqual(saved["lifecycleStatus"], "DRAFT")
            self.assertIsNone(saved["settlement"]["winner"])
            self.assertEqual(saved["settlement"]["clearingPrice"], 600000.0)
            self.assertEqual(saved["settlement"]["actualTotal"], 850000.0)
            self.assertEqual(saved["settlement"]["realizedProfit"], 245000.0)

            # Contract validation
            is_valid, reasons = validate_canonical_match_record_v7(saved)
            self.assertTrue(is_valid, f"Base v7 validation failed on draft: {reasons}")

    def test_bounded_error_handling_prevents_19x_duplicate_writes(self):
        """AC3: Repeated identical frames with leaderName=None are bounded by duplicate signature gate."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "异环拍卖数据.json"
            archiver = AutoArchiver(db_paths=[str(db_path)])

            match_id = "test_repeat_001"
            ctx = {
                "id": match_id,
                "matchId": match_id,
                "venue": "shanhu",
                "box": "实木宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
                "q": 6,
                "myName": "玩家本人",
                "myBid": 0,
                "leaderName": None,
                "settlementReady": True,
                "settlementData": {
                    "isSettlement": True,
                    "clearingPrice": 300000,
                    "actualTotal": 181156,
                    "profit": -118844,
                    "items": [],
                },
            }

            # First call succeeds and saves to DRAFT
            saved1 = archiver.archive_match(ctx)
            self.assertIsNotNone(saved1)
            self.assertEqual(saved1["lifecycleStatus"], "DRAFT")

            # Subsequent calls with the exact same settlement frame are deduplicated (return None)
            saved2 = archiver.archive_match(ctx)
            self.assertIsNone(saved2, "Duplicate frame within 60s should be debounced")
            saved3 = archiver.archive_match(ctx)
            self.assertIsNone(saved3, "Duplicate frame within 60s should be debounced")


if __name__ == "__main__":
    unittest.main()
