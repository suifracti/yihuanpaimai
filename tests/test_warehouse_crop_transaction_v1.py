"""Production crop provenance and failure recovery; all files are isolated."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core')]
import cv2
import numpy as np
import warehouse_capture_host as capture
from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7


class CropTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.blobs = []
        for color in [(0, 0, 255), (0, 255, 0)]:
            ok, encoded = cv2.imencode('.png', np.full((100, 100, 3), color, dtype=np.uint8))
            self.assertTrue(ok)
            raw = encoded.tobytes()
            digest = hashlib.sha256(raw).hexdigest()
            p = self.root / 'evidence' / 'settlement_v2' / 'blobs' / digest[:2] / (digest + '.png')
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
            self.blobs.append((digest, p, raw))
        self.store = CanonicalHistoryStore(str(self.root / 'history' / 'history.json'))
        rec = build_canonical_match_record_v7(match_id='crop_case', played_at='2026-09-12T07:00:00Z',
                                            lifecycle_status='DRAFT', source='live_capture', environment={})
        rec['settlement']['isSettled'] = True
        self.store.persist_record_transactional(rec, is_finalized=False)
        self.host = capture.WarehouseCaptureHost(history_store_factory=lambda: self.store)
        self.assertIsNotNone(self.host.persist_warehouse_occupancy_and_review(self.packet(0)))
        self.crops = [self.root / 'crops' / ('crop_case_unit_%d.png' % i) for i in range(2)]
        self.originals = [p.read_bytes() for p in self.crops]
        self.history_before = Path(self.store.db_path).read_bytes()

    def packet(self, blob_index):
        digest = self.blobs[blob_index][0]
        return {'recordStableKey': 'crop_case', 'capturedAt': '2026-09-12T07:00:00Z',
                'segments': [{'evidenceId': 'obs', 'sha256': digest}],
                'reviewUnits': [
                    {'reviewUnitId': 'unit_%d' % i, 'bbox': bbox,
                     'observations': [{'evidenceId': 'obs', 'sha256': digest, 'bbox': bbox, 'status': 'FULL'}]}
                    for i, bbox in enumerate(([10, 10, 40, 40], [50, 50, 90, 90]))]}

    def assert_original_state(self):
        self.assertEqual(Path(self.store.db_path).read_bytes(), self.history_before)
        self.assertEqual([p.read_bytes() for p in self.crops], self.originals)

    def test_legacy_without_source_binding_is_recut(self):
        for observations in ([], [{'sha256': ''}]):
            with self.subTest(observations=observations):
                units = copy.deepcopy(self.store.get_record('crop_case')['settlement']['reviewUnits'])
                for u in units:
                    u['observations'] = observations
                self.assertIsNotNone(self.store.persist_warehouse_evidence('crop_case', review_units=units))
                (self.root / 'crops' / '.crop_cache.json').unlink(missing_ok=True)
                next_blob = 1 if self.crops[0].read_bytes() == self.originals[0] else 0
                before = self.crops[0].read_bytes()
                self.assertIsNotNone(self.host.persist_warehouse_occupancy_and_review(self.packet(next_blob)))
                self.assertNotEqual(self.crops[0].read_bytes(), before)
                cached = json.loads((self.root / 'crops' / '.crop_cache.json').read_text())
                self.assertEqual(cached['crop_case_unit_0']['blobSha256'], self.blobs[next_blob][0])

    def test_backup_read_failure_aborts_before_persist_or_overwrite(self):
        original_read = Path.read_bytes
        def read(path):
            if path == self.crops[1]:
                raise PermissionError('backup unavailable')
            return original_read(path)
        with patch.object(Path, 'read_bytes', read), patch.object(self.store, 'persist_warehouse_evidence') as persist:
            self.assertIsNone(self.host.persist_warehouse_occupancy_and_review(self.packet(1)))
            persist.assert_not_called()
        self.assert_original_state()

    def test_source_hash_mismatch_rejected_even_on_cache_hit(self):
        self.blobs[0][1].write_bytes(self.blobs[1][2])
        self.assertIsNone(self.host.persist_warehouse_occupancy_and_review(self.packet(0)))
        self.assert_original_state()

    def test_source_hash_mismatch_rejected_on_cache_miss(self):
        self.blobs[1][1].write_bytes(self.blobs[0][2])
        self.assertIsNone(self.host.persist_warehouse_occupancy_and_review(self.packet(1)))
        self.assert_original_state()

    def test_partial_replace_failure_restores_all_old_crops(self):
        real_replace = capture.os.replace
        def replace(src, dst):
            if Path(dst) == self.crops[1] and Path(src).name == self.crops[1].name:
                raise OSError('second replacement failed')
            return real_replace(src, dst)
        with patch.object(capture.os, 'replace', replace), patch.object(self.store, 'persist_warehouse_evidence') as persist:
            self.assertIsNone(self.host.persist_warehouse_occupancy_and_review(self.packet(1)))
            persist.assert_not_called()
        self.assert_original_state()
        self.assertFalse(list((self.root / 'crops').glob('.staging_*')))

    def test_failed_recovery_is_reported_and_backups_survive(self):
        real_replace = capture.os.replace
        def replace(src, dst):
            if Path(dst) == self.crops[0] and Path(src).name.startswith('.restore_'):
                raise PermissionError('recovery target unavailable')
            return real_replace(src, dst)
        with patch.object(capture.os, 'replace', replace), \
             patch.object(self.store, 'persist_warehouse_evidence', side_effect=OSError('history unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'recovery') as caught:
                self.host.persist_warehouse_occupancy_and_review(self.packet(1))
        recovery_dir = caught.exception.recovery_dir
        self.assertTrue(recovery_dir.is_dir())
        manifest = json.loads((recovery_dir / 'rollback.json').read_text())
        self.assertEqual(manifest['recordId'], 'crop_case')
        for entry, original in zip(manifest['files'], self.originals):
            backup = recovery_dir / entry['backup']
            self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(Path(self.store.db_path).read_bytes(), self.history_before)
        # Restoration continues for the other crop even when one restoration fails.
        self.assertEqual(self.crops[1].read_bytes(), self.originals[1])

    def test_background_capture_reports_failed_recovery(self):
        error = capture.WarehouseCropRecoveryError(self.root, ['restore unavailable'])
        self.host.set_occupancy_sink(lambda occupancy: None)
        with patch.object(self.host, '_persist_draft_occupancy', side_effect=error):
            self.host._finish({'coverageStatus': 'COMPLETE', 'segmentCount': 1}, self.packet(0))
        presentation = self.host._presentation.to_payload()
        self.assertEqual(presentation['state'], 'ERROR')
        self.assertEqual(presentation['terminationReason'], 'CROP_RECOVERY_REQUIRED')
        self.assertIn('恢复未完成', presentation['message'])


if __name__ == '__main__':
    unittest.main()
