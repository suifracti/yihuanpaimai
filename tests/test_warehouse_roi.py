"""仓库输入区域必须落在真实「我的资产」网格，不能扫到 HUD。"""

import os
import sys
import unittest

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from warehouse_vision import WarehouseVisionV1
from roi_scaler import NORMALIZED_ROIS


class TestWarehouseRoi(unittest.TestCase):
    def test_board_roi_covers_full_visible_grid(self):
        x1, y1, x2, y2 = NORMALIZED_ROIS["warehouse_board"]
        self.assertGreaterEqual(x1, 0.64)
        self.assertGreaterEqual(x2, 0.95)
        self.assertLessEqual(x2, 0.99)
        self.assertGreaterEqual(y1, 0.16)
        self.assertLessEqual(y2, 0.82)

    def test_t037_blobs_stay_inside_board(self):
        path = os.path.join(PROJECT_ROOT, "build", "live_auc", "t037.jpg")
        if not os.path.exists(path):
            self.skipTest("t037 missing")
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        x1, y1, x2, y2 = NORMALIZED_ROIS["warehouse_board"]
        vis = WarehouseVisionV1()
        state = vis.process_frame(img)
        h, w = img.shape[:2]
        left, right = int(w * x1) - 2, int(w * x2) + 2
        for slot in state.get("slots") or []:
            box = slot.get("box") or (0, 0, 0, 0)
            self.assertGreaterEqual(box[0], left, slot)
            self.assertLess(box[0], right, slot)


if __name__ == "__main__":
    unittest.main()
