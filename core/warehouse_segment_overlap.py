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


def align_warehouse_segments(
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
        if not (second_count >= max(2, int(0.7 * len(best_votes))) and len(clusters) > 1):
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

    # 2. Try Strip Image Match on grid image
    h_img, w_img = prev_img.shape[:2]
    strip_h = int(h_img * 0.5)
    strip_w = int(w_img * 0.7)
    strip_x0 = int(w_img * 0.1)
    strip_y0 = int(h_img * 0.2)
    tmpl = prev_img[strip_y0 : strip_y0 + strip_h, strip_x0 : strip_x0 + strip_w]
    scores = cv2.matchTemplate(next_img, tmpl, cv2.TM_CCOEFF_NORMED)
    _, max_score, _, max_loc = cv2.minMaxLoc(scores)
    dy = int(max_loc[1] - strip_y0)
    dx = int(max_loc[0] - strip_x0)

    if max_score >= 0.80 and abs(dx) <= MAX_H_DRIFT and -max_shift_px <= dy <= -6:
        result.update({
            "status": STATUS_VERIFIED,
            "direction": DIR_DOWN,
            "verticalOffsetPx": dy,
            "normalizedOffset": round(dy / float(height), 4),
            "overlapRatio": round(max(0.0, min(1.0, 1.0 - abs(dy) / float(height))), 4),
            "confidence": round(max_score * 0.9, 3),
            "reason": "STRIP_IMAGE_MATCH",
            "supportCount": 2,
            "progressionVerified": True,
            "progressionProofId": f"overlap-down:{prev_id}:{next_id}:{dy}",
        })
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
