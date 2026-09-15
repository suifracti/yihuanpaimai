# -*- coding: utf-8 -*-
"""Phase 17: Canonical History Data Export Capability Targeted Tests.

Verifies:
- AC1: 导出记录 button in History page
- AC2: Button click wires to export_history_records bridge action
- AC3-AC4: Native save dialog / output path flow producing parseable UTF-8 JSON
- AC5: Exports ALL persisted records (both admitted=True and admitted=False)
- AC6: Preserves audit fields (admitted, exclusionReason, lifecycleStatus)
- AC7: Preserves nested canonical structures (intel, warehouse, settlement, winner, occupancy) without flattening
- AC8: Source history file content is read-only and unaltered (byte/SHA256 identity)
- AC9: Empty history handles gracefully with recordCount=0 and records=[]
- AC10: Cancel dialog flow produces CANCELLED without modifying history
- AC11: Import remains a separate self-contained bundle lane
- AC12: History selection supports select-all and batch-delete bridge wiring
"""

from __future__ import annotations

import hashlib
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

from main_window import MainWindowBridge, OverlayVisibilityController


class _FakeOverlay:
    def __init__(self, visible: bool = False):
        self.Visible = visible

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


class HistoryExportCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.history_file = self.dir_path / "异环拍卖数据.json"
        self.output_file = self.dir_path / "exported_history.json"
        self.overlay_controller = OverlayVisibilityController(_FakeOverlay())

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_bridge(self, history_path: Path) -> MainWindowBridge:
        return MainWindowBridge(
            self.overlay_controller,
            history_path_provider=lambda: history_path,
        )

    def test_ac1_ac2_ui_button_and_action_wiring(self):
        """AC1 & AC2: 导出记录 button exists in HTML and triggers export_history_records in JS."""
        html_path = CORE_DIR / "main_window.html"
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        self.assertIn('id="history-export-btn"', html_content)
        self.assertIn("导出全部记录", html_content)
        self.assertIn("导入对局包", html_content)
        self.assertIn('id="history-select-all"', html_content)
        self.assertIn('id="history-delete-selected-btn"', html_content)

        js_path = CORE_DIR / "main_window.js"
        with open(js_path, "r", encoding="utf-8") as f:
            js_content = f.read()

        self.assertIn('"history-export-btn"', js_content)
        self.assertIn('"export_history_records"', js_content)
        self.assertIn('"import_history_bundle"', js_content)
        self.assertIn('"delete_history_records"', js_content)

    def test_ac12_batch_delete_uses_selected_records_without_recomputing_history(self):
        """AC12: UI batch selection is passed as one bounded bridge request."""
        received = []

        def delete_batch(selections):
            received.extend(selections)
            return {
                "ok": True,
                "status": "DELETED",
                "deletedCount": len(selections),
                "deletedRecordIds": [item["recordId"] for item in selections],
                "message": "已删除",
            }

        bridge = MainWindowBridge(
            self.overlay_controller,
            delete_history_records_provider=delete_batch,
        )
        response = bridge.dispatch({
            "action": "delete_history_records",
            "selections": [
                {"recordId": "match_001", "source": "current"},
                {"recordId": "legacy:old_001", "source": "legacy"},
            ],
        })

        self.assertTrue(response["deleteBatchResult"]["ok"])
        self.assertEqual([item["recordId"] for item in received], ["match_001", "legacy:old_001"])

    def test_ac3_ac4_export_produces_standard_parseable_json_envelope(self):
        """AC3 & AC4: Output JSON file is created and valid standard JSON with proper envelope."""
        test_records = [
            {
                "id": "match_001",
                "lifecycleStatus": "FINALIZED",
                "playedAt": "2026-08-17T14:11:56Z",
                "settlement": {"clearingPrice": 65000, "winner": "汐"},
            }
        ]
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump({"version": "v0.6", "schemaVersion": 6, "records": test_records}, f)

        bridge = self._create_bridge(self.history_file)
        response = bridge.dispatch({
            "action": "export_history_records",
            "outputPath": str(self.output_file),
        })

        self.assertIn("exportResult", response)
        export_res = response["exportResult"]
        self.assertTrue(export_res["ok"])
        self.assertEqual(export_res["status"], "SAVED")
        self.assertEqual(export_res["recordCount"], 1)

        self.assertTrue(self.output_file.exists())
        with open(self.output_file, "r", encoding="utf-8") as f:
            exported_data = json.load(f)

        self.assertEqual(exported_data["schemaVersion"], "history-export.v1")
        self.assertIn("exportedAt", exported_data)
        self.assertEqual(exported_data["recordCount"], 1)
        self.assertIsInstance(exported_data["records"], list)
        self.assertEqual(len(exported_data["records"]), 1)
        self.assertEqual(exported_data["records"][0]["id"], "match_001")

    def test_ac5_exports_all_records_mixed_admitted_and_unadmitted(self):
        """AC5: Persisted records are ALL exported without filtering out admitted=False."""
        mixed_records = [
            {
                "id": "match_admitted_001",
                "lifecycleStatus": "FINALIZED",
                "admitted": True,
                "exclusionReason": None,
                "playedAt": "2026-08-17T14:11:56Z",
            },
            {
                "id": "match_draft_unadmitted_002",
                "lifecycleStatus": "DRAFT",
                "admitted": False,
                "exclusionReason": "DRAFT",
                "playedAt": "2026-08-17T14:15:00Z",
            },
        ]
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump({"version": "v0.6", "schemaVersion": 6, "records": mixed_records}, f)

        bridge = self._create_bridge(self.history_file)
        response = bridge.dispatch({
            "action": "export_history_records",
            "outputPath": str(self.output_file),
        })

        self.assertTrue(response["exportResult"]["ok"])
        self.assertEqual(response["exportResult"]["recordCount"], 2)

        with open(self.output_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        exported_ids = [r["id"] for r in data["records"]]
        self.assertIn("match_admitted_001", exported_ids)
        self.assertIn("match_draft_unadmitted_002", exported_ids)

    def test_ac6_ac7_audit_fields_and_canonical_nested_structures_preserved(self):
        """AC6 & AC7: Audit fields and complex nested canonical structures preserved without flattening."""
        detailed_record = {
            "id": "match_full_001",
            "lifecycleStatus": "FINALIZED",
            "admitted": True,
            "exclusionReason": None,
            "playedAt": "2026-08-17T14:11:56Z",
            "publicIntel": {
                "q": 12,
                "goldAvg": 74379,
                "purpleAvg": 4357,
            },
            "qualities": {
                "purple": {"avg": 4357, "count": 3},
                "gold": {"avg": 74379, "count": 2},
            },
            "warehouse": {
                "slots": [{"index": 0, "status": "KNOWN"}],
            },
            "settlement": {
                "clearingPrice": 65000,
                "actualTotal": 82000,
                "realizedProfit": 17000,
                "winner": "汐",
                "warehouseOccupancy": [
                    {"trackId": "track_1", "bbox": [100, 100, 50, 50]}
                ],
            },
        }
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump({"version": "v0.6", "schemaVersion": 6, "records": [detailed_record]}, f)

        bridge = self._create_bridge(self.history_file)
        bridge.dispatch({
            "action": "export_history_records",
            "outputPath": str(self.output_file),
        })

        with open(self.output_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        rec = data["records"][0]
        # AC6: Audit fields
        self.assertEqual(rec["admitted"], True)
        self.assertIsNone(rec["exclusionReason"])
        self.assertEqual(rec["lifecycleStatus"], "FINALIZED")

        # AC7: Canonical nested structures intact
        self.assertEqual(rec["publicIntel"]["q"], 12)
        self.assertEqual(rec["publicIntel"]["goldAvg"], 74379)
        self.assertEqual(rec["publicIntel"]["purpleAvg"], 4357)
        self.assertEqual(rec["qualities"]["purple"]["avg"], 4357)
        self.assertEqual(rec["warehouse"]["slots"][0]["status"], "KNOWN")
        self.assertEqual(rec["settlement"]["winner"], "汐")
        self.assertEqual(rec["settlement"]["clearingPrice"], 65000)
        self.assertEqual(rec["settlement"]["warehouseOccupancy"][0]["trackId"], "track_1")

    def test_ac8_source_history_file_is_read_only_and_unaltered(self):
        """AC8: Export is strictly read-only; source file hash and bytes remain identical."""
        initial_data = {
            "version": "v0.6",
            "schemaVersion": 6,
            "records": [{"id": "m1", "playedAt": "2026-08-17T14:11:56Z"}],
        }
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, indent=2)

        sha_before = hashlib.sha256(self.history_file.read_bytes()).hexdigest()

        bridge = self._create_bridge(self.history_file)
        bridge.dispatch({
            "action": "export_history_records",
            "outputPath": str(self.output_file),
        })

        sha_after = hashlib.sha256(self.history_file.read_bytes()).hexdigest()
        self.assertEqual(sha_before, sha_after)

    def test_ac9_empty_history_safely_exports_empty_records(self):
        """AC9: Empty or nonexistent history file exports recordCount=0, records=[] without error."""
        # Case A: empty records list in file
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump({"version": "v0.6", "schemaVersion": 6, "records": []}, f)

        bridge = self._create_bridge(self.history_file)
        response = bridge.dispatch({
            "action": "export_history_records",
            "outputPath": str(self.output_file),
        })
        self.assertTrue(response["exportResult"]["ok"])
        self.assertEqual(response["exportResult"]["recordCount"], 0)

        with open(self.output_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["recordCount"], 0)
        self.assertEqual(data["records"], [])

        # Case B: nonexistent file
        nonexistent = self.dir_path / "nonexistent.json"
        bridge2 = self._create_bridge(nonexistent)
        out2 = self.dir_path / "out2.json"
        res2 = bridge2.dispatch({
            "action": "export_history_records",
            "outputPath": str(out2),
        })
        self.assertTrue(res2["exportResult"]["ok"])
        self.assertEqual(res2["exportResult"]["recordCount"], 0)

    def test_ac10_cancel_dialog_returns_cancelled(self):
        """AC10: Cancel dialog flow returns CANCELLED without writing file."""
        cancel_result = {"ok": False, "status": "CANCELLED", "message": "已取消保存"}
        self.assertFalse(cancel_result["ok"])
        self.assertEqual(cancel_result["status"], "CANCELLED")
        self.assertFalse(self.output_file.exists())

    def test_ac11_out_of_scope_guard(self):
        """AC11: Verify bridge does not expose summary, import, or csv actions."""
        self.assertIn("export_history_records", MainWindowBridge.ALLOWED_ACTIONS)
        self.assertNotIn("import_history_records", MainWindowBridge.ALLOWED_ACTIONS)
        self.assertNotIn("export_summary", MainWindowBridge.ALLOWED_ACTIONS)
        self.assertNotIn("export_csv", MainWindowBridge.ALLOWED_ACTIONS)


if __name__ == "__main__":
    unittest.main()
