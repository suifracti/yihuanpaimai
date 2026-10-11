"""Single-book owner for the local Main <-> Native Host obligation protocol."""
from __future__ import annotations

import copy
import hashlib
import json
import threading

from domain_action_session import commit_domain_attempt, commit_domain_receipt


PROTOCOL_VERSION = 1


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def _same_intent(left, right):
    fields = ("intentId", "kind", "matchId", "matchGeneration", "observationSessionId",
              "round", "factsRevision", "amount", "budget", "maxSafeBid", "approvalId",
              "takeoverGeneration", "leaseId", "deadlineNs", "window")
    return all(left.get(field) == right.get(field) for field in fields)


class NativeBidObligationOwner:
    """Binds one already-claimed Sol-B intent to one Host process session.

    Construction never creates, reserves, claims, or repairs a ledger.  The
    only durable authority remains the injected DurableBidIntentBook.
    """

    def __init__(self, book, intent, *, current_provider, native_scope_provider,
                 now_ms, now_ns, boot_id=None):
        self.book = book
        self.intent = copy.deepcopy(intent)
        self.current_provider = current_provider
        self.native_scope_provider = native_scope_provider
        self.now_ms = now_ms
        self.now_ns = now_ns
        self.boot_id = str(boot_id or book.clock_id or "")
        self.ledger_id = str(book.ledger_id)
        self._lock = threading.RLock()
        self._requests = {}
        self._dispatched = False
        self._attempted = False
        self._closed = False
        recovered = book.recover()
        state = recovered["state"]
        entry = state["entries"].get(intent.get("intentId"))
        if (not self.boot_id or self.boot_id != book.clock_id
                or state.get("ledgerId") != self.ledger_id
                or entry is None or entry.get("storedState", entry.get("state")) != "CLAIMED"
                or entry.get("intent", {}).get("binding") != {
                    key: intent.get(key) for key in
                    ("matchId", "matchGeneration", "observationSessionId", "round", "factsRevision")
                }
                or entry.get("approvalId") != intent.get("approvalId")
                or entry.get("amount") != intent.get("amount")
                or intent.get("kind") != "Bid"):
            raise ValueError("CLAIMED_SOL_B_INTENT_REQUIRED")
        self.revision = state["revision"]
        self._claim_revision = self.revision

    def dispatch_envelope(self, request_id):
        with self._lock:
            if self._closed:
                raise RuntimeError("OBLIGATION_SESSION_CLOSED")
            if self._dispatched:
                raise RuntimeError("INTENT_ALREADY_DISPATCHED")
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError("REQUEST_ID_REQUIRED")
            try:
                state = self.book.recover()["state"]
                entry = state["entries"].get(self.intent["intentId"])
            except Exception as exc:
                self._closed = True
                raise RuntimeError("DURABLE_CLAIM_NO_LONGER_READABLE") from exc
            if (state.get("revision") != self.revision or state.get("stopped") is not False
                    or entry is None or entry.get("storedState", entry.get("state")) != "CLAIMED"):
                self._closed = True
                raise RuntimeError("DURABLE_CLAIM_CHANGED_BEFORE_DISPATCH")
            self._dispatched = True
            return {
                "type": "domain.action.dispatch",
                "protocolVersion": PROTOCOL_VERSION,
                "requestId": request_id,
                "bootId": self.boot_id,
                "ledgerId": self.ledger_id,
                "ledgerRevision": self._claim_revision,
                "observationSessionId": self.intent["observationSessionId"],
                "intent": copy.deepcopy(self.intent),
            }

    def handle_request(self, request):
        """Commit attempted/receipt before returning a correlated Main ACK."""
        if not isinstance(request, dict):
            return self._ack({}, False, "INVALID_REQUEST")
        request_id = request.get("requestId")
        if not isinstance(request_id, str) or not request_id.strip():
            return self._ack(request, False, "REQUEST_ID_REQUIRED")
        fingerprint = hashlib.sha256(_canonical(request).encode("utf-8")).hexdigest()
        with self._lock:
            prior = self._requests.get(request_id)
            if prior is not None:
                prior_fingerprint, prior_ack = prior
                if prior_fingerprint != fingerprint:
                    self._mark_unknown()
                    ack = self._ack(request, False, "REQUEST_ID_REUSED", revision=self.revision)
                    self._requests[request_id] = (prior_fingerprint, ack)
                    return copy.deepcopy(ack)
                return copy.deepcopy(prior_ack)
            if self._closed:
                return self._ack(request, False, "OBLIGATION_SESSION_CLOSED")
            reason = self._binding_error(request)
            if reason:
                same_owner = (request.get("bootId") == self.boot_id
                              and request.get("ledgerId") == self.ledger_id
                              and (request.get("intentId") == self.intent.get("intentId")
                                   or (request.get("intent") or {}).get("intentId") == self.intent.get("intentId")))
                if same_owner:
                    self._mark_unknown()
                else:
                    self._closed = True
                ack = self._ack(request, False, reason, revision=self.revision)
                self._requests[request_id] = (fingerprint, ack)
                return copy.deepcopy(ack)

            request_type = request.get("type")
            if request_type == "domain.action.obligation.request" and request.get("requestKind") == "attempted":
                ack = self._commit_attempt(request)
            elif request_type == "domain.action.receipt.commit.request":
                ack = self._commit_receipt(request)
            else:
                self._mark_unknown()
                ack = self._ack(request, False, "UNSUPPORTED_OBLIGATION_MESSAGE", revision=self.revision)
            self._requests[request_id] = (fingerprint, ack)
            return copy.deepcopy(ack)

    def receipt_is_committed(self, receipt):
        """Return true only for the receipt the Host durably committed first."""
        with self._lock:
            digest = hashlib.sha256(_canonical(receipt).encode("utf-8")).hexdigest()
            record = self._requests.get("receipt:" + str(receipt.get("intentId")))
            return bool(record and record[0] == digest and record[1].get("accepted") is True)

    def _binding_error(self, request):
        if request.get("protocolVersion") != PROTOCOL_VERSION:
            return "PROTOCOL_VERSION_MISMATCH"
        if request.get("bootId") != self.boot_id or request.get("ledgerId") != self.ledger_id:
            return "BOOT_OR_LEDGER_IDENTITY_MISMATCH"
        if type(request.get("ledgerRevision")) is not int or request["ledgerRevision"] != self.revision:
            return "LEDGER_REVISION_MISMATCH"
        if request.get("observationSessionId") != self.intent.get("observationSessionId"):
            return "STALE_OBSERVATION_SESSION"
        wire_intent = request.get("intent")
        if not isinstance(wire_intent, dict) or not _same_intent(wire_intent, self.intent):
            return "INTENT_BINDING_MISMATCH"
        return None

    def _commit_attempt(self, request):
        if self._attempted:
            return self._ack(request, False, "ATTEMPT_ALREADY_COMMITTED")
        try:
            ok = commit_domain_attempt(
                self.book, self.intent, self.current_provider(), self.native_scope_provider(),
                now_ms=self.now_ms(), now_ns=self.now_ns(), expected_revision=self.revision,
            )
        except Exception:
            ok = False
        self._refresh_revision()
        if ok:
            self._attempted = True
            return self._ack(request, True, "DURABLE_ATTEMPTED", revision=self.revision)
        self._mark_unknown()
        self._closed = True
        return self._ack(request, False, "DURABLE_ATTEMPT_NOT_COMMITTED", revision=self.revision)

    def _commit_receipt(self, request):
        receipt = request.get("receipt")
        if not isinstance(receipt, dict):
            self._mark_unknown()
            return self._ack(request, False, "RECEIPT_REQUIRED")
        if not _same_receipt_binding(receipt, self.intent):
            self._mark_unknown()
            return self._ack(request, False, "RECEIPT_BINDING_MISMATCH", revision=self.revision)
        status = receipt.get("status")
        qualified = request.get("independentlyQualified") is True
        if status == "CONFIRMED" and (not qualified or not str(receipt.get("evidenceRef") or "").strip()):
            self._mark_unknown()
            return self._ack(request, False, "VISIBLE_CONFIRMATION_REQUIRED", revision=self.revision)
        if status == "SENT_PENDING_CONFIRMATION" and not self._attempted:
            self._mark_unknown()
            return self._ack(request, False, "ATTEMPT_ACK_MISSING", revision=self.revision)
        if status not in {"NOT_SENT", "SENT_PENDING_CONFIRMATION", "CONFIRMED", "UNKNOWN"}:
            self._mark_unknown()
            return self._ack(request, False, "INVALID_RECEIPT_STATUS", revision=self.revision)
        try:
            ok = commit_domain_receipt(
                self.book, receipt, independently_qualified=qualified,
                now_ms=self.now_ms(), expected_revision=self.revision,
            )
        except Exception:
            ok = False
        self._refresh_revision()
        if not ok:
            self._closed = True
            return self._ack(request, False, "DURABLE_RECEIPT_NOT_COMMITTED", revision=self.revision)
        if status in {"CONFIRMED", "NOT_SENT", "UNKNOWN"}:
            self._closed = True
        receipt_digest = hashlib.sha256(_canonical(receipt).encode("utf-8")).hexdigest()
        ack = self._ack(request, True, "DURABLE_RECEIPT_COMMITTED", revision=self.revision)
        self._requests["receipt:" + str(receipt.get("intentId"))] = (receipt_digest, ack)
        return ack

    def _mark_unknown(self):
        wire = {key: self.intent.get(key) for key in
                ("intentId", "kind", "matchId", "matchGeneration", "observationSessionId",
                 "round", "factsRevision", "amount", "approvalId")}
        wire["status"] = "UNKNOWN"
        try:
            self.book.receipt(wire, qualified=False, now_ms=self.now_ms(), expected_revision=self.revision)
        finally:
            self._refresh_revision()
            self._closed = True

    def _refresh_revision(self):
        try:
            self.revision = int(self.book.recover()["state"]["revision"])
        except Exception:
            self._closed = True

    def _ack(self, request, accepted, reason, *, revision=None):
        return {
            "type": "domain.action.obligation.ack" if request.get("type") == "domain.action.obligation.request"
                    else "domain.action.receipt.ack",
            "requestId": request.get("requestId"),
            "bootId": self.boot_id,
            "ledgerId": self.ledger_id,
            "intentId": self.intent.get("intentId"),
            "ledgerRevision": self.revision if revision is None else revision,
            "accepted": bool(accepted),
            "reason": reason,
        }


def _same_receipt_binding(receipt, intent):
    return (receipt.get("kind") == "Bid"
            and receipt.get("intentId") == intent.get("intentId")
            and receipt.get("approvalId") == intent.get("approvalId")
            and receipt.get("amount") == intent.get("amount")
            and all(receipt.get(key) == intent.get(key) for key in
                    ("matchId", "matchGeneration", "observationSessionId", "round", "factsRevision")))
