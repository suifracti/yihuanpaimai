"""A review bbox must select the same pixels in its immutable source image."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import cv2
import numpy as np
from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from warehouse_capture_host import WarehouseCaptureHost
from warehouse_reconstruction import WarehouseReconstructionProcessor
from warehouse_scrollbar_observation import warehouse_search_roi


class SourceCoordinatesTests(unittest.TestCase):
    def exercise(self, full_frame):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = np.zeros((1080, 1920, 3), dtype=np.uint8)
            x, y, right, bottom = warehouse_search_roi(1920, 1080)
            image[y+30:y+80, x+20:x+60] = (40, 120, 220)
            if not full_frame:
                image = image[y:bottom, x:right].copy()
                x, y = 0, 0
            blob_store = SettlementEvidenceStoreV2(root)
            descriptor = blob_store.save_original(record_stable_key='coordinate_case', kind='warehouse-segment',
                                                 image_bytes=cv2.imencode('.png', image)[1].tobytes())
            eid = descriptor['evidenceId']
            observation = {'observationId': 'obs_full', 'evidenceId': eid, 'sha256': descriptor['sha256'],
                           'sequenceIndex': 0, 'bbox': [20, 30, 60, 80], 'status': 'FULL'}
            unit = {'reviewUnitId': 'coordinate_unit', 'placementStatus': 'RESOLVED', 'visibility': 'FULL',
                    'worldAnchor': {'row': 0, 'col': 0}, 'footprint': {'widthCells': 1, 'heightCells': 1},
                    'physicalGroupId': 'group_0', 'geometryEvidenceStatus': 'EXACT',
                    'identityStatus': 'REVIEW_REQUIRED', 'selectedCatalogId': None,
                    'bestObservationId': 'obs_full', 'supportingTrackIds': ['track_0'],
                    'observations': [observation, dict(observation, observationId='obs_clipped', status='CLIPPED')],
                    'candidateStatus': 'NO_CANDIDATE', 'candidates': [], 'widthCandidates': [1],
                    'heightCandidates': [1], 'spanCandidates': [1]}
            physical = Mock()
            physical.snapshot.return_value = {'recordStableKey': 'coordinate_case', 'segments': [], 'tracks': []}
            resolver = Mock()
            resolver.resolve.return_value = [unit]
            processor = WarehouseReconstructionProcessor('coordinate_case', placement_resolver=resolver,
                physical_factory=lambda key: physical, observe_grid=lambda *a, **kw: {'grid': {'status': 'OK'}})
            result = processor.accept_segment(image, descriptor, 0, already_cropped=not full_frame)
            self.assertTrue(result['accepted'])
            processor.finalize({'recordStableKey': 'coordinate_case', 'coverageStatus': 'PARTIAL',
                                'segments': [{'evidenceId': eid, 'sequenceIndex': 0}]})
            packet = processor.packet_copy()
            self.assertIsNotNone(packet)
            expected_bbox = [x+20, y+30, x+60, y+80]
            for obs in packet['reviewUnits'][0]['observations']:
                self.assertEqual(obs['bbox'], expected_bbox)
            # Repeated packet construction does not apply the offset twice.
            self.assertEqual(processor.build_review_packet(), packet)
            self.assertEqual(unit['observations'][0]['bbox'], [20, 30, 60, 80])
            history = CanonicalHistoryStore(root / 'history/history.json')
            history.persist_record_transactional(build_canonical_match_record_v7(
                match_id='coordinate_case', played_at='2026-09-12T09:00:00Z',
                lifecycle_status='DRAFT', source='live_capture'), is_finalized=False)
            host = WarehouseCaptureHost(history_store_factory=lambda: history)
            self.assertIsNotNone(host.persist_warehouse_occupancy_and_review(packet))
            saved = history.lookup('coordinate_case')['settlement']['reviewUnits'][0]
            crop = cv2.imdecode(np.frombuffer((root / saved['cropPath']).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            self.assertTrue(np.array_equal(crop, image[y+30:y+80, x+20:x+60]))
            self.assertTrue(np.all(crop == (40, 120, 220)))

    def test_full_frame_packet_and_persisted_crop_use_source_coordinates(self):
        self.exercise(True)

    def test_roi_source_does_not_receive_an_extra_offset(self):
        self.exercise(False)

    def test_cropped_input_with_full_source_descriptor_is_rejected_before_seen(self):
        processor = WarehouseReconstructionProcessor('coordinate_case', placement_resolver=Mock())
        descriptor = {'recordStableKey': 'coordinate_case', 'evidenceId': 'e', 'sha256': 'a'*64,
                      'width': 1920, 'height': 1080}
        result = processor.accept_segment(np.zeros((300, 300, 3), np.uint8), descriptor, 0)
        self.assertEqual(result, {'accepted': False, 'reason': 'SOURCE_FRAME_SIZE_MISMATCH'})
        self.assertEqual(processor.readonly_snapshot()['processedCount'], 0)
