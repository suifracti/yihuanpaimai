import unittest
from vision_pipeline import NTEVisionPipeline as VisionPipeline
from acquisition_authority import AcquisitionNameTracker


class NumericPlayerNameTests(unittest.TestCase):
    def test_numeric_name_is_not_a_bid_or_round_marker(self):
        pipe = VisionPipeline.__new__(VisionPipeline)
        pipe._slot_names = {}
        pipe._slot_cur_bids = {i: None for i in range(1, 5)}
        pipe._commit_slot_finals = lambda *args: self.fail('nickname became a historical bid')
        rows = [([[150, 674], [165, 674], [165, 697], [150, 697]], '1', .99),
                ([[165, 720], [180, 720], [180, 739], [165, 739]], '3', .99)]
        items, origin = pipe._extract_seat_panel_items(rows, 1920, 1080)
        self.assertEqual([x[-1] for x in items], ['1'])
        pipe._update_seat_names_and_finals_from_ocr(items, 3, origin)
        self.assertEqual(pipe._slot_names[4], '1')
        self.assertTrue(all(v is None for v in pipe._update_seat_current_bids_from_ocr(items, 3).values()))

    def test_winner_name_and_existing_match_tracker(self):
        self.assertEqual(VisionPipeline._clean_settlement_winner_name('1'), '1')
        self.assertIsNone(VisionPipeline._clean_settlement_winner_name('301,188'))
        tracker = AcquisitionNameTracker()
        tracker.bind('actual-match')
        for frame in (1, 2): tracker.observe_name(4, '1', frame)
        tracker.observe_winner('1', .99, False, 3)
        self.assertTrue(tracker.observe_winner('1', .99, False, 4))
        tracker.bind('next-match')
        self.assertIsNone(tracker.observe_winner('1', .99, False, 5))
