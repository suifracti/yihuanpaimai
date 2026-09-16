# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for Strategy UX Metrics & User Strategy State Management.

Verifies all PR-A external review requirements:
1. Mean is NOT impersonated by P50: meanEstimate is None with meanSource='unavailable'
   unless a true distribution mean or explicit expectation is provided.
2. Median is legitimately sourced from P50 (medianSource='p50_point').
3. Conservative estimate is strictly from P20 (conservativeSource='p20_point') or None.
4. Single Authoritative Store (SSOT) across HUD, WebView JS bridge, AuctionBrain, and payload builders.
5. Typed, fail-closed validation reducer for WebView actions (Enum coercion, range checks, whitelist).
6. Fast mode is marked fastModeAvailable=False (Option 2) and attempting to enable it is rejected fail-closed.
7. Real bridge actions (HudJsApi.strategy_edit/undo/redo) execute without AttributeError on .value.
8. History capacity limit (50) and clearing redo on divergent edits.
9. Match reset lifecycle: resets on new match identity; repeated settlement frames DO NOT reset.
10. Strict isolation: CurrentMatch facts are 100% untouched by strategy mutations.
11. PR #1 Boundary 3 input chain files remain 100% untouched.
"""

import copy
import os
import subprocess
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
APP_DIR = os.path.join(PROJECT_ROOT, "app")
for p in (PROJECT_ROOT, CORE_DIR, APP_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy_ux_metrics import (
    EstimateMode,
    StrategyProfile,
    StrategyMetricsSummary,
    StrategyPanelShellState,
    UserEditCommand,
    UserStrategyState,
    UserStrategyEditHistory,
    compute_strategy_metrics_summary,
    get_authoritative_strategy_store,
    set_authoritative_strategy_store,
)
from auction_brain import AuctionBrain
from auto_archiver import AutoArchiver
from vision_contract import VisionObservation, VisionIntel, VisionBids, VisionSettlement
from current_match import CurrentMatch
from main import HudJsApi, build_in_auction_hud_payload, build_nav_hud_payload


class TestStrategyMetricsProvenance(unittest.TestCase):
    """Tests verifying Fix A: Mean is never impersonated from P50, and provenance is exact."""

    def test_01_mean_unavailable_when_missing_distribution_expectation(self):
        """Verify that when only P50 is present, meanEstimate is None with meanSource='unavailable'."""
        summary = compute_strategy_metrics_summary(
            mode=EstimateMode.PRECISE,
            val_p50=100000.0,
            val_p20=90000.0,
            val_p80=110000.0,
        )
        # Mean MUST NOT equal P50!
        self.assertIsNone(summary.meanEstimate)
        self.assertEqual(summary.meanSource, "unavailable")

        # Median legitimately reflects P50
        self.assertEqual(summary.medianEstimate, 100000.0)
        self.assertEqual(summary.medianSource, "p50_point")

        # Conservative legitimately reflects P20
        self.assertEqual(summary.conservativeEstimate, 90000.0)
        self.assertEqual(summary.conservativeSource, "p20_point")

        self.assertTrue(summary.productionEligible)
        self.assertFalse(summary.experimental)

    def test_02_true_mean_provenance(self):
        """Verify true mean displays when explicit expectation or distribution mean is present."""
        # Case A: explicit mean_val
        summary_explicit = compute_strategy_metrics_summary(
            mode=EstimateMode.PRECISE,
            val_p50=100000.0,
            mean_val=105432.0,
        )
        self.assertEqual(summary_explicit.meanEstimate, 105432.0)
        self.assertEqual(summary_explicit.meanSource, "explicit_mean")
        self.assertEqual(summary_explicit.medianEstimate, 100000.0)
        self.assertEqual(summary_explicit.medianSource, "p50_point")

        # Case B: distribution forecast mean in snapshot
        snapshot = {
            "forecast": {
                "mean": 98765.0,
                "quantiles": {"p20": 85000.0, "p50": 95000.0, "p80": 110000.0},
            }
        }
        summary_snapshot = compute_strategy_metrics_summary(
            mode=EstimateMode.PRECISE,
            prediction_snapshot=snapshot,
        )
        self.assertEqual(summary_snapshot.meanEstimate, 98765.0)
        self.assertEqual(summary_snapshot.meanSource, "distribution_mean")
        self.assertEqual(summary_snapshot.medianEstimate, 95000.0)
        self.assertEqual(summary_snapshot.medianSource, "p50_point")
        self.assertEqual(summary_snapshot.conservativeEstimate, 85000.0)
        self.assertEqual(summary_snapshot.conservativeSource, "p20_point")

    def test_03_conservative_unavailability_never_fabricates_values(self):
        """Verify when no legal lower quantile exists, conservativeEstimate is strictly None."""
        summary = compute_strategy_metrics_summary(
            mode=EstimateMode.PRECISE,
            val_p50=150000.0,
            val_p20=None,
            val_p80=None,
        )
        self.assertIsNone(summary.meanEstimate)
        self.assertEqual(summary.meanSource, "unavailable")
        self.assertEqual(summary.medianEstimate, 150000.0)
        self.assertEqual(summary.medianSource, "p50_point")
        self.assertIsNone(summary.conservativeEstimate)
        self.assertEqual(summary.conservativeSource, "unavailable")


class TestStrategySSOTAndBridge(unittest.TestCase):
    """Tests verifying Fix B, Fix C, Fix D, Fix F: Single SSOT, typed reducer, Fast unavailable."""

    def setUp(self):
        # Create a fresh isolated store for testing
        self.store = UserStrategyEditHistory(capacity=5)
        set_authoritative_strategy_store(self.store)
        self.api = HudJsApi()

    def test_04_single_ssot_synchronization(self):
        """Verify modifying store via API immediately synchronizes across AuctionBrain and HUD payload."""
        brain = AuctionBrain(strategy_store=self.store)
        self.assertEqual(brain.strategy_history.state.strategy_profile, StrategyProfile.DEFAULT)

        # Edit via API
        res = self.api.strategy_edit({"field": "strategy_profile", "value": "balanced"})
        self.assertEqual(res["status"], "ok")

        # Authoritative store has changed
        self.assertEqual(self.store.state.strategy_profile, StrategyProfile.BALANCED)
        # AuctionBrain sees the change immediately
        self.assertEqual(brain.strategy_history.state.strategy_profile, StrategyProfile.BALANCED)

        # In-auction payload reflects the change
        ctx = {"round": 1, "venue": "haibei", "q": 9, "goldAvg": 30000}
        payload = build_in_auction_hud_payload(ctx)
        self.assertEqual(payload["strategyPanel"]["strategyProfile"], "balanced")

        # Undo restores all components simultaneously
        undo_res = self.api.strategy_undo()
        self.assertEqual(undo_res["status"], "ok")
        self.assertEqual(self.store.state.strategy_profile, StrategyProfile.DEFAULT)
        self.assertEqual(brain.strategy_history.state.strategy_profile, StrategyProfile.DEFAULT)

    def test_05_webview_action_typed_reducer_and_fail_closed(self):
        """Verify typed reducer converts strings to Enums and fails closed on invalid inputs."""
        # 1. Valid string enum coercion
        res_prof = self.api.strategy_edit({"field": "strategy_profile", "value": "aggressive"})
        self.assertEqual(res_prof["status"], "ok")
        self.assertIsInstance(self.store.state.strategy_profile, StrategyProfile)
        self.assertEqual(self.store.state.strategy_profile, StrategyProfile.AGGRESSIVE)
        # Accessing .value must NEVER raise AttributeError
        self.assertEqual(self.store.state.strategy_profile.value, "aggressive")

        # 2. Invalid enum value -> FAIL CLOSED
        undo_len_before = len(self.store.undo_stack)
        res_bad_prof = self.api.strategy_edit({"field": "strategy_profile", "value": "super_greedy"})
        self.assertEqual(res_bad_prof["status"], "error")
        self.assertIn("Invalid strategy_profile", res_bad_prof["error"])
        self.assertEqual(self.store.state.strategy_profile, StrategyProfile.AGGRESSIVE)  # Unchanged
        self.assertEqual(len(self.store.undo_stack), undo_len_before)  # No dirty undo

        # 3. Strategy round validation [1..5]
        res_r_bad0 = self.api.strategy_edit({"field": "strategy_round", "value": 0})
        self.assertEqual(res_r_bad0["status"], "error")
        res_r_bad6 = self.api.strategy_edit({"field": "strategy_round", "value": 6})
        self.assertEqual(res_r_bad6["status"], "error")
        res_r_bad_str = self.api.strategy_edit({"field": "strategy_round", "value": "not_an_int"})
        self.assertEqual(res_r_bad_str["status"], "error")

        res_r_ok = self.api.strategy_edit({"field": "strategy_round", "value": 3})
        self.assertEqual(res_r_ok["status"], "ok")
        self.assertEqual(self.store.state.strategy_round, 3)

        # 4. Strategy venue validation
        res_v_bad = self.api.strategy_edit({"field": "strategy_venue", "value": "mars_venue"})
        self.assertEqual(res_v_bad["status"], "error")
        res_v_ok = self.api.strategy_edit({"field": "strategy_venue", "value": "shanhu"})
        self.assertEqual(res_v_ok["status"], "ok")
        self.assertEqual(self.store.state.strategy_venue, "shanhu")

        # 5. Unknown field -> FAIL CLOSED
        res_unknown = self.api.strategy_edit({"field": "hack_field", "value": 999})
        self.assertEqual(res_unknown["status"], "error")
        self.assertIn("Unknown or disallowed", res_unknown["error"])

    def test_06_fast_mode_unavailable_contract(self):
        """Verify Option 2: Fast mode solver is unavailable and setting it fails closed."""
        panel_state = StrategyPanelShellState()
        self.assertFalse(panel_state.fast_mode_available)
        payload = panel_state.to_payload()
        self.assertFalse(payload["fastModeAvailable"])

        # Attempt to edit estimate_mode to fast
        res_fast = self.api.strategy_edit({"field": "estimate_mode", "value": "fast"})
        self.assertEqual(res_fast["status"], "error")
        self.assertIn("Fast mode compute-budget solver is currently unavailable", res_fast["error"])
        # Mode remains PRECISE
        self.assertEqual(self.store.state.estimate_mode, EstimateMode.PRECISE)

    def test_07_strategy_round_and_venue_do_not_impersonate_canonical_facts(self):
        """Verify strategyRound/strategyVenue are labeled with user_strategy and do not touch CurrentMatch."""
        cm = CurrentMatch()
        cm.apply_facts({"venue": "haibei", "roundNo": 1, "q": 9, "goldAvg": 30000})

        # Apply strategy edits
        self.api.strategy_edit({"field": "strategy_venue", "value": "zhenzhu"})
        self.api.strategy_edit({"field": "strategy_round", "value": 4})

        # Check strategy panel payload
        panel = StrategyPanelShellState(
            strategy_round=self.store.state.strategy_round,
            strategy_venue=self.store.state.strategy_venue,
        )
        payload = panel.to_payload()
        self.assertEqual(payload["strategyRound"], 4)
        self.assertEqual(payload["strategyVenue"], "zhenzhu")
        self.assertEqual(payload["strategySource"], "user_strategy")

        # Canonical CurrentMatch facts MUST remain haibei and roundNo=1
        self.assertEqual(cm.facts["venue"], "haibei")
        self.assertEqual(cm.facts["roundNo"], 1)

    def test_08_capacity_limit_and_redo_clearing(self):
        """Verify history capacity limit of 5 is enforced and new edit invalidates redo."""
        for i in range(10):
            self.store.edit_typed("strategy_round", (i % 5) + 1)
        self.assertEqual(len(self.store.undo_stack), 5)

        self.store.undo()
        self.assertTrue(self.store.can_redo)
        self.store.edit_typed("strategy_venue", "shanhu")
        self.assertFalse(self.store.can_redo)


class TestAuctionBrainLifecycleIntegration(unittest.TestCase):
    """Tests verifying Fix E: Lifecycle-aware match reset in AuctionBrain."""

    def setUp(self):
        self.store = UserStrategyEditHistory(capacity=5)
        set_authoritative_strategy_store(self.store)
        self.archiver = AutoArchiver(db_paths=[])
        self.brain = AuctionBrain(archiver=self.archiver, strategy_store=self.store)

    def test_09_auction_brain_precise_parity(self):
        """Verify solve_session baseline calculation parity in PRECISE mode."""
        session_ctx = {
            "q": 9,
            "goldAvg": 33538,
            "costs": {"sunkCost": 5000, "futureIncrementalCost": 0},
            "targetProfit": 30000,
            "leaderBid": 120000,
        }
        res = self.brain.solve_session(session_ctx)
        expected_center = 9 * 33538
        expected_p20 = int(expected_center * 0.9)
        expected_p80 = int(expected_center * 1.1)

        self.assertEqual(res["valP50"], expected_center)
        self.assertEqual(res["valRange"], (expected_p20, expected_p80))
        metrics = res["strategyMetrics"]
        # Mean is None because analytical bounds have no true distribution expectation
        self.assertIsNone(metrics["meanEstimate"])
        self.assertEqual(metrics["meanSource"], "unavailable")
        self.assertEqual(metrics["medianEstimate"], float(expected_center))
        self.assertEqual(metrics["medianSource"], "p50_point")
        self.assertEqual(metrics["conservativeEstimate"], float(expected_p20))
        self.assertEqual(metrics["conservativeSource"], "p20_point")

    def test_10_new_match_resets_history_and_repeated_settlement_does_not_reset(self):
        """Verify Fix E: Reset occurs when a new match lifecycle begins, NOT on each settlement frame."""
        # 1. Round 1 observation begins Match 1
        obs_r1 = VisionObservation(
            round=1,
            timer=20,
            venue="shanhu",
            boxType="standard",
            intel=VisionIntel(type="goldAvg", q=9, goldAvg=33538),
            bids=VisionBids(myBid=100000, leaderBid=120000, leaderName="对手1"),
        )
        self.brain.process_observation(obs_r1)
        session_id_1 = self.brain._active_session_id
        self.assertIsNotNone(session_id_1)

        # 2. User makes strategy edits during Match 1
        self.store.edit_typed("strategy_profile", "conservative")
        self.store.edit_typed("strategy_venue", "shanhu")
        self.assertTrue(self.store.can_undo)
        self.assertEqual(self.store.state.strategy_profile, StrategyProfile.CONSERVATIVE)

        # 3. Settlement Frame 1 arrives
        obs_settle_1 = VisionObservation(
            round=5,
            timer=0,
            settlement=VisionSettlement(
                isSettlement=True,
                clearingPrice=450000,
                actualTotal=900000,
                profit=450000,
            ),
        )
        self.brain.process_observation(obs_settle_1)

        # Strategy state MUST NOT be wiped out by settlement frame 1!
        self.assertTrue(self.store.can_undo)
        self.assertEqual(self.store.state.strategy_profile, StrategyProfile.CONSERVATIVE)

        # 4. Settlement Frame 2 arrives (same match settlement streaming)
        obs_settle_2 = VisionObservation(
            round=5,
            timer=0,
            settlement=VisionSettlement(
                isSettlement=True,
                clearingPrice=450000,
                actualTotal=900000,
                profit=450000,
                items=["item1", "item2"],
            ),
        )
        self.brain.process_observation(obs_settle_2)

        # Still MUST NOT be wiped out!
        self.assertTrue(self.store.can_undo)
        self.assertEqual(self.store.state.strategy_profile, StrategyProfile.CONSERVATIVE)

        # 5. Now, a brand new match starts (reset FSM to preparing then start new session)
        self.brain.fsm.trigger_match_start(venue="haibei")
        obs_new_match = VisionObservation(
            round=1,
            timer=20,
            venue="haibei",
            boxType="standard",
            intel=VisionIntel(type="goldAvg", q=9, goldAvg=33538),
            bids=VisionBids(myBid=100000, leaderBid=120000, leaderName="对手2"),
        )
        self.brain.process_observation(obs_new_match)

        # History MUST be reset for the new match lifecycle!
        self.assertFalse(self.store.can_undo)
        self.assertFalse(self.store.can_redo)
        self.assertEqual(self.store.state.strategy_profile, StrategyProfile.DEFAULT)

    def test_11_boundary3_files_unchanged(self):
        """Verify PR #1 (feature/b3-input-safety) files remain 100% untouched."""
        cmd = ["git", "diff", "--name-only", "fbd30a204c9c023034c725b7bcded158655bc53c"]
        res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
        changed_files = [line.strip().replace("\\", "/") for line in res.stdout.splitlines() if line.strip()]
        b3_forbidden_prefixes = [
            "app/warehouse_capture_host.py",
            "core/warehouse_capture_production.py",
            "core/warehouse_capture_session.py",
            "core/warehouse_input_abort_guard.py",
            "core/warehouse_wheel_driver.py",
            "tests/negative_matrix_evidence.json",
            "tests/test_boundary3",
            "tests/test_warehouse_input_abort_guard",
            "tests/toctou_timeline_evidence.json",
        ]
        for f in changed_files:
            for forbidden in b3_forbidden_prefixes:
                self.assertFalse(
                    f.startswith(forbidden),
                    f"Forbidden Boundary 3 file modified in PR-A branch: {f}"
                )


if __name__ == "__main__":
    unittest.main()
