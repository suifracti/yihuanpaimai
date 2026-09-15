"""真实局内关键帧：横向 4 席位绑定 + 仓库 ROI 不再扫 HUD。"""

import os
import sys
import unittest

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from vision_pipeline import NTEVisionPipeline, SCENE_IN_AUCTION
from warehouse_vision import WarehouseVisionV1
from roi_scaler import NORMALIZED_ROIS


def _load(name):
    path = os.path.join(PROJECT_ROOT, "build", "live_auc", name)
    if not os.path.exists(path):
        return None
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


class TestLiveSeatAndWarehouseRoi(unittest.TestCase):
    def test_t065_binds_real_seats_and_leader(self):
        img = _load("t065.jpg")
        if img is None:
            self.skipTest("t065 missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        ctx = pipe.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_IN_AUCTION)
        self.assertEqual(ctx["round"], 1)
        self.assertEqual(ctx["timer"], 24)
        self.assertEqual(ctx["q"], 7)
        names = [s.get("name") for s in ctx["seats"]]
        bids = [s.get("bid") for s in ctx["seats"]]
        self.assertIn("乐观的摸摸元", names)
        self.assertIn("可可", names)
        self.assertTrue(any(n and "狂澜" in n for n in names))
        self.assertIn("秋星祭02", names)
        self.assertIn(100000, bids)
        self.assertIn(88888, bids)
        self.assertIn(260544, bids)
        self.assertEqual(ctx["currentLeaderBid"], 260544)
        self.assertTrue(ctx.get("leaderName") and "狂澜" in ctx["leaderName"])
        self.assertNotIn("对手1", names)
        self.assertNotEqual(ctx.get("myName"), "NTE")

    def test_warehouse_roi_covers_full_board(self):
        x1, y1, x2, y2 = NORMALIZED_ROIS["warehouse_board"]
        self.assertGreaterEqual(x2, 0.95)
        self.assertLessEqual(y2, 0.82)
        img = _load("t037.jpg")
        if img is None:
            self.skipTest("t037 missing")
        vis = WarehouseVisionV1()
        state = vis.process_frame(img)
        h, w = img.shape[:2]
        roi_right = int(w * x2) + 2
        for slot in state.get("slots") or []:
            box = slot.get("box") or (0, 0, 0, 0)
            self.assertLess(box[0], roi_right, slot)
            self.assertGreaterEqual(box[0], int(w * x1) - 2, slot)


if __name__ == "__main__":
    unittest.main()
