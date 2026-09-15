# -*- coding: utf-8 -*-
"""Targeted unit tests for get_current_match_presentation_summary fail-closed acquired presentation."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"

for p in (
    r"C:\Program Files\Python310\Lib\site-packages",
    r"C:\Program Files\Python310\Lib\site-packages\win32",
    r"C:\Program Files\Python310\Lib\site-packages\win32\lib",
    str(PROJECT_ROOT),
    str(CORE_DIR),
    str(APP_DIR),
):
    if p not in sys.path:
        sys.path.insert(0, p)

import os
if hasattr(os, "add_dll_directory"):
    dll_dir = r"C:\Program Files\Python310\Lib\site-packages\pywin32_system32"
    if os.path.exists(dll_dir):
        os.add_dll_directory(dll_dir)

from main import CURRENT_MATCH, get_current_match_presentation_summary


class TestPresentationAcquiredFailClosedV1(unittest.TestCase):
    def setUp(self):
        CURRENT_MATCH.begin_next_match()

    def test_case_a_explicit_true(self):
        """CASE A — isAcquired=True => presentation settlement.acquired=True."""
        CURRENT_MATCH.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 300000,
            "actualTotal": 450000,
            "realizedProfit": 150000,
            "isAcquired": True,
        })
        summary = get_current_match_presentation_summary()
        self.assertIsNotNone(summary.get("settlement"))
        self.assertIs(summary["settlement"]["acquired"], True)

    def test_case_b_explicit_false(self):
        """CASE B — isAcquired=False => presentation settlement.acquired=False."""
        CURRENT_MATCH.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 300000,
            "actualTotal": 450000,
            "realizedProfit": 150000,
            "isAcquired": False,
        })
        summary = get_current_match_presentation_summary()
        self.assertIsNotNone(summary.get("settlement"))
        self.assertIs(summary["settlement"]["acquired"], False)

    def test_case_c_unknown_none(self):
        """CASE C — isAcquired=None, didCurrentUserAcquire=None => presentation settlement.acquired=None."""
        CURRENT_MATCH.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 300000,
            "actualTotal": 450000,
            "realizedProfit": 150000,
        })
        CURRENT_MATCH.facts["isAcquired"] = None
        CURRENT_MATCH.facts["didCurrentUserAcquire"] = None
        summary = get_current_match_presentation_summary()
        self.assertIsNotNone(summary.get("settlement"))
        self.assertIsNone(summary["settlement"]["acquired"])
        self.assertNotEqual(summary["settlement"]["acquired"], False)

    def test_case_d_missing_authority(self):
        """CASE D — 两个 acquired authority 字段均缺失 => presentation settlement.acquired=None."""
        CURRENT_MATCH.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 300000,
            "actualTotal": 450000,
        })
        CURRENT_MATCH.facts.pop("isAcquired", None)
        CURRENT_MATCH.facts.pop("didCurrentUserAcquire", None)
        CURRENT_MATCH.facts.pop("acquired", None)
        summary = get_current_match_presentation_summary()
        self.assertIsNotNone(summary.get("settlement"))
        self.assertIsNone(summary["settlement"]["acquired"])
        self.assertNotEqual(summary["settlement"]["acquired"], False)

    def test_case_e_unknown_with_other_facts(self):
        """CASE E — acquired unknown + winner='汐' + profit>0 + clearing/leader 等 => presentation settlement.acquired 仍为 None."""
        CURRENT_MATCH.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 666666,
            "actualTotal": 700000,
            "realizedProfit": 33334,
            "leaderBid": 666666,
            "leaderName": "汐",
            "winner": "汐",
        })
        CURRENT_MATCH.facts["isAcquired"] = None
        CURRENT_MATCH.facts["didCurrentUserAcquire"] = None
        summary = get_current_match_presentation_summary()
        self.assertIsNotNone(summary.get("settlement"))
        self.assertIsNone(summary["settlement"]["acquired"])
        self.assertNotEqual(summary["settlement"]["acquired"], False)

    def test_case_f_explicit_false_not_overridden(self):
        """CASE F — 显式 False + 任意 winner/profit/leader 数据 => 仍为 False."""
        CURRENT_MATCH.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "q": 10,
            "clearingPrice": 666666,
            "actualTotal": 700000,
            "realizedProfit": 33334,
            "leaderBid": 666666,
            "leaderName": "汐",
            "winner": "汐",
            "isAcquired": False,
        })
        summary = get_current_match_presentation_summary()
        self.assertIsNotNone(summary.get("settlement"))
        self.assertIs(summary["settlement"]["acquired"], False)

    def test_did_current_user_acquire_alternative_key(self):
        """didCurrentUserAcquire=True/False is recognized when isAcquired is None."""
        CURRENT_MATCH.apply_facts({
            "venue": "shanhu",
            "box": "实木宝箱",
            "clearingPrice": 200000,
            "actualTotal": 300000,
        })
        CURRENT_MATCH.facts["isAcquired"] = None
        CURRENT_MATCH.facts["didCurrentUserAcquire"] = True
        summary_true = get_current_match_presentation_summary()
        self.assertIs(summary_true["settlement"]["acquired"], True)

        CURRENT_MATCH.facts["didCurrentUserAcquire"] = False
        summary_false = get_current_match_presentation_summary()
        self.assertIs(summary_false["settlement"]["acquired"], False)

    def test_non_boolean_ownership_is_unknown(self):
        for value in ("true", "false", "1", "0", 1, 0, 1.0, {}, [], [True]):
            with self.subTest(value=value):
                CURRENT_MATCH.facts.update({"clearingPrice": 100, "actualTotal": 101,
                                           "realizedProfit": 1, "isAcquired": value})
                summary = get_current_match_presentation_summary()
                self.assertIsNone(summary["settlement"]["acquired"])


if __name__ == "__main__":
    unittest.main()
