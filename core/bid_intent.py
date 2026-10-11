"""Offline decision boundary for live_shadow prediction-listener events.

No input APIs or history writes. Times are caller-supplied monotonic milliseconds.
Luna-B supplies admitted live scope; Sol-C must claim immediately before dispatch,
persist reservations/unknown outcomes across restart, and never resend UNKNOWN.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import threading


def money(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 <= value <= 2**53 - 1)


def binding(value):
    return {key: value.get(key) for key in
            ('matchId', 'matchGeneration', 'observationSessionId', 'round', 'factsRevision')}


def scope_valid(value):
    return (all(isinstance(value.get(k), str) and value[k].strip()
                for k in ('matchId', 'observationSessionId'))
            and all(type(value.get(k)) is int and value[k] >= (0 if k == 'factsRevision' else 1)
                    for k in ('matchGeneration', 'round', 'factsRevision')))


def admitted(current):
    return (scope_valid(current) and current.get('scene') == 'IN_AUCTION'
            and current.get('decisionEligible') is True
            and current.get('sourceQualified') is True)


def intent_id(intent):
    identity = {k: intent[k] for k in ('binding', 'source', 'maxSafeBid', 'requestedBid', 'deadlineMs', 'valuationBasis', 'costs')}
    return 'bid_' + hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_bid_intent(event, current, *, now_ms, deadline_ms, requested_bid=None):
    """Consume existing snapshot, never re-solve or use settlement answers.

    Conservative policy: feasible minimum or whole-inventory P20, less all
    costs and existing targetProfit. Full-shadow targetLine additionally caps it.
    A READY result is an offline proposal, never permission to send input.
    """
    scope = binding(event)
    result = {'schemaVersion': 'bid-intent.v1', 'binding': scope, 'status': 'SKIP',
              'executionEnabled': False, 'maxSafeBid': None, 'requestedBid': requested_bid,
              'deadlineMs': deadline_ms, 'prohibitions': [], 'source': {},
              'budget': {'approved': False, 'remaining': None, 'reserved': None, 'available': None},
              'valuationBasis': None, 'explanation': ''}

    def reject(reason, status='SKIP'):
        result.update(status=status, prohibitions=[reason], explanation=reason)
        return result

    if not admitted(current):
        return reject('OBSERVATION_NOT_ELIGIBLE')
    if not scope_valid(event) or scope != binding(current):
        return reject('STALE_SCOPE')
    if event.get('scene') != 'IN_AUCTION':
        return reject('NOT_PRE_SETTLEMENT')
    if not money(now_ms) or not money(deadline_ms) or now_ms >= deadline_ms:
        return reject('DEADLINE_EXPIRED')
    snap = event.get('predictionSnapshot') or {}
    facts = (snap.get('input') or {}).get('normalizedFacts') or {}
    status = snap.get('status') or {}
    if (snap.get('schemaVersion') != 'prediction-snapshot.v1'
            or snap.get('snapshotRole') != 'latest_valid_pre_settlement'
            or snap.get('matchId') != scope['matchId'] or facts.get('round') != scope['round']):
        return reject('SNAPSHOT_BINDING_INVALID')
    if (status.get('solverStatus') != 'valid' or status.get('diagnosticOnly') is not False
            or status.get('provisional') is not False):
        return reject('SOLVER_NOT_VALID')
    result['source'] = {'predictionId': snap.get('predictionId'),
                        'inputHash': (snap.get('input') or {}).get('inputHash'),
                        'producer': copy.deepcopy(snap.get('producer')),
                        'informationCutoffAt': snap.get('informationCutoffAt')}
    if not result['source']['predictionId'] or not result['source']['inputHash']:
        return reject('SOURCE_ID_MISSING', 'UNKNOWN')
    if not money(facts.get('q')) or facts['q'] <= 0 or not money(facts.get('goldAvg')) or facts['goldAvg'] <= 0:
        return reject('MISSING_QUANTITY_OR_AVERAGE', 'UNKNOWN')
    costs = facts.get('costs') or {}
    sunk, total, target = costs.get('sunkCost'), costs.get('total'), facts.get('targetProfit')
    # Existing snapshot publishes total + sunk; its serializer currently omits
    # futureIncrementalCost. Recover the difference, never assume zero.
    future = total - sunk if money(total) and money(sunk) and total >= sunk else None
    if not all(money(v) for v in (sunk, future, target)):
        return reject('COST_OR_POLICY_UNKNOWN', 'UNKNOWN')
    forecast = snap.get('forecast') or {}
    mode = (snap.get('mode') or {}).get('informationMode')
    if mode == 'structural_only' and forecast.get('scope') == 'structural_inventory':
        bounds = (forecast.get('structural') or {}).get('feasibleRange')
        if not isinstance(bounds, list) or len(bounds) != 2 or not all(money(v) for v in bounds) or bounds[0] > bounds[1]:
            return reject('STRUCTURAL_BOUNDS_UNKNOWN', 'UNKNOWN')
        base, basis = bounds[0], 'FEASIBLE_LOWER_BOUND_NOT_P50'
    elif mode == 'full_shadow' and forecast.get('scope') == 'full_inventory':
        if (snap.get('mode') or {}).get('coverageRatio') != 1:
            return reject('FULL_SHADOW_COVERAGE_UNPROVEN', 'UNKNOWN')
        quantiles = forecast.get('quantiles') or {}
        values = [quantiles.get(k) for k in ('p20', 'p50', 'p80')]
        if not all(money(v) for v in values) or values != sorted(values):
            return reject('QUANTILES_UNKNOWN', 'UNKNOWN')
        base, basis = values[0], 'WHOLE_INVENTORY_P20'
    else:
        return reject('FULL_VALUE_UNAVAILABLE', 'UNKNOWN')
    cap = math.floor(base - sunk - future - target)
    if mode == 'full_shadow':
        line = ((event.get('frozenPrediction') or {}).get('decision') or {}).get('targetLine')
        if not money(line):
            return reject('RISK_POLICY_LINE_UNKNOWN', 'UNKNOWN')
        cap = min(cap, math.floor(line))
    result.update(maxSafeBid=max(0, cap), valuationBasis=basis,
                  costs={'sunk': sunk, 'future': future, 'targetProfit': target})
    if cap <= 0:
        return reject('NO_POSITIVE_SAFE_BID')
    if requested_bid is not None and (not money(requested_bid) or type(requested_bid) is not int or not 0 < requested_bid <= cap):
        return reject('BID_EXCEEDS_SAFE_CAP')
    result.update(status='READY', prohibitions=['BUDGET_APPROVAL_REQUIRED'],
                  explanation=f'{basis}: {base} - costs {sunk + future} - target {target}; cap {cap}. '
                              'Bounds/distributions remain model dependent; not a profit guarantee.')
    result['intentId'] = intent_id(result)
    return result


class BidIntentBook:
    """One approval book, locked reservations and one dispatch claim per round.

    budget: approved=True, approvalId, binding (match + session + generation),
    expiresAtMs, remaining, maxBid. Caller approval is trusted user-approval
    authority, not a flag inferred from Solver or a UI text field. Persist this
    book in execution owner before enabling real dispatch; this class sends none.
    """
    def __init__(self, budget=None):
        self.budget = copy.deepcopy(budget or {})
        self.entries = {}
        self.spent = 0
        self.round_claims = set()
        self.lock = threading.RLock()

    def _gate(self, intent, current, now_ms):
        b = self.budget
        if not admitted(current) or intent.get('binding') != binding(current):
            return 'STALE_OR_INELIGIBLE'
        if not money(now_ms) or not money(intent.get('deadlineMs')) or now_ms >= intent['deadlineMs']:
            return 'DEADLINE_EXPIRED'
        if b.get('approved') is not True or not isinstance(b.get('approvalId'), str) or not b['approvalId'].strip():
            return 'BUDGET_NOT_APPROVED'
        if any((b.get('binding') or {}).get(k) != current.get(k) for k in ('matchId', 'matchGeneration', 'observationSessionId')):
            return 'BUDGET_SCOPE_MISMATCH'
        if not money(b.get('expiresAtMs')) or now_ms >= b['expiresAtMs']:
            return 'BUDGET_EXPIRED'
        if not all(money(b.get(k)) for k in ('remaining', 'maxBid')):
            return 'BUDGET_UNKNOWN'
        return None

    def _reserved(self):
        return sum(e['amount'] for e in self.entries.values() if e['state'] in ('RESERVED', 'CLAIMED', 'UNKNOWN'))

    def reserve(self, intent, current, *, now_ms):
        with self.lock:
            reason = self._gate(intent, current, now_ms)
            amount, iid = intent.get('requestedBid'), intent.get('intentId')
            if reason:
                return {'ok': False, 'reason': reason, 'executionEnabled': False}
            if intent.get('status') != 'READY' or not iid or type(amount) is not int or not money(amount) or amount <= 0 or not money(intent.get('maxSafeBid')) or amount > intent['maxSafeBid']:
                return {'ok': False, 'reason': 'INVALID_INTENT', 'executionEnabled': False}
            try:
                intact = iid == intent_id(intent)
            except (KeyError, TypeError, ValueError):
                intact = False
            if not intact:
                return {'ok': False, 'reason': 'INTENT_MODIFIED', 'executionEnabled': False}
            if iid in self.entries:
                return {'ok': False, 'reason': 'DUPLICATE_INTENT', 'executionEnabled': False}
            remaining = self.budget['remaining'] - self.spent - self._reserved()
            if amount > min(remaining, self.budget['maxBid']):
                return {'ok': False, 'reason': 'BUDGET_EXCEEDED', 'executionEnabled': False}
            self.entries[iid] = {'intent': copy.deepcopy(intent), 'amount': amount, 'state': 'RESERVED'}
            return {'ok': True, 'state': 'RESERVED', 'reserved': self._reserved(),
                    'remaining': self.budget['remaining'] - self.spent - self._reserved(),
                    'budget': self._budget_view(), 'executionEnabled': False}

    def _budget_view(self):
        return {'approved': self.budget.get('approved') is True,
                'approvalId': self.budget.get('approvalId'),
                'remaining': self.budget['remaining'] - self.spent,
                'reserved': self._reserved(),
                'available': self.budget['remaining'] - self.spent - self._reserved()}

    def claim(self, intent_id, current, *, now_ms):
        with self.lock:
            e = self.entries.get(intent_id)
            if not e or e['state'] != 'RESERVED':
                return {'ok': False, 'reason': 'ALREADY_CLAIMED_OR_UNKNOWN', 'executionEnabled': False}
            reason = self._gate(e['intent'], current, now_ms)
            if not reason and (e['amount'] > self.budget['maxBid'] or self.spent + self._reserved() > self.budget['remaining']):
                reason = 'BUDGET_CHANGED_OR_EXCEEDED'
            round_key = tuple(e['intent']['binding'][k] for k in ('matchId', 'matchGeneration', 'observationSessionId', 'round'))
            if reason or round_key in self.round_claims:
                e['state'] = 'CANCELLED'
                return {'ok': False, 'reason': reason or 'ROUND_ALREADY_CLAIMED', 'executionEnabled': False}
            self.round_claims.add(round_key)
            e['state'] = 'CLAIMED'
            return {'ok': True, 'state': 'CLAIMED', 'executionEnabled': True,
                    'amount': e['amount'], 'approvalId': self.budget['approvalId'],
                    'budget': self._budget_view(), 'intent': copy.deepcopy(e['intent'])}

    def confirm(self, intent_id, outcome):
        """Execution owner reports visible receipt: EFFECTIVE/NOT_SENT/UNKNOWN.

        Unknown keeps full reservation; even NOT_SENT never permits this round
        to dispatch again. Duplicate identical receipts are idempotent.
        """
        with self.lock:
            e = self.entries.get(intent_id)
            if not e or outcome not in ('EFFECTIVE', 'NOT_SENT', 'UNKNOWN'):
                return {'ok': False, 'reason': 'INVALID_RECEIPT'}
            if e['state'] == outcome:
                return {'ok': True, 'state': outcome, 'duplicate': True}
            if e['state'] not in ('CLAIMED', 'UNKNOWN'):
                return {'ok': False, 'reason': 'CONFLICTING_OR_UNCLAIMED_RECEIPT'}
            e['state'] = outcome
            if outcome == 'EFFECTIVE':
                self.spent += e['amount']
            return {'ok': True, 'state': outcome, 'reserved': self._reserved(),
                    'remaining': self.budget['remaining'] - self.spent - self._reserved()}
