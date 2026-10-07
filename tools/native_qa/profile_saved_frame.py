"""Profile one saved BMP through the real Engine, without capture or pipe startup.

All state/history/profile output stays under build/. This is an offline timing
comparison; the saved final context cannot reproduce unlogged prior-frame state.
"""
from __future__ import annotations

import argparse
import copy
import cProfile
import hashlib
import importlib.util
import json
from pathlib import Path
import pstats
import sys
import time
from types import SimpleNamespace

import cv2

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frame', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--expected-pixel-sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if ROOT / 'build' not in output.parents:
        raise ValueError('Output must be a new directory below project build/')
    output.mkdir(parents=True, exist_ok=False)
    raw = Path(args.frame).read_bytes()
    offset = int.from_bytes(raw[10:14], 'little')
    pixel_sha = hashlib.sha256(raw[offset:]).hexdigest()
    if pixel_sha != args.expected_pixel_sha256:
        raise ValueError('Saved BMP does not match the accepted frame evidence')
    frame = cv2.imread(str(Path(args.frame).resolve()))
    if frame is None:
        raise ValueError('Saved BMP cannot be decoded')
    state = json.loads(Path(args.state).read_text(encoding='utf-8'))
    records_path = Path(args.frame).resolve().parent / 'frame_records.ndjson'
    records = [json.loads(line) for line in records_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    original = next(record for record in reversed(records) if record.get('pixelSha256') == pixel_sha)
    header = copy.deepcopy(original['header'])
    path = ROOT / 'architecture/v2/host/engine_v22/nte_engine_v22.py'
    spec = importlib.util.spec_from_file_location('offline_saved_frame_engine', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    preload_started = time.perf_counter()
    engine = module.RealEngine(SimpleNamespace(
        session_id='offline-saved-frame-profile', nonce='offline-only', pipe_name='unused',
        frame_buffer_name='unused', frame_buffer_size=0, work_dir=str(output),
        generation_id=1, log=str(output / 'engine-profile.jsonl'), fault='',
        data_origin='live-trial', catalog=str(ROOT / 'assets/catalog_065.json')))
    preload_seconds = time.perf_counter() - preload_started
    engine.pipeline.current_context = copy.deepcopy(state.get('pipelineContext') or {})
    engine.pipeline._last_loadout_ts = 0.0
    messages = []
    engine.send = lambda kind, payload, *a, **kw: messages.append((kind, payload))
    stamp = module.qpc_ns()
    item = {'header': header, 'bgr': frame,
            'bufferIndex': 0, 'rawSha256': pixel_sha, 'receivedNs': stamp,
            'readCompletedNs': stamp, 'ackSent': True, 'identityInvalidationGeneration': 0}
    profiler = cProfile.Profile()
    profiler.runcall(engine._process_frame, item)
    with (output / 'profile.txt').open('w', encoding='utf-8') as stream:
        pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(20)
    traces = [json.loads(line) for line in (output / 'engine-profile.jsonl').read_text(encoding='utf-8').splitlines()]
    processed = next((entry['details'] for entry in traces if entry['event'] == 'frame.processed'), None)
    result = {'scope': 'one saved accepted frame, offline diagnostic comparison only',
              'inputPixelSha256': pixel_sha, 'preloadSecondsExcluded': preload_seconds,
              'originalFrameHeader': header,
              'contextSeed': 'saved final context; original preceding frame context unavailable',
              'transport': 'inert send adapter, no pipe/MMF/Host/capture/input',
              'processed': processed, 'processingErrors': engine.processing_errors,
              'historical4678msSubstageRecovered': False}
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if engine._identity_analyzer is not None:
        engine._identity_analyzer.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if processed and not engine.processing_errors else 1


if __name__ == '__main__':
    raise SystemExit(main())
