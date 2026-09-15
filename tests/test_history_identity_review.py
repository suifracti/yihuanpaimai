import copy
import unittest
import uuid
from pathlib import Path

from test_settlement_review_v1 import TestSettlementReviewV1 as ReviewFixture, _persist_record_with_evidence


class HistoryIdentityReviewTests(unittest.TestCase):
    setUp = ReviewFixture.setUp
    tearDown = ReviewFixture.tearDown

    def seed(self, draft=True):
        key, _, _ = _persist_record_with_evidence(self.history_path, self.root, match_id=uuid.uuid4().hex)
        if draft:
            self.store.update_record_transactional(key, {'lifecycleStatus': 'DRAFT',
                'settlement': {'winner': '秋星蔡02', 'acquired': None, 'verified': False}})
        return key

    def save(self, key, acquired=None):
        return self.service.save_reviewed_settlement(key, [], runtime_file_originals=[],
            identity_review={'winner': 'PLAYER_LOCAL', 'acquired': acquired})

    def test_review_preserves_unknown_and_original_evidence(self):
        key = self.seed()
        before = self.store.lookup(key)
        result = self.save(key)
        self.assertTrue(result['ok'], result)
        after = self.store.lookup(key)
        self.assertEqual(after['lifecycleStatus'], 'DRAFT')
        self.assertEqual(after['settlement']['winner'], 'PLAYER_LOCAL')
        self.assertIsNone(after['settlement']['acquired'])
        self.assertEqual(after['settlement']['truthEvidence'], before['settlement']['truthEvidence'])
        self.assertEqual(after['settlement']['identityReviews'][0]['before']['winner'], '秋星蔡02')
        self.assertEqual(after['settlement']['actualTotal'], before['settlement']['actualTotal'])

    def test_finalized_and_invalid_ownership_leave_disk_unchanged(self):
        key = self.seed(False)
        before = Path(self.history_path).read_bytes()
        self.assertFalse(self.save(key)['ok'])
        self.assertEqual(Path(self.history_path).read_bytes(), before)
        key = self.seed()
        before = Path(self.history_path).read_bytes()
        self.assertFalse(self.save(key, 'false')['ok'])
        self.assertEqual(Path(self.history_path).read_bytes(), before)

    def test_late_ocr_archive_does_not_replace_reviewed_identity(self):
        key = self.seed()
        stale = copy.deepcopy(self.store.lookup(key))
        self.assertTrue(self.save(key, False)['ok'])
        self.store.persist_record_transactional(stale, is_finalized=False, preserve_archive_sidecars=True)
        after = self.store.lookup(key)['settlement']
        self.assertEqual(after['winner'], 'PLAYER_LOCAL')
        self.assertIs(after['acquired'], False)
        self.assertEqual(len(after['identityReviews']), 1)
