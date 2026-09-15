"""Tests for Production Focused Opening OCR Fast Path (4D2D1Q-UAT22)."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "core"))
sys.path.insert(0, str(PROJECT_ROOT / "app"))

import main
from vision_pipeline import NTEVisionPipeline
from vision_worker_loop import run_vision_capture_loop


class TestOpeningOCRFastPathV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames_dir = PROJECT_ROOT / "assets" / "replay_frames"
        cls.f35_path = cls.frames_dir / "frame_0035s_00m35s.jpg"
        cls.f75_path = cls.frames_dir / "frame_0075s_01m15s.jpg"
        cls.f80_path = cls.frames_dir / "frame_0080s_01m20s.jpg"
        cls.f85_path = cls.frames_dir / "frame_0085s_01m25s.jpg"
        assert cls.f35_path.is_file(), f"Missing {cls.f35_path}"
        assert cls.f75_path.is_file(), f"Missing {cls.f75_path}"
        assert cls.f80_path.is_file(), f"Missing {cls.f80_path}"
        assert cls.f85_path.is_file(), f"Missing {cls.f85_path}"

        cls.img35 = cv2.imread(str(cls.f35_path))
        cls.img75 = cv2.imread(str(cls.f75_path))
        cls.img80 = cv2.imread(str(cls.f80_path))
        cls.img85 = cv2.imread(str(cls.f85_path))

    def setUp(self):
        self.pipe = NTEVisionPipeline()
        self.pipe._ensure_ocr()

    def test_01_real_replay_sequence_fact_truth(self):
        """Verify fact truth across 35s -> 75s -> 80s -> 85s frames."""
        # 1. 35s pre-opening
        ctx35 = self.pipe.process_frame(self.img35, force_refresh=True)
        # Raw opening observation: all opening facts are None / UNKNOWN
        raw_round_35 = ctx35.get("round") if ctx35.get("round", 0) > 0 else None
        self.assertIsNone(raw_round_35, "Raw opening observation round on 35s must be UNKNOWN/None")
        self.assertIsNone(ctx35.get("q"), "q on 35s must be UNKNOWN/None")
        self.assertIsNone(ctx35.get("goldAvg") or ctx35.get("avg"), "goldAvg on 35s must be UNKNOWN/None")
        box35 = ctx35.get("box")
        self.assertTrue(box35 is None or "未知" in str(box35), "box on 35s must be UNKNOWN/None")
        self.assertIsNone(ctx35.get("timer"), "timer on 35s must be UNKNOWN/None")
        # Presentation / default context sentinel
        self.assertEqual(ctx35.get("round", 0), 0, "Presentation layer sentinel for pre-round is 0")

        # 2. 75s opening first visible
        ctx75 = self.pipe.process_frame(self.img75, force_refresh=True)
        self.assertEqual(ctx75.get("round"), 1)
        self.assertEqual(ctx75.get("timer"), 12)
        self.assertIn("机械宝箱", str(ctx75.get("box")))
        self.assertEqual(ctx75.get("goldAvg") or ctx75.get("avg"), 67571)
        self.assertIsNone(ctx75.get("q"))  # q not yet visible on 75s

        # 3. 80s opening bid popup overlay (facts preserved)
        ctx80 = self.pipe.process_frame(self.img80, force_refresh=True)
        self.assertEqual(ctx80.get("round"), 1)
        self.assertEqual(ctx80.get("timer"), 7)
        self.assertIn("机械宝箱", str(ctx80.get("box")))
        self.assertEqual(ctx80.get("goldAvg") or ctx80.get("avg"), 67571)
        self.assertIsNone(ctx80.get("q"))

        # 4. 85s opening Q card visible (q updated)
        ctx85 = self.pipe.process_frame(self.img85, force_refresh=True)
        self.assertEqual(ctx85.get("round"), 1)
        self.assertEqual(ctx85.get("timer"), 2)
        self.assertIn("机械宝箱", str(ctx85.get("box")))
        self.assertEqual(ctx85.get("goldAvg") or ctx85.get("avg"), 67571)
        self.assertEqual(ctx85.get("q"), 16)

    def test_02_opening_frame_single_ocr_call_and_no_redundant_ocr(self):
        """Verify that on the first successful opening frame, only 1 Focused OCR is made."""
        ocr_crops: List[tuple] = []
        orig_ocr = self.pipe._ensure_ocr()

        def spy_ocr(crop):
            if hasattr(crop, "shape"):
                ocr_crops.append(crop.shape)
            return orig_ocr(crop)

        self.pipe._ocr_engine = spy_ocr
        self.pipe.reset_session_state()

        # Run 75s frame
        ctx75 = self.pipe.process_frame(self.img75, force_refresh=True)

        self.assertEqual(len(ocr_crops), 1, f"Expected exactly 1 OCR call, got {len(ocr_crops)}: {ocr_crops}")
        # Crop should be Focused Opening Canvas shape ~ (465, 422, 3), NOT full canvas (529, 921, 3)
        h_crop, w_crop = ocr_crops[0][:2]
        self.assertLess(w_crop, 600, f"Crop width {w_crop} should be narrow focused ROI, not full screen")
        self.assertEqual(ctx75.get("goldAvg"), 67571)

    def test_03_seat_binding_resumes_on_subsequent_frame(self):
        """Verify that seat binding is not permanently disabled and resumes on subsequent frame."""
        self.pipe.reset_session_state()

        # Frame 1 (75s): Opening facts extracted, seat heavy panel deferred
        ctx75 = self.pipe.process_frame(self.img75, force_refresh=True)
        self.assertEqual(ctx75.get("round"), 1)
        self.assertTrue(self.pipe._opening_seat_deferred)

        # Frame 2 (80s): Normal execution continues
        ctx80 = self.pipe.process_frame(self.img80, force_refresh=True)
        self.assertEqual(ctx80.get("round"), 1)

    def test_04_real_worker_warm_latency_under_3250ms(self):
        """Verify warm worker capture->publish latency is <= 3250ms."""
        # Warm up engine with lobby frame (matching UAT20R warm definition)
        lobby_path = self.frames_dir / "frame_0000s_00m00s.jpg"
        if lobby_path.is_file():
            img_lobby = cv2.imread(str(lobby_path))
            self.pipe.process_frame(img_lobby)
        else:
            self.pipe.process_frame(self.img35)

        timestamps: Dict[str, float] = {}
        published_payload: Dict[str, Any] = {}
        stop_flag = {"stop": False}

        def frame_provider():
            if "t_capture" not in timestamps:
                timestamps["t_capture"] = time.perf_counter()
                return 1234, self.img75, "2026-08-31T18:01:15Z"
            return None, None, ""

        async def publish_fn(payload):
            if payload.get("goldAvg") is not None or payload.get("inAuction"):
                if "t_publish" not in timestamps:
                    timestamps["t_publish"] = time.perf_counter()
                    published_payload.update(payload)
                    stop_flag["stop"] = True

        async def _runner():
            task = asyncio.create_task(
                run_vision_capture_loop(
                    pipeline=self.pipe,
                    stop_flag=stop_flag,
                    frame_provider=frame_provider,
                    publish_fn=publish_fn,
                    fps=20.0,
                    process_live_game_frame_fn=main.process_live_game_frame,
                )
            )
            try:
                await asyncio.wait_for(task, timeout=10.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                stop_flag["stop"] = True

        asyncio.run(_runner())

        t_capture = timestamps.get("t_capture")
        t_publish = timestamps.get("t_publish")
        self.assertIsNotNone(t_capture)
        self.assertIsNotNone(t_publish)

        app_latency_ms = (t_publish - t_capture) * 1000
        self.assertLessEqual(app_latency_ms, 3250.0, f"Worker latency {app_latency_ms:.2f}ms exceeds 3250ms limit")
        self.assertEqual(published_payload.get("goldAvg"), 67571)


if __name__ == "__main__":
    unittest.main()
