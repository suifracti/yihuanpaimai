"""Cheap text-shape anchors before weak navigation color heuristics."""
from functools import lru_cache
import cv2
import numpy as np

from visual_catalog import asset_root


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
