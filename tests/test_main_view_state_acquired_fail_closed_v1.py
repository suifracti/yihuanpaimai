# -*- coding: utf-8 -*-
"""Targeted unit tests for MainViewStateProvider fail-closed acquired history projection."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"

for p in (
    r"C:\Program Files\Python310\Lib\site-packages",
    str(PROJECT_ROOT),
    str(CORE_DIR),
    str(APP_DIR),
):
    if p not in sys.path:
        sys.path.insert(0, p)

from main_view_state import MainViewStateProvider
from history_admission import build_duplicate_index, evaluate_history_admission


class TestMainViewStateAcquiredFailClosedV1(unittest.TestCase):
    def _project(self, record: dict):
        dup_idx = build_duplicate_index([record])
        decision = evaluate_history_admission(record, dup_idx)
        proj = MainViewStateProvider._project_record(record, decision)
        payload = proj.to_payload()
        return proj.settlement_acquired, payload["settlement"]["acquired"]

    def test_case_a_null_no_winner(self):
        """CASE A — settlement.acquired=None, winner=None => projected acquired=None."""
        record = {
            "schemaVersion": 7,
            "id": "case_a_001",
            "lifecycleStatus": "DRAFT",
            "settlement": {
                "clearingPrice": 300000,
                "actualTotal": 450000,
                "acquired": None,
                "winner": None,
            },
        }
        acquired, payload_acquired = self._project(record)
        self.assertIsNone(acquired)
        self.assertIsNone(payload_acquired)

    def test_case_b_null_winner_other(self):
        """CASE B — settlement.acquired=None, winner='汐', myName='玩家本人' => projected acquired=None."""
        record = {
            "schemaVersion": 7,
            "id": "case_b_001",
            "lifecycleStatus": "DRAFT",
            "myName": "玩家本人",
            "bidding": {"myName": "玩家本人"},
            "settlement": {
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "acquired": None,
                "winner": "汐",
            },
        }
        acquired, payload_acquired = self._project(record)
        self.assertIsNone(acquired)
        self.assertIsNone(payload_acquired)

    def test_case_c_null_winner_self(self):
        """CASE C — settlement.acquired=None, winner='玩家本人', myName='玩家本人' => projected acquired=None."""
        record = {
            "schemaVersion": 7,
            "id": "case_c_001",
            "lifecycleStatus": "DRAFT",
            "myName": "玩家本人",
            "bidding": {"myName": "玩家本人"},
            "settlement": {
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "acquired": None,
                "winner": "玩家本人",
            },
        }
        acquired, payload_acquired = self._project(record)
        self.assertIsNone(acquired)
        self.assertIsNone(payload_acquired)

    def test_case_d_missing_acquired(self):
        """CASE D — settlement.acquired 缺失, winner='玩家本人', myName='玩家本人' => projected acquired=None."""
        record = {
            "schemaVersion": 7,
            "id": "case_d_001",
            "lifecycleStatus": "DRAFT",
            "myName": "玩家本人",
            "bidding": {"myName": "玩家本人"},
            "settlement": {
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "winner": "玩家本人",
            },
        }
        acquired, payload_acquired = self._project(record)
        self.assertIsNone(acquired)
        self.assertIsNone(payload_acquired)

    def test_case_e_explicit_true_preserved(self):
        """CASE E — settlement.acquired=True, 即使 winner != myName => projected True."""
        record = {
            "schemaVersion": 7,
            "id": "case_e_001",
            "lifecycleStatus": "FINALIZED",
            "myName": "秋星祭02",
            "bidding": {"myName": "秋星祭02"},
            "settlement": {
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "acquired": True,
                "winner": "汐",
            },
        }
        acquired, payload_acquired = self._project(record)
        self.assertIs(acquired, True)
        self.assertIs(payload_acquired, True)

    def test_case_f_explicit_false_preserved(self):
        """CASE F — settlement.acquired=False, 即使 winner == myName => projected False."""
        record = {
            "schemaVersion": 7,
            "id": "case_f_001",
            "lifecycleStatus": "FINALIZED",
            "myName": "玩家本人",
            "bidding": {"myName": "玩家本人"},
            "settlement": {
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "acquired": False,
                "winner": "玩家本人",
            },
        }
        acquired, payload_acquired = self._project(record)
        self.assertIs(acquired, False)
        self.assertIs(payload_acquired, False)

    def test_non_boolean_ownership_is_unknown(self):
        for value in ("true", "false", "1", "0", 1, 0, 1.0, {}, [], [True]):
            with self.subTest(value=value):
                record = {"schemaVersion": 7, "id": "invalid", "lifecycleStatus": "FINALIZED",
                          "settlement": {"acquired": value, "realizedProfit": 333902}}
                self.assertEqual(self._project(record), (None, None))


if __name__ == "__main__":
    unittest.main()
