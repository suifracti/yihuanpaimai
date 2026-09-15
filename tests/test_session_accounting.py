import copy
import json
import unittest
from current_match import CurrentMatch
from canonical_match_record import build_canonical_match_record_v7
from session_accounting import receipt_amount, settlement_accounting


class SessionAccountingTests(unittest.TestCase):
    def record(self, acquired=True, receipt=3000):
        return {'environment': {'fieldCondition': 'welfare'},
                'costs': {'entry': 5000, 'intel': 1200, 'other': 300, 'futureIncrementalCost': 700, 'total': 7200},
                'settlement': {'acquired': acquired, 'actualTotal': 60040, 'clearingPrice': 40000,
                               'realizedProfit': 999999, 'welfare': {'received': receipt, 'expected': 90000}}}

    def test_self_other_unknown_and_no_double_deduction(self):
        for acquired, expected in ((True, 16540), (False, -3500), (None, None)):
            record = self.record(acquired)
            original = copy.deepcopy(record)
            result = settlement_accounting(record)
            self.assertEqual(result['sessionNet'], expected)
            self.assertEqual(result['paidCosts'], 6500)
            self.assertEqual(record, original)
        record = self.record(False)
        record['settlement']['actualTotal'] = record['settlement']['clearingPrice'] = None
        self.assertEqual(settlement_accounting(record)['sessionNet'], -3500)

    def test_unknown_receipt_costs_and_expected_cannot_be_actual(self):
        self.assertIsNone(settlement_accounting(self.record(receipt=None))['sessionNet'])
        self.assertEqual(settlement_accounting(self.record(receipt=0))['sessionNet'], 13540)
        for key in ('entry', 'intel', 'other'):
            record = self.record()
            record['costs'][key] = None
            self.assertIsNone(settlement_accounting(record)['sessionNet'])
        record = self.record(receipt=None)
        record['environment']['fieldCondition'] = 'standard'
        self.assertEqual(settlement_accounting(record)['sessionNet'], 13540)
        record['environment']['fieldCondition'] = 'unknown'
        self.assertIsNone(settlement_accounting(record)['sessionNet'])

    def test_receipt_persistence_clear_zero_and_atomic_rejection(self):
        match = CurrentMatch()
        for value in (3000, 0, None):
            match.apply_facts({'welfareReceived': value}, intent='confirm',
                              cleared_fields=['welfareReceived'] if value is None else None)
            record = json.loads(json.dumps(match.to_canonical()))
            self.assertEqual(record['settlement']['welfare']['received'], value)
            restored = CurrentMatch()
            restored.apply_facts(record, intent='snapshot')
            self.assertEqual(restored.snapshot()['welfareReceived'], value)
        match.apply_facts({'welfareReceived': 3000}, intent='confirm')
        for invalid in (True, -1, 1.5, '1.5', '1e3', 'nan', float('inf'), 10**1000):
            before = match.snapshot()
            with self.assertRaises(ValueError):
                match.apply_facts({'q': 10, 'welfareReceived': invalid}, intent='confirm')
            self.assertEqual(match.snapshot(), before)
        match.apply_facts({}, cleared_fields=['welfareReceived'])
        self.assertIsNone(match.snapshot()['welfareReceived'])
        match.apply_facts({'welfareReceived': 0}, intent='confirm')
        self.assertTrue(match.has_any_fact())
        match.begin_next_match()
        self.assertIsNone(match.snapshot()['welfareReceived'])

    def test_standard_builder_keeps_receipt_separate_from_value(self):
        original = self.record()
        built = build_canonical_match_record_v7('test', '2026-09-13',
            environment=original['environment'], costs=original['costs'], settlement=original['settlement'])
        self.assertEqual(built['settlement']['welfare'], {'received': 3000})
        self.assertEqual(built['settlement']['actualTotal'], 60040)
        self.assertEqual(settlement_accounting(built)['sessionNet'], 16540)
