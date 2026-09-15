import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "core"))
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from vision_pipeline import NTEVisionPipeline

class TestSeatBidConfirmationV1(unittest.TestCase):
    def test_seat_bid_single_frame_fake_high(self):
        pipe = NTEVisionPipeline()
        pipe.reset_session_state()

        # Step 1: Establish baseline 500k
        pipe._update_seat_current_bids_from_df([None, None, None, 500000], 1)
        pipe._update_seat_current_bids_from_df([None, None, None, 500000], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000)

        # Step 2: Inject single-frame fake high (3,200,000)
        pipe._update_seat_current_bids_from_df([None, None, None, 3200000], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000, "1-frame fake high must NOT be committed!")
        self.assertEqual(pipe._slot_bid_candidates[4]["val"], 3200000)
        self.assertEqual(pipe._slot_bid_candidates[4]["count"], 1)

        # Step 3: Returns to 500,000
        pipe._update_seat_current_bids_from_df([None, None, None, 500000], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000, "Confirmed bid must remain 500,000!")
        self.assertIsNone(pipe._slot_bid_candidates[4]["val"])
        self.assertEqual(pipe._slot_bid_candidates[4]["count"], 0)

    def test_seat_bid_single_frame_fake_low(self):
        pipe = NTEVisionPipeline()
        pipe.reset_session_state()

        # Step 1: Establish baseline 500k
        pipe._update_seat_current_bids_from_df([None, None, None, 500000], 1)
        pipe._update_seat_current_bids_from_df([None, None, None, 500000], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000)

        # Step 2: Inject single-frame fake low (666)
        pipe._update_seat_current_bids_from_df([None, None, None, 666], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000, "1-frame fake low must NOT be committed!")
        self.assertEqual(pipe._slot_bid_candidates[4]["val"], 666)
        self.assertEqual(pipe._slot_bid_candidates[4]["count"], 1)

        # Step 3: Returns to 500,000
        pipe._update_seat_current_bids_from_df([None, None, None, 500000], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000, "Confirmed bid must remain 500,000!")
        self.assertIsNone(pipe._slot_bid_candidates[4]["val"])
        self.assertEqual(pipe._slot_bid_candidates[4]["count"], 0)

    def test_seat_bid_two_frame_real_increase(self):
        pipe = NTEVisionPipeline()
        pipe.reset_session_state()

        # Baseline 500k
        pipe._update_seat_current_bids_from_df([None, None, None, 500000], 1)
        pipe._update_seat_current_bids_from_df([None, None, None, 500000], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000)

        # Frame 1 of real increase (879182)
        pipe._update_seat_current_bids_from_df([None, None, None, 879182], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000, "1st frame of increase must remain uncommitted")

        # Frame 2 of real increase (879182) -> Commit
        pipe._update_seat_current_bids_from_df([None, None, None, 879182], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 879182, "2nd consecutive frame must commit 879,182")
        self.assertIsNone(pipe._slot_bid_candidates[4]["val"])
        self.assertEqual(pipe._slot_bid_candidates[4]["count"], 0)

    def test_seat_bid_two_frame_real_decrease(self):
        pipe = NTEVisionPipeline()
        pipe.reset_session_state()

        # Step 1: Establish baseline 879182
        pipe._update_seat_current_bids_from_df([None, None, None, 879182], 1)
        pipe._update_seat_current_bids_from_df([None, None, None, 879182], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 879182)

        # Step 2: Frame 1 of real decrease (581921)
        pipe._update_seat_current_bids_from_df([None, None, None, 581921], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 879182, "1st frame of decrease must remain uncommitted")
        self.assertEqual(pipe._slot_bid_candidates[4]["val"], 581921)

        # Step 3: Frame 2 of real decrease (581921) -> Commit!
        pipe._update_seat_current_bids_from_df([None, None, None, 581921], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 581921, "2nd consecutive frame must commit decreased bid 581,921")
        self.assertIsNone(pipe._slot_bid_candidates[4]["val"])

    def test_seat_bid_two_frame_deep_decrease(self):
        pipe = NTEVisionPipeline()
        pipe.reset_session_state()

        # Step 1: Baseline 581921
        pipe._update_seat_current_bids_from_df([None, None, None, 581921], 1)
        pipe._update_seat_current_bids_from_df([None, None, None, 581921], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 581921)

        # Step 2: Frame 1 of drop to 666
        pipe._update_seat_current_bids_from_df([None, None, None, 666], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 581921)

        # Step 3: Frame 2 of drop to 666 -> Commit!
        pipe._update_seat_current_bids_from_df([None, None, None, 666], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 666, "Must commit deep decrease to 666")

    def test_seat_bid_two_frame_small_quote(self):
        pipe = NTEVisionPipeline()
        pipe.reset_session_state()

        # Step 1: Baseline 581921
        pipe._update_seat_current_bids_from_df([None, None, None, 581921], 1)
        pipe._update_seat_current_bids_from_df([None, None, None, 581921], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 581921)

        # Step 2: Frame 1 of 23333
        pipe._update_seat_current_bids_from_df([None, None, None, 23333], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 581921)

        # Step 3: Frame 2 of 23333 -> Commit!
        pipe._update_seat_current_bids_from_df([None, None, None, 23333], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 23333, "Must commit valid quote 23,333")

    def test_seat_bid_candidate_mutation_downward(self):
        pipe = NTEVisionPipeline()
        pipe.reset_session_state()

        # Baseline 879182
        pipe._update_seat_current_bids_from_df([None, None, None, 879182], 1)
        pipe._update_seat_current_bids_from_df([None, None, None, 879182], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 879182)

        # Frame 1: Candidate 581921 (count=1)
        pipe._update_seat_current_bids_from_df([None, None, None, 581921], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 879182)
        self.assertEqual(pipe._slot_bid_candidates[4]["val"], 581921)

        # Frame 2: Candidate replaces with 666 (count=1)
        pipe._update_seat_current_bids_from_df([None, None, None, 666], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 879182)
        self.assertEqual(pipe._slot_bid_candidates[4]["val"], 666)
        self.assertEqual(pipe._slot_bid_candidates[4]["count"], 1)

        # Frame 3: Candidate 666 confirms (count=2)
        pipe._update_seat_current_bids_from_df([None, None, None, 666], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 666)
        self.assertIsNone(pipe._slot_bid_candidates[4]["val"])

    def test_seat_bid_miss_interrupts(self):
        pipe = NTEVisionPipeline()
        pipe.reset_session_state()

        # Baseline 500k
        pipe._update_seat_current_bids_from_df([None, None, None, 500000], 1)
        pipe._update_seat_current_bids_from_df([None, None, None, 500000], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000)

        # Frame 1: 600k (candidate=1)
        pipe._update_seat_current_bids_from_df([None, None, None, 600000], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000)

        # Frame 2: None (Miss -> Clears candidate)
        pipe._update_seat_current_bids_from_df([None, None, None, None], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000)
        self.assertIsNone(pipe._slot_bid_candidates[4]["val"])
        self.assertEqual(pipe._slot_bid_candidates[4]["count"], 0)

        # Frame 3: 600k (Restarts candidate=1, NOT committed yet!)
        pipe._update_seat_current_bids_from_df([None, None, None, 600000], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 500000)
        self.assertEqual(pipe._slot_bid_candidates[4]["count"], 1)

        # Frame 4: 600k (count=2 -> Committed!)
        pipe._update_seat_current_bids_from_df([None, None, None, 600000], 1)
        self.assertEqual(pipe._slot_cur_bids[4], 600000)

    def test_four_slots_independent(self):
        pipe = NTEVisionPipeline()
        pipe.reset_session_state()

        # Slot 1: 100k, Slot 2: 200k, Slot 3: 300k, Slot 4: 400k
        pipe._update_seat_current_bids_from_df([100000, 200000, 300000, 400000], 1)
        pipe._update_seat_current_bids_from_df([100000, 200000, 300000, 400000], 1)
        self.assertEqual(pipe._slot_cur_bids, {1: 100000, 2: 200000, 3: 300000, 4: 400000})

        # Slot 1 gets fake high, Slot 2 gets real drop (150k), Slot 3 miss, Slot 4 same
        pipe._update_seat_current_bids_from_df([999999, 150000, None, 400000], 1)
        self.assertEqual(pipe._slot_cur_bids, {1: 100000, 2: 200000, 3: 300000, 4: 400000})
        self.assertEqual(pipe._slot_bid_candidates[1]["val"], 999999)
        self.assertEqual(pipe._slot_bid_candidates[2]["val"], 150000)
        self.assertIsNone(pipe._slot_bid_candidates[3]["val"])
        self.assertIsNone(pipe._slot_bid_candidates[4]["val"])

        # Next frame: Slot 1 back to 100k, Slot 2 confirms drop to 150k, Slot 3 back to 300k, Slot 4 same
        pipe._update_seat_current_bids_from_df([100000, 150000, 300000, 400000], 1)
        self.assertEqual(pipe._slot_cur_bids, {1: 100000, 2: 150000, 3: 300000, 4: 400000})
        self.assertIsNone(pipe._slot_bid_candidates[1]["val"])
        self.assertIsNone(pipe._slot_bid_candidates[2]["val"])

    def test_leader_derivation_after_downward_commit(self):
        pipe = NTEVisionPipeline()
        pipe.reset_session_state()
        pipe._slot_names = {1: "Alice", 2: "Bob", 3: "Charlie", 4: "David"}

        # Step 1: Slot 1 = 879182 (Leader), Slot 2 = 700000
        pipe._update_seat_current_bids_from_df([879182, 700000, None, None], 1)
        pipe._update_seat_current_bids_from_df([879182, 700000, None, None], 1)
        pipe._derive_seat_leader_and_context(1, pipe._slot_cur_bids)

        self.assertEqual(pipe.current_context["currentLeaderBid"], 879182)
        self.assertEqual(pipe.current_context["leaderName"], "Alice")

        # Step 2: Slot 1 frame 1 of decrease (581921)
        pipe._update_seat_current_bids_from_df([581921, 700000, None, None], 1)
        pipe._derive_seat_leader_and_context(1, pipe._slot_cur_bids)

        # Leader must REMAIN Alice (879182) because 581921 is not yet confirmed!
        self.assertEqual(pipe.current_context["currentLeaderBid"], 879182)
        self.assertEqual(pipe.current_context["leaderName"], "Alice")

        # Step 3: Slot 1 frame 2 of decrease (581921) -> Confirmed!
        pipe._update_seat_current_bids_from_df([581921, 700000, None, None], 1)
        pipe._derive_seat_leader_and_context(1, pipe._slot_cur_bids)

        # Leader must switch to Bob with 700,000!
        self.assertEqual(pipe.current_context["currentLeaderBid"], 700000)
        self.assertEqual(pipe.current_context["leaderName"], "Bob")

if __name__ == "__main__":
    unittest.main()
