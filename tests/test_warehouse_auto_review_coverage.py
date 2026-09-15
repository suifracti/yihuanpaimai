import copy
import json
from pathlib import Path
import unittest

from warehouse_auto_confirmation import evaluate_auto_confirmation
from warehouse_identity_review import build_auto_identity_review_artifact


class AutoReviewCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / 'fixtures/warehouse_grid_bounds/review_packet_visible.json'
        cls.packet = json.loads(path.read_text(encoding='utf-8'))
        cls.units = evaluate_auto_confirmation(cls.packet['reviewUnits'], cls.packet['segments'])

    def test_real_partial_packet_keeps_partial_auto_summary(self):
        artifact = build_auto_identity_review_artifact(self.packet, self.units)
        self.assertEqual(artifact['warehouseCoverageStatus'], 'PARTIAL')
        self.assertEqual(artifact['identityResolution'], 'PARTIAL')
        self.assertEqual(len(artifact['resolvedItems']), 14)

    def test_all_visible_items_confirmed_does_not_resolve_missing_coverage(self):
        confirmed = [u for u in self.units if u['confirmationStatus'] == 'CONFIRMED']
        for coverage in ('PARTIAL', 'COVERAGE_UNPROVEN', 'COMPLETE'):
            with self.subTest(coverage=coverage):
                packet = {'recordStableKey': self.packet['recordStableKey'],
                          'segments': self.packet['segments'],
                          'warehouseCoverage': {'status': coverage}}
                artifact = build_auto_identity_review_artifact(packet, confirmed)
                self.assertEqual(artifact['reviewCompletion'], 'COMPLETE')
                self.assertEqual(artifact['warehouseCoverageStatus'], coverage)
                self.assertEqual(artifact['identityResolution'], 'RESOLVED' if coverage == 'COMPLETE' else 'PARTIAL')

    def test_absent_invalid_and_conflicting_coverage_fail_closed(self):
        confirmed = [u for u in self.units if u['confirmationStatus'] == 'CONFIRMED'][:1]
        cases = [({}, 'COVERAGE_UNPROVEN'),
                 ({'warehouseCoverage': None, 'warehouseCoverageStatus': 'COMPLETE'}, 'COVERAGE_UNPROVEN'),
                 ({'warehouseCoverage': {'status': 'bad'}}, 'COVERAGE_UNPROVEN'),
                 ({'warehouseCoverage': {'status': []}}, 'COVERAGE_UNPROVEN'),
                 ({'warehouseCoverage': {'status': 'PARTIAL'}, 'warehouseCoverageStatus': 'COMPLETE'}, 'PARTIAL'),
                 ({'warehouseCoverageStatus': 'PARTIAL'}, 'PARTIAL'),
                 ({'warehouseCoverageStatus': 'COMPLETE'}, 'COMPLETE')]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                packet = {'recordStableKey': self.packet['recordStableKey'], 'segments': self.packet['segments'], **fields}
                before = copy.deepcopy(packet)
                artifact = build_auto_identity_review_artifact(packet, confirmed)
                self.assertEqual(artifact['warehouseCoverageStatus'], expected)
                self.assertEqual(artifact['identityResolution'], 'RESOLVED' if expected == 'COMPLETE' else 'PARTIAL')
                self.assertEqual(packet, before)
