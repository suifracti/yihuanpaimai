"""Read-only pixel-stage diagnosis of known regressions; never loads a catalog.

Grid interventions below are causal probes, not a repair or a passing test.
Expected frames come from the previously reviewed visible outlines, with no IDs.
"""
from pathlib import Path
import argparse
import ast
import copy
import hashlib
import inspect
import json
import sys
import textwrap

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
import cv2
import numpy as np
from warehouse_vision import WarehouseVisionV1


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def array_edges(crop):
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return (np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)),
            np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)))


def correlations(profile):
    x = profile.astype(np.float32) - float(profile.mean())
    ac = np.correlate(x, x, mode='full')[len(x)-1:]
    return ac / ac[0] if ac[0] > 1e-6 else ac * 0


def overlap(a, b):
    x, y = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0]+a[2], b[0]+b[2]), min(a[1]+a[3], b[1]+b[3])
    area = max(0, right-x) * max(0, bottom-y)
    return area / max(1, a[2]*a[3] + b[2]*b[3] - area)


def trace_frames(vision, crop, offset, grid, occupancy, expected):
    """Observe the frozen function's real reject branches, without replacing it."""
    function = WarehouseVisionV1._complete_frame_slots
    lines, start = inspect.getsourcelines(function)
    syntax = ast.parse(textwrap.dedent(''.join(lines)))
    rejects = {}
    accepted = set()
    for node in ast.walk(syntax):
        if isinstance(node, ast.If) and any(isinstance(n, ast.Continue) for n in node.body):
            for n in node.body:
                if isinstance(n, ast.Continue):
                    rejects[start+n.lineno-1] = ast.unparse(node.test)
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == 'recovered'
                and node.value.func.attr == 'append'):
            accepted.add(start+node.lineno-1)
    records = []

    def observe(frame, event, arg):
        if frame.f_code is not function.__code__ or event != 'line':
            return observe
        if frame.f_lineno not in rejects and frame.f_lineno not in accepted:
            return observe
        values = frame.f_locals
        x, y, width, height = [int(values[k]) for k in ('x', 'y', 'width', 'height')]
        box = [x+offset[0], y+offset[1], width, height]
        associations = [i for i, target in enumerate(expected) if overlap(box, target['sourceBoxXYWH']) >= .15]
        contour_area = float(cv2.contourArea(values['contour']))
        if not associations and contour_area < 1.25 * grid['cell_w'] * grid['cell_h']:
            return observe
        band = max(1, int(round(.06 * min(grid['cell_w'], grid['cell_h']))))
        mask, value = values['mask'], values['value']
        bounds = [(y,y+band,x+band,x+width-band),
                  (y+height-band,y+height,x+band,x+width-band),
                  (y+band,y+height-band,x,x+band),
                  (y+band,y+height-band,x+width-band,x+width)]
        inner_bounds = [(y+band,y+2*band,x+band,x+width-band),
                        (y+height-2*band,y+height-band,x+band,x+width-band),
                        (y+band,y+height-band,x+band,x+2*band),
                        (y+band,y+height-band,x+width-2*band,x+width-band)]
        coverage, contrast = [], []
        for i, (bound, inward) in enumerate(zip(bounds, inner_bounds)):
            a,b,c,d = bound
            ia,ib,ic,id_ = inward
            side = mask[a:b,c:d]
            stroke, inner = value[a:b,c:d], value[ia:ib,ic:id_]
            axis = 0 if i < 2 else 1
            coverage.append(float(np.mean(np.any(side, axis=axis))) if side.size else None)
            contrast.append(float(stroke.max(axis=axis).mean()-inner.mean()) if stroke.size and inner.size else None)
        records.append(dict(rarity=values['rarity'], sourceBoxXYWH=box,
                            contourArea=contour_area, rectangularity=contour_area/(width*height),
                            targetIndices=associations, sidesOrder=['top','bottom','left','right'],
                            colourCoverage=coverage, strokeMinusInwardValue=contrast,
                            branch=('ACCEPT' if frame.f_lineno in accepted else rejects[frame.f_lineno]),
                            sourceLine=frame.f_lineno))
        return observe

    old_trace = sys.gettrace()
    try:
        sys.settrace(observe)
        recovered = vision._complete_frame_slots(crop, *offset, *grid['origin'],
                                                  grid['cell_w'], grid['cell_h'],
                                                  grid['cols'], grid['rows'], occupancy)
    finally:
        sys.settrace(old_trace)
    return recovered, records


def gutters(vision, crop, offset, grid, target):
    col,row,wc,hc = vision._map_box_to_cells(
        tuple(v-o if i<2 else v for i,(v,o) in enumerate(zip(target['sourceBoxXYWH'],[*offset,0,0]))),
        grid,*offset)
    ox,oy = grid['origin']; cw,ch = grid['cell_w'],grid['cell_h']
    result=[]
    for r in range(row,row+hc):
        for c in range(col,col+wc):
            for dc,dr in [(1,0),(0,1)]:
                if c+dc>=col+wc or r+dr>=row+hc:
                    continue
                a = vision._side_frame_strength(crop,*offset,ox,oy,cw,ch,c,r,'right' if dc else 'bottom')
                b = vision._side_frame_strength(crop,*offset,ox,oy,cw,ch,c+dc,r+dr,'left' if dc else 'top')
                gutter = vision._has_item_gutter(crop,*offset,ox,oy,cw,ch,c,r,c+dc,r+dr)
                interior = vision._shared_edge_is_interior(crop,*offset,ox,oy,cw,ch,c,r,c+dc,r+dr)
                result.append(dict(cells=[[r,c],[r+dr,c+dc]],darkGutter=bool(gutter),
                                   opposingFrameStrength=[a,b],sharedEdgeInterior=bool(interior)))
    return result


def run(args):
    main=args.source_root.resolve(); output=args.output.resolve()
    output.relative_to(main/'build')
    if output.exists():
        raise ValueError('Prior evidence is immutable; choose a fresh output directory')
    algorithm=ROOT/'core/warehouse_vision.py'
    before=sha(algorithm)
    baseline=json.loads((main/'build/offline-right-warehouse-round2-20261003/diagnosis-baseline.json').read_text(encoding='utf-8'))
    assert before==baseline['algorithmAndDataHashes']['core/warehouse_vision.py']
    prior=json.loads((main/'build/offline-right-warehouse-20261003/reserved-repeat-final/results.json').read_text(encoding='utf-8'))
    case=next(c for c in prior['cases'] if c['id']=='reserved-different-match-icons')
    source=main/case['source']
    assert sha(source)==case['sourceFileSha256']
    frame=cv2.imdecode(np.fromfile(str(source),dtype=np.uint8),cv2.IMREAD_COLOR)
    x1,y1,x2,y2=case['boardCropXYXY']; offset=(x1,y1)
    crop=frame[y1:y2,x1:x2]
    # No constructor: no catalog, template, candidate, identity or pricing input.
    vision=WarehouseVisionV1.__new__(WarehouseVisionV1)
    grid=vision._measure_board_grid(crop,*offset)
    gx,gy=array_edges(crop)
    lo=max(16,int(min(crop.shape[:2])*.05)); hi=max(lo+8,int(min(crop.shape[:2])*.28))
    profiles={'x-mean':gx.mean(axis=0),'y-mean':gy.mean(axis=1),
              'x-median':np.median(gx,axis=0),'y-median':np.median(gy,axis=1)}
    signals={}
    period=int(round(grid['cell_w']))
    for label, profile in profiles.items():
        ac=correlations(profile)
        p,score=vision._acf_period(profile,lo,hi)
        signals[label]=dict(selectedPeriod=p,selectedScore=score,
                           nearbyACF={str(n):float(ac[n]) for n in range(period-2,period+3)})
    shared=copy.deepcopy(grid); shared['cell_h']=grid['cell_w']
    rephase=copy.deepcopy(shared)
    phase=vision._grid_phase(profiles['y-mean'],shared['cell_h'])
    if phase>.45*shared['cell_h']:
        phase=max(0.,phase-shared['cell_h'])
    rephase['origin']=(grid['origin'][0],y1+phase)
    probes={}
    for label,g in [('frozen-measured',grid),('square-period-only-causal-probe',shared),
                    ('square-period-and-rephase-causal-probe',rephase)]:
        occ=[[vision._classify_grid_cell(crop,*offset,*g['origin'],c,r,g['cell_w'],g['cell_h'])
              for c in range(g['cols'])] for r in range(g['rows'])]
        recovered,trace=trace_frames(vision,crop,offset,g,copy.deepcopy(occ),case['expectedSlots'])
        slots=vision._group_occupied_cells(copy.deepcopy(occ),crop,*offset,*g['origin'],g['cell_w'],g['cell_h'])
        probes[label]=dict(grid=g,occupancy=occ,recovered=recovered,frameRejectTrace=trace,
                          slots=slots,internalEdges=[gutters(vision,crop,offset,g,t) for t in case['expectedSlots']])
        print(json.dumps(dict(probe=label,period=[g['cell_w'],g['cell_h']],origin=g['origin'],
                              recovered=len(recovered),components=len(slots)),ensure_ascii=False))
    output.mkdir(parents=True)
    cv2.imencode('.png',crop)[1].tofile(str(output/'known-regression-board.png'))
    result=dict(algorithmSha256=before,algorithmRoot=str(ROOT),source=str(source),sourceSha256=sha(source),
                boardCropXYXY=case['boardCropXYXY'],catalogLoaded=False,matcherConstructed=False,
                candidateGeometryUsed=False,knownRegression=True,identityTruth=None,quantity=None,
                expectedVisibleOutlines=case['expectedSlots'],signals=signals,probes=probes,
                causalProbePolicy='Diagnostic geometry inputs only, not implemented repairs or passing validation',
                sourceUnmodified=before==sha(algorithm),liveCaptureUsed=False)
    (output/'trace.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    assert result['sourceUnmodified']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args())
