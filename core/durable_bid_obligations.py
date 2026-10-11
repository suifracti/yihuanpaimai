"""Dedicated bid obligations, never a wallet, input backend or match History.

Explicit path + ledger identity only. Reuses project OS lock/atomic file writer.
All grants are returned AFTER fsync/replace/read-back. A recovered grant cannot
send. Caller must supply current trusted approval and a boot-clock identity.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import uuid

from bid_intent import BidIntentBook, binding, money, scope_valid
from history_file_lock import history_file_lock
from runtime_data import _atomic_write_bytes

SCHEMA = 'bid-obligations.v1'
HELD = {'RESERVED', 'CLAIMED', 'ATTEMPTED', 'PENDING', 'UNKNOWN'}
AMBIGUOUS = {'CLAIMED', 'ATTEMPTED', 'PENDING', 'UNKNOWN'}
STATES = HELD | {'EFFECTIVE', 'NOT_SENT', 'CANCELLED'}


class ObligationError(RuntimeError):
    pass


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


class DurableBidIntentBook:
    def __init__(self, path, *, ledger_id, budget=None, clock_id=None):
        self.path = Path(path).resolve()
        self.ledger_id = ledger_id
        self.budget = copy.deepcopy(budget or {})  # supplied authority, never restored authority
        self.clock_id = clock_id
        self.instance_id = uuid.uuid4().hex
        with history_file_lock(self.path):
            self._read()  # open NEVER initializes or repairs a missing/corrupt file

    @classmethod
    def create(cls, path, *, ledger_id, budget, clock_id):
        path = Path(path).resolve()
        if (not isinstance(ledger_id, str) or not ledger_id.strip()
                or not isinstance(clock_id, str) or not clock_id.strip()
                or budget.get('approved') is not True
                or not isinstance(budget.get('approvalId'), str) or not budget['approvalId'].strip()
                or not all(money(budget.get(k)) for k in ('remaining', 'maxBid', 'expiresAtMs'))
                or not all((budget.get('binding') or {}).get(k) is not None for k in
                           ('matchId', 'matchGeneration', 'observationSessionId'))):
            raise ObligationError('EXPLICIT_APPROVAL_AND_IDENTITY_REQUIRED')
        anchor = path.with_name(path.name + '.owner')
        with history_file_lock(path):
            if path.exists() or anchor.exists():
                raise ObligationError('ALREADY_EXISTS_OR_INCOMPLETE_CREATION')
            # Permanent ownership anchor: missing ledger cannot become an empty
            # budget after deletion/crash. Do not overwrite any existing file.
            with anchor.open('xb') as stream:
                stream.write(encoded({'schemaVersion': SCHEMA, 'ledgerId': ledger_id}))
                stream.flush()
                os.fsync(stream.fileno())
            terms = copy.deepcopy(budget)
            terms.pop('approved', None)
            state = {'schemaVersion': SCHEMA, 'ledgerId': ledger_id, 'clockId': clock_id,
                     'terms': terms, 'revision': 0, 'stopped': False,
                     'entries': {}, 'roundClaims': [], 'spent': 0}
            raw = encoded({'state': state, 'sha256': digest(state)})
            _atomic_write_bytes(path, raw)
            if path.read_bytes() != raw:
                raise ObligationError('WRITE_VERIFICATION_FAILED')
        return cls(path, ledger_id=ledger_id, budget=budget, clock_id=clock_id)

    def _read(self):
        try:
            anchor = json.loads(self.path.with_name(self.path.name + '.owner').read_bytes())
            envelope = json.loads(self.path.read_bytes())
            state = envelope['state']
            if (anchor != {'schemaVersion': SCHEMA, 'ledgerId': self.ledger_id}
                    or state['schemaVersion'] != SCHEMA or state['ledgerId'] != self.ledger_id
                    or envelope['sha256'] != digest(state)):
                raise ValueError('identity/checksum')
            entries = state['entries']
            if (not isinstance(entries, dict) or type(state['revision']) is not int
                    or state['revision'] < 0 or type(state['stopped']) is not bool
                    or not money(state['spent']) or not isinstance(state['roundClaims'], list)):
                raise ValueError('state')
            effective = 0
            for iid, e in entries.items():
                if (e['state'] not in STATES or iid != e['intent']['intentId']
                        or type(e['amount']) is not int or e['amount'] <= 0
                        or e['amount'] != e['intent']['requestedBid']
                        or e['approvalId'] != state['terms']['approvalId']):
                    raise ValueError('entry')
                if e['state'] == 'EFFECTIVE':
                    effective += e['amount']
            if effective != state['spent'] or effective + self._held(state) > state['terms']['remaining']:
                raise ValueError('accounting')
            return state
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ObligationError('MISSING_CORRUPT_OR_FOREIGN_LEDGER') from exc

    @staticmethod
    def _held(state):
        return sum(e['amount'] for e in state['entries'].values() if e['state'] in HELD)

    def _write(self, state):
        state['revision'] += 1
        raw = encoded({'state': state, 'sha256': digest(state)})
        _atomic_write_bytes(self.path, raw)
        if self.path.read_bytes() != raw:
            raise ObligationError('WRITE_VERIFICATION_FAILED')
        self._read()

    def _transaction(self, mutate):
        try:
            with history_file_lock(self.path):
                state = self._read()
                before = encoded(state)
                result = mutate(state)
                if encoded(state) != before:
                    self._write(state)
                return result
        except (ObligationError, OSError, TimeoutError, ValueError) as exc:
            # No volatile success is returned if commit or verification fails.
            return {'ok': False, 'reason': 'DURABLE_COMMIT_FAILED',
                    'executionEnabled': False, 'detail': type(exc).__name__}

    def recover(self, current=None):
        """Read-only view; no disk repair, promotion, active approval or replay."""
        with history_file_lock(self.path):
            state = self._read()
        view = copy.deepcopy(state)
        matching, foreign = [], []
        for iid, e in view['entries'].items():
            e['storedState'] = e['state']
            if e['state'] in AMBIGUOUS:
                e['state'] = 'UNKNOWN'
            (matching if current and e['intent']['binding'] == binding(current) else foreign).append(iid)
        return {'ok': True, 'executionEnabled': False, 'state': view,
                'matchingIntentIds': matching, 'foreignIntentIds': foreign,
                'reserved': self._held(state), 'spent': state['spent'],
                'reconciliationRequired': any(e['state'] in AMBIGUOUS for e in state['entries'].values())}

    def _memory_book(self, state):
        book = BidIntentBook(self.budget)
        book.entries = copy.deepcopy(state['entries'])
        book.spent = state['spent']
        book.round_claims = {tuple(row) for row in state['roundClaims']}
        return book

    def _approval_gate(self, state):
        terms, b = state['terms'], self.budget
        if state['stopped']:
            return 'TAKEOVER_OR_STOPPED'
        if self.clock_id != state['clockId']:
            return 'BOOT_CLOCK_CHANGED'
        if (b.get('approvalId') != terms.get('approvalId') or b.get('binding') != terms.get('binding')
                or b.get('expiresAtMs') != terms.get('expiresAtMs')
                or not all(money(b.get(k)) and b[k] <= terms[k] for k in ('remaining', 'maxBid'))):
            return 'APPROVAL_MISSING_CHANGED_OR_INCREASED'
        return None

    @staticmethod
    def _deny(reason):
        return {'ok': False, 'reason': reason, 'executionEnabled': False}

    def reserve(self, intent, current, *, now_ms):
        def mutate(state):
            reason = self._approval_gate(state)
            if reason:
                return self._deny(reason)
            if any(e['state'] in AMBIGUOUS for e in state['entries'].values()):
                return self._deny('UNRESOLVED_OBLIGATION')
            result = self._memory_book(state).reserve(intent, current, now_ms=now_ms)
            if result['ok']:
                state['entries'][intent['intentId']] = {'intent': copy.deepcopy(intent),
                    'amount': intent['requestedBid'], 'state': 'RESERVED',
                    'approvalId': state['terms']['approvalId'], 'instanceId': self.instance_id}
            return result
        return self._transaction(mutate)

    def claim(self, intent_id, current, *, now_ms):
        def mutate(state):
            reason = self._approval_gate(state)
            e = state['entries'].get(intent_id)
            if reason or not e or e['instanceId'] != self.instance_id:
                return self._deny(reason or 'RECOVERED_RESERVATION_REQUIRES_RECONCILIATION')
            if any(v['state'] in AMBIGUOUS for v in state['entries'].values()):
                return self._deny('UNRESOLVED_OBLIGATION')
            book = self._memory_book(state)
            result = book.claim(intent_id, current, now_ms=now_ms)
            state['entries'][intent_id]['state'] = book.entries[intent_id]['state']
            state['roundClaims'] = [list(row) for row in sorted(book.round_claims)]
            # This is not a send permit. Sol-C may build its domain intent, but
            # first primitive requires successful durable attempted() below.
            result['executionEnabled'] = False
            result['commitBeforeSendRequired'] = bool(result['ok'])
            return result
        return self._transaction(mutate)

    def attempted(self, intent_id, current, *, now_ms, expected_revision=None):
        """Commit once immediately BEFORE first primitive. No retry token."""
        def mutate(state):
            if expected_revision is not None and state['revision'] != expected_revision:
                return self._deny('LEDGER_REVISION_MISMATCH')
            e = state['entries'].get(intent_id)
            if not e or e['state'] != 'CLAIMED' or e['instanceId'] != self.instance_id:
                return self._deny('ALREADY_ATTEMPTED_OR_RECOVERED')
            reason = self._approval_gate(state) or self._memory_book(state)._gate(e['intent'], current, now_ms)
            if not reason and (e['amount'] > self.budget['maxBid']
                               or state['spent'] + self._held(state) > self.budget['remaining']):
                reason = 'BUDGET_CHANGED_OR_EXCEEDED'
            if reason:
                e['state'] = 'UNKNOWN'
                return self._deny(reason)
            e['state'] = 'ATTEMPTED'
            # Existing Sol-C converter consumes a CLAIMED envelope. The durable
            # state is already ATTEMPTED; this compatible envelope is single use.
            return {'ok': True, 'state': 'CLAIMED', 'durableState': 'ATTEMPTED', 'executionEnabled': True,
                    'amount': e['amount'], 'approvalId': e['approvalId'],
                    'intent': copy.deepcopy(e['intent']), 'ledgerId': self.ledger_id,
                    'budget': {'approved': True, 'approvalId': e['approvalId'],
                               'remaining': self.budget['remaining'] - state['spent'],
                               'reserved': self._held(state),
                               'available': self.budget['remaining'] - state['spent'] - self._held(state)}}
        return self._transaction(mutate)

    def receipt(self, receipt, *, qualified=False, now_ms=None, expected_revision=None):
        """Sol-C four-state wire receipt. qualified is independent evidence gate.

        Missing/mismatched binding never settles money. UNKNOWN stays frozen;
        only correctly attributed, qualified CONFIRMED can reconcile it.
        """
        def mutate(state):
            if expected_revision is not None and state['revision'] != expected_revision:
                return self._deny('LEDGER_REVISION_MISMATCH')
            e = state['entries'].get(receipt.get('intentId'))
            if (not e or not scope_valid(receipt) or receipt.get('kind') != 'Bid'
                    or receipt.get('approvalId') != e['approvalId']
                    or type(receipt.get('amount')) is not int or receipt['amount'] != e['amount']
                    or binding(receipt) != e['intent']['binding']):
                return self._deny('RECEIPT_BINDING_MISMATCH')
            incoming = receipt.get('status')
            mapped = {'CONFIRMED': 'EFFECTIVE', 'NOT_SENT': 'NOT_SENT',
                      'SENT_PENDING_CONFIRMATION': 'PENDING', 'UNKNOWN': 'UNKNOWN'}.get(incoming)
            if mapped is None:
                return self._deny('INVALID_RECEIPT')
            if e['state'] == mapped:
                return {'ok': True, 'state': mapped, 'duplicate': True, 'executionEnabled': False}
            if e['state'] in {'EFFECTIVE', 'NOT_SENT', 'CANCELLED', 'RESERVED'}:
                return self._deny('CONFLICTING_OR_UNCLAIMED_RECEIPT')
            if mapped == 'EFFECTIVE':
                if (e['state'] == 'CLAIMED' or qualified is not True
                        or self._approval_gate(state) or self.budget.get('approved') is not True
                        or not money(now_ms) or now_ms >= self.budget['expiresAtMs']
                        or not isinstance(receipt.get('evidenceRef'), str) or not receipt['evidenceRef'].strip()):
                    return self._deny('VISIBLE_CONFIRMATION_REQUIRED')
                e['state'] = mapped
                e['evidenceRef'] = receipt['evidenceRef']
                state['spent'] += e['amount']
            elif mapped == 'NOT_SENT' and e['state'] == 'CLAIMED' and qualified is True:
                e['state'] = mapped  # proven no first primitive; claim remains burned
            elif mapped == 'PENDING' and e['state'] == 'ATTEMPTED':
                e['state'] = mapped
            else:
                e['state'] = 'UNKNOWN'  # no pending->NOT_SENT or UNKNOWN unfreeze
            return {'ok': True, 'state': e['state'], 'executionEnabled': False,
                    'reserved': self._held(state), 'spent': state['spent']}
        return self._transaction(mutate)

    def _stop(self, reason):
        def mutate(state):
            state['stopped'] = True
            state['stopReason'] = reason
            for e in state['entries'].values():
                if e['state'] == 'RESERVED':
                    e['state'] = 'CANCELLED'
                elif e['state'] in AMBIGUOUS:
                    e['state'] = 'UNKNOWN'
            return {'ok': True, 'executionEnabled': False, 'reserved': self._held(state)}
        return self._transaction(mutate)

    def takeover(self):
        return self._stop('MANUAL_TAKEOVER')

    def revoke_approval(self):
        """Persist withdrawal; an old approved object cannot reactivate it."""
        return self._stop('APPROVAL_REVOKED')
