"""One own-generated-window boundary comparison, six requests, 8s/10s."""
import hashlib
import json
import argparse
import os
from pathlib import Path
import run_timestamp_probe as controller

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/native-pool-boundary-20261006'
HOST = ROOT / 'build/native-delivery-20261006/host'
EXE = OUT / 'out/PoolBoundaryProbe.exe'

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--integrated',action='store_true',help='Exercise actual production CaptureDelivered three times')
    parser.add_argument('--candidate',type=Path)
    args=parser.parse_args()
    if args.integrated:
        if args.candidate is None:parser.error('--integrated requires a pinned --candidate')
        OUT=ROOT/'build/native-retained-boundary-20261006'; EXE=OUT/'qa/PoolBoundaryProbe.exe'
        manifest_path=args.candidate.resolve()
        os.environ['NTE_POOL_PROBE_INTEGRATED']='1'
    else:
        manifest_path=HOST.parent/'candidate-manifest.json'
        os.environ.pop('NTE_POOL_PROBE_INTEGRATED',None)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    HOST=Path(manifest['start']['environment']['NTE_NATIVE_HOST_EXE']).parent
    for path, expected in manifest['binaryFiles'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Pinned Host changed:'+path)
    for name in ('Microsoft.Windows.SDK.NET.dll','WinRT.Runtime.dll','NteHost.Protocol.dll'):
        if (HOST/name).read_bytes() != (EXE.parent/name).read_bytes():
            raise RuntimeError('QA dependency mismatch:'+name)
    plan={'productionCandidate':manifest['candidateId'],'experimentKind':'pool-boundary-own-window',
          'hypotheses':['production selector establishes bounded retained-buffer empty boundary'] if args.integrated else ['immediate Dispose allows refill during drain','holding the two checked-out buffers exposes a bounded null boundary'],
          'budget':{'requests':3 if args.integrated else 6,'maximumTakesPerBoundary':3,'workSeconds':8,'exitSeconds':10},
          'productionSelector':args.integrated,'controlledGapMs':0 if args.integrated else 30,'doesNotClaimIdenticalGameTiming':True,
          'probeSha256':hashlib.sha256(EXE.with_suffix('.dll').read_bytes()).hexdigest()}
    (OUT/'plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    controller.EVIDENCE=OUT;controller.HOST=HOST
    raise SystemExit(controller.run_once(plan,executable=EXE))
