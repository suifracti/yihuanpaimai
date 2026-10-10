"""Vertical overlap alignment for warehouse ROI segments.

Produces fail-closed visual proofs only. Does not identify items, scroll,
or write History / Coverage Ledger.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

STATUS_VERIFIED = "VERIFIED"
STATUS_UNVERIFIED = "UNVERIFIED"
STATUS_CONFLICT = "CONFLICT"

DIR_DOWN = "DOWN"
DIR_UP = "UP"
DIR_NONE = "NONE"
DIR_UNKNOWN = "UNKNOWN"

REASON_NO_MOVEMENT = "NO_MOVEMENT"
REASON_ALIGNED = "CONTENT_ALIGNED"
REASON_INSUFFICIENT_FEATURES = "INSUFFICIENT_FEATURES"
REASON_AMBIGUOUS_OFFSET = "AMBIGUOUS_OFFSET"
REASON_DIRECTION_MISMATCH = "DIRECTION_MISMATCH"
REASON_HORIZONTAL_DRIFT = "HORIZONTAL_DRIFT"
REASON_EMPTY_CONTENT = "EMPTY_CONTENT"
REASON_LARGE_GAP = "LARGE_GAP"
REASON_LOW_OVERLAP = "LOW_OVERLAP"

MIN_BLOBS = 3
MIN_SCORE = 0.72
MIN_AREA = 260
MAX_H_DRIFT = 10
CLUSTER_BIN = 4


def _content_view(bgr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    h, w = bgr.shape[:2]
    roi = bgr[: int(h * 0.88), : int(w * 0.88)]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    occupied = ((sat > 35) & (val > 40)) | ((val > 70) & (sat > 18))
    occupied = cv2.morphologyEx(occupied.astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    occupied = cv2.morphologyEx(occupied, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return roi, occupied


def _blobs(mask: np.ndarray) -> List[Tuple[int, int, int, int, int]]:
    count, _labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    blobs: List[Tuple[int, int, int, int, int]] = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if area < MIN_AREA or w < 10 or h < 10:
            continue
        if w > mask.shape[1] * 0.82:
            continue
        blobs.append((int(x), int(y), int(w), int(h), int(area)))
    return blobs


def _cluster_offsets(votes: Sequence[Tuple[int, float, int]]) -> List[Tuple[int, List[Tuple[int, float, int]]]]:
    buckets: Dict[int, List[Tuple[int, float, int]]] = defaultdict(list)
    for dy, score, area in votes:
        buckets[int(round(dy / float(CLUSTER_BIN)) * CLUSTER_BIN)].append((dy, score, area))
    ranked = sorted(
        buckets.items(),
        key=lambda item: (-len(item[1]), -sum(score for _dy, score, _area in item[1])),
    )
    return ranked


def _overlap_ratio(mask_a: np.ndarray, mask_b: np.ndarray, dy: int) -> float:
    h = mask_a.shape[0]
    if dy <= 0:
        a = mask_a[-dy:h]
        b = mask_b[0 : h + dy]
    else:
        a = mask_a[0 : h - dy]
        b = mask_b[dy:h]
    if a.size == 0 or b.shape != a.shape:
        return 0.0
    union = np.logical_or(a > 0, b > 0)
    if int(union.sum()) == 0:
        return 0.0
    inter = np.logical_and(a > 0, b > 0)
    return float(inter.sum()) / float(union.sum())


def _band_alignment(view_a: np.ndarray, view_b: np.ndarray,
                    mask_a: np.ndarray, mask_b: np.ndarray, max_shift_px: int) -> Dict[str, Any]:
    """Match disjoint content bands anywhere in the other viewport.

    A fixed upper strip cannot survive a half-viewport downward scroll. Short
    bands distributed over the content retain lower overlaps in either
    direction. Two distinct bands must agree, and the entire shared area must
    support that displacement; repeated grid/background alone is insufficient.
    """
    height, width = view_a.shape[:2]
    band_h = max(12, height // 8)
    x = width // 10
    band_w = width - 2 * x
    if height < 2 * band_h or band_w < 12:
        return {}
    votes = []
    for y in range(0, height - band_h + 1, band_h):
        template = view_a[y:y + band_h, x:x + band_w]
        occupied = mask_a[y:y + band_h, x:x + band_w]
        if float(template.std()) < 8 or np.count_nonzero(occupied) < .05 * occupied.size:
            continue
        scores = cv2.matchTemplate(view_b, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(scores)
        if score < .80:
            continue
        dy, dx = loc[1] - y, loc[0] - x
        if abs(dx) > MAX_H_DRIFT or abs(dy) > max_shift_px:
            continue
        # Reject a second plausible location, including horizontal aliases.
        competitors = scores.copy()
        radius = max(CLUSTER_BIN, band_h // 4)
        competitors[max(0, loc[1] - radius):loc[1] + radius + 1,
                    max(0, loc[0] - MAX_H_DRIFT):loc[0] + MAX_H_DRIFT + 1] = -1
        if float(competitors.max()) >= score - .05:
            continue
        votes.append((int(dy), float(score), y))
    if len(votes) < 2:
        return {}
    clusters = _cluster_offsets(votes)
    candidates = []
    for _, supporting in clusters:
        if len(supporting) < 2:
            continue
        offset = int(round(float(np.mean([dy for dy, _, _ in supporting]))))
        if offset < 0:
            shared_a, shared_b = view_a[-offset:], view_b[:height + offset]
        else:
            shared_a, shared_b = view_a[:height - offset], view_b[offset:]
        overlap = 1 - abs(offset) / float(height)
        if overlap < .12 or _overlap_ratio(mask_a, mask_b, offset) < .12:
            continue
        shared_score = float(cv2.matchTemplate(shared_a, shared_b, cv2.TM_CCOEFF_NORMED)[0, 0])
        if shared_score >= .80:
            candidates.append((shared_score, offset, overlap, len(supporting)))
    if not candidates:
        return {}  # Matched fragments do not certify the rest of the overlap.
    candidates.sort(reverse=True)
    shared_score, offset, overlap, support = candidates[0]
    # Adjacent quantization buckets can split votes differing by one pixel.
    # They support the same displacement, not competing physical locations.
    support = sum(count for _, dy, _, count in candidates if abs(dy - offset) <= CLUSTER_BIN)
    if any(abs(dy - offset) > CLUSTER_BIN and score >= shared_score - .05
           for score, dy, _, _ in candidates[1:]):
        return {"reason": REASON_AMBIGUOUS_OFFSET}
    if abs(offset) <= 3:
        return {"direction": DIR_NONE, "verticalOffsetPx": 0, "reason": REASON_NO_MOVEMENT}
    return {"status": STATUS_VERIFIED, "direction": DIR_DOWN if offset < 0 else DIR_UP,
            "verticalOffsetPx": offset, "normalizedOffset": round(offset / float(height), 4),
            "overlapRatio": round(overlap, 4), "confidence": round(shared_score, 3),
            "reason": "DISJOINT_CONTENT_BANDS", "supportCount": support,
            "progressionVerified": True}


def _align_warehouse_segments(
    prev_img: Optional[np.ndarray],
    next_img: Optional[np.ndarray],
    *,
    prev_id: str = "",
    next_id: str = "",
    required_direction: Optional[str] = None,
    max_shift_px: int = 320,
) -> Dict[str, Any]:
    result = {
        "status": STATUS_UNVERIFIED,
        "direction": DIR_UNKNOWN,
        "verticalOffsetPx": None,
        "normalizedOffset": None,
        "overlapRatio": None,
        "confidence": 0.0,
        "reason": REASON_INSUFFICIENT_FEATURES,
        "prevId": prev_id,
        "nextId": next_id,
        "supportCount": 0,
        "progressionVerified": False,
        "progressionProofId": None,
    }
    if prev_img is None or next_img is None or prev_img.size == 0 or next_img.size == 0:
        return result
    if prev_img.shape[:2] != next_img.shape[:2]:
        result["reason"] = "SIZE_MISMATCH"
        return result

    view_a, mask_a = _content_view(prev_img)
    view_b, mask_b = _content_view(next_img)
    height = view_a.shape[0]

    # 1. Primary path: Content item blobs template matching (MIN_BLOBS = 3 strictly enforced)
    blobs = _blobs(mask_a) if (mask_a > 0).sum() >= 800 and (mask_b > 0).sum() >= 800 else []
    votes: List[Tuple[int, float, int]] = []
    h_drift_hits = 0
    for x, y, w, h, area in blobs:
        tmpl = view_a[y : y + h, x : x + w]
        if tmpl.size == 0:
            continue
        xs = max(0, x - 8)
        xe = min(view_b.shape[1], x + w + 8)
        search = view_b[:, xs:xe]
        if search.shape[0] <= h + 2 or search.shape[1] < w:
            continue
        scores = cv2.matchTemplate(search, tmpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(scores)
        if score < MIN_SCORE:
            continue
        dy = int(loc[1] - y)
        dx = int(loc[0] + xs - x)
        if abs(dx) > MAX_H_DRIFT:
            h_drift_hits += 1
            continue
        if abs(dy) > max_shift_px:
            continue
        votes.append((dy, float(score), area))

    if h_drift_hits >= 3 and len(votes) < MIN_BLOBS:
        result["status"] = STATUS_UNVERIFIED
        result["reason"] = REASON_HORIZONTAL_DRIFT
        return result

    if len(votes) >= MIN_BLOBS:
        clusters = _cluster_offsets(votes)
        best_key, best_votes = clusters[0]
        second_count = len(clusters[1][1]) if len(clusters) > 1 else 0
        if len(best_votes) >= MIN_BLOBS and not (
                second_count >= max(2, int(0.7 * len(best_votes))) and len(clusters) > 1):
            offset = int(round(float(np.mean([dy for dy, _s, _a in best_votes]))))
            support = len(best_votes)
            mean_score = float(np.mean([score for _dy, score, _a in best_votes]))
            if abs(offset) <= 3:
                result.update({
                    "status": STATUS_UNVERIFIED,
                    "direction": DIR_NONE,
                    "verticalOffsetPx": 0,
                    "normalizedOffset": 0.0,
                    "overlapRatio": 1.0,
                    "confidence": 1.0,
                    "reason": REASON_NO_MOVEMENT,
                    "supportCount": support,
                    "progressionVerified": False,
                    "progressionProofId": None,
                })
                return result
            elif offset < 0:
                direction = DIR_DOWN
                reason = REASON_ALIGNED
                status = STATUS_VERIFIED
            else:
                direction = DIR_UP
                reason = REASON_ALIGNED
                status = STATUS_VERIFIED

            if required_direction in {DIR_DOWN, DIR_UP} and direction not in {DIR_NONE, DIR_UNKNOWN}:
                if direction != required_direction:
                    result.update({
                        "status": STATUS_CONFLICT,
                        "direction": direction,
                        "verticalOffsetPx": offset,
                        "normalizedOffset": round(offset / float(height), 4),
                        "overlapRatio": round(_overlap_ratio(mask_a, mask_b, offset), 4),
                        "confidence": round(mean_score * min(1.0, support / 4.0), 3),
                        "reason": REASON_DIRECTION_MISMATCH,
                        "supportCount": support,
                    })
                    return result

            if status == STATUS_VERIFIED and abs(offset) > int(0.55 * height) and support < 4:
                status = STATUS_UNVERIFIED
                reason = REASON_LARGE_GAP

            overlap = _overlap_ratio(mask_a, mask_b, offset)
            if status == STATUS_VERIFIED and overlap < 0.12 and direction != DIR_NONE:
                status = STATUS_UNVERIFIED
                reason = REASON_LOW_OVERLAP

            if status == STATUS_VERIFIED:
                result.update({
                    "status": status,
                    "direction": direction,
                    "verticalOffsetPx": offset,
                    "normalizedOffset": round(offset / float(height), 4),
                    "overlapRatio": round(overlap, 4),
                    "confidence": round(mean_score * min(1.0, support / 4.0), 3),
                    "reason": reason,
                    "supportCount": support,
                    "progressionVerified": True,
                    "progressionProofId": f"overlap-down:{prev_id}:{next_id}:{offset}",
                })
                return result

    # 2. Actual shared content at either edge, independent of scrollbar scale.
    bands = _band_alignment(view_a, view_b, mask_a, mask_b, max_shift_px)
    if bands:
        result.update(bands)
        direction = bands.get("direction")
        if bands.get("status") == STATUS_VERIFIED:
            if required_direction in {DIR_DOWN, DIR_UP} and direction != required_direction:
                result.update(status=STATUS_CONFLICT, reason=REASON_DIRECTION_MISMATCH,
                              progressionVerified=False)
            else:
                result["progressionProofId"] = f"overlap-{direction.lower()}:{prev_id}:{next_id}:{bands['verticalOffsetPx']}"
        return result

    # 3. Sparse / Empty Progression Fallback (No fake verticalOffsetPx)
    from warehouse_grid_geometry import observe_warehouse_grid
    from warehouse_scrollbar_observation import observe_warehouse_scrollbar

    prev_grid = observe_warehouse_grid(prev_img, already_cropped=True)
    next_grid = observe_warehouse_grid(next_img, already_cropped=True)
    if prev_grid.get("grid", {}).get("status") != "OK" or next_grid.get("grid", {}).get("status") != "OK":
        result["reason"] = REASON_INSUFFICIENT_FEATURES
        result["supportCount"] = len(votes)
        return result

    prev_sb = observe_warehouse_scrollbar(prev_img, already_cropped=True)
    next_sb = observe_warehouse_scrollbar(next_img, previous=prev_sb, already_cropped=True)
    pos_prev = prev_sb.get("thumbPosition")
    pos_next = next_sb.get("thumbPosition")
    if pos_prev is None or pos_next is None:
        result["reason"] = REASON_INSUFFICIENT_FEATURES
        result["supportCount"] = len(votes)
        return result

    delta_pos = float(pos_next) - float(pos_prev)
    if delta_pos < -0.01:
        if required_direction == DIR_DOWN:
            result.update({"status": STATUS_CONFLICT, "direction": DIR_UP, "reason": REASON_DIRECTION_MISMATCH})
            return result
        result.update({"status": STATUS_UNVERIFIED, "direction": DIR_UP, "reason": REASON_DIRECTION_MISMATCH})
        return result
    if delta_pos <= 0.003:
        result.update({"status": STATUS_UNVERIFIED, "direction": DIR_NONE, "verticalOffsetPx": 0, "reason": REASON_NO_MOVEMENT})
        return result
    if delta_pos > 0.15:
        result.update({"status": STATUS_UNVERIFIED, "direction": DIR_DOWN, "reason": REASON_LARGE_GAP})
        return result

    result.update({
        "status": STATUS_UNVERIFIED,
        "direction": DIR_DOWN,
        "verticalOffsetPx": None,
        "normalizedOffset": None,
        "overlapRatio": None,
        "confidence": round(float(next_sb.get("confidence", 0.8)) * 0.8, 3),
        "reason": "SPARSE_PROGRESSION_VERIFIED",
        "supportCount": 0,
        "progressionVerified": True,
        "progressionProofId": f"progression-down:{prev_id}:{next_id}:{pos_prev:.4f}->{pos_next:.4f}",
    })
    return result


class TerminalContinuity:
    """Same-chain pixel/scrollbar calibration; never learns from grid aliases.

    Two content matches starting at TOP bound the scale. Integer pixel and
    thumb localization each have one-pixel uncertainty. A sparse terminal
    step may interpolate within both observed steps, but cannot extrapolate,
    reconnect a skipped viewport, or establish the physical bottom.
    """
    def __init__(self):
        self.samples = []
        self.end = None
        self.shape = None

    @staticmethod
    def _observations(a, b):
        from warehouse_scrollbar_observation import observe_warehouse_scrollbar
        return (observe_warehouse_scrollbar(a, already_cropped=True),
                observe_warehouse_scrollbar(b, already_cropped=True))

    @staticmethod
    def _same_geometry(a, b):
        return (a.get('trackBox') is not None and a.get('trackBox') == b.get('trackBox')
                and a.get('thumbBox') is not None and b.get('thumbBox') is not None
                and a['thumbBox'][0::2] == b['thumbBox'][0::2]
                and abs((a['thumbBox'][3] - a['thumbBox'][1])
                        - (b['thumbBox'][3] - b['thumbBox'][1])) <= 1)

    def record(self, a, b, motion):
        before, after = self._observations(a, b)
        if (not self._same_geometry(before, after)
                or not motion.get('prevId') or not motion.get('nextId')
                or motion['prevId'] == motion['nextId']):
            self.samples, self.end = [], None
            return
        if (self.end is None or self.shape != a.shape
                or not self._same_geometry(self.end, before)
                or self.end['thumbBox'] != before['thumbBox']):
            self.samples, self.end = [], None
            if before['scrollState'] != 'TOP':
                return
        delta = after['thumbBox'][1] - before['thumbBox'][1]
        offset = abs(motion['verticalOffsetPx'])
        if delta <= 1 or offset <= 3:
            return
        self.samples = (self.samples + [{'thumbDelta': delta, 'offset': offset,
            'proofId': motion['progressionProofId']}])[-2:]
        self.end, self.shape = after, a.shape

    def terminal(self, a, b, max_shift_px):
        if len(self.samples) < 2 or a.shape != self.shape or b.shape != a.shape:
            return {}
        before, after = self._observations(a, b)
        if (after.get('scrollState') != 'BOTTOM' or before.get('scrollState') not in {'MIDDLE', 'BOTTOM'}
                or not self._same_geometry(before, after)
                or not self._same_geometry(self.end, before)
                or before['thumbBox'] != self.end['thumbBox']):
            return {}
        delta = after['thumbBox'][1] - before['thumbBox'][1]
        if delta <= 0 or delta > min(s['thumbDelta'] for s in self.samples) + 1:
            return {}  # A larger/skipped step needs actual content correspondences.
        from warehouse_grid_geometry import observe_warehouse_grid
        ga, gb = (observe_warehouse_grid(im, already_cropped=True) for im in (a, b))
        g0, g1 = ga['grid'], gb['grid']
        if (g0['status'] != 'OK' or g1['status'] != 'OK' or gb['components']
                or g0['columnCount'] != g1['columnCount']
                or abs(g0['cellWidth'] - g1['cellWidth']) > 1
                or abs(g0['cellHeight'] - g1['cellHeight']) > 1
                or len(g0['xLines']) != len(g1['xLines'])
                or max(abs(x - y) for x, y in zip(g0['xLines'], g1['xLines'])) > 1):
            return {}
        low = max((s['offset'] - 1) / (s['thumbDelta'] + 1) for s in self.samples)
        high = min((s['offset'] + 1) / (s['thumbDelta'] - 1) for s in self.samples)
        lo, hi = int(np.ceil(low * max(0, delta - 1))), int(np.floor(high * (delta + 1)))
        va, _ = _content_view(a); vb, _ = _content_view(b)
        height = va.shape[0]
        if (low > high or lo <= 3 or hi > min(max_shift_px, .88 * height)
                or hi - lo >= .5 * g0['cellHeight']):
            return {}  # The calibrated interval must exclude grid-period aliases.
        gradients = [cv2.Sobel(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY),
                              cv2.CV_32F, 0, 1, ksize=3) for im in (va, vb)]
        candidates = []
        for offset in range(lo, hi + 1):
            shared_a, shared_b = gradients[0][offset:], gradients[1][:-offset]
            halves = [(shared_a, shared_b), *zip(np.array_split(shared_a, 2), np.array_split(shared_b, 2))]
            if any(float(x.std()) < 8 or float(y.std()) < 8 for x, y in halves):
                continue
            scores = [float(cv2.matchTemplate(x, y, cv2.TM_CCOEFF_NORMED)[0, 0]) for x, y in halves]
            # Same .80 correspondence floor as content bands; require both
            # disjoint grid portions as well as the complete shared gradient.
            if min(scores) >= .80:
                candidates.append((min(scores), offset, scores))
        if not candidates:
            return {}
        candidates.sort(reverse=True)
        score, offset, scores = candidates[0]
        if any(abs(dy - offset) > CLUSTER_BIN for _, dy, _ in candidates[1:]):
            return {}
        self.end = after  # Advance the cursor, never train the scale on this inference.
        return {'status': STATUS_VERIFIED, 'direction': DIR_DOWN,
                'verticalOffsetPx': -offset, 'normalizedOffset': round(-offset / height, 4),
                'overlapRatio': round(1 - offset / height, 4), 'confidence': round(score, 3),
                'reason': 'TERMINAL_SCROLLBAR_GRID_CONTINUITY', 'supportCount': 2,
                'progressionVerified': True, 'bottomConfirmed': False,
                'offsetBasis': 'content-calibrated scrollbar interval plus registered grid gradients',
                'terminalContinuity': {'calibration': self.samples.copy(),
                    'thumbDelta': delta, 'displacementIntervalPx': [lo, hi],
                    'gridPeriodPx': g0['cellHeight'], 'sharedGradientScores': scores}}


def align_warehouse_segments(prev_img, next_img, *, prev_id='', next_id='',
                             required_direction=None, max_shift_px=320, terminal_continuity=None):
    result = _align_warehouse_segments(prev_img, next_img, prev_id=prev_id, next_id=next_id,
        required_direction=required_direction, max_shift_px=max_shift_px)
    if terminal_continuity is None or prev_img is None or next_img is None:
        return result
    if (result['status'] == STATUS_VERIFIED and result['direction'] == DIR_DOWN
            and result['reason'] in {REASON_ALIGNED, 'DISJOINT_CONTENT_BANDS'}):
        terminal_continuity.record(prev_img, next_img, result)
    elif (required_direction == DIR_DOWN and result['status'] == STATUS_UNVERIFIED
            and result['reason'] in {REASON_LARGE_GAP, REASON_INSUFFICIENT_FEATURES,
                                    REASON_LOW_OVERLAP, 'SPARSE_PROGRESSION_VERIFIED'}
            and prev_id and next_id and prev_id != next_id):
        terminal = terminal_continuity.terminal(prev_img, next_img, max_shift_px)
        if terminal:
            result.update(terminal)
            result['progressionProofId'] = f'terminal-grid:{prev_id}:{next_id}:{terminal["verticalOffsetPx"]}'
    return result
