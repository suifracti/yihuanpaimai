"""New delivery contract only. Inert pixels/events; no window or desktop capture."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import queue
import struct
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core'), str(ROOT)]
from native_capture_delivery import DELIVERY, validate_delivery, independent_support
from native_trial_drafts import NativeTrialDraftStore
from native_warehouse_intake import NativeWarehouseIntake
from native_warehouse_source import NativeWarehouseSourceCoordinator, SCHEMA_V2
from native_warehouse_auto_capture import NativeWarehouseAutoCapture
from canonical_match_record import build_canonical_match_record_v7


def sample(ns):
    return {'rawTicks': ns // 100, 'frequencyHz': 10_000_000, 'nanoseconds': ns,
            'wholeSeconds': ns // 1_000_000_000, 'remainderTicks': ns // 100 % 10_000_000}


def proof(seq=1, request=10_000_000_000, *, session='offline', previous=0):
    compared = request + 100_000
    source = compared + 10_000_000  # Deliberately future, no added tolerance.
    return {'schemaVersion': 'capture-delivery-proof.v2', 'capturePolicy': DELIVERY,
            'boundaryKind': 'retained-pool-buffers.v1', 'poolBufferCount': 2,
            'drainTakeCount': 3, 'boundaryHeldCount': 2, 'releaseCompletedNs': request + 100,
            'captureId': f'{session}/1/{seq}', 'observationSessionId': session,
            'poolEpoch': 1, 'acquisitionSequence': seq, 'requestNs': request,
            'deadlineNs': request + 5_000_000_000, 'emptyBoundaryNs': request + 100,
            'dequeueBeforeNs': request + 200, 'dequeueAfterNs': request + 300,
            'getterBefore': sample(request + 400), 'comparison': sample(compared),
            'sourceTicks': source // 100, 'repeatedSourceTicks': source // 100, 'readbackSourceTicks': source // 100,
            'sourceTimestampNs': source, 'previousMarkerNs': previous,
            'readbackBeforeNs': compared + 100, 'readbackCompletedNs': compared + 200,
            'originStatus': 'FUTURE_AT_READ', 'originStrictQualified': False,
            'sourceMarkerProgress': True, 'deliveryQualified': True}


def advice_qualification(qualified):
    return {'qualified': qualified, 'sourceMarkerProgress': True,
            'supportSummaryPresent': True, 'supportActionQualified': qualified,
            'samePoolEpoch': True, 'readbackNotAfterPublication': True,
            'readbackWithinTwoSeconds': True, 'sceneRoiMatches': True,
            'observationRoiMatches': True, 'warehouseRoiMatches': True,
            'failureReasons': [] if qualified else ['SUPPORT_ACTION_UNQUALIFIED']}


def delivery_observation(fixture, sequence, scene, *, advice=True, close=False, match=None, target=None):
    ns = fixture.ns
    event = fixture.frame(sequence)
    delivery_proof = proof(sequence, request=99_000_000_000 + sequence * 1_000_000,
                           session='background-session')
    event['captureFreshnessPolicy'] = DELIVERY
    event['frame'].update(deliveryProof=delivery_proof,
        sourceTimestampNs=delivery_proof['sourceTimestampNs'],
        capturedAtNs=delivery_proof['readbackCompletedNs'], deliveryAgeMs=999,
        currentAdviceQualified=advice,
        currentAdviceQualification=advice_qualification(advice))
    event['frame'].pop('freshnessMs', None)
    event['perception'].update(scene=scene, inAuction=scene == 'IN_AUCTION')
    event['pipelineContext'].update(scene=scene, inAuction=scene == 'IN_AUCTION', settlementReady=close)
    event['currentMatch']['factsRevision'] = sequence
    event['currentMatch']['roundNo'] = 1
    event['lastFrame']['matchGeneration'] = ns['CURRENT_MATCH']._seq
    if match:
        event['currentMatch']['id'] = match
    if target is not None:
        event['target'] = target
    event['frame']['currentAdviceQualification'].update(
        schemaVersion='delivery-facts-computation.v1', originalCaptureId=delivery_proof['captureId'],
        originalReadbackNs=delivery_proof['readbackCompletedNs'])
    event['lastFrame'].update(captureTimestampNs=delivery_proof['readbackCompletedNs'],
        captureProof={'deliveryProof': copy.deepcopy(delivery_proof)},
        stateMatchId=event['currentMatch']['id'], stateFactsRevision=sequence, scene=scene)
    return event


def prepare_delivery_fixture(test_case):
    from tests.test_native_warehouse_auto_capture import NativeAutomaticTriggerTests
    from tests.test_native_background_observation import _target
    fixture = NativeAutomaticTriggerTests('runTest')
    fixture.setUp()
    test_case.addCleanup(fixture.doCleanups)
    ns = fixture.ns
    ns['_NATIVE_CAPTURE_POLICY'] = DELIVERY
    ns['_native_observation_event']({'type': 'native_observation', 'sourceKind': 'native_wgc',
        'inputActions': False, 'formalHistoryWriter': False,
        'observationSessionId': 'background-session', 'observationWindowMode': 'background-readonly',
        'captureFreshnessPolicy': DELIVERY, 'status': 'READY',
        'details': {'target': _target(), 'warehouseSourceBeforeBillFrozen': True}})
    return fixture


class DeliveryTests(unittest.TestCase):
    def test_computation_lease_binds_fact_version_and_preserves_manual_correction(self):
        fixture = prepare_delivery_fixture(self)
        ns = fixture.ns
        first = delivery_observation(fixture, 1, 'IN_AUCTION')
        first['frame']['currentAdviceQualification'].update(
            sceneRoiMatches=False, observationRoiMatches=False, warehouseRoiMatches=False)
        ns['_native_observation_event'](first)
        payload = copy.deepcopy(ns['LATEST_PAYLOAD'])
        self.assertEqual(payload['observationStatus'], 'FRAME')
        self.assertTrue(ns['_native_solver_lease_matches'](payload))
        self.assertIsNone(payload['computationQualification']['sourceAbsoluteAgeMs'])
        self.assertFalse(payload['computationQualification']['automaticBidExecutionQualified'])
        for mismatch in ({'round': 2}, {'factsRevision': 0}, {'engineFactsRevision': 0},
                         {'matchId': 'other-match'}, {'observationSessionId': 'old-session'},
                         {'target': {**payload['target'], 'targetPid': 999}}):
            self.assertFalse(ns['_native_solver_lease_matches']({**payload, **mismatch}), mismatch)
        wrong_original = copy.deepcopy(payload)
        wrong_original['observationFrameBinding']['stateFactsRevision'] = 0
        self.assertIsNone(ns['_native_accept_observation_locked'](wrong_original))
        self.assertEqual(wrong_original['computationRejection'], 'FACT_SOURCE_FRAME_BINDING_MISMATCH')
        false_qualification = copy.deepcopy(payload)
        false_qualification['currentAdviceQualification']['qualified'] = False
        self.assertIsNone(ns['_native_accept_observation_locked'](false_qualification))

        ns['CURRENT_MATCH'].apply_facts({'q': 19}, source='manual', intent='confirm')
        self.assertFalse(ns['_native_solver_lease_matches'](payload), 'manual change must retire old result')
        corrected = delivery_observation(fixture, 2, 'IN_AUCTION')
        corrected['currentMatch']['q'] = 17  # Worker OCR cannot overwrite Main's confirmed correction.
        ns['_native_observation_event'](corrected)
        self.assertEqual(ns['CURRENT_MATCH'].facts['q'], 19)
        newest = copy.deepcopy(ns['LATEST_PAYLOAD'])
        self.assertTrue(ns['_native_solver_lease_matches'](newest))
        self.assertFalse(ns['_native_solver_lease_matches'](payload))
        fixture.clock[0] += 31_000_000_000
        self.assertFalse(ns['_native_solver_lease_matches'](newest))
        self.assertIsNone(ns['_native_accept_observation_locked'](copy.deepcopy(newest)))

    def test_main_delivery_lifecycle_auction_scroll_observation_settlement_once_and_next_match(self):
        fixture = prepare_delivery_fixture(self)
        ns = fixture.ns

        def event(sequence, scene, match=None):
            # This is an Engine event stream; its revisions advance independently
            # of Main's projection resets when a new match is accepted.
            return delivery_observation(fixture, sequence, scene, close=sequence == 4, match=match)

        # A stand-alone settlement has no current-match auction chain, so no auto input lease.
        with patch('scene_anchors.settlement_title_visible', return_value=True):
            unanchored = event(1, 'SETTLEMENT')
            unanchored['frame']['currentAdviceQualified'] = False
            unanchored['frame']['currentAdviceQualification'] = advice_qualification(False)
            ns['_native_source_observation_notice'](unanchored)
            self.assertEqual(fixture.source.actions, [])
            notice = ns['_NATIVE_AUTO_TRIGGER_STATUS']
            self.assertEqual(notice['reasonCodes'], ['AUCTION_ANCHOR_MISSING'])
            self.assertIn('未建立同局对局锚点', notice['reasonText'])
            self.assertEqual(notice['sourceQualification']['currentAdviceQualification']['failureReasons'],
                             ['SUPPORT_ACTION_UNQUALIFIED'])
            self.assertEqual(notice['matchId'], ns['CURRENT_MATCH'].id)
            ns['_native_source_observation_notice'](event(2, 'IN_AUCTION'))
            ns['_native_source_observation_notice'](event(3, 'IN_AUCTION'))  # manual viewport motion is normal observation
            self.assertEqual(fixture.source.actions, [])
            ns['_native_source_observation_notice'](delivery_observation(
                fixture, 4, 'SETTLEMENT', advice=False, close=True))
            self.assertEqual(fixture.source.actions, [('OPEN', True)])
            fixture.auto.stop()
            ns['_native_source_observation_notice'](delivery_observation(
                fixture, 5, 'SETTLEMENT', advice=False, close=True))
            self.assertEqual(sum(x[0] == 'OPEN' for x in fixture.source.actions), 1)
            retired = event(6, 'SETTLEMENT')
            ns['_native_source_observation_notice'](event(7, 'AUCTION_LOBBY', 'next-match'))
            ns['_native_source_observation_notice'](event(8, 'IN_AUCTION', 'next-match'))
            ns['_native_source_observation_notice'](event(9, 'SETTLEMENT', 'next-match'))
            self.assertEqual(sum(x[0] == 'OPEN' for x in fixture.source.actions), 2,
                {'scope': ns['_native_warehouse_intake_scope'](), 'anchor': ns['_NATIVE_DELIVERY_ANCHORED_MATCH'],
                 'captureScope': (ns.get('_NATIVE_WAREHOUSE_FRAME_LEASE') or {}).get('scope'),
                 'last': {k: ns['LATEST_PAYLOAD'].get(k) for k in ('matchId','matchGeneration','sourceMatchGeneration','scene','currentAdviceQualified')},
                 'actions': fixture.source.actions, 'reason': fixture.auto._reason,
                 'health': ns['LATEST_PAYLOAD'].get('visionHealth'), 'sequence': ns['_NATIVE_OBSERVATION_SEQUENCE'],
                 'logs': str(ns['log_stage'].call_args_list[-8:])})
            actions = copy.deepcopy(fixture.source.actions)
            ns['_native_source_observation_notice'](retired)
            self.assertEqual(fixture.source.actions, actions)

    def test_delivery_postclose_probe_starts_on_current_evidence_without_advice_gate(self):
        from native_warehouse_source import SCHEMA_V2
        fixture = prepare_delivery_fixture(self)
        ns = fixture.ns
        with patch('scene_anchors.settlement_title_visible', return_value=True):
            ns['_native_source_observation_notice'](delivery_observation(fixture, 1, 'IN_AUCTION'))
            self.assertEqual(ns['_NATIVE_DELIVERY_ANCHORED_MATCH'], ns['CURRENT_MATCH'].id)
            fixture.install_trigger_watch_adapter()
            fixture.scroll.side_effect = [{'scrollState': 'MIDDLE'}, {'scrollState': 'TOP'}]
            close = delivery_observation(fixture, 2, 'SETTLEMENT', advice=False, close=True)
            close['frame']['settlementBusinessClosed'] = True
            close['frame']['settlementDeadlineNs'] = fixture.clock[0] + 70_000_000_000
            ns['_native_source_observation_notice'](close)
            self.assertIsNotNone(fixture.watch)
            self.assertEqual(fixture.source.actions, [])

            probe = fixture.trigger_probe_event(3)
            probe['schemaVersion'] = SCHEMA_V2
            probe['capturePolicy'] = DELIVERY
            probe['details']['deliveryProof'] = copy.deepcopy(close['frame']['deliveryProof'])
            ns['_native_source_evidence_event'](probe)
        self.assertEqual(fixture.source.actions, [('OPEN', True)])
        qualification = ns['_NATIVE_AUTO_TRIGGER_STATUS']['sourceQualification']
        self.assertFalse(qualification['adviceQualificationEvaluated'])

    def test_business_close_after_admission_late_frame_and_durable_attempt_do_not_duplicate(self):
        fixture = prepare_delivery_fixture(self)
        ns = fixture.ns
        with patch('scene_anchors.settlement_title_visible', return_value=True):
            ns['_native_source_observation_notice'](delivery_observation(fixture, 1, 'IN_AUCTION'))
            # The source is admitted before the Engine publishes its close boundary.
            ns['_native_source_observation_notice'](delivery_observation(
                fixture, 2, 'SETTLEMENT', advice=False, close=False))
            self.assertEqual(fixture.source.actions, [('OPEN', True)])
            # The final business frame carries the close; an older late callback is then dropped.
            ns['_native_source_observation_notice'](delivery_observation(
                fixture, 3, 'SETTLEMENT', advice=False, close=True))
            late = delivery_observation(fixture, 2, 'SETTLEMENT', advice=False, close=True)
            ns['_native_source_observation_notice'](late)
            self.assertEqual(sum(action[0] == 'OPEN' for action in fixture.source.actions), 1)
            fixture.auto.stop()
            ns['_AUTO_CAPTURE_ATTEMPTED_KEYS'].clear()
            ns['_native_source_observation_notice'](delivery_observation(
                fixture, 4, 'SETTLEMENT', advice=False, close=True))
            self.assertEqual(sum(action[0] == 'OPEN' for action in fixture.source.actions), 1)

    def test_scene_identity_and_delivery_marker_mismatches_do_not_start_source(self):
        from tests.test_native_background_observation import _target
        for rejected in ('scene', 'identity', 'marker'):
            with self.subTest(rejected=rejected):
                fixture = prepare_delivery_fixture(self)
                ns = fixture.ns
                ns['_native_source_observation_notice'](delivery_observation(fixture, 1, 'IN_AUCTION'))
                if rejected == 'scene':
                    event = delivery_observation(fixture, 2, 'AUCTION_LOBBY', advice=False)
                elif rejected == 'identity':
                    target = _target(); target['targetHwnd'] += 1
                    event = delivery_observation(fixture, 2, 'SETTLEMENT', advice=False, target=target)
                else:
                    event = delivery_observation(fixture, 2, 'SETTLEMENT', advice=False)
                    event['frame']['deliveryProof']['previousMarkerNs'] = event['frame']['deliveryProof']['sourceTimestampNs']
                    event['frame']['deliveryProof']['sourceMarkerProgress'] = False
                    event['frame']['currentAdviceQualification'] = {
                        **advice_qualification(False), 'sourceMarkerProgress': False,
                        'failureReasons': ['SOURCE_MARKER_NO_PROGRESS', 'SUPPORT_ACTION_UNQUALIFIED']}
                ns['_native_source_observation_notice'](event)
                self.assertEqual(fixture.source.actions, [])
                if rejected == 'marker':
                    self.assertIn('SOURCE_MARKER_NO_PROGRESS', ns['_NATIVE_AUTO_TRIGGER_STATUS']['reasonCodes'])

    def test_monitor_follows_stdout_and_session_diagnostic_logs_without_double_counting(self):
        from tools.start_native_delivery_candidate import NativeRunLogTail
        native_root = ROOT / 'build/native-observation'
        native_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='monitor-test-') as output_dir, \
                tempfile.TemporaryDirectory(dir=native_root, prefix='session-monitor-') as session_dir:
            output = Path(output_dir); session = Path(session_dir)
            diagnostic = session / 'main-diagnostic.log'
            shared = '[2026-10-06 12:00:00] [1.00ms] [WAREHOUSE:NATIVE_AUTO] {"kind":"admitted"}'
            identity = '[2026-10-06 12:00:00] [1.00ms] [STARTUP:NATIVE_IDENTITY] ' + json.dumps(
                {'sessionDirectory': str(session)}, ensure_ascii=False)
            (output / 'main.log').write_text(identity + '\n' + shared + '\n', encoding='utf-8')
            diagnostic.write_text(shared + '\n' + shared.replace('admitted', 'redirected-only') + '\n',
                                  encoding='utf-8')
            tail = NativeRunLogTail(output)
            try:
                rows = tail.poll()
                self.assertEqual(sum(line == shared for _, line in rows), 1)
                self.assertIn(('redirected', shared.replace('admitted', 'redirected-only')), rows)
                diagnostic.write_text(diagnostic.read_text(encoding='utf-8') +
                                      shared.replace('admitted', 'later-detail') + '\n', encoding='utf-8')
                self.assertIn(('redirected', shared.replace('admitted', 'later-detail')), tail.poll())
            finally:
                tail.close()

    def test_origin_label_local_age_and_independent_stability(self):
        first = proof()
        self.assertIsNone(validate_delivery(first, first['readbackCompletedNs'], session='offline'))
        # Later clocks passing the source do not reclassify its original FUTURE_AT_READ.
        self.assertIsNone(validate_delivery(first, first['sourceTimestampNs'] + 100))
        self.assertFalse(first['originStrictQualified'])
        self.assertFalse(independent_support(first, first))
        later = proof(2, request=first['readbackCompletedNs'] + 250_000_000,
                      previous=first['sourceTimestampNs'])
        self.assertTrue(independent_support(first, later))
        for mutation in ({'emptyBoundaryNs': 0}, {'repeatedSourceTicks': first['sourceTicks'] + 1},
                         {'sourceTimestampNs': 1}, {'originStrictQualified': True}, {'captureId': 'wrong'},
                         {'releaseCompletedNs': first['dequeueBeforeNs'] + 1}, {'boundaryHeldCount': 3},
                         {'drainTakeCount': 4}, {'poolBufferCount': 3},
                         {'boundaryKind': 'immediate-release'}, {'schemaVersion': 'capture-delivery-proof.v1'}):
            bad = {**first, **mutation}
            self.assertIsNotNone(validate_delivery(bad, first['readbackCompletedNs']))
        self.assertIsNotNone(validate_delivery(first, first['readbackCompletedNs'] + 2_000_000_001))

    def test_engine_checks_and_copies_proof_before_ack_and_never_uses_changed_slot(self):
        spec = importlib.util.spec_from_file_location('delivery_engine', ROOT / 'architecture/v2/host/engine_v22/nte_engine_v22.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        engine = module.RealEngine.__new__(module.RealEngine)
        root = Path(tempfile.mkdtemp(dir=ROOT / 'build/native-delivery-20261006', prefix='slot-'))
        (root / 'capture-proofs').mkdir()
        p = proof()
        item = {'bufferIndex': 0, 'rawSha256': hashlib.sha256(b'inert').hexdigest(),
                'header': {'sequence': 1, 'captureTimestampNs': p['readbackCompletedNs']}}
        binding = {'capturePolicy': DELIVERY, 'sessionId': 'offline', 'bufferIndex': 0, 'sequence': 1,
                   'pixelSha256': item['rawSha256'], 'targetInstance': {'targetHwnd': 12},
                   'recordStableKey': 'match', 'clientMap': 'map', 'deliveryProof': p}
        path = root / 'capture-proofs/0.json'
        engine.capture_policy = DELIVERY; engine.capture_client_map = 'map'
        engine.session_id = 'offline'; engine.work_dir = root
        engine.observation_target_identity = {'targetHwnd': 12}
        engine.current_match = SimpleNamespace(id='match', _seq=1)
        engine.stop_event = threading.Event(); engine.fault = ''; engine._identity_generation = lambda: 0
        engine._last_delivery_sequence = engine._last_delivery_epoch = 0
        engine.frame_queue = queue.Queue(maxsize=2)
        engine.reader = SimpleNamespace(read_frame=lambda *_: copy.deepcopy(item))
        acks = []
        engine._frame_ack = lambda data, *_: acks.append(copy.deepcopy(data))
        for broken in ({'pixelSha256': 'bad'}, {'sequence': 2}, {'clientMap': 'different'},
                       {'recordStableKey': 'retired'}):
            path.write_text(json.dumps({**binding, **broken}))
            with patch.object(module, 'qpc_ns', return_value=p['readbackCompletedNs']):
                with self.assertRaises((ValueError, module.ProtocolError)):
                    engine.handle_frame_ready({'payload': {}})
            self.assertTrue(engine.frame_queue.empty()); self.assertEqual(acks, [])
        path.write_text(json.dumps(binding))
        with patch.object(module, 'qpc_ns', return_value=p['readbackCompletedNs']):
            engine.handle_frame_ready({'payload': {}})
        self.assertEqual(len(acks), 1)
        path.write_text('{}')  # Host may now reuse the slot. Queued proof must stay immutable.
        queued = engine.frame_queue.get_nowait()
        self.assertEqual(queued['captureProof'], binding)
        path.write_text(json.dumps(binding))
        with patch.object(module, 'qpc_ns', return_value=p['readbackCompletedNs']):
            with self.assertRaises(module.ProtocolError):
                engine.handle_frame_ready({'payload': {}})
        self.assertTrue(engine.frame_queue.empty())

    def test_closed_settlement_anchor_path_bypasses_full_pipeline(self):
        spec = importlib.util.spec_from_file_location(
            'delivery_engine_closed_anchor', ROOT / 'architecture/v2/host/engine_v22/nte_engine_v22.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        engine = module.RealEngine.__new__(module.RealEngine)
        current = {'scene': 'SETTLEMENT', 'isSettlement': True, 'round': 1}
        process_frame = Mock(side_effect=AssertionError('closed settlement probe must stay lightweight'))
        engine._settlement_collection_closed = True
        engine.pipeline = SimpleNamespace(current_context=current, process_frame=process_frame)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with patch.object(module, 'settlement_title_visible', return_value=True):
            context, closed = engine._observe_frame_context(frame, 'offline')
        self.assertTrue(closed)
        self.assertEqual(context, current)
        process_frame.assert_not_called()

    def make_intake(self):
        root = Path(tempfile.mkdtemp(dir=ROOT / 'build/native-delivery-20261006', prefix='intake-'))
        store = NativeTrialDraftStore(root / 'trial/history.json')
        scope = {'recordStableKey': 'match', 'observationSessionId': 'offline',
                 'targetInstance': {'targetHwnd': 12}, 'matchGeneration': 1,
                 'scene': 'SETTLEMENT', 'capturePolicy': DELIVERY}
        record = build_canonical_match_record_v7(match_id='match', played_at='2026-10-06T00:00:00Z',
                                                lifecycle_status='DRAFT', source='manual', settlement={})
        record['dataOrigin'] = 'live-trial'; store.save_draft(record)
        intake = NativeWarehouseIntake(draft_store=store, scope_provider=lambda: copy.deepcopy(scope),
                                      source_provider=lambda: None)
        sent = []; now = proof()['readbackCompletedNs']
        coordinator = NativeWarehouseSourceCoordinator(intake, send_control=lambda c: sent.append(c) or True,
            source_root_provider=lambda: root, timers=False, qpc=lambda: now)
        self.assertTrue(coordinator.start_manual()['ok'])
        def event(kind, **kwargs):
            c = sent[-1]
            evt = {k: copy.deepcopy(c[k]) for k in ('commandId', 'nonce', 'requestOrdinal',
                'observationSessionId', 'reviewSessionId', 'reviewGeneration', 'recordStableKey', 'matchGeneration')}
            evt.update(type='native_warehouse_evidence', schemaVersion=SCHEMA_V2, capturePolicy=DELIVERY,
                       sourceKind='native_wgc', formalHistoryWriter=False, inputActions=False,
                       event=kind, targetInstance=copy.deepcopy(scope['targetInstance']), leaseToken='a' * 32)
            evt.update(kwargs); return evt
        coordinator.on_event(event('OPENED', details={'deadlineNs': now + 69_000_000_000,
            'clientWidth': 32, 'clientHeight': 32, 'remainingSourcePages': 16,
            'remainingRawBytes': 128 * 1024 * 1024, 'maxPngBytes': 64 * 1024 * 1024,
            'pngEncoding': 'opencv-bgr8-png-bound.v1', 'clientMap': 'map', 'windowScrollSupported': True}))
        self.assertTrue(coordinator.capture_manual_page()['ok'])
        pixels = np.arange(32 * 32 * 4, dtype=np.uint8).tobytes()
        header = struct.pack('<2sIHHI', b'BM', 54 + len(pixels), 0, 0, 54)
        header += struct.pack('<IiiHHIIiiII', 40, 32, -32, 1, 32, 0, len(pixels), 0, 0, 0, 0)
        raw = header + pixels
        directory = root / 'warehouse-sources'; directory.mkdir()
        path = directory / ('b' * 32 + '.bmp'); path.write_bytes(raw)
        p = proof()
        source = {'sourceLeaseId': 'b' * 32, 'path': str(path), 'width': 32, 'height': 32, 'stride': 128,
                  'byteCount': len(raw), 'pixelSha256': hashlib.sha256(pixels).hexdigest(),
                  'bmpSha256': hashlib.sha256(raw).hexdigest(), 'capturedAtUtc': '2026-10-06T00:00:00Z',
                  'frameSequence': 1, 'sourceTimestampNs': p['sourceTimestampNs'], 'requestGateNs': p['requestNs'],
                  'readbackTimestampNs': p['readbackCompletedNs'], 'clientMap': 'map', 'deliveryProof': p,
                  'capturePolicy': DELIVERY, 'matchGeneration': 1, 'formalFactsQualified': False}
        visible = patch('scene_anchors.settlement_title_visible', return_value=True)
        visible.start(); self.addCleanup(visible.stop)
        return root, store, scope, intake, coordinator, sent, event('SOURCE', source=source), raw

    def test_source_v2_original_saved_before_ocr_without_formal_facts_and_late_scope_rejected(self):
        root, store, scope, intake, coordinator, sent, evt, raw = self.make_intake()
        history = store.history_path.read_bytes()
        coordinator.on_event(evt)
        self.assertEqual(sent[-1]['operation'], 'ACK_SOURCE'); self.assertEqual(sent[-1]['result'], 'SAVED')
        pages = intake.pages_copy(); self.assertEqual(len(pages), 1)
        self.assertEqual(store.read_source_image_descriptor(pages[0]['nativeSource'])['data'], raw)
        self.assertEqual(pages[0]['deliveryProof']['originStatus'], 'FUTURE_AT_READ')
        self.assertEqual(store.history_path.read_bytes(), history)
        scope['recordStableKey'] = 'next'; scope['matchGeneration'] = 2
        coordinator.on_event(evt)
        self.assertEqual(len(intake.pages_copy()), 1)
        self.assertEqual(coordinator.source_session_snapshot()['state'], 'CLOSED')
        self.assertEqual(store.history_path.read_bytes(), history)

    def test_saved_original_rechecked_before_recognition_and_save_failure(self):
        _, store, _, intake, coordinator, sent, evt, _ = self.make_intake()
        with patch.object(store, 'capture_frame', side_effect=OSError('disk failure')):
            coordinator.on_event(evt)
        self.assertEqual(intake.pages_copy(), []); self.assertEqual(sent[-1]['result'], 'REJECTED')
        _, store, _, intake, coordinator, _, evt, _ = self.make_intake()
        coordinator.on_event(evt)
        with patch.object(store, 'read_source_image_descriptor', return_value={'error': 'tampered'}), \
                patch('native_warehouse_intake.WarehouseCaptureHost._process_saved_pages') as ocr:
            self.assertTrue(intake.finish_manual_capture()['ok'])
            intake.wait_processing(2)
            ocr.assert_not_called()
        self.assertEqual(intake.presentation_payload()['state'], 'ERROR')

    def test_non_settlement_original_retained_without_page_or_recognition_admission(self):
        _, store, _, intake, coordinator, sent, evt, raw = self.make_intake()
        history = store.history_path.read_bytes()
        with patch('scene_anchors.settlement_title_visible', return_value=False):
            coordinator.on_event(evt)
        self.assertEqual(sent[-1]['result'], 'REJECTED')
        self.assertEqual(intake.pages_copy(), [])
        original = intake._rejected_originals[0]['nativeSource']
        self.assertEqual(store.read_source_image_descriptor(original)['data'], raw)
        self.assertEqual(store.history_path.read_bytes(), history)

    def test_slow_recognition_stop_and_cross_match_cannot_write_history_or_publish_packet(self):
        _, store, scope, intake, coordinator, _, evt, _ = self.make_intake()
        coordinator.on_event(evt)
        history = store.history_path.read_bytes()
        entered, resume = threading.Event(), threading.Event()
        def slow(record, descriptors, *, history_store, **kwargs):
            entered.set()
            if not resume.wait(2):
                raise TimeoutError('bounded offline recognition')
            # The real history adapter must reject the retired generation before
            # calling the store, irrespective of this worker's apparent success.
            history_store.persist_warehouse_evidence(record, evidence=None)
            return {'ok': True, 'packet': {'sourceFingerprint': 'old'}, 'coverageStatus': 'COMPLETE'}
        with patch('native_warehouse_intake.WarehouseCaptureHost._process_saved_pages', side_effect=slow):
            self.assertTrue(intake.finish_manual_capture()['ok'])
            self.assertTrue(entered.wait(1))
            scope['recordStableKey'] = 'next'; scope['matchGeneration'] = 2
            intake.cancel_manual_capture(reason='OBSERVATION_STOPPED')
            resume.set(); intake.wait_processing(2)
        self.assertEqual(store.history_path.read_bytes(), history)
        self.assertEqual(intake.presentation_payload()['state'], 'CANCELLED')
        self.assertIsNone(intake.review_packet_copy())
        self.assertEqual(len(intake.pages_copy()), 1)

    def test_scroll_effect_requires_both_image_displacement_and_thumb_change(self):
        old = np.arange(20 * 20 * 3, dtype=np.uint8).reshape(20, 20, 3)
        before = {'scrollState': 'TOP', 'capturePolicy': DELIVERY, 'deliveryProof': proof(),
                  'trackBox': [90, 0, 96, 100], 'thumbBox': [90, 0, 96, 20], 'thumbPosition': 0.0}
        for image_moved, slider_moved in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(image=image_moved, slider=slider_moved):
                source = SimpleNamespace(intake=SimpleNamespace(_scope_lock=threading.RLock()))
                auto = NativeWarehouseAutoCapture(source, clock=lambda: 100, timers=False)
                auto._phase = 'WAIT_MOVED'; auto._anchor = old; auto._observation = before
                auto._seen_pages = 1; auto._diagnose = lambda *_a, **_k: None
                stopped, scheduled = [], []
                auto._stop = lambda reason, **_: stopped.append(reason)
                auto._schedule_page = lambda delay: scheduled.append(delay)
                after = {**before, 'scrollState': 'MIDDLE', 'thumbPosition': 0.3 if slider_moved else 0.0,
                         'thumbBox': [90, 30, 96, 50] if slider_moved else [90, 0, 96, 20]}
                overlap = {'status': 'VERIFIED', 'direction': 'DOWN', 'verticalOffsetPx': -20} if image_moved else {'status': 'UNVERIFIED'}
                with patch('native_warehouse_auto_capture.align_warehouse_segments', return_value=overlap):
                    auto._page(old, after)
                self.assertEqual(bool(scheduled), image_moved and slider_moved)
                self.assertEqual(bool(stopped), not (image_moved and slider_moved))

    def test_auto_stability_rejects_repeated_id_while_distinct_delivery_can_scroll(self):
        crop = np.arange(20 * 20 * 3, dtype=np.uint8).reshape(20, 20, 3)
        def run(later):
            calls = []
            source = SimpleNamespace(request_scroll_down=lambda **kw: calls.append(kw) or {'ok': True})
            source.intake = SimpleNamespace(_scope_lock=threading.RLock())
            auto = NativeWarehouseAutoCapture(source, clock=lambda: 100, timers=False)
            auto._phase = 'WAIT_STABLE'; auto._due = 99; auto._seen_pages = 1
            auto._anchor = crop; auto._deadline = 170
            obs = {'scrollState': 'TOP', 'capturePolicy': DELIVERY, 'deliveryProof': proof(),
                   'trackBox': [90, 0, 96, 100], 'thumbBox': [90, 0, 96, 20], 'thumbPosition': 0.0}
            auto._observation = obs
            stopped = []; auto._stop = lambda reason, **_: stopped.append(reason)
            auto._diagnose = lambda *_a, **_k: None
            auto._page(crop, {**obs, 'deliveryProof': later})
            return calls, stopped
        calls, stopped = run(proof())
        self.assertEqual(calls, []); self.assertEqual(stopped, ['INDEPENDENT_STABILITY_UNPROVEN'])
        later = proof(2, proof()['readbackCompletedNs'] + 250_000_000, previous=proof()['sourceTimestampNs'])
        calls, stopped = run(later)
        self.assertEqual(len(calls), 1); self.assertEqual(stopped, [])
        self.assertNotEqual(calls[0]['base_proof']['captureId'], calls[0]['stable_proof']['captureId'])


if __name__ == '__main__':
    unittest.main()
