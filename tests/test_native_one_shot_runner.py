"""Offline acceptance orchestration; no Main, Host or game is launched."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools import start_native_delivery_candidate as runner


class Socket:
    def __init__(self, events=()):
        self.events = list(events)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        if self.events:
            return json.dumps(self.events.pop(0))
        raise asyncio.TimeoutError


class Child:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class OneShotTests(unittest.TestCase):
    def setUp(self):
        build = runner.ROOT / 'build'
        build.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=build)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_stdout_discovers_redirected_failure_and_stops(self):
        native = self.root / 'build/native-observation/session-test'
        native.mkdir(parents=True)
        output = self.root / 'output'
        output.mkdir()
        (output / 'stdout.log').write_text('STARTUP:NATIVE_IDENTITY ' + json.dumps(
            {'sessionDirectory': str(native)}) + '\n', encoding='utf-8')
        (output / 'main.log').write_text('', encoding='utf-8')
        failure = {'kind': 'capture-ended', 'finalizationReason': 'INCOMPLETE',
                   'reason': 'WINDOW_SCROLL_FAILED_OR_TARGET_CHANGED'}
        (native / 'main-diagnostic.log').write_text('WAREHOUSE:NATIVE_AUTO ' +
            json.dumps(failure) + '\n', encoding='utf-8')
        with patch.object(runner, 'ROOT', self.root):
            tail = runner.NativeRunLogTail(output)
            try:
                rows = tail.poll()
                self.assertTrue(any(json.dumps(failure) in line for _, line in rows))
                self.assertEqual(tail.poll(), [])
            finally:
                tail.close()

    def test_false_stop_receipt_is_not_exit_confirmation(self):
        socket = Socket([{'type': 'native_stop_receipt', 'processExitConfirmed': False},
                         {'type': 'native_stop_receipt', 'processExitConfirmed': True}])
        records = []
        asyncio.run(runner.stop_once(socket, lambda kind, **data: records.append(data), 'FAIL'))
        self.assertTrue(records[-1]['processExitConfirmed'])
        self.assertEqual(socket.sent, [{'type': 'stop_live_vision'}])

    def test_complete_stops_without_waiting_for_next_match(self):
        (self.root / 'main.log').write_text('WAREHOUSE:NATIVE_AUTO ' + json.dumps(
            {'kind': 'capture-ended', 'finalizationReason': 'COMPLETE', 'reason': 'BOTTOM'}) + '\n')
        socket = Socket([{'visionHealth': {'stage': 'native-error', 'reason': 'TOO_LATE'}},
                         {'type': 'native_stop_receipt', 'processExitConfirmed': True}])
        records = []
        with patch('websockets.connect', return_value=socket):
            asyncio.run(runner.monitor({'port': 1}, self.root,
                lambda kind, **data: records.append({'kind': kind, **data})))
        ended = next(row for row in records if row['kind'] == 'observation-ended')
        self.assertEqual(ended['reason'], 'COLLECTION_COMPLETE')
        self.assertEqual(socket.sent, [{'type': 'stop_live_vision'}])

    def test_redirected_partial_duplicate_events_stop_once(self):
        line = 'WAREHOUSE:NATIVE_AUTO ' + json.dumps({'kind': 'capture-ended',
            'finalizationReason': 'INCOMPLETE', 'reason': 'TARGET_UNKNOWN'}) + '\n'
        (self.root / 'stdout.log').write_text(line * 2)
        socket = Socket([{'type': 'native_stop_receipt', 'processExitConfirmed': True}])
        rows = []
        with patch('websockets.connect', return_value=socket):
            result = asyncio.run(runner.monitor({'port': 1}, self.root,
                lambda kind, **data: rows.append({'kind': kind, **data})))
        reason, exit_confirmed = result
        self.assertEqual(reason, 'COLLECTION_PARTIAL:TARGET_UNKNOWN')
        self.assertTrue(exit_confirmed)
        self.assertEqual(sum(r['kind'] == 'capture-ended' for r in rows), 1)
        self.assertTrue(rows[-1]['processExitConfirmed'])
        self.assertEqual(socket.sent, [{'type': 'stop_live_vision'}])

    def test_stop_timeout_or_transport_failure_never_confirms(self):
        for events in ([], [{'type': 'native_stop_receipt', 'processExitConfirmed': False}]):
            with self.subTest(events=events):
                socket = Socket(events)
                rows = []
                result = asyncio.run(runner.stop_once(socket,
                    lambda kind, **data: rows.append(data), 'FAIL', timeout=.01))
                self.assertFalse(result)
                self.assertFalse(rows[-1]['processExitConfirmed'])
                self.assertEqual(socket.sent, [{'type': 'stop_live_vision'}])

    def test_stop_send_is_bounded(self):
        class Blocked(Socket):
            async def send(self, text):
                await asyncio.Event().wait()
        self.assertFalse(asyncio.run(runner.stop_once(Blocked(), lambda *a, **k: None,
                                                     'FAIL', timeout=.01)))

    def test_cancelled_monitor_still_stops_and_closes_tail(self):
        class Cancelled(Socket):
            async def recv(self):
                if not self.sent:
                    raise asyncio.CancelledError
                return await super().recv()
        socket = Cancelled([{'type': 'native_stop_receipt', 'processExitConfirmed': True}])
        tail = runner.NativeRunLogTail(self.root)
        rows = []
        with patch('websockets.connect', return_value=socket), patch.object(runner, 'NativeRunLogTail', return_value=tail):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(runner.monitor({'port': 1}, self.root,
                    lambda kind, **data: rows.append({'kind': kind, **data})))
        self.assertTrue(rows[-1]['processExitConfirmed'])
        self.assertEqual(tail.tails, {})
        self.assertEqual(socket.sent, [{'type': 'stop_live_vision'}])

    def test_settlement_past_seventy_seconds_stops_on_scene_exit(self):
        clock = SimpleNamespace(now=0)
        class Timed(Socket):
            async def recv(self):
                if self.sent:
                    return await super().recv()
                clock.now += 40
                return json.dumps({'scene': 'SETTLEMENT' if clock.now <= 120 else 'AUCTION_LOBBY',
                                   'matchId': 'test-match'})
        socket = Timed([{'type': 'native_stop_receipt', 'processExitConfirmed': True}])
        rows = []
        with patch('websockets.connect', return_value=socket), patch.object(runner, 'time',
                SimpleNamespace(monotonic=lambda: clock.now)):
            asyncio.run(runner.monitor({'port': 1}, self.root,
                lambda kind, **data: rows.append({'kind': kind, **data})))
        self.assertEqual(next(r['reason'] for r in rows if r['kind'] == 'observation-ended'),
                         'FIRST_SETTLEMENT_LEFT')
        self.assertEqual(clock.now, 160)
        self.assertTrue(rows[-1]['processExitConfirmed'])

    def test_scene_exit_match_change_and_health_failure_stop(self):
        first = {'scene': 'SETTLEMENT', 'matchId': 'test-one'}
        for event, reason in (({'scene': 'AUCTION_LOBBY'}, 'FIRST_SETTLEMENT_LEFT'),
                ({'scene': 'IN_AUCTION', 'matchId': 'test-two'}, 'ONE_SHOT_MATCH_CHANGED'),
                ({'visionHealth': {'stage': 'native-paused', 'reason': 'TARGET_UNKNOWN'}}, 'TARGET_UNKNOWN')):
            with self.subTest(reason=reason):
                socket = Socket([first, event, {'type': 'native_stop_receipt', 'processExitConfirmed': True}])
                rows = []
                with patch('websockets.connect', return_value=socket):
                    stopped, exit_confirmed = asyncio.run(runner.monitor({'port': 1}, self.root,
                        lambda kind, **data: rows.append({'kind': kind, **data})))
                self.assertEqual(stopped, reason)
                self.assertTrue(exit_confirmed)
                self.assertEqual(next(r['reason'] for r in rows if r['kind'] == 'observation-ended'), reason)
                self.assertEqual(socket.sent, [{'type': 'stop_live_vision'}])

    def test_owned_shutdown_waits_for_exit_unknown_never_commands_bus(self):
        child = Child()
        class Shutdown(Socket):
            async def send(self, text):
                await super().send(text)
                child.code = 0
        socket = Shutdown()
        with patch('websockets.connect', return_value=socket) as connect:
            self.assertTrue(asyncio.run(runner.close_owned_assistant(child, {'port': 1}, lambda *a, **k: None)))
            self.assertEqual(socket.sent[0]['type'], 'eval_overlay_js')
            self.assertEqual(socket.sent[0]['script'], 'window.pywebview.api.exit_app();')
            self.assertTrue(asyncio.run(runner.close_owned_assistant(child, {'port': 1}, lambda *a, **k: None)))
            self.assertFalse(asyncio.run(runner.close_owned_assistant(None, {'port': 1}, lambda *a, **k: None)))
            self.assertEqual(connect.call_count, 1)

    def test_main_bridge_rejects_exit_app_without_adding_a_main_whitelist_action(self):
        from main_window import MainWindowBridge
        with self.assertRaisesRegex(ValueError, "Main bridge action is not allowed: 'exit_app'"):
            MainWindowBridge(None).dispatch({'action': 'exit_app'})

    def test_shutdown_request_is_not_process_exit(self):
        socket = Socket()
        with patch('websockets.connect', return_value=socket):
            self.assertFalse(asyncio.run(runner.close_owned_assistant(Child(), {'port': 1},
                lambda *a, **k: None, timeout=.01)))
        self.assertEqual(socket.sent[0]['type'], 'eval_overlay_js')

    def test_overlay_unavailable_does_not_claim_exit_or_kill_process(self):
        child = Child()
        rows = []
        with patch('websockets.connect', side_effect=OSError('Overlay unavailable')):
            self.assertFalse(asyncio.run(runner.close_owned_assistant(child, {'port': 1},
                lambda kind, **data: rows.append({'kind': kind, **data}), timeout=.01)))
        self.assertIsNone(child.poll())
        self.assertFalse(next(row for row in rows if row['kind'] == 'assistant-exit')['processExitConfirmed'])
        self.assertEqual(next(row for row in rows if row['kind'] == 'assistant-shutdown-request-failed')['reason'],
                         'OSError')

    def make_config(self):
        (self.root / 'app').mkdir()
        candidate = self.root / 'build/candidate.json'
        candidate.parent.mkdir()
        config = self.root / 'app/config.json'
        original = b'{"app":{"captureFreshnessPolicy":"wgc-origin-strict-v1","nativeAutoWarehouseCapture":false}}\n'
        config.write_bytes(original)
        manifest = {'scopeFiles': {'app/config.json': hashlib.sha256(original).hexdigest()}}
        return candidate, config, original, manifest

    def test_config_restore_preserves_original_and_refuses_concurrent_edits(self):
        candidate, config, original, manifest = self.make_config()
        with patch.object(runner, 'ROOT', self.root):
            old, selected = runner.select_options(manifest, candidate)
            self.assertTrue(runner.restore_options(old, selected, candidate, process_exit_confirmed=True))
            self.assertEqual(config.read_bytes(), original)
            old, selected = runner.select_options(manifest, candidate)
            config.write_bytes(b'{"app":{"userEdit":true}}')
            self.assertFalse(runner.restore_options(old, selected, candidate, process_exit_confirmed=True))
            self.assertEqual(config.read_bytes(), b'{"app":{"userEdit":true}}')

    def test_config_restore_accepts_main_reserialization_and_is_idempotent(self):
        candidate, config, original, manifest = self.make_config()
        with patch.object(runner, 'ROOT', self.root):
            old, selected = runner.select_options(manifest, candidate)
            # Main serializes the selected JSON object with different whitespace/key order.
            current = json.loads(selected)
            config.write_bytes(json.dumps(current, ensure_ascii=False, sort_keys=True,
                                          separators=(',', ':')).encode('utf-8'))
            self.assertTrue(runner.restore_options(old, selected, candidate, process_exit_confirmed=True))
            self.assertEqual(config.read_bytes(), original)
            self.assertTrue(runner.restore_options(old, selected, candidate, process_exit_confirmed=True))
            self.assertEqual(config.read_bytes(), original)

    def test_config_restore_requires_confirmed_process_exit(self):
        candidate, config, original, manifest = self.make_config()
        with patch.object(runner, 'ROOT', self.root):
            old, selected = runner.select_options(manifest, candidate)
            selected_bytes = config.read_bytes()
            self.assertFalse(runner.restore_options(old, selected, candidate, process_exit_confirmed=False))
            self.assertEqual(config.read_bytes(), selected_bytes)
            self.assertTrue(runner.restore_options(old, selected, candidate, process_exit_confirmed=True))
            self.assertEqual(config.read_bytes(), original)

    def test_config_restore_refuses_edit_during_restore(self):
        candidate, config, original, manifest = self.make_config()
        external = b'{"app":{"captureFreshnessPolicy":"user-change"}}'
        with patch.object(runner, 'ROOT', self.root):
            old, selected = runner.select_options(manifest, candidate)
            actual_read_bytes = Path.read_bytes
            reads = 0
            def read_with_concurrent_edit(path):
                nonlocal reads
                if path == config:
                    reads += 1
                    if reads == 2:
                        config.write_bytes(external)
                return actual_read_bytes(path)
            with patch.object(Path, 'read_bytes', read_with_concurrent_edit):
                self.assertFalse(runner.restore_options(old, selected, candidate,
                                                        process_exit_confirmed=True))
            self.assertEqual(config.read_bytes(), external)

    def test_unconfirmed_owned_process_keeps_selected_configuration(self):
        candidate, config, original, manifest = self.make_config()
        child = Child()
        async def launch(prepared, output, *, environment, on_launch):
            output.mkdir()
            on_launch(child)
            return True
        async def unconfirmed(*args, **kwargs):
            return False
        receipt = {'candidateManifest': str(candidate), 'existingAssistantBusOccupied': False, 'candidateId': 'test'}
        rows = []
        with patch.object(runner, 'ROOT', self.root), patch.object(runner, 'Recorder',
                return_value=lambda kind, **data: rows.append({'kind': kind, **data})), \
                patch.object(runner, 'monitor', return_value=('USER_STOP', False)), \
                patch.object(runner, 'close_owned_assistant', new=unconfirmed), \
                patch.object(runner, 'port_released', return_value=False):
            result = asyncio.run(runner.start(SimpleNamespace(start=launch), {'port': 1}, manifest,
                                               receipt, self.root / 'build/run'))
        self.assertEqual(result, 1)
        self.assertIsNone(child.poll())
        self.assertNotEqual(config.read_bytes(), original)
        self.assertFalse(rows[-1]['assistantExitConfirmed'])
        self.assertFalse(rows[-1]['configRestored'])
        self.assertFalse(rows[-1]['portReleased'])

    def test_port_still_occupied_prevents_success_after_confirmed_exit(self):
        candidate, config, original, manifest = self.make_config()
        child = Child(0)
        async def launch(prepared, output, *, environment, on_launch):
            output.mkdir()
            on_launch(child)
            return True
        async def exited(*args, **kwargs):
            return True
        receipt = {'candidateManifest': str(candidate), 'existingAssistantBusOccupied': False, 'candidateId': 'test'}
        rows = []
        with patch.object(runner, 'ROOT', self.root), patch.object(runner, 'Recorder',
                return_value=lambda kind, **data: rows.append({'kind': kind, **data})), \
                patch.object(runner, 'monitor', return_value=('COLLECTION_COMPLETE', True)), \
                patch.object(runner, 'close_owned_assistant', new=exited), \
                patch.object(runner, 'port_released', return_value=False):
            result = asyncio.run(runner.start(SimpleNamespace(start=launch), {'port': 1}, manifest,
                                               receipt, self.root / 'build/run'))
        # 892525a: a confirmed complete stop leaves main open for review.
        # An occupied port is recorded and does not close or restore it.
        self.assertEqual(result, 0)
        self.assertNotEqual(config.read_bytes(), original)
        self.assertTrue(rows[-1]['assistantLeftOpen'])
        self.assertFalse(rows[-1]['assistantExitConfirmed'])
        self.assertFalse(rows[-1]['configRestored'])
        self.assertFalse(rows[-1]['portReleased'])

    def test_start_cleanup_and_return_status_are_not_false_pass(self):
        candidate, config, original, manifest = self.make_config()
        child = Child(0)
        async def launch(prepared, output, *, environment, on_launch):
            output.mkdir()
            on_launch(child)
            return True
        receipt = {'candidateManifest': str(candidate), 'existingAssistantBusOccupied': False, 'candidateId': 'test'}
        rows = []
        with patch.object(runner, 'ROOT', self.root), patch.object(runner, 'Recorder',
                return_value=lambda kind, **data: rows.append({'kind': kind, **data})), \
                patch.object(runner, 'monitor', return_value=('USER_STOP', False)), patch.object(runner, 'port_released', return_value=True):
            result = asyncio.run(runner.start(SimpleNamespace(start=launch), {'port': 1}, manifest,
                                               receipt, self.root / 'build/run'))
        self.assertEqual(result, 1)
        self.assertEqual(config.read_bytes(), original)
        self.assertTrue(rows[-1]['assistantExitConfirmed'])
        self.assertTrue(rows[-1]['configRestored'])
        self.assertTrue(rows[-1]['portReleased'])

    def test_authorized_wrapper_orders_stop_exit_restore_and_port_check(self):
        candidate, config, original, manifest = self.make_config()
        child = Child()
        async def launch(prepared, output, *, environment, on_launch):
            self.assertEqual(environment['NTE_ALLOW_HUD_CAPTURE'], '1')
            output.mkdir()
            on_launch(child)
            (output / 'stdout.log').write_text('WAREHOUSE:NATIVE_AUTO ' + json.dumps(
                {'kind': 'capture-ended', 'finalizationReason': 'INCOMPLETE', 'reason': 'TARGET_UNKNOWN'}) + '\n')
            return True
        class Shutdown(Socket):
            async def send(self, text):
                await super().send(text)
                child.code = 0
        stop_socket = Socket([{'type': 'native_stop_receipt', 'processExitConfirmed': True}])
        shutdown_socket = Shutdown()
        receipt = {'candidateManifest': str(candidate), 'existingAssistantBusOccupied': False, 'candidateId': 'test'}
        def released(port):
            self.assertIsNone(child.poll())
            self.assertNotEqual(config.read_bytes(), original)
            return False
        with patch.object(runner, 'ROOT', self.root), patch('websockets.connect',
                side_effect=[stop_socket, shutdown_socket]), patch.object(runner, 'port_released', side_effect=released):
            self.assertEqual(asyncio.run(runner.start(SimpleNamespace(start=launch), {'port': 1}, manifest,
                receipt, self.root / 'build/run')), 1)
        self.assertEqual(stop_socket.sent, [{'type': 'stop_live_vision'}])
        self.assertEqual(shutdown_socket.sent, [])
        result = json.loads((self.root / 'build/run/acceptance-events.jsonl').read_text().splitlines()[-1])
        self.assertTrue(result['assistantLeftOpen'])
        self.assertFalse(result['assistantExitConfirmed'])
        self.assertFalse(result['configRestored'])
        self.assertFalse(result['portReleased'])

    def test_cancelled_start_restores_config_without_game_retry(self):
        candidate, config, original, manifest = self.make_config()
        async def launch(prepared, output, *, environment, on_launch):
            output.mkdir()
            on_launch(Child(0))
            raise asyncio.CancelledError
        receipt = {'candidateManifest': str(candidate), 'existingAssistantBusOccupied': False, 'candidateId': 'test'}
        with patch.object(runner, 'ROOT', self.root), patch.object(runner, 'port_released', return_value=True), \
                patch('websockets.connect') as connect:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(runner.start(SimpleNamespace(start=launch), {'port': 1}, manifest,
                                          receipt, self.root / 'build/run'))
            connect.assert_not_called()
        self.assertEqual(config.read_bytes(), original)
