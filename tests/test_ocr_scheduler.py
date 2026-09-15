# -*- coding: utf-8 -*-
"""IN_AUCTION RapidOCR is event/interval scheduled, not every frame."""
import os
import sys
import time
import unittest

import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from vision_pipeline import (
    AUCTION_DYNAMIC_OCR_INTERVAL_S,
    NTEVisionPipeline,
    SCENE_AUCTION_LOADING,
    SCENE_IN_AUCTION,
    SCENE_SETTLEMENT,
)


def _frame(seed=0):
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    img[:, :] = (20, 18, 16)
    tone = 20 if seed < 40 else 220
    img[200:700, 700:1200] = (tone, tone, tone)
    return img


class DummyOcrEngine:
    def __call__(self, *args, **kwargs):
        return [], [0.0, 0.0, 0.0]

    def text_rec(self, crops, *args, **kwargs):
        return [("", 1.0)] * len(crops), [0.0] * len(crops)


class TestOcrScheduler(unittest.TestCase):
    def setUp(self):
        self.pipe = NTEVisionPipeline()
        self.pipe._ocr_engine = DummyOcrEngine()

    def _lock_in_auction(self, **kwargs):
        ctx = {
            "scene": SCENE_IN_AUCTION,
            "inAuction": True,
            "isSettlement": False,
            "round": 1,
            "q": 11,
            "goldAvg": 47286,
            "avg": 47286,
            "purpleAvg": 4357,
            "box": "皮制宝箱 · 高级藏品概率提升",
            "fieldCondition": "standard",
            "timer": 15,
        }
        ctx.update(kwargs)
        self.pipe.current_context.update(ctx)
        self.pipe._match_active = True
        self.pipe._slot_names = {1: "P1", 2: "P2", 3: "P3", 4: "P4"}
        self.pipe._seat_round = 1

    def test_quote_ready_is_not_all_intel_collected(self):
        self._lock_in_auction(purple=None, goldCount=None, totalGrids=None)
        self.assertTrue(self.pipe._official_quote_facts_ready())
        self.assertIsNone(self.pipe.current_context.get("purple"))
        self.assertIsNone(self.pipe.current_context.get("goldCount"))

    def test_q_plus_purple_avg_still_runs_ocr(self):
        self._lock_in_auction(goldAvg=None, avg=None, purpleAvg=4357)
        self.assertFalse(self.pipe._official_quote_facts_ready())
        self.assertTrue(self.pipe._should_run_auction_canvas_ocr(_frame()))

    def test_quote_ready_skips_repeat_same_frame(self):
        self._lock_in_auction()
        img = _frame(3)
        self.pipe._last_auction_ocr_ts = time.monotonic()
        self.pipe._last_intel_sig = self.pipe._intel_region_sig(img)
        before = self.pipe.ocr_skip_count
        self.assertFalse(self.pipe._should_run_auction_canvas_ocr(img))
        self.assertEqual(self.pipe.ocr_skip_count, before + 1)

    def test_quote_ready_rescans_on_interval(self):
        self._lock_in_auction()
        img = _frame(4)
        self.pipe._last_auction_ocr_ts = time.monotonic() - (AUCTION_DYNAMIC_OCR_INTERVAL_S + 0.2)
        self.pipe._last_intel_sig = self.pipe._intel_region_sig(img)
        self.assertTrue(self.pipe._should_run_auction_canvas_ocr(img))

    def test_quote_ready_rescans_when_intel_region_changes(self):
        self._lock_in_auction()
        first = _frame(1)
        second = _frame(80)
        self.pipe._last_auction_ocr_ts = time.monotonic()
        self.pipe._last_intel_sig = self.pipe._intel_region_sig(first)
        self.assertTrue(self.pipe._should_run_auction_canvas_ocr(second))

    def test_busy_never_queues_second_ocr(self):
        self._lock_in_auction(goldAvg=None, avg=None)
        self.pipe._ocr_busy = True
        self.assertFalse(self.pipe._should_run_auction_canvas_ocr(_frame(), force_refresh=False))

    def test_force_refresh_overrides_skip(self):
        self._lock_in_auction()
        img = _frame(2)
        self.pipe._last_auction_ocr_ts = time.monotonic()
        self.pipe._last_intel_sig = self.pipe._intel_region_sig(img)
        self.assertTrue(self.pipe._should_run_auction_canvas_ocr(img, force_refresh=True))

    def test_settlement_and_loading_still_need_ocr(self):
        self.pipe.current_context.update({"scene": SCENE_SETTLEMENT, "isSettlement": True})
        self.assertTrue(self.pipe._should_run_auction_canvas_ocr(_frame()))
        self.pipe.current_context.update({"scene": SCENE_AUCTION_LOADING, "isSettlement": False})
        self.assertTrue(self.pipe._should_run_auction_canvas_ocr(_frame()))

    def test_process_frame_skips_canvas_ocr_when_quote_ready(self):
        self._lock_in_auction()
        img = _frame(5)
        self.pipe._full_canvas_frame_count = 1
        self.pipe._last_auction_ocr_ts = time.monotonic()
        self.pipe._last_intel_sig = self.pipe._intel_region_sig(img)
        self.pipe.ocr_skip_count = 1
        before_skip = self.pipe.ocr_skip_count
        ctx = self.pipe.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_IN_AUCTION)
        self.assertEqual(ctx["q"], 11)
        self.assertEqual(ctx["goldAvg"], 47286)
        self.assertGreater(self.pipe.ocr_skip_count, before_skip)
        self.assertFalse(self.pipe._should_run_auction_canvas_ocr(img))


if __name__ == "__main__":
    unittest.main()
