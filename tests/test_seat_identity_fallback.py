import unittest
from unittest.mock import patch

from vision_pipeline import NTEVisionPipeline


class SeatIdentityFallbackTests(unittest.TestCase):
    def setUp(self):
        self.player_name = patch('player_identity.get_player_name', return_value='本人昵称')
        self.player_name.start()
        self.addCleanup(self.player_name.stop)
        self.pipe = NTEVisionPipeline()
        self.pipe.current_context['round'] = 2
        self.pipe._slot_names = {1: '甲玩家', 2: '乙玩家', 3: '丙玩家', 4: '本人昵称'}
        self.pipe._derive_seat_leader_and_context(2, {})

    def test_empty_fallback_preserves_identified_self(self):
        self.pipe._bind_horizontal_seats([], 1920, 1080)
        self.assertEqual(self.pipe.current_context['myName'], '本人昵称')
        self.assertEqual([s['slot'] for s in self.pipe.current_context['seats'] if s['isMe']], [4])

    def test_duplicate_name_does_not_guess_self_slot(self):
        self.pipe._slot_names[1] = '本人昵称'
        self.pipe._derive_seat_leader_and_context(2, {})
        self.assertEqual([s['slot'] for s in self.pipe.current_context['seats'] if s['isMe']], [])
        self.assertIsNone(self.pipe.current_context['myBid'])

    def test_actual_self_can_be_third_seat(self):
        self.pipe._slot_names = {1: 'or', 2: 'SIGUNA', 3: '本人昵称', 4: '幽零'}
        self.pipe._slot_cur_bids = {1: 450000, 2: 456789, 3: 7897, 4: 510000}
        self.pipe._derive_seat_leader_and_context(4, self.pipe._slot_cur_bids)
        self.assertEqual([s['slot'] for s in self.pipe.current_context['seats'] if s['isMe']], [3])
        self.assertEqual(self.pipe.current_context['myName'], '本人昵称')
        self.assertEqual(self.pipe.current_context['myBid'], 7897)
        self.assertFalse(self.pipe.current_context['isMyLead'])

    def test_fallback_does_not_invent_unknown_self(self):
        self.pipe.current_context['seats'] = self.pipe._empty_seats()
        self.pipe.current_context['myName'] = None
        self.pipe._bind_horizontal_seats([], 1920, 1080)
        self.assertIsNone(self.pipe.current_context['myName'])

    def test_new_session_clears_previous_self(self):
        self.pipe.reset_session_state()
        self.pipe._bind_horizontal_seats([], 1920, 1080)
        self.assertIsNone(self.pipe.current_context['myName'])
        self.assertFalse(any(s['isMe'] for s in self.pipe.current_context['seats']))

    def test_normal_exit_clears_winner_and_internal_seat_memory(self):
        self.pipe.current_context['winner'] = '旧局竞得者'
        self.pipe._slot_finals[4] = {'1': 480000}
        self.pipe._slot_cur_bids[4] = 500000
        self.pipe._slot_bid_candidates[4] = {'val': 510000, 'count': 1}
        self.assertTrue(self.pipe.clear_match_trunk())
        self.assertIsNone(self.pipe.current_context['winner'])
        self.pipe._derive_seat_leader_and_context(1, self.pipe._slot_cur_bids)
        self.assertIsNone(self.pipe.current_context['myName'])
        self.assertIsNone(self.pipe.current_context['myBid'])
        self.assertFalse(self.pipe.current_context['finalBids'])
        self.assertEqual(self.pipe._slot_bid_candidates[4], {'val': None, 'count': 0})


if __name__ == '__main__':
    unittest.main()
