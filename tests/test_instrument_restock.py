import unittest
from instrument_restock import advance


class InstrumentRestockTests(unittest.TestCase):
    def test_background_lobby_dispatches_to_host_for_game_activation(self):
        state, sent = {'phase':'idle'}, []
        view = self.view()
        view['foreground'] = False
        advance(state,view,lambda _,e:sent.append(e) or True,{})
        self.assertEqual(sent[0]['intent']['kind'],'OpenToolSetup')
        self.assertEqual(sent[0]['intent']['window'],view['window'])

    def test_entry_confirmation_animation_does_not_restart_preflight(self):
        state={'phase':'idle','restock':{'ready':True,'step':4,'spent':5000}}
        sent=[]
        send=lambda _,e:sent.append(e) or True
        transient=self.view('AUCTION')
        transient['engine']['round']=0
        self.assertTrue(advance(state,transient,send,{}))
        self.assertTrue(advance(state,self.view('LOBBY'),send,{}))
        self.assertTrue(state['restock']['ready'])
        self.assertFalse(state['restock'].get('leftLobby',False))
        self.assertEqual(sent,[])
        actual=self.view('AUCTION')
        actual['engine']['round']=1
        advance(state,actual,send,{})
        advance(state,self.view('LOBBY'),send,{})
        self.assertEqual(sent[-1]['intent']['kind'],'OpenToolSetup')

    def test_default_group_browse_select_then_stock_and_close(self):
        state, sent = {'phase':'idle'}, []
        send=lambda _,e:sent.append(e['intent']) or True
        advance(state,self.view(),send,{})
        for scene,extra,kind in [
            ('TOOL_GROUPS',{},'BrowseToolGroups'),
            ('TOOL_GROUPS',{'advancedToolGroupVisible':True},'SelectToolGroup'),
            ('TOOL_SETUP',{'instruments':{'goldAverage':1,'purpleCount':1}},'CloseToolSetup')]:
            advance(state,self.view(scene,preparationReceipt=dict(sent[-1],status='CONFIRMED'),**extra),send,{})
            self.assertEqual(sent[-1]['kind'],kind)
        self.assertTrue(advance(state,self.view(preparationReceipt=dict(sent[-1],status='CONFIRMED')),send,{}))
        self.assertFalse(any(i['kind']=='ConfirmToolRefill' for i in sent))

    def test_group_navigation_is_bounded_and_unknown_waits_for_scene_progress(self):
        for scene,status,reason in [('TOOL_GROUPS','CONFIRMED','INSTRUMENT_ADVANCED_GROUP_NOT_FOUND'),
                                    ('AUCTION','UNKNOWN','INSTRUMENT_UNKNOWN')]:
            state,sent={'phase':'idle'},[]
            send=lambda _,e:sent.append(e['intent']) or True
            advance(state,self.view(),send,{})
            advance(state,self.view('TOOL_GROUPS',preparationReceipt=dict(sent[-1],status='CONFIRMED')),send,{})
            advance(state,self.view(scene,preparationReceipt=dict(sent[-1],status=status)),send,{})
            self.assertNotEqual(state['phase'],'stopped')
            self.assertEqual(state['reason'],reason)
            self.assertEqual(len(sent),2)

    def test_purchase_returns_to_lobby_then_rereads_stock_before_entry(self):
        state, sent = {'phase':'idle'}, []
        send = lambda _, e: sent.append(e['intent']) or True
        advance(state,self.view(),send,{})
        steps=[('TOOL_SETUP',dict(goldAverage=0,purpleCount=1,refillCost=5000),'RequestToolRefill'),
               ('TOOL_REFILL_CONFIRM',dict(refillCost=5000),'ConfirmToolRefill'),
               ('LOBBY',{},'OpenToolSetup'),
               ('TOOL_SETUP',dict(goldAverage=1,purpleCount=1,refillCost=0),'CloseToolSetup')]
        for scene,stock,expected in steps:
            receipt=dict(sent[-1],status='CONFIRMED')
            self.assertFalse(advance(state,self.view(scene,instruments=stock,preparationReceipt=receipt),send,{}))
            self.assertEqual(sent[-1]['kind'],expected)
            self.assertFalse(state['restock'].get('ready',False))
        self.assertTrue(advance(state,self.view(preparationReceipt=dict(sent[-1],status='CONFIRMED')),send,{}))
        self.assertEqual(state['restock']['spent'],5000)
        self.assertEqual(sum(i['kind']=='ConfirmToolRefill' for i in sent),1)

    def test_reopened_group_list_can_navigate_once_again_after_purchase(self):
        pending=dict(intentId='reopen',kind='OpenToolSetup',matchId='lobby-obs',matchGeneration=1,
            observationSessionId='obs',round=0)
        state={'phase':'restocking','restock':{'pending':pending,'browsed':True,'step':4,'spent':5000}}
        sent=[]
        advance(state,self.view('TOOL_GROUPS',preparationReceipt=dict(pending,status='CONFIRMED')),
                lambda _,e:sent.append(e) or True,{})
        self.assertEqual(sent[-1]['intent']['kind'],'BrowseToolGroups')
        self.assertEqual(state['restock']['spent'],5000)

    def view(self, scene='LOBBY', **extra):
        return dict(publishedScene=scene, currentFunds=200000, foreground=True,
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
            self.assertEqual(s['phase'],'restocking')
            self.assertEqual(len(sent),1)
        s,sent={'phase':'idle'},[]
        send=lambda _,e:sent.append(e['intent']) or True
        advance(s,self.view(),send,{})
        v=self.view('TOOL_SETUP',instruments=dict(goldAverage=0,purpleCount=1,refillCost=150000),
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
            else:self.assertEqual(s['phase'],'restocking')
