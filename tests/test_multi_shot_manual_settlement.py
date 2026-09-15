# -*- coding: utf-8 -*-
"""Tests for multi-shot manual settlement capture, deduplication, and review recovery."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from runtime_data import runtime_data_paths
from settlement_evidence_store_v2 import (
    KIND_MANUAL_GAME,
    SettlementEvidenceStoreV2,
)
from settlement_review import SettlementReviewService
from app.main import CURRENT_MATCH, handle_save_game_screenshot


def _make_dummy_frame(color: tuple[int, int, int]) -> np.ndarray:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[:] = color
    return frame


class TestMultiShotManualSettlement(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.temp_root = Path(self._tmp.name).resolve()
        os.environ["YIHUAN_DATA_DIR"] = str(self.temp_root)
        self.paths = runtime_data_paths()

        # Reset CURRENT_MATCH with clean draft match
        CURRENT_MATCH.begin_next_match()
        self.match_id = CURRENT_MATCH.id

    def tearDown(self):
        os.environ.pop("YIHUAN_DATA_DIR", None)
        self._tmp.cleanup()

    @mock.patch("app.main.WindowCaptureManager")
    def test_multi_shot_capture_and_deduplication(self, mock_wcm_cls):
        mock_mgr = mock_wcm_cls.return_value
        mock_mgr.find_game_hwnd.return_value = 12345
        mock_mgr.keywords = ["异环"]

        frame1 = _make_dummy_frame((10, 20, 30))
        frame2 = _make_dummy_frame((40, 50, 60))

        # 1. Capture 1st screenshot
        mock_mgr.capture_game_client.return_value = (frame1, "test_client")
        res1 = handle_save_game_screenshot()
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["status"], "SAVED")
        self.assertEqual(res1["sequence"], 1)
        self.assertIn("第 1 张截图", res1["message"])
        sha1 = res1["sha256"]

        # 2. Capture identical frame (duplicate) -> DUPLICATE_IGNORED
        res_dup = handle_save_game_screenshot()
        self.assertTrue(res_dup["ok"])
        self.assertEqual(res_dup["status"], "DUPLICATE_IGNORED")
        self.assertTrue(res_dup["duplicate"])
        self.assertEqual(res_dup["sha256"], sha1)
        self.assertIn("完全相同，未重复追加", res_dup["message"])

        # 3. Capture 2nd different screenshot -> sequence 2
        mock_mgr.capture_game_client.return_value = (frame2, "test_client")
        res2 = handle_save_game_screenshot()
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["status"], "SAVED")
        self.assertEqual(res2["sequence"], 2)
        self.assertIn("第 2 张截图", res2["message"])
        sha2 = res2["sha256"]
        self.assertNotEqual(sha1, sha2)

        # 4. Verify canonical CURRENT_MATCH facts contains both captures
        evidence = CURRENT_MATCH.facts.get("settlementEvidence", {})
        captures = evidence.get("captures", [])
        self.assertEqual(len(captures), 2)
        self.assertEqual(captures[0]["sha256"], sha1)
        self.assertEqual(captures[1]["sha256"], sha2)

        # 5. Verify SettlementReviewService.list_original_screenshots
        review_service = SettlementReviewService()
        originals = review_service.list_original_screenshots(self.match_id)
        self.assertTrue(originals["ok"])
        images = originals.get("images", [])
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0]["sequence"], 1)
        self.assertEqual(images[0]["sha256"], sha1)
        self.assertEqual(images[0]["kind"], KIND_MANUAL_GAME)
        self.assertTrue(images[0]["dataUrl"].startswith("data:image/png;base64,"))

        self.assertEqual(images[1]["sequence"], 2)
        self.assertEqual(images[1]["sha256"], sha2)
        self.assertEqual(images[1]["kind"], KIND_MANUAL_GAME)
        self.assertTrue(images[1]["dataUrl"].startswith("data:image/png;base64,"))

        # 6. Verify _load_v2_evidence_for_record falls back to manual-game when no main settlement image
        blob_path, loaded_sha, loaded_img = review_service._load_v2_evidence_for_record(self.match_id)
        self.assertIsNotNone(blob_path)
        self.assertIsNotNone(loaded_sha)
        self.assertIsNotNone(loaded_img)
        self.assertEqual(loaded_img.shape, (100, 100, 3))


if __name__ == "__main__":
    unittest.main()
