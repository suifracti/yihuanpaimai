"""Pinned, one-shot acceptance launcher. Default only prepares; never captures.

--start-authorized selects the already-approved delivery/auto-collection options
and uses Main's existing start/stop commands. Monitoring does not drive gameplay
or introduce another match lifecycle. Originals remain in the existing stores.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import time

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / 'build/native-retained-boundary-20261006/candidate-manifest.json'
POLICY = 'wgc-delivery-v1'


def prepare(candidate=CANDIDATE):
    candidate = candidate.resolve()
    if not candidate.is_relative_to((ROOT / 'build').resolve()):
        raise ValueError('Candidate manifest must be inside build/')
    manifest = json.loads(candidate.read_text(encoding='utf-8'))
    for group in ('scopeFiles', 'inheritedRuntimeDependencies', 'binaryFiles'):
        for name, expected in manifest[group].items():
            file = ROOT / name
            if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
                raise RuntimeError('Pinned candidate changed: ' + name)
    spec = importlib.util.spec_from_file_location('native_one_shot_start', ROOT / 'tools/start_native_observation.py')
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    os.environ['NTE_NATIVE_HOST_EXE'] = manifest['start']['environment']['NTE_NATIVE_HOST_EXE']
    prepared = entry.prepare()
    with socket.socket() as probe:
        probe.settimeout(.2)
        occupied = probe.connect_ex(('127.0.0.1', prepared['port'])) == 0
    host_key = Path(prepared['hostExe']).relative_to(ROOT).as_posix()
    receipt = {'preparedOnly': True, 'candidateId': manifest['candidateId'],
        'candidateManifest': str(candidate), 'existingAssistantBusOccupied': occupied,
        'hostExe': prepared['hostExe'], 'hostSha256': manifest['binaryFiles'][host_key],
        'capturePolicyOnStart': POLICY, 'automaticSettlementCollectionOnStart': True,
        'currentConfigPolicy': prepared['captureFreshnessPolicy'],
        'configSelectionOnlyAfterStartAuthorization': True,
        'sourceLimits': {'originals': 16, 'requests': 32, 'seconds': 70},
        'monitorLimitSeconds': 1200, 'waitForNaturalNextMatchSeconds': 120,
        'noCaptureNoInputNoAssistantLaunch': True}
    return entry, prepared, manifest, receipt


def select_options(manifest, candidate=CANDIDATE):
    path = ROOT / 'app/config.json'
    original = path.read_bytes()
    expected = manifest['scopeFiles']['app/config.json']
    if hashlib.sha256(original).hexdigest() != expected:
        raise RuntimeError('Configuration changed after preparation; refusing overwrite')
    config = json.loads(original.decode('utf-8'))
    config['app']['captureFreshnessPolicy'] = POLICY
    config['app']['nativeAutoWarehouseCapture'] = True
    selected = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    pending = candidate.resolve().parent / 'selected-launch-options.json'
    pending.write_text(selected, encoding='utf-8')
    if path.read_bytes() != original:
        raise RuntimeError('Concurrent configuration edit; refusing overwrite')
    os.replace(pending, path)  # Only these explicit startup choices differ; no runtime switch/restore.


class Recorder:
    def __init__(self, output):
        self.output = output
        self.begun = time.perf_counter_ns()
        startup = output / 'startup.jsonl'
        if startup.is_file():
            first = json.loads(startup.read_text(encoding='utf-8').splitlines()[0])
            self.begun = first['perfCounterNs'] - int(first['elapsedMs'] * 1e6)
        self.bytes = 0

    def __call__(self, kind, **details):
        row = {'kind': kind, 'utcNs': time.time_ns(), 'monotonicNs': time.monotonic_ns(),
               'elapsedMs': (time.perf_counter_ns() - self.begun) / 1e6, **details}
        text = json.dumps(row, ensure_ascii=False) + '\n'
        self.bytes += len(text.encode('utf-8'))
        if self.bytes > 16 * 1024 * 1024:
            raise RuntimeError('Acceptance telemetry budget exhausted')
        with (self.output / 'acceptance-events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(text)
        if kind in {'observation-started', 'original-saved', 'capture-ended', 'observation-ended', 'stop-receipt'}:
            print(text, end='', flush=True)


class NativeRunLogTail:
    """Follow stdout and the active background-readonly redirected diagnostic log."""
    def __init__(self, output):
        self.output = Path(output)
        self.native_root = (ROOT / 'build/native-observation').resolve()
        self.session_log = None
        self.tails = {}
        self.seen_lines = set()

    def _discover_session_log(self, line):
        if 'STARTUP:NATIVE_IDENTITY' not in line:
            return
        start = line.find('{')
        if start < 0:
            return
        try:
            session_dir = Path(json.loads(line[start:]).get('sessionDirectory') or '').resolve()
        except (OSError, TypeError, ValueError):
            return
        if (session_dir.name.startswith('session-') and session_dir.parent == self.native_root):
            self.session_log = session_dir / 'main-diagnostic.log'

    def _drain(self, channel, path):
        if path is None or not path.is_file():
            return []
        key = path.resolve()
        tail = self.tails.get(key)
        if tail is None:
            tail = {'file': key.open(encoding='utf-8', errors='replace'), 'partial': ''}
            self.tails[key] = tail
        stream = tail['file']
        if key.stat().st_size < stream.tell():
            stream.seek(0)
            tail['partial'] = ''
        tail['partial'] += stream.read(256 * 1024)
        lines = tail['partial'].split('\n')
        tail['partial'] = lines.pop()
        result = []
        for line in lines:
            if channel == 'stdout':
                self._discover_session_log(line)
            digest = hashlib.sha256(line.encode('utf-8', errors='replace')).digest()
            if digest in self.seen_lines:
                continue
            self.seen_lines.add(digest)
            result.append((channel, line))
        return result

    def poll(self):
        # stdout announces the session directory; then the redirected stream can be tailed too.
        rows = self._drain('stdout', self.output / 'main.log')
        rows.extend(self._drain('redirected', self.session_log))
        return rows

    def close(self):
        for tail in self.tails.values():
            tail['file'].close()
        self.tails.clear()


async def stop_once(ws, record, reason):
    await ws.send(json.dumps({'type': 'stop_live_vision'}))
    def safe_record(kind, **details):
        try:
            record(kind, **details)
        except (OSError, RuntimeError):
            print(json.dumps({'kind': kind, **details}, ensure_ascii=False), flush=True)
    safe_record('stop-request', reason=reason)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            event = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.monotonic()))
        except asyncio.TimeoutError:
            break
        if event.get('type') == 'native_stop_receipt':
            safe_record('stop-receipt', receipt=event, processExitConfirmed=event.get('processExitConfirmed') is True)
            return
    safe_record('stop-receipt', processExitConfirmed=False, reason='Host exit not confirmed by deadline')


async def monitor(prepared, output, record):
    import websockets
    log_tailer = NativeRunLogTail(output)
    first_match = None
    first_generation = None
    capture_ended = False
    lobby_deadline = None
    last_snapshot = None
    cross_match = False
    reason = 'MONITOR_DEADLINE'
    deadline = time.monotonic() + 1200  # Harness observation only; SOURCE still has its own 70s limit.
    async with websockets.connect(f"ws://127.0.0.1:{prepared['port']}", max_size=8 * 1024 * 1024) as ws:
        try:
            while time.monotonic() < deadline:
                if lobby_deadline is not None and time.monotonic() >= lobby_deadline:
                    reason = 'NO_NATURAL_NEXT_MATCH_WITHIN_MONITOR_WINDOW'; break
                for source_log, line in log_tailer.poll():
                    if 'STARTUP:' in line:
                        record('startup-log', sourceLog=source_log, line=line)
                    if 'WAREHOUSE:NATIVE_AUTO' not in line:
                        continue
                    start = line.find('{')
                    if start < 0:
                        record('collection-log', sourceLog=source_log, line=line)
                        continue
                    try:
                        diagnostic = json.loads(line[start:])
                    except ValueError:
                        record('collection-log', sourceLog=source_log, line=line)
                        continue
                    kind = diagnostic.get('kind', 'collection-log')
                    record(kind, sourceLog=source_log, diagnostic=diagnostic,
                           message='已保存结算原页' if kind == 'original-saved' else None)
                    if kind == 'capture-ended':
                        capture_ended = True
                        if diagnostic.get('finalizationReason') != 'COMPLETE':
                            reason = 'COLLECTION_PARTIAL:' + str(diagnostic.get('reason'))
                            break
                if reason.startswith('COLLECTION_PARTIAL:'):
                    break
                try:
                    event = json.loads(await asyncio.wait_for(ws.recv(), .25))
                except asyncio.TimeoutError:
                    continue
                view = {**event, **(event.get('currentMatch') or {})}
                health = event.get('visionHealth') or view.get('visionHealth') or {}
                scene = view.get('scene') or health.get('scene')
                match = view.get('matchId') or view.get('id')
                snapshot = {key: view.get(key) for key in (
                    'matchId', 'scene', 'factsRevision', 'lifecycleStatus', 'observationSessionId',
                    'nativeInstanceDecisionGeneration', 'effectiveCaptureFreshnessPolicy',
                    'deliveryAgeMs', 'originStatus', 'nextMatchPreparation', 'sourceMatchGeneration',
                    'matchGeneration', 'target', 'capturedAtNs', 'sourceTimestampNs', 'frameSequence', 'deliveryProof')}
                snapshot['visionHealth'] = health
                if snapshot != last_snapshot:
                    record('observation-state', snapshot=snapshot)
                    last_snapshot = snapshot
                effective = view.get('effectiveCaptureFreshnessPolicy') or health.get('captureFreshnessPolicy')
                if effective is not None and effective != POLICY:
                    reason = 'CAPTURE_POLICY_MISMATCH'; break
                if health.get('stage') in {'native-error', 'native-paused', 'native-stopped'}:
                    reason = str(health.get('reason') or health['stage']); break
                generation = view.get('sourceMatchGeneration')
                if scene == 'IN_AUCTION' and match and health.get('stage') == 'native-frame':
                    if first_match is None:
                        first_match = match
                        first_generation = generation
                    elif (capture_ended and lobby_deadline is not None and match != first_match
                          and type(first_generation) is int and type(generation) is int
                          and generation > first_generation):
                        cross_match = True; reason = 'NATURAL_NEXT_MATCH_OBSERVED'; break
                if capture_ended and scene == 'AUCTION_LOBBY':
                    if lobby_deadline is None:
                        lobby_deadline = time.monotonic() + 120
                if lobby_deadline is not None and time.monotonic() >= lobby_deadline:
                    reason = 'NO_NATURAL_NEXT_MATCH_WITHIN_MONITOR_WINDOW'; break
        except Exception as exc:
            reason = 'MONITOR_EXCEPTION:' + type(exc).__name__ + ':' + str(exc)
            raise
        finally:
            log_tailer.close()
            try:
                record('observation-ended', reason=reason, naturalNextMatchObserved=cross_match,
                       evidenceMeaning='delivery only; source-time defect not fixed; page/component counts are not item totals')
            except (OSError, RuntimeError):
                print(json.dumps({'kind': 'observation-ended', 'reason': reason}, ensure_ascii=False), flush=True)
            try:
                await stop_once(ws, record, reason)
            except Exception as exc:
                record('stop-receipt', processExitConfirmed=False,
                       reason='Stop transport failed: ' + type(exc).__name__ + ':' + str(exc))


async def start(entry, prepared, manifest, receipt, output):
    if output.exists() or not output.resolve().is_relative_to((ROOT / 'build').resolve()):
        raise ValueError('Use a fresh output directory inside build/')
    if receipt['existingAssistantBusOccupied']:
        raise RuntimeError('Assistant bus occupied; refusing to command or replace an existing assistant')
    select_options(manifest, Path(receipt['candidateManifest']))
    prepared['captureFreshnessPolicy'] = POLICY
    prepared['autoWarehouseCapture'] = True
    os.environ['NTE_DISABLE_ICON'] = '1'  # Do not run the legacy icon injector against game windows.
    print(json.dumps({'kind': 'authorized-launch', 'candidateId': receipt['candidateId'], 'hostExe': prepared['hostExe'],
                      'capturePolicy': POLICY, 'configOptionsSelected': True}, ensure_ascii=False), flush=True)
    if not await entry.start(prepared, output):
        record = Recorder(output)
        try:
            import websockets
            async with websockets.connect(f"ws://127.0.0.1:{prepared['port']}", open_timeout=2) as ws:
                await stop_once(ws, record, 'START_FAILED')
        except Exception as exc:
            record('stop-receipt', processExitConfirmed=False, reason=type(exc).__name__ + ':' + str(exc))
        print(json.dumps({'kind': 'observation-start-failed', 'noRetry': True, 'evidence': str(output)}, ensure_ascii=False), flush=True)
        return 1
    record = Recorder(output)
    record('observation-started', message='观察已开始', candidateId=receipt['candidateId'],
           capturePolicy=POLICY, configSelectionRecorded=True)
    (output / 'acceptance-plan.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    await monitor(prepared, output, record)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-authorized', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--candidate', type=Path, default=CANDIDATE)
    args = parser.parse_args()
    entry, prepared, manifest, receipt = prepare(args.candidate)
    if not args.start_authorized:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    if args.output is None:
        parser.error('Authorized start requires --output inside build/')
    return asyncio.run(start(entry, prepared, manifest, receipt, args.output.resolve()))


if __name__ == '__main__':
    raise SystemExit(main())
