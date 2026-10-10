"""Read retained originals; replay SOURCE collection on their recorded timeline.

Only transport/window sending and identity references are inert. No game capture
or input. The retained second viewport was obtained manually, not by this replay.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import re
from datetime import datetime
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('app', 'core')]
from native_trial_drafts import NativeTrialDraftStore
from canonical_match_record import build_canonical_match_record_v7
from native_warehouse_intake import NativeWarehouseIntake
from native_warehouse_source import NativeWarehouseSourceCoordinator, SCHEMA_V2
from native_warehouse_auto_capture import NativeWarehouseAutoCapture
from native_warehouse_visible_content_gate import VisibleContentGate
from native_warehouse_content_stability import content_stability
from warehouse_scrollbar_observation import warehouse_search_roi
from warehouse_placement_resolver import WarehousePlacementResolver


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'build'):
        raise ValueError('OUTPUT_OUTSIDE_BUILD')
    output.mkdir(parents=True, exist_ok=True)
    run = args.run.resolve()
    saved = json.loads((run/'evidence-result.json').read_text(encoding='utf-8'))
    pages = saved['pages']
    host_root = Path(saved['snapshot']['savedSource']['path']).parent.parent
    host_paths = {hashlib.sha256(p.read_bytes()).hexdigest():p
        for p in (host_root/'warehouse-sources').glob('*.bmp')}
    frames, originals = [], []
    for page in pages:
        path = run/'trial-drafts'/page['nativeSource']['relativePath']
        raw = path.read_bytes()
        if (hashlib.sha256(raw).hexdigest() != page['bmpSha256']
                or hashlib.sha256(raw[54:]).hexdigest() != page['pixelSha256']):
            raise ValueError('RETAINED_ORIGINAL_CHANGED')
        frames.append(cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR))
        originals.append({**page, 'bmpPath': str(path)})
    x,y,r,b = warehouse_search_roi(1920,1080)
    pairs = []
    for i,j in [(1,2),(2,3),(3,4),(4,5),(5,6),(6,7),(7,8),(8,9),(9,10),(11,12),(12,13),(13,14)]:
        result = content_stability(frames[i-1][y:b,x:r], frames[j-1][y:b,x:r])
        normal = i >= 5
        if normal and not result['qualified']:
            raise AssertionError((i,j,result))
        if i < 5 and result['qualified']:
            raise AssertionError('UNRESOLVED_OR_CHANGING_PAGE_ACCEPTED')
        pairs.append({'from':i,'to':j, 'result':result})
    old_run = json.loads((ROOT/'build/native-restability-timer-20261007/lifecycle-real-01/real-result.json').read_text(encoding='utf-8'))
    old = []
    for desc in old_run['verifiedOriginals'][6:8]:
        raw = Path(desc['bmpPath']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != desc['bmpSha256']:
            raise ValueError('REVEAL_ORIGINAL_CHANGED')
        old.append(cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)[y:b,x:r])
    reveal = content_stability(*old)
    if reveal['qualified']:
        raise AssertionError('KNOWN_REAL_REVEAL_ACCEPTED')
    # Explicit two-code visibility boundary, including smallest protected edits.
    mutations = []
    for name,point in [('dark-cell',(20,560)),('badge',(26,70)),('quality',(10,15)),('clipping',(599,635))]:
        a = frames[4][y:b,x:r].copy(); changed = a.copy(); xx,yy = point
        changed[yy,xx,0] = int(a[yy,xx,0])+2 if a[yy,xx,0] <= 253 else int(a[yy,xx,0])-2
        check = content_stability(a,changed)
        if check['qualified']:
            raise AssertionError(name)
        mutations.append({'case':name,'syntheticRuleCheck':True,'qualified':False})

    # Labels were assigned by inspecting originals/contact sheets, before any
    # detector result. They describe visible business evidence, not RGB causes.
    annotations = [
        ('无法判断','多处未显暗框；当前物件总内容无法判断'),
        ('无法判断','未显暗框仍在；小白图案变化不能确定物件事实'),
        ('明确业务变化','相对2，顶部蓝色长形物件显现；其余仍有未显暗框'),
        ('无法判断','未显暗框仍在；小白图案变化的业务含义未知'),
        ('明确业务变化','相对4，大面积物件图案/品质底色及勾选状态显现'),
        *[('可见业务未变','相对上一顶部原图，图案/品质/勾选/边缘未见改变')]*5,
        ('明确业务变化','视口向下位移，新增可见区域；不是物件新增事实'),
        *[('可见业务未变','相对上一中段原图，图案/品质/勾选/边缘未见改变')]*3]
    (output/'annotations.json').write_text(json.dumps([{'ordinal':i+1,'bmpSha256':p['bmpSha256'],
        'label':label,'basis':basis,'fullInventoryKnown':False}
        for i,(p,(label,basis)) in enumerate(zip(originals,annotations))],ensure_ascii=False,indent=2),encoding='utf-8')

    scope = copy.deepcopy(saved['snapshot']['binding']['scope'])
    deadline = saved['snapshot']['limits']['deadlineNs']
    # Start this bounded replay at its first retained request, with only the
    # remainder of the ORIGINAL deadline. No request waits across the user gap.
    now = [pages[4]['deliveryProof']['requestNs']/1e9 - .0001]
    sent, logs = [], []
    store = NativeTrialDraftStore(output/'trial/history.json')
    record = build_canonical_match_record_v7(match_id=scope['recordStableKey'],
        played_at=datetime.fromisoformat(re.sub(r'(\.\d{6})\d+', r'\1', pages[0]['descriptor']['capturedAt'])).isoformat(),
        lifecycle_status='DRAFT', source='manual', settlement={})
    record['dataOrigin'] = 'live-trial'
    store.save_draft(record)
    intake = NativeWarehouseIntake(draft_store=store,scope_provider=lambda:copy.deepcopy(scope),
        source_provider=lambda:None, clock=lambda:now[0])
    source = NativeWarehouseSourceCoordinator(intake,send_control=lambda c:sent.append(copy.deepcopy(c)) or True,
        source_root_provider=lambda:host_root,
        timers=False, clock=lambda:now[0],qpc=lambda:round(now[0]*1e9))
    gate = VisibleContentGate()
    auto = NativeWarehouseAutoCapture(source,clock=lambda:now[0],timers=False,content_gate=gate,
        diagnostic_log=lambda s:logs.append(json.loads(s)))
    if not auto.confirm(auto.prepare()['armingToken'])['ok']:
        raise AssertionError('REPLAY_DID_NOT_START')
    def event(kind, cmd=None, **extras):
        cmd = cmd or source._pending or sent[-1]
        e = {k:copy.deepcopy(cmd[k]) for k in ('commandId','nonce','requestOrdinal','observationSessionId',
            'reviewSessionId','reviewGeneration','recordStableKey','matchGeneration')}
        e.update(type='native_warehouse_evidence',schemaVersion=SCHEMA_V2,capturePolicy=scope['capturePolicy'],
            sourceKind='native_wgc',inputActions=False,formalHistoryWriter=False,event=kind,
            targetInstance=copy.deepcopy(scope['targetInstance']),leaseToken='a'*32)
        e.update(extras)
        return e
    auto.on_event(event('OPENED',details={'deadlineNs':deadline,'clientWidth':1920,'clientHeight':1080,
        'remainingSourcePages':16,'remainingRawBytes':128*1024*1024,'maxPngBytes':64*1024*1024,
        'pngEncoding':'opencv-bgr8-png-bound.v1','clientMap':pages[0]['clientMap'],
        'windowScrollSupported':True,'retainIndependentOriginals':True}))
    for ordinal in (5,7,11,14):
        page = originals[ordinal-1]; p = page['deliveryProof']
        if source._state == 'SCROLL_PENDING':
            cmd = copy.deepcopy(source._pending)
            auto.on_event(event('SCROLLED',cmd,inputActions=True,details={'direction':'DOWN','delta':-120,
                'sourceLeaseId':cmd['sourceLeaseId'],'messageCompletedNs':round(now[0]*1e9)}))
        if source._state != 'REQUEST_PENDING':
            now[0] = p['requestNs']/1e9
            auto.poll()
        if source._state != 'REQUEST_PENDING':
            raise AssertionError(('REQUEST_NOT_READY',ordinal,auto._phase,auto._reason))
        cmd = copy.deepcopy(source._pending)
        now[0] = (p['readbackCompletedNs']+100_000)/1e9
        host_path = host_paths[page['bmpSha256']]
        src = {'sourceLeaseId':host_path.stem,'path':str(host_path),'width':1920,'height':1080,'stride':7680,
            'byteCount':page['nativeSource']['byteSize'],'pixelSha256':page['pixelSha256'],'bmpSha256':page['bmpSha256'],
            'capturedAtUtc':page['descriptor']['capturedAt'],'frameSequence':page['sourceSequence'],
            'sourceTimestampNs':p['sourceTimestampNs'],'requestGateNs':p['requestNs'],
            'readbackTimestampNs':p['readbackCompletedNs'],'clientMap':page['clientMap'],
            'deliveryProof':p,'capturePolicy':scope['capturePolicy'],'matchGeneration':scope['matchGeneration'],
            'formalFactsQualified':False}
        auto.on_event(event('SOURCE',cmd,source=src))
        if not auto._active:
            raise AssertionError(('REPLAY_STOPPED',ordinal,auto._reason))
    # Scope and retained-original binding checks exercise the new adapter, not
    # already closed lifecycle/transport suites.
    supported_observation = auto._observation
    anchor_observation = {'contentProfile':{**copy.deepcopy(supported_observation['contentProfile']),
        **supported_observation['contentStability']['certificate']['anchor'],
        'rawBgrSha256':hashlib.sha256(frames[10].tobytes()).hexdigest()},
        'deliveryProof':copy.deepcopy(supported_observation['stableBaseDeliveryProof'])}
    altered = copy.deepcopy(supported_observation)
    altered['contentProfile']['scope']['recordStableKey'] = 'other-match'
    if gate.compare(anchor_observation,altered)['qualified']:
        raise AssertionError('CROSS_MATCH_CONTENT_ACCEPTED')
    altered = copy.deepcopy(supported_observation)
    altered['contentProfile']['rawBgrSha256'] = '0'*64
    if gate.compare(anchor_observation,altered)['reason'] != 'CONTENT_ORIGINAL_UNAVAILABLE':
        raise AssertionError('ORIGINAL_BINDING_NOT_CHECKED')
    empty = output/'empty-identity-references.json'
    empty.write_text('{"records":[],"meaning":"content/coverage replay; item identities not checked"}',encoding='utf-8')
    resolver = WarehousePlacementResolver(manifest_path=empty)
    with patch('warehouse_capture_production.get_production_placement_resolver',return_value=resolver):
        auto.stop()
        intake.wait_processing(30)
    if gate.final_support(supported_observation)['qualified']:
        raise AssertionError('RELEASED_CERTIFICATE_ACCEPTED')
    result = {'verificationMode':'saved-offline-replay','gameCapture':False,'gameInput':False,
        'pairs':pairs,'oldRealReveal7to8':reveal,'syntheticBoundaryChecks':mutations,
        'replayedSourceOrdinals':[5,7,11,14],'representativeIds':gate.representatives(),
        'scrollCommands':sum(c['operation']=='SCROLL_DOWN' for c in sent),
        'deadlineNs':deadline,'intakeState':intake._state,'coverage':intake._coverage,
        'reviewCoverage':(intake.review_packet_copy() or {}).get('warehouseCoverage'),
        'contentFramesReleased':not gate._frames,'sourceReleased':source._source is None,
        'crossMatchAndOriginalBindingRejected':True,
        'releasedCertificateRejected':True,
        'identityReferenceAdapter':'empty; no identity or price validation',
        'manualSecondViewportNotAnAutomaticScrollReceipt':True}
    (output/'replay-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'trace.json').write_text(json.dumps({'sent':sent,'diagnostics':logs},ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'host-input.json').write_text(json.dumps({'originals':originals,'scope':scope,'deadlineNs':deadline},ensure_ascii=False),encoding='utf-8')
    if len(gate.representatives()) != 2 or intake._coverage != 'PARTIAL':
        raise AssertionError(('PARTIAL_TWO_VIEWPORTS_NOT_ESTABLISHED',result['intakeState'],result['coverage']))
    print(json.dumps({'passed':True,'normalPairs':8,'coverage':result['coverage'],
        'scrollCommands':result['scrollCommands'],'output':str(output/'replay-result.json')},ensure_ascii=False))


if __name__ == '__main__':
    main()
