import unittest
import numpy as np
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from warehouse_vision import (
    WarehouseVisionV1,
    WarehouseVisionConfig,
    EvidenceLevel,
    TrackedSlotBlob,
    WarehouseTemplateMatcher
)

class TestWarehouseVisionV1(unittest.TestCase):
    def setUp(self):
        self.config = WarehouseVisionConfig(
            MATCH_CONFIDENCE_THRESHOLD=0.85,
            MATCH_MARGIN_THRESHOLD=0.08,
            IOU_TRACK_THRESHOLD=0.70,
            TEMPORAL_CONFIRM_FRAMES=4
        )
        cat_path = os.path.join(PROJECT_ROOT, "assets", "catalog_065.json")
        self.vision = WarehouseVisionV1(config=self.config, catalog_path=cat_path)

    def test_config_calibration_hyperparameters(self):
        """验证所有基准超参数已显式声明并可供真人实拍校准"""
        self.assertEqual(self.vision.config.MATCH_CONFIDENCE_THRESHOLD, 0.85)
        self.assertEqual(self.vision.config.MATCH_MARGIN_THRESHOLD, 0.08)
        self.assertEqual(self.vision.config.IOU_TRACK_THRESHOLD, 0.70)
        self.assertEqual(self.vision.config.TEMPORAL_CONFIRM_FRAMES, 4)

    def test_track_id_and_temporal_stability(self):
        """验证 TrackId 空间关联与 3~5 帧时序稳定确认机制"""
        # 在完整仓库 Board 里画规则暗格 + 一件金色 2x2。
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        x1, y1, cell = 1316, 216, 56
        for r in range(10):
            for c in range(10):
                cx1 = x1 + c * cell + 3
                cy1 = y1 + r * cell + 3
                frame[cy1:cy1 + cell - 6, cx1:cx1 + cell - 6] = (18, 18, 18)
        frame[y1 + 3:y1 + 2 * cell - 6, x1 + 3:x1 + 2 * cell - 6] = (30, 180, 220)

        # 帧 1: 初次发现，分配 track_id=1，尚未稳定确认
        res1 = self.vision.process_frame(frame)
        self.assertEqual(res1["totalSlots"], 1)
        slot1 = self.vision.tracked_blobs[1]
        self.assertEqual(slot1.track_id, 1)
        self.assertEqual(slot1.consecutive_stable_frames, 1)
        self.assertFalse(slot1.is_confirmed)
        self.assertIn(slot1.evidence_level, (EvidenceLevel.RARITY_AND_SHAPE, EvidenceLevel.RARITY_ONLY))

        # 帧 2 & 3: 持续追踪同一 TrackId
        self.vision.process_frame(frame)
        self.vision.process_frame(frame)
        slot2 = self.vision.tracked_blobs[1]
        self.assertEqual(slot2.consecutive_stable_frames, 3)
        self.assertFalse(slot2.is_confirmed)

        # 帧 4: 达到 TEMPORAL_CONFIRM_FRAMES=4，升为 confirmed
        res4 = self.vision.process_frame(frame)
        slot4 = self.vision.tracked_blobs[1]
        self.assertEqual(slot4.consecutive_stable_frames, 4)
        self.assertTrue(slot4.is_confirmed)
        self.assertEqual(res4["confirmedSlots"], 1)

    def test_unique_in_catalog_strict_gating(self):
        """验证 UNIQUE_IN_CATALOG 仅在 rarity+shape 达到稳定确认后才允许锁定"""
        # 手动注入一个全图鉴唯一的尺寸项 (例如金色 4x5)
        # 帧 1: 尚未确认时，即使候选数 == 1，也绝不允许升级为 UNIQUE_IN_CATALOG
        mock_candidates = [{"Name": "金色大货4x5", "Value": 88000, "Quality": "金", "Width": 4, "Height": 5}]
        
        blob = TrackedSlotBlob(
            track_id=10,
            first_seen_frame=1,
            last_seen_frame=1,
            consecutive_stable_frames=1,
            is_confirmed=False, # 尚未时序确认
            box=(1400, 300, 150, 150),
            width_cells=4,
            height_cells=5,
            cell_count=20,
            rarity="gold",
            evidence_level=EvidenceLevel.RARITY_AND_SHAPE,
            shape_locked=True,
            has_glow=True,
        )
        self.vision.tracked_blobs[10] = blob
        self.vision.matcher.catalog_by_shape_rarity[("4x5", "gold")] = mock_candidates

        confirmed, unconfirmed = self.vision._evaluate_all_tracks(np.zeros((600, 600, 3), dtype=np.uint8), 0, 0)
        self.assertIn(blob, unconfirmed)
        self.assertEqual(blob.evidence_level, EvidenceLevel.RARITY_AND_SHAPE)

        # 模拟达到 4 帧稳定确认
        blob.consecutive_stable_frames = 4
        blob.is_confirmed = True
        confirmed_after, _ = self.vision._evaluate_all_tracks(np.zeros((600, 600, 3), dtype=np.uint8), 0, 0)
        self.assertIn(blob, confirmed_after)
        self.assertEqual(blob.evidence_level, EvidenceLevel.UNIQUE_IN_CATALOG)
        self.assertEqual(blob.expected_price, 88000)

    def test_no_blind_candidates_pick(self):
        """验证候选 > 1 时严禁盲选 candidates[0]，若无法高置信区分则忠实保留 CANDIDATE_SET 与区间"""
        cand_a = {"Name": "金色单反相机", "Value": 38500, "Quality": "金", "Width": 2, "Height": 2}
        cand_b = {"Name": "大理石雕像", "Value": 51077, "Quality": "金", "Width": 2, "Height": 2}
        
        blob = TrackedSlotBlob(
            track_id=20,
            first_seen_frame=1,
            last_seen_frame=4,
            consecutive_stable_frames=4,
            is_confirmed=True,
            box=(100, 100, 100, 100),
            width_cells=2,
            height_cells=2,
            cell_count=4,
            rarity="gold",
            evidence_level=EvidenceLevel.RARITY_AND_SHAPE,
            shape_locked=True,
            has_glow=True,
        )
        self.vision.tracked_blobs[20] = blob
        self.vision.matcher.catalog_by_shape_rarity[("2x2", "gold")] = [cand_a, cand_b]

        # 传入纯黑空白 ROI (无有效模板匹配)
        dummy_crop = np.zeros((300, 300, 3), dtype=np.uint8)
        confirmed, _ = self.vision._evaluate_all_tracks(dummy_crop, 0, 0)
        
        self.assertEqual(blob.evidence_level, EvidenceLevel.CANDIDATE_SET)
        self.assertIsNone(blob.identified_item) # 严禁盲猜 candidates[0]
        self.assertEqual(len(blob.candidates), 2)
        self.assertEqual(blob.min_price, 38500)
        self.assertEqual(blob.max_price, 51077)

    def test_glow_locks_shape_unglowed_color_does_not(self):
        """有绕光才锁完整轮廓；有色无光只报品质。"""
        glow = TrackedSlotBlob(
            track_id=31, first_seen_frame=1, last_seen_frame=4,
            consecutive_stable_frames=4, is_confirmed=True,
            box=(10, 10, 40, 40), width_cells=1, height_cells=1, cell_count=1,
            rarity="red", evidence_level=EvidenceLevel.RARITY_AND_SHAPE,
            has_glow=True, shape_locked=True,
        )
        no_glow = TrackedSlotBlob(
            track_id=32, first_seen_frame=1, last_seen_frame=4,
            consecutive_stable_frames=4, is_confirmed=True,
            box=(80, 10, 80, 80), width_cells=2, height_cells=2, cell_count=4,
            rarity="purple", evidence_level=EvidenceLevel.RARITY_AND_SHAPE,
            has_glow=False, shape_locked=False,
        )
        gray = TrackedSlotBlob(
            track_id=33, first_seen_frame=1, last_seen_frame=4,
            consecutive_stable_frames=4, is_confirmed=True,
            box=(180, 10, 80, 80), width_cells=2, height_cells=2, cell_count=4,
            rarity="unknown", evidence_level=EvidenceLevel.OUTLINE_ONLY,
            has_glow=False, shape_locked=True,
        )
        self.vision.tracked_blobs = {31: glow, 32: no_glow, 33: gray}
        dummy = np.zeros((300, 300, 3), dtype=np.uint8)
        self.vision._evaluate_all_tracks(dummy, 0, 0)
        self.assertEqual(no_glow.evidence_level, EvidenceLevel.RARITY_ONLY)
        self.assertEqual(no_glow.candidates, [])
        self.assertEqual(gray.evidence_level, EvidenceLevel.OUTLINE_ONLY)
        self.assertTrue(glow.shape_locked)

    def test_surrounded_one_cell_can_lock_without_glow(self):
        """被四周占满的 1 格有色块，即使无光也可锁 1x1。"""
        crop = np.zeros((400, 400, 3), dtype=np.uint8)
        # cell_size ≈ 40，四周灰块把中间红 1 格围死
        crop[180:220, 180:220] = (20, 20, 200)
        crop[180:220, 130:170] = (90, 90, 90)
        crop[180:220, 230:270] = (90, 90, 90)
        crop[130:170, 180:220] = (90, 90, 90)
        crop[230:270, 180:220] = (90, 90, 90)
        blobs = self.vision._extract_raw_blobs(crop, 0, 0)
        reds = [b for b in blobs if b["rarity"] == "red"]
        self.assertTrue(reds)
        self.assertTrue(any(b.get("surround_locked") or b.get("shape_locked") for b in reds))
        self.assertTrue(all(b["w_cells"] == 1 and b["h_cells"] == 1 for b in reds))


    def test_phase5_grey_unrevealed_slot_occupancy_and_negative_empty_cells(self):
        """Phase 5: 真实录像灰轮廓 (core_v=59~69) 识别为 unknown/OUTLINE_ONLY，暗色空格 (core_v<25) 严禁误判"""
        # 1. 最小单元测试：合成网格切片
        crop = np.zeros((200, 200, 3), dtype=np.uint8)
        # 空白暗底格子 (core_v ≈ 15)
        crop[10:90, 10:90] = (15, 15, 15)
        empty_cell = self.vision._classify_grid_cell(
            crop, offset_x=0, offset_y=0, ox=0.0, oy=0.0,
            col=0, row=0, cell_w=100.0, cell_h=100.0,
        )
        self.assertIsNone(empty_cell, "暗色空格不得被误判为占用")

        # 真实灰色未揭示轮廓格子 (core_v ≈ 60, core_s = 0)
        crop[110:190, 110:190] = (60, 60, 60)
        occupied_cell = self.vision._classify_grid_cell(
            crop, offset_x=0, offset_y=0, ox=0.0, oy=0.0,
            col=1, row=1, cell_w=100.0, cell_h=100.0,
        )
        self.assertIsNotNone(occupied_cell, "真实灰色未揭示格子应被识别为占用")
        self.assertEqual(occupied_cell["rarity"], "unknown")
        self.assertEqual(occupied_cell["fill"], 1.0)

        # 2. 真实录像端到端抽帧验证
        import cv2
        p1 = r"C:\Users\Administrator\Videos\2026-08-17 14-11-56.mkv"
        if os.path.exists(p1):
            cap = cv2.VideoCapture(p1)
            fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
            
            # Primary 75s
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(75.0 * fps))
            ret, frame = cap.read()
            if ret:
                self.vision.reset()
                out = self.vision.process_frame(frame)
                slots = out.get("slots", [])
                self.assertGreater(len(slots), 0, "Primary 75s 必须检出非空槽位")
                for s in slots:
                    self.assertEqual(s.get("rarity"), "unknown")
                    self.assertEqual(s.get("evidenceLevel"), "OUTLINE_ONLY")
                    self.assertIsNone(s.get("identifiedName"))
            
            # Primary 90s
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(90.0 * fps))
            ret, frame = cap.read()
            if ret:
                self.vision.reset()
                out = self.vision.process_frame(frame)
                slots = out.get("slots", [])
                self.assertGreater(len(slots), 0, "Primary 90s 必须检出非空槽位")
                for s in slots:
                    self.assertEqual(s.get("rarity"), "unknown")
                    self.assertEqual(s.get("evidenceLevel"), "OUTLINE_ONLY")
                    self.assertIsNone(s.get("identifiedName"))
            cap.release()

        # Cross 70s (12-42-40.mkv 空仓基线)
        p2 = r"C:\Users\Administrator\Videos\2026-08-17 12-42-40.mkv"
        if os.path.exists(p2):
            cap = cv2.VideoCapture(p2)
            fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(70.0 * fps))
            ret, frame = cap.read()
            if ret:
                self.vision.reset()
                out = self.vision.process_frame(frame)
                slots = out.get("slots", [])
                self.assertEqual(len(slots), 0, "Cross 70s 空仓基线不得产生误检")
            cap.release()


if __name__ == "__main__":
    unittest.main()

