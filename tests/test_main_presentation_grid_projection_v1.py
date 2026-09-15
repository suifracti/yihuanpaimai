# -*- coding: utf-8 -*-
"""Phase 1: Main presentation projects existing purpleGrid without mutating facts."""

from __future__ import annotations

import os
import sys
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(PROJECT_ROOT, "app")
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
for path in (APP_DIR, CORE_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


class MainPresentationGridProjectionTests(unittest.TestCase):
    def setUp(self):
        from main import CURRENT_MATCH

        CURRENT_MATCH.begin_next_match()

    def tearDown(self):
        from main import CURRENT_MATCH

        CURRENT_MATCH.begin_next_match()

    def test_form_projection_exposes_existing_purple_grid_and_keeps_unsourced_blank(self):
        from main import CURRENT_MATCH, get_current_match_presentation_summary

        CURRENT_MATCH.apply_facts(
            {
                "totalItems": 21,
                "q": 9,
                "purpleGrid": 6,
            },
            source="triggered_snapshot",
        )
        authority = dict(CURRENT_MATCH.facts)

        summary = get_current_match_presentation_summary()
        form = {
            **(summary.get("publicIntel") or {}),
            **(summary.get("facts") or {}),
        }

        self.assertEqual(form.get("totalItems"), 21)
        self.assertEqual(form.get("purpleGrid"), 6)
        self.assertIsNone(form.get("redCount"))
        self.assertIsNone(form.get("goldGrid"))
        self.assertEqual(summary["publicIntel"].get("totalItems"), 21)
        self.assertNotIn("totalItems", summary["facts"])
        self.assertEqual(CURRENT_MATCH.facts.get("purpleGrid"), 6)
        self.assertIsNone(CURRENT_MATCH.facts.get("redCount"))
        self.assertIsNone(CURRENT_MATCH.facts.get("goldGrid"))
        self.assertEqual(CURRENT_MATCH.facts, authority)
        self.assertEqual(summary["qualities"]["purple"]["grid"], 6)
        self.assertIsNone(summary["qualities"]["red"]["count"])
        self.assertIsNone(summary["qualities"]["gold"]["grid"])


if __name__ == "__main__":
    unittest.main()
