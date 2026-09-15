# -*- coding: utf-8 -*-
"""Scene-gate hysteresis: confirmed IN_AUCTION / SETTLEMENT cannot be killed by one weak fast nav hit."""
import os
import sys
import unittest

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from vision_pipeline import (
    MATCH_EXIT_HOLD_FRAMES,
    NTEVisionPipeline,
    SCENE_AUCTION_LOBBY,
    SCENE_IN_AUCTION,
    SCENE_OPEN_WORLD,
    SCENE_SETTLEMENT,
    SCENE_UNKNOWN,
)


def _load(rel):
    path = os.path.join(PROJECT_ROOT, rel)
    if not os.path.exists(path):
        return None
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def _paint_open_world(w=1920, h=1080):
    img = np.full((h, w, 3), 70, dtype=np.uint8)
    cv2.circle(img, (int(w * 0.07), int(h * 0.10)), int(h * 0.07), (18, 18, 18), -1)
    cv2.circle(img, (int(w * 0.07), int(h * 0.10)), int(h * 0.07), (160, 160, 160), 3)
    img[int(h * 0.91):int(h * 0.96), int(w * 0.32):int(w * 0.68)] = (230, 230, 230)
    return img


def _paint_lobby_orange(w=1920, h=1080):
    img = np.full((h, w, 3), 40, dtype=np.uint8)
    img[int(h * 0.20):int(h * 0.58), int(w * 0.62):int(w * 0.94)] = (30, 110, 220)
    img[int(h * 0.84):int(h * 0.95), int(w * 0.64):int(w * 0.94)] = (235, 235, 235)
    return img


def _lock_in_auction(pipe):
    pipe.current_context["scene"] = SCENE_IN_AUCTION
    pipe.current_context["sceneLabel"] = "拍卖进行中"
    pipe.current_context["inAuction"] = True
    pipe.current_context["inLobby"] = False
    pipe.current_context["isSettlement"] = False
    pipe.current_context["round"] = 1
    pipe.current_context["avg"] = 6219
    pipe.current_context["q"] = 23
    pipe.current_context["fieldCondition"] = "standard"
    pipe.current_context["box"] = "实木宝箱 · 中级藏品概率提升"


def _lock_settlement(pipe):
    pipe.current_context["scene"] = SCENE_SETTLEMENT
    pipe.current_context["sceneLabel"] = "结算界面"
    pipe.current_context["inAuction"] = True
    pipe.current_context["isSettlement"] = True
    pipe.current_context["inLobby"] = False
    pipe.current_context["settlementData"] = {
        "isSettlement": True,
        "clearingPrice": 200000,
        "actualTotal": 102884,
        "profit": 97116,
    }


class TestSceneGateHysteresis(unittest.TestCase):
    def test_fast_open_world_does_not_drop_in_auction(self):
        pipe = NTEVisionPipeline()
        _lock_in_auction(pipe)
        img = _paint_open_world()
        self.assertEqual(pipe._classify_scene_fast(img)["scene"], SCENE_OPEN_WORLD)
        ctx = pipe.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_IN_AUCTION)
        self.assertEqual(ctx["round"], 1)
        self.assertEqual(ctx["avg"], 6219)
        self.assertEqual(ctx["q"], 23)
        self.assertIsNone(pipe._ocr_engine)

    def test_repeated_open_world_without_ocr_still_holds(self):
        pipe = NTEVisionPipeline()
        _lock_in_auction(pipe)
        img = _paint_open_world()
        for _ in range(MATCH_EXIT_HOLD_FRAMES + 2):
            ctx = pipe.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_IN_AUCTION)
        self.assertEqual(ctx["round"], 1)

    def test_fast_lobby_does_not_drop_settlement(self):
        pipe = NTEVisionPipeline()
        _lock_settlement(pipe)
        settle = _load(os.path.join("build", "live_2230", "t256.jpg"))
        if settle is None:
            img = _paint_lobby_orange()
            fast = pipe._classify_scene_fast(img)
            self.assertIn(fast["scene"], (SCENE_AUCTION_LOBBY, SCENE_UNKNOWN))
        else:
            img = settle
            self.assertEqual(pipe._classify_scene_fast(img)["scene"], SCENE_AUCTION_LOBBY)
        ctx = pipe.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_SETTLEMENT)
        self.assertTrue(ctx["isSettlement"])
        self.assertFalse(ctx["inLobby"])
        self.assertEqual(ctx["settlementData"]["actualTotal"], 102884)

    def test_fresh_open_world_still_early_returns(self):
        pipe = NTEVisionPipeline()
        img = _paint_open_world()
        ctx = pipe.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_OPEN_WORLD)
        self.assertIsNone(pipe._ocr_engine)


class TestLive2230SceneGateReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = {}
        for name in ("t243.jpg", "t256.jpg", "t376.jpg", "t379.jpg", "t388.jpg", "t396.jpg", "t405.jpg", "t420.jpg"):
            img = _load(os.path.join("build", "live_2230", name))
            if img is not None:
                cls.frames[name] = img

    def test_match2_stays_in_auction_after_open_world_fast(self):
        needed = ("t376.jpg", "t379.jpg", "t388.jpg", "t396.jpg", "t420.jpg")
        if any(name not in self.frames for name in needed):
            self.skipTest("live_2230 match-2 frames missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        scenes = []
        for name in needed:
            ctx = pipe.process_frame(self.frames[name])
            scenes.append((name, ctx["scene"]))
            self.assertNotEqual(ctx["scene"], SCENE_OPEN_WORLD, scenes)
            self.assertNotEqual(ctx["scene"], SCENE_AUCTION_LOBBY, scenes)
        self.assertEqual(ctx["scene"], SCENE_IN_AUCTION, scenes)
        self.assertEqual(ctx["round"], 1)
        self.assertEqual(ctx.get("fieldCondition"), "standard")
        self.assertIn("实木", ctx.get("box") or "")
        self.assertEqual(ctx.get("purpleAvg"), 6219)
        self.assertEqual(ctx.get("q"), 23)
        seats = [s for s in (ctx.get("seats") or []) if s.get("name")]
        self.assertGreaterEqual(len(seats), 3, seats)
        slots = (ctx.get("warehouseVision") or {}).get("slots") or ctx.get("warehouseSlots") or []
        self.assertGreaterEqual(len(slots), 1)

    def test_match1_final_settlement_not_overwritten_by_lobby_fast(self):
        if "t243.jpg" not in self.frames or "t256.jpg" not in self.frames:
            self.skipTest("live_2230 settlement frames missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        early = pipe.process_frame(self.frames["t243.jpg"])
        self.assertEqual(early["scene"], SCENE_SETTLEMENT)
        self.assertTrue(early["isSettlement"])
        fast = pipe._classify_scene_fast(self.frames["t256.jpg"])
        self.assertEqual(fast["scene"], SCENE_AUCTION_LOBBY)
        final = pipe.process_frame(self.frames["t256.jpg"])
        self.assertEqual(final["scene"], SCENE_SETTLEMENT)
        self.assertTrue(final["isSettlement"])
        self.assertFalse(final["inLobby"])
        data = final.get("settlementData") or {}
        self.assertEqual(data.get("clearingPrice"), 200000)
        self.assertEqual(data.get("actualTotal"), 102884)


if __name__ == "__main__":
    unittest.main()
