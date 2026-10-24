import unittest
from domain_action_session import fresh_live_domain_state, advance_live_domain_loop
from test_domain_action_session import AuthorizedLiveDomainLoopTests


class SettlementAutoSaleTests(unittest.TestCase):
    def setUp(self):
        self.view = AuthorizedLiveDomainLoopTests().view(
            funds=200000, scene='SETTLEMENT', round_no=5, directory='build',
            collectionFinished=True, settlementAcquired=True, mode='bid')
        self.state, self.sent = fresh_live_domain_state(), []

    def step(self):
        self.view['frameSequence'] = self.view.get('frameSequence', 0) + 1
        advance_live_domain_loop(self.state, self.view, lambda _, e: self.sent.append(e['intent']) or True)

    def receipt(self, status, reason='test'):
        self.view['sessionReceipt'] = dict(self.sent[-1], status=status, reason=reason)

    def test_saved_own_match_sells_then_returns(self):
        self.view['collectionFinished'] = False
        self.step()
        self.assertFalse(self.sent)
        self.view['collectionFinished'] = True
        self.step()
        self.assertEqual(self.sent[-1]['kind'], 'SellNonRed')
        self.assertEqual(self.sent[-1]['fundsBefore'], 200000)
        self.step()
        self.assertEqual(len(self.sent), 1)
        self.receipt('CONFIRMED')
        self.step()
        self.assertEqual(self.sent[-1]['kind'], 'ReturnLobby')
        self.assertEqual(self.state['settlementSale']['status'], 'sold')

    def test_observe_other_winner_or_unknown_does_not_sell(self):
        for mode, acquired in [('observe', True), ('bid', False), ('bid', None)]:
            self.setUp()
            self.view.update(mode=mode, settlementAcquired=acquired)
            self.step()
            self.assertEqual(self.sent[-1]['kind'], 'ReturnLobby')

    def test_red_cannot_be_cancelled_returns_with_reason(self):
        self.step()
        self.receipt('NOT_SENT', 'SALE_RED_NOT_CANCELLED')
        self.step()
        self.assertEqual(self.sent[-1]['kind'], 'ReturnLobby')
        self.assertEqual(self.state['settlementSale']['reason'], 'SALE_RED_NOT_CANCELLED')

    def test_unknown_sale_retries_new_ticket_not_bid_semantics(self):
        self.step()
        first = self.sent[-1]
        self.receipt('UNKNOWN')
        self.step()
        self.assertEqual(self.sent[-1]['kind'], 'SellNonRed')
        self.assertNotEqual(first['intentId'], self.sent[-1]['intentId'])
        self.assertEqual(self.sent[-1]['fundsBefore'], first['fundsBefore'])

    def test_repeated_no_result_returns_and_records_unconfirmed(self):
        self.step()
        for _ in range(3):
            self.receipt('UNKNOWN')
            self.step()
        self.assertEqual([i['kind'] for i in self.sent], ['SellNonRed']*3+['ReturnLobby'])
        self.assertEqual(self.state['settlementSale']['status'], 'unconfirmed')

    def test_low_balance_can_sell_before_lobby_floor_stops(self):
        self.view.update(currentFunds=50000, minimumFunds=100000)
        self.step()
        self.assertEqual(self.sent[-1]['kind'], 'SellNonRed')

    def test_foreign_receipt_does_not_complete_sale(self):
        self.step()
        self.receipt('CONFIRMED')
        self.view['sessionReceipt']['matchId'] = 'other'
        self.step()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.state['phase'], 'sale_dispatched')
