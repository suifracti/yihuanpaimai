"""Consume Sol-B's actual durable contract without copying a second budget book."""
import argparse
from pathlib import Path
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--owner-root", type=Path, default=root)
owner = parser.parse_args().owner_root.resolve()
sys.path[:0] = [str(root / "core"), str(owner / "core"), str(owner)]
from domain_action_session import claimed_bid_to_domain_intent, commit_domain_attempt, commit_domain_receipt
from durable_bid_obligations import DurableBidIntentBook
from tests.test_bid_intent_contract import budget, current, intent

parent = root / "build/native-domain-actions"
parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=parent) as directory:
    path = Path(directory) / "obligations.json"
    quote = intent()
    book = DurableBidIntentBook.create(path, ledger_id="sol-c-consumer-test", budget=budget(), clock_id="test-boot")
    assert book.reserve(quote, current(), now_ms=100)["ok"]
    claim = book.claim(quote["intentId"], current(), now_ms=101)
    assert claim["executionEnabled"] is False
    native = dict(current(), budget=100000, leaseExpiresNs=1000000000, takeoverGeneration=1,
                  leaseId="consumer-lease", window=dict(hwnd=10, pid=20, processInstanceToken=30, focusEpoch=40))
    prepared = claimed_bid_to_domain_intent(claim, native, now_ms=101, now_ns=101000000)
    assert commit_domain_attempt(book, prepared, current(), native, now_ms=102, now_ns=102000000)
    assert not commit_domain_attempt(book, prepared, current(), native, now_ms=103, now_ns=103000000)
    wire = dict(current(), intentId=quote["intentId"], kind="Bid", amount=50000,
                approvalId=budget()["approvalId"], status="SENT_PENDING_CONFIRMATION")
    assert commit_domain_receipt(book, wire, independently_qualified=False, now_ms=104)
    reopened = DurableBidIntentBook(path, ledger_id="sol-c-consumer-test", budget=budget(), clock_id="test-boot")
    assert not commit_domain_attempt(reopened, prepared, current(), native, now_ms=105, now_ns=105000000)
    wire.update(status="CONFIRMED", evidenceRef="independent-capture/own-seat-1/seq-22")
    assert not commit_domain_receipt(reopened, wire, independently_qualified=False, now_ms=106)
    assert commit_domain_receipt(reopened, wire, independently_qualified=True, now_ms=107)
print("PASS actual Sol-B durable book -> prepared intent -> once-only attempted ACK -> pending -> restart no resend -> qualified receipt")
