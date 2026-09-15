"""Comprehensive contract and regression tests for Cut 5: Truthful Main + Minimal Read-only History v1."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from main_view_state import (
    MAX_RECENT_RECORDS,
    MainViewStateProvider,
    unavailable_main_view_state_snapshot,
)
from main_window import MainWindowBridge, OverlayVisibilityController


class _FakeOverlay:
    def __init__(self):
        self.Visible = True

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


class TruthfulMainAndMinimalHistoryV1Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_dir = Path(self.temp_dir.name)
        self.history_path = self.history_dir / "user_match_history.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_history(self, records: list[dict]):
        payload = {
            "schemaVersion": 1,
            "records": records,
        }
        self.history_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_main_overview_and_analysis_contain_no_fake_metrics_in_assets(self):
        js = (PROJECT_ROOT / "core" / "main_window.js").read_text(encoding="utf-8")
        html = (PROJECT_ROOT / "core" / "main_window.html").read_text(encoding="utf-8")

        # No fake mock state objects in JavaScript
        self.assertNotIn("mockDashboardState", js)
        self.assertNotIn("mockPredictionPerformanceState", js)
        self.assertNotIn("renderMockDashboard", js)
        self.assertNotIn("renderMockPredictionPerformance", js)

        # No fake hardcoded numbers in JavaScript or HTML
        for fake_val in ("26.17", "1.45 W", "5.42 W", "+8.73 W", "17.44 W", "2,420", "B+"):
            self.assertNotIn(fake_val, js)
            self.assertNotIn(fake_val, html)

        # Overview & History renderers are present
        self.assertIn("function renderOverview(mainViewState)", js)
        self.assertIn("function renderHistory(mainViewState)", js)
        self.assertIn("function renderHistoryDetail(record)", js)

        # Analysis page is honest and structured without fake metrics
        self.assertIn('data-view-page="analysis"', html)
        self.assertIn("analysis-status-card", html)
        self.assertIn("History Admission Policy v1", html)

    def test_history_nav_is_enabled_and_interactive(self):
        html = (PROJECT_ROOT / "core" / "main_window.html").read_text(encoding="utf-8")
        # History button is enabled (not disabled)
        self.assertIn('<button class="nav-item" type="button" data-view-target="history">记录</button>', html)
        # History section is defined
        self.assertIn('data-view-page="history"', html)

    def test_empty_history_produces_clean_empty_state(self):
        # Empty history file
        self._write_history([])
        provider = MainViewStateProvider(self.history_path)
        snapshot = provider.snapshot("2026-08-22T10:00:00+08:00")
        payload = snapshot.to_payload()

        self.assertEqual(payload["history"]["availability"], "EMPTY")
        self.assertEqual(payload["history"]["totalCount"], 0)
        self.assertEqual(payload["history"]["recentRecords"], [])
        self.assertEqual(payload["admission"]["admittedCount"], 0)
        self.assertEqual(payload["admission"]["excludedCount"], 0)
        self.assertEqual(payload["analysis"]["availability"], "INSUFFICIENT_SAMPLES")

    def test_missing_history_file_produces_empty_state_without_error(self):
        # Non-existent history file (first-run)
        non_existent = self.history_dir / "non_existent_history.json"
        provider = MainViewStateProvider(non_existent)
        snapshot = provider.snapshot("2026-08-22T10:00:00+08:00")
        payload = snapshot.to_payload()

        self.assertEqual(payload["history"]["availability"], "UNAVAILABLE")
        self.assertEqual(payload["history"]["reason"], "HISTORY_NOT_FOUND")
        self.assertEqual(payload["history"]["recentRecords"], [])

    def test_corrupt_history_file_fails_soft_without_path_leakage(self):
        self.history_path.write_text("CORRUPTED_JSON{[[", encoding="utf-8")
        provider = MainViewStateProvider(self.history_path)
        snapshot = provider.snapshot("2026-08-22T10:00:00+08:00")
        payload = snapshot.to_payload()

        self.assertEqual(payload["history"]["availability"], "CORRUPT")
        self.assertEqual(payload["history"]["recentRecords"], [])
        self.assertEqual(payload["history"]["reason"], "HISTORY_PARSE_FAILED")
        # Ensure raw temp file path is not leaked into the user-facing reason/description
        self.assertNotIn(str(self.history_path), json.dumps(payload))

    def test_recent_records_bounded_to_max_fifty_sorted_newest_first(self):
        records = [
            {
                "id": f"rec-{i:03d}",
                "lifecycleStatus": "FINALIZED",
                "playedAt": f"2026-08-22T{i % 24:02d}:{(i * 3) % 60:02d}:00+08:00",
                "environment": {"venue": "shanhu", "venueName": "珊瑚场"},
                "predictionSnapshot": {
                    "forecast": {"mode": "full_shadow", "supportStatus": "FULL_SHADOW", "quantiles": {"p20": 100000, "p50": 200000, "p80": 300000}},
                    "decisions": {"recommendedMax": 190000, "actionDirective": "🟢 跟进"},
                },
                "settlement": {
                    "isSettled": True,
                    "clearingPrice": 180000,
                    "actualTotal": 210000,
                    "realizedProfit": 30000,
                    "acquired": True,
                    "winner": "player",
                },
            }
            for i in range(65)
        ]
        self._write_history(records)
        provider = MainViewStateProvider(self.history_path)
        snapshot = provider.snapshot("2026-08-22T23:59:59+08:00")
        payload = snapshot.to_payload()

        recent = payload["history"]["recentRecords"]
        self.assertEqual(len(recent), MAX_RECENT_RECORDS)
        self.assertEqual(len(recent), 50)
        self.assertEqual(payload["history"]["totalCount"], 65)
        # Newest record is rec-064
        self.assertEqual(recent[0]["id"], "rec-064")
        self.assertEqual(recent[-1]["id"], "rec-015")

    def test_history_record_projection_strictly_preserves_persisted_prediction_and_settlement(self):
        record = {
            "id": "match-test-01",
            "lifecycleStatus": "FINALIZED",
            "playedAt": "2026-08-22T14:30:00+08:00",
            "environment": {
                "venue": "haibei",
                "venueName": "海贝场",
                "box": "精钢宝箱",
                "fieldCondition": "standard",
                "fieldConditionName": "标准规则",
            },
            "publicIntel": {"q": 12},
            "qualities": {
                "gold": {"avg": 30000, "knownItems": [{"name": "金藏品A", "price": 45000}]},
                "purple": {"count": 4},
            },
            "predictionSnapshot": {
                "forecast": {
                    "mode": "full_shadow",
                    "supportStatus": "FULL_SHADOW",
                    "quantiles": {"p20": 350000, "p50": 400000, "p80": 480000},
                },
                "decisions": {
                    "recommendedMax": 395000,
                    "actionDirective": "🟢 建议跟进 · 领跑中",
                    "actionReason": "估值健康",
                },
                "input": {"leaderBid": 220000},
            },
            "settlement": {
                "isSettled": True,
                "clearingPrice": 360000,
                "actualTotal": 410000,
                "realizedProfit": 50000,
                "acquired": True,
                "winner": "秋星祭",
                "resultReason": "won",
                "settlementItems": [{"name": "金藏品A", "price": 45000, "rarity": "gold"}],
            },
        }
        self._write_history([record])
        provider = MainViewStateProvider(self.history_path)
        snapshot = provider.snapshot("2026-08-22T15:00:00+08:00")
        payload = snapshot.to_payload()

        recent = payload["history"]["recentRecords"]
        self.assertEqual(len(recent), 1)
        item = recent[0]

        # Environment & authority checks
        self.assertEqual(item["environment"]["venueName"], "海贝场")
        self.assertIsNone(item["environment"]["venueTier"])  # venueTier is NOT game authority
        self.assertEqual(item["environment"]["box"], "精钢宝箱")

        # Observed facts
        self.assertEqual(item["observedFacts"]["q"], 12)
        self.assertEqual(item["observedFacts"]["goldAvg"], 30000)
        self.assertEqual(item["observedFacts"]["purpleCount"], 4)

        # Prediction Snapshot checks: preserved from persisted snapshot
        self.assertTrue(item["prediction"]["hasSnapshot"])
        self.assertEqual(item["prediction"]["p20"], 350000)
        self.assertEqual(item["prediction"]["p50"], 400000)
        self.assertEqual(item["prediction"]["p80"], 480000)
        self.assertEqual(item["prediction"]["recommendedMax"], 395000)
        self.assertEqual(item["prediction"]["actionDirective"], "🟢 建议跟进 · 领跑中")
        self.assertEqual(item["prediction"]["leaderBid"], 220000)

        # Settlement Truth checks: preserved from settlement
        self.assertTrue(item["settlement"]["isSettled"])
        self.assertEqual(item["settlement"]["actualTotal"], 410000)
        self.assertEqual(item["settlement"]["clearingPrice"], 360000)
        self.assertEqual(item["settlement"]["realizedProfit"], 50000)
        self.assertTrue(item["settlement"]["acquired"])
        self.assertEqual(item["settlement"]["winner"], "秋星祭")
        self.assertEqual(item["settlement"]["resultReason"], "won")
        # Bounded projection: raw settlementItems never cross into Main
        self.assertNotIn("settlementItems", item["settlement"])
        self.assertEqual(item["settlement"]["settlementItemCount"], 1)

    def test_draft_and_cancelled_records_are_projected_and_excluded_from_admission(self):
        records = [
            {
                "id": "draft-01",
                "lifecycleStatus": "DRAFT",
                "playedAt": "2026-08-22T10:00:00+08:00",
                "environment": {"venue": "shanhu", "venueName": "珊瑚场"},
            },
            {
                "id": "cancelled-02",
                "lifecycleStatus": "CANCELLED",
                "playedAt": "2026-08-22T11:00:00+08:00",
                "environment": {"venue": "zhenzhu", "venueName": "真珠场"},
            },
        ]
        self._write_history(records)
        provider = MainViewStateProvider(self.history_path)
        snapshot = provider.snapshot("2026-08-22T12:00:00+08:00")
        payload = snapshot.to_payload()

        self.assertEqual(payload["admission"]["admittedCount"], 0)
        self.assertEqual(payload["admission"]["excludedCount"], 2)

        recent = payload["history"]["recentRecords"]
        self.assertEqual(len(recent), 2)

        draft_item = next(r for r in recent if r["id"] == "draft-01")
        self.assertEqual(draft_item["lifecycle"], "DRAFT")
        self.assertFalse(draft_item["admitted"])
        self.assertEqual(draft_item["exclusionReason"], "DRAFT")
        self.assertFalse(draft_item["prediction"]["hasSnapshot"])
        self.assertFalse(draft_item["settlement"]["isSettled"])

        cancelled_item = next(r for r in recent if r["id"] == "cancelled-02")
        self.assertEqual(cancelled_item["lifecycle"], "CANCELLED")
        self.assertFalse(cancelled_item["admitted"])
        self.assertEqual(cancelled_item["exclusionReason"], "CANCELLED")

    def test_main_bridge_dispatch_delivers_fresh_main_view_state(self):
        record = {
            "id": "bridge-rec-01",
            "lifecycleStatus": "FINALIZED",
            "playedAt": "2026-08-22T16:00:00+08:00",
            "environment": {"venue": "shanhu", "venueName": "珊瑚场"},
            "predictionSnapshot": {"forecast": {"mode": "full_shadow", "quantiles": {"p50": 100000}}},
            "settlement": {"isSettled": True, "actualTotal": 120000},
        }
        self._write_history([record])
        provider = MainViewStateProvider(self.history_path)
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            main_view_state_provider=lambda: provider.snapshot("2026-08-22T16:30:00+08:00"),
        )

        response = bridge.dispatch({"action": "request_app_status"})
        self.assertIn("mainViewState", response)
        state = response["mainViewState"]
        self.assertEqual(state["mainViewStateVersion"], 1)
        self.assertEqual(state["history"]["totalCount"], 1)
        self.assertEqual(len(state["history"]["recentRecords"]), 1)
        self.assertEqual(state["history"]["recentRecords"][0]["id"], "bridge-rec-01")


if __name__ == "__main__":
    unittest.main()
