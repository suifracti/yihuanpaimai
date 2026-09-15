# -*- coding: utf-8 -*-
"""Targeted unit tests for AutoArchiver fail-closed acquired authority and history persistence."""

import json
import os
import sys
import tempfile
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

from auto_archiver import AutoArchiver


class TestAutoArchiverAcquiredFailClosedV1(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.orig_env = os.environ.get("YIHUAN_DATA_ROOT")
        os.environ["YIHUAN_DATA_ROOT"] = self.tmpdir.name
        self.db_path = os.path.join(self.tmpdir.name, "test_history.json")
        self.archiver = AutoArchiver(db_paths=[self.db_path])

    def tearDown(self):
        if self.orig_env is not None:
            os.environ["YIHUAN_DATA_ROOT"] = self.orig_env
        else:
            os.environ.pop("YIHUAN_DATA_ROOT", None)
        self.tmpdir.cleanup()

    def _read_persisted_record(self, record_id: str):
        with open(self.db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        records = data.get("records", [])
        for r in records:
            if r.get("id") == record_id:
                return r
        return None

    def test_receipt_updates_same_record_without_changing_inventory_value(self):
        ctx = {'id': 'receipt-update', 'isSettlement': True, 'settlementReady': True,
               'isAcquired': False, 'fieldCondition': 'welfare',
               'costs': {'entry': 5000, 'intel': 0, 'other': 0},
               'settlementData': {'isSettlement': True, 'clearingPrice': 300000, 'actualTotal': 450000}}
        for receipt in (None, 3000, 0, None):
            ctx['settlementReady'] = True
            ctx['welfareReceived'] = receipt
            self.assertIsNotNone(self.archiver.archive_match(ctx))
            saved = self._read_persisted_record(ctx['id'])
            self.assertEqual(saved['settlement']['welfare']['received'], receipt)
            self.assertEqual(saved['settlement']['actualTotal'], 450000)
            ctx['settlementReady'] = True
            self.assertIsNone(self.archiver.archive_match(ctx))

    def test_private_controls_update_and_clear_in_same_record(self):
        ctx = {'id':'dark-controls','isSettlement':True,'isAcquired':False,
               'fieldCondition':'dark','costs':{'entry':0,'intel':0,'other':0},
               'settlementData':{'isSettlement':True,'clearingPrice':300000,'actualTotal':450000}}
        for key in ('privateBidCap','bidActionCount'):
            for value in (123,0,None):
                ctx.update(settlementReady=True, **{key:value})
                self.assertIsNotNone(self.archiver.archive_match(ctx))
                saved = self._read_persisted_record(ctx['id'])
                self.assertEqual(saved['bidding'][key],value)
                self.assertEqual(saved['settlement']['clearingPrice'],300000)

    def test_unknown_and_zero_costs_do_not_abort_or_invent_entry(self):
        for index, entry in enumerate((None, 0, True, float('nan'), '1.2', 5000)):
            ctx = {'id': f'cost-{index}', 'isSettlement': True, 'settlementReady': True,
                   'isAcquired': False, 'costs': {'entry': entry, 'intel': 1200, 'other': 300,
                   'sunkCost': None, 'futureIncrementalCost': 700},
                   'settlementData': {'isSettlement': True, 'clearingPrice': 300000, 'actualTotal': 450000}}
            saved = self.archiver.archive_match(ctx)
            self.assertIsNotNone(saved)
            costs = self._read_persisted_record(ctx['id'])['costs']
            expected = entry if type(entry) is int else None
            self.assertEqual(costs['entry'], expected)
            self.assertEqual(costs['total'], None if expected is None else expected + 2200)

    def test_transient_write_failure_retries_without_sixty_second_lockout(self):
        from unittest.mock import patch
        from canonical_history_store import CanonicalHistoryStore
        ctx = {'id': 'retry-write', 'settlementReady': True, 'isAcquired': False,
               'settlementData': {'isSettlement': True, 'clearingPrice': 100, 'actualTotal': 200}}
        with patch('auto_archiver.time.time', return_value=100), patch.object(
                CanonicalHistoryStore, 'persist_record_transactional', side_effect=OSError('transient write')):
            self.assertIsNone(self.archiver.archive_match(ctx))
        self.assertTrue(ctx['settlementReady'])
        self.assertIsNone(self.archiver.last_saved_signature)
        with patch('auto_archiver.time.time', return_value=100.5), patch.object(
                CanonicalHistoryStore, 'persist_record_transactional') as writer:
            self.assertIsNone(self.archiver.archive_match(ctx))
            writer.assert_not_called()
        with patch('auto_archiver.time.time', return_value=101.1):
            self.assertIsNotNone(self.archiver.archive_match(ctx))
        self.assertIsNotNone(self._read_persisted_record('retry-write'))
        ctx['settlementReady'] = True
        with patch('auto_archiver.time.time', return_value=102), patch.object(
                CanonicalHistoryStore, 'persist_record_transactional') as writer:
            self.assertIsNone(self.archiver.archive_match(ctx))
            writer.assert_not_called()

    def test_cost_correction_updates_saved_draft_inside_duplicate_window(self):
        from unittest.mock import patch
        ctx = {'id': 'cost-correction', 'settlementReady': True, 'isAcquired': False,
               'costs': {'entry': None},
               'settlementData': {'isSettlement': True, 'clearingPrice': 100, 'actualTotal': 200}}
        with patch('auto_archiver.time.time', return_value=200):
            self.assertIsNotNone(self.archiver.archive_match(ctx))
        ctx.update(settlementReady=True, costs={'entry': 0, 'intel': 25})
        with patch('auto_archiver.time.time', return_value=201):
            self.assertIsNotNone(self.archiver.archive_match(ctx))
        self.assertEqual(self._read_persisted_record('cost-correction')['costs']['total'], 25)

    def test_case_a_unknown_empty(self):
        """CASE A — upstream acquired=None / absent, winner=None => persisted acquired=None."""
        ctx = {
            "id": "case_a_001",
            "isSettlement": True,
            "settlementReady": True,
            "settlementFinalized": False,
            "winner": None,
            "settlementData": {
                "isSettlement": True,
                "clearingPrice": 300000,
                "actualTotal": 450000,
            },
        }
        res = self.archiver.archive_match(ctx)
        self.assertIsNotNone(res)
        self.assertIsNone(res["settlement"]["acquired"])
        persisted = self._read_persisted_record("case_a_001")
        self.assertIsNotNone(persisted)
        self.assertIsNone(persisted["settlement"]["acquired"])

    def test_case_b_unknown_with_winner_name(self):
        """CASE B — upstream acquired=None / absent, winner='汐', no self identity authority => persisted acquired=None."""
        ctx = {
            "id": "case_b_001",
            "isSettlement": True,
            "settlementReady": True,
            "settlementFinalized": False,
            "winner": "汐",
            "myName": "玩家本人",
            "settlementData": {
                "isSettlement": True,
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "winner": "汐",
            },
        }
        res = self.archiver.archive_match(ctx)
        self.assertIsNotNone(res)
        self.assertIsNone(res["settlement"]["acquired"])
        self.assertNotEqual(res["settlement"]["acquired"], False)
        persisted = self._read_persisted_record("case_b_001")
        self.assertIsNotNone(persisted)
        self.assertIsNone(persisted["settlement"]["acquired"])

    def test_case_c_explicit_true(self):
        """CASE C — 显式 acquired=True => persisted True."""
        ctx = {
            "id": "case_c_001",
            "isSettlement": True,
            "settlementReady": True,
            "settlementFinalized": False,
            "winner": "汐",
            "isAcquired": True,
            "box": "实木宝箱",
            "fieldCondition": "normal",
            "settlementData": {
                "isSettlement": True,
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "winner": "汐",
            },
        }
        res = self.archiver.archive_match(ctx)
        self.assertIsNotNone(res)
        self.assertIs(res["settlement"]["acquired"], True)
        persisted = self._read_persisted_record("case_c_001")
        self.assertIsNotNone(persisted)
        self.assertIs(persisted["settlement"]["acquired"], True)

    def test_case_d_explicit_false(self):
        """CASE D — 显式 acquired=False => persisted False."""
        ctx = {
            "id": "case_d_001",
            "isSettlement": True,
            "settlementReady": True,
            "settlementFinalized": False,
            "winner": "汐",
            "isAcquired": False,
            "box": "实木宝箱",
            "fieldCondition": "normal",
            "settlementData": {
                "isSettlement": True,
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "winner": "汐",
            },
        }
        res = self.archiver.archive_match(ctx)
        self.assertIsNotNone(res)
        self.assertIs(res["settlement"]["acquired"], False)
        persisted = self._read_persisted_record("case_d_001")
        self.assertIsNotNone(persisted)
        self.assertIs(persisted["settlement"]["acquired"], False)

    def test_case_e_unknown_with_financial_facts(self):
        """CASE E — acquired=None + profit>0 / clearing / leader 等 => persisted None."""
        ctx = {
            "id": "case_e_001",
            "isSettlement": True,
            "settlementReady": True,
            "settlementFinalized": False,
            "winner": None,
            "leaderBid": 300000,
            "leaderName": "汐",
            "settlementData": {
                "isSettlement": True,
                "clearingPrice": 300000,
                "actualTotal": 450000,
                "profit": 150000,
            },
        }
        res = self.archiver.archive_match(ctx)
        self.assertIsNotNone(res)
        self.assertIsNone(res["settlement"]["acquired"])
        persisted = self._read_persisted_record("case_e_001")
        self.assertIsNotNone(persisted)
        self.assertIsNone(persisted["settlement"]["acquired"])

    def test_case_f_explicit_false_not_overridden_by_matching_names(self):
        """CASE F — 显式 acquired=False + winner_name/raw_my_name 看起来相等 => 仍然 False."""
        ctx = {
            "id": "case_f_001",
            "isSettlement": True,
            "settlementReady": True,
            "settlementFinalized": False,
            "winner": "汐",
            "myName": "汐",
            "isAcquired": False,
            "box": "实木宝箱",
            "fieldCondition": "normal",
            "settlementData": {
                "isSettlement": True,
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "winner": "汐",
            },
        }
        res = self.archiver.archive_match(ctx)
        self.assertIsNotNone(res)
        self.assertIs(res["settlement"]["acquired"], False)
        persisted = self._read_persisted_record("case_f_001")
        self.assertIsNotNone(persisted)
        self.assertIs(persisted["settlement"]["acquired"], False)

    def test_case_g_explicit_true_not_overridden_by_differing_names(self):
        """CASE G — 显式 acquired=True + winner_name/raw_my_name 看起来不等 => 仍然 True."""
        ctx = {
            "id": "case_g_001",
            "isSettlement": True,
            "settlementReady": True,
            "settlementFinalized": False,
            "winner": "汐",
            "myName": "PLAYER_LOCAL",
            "isAcquired": True,
            "box": "实木宝箱",
            "fieldCondition": "normal",
            "settlementData": {
                "isSettlement": True,
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "winner": "汐",
            },
        }
        res = self.archiver.archive_match(ctx)
        self.assertIsNotNone(res)
        self.assertIs(res["settlement"]["acquired"], True)
        persisted = self._read_persisted_record("case_g_001")
        self.assertIsNotNone(persisted)
        self.assertIs(persisted["settlement"]["acquired"], True)

    def test_nested_settlement_acquired_authority(self):
        """Authority passed in settlement.acquired or settlementData.acquired is honored."""
        ctx = {
            "id": "nested_001",
            "isSettlement": True,
            "settlementReady": True,
            "settlementFinalized": False,
            "box": "实木宝箱",
            "fieldCondition": "normal",
            "settlement": {
                "acquired": True,
            },
            "settlementData": {
                "isSettlement": True,
                "clearingPrice": 100000,
                "actualTotal": 150000,
                "winner": "汐",
            },
        }
        res = self.archiver.archive_match(ctx)
        self.assertIsNotNone(res)
        self.assertIs(res["settlement"]["acquired"], True)


if __name__ == "__main__":
    unittest.main()
