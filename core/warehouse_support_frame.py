"""Verify stationary, distinct warehouse frames without claiming scroll progress."""
import hashlib
from typing import Any, Optional
import numpy as np


def same_viewport_proof(previous: Any, current: Any) -> Optional[dict]:
    """Same observed viewport while settlement reveal is still animating.

    The scrollbar shows the same thumb in the same track and the grid keeps the
    same column spacing, while item pixels differ because items are appearing in
    place. Vertical scrolling cannot preserve both, so this is a coverage-only
    link: it never grants item identity and never measures displacement.
    """
    if previous is None or current is None or previous.shape != current.shape or previous.size == 0:
        return None
    if np.array_equal(previous, current):
        return None
    from warehouse_grid_geometry import observe_warehouse_grid
    from warehouse_scrollbar_observation import observe_warehouse_scrollbar
    before = observe_warehouse_scrollbar(previous, already_cropped=True)
    after = observe_warehouse_scrollbar(current, already_cropped=True)
    if (before.get('trackBox') is None or before.get('trackBox') != after.get('trackBox')
            or before.get('thumbBox') is None or before.get('thumbBox') != after.get('thumbBox')
            or before.get('scrollState') != after.get('scrollState')):
        return None
    ga = observe_warehouse_grid(previous, already_cropped=True)['grid']
    gb = observe_warehouse_grid(current, already_cropped=True)['grid']
    if (ga['status'] != 'OK' or gb['status'] != 'OK'
            or ga['columnCount'] != gb['columnCount']
            or abs(ga['cellWidth'] - gb['cellWidth']) > 1
            or abs(ga['cellHeight'] - gb['cellHeight']) > 1
            or len(ga['xLines']) != len(gb['xLines'])
            or np.max(np.abs(np.diff(ga['xLines']) - np.diff(gb['xLines']))) > 1):
        return None
    digest_a = hashlib.sha256(previous.tobytes()).hexdigest()
    digest_b = hashlib.sha256(current.tobytes()).hexdigest()
    return {"status": "UNVERIFIED", "direction": "NONE", "verticalOffsetPx": 0,
            "reason": "SAME_VIEWPORT_ANIMATING", "progressionVerified": False,
            "sameViewportVerified": True, "identitySupportVerified": False,
            "proofId": f"same-viewport:{digest_a}:{digest_b}"}


def stationary_support_proof(previous: Any, current: Any) -> Optional[dict]:
    if previous is None or current is None or previous.shape != current.shape or previous.size == 0:
        return None
    if np.array_equal(previous, current):
        return None
    a, b = previous.astype(np.float32), current.astype(np.float32)
    if float(a.std()) < 8 or float(b.std()) < 8:
        return None
    error = np.abs(a-b)
    if float(error.mean()) > 1.5:
        return None
    for tile in np.array_split(error, 3, axis=0):
        if any(float(part.mean()) > 3.0 for part in np.array_split(tile, 3, axis=1)):
            return None
    correlation = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
    if not np.isfinite(correlation) or correlation < 0.99:
        return None
    digest_a = hashlib.sha256(previous.tobytes()).hexdigest()
    digest_b = hashlib.sha256(current.tobytes()).hexdigest()
    return {"status": "UNVERIFIED", "direction": "NONE", "verticalOffsetPx": 0,
            "reason": "NO_MOVEMENT", "progressionVerified": False,
            "identitySupportVerified": True, "confidence": correlation,
            "proofId": f"stationary:{digest_a}:{digest_b}"}
