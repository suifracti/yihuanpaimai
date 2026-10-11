"""Crash/restart and funds contracts; all files isolated under project build/."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from durable_bid_obligations import DurableBidIntentBook, ObligationError
from tests.test_bid_intent_contract import budget, current, intent


class DurableContracts(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'build' / 'bid-obligation-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'obligations.json'
        self.budget = budget()
        self.book = DurableBidIntentBook.create(self.path, ledger_id='sol-b-test', budget=self.budget, clock_id='boot-1')
        self.quote = intent()

    def reopen(self, **overrides):
        args = dict(ledger_id='sol-b-test', budget=self.budget, clock_id='boot-1')
        args.update(overrides)
        return DurableBidIntentBook(self.path, **args)

    def claim(self):
        self.assertTrue(self.book.reserve(self.quote, current(), now_ms=100)['ok'])
        result = self.book.claim(self.quote['intentId'], current(), now_ms=101)
        self.assertTrue(result['ok'])
        self.assertFalse(result['executionEnabled'])
        return result

    def attempt(self):
        self.claim()
        result = self.book.attempted(self.quote['intentId'], current(), now_ms=102)
        self.assertTrue(result['executionEnabled'])
        self.assertEqual(result['durableState'], 'ATTEMPTED')
        return result

    def wire(self, status, **changes):
        return dict(current(), kind='Bid', intentId=self.quote['intentId'],
                    approvalId=self.budget['approvalId'], amount=50000, status=status,
                    evidenceRef='visible-own-bid/sequence-99', **changes)

    def test_restart_read_only_unknown_no_replay(self):
        self.attempt()
        self.book.receipt(self.wire('SENT_PENDING_CONFIRMATION'))
        before = self.path.read_bytes()
        book = self.reopen(budget=None)
        view = book.recover(current())
        self.assertEqual(view['reserved'], 50000)
        self.assertEqual(view['state']['entries'][self.quote['intentId']]['state'], 'UNKNOWN')
        self.assertFalse(view['executionEnabled'])
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(book.claim(self.quote['intentId'], current(), now_ms=103)['ok'])
        self.assertFalse(book.receipt(self.wire('CONFIRMED'), qualified=True, now_ms=104)['ok'])

    def test_committed_claim_restart_burns_round_and_preserves_money(self):
        self.claim()
        book = self.reopen()
        self.assertFalse(book.attempted(self.quote['intentId'], current(), now_ms=102)['ok'])
        self.assertFalse(book.reserve(intent(amount=30000), current(), now_ms=103)['ok'])
        self.assertEqual(book.recover()['reserved'], 50000)

    def test_reserved_restart_does_not_dispatch(self):
        self.book.reserve(self.quote, current(), now_ms=100)
        book = self.reopen()
        self.assertFalse(book.claim(self.quote['intentId'], current(), now_ms=101)['ok'])
        self.assertEqual(book.recover()['reserved'], 50000)

    def test_duplicate_claim_attempt_and_receipt(self):
        self.attempt()
        self.assertFalse(self.book.claim(self.quote['intentId'], current(), now_ms=103)['ok'])
        self.assertFalse(self.book.attempted(self.quote['intentId'], current(), now_ms=103)['ok'])
        self.assertTrue(self.book.receipt(self.wire('CONFIRMED'), qualified=True, now_ms=104)['ok'])
        self.assertTrue(self.reopen().receipt(self.wire('CONFIRMED'), qualified=True, now_ms=105)['duplicate'])
        self.assertEqual(self.reopen().recover()['spent'], 50000)
        self.assertEqual(self.reopen().recover()['reserved'], 0)
        self.assertFalse(self.book.receipt(self.wire('NOT_SENT'), qualified=True)['ok'])

    def test_unknown_cannot_release_or_resend(self):
        self.attempt()
        self.book.receipt(self.wire('UNKNOWN'))
        self.assertEqual(self.book.receipt(self.wire('NOT_SENT'), qualified=True)['state'], 'UNKNOWN')
        self.assertEqual(self.book.receipt(self.wire('SENT_PENDING_CONFIRMATION'))['state'], 'UNKNOWN')
        self.assertFalse(self.reopen().reserve(intent(amount=30000), current(), now_ms=103)['ok'])
        self.assertEqual(self.reopen().recover()['reserved'], 50000)

    def test_foreign_receipt_or_unqualified_confirmation_not_effective(self):
        self.attempt()
        for field, value in [('factsRevision', 5), ('round', 3), ('matchId', 'm2'),
                             ('approvalId', 'other'), ('amount', 49000), ('observationSessionId', 's2')]:
            receipt = self.wire('CONFIRMED')
            receipt[field] = value
            self.assertFalse(self.book.receipt(receipt, qualified=True, now_ms=103)['ok'])
        self.assertFalse(self.book.receipt(self.wire('CONFIRMED'), qualified=False, now_ms=103)['ok'])
        self.assertEqual(self.reopen().recover()['spent'], 0)

    def test_revocation_expiry_and_changed_clock_never_send(self):
        self.claim()
        self.book.budget['approved'] = False
        self.assertFalse(self.book.attempted(self.quote['intentId'], current(), now_ms=102)['ok'])
        self.assertEqual(self.reopen().recover()['reserved'], 50000)
        self.assertFalse(self.reopen(clock_id='boot-2').reserve(intent(amount=30000), current(), now_ms=0)['ok'])
        self.assertFalse(self.reopen().receipt(self.wire('CONFIRMED'), qualified=True, now_ms=1000)['ok'])

    def test_takeover_durable_freezes_and_blocks(self):
        self.attempt()
        self.book.takeover()
        book = self.reopen()
        self.assertEqual(book.recover()['reserved'], 50000)
        self.assertTrue(book.recover()['state']['stopped'])
        self.assertFalse(book.reserve(intent(amount=30000), current(), now_ms=103)['ok'])

    def test_revocation_is_durable_even_with_old_approved_object(self):
        self.claim()
        self.assertTrue(self.book.revoke_approval()['ok'])
        book = self.reopen(budget=budget())
        self.assertEqual(book.recover()['state']['stopReason'], 'APPROVAL_REVOKED')
        self.assertFalse(book.attempted(self.quote['intentId'], current(), now_ms=102)['ok'])
        self.assertFalse(book.reserve(intent(amount=30000), current(), now_ms=103)['ok'])

    def test_concurrent_attempt_returns_only_one_permission(self):
        self.claim()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.book.attempted(self.quote['intentId'], current(), now_ms=102), range(2)))
        self.assertEqual(sum(r['executionEnabled'] for r in results), 1)

    def test_next_match_cannot_inherit_obligation_or_reset_approval(self):
        self.attempt()
        next_scope = dict(current(), matchId='m2', matchGeneration=2, observationSessionId='s2', round=1)
        view = self.reopen().recover(next_scope)
        self.assertEqual(view['matchingIntentIds'], [])
        self.assertEqual(view['foreignIntentIds'], [self.quote['intentId']])
        new_budget = dict(budget(), approvalId='new-approval', binding=next_scope)
        self.assertFalse(self.reopen(budget=new_budget).reserve(self.quote, next_scope, now_ms=103)['ok'])
        self.assertEqual(self.reopen().recover()['reserved'], 50000)

    def test_truncation_checksum_foreign_file_and_missing_file_fail_closed(self):
        original = self.path.read_bytes()
        for damaged in (original[:30], b'{"unrelatedWallet":123}',
                        original.replace(b'"spent":0', b'"spent":1')):
            self.path.write_bytes(damaged)
            with self.assertRaises(ObligationError):
                self.reopen()
            self.assertEqual(self.path.read_bytes(), damaged)
        self.path.write_bytes(original)
        self.path.unlink()
        with self.assertRaises(ObligationError):
            self.reopen()
        with self.assertRaises(ObligationError):
            DurableBidIntentBook.create(self.path, ledger_id='sol-b-test', budget=budget(), clock_id='boot-1')

    def test_write_failure_returns_no_permission(self):
        self.claim()
        with patch('durable_bid_obligations._atomic_write_bytes', side_effect=OSError('simulated disk failure')):
            self.assertFalse(self.book.attempted(self.quote['intentId'], current(), now_ms=102)['executionEnabled'])
        self.assertEqual(self.reopen().recover()['state']['entries'][self.quote['intentId']]['storedState'], 'CLAIMED')

    def test_independent_processes_cannot_overreserve(self):
        # Separate interpreters prove the existing OS lock, not just a thread lock.
        script = """import sys,json;sys.path.insert(0,'core')
from durable_bid_obligations import DurableBidIntentBook
from tests.test_bid_intent_contract import budget,current,intent
b=DurableBidIntentBook(sys.argv[1],ledger_id='sol-b-test',budget=dict(budget(),remaining=70000),clock_id='boot-1')
print(json.dumps(b.reserve(intent(amount=int(sys.argv[2])),current(),now_ms=100)))"""
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda amount: json.loads(subprocess.check_output(
                [sys.executable, '-c', script, str(self.path), str(amount)], cwd=ROOT, text=True, encoding='utf-8')), [50000, 50001]))
        self.assertEqual(sum(r['ok'] for r in results), 1)
        self.assertLessEqual(self.book.recover()['reserved'], 70000)

    def test_hard_exit_before_replace_and_after_commit(self):
        for boundary in ('before_replace', 'after_commit'):
            path = Path(self.temp.name) / (boundary + '.json')
            script = """import sys,os;sys.path.insert(0,'core')
import durable_bid_obligations as d
from tests.test_bid_intent_contract import budget,current,intent
b=d.DurableBidIntentBook.create(sys.argv[1],ledger_id='crash',budget=budget(),clock_id='boot-1')
q=intent();b.reserve(q,current(),now_ms=100);b.claim(q['intentId'],current(),now_ms=101)
if sys.argv[2]=='before_replace':
    d.os.replace=lambda *a:os._exit(74)
else:
    original=d._atomic_write_bytes
    def commit_then_crash(*a):
        original(*a);os._exit(75)
    d._atomic_write_bytes=commit_then_crash
b.attempted(q['intentId'],current(),now_ms=102)"""
            code = subprocess.run([sys.executable, '-c', script, str(path), boundary], cwd=ROOT).returncode
            self.assertEqual(code, 74 if boundary == 'before_replace' else 75)
            reopened = DurableBidIntentBook(path, ledger_id='crash', budget=budget(), clock_id='boot-1')
            view = reopened.recover()
            self.assertEqual(view['reserved'], 50000)
            self.assertFalse(reopened.attempted(self.quote['intentId'], current(), now_ms=103)['ok'])
            entry = view['state']['entries'][self.quote['intentId']]
            self.assertEqual(entry['state'], 'UNKNOWN')
            self.assertEqual(entry['storedState'], 'CLAIMED' if boundary == 'before_replace' else 'ATTEMPTED')


if __name__ == '__main__':
    unittest.main()
