import copy
import json
from pathlib import Path
import unittest

from tools.audit_warehouse_review_packet import audit

ROOT = Path(__file__).resolve().parents[1]


class WarehouseReferenceScopeTests(unittest.TestCase):
    def setUp(self):
        self.packet = json.loads((ROOT / 'tests/fixtures/warehouse_grid_bounds/review_packet_visible.json').read_text(encoding='utf-8'))
        self.reference = json.loads((ROOT / 'assets/items/video_ground_truth_reference_134043_visible.json').read_text(encoding='utf-8'))

    def test_real_visible_packet_keeps_identity_and_coverage_gaps(self):
        result = audit(self.packet, self.reference)
        self.assertEqual(result['exactGeometryCount'], 17)
        self.assertEqual(result['confirmedCorrectCount'], 14)
        self.assertEqual(len(result['unconfirmedUnits']), 3)
        self.assertFalse(result['wholeWarehouseAcceptance'])

    def test_perfect_visible_subset_cannot_prove_whole_warehouse(self):
        self.packet['reviewUnits'] = self.packet['reviewUnits'][:1]
        self.reference['items'] = [self.reference['items'][-1]]
        self.packet['warehouseCoverage']['status'] = 'COMPLETE'
        result = audit(self.packet, self.reference)
        self.assertTrue(result['visibleIdentityPass'])
        self.assertFalse(result['wholeWarehouseAcceptance'])

    def test_whole_reference_requires_complete_observed_coverage(self):
        self.packet['reviewUnits'] = self.packet['reviewUnits'][:1]
        self.reference['items'] = [self.reference['items'][-1]]
        self.reference['metadata']['annotationScope'] = 'WHOLE_WAREHOUSE'
        self.assertFalse(audit(self.packet, self.reference)['wholeWarehouseAcceptance'])
        self.packet['warehouseCoverage']['status'] = 'COMPLETE'
        self.assertTrue(audit(self.packet, self.reference)['wholeWarehouseAcceptance'])

    def test_duplicate_regions_and_wrong_match_are_not_accepted(self):
        self.packet['reviewUnits'].append(copy.deepcopy(self.packet['reviewUnits'][0]))
        result = audit(self.packet, self.reference)
        self.assertFalse(result['visibleGeometryPass'])
        self.assertEqual(len(result['duplicateUnits']), 1)
        self.packet['recordStableKey'] = 'different_match'
        with self.assertRaises(ValueError):
            audit(self.packet, self.reference)

    def test_invalid_source_binding_and_empty_reference_are_rejected(self):
        self.reference['items'][0]['sourceScreenshotSha256'] = '0' * 64
        with self.assertRaises(ValueError):
            audit(self.packet, self.reference)
        self.reference['items'] = []
        with self.assertRaises(ValueError):
            audit(self.packet, self.reference)
