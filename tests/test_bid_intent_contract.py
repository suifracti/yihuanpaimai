"""Issue #43 behavior contracts, no game/GUI/history/input dependencies."""
import copy
import json
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from bid_intent import build_bid_intent, BidIntentBook


def current():
    return dict(matchId='m1', matchGeneration=1, observationSessionId='s1',
                round=2, factsRevision=4, scene='IN_AUCTION',
                decisionEligible=True, sourceQualified=True)


def event():
    return dict(current(), predictionSnapshot={
        'schemaVersion': 'prediction-snapshot.v1', 'snapshotRole': 'latest_valid_pre_settlement',
        'matchId': 'm1', 'round': 2, 'predictionId': 'p1',
        'input': {'inputHash': 'h1', 'normalizedFacts': {'q': 9, 'goldAvg': 33538, 'round': 2,
                  'costs': {'sunkCost': 5000, 'total': 12000}, 'targetProfit': 30000}},
        'status': {'solverStatus': 'valid', 'diagnosticOnly': False, 'provisional': False},
        'mode': {'informationMode': 'structural_only'},
        'forecast': {'scope': 'structural_inventory', 'quantiles': None,
                     'structural': {'feasibleRange': [100000, 300000], 'center': 200000}}})


def budget():
    return dict(approved=True, approvalId='user-approval-1', binding=current(),
                expiresAtMs=1000, remaining=100000, maxBid=80000)


def intent(e=None, c=None, amount=50000):
    return build_bid_intent(e or event(), c or current(), now_ms=100, deadline_ms=800, requested_bid=amount)


class BidIntentContract(unittest.TestCase):
    def test_main_delivery_proposal_uses_readback_age_and_rejects_missing_or_invalid_timing(self):
        import ast
        import math
        from types import SimpleNamespace
        from native_capture_delivery import DELIVERY, validate_delivery
        from tests.test_native_delivery_contract import proof
        tree = ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8'))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in {'_build_native_bid_intent_presentation', '_native_use_age_ms'}]
        original = proof(1, request=1_000_000_000, session='s1')
        ns = dict(math=math, DELIVERY=DELIVERY, validate_delivery=validate_delivery,
                  time=SimpleNamespace(perf_counter_ns=lambda: original['readbackCompletedNs'] + 250_000_000),
                  native_observation_enabled=lambda: True, CURRENT_MATCH=SimpleNamespace(id='m1', _seq=1),
                  _native_solver_lease_matches=lambda _: True)
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *functions], type_ignores=[])),
                     str(ROOT / 'app/main.py'), 'exec'), ns)
        payload = {**current(), 'timer': 5, 'freshnessMs': None, 'captureFreshnessPolicy': DELIVERY,
                   'deliveryProof': original, 'observationStatus': 'FRAME',
                   'observationProfile': 'native-readonly-v1', 'sourceKind': 'native_wgc'}
        build = lambda value: ns['_build_native_bid_intent_presentation'](value,
            event()['predictionSnapshot'], None, native_projection_current=True,
            solver_status='valid', solver_admission={'eligible': True})
        self.assertEqual(build(payload)['status'], 'READY')
        self.assertEqual(build(payload)['maxSafeBid'], 58000)
        self.assertFalse(build(payload)['executionEnabled'])
        for bad in ({**payload, 'timer': None},
                    {**payload, 'deliveryProof': {**original, 'drainTakeCount': 0}}):
            self.assertEqual(build(bad)['status'], 'UNKNOWN')

    def test_structural_floor_not_center_or_p50_and_costs_once(self):
        value = intent()
        self.assertEqual(value['status'], 'READY', value)
        self.assertEqual(value['maxSafeBid'], 58000)  # 100000 - 5000 - 7000 - 30000
        self.assertEqual(value['valuationBasis'], 'FEASIBLE_LOWER_BOUND_NOT_P50')
        self.assertFalse(value['executionEnabled'])
        self.assertFalse(BidIntentBook().reserve(value, current(), now_ms=100)['ok'])

    def test_same_match_update_late_round_and_other_session_rejected(self):
        for key, value in [('factsRevision', 5), ('round', 3), ('matchId', 'm2'),
                           ('matchGeneration', 2), ('observationSessionId', 's2')]:
            with self.subTest(key=key):
                live = dict(current(), **{key: value})
                self.assertEqual(intent(c=live)['prohibitions'], ['STALE_SCOPE'])

    def test_revision_update_between_reservation_and_dispatch_cancels(self):
        book = BidIntentBook(budget())
        value = intent()
        self.assertTrue(book.reserve(value, current(), now_ms=100)['ok'])
        self.assertFalse(book.claim(value['intentId'], dict(current(), factsRevision=5), now_ms=101)['ok'])
        self.assertEqual(book._reserved(), 0)

    def test_no_average_is_unknown_even_if_snapshot_has_range(self):
        e = event()
        del e['predictionSnapshot']['input']['normalizedFacts']['goldAvg']
        self.assertEqual(intent(e)['status'], 'UNKNOWN')

    def test_qualification_loss_and_settlement_do_not_use_answers(self):
        for changes in ({'sourceQualified': False}, {'decisionEligible': False}, {'scene': 'SETTLEMENT'}):
            with self.subTest(changes=changes):
                self.assertEqual(intent(c=dict(current(), **changes))['status'], 'SKIP')
        e = event()
        e['scene'] = 'SETTLEMENT'
        e['actualTotal'] = 90000000
        self.assertEqual(intent(e)['status'], 'SKIP')

    def test_possible_loss_or_above_cap_is_skip(self):
        self.assertEqual(intent(amount=58001)['prohibitions'], ['BID_EXCEEDS_SAFE_CAP'])
        e = event()
        e['predictionSnapshot']['forecast']['structural']['feasibleRange'] = [10000, 300000]
        self.assertEqual(intent(e)['prohibitions'], ['NO_POSITIVE_SAFE_BID'])

    def test_full_shadow_reuses_risk_line_and_p20(self):
        e = event()
        e['predictionSnapshot']['mode']['informationMode'] = 'full_shadow'
        e['predictionSnapshot']['mode']['coverageRatio'] = 1
        e['predictionSnapshot']['forecast'] = {'scope': 'full_inventory', 'quantiles': {'p20': 150000, 'p50': 200000, 'p80': 260000}}
        e['frozenPrediction'] = {'decision': {'targetLine': 90000}}
        self.assertEqual(intent(e)['maxSafeBid'], 90000)
        e['frozenPrediction']['decision']['targetLine'] = 150000
        self.assertEqual(intent(e)['maxSafeBid'], 108000)

    def test_partial_shadow_and_bad_solver_states_never_ready(self):
        e = event()
        e['predictionSnapshot']['mode']['informationMode'] = 'partial_shadow'
        self.assertEqual(intent(e)['status'], 'UNKNOWN')
        for status in ('incomplete', 'timeout', 'diagnostic', 'no-match', 'stale', 'fallback'):
            e = event()
            e['predictionSnapshot']['status']['solverStatus'] = status
            self.assertEqual(intent(e)['status'], 'SKIP')

    def test_deadline_and_approval_expiry(self):
        value = intent()
        self.assertFalse(BidIntentBook(budget()).reserve(value, current(), now_ms=800)['ok'])
        b = budget()
        b['expiresAtMs'] = 100
        self.assertFalse(BidIntentBook(b).reserve(value, current(), now_ms=100)['ok'])

    def test_budget_limit_and_reservation_compete(self):
        book = BidIntentBook(dict(budget(), remaining=70000))
        self.assertTrue(book.reserve(intent(), current(), now_ms=100)['ok'])
        self.assertEqual(book.reserve(intent(amount=30000), current(), now_ms=100)['reason'], 'BUDGET_EXCEEDED')
        self.assertEqual(book._reserved(), 50000)

    def test_concurrent_reservation_cannot_overdraw(self):
        book = BidIntentBook(dict(budget(), remaining=70000))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda amount: book.reserve(intent(amount=amount), current(), now_ms=100), [50000, 50001]))
        self.assertEqual(sum(r['ok'] for r in results), 1)
        self.assertLessEqual(book._reserved(), 70000)

    def test_budget_revocation_or_reduction_at_dispatch(self):
        for change in ({'approved': False}, {'remaining': 40000}, {'maxBid': 40000}):
            book = BidIntentBook(budget())
            value = intent()
            book.reserve(value, current(), now_ms=100)
            book.budget.update(change)
            self.assertFalse(book.claim(value['intentId'], current(), now_ms=101)['executionEnabled'])

    def test_modified_quote_cannot_reserve_under_old_identity(self):
        value = intent()
        value['maxSafeBid'] = 100000
        self.assertEqual(BidIntentBook(budget()).reserve(value, current(), now_ms=100)['reason'], 'INTENT_MODIFIED')

    def test_duplicate_confirmation_debits_once_and_conflict_rejected(self):
        book = BidIntentBook(budget())
        value = intent()
        book.reserve(value, current(), now_ms=100)
        self.assertTrue(book.claim(value['intentId'], current(), now_ms=101)['executionEnabled'])
        self.assertTrue(book.confirm(value['intentId'], 'EFFECTIVE')['ok'])
        self.assertTrue(book.confirm(value['intentId'], 'EFFECTIVE')['duplicate'])
        self.assertEqual(book.spent, 50000)
        self.assertFalse(book.confirm(value['intentId'], 'NOT_SENT')['ok'])

    def test_unknown_holds_money_and_blocks_repeat_dispatch(self):
        book = BidIntentBook(budget())
        value = intent()
        book.reserve(value, current(), now_ms=100)
        book.claim(value['intentId'], current(), now_ms=101)
        book.confirm(value['intentId'], 'UNKNOWN')
        self.assertEqual(book._reserved(), 50000)
        self.assertFalse(book.claim(value['intentId'], current(), now_ms=102)['ok'])
        other = intent(amount=30000)
        book.reserve(other, current(), now_ms=103)
        self.assertEqual(book.claim(other['intentId'], current(), now_ms=104)['reason'], 'ROUND_ALREADY_CLAIMED')

    def test_approval_scope_and_invalid_money_fail_closed(self):
        b = budget()
        b['binding'] = dict(current(), matchId='m2')
        self.assertEqual(BidIntentBook(b).reserve(intent(), current(), now_ms=100)['reason'], 'BUDGET_SCOPE_MISMATCH')
        for invalid in (True, float('nan'), -1, '50000'):
            self.assertEqual(intent(amount=invalid)['status'], 'SKIP')
        proposal_only = intent(amount=None)
        self.assertEqual(proposal_only['status'], 'READY')
        self.assertFalse(BidIntentBook(budget()).reserve(proposal_only, current(), now_ms=100)['ok'])

    def test_actual_existing_solver_output_is_consumed(self):
        script = """const e=require('./core/auction_engine_v06.js');
        const r=e.solveAuctionPipeline({matchId:'m1',round:2,q:9,avg:33538,venue:'shanhu',fieldCondition:'standard',
        costs:{entry:5000,sunkCost:5000,futureIncrementalCost:7000},targetProfit:30000},[]);
        process.stdout.write(JSON.stringify({predictionSnapshot:r.predictionSnapshot,frozenPrediction:r.frozenPrediction}));"""
        solved = json.loads(subprocess.check_output(['node', '-e', script], cwd=ROOT, text=True, encoding='utf-8'))
        self.assertEqual(solved['predictionSnapshot']['schemaVersion'], 'prediction-snapshot.v1')
        self.assertEqual(solved['predictionSnapshot']['matchId'], 'm1')
        self.assertEqual(solved['predictionSnapshot']['input']['normalizedFacts']['round'], 2)
        value = intent(dict(current(), **solved), amount=1000)
        self.assertEqual(value['status'], 'READY', value)
        self.assertEqual(value['costs'], {'sunk': 5000, 'future': 7000, 'targetProfit': 30000})
        self.assertEqual(value['source']['producer']['solverName'], 'auction_engine_v06')
        self.assertFalse(value['executionEnabled'])


if __name__ == '__main__':
    unittest.main()
