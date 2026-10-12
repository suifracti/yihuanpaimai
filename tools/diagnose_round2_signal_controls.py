"""Reproduce the signal exclusions and real adjacent-item boundary measurements.

Only frozen geometry helpers are used. No matcher, catalog or repaired code runs.
"""
from pathlib import Path
import argparse
import json
import sys

sys.dont_write_bytecode = True
import cv2
import numpy as np
from diagnose_warehouse_round2_geometry import (
    WarehouseVisionV1, array_edges, correlations, gutters, trace_frames, sha, ROOT)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def image(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def run(args):
    main = args.source_root.resolve(); output = args.output.resolve()
    output.relative_to(main / 'build')
    if output.exists():
        raise ValueError('Evidence directory exists; use a fresh one')
    failure = read(args.trace)
    assert sha(ROOT / 'core/warehouse_vision.py') == failure['algorithmSha256']
    assert sha(Path(failure['source'])) == failure['sourceSha256']
    vision = WarehouseVisionV1.__new__(WarehouseVisionV1)
    x1,y1,x2,y2 = failure['boardCropXYXY']
    crop = image(Path(failure['source']))[y1:y2,x1:x2]
    grid = failure['probes']['frozen-measured']['grid']
    gx,gy = array_edges(crop)
    lo = max(16, int(min(crop.shape[:2]) * .05)); hi = max(lo+8, int(min(crop.shape[:2]) * .28))
    robust_period,score = vision._acf_period(np.median(gy,axis=1),lo,hi)
    phase = vision._grid_phase(np.median(gy,axis=1),robust_period)
    if phase > .45*robust_period:
        phase = max(0.,phase-robust_period)
    end = int(round(phase+grid['rows']*robust_period))
    masked = gy.copy()
    for target in failure['expectedVisibleOutlines']:
        x,y,w,h = target['sourceBoxXYWH']
        masked[y-y1:y-y1+h,x-x1:x-x1+w] = np.nan
    profiles = {'mean-board-without-footer':gy[:end].mean(axis=1),
                'mean-with-two-visible-object-regions-excluded':np.nanmean(masked,axis=1),
                'mean-board-no-footer-and-object-regions-excluded':np.nanmean(masked[:end],axis=1)}
    signals = {}
    for label,profile in profiles.items():
        ac = correlations(profile); p,s = vision._acf_period(profile,lo,hi)
        signals[label] = dict(period=p,score=s,nearbyACF={str(n):float(ac[n]) for n in range(int(robust_period)-2,int(robust_period)+3)})
    contribution = dict(algorithmSha256=failure['algorithmSha256'],catalogLoaded=False,
                        robustPhaseFromPixelProfile=phase,robustPeriodFromPixelProfile=robust_period,
                        bodyEndY=y1+end,signals=signals,
                        note='Diagnostic signal exclusions only; visible outlines are indexed ROI facts, not production size constants')
    control_case = read(main / 'build/offline-right-warehouse-20261003/final-development-control/results.json')['cases'][0]
    cx1,cy1,cx2,cy2 = control_case['boardCropXYXY']
    ccrop = image(main/control_case['source'])[cy1:cy2,cx1:cx2]
    cg = vision._measure_board_grid(ccrop,cx1,cy1)
    a,b = control_case['expectedSlots']
    ax,ay,aw,ah = a['sourceBoxXYWH']
    combined = dict(sourceBoxXYWH=[ax,ay,aw,ah+b['sourceBoxXYWH'][3]])
    edges = gutters(vision,ccrop,(cx1,cy1),cg,combined)
    gray = cv2.cvtColor(ccrop,cv2.COLOR_BGR2GRAY)
    seam_y = b['sourceBoxXYWH'][1]
    span_x1,span_x2 = int(ax+.28*aw)-cx1,int(ax+.72*aw)-cx1
    gap = {str(y):float(np.median(gray[y-cy1,span_x1:span_x2])) for y in range(seam_y-8,seam_y+9)}
    fg = cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
    nx,ny,nw,nh = failure['expectedVisibleOutlines'][0]['sourceBoxXYWH']
    mid_x = int(nx+grid['cell_w']); ys = int(ny+.28*grid['cell_h'])-y1; ye = int(ny+.72*grid['cell_h'])-y1
    internal = {str(x):float(np.median(fg[ys:ye,x-x1])) for x in range(mid_x-8,mid_x+9)}
    occ = [[vision._classify_grid_cell(ccrop,cx1,cy1,*cg['origin'],c,r,cg['cell_w'],cg['cell_h'])
            for c in range(cg['cols'])] for r in range(cg['rows'])]
    recovered,trace = trace_frames(vision,ccrop,(cx1,cy1),cg,occ,control_case['expectedSlots'])
    boundary = dict(source=control_case['source'],sourceSha256=sha(main/control_case['source']),
                    catalogLoaded=False,grid=cg,seamEdges=edges,crossGapGrayMedian=gap,
                    knownNecklaceInternalCrossGapGrayMedian=internal,
                    contoursAssociatedWithTwoIndependentFrames=[c for c in trace if c['targetIndices']],
                    identityTruth=None,quantity=None)
    output.mkdir(parents=True)
    for name,record in [('period-contributions.json',contribution),('adjacent-boundary.json',boundary)]:
        (output/name).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    assert sha(ROOT / 'core/warehouse_vision.py') == failure['algorithmSha256']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--trace',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args())
