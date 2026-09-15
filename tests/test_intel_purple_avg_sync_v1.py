# -*- coding: utf-8 -*-
"""
Tests for Phase 15: Sync Observed purpleAvg to CurrentMatch and Canonical.
Validates AC1 through AC7.
"""
import sys
import unittest
from pathlib import Path
import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for p in [str(APP_DIR), str(CORE_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from vision_pipeline import NTEVisionPipeline
from current_match import CURRENT_MATCH
from main import sync_vision_to_current_match, process_live_game_frame

FIXTURE_R2_PATH = PROJECT_ROOT / "tests" / "fixtures" / "intel_card_evidence_v1" / "r2_viewport.png"


class TestIntelPurpleAvgSyncV1(unittest.TestCase):

    def setUp(self):
        CURRENT_MATCH.begin_next_match()

    def test_ac1_ac2_r2_viewport_purple_avg_sync_and_canonical(self):
        """AC1 & AC2: Real r2_viewport fixture extracts purpleAvg=4357 and ingests to CurrentMatch and Canonical."""
        self.assertTrue(FIXTURE_R2_PATH.exists(), f"Fixture missing at {FIXTURE_R2_PATH}")
        img = cv2.imread(str(FIXTURE_R2_PATH))
        self.assertIsNotNone(img)

        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        pipe.current_context["scene"] = "IN_AUCTION"
        pipe.current_context["inAuction"] = True
        pipe.current_context["round"] = 2

        CURRENT_MATCH.apply_facts({"scene": "IN_AUCTION", "inAuction": True, "round": 2})

        process_live_game_frame(img, pipeline_inst=pipe)
        ctx = pipe.current_context

        # Vision pipeline extracts purpleAvg = 4357
        self.assertEqual(ctx.get("purpleAvg"), 4357)

        # AC1: CURRENT_MATCH.facts["purpleAvg"] == 4357
        self.assertEqual(CURRENT_MATCH.facts.get("purpleAvg"), 4357)

        # AC2: CURRENT_MATCH.to_canonical()["qualities"]["purple"]["avg"] == 4357
        canonical = CURRENT_MATCH.to_canonical()
        self.assertEqual(canonical.get("qualities", {}).get("purple", {}).get("avg"), 4357)

    def test_ac3_none_fail_closed(self):
        """AC3: When ctx['purpleAvg'] is None, CURRENT_MATCH.facts['purpleAvg'] remains None (no default injected)."""
        ctx = {
            "scene": "IN_AUCTION",
            "inAuction": True,
            "purpleAvg": None,
            "q": 11,
        }
        sync_vision_to_current_match(ctx)
        self.assertIsNone(CURRENT_MATCH.facts.get("purpleAvg"))
        canonical = CURRENT_MATCH.to_canonical()
        self.assertIsNone(canonical.get("qualities", {}).get("purple", {}).get("avg"))

    def test_ac4_existing_fields_sync_intact(self):
        """AC4: q, goldAvg, and purpleCount continue to sync properly alongside purpleAvg."""
        ctx = {
            "scene": "IN_AUCTION",
            "inAuction": True,
            "q": 12,
            "goldAvg": 74379,
            "purpleCount": 4,
            "purpleAvg": 5200,
        }
        sync_vision_to_current_match(ctx)
        self.assertEqual(CURRENT_MATCH.facts.get("q"), 12)
        self.assertEqual(CURRENT_MATCH.facts.get("goldAvg"), 74379)
        self.assertEqual(CURRENT_MATCH.facts.get("purpleCount"), 4)
        self.assertEqual(CURRENT_MATCH.facts.get("purpleAvg"), 5200)

        canonical = CURRENT_MATCH.to_canonical()
        self.assertEqual(canonical.get("publicIntel", {}).get("q"), 12)
        self.assertEqual(canonical.get("qualities", {}).get("gold", {}).get("avg"), 74379)
        self.assertEqual(canonical.get("qualities", {}).get("purple", {}).get("count"), 4)
        self.assertEqual(canonical.get("qualities", {}).get("purple", {}).get("avg"), 5200)


if __name__ == "__main__":
    unittest.main()
