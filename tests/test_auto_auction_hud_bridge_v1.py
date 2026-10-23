"""The floating ticket's stop is the same switch the main window uses.

Only the routing function is exercised: it must call the one start/stop pair,
push the state to the main window and broadcast the same app_status shape.
No window, WebView or game is created.
"""
import ast
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'core'), str(ROOT / 'app')]

FUNCTIONS = {'_dispatch_hud_auto_auction'}


def _isolated(holder=None, loop=None):
    tree = ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8-sig'))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    assert nodes, 'main.py must keep _dispatch_hud_auto_auction'
    broadcast = Mock(name='broadcast_ws')
    schedule = Mock(name='run_coroutine_threadsafe')
    namespace = {
        '__name__': 'isolated_hud_auto_auction',
        'asyncio': SimpleNamespace(run_coroutine_threadsafe=schedule),
        'json': json,
        'log_stage': lambda *args: None,
        '_MAIN_WINDOW_HOLDER': holder if holder is not None else [],
        'WS_EVENT_LOOP': loop,
        '_start_auto_auction': Mock(return_value={'ok': True, 'autoAuction': {'running': True}}),
        '_stop_auto_auction': Mock(return_value={'ok': True, 'autoAuction': {'running': False}}),
        '_auto_auction_public': Mock(return_value={'enabled': False, 'running': False,
                                                   'phase': 'stopped', 'reason': 'USER_STOP'}),
        'broadcast_ws': broadcast,
    }
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[
        ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROOT / 'app/main.py'), 'exec'), namespace)
    return namespace


class HudAutoAuctionRoutingTests(unittest.TestCase):
    def test_ticket_stop_uses_the_switch_stop_and_reports_the_reason(self):
        form = Mock()
        namespace = _isolated(holder=[form])
        result = namespace['_dispatch_hud_auto_auction']('auto_auction_stop')
        namespace['_stop_auto_auction'].assert_called_once_with('USER_STOP')
        namespace['_start_auto_auction'].assert_not_called()
        self.assertTrue(result['ok'])
        form.post_status.assert_called_once_with('auto_auction_stop')

    def test_ticket_start_uses_the_switch_start_without_a_payload(self):
        namespace = _isolated(holder=[Mock()])
        namespace['_dispatch_hud_auto_auction']('auto_auction_start')
        namespace['_start_auto_auction'].assert_called_once_with()
        namespace['_stop_auto_auction'].assert_not_called()

    def test_no_main_window_and_no_loop_still_returns_the_command_result(self):
        namespace = _isolated(holder=[], loop=None)
        result = namespace['_dispatch_hud_auto_auction']('auto_auction_stop')
        namespace['_stop_auto_auction'].assert_called_once_with('USER_STOP')
        namespace['broadcast_ws'].assert_not_called()
        self.assertEqual(result['autoAuction'], {'running': False})

    def test_running_loop_receives_the_same_app_status_shape(self):
        holder = [Mock()]
        loop = Mock()
        loop.is_running.return_value = True
        namespace = _isolated(holder=holder, loop=loop)
        captured = []
        namespace['json'] = SimpleNamespace(
            dumps=lambda obj, ensure_ascii=True: captured.append(obj) or '{}')
        namespace['_dispatch_hud_auto_auction']('auto_auction_stop')
        self.assertEqual(len(captured), 1)
        message = captured[0]
        self.assertEqual(message['type'], 'app_status')
        self.assertEqual(message['action'], 'auto_auction_stop')
        self.assertTrue(message['autoAuctionCommand']['ok'])
        self.assertEqual(message['autoAuction']['reason'], 'USER_STOP')
        namespace['broadcast_ws'].assert_called_once()
        self.assertEqual(namespace['asyncio'].run_coroutine_threadsafe.call_count, 1)


if __name__ == '__main__':
    unittest.main()
