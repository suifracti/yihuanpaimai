"""Cheap text-shape anchors before weak navigation color heuristics."""
from functools import lru_cache
import hashlib
import cv2
import numpy as np

from visual_catalog import asset_root
from roi_scaler import ROIScaler


@lru_cache(maxsize=1)
def _settlement_title():
    path = asset_root() / 'assets/scene_anchors/settlement_title.png'
    if not path.is_file():
        return None
    return cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_GRAYSCALE)


def settlement_title_visible(frame):
    template = _settlement_title()
    if template is None or frame is None or frame.size == 0:
        return False
    h, w = frame.shape[:2]
    crop = frame[round(h*125/1080):round(h*220/1080), round(w*60/1920):round(w*355/1920)]
    if crop.size == 0:
        return False
    gray = cv2.cvtColor(cv2.resize(crop, (295, 95)), cv2.COLOR_BGR2GRAY)
    score = cv2.minMaxLoc(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED))[1]
    return bool(np.isfinite(score) and score >= .88)


@lru_cache(maxsize=1)
def _settlement_controls():
    result = []
    for name in ('settlement_sale_label', 'settlement_exit_label'):
        path = asset_root() / ('assets/scene_anchors/' + name + '.png')
        result.append(cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_GRAYSCALE)
                      if path.is_file() else None)
    return result


def settlement_controls_visible(frame):
    """Final sale/exit text layout; not a claim that item identities are known.

    Real saved sequences show these controls appear after the reveal sequence,
    including the last item below TOP. Skip text and a stable TOP alone don't.
    The templates contain only labels, excluding price/countdown digits.
    """
    if frame is None or frame.size == 0:
        return False
    vx, vy, vw, vh = ROIScaler.get_viewport_rect(frame.shape[1], frame.shape[0])
    boxes = ((1328, 851, 1465, 911), (1665, 969, 1750, 1032))
    for template, (x, y, r, b) in zip(_settlement_controls(), boxes):
        if template is None:
            return False
        crop = frame[vy+round(y*vh/1080):vy+round(b*vh/1080),
                     vx+round(x*vw/1920):vx+round(r*vw/1920)]
        if crop.size == 0:
            return False
        gray = cv2.cvtColor(cv2.resize(crop, (r-x, b-y)), cv2.COLOR_BGR2GRAY)
        score = cv2.minMaxLoc(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED))[1]
        if not np.isfinite(score) or score < .88:
            return False
    return True


def settlement_reveal_progress(frame):
    """Visible value glyphs for bounded no-progress recovery, never OCR facts."""
    vx, vy, vw, vh = ROIScaler.get_viewport_rect(frame.shape[1], frame.shape[0])
    crop = frame[vy+round(143*vh/1080):vy+round(185*vh/1080),
                 vx+round(1620*vw/1920):vx+round(1880*vw/1920)]
    bgr = cv2.resize(crop, (260,42)).astype(np.int16)
    ink = (bgr[:,:,2] >= 180) & (bgr[:,:,2]-bgr[:,:,1] > 30) & (bgr[:,:,2]-bgr[:,:,0] > 80)
    return hashlib.sha256(ink.tobytes()).hexdigest()
