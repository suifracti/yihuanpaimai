import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
from recognition_mode import get_recognition_mode, set_recognition_mode
from seat_bid_observation import visible_seat_bids
from snapshot_recognizer import SingleFrameSnapshotRecognizer
from vision_pipeline import NTEVisionPipeline


class SessionRepairs(unittest.TestCase):
    def test_mode_persists_and_rejects_invalid_value(self):
        with tempfile.TemporaryDirectory() as root, patch('recognition_mode.resolve_runtime_data_root', return_value=Path(root)):
            self.assertEqual(get_recognition_mode(), 'manual')
            set_recognition_mode('auto')
            self.assertEqual(get_recognition_mode(), 'auto')
            with self.assertRaises(ValueError):
                set_recognition_mode('invalid')
            self.assertEqual(get_recognition_mode(), 'auto')
            set_recognition_mode('manual')
            self.assertEqual(get_recognition_mode(), 'manual')

    def test_manual_frame_never_starts_ocr(self):
        pipe = NTEVisionPipeline()
        pipe.recognition_mode_provider = lambda: 'manual'
        pipe._classify_scene_fast = Mock(return_value={'scene': 'UNKNOWN'})
        pipe._ocr_engine = Mock(side_effect=AssertionError('manual OCR'))
        result = pipe.process_frame(np.zeros((1080, 1920, 3), np.uint8))
        self.assertEqual(result['recognitionMode'], 'manual')
        pipe._ocr_engine.assert_not_called()

    def test_focused_snapshot_rejects_settlement_before_ocr(self):
        engine = Mock(side_effect=AssertionError('settlement auction OCR'))
        recognizer = SingleFrameSnapshotRecognizer(engine, focused=True, include_card_evidence=False)
        with patch('scene_anchors.settlement_title_visible', return_value=True):
            result = recognizer.process_frame(np.zeros((1080,1920,3),np.uint8))
        self.assertEqual(result['scene'], 'SETTLEMENT')
        self.assertEqual(result['appliedFacts'], {})
        engine.assert_not_called()

    def test_manual_mode_keeps_settlement_ocr(self):
        pipe = NTEVisionPipeline()
        pipe.recognition_mode_provider = lambda: 'manual'
        pipe._classify_scene_fast = Mock(return_value={'scene':'SETTLEMENT'})
        pipe._ocr_engine = Mock(return_value=([], None))
        pipe.process_frame(np.zeros((1080,1920,3),np.uint8), include_heavy_identity=False)
        pipe._ocr_engine.assert_called()

    def test_manual_display_does_not_override_capture_scene(self):
        import main
        with patch.object(main, 'LATEST_VISION_PAYLOAD', {'scene':'SETTLEMENT','isSettlement':True,'gameHwnd':123,'warehousePresent':True,'scrollState':'TOP'}), patch.object(main, 'LATEST_PAYLOAD', {'scene':'IN_AUCTION','isSettlement':False}):
            bindings = main.get_production_warehouse_bindings()
        self.assertTrue(bindings['isSettlement'])
        self.assertEqual(bindings['scrollState'], 'TOP')

    def test_bid_bands_ignore_history_and_other_numbers(self):
        def row(x,y,text,score=.99):
            return ([[x-20,y-5],[x+20,y-5],[x+20,y+5],[x-20,y+5]],text,score)
        bids = visible_seat_bids([row(315,267,'223333'),row(315,428,'114,514'),
            row(315,588,'152924'),row(315,315,'999999'),row(960,267,'999999'),
            row(315,750,'666'),row(315,750,'999999',.5)],1920,1080)
        self.assertEqual(bids,[223333,114514,152924,None])
