"""Real recorded v2 packet: mixed human/automatic review must remain distinct."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from warehouse_auto_confirmation import evaluate_auto_confirmation, extract_human_decisions
from warehouse_identity_review import resolve_warehouse_identity_review, build_auto_identity_review_artifact
from warehouse_identity_review_persist import (persist_warehouse_identity_review,
    review_persistence_status, WarehouseIdentityReviewPersistError)
from warehouse_identity_review_session import WarehouseIdentityReviewSession


class ManualReviewV2Tests(unittest.TestCase):
    def setUp(self):
        self.packet = json.loads((ROOT / 'tests/fixtures/warehouse_manual_review/desktop_match2_packet.json').read_text(encoding='utf-8'))
        self.key = self.packet['recordStableKey']
        self.units = evaluate_auto_confirmation(self.packet['reviewUnits'], self.packet['segments'])
        self.auto = build_auto_identity_review_artifact(self.packet, self.units)
        self.decisions = [dict(decisionId='manual-' + str(i), reviewUnitId=uid,
            action='CONFIRM_CATALOG_OVERRIDE', selectedCatalogId=cid,
            confirmedByHuman=True, overrideReason='HUMAN_VISUAL_IDENTIFICATION')
            for i, (uid, cid) in enumerate([('unit-world-2-2-2x1', 'image20-0-2'),
                                           ('unit-world-1-3-1x1', 'image16-0-1')])]
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CanonicalHistoryStore(Path(self.tmp.name) / 'history.json')
        record = build_canonical_match_record_v7(match_id=self.key,
            played_at='2026-09-08T13:44:36+08:00', lifecycle_status='DRAFT',
            source='isolated-manual-review-test')
        record['settlement'].update(warehouseIdentityReview=self.auto, reviewUnits=self.units)
        self.store.persist_record_transactional(record, is_finalized=False)

    def tearDown(self):
        self.tmp.cleanup()

    def artifact(self, decisions=None):
        return resolve_warehouse_identity_review(self.packet, dict(
            schemaVersion='warehouse-identity-review-decision.v2', recordStableKey=self.key,
            packetFingerprint=self.packet['sourceFingerprint'], reviewedAt='2026-09-12T13:00:00Z',
            reviewerType='HUMAN', decisions=self.decisions if decisions is None else decisions))

    def session(self, artifact):
        session = Mock()
        session.artifact_copy.return_value = artifact
        session.persist_binding.return_value = dict(sessionId='test-session', recordStableKey=self.key,
            packetFingerprint=artifact['packetFingerprint'], artifactFingerprint=artifact['artifactFingerprint'])
        return session

    def save(self, session):
        return persist_warehouse_identity_review(session=session, history_store=self.store,
            session_id='test-session', packet_fingerprint=self.packet['sourceFingerprint'])

    def test_two_manual_keep_twenty_one_auto_and_partial_coverage(self):
        artifact = self.artifact()
        self.assertEqual(len(artifact['resolvedItems']), 23)
        self.assertEqual(artifact['warehouseCoverageStatus'], 'PARTIAL')
        self.assertEqual(artifact['identityResolution'], 'PARTIAL')
        human = extract_human_decisions({'settlement': {'warehouseIdentityReview': artifact}})
        self.assertEqual(set(human), {d['reviewUnitId'] for d in self.decisions})

    def test_unreviewed_unknown_is_not_a_human_defer(self):
        artifact = self.artifact(self.decisions[:1])
        self.assertEqual(len(artifact['resolvedItems']), 22)
        self.assertEqual(len(extract_human_decisions({'settlement': {'warehouseIdentityReview': artifact}})), 1)

    def test_explicit_defer_overrides_machine_confirmation(self):
        uid = self.auto['resolvedItems'][0]['reviewUnitId']
        artifact = self.artifact([dict(decisionId='defer', reviewUnitId=uid, action='DEFER', confirmedByHuman=True)])
        self.assertNotIn(uid, {i['reviewUnitId'] for i in artifact['resolvedItems']})
        human = extract_human_decisions({'settlement': {'warehouseIdentityReview': artifact}})
        self.assertEqual(set(human), {uid})
        self.assertIsNone(human[uid]['catalogId'])

    def test_save_projection_idempotency_and_late_auto(self):
        session = self.session(self.artifact())
        self.assertEqual(review_persistence_status(session, self.store)['persistStatus'], 'READY')
        self.assertTrue(self.save(session)['written'])
        record = CanonicalHistoryStore(self.store.db_path).lookup(self.key)
        self.assertEqual(record['lifecycleStatus'], 'DRAFT')
        units = record['settlement']['reviewUnits']
        self.assertEqual(sum(u.get('confirmedByHuman') is True for u in units), 2)
        self.assertEqual(sum(u['confirmationStatus'] == 'CONFIRMED' for u in units), 23)
        later = evaluate_auto_confirmation(self.packet['reviewUnits'], self.packet['segments'], record)
        self.assertEqual(sum(u.get('confirmedByHuman') is True for u in later), 2)
        self.assertEqual(sum(u['confirmationStatus'] == 'CONFIRMED' for u in later), 23)
        self.assertTrue(self.save(session)['idempotent'])
        self.assertEqual(review_persistence_status(session, self.store)['persistStatus'], 'SAVED')

    def test_existing_human_cannot_be_overwritten(self):
        self.save(self.session(self.artifact()))
        with self.assertRaisesRegex(WarehouseIdentityReviewPersistError, 'ARTIFACT_CONFLICT'):
            self.save(self.session(self.artifact(self.decisions[:1])))

    def test_concurrent_review_change_is_preserved(self):
        session = self.session(self.artifact())
        concurrent = self.artifact(self.decisions[:1])
        original = self.store.update_record_transactional
        def race(*args, **kwargs):
            original(self.key, {'settlement': {'warehouseIdentityReview': concurrent}})
            return original(*args, **kwargs)
        with patch.object(self.store, 'update_record_transactional', side_effect=race):
            with self.assertRaises(WarehouseIdentityReviewPersistError) as caught:
                self.save(session)
            self.assertEqual(caught.exception.code, 'ARTIFACT_CONFLICT')
        self.assertEqual(self.store.lookup(self.key)['settlement']['warehouseIdentityReview'], concurrent)

    def test_native_resume_edit_keeps_other_decisions_and_revision_history(self):
        initial = self.artifact()
        self.save(self.session(initial))
        session = WarehouseIdentityReviewSession()
        session.open(self.packet, saved_artifact=initial)
        self.assertEqual(session.persist_binding()['baseArtifactFingerprint'], initial['artifactFingerprint'])
        uid = self.decisions[0]['reviewUnitId']
        session.select_track(uid)
        self.assertEqual(session.view()['draftAction'], 'CONFIRM_CATALOG_OVERRIDE')
        session.undo()
        session.apply({'action': 'DEFER'})
        session.finalize()
        binding = session.persist_binding()
        persist_warehouse_identity_review(session=session, history_store=self.store,
            session_id=binding['sessionId'], packet_fingerprint=binding['packetFingerprint'])
        st = self.store.lookup(self.key)['settlement']
        self.assertEqual(len(st['warehouseIdentityReview']['resolvedItems']), 22)
        self.assertEqual(st['warehouseIdentityReviewHistory'], [self.auto, initial])
        changed = next(u for u in st['reviewUnits'] if u['reviewUnitId'] == uid)
        self.assertIsNone(changed['selectedCatalogId'])
        self.assertTrue(changed['confirmedByHuman'])
        self.assertEqual(review_persistence_status(session, self.store)['persistStatus'], 'SAVED')
        # The same live session may make another edit after saving.
        session.undo()
        session.finalize()
        persist_warehouse_identity_review(session=session, history_store=self.store,
            session_id=binding['sessionId'], packet_fingerprint=binding['packetFingerprint'])
        st = self.store.lookup(self.key)['settlement']
        changed = next(u for u in st['reviewUnits'] if u['reviewUnitId'] == uid)
        self.assertIsNone(changed['selectedCatalogId'])
        self.assertFalse(changed['confirmedByHuman'])
        self.assertEqual(len(st['warehouseIdentityReviewHistory']), 3)

    def test_native_resume_rejects_different_packet_and_stale_session(self):
        initial = self.artifact()
        self.save(self.session(initial))
        session = WarehouseIdentityReviewSession()
        session.open(self.packet, saved_artifact=initial)
        session.select_track(self.decisions[0]['reviewUnitId'])
        session.undo()
        session.finalize()
        other = self.artifact(self.decisions[:1])
        self.store.update_record_transactional(self.key, {'settlement': {'warehouseIdentityReview': other}})
        binding = session.persist_binding()
        with self.assertRaises(WarehouseIdentityReviewPersistError) as caught:
            persist_warehouse_identity_review(session=session, history_store=self.store,
                session_id=binding['sessionId'], packet_fingerprint=binding['packetFingerprint'])
        self.assertEqual(caught.exception.code, 'ARTIFACT_CONFLICT')

    def test_packet_persists_and_history_open_needs_no_live_host(self):
        self.store.persist_warehouse_evidence(self.key, review_packet=self.packet)
        fresh = CanonicalHistoryStore(self.store.db_path)
        self.assertEqual(fresh.lookup(self.key)['settlement']['warehouseReviewPacket'], self.packet)
        sys.path.insert(0, str(ROOT / 'app'))
        from main_window import MainWindowBridge
        bridge = MainWindowBridge(Mock(), warehouse_identity_review_session=WarehouseIdentityReviewSession(),
                                  warehouse_identity_review_history_store=fresh)
        response = bridge.dispatch({'action': 'warehouse_identity_review', 'op': 'open', 'recordId': self.key})
        self.assertTrue(response['warehouseIdentityReview']['available'])
        self.assertEqual(response['warehouseIdentityReview']['trackCount'], 23)

    def test_corrupted_packet_never_replaces_saved_packet(self):
        from canonical_history_store import HistoryStoreError
        self.store.persist_warehouse_evidence(self.key, review_packet=self.packet)
        before = self.store.db_path.read_bytes()
        corrupt = copy.deepcopy(self.packet)
        corrupt['sourceFingerprint'] = '0' * 64
        with self.assertRaises(HistoryStoreError):
            self.store.persist_warehouse_evidence(self.key, review_packet=corrupt)
        self.assertEqual(self.store.db_path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
