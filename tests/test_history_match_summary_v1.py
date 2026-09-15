# -*- coding: utf-8 -*-
"""Phase 18: Deterministic History Match Summary Targeted Tests.

Verifies AC1-AC13:
- AC1: Deterministic repetition (identical output on repeated runs)
- AC2: Golden example exact match
- AC3: No winnerCharacter sentence
- AC4: loadout.character ("达芙蒂尔") never leaks into summary
- AC5: Ambiguous settlement candidate names never leak into summary
- AC6: Winner missing + clearingPrice known expresses "成交者未识别" without inventing names
- AC7: Missing amounts omitted; true zero amounts preserved as 0
- AC8: All unknown record yields None; UI section hidden
- AC9: Warehouse slots / occupancy counts deterministic and accurate
- AC10: Persisted history file unchanged (pure runtime presentation derivation)
- AC11: Exported records do not contain matchSummary
- AC12: No canonical schema modifications
- AC13: Integration with MainViewStateProvider projection and payload
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

from match_summary import format_match_summary
from main_view_state import MainViewStateProvider, HistoryRecordProjection
from main_window import MainWindowBridge, OverlayVisibilityController


class _FakeOverlay:
    def __init__(self, visible: bool = False):
        self.Visible = visible

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


class _DummyDecision:
    normalized_time = None
    lifecycle = "FINALIZED"
    admitted = True
    exclusion_reason = None


class HistoryMatchSummaryTests(unittest.TestCase):
    def test_canonical_unknown_ownership_does_not_claim_player_profit(self):
        record = {"schemaVersion": 7, "lifecycleStatus": "DRAFT", "settlement": {
            "winner": "ObservedWinner", "clearingPrice": 600000, "actualTotal": 785974,
            "realizedProfit": 185974, "acquired": None}}
        summary = format_match_summary(record)
        self.assertIn("ObservedWinner", summary)
        self.assertIn("实际价值 785,974", summary)
        self.assertNotIn("收益 185,974", summary)
        self.assertIn("归属未知", summary)

    def setUp(self):
        self.golden_record = {
            "id": "match_golden_001",
            "lifecycleStatus": "FINALIZED",
            "playedAt": "2026-08-17T14:11:56Z",
            "publicIntel": {
                "q": 12,
            },
            "qualities": {
                "gold": {
                    "avg": 74379,
                },
                "purple": {
                    "count": 7,
                    "avg": 4357,
                },
            },
            "settlement": {
                "winner": "汐",
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "realizedProfit": -34673,
                "warehouseOccupancy": {
                    "schemaVersion": "settlement-warehouse-occupancy.v1",
                    "tracks": [{"trackId": f"t_{i}"} for i in range(7)],
                },
                "settlementItems": {
                    "candidates": ["拈花小像", "金角月芒"],
                },
            },
            "warehouse": {
                "slots": [
                    {"index": 0, "status": "UNKNOWN"},
                    {"index": 1, "status": "OUTLINE"},
                ],
            },
            "loadout": {
                "character": "达芙蒂尔",
            },
        }

    def test_ac1_deterministic_repetition(self):
        """AC1: Repeated calls on the same record produce identical string output."""
        res1 = format_match_summary(self.golden_record)
        res2 = format_match_summary(self.golden_record)
        self.assertIsNotNone(res1)
        self.assertEqual(res1, res2)

    def test_ac2_golden_example_exact_match(self):
        """AC2: Golden input produces the exact specified multi-section summary."""
        expected = (
            "本局已识别情报：Q=12，金色均价 74,379，紫色数量 7，紫色均价 4,357。"
            "最终由「汐」以 666,666 成交，实际价值 631,993，收益 -34,673。"
            "局内仓库记录 2 个槽位，结算全仓记录 7 个物理占用项，藏品身份仍有未确认项。"
        )
        actual = format_match_summary(self.golden_record)
        self.assertEqual(actual, expected)

    def test_ac3_ac4_ac5_forbidden_fields_not_leaked(self):
        """AC3, AC4, AC5: winnerCharacter, loadout.character, and settlement candidates never leak."""
        summary = format_match_summary(self.golden_record)
        self.assertIsNotNone(summary)

        # AC3 & AC4: Player loadout character "达芙蒂尔" must not appear
        self.assertNotIn("达芙蒂尔", summary)
        self.assertNotIn("winnerCharacter", summary)

        # AC5: Ambiguous candidate item names must not appear
        self.assertNotIn("拈花小像", summary)
        self.assertNotIn("金角月芒", summary)

    def test_ac6_winner_missing_with_amount_known(self):
        """AC6: If winner is missing but clearingPrice is known, expresses '成交者未识别'."""
        record = {
            "settlement": {
                "clearingPrice": 666666,
                "actualTotal": 631993,
                "realizedProfit": -34673,
            }
        }
        summary = format_match_summary(record)
        self.assertIsNotNone(summary)
        self.assertIn("成交者未识别，最终成交价 666,666", summary)
        self.assertIn("实际价值 631,993", summary)
        self.assertIn("收益 -34,673", summary)

    def test_ac7_missing_amounts_omitted_and_zero_preserved(self):
        """AC7: Missing amounts are omitted; true zero amounts are preserved as 0."""
        # Case A: amounts are None/missing
        record_missing = {
            "settlement": {
                "winner": "汐",
            }
        }
        summary_missing = format_match_summary(record_missing)
        self.assertEqual(summary_missing, "最终由「汐」成交。")

        # Case B: amounts are explicitly 0
        record_zero = {
            "settlement": {
                "winner": "汐",
                "clearingPrice": 0,
                "actualTotal": 0,
                "realizedProfit": 0,
            }
        }
        summary_zero = format_match_summary(record_zero)
        self.assertEqual(summary_zero, "最终由「汐」以 0 成交，实际价值 0，收益 0。")

    def test_ac8_all_unknown_yields_none(self):
        """AC8: Completely empty / unknown record produces None."""
        empty_record = {
            "id": "match_empty",
            "playedAt": "2026-08-17T14:11:56Z",
        }
        summary = format_match_summary(empty_record)
        self.assertIsNone(summary)

        # Also verify projection sets match_summary = None
        proj = MainViewStateProvider._project_record(empty_record, _DummyDecision())
        self.assertIsNone(proj.match_summary)
        payload = proj.to_payload()
        self.assertIn("matchSummary", payload)
        self.assertIsNone(payload["matchSummary"])

    def test_ac9_warehouse_slots_and_occupancy_counts(self):
        """AC9: Warehouse slot and occupancy counts are accurate."""
        record = {
            "warehouse": {
                "slots": [{"index": i} for i in range(5)],
            },
            "settlement": {
                "warehouseOccupancy": {
                    "tracks": [{"trackId": f"t_{i}"} for i in range(3)],
                }
            }
        }
        summary = format_match_summary(record)
        self.assertIsNotNone(summary)
        self.assertIn("局内仓库记录 5 个槽位", summary)
        self.assertIn("结算全仓记录 3 个物理占用项", summary)

    def test_ac10_persisted_history_source_unchanged(self):
        """AC10: Projection and summary generation are purely in-memory and do not mutate disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_path = Path(tmpdir) / "异环拍卖数据.json"
            with open(hist_path, "w", encoding="utf-8") as f:
                json.dump({"version": "v0.6", "schemaVersion": 6, "records": [self.golden_record]}, f, indent=2)

            sha_before = hashlib.sha256(hist_path.read_bytes()).hexdigest()

            # Perform projection
            proj = MainViewStateProvider._project_record(self.golden_record, _DummyDecision())
            self.assertIsNotNone(proj.match_summary)

            sha_after = hashlib.sha256(hist_path.read_bytes()).hexdigest()
            self.assertEqual(sha_before, sha_after)

    def test_ac11_export_records_do_not_contain_match_summary(self):
        """AC11: Phase 17 export exports canonical persisted records; matchSummary must not be added to records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hist_path = Path(tmpdir) / "异环拍卖数据.json"
            out_path = Path(tmpdir) / "exported.json"
            with open(hist_path, "w", encoding="utf-8") as f:
                json.dump({"version": "v0.6", "schemaVersion": 6, "records": [self.golden_record]}, f)

            bridge = MainWindowBridge(
                OverlayVisibilityController(_FakeOverlay()),
                history_path_provider=lambda: hist_path,
            )
            res = bridge.dispatch({
                "action": "export_history_records",
                "outputPath": str(out_path),
            })
            self.assertTrue(res["exportResult"]["ok"])

            with open(out_path, "r", encoding="utf-8") as f:
                exported_doc = json.load(f)

            # Records in export must be pure persisted records
            for rec in exported_doc["records"]:
                self.assertNotIn("matchSummary", rec)

    def test_ac12_ui_dom_and_javascript_wiring(self):
        """AC12: UI HTML contains #detail-summary-section and JS binds record.matchSummary."""
        html_path = CORE_DIR / "main_window.html"
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('id="detail-summary-section"', html)
        self.assertIn('id="detail-match-summary"', html)
        self.assertIn("本局总结", html)

        js_path = CORE_DIR / "main_window.js"
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()

        self.assertIn("detail-summary-section", js)
        self.assertIn("detail-match-summary", js)
        self.assertIn("record.matchSummary", js)


if __name__ == "__main__":
    unittest.main()
