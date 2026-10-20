import unittest
from instrument_restock import advance


class InstrumentRestockTests(unittest.TestCase):
    def view(self, scene='LOBBY', **extra):
        return dict(publishedScene=scene, currentFunds=200000,
            engine=dict(matchId='old', matchGeneration=3, round=1, factsRevision=0, observationSessionId='obs'),
            window=dict(hwnd=1, pid=2, processInstanceToken=3, focusEpoch=0),
            nowNs=100, approvalId='user', bootId='boot', **extra)

    def test_refill_confirm_close_then_ready_cost_recorded_once(self):
        state, sent = {'phase': 'idle'}, []
        send = lambda owner, envelope: sent.append(envelope['intent']) or True
        config = {'minimumFunds':100000, 'instrumentTargets':{'goldAverage':1}}
        self.assertFalse(advance(state,self.view(),send,config))
        for scene, inventory, expected in [
            ('TOOL_SETUP', dict(goldAverage=0,purpleCount=1,refillCost=5000),'RequestToolRefill'),
            ('TOOL_REFILL_CONFIRM',dict(refillCost=5000),'ConfirmToolRefill'),
            ('TOOL_SETUP',dict(goldAverage=1,purpleCount=1,refillCost=0),'CloseToolSetup')]:
            receipt=dict(sent[-1],status='CONFIRMED')
            self.assertFalse(advance(state,self.view(scene,instruments=inventory,preparationReceipt=receipt),send,config))
            self.assertEqual(sent[-1]['kind'],expected)
            self.assertEqual(sent[-1]['matchId'],'lobby-obs')
            self.assertEqual(sent[-1]['round'],0)
        view=self.view(preparationReceipt=dict(sent[-1],status='CONFIRMED'))
        self.assertTrue(advance(state,view,send,config))
        self.assertTrue(advance(state,view,send,config))
        self.assertEqual(state['restock']['spent'],5000)
        self.assertEqual(len(sent),4)

    def test_funds_floor_no_purchase_and_unknown_never_resends(self):
        for status in ['UNKNOWN','NOT_SENT']:
            s,sent={'phase':'idle'},[]
            send=lambda _,e:sent.append(e['intent']) or True
            advance(s,self.view(),send,{})
            v=self.view('TOOL_SETUP',preparationReceipt=dict(sent[-1],status=status),instruments={})
            advance(s,v,send,{})
            advance(s,v,send,{})
            self.assertEqual(s['phase'],'stopped')
            self.assertEqual(len(sent),1)
        s,sent={'phase':'idle'},[]
        send=lambda _,e:sent.append(e['intent']) or True
        advance(s,self.view(),send,{})
        v=self.view('TOOL_SETUP',instruments=dict(goldAverage=0,refillCost=150000),
                    preparationReceipt=dict(sent[-1],status='CONFIRMED'))
        advance(s,v,send,{})
        self.assertEqual(s['reason'],'INSTRUMENT_REFILL_WOULD_CROSS_FUNDS_FLOOR')
        self.assertEqual(len(sent),1)

    def test_stock_enough_no_refill_and_impossible_target_stops(self):
        for target,expected in [(1,'CloseToolSetup'),(2,None)]:
            s,sent={'phase':'idle'},[]
            send=lambda _,e:sent.append(e['intent']) or True
            config={'instrumentTargets':{'goldAverage':target}}
            advance(s,self.view(),send,config)
            v=self.view('TOOL_SETUP',instruments=dict(goldAverage=1,refillCost=0),
                        preparationReceipt=dict(sent[-1],status='CONFIRMED'))
            advance(s,v,send,config)
            if expected:self.assertEqual(sent[-1]['kind'],expected)
            else:self.assertEqual(s['phase'],'stopped')
