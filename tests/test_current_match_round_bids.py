"""The Native CurrentMatch writer keeps observations for each auction round."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "core"), str(ROOT / "app")]

from canonical_history_store import CanonicalHistoryStore
from current_match import CurrentMatch
from live_match_transport import LiveMatchPublisher, LiveMatchReceiver


def seat(slot, bid=None, name=None):
    return {"slot": slot, "name": name, "currentBid": bid, "bid": bid,
            "observationStatus": "VISIBLE" if bid is not None else "UNOBSERVED"}


class CurrentMatchRoundBidsTests(unittest.TestCase):
    def rounds(self, match):
        return match.to_canonical()["bidding"]["rounds"]

    def test_round_switch_preserves_four_seats_and_does_not_carry_quotes(self):
        match = CurrentMatch()
        match.apply_facts({"roundNo": 1, "seats": [seat(1, 311847, "A"), seat(3, 450000, "C")]}, source="vision")
        match.apply_facts({"roundNo": 2, "seats": [seat(1), seat(2, 200000, "B")]}, source="vision")
        rows = self.rounds(match)
        self.assertEqual([row["round"] for row in rows], [1, 2])
        self.assertEqual([s["currentBid"] for s in rows[0]["bids"]["opponents"]], [311847, None, 450000, None])
        self.assertEqual([s["currentBid"] for s in rows[1]["bids"]["opponents"]], [None, 200000, None, None])
        self.assertEqual(rows[0]["bids"]["opponents"][0]["name"], "A")

    def test_same_round_latest_observed_quote_and_missing_do_not_erase(self):
        match = CurrentMatch()
        for amount in (500000, 500000, 400000, None):
            match.apply_facts({"roundNo": 1, "seats": [seat(1, amount)]}, source="vision")
        rows = self.rounds(match)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bids"]["opponents"][0]["currentBid"], 400000)

    def test_observed_round_with_no_quotes_is_four_unknowns_and_visible_zero_is_retained(self):
        match = CurrentMatch()
        match.apply_facts({"roundNo": 1}, source="vision")
        self.assertEqual([s["currentBid"] for s in self.rounds(match)[0]["bids"]["opponents"]], [None] * 4)
        match.apply_facts({"seats": [seat(4, 0)]}, source="vision")
        self.assertEqual(self.rounds(match)[0]["bids"]["opponents"][3]["currentBid"], 0)
        match.apply_facts({"bidRounds": []}, source="vision", intent="snapshot")
        self.assertEqual(len(self.rounds(match)), 1)

    def test_round_only_transition_clears_live_quotes_before_next_observation(self):
        match = CurrentMatch()
        match.apply_facts({"roundNo": 1, "seats": [seat(1, 500000)]}, source="vision")
        match.apply_facts({"roundNo": 2}, source="vision")
        self.assertIsNone(match.facts["seats"][0]["currentBid"])
        match.apply_facts({"seats": [seat(2, 200000)]}, source="vision")
        self.assertEqual(self.rounds(match)[-1]["round"], 2)
        self.assertIsNone(self.rounds(match)[-1]["bids"]["opponents"][0]["currentBid"])

    def test_transport_store_cold_read_and_new_match(self):
        worker = CurrentMatch()
        worker.apply_facts({"roundNo": 1, "seats": [seat(4, 387554)]}, source="vision")
        worker.apply_facts({"roundNo": 2, "seats": [seat(1, 273000)]}, source="vision")
        self.assertEqual(len(self.rounds(worker)), 2)
        main = CurrentMatch()
        self.assertTrue(LiveMatchReceiver().apply(LiveMatchPublisher().attach({}, worker)["visionState"], main))
        self.assertEqual(self.rounds(main), self.rounds(worker))
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
            path = str(Path(directory) / "history.json")
            CanonicalHistoryStore(path).persist_record_transactional(main.to_canonical(), is_finalized=False)
            saved = CanonicalHistoryStore(path).lookup(main.id)
            self.assertEqual(saved["bidding"]["rounds"], self.rounds(worker))
            reopened = CurrentMatch()
            reopened.apply_facts(saved, source="auto", intent="snapshot")
            self.assertEqual(self.rounds(reopened), self.rounds(worker))
        main.begin_next_match()
        self.assertEqual(self.rounds(main), [])

    def test_settlement_does_not_create_a_round_or_rewrite_past_bids(self):
        match = CurrentMatch()
        match.apply_facts({"roundNo": 1, "seats": [seat(1, 311847)]}, source="vision")
        before = self.rounds(match)
        self.assertEqual(len(before), 1)
        match.apply_facts({"roundNo": 0, "seats": [], "actualTotal": 9999999}, source="vision")
        self.assertEqual(self.rounds(match), before)

    def test_partial_seat_observation_keeps_other_observed_slots_in_round(self):
        match = CurrentMatch()
        match.apply_facts({"roundNo": 1, "seats": [seat(1, 100000), seat(2, 200000)]}, source="vision")
        match.apply_facts({"seats": [seat(3, 300000)]}, source="vision")
        self.assertEqual([s["currentBid"] for s in self.rounds(match)[0]["bids"]["opponents"]],
                         [100000, 200000, 300000, None])

    def test_main_readback_projection_uses_capture_time_and_survives_cold_read(self):
        match = CurrentMatch()
        observed = {**seat(1, 311847), "capturedAt": "2026-10-21T06:05:57.046530+00:00",
                    "bidRawText": "311,847"}
        match.apply_facts({"roundNo": 1, "seats": [observed]}, source="vision")
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
            path = str(Path(directory) / "history.json")
            CanonicalHistoryStore(path).persist_record_transactional(match.to_canonical(), is_finalized=False)
            record = CanonicalHistoryStore(path).lookup(match.id)
        # Main's existing history view reads this exact round / seats shape.
        displayed = record["auctionEvidence"]["bids"]
        self.assertEqual(len(displayed), 1)
        self.assertEqual(displayed[0]["round"], 1)
        self.assertEqual(displayed[0]["capturedAt"], observed["capturedAt"])
        self.assertEqual(displayed[0]["source"], "canonical-bidding-round")
        self.assertEqual([s["currentBid"] for s in displayed[0]["seats"]], [311847, None, None, None])
        self.assertEqual(displayed[0]["seats"][0]["bidRawText"], observed["bidRawText"])
        reopened = CurrentMatch()
        reopened.apply_facts(record, source="auto", intent="snapshot")
        reopened.apply_facts({"roundNo": 1, "seats": [seat(1, 400000)]}, source="vision")
        self.assertEqual(reopened.to_canonical()["auctionEvidence"]["bids"][0]["seats"][0]["currentBid"], 400000)

    def test_existing_raw_evidence_untouched_new_round_added_without_invented_time(self):
        match = CurrentMatch()
        original = {"version": 1, "ownerMatchId": match.id,
                    "bids": [{"round": 1, "capturedAt": "original-capture", "seats": [seat(1, 500000)]}],
                    "intel": [{"rawText": "原有情报"}]}
        match.apply_facts({"auctionEvidence": original}, source="vision")
        match.apply_facts({"roundNo": 1, "seats": [seat(1, 400000)]}, source="vision")
        match.apply_facts({"roundNo": 2, "seats": [seat(2, 200000)]}, source="vision")
        projected = match.to_canonical()["auctionEvidence"]
        self.assertEqual(projected["bids"][0], original["bids"][0])
        self.assertEqual(projected["intel"], original["intel"])
        self.assertEqual([r["round"] for r in projected["bids"]], [1, 2])
        self.assertNotIn("capturedAt", projected["bids"][1])
        self.assertEqual(match.facts["auctionEvidence"], original)
        self.assertEqual(len(original["bids"]), 1)


if __name__ == "__main__":
    unittest.main()
