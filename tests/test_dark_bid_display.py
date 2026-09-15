import copy
import unittest
from unittest.mock import patch
from current_match import CurrentMatch
from live_match_projection import bids_hidden_now, project_bidding_summary
import main


class DarkBidDisplayTests(unittest.TestCase):
    def test_live_hidden_settlement_visible_without_erasing_evidence(self):
        facts = {'fieldCondition':'dark', 'leaderBid':900000,
                 'seats':[{'slot':1,'name':'test','currentBid':900000,'bid':900000,'observationStatus':'VISIBLE'}]}
        before = copy.deepcopy(facts)
        summary = project_bidding_summary(facts)
        self.assertTrue(summary['hiddenBids'])
        self.assertEqual(summary['seats'][0]['currentBid'], 900000)
        self.assertEqual(facts, before)
        for patch_data in ({'fieldCondition':'standard'}, {'scene':'SETTLEMENT'}, {'isSettlement':True}, {'lifecycleStatus':'FINALIZED'}, {'settlementFinalized':True}):
            self.assertFalse(bids_hidden_now({**facts, **patch_data}))
        self.assertTrue(bids_hidden_now({**facts, 'fieldCondition':'天黑了'}))

    def test_main_hud_mark_hidden_but_preserve_current_fact(self):
        match = CurrentMatch()
        match.apply_facts({'fieldCondition':'dark','leaderBid':900000}, intent='confirm')
        with patch.object(main, 'CURRENT_MATCH', match):
            self.assertTrue(main.get_current_match_presentation_summary()['bidding']['hiddenBids'])
            hud = main.build_manual_alpha_payload(include_solver_input=False)
            self.assertTrue(hud['hiddenBids'])
            self.assertEqual(hud['leaderBid'], 900000)
        self.assertEqual(match.snapshot()['leaderBid'], 900000)
