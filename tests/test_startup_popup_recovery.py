import unittest
from startup_popup_recovery import advance, KNOWN_POPUPS
import test_instrument_restock

class StartupPopupRecoveryTests(unittest.TestCase):
    def view(self, scene):
        v=test_instrument_restock.InstrumentRestockTests().view(scene)
        v['currentFunds']=None
        return v
    def test_all_known_popups_cancel_without_money_then_reread_lobby(self):
        for scene in KNOWN_POPUPS:
            state, sent={'phase':'idle'},[]
            send=lambda _,e: sent.append(e['intent']) or True
            self.assertTrue(advance(state,self.view(scene),send))
            self.assertEqual(sent[-1]['kind'],'CancelKnownPopup')
            self.assertIsNone(sent[-1]['amount'])
            self.assertEqual(sent[-1]['recoveryScene'],scene)
            self.assertTrue(advance(state,self.view(scene),send))
            self.assertEqual(len(sent),1)
            v=self.view('LOBBY')
            self.assertFalse(advance(state,v,send))
            self.assertTrue(state['startupRecovery']['done'])
            self.assertIsNone(state.get('funds'))
            self.assertFalse(advance(state,self.view('ENTRY_FEE'),send))
            self.assertEqual(len(sent),1) # Normal next-match fee must not be cancelled.
    def test_nested_cancel_then_close(self):
        state,sent={'phase':'idle'},[]
        send=lambda _,e: sent.append(e['intent']) or True
        advance(state,self.view('TOOL_REFILL_CONFIRM'),send)
        v=self.view('TOOL_SETUP');v['preparationReceipt']=dict(sent[-1],status='CONFIRMED')
        advance(state,v,send)
        self.assertEqual(sent[-1]['recoveryScene'],'TOOL_SETUP')
        self.assertEqual(len(sent),2)
    def test_no_blind_infinite_cancel(self):
        state,sent={'phase':'idle'},[]
        send=lambda _,e: sent.append(e['intent']) or True
        v=self.view('ENTRY_FEE')
        for _ in range(4):
            if sent:v['preparationReceipt']=dict(sent[-1],status='UNKNOWN')
            advance(state,v,send)
        self.assertEqual(len(sent),3)
        self.assertEqual(state['phase'],'stopped')
    def test_loading_waits_and_auction_is_not_cancelled(self):
        state={'phase':'idle'}
        self.assertTrue(advance(state,self.view('LOADING'),None))
        self.assertFalse(advance(state,self.view('AUCTION_READY'),None))
