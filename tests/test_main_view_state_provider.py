import ast
import dataclasses
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from main_view_state import (  # noqa: E402
    LOCAL_TIME_ZONE,
    MainViewStateProvider,
)
from main_window import MainWindowBridge, OverlayVisibilityController  # noqa: E402


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=LOCAL_TIME_ZONE)


class _FakeOverlay:
    def __init__(self):
        self.Visible = True

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


def _finalized(record_id, played_at):
    return {
        "id": record_id,
        "lifecycleStatus": "FINALIZED",
        "playedAt": played_at,
    }


def _verified_legacy(record_id, played_at):
    return {
        "id": record_id,
        "playedAt": played_at,
        "actualTotal": 100,
        "settlement": {
            "status": "verified",
            "verified": True,
            "actualTotal": 100,
        },
    }


def _write_history(path, records):
    path.write_text(
        json.dumps({"schemaVersion": 6, "records": records}, ensure_ascii=False),
        encoding="utf-8",
    )


class MainViewStateProviderTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory(prefix="nte-main-view-state-")
        self.history_path = Path(self._temp_dir.name) / "history.json"

    def tearDown(self):
        self._temp_dir.cleanup()

    def _snapshot(self, records):
        _write_history(self.history_path, records)
        return MainViewStateProvider(self.history_path).snapshot(NOW)

    def test_admission_policy_handles_finalized_legacy_draft_cancelled_and_diagnostic(self):
        records = [
            _finalized("final", "2026-08-21T10:00:00"),
            _verified_legacy("legacy", "2026-08-21T10:01:00"),
            {
                "id": "auto",
                "playedAt": "2026-08-21T10:02:00",
                "source": "0.65-vision-auto-archiver",
                "actualTotal": 100,
                "clearingPrice": 80,
            },
            {
                "id": "draft",
                "lifecycleStatus": "DRAFT",
                "playedAt": "2026-08-21T10:03:00",
            },
            {
                "id": "cancelled",
                "lifecycleStatus": "CANCELLED",
                "playedAt": "2026-08-21T10:04:00",
            },
            {
                "id": "diagnostic",
                "lifecycleStatus": "FINALIZED",
                "playedAt": "2026-08-21T10:05:00",
                "diagnosticOnly": True,
            },
            {"id": "unverified", "playedAt": "2026-08-21T10:06:00"},
        ]

        payload = self._snapshot(records).to_payload()

        self.assertEqual(payload["admission"]["admittedCount"], 3)
        self.assertEqual(payload["admission"]["excludedCount"], 4)
        self.assertEqual(
            payload["admission"]["exclusionReasonCounts"],
            {
                "CANCELLED": 1,
                "DIAGNOSTIC": 1,
                "DRAFT": 1,
                "LEGACY_WITHOUT_SETTLEMENT_EVIDENCE": 1,
            },
        )
        metric = payload["overview"]["metrics"]["matchCount"]
        self.assertEqual(metric["value"], 3)
        self.assertEqual(metric["excludedN"], 4)

    def test_naive_and_aware_timestamps_share_asia_shanghai_day_boundary(self):
        records = [
            _finalized("naive-today", "2026-08-21T00:01:00"),
            _finalized("utc-today", "2026-08-20T16:01:00+00:00"),
            _finalized("naive-yesterday", "2026-08-20T23:59:00"),
            _finalized("utc-yesterday", "2026-08-20T15:59:00+00:00"),
        ]

        metric = self._snapshot(records).to_payload()["overview"]["metrics"]["matchCount"]

        self.assertEqual(metric["value"], 2)
        self.assertEqual(metric["comparison"]["previousValue"], 2)
        self.assertEqual(metric["comparison"]["absoluteDelta"], 0)
        self.assertEqual(metric["comparison"]["relativeDelta"], 0.0)

    def test_yesterday_comparison_and_series_are_presentation_ready(self):
        records = [
            _finalized("today-1", "2026-08-21T01:00:00"),
            _finalized("today-2", "2026-08-21T02:00:00"),
            _finalized("today-3", "2026-08-21T03:00:00"),
            _finalized("yesterday-1", "2026-08-20T01:00:00"),
            _finalized("yesterday-2", "2026-08-20T02:00:00"),
        ]

        metric = self._snapshot(records).to_payload()["overview"]["metrics"]["matchCount"]

        self.assertEqual(metric["value"], 3)
        self.assertEqual(metric["sampleN"], 3)
        self.assertEqual(metric["comparison"]["previousValue"], 2)
        self.assertEqual(metric["comparison"]["absoluteDelta"], 1)
        self.assertEqual(metric["comparison"]["relativeDelta"], 0.5)
        self.assertEqual(len(metric["series"]), 12)
        self.assertEqual(metric["series"][-2:], [
            {"date": "2026-08-20", "value": 2},
            {"date": "2026-08-21", "value": 3},
        ])

    def test_zero_previous_value_has_null_relative_delta(self):
        snapshot = self._snapshot([_finalized("today", "2026-08-21T01:00:00")])
        comparison = snapshot.to_payload()["overview"]["metrics"]["matchCount"]["comparison"]
        self.assertEqual(comparison["previousValue"], 0)
        self.assertEqual(comparison["absoluteDelta"], 1)
        self.assertIsNone(comparison["relativeDelta"])

    def test_duplicate_record_ids_fail_closed(self):
        snapshot = self._snapshot([
            _finalized("duplicate", "2026-08-21T01:00:00"),
            _finalized("duplicate", "2026-08-21T02:00:00"),
        ])
        payload = snapshot.to_payload()
        self.assertEqual(payload["admission"]["admittedCount"], 0)
        self.assertEqual(payload["admission"]["excludedCount"], 2)
        self.assertEqual(
            payload["admission"]["exclusionReasonCounts"],
            {"DUPLICATE_RECORD_ID": 2},
        )

    def test_source_revision_cache_hits_and_returns_same_immutable_snapshot(self):
        _write_history(self.history_path, [_finalized("one", "2026-08-21T01:00:00")])
        provider = MainViewStateProvider(self.history_path)

        with mock.patch.object(
            provider, "_read_stable_bytes", wraps=provider._read_stable_bytes
        ) as reader:
            first = provider.snapshot(NOW)
            second = provider.snapshot(NOW)

        self.assertIs(first, second)
        self.assertEqual(reader.call_count, 1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            first.generated_at = "tampered"

    def test_source_change_invalidates_cache_and_hash(self):
        _write_history(self.history_path, [_finalized("one", "2026-08-21T01:00:00")])
        provider = MainViewStateProvider(self.history_path)
        first = provider.snapshot(NOW)

        _write_history(self.history_path, [
            _finalized("one", "2026-08-21T01:00:00"),
            _finalized("two", "2026-08-21T02:00:00"),
        ])
        second = provider.snapshot(NOW)

        self.assertIsNot(first, second)
        self.assertNotEqual(first.history_revision.sha256, second.history_revision.sha256)
        self.assertEqual(second.match_count.value, 2)

    def test_payload_is_fresh_and_contains_no_raw_record_authority(self):
        snapshot = self._snapshot([_verified_legacy("rec-1", "2026-08-21T01:00:00")])
        first = snapshot.to_payload()
        first["overview"]["metrics"]["matchCount"]["series"][0]["value"] = 999
        first["history"]["recentRecords"][0]["id"] = "tampered-id"
        second = snapshot.to_payload()
        self.assertNotEqual(
            second["overview"]["metrics"]["matchCount"]["series"][0]["value"],
            999,
        )
        self.assertEqual(
            second["history"]["recentRecords"][0]["id"],
            "rec-1",
        )
        serialized = json.dumps(second, ensure_ascii=False)
        for forbidden in (
            '"bids"',
            '"solverInput"',
            '"CurrentMatch"',
            '"LATEST_PAYLOAD"',
            '"candidateGs"',
            '"probabilityWeights"',
            '"rawShadow"',
        ):
            self.assertNotIn(forbidden, serialized)

    def test_bounded_recent_records_capped_at_fifty_and_newest_first(self):
        records = [
            _finalized(f"match-{i:03d}", f"2026-08-21T{i%24:02d}:00:00")
            for i in range(60)
        ]
        payload = self._snapshot(records).to_payload()
        recent = payload["history"]["recentRecords"]
        self.assertEqual(len(recent), 50)
        self.assertEqual(payload["history"]["totalCount"], 60)
        # Newest record is match-059
        self.assertEqual(recent[0]["id"], "match-059")
        self.assertEqual(recent[-1]["id"], "match-010")

    def test_history_projection_handles_prediction_snapshot_and_settlement_separation(self):
        record = {
            "id": "match-full-001",
            "lifecycleStatus": "FINALIZED",
            "playedAt": "2026-08-21T10:00:00+08:00",
            "environment": {
                "venue": "shanhu",
                "venueName": "珊瑚场",
                "box": "实木宝箱",
                "fieldCondition": "standard",
                "fieldConditionName": "标准规则",
            },
            "publicIntel": {"q": 15},
            "qualities": {
                "gold": {"avg": 33538, "knownItems": [{"name": "万有星仪", "price": 51077}]},
                "purple": {"count": 5},
            },
            "predictionSnapshot": {
                "forecast": {
                    "mode": "full_shadow",
                    "supportStatus": "FULL_SHADOW",
                    "quantiles": {"p20": 415124, "p50": 437503, "p80": 513175},
                },
                "decisions": {
                    "recommendedMax": 432503,
                    "actionDirective": "🟢 建议跟进 · 领跑中",
                    "actionReason": "当前叫价接近边际价值",
                },
                "input": {"leaderBid": 200000},
            },
            "settlement": {
                "isSettled": True,
                "clearingPrice": 380000,
                "actualTotal": 450000,
                "realizedProfit": 65000,
                "acquired": True,
                "winner": "PLAYER_LOCAL",
                "resultReason": "won",
                "settlementItems": [{"name": "万有星仪", "price": 51077, "rarity": "gold"}],
            },
        }
        payload = self._snapshot([record]).to_payload()
        recent = payload["history"]["recentRecords"]
        self.assertEqual(len(recent), 1)
        item = recent[0]
        self.assertEqual(item["id"], "match-full-001")
        self.assertEqual(item["lifecycle"], "FINALIZED")
        self.assertTrue(item["admitted"])
        self.assertEqual(item["environment"]["venueName"], "珊瑚场")
        self.assertIsNone(item["environment"]["venueTier"])  # Strict: venueTier is NOT game authority

        # Prediction is preserved from snapshot, NOT overwritten by settlement
        self.assertTrue(item["prediction"]["hasSnapshot"])
        self.assertEqual(item["prediction"]["p50"], 437503)
        self.assertEqual(item["prediction"]["recommendedMax"], 432503)
        self.assertEqual(item["prediction"]["leaderBid"], 200000)

        # Settlement is preserved from settlement truth
        self.assertTrue(item["settlement"]["isSettled"])
        self.assertEqual(item["settlement"]["actualTotal"], 450000)
        self.assertEqual(item["settlement"]["clearingPrice"], 380000)
        self.assertEqual(item["settlement"]["realizedProfit"], 65000)
        self.assertTrue(item["settlement"]["acquired"])
        # Bounded projection: raw settlementItems never cross into Main
        self.assertNotIn("settlementItems", item["settlement"])
        self.assertEqual(item["settlement"]["settlementItemCount"], 1)

    def test_history_projection_strictly_reflects_persisted_prediction_and_never_fabricates(self):
        # A draft or record without prediction snapshot
        record = {
            "id": "draft-no-pred",
            "lifecycleStatus": "DRAFT",
            "playedAt": "2026-08-21T11:00:00+08:00",
            "environment": {"venue": "haibei", "venueName": "海贝场"},
        }
        payload = self._snapshot([record]).to_payload()
        item = payload["history"]["recentRecords"][0]
        self.assertEqual(item["lifecycle"], "DRAFT")
        self.assertFalse(item["admitted"])
        self.assertEqual(item["exclusionReason"], "DRAFT")
        self.assertFalse(item["prediction"]["hasSnapshot"])
        self.assertIsNone(item["prediction"]["p50"])
        self.assertIsNone(item["prediction"]["recommendedMax"])
        self.assertIsNone(item["prediction"]["actionDirective"])

    def test_auction_observations_survive_history_projection_without_shared_mutation(self):
        evidence={'ownerMatchId':'flow-a','intel':[{'round':2,'lines':[{'text':'随机展示5件藏品'}]}],
                  'bids':[{'seats':[{'slot':2,'currentBid':0}]}], 'warehouse':[{'slots':[{'w':2,'h':2,'identityStatus':'UNKNOWN'}]}]}
        snapshot=self._snapshot([{'id':'flow-a','lifecycleStatus':'DRAFT','auctionEvidence':evidence}])
        projected=snapshot.to_payload()['history']['recentRecords'][0]['auctionEvidence']
        self.assertEqual(projected,evidence)
        projected['intel'].clear()
        self.assertEqual(len(snapshot.to_payload()['history']['recentRecords'][0]['auctionEvidence']['intel']),1)

    def test_provider_imports_no_solver_current_match_shadow_vision_or_ocr_module(self):
        source = (APP_DIR / "main_view_state.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue(
            imported_roots.isdisjoint(
                {"current_match", "live_shadow", "auction_engine_v06", "vision_pipeline", "ocr"}
            )
        )

    def test_bridge_reuses_existing_action_and_serializes_only_snapshot_payload(self):
        _write_history(self.history_path, [_finalized("one", "2026-08-21T01:00:00")])
        provider = MainViewStateProvider(self.history_path)
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            main_view_state_provider=lambda: provider.snapshot(NOW),
        )

        response = bridge.dispatch({"action": "request_app_status"})

        self.assertEqual(response["mainViewState"]["mainViewStateVersion"], 1)
        self.assertEqual(response["mainViewState"]["overview"]["metrics"]["matchCount"]["value"], 1)
        self.assertEqual(len(response["mainViewState"]["history"]["recentRecords"]), 1)
        self.assertEqual(
            MainWindowBridge.ALLOWED_ACTIONS - {'request_original_screenshots', 'delete_original_screenshot', 'restore_original_screenshot'},
            frozenset(("toggle_overlay", "get_overlay_visibility", "toggle_main_pin", "set_main_pin", "request_app_status", "delete_history_record", "delete_history_records", "request_legacy_archive", "select_legacy_archive_source", "request_settlement_review", "import_settlement_screenshot", "replace_settlement_screenshot", "delete_settlement_screenshot", "rerun_settlement_recognition", "save_settlement_review", "settlement_item_review_action", "manual_facts", "manual_next_match", "manual_finalize", "manual_bootstrap", "start_live_vision", "export_reviewed_labels", "triggered_snapshot", "save_settlement_screenshot", "save_game_screenshot", "start_warehouse_capture", "prepare_warehouse_capture", "confirm_warehouse_capture", "stop_warehouse_capture", "warehouse_identity_review", "export_history_records", "import_history_bundle")),
        )

    def test_bridge_fail_softs_mutable_main_view_state_provider_result(self):
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            main_view_state_provider=lambda: {"records": []},
        )
        response = bridge.dispatch({"action": "request_app_status"})
        self.assertEqual(
            response["mainViewState"]["history"]["reason"],
            "HISTORY_PROVIDER_INVALID",
        )

    def test_ui_replaces_all_mocks_with_truthful_main_view_state(self):
        javascript = (PROJECT_ROOT / "core" / "main_window.js").read_text(encoding="utf-8")
        html = (PROJECT_ROOT / "core" / "main_window.html").read_text(encoding="utf-8")
        self.assertNotIn("mockDashboardState", javascript)
        self.assertNotIn("mockPredictionPerformanceState", javascript)
        self.assertNotIn("2,420", javascript)
        self.assertNotIn("2,420", html)
        self.assertNotIn("B+", javascript)
        self.assertNotIn("B+", html)
        self.assertNotIn("部分演示", html)
        self.assertIn("function renderOverview(mainViewState)", javascript)
        self.assertIn("function renderHistory(mainViewState)", javascript)
        self.assertIn("真实历史", html)
        self.assertIn('data-view-target="history"', html)


if __name__ == "__main__":
    unittest.main()
