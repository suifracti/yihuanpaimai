import copy
import unittest
from pathlib import Path
import cv2
from intel_card_source import card_source
from intel_card_evidence import IntelCardEvidenceExtractor
from current_match import CurrentMatch
from intel_evidence_presentation import intel_evidence_text


class IntelCardSourceTests(unittest.TestCase):
    def test_exact_leading_title_only_never_guesses_cost(self):
        for text in ('拍卖师公开情报 本局内所有金色品质藏品的平均价值为47,286。',
                     '拍 卖 师 公 开 情 报 随机展示2件藏品'):
            self.assertEqual(card_source(text)['kind'], 'AUCTIONEER_PUBLIC')
        for text in (None, '', '公开情报 本局', '拍卖师公幵情报 本局',
                     '金品均价仪器 本局内拍卖师公开情报', '非拍卖师公开情报 本局',
                     '拍卖师公开情报尚未获得', '拍卖师公开情报'):
            self.assertEqual(card_source(text)['kind'], 'UNKNOWN')

    def test_real_fast_ocr_distinguishes_same_value_cards_and_keeps_cache_provenance(self):
        root = Path(__file__).resolve().parents[1]
        frame = cv2.imread(str(root/'tests/fixtures/intel_card_evidence_v1/r3_viewport.png'))
        self.assertIsNotNone(frame)
        extractor = IntelCardEvidenceExtractor()
        first = extractor.extract_cards_fast(frame, frame_id='source-fixture-r3', known_round=3)
        second = extractor.extract_cards_fast(frame, frame_id='source-fixture-r3-cache', known_round=3)
        for ev, physical in ((first, True), (second, False)):
            rows = [o.to_dict() for o in ev.observations if o.field == 'goldAvg']
            self.assertEqual(len(rows), 2)
            self.assertEqual([o['value'] for o in rows], [47286, 47286])
            self.assertEqual([o['cardSource']['kind'] for o in rows], ['UNKNOWN', 'AUCTIONEER_PUBLIC'])
            self.assertEqual([o['is_physical_ocr'] for o in rows], [physical, physical])
            current = CurrentMatch()
            current.apply_facts({'intelObservations': rows, 'intelCost': 1200}, intent='confirm')
            saved = current.to_canonical()
            restored = CurrentMatch()
            restored.apply_facts(saved, intent='snapshot')
            self.assertEqual(restored.snapshot()['intelObservations'], rows)
            self.assertEqual(saved['costs']['intel'], 1200)
            self.assertEqual(saved['intelCardEvidence']['costClassification'], 'UNKNOWN')
            original = copy.deepcopy(saved)
            self.assertIn('读到拍卖师公开情报标题', intel_evidence_text(saved))
            self.assertEqual(saved, original)
