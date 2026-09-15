# -*- coding: utf-8 -*-
"""Regression evidence for the Manual estimate/advice context boundary."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = REPO_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from venue_box_catalog import load_catalog, solver_context_translation


class TestManualEstimateAdviceContextGateV1(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog()

    def test_all_current_venue_solver_translations_are_catalog_owned(self) -> None:
        self.assertEqual(self.catalog["catalogStatus"], "APPROVED_FOR_ALPHA")
        for venue_id in ("venue-haibei", "venue-shanhu", "venue-zhenzhu"):
            translated = solver_context_translation(
                self.catalog,
                venue_id=venue_id,
                box_id=None,
            )
            self.assertEqual(
                translated["status"],
                "COMPATIBILITY_TRANSLATION",
                venue_id,
            )
            self.assertIsNotNone(translated["venue"])
            self.assertIsNone(translated["box"])
            self.assertEqual(translated["boxStatus"], "UNKNOWN_NO_BOX_EFFECT")

    def test_exact_current_venue_does_not_reproduce_v06_low_tier_priors(self) -> None:
        script = r"""
const engine = require('./core/auction_engine_v06.js');
const pairs = [
  ['海贝场', '初级场 · 海贝场'],
  ['珊瑚场', '中级场 · 珊瑚场'],
  ['真珠场', '高级场 · 真珠场']
];
const rows = pairs.map(([currentVenue, legacyVenue]) => ({
  currentVenue,
  legacyVenue,
  currentMid: engine.lowTierValue({venue: currentVenue}).mid,
  legacyMid: engine.lowTierValue({venue: legacyVenue}).mid
}));
process.stdout.write(JSON.stringify(rows));
"""
        output = subprocess.check_output(
            ["node", "-e", script],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
        )
        rows = {row["currentVenue"]: row for row in json.loads(output)}

        self.assertEqual(rows["海贝场"]["currentMid"], 12000)
        self.assertEqual(rows["海贝场"]["legacyMid"], 8000)
        self.assertEqual(rows["珊瑚场"]["currentMid"], rows["珊瑚场"]["legacyMid"])
        self.assertEqual(rows["真珠场"]["currentMid"], 12000)
        self.assertEqual(rows["真珠场"]["legacyMid"], 30000)

        self.assertNotEqual(rows["海贝场"]["currentMid"], rows["海贝场"]["legacyMid"])
        self.assertNotEqual(rows["真珠场"]["currentMid"], rows["真珠场"]["legacyMid"])


if __name__ == "__main__":
    unittest.main()
