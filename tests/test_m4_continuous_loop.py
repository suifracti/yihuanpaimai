"""Continuous sequencing only; uses the existing bid/collection/Host contracts."""
import unittest
from unittest.mock import patch
from domain_action_session import advance_live_domain_loop as advance, fresh_live_domain_state


class ContinuousLoopTests(unittest.TestCase):
    def test_saved_capture_can_return_while_analysis_is_aligning_and_lobby_counts_once(self):
        import main
        from types import SimpleNamespace
        from unittest import mock
        cap=SimpleNamespace(_running=False,_scroll_count=13,
            presentation_payload=lambda:dict(state='ALIGNING',segmentCount=47,coverageStatus='COVERAGE_UNPROVEN',stopAvailable=False),
            source=SimpleNamespace(intake=SimpleNamespace(_binding=dict(recordStableKey='finished'),_processing_binding=None)))
        state=dict(fresh_live_domain_state(),phase='collecting',settledMatch='finished')
        with mock.patch.multiple(main,CURRENT_MATCH=SimpleNamespace(facts={},id='finished'),
                _NATIVE_WAREHOUSE_SOURCE_COORDINATOR=cap,_LIVE_DOMAIN_LOOP=state,
                _NATIVE_DOMAIN_ACTION_BOOT_ID='boot',CONFIG={},LATEST_PAYLOAD={}), \
             mock.patch.object(main,'_game_is_foreground',return_value=True):
            data=dict(round=4,sourceMatchGeneration=2,factsRevision=1,matchId='finished',
                observationSessionId='obs',target=dict(targetHwnd=1,targetPid=2,identity=dict(ProcessInstanceToken=3)))
            view=main._live_loop_view(data,'SETTLEMENT',None)
            self.assertTrue(view['collectionFinished'],'SAVED_ORIGINALS_BLOCKED_BY_BACKGROUND_ANALYSIS')
            self.assertNotEqual(view['coverageStatus'],'COMPLETE')
            lobby=main._live_loop_view(data,'LOBBY',200000)
            self.assertTrue(lobby['collectionFinished'])
            self.assertEqual(lobby['captureRecordKey'],'finished')
            sent=[];send=lambda _,e:sent.append(e) or True
            advance(state,lobby,send)
            self.assertEqual(state['matchesDone'],1)
            self.assertEqual(state['completedRuns'][0]['returnedBy'],'OBSERVED_LOBBY')
            advance(state,lobby,send);self.assertEqual(state['matchesDone'],1)

    def view(self, scene, match='match-1', round=1, **extra):
        return dict(publishedScene=scene, mode='bid', foreground=True, userConfirmed=True,
            engine=dict(matchId=match,matchGeneration=2,observationSessionId='obs',round=round,factsRevision=1),
            nowNs=1_000_000,nowMs=1,deadlineNs=999_000_000,deadlineMs=999,currentFunds=200000,
            minimumFunds=100000,window=dict(hwnd=1,pid=2,processInstanceToken=3,focusEpoch=0),
            approvalId='approved',bootId='boot',leaseId='lease',**extra)

    def test_three_matches_round_reentry_collection_and_both_modes(self):
        state, sent = fresh_live_domain_state(), []
        def bid(state,view,send):
            state.update(phase='bid_dispatched',bidIntentId='b'+str(view['engine']),
                bidRound=[view['engine'][k] for k in ('matchId','matchGeneration','round')])
            sent.append('Bid')
            return state
        def send(_,envelope): sent.append(envelope['intent']['kind']); return True
        with patch('domain_action_session._dispatch_live_bid',side_effect=bid):
            for n in range(3):
                match='match-'+str(n)
                mode='observe' if n==1 else 'bid'
                v=self.view('AUCTION',match,1);v['mode']=mode
                advance(state,v,send)
                if mode=='bid':
                    advance(state,self.view('AUCTION',match,1,bidReceipt=dict(intentId=state['bidIntentId'],status='CONFIRMED')),send)
                    self.assertEqual(state['phase'],'round_done')
                    advance(state,self.view('AUCTION',match,2),send)
                    self.assertEqual(state['phase'],'bid_dispatched')
                v=self.view('SETTLEMENT',match,2,collectionFinished=False)
                if state.get('bidIntentId'):v['bidReceipt']=dict(intentId=state['bidIntentId'],status='CONFIRMED')
                count=len(sent);advance(state,v,send)
                self.assertEqual(state['phase'],'collecting');self.assertEqual(len(sent),count)
                v.update(collectionFinished=True,coverageStatus='PARTIAL')
                advance(state,v,send); self.assertEqual(sent[-1],'ReturnLobby')
                v=self.view('LOBBY',match,0,sessionReceipt=dict(intentId=state['returnIntentId'],status='CONFIRMED'))
                advance(state,v,send);self.assertEqual(state['matchesDone'],n+1)
                self.assertEqual(sent[-1],'StartNextMatch')
                v=self.view('ENTRY_FEE',match,0,sessionReceipt=dict(intentId=state['startIntentId'],status='CONFIRMED'),
                    instruments=dict(refillCost=5000))
                advance(state,v,send);self.assertEqual(sent[-1],'ConfirmEntryFee')
                v=self.view('LOBBY',match,0,preparationReceipt=dict(intentId=state['preparationIntent']['intentId'],status='CONFIRMED'))
                before=len(sent);advance(state,v,send);self.assertEqual(len(sent),before)
        self.assertEqual(sent.count('Bid'),4)  # Pure observation used no instruments or bids.
        self.assertEqual(len(state['completedMatches']),3)

    def test_unknown_bid_stops_but_unknown_entry_fee_is_not_resent(self):
        sent=[];send=lambda _,e:sent.append(e) or True
        state=dict(fresh_live_domain_state(),phase='bid_dispatched',bidIntentId='bid')
        advance(state,self.view('AUCTION',bidReceipt=dict(intentId='bid',status='UNKNOWN')),send)
        self.assertEqual(state['phase'],'stopped');self.assertEqual(sent,[])
        state=dict(fresh_live_domain_state(),phase='entry_dispatched',preparationIntent=dict(intentId='fee'))
        v=self.view('ENTRY_FEE',round=0,preparationReceipt=dict(intentId='fee',status='UNKNOWN'),instruments=dict(refillCost=5000))
        advance(state,v,send);advance(state,v,send)
        self.assertEqual(state['phase'],'entry_unknown');self.assertEqual(sent,[])

    def test_loading_and_no_frames_have_no_total_deadline(self):
        # Real run-1 briefly showed AUCTION/round 0 before returning to the
        # matching lobby. A paid entry must not become another Start action.
        paid=dict(fresh_live_domain_state(),phase='entry_paid')
        clicks=[]
        advance(paid,self.view('AUCTION',round=0),lambda _,e: clicks.append(e) or True)
        advance(paid,self.view('LOBBY',round=0),lambda _,e: clicks.append(e) or True)
        self.assertEqual(paid['phase'],'entry_paid')
        self.assertEqual(clicks,[])
        state=fresh_live_domain_state()
        for now in (1,999_000_000_000,999_999_000_000_000):
            v=self.view(None);v['nowNs']=now;advance(state,v,lambda *_:False)
        self.assertNotEqual(state['phase'],'stopped')
        v=self.view('ENTRY_FEE',instruments={});v['nowNs']=1
        advance(state,v,lambda *_:False);v['nowNs']=91_000_000_002;advance(state,v,lambda *_:False)
        self.assertEqual(state['reason'],'SCENE_NO_PROGRESS_TIMEOUT')
