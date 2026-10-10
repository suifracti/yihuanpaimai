# -*- coding: utf-8 -*-
"""P2: four-seat bids and full intel reach presentation and history."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "core")]

DATA_ROOT = ROOT / "build" / "diagnosis_20260909" / "p2-seats-intel-data"
os.environ["YIHUAN_DATA_ROOT"] = str(DATA_ROOT)

from current_match import CurrentMatch
from live_match_projection import project_four_seats, project_intel, project_bidding_summary
import main


class TestP2SeatsIntelProjection(unittest.TestCase):
    def setUp(self):
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        self.match = CurrentMatch()

    def test_zero_bid_is_visible_not_missing(self):
        seats = project_four_seats([
            {"slot": 1, "name": "甲", "currentBid": 1222222},
            {"slot": 2, "name": "乙", "currentBid": 0},
            {"slot": 3, "name": "丙", "currentBid": 555555},
            {"slot": 4, "name": "丁", "currentBid": 666666, "isMe": True},
        ])
        self.assertEqual(seats[1]["currentBid"], 0)
        self.assertEqual(seats[1]["bid"], 0)
        self.assertEqual(seats[1]["observationStatus"], "VISIBLE")
        self.assertTrue(seats[3]["isMe"])

    def test_unnamed_slots_are_not_invented_player_names(self):
        seats = project_four_seats([])
        names = [s["name"] for s in seats]
        self.assertEqual(names, [None, None, None, None])
        self.assertNotIn("玩家本人", names)
        self.assertNotIn("席位 2", names)

    def test_intel_keeps_full_text(self):
        evidence = {
            "intel": [{
                "round": 2,
                "capturedAt": "2026-09-09T21:00:00",
                "lines": [{"text": "随机展示5件藏品。"}, {"text": "金色均价 64836"}],
            }]
        }
        from copy import deepcopy
        first = deepcopy(evidence["intel"][0])
        evidence["intel"].extend([
            {**deepcopy(first), "capturedAt": "2026-09-09T21:00:01", "timer": 24},
            {**deepcopy(first), "round": 3},
            {"round": 2, "lines": [{"text": "随机展示6件藏品。"}, {"text": "金色均价 64836"}]},
        ])
        original = deepcopy(evidence)
        intel = project_intel(evidence, {"q": {"status": "OBSERVED", "value": 21}})
        self.assertIn("随机展示5件藏品。", intel["observations"][0]["text"])
        self.assertEqual(intel["structured"][0]["participation"], "valuation")
        self.assertEqual(evidence, original)
        self.assertEqual(intel["observationCount"], 4)
        self.assertEqual(len(intel["observations"]), 3)
        self.assertEqual(intel["observations"][0]["readingCount"], 2)
        self.assertEqual(intel["observations"][0]["lastCapturedAt"], "2026-09-09T21:00:01")
        self.assertEqual(intel["observations"][1]["round"], 3)
        self.assertIn("随机展示6件藏品。", intel["observations"][2]["text"])

    def test_transient_card_text_survives_blank_followup_into_draft(self):
        first = {"round": 4, "frameId": "capture-1", "rawText": "本局内所有蓝色品质藏品的总数量为2件。", "is_physical_ocr": True}
        blank = {"round": 4, "frameId": "capture-2", "rawText": "", "is_physical_ocr": True}
        prior_cost = self.match.facts["intelCost"]
        self.match.apply_facts({"intelCardReadings": [first]}, source="vision")
        self.match.apply_facts({"intelCardReadings": [blank]}, source="vision")
        evidence = self.match.to_canonical()["intelCardEvidence"]
        self.assertEqual(evidence["cardReadings"], [first])
        self.assertIsNone(self.match.facts["blueCount"])
        self.assertEqual(self.match.facts["intelCost"], prior_cost)

    def test_current_match_stores_seats_and_intel(self):
        seats = [
            {"slot": 1, "name": "甲", "currentBid": 1000, "bid": 1000},
            {"slot": 2, "name": None, "currentBid": 0, "bid": 0},
            {"slot": 3, "name": "丙", "currentBid": None},
            {"slot": 4, "name": "丁", "currentBid": 2000, "isMe": True},
        ]
        evidence = {
            "ownerMatchId": self.match.id,
            "intel": [{"round": 1, "lines": [{"text": "本回合展示Q=21"}]}],
            "bids": [{"round": 1, "seats": seats}],
        }
        self.match.apply_facts({
            "q": 21,
            "seats": seats,
            "auctionEvidence": evidence,
            "intelFacts": {"q": {"status": "OBSERVED", "value": 21}},
        }, source="vision")
        self.assertEqual(self.match.facts["seats"][1]["currentBid"], 0)
        record = self.match.to_canonical()
        self.assertEqual(record["bidding"]["seats"][1]["currentBid"], 0)
        self.assertEqual(record["auctionEvidence"]["intel"][0]["lines"][0]["text"], "本回合展示Q=21")

    def test_presentation_uses_observed_seats(self):
        seats = [
            {"slot": 1, "name": "甲", "currentBid": 1222222, "bid": 1222222},
            {"slot": 2, "name": "乙", "currentBid": 0, "bid": 0},
            {"slot": 3, "name": "丙", "currentBid": 555555, "bid": 555555},
            {"slot": 4, "name": "丁", "currentBid": 666666, "bid": 666666, "isMe": True},
        ]
        self.match.apply_facts({"q": 21, "goldAvg": 64836, "seats": seats, "leaderName": "丁"}, source="vision")
        with patch.object(main, "CURRENT_MATCH", self.match):
            summary = main.get_current_match_presentation_summary()
        shown = summary["bidding"]["seats"]
        self.assertEqual(len(shown), 4)
        self.assertEqual(shown[1]["bid"], 0)
        self.assertEqual(shown[0]["name"], "甲")
        self.assertNotEqual(shown[0]["name"], "玩家本人")
        self.assertNotEqual(shown[1]["name"], "席位 2")

    def test_self_bid_follows_confirmed_seat_not_fourth_position(self):
        # Saved R4 image: PLAYER_LOCAL is the orange third seat (7,897),
        # while the fourth seat 幽零 bids 510,000.
        seats = [
            {"slot": 1, "name": "or", "currentBid": 450000, "isMe": False},
            {"slot": 2, "name": "SIGUNA", "currentBid": 456789, "isMe": False},
            {"slot": 3, "name": "PLAYER_LOCAL", "currentBid": 7897, "isMe": True},
            {"slot": 4, "name": "幽零", "currentBid": 510000, "isMe": False},
        ]
        self.match.apply_facts({"roundNo": 4, "seats": [{**s, "isMe": s["slot"] == 4} for s in seats]}, source="vision")
        self.match.apply_facts({"roundNo": 4, "seats": seats}, source="vision")
        self.assertEqual([s["slot"] for s in self.match.facts["seats"] if s.get("isMe")], [3])
        data = {"seats": self.match.facts["seats"]}
        main._native_project_current_quote(data, self.match)
        self.assertEqual(data["myBid"], 7897)
        self.assertEqual(data["leaderBid"], 510000)

    def test_hud_payload_keeps_zero_bid(self):
        payload = main.build_in_auction_hud_payload({
            "scene": "IN_AUCTION",
            "round": 2,
            "q": 21,
            "goldAvg": 64836,
            "seats": [
                {"slot": 1, "name": "甲", "bid": 1222222, "currentBid": 1222222},
                {"slot": 2, "name": "乙", "bid": 0, "currentBid": 0},
                {"slot": 3, "name": "丙", "bid": 555555, "currentBid": 555555},
                {"slot": 4, "name": "丁", "bid": 666666, "currentBid": 666666, "isMe": True},
            ],
        }, compute_shadow=False)
        self.assertEqual(payload["seats"][1]["currentBid"], 0)

    def test_per_seat_round_lifecycle_and_settlement_protection(self):
        match = CurrentMatch()
        # Round 1: Seat 1 bids 711111, Seat 2 bids 0
        match.apply_facts({
            "round": 1,
            "scene": "IN_AUCTION",
            "seats": [
                {"slot": 1, "name": "A", "currentBid": 711111, "bid": 711111, "observationStatus": "VISIBLE"},
                {"slot": 2, "name": "B", "currentBid": 0, "bid": 0, "observationStatus": "VISIBLE"},
                {"slot": 3, "name": "C", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
                {"slot": 4, "name": "D", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
            ]
        }, source="vision")
        self.assertEqual(match.facts["seats"][0]["currentBid"], 711111)
        self.assertEqual(match.facts["seats"][1]["currentBid"], 0)

        # Partial observation within same Round 1: only Seat 3 updates, Seat 1 and 2 should be preserved
        match.apply_facts({
            "round": 1,
            "scene": "IN_AUCTION",
            "seats": [
                {"slot": 1, "name": "A", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
                {"slot": 2, "name": "B", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
                {"slot": 3, "name": "C", "currentBid": 555555, "bid": 555555, "observationStatus": "VISIBLE"},
                {"slot": 4, "name": "D", "currentBid": 333333, "bid": 333333, "observationStatus": "VISIBLE"},
            ]
        }, source="vision")
        self.assertEqual(match.facts["seats"][0]["currentBid"], 711111)
        self.assertEqual(match.facts["seats"][1]["currentBid"], 0)
        self.assertEqual(match.facts["seats"][2]["currentBid"], 555555)
        self.assertEqual(match.facts["seats"][3]["currentBid"], 333333)

        # Round 2 begins: new round MUST NOT show round 1 prices as current active bids!
        match.apply_facts({
            "round": 2,
            "scene": "IN_AUCTION",
            "seats": [
                {"slot": 1, "name": "A", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
                {"slot": 2, "name": "B", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
                {"slot": 3, "name": "C", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
                {"slot": 4, "name": "D", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
            ]
        }, source="vision")
        self.assertIsNone(match.facts["seats"][0]["currentBid"])
        self.assertIsNone(match.facts["seats"][1]["currentBid"])

        # Round 2 bids arrive: 1222222 / 0 / 555555 / 666666
        match.apply_facts({
            "round": 2,
            "scene": "IN_AUCTION",
            "seats": [
                {"slot": 1, "name": "A", "currentBid": 1222222, "bid": 1222222, "observationStatus": "VISIBLE"},
                {"slot": 2, "name": "B", "currentBid": 0, "bid": 0, "observationStatus": "VISIBLE"},
                {"slot": 3, "name": "C", "currentBid": 555555, "bid": 555555, "observationStatus": "VISIBLE"},
                {"slot": 4, "name": "D", "currentBid": 666666, "bid": 666666, "observationStatus": "VISIBLE"},
            ]
        }, source="vision")
        self.assertEqual(match.facts["seats"][0]["currentBid"], 1222222)
        self.assertEqual(match.facts["seats"][1]["currentBid"], 0)

        # Transition to SETTLEMENT with empty seats: settlement frames must NOT clear round 2 bids to 0 or None!
        match.apply_facts({
            "round": 2,
            "scene": "SETTLEMENT",
            "isSettlement": True,
            "seats": [
                {"slot": 1, "name": "A", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
                {"slot": 2, "name": "B", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
                {"slot": 3, "name": "C", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
                {"slot": 4, "name": "D", "currentBid": None, "bid": None, "observationStatus": "UNOBSERVED"},
            ]
        }, source="vision")
        self.assertEqual(match.facts["seats"][0]["currentBid"], 1222222)
        self.assertEqual(match.facts["seats"][1]["currentBid"], 0)
        self.assertEqual(match.facts["seats"][2]["currentBid"], 555555)
        self.assertEqual(match.facts["seats"][3]["currentBid"], 666666)

    def test_engine_round_number_clears_current_quote_not_history_or_manual_fact(self):
        match = CurrentMatch()
        match.apply_facts({
            "roundNo": 4, "leaderBid": 711111,
            "seats": [{"slot": 1, "currentBid": 711111, "observationStatus": "VISIBLE"}],
            "historicalBids": {"3": {"seat1": 555555}},
            "q": 22,
        }, source="vision")
        match.apply_facts({"q": 23}, source="manual", intent="confirm")
        match.apply_facts({
            "roundNo": 5, "leaderBid": None, "myBid": None,
            "seats": [{"slot": 1, "currentBid": None, "observationStatus": "UNOBSERVED"}],
            "q": 22,
        }, source="vision")
        self.assertIsNone(match.facts["leaderBid"])
        self.assertIsNone(match.facts["seats"][0]["currentBid"])
        self.assertEqual(match.facts["historicalBids"], {"3": {"seat1": 555555}})
        self.assertEqual(match.facts["q"], 23)


if __name__ == "__main__":
    unittest.main()
