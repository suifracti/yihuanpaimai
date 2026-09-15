"""Isolated tests for warehouse grid geometry and occupancy evidence."""

from __future__ import annotations

import json
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

from warehouse_grid_geometry import (
    COMPONENT_KEYS,
    GRID_KEYS,
    STATUS_AMBIGUOUS,
    STATUS_OBSERVED,
    STATUS_OK,
    STATUS_UNKNOWN,
    observe_warehouse_grid,
)
from warehouse_scrollbar_observation import warehouse_search_roi

SCROLL = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_scrollbar_v1"
EXPECT = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_grid_v1" / "expectations.json"
FORBIDDEN_FIELDS = (
    "rarity",
    "name",
    "price",
    "catalog",
    "knownItems",
    "candidate",
    "itemId",
    "quality",
)


def _load(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return image


def _paste(crop: np.ndarray, size=(1920, 1080)) -> np.ndarray:
    canvas = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    x1, y1, x2, y2 = warehouse_search_roi(size[0], size[1])
    dest = canvas[y1:y2, x1:x2]
    canvas[y1:y2, x1:x2] = cv2.resize(crop, (dest.shape[1], dest.shape[0]), interpolation=cv2.INTER_AREA)
    return canvas


class WarehouseGridGeometryV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expect = json.loads(EXPECT.read_text(encoding="utf-8"))
        cls.frames = {item["id"]: item for item in cls.expect["frames"]}

    def _observe(self, frame_id: str):
        spec = self.frames[frame_id]
        path = (EXPECT.parent / spec["file"]).resolve()
        return observe_warehouse_grid(
            _load(path),
            already_cropped=bool(spec.get("alreadyCropped")),
            source_id=frame_id,
            timecode=spec.get("timecodeSec"),
        )

    def test_expectations_are_marked_developer_only(self):
        self.assertEqual(self.expect["kind"], "DEVELOPER_FIXTURE_EXPECTATION")
        self.assertTrue(self.expect["notGroundTruth"])
        self.assertTrue(self.expect["notTrainingLabel"])
        self.assertNotIn("groundTruth", json.dumps(self.expect))

    def test_top_middle_bottom_recover_ten_columns(self):
        for frame_id in ("top", "middle", "bottom"):
            result = self._observe(frame_id)
            grid = result["grid"]
            spec = self.frames[frame_id]["grid"]
            self.assertEqual(grid["status"], STATUS_OK, frame_id)
            self.assertEqual(grid["columnCount"], 10, frame_id)
            self.assertGreaterEqual(grid["visibleRowCount"], spec["visibleRowMin"], frame_id)
            self.assertLessEqual(grid["visibleRowCount"], spec["visibleRowMax"], frame_id)
            self.assertGreaterEqual(grid["cellWidth"], spec["cellMin"], frame_id)
            self.assertLessEqual(grid["cellWidth"], spec["cellMax"], frame_id)
            self.assertGreaterEqual(grid["cellHeight"], spec["cellMin"], frame_id)
            self.assertLessEqual(grid["cellHeight"], spec["cellMax"], frame_id)
            self.assertEqual(len(grid["xLines"]), 11, frame_id)
            self.assertEqual(len(grid["yLines"]), grid["visibleRowCount"] + 1, frame_id)
            self.assertEqual(set(grid), set(GRID_KEYS), frame_id)

    def test_confirmed_component_masks_and_clip_flags(self):
        for frame_id in ("top", "middle", "bottom"):
            result = self._observe(frame_id)
            expected = self.frames[frame_id]["confirmedComponents"]
            if self.frames[frame_id].get("expectEmptyViewport"):
                self.assertEqual(result["components"], [])
                continue
            found = {
                (item["viewportColumn"], item["viewportRow"], item["widthCells"], item["heightCells"]): item
                for item in result["components"]
            }
            for spec in expected:
                key = (spec["viewportColumn"], spec["viewportRow"], spec["widthCells"], spec["heightCells"])
                self.assertIn(key, found, (frame_id, spec, list(found)))
                item = found[key]
                self.assertEqual(item["spanCells"], spec["spanCells"], spec)
                self.assertEqual(item["clippedTop"], spec["clippedTop"], spec)
                self.assertEqual(item["clippedBottom"], spec["clippedBottom"], spec)
                self.assertEqual(item["status"], spec["status"], spec)
                self.assertEqual(set(item), set(COMPONENT_KEYS))

    def test_large_item_width_is_stable_across_scroll(self):
        top = self._observe("top")
        middle = self._observe("middle")
        top_left = [item for item in top["components"] if item["viewportColumn"] == 0 and item["widthCells"] == 5]
        mid_left = [item for item in middle["components"] if item["viewportColumn"] == 0 and item["widthCells"] == 5]
        self.assertTrue(top_left, top["components"])
        self.assertTrue(mid_left, middle["components"])
        self.assertTrue(all(item["status"] == STATUS_AMBIGUOUS for item in top_left + mid_left))
        self.assertTrue(any(item["clippedTop"] for item in mid_left))

    def test_empty_viewport_and_reveal_do_not_invent_items(self):
        bottom = self._observe("bottom")
        unknown = self._observe("unknown")
        self.assertEqual(bottom["grid"]["status"], STATUS_OK)
        self.assertEqual(bottom["components"], [])
        self.assertEqual(unknown["grid"]["status"], STATUS_UNKNOWN)
        self.assertEqual(unknown["components"], [])

    def test_blur_and_four_column_crop_are_honest(self):
        top = _load(SCROLL / "top_warehouse.png")
        blurred = cv2.GaussianBlur(top, (31, 31), 0)
        blur_result = observe_warehouse_grid(blurred, already_cropped=True, source_id="blur")
        self.assertIn(blur_result["grid"]["status"], {STATUS_UNKNOWN, STATUS_OK})
        if blur_result["grid"]["status"] == STATUS_OK:
            self.assertLess(blur_result["grid"]["confidence"], 0.85)

        bottom = _load(SCROLL / "bottom_warehouse.png")
        four = bottom[:, : 4 * 56 + 12]
        cropped = observe_warehouse_grid(four, already_cropped=True, source_id="four")
        if cropped["grid"]["status"] == STATUS_OK:
            self.assertLessEqual(cropped["grid"]["columnCount"], 6)
            self.assertNotEqual(cropped["grid"]["columnCount"], 10)

    def test_scaled_full_frame_keeps_ten_columns(self):
        crop = _load(SCROLL / "bottom_warehouse.png")
        for size in ((1920, 1080), (1440, 810), (2560, 1440)):
            frame = _paste(crop, size)
            result = observe_warehouse_grid(frame, already_cropped=False, source_id=f"s{size[0]}")
            self.assertEqual(result["grid"]["status"], STATUS_OK, size)
            self.assertEqual(result["grid"]["columnCount"], 10, size)
            self.assertEqual(result["components"], [])

    def test_output_is_deterministic_and_has_no_identity_fields(self):
        first = self._observe("top")
        second = self._observe("top")
        self.assertEqual(first, second)
        blob = json.dumps(first)
        for token in FORBIDDEN_FIELDS:
            self.assertNotIn(token, blob)
        for item in first["components"]:
            self.assertIn(item["status"], {STATUS_OBSERVED, STATUS_AMBIGUOUS})
            if item["clippedTop"] or item["clippedBottom"]:
                self.assertEqual(item["status"], STATUS_AMBIGUOUS)

    def test_linear_one_by_two_and_two_by_one_components_merge(self):
        result = self._observe("top")
        components = result["components"]
        by_coord = {(c["viewportColumn"], c["viewportRow"]): c for c in components}

        # 6 confirmed linear 1x2 and 2x1 items
        confirmed = [
            (5, 0, 1, 2, "TOP_I02"),
            (8, 0, 1, 2, "TOP_I04"),
            (9, 4, 1, 2, "[9,4]"),
            (9, 6, 1, 2, "[9,6]"),
            (5, 6, 1, 2, "[5,6]"),
            (5, 9, 2, 1, "[5,9]"),
        ]
        for col, row, exp_w, exp_h, label in confirmed:
            self.assertIn((col, row), by_coord, f"Missing {label} at col={col}, row={row}")
            comp = by_coord[(col, row)]
            self.assertEqual(comp["widthCells"], exp_w, f"{label} width")
            self.assertEqual(comp["heightCells"], exp_h, f"{label} height")
            self.assertEqual(comp["spanCells"], exp_w * exp_h, f"{label} span")

        # Negative controls: independent 1x1 items must not merge
        neg_controls = [
            (9, 0, "TOP_I05"),
            (9, 1, "TOP_I06"),
            (5, 2, "TOP_I07"),
            (9, 3, "TOP_I10"),
            (7, 9, "TOP_I20"),
            (8, 9, "TOP_I21"),
        ]
        for col, row, label in neg_controls:
            self.assertIn((col, row), by_coord, f"Missing {label} at col={col}, row={row}")
            comp = by_coord[(col, row)]
            self.assertEqual(comp["widthCells"], 1, f"{label} width")
            self.assertEqual(comp["heightCells"], 1, f"{label} height")
            self.assertEqual(comp["spanCells"], 1, f"{label} span")


if __name__ == "__main__":
    unittest.main()

