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
        'monitorLimitSeconds': 1200, 'oneMatchOnly': True,
        'settlementMonitorSeconds': 70, 'stopConfirmationSeconds': 10,
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
    os.replace(pending, path)
    return original, path.read_bytes()


def restore_options(original, selected, candidate=CANDIDATE):
    """Restore only our unchanged selection; never overwrite a concurrent edit."""
    path = ROOT / 'app/config.json'
    if path.read_bytes() != selected:
        return False
    pending = candidate.resolve().parent / 'restore-launch-options.json'
    pending.write_bytes(original)
    if path.read_bytes() != selected:
        pending.unlink()
        return False
    os.replace(pending, path)
    return True


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
        rows.extend(self._drain('stdout', self.output / 'stdout.log'))
        rows.extend(self._drain('redirected', self.session_log))
        return rows

    def close(self):
        for tail in self.tails.values():
            tail['file'].close()
        self.tails.clear()


def safe_record(record, kind, **details):
    try:
        record(kind, **details)
    except (OSError, RuntimeError):
        print(json.dumps({'kind': kind, **details}, ensure_ascii=False), flush=True)


async def stop_once(ws, record, reason, *, timeout=10):
    """One stop command, bounded send/receive; a request is never a receipt."""
    deadline = time.monotonic() + timeout
    try:
        await asyncio.wait_for(ws.send(json.dumps({'type': 'stop_live_vision'})), timeout)
        safe_record(record, 'stop-request', reason=reason)
        while time.monotonic() < deadline:
            event = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.monotonic()))
            if event.get('type') == 'native_stop_receipt':
                confirmed = event.get('processExitConfirmed') is True
                safe_record(record, 'stop-receipt', receipt=event, processExitConfirmed=confirmed)
                if confirmed:
                    return True
    except Exception as exc:
        safe_record(record, 'stop-receipt', processExitConfirmed=False,
                    reason='STOP_UNCONFIRMED:' + type(exc).__name__)
        return False
    safe_record(record, 'stop-receipt', processExitConfirmed=False, reason='Host exit not confirmed by deadline')
    return False


async def close_owned_assistant(child, prepared, record, *, timeout=10):
    """Use existing QA/UI shutdown, then poll the retained Popen handle. Never kill."""
    import websockets
    if child is None:
        safe_record(record, 'assistant-exit', processExitConfirmed=False, reason='OWNERSHIP_UNKNOWN')
        return False
    deadline = time.monotonic() + timeout
    if child.poll() is None:
        try:
            async with websockets.connect(f"ws://127.0.0.1:{prepared['port']}", open_timeout=2,
                                          close_timeout=1) as ws:
                # Existing Main WebView action invokes ShutdownCoordinator (no game input).
                await asyncio.wait_for(ws.send(json.dumps({'type': 'eval_main_js',
                    'script': 'window.chrome.webview.postMessage(JSON.stringify({action:"exit_app"}));'})), 2)
        except Exception as exc:
            safe_record(record, 'assistant-shutdown-request-failed', reason=type(exc).__name__)
    while child.poll() is None and time.monotonic() < deadline:
        await asyncio.sleep(.05)
    confirmed = child.poll() is not None
    safe_record(record, 'assistant-exit', processExitConfirmed=confirmed)
    return confirmed


def port_released(port):
    with socket.socket() as probe:
        probe.settimeout(.2)
        return probe.connect_ex(('127.0.0.1', port)) != 0


async def monitor(prepared, output, record):
    import websockets
    log_tailer = NativeRunLogTail(output)
    first_match = None
    settlement_deadline = None
    last_snapshot = None
    reason = 'MONITOR_DEADLINE'
    exit_confirmed = False
    deadline = time.monotonic() + 1200  # Only this acceptance session, never the product observer.
    try:
        async with websockets.connect(f"ws://127.0.0.1:{prepared['port']}", max_size=8 * 1024 * 1024,
                                      open_timeout=2, close_timeout=1) as ws:
            try:
                while time.monotonic() < deadline:
                    if settlement_deadline is not None and time.monotonic() >= settlement_deadline:
                        reason = 'FIRST_SETTLEMENT_OBSERVATION_70S_END'; break
                    for source_log, line in log_tailer.poll():
                        if 'WAREHOUSE:NATIVE_AUTO' not in line:
                            continue
                        try:
                            diagnostic = json.loads(line[line.index('{'):])
                        except (ValueError, TypeError):
                            continue
                        kind = diagnostic.get('kind', 'collection-log')
                        safe_record(record, kind, sourceLog=source_log, diagnostic=diagnostic)
                        if kind == 'capture-ended':
                            reason = ('COLLECTION_COMPLETE' if diagnostic.get('finalizationReason') == 'COMPLETE'
                                      else 'COLLECTION_PARTIAL:' + str(diagnostic.get('reason')))
                            break
                    if reason.startswith('COLLECTION_'):
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
                        'sourceMatchGeneration', 'effectiveCaptureFreshnessPolicy', 'frameSequence')}
                    snapshot['visionHealth'] = health
                    if snapshot != last_snapshot:
                        safe_record(record, 'observation-state', snapshot=snapshot)
                        last_snapshot = snapshot
                    effective = view.get('effectiveCaptureFreshnessPolicy') or health.get('captureFreshnessPolicy')
                    if effective is not None and effective != POLICY:
                        reason = 'CAPTURE_POLICY_MISMATCH'; break
                    if health.get('stage') in {'native-error', 'native-paused', 'native-stopped'}:
                        reason = str(health.get('reason') or health['stage']); break
                    if scene in {'IN_AUCTION', 'SETTLEMENT'} and match and first_match is None:
                        first_match = match
                    elif first_match and match and first_match != match:
                        reason = 'ONE_SHOT_MATCH_CHANGED'; break
                    if scene == 'SETTLEMENT' and settlement_deadline is None:
                        settlement_deadline = time.monotonic() + 70
                    elif settlement_deadline is not None and scene and scene != 'SETTLEMENT':
                        reason = 'FIRST_SETTLEMENT_LEFT'; break
            except asyncio.CancelledError:
                reason = 'MONITOR_CANCELLED'
                raise
            except Exception as exc:
                reason = 'MONITOR_EXCEPTION:' + type(exc).__name__
            finally:
                safe_record(record, 'observation-ended', reason=reason, oneMatchOnly=True)
                exit_confirmed = await stop_once(ws, record, reason)
    finally:
        log_tailer.close()
    return reason == 'COLLECTION_COMPLETE' and exit_confirmed


async def start(entry, prepared, manifest, receipt, output):
    if output.exists() or not output.resolve().is_relative_to((ROOT / 'build').resolve()):
        raise ValueError('Use a fresh output directory inside build/')
    if receipt['existingAssistantBusOccupied']:
        raise RuntimeError('Assistant bus occupied; refusing to command or replace an existing assistant')
    candidate = Path(receipt['candidateManifest'])
    original, selected = select_options(manifest, candidate)
    prepared = {**prepared, 'captureFreshnessPolicy': POLICY, 'autoWarehouseCapture': True}
    owned = []
    record = lambda kind, **data: print(json.dumps({'kind': kind, **data}), flush=True)
    passed = False
    try:
        started = await entry.start(prepared, output,
            environment={'NTE_DISABLE_ICON': '1', 'NTE_ALLOW_HUD_CAPTURE': '1'},
            on_launch=owned.append)
        record = Recorder(output)
        if started:
            safe_record(record, 'observation-started', oneMatchOnly=True, candidateId=receipt['candidateId'])
            (output / 'acceptance-plan.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
            passed = await monitor(prepared, output, record)
        elif owned and owned[0].poll() is None:
            import websockets
            async with websockets.connect(f"ws://127.0.0.1:{prepared['port']}", open_timeout=2, close_timeout=1) as ws:
                await stop_once(ws, record, 'START_FAILED')
    finally:
        # Cancellation and startup/transport errors follow the same owned cleanup.
        assistant_confirmed = False
        restored = False
        released = False
        try:
            assistant_confirmed = await close_owned_assistant(owned[0] if owned else None, prepared, record)
        finally:
            try:
                if not owned or assistant_confirmed:
                    restored = restore_options(original, selected, candidate)
                released = port_released(prepared['port'])
            except OSError as exc:
                safe_record(record, 'cleanup-error', reason=type(exc).__name__)
        safe_record(record, 'cleanup-result', assistantExitConfirmed=assistant_confirmed,
                    configRestored=restored, portReleased=released, noRetry=True)
    return 0 if passed and assistant_confirmed and restored and released else 1


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
