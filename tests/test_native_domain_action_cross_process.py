"""Windows-only real-process Main/Host obligation round trip against an owned dummy."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "core"), str(ROOT / "tests")]

from bid_intent import build_bid_intent
from durable_bid_obligations import DurableBidIntentBook
from domain_action_session import claimed_bid_to_domain_intent
from native_domain_action_obligations import NativeBidObligationOwner
from native_observation import NativeObservationBridge
from test_bid_intent_contract import budget as sample_budget, current as sample_current, event as sample_event


@unittest.skipUnless(os.name == "nt", "requires the self-owned Windows dummy target")
class NativeDomainActionCrossProcessTests(unittest.TestCase):
    def test_main_durable_ack_precedes_dummy_input_and_receipts_precede_projection(self):
        import main as app_main

        evidence_dir = ROOT / "build" / "native-domain-actions"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        errors = []
        receipts = []
        obligation_acks = []
        projected = []
        complete = threading.Event()
        owner_holder = {}
        host_complete_seen = []
        current_holder = {}
        scope_holder = {}
        book_holder = {}
        root_tmp = tempfile.TemporaryDirectory(prefix="cross-process-", dir=evidence_dir)
        current_match = SimpleNamespace(id="match-1", _seq=1)
        latest = {}

        def build_and_dispatch(bridge, ready):
            try:
                now_ms = int(time.monotonic() * 1000)
                now_ns = time.monotonic_ns()
                scope = dict(sample_current(), matchId="match-1", matchGeneration=1,
                             observationSessionId="obs-1", round=1, factsRevision=7,
                             scene="IN_AUCTION", sourceQualified=True, decisionEligible=True)
                proposal_event = sample_event()
                proposal_event.update(scope)
                proposal_event["predictionSnapshot"]["matchId"] = "match-1"
                proposal_event["predictionSnapshot"]["round"] = 1
                proposal_event["predictionSnapshot"]["input"]["normalizedFacts"]["round"] = 1
                proposal = build_bid_intent(proposal_event, scope, now_ms=now_ms,
                                            deadline_ms=now_ms + 45_000, requested_bid=12_345)
                budget = sample_budget()
                budget["binding"] = scope
                budget["expiresAtMs"] = now_ms + 60_000
                ledger_id = "cross-process-" + uuid.uuid4().hex
                path = Path(root_tmp.name) / "obligations.json"
                book = DurableBidIntentBook.create(path, ledger_id=ledger_id,
                                                   budget=budget, clock_id=ready["bootId"])
                if not book.reserve(proposal, scope, now_ms=now_ms)["ok"]:
                    raise AssertionError("DUMMY_RESERVATION_FAILED")
                claim = book.claim(proposal["intentId"], scope, now_ms=now_ms + 1)
                if not claim.get("ok") or claim.get("state") != "CLAIMED":
                    raise AssertionError("DUMMY_CLAIM_FAILED")
                window = copy.deepcopy(ready["window"])
                native_scope = dict(scope, budget=budget["remaining"],
                    clockAnchorMs=now_ms, clockAnchorNs=now_ns,
                    leaseExpiresNs=now_ns + 60_000_000_000, takeoverGeneration=2,
                    leaseId="dummy-lease", window=window)
                prepared = claimed_bid_to_domain_intent(claim, native_scope,
                    now_ms=now_ms + 2, now_ns=now_ns + 2_000_000)
                owner = NativeBidObligationOwner(book, prepared,
                    current_provider=lambda: scope,
                    native_scope_provider=lambda: native_scope,
                    now_ms=lambda: int(time.monotonic() * 1000),
                    now_ns=time.monotonic_ns, boot_id=ready["bootId"])
                owner_holder["owner"] = owner
                current_holder["scope"] = scope
                scope_holder["native"] = native_scope
                book_holder["book"] = book
                app_main._NATIVE_DOMAIN_ACTION_BOOT_ID = ready["bootId"]
                if not app_main._native_bind_claimed_bid_obligation_owner(owner):
                    raise AssertionError("MAIN_REFUSED_CURRENT_CLAIM_BINDING")
                if not app_main._native_dispatch_claimed_bid_to_host():
                    raise AssertionError("MAIN_DISPATCH_DID_NOT_REACH_HOST")
            except Exception as exc:
                errors.append(exc)
                complete.set()

        def on_event(event):
            if event.get("type") == "domain.action.host_ready":
                build_and_dispatch(bridge, event)
            elif event.get("type") == "domain.action.receipt":
                projected_event = app_main._native_observation_event(event)
                if projected_event is not None:
                    projected.append(projected_event)
                receipts.append(copy.deepcopy(event["receipt"]))
            elif event.get("type") == "domain.action.host_complete":
                if event.get("dummyInputCount") != 3 or event.get("inputActions") is not False:
                    errors.append(AssertionError("DUMMY_HOST_COMPLETION_SCOPE_INVALID"))
                host_complete_seen.append(True)
                complete.set()
            elif event.get("type") == "native_observation" and event.get("status") in {"ERROR", "PAUSED"}:
                if not host_complete_seen:
                    errors.append(copy.deepcopy(event))
                    complete.set()

        def handle_obligation(request):
            ack = app_main._native_domain_action_obligation_request(request)
            obligation_acks.append((request.get("type"), request.get("requestKind"), copy.deepcopy(ack)))
            return ack

        logs = []
        bridge = NativeObservationBridge(
            str(ROOT), on_event, lambda category, message: logs.append((category, message)),
            on_obligation_request=handle_obligation,
        )
        command = ["dotnet", "run", "--project",
                   str(ROOT / "tests" / "native_domain_actions" / "domain-actions.csproj"),
                   "--", "--cross-process-dummy-host"]
        child = subprocess.Popen(command, cwd=str(ROOT), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        bridge.process = child
        bridge._reader = threading.Thread(target=bridge._read_stdout, args=(child,), daemon=True)
        bridge._stderr_reader = threading.Thread(target=bridge._read_stderr, args=(child,), daemon=True)
        bridge._reader.start()
        bridge._stderr_reader.start()
        old_owner = app_main._NATIVE_DURABLE_BID_OBLIGATION_OWNER
        try:
            with mock.patch.multiple(app_main,
                _NATIVE_EXPECTED_SESSION="obs-1", _NATIVE_OBSERVATION_SESSION="obs-1",
                CURRENT_MATCH=current_match, LATEST_PAYLOAD=latest, WS_EVENT_LOOP=None,
                NATIVE_OBSERVATION_BRIDGE=bridge, _NATIVE_DOMAIN_ACTION_BOOT_ID=None), \
                 mock.patch.object(app_main, "get_current_match_presentation_summary",
                    side_effect=lambda: {"bidActionReceipt": copy.deepcopy(latest.get("bidActionReceipt"))}), \
                 mock.patch.object(app_main, "_native_post_main_status"):
                app_main._NATIVE_DURABLE_BID_OBLIGATION_OWNER = None
                self.assertTrue(complete.wait(45), "CROSS_PROCESS_DUMMY_TIMEOUT")
                early_errors = [error for error in errors if not isinstance(error, dict)]
                self.assertFalse(early_errors, early_errors)
                exit_code = child.wait(timeout=10)
                bridge._stderr_reader.join(timeout=2)
                self.assertFalse(errors, "HOST_EXITED_BEFORE_DOMAIN_E2E_COMPLETE: "
                    + repr(errors) + " | " + " | ".join(message for _, message in logs[-8:])
                    + " | ACKS=" + repr(obligation_acks))
                self.assertEqual(exit_code, 0, "HOST_PROCESS_FAILED: " + " | ".join(message for _, message in logs[-8:]))
                self.assertEqual([row["status"] for row in receipts],
                                 ["SENT_PENDING_CONFIRMATION", "CONFIRMED"])
                self.assertEqual([row["currentMatch"]["bidActionReceipt"]["status"] for row in projected],
                                 ["SENT_PENDING_CONFIRMATION", "CONFIRMED"])
                owner = owner_holder["owner"]
                entry = owner.book.recover()["state"]["entries"][owner.intent["intentId"]]
                self.assertEqual(entry["state"], "EFFECTIVE")
                self.assertEqual(owner.book.recover()["state"]["spent"], owner.intent["amount"])
                self.assertEqual(latest["bidActionReceipt"]["status"], "CONFIRMED")
        finally:
            app_main._NATIVE_DURABLE_BID_OBLIGATION_OWNER = old_owner
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
            root_tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
