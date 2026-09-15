# -*- coding: utf-8 -*-
"""Verification of 6-rarity rows and 4-column alignment for Main and HUD."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"


class TestQualityMatrixLayout(unittest.TestCase):
    def setUp(self):
        self.main_html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        self.overlay_html = (CORE_DIR / "overlay_alpha.html").read_text(encoding="utf-8")

    def test_main_window_quality_matrix(self):
        # 1. Verify no duplicate IDs for quality inputs
        expected_ids = [
            "match-input-gold-count", "match-input-gold-avg", "match-input-gold-grid",
            "match-input-purple-count", "match-input-purple-avg", "match-input-purple-grid",
            "match-input-blue-count", "match-input-blue-avg", "match-input-blue-grid",
            "match-input-green-count", "match-input-green-avg", "match-input-green-grid",
            "match-input-white-count", "match-input-white-avg", "match-input-white-grid",
            "match-input-red-count", "match-input-red-grid",
            # Global
            "match-input-q", "match-input-total-items", "match-input-total-grid",
            "match-input-intel-cost", "match-input-other-cost", "match-input-future-cost",
            "match-input-welfare-received", "match-input-private-bid-cap", "match-input-bid-action-count",
            "match-sparkle-count", "match-sparkle-names"
        ]
        for field_id in expected_ids:
            matches = len(re.findall(rf'id="{field_id}"', self.main_html))
            self.assertEqual(matches, 1, f"Main window should have exactly one id='{field_id}', got {matches}")

        # 2. Verify order of 6 qualities in quality-matrix-table
        matrix_match = re.search(r'<div class="quality-matrix-table">(.*?)</div>\s*</div>\s*</details>', self.main_html, re.DOTALL)
        self.assertIsNotNone(matrix_match, "quality-matrix-table must exist in main_window.html")
        matrix_html = matrix_match.group(1)

        # Check rarity badge order: 金 -> 紫 -> 蓝 -> 绿 -> 白 -> 红
        badges = re.findall(r'<span class="rarity-pill is-([a-z]+)">([金紫蓝绿白红])</span>', matrix_html)
        expected_order = [("gold", "金"), ("purple", "紫"), ("blue", "蓝"), ("green", "绿"), ("white", "白"), ("red", "红")]
        self.assertEqual(badges, expected_order, f"Rarity badges must be strictly in order 金->紫->蓝->绿->白->红, got {badges}")

        # Check that red has placeholder for avg
        self.assertIn('class="quality-matrix-placeholder"', matrix_html)

        # 3. Verify global parameters are in match-card-global-params, not in matrix
        global_card = re.search(r'id="match-card-global-params".*?(?=<div class="match-card"|<details)', self.main_html, re.DOTALL)
        self.assertIsNotNone(global_card)
        self.assertIn('id="match-input-q"', global_card.group(0))
        self.assertIn('id="match-input-total-items"', global_card.group(0))
        self.assertIn('id="match-input-total-grid"', global_card.group(0))
        self.assertNotIn('id="match-input-total-items"', matrix_html)

    def test_overlay_quality_matrix(self):
        expected_ids = [
            "goldCountInput", "goldAvgInput", "goldGridInput",
            "purpleCountInput", "purpleAvgInput", "purpleGridInput",
            "blueCountInput", "blueAvgInput", "blueGridInput",
            "greenCountInput", "greenAvgInput", "greenGridInput",
            "whiteCountInput", "whiteAvgInput", "whiteGridInput",
            "redCountInput", "redGridInput",
            # Global
            "qInput", "totalItemsInput", "totalGridInput", "leaderBidInput",
            "intelCostInput", "otherCostInput", "futureIncrementalCostInput",
            "welfareReceivedInput", "privateBidCapInput", "bidActionCountInput",
            "sparkleCountInput", "sparkleNamesInput"
        ]
        for field_id in expected_ids:
            matches = len(re.findall(rf'id="{field_id}"', self.overlay_html))
            self.assertEqual(matches, 1, f"HUD overlay should have exactly one id='{field_id}', got {matches}")

        # Check rarity badge order in extraNumericFields
        matrix_match = re.search(r'<div class="quality-matrix-table">(.*?)</div>\s*</details>', self.overlay_html, re.DOTALL)
        self.assertIsNotNone(matrix_match, "quality-matrix-table must exist in overlay_alpha.html")
        matrix_html = matrix_match.group(1)

        badges = re.findall(r'<div class="rarity-badge badge-([a-z]+)" title="[^"]*">([金紫蓝绿白红])</div>', matrix_html)
        expected_order = [("gold", "金"), ("purple", "紫"), ("blue", "蓝"), ("green", "绿"), ("white", "白"), ("red", "红")]
        self.assertEqual(badges, expected_order, f"HUD Rarity badges must be strictly in order 金->紫->蓝->绿->白->红, got {badges}")

        # Check that red has placeholder
        self.assertIn('class="quality-matrix-placeholder"', matrix_html)


if __name__ == "__main__":
    unittest.main()
