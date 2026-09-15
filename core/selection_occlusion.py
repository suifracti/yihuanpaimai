"""Locate a visible selection badge; never reconstruct pixels underneath it."""
from functools import lru_cache
from pathlib import Path
import sys

import cv2
import numpy as np


# The selection badge is rendered through the video-compressed game surface.
# At the native screenshot size its template score is usually above .85, but
# short settlement captures can fall to .78-.84 even when the badge is clear.
# Keep this threshold local to badge detection; identity matching thresholds
# remain unchanged and pixels under the badge are still never reconstructed.
SELECTION_MARKER_MATCH_THRESHOLD = 0.75


def _pink_pixels(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return (((hsv[:, :, 0] > 140) & (hsv[:, :, 0] < 175)
             & (hsv[:, :, 1] > 110) & (hsv[:, :, 2] > 85)).astype(np.uint8) * 255)


@lru_cache(maxsize=1)
def _marker():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    path = root / "assets/scene_anchors/selection_marker.png"
    if not path.is_file():
        return None
    image = cv2.imdecode(np.fromfile(path, np.uint8), 1)
    return _pink_pixels(image) if image is not None else None


def selection_occlusion(image):
    mask = np.zeros(image.shape[:2], np.uint8)
    marker = _marker()
    if marker is None:
        return mask, {"score": 0.0}
    query = _pink_pixels(image)
    if np.count_nonzero(query) < 30:
        return mask, {"score": 0.0}
    best_score, best_rect = 0.0, None
    for scale in (.5, .67, .75, 1, 1.33, 1.5, 2):
        template = cv2.resize(marker, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        h, w = template.shape
        if h > query.shape[0] or w > query.shape[1]:
            continue
        _, score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(query, template, cv2.TM_CCORR_NORMED))
        if np.isfinite(score) and score > best_score:
            patch = query[y:y+h, x:x+w]
            t_bg = template <= 127
            bg_pink_ratio = np.count_nonzero(patch[t_bg]) / max(1, np.count_nonzero(t_bg))
            if bg_pink_ratio <= 0.25:
                best_score, best_rect = score, (x, y, w, h)
    if best_score < SELECTION_MARKER_MATCH_THRESHOLD or best_rect is None:
        return mask, {"score": round(best_score, 4)}
    x, y, w, h = best_rect
    mask[max(0, y-1):y+h+1, max(0, x-1):x+w+1] = 255
    return mask, {"score": round(best_score, 4), "bbox": list(best_rect)}
