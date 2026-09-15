import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
from test_settlement_review_v1 import TestSettlementReviewV1 as ReviewFixture, _make_frame, _persist_record_with_evidence


class ImportUnlinkTests(unittest.TestCase):
    setUp = ReviewFixture.setUp
    tearDown = ReviewFixture.tearDown

    def test_delete_preserves_canonical_and_captured_original_even_with_same_bytes(self):
        record_id, _, _ = _persist_record_with_evidence(self.history_path, self.root)
        raw = cv2.imencode('.png', _make_frame())[1].tobytes()
        store = self.service._v2_store()
        captured = store.save_original(record_stable_key=record_id, kind='main-settlement', image_bytes=raw)
        source = Path(self.root) / 'import.png'
        source.write_bytes(raw)
        imported = self.service.import_screenshot(record_id, str(source))
        self.assertTrue(imported['ok'])
        self.assertNotEqual(imported['evidence']['evidenceId'], captured['evidenceId'])
        before = Path(self.history_path).read_bytes()
        with patch.object(self.service, 'create_review_session', return_value={'ok': True}):
            self.assertTrue(self.service.delete_imported_screenshot(record_id)['ok'])
        self.assertEqual(Path(self.history_path).read_bytes(), before)
        self.assertEqual(store.list_record_evidence(record_id), [captured])
        self.assertEqual(store.load_original(captured), raw)
        self.assertEqual(store.load_original(imported['evidence']), raw)
        self.assertEqual(store.unlink_user_imports(record_id), 0)

    def test_unknown_legacy_origin_is_preserved(self):
        store = self.service._v2_store()
        desc = store.save_original(record_stable_key='old', kind='main-settlement',
                                   image_bytes=cv2.imencode('.png', _make_frame())[1].tobytes())
        desc.pop('evidenceOrigin')
        store._write_index('old', [desc])
        self.assertEqual(store.unlink_user_imports('old'), 0)
        self.assertEqual(store.list_record_evidence('old'), [desc])

    def test_index_failure_is_reported(self):
        record_id, _, _ = _persist_record_with_evidence(self.history_path, self.root)
        with patch('settlement_evidence_store_v2.SettlementEvidenceStoreV2.unlink_user_imports', side_effect=OSError('index unavailable')):
            result = self.service.delete_imported_screenshot(record_id)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'DELETE_FAILED')
