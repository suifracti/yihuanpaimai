"""Reuse witnessed identities only after same-viewport pixel registration.

Earlier reveal frames are evidence, not final bills. Each promoted item retains
its persisted original, and failures to persist leave the item unresolved.
"""
import copy
from datetime import datetime

import cv2
import numpy as np

from selection_occlusion import selection_occlusion


def _rect(item):
    return tuple(int(item[k]) for k in ('row', 'col', 'widthCells', 'heightCells'))


def _roi(frame, item):
    x, y, w, h = map(int, item['bbox'])
    if min(x, y) < 0 or min(w, h) <= 0 or x+w > frame.shape[1] or y+h > frame.shape[0]:
        return None
    return cv2.resize(frame[y:y+h, x:x+w], (item['widthCells'] * 56, item['heightCells'] * 56))


def registered_pixels(source, current):
    if source is None or current is None or source.shape != current.shape:
        return None
    source_mask, _ = selection_occlusion(source)
    current_mask, _ = selection_occlusion(current)
    valid = (source_mask == 0) & (current_mask == 0)
    valid[:4] = valid[-4:] = False
    valid[:, :4] = valid[:, -4:] = False
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    edges = np.hypot(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1)) > 25
    edges = cv2.dilate(edges.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    visible = edges & valid
    fraction = float(visible.sum() / max(1, edges.sum()))
    if visible.sum() < max(64, gray.size * .01) or fraction < .3:
        return None
    a, b = source[visible].astype(np.float32).ravel(), current[visible].astype(np.float32).ravel()
    error = float(np.mean(np.abs(a - b)))
    a, b = a-a.mean(), b-b.mean()
    correlation = float(np.dot(a, b) / max(1e-8, float(np.linalg.norm(a)*np.linalg.norm(b))))
    if correlation < .99 or error > 4:
        return None
    return {'correlation': round(correlation, 5), 'pixelError': round(error, 4),
            'visibleEdgeFraction': round(fraction, 4), 'visiblePixels': int(visible.sum())}


class SettlementIdentityMemory:
    def __init__(self):
        self.key = None
        self.observations = []

    def observe(self, *, key, ledger, frame, captured_at):
        if key != self.key:
            self.key, self.observations = key, []
        if frame is None or not captured_at:
            return
        try:
            datetime.fromisoformat(captured_at)
        except (ValueError, TypeError):
            return
        exact = [copy.deepcopy(i) for i in ledger.get('settlementItems', [])
                 if i.get('status') == 'exact' and i.get('exactItemId')
                 and not i.get('groupingAmbiguous') and not i.get('identityObservation')]
        if len(exact) < 2:
            return
        signature = tuple(sorted((_rect(i), i['exactItemId']) for i in exact))
        if any(o['signature'] == signature for o in self.observations):
            return
        self.observations.append({'signature': signature, 'items': exact,
                                  'frame': frame.copy(), 'capturedAt': captured_at})
        self.observations = self.observations[-16:]

    def fuse(self, *, key, ledger, frame, captured_at, persist):
        if key != self.key or frame is None or not captured_at:
            return ledger
        result = copy.deepcopy(ledger)
        current = {_rect(i): i for i in result.get('settlementItems', []) if not i.get('groupingAmbiguous')}
        descriptors = []
        for observation in self.observations:
            try:
                age = (datetime.fromisoformat(captured_at)-datetime.fromisoformat(observation['capturedAt'])).total_seconds()
            except (ValueError, TypeError):
                continue
            if not 0 < age <= 120:
                continue
            matches, conflict = [], False
            for previous in observation['items']:
                item = current.get(_rect(previous))
                if item is None or item.get('rarity') != previous.get('rarity'):
                    continue
                if item.get('status') == 'exact' and item.get('exactItemId') != previous['exactItemId']:
                    conflict = True
                    break
                evidence = registered_pixels(_roi(observation['frame'], previous), _roi(frame, item))
                if evidence:
                    matches.append((item, previous, evidence))
            # Two nonoverlapping cards and at least four cells must jointly
            # register. Position/rarity alone never carries an identity forward.
            if conflict or len(matches) < 2 or sum(_rect(i)[2]*_rect(i)[3] for i, _, _ in matches) < 4:
                continue
            missing = [(i, p, e) for i, p, e in matches if i.get('status') != 'exact']
            if not missing:
                continue
            descriptor = observation.get('descriptor')
            if descriptor is None:
                try:
                    descriptor = persist(observation['frame'], observation['capturedAt'])
                except Exception:
                    descriptor = None
                if not descriptor or not descriptor.get('sha256') or not descriptor.get('evidenceId'):
                    continue
                observation['descriptor'] = copy.deepcopy(descriptor)
            descriptors.append(copy.deepcopy(descriptor))
            for item, previous, evidence in missing:
                for field in ('name', 'price', 'exactItemId', 'status', 'identificationStatus',
                              'confidence', 'candidateItemIds', 'candidatePrices',
                              'identityEvidence'):
                    item[field] = copy.deepcopy(previous.get(field))
                item['identityObservation'] = {'parentEvidenceId': descriptor['evidenceId'],
                    'parentSha256': descriptor['sha256'], 'capturedAt': observation['capturedAt'],
                    'sourceBbox': previous['bbox'], 'registration': evidence,
                    'registeredAnchorCount': len(matches)}
        if not descriptors:
            return ledger
        exact = [i for i in result['settlementItems'] if i.get('status') == 'exact']
        result['settlementExactItemCount'] = len(exact)
        result['settlementUnknownItemCount'] = len(result['settlementItems']) - len(exact)
        result['settlementExactValueSum'] = sum(i['price'] for i in exact)
        # Bill equality is only a final check, never a source of identity.
        old_sum, old_delta = ledger.get('settlementExactValueSum'), ledger.get('settlementLedgerDelta')
        total = old_sum-old_delta if old_sum is not None and old_delta is not None else None
        result['settlementLedgerDelta'] = result['settlementExactValueSum']-total if total is not None else None
        verified = bool(exact) and result['settlementUnknownItemCount'] == 0 and total == result['settlementExactValueSum']
        result['settlementLedgerVerified'] = verified
        result['settlementLedgerStatus'] = 'verified' if verified else 'partial'
        result['settlementIdentityFileOriginals'] = list({d['evidenceId']: d for d in descriptors}.values())
        return result
