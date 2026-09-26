import unittest
from unittest.mock import patch
import numpy as np
from intel_card_evidence import IntelCardEvidenceExtractor
from current_match import CurrentMatch
from intel_evidence_record import intel_evidence_record
from intel_evidence_presentation import intel_evidence_text


class IntelCardReadingsTests(unittest.TestCase):
    def test_pending_verification_rereads_card_instead_of_replacing_with_empty_text(self):
        text = '拍卖师公开情报 本局内所有蓝色品质藏品的总数量为2件。'
        class Recognizer:
            def text_rec(self, crops):
                return [(text, .99) for _ in crops], 0
        extractor = IntelCardEvidenceExtractor(ocr_engine=Recognizer())
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with patch('intel_card_evidence.detect_card_boxes', return_value=[[0, 0, 100, 80]]), \
             patch.object(extractor, '_extract_text_lines_projected', return_value=[frame[:20, :100]]):
            extractor.extract_cards_fast(frame, frame_id='first', known_round=4, allow_detector_fallback=False)
            second = extractor.extract_cards_fast(frame, frame_id='second', known_round=4,
                pending_verify_fields=['blueCount'], allow_detector_fallback=False)
        self.assertEqual(second.cardReadings[0]['rawText'], text)
        self.assertTrue(second.cardReadings[0]['is_physical_ocr'])
        self.assertEqual([(o.field, o.value) for o in second.observations], [('blueCount', 2)])

    def test_non_numeric_full_card_survives_standard_extractor_and_history(self):
        text = '拍卖师公开情报 随机展示2件藏品'
        extractor = IntelCardEvidenceExtractor()
        with patch('intel_card_evidence.detect_card_boxes', return_value=[[0, 0, 100, 80]]), patch.object(extractor, '_ocr_text', return_value=text):
            ev = extractor.extract_stack(np.zeros((100, 120, 3), dtype=np.uint8), frame_id='synthetic-random-card')
        self.assertEqual(ev.observations, [])
        self.assertEqual(len(ev.cardReadings), 1)
        self.assertEqual(ev.cardReadings[0]['rawText'], text)
        self.assertEqual(ev.cardReadings[0]['cardSource']['kind'], 'AUCTIONEER_PUBLIC')
        current = CurrentMatch()
        current.apply_facts({'intelCardReadings': ev.to_dict()['cardReadings'], 'intelCost': 1200}, intent='confirm')
        self.assertIsNone(current.snapshot()['totalItems'])
        saved = current.to_canonical()
        restored = CurrentMatch()
        restored.apply_facts(saved, intent='snapshot')
        self.assertEqual(restored.snapshot()['intelCardReadings'], ev.cardReadings)
        self.assertEqual(saved['costs']['intel'], 1200)
        self.assertIn(text, intel_evidence_text(saved))
        self.assertIn('不作为新增事实', intel_evidence_text(saved))
        ev.to_dict()['cardReadings'][0]['cardBox'][0] = 500
        self.assertEqual(ev.cardReadings[0]['cardBox'][0], 0)
        restored.begin_next_match()
        self.assertEqual(restored.snapshot()['intelCardReadings'], [])

    def test_fast_path_keeps_unrouted_card_and_cache_marker(self):
        text = '拍卖师公开情报 随机展示2件藏品'
        extractor = IntelCardEvidenceExtractor()
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with patch('intel_card_evidence.detect_card_boxes', return_value=[[0, 0, 100, 80]]), patch.object(extractor, '_ocr_card_fast_projected', return_value=(text, [], True)) as ocr:
            first = extractor.extract_cards_fast(frame, frame_id='synthetic-a', known_round=1)
            second = extractor.extract_cards_fast(frame, frame_id='synthetic-b', known_round=1)
        self.assertEqual(ocr.call_count, 1)
        self.assertEqual(first.observations, [])
        self.assertEqual(second.observations, [])
        self.assertTrue(first.cardReadings[0]['is_physical_ocr'])
        self.assertFalse(second.cardReadings[0]['is_physical_ocr'])
        saved = intel_evidence_record({'intelCardReadings': second.cardReadings})
        self.assertIn('复用或来源待核实', intel_evidence_text({'intelCardEvidence': saved}))
