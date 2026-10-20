"""Match-12 real facts -> actual Node Solver -> Main view -> durable bid/send.

No game or GUI. Saved facts are public/sanitized; the positive frame admission,
target, approval, clock and send adapter are explicit synthetic transport.
"""
import copy
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from live_shadow import compute_live_probability_profile
from session_costs import costs_from_facts
from venue_box_catalog import load_catalog, solver_context_translation
from bid_intent import build_bid_intent
from domain_action_session import fresh_live_domain_state, advance_live_domain_loop
from test_native_background_observation import ROOT, _isolated_main


class SavedAuctionBidReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / 'tests/fixtures/match12_solver_input.json').read_text(encoding='utf-8'))
        facts = cls.fixture['facts']
        mapped = solver_context_translation(load_catalog(None), venue_id=facts['venueId'], box_id=facts['boxId'])
        cls.context = {**facts, 'matchId': facts['id'], 'round': facts['roundNo'],
                       'scene': 'IN_AUCTION', 'venue': mapped['venue'], 'box': mapped['box'],
                       'costs': costs_from_facts(facts), 'targetProfit': 0}
        # Zero invented history; the Solver keeps its own catalog/structural model.
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory) / 'history.json'
            history.write_text(json.dumps({'version': 'v0.6', 'schemaVersion': 6, 'records': []}), encoding='utf-8')
            _, cls.meta = compute_live_probability_profile(cls.context, str(history), persist_runtime=False)

    def view(self, directory):
        ns, _, _ = _isolated_main()
        ns['time'].time = lambda: 1000
        ns['math'] = math
        ns['_NATIVE_DOMAIN_ACTION_BOOT_ID'] = 'offline-replay'
        ns['_game_is_foreground'] = lambda _: True
        facts = self.fixture['facts']
        data = dict(self.context, sourceMatchGeneration=1, factsRevision=100,
                    observationSessionId='offline-match12', observationStatus='FRAME',
                    timer=30, domainObservation={'readbackNs': ns['time'].monotonic_ns()}, # synthetic transport timer
                    target={'targetHwnd': 10, 'targetPid': 20, 'identity': {'ProcessInstanceToken': 30}},
                    predictionSnapshot=self.meta.get('predictionSnapshot'),
                    frozenPrediction=self.meta.get('frozenPrediction'))
        with patch.dict(os.environ, {'NTE_DOMAIN_LIVE_DIR': directory}):
            return ns['_live_loop_view'](data, 'AUCTION', self.fixture['funds'])

    def test_real_solver_keeps_round_and_explicit_zero_profit_policy(self):
        self.assertIsNone(self.meta.get('error'), self.meta)
        snap = self.meta['predictionSnapshot']
        self.assertEqual(snap['input']['normalizedFacts'].get('round'), 1)
        self.assertEqual(snap['input']['normalizedFacts']['targetProfit'], 0)

    def test_real_partial_probability_keeps_all_state_floor_and_dispatches_once(self):
        snap = self.meta['predictionSnapshot']
        self.assertEqual(snap['mode']['informationMode'], 'partial_shadow')
        self.assertIsNone(snap['forecast']['quantiles'])
        with tempfile.TemporaryDirectory() as directory:
            view = self.view(directory)
            sent = []
            state = advance_live_domain_loop(fresh_live_domain_state(), view,
                                            lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(state['phase'], 'bid_dispatched', state)
            lower = snap['forecast']['structural']['feasibleRange'][0]
            expected = math.floor(lower - 5000)  # exact existing policy, not partial P50
            self.assertEqual(sent[0]['intent']['amount'], expected)
            self.assertLessEqual(expected, self.fixture['funds'])
            advance_live_domain_loop(state, view, lambda owner, envelope: sent.append(envelope) or True)
            self.assertEqual(len(sent), 1)

    def test_missing_floor_wrong_round_and_unqualified_source_still_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            view = self.view(directory)
            event, current = view['proposalEvent'], view['current']
            for kind in ('missing-floor', 'wrong-round', 'unqualified'):
                with self.subTest(kind=kind):
                    e, c = copy.deepcopy(event), copy.deepcopy(current)
                    if kind == 'missing-floor':
                        e['predictionSnapshot']['forecast'].pop('structural', None)
                    elif kind == 'wrong-round':
                        c['round'] = 2
                    else:
                        c['sourceQualified'] = False
                    result = build_bid_intent(e, c, now_ms=view['nowMs'], deadline_ms=view['deadlineMs'])
                    self.assertNotEqual(result['status'], 'READY', result)


if __name__ == '__main__':
    unittest.main()
