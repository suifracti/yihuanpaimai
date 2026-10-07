"""Offline behavior tests: actual SOURCE/store/collector/observer/overlap/ledger.

Only WGC delivery and window send are inert. No patches to content, read_page,
observer, alignment, coverage or history finalization. Real game is not used.
"""
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'app'), str(ROOT/'core'), str(ROOT/'tools/native_qa'), str(ROOT/'tests'), str(ROOT)]
from canonical_match_record import build_canonical_match_record_v7
from native_trial_drafts import NativeTrialDraftStore
from native_warehouse_intake import NativeWarehouseIntake
from native_warehouse_source import NativeWarehouseSourceCoordinator, SCHEMA_V2
from native_warehouse_auto_capture import NativeWarehouseAutoCapture
from native_warehouse_sampling_model import CommonSamplingModel, ContentLayout
from offline_content_gate import OfflineContentGate
from native_content_fixture import scene, render_phase, GRID, REFERENCES
from tests.test_native_delivery_contract import proof

OUT = ROOT/'build/native-content-flow-offline-20261007'
TRACES = []
LAYOUT = ContentLayout(GRID, REFERENCES, 'independent procedural scene; full rectangular visible grid; Q5 fixture renderer only')


class Run:
    def __init__(self):
        OUT.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(dir=OUT, prefix='flow-'))
        self.now, self.sent, self.logs, self.sequence = 100., [], [], 0
        self.scope = {'recordStableKey': 'match', 'observationSessionId': 'fixture',
                      'targetInstance': {'targetHwnd': 12, 'processId': 123}, 'matchGeneration': 1,
                      'scene': 'SETTLEMENT', 'capturePolicy': 'wgc-delivery-v1'}
        self.store = NativeTrialDraftStore(self.root/'trial/history.json')
        record = build_canonical_match_record_v7(match_id='match', played_at='2026-10-07T00:00:00Z',
                      lifecycle_status='DRAFT', source='manual', settlement={})
        record['dataOrigin'] = 'live-trial'
        self.store.save_draft(record)
        self.intake = NativeWarehouseIntake(draft_store=self.store,
                      scope_provider=lambda: copy.deepcopy(self.scope), source_provider=lambda: None,
                      clock=lambda: self.now)
        self.source = NativeWarehouseSourceCoordinator(self.intake,
                      send_control=lambda c: self.sent.append(copy.deepcopy(c)) or True,
                      source_root_provider=lambda: self.root, timers=False,
                      clock=lambda: self.now, qpc=lambda: round(self.now*1e9))
        self.source.offline_test_adapter = True
        self.gate = OfflineContentGate(LAYOUT)
        self.auto = NativeWarehouseAutoCapture(self.source, clock=lambda: self.now, timers=False,
                      diagnostic_log=lambda s: self.logs.append(json.loads(s)), offline_content_gate=self.gate)
        assert self.auto.confirm(self.auto.prepare()['armingToken'])['ok']
        self.auto.on_event(self.event('OPENED', details={'deadlineNs': 170_000_000_000,
            'clientWidth': 1920, 'clientHeight': 1080, 'remainingSourcePages': 16,
            'remainingRawBytes': 128*1024*1024, 'maxPngBytes': 64*1024*1024,
            'pngEncoding': 'opencv-bgr8-png-bound.v1', 'clientMap': 'map', 'windowScrollSupported': True}))

    def event(self, kind, command=None, **extras):
        cmd = command or self.sent[-1]
        e = {k: copy.deepcopy(cmd[k]) for k in ('commandId', 'nonce', 'requestOrdinal',
             'observationSessionId', 'reviewSessionId', 'reviewGeneration', 'recordStableKey', 'matchGeneration')}
        e.update(type='native_warehouse_evidence', schemaVersion=SCHEMA_V2, capturePolicy='wgc-delivery-v1',
                 sourceKind='native_wgc', inputActions=False, formalHistoryWriter=False,
                 event=kind, targetInstance=copy.deepcopy(self.scope['targetInstance']), leaseToken='a'*32)
        e.update(extras)
        return e

    def tick(self):
        self.now = self.auto._due + .05
        self.auto.poll()

    def deliver(self, frame, *, mapping='map'):
        assert self.source._state == 'REQUEST_PENDING', self.source.source_session_snapshot()
        cmd = copy.deepcopy(self.source._pending)
        self.sequence += 1
        pixels = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA).tobytes()
        raw = struct.pack('<2sIHHI', b'BM', 54+len(pixels), 0, 0, 54)
        raw += struct.pack('<IiiHHIIiiII', 40, 1920, -1080, 1, 32, 0, len(pixels), 0, 0, 0, 0)+pixels
        sid = f'{self.sequence:032x}'
        path = self.root/'warehouse-sources'/f'{sid}.bmp'
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
        p = proof(self.sequence, request=round((self.now-.001)*1e9)//100*100, session='fixture')
        src = {'sourceLeaseId': sid, 'path': str(path), 'width': 1920, 'height': 1080, 'stride': 7680,
               'byteCount': len(raw), 'pixelSha256': hashlib.sha256(pixels).hexdigest(),
               'bmpSha256': hashlib.sha256(raw).hexdigest(), 'capturedAtUtc': '2026-10-07T00:00:00Z',
               'frameSequence': self.sequence, 'sourceTimestampNs': p['sourceTimestampNs'],
               'requestGateNs': p['requestNs'], 'readbackTimestampNs': p['readbackCompletedNs'],
               'clientMap': mapping, 'deliveryProof': p, 'capturePolicy': 'wgc-delivery-v1',
               'matchGeneration': 1, 'formalFactsQualified': False}
        evt = self.event('SOURCE', cmd, source=src)
        self.auto.on_event(evt)
        return evt

    def scroll_ack(self):
        cmd = copy.deepcopy(self.source._pending)
        assert cmd['operation'] == 'SCROLL_DOWN', cmd
        self.auto.on_event(self.event('SCROLLED', cmd, inputActions=True, details={
             'direction': 'DOWN', 'delta': -120, 'sourceLeaseId': cmd['sourceLeaseId'],
             'messageCompletedNs': round(self.now*1e9)}))

    def stable(self, view=0):
        self.deliver(scene(view)); self.tick(); self.deliver(render_phase(scene(view)))

    def hint(self, frame):
        self.sequence += 1
        return self.auto.note_offline_observation_hint(frame, scope=self.intake.source_contract()['scope'],
            mapping='map', proof=proof(self.sequence,request=round((self.now-.001)*1e9)//100*100,session='fixture'))

    def trace(self, name):
        self.intake.wait_processing(30)
        result = {'case': name, 'termination': self.auto._reason,
             'deadline': self.auto._deadline, 'requests': self.source.source_session_snapshot()['requestAttempts'],
             'savedOriginals': len(self.source.pages_copy()), 'representativeIds': self.gate.representatives(),
             'scrollMessages': sum(c['operation'] == 'SCROLL_DOWN' for c in self.sent),
             'intakeState': self.intake._state, 'coverage': self.intake._coverage,
             'pendingReleased': self.source._pending is None, 'sourceReleased': self.source._source is None,
             'contentFramesReleased': len(self.gate._frames) == 0,
             'coveragePacket': (self.intake.review_packet_copy() or {}).get('warehouseCoverage'),
             'newGameCapture': False, 'realWindowInput': False}
        (self.root/'trace.json').write_text(json.dumps({'result': result, 'sent': self.sent,
                    'diagnostics': self.logs}, ensure_ascii=False, indent=2), encoding='utf-8')
        TRACES.append(result)
        return result


class ContentTests(unittest.TestCase):
    def test_full_protection_phase_external_and_real_content_counterexamples(self):
        model = CommonSamplingModel(LAYOUT)
        a, b = scene(), render_phase(scene())
        r = model.compare(a, b)
        self.assertTrue(r['qualified'], r)
        self.assertEqual(r['phaseQ5'], [2, 1])
        self.assertEqual(r['current']['protectedPixels'], 562*562)
        self.assertEqual(r['unexplainedPixels'], 0)
        external = b.copy(); external[860:900, 1600:1700] = (30, 90, 80)
        self.assertTrue(model.compare(a, external)['qualified'])
        # Each semantic mutation is defined independently of the detector.
        mutations = [('quantity-glyph', (1388, 279)), ('quality-rim', (1334, 230)),
                     ('printed-text', (1352, 280)), ('artwork', (1364, 249)),
                     ('footprint', (1424, 292)), ('empty-cell', (1848, 245)),
                     ('unrevealed-cell', (1848, 745)), ('clipped-fragment', (1350, 775)),
                     ('first-protected-pixel', (1315, 214)), ('last-protected-pixel', (1876, 775))]
        for name, (x, y) in mutations:
            with self.subTest(name=name):
                changed = b.copy()
                changed[y:y+1, x:x+1, 0] = np.bitwise_xor(changed[y:y+1, x:x+1, 0], 1)
                result = model.compare(a, changed)
                self.assertFalse(result['qualified'], result)
                self.assertGreater(result['unexplainedPixels'], 0)
        self.assertFalse(model.compare(scene(revealing=True), render_phase(scene(revealing=True)))['qualified'])
        # High-contrast semantic change and heldout-reference corruption.
        changed = b.copy(); cv2.putText(changed, '3', (1407, 305), cv2.FONT_HERSHEY_SIMPLEX, .5, (250,250,250), 1)
        self.assertFalse(model.compare(a, changed)['qualified'])
        changed = b.copy(); changed[740, 1220, 0] ^= 1
        self.assertEqual(model.compare(a, changed)['reason'], 'HELDOUT_REFERENCE_UNEXPLAINED')

    def test_independent_low_contrast_glyph_quality_and_footprint_scenes(self):
        model = CommonSamplingModel(LAYOUT)
        results=[]
        for amplitude in (1,3,5):
            for semantics in ('quantity', 'printed-text', 'quality', 'footprint', 'new-artwork'):
                a, changed = scene(), scene()
                # Independent semantic variants, before rendering. A and B
                # differ in numeral/letter/quality band/physical edge/artwork.
                box=(1400,265,1430,308)
                x,y,r,b=box
                a[y:b,x:r]=80; changed[y:b,x:r]=80
                value=(80+amplitude,)*3
                if semantics in ('quantity','printed-text'):
                    cv2.putText(a,'1' if semantics=='quantity' else 'A',(x+3,y+30),
                        cv2.FONT_HERSHEY_SIMPLEX,.7,value,1,cv2.LINE_8)
                    cv2.putText(changed,'2' if semantics=='quantity' else 'B',(x+3,y+30),
                        cv2.FONT_HERSHEY_SIMPLEX,.7,value,1,cv2.LINE_8)
                elif semantics=='quality':
                    a[y+2:y+5,x+2:r-2,0]=80+amplitude
                    changed[y+2:y+5,x+2:r-2,2]=80+amplitude
                elif semantics=='footprint':
                    a[y+2:b-2,x+5:x+6]=value
                    changed[y+2:b-2,x+6:x+7]=value
                else:
                    cv2.circle(a,(x+12,y+20),5,value,1)
                    cv2.rectangle(changed,(x+7,y+15),(x+17,y+25),value,1)
                stable=model.compare(a,render_phase(a))
                self.assertTrue(stable['qualified'],stable)
                result=model.compare(a,render_phase(changed))
                self.assertFalse(result['qualified'],(semantics,amplitude,result))
                self.assertGreater(result['unexplainedPixels'],0)
                results.append({'semantics':semantics,'channelAmplitude':amplitude,
                                'reason':result['reason'],'unexplainedPixels':result['unexplainedPixels']})
        (OUT/'semantic-counterexamples.json').write_text(json.dumps(results,indent=2),encoding='utf-8')

class FlowTests(unittest.TestCase):
    def test_invalid_second_reference_cannot_partially_replace_certificate(self):
        f=Run(); f.stable()
        before=f.source.pages_copy()
        certificate=copy.deepcopy(before[-1]['offlineContentCertificate'])
        certificate['reviewBinding']['generation']+=1
        with self.assertRaisesRegex(RuntimeError,'STALE_CONTENT_CERTIFICATE'):
            f.intake.annotate_offline_content_support(certificate)
        certificate=copy.deepcopy(before[-1]['offlineContentCertificate'])
        certificate['mapping']='unproven-map'
        with self.assertRaisesRegex(RuntimeError,'CONTENT_CERTIFICATE_ORIGINAL_CHANGED'):
            f.intake.annotate_offline_content_support(certificate)
        certificate=copy.deepcopy(before[-1]['offlineContentCertificate'])
        certificate['phaseQ5']=[3,1]
        certificate['support']['sha256']='f'*64
        with self.assertRaisesRegex(RuntimeError,'CONTENT_CERTIFICATE_ORIGINAL_CHANGED'):
            f.intake.annotate_offline_content_support(certificate)
        self.assertEqual(f.source.pages_copy(),before)
        f.auto.stop(); f.trace('invalid-second-certificate-reference')

    def test_unexpected_content_error_releases_and_live_entry_cannot_enable_adapter(self):
        f=Run(); f.deliver(scene()); f.tick()
        with patch.object(f.gate.model,'compare',side_effect=AttributeError('induced-offline-error')):
            f.deliver(render_phase(scene()))
        result=f.trace('unknown-content-error')
        self.assertEqual(result['termination'],'OFFLINE_CONTENT_CALLBACK_FAILED:AttributeError')
        self.assertTrue(result['contentFramesReleased'] and result['sourceReleased'] and result['pendingReleased'])
        self.assertEqual(result['scrollMessages'],0)
        f.source.offline_test_adapter=False
        with self.assertRaisesRegex(ValueError,'OFFLINE_CONTENT_ADAPTER_REQUIRED'):
            NativeWarehouseAutoCapture(f.source,offline_content_gate=OfflineContentGate(LAYOUT))
    def test_hints_only_time_requests_and_do_not_grant_scroll(self):
        f=Run(); f.deliver(scene(revealing=True))
        for gap in (.65, 8., 25.):
            f.now += gap
            self.assertTrue(f.hint(scene(revealing=True)))
            f.auto.poll()
            self.assertEqual(f.source.source_session_snapshot()['requestAttempts'],1)
            self.assertEqual(f.auto._deadline,170)
        self.assertTrue(f.hint(scene()) is False, '600ms throttle must reject immediate hint')
        f.now += .65; self.assertTrue(f.hint(scene()))
        self.assertEqual(f.source.source_session_snapshot()['requestAttempts'],1)
        self.assertEqual(f.gate.representatives(),[])
        self.assertFalse(any(c['operation']=='SCROLL_DOWN' for c in f.sent))
        f.tick(); self.assertEqual(f.source.source_session_snapshot()['requestAttempts'],2)
        f.auto.stop(); f.trace('frame-hints-only')

    def test_cancel_after_support_and_cross_generation_late_processing(self):
        f=Run(); f.stable()
        cmd=copy.deepcopy(f.source._pending)
        certificate=f.source.pages_copy()[-1]['offlineContentCertificate']
        f.auto.stop(); before=copy.deepcopy(f.sent)
        f.auto.on_event(f.event('SCROLLED',cmd,inputActions=True,details={'direction':'DOWN','delta':-120,
                        'sourceLeaseId':cmd['sourceLeaseId'],'messageCompletedNs':round(f.now*1e9)}))
        self.assertEqual(f.sent,before)
        with self.assertRaisesRegex(RuntimeError,'STALE_CONTENT_CERTIFICATE'):
            f.intake.annotate_offline_content_support(certificate)
        f.trace('cancel-after-support')

        from warehouse_capture_host import WarehouseCaptureHost
        entered, release = threading.Event(), threading.Event()
        original=WarehouseCaptureHost._process_saved_pages
        def delayed(owner,*args,**kwargs):
            entered.set()
            if not release.wait(3): raise RuntimeError('offline-late-processing-bound')
            return original(owner,*args,**kwargs)
        f=Run()
        with patch.object(WarehouseCaptureHost,'_process_saved_pages',new=delayed):
            try:
                f.stable()
                for view in (1,2):
                    f.scroll_ack();f.tick();f.stable(view)
                self.assertTrue(entered.wait(3))
                history=f.store.history_path.read_bytes()
                f.scope.update(recordStableKey='next',matchGeneration=2)
                f.intake.cancel_manual_capture(reason='SOURCE_SCOPE_CHANGED')
            finally:
                release.set()
            f.intake.wait_processing(10)
        self.assertIsNone(f.intake.review_packet_copy())
        self.assertEqual(f.store.history_path.read_bytes(),history)
        f.trace('cross-generation-late-processing')

    def test_normal_reveal_stability_save_scroll_overlap_bottom(self):
        f = Run()
        f.deliver(scene(revealing=True)); f.tick()
        self.assertEqual(f.source.source_session_snapshot()['requestAttempts'],1)
        self.assertTrue(f.hint(scene()))
        f.tick()
        # Ending reveal establishes a new anchor, never releases a scroll itself.
        f.deliver(scene()); self.assertEqual(f.auto._phase, 'WAIT_STABLE')
        self.assertFalse(any(c['operation'] == 'SCROLL_DOWN' for c in f.sent))
        f.tick(); f.deliver(render_phase(scene()))
        self.assertEqual(f.auto._phase, 'WAIT_SCROLL', f.logs[-3:])
        for view in (1,2):
            f.scroll_ack(); f.tick(); f.stable(view)
        result = f.trace('normal-three-viewports')
        self.assertEqual(result['termination'], 'COMPLETE', result)
        self.assertEqual(result['coverage'], 'COMPLETE', result)
        self.assertEqual(result['savedOriginals'], 7)
        self.assertEqual(len(result['representativeIds']), 3)
        self.assertEqual(result['scrollMessages'], 2)
        self.assertEqual(result['deadline'], 170)
        self.assertTrue(result['contentFramesReleased'])
        packet = f.intake.review_packet_copy()
        self.assertIsNotNone(packet)
        # Supports are independent evidence, not additional coverage pages.
        self.assertEqual(len(packet['segments']), 3)
        self.assertEqual(packet['warehouseCoverage']['segmentCount'], 3)
        displacements=[e['alignment']['verticalOffsetPx'] for e in f.logs if e['kind']=='image-overlap']
        self.assertEqual(displacements,[-180,-180])
        self.assertTrue(f.gate.comparisons[0]['current']['partialCandidates'])
        self.assertFalse(f.gate.comparisons[-1]['current']['partialCandidates'])
        roles=[p.get('offlineContentRole','UNQUALIFIED_OBSERVATION') for p in f.source.pages_copy()]
        self.assertEqual(roles.count('STABLE_SUPPORT'),3)
        self.assertEqual(roles.count('STABLE_ANCHOR'),3)
        self.assertEqual(roles.count('UNQUALIFIED_OBSERVATION'),1)

    def test_message_receipt_without_movement_and_unrelated_image(self):
        for mode in ('same', 'unrelated'):
            with self.subTest(mode=mode):
                f = Run(); f.stable(); f.scroll_ack(); f.tick()
                frame = scene(0 if mode == 'same' else 1)
                if mode == 'unrelated':
                    x,y,r,b = GRID; frame[y:b,x:r] = np.random.RandomState(34).randint(0,256,(b-y,r-x,3),dtype=np.uint8)
                # Make a unique original; same viewport is still not progress.
                frame[870,1600,0] ^= 1
                f.deliver(frame)
                result = f.trace(mode)
                self.assertEqual(result['scrollMessages'], 1)
                self.assertEqual(len(result['representativeIds']), 1)
                self.assertNotEqual(result['coverage'], 'COMPLETE')
                self.assertEqual(result['termination'], 'WINDOW_SCROLL_NO_PROGRESS' if mode == 'same'
                                 else 'OVERLAP_OR_SCROLL_PROGRESS_UNVERIFIED')

    def test_stop_scope_loss_save_failure_hash_failure_and_late_callback(self):
        for cause in ('cancel', 'identity', 'mapping', 'generation', 'save', 'hash'):
            with self.subTest(cause=cause):
                f = Run(); evt = f.deliver(scene()); deadline = f.auto._deadline
                if cause == 'save':
                    f.tick()
                    with patch.object(f.intake.evidence_store, 'save_original', side_effect=OSError('induced-disk-failure')):
                        f.deliver(render_phase(scene()))
                elif cause == 'hash':
                    f.tick()
                    with patch.object(f.intake.evidence_store, 'load_original', return_value=b'corrupt'):
                        f.deliver(render_phase(scene()))
                    self.assertEqual(f.auto._reason,'PAGE_PROOF_REJECTED:SOURCE_HASH_CHANGED')
                elif cause == 'mapping':
                    f.tick(); f.deliver(render_phase(scene()),mapping='changed')
                    self.assertEqual(f.auto._reason,'SOURCE_PROOF_REJECTED')
                elif cause == 'cancel':
                    f.auto.stop()
                else:
                    if cause == 'identity': f.scope['targetInstance']['processId'] = 124
                    else: f.scope.update(recordStableKey='next', matchGeneration=2)
                    f.auto.check_business_boundary({'status':'FRAME','observationSessionId':'fixture'})
                before = copy.deepcopy(f.sent)
                f.auto.on_event(evt); f.auto.poll(f.auto._generation-1)
                self.assertEqual(f.sent, before)
                result = f.trace(cause)
                self.assertEqual(result['deadline'], deadline)
                self.assertEqual(result['scrollMessages'], 0)
                self.assertTrue(result['pendingReleased'] and result['sourceReleased'] and result['contentFramesReleased'])
                self.assertNotEqual(result['coverage'], 'COMPLETE')

    def test_original_deadline_sources_and_requests_remain_bounded(self):
        f = Run(); f.deliver(scene(revealing=True)); f.now = 170.; f.auto.poll()
        r = f.trace('absolute-deadline')
        self.assertEqual(r['termination'], 'ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
        self.assertEqual(r['requests'], 1)
        f = Run()
        # 16 different originals are paid even though all are unsuitable.
        for i in range(16):
            if i:
                # This test drives paid SOURCE attempts at the coordinator;
                # a FRAME hint is deliberately not used to bypass the budget.
                f.now += .601
                self.assertTrue(f.source.capture_manual_page()['ok'])
            frame=scene(revealing=True); frame[260,1360,0] = 30+i
            f.deliver(frame)
        r=f.trace('source-bound')
        self.assertEqual(r['savedOriginals'], 16)
        self.assertEqual(r['requests'], 16)
        self.assertEqual(r['termination'], 'SOURCE_LIMIT_REACHED')
        f=Run(); f.deliver(scene(revealing=True))
        # Fresh equal acquisitions use the real coordinator duplicate admission
        # and consume attempts; they cannot prove an unrevealed page stable.
        for i in range(2,33):
            f.now += .601
            self.assertTrue(f.source.capture_manual_page()['ok'])
            p=proof(i,request=round((f.now-.001)*1e9)//100*100,session='fixture')
            f.source.on_event(f.event('RESULT',reason='DUPLICATE_PAGE',details={
                'pixelSha256':f.source.pages_copy()[0]['pixelSha256'],'clientMap':'map',
                'frameSequence':i,'requestGateNs':p['requestNs'],'sourceTimestampNs':p['sourceTimestampNs'],'deliveryProof':p}))
        f.auto.poll()
        r=f.trace('repeated-unrevealed')
        self.assertEqual(r['requests'],32)
        self.assertEqual(r['termination'],'SOURCE_REQUEST_LIMIT_REACHED')
        self.assertEqual(r['scrollMessages'],0)
        self.assertNotEqual(r['coverage'],'COMPLETE')


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    # Offline identity reference adapter: no fixture is a catalog item. Retain
    # the actual placement resolver/grid/physical ledger/packet path, while
    # avoiding a repeated full real-item template load for a collection test.
    from warehouse_placement_resolver import WarehousePlacementResolver
    empty = OUT/'empty-offline-identities.json'
    empty.write_text('{"records":[],"meaning":"procedural fixtures have no asserted catalog identities"}',encoding='utf-8')
    resolver = WarehousePlacementResolver(manifest_path=empty)
    suite = (unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:], sys.modules[__name__]) if len(sys.argv)>1
             else unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    with patch('warehouse_capture_production.get_production_placement_resolver', return_value=resolver):
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    selector=';'.join(sys.argv[1:]) or 'all'
    result_path=OUT/('checks-'+hashlib.sha256(selector.encode()).hexdigest()[:12]+'.json')
    result_path.write_text(json.dumps({'passed':result.wasSuccessful(), 'selector':selector,
        'testMethods':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'newGameCapture':False,'realScroll':False,'identityReferenceAdapter':'empty/offline-only',
        'productionCatalogIdentityValidation':False,'traces':TRACES},ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(not result.wasSuccessful())
