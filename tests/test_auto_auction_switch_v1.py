"""The auto-auction switch: one persisted product setting, two separate stops.

Part A runs the real Main functions without Main's configuration/GUI bootstrap.
Part B checks the Main bridge contract that the buttons will call next.
"""
import ast
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'core'), str(ROOT / 'app')]
from main_window import MainWindowBridge  # noqa: E402

FUNCTIONS = {
    '_auto_auction_settings', '_auto_auction_enabled', '_auto_auction_approval_id',
    '_set_auto_auction_enabled', '_auto_auction_public', '_start_auto_auction',
    '_stop_auto_auction', '_observation_running',
}


def _isolated(directory, config):
    tick = iter(range(1000000))
    tree = ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8'))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    form = Mock()
    namespace = {
        '__name__': 'isolated_auto_auction',
        'os': os, 'json': json, 'copy': copy, 'BASE_DIR': str(directory),
        'CONFIG': config,
        'time': SimpleNamespace(strftime=lambda fmt: '20261022T12%06d' % next(tick)),
        'log_stage': lambda *args: None,
        '_MAIN_WINDOW_HOLDER': [form],
        '_LIVE_DOMAIN_LOOP': None,
        '_AUTO_AUCTION_APPROVAL_ID': None,
        '_AUTO_AUCTION_STOP_REASON': None,
        'NATIVE_OBSERVATION_BRIDGE': SimpleNamespace(running=True),
        'start_vision_worker': Mock(return_value=object()),
        '_stop_authorized_live_domain_loop': Mock(),
    }
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[
        ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROOT / 'app/main.py'), 'exec'), namespace)
    return namespace, form


def _config(**auto_auction):
    settings = {'enabled': False, 'mode': 'bid', 'minimumFunds': 120000,
                'instrumentTargets': {'goldAverage': 2, 'purpleCount': 1},
                'comment': 'keep me'}
    settings.update(auto_auction)
    return {'app': {'mode': 'live', 'version': '0.68-alpha'},
            'bid': {'perMatchFundCap': None}, 'autoAuction': settings}


class SwitchPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def _written(self):
        return json.loads((Path(self.directory.name) / 'config.json').read_text(encoding='utf-8'))

    def test_start_twice_keeps_the_match_count_and_the_ticket(self):
        namespace, _ = _isolated(self.directory.name, _config())
        first = namespace['_start_auto_auction']()
        ticket = first['autoAuction']['approvalId']
        namespace['_LIVE_DOMAIN_LOOP'] = {'phase': 'idle', 'matchesDone': 3}
        second = namespace['_start_auto_auction']()
        self.assertTrue(second['ok'])
        self.assertEqual(second['reason'], 'ALREADY_RUNNING')
        self.assertEqual(namespace['_LIVE_DOMAIN_LOOP']['matchesDone'], 3)
        self.assertEqual(second['autoAuction']['approvalId'], ticket)
        # Starting again after a terminal stop is a new run: clean count, new ticket.
        namespace['_LIVE_DOMAIN_LOOP'] = {'phase': 'stopped', 'matchesDone': 3}
        third = namespace['_start_auto_auction']()
        self.assertIsNone(third['reason'])
        self.assertIsNone(namespace['_LIVE_DOMAIN_LOOP'])
        self.assertNotEqual(namespace['_AUTO_AUCTION_APPROVAL_ID'], ticket)

    def test_start_and_stop_keep_instrument_targets_and_every_other_section(self):
        namespace, _ = _isolated(self.directory.name, _config())
        started = namespace['_start_auto_auction']()
        self.assertTrue(started['ok'])
        on_disk = self._written()
        self.assertIs(on_disk['autoAuction']['enabled'], True)
        self.assertEqual(on_disk['autoAuction']['instrumentTargets'],
                         {'goldAverage': 2, 'purpleCount': 1})
        self.assertEqual(on_disk['autoAuction']['comment'], 'keep me')
        self.assertEqual(on_disk['autoAuction']['minimumFunds'], 120000)
        self.assertEqual(on_disk['app'], {'mode': 'live', 'version': '0.68-alpha'})
        self.assertEqual(on_disk['bid'], {'perMatchFundCap': None})
        self.assertTrue(started['autoAuction']['approvalId'].startswith('auto-'))

        stopped = namespace['_stop_auto_auction']('USER_STOP')
        self.assertTrue(stopped['ok'])
        on_disk = self._written()
        self.assertIs(on_disk['autoAuction']['enabled'], False)
        self.assertEqual(on_disk['autoAuction']['instrumentTargets'],
                         {'goldAverage': 2, 'purpleCount': 1})
        self.assertEqual(stopped['autoAuction']['reason'], 'USER_STOP')
        self.assertFalse(stopped['autoAuction']['running'])

    def test_unknown_keys_survive_a_round_trip(self):
        namespace, _ = _isolated(self.directory.name, _config(instrumentTargets={'goldAverage': 0}))
        namespace['_start_auto_auction']()
        on_disk = self._written()
        self.assertEqual(on_disk['autoAuction']['instrumentTargets'],
                         {'goldAverage': 0, 'purpleCount': 1})
        self.assertEqual(on_disk['autoAuction']['comment'], 'keep me')

    def test_start_without_observation_leaves_the_switch_off(self):
        namespace, _ = _isolated(self.directory.name, _config())
        namespace['NATIVE_OBSERVATION_BRIDGE'] = SimpleNamespace(running=False)
        namespace['start_vision_worker'] = Mock(return_value=None)
        started = namespace['_start_auto_auction']()
        self.assertFalse(started['ok'])
        self.assertEqual(started['reason'], 'OBSERVATION_UNAVAILABLE')
        self.assertIs(self._written()['autoAuction']['enabled'], False)
        self.assertFalse(started['autoAuction']['enabled'])

    def test_status_reports_the_running_loop_and_the_stop_reason(self):
        namespace, form = _isolated(self.directory.name, _config())
        namespace['_LIVE_DOMAIN_LOOP'] = {'phase': 'idle', 'matchesDone': 2}
        status = namespace['_auto_auction_public']()
        self.assertEqual(status['phase'], 'idle')
        self.assertEqual(status['matchesDone'], 2)
        self.assertFalse(status['running'])
        namespace['_LIVE_DOMAIN_LOOP'] = None
        namespace['_AUTO_AUCTION_STOP_REASON'] = 'AUTO_AUCTION_MATCH_LIMIT'
        self.assertEqual(namespace['_auto_auction_public']()['reason'],
                         'AUTO_AUCTION_MATCH_LIMIT')
        form.announce_auto_auction_stop.assert_not_called()

    def test_switch_stop_restores_the_main_window_with_its_reason(self):
        namespace, form = _isolated(self.directory.name, _config(enabled=True))
        namespace['_stop_auto_auction']('USER_STOP')
        form.announce_auto_auction_stop.assert_called_once_with('USER_STOP')
        namespace['_stop_authorized_live_domain_loop'].assert_not_called()

    def test_switch_on_then_stop_terminalises_the_existing_loop(self):
        namespace, form = _isolated(self.directory.name, _config(enabled=True))
        namespace['_LIVE_DOMAIN_LOOP'] = {'phase': 'collecting', 'matchesDone': 1}
        namespace['_stop_auto_auction']('USER_STOP')
        namespace['_stop_authorized_live_domain_loop'].assert_called_once_with('USER_STOP')
        form.announce_auto_auction_stop.assert_called_once_with('USER_STOP')


class BridgeContractTests(unittest.TestCase):
    def bridge(self, enabled=False, **kwargs):
        status = {'enabled': enabled, 'running': False, 'phase': None,
                  'reason': None, 'matchesDone': 0}
        return MainWindowBridge(
            SimpleNamespace(visible=False), auto_auction_provider=lambda: status, **kwargs)

    def test_start_and_stop_actions_are_routed_to_the_product_switch(self):
        bridge = self.bridge(
            auto_auction_start_provider=lambda: {'ok': True, 'autoAuction': {'enabled': True}},
            auto_auction_stop_provider=lambda: {'ok': True, 'autoAuction': {'enabled': False}})
        started = bridge.dispatch({'action': 'auto_auction_start', 'requestId': 'one'})
        self.assertEqual(started['autoAuctionCommand'], {'ok': True, 'autoAuction': {'enabled': True}})
        self.assertIn('autoAuction', started)
        stopped = bridge.dispatch({'action': 'auto_auction_stop'})
        self.assertEqual(stopped['autoAuctionCommand'], {'ok': True, 'autoAuction': {'enabled': False}})

    def test_status_carries_the_switch_state(self):
        bridge = self.bridge(enabled=True)
        response = bridge.dispatch({'action': 'request_app_status'})
        self.assertEqual(response['autoAuction'],
                         {'enabled': True, 'running': False, 'phase': None,
                          'reason': None, 'matchesDone': 0})

    def test_missing_switch_is_reported_not_assumed(self):
        bridge = MainWindowBridge(SimpleNamespace(visible=False))
        self.assertIsNone(bridge.dispatch({'action': 'request_app_status'})['autoAuction'])
        refused = bridge.dispatch({'action': 'auto_auction_stop'})
        self.assertEqual(refused['autoAuctionCommand']['reason'], 'AUTO_AUCTION_UNAVAILABLE')

    def test_stopping_one_capture_does_not_stop_the_auction_switch(self):
        stop_switch = Mock(return_value={'ok': True})
        host = SimpleNamespace(stop=Mock(return_value={'ok': True, 'reason': 'STOP_REQUESTED'}),
                               presentation_payload=lambda: {'state': 'PARTIAL'})
        bridge = MainWindowBridge(SimpleNamespace(visible=False),
                                  auto_auction_stop_provider=stop_switch,
                                  warehouse_capture_host=host)
        response = bridge.dispatch({'action': 'stop_warehouse_capture'})
        self.assertEqual(response['warehouseCaptureCommand']['reason'], 'STOP_REQUESTED')
        self.assertEqual(response['warehouseCapture'], {'state': 'PARTIAL'})
        stop_switch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
