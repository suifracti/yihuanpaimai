# -*- coding: utf-8 -*-
"""Phase 8: AutoArchiver canonical warehouse preservation test."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from auto_archiver import AutoArchiver
from canonical_match_record import validate_canonical_match_record_v7


class AutoArchiverWarehouseCanonicalTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "异环拍卖数据.json")
        self.archiver = AutoArchiver(db_paths=[self.db_path])

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _base_ctx(self, match_id: str = "test_match_001"):
        return {
            "id": match_id,
            "isSettlement": True,
            "settlementReady": True,
            "settlementFinalized": False,
            "settlementData": {
                "isSettlement": True,
                "clearingPrice": 65000,
                "actualTotal": 88000,
                "profit": 18000,
                "winner": "玩家本人",
            },
            "myName": "玩家本人",
            "winner": "玩家本人",
            "venue": "shanhu",
            "venueTier": "tier1",
            "box": "实木宝箱",
            "boxType": "wood",
            "fieldCondition": "standard",
            "q": 15,
            "myBid": 65000,
            "costs": {"entry": 5000},
            "opponents": [],
        }

    def test_archive_with_warehouse_preserves_slots_in_memory_and_on_disk(self):
        """AC1 & AC3: archive_match 返回与写盘记录均完整保留 warehouse.slots"""
        ctx = self._base_ctx("match_with_wh_001")
        canonical_slots = [
            {"col": 0, "row": 0, "w": 1, "h": 3, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None, "trackId": 1},
            {"col": 1, "row": 0, "w": 1, "h": 1, "rarity": "unknown", "evidenceLevel": "OUTLINE_ONLY", "identifiedName": None, "trackId": 2},
            {"col": 2, "row": 4, "w": 4, "h": 1, "rarity": "gold", "evidenceLevel": "EXACT_IDENTIFIED", "identifiedName": "金色大货", "trackId": 3},
        ]
        ctx["warehouse"] = {"slots": canonical_slots}

        record = self.archiver.archive_match(ctx)
        self.assertIsNotNone(record, "archive_match should succeed")
        
        # 内存中 record 检查
        self.assertIn("warehouse", record)
        self.assertIn("slots", record["warehouse"])
        archived_slots = record["warehouse"]["slots"]
        self.assertEqual(len(archived_slots), 3)
        self.assertEqual(archived_slots[0]["rarity"], "unknown")
        self.assertEqual(archived_slots[0]["evidenceLevel"], "OUTLINE_ONLY")
        self.assertIsNone(archived_slots[0]["identifiedName"])
        self.assertEqual(archived_slots[2]["identifiedName"], "金色大货")

        # 磁盘 JSON 检查
        self.assertTrue(os.path.exists(self.db_path), "DB file must exist")
        with open(self.db_path, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        
        records = disk_data.get("records", [])
        self.assertEqual(len(records), 1)
        disk_rec = records[0]
        self.assertIn("warehouse", disk_rec)
        disk_slots = disk_rec["warehouse"]["slots"]
        self.assertEqual(len(disk_slots), 3)
        self.assertEqual(disk_slots[0]["rarity"], "unknown")
        self.assertIsNone(disk_slots[0]["identifiedName"])
        self.assertEqual(disk_slots[2]["identifiedName"], "金色大货")

        # 校验器通过
        is_valid, reasons = validate_canonical_match_record_v7(disk_rec)
        self.assertTrue(is_valid, f"Archived record should be valid v7: {reasons}")

    def test_unknown_identity_fail_closed(self):
        """AC2: 即使 ctx 中传入带名字的 unknown/OUTLINE_ONLY，archive 也必须强制 fail-closed 置 None"""
        ctx = self._base_ctx("match_fail_closed_001")
        ctx["warehouse"] = {
            "slots": [
                {
                    "col": 0, "row": 0, "w": 1, "h": 2,
                    "rarity": "unknown",
                    "evidenceLevel": "OUTLINE_ONLY",
                    "identifiedName": "非法臆测名称",
                }
            ]
        }
        record = self.archiver.archive_match(ctx)
        self.assertIsNotNone(record)
        slot = record["warehouse"]["slots"][0]
        self.assertIsNone(slot["identifiedName"], "unknown/OUTLINE_ONLY 槽位 identifiedName 必须强制为 None")

    def test_archive_without_warehouse_backward_compatible(self):
        """AC4: 不带 warehouse 的旧 ctx 仍能正常归档，保持向后兼容"""
        ctx = self._base_ctx("match_legacy_001")
        self.assertNotIn("warehouse", ctx)

        record = self.archiver.archive_match(ctx)
        self.assertIsNotNone(record, "legacy ctx archive should succeed")
        self.assertNotIn("warehouse", record)

        with open(self.db_path, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        self.assertEqual(len(disk_data.get("records", [])), 1)
        is_valid, reasons = validate_canonical_match_record_v7(disk_data["records"][0])
        self.assertTrue(is_valid, f"Legacy record should be valid v7: {reasons}")


if __name__ == "__main__":
    unittest.main()
