"""Real-fixture tests for passive warehouse scrollbar observation."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(CORE_DIR),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from roi_scaler import ROIScaler
from warehouse_scrollbar_observation import (
    CHANGE_CHANGED,
    CHANGE_UNCHANGED,
    STATE_BOTTOM,
    STATE_MIDDLE,
    STATE_TOP,
    STATE_UNKNOWN,
    WarehouseScrollbarObserver,
    observe_warehouse_scrollbar,
    warehouse_search_roi,
)

FIX = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_scrollbar_v1"


def _load(name: str) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(FIX / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(name)
    return img


def _paste_on_canvas(crop: np.ndarray, size=(1920, 1080)) -> np.ndarray:
    canvas = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    x1, y1, x2, y2 = warehouse_search_roi(size[0], size[1])
    dest = canvas[y1:y2, x1:x2]
    resized = cv2.resize(crop, (dest.shape[1], dest.shape[0]), interpolation=cv2.INTER_AREA)
    canvas[y1:y2, x1:x2] = resized
    return canvas


class WarehouseScrollbarObservationV1Tests(unittest.TestCase):
    def test_live_white_item_border_does_not_hide_thumb(self):
        # 2026-09-08 live settlement evidence fa25907e106306b3...,
        # client crop [1315, 211, 1915, 847]. Old brightest-column
        # selection chose an item border and returned UNKNOWN.
        crop = _load("live_white_border_top.png")
        for scale in (1.0, 2 / 3, 4 / 3):
            frame = cv2.resize(crop, None, fx=scale, fy=scale)
            obs = observe_warehouse_scrollbar(frame, already_cropped=True)
            self.assertEqual(obs["scrollState"], STATE_TOP)
            self.assertGreater(obs["thumbBox"][0], frame.shape[1] * .92)

    def test_cursor_occluding_a_real_thumb_cannot_prove_an_endpoint(self):
        cursor_fixtures = PROJECT_ROOT / "tests/fixtures/warehouse_scrollbar_cursor_v1"
        for name in ("occluded_top.png", "occluded_bottom.png"):
            with self.subTest(frame=name):
                frame = cv2.imdecode(np.frombuffer((cursor_fixtures / name).read_bytes(), dtype=np.uint8),
                                     cv2.IMREAD_COLOR)
                self.assertIsNotNone(frame)
                observation = observe_warehouse_scrollbar(frame, already_cropped=True)
                self.assertEqual(observation["scrollState"], STATE_UNKNOWN)
                self.assertIsNone(observation["thumbBox"])

    def test_wide_bright_region_cannot_prove_a_narrow_scroll_thumb(self):
        frame = np.zeros((630, 600, 3), dtype=np.uint8)
        frame[20:600, 575:595] = 50
        frame[40:180, 575:595] = 220
        observation = observe_warehouse_scrollbar(frame, already_cropped=True)
        self.assertEqual(observation["scrollState"], STATE_UNKNOWN)
        self.assertIsNone(observation["thumbBox"])

    def test_real_top_middle_bottom_and_unknown(self):
        top = observe_warehouse_scrollbar(_load("top_warehouse.png"), already_cropped=True, source_id="top")
        mid = observe_warehouse_scrollbar(_load("middle_warehouse.png"), already_cropped=True, source_id="middle")
        bot = observe_warehouse_scrollbar(_load("bottom_warehouse.png"), already_cropped=True, source_id="bottom")
        unk = observe_warehouse_scrollbar(_load("unknown_warehouse.png"), already_cropped=True, source_id="unknown")
        self.assertEqual(top["scrollState"], STATE_TOP)
        self.assertEqual(mid["scrollState"], STATE_MIDDLE)
        self.assertEqual(bot["scrollState"], STATE_BOTTOM)
        self.assertEqual(unk["scrollState"], STATE_UNKNOWN)
        self.assertLess(top["thumbPosition"], mid["thumbPosition"])
        self.assertLess(mid["thumbPosition"], bot["thumbPosition"])
        self.assertGreater(top["confidence"], 0.5)
        self.assertIsNotNone(top["trackBox"])
        self.assertIsNotNone(top["thumbBox"])

    def test_same_frame_is_unchanged_and_scroll_is_changed(self):
        observer = WarehouseScrollbarObserver()
        first = observer.observe(_load("top_warehouse.png"), already_cropped=True, source_id="t1")
        second = observer.observe(_load("top_warehouse.png"), already_cropped=True, source_id="t2")
        third = observer.observe(_load("middle_warehouse.png"), already_cropped=True, source_id="m1")
        self.assertEqual(first["scrollState"], STATE_TOP)
        self.assertEqual(second["segmentChange"], CHANGE_UNCHANGED)
        self.assertEqual(third["scrollState"], STATE_MIDDLE)
        self.assertEqual(third["segmentChange"], CHANGE_CHANGED)

    def test_reconstructed_and_scaled_viewport_keep_state(self):
        crop = _load("top_warehouse.png")
        full = _paste_on_canvas(crop, (1920, 1080))
        scaled = cv2.resize(full, (1280, 720), interpolation=cv2.INTER_AREA)
        full_obs = observe_warehouse_scrollbar(full, source_id="full1080")
        scaled_obs = observe_warehouse_scrollbar(scaled, source_id="scaled720")
        self.assertEqual(full_obs["scrollState"], STATE_TOP)
        self.assertEqual(scaled_obs["scrollState"], STATE_TOP)
        x1, y1, x2, y2 = warehouse_search_roi(2560, 1440)
        base = ROIScaler.scale_roi("warehouse_board", 2560, 1440)
        self.assertGreater(x2, base[2])
        self.assertGreater(y2, base[3])

    def test_provenance_records_source_and_crops(self):
        manifest = json.loads((FIX / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], "warehouse-scrollbar-fixture-v1")
        self.assertEqual(len(manifest["sourceSha256"]), 64)
        roles = {item["role"] for item in manifest["frames"]}
        self.assertEqual(roles, {"top", "middle", "bottom", "unknown"})
        for item in manifest["frames"]:
            self.assertTrue((FIX / item["file"]).is_file())
            self.assertFalse(item["scaled"])
            self.assertEqual(len(item["cropRect"]), 4)


if __name__ == "__main__":
    unittest.main()
