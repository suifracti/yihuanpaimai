"""Empty or incomplete estimates must not manufacture bidding authority."""
import unittest
from unittest.mock import patch

import main
from current_match import CurrentMatch
from prediction_snapshot_holder import ActivePredictionSnapshotHolder


class PredictionAdvicePresentationTests(unittest.TestCase):
    def summary(self, prediction, frozen=None):
        current = CurrentMatch()
        current.id = prediction.get("matchId") or current.id
        current.apply_facts({"venue": "珊瑚场", "box": "实木宝箱"})
        holder = ActivePredictionSnapshotHolder()
        holder.update(match_id=current.id, snapshot={"matchId": current.id, **prediction}, frozen_prediction=frozen)
        with patch.object(main, "CURRENT_MATCH", current), patch.object(main, "ACTIVE_SNAPSHOT_HOLDER", holder):
            return main.get_current_match_presentation_summary()["prediction"]

    def test_empty_prediction_waits_without_recommendation(self):
        result = self.summary({})
        self.assertEqual(result["actionDirective"], "WAIT")
        self.assertIn("等待情报", result["actionReason"])
        self.assertIsNone(result["recommendedMax"])
        self.assertIsNone(result["entryGrade"])

    def test_value_is_not_an_authorized_bid_limit(self):
        result = self.summary({"formalValue": {"ev": 50000}})
        self.assertIsNone(result["recommendedMax"])
        self.assertEqual(result["actionDirective"], "WAIT")

    def test_invalid_limit_cannot_enable_bid(self):
        for limit in (None, float("nan"), float("inf"), True, -1, "100"):
            with self.subTest(limit=limit):
                result = self.summary({"actionDirective": "BID", "actionReason": "可出价",
                                       "forecast": {"quantiles": {"recommendedMax": limit}}})
                self.assertEqual(result["actionDirective"], "WAIT")
                self.assertNotEqual(result["actionReason"], "可出价")

    def test_explicit_decision_and_zero_limit_are_preserved(self):
        result = self.summary({"mode": "structural_only"}, {"decision": {
            "actionDirective": "PASS", "actionReason": "约束冲突", "recommendedMax": 0}})
        self.assertEqual(result["actionDirective"], "PASS")
        self.assertEqual(result["actionReason"], "约束冲突")
        self.assertEqual(result["recommendedMax"], 0)

    def test_explicit_valid_bid_is_preserved(self):
        result = self.summary({"decision": {"actionDirective": "BID", "actionReason": "求解器建议",
                                            "recommendedMax": 40000}})
        self.assertEqual(result["actionDirective"], "BID")
        self.assertEqual(result["actionReason"], "求解器建议")

    def test_real_structural_solver_output_is_not_presented_as_quantiles(self):
        from test_prediction_snapshot_persistence_v1 import run_js_solver
        solved = run_js_solver({"matchId": "structural-ui", "q": 9, "goldAvg": 33538,
                                "purpleCount": 5, "venue": "shanhu", "box": "实木宝箱"})
        frozen = solved["frozenPrediction"]
        self.assertEqual(frozen["decision"], solved["decision"])
        summary = self.summary(solved["predictionSnapshot"], frozen)
        self.assertIsNone(summary["p20"])
        self.assertIsNone(summary["p50"])
        self.assertIsNone(summary["p80"])
        self.assertEqual(summary["referenceValue"], frozen["formalValue"]["ev"])
        self.assertIn("非 P50", summary["estimateLabel"])
        self.assertEqual(summary["actionReason"], solved["decision"]["actionReason"])

    def test_formal_forecast_quantiles_remain_authoritative(self):
        summary = self.summary({"mode": {"informationMode": "full_shadow"},
                                "forecast": {"quantiles": {"p20": 100, "p50": 200, "p80": 300}}},
                               {"formalValue": {"p20": 1, "p50": 2, "p80": 3}})
        self.assertEqual([summary[key] for key in ("p20", "p50", "p80")], [100, 200, 300])
