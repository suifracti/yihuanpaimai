import unittest
from auction_flow_evidence import AuctionFlowEvidence


class LateSettlementEvidenceTests(unittest.TestCase):
    def test_settlement_start_owns_only_observed_evidence(self):
        flow = AuctionFlowEvidence()
        flow.scene('SETTLEMENT', 't1', 'match-one')
        flow.data.setdefault('acquisition', [])
        flow.add('acquisition', {'acquired': False}, 't2')
        saved = flow.snapshot()
        self.assertTrue(saved['startedAtSettlement'])
        self.assertEqual(saved['ownerMatchId'], 'match-one')
        self.assertEqual(saved['bids'], [])
        self.assertEqual(saved['intel'], [])
        self.assertEqual(saved['acquisition'][0]['acquired'], False)
        flow.scene('SETTLEMENT', 't3', 'match-two')
        self.assertEqual(flow.data['ownerMatchId'], 'match-two')
        self.assertNotIn('acquisition', flow.data)
        self.assertEqual(flow.data['flow'], [{'scene': 'SETTLEMENT', 'capturedAt': 't3'}])
        self.assertEqual(saved['ownerMatchId'], 'match-one')

    def test_new_match_is_not_marked_returned_and_unknown_owner_not_invented(self):
        flow = AuctionFlowEvidence()
        flow.scene('SETTLEMENT', 't0', '')
        self.assertIsNone(flow.data)
        flow.scene('SETTLEMENT', 't1', 'old')
        flow.scene('IN_AUCTION', 't2', 'new')
        self.assertFalse(flow.returned)
        self.assertNotIn('hasReturned', flow.data)
        self.assertFalse(flow.data['startedAtSettlement'])
        flow.scene('SETTLEMENT', 't3', 'new')
        flow.scene('OPEN_WORLD', 't4', 'new')
        self.assertTrue(flow.data['hasReturned'])


if __name__ == '__main__':
    unittest.main()
