"""Prepare by default; one-shot 4+ready-mark+6+user-scroll+4 SOURCE evidence."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

import start_native_observation as entry

ROOT = entry.ROOT
HOST = ROOT / 'build/native-content-evidence-20261009/host/WgcLiveHarness.exe'
BUILD_RECEIPT = ROOT / 'build/native-content-evidence-20261009/host-build.json'


def prepare():
    # Require the explicitly built host, including independent-original support.
    receipt = json.loads(BUILD_RECEIPT.read_text(encoding='utf-8'))
    for name, digest in receipt['files'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Evidence host/source changed; rebuild preparation: ' + name)
    os.environ['NTE_NATIVE_HOST_EXE'] = str(HOST)
    result = entry.prepare()
    result.update(autoWarehouseCapture=False, captureFreshnessPolicy='wgc-delivery-v1',
        evidenceOnly=True, sourcePlan=[4, 6, 4], maxRequests=14,
        hostLimits={'sources': 16, 'requests': 32, 'absoluteSettlementSeconds': 70},
        configurationFilesModified=False, automaticInput=False)
    return result


def user_signal(output):
    if (output / 'STOP').exists():
        raise RuntimeError('USER_STOP')
    # Nonblocking input: Enter acknowledges only the currently prompted evidence stage.
    import msvcrt
    result = False
    while msvcrt.kbhit():
        char = msvcrt.getwch()
        if char.lower() == 'q':
            raise RuntimeError('USER_STOP')
        if char == '\r':
            result = True
    return result


async def collect(ws, output, record):
    async def control(operation):
        request = uuid.uuid4().hex
        await ws.send(json.dumps({'type': 'native_content_evidence',
            'operation': operation, 'requestId': request}))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            event = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.monotonic()))
            if event.get('type') == 'native_content_evidence_receipt' and event.get('requestId') == request:
                return event
        raise TimeoutError('EVIDENCE_CONTROL_TIMEOUT')

    pages = []
    result = {'automaticCaptureComplete': False, 'formalFactsQualified': False,
        'sourcePlan': [4, 6, 4], 'pages': pages}
    try:
        # No SOURCE/WAIT_STABLE requests before the one settlement is available.
        record('waiting-for-one-settlement', message='正常进行一局；保持仓库顶部。4张后按提示标记当前视口已显露；10张后按提示滚动一次再确认。q 或 --stop 停止。')
        wait_deadline = time.monotonic() + 1200
        while True:
            user_signal(output)
            ready = await control('prepare')
            if ready.get('ok'):
                break
            if ready.get('reason') not in {'NATIVE_NOT_SETTLEMENT', 'NATIVE_DRAFT_NOT_SAVED',
                    'NATIVE_SCOPE_UNAVAILABLE', 'EVIDENCE_LAUNCH_REQUIRED', 'PROCESSING_CANCEL_PENDING'}:
                raise RuntimeError(ready.get('reason'))
            if time.monotonic() >= wait_deadline:
                raise TimeoutError('SETTLEMENT_NOT_OBSERVED')
            await asyncio.sleep(.2)
        begun = await control('begin')
        if not begun.get('ok'):
            raise RuntimeError(begun.get('reason'))
        requests = 0
        visible_prompted = False
        scroll_prompted = False
        last_capture = None
        while len(pages) < 14:
            entered = user_signal(output)
            status = await control('status')
            if not status.get('ok'):
                raise RuntimeError(status.get('reason'))
            snapshot = status['snapshot']
            result['snapshot'] = snapshot
            pages[:] = status['pages']
            state = snapshot['state']
            if state == 'CLOSED':
                raise RuntimeError(snapshot['reason'])
            if state == 'OPEN':
                if time.monotonic() >= snapshot['deadline']:
                    raise TimeoutError('ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
                if snapshot['requestAttempts'] != requests or len(pages) != requests:
                    raise RuntimeError(snapshot['reason'] or 'EVIDENCE_ORIGINAL_NOT_SAVED')
                if pages and pages[-1]['deliveryProof']['captureId'] != last_capture:
                    proof = pages[-1]['deliveryProof']
                    last_capture = proof['captureId']
                    record('original-saved', ordinal=len(pages),
                        intendedPhase='reveal-candidate' if len(pages) <= 4 else
                            'same-viewport-candidate' if len(pages) <= 10 else 'second-viewport-candidate',
                        actualReadbackGapMs=None if len(pages) < 2 else
                            (proof['readbackCompletedNs'] - pages[-2]['deliveryProof']['readbackCompletedNs']) / 1e6,
                        page=pages[-1])
                if len(pages) == 14:
                    break
                if requests == 4 and status.get('userVisibleContentReadyNs') is None:
                    if not visible_prompted:
                        user_signal(output)  # discard buffered Enter before this stage's prompt
                        record('visible-content-ready-now', remainingSeconds=snapshot['deadline'] - time.monotonic(),
                            message='已保存4张：保持仓库顶部。目视当前视口已显露且没有明显继续揭示后，回本控制台按Enter。仅记开发观察标记，70秒截止继续流逝。')
                        visible_prompted = True
                    elif entered:
                        ack = await control('visible-content-ready')
                        if not ack.get('ok'):
                            raise RuntimeError(ack.get('reason'))
                        result['userVisibleContentReady'] = ack
                        record('USER_VISIBLE_CONTENT_READY', receipt=ack)
                    await asyncio.sleep(.05)
                    continue
                if requests == 10:
                    # The acknowledgement is returned at top-level, never a motion proof.
                    if status.get('manualScrollAcknowledgedNs') is None:
                        if not scroll_prompted:
                            user_signal(output)  # discard earlier Enter; no premature acknowledgement
                            record('one-manual-scroll-now', remainingSeconds=snapshot['deadline'] - time.monotonic(),
                                message='已保存10张：现在在游戏仓库向下滚动一次到第二视口，然后回本控制台按Enter。不要点击跳过/退出。')
                            scroll_prompted = True
                        elif entered:
                            ack = await control('manual-scroll-done')
                            if not ack.get('ok'):
                                raise RuntimeError(ack.get('reason'))
                            record('manual-scroll-user-acknowledged', receipt=ack)
                        await asyncio.sleep(.05)
                        continue
                reply = await control('page')
                if reply.get('ok'):
                    requests += 1
                    record('source-requested', ordinal=requests)
                elif reply.get('reason') != 'INDEPENDENT_REQUEST_INTERVAL_PENDING':
                    raise RuntimeError(reply.get('reason'))
            await asyncio.sleep(.05)
        result['terminationReason'] = 'EVIDENCE_PLAN_FINISHED'
    except (Exception, asyncio.CancelledError) as exc:
        result['terminationReason'] = str(exc) or type(exc).__name__
    finally:
        # Save the last admitted materials even when the console/Host stops mid-phase.
        try:
            last = await control('status')
            if last.get('ok'):
                pages[:] = last['pages']
                result['snapshot'] = last['snapshot']
        except Exception as exc:
            result['lastStatusError'] = type(exc).__name__
        try:
            result['endReceipt'] = await control('end')
        except Exception as exc:
            result['endReceiptError'] = type(exc).__name__
        (output / 'evidence-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        record('evidence-ended', reason=result['terminationReason'], originalCount=len(pages))
    return result['terminationReason'] == 'EVIDENCE_PLAN_FINISHED'


async def run(prepared, output):
    if not await entry.start(prepared, output, environment={'NTE_CONTENT_EVIDENCE_ONLY': '1',
            'NTE_CONTENT_EVIDENCE_ROOT': str(output / 'trial-drafts')}):
        return 1
    import websockets
    from start_native_delivery_candidate import stop_once
    logged_bytes = 0
    def record(kind, **details):
        nonlocal logged_bytes
        line = json.dumps({'kind': kind, 'utcNs': time.time_ns(),
            'monotonicNs': time.monotonic_ns(), **details}, ensure_ascii=False) + '\n'
        logged_bytes += len(line.encode('utf-8'))
        if logged_bytes > 4 * 1024 * 1024:
            raise RuntimeError('EVIDENCE_TELEMETRY_LIMIT_REACHED')
        with (output / 'evidence-events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(line)
        if kind == 'original-saved':
            print(f"已保存 {details['ordinal']}/14；原图间隔 {details['actualReadbackGapMs']} ms", flush=True)
        else:
            print(line, end='', flush=True)
    async with websockets.connect(f"ws://127.0.0.1:{prepared['port']}", max_size=1024 * 1024) as ws:
        try:
            completed = await collect(ws, output, record)
        finally:
            await stop_once(ws, record, 'CONTENT_EVIDENCE_ENDED')
    return 0 if completed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-authorized', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        output = args.output.resolve()
        if not output.is_relative_to((ROOT / 'build').resolve()):
            parser.error('--output must be inside the project build directory')
    else:
        output = None
    if args.stop:
        if args.start_authorized or output is None or not (output / 'prepared.json').is_file():
            parser.error('--stop requires the existing evidence --output')
        (output / 'STOP').write_text('USER_STOP\n', encoding='utf-8')
        return 0
    prepared = prepare()
    if not args.start_authorized:
        print(json.dumps({'preparedOnly': True, **prepared}, ensure_ascii=False, indent=2))
        return 0
    if output is None:
        parser.error('--start-authorized requires a fresh --output')
    return asyncio.run(run(prepared, output))


if __name__ == '__main__':
    raise SystemExit(main())
