# -*- coding: utf-8 -*-
"""Completed Shadow events must update the nested Overlay Solver input."""
import os
import sys
import unittest
from unittest import mock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

import main as app_main


class TestLiveShadowPresentationPayloadV1(unittest.TestCase):
    def test_completed_event_replaces_nested_pending_solver_input(self):
        current = app_main.CURRENT_MATCH
        original_payload = dict(app_main.LATEST_PAYLOAD)
        original_keys = dict(getattr(app_main, "_SHADOW_PRESENTATION_KEYS", {}))
        try:
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            match_id = current.id
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update({
                "type": "manual_alpha_state",
                "scene": "IN_AUCTION",
                "matchId": match_id,
                "shadowUpdating": True,
                "solverInput": {
                    "matchId": match_id,
                    "q": 12,
                    "goldAvg": 74379,
                    "probabilityProfile": None,
                    "shadowUpdating": True,
                },
                "shadowSupport": {
                    "status": "SUPPORT_UPDATING",
                    "reasonCodes": ["HISTORICAL_PROFILE_PENDING"],
                    "historyN": 290,
                    "coverageRatio": 0.0,
                },
            })
            profile = {
                "coverageRatio": 1,
                "shadowWhole": {"p20": 100, "p50": 200, "p80": 300},
            }
            snapshot = {"matchId": match_id, "predictionId": "presentation-test"}
            app_main._publish_live_shadow_event({
                "matchId": match_id,
                "shadowGen": 2,
                "probabilityProfile": profile,
                "predictionSnapshot": snapshot,
                "frozenPrediction": {"recommendedMax": 180},
                "shadowMeta": {"cache": "miss", "historyN": 290, "shadowUpdating": False},
                "shadowStates": {"exact": [], "expanded": []},
            })
            payload = app_main.LATEST_PAYLOAD
            self.assertFalse(payload["shadowUpdating"])
            self.assertEqual(payload["solverInput"]["probabilityProfile"], profile)
            self.assertEqual(payload["solverInput"]["predictionSnapshot"], snapshot)
            self.assertFalse(payload["solverInput"]["shadowUpdating"])
            self.assertEqual(payload["shadowSupport"]["status"], "HISTORICAL_SUPPORTED")
            self.assertEqual(payload["shadowSupport"]["coverageRatio"], 1)
            self.assertNotIn("HISTORICAL_PROFILE_PENDING", payload["shadowSupport"]["reasonCodes"])
        finally:
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update(original_payload)
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main._SHADOW_PRESENTATION_KEYS.update(original_keys)


if __name__ == "__main__":
    unittest.main()
