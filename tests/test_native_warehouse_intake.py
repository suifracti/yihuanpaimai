"""Native intake contracts with versioned development crops on offline canvases."""
import copy
import hashlib
import json
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core')]
from native_trial_drafts import NativeTrialDraftStore
from native_warehouse_intake import (NativeWarehouseIntake, WarehouseCaptureRouter,
    WarehouseReviewHistoryRouter, WarehouseIdentityReviewRouter)
from warehouse_capture_host import WarehouseCaptureHost
from canonical_match_record import build_canonical_match_record_v7
from settlement_truth_evidence_contract import validate_settlement_evidence_original_v2


class NativeWarehouseIntakeTests(unittest.TestCase):
    def test_saved_analysis_uses_independent_same_viewport_originals_not_whole_page_equality(self):
        from native_warehouse_intake import _anchor
        root = ROOT / 'build/t1-20261012/real-once-10/runtime-data/native-live-trial'
        path = root / 'warehouse-intake/b546a40dde6a4cac8c61383b95bd34aa.json'
        if not path.is_file():
            self.skipTest('Private once-10 SOURCE material is not distributed')
        manifest = json.loads(path.read_text('utf-8'))
        reader = NativeWarehouseIntake(draft_store=NativeTrialDraftStore(root/'canonical-history.json'),
            scope_provider=lambda:None, source_provider=lambda:None, auto_refine=False)
        reader._binding = _anchor(manifest['scope'])
        reader._session_id, reader._generation = manifest['sessionId'], manifest['generation']
        top_anchor, top = copy.deepcopy(manifest['pages'][25:27])
        top_ids = [p['descriptor']['evidenceId'] for p in (top_anchor,top)]
        reader._pages = [top_anchor,top]
        reader._coverage_evidence_ids = [top_ids[1]]
        self.assertEqual(reader._saved_identity_ids(), [])  # Old global certificate is absent.
        self.assertEqual(reader._saved_analysis_ids(), top_ids)
        self.assertEqual(reader._saved_support_ids(), [])  # No new SOURCE/fact certificate.
        self.assertNotIn('contentCertificate', top)
        # A saved geometry chain can queue per-item analysis even when no whole
        # viewport has the old global pixel certificate. Queueing is not a fact.
        from native_warehouse_refinement import SavedWarehouseRefinement
        manifest_path = self.store.root/'warehouse-intake'/path.name
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        raw_only = {**manifest, 'pages':[top_anchor,top], 'processingEvidenceIds':[],
                    'coverageEvidenceIds':[top_ids[1]], 'state':'PARTIAL', 'refinement':{}}
        manifest_path.write_text(json.dumps(raw_only), encoding='utf-8')
        refiner = SavedWarehouseRefinement(self.intake)
        with patch.object(refiner, '_run'):
            self.assertTrue(refiner.enqueue(manifest['sessionId'],resume=True)['ok'])
        queued = json.loads(manifest_path.read_text('utf-8'))
        self.assertEqual(queued['refinement']['state'], 'QUEUED')
        self.assertEqual(queued['processingEvidenceIds'], [])
        top_anchor['deliveryProof']['captureId'] = top['deliveryProof']['captureId']
        self.assertEqual(reader._saved_analysis_ids(), [])
        reader._pages = copy.deepcopy(manifest['pages'][25:27])
        reader._pages[0]['clientMap'] = 'different-window-map'
        self.assertEqual(reader._saved_analysis_ids(), [])
        reader._pages = copy.deepcopy(manifest['pages'][25:27])
        reader._pages[0]['deliveryProof']['deliveryQualified'] = False
        self.assertEqual(reader._saved_analysis_ids(), [])
        reader._pages = copy.deepcopy(manifest['pages'][26:28])  # Actual scroll between these originals.
        reader._coverage_evidence_ids = [reader._pages[-1]['descriptor']['evidenceId']]
        self.assertEqual(reader._saved_analysis_ids(), [])

    def test_collection_retention_is_not_cut_off_at_sixteen_sources(self):
        self.frame(163, 1)
        self.assertTrue(self.intake.start_manual(retain_independent_originals=True)['ok'])
        for sequence in range(1, 18):
            self.source['frameSequence'] = sequence
            self.source['receivedAt'] = time.monotonic()  # Independent synthetic fixture arrivals.
            result = self.intake.capture_manual_page()
            self.assertTrue(result['ok'], (sequence, result))
        self.assertEqual(len(self.intake.pages_copy()), 17)
        self.assertEqual(self.intake.presentation_payload()['coverageStatus'], 'COVERAGE_UNPROVEN')

    def test_source_trial_store_follows_explicit_runtime_isolation(self):
        from native_trial_drafts import resolve_native_trial_history_path
        import os
        isolated = ROOT / 'build/t1-20261012/preflight-runtime'
        with patch.dict(os.environ, {'YIHUAN_DATA_ROOT': str(isolated)}):
            self.assertEqual(resolve_native_trial_history_path(ROOT, frozen=False),
                isolated.resolve() / 'native-live-trial/canonical-history.json')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_native_trial_history_path(ROOT, frozen=False),
                ROOT / 'build/native-observation/trial-drafts/canonical-history.json')

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='native-intake-', dir=ROOT / 'build'))
        self.store = NativeTrialDraftStore(self.root / 'trial/canonical-history.json')
        self.scope = {'recordStableKey': 'native_intake_development',
                      'observationSessionId': 'test-native-session',
                      'targetInstance': {'targetHwnd': 123, 'targetPid': 456, 'generation': 1},
                      'matchGeneration': 1, 'scene': 'SETTLEMENT'}
        record = build_canonical_match_record_v7(
            match_id=self.scope['recordStableKey'], played_at='2026-09-30T10:00:00Z',
            lifecycle_status='DRAFT', source='manual', settlement={})
        record['dataOrigin'] = 'live-trial'
        self.store.save_draft(record)
        self.source = None
        self.intake = NativeWarehouseIntake(draft_store=self.store,
            scope_provider=lambda: copy.deepcopy(self.scope),
            source_provider=lambda: copy.deepcopy(self.source), auto_refine=False)

    def frame(self, seconds, sequence):
        directory = ROOT / 'tests/fixtures/native_intake_pages_v1'
        samples = json.loads((directory / 'provenance.json').read_text(encoding='utf-8'))
        entry = next(s for s in samples['frames'] if s['seconds'] == seconds)
        crop_path = directory / entry['file']
        self.assertEqual(hashlib.sha256(crop_path.read_bytes()).hexdigest(), entry['fixtureSha256'])
        crop = cv2.imread(str(crop_path))
        self.assertIsNotNone(crop)
        # Unchanged source crop at its original coordinates; black surroundings
        # are an offline storage/IPC canvas, never claimed as real WGC evidence.
        width, height = entry['canvasSizeWH']
        x1, y1, x2, y2 = entry['cropXYXY']
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[y1:y2, x1:x2] = crop
        bgra = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
        h, w = frame.shape[:2]
        pixels = bgra.tobytes()
        header = struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54)
        header += struct.pack('<IiiHHIIiiII', 40, w, -h, 1, 32, 0, len(pixels), 0, 0, 0, 0)
        path = self.root / f'frame-{sequence}.bmp'
        path.write_bytes(header + pixels)
        self.source = {'path': str(path), 'sourceRoot': str(self.root),
            'width': w, 'height': h, 'frameSequence': sequence,
            'capturedAt': f'2026-09-30T10:00:{sequence:02d}Z',
            'pixelSha256': hashlib.sha256(pixels).hexdigest(),
            'receivedAt': time.monotonic(), 'scope': copy.deepcopy(self.scope)}
        return frame

    def test_original_gate_rejects_overwrite_and_real_store_failure(self):
        self.frame(163, 1)
        self.assertTrue(self.intake.start_manual()['ok'])
        original = Path(self.source['path']).read_bytes()
        Path(self.source['path']).write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        # Each attempt models one fresh delivery; the 2s freshness window must
        # not be spent by the fixture's own disk work on a loaded machine.
        self.source['receivedAt'] = time.monotonic()
        bad = self.intake.capture_manual_page()
        self.assertFalse(bad['ok']); self.assertEqual(bad['pageCount'], 0)
        Path(self.source['path']).write_bytes(original)
        self.source['receivedAt'] = time.monotonic()
        with patch('native_trial_drafts.os.replace', side_effect=OSError('actual storage failure')):
            failed = self.intake.capture_manual_page()
        self.assertFalse(failed['ok']); self.assertEqual(failed['pageCount'], 0)
        self.source['receivedAt'] = time.monotonic()
        accepted = self.intake.capture_manual_page()
        self.assertTrue(accepted['ok'], accepted)
        page = self.intake.pages_copy()[0]
        self.assertTrue(validate_settlement_evidence_original_v2(page['descriptor'])[0])
        self.assertTrue(self.intake.evidence_store.verify(page['descriptor'])['ok'])
        self.assertEqual(page['nativeSource']['observationSessionId'], self.scope['observationSessionId'])
        manifest = next((self.store.root / 'warehouse-intake').glob('*.json'))
        self.assertEqual(json.loads(manifest.read_text(encoding='utf-8'))['pages'], self.intake.pages_copy())

    def test_scope_duplicate_and_limits_fail_closed(self):
        self.frame(163, 1)
        self.scope['scene'] = 'IN_AUCTION'
        self.assertFalse(self.intake.start_manual()['ok'])
        self.scope['scene'] = 'SETTLEMENT'
        self.assertTrue(self.intake.start_manual()['ok'])
        self.source['scope']['observationSessionId'] = 'wrong-session'
        self.assertFalse(self.intake.capture_manual_page()['ok'])
        self.source['scope'] = copy.deepcopy(self.scope)
        self.assertTrue(self.intake.capture_manual_page()['ok'])
        self.source['frameSequence'] = 2
        duplicate = self.intake.capture_manual_page()
        self.assertTrue(duplicate['duplicate']); self.assertEqual(duplicate['pageCount'], 1)
        self.frame(164, 3)
        # Page completion follows saved coverage, not an image quota: MAX_PAGES
        # stays None, so a fresh independent frame is still accepted.
        import native_warehouse_intake as intake_module
        self.assertIsNone(intake_module.MAX_PAGES)
        self.assertTrue(self.intake.capture_manual_page()['ok'])
        self.assertEqual(self.intake.presentation_payload()['segmentCount'], 2)
        self.source['receivedAt'] -= 10
        self.assertEqual(self.intake.capture_manual_page()['reason'], 'NO_FRESH_NATIVE_FRAME')

    def test_cancelled_processing_cannot_persist_or_replace_next_session(self):
        self.frame(163, 1); self.assertTrue(self.intake.start_manual()['ok'])
        self.assertTrue(self.intake.capture_manual_page()['ok'])
        before = self.store.history_path.read_bytes()
        entered, release = threading.Event(), threading.Event()
        real = WarehouseCaptureHost._process_saved_pages
        def delayed(host, *args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(4))
            return real(host, *args, **kwargs)
        with patch('warehouse_capture_production.get_production_placement_resolver', return_value=None), \
             patch.object(WarehouseCaptureHost, '_process_saved_pages', delayed):
            self.assertTrue(self.intake.finish_manual_capture()['ok'])
            self.assertTrue(entered.wait(2))
            self.assertTrue(self.intake.cancel_manual_capture()['ok'])
            self.assertFalse(self.intake.start_manual()['ok'])
            release.set(); self.intake.wait_processing(10)
        self.assertEqual(before, self.store.history_path.read_bytes())
        self.assertEqual(self.intake.presentation_payload()['state'], 'CANCELLED')
        cold = NativeTrialDraftStore(self.store.history_path)
        self.assertEqual(cold.list_raw_partial_warehouse_archives()[0]['pageCount'], 1)
        raw = cold.read_raw_partial_warehouse_page(self.intake._session_id, 0)
        self.assertTrue(raw['ok'], raw)
        self.assertEqual(raw['coverageStatus'], 'COVERAGE_UNPROVEN')
        self.assertTrue(self.intake.start_manual()['ok'])
        self.assertEqual(self.intake.presentation_payload()['segmentCount'], 0)

    def test_saved_processing_survives_stop_and_new_match_without_misattribution(self):
        self.frame(163, 1); self.intake.start_manual(); self.intake.capture_manual_page()
        old_key = self.scope['recordStableKey']
        observation_snapshot = self.store.lookup(old_key)
        next_record = build_canonical_match_record_v7(match_id='next_intake_match',
            played_at='2026-10-09T10:00:00Z', lifecycle_status='DRAFT', source='manual')
        next_record['dataOrigin'] = 'live-trial'
        self.store.save_draft(next_record)
        next_before = self.store.lookup('next_intake_match')
        entered, release = threading.Event(), threading.Event()
        real = WarehouseCaptureHost._process_saved_pages
        def delayed(host, *args, **kwargs):
            entered.set(); self.assertTrue(release.wait(5))
            return real(host, *args, **kwargs)
        with patch('warehouse_capture_production.get_production_placement_resolver', return_value=None), \
             patch.object(WarehouseCaptureHost, '_process_saved_pages', delayed):
            self.assertTrue(self.intake.finish_manual_capture(termination_reason='INCOMPLETE')['ok'])
            self.assertTrue(entered.wait(2))
            self.intake._scope_provider = lambda:None
            from native_warehouse_source import NativeWarehouseSourceCoordinator
            from native_warehouse_auto_capture import NativeWarehouseAutoCapture
            source = NativeWarehouseSourceCoordinator(self.intake, send_control=lambda c: True,
                source_root_provider=lambda: self.root, timers=False)
            auto = NativeWarehouseAutoCapture(source, timers=False)
            self.assertTrue(auto.stop()['ok'])
            self.assertTrue(auto.stop()['ok'])  # Shutdown is idempotent, not a cancellation of saved work.
            self.assertEqual(self.intake._state, 'ALIGNING')
            self.intake._scope_provider = lambda:{**self.scope, 'recordStableKey':'next_intake_match'}
            release.set(); self.intake.wait_processing(15)
        self.assertEqual(self.intake.presentation_payload()['state'],'PARTIAL')
        self.assertEqual(self.store.lookup('next_intake_match'),next_before)
        self.assertEqual(self.store.lookup(old_key)['settlement']['warehouseReviewPacket']['recordStableKey'],old_key)
        manifest = json.loads((self.store.root/'warehouse-intake'/f'{self.intake._session_id}.json').read_text())
        self.assertEqual(manifest['state'],'PARTIAL')
        archived = self.store.lookup(old_key)['settlement']
        # A later observation contains no capture-owned packet. Saving it must
        # preserve the old archive and permit reopening without recognition.
        self.store.save_draft(observation_snapshot)
        saved = self.store.lookup(old_key)
        self.assertEqual(saved['settlement'].get('warehouseReviewPacket'), archived['warehouseReviewPacket'])
        self.assertEqual(saved['settlement'].get('warehousePageCount'), 1)
        self.assertEqual(saved['lifecycleStatus'], 'DRAFT')
        fresh = NativeWarehouseIntake(draft_store=self.store,
            scope_provider=lambda: {'recordStableKey': 'next_intake_match'},
            source_provider=lambda: None, auto_refine=False)
        before_reopen = self.store.history_path.read_bytes()
        with patch.object(WarehouseCaptureHost, '_process_saved_pages',
                          side_effect=AssertionError('Saved PARTIAL must not be recognized again')):
            reply = fresh.recover_saved_capture(self.intake._session_id)
        self.assertTrue(reply['ok'], reply)
        self.assertEqual(reply['reason'], 'SAVED_ARCHIVE_RESUMED')
        self.assertEqual(fresh.review_packet_copy(), archived['warehouseReviewPacket'])
        self.assertEqual(fresh.presentation_payload()['state'], 'PARTIAL')
        self.assertEqual(self.store.history_path.read_bytes(), before_reopen)
        self.assertEqual(self.store.lookup('next_intake_match'), next_before)

    def test_rejected_support_selection_keeps_raw_partial_cold_reopenable(self):
        from native_warehouse_source import NativeWarehouseSourceCoordinator

        self.frame(163, 1)
        self.assertTrue(self.intake.start_manual()['ok'])
        self.assertTrue(self.intake.capture_manual_page()['ok'])
        session = self.intake._session_id
        before = self.store.history_path.read_bytes()
        source = NativeWarehouseSourceCoordinator(self.intake,
            send_control=lambda _command: True,
            source_root_provider=lambda: self.root,
            timers=False)

        finalized = source.finish_manual_capture(termination_reason='INCOMPLETE',
            qualified_evidence_ids=['not-a-saved-support-page'])

        self.assertTrue(finalized['ok'], finalized)
        self.assertEqual(finalized['reason'], 'RAW_PARTIAL_ARCHIVED')
        manifest_path = self.store.root / 'warehouse-intake' / f'{session}.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        self.assertEqual(manifest['state'], 'PARTIAL')
        self.assertEqual(manifest['processingEvidenceIds'], [])
        self.assertEqual(len(manifest['pages']), 1)

        cold_store = NativeTrialDraftStore(self.store.history_path)
        cold = NativeWarehouseIntake(draft_store=cold_store,
            scope_provider=lambda: None, source_provider=lambda: None, auto_refine=False)
        with patch.object(WarehouseCaptureHost, '_process_saved_pages',
                          side_effect=AssertionError('Raw-only archive must not be recognized')):
            reopened = cold.recover_saved_capture(session)

        self.assertTrue(reopened['ok'], reopened)
        self.assertEqual(reopened['reason'], 'RAW_PARTIAL_ARCHIVE_RESUMED')
        self.assertEqual(cold.presentation_payload()['state'], 'PARTIAL')
        self.assertEqual(cold.presentation_payload()['coverageStatus'], 'COVERAGE_UNPROVEN')
        self.assertEqual(len(cold.pages_copy()), 1)
        archive_rows = cold_store.list_raw_partial_warehouse_archives()
        self.assertEqual(len(archive_rows), 1)
        self.assertEqual(archive_rows[0]['sessionId'], session)
        self.assertEqual(archive_rows[0]['archiveStatus'], 'RAW_PARTIAL_ARCHIVED')
        self.assertEqual(archive_rows[0]['coverageStatus'], 'COVERAGE_UNPROVEN')
        preview = cold_store.read_raw_partial_warehouse_page(session, 0)
        self.assertTrue(preview['ok'], preview)
        self.assertEqual(preview['status'], 'RAW_PARTIAL_ARCHIVED')
        self.assertEqual(preview['sourceSha256'], cold.pages_copy()[0]['nativeSource']['sha256'])
        self.assertTrue(preview['previewDataUrl'].startswith('data:image/jpeg;base64,'))
        self.assertEqual(cold_store.read_raw_partial_warehouse_page(session, 1)['status'], 'PAGE_NOT_FOUND')
        record = cold_store.lookup(self.scope['recordStableKey'])
        self.assertEqual(record['lifecycleStatus'], 'DRAFT')
        self.assertNotIn('warehouseReviewPacket', record['settlement'])
        self.assertEqual(self.store.history_path.read_bytes(), before)

    def test_alignment_pending_keeps_original_pages_reopenable(self):
        self.frame(163, 1)
        self.assertTrue(self.intake.start_manual()['ok'])
        self.assertTrue(self.intake.capture_manual_page()['ok'])
        waiting, release = threading.Event(), threading.Event()

        def pending(*args, **kwargs):
            waiting.set()
            release.wait(5)
            return {'ok': False, 'reason': 'OFFLINE_PROCESSOR_STOPPED'}

        with patch.object(WarehouseCaptureHost, '_process_saved_pages', side_effect=pending):
            try:
                self.assertTrue(self.intake.finish_manual_capture(termination_reason='INCOMPLETE')['ok'])
                self.assertTrue(waiting.wait(3))
                cold = NativeTrialDraftStore(self.store.history_path)
                archives = cold.list_raw_partial_warehouse_archives()
                self.assertEqual(len(archives), 1, 'Pending recognition cannot hide saved SOURCE originals')
                page = cold.read_raw_partial_warehouse_page(self.intake._session_id, 0)
                self.assertTrue(page['ok'], page)
                self.assertEqual(page['coverageStatus'], 'COVERAGE_UNPROVEN')
                self.assertEqual(page['sourceSha256'], self.intake.pages_copy()[0]['nativeSource']['sha256'])
                # Reading originals neither finishes alignment nor adds facts.
                self.assertEqual(self.intake._state, 'ALIGNING')
                self.assertNotIn('warehouseReviewPacket', cold.lookup(self.scope['recordStableKey'])['settlement'])
            finally:
                release.set()
                self.intake.wait_processing(3)

    def test_empty_support_selection_archives_raw_partial(self):
        from native_warehouse_source import NativeWarehouseSourceCoordinator

        self.frame(163, 1)
        self.assertTrue(self.intake.start_manual()['ok'])
        self.assertTrue(self.intake.capture_manual_page()['ok'])
        source = NativeWarehouseSourceCoordinator(self.intake,
            send_control=lambda _command: True,
            source_root_provider=lambda: self.root,
            timers=False)

        finalized = source.finish_manual_capture(termination_reason='INCOMPLETE',
            qualified_evidence_ids=[])

        self.assertTrue(finalized['ok'], finalized)
        self.assertEqual(finalized['reason'], 'RAW_PARTIAL_ARCHIVED')
        manifest = json.loads((self.store.root / 'warehouse-intake' /
            f"{self.intake._session_id}.json").read_text(encoding='utf-8'))
        self.assertEqual(manifest['state'], 'PARTIAL')
        self.assertEqual(manifest['processingEvidenceIds'], [])
        self.assertEqual(self.intake.presentation_payload()['coverageStatus'], 'COVERAGE_UNPROVEN')

    def test_processing_exception_after_stop_has_durable_error(self):
        self.frame(163,1); self.intake.start_manual(); self.intake.capture_manual_page()
        with patch.object(WarehouseCaptureHost,'_process_saved_pages',side_effect=ValueError('broken original')):
            self.intake._scope_provider=lambda:None
            self.assertTrue(self.intake.finish_manual_capture()['ok'])
            self.intake.wait_processing(10)
        manifest=json.loads((self.store.root/'warehouse-intake'/f'{self.intake._session_id}.json').read_text())
        self.assertEqual(manifest['state'],'ERROR')
        self.assertIn('broken original',manifest['terminationReason'])

    def test_processing_timeout_revokes_worker_and_keeps_saved_session_recoverable(self):
        self.frame(163,1); self.intake.start_manual(); self.intake.capture_manual_page()
        entered, release = threading.Event(), threading.Event()
        real = WarehouseCaptureHost._process_saved_pages
        def delayed(host,*args,**kwargs):
            entered.set(); self.assertTrue(release.wait(5))
            return real(host,*args,**kwargs)
        before = self.store.history_path.read_bytes()
        session, generation = self.intake._session_id, self.intake._generation
        with patch.object(WarehouseCaptureHost,'_process_saved_pages',delayed):
            self.intake.finish_manual_capture(termination_reason='INCOMPLETE')
            self.assertTrue(entered.wait(2))
            self.intake.fail_processing('PROCESSING_TIMEOUT')
            release.set(); self.intake.wait_processing(10)
        path = self.store.root/'warehouse-intake'/f'{session}.json'
        manifest = json.loads(path.read_text())
        self.assertEqual(manifest['state'],'ERROR')
        self.assertEqual(manifest['terminationReason'],'PROCESSING_TIMEOUT')
        self.assertEqual(manifest['generation'],generation)
        self.assertEqual(self.store.history_path.read_bytes(),before)
        raw = path.read_bytes()
        self.assertFalse(self.intake.recover_saved_capture('invalid')['ok'])
        self.assertEqual(path.read_bytes(),raw)
        self.assertTrue(self.intake.recover_saved_capture(session)['ok'])
        self.intake.wait_processing(15)
        self.assertEqual(self.intake._state,'PARTIAL')

    def test_saved_refinement_auto_queue_cancel_and_resume_remain_on_old_match(self):
        from native_warehouse_refinement import SavedWarehouseRefinement
        from main_window import MainWindowBridge, OverlayVisibilityController
        class Overlay:
            Visible = True
        entered = threading.Event()
        processes = []
        class WaitingProcess:
            def __init__(process,*args,**kwargs):
                process.returncode = None; processes.append(process); entered.set()
            def poll(process): return process.returncode
            def kill(process): process.returncode = -1
            def wait(process): return process.returncode
        self.intake._refiner = SavedWarehouseRefinement(self.intake)
        bridge = MainWindowBridge(OverlayVisibilityController(Overlay()),warehouse_capture_host=self.intake)
        self.frame(163,1); self.intake.start_manual(); self.intake.capture_manual_page()
        session = self.intake._session_id
        with patch('native_warehouse_refinement.subprocess.Popen',WaitingProcess):
            self.intake.finish_manual_capture(termination_reason='INCOMPLETE')
            self.intake.wait_processing(10)
            self.assertTrue(entered.wait(2))  # Archive automatically queues refinement.
            self.intake._scope_provider = lambda:None
            self.assertTrue(self.intake.end_collection('OBSERVATION_ENDED')['ok'])
            next_record = build_canonical_match_record_v7(match_id='next_refinement_match',
                played_at='2026-10-09T10:00:00Z',lifecycle_status='DRAFT',source='manual')
            next_record['dataOrigin'] = 'live-trial'; self.store.save_draft(next_record)
            next_before = self.store.lookup('next_refinement_match')
            self.intake._scope_provider = lambda:{**self.scope,'recordStableKey':'next_refinement_match'}
            self.assertTrue(self.intake.start_manual()['ok'])
            reply = bridge.dispatch({'action':'cancel_warehouse_refinement','sessionId':session,
                'recordId':self.scope['recordStableKey']})
            self.assertTrue(reply['warehouseCaptureCommand']['ok'])
            self.intake.wait_refinement(3)
            self.assertEqual(processes[0].returncode,-1)
            self.assertEqual(self.intake.refinement_payload(self.scope['recordStableKey'])['state'],'CANCELLED')
            # A fresh owner preserves deliberate cancellation; explicit UI resume requeues.
            fresh = NativeWarehouseIntake(draft_store=self.store,scope_provider=lambda:None,source_provider=lambda:None)
            fresh.resume_pending()
            self.assertEqual(fresh.refinement_payload(self.scope['recordStableKey'])['state'],'CANCELLED')
            with patch('native_warehouse_refinement.REFINEMENT_SECONDS',.03):
                reply = bridge.dispatch({'action':'resume_warehouse_refinement','sessionId':session,
                    'recordId':self.scope['recordStableKey']})
                self.assertTrue(reply['warehouseCaptureCommand']['ok'])
                self.intake.wait_refinement(3)
            status = self.intake.refinement_payload(self.scope['recordStableKey'])
            self.assertEqual(status['state'],'FAILED')
            self.assertIn('REFINEMENT_TIME_LIMIT',status['reason'])
            self.assertEqual(self.store.lookup('next_refinement_match'),next_before)
            old = self.store.lookup(self.scope['recordStableKey'])
            self.assertEqual(old['settlement']['warehouseReviewPacket']['schemaVersion'],'warehouse-review-packet.v1')
            self.assertEqual(old['lifecycleStatus'],'DRAFT')
            self.assertEqual(self.intake._binding['recordStableKey'],'next_refinement_match')
            manifest = json.loads((self.store.root/'warehouse-intake'/f'{session}.json').read_text())
            self.assertEqual(manifest['state'],'PARTIAL')
            self.assertTrue(manifest['placementRefinementPending'])

    def test_completed_result_is_recovered_before_starting_another_worker(self):
        from native_warehouse_refinement import SavedWarehouseRefinement, fingerprint
        self.frame(163, 1); self.intake.start_manual(); self.intake.capture_manual_page()
        self.intake.finish_manual_capture(termination_reason='INCOMPLETE'); self.intake.wait_processing(10)
        session = self.intake._session_id
        path = self.store.root/'warehouse-intake'/f'{session}.json'
        manifest = json.loads(path.read_text('utf-8'))
        saved = self.store.lookup(self.scope['recordStableKey'])['settlement']
        work = self.store.root/'warehouse-refinement'/session
        work.mkdir(parents=True, exist_ok=True)
        token = 'a'*32
        result = {'jobId':token, 'inputFingerprint':fingerprint(manifest),
            'evidence':{'review_units':saved['reviewUnits'],
                        'identity_review':saved['warehouseIdentityReview'],
                        'review_packet':saved['warehouseReviewPacket']},
            'summary':{'fixture':'completed-before-main-exited'}}
        (work/(token+'.json')).write_text(json.dumps(result), encoding='utf-8')
        manifest['placementRefinementPending'] = True
        manifest['refinement'] = {'state':'FAILED', 'jobId':'b'*32,
            'inputFingerprint':fingerprint(manifest), 'reason':'REFINEMENT_TIME_LIMIT:NO_PROGRESS'}
        path.write_text(json.dumps(manifest), encoding='utf-8')
        fresh = NativeWarehouseIntake(draft_store=self.store, scope_provider=lambda:None,
            source_provider=lambda:None)
        with patch('native_warehouse_refinement.subprocess.Popen', side_effect=AssertionError('must reuse saved result')):
            fresh.resume_pending()
            fresh.wait_refinement(3)
            self.assertEqual(fresh.refinement_payload(self.scope['recordStableKey'])['state'], 'COMPLETE')
            self.assertFalse(fresh.refinement_payload(self.scope['recordStableKey'])['pending'])
            fresh.resume_pending()
            self.assertEqual(fresh.resume_refinement(session)['reason'], 'REFINEMENT_COMPLETE')

    def test_interrupted_refinement_is_resumed_on_the_next_start(self):
        from native_warehouse_refinement import SavedWarehouseRefinement
        entered = threading.Event()
        processes = []
        class WaitingProcess:
            def __init__(process,*args,**kwargs):
                process.returncode = None; processes.append(process); entered.set()
            def poll(process): return process.returncode
            def kill(process): process.returncode = -1
            def wait(process): return process.returncode
        self.intake._refiner = SavedWarehouseRefinement(self.intake)
        self.frame(163,1); self.intake.start_manual(); self.intake.capture_manual_page()
        session = self.intake._session_id
        manifest_path = self.store.root/'warehouse-intake'/f'{session}.json'
        with patch('native_warehouse_refinement.subprocess.Popen',WaitingProcess):
            self.intake.finish_manual_capture(termination_reason='INCOMPLETE')
            self.intake.wait_processing(10)
            self.assertTrue(entered.wait(2))
            running = json.loads(manifest_path.read_text('utf-8'))
            self.assertEqual(running['refinement']['state'],'RUNNING')
            self.assertEqual(len(processes),1)
            interrupted_token = running['refinement']['jobId']
            # A later manifest write must not clear the marker while it runs.
            self.intake._write_manifest(self.intake._pages)
            self.assertTrue(json.loads(manifest_path.read_text('utf-8'))['placementRefinementPending'])
            # The process dies here: only the manifest knows the job existed.
            entered.clear()
            fresh = NativeWarehouseIntake(draft_store=self.store,scope_provider=lambda:None,
                source_provider=lambda:None)
            reply = fresh.resume_pending()
            self.assertEqual(reply['queued'],1)
            self.assertTrue(entered.wait(2))
            resumed = json.loads(manifest_path.read_text('utf-8'))
            self.assertEqual(resumed['refinement']['state'],'RUNNING')
            self.assertEqual(resumed['refinement']['jobId'],interrupted_token)
            self.assertEqual(len(processes),2)
            fresh._refiner.cancel(session); fresh.wait_refinement(3)
            self.intake._refiner.cancel(session); self.intake.wait_refinement(3)

    def test_refinement_publishes_frozen_old_archive_after_new_session_starts(self):
        from native_warehouse_refinement import SavedWarehouseRefinement, fingerprint
        self.frame(163,1); self.intake.start_manual(); self.intake.capture_manual_page()
        self.intake.finish_manual_capture(termination_reason='INCOMPLETE'); self.intake.wait_processing(10)
        session = self.intake._session_id; old_key = self.scope['recordStableKey']
        old = self.store.lookup(old_key)['settlement']
        entered, release = threading.Event(), threading.Event()
        class ReadyProcess:
            def __init__(process,command,**kwargs):
                process.returncode = None
                process.log = kwargs['stdout']
                root, sid, token = Path(command[-3]),command[-2],command[-1]
                manifest = json.loads((root/'warehouse-intake'/f'{sid}.json').read_text())
                output = root/'warehouse-refinement'/sid/(token+'.json')
                output.write_text(json.dumps({'jobId':token,'inputFingerprint':fingerprint(manifest),
                    'evidence':{'review_units':old['reviewUnits'],'identity_review':old['warehouseIdentityReview'],
                                'review_packet':old['warehouseReviewPacket']},'summary':{'fixture':'no-new-identities'}}))
                entered.set()
            def poll(process):
                if not release.is_set():
                    process.log.write('completed another finite matching query\n')
                    process.log.flush()
                if release.is_set(): process.returncode = 0
                return process.returncode
            def wait(process): return process.returncode
            def kill(process): process.returncode = -1
        self.intake._refiner = SavedWarehouseRefinement(self.intake)
        with patch('native_warehouse_refinement.subprocess.Popen',ReadyProcess), \
                patch('native_warehouse_refinement.REFINEMENT_SECONDS',.15):
            self.assertTrue(self.intake.resume_refinement(session)['ok']); self.assertTrue(entered.wait(2))
            # A working job may outlive the inactivity interval; elapsed total
            # time alone must not discard its eventual saved result.
            self.assertFalse(release.wait(.4))
            self.assertEqual(self.intake.refinement_payload(old_key)['state'],'RUNNING')
            next_record = build_canonical_match_record_v7(match_id='after_refinement',
                played_at='2026-10-09T10:00:00Z',lifecycle_status='DRAFT',source='manual')
            next_record['dataOrigin'] = 'live-trial'; self.store.save_draft(next_record)
            before = self.store.lookup('after_refinement')
            self.intake._scope_provider = lambda:{**self.scope,'recordStableKey':'after_refinement'}
            self.assertTrue(self.intake.start_manual()['ok'])
            release.set(); self.intake.wait_refinement(10)
        self.assertEqual(self.store.lookup('after_refinement'),before)
        status = self.intake.refinement_payload(old_key)
        self.assertEqual(status['state'],'COMPLETE'); self.assertFalse(status['pending'])
        self.assertIsNone(self.intake.review_packet_copy())
        self.assertEqual(self.intake._binding['recordStableKey'],'after_refinement')

    def test_two_fixture_pages_use_same_manual_pipeline_and_isolated_history(self):
        frames = [self.frame(163, 1)]
        self.assertTrue(self.intake.start_manual()['ok'])
        self.assertTrue(self.intake.capture_manual_page()['ok'])
        frames.append(self.frame(164, 2))
        self.assertTrue(self.intake.capture_manual_page()['ok'])
        sources_before = self.store.lookup(self.scope['recordStableKey'])['auctionEvidence']['nativeObservation']['sourceFrames']
        with patch('warehouse_capture_production.get_production_placement_resolver', return_value=None):
            self.assertTrue(self.intake.finish_manual_capture()['ok'])
            self.intake.wait_processing(15)
            other = NativeTrialDraftStore(self.root / 'comparison/canonical-history.json')
            other.save_draft(self.store.lookup(self.scope['recordStableKey']))
            host = WarehouseCaptureHost(store_factory=lambda: self.intake.evidence_store, driver_available=False)
            result = host._process_saved_pages(self.scope['recordStableKey'],
                [p['descriptor'] for p in self.intake.pages_copy()],
                history_store=other._store())
        view = self.intake.presentation_payload()
        self.assertEqual(view['coverageStatus'], result['coverageStatus'])
        self.assertEqual(view['coverageStatus'], 'PARTIAL')
        record = self.store.lookup(self.scope['recordStableKey'])
        packet = record['settlement']['warehouseReviewPacket']
        self.assertEqual(len(packet['segments']), 2)
        self.assertEqual(record['auctionEvidence']['nativeObservation']['sourceFrames'], sources_before)
        self.assertEqual(record['lifecycleStatus'], 'DRAFT')
        self.assertEqual(packet['warehouseCoverage'], result['packet']['warehouseCoverage'])
        from main_window import MainWindowBridge, OverlayVisibilityController
        from warehouse_identity_review_session import WarehouseIdentityReviewSession
        from canonical_history_store import CanonicalHistoryStore
        class Overlay:
            Visible = True
            def Show(self): self.Visible = True
            def Hide(self): self.Visible = False
        normal = CanonicalHistoryStore(self.root / 'normal-history.json')
        normal_record = build_canonical_match_record_v7(match_id='normal_review_record',
            played_at='2026-09-30T10:00:00Z', lifecycle_status='DRAFT', source='manual')
        normal.persist_record_transactional(normal_record, is_finalized=False)
        normal_bytes = normal.db_path.read_bytes()
        history = WarehouseReviewHistoryRouter(normal, self.intake)
        session = WarehouseIdentityReviewRouter(WarehouseIdentityReviewSession(), self.intake, history)
        bridge = MainWindowBridge(OverlayVisibilityController(Overlay()),
            warehouse_capture_host=WarehouseCaptureRouter(host, self.intake, lambda: True),
            warehouse_identity_review_session=session, warehouse_identity_review_history_store=history)
        opened = bridge.dispatch({'action': 'warehouse_identity_review', 'op': 'open'})
        self.assertTrue(opened['warehouseIdentityReview']['available'], opened)
        self.assertIs(session._active, session.native)
        self.assertEqual(history.lookup('normal_review_record')['id'], 'normal_review_record')
        self.assertEqual(normal_bytes, normal.db_path.read_bytes())

    def test_existing_bridge_routes_native_manual_commands_without_legacy_capture(self):
        from main_window import MainWindowBridge, OverlayVisibilityController
        class Overlay:
            Visible = True
            def Show(self): self.Visible = True
            def Hide(self): self.Visible = False
        legacy = WarehouseCaptureHost(input_execution_allowed=lambda: False)
        router = WarehouseCaptureRouter(legacy, self.intake, lambda: True)
        bridge = MainWindowBridge(OverlayVisibilityController(Overlay()), warehouse_capture_host=router)
        with patch.object(legacy, 'capture_manual_page', side_effect=AssertionError('legacy capture forbidden')):
            self.assertTrue(bridge.dispatch({'action': 'start_warehouse_manual_takeover'})['warehouseCaptureCommand']['ok'])
            self.frame(163, 1)
            # Client paths/descriptors are ignored by the existing command bridge.
            result = bridge.dispatch({'action': 'capture_warehouse_manual_page', 'path': 'untrusted', 'descriptor': {}})
            self.assertTrue(result['warehouseCaptureCommand']['ok'], result)
            self.assertEqual(result['warehouseCapture']['segmentCount'], 1)
            self.assertFalse(router.prepare()['ok'])

    def test_manifest_atomic_failure_and_encoded_cap_do_not_accept_page(self):
        import os
        self.frame(163, 1); self.assertTrue(self.intake.start_manual()['ok'])
        real_replace = os.replace
        def fail_manifest(src, dst):
            if Path(dst).parent.name == 'warehouse-intake':
                raise OSError('manifest atomic save failed')
            return real_replace(src, dst)
        with patch('native_warehouse_intake.os.replace', side_effect=fail_manifest):
            self.assertFalse(self.intake.capture_manual_page()['ok'])
        self.assertEqual(self.intake.pages_copy(), [])
        self.source['receivedAt'] = time.monotonic()
        with patch('native_warehouse_intake.MAX_ENCODED_BYTES', 1):
            self.assertEqual(self.intake.capture_manual_page()['reason'], 'LIMIT_REACHED')
        self.assertEqual(self.intake.pages_copy(), [])

if __name__ == '__main__':
    unittest.main()
