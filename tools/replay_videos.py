"""Replay complete video timelines through the production vision worker.

Writes isolated history, per-frame observations and transition images. This is
a recognition/state/archive audit, not a GUI or Solver accuracy acceptance test.
Sampling is explicit; recordings are independent sessions, never spliced into
an invented continuous match. Inference uses its normal wall-clock throttles.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def validate_recorded_bills(entry, records, expected):
    """Check all writes, not just the final file after an incorrect overwrite."""
    errors = []
    signature = lambda value: (value.get('clearingPrice'), value.get('actualTotal'))
    wanted = [signature(value) for value in expected]
    actual = [signature(value.get('settlement') or {}) for value in records]
    if Counter(actual) != Counter(wanted):
        errors.append(f'Archived bills differ: expected {wanted}, got {actual}')
    for write in entry.get('archives') or []:
        if signature(write.get('settlement') or {}) not in wanted:
            errors.append(f'Intermediate/wrong bill archived at {write.get("seconds")}s')
    for record in records:
        st = record.get('settlement') or {}
        wanted_match = next((value for value in expected if signature(value) == signature(st)), None)
        if wanted_match:
            if st.get('realizedProfit') != wanted_match.get('profit'):
                errors.append('Archived profit differs from recording')
            if len(st.get('settlementItems') or []) != wanted_match.get('visibleItemCount'):
                errors.append('Archived visible item count differs from recording')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('videos', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--step', type=float, default=1.0)
    parser.add_argument('--start', type=float, default=0.0)
    parser.add_argument('--end', type=float)
    parser.add_argument('--expectations', type=Path, help='Manually checked video_replay/expectations.json')
    args = parser.parse_args()
    expected_matches = json.loads(args.expectations.read_text(encoding='utf-8'))['matches'] if args.expectations else []
    if args.step <= 0 or args.start < 0:
        parser.error('step must be positive and start nonnegative')
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'frames.jsonl').exists():
        parser.error('output already contains a replay; choose a new directory')
    sys.path[:0] = [str(root / p) for p in ('app', 'core')] + [str(root)]
    os.environ['YIHUAN_DATA_ROOT'] = str(output / 'data')
    os.environ['YIHUAN_UPPER_TAIL_CAPTURE_DIR'] = str(output / 'captures')
    os.environ['NTE_LOG_FILE'] = str(output / 'runtime.log')
    import cv2
    import business_sot
    business_sot._SOT_PATH = str(root / 'assets/business_sot_v06.json')
    business_sot.load_sot.cache_clear()
    from auto_archiver import AutoArchiver
    from current_match import CurrentMatch, FACT_KEYS
    from live_match_transport import LiveMatchReceiver
    from vision_pipeline import NTEVisionPipeline
    from vision_worker_loop import run_vision_capture_loop

    report = {'status': 'RUNNING', 'stepSeconds': args.step,
              'scope': 'vision-worker-state-archive; no GUI/Solver', 'videos': [], 'errors': []}
    report['sourceSha256'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ('core/vision_pipeline.py', 'core/settlement_item_recognizer.py',
                     'core/settlement_observation.py', 'core/scene_anchors.py', 'core/auto_archiver.py',
                     'core/visual_catalog.py', 'assets/items/visual_catalog_v2.json',
                     'assets/items/video_development_references_v1.json')}
    started = time.monotonic()
    def checkpoint():
        report['elapsedSeconds'] = round(time.monotonic() - started, 2)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    frames_log = (output / 'frames.jsonl').open('w', encoding='utf-8', buffering=1)
    events_log = (output / 'events.jsonl').open('w', encoding='utf-8', buffering=1)

    async def replay(path, video_index):
        cap = cv2.VideoCapture(str(path.resolve()))
        if not cap.isOpened():
            raise RuntimeError(f'Cannot open {path}')
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if fps <= 0 or count <= 0:
            raise RuntimeError(f'Invalid stream metadata: {path}')
        duration = count / fps
        end = min(args.end, duration) if args.end is not None else duration
        targets = sorted(set([min(count-1, round(t * fps)) for t in
                            (args.start + i * args.step for i in range(max(0, int((end-args.start)/args.step)+1)))
                            if t < end] + ([min(count-1, max(0, int(end*fps)-1))] if end > args.start else [])))
        entry = {'video': str(path.resolve()), 'duration': duration, 'fps': fps,
                 'frameCount': count, 'expectedSamples': len(targets), 'processed': 0,
                 'transitions': [], 'archives': [], 'status': 'RUNNING'}
        report['videos'].append(entry)
        with path.open('rb') as source:
            digest = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        entry['sha256'] = digest.hexdigest()
        pipeline = NTEVisionPipeline(catalog_path=str(root / 'assets/catalog_065.json'))
        current, receiver_match = CurrentMatch(), CurrentMatch()
        receiver = LiveMatchReceiver()
        class RecordingArchiver(AutoArchiver):
            def archive_match(self, ctx):
                saved = super().archive_match(ctx)
                if saved:
                    entry['archives'].append({'seconds': state['seconds'], **{
                        k: saved.get(k) for k in ('id', 'lifecycleStatus')},
                        'settlement': {k: (saved.get('settlement') or {}).get(k)
                                       for k in ('clearingPrice', 'actualTotal', 'winner')}})
                return saved
        archiver = RecordingArchiver(db_paths=[str(output / 'data' / f'history-{video_index}.json')])
        stop = {'stop': False}
        state = {'index': 0, 'seconds': 0, 'signature': None, 'frame': None, 'decoded': -1}
        try:
            origin = datetime.strptime(path.stem, '%Y-%m-%d %H-%M-%S').replace(tzinfo=timezone(timedelta(hours=8)))
        except ValueError:
            origin = datetime(2000, 1, 1, tzinfo=timezone.utc)
        def provider():
            if state['index'] >= len(targets):
                stop['stop'] = True
                return None, None, ''
            target = targets[state['index']]
            # MKV frame counts can be duration estimates, several frames beyond
            # decodable EOF. Read the tail to its actual end and retain its final
            # decoded image instead of inventing missing frames from metadata.
            if state['index'] == len(targets) - 1:
                frame = None
                while args.end is None or state['decoded'] < target:
                    ok, candidate = cap.read()
                    if not ok:
                        entry['decodedEofFrame'] = state['decoded']
                        break
                    state['decoded'] += 1
                    frame = candidate
                if frame is not None:
                    entry['tailMetadataDeltaFrames'] = state['decoded'] - target
                    if state['decoded'] < target - max(3, round(fps * .10)):
                        stop['stop'] = True
                        raise RuntimeError(f'Premature decode EOF: {state["decoded"]}, expected {target}')
                    state.update(index=state['index']+1, seconds=state['decoded']/fps, frame=frame)
                    return 1, frame, (origin + timedelta(seconds=state['decoded']/fps)).isoformat()
                stop['stop'] = True
                raise RuntimeError('No decodable tail frame')
            while state['decoded'] < target:
                if not cap.grab():
                    stop['stop'] = True
                    raise RuntimeError(f'decode ended at {state["decoded"]}, target {target}')
                state['decoded'] += 1
            ok, frame = cap.retrieve()
            if not ok:
                stop['stop'] = True
                raise RuntimeError(f'Cannot retrieve frame {target}')
            state.update(index=state['index']+1, seconds=target/fps, frame=frame)
            return 1, frame, (origin + timedelta(seconds=target/fps)).isoformat()
        def sync(ctx):
            current.apply_facts({k: ctx[k] for k in FACT_KEYS if k in ctx}, source='vision')
        def log(tag, message):
            event = {'video': video_index, 'seconds': state['seconds'], 'tag': tag, 'message': message}
            events_log.write(json.dumps(event, ensure_ascii=False) + '\n')
            if 'error' in message.lower():
                report['errors'].append(event)
        async def publish(payload):
            if not payload.get('visionState'):
                return
            accepted = receiver.apply(payload['visionState'], receiver_match)
            if not accepted:
                report['errors'].append({'video': video_index, 'seconds': state['seconds'], 'message': 'receiver rejected snapshot'})
            fields = ('scene', 'round', 'timer', 'myName', 'winner', 'inAuction', 'isSettlement',
                      'settlementReady', 'settlementItemCount', 'settlementExactItemCount',
                      'settlementUnknownItemCount', 'settlementExactValueSum', 'settlementLedgerVerified',
                      'settlementFileEvidenceStatus', 'currentLeaderBid', 'venue', 'box', 'q', 'goldAvg')
            fields += ('settlementObservationAt',)
            row = {k: payload.get(k) for k in fields}
            row.update(video=video_index, seconds=state['seconds'], matchId=current.id, receiverAccepted=accepted)
            st = payload.get('settlementData') or {}
            row['settlement'] = {k: st.get(k) for k in ('clearingPrice', 'actualTotal', 'profit', 'winner', 'animationComplete')}
            row['items'] = [{k: item.get(k) for k in ('name', 'itemId', 'exactItemId', 'price', 'row', 'col', 'widthCells', 'heightCells', 'status', 'groupingAmbiguous')}
                            for item in (payload.get('settlementItems') or [])]
            signature = (row['scene'], row['round'], row['settlementReady'], current.id)
            if signature != state['signature']:
                image_name = f'v{video_index}-{state["seconds"]:08.3f}.jpg'
                cv2.imencode('.jpg', state['frame'])[1].tofile(str(output / image_name))
                entry['transitions'].append({k: row[k] for k in ('seconds', 'scene', 'round', 'matchId') } | {'image': image_name})
                state['signature'] = signature
            frames_log.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
            entry['processed'] += 1
            entry['lastSeconds'] = state['seconds']
            checkpoint()
            if entry['processed'] % 10 == 0:
                print(f'VIDEO {video_index} {state["seconds"]:.1f}/{duration:.1f}s {row["scene"]} R{row["round"]}', flush=True)
        try:
            await run_vision_capture_loop(pipeline=pipeline, frame_provider=provider, stop_flag=stop,
                publish_fn=publish, archiver=archiver, current_match=current, sync_context_fn=sync,
                fps=1000, log_fn=log)
            entry['status'] = 'COMPLETE' if entry['processed'] == len(targets) else 'INCOMPLETE'
            expected = [value for value in expected_matches if value['video'] == path.name
                        and args.start <= value['referenceSeconds'] < end]
            if expected:
                history = output / 'data' / f'history-{video_index}.json'
                records = json.loads(history.read_text(encoding='utf-8'))['records'] if history.exists() else []
                entry['expectationErrors'] = validate_recorded_bills(entry, records, expected)
                for error in entry['expectationErrors']:
                    report['errors'].append({'video': video_index, 'message': error})
        finally:
            cap.release()
            worker = getattr(pipeline, '_async_intel_worker', None)
            if worker and hasattr(worker, 'shutdown'):
                worker.shutdown()
            checkpoint()
    try:
        for i, path in enumerate(args.videos, 1):
            asyncio.run(replay(path, i))
        report['status'] = 'COMPLETE' if not report['errors'] and all(v['status'] == 'COMPLETE' for v in report['videos']) else 'ISSUES'
    except BaseException as exc:
        report['status'] = 'INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'FAILED'
        report['errors'].append({'message': f'{type(exc).__name__}: {exc}'})
        raise
    finally:
        checkpoint()
        frames_log.close()
        events_log.close()
    return 0 if report['status'] == 'COMPLETE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
