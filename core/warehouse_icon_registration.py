"""Photometric verification of a fine-scale feature match at native resolution."""
import cv2
import numpy as np


def verify_registered_icon(query, body, source_features, target_features, matcher, distinct):
    kp1, des1 = source_features
    kp2, des2 = target_features
    if des1 is None or des2 is None or len(des2) < 2:
        return None
    pairs = matcher.knnMatch(des1, des2, k=2)
    good = distinct([p[0] for p in pairs if len(p) == 2 and p[0].distance < .75 * p[1].distance], kp1, kp2)
    if len(good) < 7:
        return None
    src = np.float32([kp1[m.queryIdx].pt for m in good])
    dst = np.float32([kp2[m.trainIdx].pt for m in good])
    transform, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3)
    if transform is None or inliers is None or int(inliers.sum()) < 7:
        return None
    determinant = float(np.linalg.det(transform[:, :2]))
    if determinant <= 0:
        return None
    scale = determinant ** .5
    if not .08 <= scale <= 3:
        return None
    hsv = cv2.cvtColor(body, cv2.COLOR_BGR2HSV).astype(np.float32)
    pad = max(2, round(min(body.shape[:2]) * .08))
    border = np.concatenate((hsv[pad, pad:-pad], hsv[-pad-1, pad:-pad],
                             hsv[pad:-pad, pad], hsv[pad:-pad, -pad-1]))
    hue, saturation, _ = np.median(border, axis=0)
    distance = np.abs(hsv[:, :, 0] - hue)
    distance = np.minimum(distance, 180 - distance)
    if saturation > 45:
        mask = ((distance > 12) & (hsv[:, :, 1] > 40)) | (hsv[:, :, 1] < saturation * .35)
    else:
        mask = hsv[:, :, 1] > max(15, saturation + 12)
    mask[:pad] = mask[-pad:] = False
    mask[:, :pad] = mask[:, -pad:] = False
    if not mask.any():
        return None
    height, width = query.shape[:2]
    # Anti-alias the source before minification. warpAffine's linear sampler
    # alone would alias the high-resolution source at these capture scales.
    sigma = .5 * max(0, 1 / (scale * scale) - 1) ** .5
    filtered = cv2.GaussianBlur(body, (0, 0), sigma) if sigma > .01 else body
    warped = cv2.warpAffine(filtered, transform, (width, height))
    support = cv2.warpAffine(mask.astype(np.float32), transform, (width, height)) > .5
    expected_area = float(mask.sum()) * scale * scale
    if support.sum() < 16 or support.sum() < .85 * expected_area:
        return None
    a, b = query[support].astype(np.float32).ravel(), warped[support].astype(np.float32).ravel()
    error = float(np.abs(a - b).mean())
    a, b = a - a.mean(), b - b.mean()
    correlation = float(np.dot(a, b) / max(1e-8, float(np.linalg.norm(a) * np.linalg.norm(b))))
    if correlation < .85:
        return None
    if error > 22:
        # At thin native-pixel edges the two independently rasterized images
        # can have different sample phases. Compare the same fixed 3x3
        # neighbourhood on BOTH images, without moving/resizing either one.
        # Retain native structural correlation and separately verify hue so
        # smoothing cannot turn a recolored object into a valid match.
        sampled_query = cv2.GaussianBlur(query, (3, 3), .8)
        sampled_card = cv2.GaussianBlur(warped, (3, 3), .8)
        qh = cv2.cvtColor(sampled_query, cv2.COLOR_BGR2HSV).astype(np.float32)
        th = cv2.cvtColor(sampled_card, cv2.COLOR_BGR2HSV).astype(np.float32)
        colored = support & (qh[:, :, 1] >= 45) & (th[:, :, 1] >= 45)
        if int(colored.sum()) < 16:
            return None
        hue_distance = np.abs(qh[:, :, 0][colored] - th[:, :, 0][colored])
        hue_error = float(np.minimum(hue_distance, 180 - hue_distance).mean())
        if hue_error > 12:
            return None
        sa = sampled_query[support].astype(np.float32).ravel()
        sb = sampled_card[support].astype(np.float32).ravel()
        sampled_error = float(np.abs(sa - sb).mean())
        sa, sb = sa - sa.mean(), sb - sb.mean()
        sampled_correlation = float(np.dot(sa, sb) / max(1e-8, float(np.linalg.norm(sa) * np.linalg.norm(sb))))
        if sampled_error > 22 or sampled_correlation < .85:
            return None
        return {"error": sampled_error, "correlation": sampled_correlation,
                "supportPixels": int(support.sum()), "nativeError": error,
                "nativeCorrelation": correlation, "hueError": hue_error,
                "samplingModel": "SYMMETRIC_NATIVE_3X3"}
    return {"error": error, "correlation": correlation, "supportPixels": int(support.sum())}
