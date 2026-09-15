import copy
import json
import tempfile
import unittest
from pathlib import Path

from current_match import CurrentMatch
from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import FORBIDDEN_ROOT_LEGACY_FIELDS
from intel_card_evidence import IntelCardEvidenceLedger, IntelCardObservation, FrameIntelEvidence
from intel_evidence_record import restore_intel_evidence
from field_intel_status import free_intel_status
from auto_archiver import AutoArchiver


def observed(ledger, frame_id, value):
    obs = IntelCardObservation('goldCount', value, 'OBSERVED', frame_id, 1, 40,
                               [10, 20, 300, 80], f'金色藏品总数量{value}', .95)
    facts = ledger.merge(FrameIntelEvidence(frame_id, observations=[obs]))['facts']
    return {'intelFacts': facts, 'intelObservations': [obs.to_dict()]}


class IntelEvidencePersistenceTests(unittest.TestCase):
    def test_ledger_roundtrip_keeps_tentative_confirmed_conflict_without_promoting_facts(self):
        ledger = IntelCardEvidenceLedger()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'history.json'
            for index, value, status in ((1, 2, 'UNKNOWN'), (2, 2, 'OBSERVED'),
                                         (3, 3, 'OBSERVED'), (4, 3, 'CONFLICT')):
                payload = observed(ledger, f'frame-{index}', value)
                expected = copy.deepcopy(payload)
                match = CurrentMatch()
                match.apply_facts({'fieldCondition': 'extraIntel', 'roundNo': 1,
                                   'intelCost': 1200, **payload}, intent='confirm')
                payload['intelObservations'][0]['rawText'] = 'mutated'
                canonical = {k:v for k,v in match.to_canonical().items() if k not in FORBIDDEN_ROOT_LEGACY_FIELDS}
                CanonicalHistoryStore(path).persist_record_transactional(canonical, is_finalized=False)
                saved = next(r for r in json.loads(path.read_text(encoding='utf-8'))['records'] if r['id'] == match.id)
                restored = CurrentMatch()
                restored.apply_facts(saved, intent='snapshot')
                self.assertEqual(restored.snapshot()['intelFacts'], expected['intelFacts'])
                self.assertEqual(restored.snapshot()['intelObservations'], expected['intelObservations'])
                self.assertEqual(restored.snapshot()['intelFacts']['goldCount']['status'], status)
                self.assertIsNone(restored.snapshot()['goldCount'])
                self.assertEqual(saved['costs']['intel'], 1200)
                self.assertEqual(saved['intelCardEvidence']['costClassification'], 'UNKNOWN')
                self.assertFalse(free_intel_status(restored.snapshot())['observed'])
                restored.begin_next_match()
                self.assertIsNone(restored.snapshot()['intelFacts'])
                self.assertEqual(restored.snapshot()['intelObservations'], [])

    def test_unknown_schema_and_explicit_flat_values(self):
        for version in (None, True, '1', 2):
            self.assertEqual(restore_intel_evidence({'intelCardEvidence': {'version': version, 'facts': {'q': 100}}}), {})
        current = CurrentMatch()
        current.apply_facts({'intelCardEvidence': {'version': 1, 'facts': {'q': 100}, 'observations': []},
                             'intelFacts': {'q': 200}}, intent='snapshot')
        self.assertEqual(current.snapshot()['intelFacts'], {'q': 200})


class IntelArchiveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'history.json'
        self.archiver = AutoArchiver(db_paths=[str(self.path)])

    def _read_persisted_record(self, record_id):
        return next(r for r in json.loads(self.path.read_text(encoding='utf-8'))['records'] if r['id'] == record_id)

    def test_evidence_only_update_and_missing_payload_preservation(self):
        ledger = IntelCardEvidenceLedger()
        ctx = {'id': 'intel-update', 'isSettlement': True, 'isAcquired': False,
               'fieldCondition': 'extraIntel', 'costs': {'entry': 0, 'intel': 1200, 'other': 0},
               'settlementData': {'isSettlement': True, 'clearingPrice': 300000, 'actualTotal': 450000}}
        for index in (1, 2):
            ctx.update(observed(ledger, f'frame-{index}', 2), settlementReady=True)
            self.assertIsNotNone(self.archiver.archive_match(ctx))
            saved = self._read_persisted_record(ctx['id'])
            self.assertEqual(saved['intelCardEvidence']['facts'], ctx['intelFacts'])
            self.assertEqual(saved['costs']['intel'], 1200)
            ctx['settlementReady'] = True
            self.assertIsNone(self.archiver.archive_match(ctx))
        expected = saved['intelCardEvidence']
        ctx.pop('intelFacts'); ctx.pop('intelObservations')
        ctx['settlementReady'] = True
        self.assertIsNotNone(self.archiver.archive_match(ctx))
        self.assertEqual(self._read_persisted_record(ctx['id'])['intelCardEvidence'], expected)
        ctx.update(intelFacts=None, intelObservations=[], settlementReady=True)
        self.assertIsNotNone(self.archiver.archive_match(ctx))
        self.assertEqual(self._read_persisted_record(ctx['id'])['intelCardEvidence']['observations'], [])
        self.assertIsNone(self._read_persisted_record(ctx['id'])['intelCardEvidence']['facts'])
