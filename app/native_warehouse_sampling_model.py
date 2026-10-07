"""Offline-only, finite common sampling hypothesis. No capture or corrected evidence.

The contract here is deliberately narrower than 'GPU noise': one bilinear
resampling of an integer BGR image, phase in [-1/2, 1/2] on a 1/32 lattice,
round-to-nearest/ties-even integer output. It is a known fixture renderer contract, NOT an
established WGC/game renderer contract. All residuals, including one level in
one channel, reject support. The live entry does not enable this hypothesis.
"""
from dataclasses import dataclass
import hashlib

import cv2
import numpy as np

from native_warehouse_content_stability import content_observation
from warehouse_vision import WarehouseVisionV1, WarehouseVisionConfig


class _GeometryOnly(WarehouseVisionV1):
    def __init__(self):
        # Read-only measurement; no matcher/catalog/tracking/identity lifecycle.
        self.config = WarehouseVisionConfig()


@dataclass(frozen=True)
class ContentLayout:
    protected: tuple
    references: tuple  # at least three separated fit regions and one holdout
    provenance: str

    def validate(self, shape):
        h, w = shape[:2]
        boxes = (self.protected, *self.references)
        if len(self.references) < 4 or not self.provenance:
            raise ValueError('REFERENCE_CONTRACT_UNPROVEN')
        for box in boxes:
            if (len(box) != 4 or any(type(v) is not int for v in box)
                    or not (1 <= box[0] < box[2] < w-1 and 1 <= box[1] < box[3] < h-1)):
                raise ValueError('FULL_PROTECTION_GEOMETRY_UNPROVEN')
        for i, a in enumerate(boxes):
            for b in boxes[i+1:]:
                if min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]):
                    raise ValueError('REFERENCE_NOT_INDEPENDENT')


def _crop(image, box):
    x, y, r, b = box
    return image[y:b, x:r]


def _predicted(image, box, dx, dy):
    # Integer weights, no tolerance, no smoothing/quantization of the source.
    # Only a temporary predicted array; it is never a replacement original.
    x, y, r, b = box
    sx, sy = (-1 if dx < 0 else 1), (-1 if dy < 0 else 1)
    ax, ay = abs(dx), abs(dy)
    a = image[y:b, x:r].astype(np.int32)
    bx = image[y:b, x+sx:r+sx].astype(np.int32)
    by = image[y+sy:b+sy, x:r].astype(np.int32)
    xy = image[y+sy:b+sy, x+sx:r+sx].astype(np.int32)
    total = a*(32-ax)*(32-ay) + bx*ax*(32-ay) + by*(32-ax)*ay + xy*ax*ay
    quotient, remainder = total//1024, total%1024
    return (quotient + ((remainder > 512) | ((remainder == 512) & ((quotient & 1) == 1)))).astype(np.uint8)


def _structure(image):
    # Contrast contours supplement exact per-channel model validation. This
    # threshold defines a high-contrast diagnostic, NOT a low-contrast escape.
    # Every low-contrast pixel is still checked by the exact model below.
    a = image.astype(np.int16)
    edge = np.zeros(image.shape[:2], np.uint8)
    edge[:, :-1] |= (np.abs(a[:, 1:] - a[:, :-1]).max(axis=2) >= 32).astype(np.uint8)
    edge[:-1] |= (np.abs(a[1:] - a[:-1]).max(axis=2) >= 32).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(edge, 8)
    return sorted(tuple(map(int, s[:4])) for s in stats[1:n] if s[4] >= 4)


def _same_topology(before, after):
    if len(before) != len(after):
        return False
    # The kernel reaches at most an adjacent pixel. No fitted per-item motion.
    unused = list(after)
    for x, y, w, h in before:
        hits = [i for i, (xx, yy, ww, hh) in enumerate(unused)
                if max(abs(x-xx), abs(y-yy), abs(x+w-xx-ww), abs(y+h-yy-hh)) <= 1]
        if len(hits) != 1:
            return False
        unused.pop(hits[0])
    return True


class CommonSamplingModel:
    schema = 'offline-common-bilinear-q5.v1'
    offline_only = True

    def __init__(self, layout):
        self.layout = layout

    def profile(self, frame):
        self.layout.validate(frame.shape)
        crop = _crop(frame, self.layout.protected)
        geometry = _GeometryOnly()._measure_board_grid(crop, *self.layout.protected[:2])
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        visible = ((hsv[:,:,1] > 35) & (hsv[:,:,2] > 40)).astype(np.uint8)
        n, _, components, _ = cv2.connectedComponentsWithStats(visible, 8)
        fragments = []
        for x, y, w, h, area in components[1:n]:
            if area >= 4 and (x == 0 or y == 0 or x+w == crop.shape[1] or y+h == crop.shape[0]):
                fragments.append({'box': [int(x+self.layout.protected[0]), int(y+self.layout.protected[1]),
                                          int(x+w+self.layout.protected[0]), int(y+h+self.layout.protected[1])],
                                  'status': 'PARTIAL_OBJECT_CANDIDATE', 'formalFactsQualified': False})
        # Measurement is descriptive: never shrink the rectangular protection
        # to detected slots, and never turn a fallback lattice into slot facts.
        return {'protectedBox': list(self.layout.protected), 'protectedPixels': int(crop.shape[0]*crop.shape[1]),
                'coverageHoles': 0, 'grid': geometry, 'unrevealed': content_observation(crop),
                'structure': _structure(crop),
                'partialCandidates': fragments,
                'emptyAndUnrevealedPolicy': 'all pixels protected; no positive empty-slot fact from absence of outlines',
                'partialPolicy': 'edge fragments protected; identity/count/footprint unqualified until overlap',
                'rawBgrSha256': hashlib.sha256(frame.tobytes()).hexdigest(),
                'layoutProvenance': self.layout.provenance}

    def compare(self, before, after):
        self.layout.validate(before.shape)
        if before.shape != after.shape or before.dtype != np.uint8 or after.dtype != np.uint8:
            return {'qualified': False, 'reason': 'CONTENT_GEOMETRY_UNPROVEN'}
        a, b = self.profile(before), self.profile(after)
        base = {'schema': self.schema, 'previous': a, 'current': b,
                'meaning': 'conditional content support, not request-after-render or absolute source age',
                'rendererContractEstablishedForGame': False}
        if not a['unrevealed']['qualified'] or not b['unrevealed']['qualified']:
            return {**base, 'qualified': False, 'reason': 'CONTENT_UNREVEALED_OR_UNKNOWN'}
        exact, best = [], None
        # Fit regions only. Protected pixels and the final reference cannot
        # choose a model; ambiguous references fail instead of cherry-picking.
        for dy in range(-16, 17):
            for dx in range(-16, 17):
                errors = [int(np.any(_predicted(before, box, dx, dy) != _crop(after, box), axis=2).sum())
                          for box in self.layout.references[:-1]]
                n = sum(errors)
                if best is None or n < best['unexplainedPixels']:
                    best = {'phaseQ5': [dx, dy], 'unexplainedPixels': n, 'perReference': errors}
                if not n:
                    exact.append((dx, dy))
        base.update(referenceFit=best, exactReferenceModels=len(exact))
        if len(exact) != 1:
            return {**base, 'qualified': False, 'reason': 'REFERENCE_MODEL_AMBIGUOUS' if exact else 'REFERENCE_MODEL_UNEXPLAINED'}
        dx, dy = exact[0]
        holdout = self.layout.references[-1]
        hold_errors = int(np.any(_predicted(before, holdout, dx, dy) != _crop(after, holdout), axis=2).sum())
        pred = _predicted(before, self.layout.protected, dx, dy)
        actual = _crop(after, self.layout.protected)
        residual = actual.astype(np.int16)-pred.astype(np.int16)
        bad = np.any(residual != 0, axis=2)
        yy, xx = np.where(bad)
        base.update(phaseQ5=[dx, dy], heldoutUnexplainedPixels=hold_errors,
                    unexplainedPixels=int(bad.sum()), maxResidualChannel=int(np.abs(residual).max()),
                    firstUnexplainedCoordinates=[[int(x+self.layout.protected[0]), int(y+self.layout.protected[1])]
                                                 for x, y in zip(xx[:16], yy[:16])],
                    topologySupported=_same_topology(a['structure'], b['structure']))
        reason = ('HELDOUT_REFERENCE_UNEXPLAINED' if hold_errors else 'CONTENT_INTERNAL_UNEXPLAINED' if bad.any()
                  else 'CONTENT_STRUCTURE_CHANGED' if not base['topologySupported'] else 'CONTENT_STRUCTURE_SUPPORTED')
        return {**base, 'qualified': reason == 'CONTENT_STRUCTURE_SUPPORTED', 'reason': reason}
