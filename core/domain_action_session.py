"""Receipt-driven orchestration around the existing AuctionSessionFSM.

Only qualified observations go to the legacy FSM. Preparation is configuration;
neither it nor a successful send may create a new session. No input or history IO.
"""
from dataclasses import dataclass
from typing import Optional

from session_fsm import AuctionSessionFSM, SessionState
from vision_contract import VisionObservation


@dataclass(frozen=True)
class NextMatchAdmission:
    admission_id: str
    previous_match_id: str
    budget: int
    deadline_ns: int
    lease_id: str
    takeover_generation: int
    previous_match_generation: int
    observation_session_id: str
    explicitly_authorized: bool = False


class DomainActionSession:
    def __init__(self, fsm: AuctionSessionFSM, match_id: str, *, match_generation: int,
                 observation_session_id: str):
        if not match_id or fsm.state not in (SessionState.AUCTION_R1, SessionState.AUCTION_ACTIVE):
            raise ValueError("ACTIVE_MATCH_REQUIRED")
        self.fsm = fsm
        self.match_id = match_id
        if type(match_generation) is not int or match_generation <= 0 or not observation_session_id:
            raise ValueError("GENERATION_AND_OBSERVATION_SESSION_REQUIRED")
        self.match_generation = match_generation
        self.observation_session_id = observation_session_id
        self.phase = "AUCTION"
        self.admission: Optional[NextMatchAdmission] = None
        self.pending_intent: Optional[str] = None
        self.last_evidence_sequence = 0

    def observe(self, observation: VisionObservation, *, match_id: str,
                qualified: bool, source_sequence: int) -> bool:
        if (self.phase != "AUCTION" or not qualified or match_id != self.match_id
                or source_sequence <= self.last_evidence_sequence):
            return False
        self.fsm.handle_observation(observation)
        self.last_evidence_sequence = source_sequence
        if self.fsm.state == SessionState.SETTLEMENT:
            self.phase = "SETTLEMENT"
        return True

    def archive_completed(self, *, match_id: str, write_success: bool) -> bool:
        if self.phase != "SETTLEMENT" or match_id != self.match_id:
            return False
        if not self.fsm.mark_archive_ready(write_success):
            return False
        self.phase = "ARCHIVED"
        return True

    def accept_receipt(self, receipt: dict, *, now_ns: int) -> bool:
        """Consume Native confirmed receipts; Main must not manufacture CONFIRMED.

        The Native coordinator validates identity, current lease, budget, source
        qualification/age and result attribution before publishing this contract.
        """
        if (self.phase == "STOPPED" or receipt.get("matchId") != self.match_id
                or receipt.get("matchGeneration") != self.match_generation
                or receipt.get("observationSessionId") != self.observation_session_id):
            return False
        status = receipt.get("status")
        kind = receipt.get("kind")
        intent_id = receipt.get("intentId")
        if not isinstance(intent_id, str) or not intent_id:
            return False
        if status == "UNKNOWN":
            self.stop()
            return False
        if status == "NOT_SENT":
            # NOT_SENT cannot revoke an already pending send. A conflicting
            # same-ID receipt is uncertain delivery, never permission to retry.
            if intent_id == self.pending_intent:
                self.stop()
            return False
        expected = ((kind == "ReturnLobby" and self.phase == "ARCHIVED")
                    or (kind == "StartNextMatch" and self.phase == "NEXT_PREPARED"))
        if not expected:
            return False
        if self.pending_intent is not None and intent_id != self.pending_intent:
            return False
        if kind == "StartNextMatch" and not self.admission_current(now_ns):
            self.stop()
            return False
        if status == "SENT_PENDING_CONFIRMATION":
            self.pending_intent = intent_id
            return True  # Legacy FSM deliberately unchanged.
        sequence = receipt.get("evidenceSequence", 0)
        if (status != "CONFIRMED" or self.pending_intent != intent_id
                or type(sequence) is not int or sequence <= self.last_evidence_sequence):
            return False
        if kind == "ReturnLobby":
            # Zero-round lobby evidence only: do not feed a retained auction frame
            # to the legacy ARCHIVED reset branch (which can auto-create a session).
            self.fsm.handle_observation(VisionObservation(round=0))
            self.phase = "LOBBY"
        else:
            new_id = receipt.get("newMatchId")
            new_generation = receipt.get("newMatchGeneration")
            if (not isinstance(new_id, str) or not new_id or new_id == self.match_id
                    or type(new_generation) is not int or new_generation <= self.match_generation):
                return False
            self.fsm.trigger_match_start()
            self.fsm.handle_observation(VisionObservation(round=1))
            self.match_id = new_id
            self.match_generation = new_generation
            self.phase = "AUCTION"
            self.admission = None
        self.last_evidence_sequence = sequence
        self.pending_intent = None
        return True

    def prepare_next(self, admission: NextMatchAdmission, *, now_ns: int) -> bool:
        if (self.phase != "LOBBY" or self.pending_intent is not None
                or admission.previous_match_id != self.match_id
                or admission.previous_match_generation != self.match_generation
                or admission.observation_session_id != self.observation_session_id
                or not admission.admission_id or not admission.lease_id
                or type(admission.budget) is not int or admission.budget <= 0
                or not admission.explicitly_authorized or now_ns >= admission.deadline_ns):
            return False
        self.admission = admission
        self.phase = "NEXT_PREPARED"
        return True

    def admission_current(self, now_ns: int) -> bool:
        return bool(self.admission and self.admission.explicitly_authorized
                    and self.admission.previous_match_id == self.match_id
                    and self.admission.previous_match_generation == self.match_generation
                    and self.admission.observation_session_id == self.observation_session_id
                    and self.admission.budget > 0 and now_ns < self.admission.deadline_ns)

    def continuity(self, *, connected: bool, target_matches: bool, budget_known: bool,
                   lease_id: str, takeover_generation: int, now_ns: int) -> bool:
        if (not connected or not target_matches or not budget_known
                or (self.admission and (not self.admission_current(now_ns)
                    or lease_id != self.admission.lease_id
                    or takeover_generation != self.admission.takeover_generation))):
            self.stop()
            return False
        return self.phase != "STOPPED"

    def stop(self):
        self.phase = "STOPPED"
        self.admission = None
        # Preserve pending ID for diagnosis; stopping never means a safe retry.


def claimed_bid_to_domain_intent(claim: dict, native_scope: dict, *, now_ms: int,
                                 now_ns: int) -> dict:
    """Translate Sol-B #47's once-only claim; never reserve/claim or grant approval.

    The caller pairs current monotonic readings, persists the claimed obligation
    BEFORE handing this result to Native, and supplies independent Native scope.
    """
    durable_preparation = (claim.get("executionEnabled") is False
                           and claim.get("commitBeforeSendRequired") is True)
    if (claim.get("ok") is not True or claim.get("state") != "CLAIMED"
            or (claim.get("executionEnabled") is not True and not durable_preparation)):
        raise ValueError("ONCE_ONLY_CLAIM_REQUIRED")
    proposal = claim.get("intent") or {}
    budget = claim.get("budget") or {}
    binding = proposal.get("binding") or {}
    keys = ("matchId", "matchGeneration", "observationSessionId", "round", "factsRevision")
    if (proposal.get("schemaVersion") != "bid-intent.v1" or proposal.get("status") != "READY"
            or any(binding.get(key) != native_scope.get(key) for key in keys)
            or any(not isinstance(binding.get(key), str) or not binding[key].strip()
                   for key in ("matchId", "observationSessionId"))
            or any(type(binding.get(key)) is not int or binding[key] < (0 if key == "factsRevision" else 1)
                   for key in ("matchGeneration", "round", "factsRevision"))):
        raise ValueError("CLAIM_SCOPE_MISMATCH")
    amount = claim.get("amount")
    remaining = budget.get("remaining")
    deadline_ms = proposal.get("deadlineMs")
    cap = proposal.get("maxSafeBid")
    if (type(amount) is not int or not 0 < amount <= 9_999_999
            or type(cap) is not int or amount > cap or amount != proposal.get("requestedBid")
            or budget.get("approved") is not True or not claim.get("approvalId")
            or claim.get("approvalId") != budget.get("approvalId")
            or type(remaining) is not int or remaining < amount
            or remaining != native_scope.get("budget")):
        raise ValueError("CLAIM_AMOUNT_OR_APPROVED_BUDGET_INVALID")
    if (type(now_ms) is not int or type(now_ns) is not int
            or type(deadline_ms) is not int or now_ms >= deadline_ms):
        raise ValueError("CLAIM_DEADLINE_INVALID")
    # Convert once per captured scope. Repeating this conversion with a newly
    # rounded millisecond sample moves the deadline by up to a millisecond and
    # spuriously rejects the very same immutable intent at commit-before-input.
    anchor_ms = native_scope.get("clockAnchorMs", now_ms)
    anchor_ns = native_scope.get("clockAnchorNs", now_ns)
    if (type(anchor_ms) is not int or type(anchor_ns) is not int
            or anchor_ms > now_ms or anchor_ns > now_ns):
        raise ValueError("CLAIM_CLOCK_ANCHOR_INVALID")
    deadline_ns = anchor_ns + (deadline_ms - anchor_ms) * 1_000_000
    if now_ns >= deadline_ns:
        raise ValueError("CLAIM_DEADLINE_INVALID")
    if deadline_ns > native_scope.get("leaseExpiresNs", 0):
        raise ValueError("CLAIM_EXCEEDS_NATIVE_LEASE")
    return dict(intentId=proposal["intentId"], kind="Bid", **binding, amount=amount, maxSafeBid=cap,
                budget=remaining, deadlineNs=deadline_ns, approvalId=claim["approvalId"],
                takeoverGeneration=native_scope["takeoverGeneration"],
                leaseId=native_scope["leaseId"], window=dict(native_scope["window"]))


def commit_domain_attempt(book, intent: dict, current: dict, native_scope: dict, *,
                          now_ms: int, now_ns: int, expected_revision=None) -> bool:
    """Native commit-before-input callback into Sol-B's sole durable book.

    Luna-B owns transport. The prepared intent grants no send permission. Never
    call attempted() during preparation or call it a second time on its ACK.
    """
    permit = book.attempted(intent.get("intentId"), current, now_ms=now_ms,
                            expected_revision=expected_revision)
    if permit.get("ok") is not True or permit.get("durableState") != "ATTEMPTED":
        return False
    try:
        verified = claimed_bid_to_domain_intent(permit, native_scope, now_ms=now_ms, now_ns=now_ns)
        intact = all(intent.get(key) == verified.get(key) for key in verified if key != "deadlineNs")
        # A conversion cannot extend the deadline of the earlier prepared intent.
        intact = intact and now_ns < intent["deadlineNs"] <= verified["deadlineNs"]
    except (KeyError, TypeError, ValueError):
        intact = False
    if not intact:
        unknown = {key: intent.get(key) for key in ("intentId", "kind", "matchId", "matchGeneration",
            "observationSessionId", "round", "factsRevision", "amount", "approvalId")}
        unknown["status"] = "UNKNOWN"
        book.receipt(unknown, qualified=False, now_ms=now_ms)
    return intact


def confirm_send_and_receive(ledger_path, event, current, *, configured_cap, current_funds,
                             user_confirmed, approval_id, pre_frame, next_frame,
                             native_scope, now_ms, now_ns, deadline_ms, clock_id):
    """建议出价 → 主窗口确认 → Host 发送 → 新画面回执.

    A missing or unchanged picture is UNKNOWN and is not sent again. This is
    not the skip-animation retry. The ledger is created only after the bid
    panel, the Solver suggestion, the fund cap, and the confirmation all pass.
    """
    from bid_intent import build_bid_intent, capped_send_amount, solver_suggestion
    from scene_anchors import classify_auction_flow_frame, committed_bid_amounts, frame_digest

    scene = classify_auction_flow_frame(pre_frame)
    if scene.get('scene') != 'BID_PANEL':
        return _bid_stop('PRECONDITION_NOT_BID_PANEL', scene=scene)
    proposal = build_bid_intent(event, current, now_ms=now_ms, deadline_ms=deadline_ms, requested_bid=None)
    suggestion = solver_suggestion(proposal)
    if suggestion is None:
        return _bid_stop(proposal.get('prohibitions', ['NO_SOLVER_SUGGESTION'])[0], proposal=proposal)
    amount = capped_send_amount(suggestion, configured_cap, current_funds)
    if amount is None:
        return _bid_stop('FUND_CAP_BLOCKS_SEND', suggestion=suggestion)
    if user_confirmed is not True:
        return _bid_stop('USER_CONFIRMATION_REQUIRED', suggestion=suggestion, amount=amount)
    if not isinstance(approval_id, str) or not approval_id.strip():
        return _bid_stop('USER_CONFIRMATION_REQUIRED', suggestion=suggestion, amount=amount)

    from pathlib import Path
    from durable_bid_obligations import DurableBidIntentBook
    path = Path(ledger_path)
    if path.exists():
        book = DurableBidIntentBook(path, ledger_id=clock_id, budget=_bid_budget(
            current, approval_id, current_funds, amount, deadline_ms), clock_id=clock_id)
        state = book.recover()['state']
        if state.get('entries') or state.get('stopped'):
            return _bid_stop('RESEND_BLOCKED', suggestion=suggestion, amount=amount,
                             sent=False, resendAllowed=False)
        return _bid_stop('LEDGER_ALREADY_OPEN', suggestion=suggestion, amount=amount)

    confirmed = build_bid_intent(event, current, now_ms=now_ms, deadline_ms=deadline_ms, requested_bid=amount)
    if solver_suggestion(confirmed) != suggestion or confirmed.get('requestedBid') != amount:
        return _bid_stop('SUGGESTION_NOT_SENDABLE', suggestion=suggestion, amount=amount)
    budget = _bid_budget(current, approval_id, current_funds, amount, deadline_ms)
    book = DurableBidIntentBook.create(path, ledger_id=clock_id, budget=budget, clock_id=clock_id)
    reserved = book.reserve(confirmed, current, now_ms=now_ms)
    if reserved.get('ok') is not True:
        return _bid_stop(reserved.get('reason') or 'RESERVE_REFUSED', suggestion=suggestion, amount=amount)
    claim = book.claim(confirmed['intentId'], current, now_ms=now_ms)
    if claim.get('ok') is not True:
        return _bid_stop(claim.get('reason') or 'CLAIM_REFUSED', suggestion=suggestion, amount=amount)
    scope = dict(native_scope)
    for key in ('matchId', 'matchGeneration', 'observationSessionId', 'round', 'factsRevision'):
        if key not in scope:
            scope[key] = current.get(key)
        elif scope[key] != current.get(key):
            _freeze_unknown(book, confirmed, now_ms)
            return _bid_stop('HOST_SCOPE_MISMATCH', suggestion=suggestion, amount=amount, resendAllowed=False)
    scope['budget'] = current_funds
    try:
        domain = claimed_bid_to_domain_intent(claim, scope, now_ms=now_ms, now_ns=now_ns)
    except (TypeError, ValueError, KeyError):
        _freeze_unknown(book, confirmed, now_ms)
        return _bid_stop('HOST_INTENT_REFUSED', suggestion=suggestion, amount=amount, resendAllowed=False)
    from native_domain_action_obligations import NativeBidObligationOwner
    owner = NativeBidObligationOwner(
        book, domain, current_provider=lambda: current, native_scope_provider=lambda: scope,
        now_ms=lambda: now_ms, now_ns=lambda: now_ns, boot_id=clock_id)
    envelope = owner.dispatch_envelope('dispatch-' + confirmed['intentId'])
    attempt = _host_attempt(owner, domain)
    if attempt.get('accepted') is not True:
        return _bid_result('UNKNOWN', suggestion, amount, envelope, resendAllowed=False, scene=scene)
    outcome, evidence = _new_frame_outcome(pre_frame, next_frame, amount)
    receipt = _wire_receipt(domain, 'CONFIRMED' if outcome == 'FILLED' else 'UNKNOWN', evidence)
    ack = _host_receipt(owner, domain, receipt, qualified=outcome == 'FILLED')
    if ack.get('accepted') is not True or outcome != 'FILLED':
        stored = book.recover()['state']['entries'][domain['intentId']]['storedState']
        if stored == 'EFFECTIVE':
            return _bid_stop('RECEIPT_STATE_UNEXPECTED', suggestion=suggestion, amount=amount, sent=True)
        outcome = outcome if outcome in ('NOT_FILLED', 'UNKNOWN') else 'UNKNOWN'
    return _bid_result(outcome, suggestion, amount, envelope, resendAllowed=False,
                       evidenceRef=evidence, scene=scene)


def _bid_budget(current, approval_id, current_funds, amount, deadline_ms):
    return {'approved': True, 'approvalId': approval_id, 'binding': {
                'matchId': current.get('matchId'), 'matchGeneration': current.get('matchGeneration'),
                'observationSessionId': current.get('observationSessionId')},
            'expiresAtMs': deadline_ms, 'remaining': current_funds, 'maxBid': amount}


def _bid_stop(reason, **extra):
    extra.setdefault('sent', False)
    extra.setdefault('resendAllowed', False)
    extra.setdefault('executionEnabled', False)
    return {'ok': False, 'outcome': 'REFUSED', 'reason': reason, **extra}


def _bid_result(outcome, suggestion, amount, envelope, *, resendAllowed, evidenceRef=None, scene=None):
    return {'ok': outcome == 'FILLED', 'outcome': outcome, 'suggestion': suggestion, 'amount': amount,
            'sent': True, 'resendAllowed': resendAllowed, 'executionEnabled': False,
            'envelope': envelope, 'evidenceRef': evidenceRef, 'scene': scene}


def _freeze_unknown(book, intent, now_ms):
    wire = {'intentId': intent.get('intentId'), 'kind': 'Bid', 'status': 'UNKNOWN',
            'approvalId': None, 'amount': intent.get('requestedBid')}
    wire.update(intent.get('binding') or {})
    book.receipt(wire, qualified=False, now_ms=now_ms)


def _host_attempt(owner, domain):
    return owner.handle_request({
        'type': 'domain.action.obligation.request', 'protocolVersion': 1,
        'requestId': 'attempt-' + domain['intentId'], 'requestKind': 'attempted',
        'bootId': owner.boot_id, 'ledgerId': owner.ledger_id, 'ledgerRevision': owner.revision,
        'observationSessionId': domain['observationSessionId'],
        'intentId': domain['intentId'], 'intent': domain,
    })


def _host_receipt(owner, domain, receipt, *, qualified):
    return owner.handle_request({
        'type': 'domain.action.receipt.commit.request', 'protocolVersion': 1,
        'requestId': 'receipt-' + domain['intentId'], 'bootId': owner.boot_id,
        'ledgerId': owner.ledger_id, 'ledgerRevision': owner.revision,
        'observationSessionId': domain['observationSessionId'],
        'intentId': domain['intentId'], 'intent': domain,
        'receipt': receipt, 'independentlyQualified': qualified,
    })


def _wire_receipt(domain, status, evidence):
    receipt = {key: domain.get(key) for key in (
        'intentId', 'kind', 'matchId', 'matchGeneration', 'observationSessionId',
        'round', 'factsRevision', 'amount', 'approvalId')}
    receipt['status'] = status
    if evidence:
        receipt['evidenceRef'] = evidence
    return receipt


def _new_frame_outcome(pre_frame, next_frame, amount):
    from scene_anchors import classify_auction_flow_frame, committed_bid_amounts, frame_digest
    if next_frame is None or frame_digest(next_frame) == frame_digest(pre_frame):
        return 'UNKNOWN', None
    scene = classify_auction_flow_frame(next_frame).get('scene')
    if scene in ('IN_AUCTION', 'SETTLEMENT', 'AUCTION_LOBBY') and amount in committed_bid_amounts(next_frame):
        return 'FILLED', 'frame/' + frame_digest(next_frame)
    if scene in ('IN_AUCTION', 'SETTLEMENT', 'AUCTION_LOBBY'):
        return 'NOT_FILLED', 'frame/' + frame_digest(next_frame)
    return 'UNKNOWN', None


def commit_domain_receipt(book, receipt: dict, *, independently_qualified: bool,
                          now_ms: int, expected_revision=None) -> bool:
    """Forward exact Native wire (including approvalId/evidenceRef) to Sol-B.

    independently_qualified must come from Native receipt/source provenance,
    never from a UI status or OS send result. No second budget store is created.
    """
    expected = {"NOT_SENT": "NOT_SENT", "SENT_PENDING_CONFIRMATION": "PENDING",
                "CONFIRMED": "EFFECTIVE", "UNKNOWN": "UNKNOWN"}.get(receipt.get("status"))
    if expected is None:
        return False
    result = book.receipt(receipt, qualified=independently_qualified, now_ms=now_ms,
                          expected_revision=expected_revision)
    return result.get("ok") is True and result.get("state") == expected


def fresh_live_domain_state():
    """One authorized pass: bid, return, then the next match. Unknown is terminal."""
    return {
        "phase": "idle",
        "resendAllowed": False,
        "reason": None,
        "amount": None,
        "funds": None,
        "bidIntentId": None,
        "returnIntentId": None,
        "startIntentId": None,
    }


def live_domain_loop_public(state):
    """Field for the main window. Claude binds it; this process does not paint it.

    liveDomainLoop: {phase, reason, amount, resendAllowed}. phase is idle,
    bid_dispatched, bid_confirmed, return_dispatched, return_confirmed,
    start_dispatched, done, or stopped. amount is the capped Solver suggestion
    once a bid is prepared, otherwise null. resendAllowed stays false.
    """
    if not isinstance(state, dict):
        return None
    return {
        "phase": state.get("phase"),
        "reason": state.get("reason"),
        "amount": state.get("amount"),
        "resendAllowed": False,
    }


def advance_live_domain_loop(state, view, send):
    """Move the authorized loop by one observation. send(owner, envelope) -> bool.

    A false or missing send does not try a second envelope. UNKNOWN and NOT_SENT
    stop the loop. The bid uses the existing once-only ledger; return and the
    next match are session envelopes with amount null, focus epoch 0, and
    takeover 0. The caller supplies the host's engine scope, not a private one.
    """
    if not isinstance(state, dict) or state.get("phase") is None:
        raise ValueError("LIVE_LOOP_STATE_REQUIRED")
    if not isinstance(view, dict) or not callable(send):
        raise ValueError("LIVE_LOOP_VIEW_REQUIRED")
    if state.get("phase") in ("done", "stopped"):
        return state
    _consume_live_receipt(state, view)
    if state.get("phase") in ("done", "stopped"):
        return state
    if state.get("phase") == "idle":
        return _dispatch_live_bid(state, view, send)
    if state.get("phase") == "bid_confirmed":
        return _dispatch_live_session(state, view, send, "ReturnLobby")
    if state.get("phase") == "return_confirmed":
        return _dispatch_live_session(state, view, send, "StartNextMatch")
    return state


def _consume_live_receipt(state, view):
    phase = state.get("phase")
    if phase == "bid_dispatched":
        receipt, intent_id = view.get("bidReceipt"), state.get("bidIntentId")
    elif phase == "return_dispatched":
        receipt, intent_id = view.get("sessionReceipt"), state.get("returnIntentId")
    elif phase == "start_dispatched":
        receipt, intent_id = view.get("sessionReceipt"), state.get("startIntentId")
    else:
        return
    if not isinstance(receipt, dict) or receipt.get("intentId") != intent_id:
        return
    status = receipt.get("status")
    if status == "SENT_PENDING_CONFIRMATION":
        state["reason"] = "WAITING_VISIBLE_RESULT"
        return
    if status == "CONFIRMED":
        if phase == "bid_dispatched":
            state["phase"] = "bid_confirmed"
            state["reason"] = None
        elif phase == "return_dispatched":
            state["phase"] = "return_confirmed"
            state["reason"] = None
        else:
            new_id = receipt.get("newMatchId")
            engine = view.get("engine") or {}
            new_generation = receipt.get("newMatchGeneration")
            current_generation = engine.get("matchGeneration")
            if (isinstance(new_id, str) and new_id and new_id != engine.get("matchId")
                    and type(new_generation) is int and type(current_generation) is int
                    and new_generation > current_generation):
                state["phase"] = "done"
                state["reason"] = None
            else:
                state["phase"] = "stopped"
                state["reason"] = "NEXT_MATCH_IDENTITY_MISSING"
        state["resendAllowed"] = False
        return
    if status in ("UNKNOWN", "NOT_SENT"):
        state["phase"] = "stopped"
        state["reason"] = status
        state["resendAllowed"] = False


def _dispatch_live_bid(state, view, send):
    if view.get("foreground") is not True:
        state["reason"] = "GAME_NOT_FOREGROUND"
        return state
    if view.get("publishedScene") != "AUCTION":
        state["reason"] = "WAITING_BID_PANEL"
        return state
    if view.get("userConfirmed") is not True:
        state["reason"] = "USER_CONFIRMATION_REQUIRED"
        return state
    funds = view.get("currentFunds")
    if type(funds) is not int or isinstance(funds, bool) or funds < 0:
        state["reason"] = "FUNDS_NOT_ONE_INTEGER"
        return state
    engine = _live_engine(view)
    if engine is None:
        state["reason"] = "ENGINE_SCOPE_INCOMPLETE"
        return state
    if engine["round"] not in range(1, 6):
        state["reason"] = "BID_ROUND_UNUSABLE"
        return state
    proposal_event = view.get("proposalEvent")
    current = view.get("current")
    if not isinstance(proposal_event, dict) or not isinstance(current, dict):
        state["reason"] = "NO_SOLVER_SUGGESTION"
        return state
    from bid_intent import build_bid_intent, capped_send_amount, solver_suggestion
    now_ms, deadline_ms = view.get("nowMs"), view.get("deadlineMs")
    try:
        proposal = build_bid_intent(proposal_event, current, now_ms=now_ms, deadline_ms=deadline_ms, requested_bid=None)
    except (TypeError, ValueError):
        state["reason"] = "NO_SOLVER_SUGGESTION"
        return state
    suggestion = solver_suggestion(proposal)
    amount = None if suggestion is None else capped_send_amount(suggestion, view.get("configuredCap"), funds)
    if amount is None:
        state["reason"] = ("FUND_CAP_BLOCKS_SEND" if suggestion is not None else
                           next(iter(proposal.get("prohibitions") or []), "NO_SOLVER_SUGGESTION"))
        return state
    if proposal.get("binding") != {key: engine[key] for key in
                                   ("matchId", "matchGeneration", "observationSessionId", "round", "factsRevision")}:
        state["reason"] = "ENGINE_SCOPE_MISMATCH"
        return state
    ledger_path = view.get("ledgerPath")
    approval_id = view.get("approvalId")
    boot_id = view.get("bootId")
    if (not isinstance(ledger_path, str) or not ledger_path.strip()
            or not isinstance(approval_id, str) or not approval_id.strip()
            or not isinstance(boot_id, str) or not boot_id.strip()):
        state["reason"] = "LIVE_LOOP_IDENTITY_INCOMPLETE"
        return state
    from pathlib import Path
    path = Path(ledger_path)
    if path.exists() or path.with_name(path.name + ".owner").exists():
        state["phase"] = "stopped"
        state["reason"] = "RESEND_BLOCKED"
        state["resendAllowed"] = False
        return state
    confirmed = build_bid_intent(proposal_event, current, now_ms=now_ms, deadline_ms=deadline_ms, requested_bid=amount)
    if solver_suggestion(confirmed) != suggestion or confirmed.get("requestedBid") != amount:
        state["reason"] = "SUGGESTION_NOT_SENDABLE"
        return state
    scope = _live_native_scope(view, engine, funds)
    if scope is None:
        state["reason"] = "LIVE_LOOP_IDENTITY_INCOMPLETE"
        return state
    from durable_bid_obligations import DurableBidIntentBook
    from native_domain_action_obligations import NativeBidObligationOwner
    budget = _bid_budget(current, approval_id, funds, amount, deadline_ms)
    try:
        book = DurableBidIntentBook.create(path, ledger_id=boot_id, budget=budget, clock_id=boot_id)
        reserved = book.reserve(confirmed, current, now_ms=now_ms)
        claim = book.claim(confirmed["intentId"], current, now_ms=now_ms) if reserved.get("ok") is True else reserved
        if claim.get("ok") is not True or claim.get("state") != "CLAIMED":
            state["phase"] = "stopped"
            state["reason"] = claim.get("reason") or "CLAIM_REFUSED"
            state["resendAllowed"] = False
            return state
        domain = claimed_bid_to_domain_intent(claim, scope, now_ms=now_ms, now_ns=view["nowNs"])
        owner = NativeBidObligationOwner(
            book, domain, current_provider=lambda current=current: current,
            native_scope_provider=lambda scope=scope: scope,
            now_ms=lambda now_ms=now_ms: now_ms, now_ns=lambda now_ns=view["nowNs"]: now_ns,
            boot_id=boot_id)
        envelope = owner.dispatch_envelope("dispatch-" + domain["intentId"])
    except (OSError, TypeError, ValueError, KeyError, RuntimeError) as exc:
        state["phase"] = "stopped"
        state["reason"] = type(exc).__name__
        state["resendAllowed"] = False
        return state
    state["amount"] = amount
    state["funds"] = funds
    state["bidIntentId"] = domain["intentId"]
    if send(owner, envelope) is not True:
        state["phase"] = "stopped"
        state["reason"] = "DISPATCH_NOT_ACCEPTED"
        state["resendAllowed"] = False
        return state
    state["phase"] = "bid_dispatched"
    state["reason"] = "WAITING_VISIBLE_RESULT"
    state["resendAllowed"] = False
    return state


def _dispatch_live_session(state, view, send, kind):
    if view.get("foreground") is not True:
        state["reason"] = "GAME_NOT_FOREGROUND"
        return state
    expected = "SETTLEMENT" if kind == "ReturnLobby" else "LOBBY"
    if view.get("publishedScene") != expected:
        state["reason"] = "WAITING_" + expected
        return state
    engine = _live_engine(view)
    if engine is None:
        state["reason"] = "ENGINE_SCOPE_INCOMPLETE"
        return state
    if kind == "StartNextMatch" and engine["round"] != 0:
        state["reason"] = "LOBBY_ROUND_NOT_ZERO"
        return state
    if kind == "ReturnLobby" and engine["round"] not in range(0, 6):
        state["reason"] = "SETTLEMENT_ROUND_UNUSABLE"
        return state
    funds = state.get("funds")
    if type(funds) is not int or isinstance(funds, bool) or funds <= 0:
        state["reason"] = "FUNDS_NOT_ONE_INTEGER"
        return state
    scope = _live_native_scope(view, engine, funds)
    if scope is None or view.get("userConfirmed") is not True:
        state["reason"] = "LIVE_LOOP_IDENTITY_INCOMPLETE"
        return state
    intent_id = ("return-" if kind == "ReturnLobby" else "start-") + engine["matchId"]
    intent = {
        "intentId": intent_id,
        "kind": kind,
        "matchId": engine["matchId"],
        "round": 0 if kind == "StartNextMatch" else engine["round"],
        "factsRevision": engine["factsRevision"],
        "amount": None,
        "budget": funds,
        "deadlineNs": scope["leaseExpiresNs"],
        "takeoverGeneration": 0,
        "leaseId": scope["leaseId"],
        "window": scope["window"],
        "matchGeneration": engine["matchGeneration"],
        "observationSessionId": engine["observationSessionId"],
        "maxSafeBid": 0,
        "approvalId": view.get("approvalId"),
    }
    envelope = {
        "type": "domain.action.dispatch",
        "protocolVersion": 1,
        "requestId": "dispatch-" + intent_id,
        "bootId": view.get("bootId"),
        "observationSessionId": engine["observationSessionId"],
        "intent": intent,
    }
    if kind == "ReturnLobby":
        state["returnIntentId"] = intent_id
    else:
        state["startIntentId"] = intent_id
    if send(None, envelope) is not True:
        state["phase"] = "stopped"
        state["reason"] = "DISPATCH_NOT_ACCEPTED"
        state["resendAllowed"] = False
        return state
    state["phase"] = "return_dispatched" if kind == "ReturnLobby" else "start_dispatched"
    state["reason"] = "WAITING_VISIBLE_RESULT"
    state["resendAllowed"] = False
    return state


def _live_engine(view):
    engine = view.get("engine")
    if not isinstance(engine, dict):
        return None
    match_id = engine.get("matchId")
    session_id = engine.get("observationSessionId")
    generation = engine.get("matchGeneration")
    round_no = engine.get("round")
    revision = engine.get("factsRevision")
    if (not isinstance(match_id, str) or not match_id.strip()
            or not isinstance(session_id, str) or not session_id.strip()
            or type(generation) is not int or isinstance(generation, bool) or generation <= 0
            or type(round_no) is not int or isinstance(round_no, bool) or round_no < 0
            or type(revision) is not int or isinstance(revision, bool) or revision < 0):
        return None
    return {
        "matchId": match_id,
        "matchGeneration": generation,
        "observationSessionId": session_id,
        "round": round_no,
        "factsRevision": revision,
    }


def _live_native_scope(view, engine, funds):
    window = view.get("window")
    if not isinstance(window, dict):
        return None
    try:
        hwnd = int(window.get("hwnd"))
        pid = int(window.get("pid"))
        token = int(window.get("processInstanceToken"))
    except (TypeError, ValueError):
        return None
    lease_id = view.get("leaseId")
    now_ns = view.get("nowNs")
    deadline_ns = view.get("deadlineNs")
    boot_id = view.get("bootId")
    if (hwnd <= 0 or pid <= 0 or token <= 0
            or not isinstance(lease_id, str) or not lease_id.strip()
            or not isinstance(boot_id, str) or not boot_id.strip()
            or type(now_ns) is not int or type(deadline_ns) is not int
            or now_ns >= deadline_ns):
        return None
    return {
        **engine,
        "budget": funds,
        "clockAnchorMs": view.get("nowMs"),
        "clockAnchorNs": now_ns,
        "leaseExpiresNs": deadline_ns,
        "takeoverGeneration": 0,
        "leaseId": lease_id,
        "window": {
            "hwnd": hwnd,
            "pid": pid,
            "processInstanceToken": token,
            "focusEpoch": 0,
        },
    }
