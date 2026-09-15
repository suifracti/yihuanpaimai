# -*- coding: utf-8 -*-
"""Phase 10: HistoryRecordProjection bounded canonical warehouse summary targeted test."""

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

from main_view_state import MainViewStateProvider


class HistoryRecordWarehouseProjectionTests(unittest.TestCase):
    def _dummy_decision(self):
        class DummyDecision:
            normalized_time = None
            lifecycle = "FINALIZED"
            admitted = True
            exclusion_reason = None
        return DummyDecision()

    def test_canonical_slots_project_item_and_unknown_count(self):
        """AC1 & AC2: 5 个 unknown/OUTLINE_ONLY 槽位投射出 itemCount=5, unknownCount=5"""
        record = {
            "id": "match_wh_proj_001",
            "playedAt": "2026-08-17T14:11:56Z",
            "warehouse": {
                "slots": [
                    {"col": 0, "row": 0, "w": 1, "h": 2, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
                    {"col": 1, "row": 0, "w": 3, "h": 2, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
                    {"col": 0, "row": 2, "w": 2, "h": 1, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
                    {"col": 8, "row": 0, "w": 1, "h": 2, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
                    {"col": 9, "row": 0, "w": 1, "h": 3, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
                ]
            }
        }
        proj = MainViewStateProvider._project_record(record, self._dummy_decision())
        self.assertEqual(proj.warehouse_item_count, 5)
        self.assertEqual(proj.warehouse_unknown_count, 5)

        payload = proj.to_payload()
        self.assertIn("warehouse", payload)
        self.assertEqual(payload["warehouse"]["itemCount"], 5)
        self.assertEqual(payload["warehouse"]["unknownCount"], 5)

    def test_legacy_record_without_warehouse(self):
        """AC5: 旧记录无 warehouse 时 payload["warehouse"] 为 None，不伪造 0 件空仓"""
        record = {
            "id": "match_legacy_001",
            "playedAt": "2026-08-17T14:11:56Z",
        }
        proj = MainViewStateProvider._project_record(record, self._dummy_decision())
        self.assertIsNone(proj.warehouse_item_count)
        self.assertIsNone(proj.warehouse_unknown_count)

        payload = proj.to_payload()
        self.assertIsNone(payload["warehouse"])

    def test_mixed_slots_projection(self):
        """混合槽位：2 个确定具名 + 3 个未知轮廓"""
        record = {
            "id": "match_mixed_001",
            "warehouse": {
                "slots": [
                    {"col": 0, "row": 0, "w": 1, "h": 1, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
                    {"col": 1, "row": 0, "w": 1, "h": 1, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
                    {"col": 2, "row": 0, "w": 1, "h": 1, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None},
                    {"col": 0, "row": 1, "w": 2, "h": 2, "rarity": "gold", "evidenceLevel": "EXACT_IDENTIFIED", "identifiedName": "金色大货"},
                    {"col": 2, "row": 1, "w": 1, "h": 2, "rarity": "purple", "evidenceLevel": "UNIQUE_IN_CATALOG", "identifiedName": "紫色藏品"},
                ]
            }
        }
        proj = MainViewStateProvider._project_record(record, self._dummy_decision())
        self.assertEqual(proj.warehouse_item_count, 5)
        self.assertEqual(proj.warehouse_unknown_count, 3)

        payload = proj.to_payload()
        self.assertEqual(payload["warehouse"]["itemCount"], 5)
        self.assertEqual(payload["warehouse"]["unknownCount"], 3)

    def test_html_and_js_contract(self):
        """AC3 & AC4: 验证 HTML 和 JS 中历史详情存在仓库概况容器与格式化逻辑，无物品名/网格/估值注入"""
        html_path = CORE_DIR / "main_window.html"
        js_path = CORE_DIR / "main_window.js"

        html_text = html_path.read_text(encoding="utf-8")
        js_text = js_path.read_text(encoding="utf-8")

        # HTML 容器
        self.assertIn('id="detail-warehouse"', html_text)
        self.assertIn("仓库概况", html_text)

        # JS 渲染
        self.assertIn('setText("detail-warehouse", warehouseText)', js_text)
        self.assertIn("未记录", js_text)
        self.assertIn("（其中", js_text)
        self.assertIn("件未具名）", js_text)


if __name__ == "__main__":
    unittest.main()
