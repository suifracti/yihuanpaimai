import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import numpy as np
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from warehouse_capture_session import WarehouseCaptureSession
from warehouse_support_frame import stationary_support_proof
from test_warehouse_reconstruction_v1 import ScriptedFrames, ScriptedObserver, RecordingScroll, _obs, _verified_down


class SupportFrameTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=SettlementEvidenceStoreV2(self.root)
        self.image=np.random.default_rng(21).integers(20,220,(240,300,3),dtype=np.uint8)
        self.second=self.image.copy()
        self.second[::5,::5,0]+=1
        self.driver=RecordingScroll()

    def session(self, frames, states, **kwargs):
        return WarehouseCaptureSession(frame_provider=ScriptedFrames(frames),
            scene_validator=kwargs.pop('scene_validator',lambda raw:{'isSettlement':True,'stable':True,'recordStableKey':'support_case'}),
            observer=ScriptedObserver([_obs(s, change='CHANGED') for s in states]),
            scroll_requester=self.driver,store=self.store,already_cropped=True,
            aligner=_verified_down,top_support_attempts=1,
            clock=kwargs.pop('clock',lambda:0.0),idle=kwargs.pop('idle',lambda dt:None),**kwargs)

    def test_stationary_proof_requires_distinct_registered_texture(self):
        proof=stationary_support_proof(self.image,self.second)
        self.assertTrue(proof['identitySupportVerified'])
        self.assertFalse(proof['progressionVerified'])
        for bad in [self.image.copy(),np.roll(self.image,15,axis=0),self.image[:,::-1],self.image[:100]]:
            self.assertIsNone(stationary_support_proof(self.image,bad))
        flat=np.zeros((100,100,3),np.uint8)
        self.assertIsNone(stationary_support_proof(flat,flat+1))

    def test_no_scroll_collects_two_real_blobs_without_input(self):
        processor=Mock()
        processor.readonly_snapshot.return_value={}
        session=self.session([self.image,self.second],['NO_SCROLL','NO_SCROLL'],reconstruction_factory=lambda key:processor)
        result=session.start()
        self.assertEqual(result['coverageStatus'],'COMPLETE')
        self.assertEqual(len(result['savedDescriptors']),2)
        self.assertEqual(processor.accept_segment.call_count,2)
        proof=processor.accept_segment.call_args.args[4]
        self.assertFalse(proof['progressionVerified'])
        self.assertEqual(len(list((self.root/'evidence').rglob('*.png'))),2)
        self.assertEqual(session._scroll_request_count,0)

    def test_exact_duplicate_does_not_add_a_vote(self):
        result=self.session([self.image,self.image],['NO_SCROLL','NO_SCROLL']).start()
        self.assertEqual(len(result['savedDescriptors']),1)

    def test_top_support_does_not_prove_bottom(self):
        session=self.session([self.image,self.second],['TOP','TOP'],max_steps=0)
        result=session.start()
        self.assertEqual(len(result['savedDescriptors']),2)
        self.assertNotEqual(result['coverageStatus'],'COMPLETE')
        self.assertEqual(session._scroll_request_count,0)

    def test_movement_during_support_is_consumed_without_extra_wheel(self):
        session=self.session([self.image,np.roll(self.image,-40,axis=0)],['TOP','BOTTOM'])
        result=session.start()
        self.assertEqual(result['coverageStatus'],'COMPLETE')
        self.assertEqual(len(result['savedDescriptors']),2)
        self.assertEqual(session._scroll_request_count,0)

    def test_deadline_stops_before_second_frame_or_input(self):
        clock=[0.0]
        frames=ScriptedFrames([self.image,self.second])
        session=self.session([self.image,self.second],['TOP','TOP'],timeout_s=0.1,
            clock=lambda:clock[0],idle=lambda dt:clock.__setitem__(0,clock[0]+dt))
        session._frame_provider=frames
        result=session.start()
        self.assertEqual(result['terminationReason'],'TIMEOUT')
        self.assertEqual(frames.captures,1)
        self.assertEqual(session._scroll_request_count,0)

    def test_cross_match_support_aborts_without_second_write(self):
        keys=iter(['support_case','other_case'])
        session=self.session([self.image,self.second],['TOP','TOP'],
            scene_validator=lambda raw:{'isSettlement':True,'stable':True,'recordStableKey':next(keys)})
        result=session.start()
        self.assertEqual(result['terminationReason'],'STABLE_KEY_CHANGED')
        self.assertEqual(len(result['savedDescriptors']),1)

    def test_user_stop_during_passive_wait_preserves_first_frame(self):
        session=self.session([self.image,self.second],['TOP','TOP'])
        session._idle=lambda dt:session.stop()
        result=session.start()
        self.assertEqual(result['terminationReason'],'USER_STOP')
        self.assertEqual(len(result['savedDescriptors']),1)
        self.assertEqual(session._scroll_request_count,0)
