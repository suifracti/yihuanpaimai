"""A failed supervised game cannot silently purchase another trial."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from tests import test_m4_continuous_loop as m4
from domain_action_session import fresh_live_domain_state, advance_live_domain_loop


class M4VerificationBoundaryTests(unittest.TestCase):
    def test_explicit_stop_closes_collection_then_stops_the_auction_loop(self):
        from types import SimpleNamespace
        from native_warehouse_intake import WarehouseCaptureRouter
        calls = []
        native = SimpleNamespace(stop=lambda: calls.append('collection-closed') or {'ok':True})
        router = WarehouseCaptureRouter(None, native, lambda: True,
            on_native_stop=lambda: calls.append('auction-stopped'))
        self.assertTrue(router.stop()['ok'])
        self.assertEqual(calls, ['collection-closed','auction-stopped'])

    def view(self, scene, **kwargs):
        view = m4.ContinuousLoopTests().view(scene, **kwargs)
        view.update(mode='observe', verificationModes=['observe'])
        return view

    def test_observed_game_returns_without_archive_count_and_never_reenters(self):
        state, sends = fresh_live_domain_state(), []
        send = lambda owner, message: sends.append(message) or True
        advance_live_domain_loop(state, self.view('AUCTION'), send)
        self.assertEqual(state['verificationMatches'], ['match-1'])
        self.assertEqual(state['matchesDone'], 0)
        advance_live_domain_loop(state, self.view('LOBBY'), send)
        self.assertEqual(state['phase'], 'stopped')
        self.assertEqual(sends, [])

    def test_unknown_return_ends_the_trial_before_a_new_entry(self):
        state, sends = fresh_live_domain_state(), []
        advance_live_domain_loop(state, self.view('AUCTION'), lambda *a: True)
        view = self.view(None, sessionReceipt={'kind':'ReturnLobby','status':'UNKNOWN'})
        advance_live_domain_loop(state, view, lambda *a: sends.append(a) or True)
        self.assertEqual(state['phase'], 'stopped')
        self.assertEqual(sends, [])


if __name__ == '__main__':
    unittest.main()
