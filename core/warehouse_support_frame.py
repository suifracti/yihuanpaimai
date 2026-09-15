"""Verify stationary, distinct warehouse frames without claiming scroll progress."""
import hashlib
from typing import Any, Optional
import numpy as np


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
