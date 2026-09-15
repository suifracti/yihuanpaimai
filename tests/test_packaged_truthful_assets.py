"""Verify packaged distribution assets for Cut 5: Truthful Main + Minimal Read-only History v1."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_CORE = PROJECT_ROOT / "dist" / "cut5_truthful_main" / "异环拍卖助手" / "_internal" / "core"


class PackagedAssetsTests(unittest.TestCase):
    def test_packaged_assets_contain_truthful_main_and_history(self):
        self.assertTrue(DIST_CORE.is_dir(), f"Dist core directory missing: {DIST_CORE}")

        html = (DIST_CORE / "main_window.html").read_text(encoding="utf-8")
        js = (DIST_CORE / "main_window.js").read_text(encoding="utf-8")
        css = (DIST_CORE / "main_window.css").read_text(encoding="utf-8")

        self.assertNotIn("mockDashboardState", js)
        self.assertNotIn("mockPredictionPerformanceState", js)
        self.assertNotIn("renderMockDashboard", js)
        self.assertNotIn("renderMockPredictionPerformance", js)
        self.assertNotIn("2,420", js)
        self.assertNotIn("2,420", html)
        self.assertNotIn("B+", js)
        self.assertNotIn("B+", html)
        self.assertNotIn("部分演示", html)

        self.assertIn("renderHistory", js)
        self.assertIn("renderOverview", js)
        self.assertIn('data-view-target="history"', html)
        self.assertIn('data-view-page="history"', html)
        self.assertIn("History Admission Policy v1", html)


if __name__ == "__main__":
    unittest.main()
