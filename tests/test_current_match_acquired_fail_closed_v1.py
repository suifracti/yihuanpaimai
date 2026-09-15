# -*- coding: utf-8 -*-
"""Targeted unit tests for CurrentMatch.to_canonical() fail-closed acquired authority."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"

for p in (str(PROJECT_ROOT), str(CORE_DIR), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from current_match import CurrentMatch


class TestCurrentMatchAcquiredFailClosedV1(unittest.TestCase):
    def test_case_a_unknown_empty(self):
        """CASE A — 无 acquired，winner=None，无其他事实 => acquired=None."""
        cm = CurrentMatch()
        cm.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "winner": None,
        })
        canonical = cm.to_canonical()
        self.assertIsNone(canonical["settlement"]["acquired"])
        self.assertIsNone(canonical["bidding"]["myFinalBid"])
        self.assertFalse(canonical["bidding"]["isMyLead"])

    def test_case_b_unknown_profit(self):
        """CASE B — 无 acquired，realizedProfit>0 => acquired=None."""
        cm = CurrentMatch()
        cm.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 300000,
            "actualTotal": 450000,
            "realizedProfit": 150000,
        })
        canonical = cm.to_canonical()
        self.assertIsNone(canonical["settlement"]["acquired"])
        self.assertNotEqual(canonical["settlement"]["acquired"], True)
        self.assertNotEqual(canonical["settlement"]["acquired"], False)
        self.assertIsNone(canonical["bidding"]["myFinalBid"])

    def test_case_c_unknown_clearing(self):
        """CASE C — 无 acquired，clearingPrice == leaderBid => acquired=None."""
        cm = CurrentMatch()
        cm.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 500000,
            "actualTotal": 480000,
            "realizedProfit": -20000,
            "leaderBid": 500000,
        })
        canonical = cm.to_canonical()
        self.assertIsNone(canonical["settlement"]["acquired"])
        self.assertNotEqual(canonical["settlement"]["acquired"], True)
        self.assertNotEqual(canonical["settlement"]["acquired"], False)
        self.assertIsNone(canonical["bidding"]["myFinalBid"])

    def test_case_d_unknown_leader(self):
        """CASE D — 无 acquired，leaderName="汐" => acquired=None."""
        cm = CurrentMatch()
        cm.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 500000,
            "actualTotal": 480000,
            "realizedProfit": -20000,
            "leaderName": "汐",
        })
        canonical = cm.to_canonical()
        self.assertIsNone(canonical["settlement"]["acquired"])
        self.assertNotEqual(canonical["settlement"]["acquired"], True)
        self.assertNotEqual(canonical["settlement"]["acquired"], False)
        self.assertIsNone(canonical["bidding"]["myFinalBid"])

    def test_case_e_explicit_true(self):
        """CASE E — 显式 isAcquired=True => acquired=True."""
        cm = CurrentMatch()
        cm.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 300000,
            "actualTotal": 450000,
            "realizedProfit": 150000,
            "isAcquired": True,
        })
        canonical = cm.to_canonical()
        self.assertIs(canonical["settlement"]["acquired"], True)
        self.assertEqual(canonical["bidding"]["myFinalBid"], 300000)
        self.assertTrue(canonical["bidding"]["isMyLead"])

    def test_case_f_explicit_false(self):
        """CASE F — 显式 isAcquired=False => acquired=False."""
        cm = CurrentMatch()
        cm.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 300000,
            "actualTotal": 450000,
            "realizedProfit": 150000,
            "isAcquired": False,
        })
        canonical = cm.to_canonical()
        self.assertIs(canonical["settlement"]["acquired"], False)
        self.assertIsNone(canonical["bidding"]["myFinalBid"])
        self.assertFalse(canonical["bidding"]["isMyLead"])

    def test_case_g_explicit_false_not_overridden_by_finance(self):
        """CASE G — 显式 acquired=False，同时 profit>0 / clearing==leaderBid => 仍然 acquired=False."""
        cm = CurrentMatch()
        cm.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 300000,
            "leaderBid": 300000,
            "actualTotal": 450000,
            "realizedProfit": 150000,
            "acquired": False,
        })
        canonical = cm.to_canonical()
        self.assertIs(canonical["settlement"]["acquired"], False)
        self.assertIsNone(canonical["bidding"]["myFinalBid"])
        self.assertFalse(canonical["bidding"]["isMyLead"])

    def test_settlement_nested_acquired_authority(self):
        """settlement.acquired passed via nested dict is respected."""
        cm = CurrentMatch()
        cm.apply_facts({
            "settlement": {
                "clearingPrice": 200000,
                "actualTotal": 250000,
                "acquired": True,
            }
        })
        canonical = cm.to_canonical()
        self.assertIs(canonical["settlement"]["acquired"], True)
        self.assertEqual(canonical["bidding"]["myFinalBid"], 200000)

        cm2 = CurrentMatch()
        cm2.apply_facts({
            "settlement": {
                "clearingPrice": 200000,
                "actualTotal": 250000,
                "acquired": False,
                "realizedProfit": 50000,
            }
        })
        canonical2 = cm2.to_canonical()
        self.assertIs(canonical2["settlement"]["acquired"], False)
        self.assertIsNone(canonical2["bidding"]["myFinalBid"])


if __name__ == "__main__":
    unittest.main()
