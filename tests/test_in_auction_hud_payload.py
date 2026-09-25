"""局内 Vision 结果必须进入 HUD payload，round=0 不能降级成导航。"""

import os
import re
import sys
import unittest

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from main import build_in_auction_hud_payload, is_in_auction_hud, build_nav_hud_payload
from vision_pipeline import NTEVisionPipeline


HUD_HTML = os.path.join(PROJECT_ROOT, "core", "tactical_hud.html")


def _ctx(**kwargs):
    base = {
        "scene": "IN_AUCTION",
        "inAuction": True,
        "isSettlement": False,
        "round": 0,
        "timer": 54,
        "q": None,
        "currentLeaderBid": 0,
        "leaderName": None,
        "isMyLead": False,
        "myName": None,
        "myBid": 0,
        "seats": [
            {"slot": 1, "name": "叶隙倾光", "bid": 0, "isMe": False},
            {"slot": 2, "name": "墨雨", "bid": 0, "isMe": False},
            {"slot": 3, "name": "零沚", "bid": 0, "isMe": False},
            {"slot": 4, "name": "PLAYER_LOCAL", "bid": 0, "isMe": False},
        ],
        "opponents": [
            {"slot": 1, "name": "叶隙倾光", "bid": 0},
            {"slot": 2, "name": "墨雨", "bid": 0},
            {"slot": 3, "name": "零沚", "bid": 0},
            {"slot": 4, "name": "PLAYER_LOCAL", "bid": 0},
        ],
        "warehouseVision": {
            "grid": {"cols": 10, "rows": 10, "cellW": 56, "cellH": 56},
            "slots": [
                {"col": 1, "row": 0, "w": 1, "h": 2, "rarity": "purple", "evidenceLevel": "RARITY_AND_SHAPE"},
                {"col": 6, "row": 3, "w": 3, "h": 1, "rarity": "gold", "evidenceLevel": "RARITY_AND_SHAPE"},
            ],
        },
    }
    base.update(kwargs)
    return base


class TestInAuctionHudPayload(unittest.TestCase):
    def test_round_zero_stays_in_auction_payload(self):
        ctx = _ctx(round=0)
        self.assertTrue(is_in_auction_hud(ctx))
        payload = build_in_auction_hud_payload(ctx)
        self.assertTrue(payload["inAuction"])
        self.assertEqual(payload["scene"], "IN_AUCTION")
        self.assertEqual(payload["round"], 0)
        names = [s.get("name") for s in payload["seats"]]
        self.assertEqual(names, ["叶隙倾光", "墨雨", "零沚", "PLAYER_LOCAL"])
        slots = payload["warehouseVision"]["slots"]
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[1]["rarity"], "gold")
        self.assertEqual(slots[1]["w"], 3)
        self.assertNotIn("gridCells", payload)

    def test_late_bids_and_leader_are_published(self):
        ctx = _ctx(
            round=1,
            timer=14,
            currentLeaderBid=300001,
            leaderName="墨雨",
            seats=[
                {"slot": 1, "name": "叶隙倾光", "bid": 6, "isMe": False},
                {"slot": 2, "name": "墨雨", "bid": 300001, "isMe": False},
                {"slot": 3, "name": "零沚", "bid": 100000, "isMe": False},
                {"slot": 4, "name": "PLAYER_LOCAL", "bid": 66, "isMe": False},
            ],
        )
        payload = build_in_auction_hud_payload(ctx)
        bids = [s.get("bid") for s in payload["seats"]]
        self.assertIn(300001, bids)
        self.assertIn(100000, bids)
        self.assertIn(66, bids)
        self.assertEqual(payload["leaderName"], "墨雨")
        self.assertEqual(payload["leaderBid"], 300001)
        self.assertIn("墨雨", payload["leaderBidSub"])

    def test_nav_payload_is_not_used_for_in_auction(self):
        ctx = _ctx(round=0)
        nav = build_nav_hud_payload(ctx)
        self.assertFalse(nav["inAuction"])
        self.assertEqual(nav.get("opponents"), [])

    def test_live21_frames_publish_seats_and_slots(self):
        early = os.path.join(PROJECT_ROOT, "build", "live_21", "t049.jpg")
        late = os.path.join(PROJECT_ROOT, "build", "live_21", "t089.jpg")
        if not os.path.exists(early) or not os.path.exists(late):
            self.skipTest("live_21 frames missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()

        img = cv2.imdecode(np.fromfile(early, dtype=np.uint8), cv2.IMREAD_COLOR)
        ctx = pipe.process_frame(img)
        self.assertTrue(is_in_auction_hud(ctx))
        payload = build_in_auction_hud_payload(ctx)
        names = [s.get("name") or "" for s in payload["seats"]]
        self.assertTrue(any("叶隙" in n or "倾光" in n for n in names), names)
        self.assertTrue(any("墨" in n for n in names), names)
        self.assertTrue(any("秋星" in n for n in names), names)
        self.assertGreaterEqual(len(payload["warehouseVision"]["slots"]), 4)
        self.assertEqual(payload["warehouseVision"]["cols"], 10)
        self.assertNotIn("gridCells", payload)
        img = cv2.imdecode(np.fromfile(late, dtype=np.uint8), cv2.IMREAD_COLOR)
        pipe.process_frame(img)
        ctx = pipe.process_frame(img)
        payload = build_in_auction_hud_payload(ctx)
        bids = [int(s.get("bid") or 0) for s in payload["seats"]]
        self.assertIn(300001, bids)
        self.assertIn(100000, bids)
        self.assertTrue(6 in bids or 66 in bids)
        self.assertEqual(payload["leaderBid"], 300001)
        self.assertTrue(payload.get("leaderName") and "墨" in payload["leaderName"])

    def test_unconfirmed_visual_winner_survives_hud_projection(self):
        payload = build_in_auction_hud_payload(_ctx(warehouseVision={
            "grid": {"cols": 10, "rows": 10},
            "slots": [{
                "row": 3, "col": 2, "w": 1, "h": 1, "rarity": "green",
                "identityStatus": "CANDIDATE", "identityReferenceKind": "DIRECT",
                "bestCandidateId": "image9-0-1", "bestCandidateName": "炭火脆皮烤肉",
                "candidateCount": 6,
                "candidates": [
                    {"catalogId": "image9-0-0", "name": "几何灯"},
                    {"catalogId": "image9-0-1", "name": "炭火脆皮烤肉"},
                ],
            }],
        }))
        slot = payload["warehouseVision"]["slots"][0]
        self.assertEqual((slot["row"], slot["col"]), (3, 2))
        self.assertEqual(slot["bestCandidateId"], "image9-0-1")
        self.assertEqual(slot["bestCandidateName"], "炭火脆皮烤肉")
        self.assertEqual(slot["candidates"][0]["catalogId"], "image9-0-1")
        self.assertIsNone(slot["identifiedName"])

    def test_hud_html_consumes_slots_not_old_grid(self):
        with open(HUD_HTML, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("updateWarehouseSlots", html)
        self.assertIn("warehouseVision", html)
        self.assertNotIn("function updateGrid(", html)
        self.assertNotIn("d.round === 0", html)
        self.assertRegex(html, r"GRID_VISIBLE_ROWS\s*=\s*10")
        self.assertTrue(re.search(r"inAuctionView", html))
        self.assertIn("intelBox", html)
        self.assertIn("d.box", html)


if __name__ == "__main__":
    unittest.main()
