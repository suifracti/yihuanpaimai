"""Warehouse phase 1: measure the visible board grid, map blobs to cells."""

import os
import sys
import unittest

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from warehouse_vision import WarehouseVisionV1
from roi_scaler import NORMALIZED_ROIS
from vision_pipeline import NTEVisionPipeline, SCENE_IN_AUCTION


def _load(name):
    path = os.path.join(PROJECT_ROOT, "build", "live_auc", name)
    if not os.path.exists(path):
        return None
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


class TestWarehouseGrid(unittest.TestCase):
    def test_board_roi_covers_full_visible_grid(self):
        x1, y1, x2, y2 = NORMALIZED_ROIS["warehouse_board"]
        self.assertGreaterEqual(x1, 0.64)
        self.assertGreaterEqual(x2, 0.95)
        self.assertLessEqual(x2, 0.99)
        self.assertGreaterEqual(y1, 0.16)
        self.assertLessEqual(y2, 0.82)

    def test_t037_grid_maps_blue_to_one_cell(self):
        img = _load("t037.jpg")
        if img is None:
            self.skipTest("t037 missing")
        vis = WarehouseVisionV1()
        state = vis.process_frame(img)
        grid = state.get("grid") or {}
        self.assertGreaterEqual(grid.get("cellW") or 0, 40)
        self.assertGreaterEqual(grid.get("cellH") or 0, 40)
        self.assertLessEqual(grid.get("cellW") or 99, 70)
        self.assertLessEqual(grid.get("cellH") or 99, 70)
        self.assertGreaterEqual(grid.get("cols") or 0, 9)
        self.assertLessEqual(grid.get("cols") or 99, 11)
        self.assertGreaterEqual(grid.get("rows") or 0, 8)

        blues = [s for s in (state.get("slots") or []) if s.get("rarity") == "blue"]
        self.assertTrue(blues, state.get("slots"))
        for slot in blues:
            self.assertLess(slot["w"], 6, slot)
            self.assertLess(slot["h"], 6, slot)
            self.assertNotIn(slot["size"], ("6x2", "6x5", "5x2", "5x6"))
            self.assertIsNotNone(slot.get("col"))
            self.assertIsNotNone(slot.get("row"))

        h, w = img.shape[:2]
        x1, _, x2, _ = NORMALIZED_ROIS["warehouse_board"]
        left, right = int(w * x1) - 2, int(w * x2) + 2
        for slot in state.get("slots") or []:
            box = slot.get("box") or (0, 0, 0, 0)
            self.assertGreaterEqual(box[0], left, slot)
            self.assertLess(box[0], right, slot)
            self.assertLess(slot.get("w") or 0, 6, slot)
            self.assertLess(slot.get("h") or 0, 6, slot)

    def test_t065_blue_stays_one_or_two_cells(self):
        img = _load("t065.jpg")
        if img is None:
            self.skipTest("t065 missing")
        vis = WarehouseVisionV1()
        state = vis.process_frame(img)
        blues = [s for s in (state.get("slots") or []) if s.get("rarity") == "blue"]
        self.assertTrue(blues, state.get("slots"))
        for slot in blues:
            self.assertLess(max(slot["w"], slot["h"]), 6, slot)

    def test_synthetic_grid_period_not_crop_over_ten(self):
        """A 4-column crop must not be treated as 10 columns."""
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        x1, y1, x2, y2 = 1305, 194, 1536, 885
        cell = 56
        ox, oy = 8, 10
        # dark empty cells + one cyan 2x2
        for r in range(12):
            for c in range(4):
                cx1 = x1 + ox + c * cell + 3
                cy1 = y1 + oy + r * cell + 3
                frame[cy1:cy1 + cell - 8, cx1:cx1 + cell - 8] = (18, 18, 18)
        frame[y1 + oy + 3:y1 + oy + 2 * cell - 8, x1 + ox + 3:x1 + ox + 2 * cell - 8] = (210, 140, 20)
        vis = WarehouseVisionV1()
        state = vis.process_frame(frame)
        grid = state.get("grid") or {}
        self.assertAlmostEqual(grid.get("cellW") or 0, 56, delta=8)
        self.assertGreaterEqual(grid.get("cols") or 0, 3)
        self.assertLessEqual(grid.get("cols") or 99, 11)
        blues = [s for s in (state.get("slots") or []) if s.get("rarity") == "blue"]
        self.assertTrue(blues, state)
        self.assertTrue(any(s["w"] == 2 and s["h"] == 2 for s in blues), blues)

    def test_t078_full_board_keeps_cell_period(self):
        img = _load("t078.jpg")
        if img is None:
            self.skipTest("t078 missing")
        vis = WarehouseVisionV1()
        state = vis.process_frame(img)
        grid = state.get("grid") or {}
        self.assertGreaterEqual(grid.get("cols") or 0, 9)
        self.assertLessEqual(grid.get("cols") or 99, 11)
        self.assertGreaterEqual(grid.get("rows") or 0, 8)
        self.assertAlmostEqual(grid.get("cellW") or 0, 56, delta=8)
        self.assertAlmostEqual(grid.get("cellH") or 0, 56, delta=8)
        centers = grid.get("colCenters") or []
        self.assertGreaterEqual(len(centers), 9)
        if len(centers) >= 2:
            pitch = float(np.median(np.diff(centers)))
            self.assertAlmostEqual(pitch, 56, delta=8)

    def test_t078_viewport_slots_are_grid_items(self):
        img = _load("t078.jpg")
        if img is None:
            self.skipTest("t078 missing")
        vis = WarehouseVisionV1()
        state = vis.process_frame(img)
        slots = state.get("slots") or []
        self.assertGreaterEqual(len(slots), 4)
        self.assertTrue(any(s["rarity"] == "blue" and s["w"] == 3 and s["h"] == 3 for s in slots), slots)
        golds = [s for s in slots if s["rarity"] == "gold"]
        self.assertTrue(golds, slots)
        self.assertTrue(any(s["w"] * s["h"] >= 2 for s in golds), golds)
        for slot in slots:
            self.assertIsNotNone(slot.get("col"), slot)
            self.assertIsNotNone(slot.get("row"), slot)
            self.assertLess(slot["w"], 6, slot)
            self.assertLess(slot["h"], 6, slot)
            self.assertNotIn(slot["size"], ("6x2", "6x5", "5x2", "5x6"))
        keys = [(s["col"], s["row"], s["w"], s["h"], s["rarity"]) for s in slots]
        self.assertEqual(len(keys), len(set(keys)), slots)

    def test_t037_t065_have_stable_viewport_slots(self):
        for name, expect_blue in (("t037.jpg", True), ("t065.jpg", True)):
            img = _load(name)
            if img is None:
                self.skipTest(f"{name} missing")
            vis = WarehouseVisionV1()
            state = vis.process_frame(img)
            slots = state.get("slots") or []
            self.assertTrue(slots, name)
            if expect_blue:
                self.assertTrue(any(s["rarity"] == "blue" for s in slots), slots)
            for slot in slots:
                self.assertIsNotNone(slot.get("col"), slot)
                self.assertIsNotNone(slot.get("row"), slot)
                self.assertLess(max(slot["w"], slot["h"]), 6, slot)

    def test_in_auction_scene_and_seats_untouched(self):
        img = _load("t065.jpg")
        if img is None:
            self.skipTest("t065 missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        ctx = pipe.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_IN_AUCTION)
        names = [s.get("name") for s in ctx["seats"]]
        self.assertIn("乐观的摸摸元", names)
        self.assertIn("可可", names)
        self.assertTrue(any(n and "狂澜" in n for n in names))
        self.assertIn("秋星祭02", names)
        self.assertEqual(ctx["currentLeaderBid"], 260544)


if __name__ == "__main__":
    unittest.main()
