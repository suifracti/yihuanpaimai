"""Conservative content gate for automatic Delivery-mode scrolling.

Stationary geometry is not revealed/stable content. Neutral bright outlines
with dark, nearly featureless interiors are unresolved evidence, not item IDs
or empty slots. Ambiguous appearances fail closed; this is not a reveal oracle.
"""
import hashlib

import cv2
import numpy as np


def content_observation(crop):
    if (crop is None or crop.ndim != 3 or crop.shape[2] != 3
            or crop.size == 0):
        return {'qualified': False, 'reason': 'CONTENT_GEOMETRY_UNPROVEN'}
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    neutral_edges = ((hsv[:, :, 1] < 55) & (hsv[:, :, 2] > 140)).astype(np.uint8) * 255
    contours, _ = cv2.findContours(neutral_edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    scale = crop.shape[1] / 600.0  # existing 1920px warehouse search ROI width
    minimum = max(8, round(32 * scale))
    inset = max(2, round(6 * scale))
    unresolved = set()
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (min(w, h) < minimum or w > crop.shape[1] * .97
                or h > crop.shape[0] * .97 or cv2.contourArea(contour) / (w * h) < .85
                or min(w, h) <= 2 * inset):
            continue
        interior = crop[y + inset:y + h - inset, x + inset:x + w - inset]
        gray = cv2.cvtColor(interior, cv2.COLOR_BGR2GRAY)
        if float(gray.mean()) < 70 and float(gray.std()) < 16 and float((gray < 70).mean()) >= .98:
            unresolved.add((x, y, w, h))
    boxes = sorted(unresolved)
    return {'qualified': not boxes,
            'completionState': 'UNKNOWN',
            'reason': 'CONTENT_UNREVEALED_OR_UNKNOWN' if boxes else 'NO_UNRESOLVED_OUTLINE_DETECTED',
            'unresolvedRegionCount': len(boxes), 'unresolvedBoxes': [list(b) for b in boxes[:64]],
            'contentSha256': hashlib.sha256(crop.tobytes()).hexdigest(),
            'meaning': 'no positive identity/count/empty-slot claim; absence of this signal does not prove rendering complete'}


def content_stability(previous, current):
    a, b = content_observation(previous), content_observation(current)
    if not a['qualified'] or not b['qualified']:
        return {'qualified': False, 'reason': a['reason'] if not a['qualified'] else b['reason'],
                'previous': a, 'current': b}
    if previous.shape != current.shape:
        return {'qualified': False, 'reason': 'CONTENT_GEOMETRY_UNPROVEN', 'previous': a, 'current': b}
    # Two adjacent 8-bit rounded codes have touching quantization intervals.
    # This is a visible-support resolution contract, not a GPU/render model.
    # No averaging, fitted phase, ignored pixels, or area budget: ANY channel
    # differing by two codes vetoes support, including dark/badge/clipped pixels.
    if previous.dtype != np.uint8 or current.dtype != np.uint8:
        return {'qualified': False, 'reason': 'CONTENT_FORMAT_UNPROVEN'}
    delta = np.abs(previous.astype(np.int16) - current.astype(np.int16))
    supported = not np.any(delta > 1)
    return {'qualified': supported, 'reason': 'VISIBLE_QUANTIZATION_SUPPORT' if supported else 'CONTENT_CHANGING',
            'schema': 'visible-content-support.v1', 'maxChannelDelta': int(delta.max()),
            'beyondQuantizationPixels': int(np.any(delta > 1, axis=2).sum()),
            'changedPixels': int(np.any(previous != current, axis=2).sum()), 'previous': a, 'current': b,
            'completionState': 'UNKNOWN', 'formalFactsQualified': False,
            'meaning': 'visible content support at 8-bit adjacent-code resolution; not identity/count/reveal completion; independent source/viewport/scene gates required'}
