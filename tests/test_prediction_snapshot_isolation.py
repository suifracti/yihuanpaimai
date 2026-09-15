"""Predictions cannot cross match identity or retain mutable caller aliases."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from prediction_snapshot_holder import ActivePredictionSnapshotHolder
from live_shadow import _profile_cache_key, _solver_ctx


class PredictionIsolationTests(unittest.TestCase):
    def test_solver_request_keeps_match_identity_for_result_binding(self):
        self.assertEqual(_solver_ctx({"id": "current"})["matchId"], "current")
    def test_new_match_frozen_only_cannot_inherit_previous_snapshot(self):
        holder = ActivePredictionSnapshotHolder()
        holder.update("first", {"matchId": "first", "forecast": {"value": 10}})
        holder.update("second", frozen_prediction={"value": 20})
        self.assertIsNone(holder.get_snapshot_for_match("second"))
        self.assertIsNone(holder.get_snapshot_for_match("first"))
        self.assertEqual(holder.get_frozen_for_match("second"), {"value": 20})

    def test_rejected_snapshot_preserves_existing_and_input_is_copied(self):
        holder = ActivePredictionSnapshotHolder()
        snapshot = {"matchId": "first", "forecast": {"value": 10}}
        holder.update("first", snapshot)
        snapshot["forecast"]["value"] = 999
        self.assertEqual(holder.get_snapshot_for_match("first")["forecast"]["value"], 10)
        self.assertFalse(holder.update("second", {"matchId": "wrong"}))
        self.assertEqual(holder.match_id, "first")

    def test_same_observations_in_two_matches_have_different_cache_keys(self):
        context = {"q": 12, "goldAvg": 30000, "matchGeneration": 1}
        self.assertNotEqual(_profile_cache_key(dict(context, matchId="first"), 0),
                            _profile_cache_key(dict(context, matchId="second"), 0))
