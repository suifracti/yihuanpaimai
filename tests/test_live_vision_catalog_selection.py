import unittest
from unittest.mock import patch
import main
from current_match import CurrentMatch

class LiveVisionCatalogSelectionTests(unittest.TestCase):
    def test_confirmed_matcher_key_and_observed_box_reach_solver_catalog(self):
        current=CurrentMatch()
        ctx={'scene':'IN_AUCTION','venue':'中级场 · 珊瑚场','lobbyVenueKey':'shanhu',
             'box':'琉璃宝箱 · 宝石类概率提升','q':12,'goldAvg':74379}
        with patch.object(main,'CURRENT_MATCH',current):
            main.sync_vision_to_current_match(ctx)
        self.assertEqual(current.facts['venueId'],'venue-shanhu')
        self.assertEqual(current.facts['boxId'],'box-shanhu-glass')
        self.assertEqual(current.facts['venue'],'珊瑚场')
        self.assertEqual(current.facts['box'],'琉璃宝箱')
        self.assertEqual(ctx['venueId'],current.facts['venueId'])
        self.assertEqual(ctx['catalogSha256'],current.facts['catalogSha256'])
        self.assertTrue(current.facts['catalogSha256'])

    def test_unknown_matcher_key_does_not_invent_a_catalog_venue(self):
        current=CurrentMatch()
        with patch.object(main,'CURRENT_MATCH',current):
            main.sync_vision_to_current_match({'venue':'未知会场','lobbyVenueKey':'unrecognized','box':'琉璃宝箱'})
        self.assertIsNone(current.facts['venueId'])
        self.assertIsNone(current.facts['boxId'])

    def test_explicit_manual_ids_win_over_an_old_lobby_observation(self):
        current=CurrentMatch()
        with patch.object(main,'CURRENT_MATCH',current):
            main.sync_vision_to_current_match({'venueId':'venue-haibei','lobbyVenueKey':'shanhu',
                'venue':'海贝场','boxId':'box-haibei-damaged-package','box':'破损的包裹'})
        self.assertEqual(current.facts['venueId'],'venue-haibei')
        self.assertEqual(current.facts['boxId'],'box-haibei-damaged-package')
