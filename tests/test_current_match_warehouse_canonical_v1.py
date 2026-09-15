# -*- coding: utf-8 -*-
"""Phase 7: CurrentMatch & Canonical MatchRecord warehouse slot evidence ingest & monotonic merge."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import main as app_main
from canonical_match_record import (
    build_canonical_match_record_v7,
    validate_canonical_match_record_v7,
    validate_finalized_match_record_v7,
)
from main import CURRENT_MATCH
from vision_pipeline import NTEVisionPipeline


class CurrentMatchWarehouseCanonicalTests(unittest.TestCase):
    def setUp(self):
        self._old_payload = dict(app_main.LATEST_PAYLOAD)
        CURRENT_MATCH.begin_next_match()
        app_main.LATEST_PAYLOAD.clear()

    def tearDown(self):
        CURRENT_MATCH.begin_next_match()
        app_main.LATEST_PAYLOAD.clear()
        app_main.LATEST_PAYLOAD.update(self._old_payload)

    def test_unit_monotonic_merge_and_no_downgrade(self):
        """单元测试：验证单调合并升级，禁止降级，未知轮廓禁止补名"""
        # 初始：1 个 unknown OUTLINE_ONLY 槽位
        raw1 = [
            {"col": 0, "row": 0, "w": 1, "h": 2, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "trackId": 1, "identifiedName": None}
        ]
        wh1 = app_main._merge_canonical_warehouse(None, raw1)
        self.assertIsNotNone(wh1)
        self.assertEqual(len(wh1["slots"]), 1)
        s1 = wh1["slots"][0]
        self.assertEqual(s1["rarity"], "unknown")
        self.assertEqual(s1["evidenceLevel"], "OUTLINE_ONLY")
        self.assertIsNone(s1["identifiedName"])

        # 升级：绕光显色为 gold + RARITY_AND_SHAPE
        raw2 = [
            {"col": 0, "row": 0, "w": 1, "h": 2, "rarity": "gold", "evidenceLevel": "RARITY_AND_SHAPE", "trackId": 1, "identifiedName": None}
        ]
        wh2 = app_main._merge_canonical_warehouse(wh1, raw2)
        s2 = wh2["slots"][0]
        self.assertEqual(s2["rarity"], "gold")
        self.assertEqual(s2["evidenceLevel"], "RARITY_AND_SHAPE")

        # 升级：确定性识别为 "金色大货"
        raw3 = [
            {"col": 0, "row": 0, "w": 1, "h": 2, "rarity": "gold", "evidenceLevel": "EXACT_IDENTIFIED", "trackId": 1, "identifiedName": "金色大货"}
        ]
        wh3 = app_main._merge_canonical_warehouse(wh2, raw3)
        s3 = wh3["slots"][0]
        self.assertEqual(s3["evidenceLevel"], "EXACT_IDENTIFIED")
        self.assertEqual(s3["identifiedName"], "金色大货")

        # 降级尝试：后续较弱帧退化为 OUTLINE_ONLY 且 identifiedName 为 None
        raw4 = [
            {"col": 0, "row": 0, "w": 1, "h": 2, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "trackId": 1, "identifiedName": None}
        ]
        wh4 = app_main._merge_canonical_warehouse(wh3, raw4)
        s4 = wh4["slots"][0]
        # 必须保留最高等级事实，严禁降级
        self.assertEqual(s4["evidenceLevel"], "EXACT_IDENTIFIED")
        self.assertEqual(s4["rarity"], "gold")
        self.assertEqual(s4["identifiedName"], "金色大货")

    def test_schema_constraints_and_validator_compatibility(self):
        """验证 v7 验证器对 warehouse 的可选性与严格性，禁止估值与非授权字段"""
        # 1. 旧 v7 无 warehouse 记录必须继续合法
        rec_legacy = build_canonical_match_record_v7(
            match_id="test_legacy_1",
            played_at="2026-08-17T14:11:56+08:00",
            lifecycle_status="DRAFT",
            environment={"venueTier": "tier1", "venue": "v1", "box": "b1"},
            loadout={"character": "c1"},
            costs={"entry": 5000},
            public_intel={"q": 100},
            qualities={"gold": {"knownItems": []}},
            bidding={"seats": []},
            settlement={"clearingPrice": 0, "actualTotal": 0},
        )
        ok_leg, reasons_leg = validate_canonical_match_record_v7(rec_legacy)
        self.assertTrue(ok_leg, f"legacy v7 without warehouse failed: {reasons_leg}")

        # 2. 新 v7 携带标准 warehouse
        rec_new = dict(rec_legacy)
        rec_new["warehouse"] = {
            "slots": [
                {
                    "col": 0,
                    "row": 0,
                    "w": 1,
                    "h": 2,
                    "rarity": "unknown",
                    "evidenceLevel": "OUTLINE_ONLY",
                    "identifiedName": None,
                }
            ]
        }
        ok_new, reasons_new = validate_canonical_match_record_v7(rec_new)
        self.assertTrue(ok_new, f"new v7 with warehouse failed: {reasons_new}")

        # 3. 非法情况：unknown 带有 identifiedName 时必须报错
        rec_invalid = dict(rec_legacy)
        rec_invalid["warehouse"] = {
            "slots": [
                {
                    "col": 0,
                    "row": 0,
                    "w": 1,
                    "h": 2,
                    "rarity": "unknown",
                    "evidenceLevel": "OUTLINE_ONLY",
                    "identifiedName": "非法臆测名称",
                }
            ]
        }
        ok_inv, reasons_inv = validate_canonical_match_record_v7(rec_invalid)
        self.assertFalse(ok_inv)
        self.assertTrue(any("UNKNOWN_WITH_IDENTIFIED_NAME" in r for r in reasons_inv))

    def test_replay_primary_75s_and_empty_70s_end_to_end(self):
        """端到端验证：14-11-56 @ 75s/90s 摄入、空仓 baseline、to_canonical 序列化"""
        p_primary = Path(r"C:\Users\Administrator\Videos\2026-08-17 14-11-56.mkv")
        p_empty = Path(r"C:\Users\Administrator\Videos\2026-08-17 12-42-40.mkv")

        if p_empty.exists():
            CURRENT_MATCH.begin_next_match()
            cap = cv2.VideoCapture(str(p_empty))
            fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(70.0 * fps))
            ret, f_empty = cap.read()
            cap.release()
            if ret:
                pipe = NTEVisionPipeline(catalog_path=str(PROJECT_ROOT / "assets" / "catalog_065.json"))
                pipe.current_context["scene"] = "IN_AUCTION"
                pipe.current_context["inAuction"] = True
                ctx_empty = pipe.process_frame(f_empty, captured_at="2026-08-17T12:43:50+08:00", record_stable_key="empty", force_refresh=True)
                app_main.process_live_game_frame(f_empty, game_hwnd=7, pipeline_inst=pipe, ctx=ctx_empty)
                
                # AC7: 空仓 baseline 不产生虚假 slots
                wh_fact = CURRENT_MATCH.facts.get("warehouse")
                slots = (wh_fact.get("slots") if isinstance(wh_fact, dict) else []) or []
                self.assertEqual(len(slots), 0, "空仓 baseline 不得产生任何槽位")

        if p_primary.exists():
            CURRENT_MATCH.begin_next_match()
            cap = cv2.VideoCapture(str(p_primary))
            fps = cap.get(cv2.CAP_PROP_FPS) or 60.0

            # 75s
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(75.0 * fps))
            ret1, f75 = cap.read()
            # 90s
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(90.0 * fps))
            ret2, f90 = cap.read()
            cap.release()

            if ret1 and ret2:
                pipe = NTEVisionPipeline(catalog_path=str(PROJECT_ROOT / "assets" / "catalog_065.json"))
                pipe._ensure_ocr()
                pipe.current_context["scene"] = "IN_AUCTION"
                pipe.current_context["inAuction"] = True

                # Step 1: 处理 75s
                ctx75 = pipe.process_frame(f75, captured_at="2026-08-17T14:13:11+08:00", record_stable_key="k75", force_refresh=True)
                app_main.process_live_game_frame(f75, game_hwnd=7, pipeline_inst=pipe, ctx=ctx75)

                # Six visible independent outlines; see warehouse_outline_v1/README.md.
                wh_fact_75 = CURRENT_MATCH.facts.get("warehouse")
                self.assertIsNotNone(wh_fact_75)
                slots_75 = wh_fact_75.get("slots", [])
                from test_warehouse_outline_boundaries import EXPECTED
                self.assertEqual({tuple(s[k] for k in ('col', 'row', 'w', 'h')) for s in slots_75}, EXPECTED)
                self.assertEqual(len(slots_75), 6)

                # AC2: unknown / OUTLINE_ONLY 不产生 identifiedName
                # AC8 / AC9: 不得有估值字段，不得持久化 warehousePresent / scrollState
                for s in slots_75:
                    self.assertEqual(s.get("rarity"), "unknown")
                    self.assertEqual(s.get("evidenceLevel"), "OUTLINE_ONLY")
                    self.assertIsNone(s.get("identifiedName"))
                    self.assertNotIn("totalExpectedVal", s)
                    self.assertNotIn("valRange", s)
                    self.assertNotIn("priceRange", s)
                    self.assertNotIn("expectedPrice", s)
                    self.assertNotIn("warehousePresent", s)
                    self.assertNotIn("scrollState", s)

                self.assertNotIn("warehousePresent", wh_fact_75)
                self.assertNotIn("scrollState", wh_fact_75)

                # Step 2: 连续处理 90s，验证单调合并（AC3）
                ctx90 = pipe.process_frame(f90, captured_at="2026-08-17T14:13:26+08:00", record_stable_key="k90", force_refresh=True)
                app_main.process_live_game_frame(f90, game_hwnd=7, pipeline_inst=pipe, ctx=ctx90)

                wh_fact_90 = CURRENT_MATCH.facts.get("warehouse")
                slots_90 = wh_fact_90.get("slots", [])
                self.assertEqual({tuple(s[k] for k in ('col', 'row', 'w', 'h')) for s in slots_90}, EXPECTED)
                self.assertEqual(len(slots_90), 6, "90s 保持六个独立轮廓，不重复也不降级")
                for s in slots_90:
                    self.assertEqual(s.get("rarity"), "unknown")
                    self.assertEqual(s.get("evidenceLevel"), "OUTLINE_ONLY")
                    self.assertIsNone(s.get("identifiedName"))

                # AC4: to_canonical() 包含 warehouse.slots
                canonical_rec = CURRENT_MATCH.to_canonical()
                self.assertIn("warehouse", canonical_rec)
                self.assertEqual(len(canonical_rec["warehouse"]["slots"]), 6)

                # AC5: Canonical v7 validator 接受带 warehouse 的新记录
                is_valid, reasons = validate_canonical_match_record_v7(canonical_rec)
                self.assertTrue(is_valid, f"Canonical v7 validation failed: {reasons}")


if __name__ == "__main__":
    unittest.main()
