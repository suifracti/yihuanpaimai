# -*- coding: utf-8 -*-
"""Completed Shadow events must update the nested Overlay Solver input."""
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

import main as app_main
import live_shadow


class TestLiveShadowPresentationPayloadV1(unittest.TestCase):
    def test_qualified_node_prediction_reaches_native_owner(self):
        history_path = Path(PROJECT_ROOT) / "异环拍卖数据.json"
        if not history_path.is_file() or not shutil.which("node"):
            self.skipTest("read-only solver history or Node unavailable")
        facts = {
            "venueId": "venue-shanhu", "boxId": "box-shanhu-glass",
            "box": "琉璃宝箱 · 宝石类概率提升",
            "fieldCondition": "standard", "q": 12, "goldAvg": 74379,
            "entryCost": 5000,
        }
        self.assertEqual(app_main._native_solver_admission({**facts, "goldAvg": None})[1], "缺失金色均价")
        self.assertEqual(app_main._native_solver_admission({**facts, "entryCost": None})[1], "缺失入场费")
        mapped, reason = app_main._native_solver_admission(facts)
        self.assertIsNone(reason)
        match_id = "p2-qualified-node-owner"
        context = {
            "scene": "IN_AUCTION", "round": 3, "matchId": match_id,
            "factsRevision": 26, "matchGeneration": 1,
            "observationSessionId": "qualified-session",
            "target": {"targetHwnd": 123, "targetPid": 456},
            "q": 12, "goldAvg": 74379, "purple": 7,
            "entryCost": 5000,
            "costs": {"entry": 5000, "intel": 0, "other": 0, "sunkCost": 5000,
                      "futureIncrementalCost": 0, "total": 5000},
            "fieldCondition": "standard", "playedAt": "2026-08-17T14:15:59.030277",
            "venue": mapped["venue"], "box": mapped["box"],
        }
        original_payload = dict(app_main.LATEST_PAYLOAD)
        original_keys = dict(app_main._SHADOW_PRESENTATION_KEYS)
        try:
            live_shadow.reset_live_shadow_state()
            with mock.patch.dict(os.environ, {
                "YIHUAN_UPPER_TAIL_CAPTURE_DIR": str(Path(PROJECT_ROOT) / "build" / "p2-targeted-data" / "support-captures")
            }):
                profile, meta = live_shadow.compute_live_probability_profile(
                    context, db_path=str(history_path), persist_runtime=True
                )
            snapshot = meta.get("predictionSnapshot")
            self.assertEqual(meta.get("computeHost"), "node")
            self.assertIsNotNone(profile)
            self.assertEqual((snapshot or {}).get("status", {}).get("solverStatus"), "valid")
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update({
                "scene": "IN_AUCTION", "matchId": match_id,
                "observationProfile": "native-readonly-v1",
                "observationSessionId": "qualified-session",
                "target": context["target"], "round": 3, "factsRevision": 26,
                "matchGeneration": 1, "predictionSnapshot": None,
                "solverStatus": "pending",
            })
            with mock.patch.object(app_main, "CURRENT_MATCH", mock.Mock(id=match_id)), \
                 mock.patch.object(app_main, "get_current_match_presentation_summary", return_value={"id": match_id}), \
                 mock.patch.object(app_main, "ACTIVE_SNAPSHOT_HOLDER"):
                app_main._publish_live_shadow_event({
                    "matchId": match_id, "presentationSource": "live_vision",
                    "observationSessionId": "qualified-session",
                    "target": context["target"], "round": 3, "factsRevision": 26,
                    "matchGeneration": 1, "probabilityProfile": profile,
                    "predictionSnapshot": snapshot,
                    "frozenPrediction": meta.get("frozenPrediction"),
                })
                self.assertEqual(app_main.LATEST_PAYLOAD["solverStatus"], "valid")
                self.assertEqual(app_main.LATEST_PAYLOAD["predictionSnapshot"], snapshot)
        finally:
            live_shadow.reset_live_shadow_state()
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update(original_payload)
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main._SHADOW_PRESENTATION_KEYS.update(original_keys)

    def test_native_result_requires_current_round_revision_and_target(self):
        original_payload = dict(app_main.LATEST_PAYLOAD)
        original_keys = dict(app_main._SHADOW_PRESENTATION_KEYS)
        match_id = "p2-native-result-owner"
        payload = {
            "scene": "IN_AUCTION", "matchId": match_id,
            "observationProfile": "native-readonly-v1",
            "observationSessionId": "session-current",
            "target": {"targetHwnd": 123, "targetPid": 456},
            "round": 5, "factsRevision": 26, "matchGeneration": 1,
            "predictionSnapshot": None, "solverStatus": "pending",
        }
        event = {
            "matchId": match_id, "presentationSource": "live_vision",
            "observationSessionId": "session-current",
            "target": {"targetHwnd": 123, "targetPid": 456},
            "round": 5, "factsRevision": 26, "matchGeneration": 1,
            "predictionSnapshot": {
                "matchId": match_id, "predictionId": "current-p2",
                "status": {"solverStatus": "valid"},
            },
            "probabilityProfile": {"coverageRatio": 0.5},
        }
        try:
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update(payload)
            with mock.patch.object(app_main, "CURRENT_MATCH", mock.Mock(id=match_id)), \
                 mock.patch.object(app_main, "get_current_match_presentation_summary", return_value={"id": match_id}), \
                 mock.patch.object(app_main, "ACTIVE_SNAPSHOT_HOLDER"):
                for mismatch in (
                    {"factsRevision": 25}, {"round": 4},
                    {"target": {"targetHwnd": 123, "targetPid": 999}},
                ):
                    app_main._publish_live_shadow_event({**event, **mismatch})
                    self.assertIsNone(app_main.LATEST_PAYLOAD["predictionSnapshot"])
                    self.assertEqual(app_main.LATEST_PAYLOAD["solverStatus"], "pending")
                app_main._publish_live_shadow_event(event)
                self.assertEqual(app_main.LATEST_PAYLOAD["predictionSnapshot"]["predictionId"], "current-p2")
                self.assertEqual(app_main.LATEST_PAYLOAD["solverStatus"], "valid")
        finally:
            app_main.LATEST_PAYLOAD.clear()
            app_main.LATEST_PAYLOAD.update(original_payload)
            app_main._SHADOW_PRESENTATION_KEYS.clear()
            app_main._SHADOW_PRESENTATION_KEYS.update(original_keys)

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
