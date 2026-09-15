"""Targeted end-to-end tests for 4D2D1A3: Real Runtime Observation Publish.

Tests that calling the exact production process_live_game_frame handler on real
warehouse fixtures naturally publishes scrollState, warehouseRoi, gameHwnd,
and merges CurrentMatch authority into recordStableKey, without manual pre-filling
or manual LATEST_PAYLOAD.update mocking.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import main
from vision_pipeline import NTEVisionPipeline
from warehouse_capture_arming import (
    CONFIRM_CAPTION,
    REASON_NOT_SETTLEMENT,
    REASON_PREPARED,
    REASON_START_REQUIRES_TOP,
)
from warehouse_capture_host import (
    STATE_DRIVER_NOT_CONFIGURED,
    STATE_IDLE,
    WarehouseCaptureHost,
)
from warehouse_scrollbar_observation import (
    STATE_BOTTOM,
    STATE_MIDDLE,
    STATE_TOP,
    warehouse_search_roi,
)

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_scrollbar_v1"


def _load_fixture(name: str) -> np.ndarray:
    path = FIXTURES_DIR / name
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Fixture not found: {path}")
    return img


def _compose_full_screen(crop: np.ndarray, width: int = 1920, height: int = 1080) -> np.ndarray:
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x1, y1, x2, y2 = warehouse_search_roi(width, height)
    resized = cv2.resize(crop, (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA)
    canvas[y1:y2, x1:x2] = resized
    return canvas


class TestWarehouseRealRuntimeObservationPublish4D2D1A3(unittest.TestCase):
    def setUp(self):
        main.LATEST_PAYLOAD.clear()
        main.CURRENT_MATCH.begin_next_match()

    def tearDown(self):
        main.LATEST_PAYLOAD.clear()

    def test_real_top_fixture_runtime_handler_to_eligibility(self):
        # 1. Provide only real TOP fixture canvas, fake game HWND, and CurrentMatch authority
        top_crop = _load_fixture("top_warehouse.png")
        full_frame = _compose_full_screen(top_crop, 1920, 1080)
        expected_match_id = main.CURRENT_MATCH.id
        self.assertTrue(len(expected_match_id) > 0)

        # 2. Configure pipeline with settlement scene
        pipe = NTEVisionPipeline()
        pipe.current_context["scene"] = "SETTLEMENT"
        pipe.current_context["isSettlement"] = True
        pipe.current_context["hadSettlement"] = True
        pipe.current_context["settlementReady"] = True
        pipe.current_context["settlementData"] = {"isSettlement": True, "stable": True}

        # 3. Call the single production live-frame runtime handler
        hud_payload = main.process_live_game_frame(
            full_frame,
            game_hwnd=12345,
            pipeline_inst=pipe,
        )

        # 4. Verify that the production handler naturally published all fields into payload & LATEST_PAYLOAD
        self.assertEqual(hud_payload["scene"], "SETTLEMENT")
        self.assertTrue(hud_payload["isSettlement"])
        self.assertEqual(hud_payload["scrollState"], STATE_TOP)
        self.assertEqual(hud_payload["warehouseRoi"], warehouse_search_roi(1920, 1080))
        self.assertEqual(hud_payload["gameHwnd"], 12345)
        self.assertEqual(hud_payload["recordStableKey"], expected_match_id)

        self.assertEqual(main.LATEST_PAYLOAD.get("scrollState"), STATE_TOP)
        self.assertEqual(main.LATEST_PAYLOAD.get("recordStableKey"), expected_match_id)

        # 5. Verify get_production_warehouse_bindings() authoritative contract
        bindings = main.get_production_warehouse_bindings()
        self.assertEqual(bindings["scene"], "SETTLEMENT")
        self.assertTrue(bindings["isSettlement"])
        self.assertTrue(bindings["stable"])
        self.assertEqual(bindings["recordStableKey"], expected_match_id)
        self.assertEqual(bindings["scrollState"], STATE_TOP)
        self.assertEqual(bindings["warehouseRoi"], warehouse_search_roi(1920, 1080))
        self.assertEqual(bindings["hwnd"], 12345)

        # 6. Verify host is available and presentation is IDLE
        host = main.WAREHOUSE_CAPTURE_HOST
        self.assertTrue(host.available)
        self.assertEqual(host.presentation().state, STATE_IDLE)
        self.assertEqual(host.presentation().message, "采集完整仓库")

        # 7. Verify 2-step prepare() succeeds with confirm caption & valid arming token
        prepared = host.prepare()
        self.assertTrue(prepared["ok"])
        self.assertEqual(prepared["reason"], REASON_PREPARED)
        self.assertEqual(prepared["confirmCaption"], CONFIRM_CAPTION)
        self.assertIsNotNone(prepared.get("armingToken"))

    def test_real_middle_fixture_runtime_handler_requires_top(self):
        mid_crop = _load_fixture("middle_warehouse.png")
        full_frame = _compose_full_screen(mid_crop, 1920, 1080)

        pipe = NTEVisionPipeline()
        pipe.current_context["scene"] = "SETTLEMENT"
        pipe.current_context["isSettlement"] = True
        pipe.current_context["hadSettlement"] = True
        pipe.current_context["settlementReady"] = True
        pipe.current_context["settlementData"] = {"isSettlement": True, "stable": True}

        # Call production runtime handler
        hud_payload = main.process_live_game_frame(
            full_frame,
            game_hwnd=12345,
            pipeline_inst=pipe,
        )
        self.assertEqual(hud_payload["scrollState"], STATE_MIDDLE)

        host = main.WAREHOUSE_CAPTURE_HOST
        self.assertTrue(host.available)
        prepared = host.prepare()
        self.assertFalse(prepared["ok"])
        self.assertEqual(prepared["reason"], REASON_START_REQUIRES_TOP)
        self.assertIsNone(prepared.get("armingToken"))

    def test_lobby_scene_runtime_handler_fails_closed(self):
        # Empty / black frame in lobby
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        pipe = NTEVisionPipeline()
        pipe.current_context["scene"] = "AUCTION_LOBBY"
        pipe.current_context["inLobby"] = True
        pipe.current_context["isSettlement"] = False

        hud_payload = main.process_live_game_frame(
            frame,
            game_hwnd=12345,
            pipeline_inst=pipe,
        )
        self.assertEqual(hud_payload["scene"], "AUCTION_LOBBY")
        self.assertFalse(hud_payload["isSettlement"])

        bindings = main.get_production_warehouse_bindings()
        self.assertEqual(bindings["scene"], "AUCTION_LOBBY")
        self.assertFalse(bindings["isSettlement"])

        host = main.WAREHOUSE_CAPTURE_HOST
        self.assertFalse(host.available)
        self.assertEqual(host.presentation().state, STATE_DRIVER_NOT_CONFIGURED)
        prepared = host.prepare()
        self.assertFalse(prepared["ok"])
        self.assertEqual(prepared["reason"], REASON_NOT_SETTLEMENT)

    def test_missing_stable_key_runtime_handler_fails_closed(self):
        top_crop = _load_fixture("top_warehouse.png")
        full_frame = _compose_full_screen(top_crop, 1920, 1080)

        # Empty match ID authority
        main.CURRENT_MATCH.id = ""

        pipe = NTEVisionPipeline()
        pipe.current_context["scene"] = "SETTLEMENT"
        pipe.current_context["isSettlement"] = True
        pipe.current_context["hadSettlement"] = True
        pipe.current_context["settlementReady"] = True
        pipe.current_context["settlementData"] = {"isSettlement": True, "stable": True}

        hud_payload = main.process_live_game_frame(
            full_frame,
            game_hwnd=12345,
            pipeline_inst=pipe,
        )
        self.assertEqual(hud_payload["recordStableKey"], "")

        bindings = main.get_production_warehouse_bindings()
        self.assertEqual(bindings["recordStableKey"], "")


if __name__ == "__main__":
    unittest.main()
