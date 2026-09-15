"""Per-match public card content ledger, independent of field values and costs."""
from copy import deepcopy
import hashlib
import re
from intel_card_source import card_source


def public_card_key(text):
    if card_source(text)['kind'] != 'AUCTIONEER_PUBLIC':
        return None
    return 'public-card:' + hashlib.sha256(re.sub(r'\s+', '', text).encode('utf-8')).hexdigest()


def verified_public_event(event):
    if not isinstance(event, dict) or event.get('status') != 'CONFIRMED_CONTENT':
        return False
    key = public_card_key(event.get('rawText'))
    sources = event.get('sources')
    round_no = event.get('roundObserved')
    if not key or event.get('id') != key or type(round_no) is not int or not 1 <= round_no <= 5 or not isinstance(sources, list) or len(sources) != 2:
        return False
    if event.get('sourceKind') not in (None, 'AUCTIONEER_PUBLIC'):
        return False
    if event.get('costClassification') not in (None, 'UNKNOWN'):
        return False
    if event.get('incrementalCost') is not None:
        return False
    frames = set()
    for source in sources:
        if not isinstance(source, dict) or source.get('is_physical_ocr') is not True or type(source.get('round')) is not int or source['round'] != round_no or public_card_key(source.get('rawText')) != key:
            return False
        frame = source.get('frameId')
        if not isinstance(frame, str) or not frame:
            return False
        frames.add(frame)
    return len(frames) == 2


def public_event_identity(event):
    if not isinstance(event, dict):
        return None
    event_id = event.get('id')
    round_no = event.get('roundObserved')
    if not event_id or type(round_no) is not int:
        return None
    return (event_id, round_no)


def canonical_public_event(event):
    """Reconstruct a verified public card event into its canonical form.

    Enforces immutable business semantics:
      sourceKind = 'AUCTIONEER_PUBLIC'
      costClassification = 'UNKNOWN'
      incrementalCost = None
    Drops any extraneous or caller-injected keys.
    """
    key = public_card_key(event.get('rawText'))
    round_no = event.get('roundObserved')
    return {
        'id': key,
        'status': 'CONFIRMED_CONTENT',
        'roundObserved': round_no,
        'rawText': event['rawText'],
        'sourceKind': 'AUCTIONEER_PUBLIC',
        'costClassification': 'UNKNOWN',
        'incrementalCost': None,
        'sources': deepcopy(event['sources']),
    }


def admit_public_card_events(events, existing=None):
    """Filter and idempotently admit only verified public intel events.

    Deduplicates based on (event['id'], event['roundObserved']). Preserves
    existing confirmed events while adding new verified distinct events.
    Reconstructs admitted events as canonical objects to prevent caller tampering.
    Non-verified, single-frame, cached, or conflicting candidates are dropped.
    """
    result = []
    seen = set()
    for item in (existing or []):
        if verified_public_event(item):
            ident = public_event_identity(item)
            if ident and ident not in seen:
                seen.add(ident)
                result.append(canonical_public_event(item))
    if isinstance(events, (list, tuple)):
        for item in events:
            if verified_public_event(item):
                ident = public_event_identity(item)
                if ident and ident not in seen:
                    seen.add(ident)
                    result.append(canonical_public_event(item))
    return result


class PublicIntelLedger:
    def __init__(self):
        self.confirmed = {}
        self.pending = {}

    def update(self, readings):
        seen = set()
        for reading in readings:
            if not isinstance(reading, dict):
                continue
            key = public_card_key(reading.get('rawText'))
            frame = reading.get('frameId')
            round_no = reading.get('round')
            if not key or not isinstance(frame, str) or not frame or type(round_no) is not int or not 1 <= round_no <= 5:
                continue
            seen.add(key)
            if key in self.confirmed or reading.get('is_physical_ocr') is not True:
                continue
            prior = self.pending.get(key)
            if prior and prior['round'] == round_no and prior['frameId'] != frame:
                self.confirmed[key] = {
                    'id': key, 'status': 'CONFIRMED_CONTENT', 'roundObserved': round_no,
                    'rawText': reading['rawText'], 'sourceKind': 'AUCTIONEER_PUBLIC',
                    'costClassification': 'UNKNOWN', 'incrementalCost': None,
                    'sources': [deepcopy(prior), deepcopy(reading)],
                }
                self.pending.pop(key, None)
            else:
                self.pending[key] = deepcopy(reading)
        # Absence interrupts a tentative confirmation. Confirmed content persists.
        self.pending = {key: value for key, value in self.pending.items() if key in seen}

    def pending_keys(self):
        return set(self.pending)

    def snapshot(self):
        return deepcopy(list(self.confirmed.values()))
