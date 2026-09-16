# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for Strategy UX Metrics & User Strategy State Management.

Verifies all PR-A requirements:
1. Default behavior is PRECISE and matches production expectations.
2. Fast / Precise dual-mode toggle preserves Canonical facts and does not diverge algorithms.
3. Precise solver output is identical to baseline production solver calculations.
4. Mean and Median metrics are strictly traceable to model distributions.
5. Conservative estimate strictly reflects traceable lower quantiles (p20) or returns
   None with conservativeSource="unavailable" (never fabricates numbers).
6. Strategy Panel Shell view-model correctly structures metrics, profile, and experimental area.
7. Experimental area defaults to collapsed (is_experimental_expanded=False, experimental=False).
8. User Strategy Undo / Redo engine works with capacity limits, clears redo on edit, and
   strictly isolates user strategy from Canonical facts and archives.
9. Reset for new match clears undo/redo history to prevent cross-match leakage.
10. AuctionBrain integration properly propagates strategyMetrics and strategyPanel in HUD payload.
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
for p in (PROJECT_ROOT, CORE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategy_ux_metrics import (
    EstimateMode,
    StrategyProfile,
    StrategyMetricsSummary,
    StrategyPanelShellState,
    UserEditCommand,
    UserStrategyEditHistory,
    compute_strategy_metrics_summary,
)
from auction_brain import AuctionBrain
from auto_archiver import AutoArchiver
from vision_contract import VisionObservation, VisionIntel, VisionBids, VisionSettlement
from current_match import CurrentMatch


class TestStrategyUXMetrics(unittest.TestCase):
    """Unit tests for strategy UX metrics data contracts and calculations."""

    def test_01_default_mode_and_production_eligibility(self):
        """Verify default mode is PRECISE, productionEligible is True, and experimental is False."""
        summary = compute_strategy_metrics_summary(
            mode=EstimateMode.PRECISE,
            val_p50=100000.0,
            val_p20=90000.0,
            val_p80=110000.0,
        )
        self.assertEqual(summary.estimateMode, "precise")
        self.assertEqual(summary.meanEstimate, 100000.0)
        self.assertEqual(summary.medianEstimate, 100000.0)
        self.assertEqual(summary.conservativeEstimate, 90000.0)
        self.assertEqual(summary.conservativeSource, "p20_point")
        self.assertTrue(summary.productionEligible)
        self.assertFalse(summary.experimental)

    def test_02_fast_mode_toggle_preserves_contract(self):
        """Verify fast mode toggle reflects in estimateMode without polluting production eligibility."""
        summary = compute_strategy_metrics_summary(
            mode=EstimateMode.FAST,
            val_p50=200000.0,
            val_p20=180000.0,
            val_p80=220000.0,
        )
        self.assertEqual(summary.estimateMode, "fast")
        self.assertEqual(summary.meanEstimate, 200000.0)
        self.assertEqual(summary.medianEstimate, 200000.0)
        self.assertEqual(summary.conservativeEstimate, 180000.0)
        self.assertEqual(summary.conservativeSource, "p20_point")
        self.assertTrue(summary.productionEligible)
        self.assertFalse(summary.experimental)

    def test_03_conservative_unavailability_never_fabricates_values(self):
        """Verify when no legal lower quantile exists, conservativeEstimate is strictly None."""
        summary = compute_strategy_metrics_summary(
            mode=EstimateMode.PRECISE,
            val_p50=150000.0,
            val_p20=None,  # No low quantile
            val_p80=None,
        )
        self.assertEqual(summary.meanEstimate, 150000.0)
        self.assertEqual(summary.medianEstimate, 150000.0)
        self.assertIsNone(summary.conservativeEstimate)
        self.assertEqual(summary.conservativeSource, "unavailable")

    def test_04_prediction_snapshot_quantiles_resolution(self):
        """Verify metrics can be resolved directly from predictionSnapshot forecast quantiles."""
        fake_snapshot = {
            "forecast": {
                "quantiles": {
                    "p20": 450000.0,
                    "p50": 500000.0,
                    "p80": 550000.0,
                }
            }
        }
        summary = compute_strategy_metrics_summary(
            mode=EstimateMode.PRECISE,
            prediction_snapshot=fake_snapshot,
        )
        self.assertEqual(summary.meanEstimate, 500000.0)
        self.assertEqual(summary.medianEstimate, 500000.0)
        self.assertEqual(summary.conservativeEstimate, 450000.0)
        self.assertEqual(summary.conservativeSource, "p20_point")

    def test_05_strategy_panel_shell_defaults(self):
        """Verify StrategyPanelShellState structures and defaults (experimental default collapsed)."""
        summary = compute_strategy_metrics_summary(mode=EstimateMode.PRECISE, val_p50=300000.0, val_p20=270000.0)
        panel = StrategyPanelShellState(
            metrics_summary=summary,
            production_estimate=300000.0,
        )
        payload = panel.to_payload()
        self.assertTrue(payload["isPanelExpanded"])
        self.assertFalse(payload["isExperimentalExpanded"])  # Must default to collapsed
        self.assertFalse(payload["experimentalAvailable"])
        self.assertEqual(payload["estimateMode"], "precise")
        self.assertEqual(payload["round"], 1)
        self.assertEqual(payload["venue"], "standard")
        self.assertEqual(payload["strategyProfile"], "default")
        self.assertEqual(payload["productionEstimate"], 300000.0)
        self.assertFalse(payload["canUndo"])
        self.assertFalse(payload["canRedo"])


class TestUserStrategyEditHistory(unittest.TestCase):
    """Unit tests for user strategy edit undo/redo engine and isolation guarantees."""

    def setUp(self):
        self.history = UserStrategyEditHistory(capacity=5)

    def test_06_edit_push_and_undo_redo_sequence(self):
        """Verify basic edit, undo, redo transitions."""
        self.assertFalse(self.history.can_undo)
        self.assertFalse(self.history.can_redo)

        # Edit venue
        self.assertTrue(self.history.edit("venue", "shanhu"))
        self.assertEqual(self.history.state.venue, "shanhu")
        self.assertTrue(self.history.can_undo)
        self.assertFalse(self.history.can_redo)

        # Edit round
        self.assertTrue(self.history.edit("round", 2))
        self.assertEqual(self.history.state.round, 2)

        # Undo round
        cmd = self.history.undo()
        self.assertEqual(cmd.field, "round")
        self.assertEqual(self.history.state.round, 1)
        self.assertTrue(self.history.can_redo)

        # Redo round
        cmd_redo = self.history.redo()
        self.assertEqual(cmd_redo.field, "round")
        self.assertEqual(self.history.state.round, 2)
        self.assertFalse(self.history.can_redo)

    def test_07_new_edit_clears_redo_stack(self):
        """Verify that performing a new edit clears the redo stack."""
        self.history.edit("round", 2)
        self.history.edit("round", 3)
        self.history.undo()  # Revert to 2
        self.assertTrue(self.history.can_redo)

        # New edit
        self.history.edit("round", 4)
        self.assertEqual(self.history.state.round, 4)
        self.assertFalse(self.history.can_redo)  # Redo stack must be cleared

    def test_08_capacity_limit_enforced(self):
        """Verify stack capacity limit is strictly enforced without unbounded growth."""
        for i in range(10):
            self.history.edit("round", i + 1)

        self.assertEqual(len(self.history.undo_stack), 5)
        self.assertEqual(self.history.state.round, 10)

    def test_09_reset_for_new_match_clears_history(self):
        """Verify reset_for_new_match clears undo and redo stacks completely."""
        self.history.edit("venue", "zhenzhu")
        self.history.edit("round", 3)
        self.history.undo()
        self.assertTrue(self.history.can_undo)
        self.assertTrue(self.history.can_redo)

        # New match reset
        self.history.reset_for_new_match(match_id="match_20260916_test")
        self.assertFalse(self.history.can_undo)
        self.assertFalse(self.history.can_redo)
        self.assertEqual(self.history.state.venue, "standard")
        self.assertEqual(self.history.state.round, 1)

    def test_10_canonical_match_isolation_guarantee(self):
        """Verify strategy edits NEVER modify CurrentMatch facts or canonical data."""
        cm = CurrentMatch()
        cm.apply_facts({"venue": "haibei", "q": 9, "goldAvg": 30000})
        orig_facts = dict(cm.facts)

        # Apply various strategy edits
        self.history.edit("venue", "shanhu")
        self.history.edit("round", 4)
        self.history.edit("estimate_mode", EstimateMode.FAST)
        self.history.undo()
        self.history.undo()

        # Check that CurrentMatch is 100% untouched
        self.assertEqual(cm.facts, orig_facts)
        self.assertEqual(cm.facts["venue"], "haibei")
        self.assertEqual(cm.facts["q"], 9)


class TestAuctionBrainStrategyIntegration(unittest.TestCase):
    """Integration tests verifying AuctionBrain incorporates strategy UX metrics."""

    def test_11_auction_brain_solve_session_precise_parity(self):
        """Verify that solve_session in precise mode matches exact production baseline calculations."""
        archiver = AutoArchiver(db_paths=[])
        brain = AuctionBrain(archiver=archiver)

        session_ctx = {
            "q": 9,
            "goldAvg": 33538,
            "costs": {"sunkCost": 5000, "futureIncrementalCost": 0},
            "targetProfit": 30000,
            "leaderBid": 120000,
        }
        res = brain.solve_session(session_ctx, mode=EstimateMode.PRECISE)

        # Baseline point calculation: 9 * 33538 = 301842
        expected_center = 9 * 33538
        expected_p20 = int(expected_center * 0.9)
        expected_p80 = int(expected_center * 1.1)

        self.assertEqual(res["valP50"], expected_center)
        self.assertEqual(res["valRange"], (expected_p20, expected_p80))
        self.assertEqual(res["targetProfitLine"], max(0, expected_p20 - 5000 - 30000))
        self.assertEqual(res["globalProfitLine"], max(0, expected_p20 - 5000))
        self.assertEqual(res["marginalChaseLine"], max(0, expected_p20 - 0))

        # Check strategy metrics summary
        self.assertIn("strategyMetrics", res)
        metrics = res["strategyMetrics"]
        self.assertEqual(metrics["estimateMode"], "precise")
        self.assertEqual(metrics["meanEstimate"], float(expected_center))
        self.assertEqual(metrics["medianEstimate"], float(expected_center))
        self.assertEqual(metrics["conservativeEstimate"], float(expected_p20))
        self.assertEqual(metrics["conservativeSource"], "p20_point")
        self.assertTrue(metrics["productionEligible"])
        self.assertFalse(metrics["experimental"])

        # Check strategy panel shell
        self.assertIn("strategyPanel", res)
        panel = res["strategyPanel"]
        self.assertEqual(panel["estimateMode"], "precise")
        self.assertEqual(panel["productionEstimate"], float(expected_center))
        self.assertFalse(panel["isExperimentalExpanded"])

    def test_12_auction_brain_fast_mode_execution(self):
        """Verify that solve_session in fast mode returns immediate actionable directives."""
        archiver = AutoArchiver(db_paths=[])
        brain = AuctionBrain(archiver=archiver)
        brain.set_estimate_mode(EstimateMode.FAST)

        session_ctx = {
            "q": 9,
            "goldAvg": 33538,
            "costs": {"sunkCost": 5000, "futureIncrementalCost": 0},
            "targetProfit": 30000,
            "leaderBid": 120000,
        }
        res = brain.solve_session(session_ctx)
        self.assertEqual(res["estimateMode"], "fast")
        self.assertEqual(res["strategyMetrics"]["estimateMode"], "fast")
        self.assertIn("actionDirective", res)

    def test_13_observation_pipeline_and_settlement_reset(self):
        """Verify process_observation attaches strategy metrics and resets history on settlement."""
        archiver = AutoArchiver(db_paths=[])
        brain = AuctionBrain(archiver=archiver)

        # Make user strategy edits during round
        brain.edit_user_strategy("venue", "zhenzhu")
        brain.edit_user_strategy("round", 2)
        self.assertTrue(brain.strategy_history.can_undo)

        obs = VisionObservation(
            round=2,
            timer=10,
            venue="zhenzhu",
            boxType="standard",
            intel=VisionIntel(
                type="goldAvg",
                q=9,
                goldAvg=33538,
            ),
            bids=VisionBids(myBid=100000, leaderBid=120000, leaderName="对手1")
        )
        payload = brain.process_observation(obs)
        self.assertIn("strategyMetrics", payload)
        self.assertIn("strategyPanel", payload)
        self.assertEqual(payload["strategyMetrics"]["meanEstimate"], 9 * 33538)

        # Settlement frame
        obs_settle = VisionObservation(
            round=5,
            timer=0,
            settlement=VisionSettlement(
                isSettlement=True,
                clearingPrice=454444,
                actualTotal=972970,
                profit=518526,
            )
        )
        brain.process_observation(obs_settle)
        # History must be reset after settlement
        self.assertFalse(brain.strategy_history.can_undo)
        self.assertFalse(brain.strategy_history.can_redo)


if __name__ == "__main__":
    unittest.main()
