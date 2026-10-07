"""Optional retained-material analysis. No WGC, game, input or live configuration.

Raw game originals are deliberately not a required repository fixture. The
portable tests use the independent procedural renderer. This explicit tool
requires a retained real-result.json and fails if its originals are absent.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'app'), str(ROOT/'core')]
from native_warehouse_sampling_model import CommonSamplingModel, ContentLayout


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve()
    if ROOT/'build' not in output.parents:
        parser.error('output must be under this project build/')
    run=json.loads(args.manifest.read_text(encoding='utf-8'))
    # Fixed diagnostic geometry and references, declared BEFORE evaluation.
    # No claim that they are calibrated live/same-render-layer references.
    model=CommonSamplingModel(ContentLayout((1315,214,1877,776),
        ((1180,250,1220,290),(1200,450,1240,490),(1150,650,1190,690),(1210,730,1250,770)),
        'diagnostic layout from retained originals, not calibrated live geometry'))
    results, previous = [], None
    for i, desc in enumerate(run['verifiedOriginals']):
        raw=Path(desc['bmpPath']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=desc['bmpSha256']:
            raise ValueError('ORIGINAL_HASH_CHANGED')
        frame=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
        if frame is None or frame.shape!=(1080,1920,3):
            raise ValueError('DIAGNOSTIC_GEOMETRY_UNPROVEN')
        if previous is not None:
            result=model.compare(previous,frame)
            result.update(fromOrdinal=i,toOrdinal=i+1)
            results.append(result)
        previous=frame
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pairs':len(results),'conditionallySupported':sum(r['qualified'] for r in results),
                      'newCapture':False,'productionEnabled':False}))


if __name__=='__main__': main()
