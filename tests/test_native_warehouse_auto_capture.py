"""Session-control invariants, with an injected source and compositor facts; no OS/game IO."""
import copy
import ast
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core')]
from native_warehouse_auto_capture import NativeWarehouseAutoCapture
from native_warehouse_intake import WarehouseCaptureRouter


class Source:
    def __init__(self):
        self.intake = self
        self._scope_lock = threading.RLock()
        self.actions, self.pages = [], []
        self.scope = {'recordStableKey': 'r', 'scene': 'SETTLEMENT', 'targetInstance': {'targetHwnd': 12}}
        self.state, self.reason, self.intake_state = 'IDLE', None, 'IDLE'
        self.deadline, self.proof = 105.0, None
    def source_contract(self):
        return {'scope': copy.deepcopy(self.scope), 'state': self.intake_state}
    def prepare_manual(self):
        return {'ok': self.intake_state != 'ALIGNING', 'recordStableKey': 'r'}
    def start_manual(self, key, *, allow_window_scroll=False):
        self.actions.append(('OPEN', allow_window_scroll))
        self.state, self.reason, self.intake_state = 'OPEN_PENDING', None, 'MANUAL_CAPTURING'
        return {'ok': True}
    def on_event(self, event):
        self.state, self.reason = event['state'], event['reason']
        if event.get('page'):
            self.pages.append(event['page'])
        self.proof = event.get('proof')
    def source_session_snapshot(self):
        return {'state': self.state, 'reason': self.reason, 'deadline': self.deadline,
                'limits': {'windowScrollSupported': True}, 'duplicateProof': self.proof,
                'savedSource': {'pixelSha256': 'hash'}}
    def pages_copy(self):
        return copy.deepcopy(self.pages)
    def capture_manual_page(self):
        self.actions.append(('REQUEST_PAGE', len(self.pages)))
        self.state = 'REQUEST_PENDING'
        return {'ok': True}
    def request_scroll_down(self):
        self.actions.append(('SCROLL_DOWN', len(self.pages)))
        self.state = 'SCROLL_PENDING'
        return {'ok': True}
    def close_source(self, reason):
        self.actions.append(('CLOSE', reason))
        self.state = 'CLOSED'
    def finish_manual_capture(self, *, termination_reason):
        self.actions.append(('PROCESS', termination_reason))
        self.intake_state = 'ALIGNING'
        return {'ok': True}
    def cancel_manual_capture(self):
        self.actions.append(('CANCEL',))
        return {'ok': True}


class NativeAutoTests(unittest.TestCase):
    def start(self):
        self.now, self.source = [100.0], Source()
        self.auto = NativeWarehouseAutoCapture(self.source, clock=lambda: self.now[0], timers=False)
        self.assertTrue(self.auto.confirm(self.auto.prepare()['armingToken'])['ok'])
        self.auto.on_event({'state': 'OPEN', 'reason': 'SOURCE_READY'})
        # Inject pixels/observer facts, not the session-control decisions under test.
        image = (np.arange(1200).reshape(20, 20, 3) % 255).astype(np.uint8)
        self.read = patch.object(self.auto, '_read_page', side_effect=lambda page: (image, {'scrollState': page['scrollState']}))
        self.read.start(); self.addCleanup(self.read.stop)
    def page(self, state):
        self.auto.on_event({'state': 'OPEN', 'reason': 'PAGE_ACCEPTED', 'page': {'scrollState': state}})
    def stable_duplicate(self):
        self.now[0] += .3
        self.auto.poll()
        self.auto.on_event({'state': 'OPEN', 'reason': 'DUPLICATE_PAGE', 'proof': {'pixelSha256': 'hash'}})

    def test_save_and_stability_precede_each_wheel_and_bottom_only_finishes(self):
        self.start(); self.page('TOP')
        self.assertFalse(any(x[0] == 'SCROLL_DOWN' for x in self.source.actions))
        self.stable_duplicate()
        self.assertEqual(self.source.actions[-1], ('SCROLL_DOWN', 1))
        self.auto.on_event({'state': 'OPEN', 'reason': 'WINDOW_WHEEL_MESSAGE_SENT'})
        self.auto._advance()  # an ordinary status/UI refresh while the settle timer is pending
        self.assertTrue(self.auto._running)
        self.now[0] += .4; self.auto.poll()
        with patch('native_warehouse_auto_capture.align_warehouse_segments', return_value={
                'status': 'VERIFIED', 'direction': 'DOWN', 'verticalOffsetPx': -56}):
            self.page('BOTTOM')
        self.assertFalse(any(x[0] == 'PROCESS' for x in self.source.actions))
        self.stable_duplicate()
        self.assertEqual(self.source.actions[-1], ('PROCESS', 'COMPLETE'))
        self.assertEqual(sum(x[0] == 'SCROLL_DOWN' for x in self.source.actions), 1)
        self.assertFalse(self.auto._running)

    def test_ignored_wheel_stop_and_deadline_do_not_retry_or_extend(self):
        for failure in ('ignored-wheel', 'deadline', 'user-stop'):
            with self.subTest(failure=failure):
                self.start(); self.page('TOP'); self.stable_duplicate()
                self.auto.on_event({'state': 'OPEN', 'reason': 'WINDOW_WHEEL_MESSAGE_SENT'})
                generation = self.auto._generation
                if failure == 'deadline':
                    self.now[0] = 105.0; self.auto.poll()
                elif failure == 'user-stop':
                    self.auto.stop()
                else:
                    self.now[0] += .4; self.auto.poll()
                    self.auto.on_event({'state': 'OPEN', 'reason': 'DUPLICATE_PAGE', 'proof': {'pixelSha256': 'hash'}})
                actions = copy.deepcopy(self.source.actions)
                self.now[0] += 90; self.auto.poll(generation)
                self.assertEqual(self.source.actions, actions)
                self.assertEqual(self.source.actions[-1], ('PROCESS', 'INCOMPLETE'))
                self.assertEqual(sum(x[0] == 'SCROLL_DOWN' for x in actions), 1)

    def test_native_route_never_calls_legacy_and_changed_scope_rejects_confirmation(self):
        source = Source(); auto = NativeWarehouseAutoCapture(source, clock=lambda: 100, timers=False)
        class Legacy:
            def __getattr__(self, name):
                raise AssertionError('legacy access: ' + name)
        router = WarehouseCaptureRouter(Legacy(), auto, lambda: True)
        token = router.prepare()['armingToken']
        source.scope['targetInstance'] = {'targetHwnd': 99}
        self.assertFalse(router.confirm(token)['ok'])
        self.assertEqual(source.actions, [])
        router.stop()
        self.assertEqual(source.actions, [('CANCEL',)])

    def test_frozen_source_authority_does_not_refresh_business_frame_health(self):
        from test_native_background_observation import _isolated_main, _confirmed_start, _frame
        ns, clock, _ = _isolated_main('background-readonly')
        _confirmed_start(ns)
        ns['_native_observation_event'](_frame(ns))
        ns['LATEST_PAYLOAD']['scene'] = 'SETTLEMENT'
        clock[0] += 40_000_000_000
        before = copy.deepcopy(ns['LATEST_PAYLOAD'])
        tree = ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8'))
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == '_native_warehouse_source_scope')
        deferred = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        module = ast.fix_missing_locations(ast.Module(body=[deferred, fn], type_ignores=[]))
        exec(compile(module, str(ROOT / 'app/main.py'), 'exec'), ns)
        from types import SimpleNamespace
        ns['_NATIVE_WAREHOUSE_SOURCE_COORDINATOR'] = SimpleNamespace(lease_scope_is_current=lambda scope: True)
        self.assertEqual(ns['_native_warehouse_intake_scope']()['scene'], 'UNKNOWN')
        self.assertEqual(ns['_native_warehouse_source_scope']()['scene'], 'SETTLEMENT')
        self.assertEqual(ns['LATEST_PAYLOAD'], before)
        ns['_NATIVE_WAREHOUSE_SOURCE_COORDINATOR'] = SimpleNamespace(lease_scope_is_current=lambda scope: False)
        self.assertEqual(ns['_native_warehouse_source_scope']()['scene'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
