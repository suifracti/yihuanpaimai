"""OCR facts must publish before warehouse/settlement identity.

Live 2026-09-07 00:12 video: q arrived 20s after round=1 because
prepare_warehouse_frame ran before OCR, and capture died after a 10s
foreground timeout instead of pausing for Alt+Tab.
"""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from vision_pipeline import SCENE_IN_AUCTION, NTEVisionPipeline
from vision_worker_loop import run_vision_capture_loop


class TestLivePriceCaptureLivenessV1(unittest.TestCase):
    def test_early_path_is_geometry_only(self):
        import main

        class _Pipe:
            current_context = {"scene": "IN_AUCTION", "round": 1, "inAuction": True}

            def _classify_scene_fast(self, _img):
                return {"scene": "IN_AUCTION"}

            def prepare_warehouse_frame(self, _img):
                raise AssertionError("early path must not run warehouse identity")

        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with patch("warehouse_grid_geometry.observe_warehouse_grid", return_value={"grid": {"status": "OK"}}), patch(
            "warehouse_scrollbar_observation.observe_warehouse_scrollbar",
            return_value={"scrollState": "TOP"},
        ), patch(
            "warehouse_scrollbar_observation.warehouse_search_roi",
            return_value=(1314, 216, 1915, 847),
        ):
            payload = main.process_early_warehouse_frame(img, game_hwnd=1, pipeline_inst=_Pipe())
        self.assertIsInstance(payload, dict)
        self.assertTrue(payload.get("warehousePresent"))
        self.assertEqual(payload.get("scrollState"), "TOP")
        self.assertNotIn("warehouseSlots", payload)

    def test_deferred_warehouse_identity_keeps_pending_until_complete(self):
        pipe = NTEVisionPipeline()
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        pipe.current_context["scene"] = SCENE_IN_AUCTION
        pipe._pending_heavy_identity = {"kind": "warehouse", "frame": frame}

        class _Vision:
            calls = 0

            def process_frame(self, _frame):
                self.calls += 1
                return {"slots": [{"trackId": 7}], "totalExpectedVal": 12, "valRange": [1, 2]}

        fake = _Vision()
        pipe._warehouse_vision = fake
        out = pipe.complete_heavy_identity()
        self.assertEqual(fake.calls, 1)
        self.assertEqual(out["warehouseSlots"][0]["trackId"], 7)
        self.assertIsNone(pipe._pending_heavy_identity)

    def test_worker_publishes_ocr_before_identity(self):
        published = []
        stop_flag = {"stop": False}
        order = []

        class _Pipe:
            def process_frame(self, _img, **kwargs):
                if kwargs.get("include_heavy_identity", True):
                    raise AssertionError("worker must defer heavy identity")
                order.append("ocr")
                return {"scene": "IN_AUCTION", "round": 1, "q": 7, "goldAvg": 33538, "currentLeaderBid": 0}

            def complete_heavy_identity(self):
                time.sleep(0.05)
                order.append("identity")
                return {
                    "scene": "IN_AUCTION",
                    "round": 1,
                    "q": 7,
                    "goldAvg": 33538,
                    "warehouseSlots": [{"trackId": 1}],
                }

        pipe = _Pipe()
        frames = [(1, np.zeros((4, 4, 3), dtype=np.uint8), "t0")]

        def _provider():
            if frames:
                return frames.pop(0)
            stop_flag["stop"] = True
            return None, None, ""

        async def _publish(payload):
            published.append(dict(payload))
            if payload.get("warehouseSlots"):
                stop_flag["stop"] = True

        asyncio.run(
            run_vision_capture_loop(
                pipeline=pipe,
                stop_flag=stop_flag,
                frame_provider=_provider,
                publish_fn=_publish,
                fps=50.0,
            )
        )
        self.assertEqual(order, ["ocr", "identity"])
        q_first = next(p for p in published if p.get("q") == 7)
        ident = next(p for p in published if p.get("warehouseSlots"))
        self.assertLess(published.index(q_first), published.index(ident))


if __name__ == "__main__":
    unittest.main()
