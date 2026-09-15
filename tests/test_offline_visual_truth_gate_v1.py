"""Targeted tests for 4D2D1J: Offline Visual Truth Gate v1.

Verifies:
1. Desensitized real auction intel fixtures naturally produce goldCount=4, q=15, purpleAvg=7907.
2. Parser robustness against OCR linebreaks, punctuation, and fragment ordering.
3. Desensitized real settlement client frame naturally produces scene=SETTLEMENT, isSettlement=True, scrollState=MIDDLE.
4. Negative sample verification: auction intel frames are never misclassified as settlement.
5. Production bindings integration on settlement frame activates warehouse capture host.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "real_snapshots_4d2d1j"

for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import cv2
import main
from intel_card_evidence import route_card_text
from snapshot_recognizer import SingleFrameSnapshotRecognizer
from vision_pipeline import NTEVisionPipeline


class TestOfflineVisualTruthGateV1(unittest.TestCase):
    def setUp(self):
        self.recognizer = SingleFrameSnapshotRecognizer()
        self.pipe = NTEVisionPipeline()

    def test_round2_intel_gold_count_natural_recognition(self):
        fixture_p = FIXTURES_DIR / "fixture_round2_intel_cards.png"
        self.assertTrue(fixture_p.exists(), f"Missing fixture: {fixture_p}")
        img = cv2.imread(str(fixture_p))
        self.assertIsNotNone(img)

        res = self.recognizer.process_frame(img)
        self.assertTrue(res.get("ok"))
        facts = res.get("appliedFacts") or {}
        self.assertEqual(facts.get("goldCount"), 4)
        self.assertEqual(facts.get("q"), 15)

    def test_round3_intel_gold_count_and_purple_avg_natural_recognition(self):
        fixture_p = FIXTURES_DIR / "fixture_round3_intel_cards.png"
        self.assertTrue(fixture_p.exists(), f"Missing fixture: {fixture_p}")
        img = cv2.imread(str(fixture_p))
        self.assertIsNotNone(img)

        res = self.recognizer.process_frame(img)
        self.assertTrue(res.get("ok"))
        facts = res.get("appliedFacts") or {}
        self.assertEqual(facts.get("goldCount"), 4)
        self.assertEqual(facts.get("q"), 15)
        self.assertEqual(facts.get("purpleAvg"), 7907)

    def test_gold_count_parser_robustness_against_linebreaks_and_punctuation(self):
        variations = [
            "独家情报\n本局内所有金色品质藏品的总数量为 4 件",
            "【独家情报】本局内所有金色品质藏品总数量为4件。",
            "独家情报 NTE 本局内所有金色品质藏品总数量为4件",
            "本局内所有金色品质藏品 的 总数量 为 4 件",
            "独家情报：本局内所有金色品质藏品的总数量为：4件",
            "独家情报\n本局内\n所有金色品质藏品\n总数量为4件",
        ]
        for text in variations:
            routed = route_card_text(text)
            obs = {name: val for name, val, _ in routed}
            self.assertEqual(obs.get("goldCount"), 4, f"Failed on text variation: {text!r}")

    def test_settlement_natural_recognition_and_honest_scroll_state(self):
        fixture_p = FIXTURES_DIR / "fixture_settlement_client_sanitized.png"
        self.assertTrue(fixture_p.exists(), f"Missing fixture: {fixture_p}")
        img = cv2.imread(str(fixture_p))
        self.assertIsNotNone(img)

        res = None
        for _ in range(5):
            res = main.process_live_game_frame(
                img,
                game_hwnd=12345,
                pipeline_inst=self.pipe,
            )

        self.assertIsNotNone(res)
        self.assertEqual(res.get("scene"), "SETTLEMENT")
        self.assertTrue(res.get("isSettlement"))
        self.assertIsNotNone(res.get("warehouseRoi"))
        self.assertEqual(res.get("scrollState"), "MIDDLE")

    def test_negative_samples_not_misclassified_as_settlement(self):
        for fname in ["fixture_round2_intel_cards.png", "fixture_round3_intel_cards.png"]:
            fixture_p = FIXTURES_DIR / fname
            self.assertTrue(fixture_p.exists())
            img = cv2.imread(str(fixture_p))
            pipe = NTEVisionPipeline()
            res = None
            for _ in range(3):
                res = main.process_live_game_frame(img, game_hwnd=12345, pipeline_inst=pipe)
            self.assertFalse(res.get("isSettlement"), f"{fname} should not be settlement")
            self.assertNotEqual(res.get("scene"), "SETTLEMENT", f"{fname} should not have scene=SETTLEMENT")

    def test_phase4_real_uat_settlement_frame_detected_from_in_auction(self):
        uat_settlement_frame = (
            PROJECT_ROOT
            / "build"
            / "uat_4ae5fbb_human"
            / "data-root"
            / "evidence"
            / "settlement"
            / "draft_cedfd5dc812144a6b6b17a064a3db511_a60d61c429f0490f.png"
        )
        self.assertTrue(uat_settlement_frame.exists(), f"missing {uat_settlement_frame}")
        img = cv2.imread(str(uat_settlement_frame))
        self.assertIsNotNone(img)

        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        pipe.current_context["scene"] = "IN_AUCTION"
        pipe.current_context["inAuction"] = True

        ctx = pipe.process_frame(
            img,
            captured_at="2026-09-02T16:16:23.560323+08:00",
            record_stable_key="draft_cedfd5dc812144a6b6b17a064a3db511",
        )

        self.assertEqual(ctx.get("scene"), "SETTLEMENT")
        self.assertTrue(ctx.get("isSettlement"))
        settle_data = ctx.get("settlementData")
        self.assertIsInstance(settle_data, dict)
        self.assertEqual(settle_data.get("clearingPrice"), 400000)
        self.assertEqual(settle_data.get("actualTotal"), 322236)
        self.assertEqual(settle_data.get("profit"), -77764)

    def test_production_bindings_integration_on_settlement_frame(self):
        fixture_p = FIXTURES_DIR / "fixture_settlement_client_sanitized.png"
        img = cv2.imread(str(fixture_p))
        pipe = NTEVisionPipeline()
        for _ in range(5):
            hud = main.process_live_game_frame(img, game_hwnd=12345, pipeline_inst=pipe)

        main.LATEST_PAYLOAD.update(hud)
        bindings = main.get_production_warehouse_bindings()
        self.assertEqual(bindings["scene"], "SETTLEMENT")
        self.assertTrue(bindings["isSettlement"])
        self.assertTrue(bindings["stable"])
        self.assertEqual(bindings["hwnd"], 12345)
        self.assertEqual(bindings["scrollState"], "MIDDLE")

        host = main.WAREHOUSE_CAPTURE_HOST
        payload = host.presentation_payload()
        self.assertTrue(payload["available"])
        self.assertEqual(payload["state"], "IDLE")


if __name__ == "__main__":
    unittest.main()
