"""Real-fixture tests for warehouse segment overlap alignment."""

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

from warehouse_segment_overlap import (
    DIR_DOWN,
    DIR_NONE,
    DIR_UP,
    REASON_DIRECTION_MISMATCH,
    REASON_EMPTY_CONTENT,
    REASON_NO_MOVEMENT,
    STATUS_CONFLICT,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    align_warehouse_segments,
)

OVERLAP = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_overlap_v1"
SCROLL = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_scrollbar_v1"


def _load(root: Path, name: str) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(root / name), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(root / name)
    return img


class WarehouseSegmentOverlapV1Tests(unittest.TestCase):
    def test_two_real_down_pairs_are_verified(self):
        a = align_warehouse_segments(
            _load(OVERLAP, "pair_a_prev.png"),
            _load(OVERLAP, "pair_a_next.png"),
            prev_id="8s",
            next_id="12s",
            required_direction=DIR_DOWN,
        )
        b = align_warehouse_segments(
            _load(OVERLAP, "pair_b_prev.png"),
            _load(OVERLAP, "pair_b_next.png"),
            prev_id="12s",
            next_id="16s",
            required_direction=DIR_DOWN,
        )
        self.assertEqual(a["status"], STATUS_VERIFIED, a)
        self.assertEqual(a["direction"], DIR_DOWN)
        self.assertLess(a["verticalOffsetPx"], 0)
        self.assertGreater(a["supportCount"], 2)
        self.assertEqual(b["status"], STATUS_VERIFIED, b)
        self.assertEqual(b["direction"], DIR_DOWN)
        self.assertAlmostEqual(a["verticalOffsetPx"], align_warehouse_segments(
            _load(OVERLAP, "pair_a_prev.png"),
            _load(OVERLAP, "pair_a_next.png"),
        )["verticalOffsetPx"])

    def test_known_10s_20s_pair_is_honest(self):
        result = align_warehouse_segments(
            _load(OVERLAP, "step10.png"),
            _load(OVERLAP, "step20.png"),
            prev_id="10s",
            next_id="20s",
            required_direction=DIR_DOWN,
        )
        self.assertIn(result["status"], {STATUS_VERIFIED, STATUS_UNVERIFIED})
        if result["status"] == STATUS_VERIFIED:
            self.assertEqual(result["direction"], DIR_DOWN)
        else:
            self.assertIn(result["reason"], {"INSUFFICIENT_FEATURES", "LARGE_GAP", "LOW_OVERLAP", "AMBIGUOUS_OFFSET"})

    def test_same_frame_is_no_movement(self):
        img = _load(OVERLAP, "pair_a_prev.png")
        result = align_warehouse_segments(img, img.copy(), prev_id="same", next_id="same")
        self.assertEqual(result["direction"], DIR_NONE)
        self.assertEqual(result["status"], STATUS_UNVERIFIED)
        self.assertEqual(result["reason"], REASON_NO_MOVEMENT)
        self.assertEqual(result["verticalOffsetPx"], 0)

    def test_reverse_pair_is_up_and_rejects_required_down(self):
        up = align_warehouse_segments(
            _load(OVERLAP, "pair_a_next.png"),
            _load(OVERLAP, "pair_a_prev.png"),
            prev_id="12s",
            next_id="8s",
        )
        self.assertEqual(up["direction"], DIR_UP, up)
        self.assertEqual(up["status"], STATUS_VERIFIED)
        denied = align_warehouse_segments(
            _load(OVERLAP, "pair_a_next.png"),
            _load(OVERLAP, "pair_a_prev.png"),
            required_direction=DIR_DOWN,
        )
        self.assertEqual(denied["status"], STATUS_CONFLICT)
        self.assertEqual(denied["reason"], REASON_DIRECTION_MISMATCH)

    def test_top_to_bottom_is_unverified_gap(self):
        result = align_warehouse_segments(
            _load(SCROLL, "top_warehouse.png"),
            _load(SCROLL, "bottom_warehouse.png"),
            prev_id="top",
            next_id="bottom",
            required_direction=DIR_DOWN,
        )
        self.assertEqual(result["status"], STATUS_UNVERIFIED)
        self.assertIn(result["reason"], {REASON_EMPTY_CONTENT, "INSUFFICIENT_FEATURES", "LARGE_GAP", "LOW_OVERLAP"})

    def test_empty_or_unknown_content_is_unverified(self):
        empty = align_warehouse_segments(
            _load(OVERLAP, "bottom.png"),
            _load(SCROLL, "unknown_warehouse.png"),
        )
        self.assertEqual(empty["status"], STATUS_UNVERIFIED)

    def test_static_grid_without_shared_items_is_not_verified(self):
        result = align_warehouse_segments(
            _load(OVERLAP, "bottom.png"),
            _load(SCROLL, "bottom_warehouse.png"),
        )
        self.assertNotEqual(result["status"], STATUS_VERIFIED)

    def test_provenance_lists_adjacent_pairs(self):
        manifest = json.loads((OVERLAP / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], "warehouse-overlap-fixture-v1")
        self.assertEqual(len(manifest["sourceSha256"]), 64)
        self.assertEqual(len(manifest["pairs"]), 2)


if __name__ == "__main__":
    unittest.main()
