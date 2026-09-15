"""Phase 1+2: 刷新事务语义 + 大厅角色闭集模板识别。"""

import os
import sys
import time
import unittest

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))

from character_matcher import CharacterMatcher, default_template_dir
from vision_pipeline import NTEVisionPipeline, SCENE_AUCTION_LOBBY


def _load(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


class TestCharacterMatcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template_dir = default_template_dir(os.path.join(PROJECT_ROOT, "assets", "catalog_065.json"))
        cls.matcher = CharacterMatcher(template_dir=cls.template_dir)
        cls.daf = _load(os.path.join(PROJECT_ROOT, "assets", "ocr_study_frames", "live_lobby", "t0022.jpg"))
        cls.hania = _load(os.path.join(PROJECT_ROOT, "assets", "ocr_study_frames", "live_lobby2", "t0048.jpg"))

    def test_templates_loaded(self):
        names = {item["id"] for item in self.matcher.templates}
        self.assertGreaterEqual(len(names), 8)
        self.assertIn("达芙蒂尔", names)
        self.assertIn("哈尼亚", names)
        self.assertIn("小吱", names)

    def test_identifies_daffodil(self):
        hit = self.matcher.identify(self.daf)
        self.assertTrue(hit["accepted"], hit)
        self.assertEqual(hit["character"], "达芙蒂尔")
        self.assertGreaterEqual(hit["score"], 0.55)
        self.assertGreaterEqual(hit["score"] - hit["secondScore"], 0.04)

    def test_identifies_hania(self):
        hit = self.matcher.identify(self.hania)
        self.assertTrue(hit["accepted"], hit)
        self.assertEqual(hit["character"], "哈尼亚")
        self.assertGreaterEqual(hit["score"], 0.55)
        self.assertGreaterEqual(hit["score"] - hit["secondScore"], 0.04)

    def test_blank_frame_unrecognized(self):
        blank = np.zeros((1080, 1920, 3), dtype=np.uint8)
        hit = self.matcher.identify(blank)
        self.assertFalse(hit["accepted"])
        self.assertIsNone(hit["character"])


class TestLobbyCharacterTemplatePath(unittest.TestCase):
    def test_process_frame_uses_template_not_ocr(self):
        pipe = NTEVisionPipeline()
        img = _load(os.path.join(PROJECT_ROOT, "assets", "ocr_study_frames", "live_lobby", "t0022.jpg"))
        before = pipe.ocr_call_count
        ctx = pipe.process_frame(img, force_refresh=True)
        self.assertEqual(ctx["scene"], SCENE_AUCTION_LOBBY)
        self.assertEqual(ctx["lobbyCharacter"], "达芙蒂尔")
        self.assertEqual(ctx["lobbyCharacterSource"], "template")
        self.assertGreaterEqual(ctx["lobbyCharacterScore"], 0.55)
        self.assertEqual(ctx["lobbyVenueLabel"], "珊瑚场")
        self.assertEqual(ctx["lobbyToolGroup"], "高级品鉴仪器组")
        self.assertEqual(ctx.get("lobbyVenueSource"), "template")
        self.assertEqual(ctx.get("lobbyToolSource"), "template")
        self.assertEqual(pipe.ocr_call_count, before)

    def test_force_refresh_does_not_keep_old_character(self):
        pipe = NTEVisionPipeline()
        pipe.current_context["lobbyCharacter"] = "小吱"
        blank = np.zeros((1080, 1920, 3), dtype=np.uint8)
        pipe._refresh_lobby_loadout(blank, force=True)
        self.assertIsNone(pipe.current_context["lobbyCharacter"])
        self.assertEqual(pipe.current_context["lobbyCharacterSource"], "unrecognized")


class TestRefreshGeneration(unittest.TestCase):
    def test_each_click_gets_unique_request_id(self):
        from main import request_force_refresh, _next_refresh_id
        a = _next_refresh_id()
        b = _next_refresh_id()
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("r"))
        rid = request_force_refresh()
        self.assertTrue(rid)
        from main import LATEST_PAYLOAD
        self.assertEqual(LATEST_PAYLOAD.get("refreshRequestId"), rid)
        self.assertTrue(LATEST_PAYLOAD.get("refreshPending"))
        self.assertIsNone(LATEST_PAYLOAD.get("lobbyCharacter"))
        self.assertEqual(LATEST_PAYLOAD.get("lobbyCharacterLabel"), "识别中")


if __name__ == "__main__":
    unittest.main()
