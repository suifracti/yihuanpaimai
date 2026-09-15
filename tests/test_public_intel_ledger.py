import copy
import unittest
from unittest.mock import patch
import numpy as np
from public_intel_ledger import (
    PublicIntelLedger,
    public_card_key,
    verified_public_event,
    admit_public_card_events,
    canonical_public_event,
)
from intel_card_evidence import IntelCardEvidenceExtractor, IntelCardEvidenceLedger, FrameIntelEvidence
from current_match import CurrentMatch
from intel_evidence_presentation import intel_evidence_text

TEXT = '拍卖师公开情报 随机展示2件藏品'


def reading(frame, physical=True, round_no=1, text=TEXT):
    return {'frameId': frame, 'round': round_no, 'rawText': text, 'is_physical_ocr': physical, 'cardBox': [0, 0, 100, 80]}


class PublicIntelLedgerTests(unittest.TestCase):
    def test_confirmation_dedup_across_rounds_and_detached_snapshot(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('a'), reading('a')])
        ledger.update([reading('b', False)])
        self.assertEqual(ledger.snapshot(), [])
        ledger.update([reading('c')])
        events = ledger.snapshot()
        self.assertEqual(len(events), 1)
        self.assertTrue(verified_public_event(events[0]))
        self.assertEqual([s['frameId'] for s in events[0]['sources']], ['a', 'c'])
        self.assertIsNone(events[0]['incrementalCost'])
        for round_no in (2, 3, 4):
            ledger.update([reading(str(round_no), round_no=round_no)])
        ledger.update([])
        self.assertEqual(ledger.snapshot(), events)
        events[0]['sources'][0]['rawText'] = 'mutated'
        self.assertTrue(verified_public_event(ledger.snapshot()[0]))

    def test_misses_round_changes_wrong_title_and_forged_evidence_do_not_confirm(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('a')]); ledger.update([]); ledger.update([reading('b')])
        self.assertFalse(ledger.snapshot())
        ledger.update([reading('c', round_no=2)])
        self.assertFalse(ledger.snapshot())
        ledger.update([reading('d', round_no=2)])
        event = ledger.snapshot()[0]
        for field, value in (('frameId', 'd'), ('is_physical_ocr', False), ('rawText', '金品均价仪器 本局'), ('round', True)):
            bad = copy.deepcopy(event); bad['sources'][0][field] = value
            self.assertFalse(verified_public_event(bad))
        self.assertFalse(public_card_key('金品均价仪器 本局随机展示2件'))

    def test_pending_public_card_bypasses_cache_then_persists_and_resets(self):
        extractor = IntelCardEvidenceExtractor()
        ledger = IntelCardEvidenceLedger()
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with patch('intel_card_evidence.detect_card_boxes', return_value=[[0, 0, 100, 80]]), patch.object(extractor, '_ocr_card_fast_projected', return_value=(TEXT, [], True)) as ocr:
            first = extractor.extract_cards_fast(frame, frame_id='synthetic-a', known_round=1)
            ledger.merge(first)
            pending = ledger.get_pending_verify_fields()
            self.assertIn(public_card_key(TEXT), pending)
            second = extractor.extract_cards_fast(frame, frame_id='synthetic-b', known_round=1, pending_verify_fields=pending)
            merged = ledger.merge(second)
            self.assertEqual(ocr.call_count, 2)
        events = merged['publicCardEvents']
        self.assertEqual(len(events), 1)
        self.assertEqual(ledger.get_pending_verify_fields(), set())
        self.assertEqual(ledger.merge(FrameIntelEvidence('empty'))['publicCardEvents'], events)
        current = CurrentMatch()
        current.apply_facts({'publicCardEvents': events, 'intelCost': 1200}, intent='confirm')
        saved = current.to_canonical()
        restored = CurrentMatch(); restored.apply_facts(saved, intent='snapshot')
        self.assertEqual(restored.snapshot()['publicCardEvents'], events)
        self.assertEqual(saved['costs']['intel'], 1200)
        self.assertIn('两次识别一致的公开内容', intel_evidence_text(saved))
        restored.begin_next_match(); ledger.clear()
        self.assertEqual(restored.snapshot()['publicCardEvents'], [])
        self.assertEqual(ledger.merge()['publicCardEvents'], [])

    def test_two_physical_frames_produce_exactly_one_event(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1)])
        self.assertEqual(ledger.snapshot(), [])
        ledger.update([reading('f2', physical=True, round_no=1)])
        events = ledger.snapshot()
        self.assertEqual(len(events), 1)
        self.assertTrue(verified_public_event(events[0]))
        self.assertEqual(events[0]['status'], 'CONFIRMED_CONTENT')
        self.assertEqual(events[0]['roundObserved'], 1)
        self.assertEqual([s['frameId'] for s in events[0]['sources']], ['f1', 'f2'])

    def test_single_physical_frame_and_cache_reuse_do_not_produce_event(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1)])
        self.assertEqual(ledger.snapshot(), [])
        ledger.update([reading('f2', physical=False, round_no=1)])
        self.assertEqual(ledger.snapshot(), [])
        ledger.update([reading('f1', physical=True, round_no=1)])
        self.assertEqual(ledger.snapshot(), [])

    def test_conflicting_content_between_frames_does_not_produce_event(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1, text='拍卖师公开情报 随机展示2件藏品')])
        self.assertEqual(ledger.snapshot(), [])
        ledger.update([reading('f2', physical=True, round_no=1, text='拍卖师公开情报 随机展示3件藏品')])
        self.assertEqual(ledger.snapshot(), [])

    def test_confirmed_result_repeated_consumption_and_dedupe(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1)])
        ledger.update([reading('f2', physical=True, round_no=1)])
        events = ledger.snapshot()
        self.assertEqual(len(events), 1)

        current = CurrentMatch()
        current.apply_facts({'publicCardEvents': events}, source='vision')
        self.assertEqual(len(current.snapshot()['publicCardEvents']), 1)

        current.apply_facts({'publicCardEvents': events}, source='vision')
        current.apply_facts({'publicCardEvents': events}, source='vision')
        self.assertEqual(len(current.snapshot()['publicCardEvents']), 1)

    def test_save_restore_json_roundtrip_and_reconsumption(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1)])
        ledger.update([reading('f2', physical=True, round_no=1)])
        events = ledger.snapshot()
        self.assertEqual(len(events), 1)

        current = CurrentMatch()
        current.apply_facts({'publicCardEvents': events, 'intelCost': 1200}, source='vision')
        canonical = current.to_canonical()

        import json
        json_str = json.dumps(canonical)
        loaded = json.loads(json_str)

        from intel_evidence_record import restore_intel_evidence
        restored_evidence = restore_intel_evidence(loaded)
        restored_events = restored_evidence.get('publicCardEvents', [])
        self.assertEqual(len(restored_events), 1)
        self.assertTrue(verified_public_event(restored_events[0]))

        restored_match = CurrentMatch()
        restored_match.apply_facts(loaded, intent='snapshot')
        self.assertEqual(len(restored_match.snapshot()['publicCardEvents']), 1)

        restored_match.apply_facts({'publicCardEvents': events}, source='vision')
        self.assertEqual(len(restored_match.snapshot()['publicCardEvents']), 1)

    def test_new_independent_round_preserves_round_semantics_not_blindly_swallowed(self):
        from public_intel_ledger import public_event_identity
        event_r1 = {
            'id': public_card_key(TEXT), 'status': 'CONFIRMED_CONTENT', 'roundObserved': 1,
            'rawText': TEXT, 'sourceKind': 'AUCTIONEER_PUBLIC',
            'costClassification': 'UNKNOWN', 'incrementalCost': None,
            'sources': [reading('f1', physical=True, round_no=1), reading('f2', physical=True, round_no=1)],
        }
        event_r3 = {
            'id': public_card_key(TEXT), 'status': 'CONFIRMED_CONTENT', 'roundObserved': 3,
            'rawText': TEXT, 'sourceKind': 'AUCTIONEER_PUBLIC',
            'costClassification': 'UNKNOWN', 'incrementalCost': None,
            'sources': [reading('f3', physical=True, round_no=3), reading('f4', physical=True, round_no=3)],
        }
        self.assertTrue(verified_public_event(event_r1))
        self.assertTrue(verified_public_event(event_r3))
        self.assertNotEqual(public_event_identity(event_r1), public_event_identity(event_r3))

        current = CurrentMatch()
        current.apply_facts({'publicCardEvents': [event_r1]}, source='vision')
        current.apply_facts({'publicCardEvents': [event_r3]}, source='vision')
        admitted = current.snapshot()['publicCardEvents']
        self.assertEqual(len(admitted), 2)
        self.assertEqual([e['roundObserved'] for e in admitted], [1, 3])

        text = intel_evidence_text(current.to_canonical())
        self.assertIn('第1回合两次识别一致的公开内容', text)
        self.assertIn('第3回合两次识别一致的公开内容', text)

    def test_exact_public_title_vs_instrument_with_same_value(self):
        from intel_card_source import card_source
        from public_intel_ledger import admit_public_card_events
        instrument_text = '金品均价仪器 本局内所有金色品质藏品的平均价值为47,286。'
        auctioneer_text = '拍卖师公开情报 本局内所有金色品质藏品的平均价值为47,286。'

        self.assertEqual(card_source(instrument_text)['kind'], 'UNKNOWN')
        self.assertEqual(card_source(auctioneer_text)['kind'], 'AUCTIONEER_PUBLIC')
        self.assertIsNone(public_card_key(instrument_text))
        self.assertIsNotNone(public_card_key(auctioneer_text))

        bad_event = {
            'id': 'public-card:fake', 'status': 'CONFIRMED_CONTENT', 'roundObserved': 3,
            'rawText': instrument_text, 'sourceKind': 'UNKNOWN',
            'sources': [reading('i1', physical=True, round_no=3, text=instrument_text),
                        reading('i2', physical=True, round_no=3, text=instrument_text)],
        }
        self.assertFalse(verified_public_event(bad_event))
        self.assertEqual(admit_public_card_events([bad_event]), [])

    def test_extra_intel_rule_hint_does_not_manufacture_observed_event(self):
        rule_hint_context = {
            'fieldCondition': 'extraIntel',
            'round': 1,
            'publicIntel': {'available': True},
            'publicCardEvents': [],
        }
        current = CurrentMatch()
        current.apply_facts(rule_hint_context, source='vision')
        self.assertEqual(current.snapshot()['publicCardEvents'], [])
        canonical = current.to_canonical()
        self.assertEqual(canonical.get('intelCardEvidence', {}).get('publicCardEvents', []), [])

    def test_intel_fee_cost_classification_and_valuation_unchanged(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1)])
        ledger.update([reading('f2', physical=True, round_no=1)])
        events = ledger.snapshot()

        current = CurrentMatch()
        current.apply_facts({'intelCost': 1200, 'entryCost': 5000}, source='manual')
        before = current.to_canonical()

        current.apply_facts({'publicCardEvents': events}, source='vision')
        after = current.to_canonical()

        self.assertEqual(before['costs']['intel'], 1200)
        self.assertEqual(after['costs']['intel'], 1200)
        self.assertEqual(after['intelCardEvidence']['costClassification'], 'UNKNOWN')
        self.assertIsNone(events[0]['incrementalCost'])

    def test_non_numeric_card_does_not_pollute_structured_facts(self):
        non_numeric_text = '拍卖师公开情报 随机展示2件藏品'
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1, text=non_numeric_text)])
        ledger.update([reading('f2', physical=True, round_no=1, text=non_numeric_text)])
        events = ledger.snapshot()
        self.assertEqual(len(events), 1)

        current = CurrentMatch()
        current.apply_facts({'publicCardEvents': events}, source='vision')
        snap = current.snapshot()

        self.assertIsNone(snap.get('totalItems'))
        self.assertIsNone(snap.get('totalGrid'))
        self.assertIsNone(snap.get('goldAvg'))
        self.assertIsNone(snap.get('goldCount'))
        self.assertIsNone(snap.get('q'))

        canonical = current.to_canonical()
        self.assertIsNone(canonical.get('publicIntel', {}).get('totalItems'))
        self.assertIsNone(canonical.get('publicIntel', {}).get('q'))

        text = intel_evidence_text(canonical)
        self.assertIn('随机展示2件藏品', text)
        self.assertNotIn('总件数：2', text)

    def test_match_lifecycle_and_cross_match_isolation(self):
        import tempfile
        from pathlib import Path
        from canonical_history_store import CanonicalHistoryStore
        from auto_archiver import AutoArchiver

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / 'history.json')
            store = CanonicalHistoryStore(db_path)
            archiver = AutoArchiver([db_path])

            ledger = PublicIntelLedger()
            ledger.update([reading('f1', physical=True, round_no=1)])
            ledger.update([reading('f2', physical=True, round_no=1)])
            events = ledger.snapshot()

            match_a = CurrentMatch()
            match_a.apply_facts({
                'matchId': 'match_a_test',
                'venue': '黄金场',
                'box': '实木宝箱',
                'publicCardEvents': events,
                'intelCost': 1200,
            }, source='vision')

            ctx_a = match_a.snapshot()
            ctx_a.update({
                'settlementReady': True,
                'settlementData': {
                    'isSettlement': True,
                    'clearingPrice': 50000,
                    'actualTotal': 60000,
                    'profit': 10000,
                },
            })
            saved_a = archiver.archive_match(ctx_a)
            self.assertIsNotNone(saved_a)
            self.assertIn('intelCardEvidence', saved_a)
            self.assertEqual(len(saved_a['intelCardEvidence']['publicCardEvents']), 1)

            match_b_snap = match_a.begin_next_match()
            self.assertEqual(match_b_snap['publicCardEvents'], [])
            self.assertEqual(match_a.snapshot()['publicCardEvents'], [])

            db_records = store.read_database().get('records', [])
            self.assertEqual(len(db_records), 1)
            archived_a = db_records[0]
            self.assertEqual(len(archived_a['intelCardEvidence']['publicCardEvents']), 1)
            self.assertIn('两次识别一致的公开内容', intel_evidence_text(archived_a))

    def test_backward_compatibility_with_legacy_records(self):
        from intel_evidence_record import restore_intel_evidence

        legacy_1 = {'id': 'legacy-1', 'schemaVersion': 7, 'publicIntel': {'q': 10}}
        self.assertEqual(restore_intel_evidence(legacy_1), {})
        current = CurrentMatch()
        current.apply_facts(legacy_1, intent='snapshot')
        self.assertEqual(current.snapshot()['publicCardEvents'], [])
        self.assertEqual(intel_evidence_text(legacy_1), '未记录情报识别证据')

        legacy_2 = {
            'id': 'legacy-2',
            'schemaVersion': 7,
            'intelCardEvidence': {
                'version': 1,
                'costClassification': 'UNKNOWN',
                'facts': {},
                'observations': [],
                'cardReadings': [{'frameId': 'f0', 'rawText': '金品均价仪器 本局', 'is_physical_ocr': True}],
            }
        }
        restored_2 = restore_intel_evidence(legacy_2)
        self.assertNotIn('publicCardEvents', restored_2)
        current.begin_next_match()
        current.apply_facts(legacy_2, intent='snapshot')
        self.assertEqual(current.snapshot()['publicCardEvents'], [])
        text_2 = intel_evidence_text(legacy_2)
        self.assertIn('金品均价仪器', text_2)
        self.assertNotIn('两次识别一致的公开内容', text_2)

    def test_real_viewport_screenshot_production_path_integration(self):
        """REAL SCREENSHOT PRODUCTION PATH INTEGRATION TEST (not claiming independent multi-frame confirmation)."""
        import cv2
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        img_path = root / 'tests/fixtures/intel_card_evidence_v1/r3_viewport.png'
        frame = cv2.imread(str(img_path))
        self.assertIsNotNone(frame, f"Fixture not found: {img_path}")

        extractor = IntelCardEvidenceExtractor()
        first = extractor.extract_cards_fast(frame, frame_id='source-r3-first', known_round=3)
        gold_obs = [o.to_dict() for o in first.observations if o.field == 'goldAvg']
        self.assertEqual(len(gold_obs), 2)
        public_card = next(o for o in gold_obs if o['cardSource'].get('kind') == 'AUCTIONEER_PUBLIC')
        instrument_card = next(o for o in gold_obs if o['cardSource'].get('kind') == 'UNKNOWN')
        self.assertEqual(public_card['value'], 47286)
        self.assertEqual(instrument_card['value'], 47286)

        ledger = IntelCardEvidenceLedger()
        snap1 = ledger.merge(first)
        self.assertEqual(snap1['publicCardEvents'], [])

        second_cached = extractor.extract_cards_fast(frame, frame_id='source-r3-cached', known_round=3)
        self.assertTrue(any(not o.is_physical_ocr for o in second_cached.observations))
        snap2 = ledger.merge(second_cached)
        self.assertEqual(snap2['publicCardEvents'], [])

    def test_vision_sync_to_current_match_production_wiring(self):
        from current_match import CURRENT_MATCH
        from main import sync_vision_to_current_match
        from recognition_mode import set_recognition_mode

        set_recognition_mode('auto')
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1)])
        ledger.update([reading('f2', physical=True, round_no=1)])
        events = ledger.snapshot()

        mock_ctx = {
            'recognitionPaused': False,
            'recognitionMode': 'auto',
            'publicCardEvents': events,
            'intelCardReadings': [reading('f2', physical=True, round_no=1)],
        }
        CURRENT_MATCH.begin_next_match()
        self.assertEqual(CURRENT_MATCH.snapshot()['publicCardEvents'], [])

        sync_vision_to_current_match(mock_ctx)
        self.assertEqual(len(CURRENT_MATCH.snapshot()['publicCardEvents']), 1)
        self.assertEqual(CURRENT_MATCH.snapshot()['publicCardEvents'][0]['id'], events[0]['id'])

        canonical = CURRENT_MATCH.to_canonical()
        self.assertIn('intelCardEvidence', canonical)
        self.assertEqual(len(canonical['intelCardEvidence']['publicCardEvents']), 1)

        CURRENT_MATCH.begin_next_match()

    def test_tampered_cost_classification_free_rejected(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1)])
        ledger.update([reading('f2', physical=True, round_no=1)])
        events = ledger.snapshot()
        self.assertEqual(len(events), 1)
        tampered = copy.deepcopy(events[0])
        tampered['costClassification'] = 'FREE'
        self.assertFalse(verified_public_event(tampered))
        self.assertEqual(admit_public_card_events([tampered]), [])
        current = CurrentMatch()
        current.apply_facts({'publicCardEvents': [tampered]}, source='vision')
        self.assertEqual(current.snapshot()['publicCardEvents'], [])

    def test_tampered_incremental_cost_zero_rejected(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1)])
        ledger.update([reading('f2', physical=True, round_no=1)])
        events = ledger.snapshot()
        tampered = copy.deepcopy(events[0])
        tampered['incrementalCost'] = 0
        self.assertFalse(verified_public_event(tampered))
        self.assertEqual(admit_public_card_events([tampered]), [])
        current = CurrentMatch()
        current.apply_facts({'publicCardEvents': [tampered]}, source='vision')
        self.assertEqual(current.snapshot()['publicCardEvents'], [])

    def test_tampered_source_kind_rejected(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1)])
        ledger.update([reading('f2', physical=True, round_no=1)])
        events = ledger.snapshot()
        tampered = copy.deepcopy(events[0])
        tampered['sourceKind'] = 'PAID_INSTRUMENT'
        self.assertFalse(verified_public_event(tampered))
        self.assertEqual(admit_public_card_events([tampered]), [])
        current = CurrentMatch()
        current.apply_facts({'publicCardEvents': [tampered]}, source='vision')
        self.assertEqual(current.snapshot()['publicCardEvents'], [])

    def test_tampered_injected_extra_keys_sanitized(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1)])
        ledger.update([reading('f2', physical=True, round_no=1)])
        events = ledger.snapshot()
        injected = copy.deepcopy(events[0])
        injected['evilKey'] = 'malicious_data'
        injected['bypassAudit'] = True
        self.assertTrue(verified_public_event(injected))
        admitted = admit_public_card_events([injected])
        self.assertEqual(len(admitted), 1)
        self.assertNotIn('evilKey', admitted[0])
        self.assertNotIn('bypassAudit', admitted[0])
        self.assertEqual(admitted[0]['sourceKind'], 'AUCTIONEER_PUBLIC')
        self.assertEqual(admitted[0]['costClassification'], 'UNKNOWN')
        self.assertIsNone(admitted[0]['incrementalCost'])

    def test_canonical_event_structure_enforced(self):
        ledger = PublicIntelLedger()
        ledger.update([reading('f1', physical=True, round_no=1)])
        ledger.update([reading('f2', physical=True, round_no=1)])
        events = ledger.snapshot()
        canonical = canonical_public_event(events[0])
        expected_keys = {
            'id', 'status', 'roundObserved', 'rawText',
            'sourceKind', 'costClassification', 'incrementalCost', 'sources'
        }
        self.assertEqual(set(canonical.keys()), expected_keys)
        self.assertEqual(canonical['sourceKind'], 'AUCTIONEER_PUBLIC')
        self.assertEqual(canonical['costClassification'], 'UNKNOWN')
        self.assertIsNone(canonical['incrementalCost'])
        self.assertEqual(canonical['status'], 'CONFIRMED_CONTENT')

    def test_real_public_intel_ledger_cross_round_same_text_audit(self):
        """Audit real PublicIntelLedger.update(): R1 A+B, R2 empty, R3 C+D same text.
        Proves that PublicIntelLedger indexes confirmed events by public_card_key(text)
        and intentionally keeps exactly 1 event (R1) across rounds within a match.
        """
        ledger = PublicIntelLedger()
        # Round 1: 2 physical OCR frames confirm the public card
        ledger.update([reading('frame_r1_a', physical=True, round_no=1)])
        ledger.update([reading('frame_r1_b', physical=True, round_no=1)])
        r1_snap = ledger.snapshot()
        self.assertEqual(len(r1_snap), 1)
        self.assertEqual(r1_snap[0]['roundObserved'], 1)

        # Round 2: empty (absence interrupts tentative pending confirmation)
        ledger.update([])
        self.assertEqual(len(ledger.snapshot()), 1)

        # Round 3: 2 physical OCR frames with the exact same text
        ledger.update([reading('frame_r3_c', physical=True, round_no=3)])
        ledger.update([reading('frame_r3_d', physical=True, round_no=3)])
        r3_snap = ledger.snapshot()
        # Result is strictly 1 event because dd12561 designed PublicIntelLedger
        # as a per-match cross-round content ledger keyed by card key:
        # line 84: if key in self.confirmed: continue
        self.assertEqual(len(r3_snap), 1)
        self.assertEqual(r3_snap[0]['roundObserved'], 1)
        self.assertEqual(r3_snap[0]['sources'][0]['frameId'], 'frame_r1_a')
        self.assertEqual(r3_snap[0]['sources'][1]['frameId'], 'frame_r1_b')

    def test_match_transition_pipeline_to_current_match_no_reinjection(self):
        """End-to-end audit: Match 1 confirms event, match transition resets ledger & context,
        Match 2 receiving new non-public-card frames does not re-inject Match 1 events.
        """
        from vision_pipeline import NTEVisionPipeline
        from current_match import CURRENT_MATCH
        from main import sync_vision_to_current_match
        from recognition_mode import set_recognition_mode

        set_recognition_mode('auto')
        pipe = NTEVisionPipeline()
        CURRENT_MATCH.begin_next_match()

        # Match 1: Pipeline ledger confirms public card
        pipe._intel_ledger = IntelCardEvidenceLedger()
        pipe._intel_ledger._public_cards.update([reading('m1_f1', physical=True, round_no=1)])
        pipe._intel_ledger._public_cards.update([reading('m1_f2', physical=True, round_no=1)])
        snap1 = pipe._intel_ledger.merge()
        pipe.current_context['publicCardEvents'] = snap1['publicCardEvents']
        sync_vision_to_current_match(pipe.current_context)
        self.assertEqual(len(CURRENT_MATCH.snapshot()['publicCardEvents']), 1)

        # Match 1 ends -> Player returns to lobby / egress -> clear_match_trunk
        pipe.clear_match_trunk()
        self.assertIsNone(pipe._intel_ledger)
        self.assertEqual(pipe.current_context['publicCardEvents'], [])

        # Match 2 begins: CURRENT_MATCH starts new draft
        CURRENT_MATCH.begin_next_match()
        self.assertEqual(CURRENT_MATCH.snapshot()['publicCardEvents'], [])

        # Match 2: Next frame arrives without public card
        if pipe._intel_ledger is not None:
            pipe.current_context['publicCardEvents'] = pipe._intel_ledger.merge().get('publicCardEvents', [])
        else:
            pipe.current_context['publicCardEvents'] = []
        sync_vision_to_current_match(pipe.current_context)

        # Assert no re-injection into Match 2
        self.assertEqual(CURRENT_MATCH.snapshot()['publicCardEvents'], [])

    def test_intel_evidence_presentation_text_updated(self):
        record = {
            'intelCardEvidence': {
                'version': 1,
                'publicCardEvents': [{
                    'id': public_card_key(TEXT),
                    'status': 'CONFIRMED_CONTENT',
                    'roundObserved': 1,
                    'rawText': TEXT,
                    'sources': [
                        {'frameId': 'f1', 'round': 1, 'rawText': TEXT, 'is_physical_ocr': True},
                        {'frameId': 'f2', 'round': 1, 'rawText': TEXT, 'is_physical_ocr': True},
                    ]
                }]
            }
        }
        text = intel_evidence_text(record)
        self.assertIn('第1回合两次识别一致的公开内容（仅记录观察事实，不据此判定免费）：', text)
        self.assertNotIn('（不重复计费）', text)

    def test_natural_match_exit_via_end_match_on_lobby_or_egress_clears_public_intel(self):
        """Verify the production natural match exit lifecycle:
        Settlement finalized -> Egress to lobby/pre-auction scene ->
        _end_match_on_lobby_or_egress() -> clear_match_trunk() ->
        cleans up _intel_ledger, publicCardEvents, and intelCardReadings.
        """
        from vision_pipeline import NTEVisionPipeline

        pipe = NTEVisionPipeline()

        # Match A: confirmed public event in ledger and context
        pipe._intel_ledger = IntelCardEvidenceLedger()
        pipe._intel_ledger._public_cards.update([reading('f1', physical=True, round_no=1)])
        pipe._intel_ledger._public_cards.update([reading('f2', physical=True, round_no=1)])
        pipe.current_context['publicCardEvents'] = pipe._intel_ledger.merge()['publicCardEvents']
        pipe.current_context['intelCardReadings'] = [reading('f2', physical=True, round_no=1)]
        pipe.current_context['box'] = '实木宝箱'
        pipe.current_context['round'] = 5

        self.assertIsNotNone(pipe._intel_ledger)
        self.assertEqual(len(pipe.current_context['publicCardEvents']), 1)
        self.assertEqual(len(pipe.current_context['intelCardReadings']), 1)

        # 1. Natural settlement finalization flags trunk for clearance after leaving
        pipe.mark_settlement_finalized()
        self.assertTrue(pipe.current_context.get('_clearTrunkAfterLeave'))

        # 2. Natural egress: game returns to lobby via _apply_pre_auction_scene,
        # which dispatches into _end_match_on_lobby_or_egress()
        pipe._apply_pre_auction_scene({'scene': 'AUCTION_LOBBY', 'auctionEntryVisible': True})

        # 3. Assert natural match exit wiped intel ledger and context
        self.assertIsNone(pipe._intel_ledger)
        self.assertEqual(pipe.current_context['publicCardEvents'], [])
        self.assertEqual(pipe.current_context['intelCardReadings'], [])

        # 4. Direct call to _end_match_on_lobby_or_egress() verification
        pipe._intel_ledger = IntelCardEvidenceLedger()
        pipe._intel_ledger._public_cards.update([reading('f3', physical=True, round_no=1)])
        pipe._intel_ledger._public_cards.update([reading('f4', physical=True, round_no=1)])
        pipe.current_context['publicCardEvents'] = pipe._intel_ledger.merge()['publicCardEvents']
        pipe.current_context['intelCardReadings'] = [reading('f4', physical=True, round_no=1)]
        pipe.current_context['box'] = '实木宝箱'
        pipe.current_context['_clearTrunkAfterLeave'] = True

        pipe._end_match_on_lobby_or_egress()

        self.assertIsNone(pipe._intel_ledger)
        self.assertEqual(pipe.current_context['publicCardEvents'], [])
        self.assertEqual(pipe.current_context['intelCardReadings'], [])

