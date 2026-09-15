"""0.6 业务闭集必须成为 live 唯一 source of truth。"""

import os
import sys
import unittest

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))

from business_sot import (
    all_boxes,
    canonicalize_box,
    canonicalize_field_condition,
    canonicalize_venue,
    extract_from_text,
    field_conditions,
    live_defaults,
    load_sot,
    venue_entry_cost,
    venues,
)
from vision_pipeline import NTEVisionPipeline
from main import build_in_auction_hud_payload


class TestBusinessSot(unittest.TestCase):
    def test_canonical_sets_from_shared_file(self):
        sot = load_sot()
        self.assertEqual([v["id"] for v in venues()], [
            "未知场地", "初级场 · 海贝场", "中级场 · 珊瑚场", "高级场 · 真珠场"
        ])
        self.assertEqual([c["id"] for c in field_conditions()], [
            "unknown", "standard", "dark", "extraIntel", "purpleDouble", "goldDouble", "sparkle", "welfare", "gemMaze"
        ])
        self.assertIn("浸水的包裹 · 紫色提升", sot["boxesByVenue"]["初级场 · 海贝场"])
        self.assertIn("机械宝箱 · 科技类概率提升", sot["boxesByVenue"]["中级场 · 珊瑚场"])
        self.assertIn("未知高级场箱型", all_boxes())
        self.assertEqual(venue_entry_cost("初级场 · 海贝场"), 0)
        self.assertEqual(venue_entry_cost("中级场 · 珊瑚场"), 5000)
        self.assertIsNone(venue_entry_cost("未知场地"))

    def test_aliases_map_to_canonical(self):
        self.assertEqual(canonicalize_venue("当前：珊瑚场"), "中级场 · 珊瑚场")
        self.assertEqual(canonicalize_venue("海贝场"), "初级场 · 海贝场")
        self.assertEqual(canonicalize_venue("珍珠场"), "高级场 · 真珠场")
        self.assertEqual(canonicalize_venue("真珠场"), "高级场 · 真珠场")
        self.assertEqual(canonicalize_venue("拉冬"), "未知场地")
        self.assertEqual(canonicalize_box("浸水的包裹（低级藏品概率提升）"), "浸水的包裹 · 紫色提升")
        self.assertEqual(canonicalize_box("机械宝箱"), "机械宝箱 · 科技类概率提升")
        self.assertEqual(canonicalize_box("螺钿宝箱"), "螺钿宝箱 · 古董类概率提升")
        self.assertEqual(canonicalize_field_condition("天黑了"), "dark")
        self.assertEqual(canonicalize_field_condition("一手情报"), "extraIntel")
        self.assertEqual(canonicalize_field_condition("加倍！！"), "purpleDouble")
        self.assertEqual(canonicalize_field_condition("加倍！！！"), "goldDouble")
        self.assertEqual(canonicalize_field_condition("闪耀之心"), "sparkle")
        self.assertEqual(canonicalize_field_condition("福利多多"), "welfare")
        self.assertEqual(canonicalize_field_condition("宝石迷阵"), "gemMaze")
        self.assertEqual(canonicalize_field_condition("宝石迷宫"), "gemMaze")

    def test_live_defaults_are_unknown(self):
        defaults = live_defaults()
        self.assertEqual(defaults["venue"], "未知场地")
        self.assertEqual(defaults["box"], "未知箱型")
        self.assertEqual(defaults["fieldCondition"], "unknown")
        self.assertIsNone(defaults["toolGroup"])

    def test_extract_does_not_treat_loading_lore_as_venue(self):
        hit = extract_from_text("「拉冬」与德沃夏克家族签订契约")
        self.assertIsNone(hit["venue"])
        self.assertIsNone(hit["box"])

    def test_live21_loading_and_box(self):
        loading = os.path.join(PROJECT_ROOT, "build", "live_21", "t023.jpg")
        ingame = os.path.join(PROJECT_ROOT, "build", "live_21", "t049.jpg")
        if not os.path.exists(loading) or not os.path.exists(ingame):
            self.skipTest("live_21 frames missing")
        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        ctx = pipe.process_frame(cv2.imdecode(np.fromfile(loading, dtype=np.uint8), cv2.IMREAD_COLOR))
        self.assertEqual(ctx.get("loadingVenue"), "拉冬")
        self.assertNotEqual(ctx.get("venue"), "拉冬")
        self.assertIn(ctx.get("venue") or "未知场地", ("未知场地", None))

        ctx = pipe.process_frame(cv2.imdecode(np.fromfile(ingame, dtype=np.uint8), cv2.IMREAD_COLOR))
        self.assertEqual(ctx.get("box"), "浸水的包裹 · 紫色提升")
        self.assertNotEqual(ctx.get("venue"), "shanhu")
        self.assertNotIn(ctx.get("box"), (None, "standard"))
        payload = build_in_auction_hud_payload(ctx)
        self.assertEqual(payload.get("box"), "浸水的包裹 · 紫色提升")
        self.assertEqual(payload.get("venue") or "未知场地", ctx.get("venue") or "未知场地")
        self.assertIn("fieldCondition", payload)
        self.assertIn("toolGroup", payload)
        self.assertNotIn("boxType", payload)
        self.assertTrue(payload.get("seats"))
        self.assertIn("warehouseVision", payload)


if __name__ == "__main__":
    unittest.main()
