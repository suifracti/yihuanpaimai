# -*- coding: utf-8 -*-
"""Targeted unit tests for get_current_match_presentation_summary fail-closed winner presentation."""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"

for p in (str(PROJECT_ROOT), str(CORE_DIR), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

sys.path.insert(0, r"C:\Program Files\Python310\Lib\site-packages")
sys.path.insert(0, r"C:\Program Files\Python310\Lib\site-packages\win32")
sys.path.insert(0, r"C:\Program Files\Python310\Lib\site-packages\win32\lib")
if hasattr(os, "add_dll_directory"):
    dll_dir = r"C:\Program Files\Python310\Lib\site-packages\pywin32_system32"
    if os.path.isdir(dll_dir):
        os.add_dll_directory(dll_dir)

from current_match import CURRENT_MATCH
from main import get_current_match_presentation_summary


class TestPresentationWinnerFailClosedV1(unittest.TestCase):
    def setUp(self):
        CURRENT_MATCH.begin_next_match()

    def tearDown(self):
        CURRENT_MATCH.begin_next_match()

    def test_case_a_explicit_winner(self):
        """CASE A — explicit winner='汐' => presentation winner => '汐'."""
        CURRENT_MATCH.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 666666,
            "actualTotal": 631993,
            "realizedProfit": -34673,
            "winner": "汐",
        })
        summary = get_current_match_presentation_summary()
        self.assertIsNotNone(summary.get("settlement"))
        self.assertEqual(summary["settlement"]["winner"], "汐")
        self.assertEqual(summary["bidding"]["leader"], "汐")

    def test_case_b_no_winner_profit_positive(self):
        """CASE B — winner=None + profit>0 => presentation winner must NOT be '玩家本人'."""
        CURRENT_MATCH.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 300000,
            "actualTotal": 450000,
            "realizedProfit": 150000,
        })
        summary = get_current_match_presentation_summary()
        self.assertIsNotNone(summary.get("settlement"))
        self.assertIsNone(summary["settlement"]["winner"])
        self.assertNotEqual(summary["settlement"]["winner"], "玩家本人")
        self.assertNotEqual(summary["settlement"]["winner"], "其他玩家")
        self.assertNotEqual(summary["settlement"]["winner"], "对手")

    def test_case_c_no_winner_acquired_like_state(self):
        """CASE C — winner=None + acquired-like state => presentation winner must NOT be '玩家本人'/'其他玩家'/'对手'."""
        CURRENT_MATCH.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 500000,
            "actualTotal": 480000,
            "realizedProfit": -20000,
            "isAcquired": True,
            "leaderBid": 500000,
        })
        summary = get_current_match_presentation_summary()
        self.assertIsNotNone(summary.get("settlement"))
        self.assertIsNone(summary["settlement"]["winner"])
        self.assertNotEqual(summary["settlement"]["winner"], "玩家本人")
        self.assertNotEqual(summary["settlement"]["winner"], "其他玩家")
        self.assertNotEqual(summary["settlement"]["winner"], "对手")

    def test_case_d_no_winner_leader_name_present(self):
        """CASE D — winner=None + leaderName present => presentation settlement winner remains unknown/null/None."""
        CURRENT_MATCH.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 500000,
            "actualTotal": 480000,
            "realizedProfit": -20000,
        })
        CURRENT_MATCH.facts["leaderName"] = "秋星祭02"
        summary = get_current_match_presentation_summary()
        self.assertIsNotNone(summary.get("settlement"))
        self.assertIsNone(summary["settlement"]["winner"])
        self.assertNotEqual(summary["settlement"]["winner"], "秋星祭02")
        self.assertNotEqual(summary["settlement"]["winner"], "玩家本人")
        self.assertEqual(summary["bidding"]["leader"], "秋星祭02")


if __name__ == "__main__":
    unittest.main()
