import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import cv2
import numpy as np
from test_settlement_review_v1 import TestSettlementReviewV1 as ReviewFixture, _persist_record_with_evidence
from settlement_review_file_originals import build_truth_evidence_v2


class MainImageSelectionTests(unittest.TestCase):
    setUp = ReviewFixture.setUp
    tearDown = ReviewFixture.tearDown

    def seed(self):
        key, _, _ = _persist_record_with_evidence(self.history_path, self.root)
        store = self.service._v2_store()
        main = store.save_original(record_stable_key=key, kind='main-settlement',
            image_bytes=cv2.imencode('.png', np.zeros((180, 320, 3), dtype=np.uint8))[1].tobytes())
        segment = store.save_original(record_stable_key=key, kind='warehouse-segment',
            image_bytes=cv2.imencode('.png', np.ones((60, 56, 3), dtype=np.uint8))[1].tobytes())
        return key, main, segment

    def test_save_keeps_main_reference_first_without_discarding_segments(self):
        key, main, segment = self.seed()
        evidence = build_truth_evidence_v2(record_id=key, existing=None,
            settlement={'actualTotal': 200000}, originals=[main, segment], observed_at='2026-09-05T12:00:00+00:00')
        self.assertEqual(evidence['evidenceReferences'][0]['sha256'], main['sha256'])
        self.assertEqual(len(evidence['fileOriginals']), 2)
        self.assertIn(segment['sha256'], [r['sha256'] for r in evidence['evidenceReferences']])

    def test_old_segment_first_record_displays_and_recognizes_same_main(self):
        key, main, segment = self.seed()
        refs = [{'uri': d['relativePath'], 'sha256': d['sha256']} for d in (segment, main)]
        self.store.update_record_transactional(key, {'settlement': {'truthEvidence': {'evidenceReferences': refs}}})
        with patch.object(self.service, '_run_recognizer', return_value=[]) as recognize, \
             patch('settlement_review.SettlementItemRecognizer.parse_settlement_ledger', return_value={}), \
             patch('settlement_review.get_global_catalog_candidate_resolver') as resolver:
            resolver.return_value.resolve_identity_evidence_for_hypotheses.return_value = []
            result = self.service.create_review_session(key)
        self.assertTrue(result['ok'])
        self.assertEqual(result['review']['screenshot']['sha256'], main['sha256'])
        self.assertEqual(recognize.call_args.args[0], Path(self.root) / main['relativePath'])

    def test_archived_clearer_main_and_identity_parent_stay_together(self):
        key, early, _ = self.seed()
        later = self.service._v2_store().save_original(record_stable_key=key, kind='main-settlement',
            image_bytes=cv2.imencode('.png', np.full((180, 320, 3), 80, dtype=np.uint8))[1].tobytes(),
            captured_at='2099-01-01T00:00:00+00:00')
        self.store.update_record_transactional(key, {'settlement': {'truthEvidence': {'fileOriginals': [later]}}})
        with patch.object(self.service, '_run_recognizer', return_value=[]) as recognize, \
             patch('settlement_review.SettlementItemRecognizer.parse_settlement_ledger', return_value={}), \
             patch('settlement_review.get_global_catalog_candidate_resolver') as resolver:
            resolver.return_value.resolve_identity_evidence_for_hypotheses.return_value = []
            result = self.service.create_review_session(key)
        self.assertTrue(result['ok'])
        self.assertEqual(result['review']['screenshot']['sha256'], later['sha256'])
        self.assertEqual(result['review']['screenshot']['evidenceId'], later['evidenceId'])
        self.assertEqual(recognize.call_args.args[0], Path(self.root) / later['relativePath'])
