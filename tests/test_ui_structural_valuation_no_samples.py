import unittest
from unittest.mock import patch
from test_prediction_snapshot_persistence_v1 import run_js_solver
import main
from current_match import CurrentMatch
from prediction_snapshot_holder import ActivePredictionSnapshotHolder


class TestUIStructuralValuationNoSamples(unittest.TestCase):
    def test_structural_solver_and_presentation_parity(self):
        # Frozen real match input from 2026-09-13 21:18~21:24
        # venue: "中级场 · 珊瑚场", box: "机械宝箱 · 科技类概率提升", q: 23, goldAvg: 59514, purpleCount: 14,
        # knownGold: "万花筒", knownRed: "「泪滴」"
        payload = {
            "matchId": "real-trial-fixture-20260913-2123",
            "venue": "中级场 · 珊瑚场",
            "box": "机械宝箱 · 科技类概率提升",
            "fieldCondition": "purpleDouble",
            "costs": {"sunkCost": 5000, "total": 5000},
            "q": 23,
            "goldAvg": 59514,
            "purpleCount": 14,
            "knownGold": "万花筒",
            "knownRed": "「泪滴」",
            "catalogVersion": "2026-08-13",
            "targetProfit": 30000,
            "roundingMode": "floor",
        }
        solved = run_js_solver(payload)
        self.assertIsNotNone(solved)
        
        # 1. Quantiles must be strictly null (0 comparable samples)
        snapshot = solved.get("predictionSnapshot") or {}
        forecast = snapshot.get("forecast") or {}
        quantiles = forecast.get("quantiles")
        self.assertIsNone(quantiles)
        
        # 2. Structural fields must be present and deterministic
        structural = forecast.get("structural") or {}
        center = structural.get("center")
        bounds_min = structural.get("candidateBoundsMin")
        bounds_max = structural.get("candidateBoundsMax")
        ref_bid = structural.get("recommendedMax")
        
        self.assertIsNotNone(center)
        self.assertAlmostEqual(center, 722297, delta=100)
        self.assertIsNotNone(bounds_min)
        self.assertAlmostEqual(bounds_min, 669635, delta=100)
        self.assertIsNotNone(bounds_max)
        self.assertAlmostEqual(bounds_max, 762299, delta=100)
        self.assertIsNotNone(ref_bid)
        self.assertAlmostEqual(ref_bid, 717297, delta=100)

        # 3. Python presentation summary maps these correctly
        current = CurrentMatch()
        current.id = payload["matchId"]
        current.apply_facts(payload)
        holder = ActivePredictionSnapshotHolder()
        holder.update(
            match_id=current.id,
            snapshot=snapshot,
            frozen_prediction=solved.get("frozenPrediction")
        )
        with patch.object(main, "CURRENT_MATCH", current), patch.object(main, "ACTIVE_SNAPSHOT_HOLDER", holder):
            pres = main.get_current_match_presentation_summary()
            summary = pres["prediction"]
            lines = pres["decisionLines"]

        self.assertIsNone(summary.get("p20"))
        self.assertIsNone(summary.get("p50"))
        self.assertIsNone(summary.get("p80"))
        self.assertIn("非概率结构估值中枢", summary.get("estimateLabel"))
        self.assertEqual(summary.get("structuralCenter"), center)
        self.assertEqual(summary.get("structuralFeasibleMin"), bounds_min)
        self.assertEqual(summary.get("structuralFeasibleMax"), bounds_max)
        self.assertEqual(summary.get("structuralReferenceBid"), ref_bid)
        self.assertEqual(lines.get("structuralCenter"), center)
        self.assertEqual(lines.get("structuralFeasibleMin"), bounds_min)
        self.assertEqual(lines.get("structuralFeasibleMax"), bounds_max)
        self.assertEqual(lines.get("structuralReferenceBid"), ref_bid)


if __name__ == "__main__":
    unittest.main()
