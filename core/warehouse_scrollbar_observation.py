"""Passive warehouse scrollbar endpoint and segment-change observer.

Detects track/thumb inside the warehouse large ROI. Does not scroll, click,
write History, or submit Coverage Ledger proofs.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from roi_scaler import ROIScaler

STATE_TOP = "TOP"
STATE_MIDDLE = "MIDDLE"
STATE_BOTTOM = "BOTTOM"
STATE_NO_SCROLL = "NO_SCROLL"
STATE_UNKNOWN = "UNKNOWN"

CHANGE_CHANGED = "CHANGED"
CHANGE_UNCHANGED = "UNCHANGED"
CHANGE_UNKNOWN = "UNKNOWN"

WAREHOUSE_ROI = "warehouse_board"
# Scrollbar sits just to the right of the grid; keep it in the same large panel.
SCROLL_RIGHT_PAD = 0.020
SCROLL_BOTTOM_PAD = 0.030


class WarehouseScrollbarObserver:
    def __init__(self):
        self._last: Optional[Dict[str, Any]] = None

    def reset(self) -> None:
        self._last = None

    def observe(self, frame: np.ndarray, *, source_id: str = "", already_cropped: bool = False) -> Dict[str, Any]:
        result = observe_warehouse_scrollbar(
            frame,
            previous=self._last,
            source_id=source_id,
            already_cropped=already_cropped,
        )
        if result.get("scrollState") != STATE_UNKNOWN:
            self._last = result
        return result


def warehouse_search_roi(width: int, height: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = ROIScaler.scale_roi(WAREHOUSE_ROI, width, height)
    vx, vy, vw, vh = ROIScaler.get_viewport_rect(width, height)
    x2 = min(width, x2 + int(SCROLL_RIGHT_PAD * vw))
    y2 = min(height, y2 + int(SCROLL_BOTTOM_PAD * vh))
    return x1, y1, max(x1 + 1, x2), max(y1 + 1, y2)


def _content_fingerprint(gray: np.ndarray) -> str:
    small = cv2.resize(gray, (24, 24), interpolation=cv2.INTER_AREA)
    return hashlib.sha256(small.tobytes()).hexdigest()


def _longest_run(flags: np.ndarray) -> Optional[Tuple[int, int]]:
    runs = []
    start = None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        elif (not flag) and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    if not runs:
        return None
    return max(runs, key=lambda item: item[1] - item[0])


def _detect_track_and_thumb(crop: np.ndarray) -> Optional[Dict[str, Any]]:
    if crop is None or crop.size == 0:
        return None
    height, width = crop.shape[:2]
    if height < 40 or width < 16:
        return None

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].astype(np.float32)
    val = hsv[:, :, 2].astype(np.float32)
    right0 = int(width * 0.78)
    right = sat[:, right0:]
    right_v = val[:, right0:]
    thumb_score = ((right < 45) & (right_v > 145)).mean(axis=0)
    if float(thumb_score.max()) < 0.04:
        return None
    # Item borders can contain more bright pixels than the actual thumb.
    # Prefer a narrow, vertically continuous component on the panel's right
    # edge instead of choosing the brightest entire column.
    bright = ((right < 45) & (right_v > 145)).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(bright, 8)
    candidates = []
    for index in range(1, count):
        x, y, cw, ch, area = stats[index]
        if (2 <= cw <= max(12, int(width * .025))
                and ch >= max(16, int(height * .06))
                and ch >= cw * 5 and area >= cw * ch * .55):
            candidates.append((x + cw / 2, int(x + cw / 2)))
    local = max(candidates)[1] if candidates else int(np.argmax(thumb_score))
    col = right0 + local
    sl = slice(max(0, col - 2), min(width, col + 3))
    sat_col = sat[:, sl].mean(axis=1)
    val_col = val[:, sl].mean(axis=1)
    thumb_flags = (sat_col < 45) & (val_col > 145)
    track_flags = (sat_col < 120) & (val_col > 20) & (val_col < 95)
    usable = thumb_flags | track_flags
    usable_u8 = usable.astype(np.uint8) * 255
    usable_u8 = cv2.morphologyEx(
        usable_u8.reshape(-1, 1),
        cv2.MORPH_CLOSE,
        np.ones((41, 1), np.uint8),
    ).ravel()
    track = _longest_run(usable_u8 > 0)
    if track is None:
        return None
    tr0, tr1 = track
    if tr1 - tr0 + 1 < max(36, int(height * 0.18)):
        return None
    inner = np.zeros_like(thumb_flags)
    inner[tr0 : tr1 + 1] = thumb_flags[tr0 : tr1 + 1]
    thumb = _longest_run(inner)
    if thumb is None:
        return None
    ty0, ty1 = thumb
    thumb_len = ty1 - ty0 + 1
    track_len = tr1 - tr0 + 1
    if thumb_len < max(16, int(height * 0.06)):
        return None
    return {
        "track": (tr0, tr1),
        "thumb": (ty0, ty1),
        "trackLen": track_len,
        "thumbLen": thumb_len,
        "col": col,
        "above": ty0 - tr0,
        "below": tr1 - ty1,
        "coverage": thumb_len / float(track_len),
    }


def _classify(geom: Dict[str, Any]) -> Tuple[str, float]:
    above = geom["above"]
    below = geom["below"]
    track_len = geom["trackLen"]
    coverage = geom["coverage"]
    tol = max(8, int(0.055 * track_len))
    if coverage >= 0.90:
        return STATE_NO_SCROLL, min(1.0, 0.55 + coverage)
    if above <= tol and below > tol:
        return STATE_TOP, min(1.0, 0.62 + (below / track_len))
    if below <= tol and above > tol:
        return STATE_BOTTOM, min(1.0, 0.62 + (above / track_len))
    if above > tol and below > tol:
        return STATE_MIDDLE, min(1.0, 0.58 + min(above, below) / track_len)
    return STATE_UNKNOWN, 0.2


def observe_warehouse_scrollbar(
    frame: Optional[np.ndarray],
    *,
    previous: Optional[Dict[str, Any]] = None,
    source_id: str = "",
    already_cropped: bool = False,
) -> Dict[str, Any]:
    empty = {
        "scrollState": STATE_UNKNOWN,
        "trackBox": None,
        "thumbBox": None,
        "thumbPosition": None,
        "thumbLength": None,
        "confidence": 0.0,
        "warehouseFingerprint": None,
        "segmentChange": CHANGE_UNKNOWN,
        "sourceId": source_id,
    }
    if frame is None or getattr(frame, "size", 0) == 0:
        return empty
    if already_cropped:
        origin = (0, 0)
        crop = frame
    else:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = warehouse_search_roi(w, h)
        crop = frame[y1:y2, x1:x2]
        origin = (x1, y1)
    if crop.size == 0:
        return empty

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    fingerprint = _content_fingerprint(gray)
    geom = _detect_track_and_thumb(crop)
    if geom is None:
        return {**empty, "warehouseFingerprint": fingerprint, "confidence": 0.15}

    state, confidence = _classify(geom)
    if confidence < 0.45:
        state = STATE_UNKNOWN
    tr0, tr1 = geom["track"]
    ty0, ty1 = geom["thumb"]
    col = geom["col"]
    ox, oy = origin
    track_box = [ox + max(0, col - 3), oy + tr0, ox + col + 3, oy + tr1]
    thumb_box = [ox + max(0, col - 3), oy + ty0, ox + col + 3, oy + ty1]
    thumb_pos = (ty0 - tr0) / float(geom["trackLen"])
    thumb_len = geom["coverage"]

    change = CHANGE_UNKNOWN
    if previous and previous.get("scrollState") not in (None, STATE_UNKNOWN) and state != STATE_UNKNOWN:
        prev_pos = previous.get("thumbPosition")
        prev_fp = previous.get("warehouseFingerprint")
        pos_delta = abs((prev_pos if prev_pos is not None else thumb_pos) - thumb_pos)
        fp_changed = prev_fp is not None and prev_fp != fingerprint
        if pos_delta < 0.035 and not fp_changed:
            change = CHANGE_UNCHANGED
        elif pos_delta >= 0.035 or fp_changed:
            change = CHANGE_CHANGED

    return {
        "scrollState": state,
        "trackBox": track_box,
        "thumbBox": thumb_box,
        "thumbPosition": round(float(thumb_pos), 4),
        "thumbLength": round(float(thumb_len), 4),
        "confidence": round(float(confidence), 3),
        "warehouseFingerprint": fingerprint,
        "segmentChange": change,
        "sourceId": source_id,
    }
