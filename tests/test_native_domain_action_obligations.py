"""Main-owned one-shot protocol checks around Sol-B's existing durable book."""
from pathlib import Path
import tempfile
import unittest

from durable_bid_obligations import DurableBidIntentBook
from domain_action_session import claimed_bid_to_domain_intent
from native_domain_action_obligations import NativeBidObligationOwner
from test_bid_intent_contract import budget, current, intent


class NativeBidObligationProtocolTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / "build" / "native-domain-actions"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.current = current()
        self.budget = budget()
        self.book = DurableBidIntentBook.create(
            Path(self.temp.name) / "obligations.json", ledger_id="protocol-ledger",
            budget=self.budget, clock_id="protocol-boot")
        self.proposal = intent()
        self.assertTrue(self.book.reserve(self.proposal, self.current, now_ms=100)["ok"])
        claim = self.book.claim(self.proposal["intentId"], self.current, now_ms=101)
        self.claim = claim
        native = dict(self.current, budget=100000, leaseExpiresNs=1_000_000_000,
                      takeoverGeneration=1, leaseId="protocol-lease",
                      window=dict(hwnd=10, pid=20, processInstanceToken=30, focusEpoch=40))
        self.native = native
        self.intent = claimed_bid_to_domain_intent(
            claim, native, now_ms=101, now_ns=101_000_000)
        self.owner = NativeBidObligationOwner(
            self.book, self.intent, current_provider=lambda: self.current,
            native_scope_provider=lambda: native, now_ms=lambda: 102,
            now_ns=lambda: 102_000_000, boot_id="protocol-boot")

    def test_millisecond_quantization_does_not_reconvert_the_fixed_deadline(self):
        self.native.update(clockAnchorMs=101, clockAnchorNs=101_900_000)
        prepared = claimed_bid_to_domain_intent(self.claim, self.native,
                                               now_ms=101, now_ns=101_900_000)
        owner = NativeBidObligationOwner(self.book, prepared,
            current_provider=lambda: self.current, native_scope_provider=lambda: self.native,
            now_ms=lambda: 102, now_ns=lambda: 102_100_000, boot_id="protocol-boot")
        request = owner.dispatch_envelope('quantized-clock')
        request.update(type='domain.action.obligation.request', requestKind='attempted',
                       intentId=prepared['intentId'])
        ack = owner.handle_request(request)
        self.assertTrue(ack['accepted'], ack)
        self.assertEqual(owner.intent['deadlineNs'], 800_900_000)
        for changes, ms, ns in (({}, 800, 800_900_000),
                                ({'clockAnchorMs': 103}, 102, 102_100_000),
                                ({'clockAnchorNs': 103_000_000}, 102, 102_100_000),
                                ({'leaseExpiresNs': 700_000_000}, 102, 102_100_000)):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    claimed_bid_to_domain_intent(self.claim, dict(self.native, **changes),
                                                now_ms=ms, now_ns=ns)

    def test_dispatch_and_attempt_are_one_shot_and_revision_bound(self):
        self.owner.dispatch_envelope("dispatch-one")
        with self.assertRaisesRegex(RuntimeError, "INTENT_ALREADY_DISPATCHED"):
            self.owner.dispatch_envelope("dispatch-two")
        # Recreate a request after its dispatch was already issued.
        request = {
            "type": "domain.action.obligation.request", "protocolVersion": 1,
            "requestId": "attempt-1", "requestKind": "attempted",
            "bootId": self.owner.boot_id, "ledgerId": self.owner.ledger_id,
            "ledgerRevision": self.owner.revision,
            "observationSessionId": self.intent["observationSessionId"],
            "intentId": self.intent["intentId"], "intent": self.intent,
        }
        first = self.owner.handle_request(request)
        self.assertTrue(first["accepted"], first)
        duplicate = dict(request, requestId="attempt-2", ledgerRevision=self.owner.revision)
        denied = self.owner.handle_request(duplicate)
        self.assertFalse(denied["accepted"])
        self.assertEqual(denied["reason"], "ATTEMPT_ALREADY_COMMITTED")
        entry = self.book.recover()["state"]["entries"][self.intent["intentId"]]
        self.assertEqual(entry["storedState"], "ATTEMPTED")

    def test_wrong_receipt_frame_freezes_attempt_as_unknown(self):
        attempt = self.owner.dispatch_envelope("dispatch-one")
        request = dict(attempt, type="domain.action.obligation.request", requestId="attempt-1",
                       requestKind="attempted", intentId=self.intent["intentId"], intent=self.intent)
        self.assertTrue(self.owner.handle_request(request)["accepted"])
        receipt = dict(self.intent, status="CONFIRMED", evidenceRef="dummy-independent-frame")
        receipt["factsRevision"] += 1
        request = {
            "type": "domain.action.receipt.commit.request", "protocolVersion": 1,
            "requestId": "wrong-frame-receipt", "bootId": self.owner.boot_id,
            "ledgerId": self.owner.ledger_id, "ledgerRevision": self.owner.revision,
            "observationSessionId": self.intent["observationSessionId"],
            "intentId": self.intent["intentId"], "intent": self.intent,
            "receipt": receipt, "independentlyQualified": True,
        }
        ack = self.owner.handle_request(request)
        self.assertFalse(ack["accepted"])
        self.assertEqual(ack["reason"], "RECEIPT_BINDING_MISMATCH")
        entry = self.book.recover()["state"]["entries"][self.intent["intentId"]]
        self.assertEqual(entry["storedState"], "UNKNOWN")
        self.assertFalse(self.owner.handle_request(dict(request, requestId="retry-receipt"))["accepted"])


if __name__ == "__main__":
    unittest.main()
