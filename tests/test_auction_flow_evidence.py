import copy
import unittest
from unittest.mock import Mock, patch, PropertyMock
import numpy as np
from auction_flow_evidence import AuctionFlowEvidence, AuctionEvidencePersistence
from current_match import CurrentMatch
from vision_pipeline import NTEVisionPipeline

class FlowEvidenceTests(unittest.TestCase):
    def test_bid_dialog_is_not_recorded_as_intel(self):
        f=AuctionFlowEvidence();f.scene('IN_AUCTION','0','a')
        rows=[([[400,300],[600,300],[600,350],[400,350]],'请输入你愿意出的价格',.99)]
        self.assertFalse(f.intel(rows,1000,800,'1',1));self.assertEqual(f.data['intel'],[])

    def test_manual_navigation_is_labelled_and_never_starts_auction_ocr(self):
        from keyboard_auction_pipeline import KeyboardAuctionPipeline
        p=KeyboardAuctionPipeline();p.recognition_mode_provider=lambda:'manual'
        route={'scene':'OPEN_WORLD','generation':1,'confirmed':True}
        with patch.object(p,'_classify_scene_fast',return_value=route),patch.object(p,'_ensure_ocr') as ocr:
            ctx=p.process_frame(np.zeros((1080,1920,3),np.uint8))
            self.assertEqual(ctx['recognitionMode'],'manual');ocr.assert_not_called()
        p._navigation_executor.shutdown(wait=True)

    def test_settlement_shapes_do_not_call_catalog_or_ocr(self):
        from settlement_shape_observation import observe_settlement_shapes
        # A synthetic colored grid-aligned card exercises morphology and rarity.
        frame=np.zeros((1080,1920,3),np.uint8)
        frame[215:325,1316:1426]=(25,110,180)
        slots=observe_settlement_shapes(frame)
        self.assertTrue(slots)
        self.assertTrue(all(s['identifiedName'] is None for s in slots))

    def test_background_navigation_cannot_overwrite_a_new_scene(self):
        from concurrent.futures import Future
        from keyboard_auction_pipeline import KeyboardAuctionPipeline
        p=KeyboardAuctionPipeline()
        p._navigation_future=Future();p._navigation_future.set_result([([], '珊瑚场',1)])
        p._navigation_request=('AUCTION_LOBBY','0',1,False,None)
        with patch.object(p,'_apply_lobby_loadout') as apply:
            p._finish_navigation_read({'scene':'IN_AUCTION','generation':2})
            apply.assert_not_called()
        p._navigation_future=Future();p._navigation_future.set_result([([], '已使用',1)])
        p._navigation_request=('TOOL_REPLENISH','0',1,False,None)
        p.flow_evidence.scene('IN_AUCTION','1','new')
        p._finish_navigation_read({'scene':'IN_AUCTION','generation':2})
        self.assertEqual(p.flow_evidence.data['replenishment'],'UNOBSERVED')
        self.assertTrue(p.flow_evidence.data['priorMatchActivity'])
        p._navigation_executor.shutdown(wait=True)

    def test_previous_restock_and_postmatch_restock_have_different_owners(self):
        f=AuctionFlowEvidence()
        f.scene('TOOL_REPLENISH','0','draft-before')
        f.replenish([([], '已使用',1)],'1')
        f.scene('AUCTION_LOADING','2','match-a')
        f.scene('IN_AUCTION','3','match-a')
        self.assertEqual(f.data['replenishment'],'UNOBSERVED')
        self.assertTrue(f.data['priorMatchActivity'])
        f.scene('SETTLEMENT','4','match-a')
        f.scene('AUCTION_LOADING','5','match-next')
        f.scene('TOOL_REPLENISH','6','match-next')
        f.replenish([([], '大型鉴定仪器已使用',1)],'7')
        self.assertEqual(f.data['ownerMatchId'],'match-a')
        self.assertEqual(f.data['replenishment'],'NEEDS_REPLENISHMENT')
        f.replenish([([], '是否一键补全？',1)],'8')
        f.scene('AUCTION_LOBBY','9','match-next')
        self.assertEqual(f.data['replenishment'],'CONFIRMATION_SEEN')
        f.scene('IN_AUCTION','10','match-next')
        self.assertEqual(f.data['ownerMatchId'],'match-next')
        self.assertEqual(f.data['intel'],[])

    def test_aborted_loading_does_not_create_a_match(self):
        f=AuctionFlowEvidence();f.scene('AUCTION_LOADING','0','a');f.scene('OPEN_WORLD','1','a')
        self.assertIsNone(f.data)
        self.assertIn('LOAD_ABORTED',[x['scene'] for x in f.before_flow])

    def test_semantic_dedup_and_snapshot_independence(self):
        f=AuctionFlowEvidence();f.scene('IN_AUCTION','0','a')
        f.add('intel',{'lines':[{'text':'展示5件','confidence':.9}]},'1',2)
        f.add('intel',{'lines':[{'text':'展示5件','confidence':.95}]},'2',2)
        self.assertEqual(len(f.data['intel']),1)
        snap=f.snapshot();snap['intel'].clear()
        self.assertEqual(len(f.data['intel']),1)
        match=CurrentMatch();match.id='a';match.apply_facts({'auctionEvidence':f.snapshot()})
        self.assertEqual(match.to_canonical()['auctionEvidence']['ownerMatchId'],'a')

    def test_postmatch_persistence_targets_old_owner_once(self):
        store=Mock();persist=AuctionEvidencePersistence(store)
        evidence={'ownerMatchId':'old','hasReturned':True,'flow':[{'scene':'TOOL_REPLENISH'}]}
        self.assertTrue(persist.save(evidence));self.assertFalse(persist.save(copy.deepcopy(evidence)))
        self.assertEqual(store.update_record_transactional.call_args.args[0],'old')

    def test_partial_digit_batch_gets_missing_seats_from_panel(self):
        p=NTEVisionPipeline();p.current_context['round']=2;p._seat_round=2
        # Coordinates relative to the production panel crop at 1920x1080.
        def row(text,x,y):return ([[x-38-40,y-129-16],[x-38+40,y-129-16],[x-38+40,y-129+16],[x-38-40,y-129+16]],text,.99)
        rows=[row('1,222,222',315,267),row('0',315,426),row('555,555',315,587),row('666,666',315,748)]
        with patch.object(NTEVisionPipeline,'ocr',new_callable=PropertyMock,return_value=lambda crop:(rows,None)):
            for _ in range(2):p._handle_seat_binding_tier(np.zeros((1080,1920,3),np.uint8),1920,1080,[1222222,None,555555,None],True)
        self.assertEqual(p._slot_cur_bids[4],666666)

if __name__=='__main__':unittest.main()
