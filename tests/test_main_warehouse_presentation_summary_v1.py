# -*- coding: utf-8 -*-
"""Phase 9: Main page warehouse presentation summary targeted test."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from main import CURRENT_MATCH, get_current_match_presentation_summary


class MainWarehousePresentationSummaryTests(unittest.TestCase):
    def setUp(self):
        CURRENT_MATCH.begin_next_match()

    def tearDown(self):
        CURRENT_MATCH.begin_next_match()

    def test_empty_warehouse_presentation(self):
        """AC2: 空仓保持现有 unrecorded / itemCount=0 呈现"""
        summary = get_current_match_presentation_summary()
        wh = summary.get("warehouse", {})
        self.assertEqual(wh.get("itemCount"), 0)
        self.assertEqual(wh.get("status"), "unrecorded")
        self.assertEqual(wh.get("exactCount"), 0)
        self.assertEqual(wh.get("unknownCount"), 0)

    def test_canonical_slots_project_item_count_and_synced_status(self):
        """AC1 & AC3: 5 个 canonical slots 正确投影为 itemCount=5, status=synced, 未知槽位不猜名称"""
        slots = [
            {"col": 0, "row": 0, "w": 1, "h": 2, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
            {"col": 1, "row": 0, "w": 3, "h": 2, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
            {"col": 0, "row": 2, "w": 2, "h": 1, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
            {"col": 8, "row": 0, "w": 1, "h": 2, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
            {"col": 9, "row": 0, "w": 1, "h": 3, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
        ]
        CURRENT_MATCH.apply_facts({"warehouse": {"slots": slots}}, source="vision")

        summary = get_current_match_presentation_summary()
        wh = summary.get("warehouse", {})

        # AC1: itemCount == 5, status == 'synced'，不再是“未录入/0件”
        self.assertEqual(wh.get("itemCount"), 5)
        self.assertEqual(wh.get("status"), "synced")
        self.assertEqual(wh.get("unknownCount"), 5)
        self.assertEqual(wh.get("exactCount"), 0)
        self.assertTrue(wh.get("evidenceAvailable"))

    def test_ghost_warehouse_items_ignored_canonical_is_sole_authority(self):
        """AC4 & AC5: 幽灵字段 warehouseItems 被彻底废弃，唯一权威来自 facts.warehouse.slots"""
        # 即使有人注入幽灵字段 warehouseItems，Presentation 也绝不读取它
        CURRENT_MATCH.apply_facts({
            "warehouseItems": [{"name": "虚假幽灵藏品1"}, {"name": "虚假幽灵藏品2"}],
            "warehouse": {
                "slots": [
                    {"col": 2, "row": 4, "w": 4, "h": 1, "rarity": "gold", "evidenceLevel": "EXACT_IDENTIFIED", "identifiedName": "金色大货"}
                ]
            }
        }, source="vision")

        summary = get_current_match_presentation_summary()
        wh = summary.get("warehouse", {})

        # 必须是 canonical slots 数量 1，绝不是幽灵字段数量 2
        self.assertEqual(wh.get("itemCount"), 1)
        self.assertEqual(wh.get("exactCount"), 1)
        self.assertEqual(wh.get("unknownCount"), 0)
        self.assertEqual(wh.get("status"), "synced")


if __name__ == "__main__":
    unittest.main()
