# -*- coding: utf-8 -*-
"""Targeted unit tests for CurrentMatch.to_canonical() fail-closed winner authority."""

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


class TestCurrentMatchWinnerFailClosedV1(unittest.TestCase):
    def test_case_a_explicit_winner(self):
        """CASE A — explicit winner: input winner='汐' => canonical settlement.winner='汐'."""
        cm = CurrentMatch()
        cm.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 666666,
            "actualTotal": 631993,
            "realizedProfit": -34673,
            "winner": "汐",
        })
        canonical = cm.to_canonical()
        self.assertEqual(canonical["settlement"]["winner"], "汐")
        self.assertEqual(canonical["bidding"]["leaderName"], "汐")

    def test_case_b_no_winner_profit_positive(self):
        """CASE B — no winner + profit > 0 => canonical settlement.winner=None, no synthetic '玩家本人'."""
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
        self.assertIsNone(canonical["settlement"]["winner"])
        self.assertNotEqual(canonical["settlement"]["winner"], "玩家本人")
        self.assertIsNone(canonical["bidding"]["leaderName"])
        self.assertNotEqual(canonical["bidding"]["leaderName"], "玩家本人")

    def test_case_c_no_winner_clearing_equals_leader_bid(self):
        """CASE C — no winner + clearing == leaderBid => canonical settlement.winner=None, no synthetic '玩家本人'."""
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
        self.assertIsNone(canonical["settlement"]["winner"])
        self.assertNotEqual(canonical["settlement"]["winner"], "玩家本人")
        self.assertIsNone(canonical["bidding"]["leaderName"])
        self.assertNotEqual(canonical["bidding"]["leaderName"], "玩家本人")

    def test_case_d_no_winner_leader_name_present(self):
        """CASE D — no winner + leaderName present => canonical settlement.winner=None."""
        cm = CurrentMatch()
        cm.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 500000,
            "actualTotal": 480000,
            "realizedProfit": -20000,
        })
        # Simulate snap containing leaderName without winner fact
        cm.facts["leaderName"] = "PLAYER_LOCAL"
        canonical = cm.to_canonical()
        self.assertIsNone(canonical["settlement"]["winner"])
        self.assertNotEqual(canonical["settlement"]["winner"], "PLAYER_LOCAL")
        self.assertNotEqual(canonical["settlement"]["winner"], "玩家本人")
        self.assertEqual(canonical["bidding"]["leaderName"], "PLAYER_LOCAL")

    def test_forbidden_placeholder_winner_rejected(self):
        """Forbidden placeholders like '玩家本人' in winner fact are rejected to None."""
        cm = CurrentMatch()
        cm.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 300000,
            "actualTotal": 400000,
            "realizedProfit": 100000,
            "winner": "玩家本人",
        })
        canonical = cm.to_canonical()
        self.assertIsNone(canonical["settlement"]["winner"])
        self.assertIsNone(canonical["bidding"]["leaderName"])


if __name__ == "__main__":
    unittest.main()
