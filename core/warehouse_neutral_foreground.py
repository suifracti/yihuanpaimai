"""Shape/color evidence for colored objects on neutral, bevelled item tiles.

Brightness thresholding can include the tile bevel as part of an object. Two
chroma masks retain pale and saturated object regions without that bevel.
Small translations compensate for quantized crop edges; they do not change
scale/aspect or the final shape, color correlation and error requirements.
"""
import cv2
import numpy as np


def _extract(image, saturation_floor):
    if image is None or min(image.shape[:2]) < 8:
        return None
    pad = max(2, round(min(image.shape[:2]) * .08))
    image = image[pad:-pad, pad:-pad]
    if min(image.shape[:2]) < 8:
        return None
    scale = 256 / max(image.shape[:2])
    image = cv2.resize(image, None, fx=scale, fy=scale)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    border = np.concatenate((hsv[1, ::3], hsv[-2, ::3], hsv[::3, 1], hsv[::3, -2]))
    saturation = float(np.median(border[:, 1]))
    if saturation > 45:
        return None
    mask = (hsv[:, :, 1] > max(saturation_floor, saturation + 12)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if not .03 < cv2.contourArea(contour) / mask.size < .85:
        return None
    x, y, w, h = cv2.boundingRect(contour)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, [contour], -1, 255, -1)
    return image[y:y+h, x:x+w], filled[y:y+h, x:x+w]


def _correlation(a, b):
    a, b = a - a.mean(), b - b.mean()
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / max(1e-8, norm))


def prepare_pair(pair):
    if pair is None:
        return None
    image, mask = pair[:2]
    return (image, mask, cv2.resize(image, (96, 96)).astype(np.float32),
            cv2.resize(mask, (96, 96)) > 127)


def prepare_neutral_foreground(image):
    return tuple(prepare_pair(_extract(image, floor)) for floor in (15, 45))


def _compare(query, template):
    q, qm = query[:2]
    t, tm = template[:2]
    ratio = (q.shape[1] / q.shape[0]) / (t.shape[1] / t.shape[0])
    if not .75 < ratio < 1.33:
        return None
    query = query if len(query) == 4 else prepare_pair(query)
    template = template if len(template) == 4 else prepare_pair(template)
    q, qm = query[2:]
    t, tm = template[2:]
    overlap = qm & tm
    if overlap.sum() / max(1, (qm | tm).sum()) < .75:
        return None
    # Registration is attempted only for already overlapping, related images.
    if _correlation(q[overlap].ravel(), t[overlap].ravel()) < .70:
        return None
    best = None
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            transform = np.float32([[1, 0, dx], [0, 1, dy]])
            shifted = cv2.warpAffine(t, transform, (96, 96))
            shifted_mask = cv2.warpAffine(tm.astype(np.uint8), transform, (96, 96)) > 0
            overlap = qm & shifted_mask
            iou = float(overlap.sum() / max(1, (qm | shifted_mask).sum()))
            if iou < .75:
                continue
            a, b = q[overlap].ravel(), shifted[overlap].ravel()
            correlation = _correlation(a, b)
            error = float(np.abs(a - b).mean())
            if correlation < .85 or error > 22:
                continue
            result = {'score': round(.9 + .1 * min(iou, correlation), 4),
                      'iou': iou, 'correlation': correlation, 'error': error,
                      'neutralBackground': True, 'translation96': [dx, dy]}
            if best is None or result['score'] > best['score']:
                best = result
    return best


def match_prepared_neutral(query_pairs, template_pairs):
    matches = []
    for query, template in zip(query_pairs, template_pairs):
        if query is not None and template is not None:
            result = _compare(query, template)
            if result is not None:
                matches.append(result)
    return max(matches, key=lambda result: result['score']) if matches else None


def match_neutral_foreground(query_image, template_body):
    return match_prepared_neutral(prepare_neutral_foreground(query_image),
                                  prepare_neutral_foreground(template_body))
