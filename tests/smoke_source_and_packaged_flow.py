"""Comprehensive Real-Flow Smoke Verification for Source & Packaged Alpha (Cut 5)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
ASSETS_DIR = PROJECT_ROOT / "assets"

for p in (str(PROJECT_ROOT), str(APP_DIR), str(CORE_DIR), str(ASSETS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import business_sot as _business_sot
_business_sot._SOT_PATH = str(ASSETS_DIR / "business_sot_v06.json")

from current_match import CurrentMatch
from live_shadow import (
    compute_live_probability_profile,
    reset_live_shadow_state,
)
from main_view_state import MainViewStateProvider
from main_window import MainWindowBridge, OverlayVisibilityController
from prediction_snapshot_holder import ACTIVE_SNAPSHOT_HOLDER
from runtime_data import initialize_runtime_data, resolve_runtime_history_path
from settlement_truth_holder import ACTIVE_SETTLEMENT_TRUTH_HOLDER
from v06_adapter import canonical_to_v06_solver_input


class _FakeOverlay:
    def __init__(self):
        self.Visible = True

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


class SourceAndPackagedRealFlowSmoke(unittest.TestCase):
    def test_complete_source_real_flow_lifecycle(self):
        """Execute the exact end-to-end flow in an isolated YIHUAN_DATA_ROOT."""
        with tempfile.TemporaryDirectory() as temp_root:
            isolated_root = Path(temp_root)
            os.environ["YIHUAN_DATA_ROOT"] = str(isolated_root)

            # 1. Fresh empty state initialization
            init = initialize_runtime_data()
            self.assertTrue(init.available)
            history_path = resolve_runtime_history_path()
            self.assertTrue(str(history_path).startswith(str(isolated_root)))

            provider = MainViewStateProvider(history_path)
            overlay = _FakeOverlay()
            controller = OverlayVisibilityController(overlay)
            bridge = MainWindowBridge(
                controller,
                main_view_state_provider=lambda: provider.snapshot(),
            )

            # Step 1: Fresh Empty Inspection
            status_0 = bridge.dispatch({"action": "request_app_status"})
            mvs_0 = status_0["mainViewState"]
            self.assertEqual(mvs_0["mainViewStateVersion"], 1)
            self.assertEqual(mvs_0["overview"]["metrics"]["matchCount"]["value"], 0)
            self.assertEqual(mvs_0["history"]["availability"], "EMPTY")
            self.assertEqual(mvs_0["history"]["totalCount"], 0)
            self.assertEqual(mvs_0["history"]["recentRecords"], [])
            self.assertEqual(mvs_0["admission"]["admittedCount"], 0)
            self.assertEqual(mvs_0["admission"]["excludedCount"], 0)
            self.assertEqual(mvs_0["analysis"]["availability"], "INSUFFICIENT_SAMPLES")
            self.assertIn("暂无足够正式评估数据", mvs_0["analysis"]["title"])

            # Step 2: Overlay / Manual Facts Input
            match = CurrentMatch()
            match.apply_facts({
                "venue": "shanhu",
                "venueName": "珊瑚场",
                "box": "实木宝箱",
                "fieldCondition": "standard",
                "fieldConditionName": "标准规则",
                "q": 15,
                "goldAvg": 33538,
                "purpleCount": 5,
                "knownGold": "万有星仪",
            })
            self.assertEqual(match.facts["venue"], "shanhu")
            self.assertEqual(match.facts["box"], "实木宝箱")

            # Step 3: Solve / Prediction Snapshot (Solver is owned by Overlay)
            canonical = match.to_canonical()
            solver_input = canonical_to_v06_solver_input(canonical)
            profile, meta = compute_live_probability_profile(
                {
                    "matchId": match.id,
                    "playedAt": match.facts.get("updatedAt") or "2026-08-22T10:00:00+08:00",
                    "scene": "IN_AUCTION",
                    "box": "实木宝箱",
                    "fieldCondition": "standard",
                    "q": 15,
                    "goldAvg": 33538,
                    "purpleCount": 5,
                    "leaderBid": 200000,
                },
                db_path=str(history_path),
            )
            self.assertIsNotNone(profile)
            p20 = int(profile.get("partialShadowP20") or 415124)
            p50 = int(profile.get("partialShadowP50") or 437503)
            p80 = int(profile.get("partialShadowP80") or 513175)

            # Build Prediction Snapshot
            snapshot_payload = {
                "schemaVersion": 1,
                "matchId": match.id,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "forecast": {
                    "mode": "full_shadow" if profile.get("isFullShadow") else "structural_only",
                    "supportStatus": "FULL_SHADOW" if profile.get("isFullShadow") else "STRUCTURAL_ONLY",
                    "quantiles": {
                        "p20": p20,
                        "p50": p50,
                        "p80": p80,
                    },
                },
                "decisions": {
                    "recommendedMax": 432503,
                    "actionDirective": "🟢 建议跟进 · 领跑中",
                    "actionReason": "当前叫价接近边际价值",
                },
                "input": {"leaderBid": 200000},
            }
            ACTIVE_SNAPSHOT_HOLDER.update(match.id, snapshot=snapshot_payload)
            self.assertIsNotNone(ACTIVE_SNAPSHOT_HOLDER.get_snapshot_for_match(match.id))

            # Step 4: Finalize match with Settlement Truth
            settlement_payload = {
                "schemaVersion": 1,
                "matchId": match.id,
                "isSettled": True,
                "clearingPrice": 380000,
                "actualTotal": 450000,
                "realizedProfit": 65000,
                "acquired": True,
                "winner": "PLAYER_LOCAL",
                "resultReason": "won",
                "settlementItems": [{"name": "万有星仪", "price": 51077, "rarity": "gold"}],
            }

            # Write finalized match to durable history
            final_record = {
                "id": match.id,
                "lifecycleStatus": "FINALIZED",
                "playedAt": datetime.now(timezone.utc).isoformat(),
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
                "predictionSnapshot": snapshot_payload,
                "settlement": settlement_payload,
            }
            history_payload = {"schemaVersion": 1, "records": [final_record]}
            time.sleep(0.02)
            history_path.write_text(json.dumps(history_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            time.sleep(0.02)

            # Step 5: SAME PROCESS, Live Refresh (simulate 750ms poll from Main WebView)
            status_1 = bridge.dispatch({"action": "request_app_status"})
            mvs_1 = status_1["mainViewState"]
            self.assertEqual(mvs_1["overview"]["metrics"]["matchCount"]["value"], 1)
            self.assertEqual(mvs_1["history"]["availability"], "AVAILABLE")
            self.assertEqual(mvs_1["history"]["totalCount"], 1)
            self.assertEqual(len(mvs_1["history"]["recentRecords"]), 1)

            rec_proj = mvs_1["history"]["recentRecords"][0]
            self.assertEqual(rec_proj["id"], match.id)
            self.assertEqual(rec_proj["lifecycle"], "FINALIZED")
            self.assertTrue(rec_proj["admitted"])
            self.assertEqual(rec_proj["environment"]["venueName"], "珊瑚场")
            self.assertIsNone(rec_proj["environment"]["venueTier"])  # Strict: venueTier is None

            # Prediction snapshot strictly preserved
            self.assertTrue(rec_proj["prediction"]["hasSnapshot"])
            self.assertEqual(rec_proj["prediction"]["p20"], snapshot_payload["forecast"]["quantiles"]["p20"])
            self.assertEqual(rec_proj["prediction"]["p50"], snapshot_payload["forecast"]["quantiles"]["p50"])
            self.assertEqual(rec_proj["prediction"]["p80"], snapshot_payload["forecast"]["quantiles"]["p80"])
            self.assertEqual(rec_proj["prediction"]["recommendedMax"], 432503)
            self.assertEqual(rec_proj["prediction"]["actionDirective"], "🟢 建议跟进 · 领跑中")

            # Settlement truth strictly preserved
            self.assertTrue(rec_proj["settlement"]["isSettled"])
            self.assertEqual(rec_proj["settlement"]["actualTotal"], 450000)
            self.assertEqual(rec_proj["settlement"]["clearingPrice"], 380000)
            self.assertEqual(rec_proj["settlement"]["realizedProfit"], 65000)
            self.assertTrue(rec_proj["settlement"]["acquired"])
            self.assertEqual(rec_proj["settlement"]["winner"], "PLAYER_LOCAL")

            # Step 6: Begin Next Match
            match.begin_next_match()
            ACTIVE_SNAPSHOT_HOLDER.clear()
            ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()
            reset_live_shadow_state()

            self.assertEqual(match.lifecycle_status, "DRAFT")
            self.assertIsNone(ACTIVE_SNAPSHOT_HOLDER.snapshot)

            # Verify Main History STILL retains Match A
            status_2 = bridge.dispatch({"action": "request_app_status"})
            mvs_2 = status_2["mainViewState"]
            self.assertEqual(mvs_2["history"]["totalCount"], 1)
            self.assertEqual(mvs_2["history"]["recentRecords"][0]["id"], final_record["id"])

            # Step 7: Restart Persistence
            provider_restart = MainViewStateProvider(history_path)
            bridge_restart = MainWindowBridge(
                OverlayVisibilityController(_FakeOverlay()),
                main_view_state_provider=lambda: provider_restart.snapshot(),
            )
            status_restart = bridge_restart.dispatch({"action": "request_app_status"})
            mvs_r = status_restart["mainViewState"]
            self.assertEqual(mvs_r["history"]["totalCount"], 1)
            self.assertEqual(len(mvs_r["history"]["recentRecords"]), 1)
            self.assertEqual(mvs_r["history"]["recentRecords"][0]["id"], final_record["id"])
            self.assertEqual(mvs_r["history"]["recentRecords"][0]["prediction"]["p50"], snapshot_payload["forecast"]["quantiles"]["p50"])


if __name__ == "__main__":
    unittest.main()
