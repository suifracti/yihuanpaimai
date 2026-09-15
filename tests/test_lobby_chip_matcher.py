"""Phase 4: 会场 / 仪器闭集模板，热路径不再 OCR。"""

import os
import sys
import unittest

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from lobby_chip_matcher import LobbyChipMatcher, asset_dir
from vision_pipeline import NTEVisionPipeline, SCENE_AUCTION_LOBBY


def _load(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


class TestLobbyChipMatcher(unittest.TestCase):
    def test_venue_coral_and_shell(self):
        matcher = LobbyChipMatcher(
            template_dir=asset_dir("lobby_venues", os.path.join(PROJECT_ROOT, "assets", "catalog_065.json")),
            roi_key="lobby_venue_search",
            result_key="venueLabel",
        )
        coral = _load(os.path.join(PROJECT_ROOT, "assets", "ocr_study_frames", "live_lobby", "t0022.jpg"))
        shell = _load(os.path.join(PROJECT_ROOT, "assets", "ocr_study_frames", "live_lobby2", "t0022.jpg"))
        a = matcher.identify(coral)
        b = matcher.identify(shell)
        self.assertTrue(a["accepted"], a)
        self.assertEqual(a["venueLabel"], "珊瑚场")
        self.assertGreaterEqual(a["score"] - a["secondScore"], 0.05)
        self.assertTrue(b["accepted"], b)
        self.assertEqual(b["venueLabel"], "海贝场")
        self.assertEqual((b.get("meta") or {}).get("entryCost"), 0)

    def test_tool_advanced_group(self):
        matcher = LobbyChipMatcher(
            template_dir=asset_dir("lobby_tools", os.path.join(PROJECT_ROOT, "assets", "catalog_065.json")),
            roi_key="lobby_tool_search",
            result_key="toolGroup",
        )
        frame = _load(os.path.join(PROJECT_ROOT, "assets", "ocr_study_frames", "live_lobby", "t0022.jpg"))
        hit = matcher.identify(frame)
        self.assertTrue(hit["accepted"], hit)
        self.assertEqual(hit["toolGroup"], "高级品鉴仪器组")

    def test_process_frame_no_ocr_on_known_lobby(self):
        pipe = NTEVisionPipeline()
        img = _load(os.path.join(PROJECT_ROOT, "assets", "ocr_study_frames", "live_lobby2", "t0022.jpg"))
        before = pipe.ocr_call_count
        ctx = pipe.process_frame(img, force_refresh=True)
        self.assertEqual(ctx["scene"], SCENE_AUCTION_LOBBY)
        self.assertEqual(ctx["lobbyVenueLabel"], "海贝场")
        self.assertEqual(ctx["lobbyEntryCost"], 0)
        self.assertEqual(ctx["lobbyToolGroup"], "高级品鉴仪器组")
        self.assertEqual(ctx["lobbyCharacter"], "达芙蒂尔")
        self.assertEqual(pipe.ocr_call_count, before)


if __name__ == "__main__":
    unittest.main()
