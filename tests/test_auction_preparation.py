"""Bounded instrument/panel orchestration. Synthetic transport, no game input."""
import tempfile
import unittest

from domain_action_session import advance_live_domain_loop, fresh_live_domain_state
import test_domain_action_session as domain_tests


class AuctionPreparationTests(unittest.TestCase):
    def view(self, directory, scene, *, average=None, receipt=None):
        view = domain_tests.AuthorizedLiveDomainLoopTests().view(
            funds=2524575, scene=scene, round_no=1, directory=directory)
        view.update(q=22, goldAvg=average, purpleCount=3, preparationReceipt=receipt)
        if average is None:
            view['proposalEvent']['predictionSnapshot']['status']['solverStatus'] = 'incomplete'
        return view

    def test_valid_interval_without_gold_average_still_gets_first_stage_instruments(self):
        with tempfile.TemporaryDirectory() as directory:
            view=self.view(directory,'AUCTION_READY')
            snap=view['proposalEvent']['predictionSnapshot']
            snap['status']['solverStatus']='valid'
            snap['input']['normalizedFacts']['goldAvg']=None
            sent=[]
            advance_live_domain_loop(fresh_live_domain_state(),view,lambda _,e:sent.append(e) or True)
            self.assertEqual(sent[0]['intent']['kind'],'OpenInstrument')

    def test_purple_count_uses_same_host_path_and_never_creates_a_numeric_fact(self):
        with tempfile.TemporaryDirectory() as directory:
            sent=[]
            send=lambda _,e:sent.append(e) or True
            state=fresh_live_domain_state()
            for scene,expected in [('AUCTION_READY','OpenInstrument'),
                                   ('INSTRUMENT_GOLD_SELECTED','SelectPurpleCount'),
                                   ('INSTRUMENT_PURPLE_SELECTED','UsePurpleCount')]:
                receipt=dict(sent[-1]['intent'],status='CONFIRMED') if sent else None
                view=self.view(directory,scene,average=29739,receipt=receipt)
                view['purpleCount']=None
                advance_live_domain_loop(state,view,send)
                self.assertEqual(sent[-1]['intent']['kind'],expected)
            view=self.view(directory,'AUCTION_READY',average=29739,
                           receipt=dict(sent[-1]['intent'],status='CONFIRMED'))
            view.update(purpleCount=None,purpleCountVisible=True)
            advance_live_domain_loop(state,view,send)
            self.assertIsNone(view['purpleCount'])
            self.assertEqual(sent[-1]['intent']['kind'],'OpenBidPanel')
            self.assertTrue(all(e['intent']['amount'] is None for e in sent))

    def test_no_solver_value_after_reveal_skips_round_without_input(self):
        with tempfile.TemporaryDirectory() as directory:
            view=self.view(directory,'AUCTION_READY')
            view['goldAverageVisible']=True
            sent=[]
            state=advance_live_domain_loop(fresh_live_domain_state(),view,lambda _,e:sent.append(e) or True)
            self.assertEqual(sent,[])
            self.assertEqual(state['reason'],'ROUND_SKIPPED_NO_SOLVER_VALUE')

    def test_select_use_and_effect_then_solver_opens_bid_panel(self):
        with tempfile.TemporaryDirectory() as directory:
            sent = []
            send = lambda owner, envelope: sent.append(envelope) or True
            state = fresh_live_domain_state()
            view = self.view(directory, 'AUCTION_READY')
            state = advance_live_domain_loop(state, view, send)
            self.assertEqual(len(sent), 1, 'missing gold mean must open the instrument, not wait forever')
            self.assertEqual(sent[-1]['intent']['kind'], 'OpenInstrument')
            self.assertEqual(state['phase'], 'preparing')
            advance_live_domain_loop(state, view, send)
            self.assertEqual(len(sent), 1, 'pending input is never repeated')
            for scene, expected in [('INSTRUMENT_LIST', 'SelectGoldAverage'),
                                    ('INSTRUMENT_GOLD_SELECTED', 'UseGoldAverage')]:
                receipt = {**sent[-1]['intent'], 'status': 'CONFIRMED'}
                state = advance_live_domain_loop(state, self.view(directory, scene, receipt=receipt), send)
                self.assertEqual(sent[-1]['intent']['kind'], expected)
            receipt = {**sent[-1]['intent'], 'status': 'CONFIRMED'}
            revealed = self.view(directory, 'AUCTION_READY', receipt=receipt)
            revealed['goldAverageVisible'] = True
            state = advance_live_domain_loop(state, revealed, send)
            self.assertEqual(len(sent), 3)
            self.assertIsNone(state.get('amount'), 'seeing a used instrument never creates a bid')
            # Only newly admitted numeric facts and the existing Solver proposal
            # permit opening the panel; no average is inferred from the receipt.
            state = advance_live_domain_loop(state, self.view(directory, 'AUCTION_READY', average=29739), send)
            self.assertEqual(sent[-1]['intent']['kind'], 'OpenBidPanel')
            self.assertEqual([row['intent']['amount'] for row in sent], [None]*4)

    def test_nonfinancial_unknown_follows_the_observed_scene_without_reusing_a_ticket(self):
        for outcome in ('UNKNOWN', 'NOT_SENT'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                sent = []
                send = lambda owner, envelope: sent.append(envelope) or True
                state = advance_live_domain_loop(fresh_live_domain_state(), self.view(directory, 'AUCTION_READY'), send)
                self.assertEqual(len(sent), 1)
                receipt = {**sent[0]['intent'], 'status': outcome}
                state = advance_live_domain_loop(state, self.view(directory, 'INSTRUMENT_LIST', receipt=receipt), send)
                self.assertEqual(state['phase'], 'preparing')
                self.assertEqual(sent[-1]['intent']['kind'],'SelectGoldAverage')
                self.assertNotEqual(sent[0]['intent']['intentId'],sent[-1]['intent']['intentId'])
                advance_live_domain_loop(state, self.view(directory, 'AUCTION_READY'), send)
                self.assertEqual(len(sent), 2)
        with tempfile.TemporaryDirectory() as directory:
            sent = []
            view = self.view(directory, 'AUCTION_READY')
            view['current']['sourceQualified'] = False
            advance_live_domain_loop(fresh_live_domain_state(), view, lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(sent, [])

    def test_old_or_foreign_preparation_receipt_cannot_advance(self):
        with tempfile.TemporaryDirectory() as directory:
            sent = []
            send = lambda owner, envelope: sent.append(envelope) or True
            state = advance_live_domain_loop(fresh_live_domain_state(), self.view(directory, 'AUCTION_READY'), send)
            receipt = {**sent[0]['intent'], 'status': 'CONFIRMED', 'matchGeneration': 99}
            advance_live_domain_loop(state, self.view(directory, 'INSTRUMENT_LIST', receipt=receipt), send)
            self.assertEqual(len(sent), 1)
            self.assertEqual(state['phase'], 'preparing')


if __name__ == '__main__':
    unittest.main()
