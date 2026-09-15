import unittest
from pathlib import Path

import cv2
from test_settlement_review_v1 import TestSettlementReviewV1 as ReviewFixture, _make_frame


class MissingRecordWriteTests(unittest.TestCase):
    setUp = ReviewFixture.setUp
    tearDown = ReviewFixture.tearDown

    def files(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in Path(self.root).rglob('*') if p.is_file()}

    def test_import_missing_record_has_no_file_side_effects(self):
        image = Path(self.root) / 'input.png'
        cv2.imencode('.png', _make_frame())[1].tofile(str(image))
        before = self.files()
        for source in ('current', 'legacy'):
            with self.subTest(source=source):
                result = self.service.import_screenshot('missing', str(image), source)
                self.assertFalse(result['ok'])
                self.assertEqual(self.files(), before)

    def test_delete_missing_record_preserves_existing_evidence_index(self):
        store = self.service._v2_store()
        store.save_original(record_stable_key='missing', kind='main-settlement',
                            image_bytes=cv2.imencode('.png', _make_frame())[1].tobytes())
        before = self.files()
        for source in ('current', 'legacy'):
            with self.subTest(source=source):
                result = self.service.delete_imported_screenshot('missing', source)
                self.assertFalse(result['ok'])
                self.assertEqual(self.files(), before)
