"""Tests for Shared Match Control Surface v1.

Verifies:
1. Main Window native commands (manual_facts, manual_next_match, manual_finalize, manual_bootstrap)
2. Bi-directional facts synchronization via CurrentMatch SSOT
3. Lifecycle parity (Next match / Draft / Settle) between Main and Overlay
4. Presentation boundaries: Main never executes Solver directly or has raw mutable authority
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(PROJECT_ROOT, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from main_window import MainWindowBridge, OverlayVisibilityController


class _FakeOverlay:
    def __init__(self):
        self.Visible = False
        self.WebView = object()

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


class SharedMatchControlV1Tests(unittest.TestCase):
    def setUp(self):
        self.overlay = _FakeOverlay()
        self.overlay_controller = OverlayVisibilityController(self.overlay)
        self.mock_facts_provider = MagicMock()
        self.mock_next_match_provider = MagicMock(return_value={"ok": True, "matchId": "m_next"})
        self.mock_finalize_provider = MagicMock(return_value={"ok": True, "matchId": "m_final"})
        self.mock_bootstrap_provider = MagicMock(return_value={"ok": True, "type": "manual_alpha_state"})

        self.current_match_data = {
            "matchId": "m_test_001",
            "lifecycleStatus": "DRAFT",
            "hasAnyFact": True,
            "isComplete": True,
            "environment": {
                "venueId": "gold_hall",
                "venueName": "黄金场",
                "boxId": "gold_box_3",
                "box": "黄金高级宝箱",
                "fieldCondition": "standard",
                "fieldConditionName": "标准对局",
            },
            "facts": {
                "venueId": "gold_hall",
                "venue": "黄金场",
                "boxId": "gold_box_3",
                "box": "黄金高级宝箱",
                "fieldCondition": "standard",
                "q": 5,
                "goldAvg": 58000,
                "purpleCount": 2,
                "leaderBid": 45000,
                "targetProfit": 30000,
                "knownGold": "幻象之钟",
                "knownRed": "古旧手提箱",
                "knownPurple": "",
            },
            "options": {
                "venues": [{"venueId": "gold_hall", "displayName": "黄金场", "boxes": []}],
                "fieldConditions": [{"id": "standard", "name": "标准对局"}],
            },
            "prediction": {
                "hasSnapshot": True,
                "p20": 42000,
                "p50": 58000,
                "p80": 72000,
                "recommendedMax": 65000,
                "actionDirective": "BID",
                "actionReason": "当前最高叫价低于推荐上限",
            },
            "settlement": None,
        }

        self.bridge = MainWindowBridge(
            self.overlay_controller,
            current_match_provider=lambda: self.current_match_data,
            manual_facts_provider=self.mock_facts_provider,
            manual_next_match_provider=self.mock_next_match_provider,
            manual_finalize_provider=self.mock_finalize_provider,
            manual_bootstrap_provider=self.mock_bootstrap_provider,
        )

    def test_main_dispatches_manual_facts_and_receives_current_match_dto(self):
        facts = {
            "venueId": "gold_hall",
            "boxId": "gold_box_3",
            "q": 6,
            "goldAvg": 60000,
            "purpleCount": 3,
            "leaderBid": 50000,
            "targetProfit": 30000,
            "knownGold": "纯白之羽",
        }
        res = self.bridge.dispatch({"action": "manual_facts", "facts": facts})
        self.mock_facts_provider.assert_called_once_with(facts)
        self.assertTrue(res.get("manualFactsResult", {}).get("ok"))
        self.assertIn("currentMatch", res)
        self.assertEqual(res["currentMatch"]["matchId"], "m_test_001")
        self.assertEqual(res["currentMatch"]["facts"]["q"], 5)

    def test_main_dispatches_manual_next_match_and_invokes_shared_lifecycle(self):
        req = {"expectedMatchId": "m_test_001", "disposition": "keep_draft"}
        res = self.bridge.dispatch({"action": "manual_next_match", **req})
        self.mock_next_match_provider.assert_called_once()
        self.assertEqual(res.get("manualNextMatchResult"), {"ok": True, "matchId": "m_next"})
        self.assertIn("currentMatch", res)

    def test_main_dispatches_manual_finalize_and_invokes_shared_lifecycle(self):
        settlement = {
            "clearingPrice": 60000,
            "actualTotal": 75000,
            "acquired": True,
            "winner": "本人拍下",
        }
        req = {"expectedMatchId": "m_test_001", "settlement": settlement}
        res = self.bridge.dispatch({"action": "manual_finalize", **req})
        self.mock_finalize_provider.assert_called_once()
        self.assertEqual(res.get("manualFinalizeResult"), {"ok": True, "matchId": "m_final"})

    def test_main_bridge_rejects_unauthorized_solver_and_ocr_actions(self):
        for action in ("solve", "set_current_match", "load_solver", "run_ocr", "eval_js", "mutate_archive"):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    self.bridge.dispatch({"action": action})

    def test_allowed_actions_set_is_strictly_bounded(self):
        expected_actions = frozenset((
            "toggle_overlay",
            "get_overlay_visibility",
            "toggle_main_pin",
            "set_main_pin",
            "request_app_status",
            "delete_history_record",
            "delete_history_records",
            "request_legacy_archive",
            "select_legacy_archive_source",
            "request_settlement_review",
            "import_settlement_screenshot",
            "replace_settlement_screenshot",
            "delete_settlement_screenshot",
            "rerun_settlement_recognition",
            "save_settlement_review",
            "settlement_item_review_action",
            "manual_facts",
            "manual_next_match",
            "manual_finalize",
            "manual_bootstrap",
            "triggered_snapshot",
            "start_warehouse_capture",
            "prepare_warehouse_capture",
            "confirm_warehouse_capture",
            "stop_warehouse_capture",
            "warehouse_identity_review",
            "save_settlement_screenshot",
            "save_game_screenshot",
            "export_history_records",
            "import_history_bundle",
        ))
        self.assertEqual(MainWindowBridge.ALLOWED_ACTIONS, expected_actions)

    def test_presentation_summary_contains_full_mode_bounded_sections(self):
        from app.main import get_current_match_presentation_summary, CURRENT_MATCH, ACTIVE_SNAPSHOT_HOLDER

        CURRENT_MATCH.begin_next_match()
        CURRENT_MATCH.apply_facts({
            "venueId": "gold_hall",
            "boxId": "gold_box_3",
            "q": 5,
            "goldAvg": 58000,
            "purpleCount": 2,
            "purpleAvg": 4000,
            "leaderBid": 45000,
            "targetProfit": 30000,
            "character": "小桃",
            "entryCost": 5000,
        }, source="manual")

        ACTIVE_SNAPSHOT_HOLDER.update(
            CURRENT_MATCH.id,
            snapshot={
                "matchId": CURRENT_MATCH.id,
                "forecast": {"quantiles": {"p20": 42000, "p50": 58000, "p80": 72000, "recommendedMax": 65000}},
                "mode": {"informationMode": "full_shadow", "coverageRatio": 1.0, "supportedStateCount": 5, "totalStateCount": 5},
                "actionDirective": "BID",
                "actionReason": "当前最高叫价低于推荐上限",
            },
            frozen_prediction={
                "targetLine": 55000,
                "globalLine": 53000,
                "marginalLine": 65000,
                "formalValue": {
                    "ev": 59000,
                    "hardFloor": 25000,
                    "candidateGs": [1, 2, 3],
                    "goldInference": "G in [1, 3]",
                    "breakdown": {"gold": 29000, "purple": 8000, "red": 0, "lowTier": 0},
                },
                "decision": {
                    "theoreticalMin": 20000,
                    "theoreticalMax": 85000,
                    "entryGrade": "A+ 推荐",
                },
            }
        )

        summary = get_current_match_presentation_summary()

        # Check top-level contract
        self.assertEqual(summary["matchId"], CURRENT_MATCH.id)
        self.assertTrue(summary["isComplete"])
        self.assertTrue(summary["hasAnyFact"])

        # Check Lobby bounded section (distinct from match trunk)
        self.assertIn("lobby", summary)
        self.assertEqual(summary["lobby"]["character"], "小桃")
        self.assertEqual(summary["lobby"]["lobbyToolGroup"], "标准仪器")
        self.assertEqual(summary["lobby"]["entryCost"], 5000)

        # Check Missing Facts categorization (missingValueFacts vs missingDecisionFacts)
        self.assertEqual(summary["missingValueFacts"], [])
        self.assertEqual(summary["missingDecisionFacts"], [])

        # Check 6-Rarity Matrix (honest nulls for unparsed white/green/blue)
        self.assertIn("qualities", summary)
        self.assertIsNone(summary["qualities"]["white"]["count"])
        self.assertIsNone(summary["qualities"]["green"]["count"])
        self.assertIsNone(summary["qualities"]["blue"]["count"])
        self.assertEqual(summary["qualities"]["purple"]["count"], 2)
        self.assertEqual(summary["qualities"]["purple"]["avg"], 4000)
        self.assertEqual(summary["qualities"]["gold"]["avg"], 58000)

        # Check Decision Lines (3 lines)
        self.assertIn("decisionLines", summary)
        self.assertEqual(summary["decisionLines"]["targetLine"], 55000)
        self.assertEqual(summary["decisionLines"]["globalLine"], 53000)
        self.assertEqual(summary["decisionLines"]["marginalLine"], 65000)

        # Check Explainability Bounded DTO
        self.assertIn("explainability", summary)
        self.assertEqual(summary["explainability"]["candidateGs"], [1, 2, 3])
        self.assertEqual(summary["explainability"]["hardFloor"], 25000)
        self.assertEqual(summary["explainability"]["theoreticalMin"], 20000)
        self.assertEqual(summary["explainability"]["theoreticalMax"], 85000)
        self.assertEqual(summary["explainability"]["goldInference"], "G in [1, 3]")

        # Check Bidding & Seats Summary (Fixed 4 seats)
        self.assertIn("bidding", summary)
        self.assertEqual(len(summary["bidding"]["seats"]), 4)

        # Check Settlement & Warehouse
        self.assertIn("settlement", summary)
        self.assertIn("warehouse", summary)
        self.assertEqual(summary["warehouse"]["status"], "unrecorded")

    def test_missing_value_facts_vs_missing_decision_facts_distinction(self):
        from app.main import get_current_match_presentation_summary, CURRENT_MATCH

        CURRENT_MATCH.begin_next_match()
        # Only value facts provided (venue, box, q, goldAvg, purpleCount), leaderBid and targetProfit are optional
        CURRENT_MATCH.apply_facts({
            "venueId": "gold_hall",
            "boxId": "gold_box_3",
            "q": 5,
            "goldAvg": 58000,
            "purpleCount": 2,
        }, source="manual")

        summary = get_current_match_presentation_summary()
        self.assertEqual(summary["missingValueFacts"], [])
        self.assertEqual(summary["missingDecisionFacts"], [])

    def test_explainability_candidate_space_is_bounded_and_limits_length(self):
        from app.main import get_current_match_presentation_summary, CURRENT_MATCH, ACTIVE_SNAPSHOT_HOLDER

        CURRENT_MATCH.begin_next_match()
        CURRENT_MATCH.apply_facts({"venueId": "gold_hall", "boxId": "gold_box_3"}, source="manual")

        # Simulate large raw candidate array of 50 items
        large_candidates = list(range(50))
        ACTIVE_SNAPSHOT_HOLDER.update(
            CURRENT_MATCH.id,
            snapshot={"matchId": CURRENT_MATCH.id, "mode": {"informationMode": "structural_only"}},
            frozen_prediction={
                "formalValue": {"candidateGs": large_candidates, "hardFloor": 10000},
                "decision": {"totalStateCount": 50},
            }
        )

        summary = get_current_match_presentation_summary()
        self.assertIsNotNone(summary["explainability"])
        # Must be bounded to at most 10 items in presentation DTO
        self.assertLessEqual(len(summary["explainability"]["candidateGs"]), 10)
        self.assertEqual(summary["explainability"]["candidateStateCount"], 50)

    def test_fact_capture_completeness_and_six_qualities_canonical_wiring(self):
        from core.current_match import CurrentMatch
        from core.canonical_match_record import validate_canonical_match_record_v7
        from core.v06_adapter import canonical_to_v06_solver_input

        match = CurrentMatch()
        match.apply_facts({
            "venueId": "gold_hall",
            "boxId": "gold_box_3",
            "totalItems": 8,
            "totalGrids": 32,
            "q": 5,
            "goldAvg": 58000,
            "goldCount": 2,
            "goldGrid": 10,
            "purpleCount": 3,
            "purpleAvg": 3904,
            "purpleGrid": 9,
            "redCount": 1,
            "redGrid": 6,
            "whiteCount": 1,
            "whiteAvg": 350,
            "whiteGrid": 2,
            "greenCount": 1,
            "greenAvg": 800,
            "greenGrid": 2,
            "blueCount": 0,
            "blueAvg": None,
            "blueGrid": 0,
            "knownGold": "万有星仪+乔望尼金雕像",
            "knownRed": "古旧手提箱",
            "knownPurple": "数码相机",
            "knownWhite": "方盒随身听",
            "knownGreen": "青玉手镯",
            "knownBlue": "漫画书",
        }, source="test_vision")

        snap = match.snapshot()
        self.assertEqual(snap["totalItems"], 8)
        self.assertEqual(snap["totalGrid"], 32)
        self.assertEqual(snap["totalGrids"], 32)
        self.assertEqual(snap["whiteCount"], 1)
        self.assertEqual(snap["whiteAvg"], 350)
        self.assertEqual(snap["whiteGrid"], 2)
        self.assertEqual(snap["greenCount"], 1)
        self.assertEqual(snap["greenAvg"], 800)
        self.assertEqual(snap["greenGrid"], 2)
        self.assertEqual(snap["blueCount"], 0)
        self.assertIsNone(snap["blueAvg"])
        self.assertEqual(snap["knownGold"], "万有星仪+乔望尼金雕像")

        canonical = match.to_canonical()
        is_valid, reasons = validate_canonical_match_record_v7(canonical)
        self.assertTrue(is_valid, f"Canonical validation failed: {reasons}")

        self.assertEqual(canonical["publicIntel"]["totalItems"], 8)
        self.assertEqual(canonical["publicIntel"]["totalGrid"], 32)
        self.assertEqual(canonical["qualities"]["white"]["count"], 1)
        self.assertEqual(canonical["qualities"]["white"]["avg"], 350)
        self.assertEqual(canonical["qualities"]["white"]["grid"], 2)
        self.assertEqual(canonical["qualities"]["green"]["count"], 1)
        self.assertEqual(canonical["qualities"]["green"]["avg"], 800)
        self.assertEqual(canonical["qualities"]["green"]["grid"], 2)
        self.assertEqual(canonical["qualities"]["blue"]["count"], 0)
        self.assertIsNone(canonical["qualities"]["blue"]["avg"])

        # Check known items normalization in canonical
        gold_items = canonical["qualities"]["gold"]["knownItems"]
        self.assertEqual(len(gold_items), 2)
        self.assertEqual(gold_items[0]["name"], "万有星仪")
        self.assertEqual(gold_items[1]["name"], "乔望尼金雕像")

        # Check solver adapter accurately extracts the facts without guessing
        solver_input = canonical_to_v06_solver_input(canonical)
        self.assertEqual(solver_input["totalItems"], 8)
        self.assertEqual(solver_input["totalGrid"], 32)
        self.assertEqual(solver_input["whiteCount"], 1)
        self.assertEqual(solver_input["whiteAvg"], 350)
        self.assertEqual(solver_input["whiteGrid"], 2)
        self.assertEqual(solver_input["greenCount"], 1)
        self.assertEqual(solver_input["greenAvg"], 800)
        self.assertEqual(solver_input["greenGrid"], 2)
        self.assertEqual(solver_input["blueCount"], 0)
        self.assertIsNone(solver_input["blueAvg"])
        self.assertIn("万有星仪", solver_input["knownGold"])
        self.assertIn("乔望尼金雕像", solver_input["knownGold"])

    def test_unobserved_facts_stay_honest_null_and_never_default_to_zero(self):
        from core.current_match import CurrentMatch
        from core.v06_adapter import canonical_to_v06_solver_input

        match = CurrentMatch()
        match.apply_facts({
            "venueId": "gold_hall",
            "boxId": "gold_box_3",
            "q": 5,
            # blue, green, white, totalItems, totalGrid NOT provided
        }, source="partial_manual")

        snap = match.snapshot()
        self.assertIsNone(snap["totalItems"])
        self.assertIsNone(snap["totalGrid"])
        self.assertIsNone(snap["whiteCount"])
        self.assertIsNone(snap["whiteAvg"])
        self.assertIsNone(snap["whiteGrid"])
        self.assertIsNone(snap["greenCount"])
        self.assertIsNone(snap["blueCount"])

        canonical = match.to_canonical()
        self.assertIsNone(canonical["publicIntel"]["totalItems"])
        self.assertIsNone(canonical["publicIntel"]["totalGrid"])
        self.assertIsNone(canonical["qualities"]["white"]["count"])
        self.assertIsNone(canonical["qualities"]["white"]["avg"])
        self.assertIsNone(canonical["qualities"]["green"]["count"])
        self.assertIsNone(canonical["qualities"]["blue"]["count"])

        solver_input = canonical_to_v06_solver_input(canonical)
        self.assertIsNone(solver_input["totalItems"])
        self.assertIsNone(solver_input["totalGrid"])
        self.assertIsNone(solver_input["whiteCount"])
        self.assertIsNone(solver_input["whiteAvg"])
        self.assertIsNone(solver_input["greenCount"])
        self.assertIsNone(solver_input["blueCount"])


if __name__ == "__main__":
    unittest.main()
