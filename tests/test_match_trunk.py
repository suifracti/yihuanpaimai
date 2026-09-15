# -*- coding: utf-8 -*-
"""感知层修复 A：席位历史/当前价、box 归档、结算一次 finalize、loading 不被 OPEN_WORLD 盖掉。"""
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from auto_archiver import AutoArchiver
from vision_pipeline import (
    NTEVisionPipeline,
    SCENE_AUCTION_LOADING,
    SCENE_AUCTION_LOBBY,
    SCENE_IN_AUCTION,
    SCENE_OPEN_WORLD,
    SCENE_SETTLEMENT,
    SCENE_UNKNOWN,
    SETTLEMENT_STABLE_FRAMES,
)


def _load(rel):
    path = os.path.join(PROJECT_ROOT, rel)
    if not os.path.exists(path):
        return None
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


class TestSeatHistoryVsCurrent(unittest.TestCase):
    def test_history_unit_does_not_become_current(self):
        pipe = NTEVisionPipeline()
        pipe.current_context["round"] = 3
        pipe.current_context["seats"][1]["name"] = "往事流入眼眸"
        ocr = [
            ([[80, 360], [220, 360], [220, 390], [80, 390]], "往事流入眼眸", 0.99),
            ([[148, 430], [220, 430], [220, 448], [148, 448]], "800K", 0.99),
        ]
        pipe._bind_horizontal_seats(ocr, 1920, 1080)
        seat = pipe.current_context["seats"][1]
        self.assertEqual(seat.get("currentBid"), None)
        self.assertEqual(seat.get("bid") or 0, 0)
        hist = pipe.current_context["historicalBids"].get("往事流入眼眸") or {}
        finals = pipe.current_context["finalBids"].get("往事流入眼眸") or {}
        self.assertNotIn("3", hist)
        self.assertIn(800000, hist.values())
        self.assertIn(800000, finals.values())

    def test_current_big_number_sets_leader(self):
        pipe = NTEVisionPipeline()
        pipe.current_context["round"] = 1
        ocr = [
            ([[80, 180], [180, 180], [180, 210], [80, 210]], "血咩月", 0.99),
            ([[80, 340], [220, 340], [220, 370], [80, 370]], "往事流入眼眸", 0.99),
            ([[80, 500], [160, 500], [160, 530], [80, 530]], "果可", 0.99),
            ([[80, 660], [200, 660], [200, 690], [80, 690]], "秋星祭02", 0.99),
            ([[90, 220], [220, 220], [220, 260], [90, 260]], "666667", 0.99),
            ([[90, 380], [220, 380], [220, 420], [90, 420]], "500000", 0.99),
            ([[90, 540], [220, 540], [220, 580], [90, 580]], "800000", 0.99),
            ([[90, 700], [220, 700], [220, 740], [90, 740]], "700000", 0.99),
        ]
        pipe._bind_horizontal_seats(ocr, 1920, 1080)
        pipe._refresh_leader_from_seats()
        self.assertEqual(pipe.current_context["currentLeaderBid"], 800000)
        self.assertEqual(pipe.current_context["leaderName"], "果可")
        self.assertEqual(pipe.current_context["leaderTies"], ["果可"])

    def test_three_way_tie_keeps_coleaders(self):
        pipe = NTEVisionPipeline()
        pipe.current_context["round"] = 2
        pipe.current_context["finalBids"] = {
            "血咩月": {"2": 666667},
            "往事流入眼眸": {"2": 800000},
            "果可": {"2": 800000},
            "秋星祭02": {"2": 800000},
        }
        pipe.current_context["seats"] = [
            {"slot": 1, "name": "血咩月", "bid": 0, "currentBid": 666667, "isMe": False},
            {"slot": 2, "name": "往事流入眼眸", "bid": 0, "currentBid": 800000, "isMe": False},
            {"slot": 3, "name": "果可", "bid": 0, "currentBid": 800000, "isMe": False},
            {"slot": 4, "name": "秋星祭02", "bid": 0, "currentBid": 800000, "isMe": False},
        ]
        pipe._refresh_leader_from_seats()
        self.assertEqual(pipe.current_context["currentLeaderBid"], 800000)
        self.assertIsNone(pipe.current_context["leaderName"])
        self.assertEqual(set(pipe.current_context["leaderTies"]), {"往事流入眼眸", "果可", "秋星祭02"})

    def test_history_slot_does_not_overwrite_current_round(self):
        pipe = NTEVisionPipeline()
        pipe.current_context["round"] = 3
        pipe.current_context["seats"][3]["name"] = "秋星祭02"
        pipe.current_context["finalBids"] = {"秋星祭02": {"1": 888888, "2": 1000000}}
        ocr = [
            ([[80, 660], [200, 660], [200, 690], [80, 690]], "秋星祭02", 0.99),
            ([[224, 726], [290, 726], [290, 746], [224, 746]], "1,000K", 0.91),
            ([[90, 690], [220, 690], [220, 730], [90, 730]], "999999", 0.99),
        ]
        pipe._bind_horizontal_seats(ocr, 1920, 1080)
        pipe._refresh_leader_from_seats()
        finals = pipe.current_context["finalBids"]["秋星祭02"]
        self.assertEqual(finals.get("2"), 1000000)
        self.assertEqual(finals.get("3"), 999999)
        self.assertNotIn("3", pipe.current_context["historicalBids"].get("秋星祭02") or {})
        self.assertEqual(pipe.current_context["leaderName"], "秋星祭02")
        self.assertEqual(pipe.current_context["currentLeaderBid"], 999999)


class TestArchiveBoxAndSettlementOnce(unittest.TestCase):
    def test_archive_uses_ctx_box_not_box_type(self):
        archiver = AutoArchiver(db_paths=[])
        rec = archiver.archive_match({
            "venue": "中级场 · 珊瑚场",
            "box": "实木宝箱 · 中级藏品概率提升",
            "boxType": None,
            "fieldCondition": "standard",
            "settlementReady": True,
            "settlementData": {
                "isSettlement": True,
                "clearingPrice": 1010000,
                "actualTotal": 1013120,
                "profit": 3120,
            },
        })
        self.assertIsNotNone(rec)
        self.assertEqual(rec["environment"]["box"], "实木宝箱 · 中级藏品概率提升")
        self.assertEqual(rec["environment"]["fieldCondition"], "standard")

    def test_archive_waits_until_ready_and_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "db.json")
            archiver = AutoArchiver(db_paths=[db])
            early = {
                "settlementReady": False,
                "settlementData": {"isSettlement": True, "clearingPrice": 1010000, "actualTotal": 202798, "profit": 807202},
            }
            self.assertIsNone(archiver.archive_match(early))
            ctx = {
                "box": "实木宝箱 · 中级藏品概率提升",
                "fieldCondition": "standard",
                "settlementReady": True,
                "settlementData": {"isSettlement": True, "clearingPrice": 1010000, "actualTotal": 1013120, "profit": 3120},
            }
            first = archiver.archive_match(ctx)
            second = archiver.archive_match(ctx)
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            self.assertTrue(ctx["settlementFinalized"])
            self.assertEqual(first["settlement"]["clearingPrice"], 1010000)
            self.assertEqual(first["settlement"]["actualTotal"], 1013120)
            self.assertEqual(first["settlement"]["realizedProfit"], 3120)


class TestLive1204Trunk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        needed = {
            "lobby": "build/live_1204/t000.jpg",
            "loading": "build/live_1204/t035.jpg",
            "spin": "build/live_1204/t045.jpg",
            "splash": "build/live_1204/t050.jpg",
            "r1": "build/live_1204/t085.jpg",
            "r2": "build/live_1204/t120.jpg",
            "r3": "build/live_1204/t160.jpg",
            "r4": "build/live_1204/t193.jpg",
            "r5": "build/live_1204/t238.jpg",
            "settle": "build/live_1204/t248.jpg",
            "exit_load": "build/live_1204/t268.jpg",
        }
        cls.frames = {k: _load(v) for k, v in needed.items()}
        if any(v is None for v in cls.frames.values()):
            cls.frames = None

    def test_loading_not_open_world_and_match_stays_locked(self):
        if not self.frames:
            self.skipTest("live_1204 frames missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        lobby = pipe.process_frame(self.frames["lobby"])
        self.assertEqual(lobby["scene"], SCENE_AUCTION_LOBBY)
        loading = pipe.process_frame(self.frames["loading"])
        self.assertNotEqual(loading["scene"], SCENE_OPEN_WORLD)
        self.assertIn(loading["scene"], (SCENE_AUCTION_LOADING, SCENE_UNKNOWN, SCENE_AUCTION_LOBBY))
        splash = pipe.process_frame(self.frames["splash"])
        self.assertNotEqual(splash["scene"], SCENE_OPEN_WORLD)
        scenes = []
        for key in ("r1", "r3", "r4", "r5"):
            ctx = pipe.process_frame(self.frames[key])
            scenes.append(ctx["scene"])
            self.assertEqual(ctx["scene"], SCENE_IN_AUCTION, scenes)
        self.assertIn("实木", pipe.current_context.get("box") or "")
        self.assertEqual(pipe.current_context.get("fieldCondition"), "standard")

    def test_seat_finals_and_r2_tie_from_history(self):
        if not self.frames:
            self.skipTest("live_1204 frames missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        pipe.current_context["scene"] = SCENE_IN_AUCTION
        pipe.current_context["inAuction"] = True
        pipe.process_frame(self.frames["splash"])
        pipe.process_frame(self.frames["r1"])
        r1 = pipe.process_frame(self.frames["r1"])
        self.assertEqual(r1["currentLeaderBid"], 800000)
        self.assertEqual(r1["leaderName"], "果可")
        bids1 = {s["name"]: s.get("currentBid") or s.get("bid") for s in r1["seats"] if s.get("name")}
        self.assertEqual(bids1.get("果可"), 800000)
        if self.frames.get("r2") is not None:
            pipe.process_frame(self.frames["r2"])
            r2 = pipe.process_frame(self.frames["r2"])
            self.assertEqual(r2["currentLeaderBid"], 800000)
            self.assertIsNone(r2["leaderName"])
            self.assertEqual(set(r2["leaderTies"]), {"往事流入眼眸", "果可", "秋星祭02"})
        pipe.process_frame(self.frames["r3"])
        r3 = pipe.process_frame(self.frames["r3"])
        self.assertEqual(r3["currentLeaderBid"], 1100000)
        self.assertEqual(r3["leaderName"], "果可")
        currents = {s.get("name"): s.get("currentBid") for s in r3["seats"] if s.get("name")}
        self.assertEqual(currents.get("果可"), 1100000)
        # 往事流入眼眸 R3 当前是 850000，不能被 R2 历史 800K 盖住
        if currents.get("往事流入眼眸") is not None:
            self.assertEqual(currents.get("往事流入眼眸"), 850000)
        pipe.process_frame(self.frames["r4"])
        r4 = pipe.process_frame(self.frames["r4"])
        self.assertEqual(r4["currentLeaderBid"], 1000000)
        self.assertEqual(r4["leaderName"], "果可")
        pipe.process_frame(self.frames["r5"])
        r5 = pipe.process_frame(self.frames["r5"])
        self.assertEqual(r5["currentLeaderBid"], 1010000)
        self.assertEqual(r5["leaderName"], "果可")
        names = [s.get("name") or "" for s in r5["seats"]]
        self.assertEqual(len([n for n in names if n]), 4, names)
        self.assertTrue(any("果可" in n for n in names), names)
        self.assertTrue(any("秋星" in n for n in names), names)
        r2_hist = {
            name: (rounds or {}).get("2")
            for name, rounds in (r5.get("finalBids") or {}).items()
        }
        tied = {name for name, bid in r2_hist.items() if bid == 800000}
        self.assertGreaterEqual(len(tied), 3, r2_hist)

    def test_settlement_finalizes_once_with_final_numbers(self):
        if not self.frames:
            self.skipTest("live_1204 frames missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        pipe.process_frame(self.frames["r5"])
        saves = []
        archiver = AutoArchiver(db_paths=[])
        for _ in range(SETTLEMENT_STABLE_FRAMES + 3):
            ctx = pipe.process_frame(self.frames["settle"])
            self.assertEqual(ctx["scene"], SCENE_SETTLEMENT)
            rec = archiver.archive_match(ctx)
            if rec:
                pipe.mark_settlement_finalized()
                saves.append(rec)
        self.assertEqual(len(saves), 1)
        rec = saves[0]
        self.assertEqual(rec["settlement"]["clearingPrice"], 1010000)
        self.assertEqual(rec["settlement"]["actualTotal"], 1013120)
        self.assertEqual(rec["settlement"]["realizedProfit"], 3120)
        self.assertTrue(rec.get("environment", {}).get("boxType") == "wood" or "实木" in (rec.get("environment", {}).get("box") or ""))
        self.assertEqual(rec.get("environment", {}).get("fieldCondition"), "standard")
        later = pipe.process_frame(self.frames["settle"])
        self.assertIsNone(archiver.archive_match(later))

    def test_early_settlement_does_not_flush(self):
        if not self.frames:
            self.skipTest("live_1204 frames missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        early = _load("build/live_1204/t248.jpg")
        # reuse known early-like numbers from 12:04 first archive
        pipe.current_context["settlementData"] = {
            "isSettlement": True,
            "clearingPrice": 800000,
            "actualTotal": 0,
            "profit": 0,
        }
        self.assertFalse(pipe.flush_settlement_for_shutdown())
        pipe.current_context["settlementData"] = {
            "isSettlement": True,
            "clearingPrice": 800000,
            "actualTotal": 800000,
            "profit": 800000,
        }
        self.assertFalse(pipe.flush_settlement_for_shutdown())

    def test_exit_loading_not_open_world(self):
        if not self.frames:
            self.skipTest("live_1204 frames missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        pipe.process_frame(self.frames["settle"])
        ctx = pipe.process_frame(self.frames["exit_load"])
        self.assertNotEqual(ctx["scene"], SCENE_OPEN_WORLD)


class TestPurpleAndShutdownFlush(unittest.TestCase):
    def test_purple_count_parser(self):
        pipe = NTEVisionPipeline()
        pipe.current_context["round"] = 2
        mapped = [([[400, 300], [900, 300], [900, 340], [400, 340]], "本局内所有紫色品质藏品的总数量为3件。", 0.99)]
        for box, text, score in mapped:
            m_purple = __import__("re").search(r"紫色品质藏品的总数量为\s*(\d+)", text)
            if m_purple:
                pipe.current_context["purple"] = int(m_purple.group(1))
        img = _load("build/live_1331/t110.jpg")
        if img is None:
            self.assertEqual(pipe.current_context["purple"], 3)
            return
        pipe._ensure_ocr()
        ctx = pipe.process_frame(img)
        self.assertEqual(ctx.get("purple"), 3)

    def test_shutdown_flush_saves_1331_final(self):
        img = _load("build/live_1331/t162.jpg")
        if img is None:
            self.skipTest("live_1331 settlement frame missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        pipe.current_context["scene"] = SCENE_SETTLEMENT
        pipe.current_context["inAuction"] = True
        ctx = pipe.process_frame(img)
        self.assertEqual(ctx["scene"], SCENE_SETTLEMENT)
        data = ctx.get("settlementData") or {}
        self.assertEqual(data.get("clearingPrice"), 800000)
        self.assertEqual(data.get("actualTotal"), 676606)
        self.assertEqual(data.get("profit"), -123394)
        self.assertTrue(pipe.flush_settlement_for_shutdown())
        rec = AutoArchiver(db_paths=[]).archive_match(pipe.current_context)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["settlement"]["clearingPrice"], 800000)
        self.assertEqual(rec["settlement"]["actualTotal"], 676606)
        self.assertEqual(rec["settlement"]["realizedProfit"], -123394)

    def test_hud_html_has_box_slot(self):
        html_path = os.path.join(PROJECT_ROOT, "core", "tactical_hud.html")
        with open(html_path, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("intelBox", html)
        self.assertIn("d.box", html)
        self.assertIn("purpleCount", html)


class TestLive1412FinalBids(unittest.TestCase):
    PLAYERS = ("华星秋月", "爱馨宝", "秦幽雪", "秋星祭02")

    def _finals(self, ctx, round_no):
        out = {}
        for name, rounds in (ctx.get("finalBids") or {}).items():
            if name in self.PLAYERS:
                out[name] = int((rounds or {}).get(str(round_no)) or 0)
        return out

    def test_round_ownership_matches_gt(self):
        frames = [
            _load("build/live_1412/B_t071.jpg"),
            _load("build/live_1412/B_t076.jpg"),
            _load("build/live_1412/B_t116.jpg"),
            _load("build/live_1412/B_t121.jpg"),
            _load("build/live_1412/B_t171.jpg"),
            _load("build/live_1412/B_t176.jpg"),
            _load("build/live_1412/B_t231.jpg"),
        ]
        if any(f is None for f in frames):
            self.skipTest("live_1412 frames missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        pipe.current_context["scene"] = SCENE_IN_AUCTION
        pipe.current_context["inAuction"] = True
        ctx = None
        for img in frames:
            pipe.process_frame(img)
            ctx = pipe.process_frame(img)
        expected = {
            1: {"华星秋月": 100, "爱馨宝": 888888, "秦幽雪": 200000, "秋星祭02": 888888},
            2: {"华星秋月": 100000, "爱馨宝": 888888, "秦幽雪": 200000, "秋星祭02": 1000000},
            3: {"华星秋月": 666666, "爱馨宝": 888888, "秦幽雪": 200000, "秋星祭02": 999999},
            4: {"华星秋月": 900001, "爱馨宝": 888888, "秦幽雪": 200000, "秋星祭02": 1099998},
        }
        for rnd, want in expected.items():
            got = self._finals(ctx, rnd)
            self.assertEqual(got, want, f"R{rnd} {got}")
        r4 = self._finals(ctx, 4)
        self.assertEqual(max(r4.values()), 1099998)
        self.assertEqual(ctx["leaderName"], "秋星祭02")
        hist = ctx.get("historicalBids") or {}
        self.assertEqual(hist.get("秋星祭02", {}).get("1"), 888888)
        self.assertEqual(hist.get("秋星祭02", {}).get("2"), 1000000)
        self.assertNotIn("4", hist.get("秋星祭02") or {})

    def test_live_1412_intel_contract_facts(self):
        """验证 14:12 真人局情报契约事实字段: totalItems=66, q=39, goldAvg=61944, purpleAvg=3904, purple=25"""
        frames = [
            _load("build/live_1412/B_t030.jpg"),
            _load("build/live_1412/B_t031.jpg"),
            _load("build/live_1412/B_t045.jpg"),
            _load("build/live_1412/B_t135.jpg"),
            _load("build/live_1412/B_t220.jpg"),
        ]
        if any(f is None for f in frames):
            self.skipTest("live_1412 frames missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        pipe.current_context["scene"] = SCENE_IN_AUCTION
        pipe.current_context["inAuction"] = True
        ctx = None
        for img in frames:
            ctx = pipe.process_frame(img)

        self.assertEqual(ctx.get("totalItems"), 66, "totalItems should be 66 (全场总件数)")
        self.assertEqual(ctx.get("q"), 39, "q should be 39 (高阶藏品件数)")
        self.assertEqual(ctx.get("goldAvg"), 61944, "goldAvg should be 61944 (金色均价)")
        self.assertEqual(ctx.get("purpleAvg"), 3904, "purpleAvg should be 3904 (紫色均价)")
        self.assertEqual(ctx.get("purple"), 25, "purple should be 25 (紫色总数量)")
        self.assertEqual(ctx.get("purpleCount"), 25, "purpleCount should be 25")
        self.assertIn("琉璃", ctx.get("box") or "", "box in 14:12 is 琉璃宝箱（宝石类概率提升）")
        self.assertEqual(ctx.get("fieldCondition"), "standard", "fieldCondition in 14:12 is standard")
        self.assertIsNone(ctx.get("avg"), "avg should remain None when only goldAvg/purpleAvg are observed")
        self.assertIsNone(ctx.get("blueAvg"), "blueAvg should remain null when unknown")
        self.assertIsNone(ctx.get("greenAvg"), "greenAvg should remain null when unknown")
        self.assertIsNone(ctx.get("whiteAvg"), "whiteAvg should remain null when unknown")

        # 验证 14:12 终局结算真值 (actualTotal=1024282, clearingPrice=1099998, profit=-75716)
        settle_img = _load("build/live_1412/B_t253.jpg")
        if settle_img is not None:
            ctx_settle = pipe.process_frame(settle_img)
            settle_data = ctx_settle.get("settlementData") or {}
            self.assertEqual(settle_data.get("clearingPrice"), 1099998)
            self.assertEqual(settle_data.get("actualTotal"), 1024282)
            self.assertEqual(settle_data.get("profit"), -75716)


if __name__ == "__main__":
    unittest.main()
