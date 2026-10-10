"""Affected scheduler/step checks using retained real pixels; no game or input.

Observation timings and transport are inert. This measures request opportunities,
not render-after-request freshness or the effect of a new real scroll delta.
"""
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
from unittest.mock import patch

import cv2

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]
from tests.test_native_content_flow import Run
from native_warehouse_visible_content_gate import VisibleContentGate
from warehouse_scrollbar_observation import warehouse_search_roi

run=ROOT/'build/native-auto-pages-20261009/real-once-01'
retained=json.loads((run/'run-result.json').read_text(encoding='utf-8'))['sources']
frames=[cv2.imread(p['png']) for p in retained]
f=Run(); gate=VisibleContentGate(); f.auto._content_gate=gate
f.deliver(frames[0])
deadline=f.auto._deadline
before=f.source.source_session_snapshot()['requestAttempts']
trace=[]
def hint(frame, ordinal):
    f.now+=.7
    x,y,r,b=warehouse_search_roi(1920,1080); crop=frame[y:b,x:r]
    pixels=cv2.cvtColor(crop,cv2.COLOR_BGR2BGRA).tobytes();h,w=crop.shape[:2]
    raw=struct.pack('<2sIHHI',b'BM',54+len(pixels),0,0,54)
    raw+=struct.pack('<IiiHHIIiiII',40,w,-h,1,32,0,len(pixels),0,0,0,0)+pixels
    path=f.root/'warehouse-sources/content-observation.bmp'; path.write_bytes(raw)
    event=f.event('CONTENT_HINT',details={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),
        'width':w,'height':h,'clientMap':'map','captureId':f'fixture/1/hint{ordinal}',
        'readbackNs':round(f.now*1e9),'sourceAuthority':False,'formalFactsQualified':False})
    return event
with patch('native_warehouse_visible_content_gate.time.perf_counter_ns',side_effect=lambda:round(f.now*1e9)):
    f.now+=.7;f.auto.poll()
    assert f.source.source_session_snapshot()['requestAttempts']==before
    for ordinal in range(2,9):
        event=hint(frames[ordinal-1],ordinal)
        if ordinal==3:
            wrong=copy.deepcopy(event);wrong['recordStableKey']='another-match';f.auto.on_event(wrong)
            assert not gate.request_eligible()
            wrong=copy.deepcopy(event);wrong['details']['sha256']='0'*64
            assert f.source.read_content_hint(wrong) is None
        f.auto.on_event(event)
        assert len(f.source.pages_copy())==1 and gate.representatives()==[]
        f.auto.poll()
        attempts=f.source.source_session_snapshot()['requestAttempts']
        trace.append({'retainedObservationOrdinal':ordinal,'requestEligible':gate.request_eligible(),
            'requestAttempts':attempts,'savedSources':len(f.source.pages_copy())})
        if ordinal<8: assert attempts==before
    assert f.source.source_session_snapshot()['requestAttempts']==before+1
    assert not any(c['operation']=='SCROLL_DOWN' for c in f.sent)
    assert f.auto._deadline==deadline
    # Explicitly prove expiry still ends the same pending request, with no renewal.
    f.now=deadline+.01;f.auto.poll()
    assert not f.auto._active and f.auto._reason=='ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED'

auto=f.auto
auto._observation={'trackBox':[1884,211,1890,771],'thumbBox':[1884,226,1890,445]}
auto._pixels_per_notch=None
assert auto._scroll_delta()==-1080  # 9 observed 30px notches; prediction <= half viewport.
auto._pixels_per_notch=60
assert auto._scroll_delta()==-480   # Actual larger motion reduces the next step.
auto._observation['thumbBox']=[1884,550,1890,769]
assert auto._scroll_delta()==-120   # Close to bottom: bounded single notch, still verify movement.
result={'passed':True,'retainedObservationTrace':trace,'hintsSavedSources':False,
    'hintsGrantedScrollOrFacts':False,'firstSupportRequestOpportunity':8,
    'waitingSourceRequestsBeforeReady':1,'oldActualFirstSupportedSourceOrdinal':8,
    'deadlineUnchangedAndEnforced':True,'scrollPredictions':[-1080,-480,-120],
    'notARealNewScrollOrCaptureValidation':True}
out=ROOT/'build/native-collection-repair-20261009/scheduler-result.json'
out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
