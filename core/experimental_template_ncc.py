# -*- coding: utf-8 -*-
"""Pure NumPy Zero-Mean Normalized Cross-Correlation (ZNCC / NCC) Module.

Experimental backend evaluation for template matching in warehouse & settlement
item recognition.

Mathematical definition:
    NCC = sum((X - mean(X)) * (T - mean(T))) / sqrt(sum((X - mean(X))^2) * sum((T - mean(T))^2))

Contracts:
- Deterministic: Identical inputs always yield identical floating point outputs.
- Finite: Outputs are guaranteed finite; NaN/Inf inputs fail closed.
- Bounded: Raw correlation strictly in [-1.0, 1.0]; normalized score in [0.0, 1.0].
- Zero-variance fail-closed: Uniform/flat crops or templates return 0.0 with fail-closed status.
- Non-mutating: Never mutates input arrays in-place.
- Memory budget: Sliding window operations calculate memory requirements upfront and
  fail closed before allocation if budget is exceeded.
- Experimental isolation: Never promoted to production default in this module.
- NCC math kernel = pure NumPy: Zero OpenCV / C++ dependencies in scoring kernel.
  Shape mismatch fails closed; preprocessing is decoupled and shared.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union
import numpy as np

SCHEMA_VERSION = "experimental-template-ncc.v1"
DEFAULT_ZERO_VARIANCE_EPS = 1e-12
DEFAULT_SLIDING_MEMORY_BUDGET_BYTES = 64 * 1024 * 1024  # 64 MB


class NccError(Exception):
    """Base exception for NCC operations."""
    pass


class NccInputValidationError(NccError):
    """Raised when input arrays fail mathematical or shape validation."""
    pass


class NccMemoryBudgetExceededError(NccError):
    """Raised when an operation would exceed the configured memory budget."""
    pass


def validate_array_finite(arr: np.ndarray, name: str = "array") -> None:
    """Ensure array contains only finite numbers (no NaN, no Inf)."""
    if not isinstance(arr, np.ndarray):
        raise NccInputValidationError(f"{name} must be a numpy ndarray, got {type(arr).__name__}")
    if arr.size == 0:
        raise NccInputValidationError(f"{name} cannot be empty")
    if not np.all(np.isfinite(arr)):
        raise NccInputValidationError(f"{name} contains NaN or Inf values")


def numpy_ncc_score(
    crop: np.ndarray,
    template: np.ndarray,
    *,
    per_channel: bool = True,
    zero_variance_eps: float = DEFAULT_ZERO_VARIANCE_EPS,
) -> Dict[str, Any]:
    """Compute Zero-Mean Normalized Cross-Correlation between a crop and a template.

    Pure NumPy math kernel. Requires identical spatial dimensions.
    Shared preprocessing should be applied prior to scoring; backend-specific
    resizing is strictly prohibited.

    Args:
        crop: Query image array (2D or 3D). Original array is NEVER mutated.
        template: Template image array (2D or 3D). Original array is NEVER mutated.
        per_channel: If True and input is 3D, zero-mean is computed per-channel
                     (matching OpenCV cv2.TM_CCOEFF_NORMED multi-channel semantics).
                     If False, overall mean across all pixels and channels is used.
        zero_variance_eps: Threshold below which array variance is treated as zero.

    Returns:
        Dict containing:
            - rawNcc: float in [-1.0, 1.0]
            - score: float in [0.0, 1.0] (clamped max(0, min(1, rawNcc)))
            - status: "EXACT_MATCH" | "SUCCESS" | "ZERO_VARIANCE_FAIL_CLOSED" | "SHAPE_MISMATCH" | "INVALID_INPUT"
            - valid: bool
            - reason: Optional descriptive status string
    """
    # 1. Input validation & non-mutation guarantee
    try:
        validate_array_finite(crop, "crop")
        validate_array_finite(template, "template")
    except NccInputValidationError as exc:
        return {
            "rawNcc": 0.0,
            "score": 0.0,
            "status": "INVALID_INPUT",
            "valid": False,
            "reason": str(exc),
        }

    # Verify matching channel count if 3D
    crop_ndim = crop.ndim
    tpl_ndim = template.ndim
    if crop_ndim not in (2, 3) or tpl_ndim not in (2, 3):
        return {
            "rawNcc": 0.0,
            "score": 0.0,
            "status": "INVALID_INPUT",
            "valid": False,
            "reason": f"Inputs must be 2D or 3D arrays, got {crop_ndim}D and {tpl_ndim}D",
        }

    if crop_ndim != tpl_ndim or (crop_ndim == 3 and crop.shape[2] != template.shape[2]):
        return {
            "rawNcc": 0.0,
            "score": 0.0,
            "status": "SHAPE_MISMATCH",
            "valid": False,
            "reason": f"Channel count mismatch: crop {crop.shape} vs template {template.shape}",
        }

    # 2. Shape alignment: handle spatial dimensions
    crop_h, crop_w = crop.shape[:2]
    tpl_h, tpl_w = template.shape[:2]

    if (crop_h, crop_w) != (tpl_h, tpl_w):
        return {
            "rawNcc": 0.0,
            "score": 0.0,
            "status": "SHAPE_MISMATCH",
            "valid": False,
            "reason": f"Spatial shape mismatch: crop {(crop_h, crop_w)} != template {(tpl_h, tpl_w)} (shared preprocessing required)",
        }

    tpl_eval = template

    # 3. Precision conversion without mutating input
    crop_f = np.asarray(crop, dtype=np.float64)
    tpl_f = np.asarray(tpl_eval, dtype=np.float64)

    # 4. Zero-mean computation
    if crop_ndim == 3 and per_channel:
        # Per-channel zero-mean matches cv2.TM_CCOEFF_NORMED multi-channel semantics
        crop_mean = np.mean(crop_f, axis=(0, 1), keepdims=True)
        tpl_mean = np.mean(tpl_f, axis=(0, 1), keepdims=True)
    else:
        # 2D or global zero-mean
        crop_mean = np.mean(crop_f)
        tpl_mean = np.mean(tpl_f)

    crop_zm = crop_f - crop_mean
    tpl_zm = tpl_f - tpl_mean

    # 5. Variance / energy calculation & zero-variance fail-closed check
    var_crop = float(np.sum(crop_zm ** 2))
    var_tpl = float(np.sum(tpl_zm ** 2))

    if var_crop <= zero_variance_eps:
        return {
            "rawNcc": 0.0,
            "score": 0.0,
            "status": "ZERO_VARIANCE_FAIL_CLOSED",
            "valid": False,
            "reason": "ZERO_VARIANCE_CROP",
        }

    if var_tpl <= zero_variance_eps:
        return {
            "rawNcc": 0.0,
            "score": 0.0,
            "status": "ZERO_VARIANCE_FAIL_CLOSED",
            "valid": False,
            "reason": "ZERO_VARIANCE_TEMPLATE",
        }

    # 6. Cross-correlation numerator and denominator
    num = float(np.sum(crop_zm * tpl_zm))
    denom = math.sqrt(var_crop * var_tpl)

    if denom <= 0.0 or not math.isfinite(denom):
        return {
            "rawNcc": 0.0,
            "score": 0.0,
            "status": "ZERO_VARIANCE_FAIL_CLOSED",
            "valid": False,
            "reason": "NON_POSITIVE_DENOMINATOR",
        }

    raw_ncc = num / denom
    # Strict clamping to theoretical mathematical bounds [-1.0, 1.0]
    raw_ncc = max(-1.0, min(1.0, raw_ncc))

    # Normalized score matching production [0.0, 1.0] range
    score = max(0.0, min(1.0, raw_ncc))

    status = "EXACT_MATCH" if abs(raw_ncc - 1.0) < 1e-6 else "SUCCESS"

    return {
        "rawNcc": round(raw_ncc, 6),
        "score": round(score, 4),
        "status": status,
        "valid": True,
        "reason": None,
        "varianceCrop": var_crop,
        "varianceTemplate": var_tpl,
    }


def numpy_sliding_ncc(
    image: np.ndarray,
    template: np.ndarray,
    *,
    memory_budget_bytes: int = DEFAULT_SLIDING_MEMORY_BUDGET_BYTES,
    zero_variance_eps: float = DEFAULT_ZERO_VARIANCE_EPS,
) -> Dict[str, Any]:
    """Compute sliding window NCC with strict pre-allocation memory budget enforcement.

    Guarantees:
    - Never allocates huge unstrided sliding views that exceed memory budget.
    - Fails closed with MEMORY_BUDGET_EXCEEDED if estimated intermediate bytes exceed budget.
    - Zero variance in template or all subwindows fails closed cleanly.
    """
    try:
        validate_array_finite(image, "image")
        validate_array_finite(template, "template")
    except NccInputValidationError as exc:
        return {
            "ok": False,
            "status": "INVALID_INPUT",
            "reason": str(exc),
            "correlationMap": None,
        }

    img_h, img_w = image.shape[:2]
    tpl_h, tpl_w = template.shape[:2]

    if tpl_h > img_h or tpl_w > img_w:
        return {
            "ok": False,
            "status": "TEMPLATE_LARGER_THAN_IMAGE",
            "reason": f"Template {(tpl_h, tpl_w)} is larger than image {(img_h, img_w)}",
            "correlationMap": None,
        }

    channels = image.shape[2] if image.ndim == 3 else 1
    out_h = img_h - tpl_h + 1
    out_w = img_w - tpl_w + 1

    # Estimate bytes required if naive sliding_window_view were materialized
    # out_h * out_w * tpl_h * tpl_w * channels * 8 bytes (float64)
    naive_materialized_bytes = out_h * out_w * tpl_h * tpl_w * channels * 8

    # Memory budget fail-closed contract
    if naive_materialized_bytes > memory_budget_bytes:
        return {
            "ok": False,
            "status": "MEMORY_BUDGET_EXCEEDED",
            "reason": (
                f"Sliding window intermediate array would require {naive_materialized_bytes} bytes, "
                f"exceeding memory budget of {memory_budget_bytes} bytes."
            ),
            "estimatedBytes": naive_materialized_bytes,
            "memoryBudgetBytes": memory_budget_bytes,
            "correlationMap": None,
        }

    # Template zero-mean and variance
    tpl_f = np.asarray(template, dtype=np.float64)
    if template.ndim == 3:
        tpl_zm = tpl_f - np.mean(tpl_f, axis=(0, 1), keepdims=True)
    else:
        tpl_zm = tpl_f - np.mean(tpl_f)
    var_tpl = float(np.sum(tpl_zm ** 2))

    if var_tpl <= zero_variance_eps:
        return {
            "ok": False,
            "status": "ZERO_VARIANCE_FAIL_CLOSED",
            "reason": "ZERO_VARIANCE_TEMPLATE",
            "correlationMap": None,
        }

    # Safe iterative window evaluation within budget
    corr_map = np.zeros((out_h, out_w), dtype=np.float32)
    img_f = np.asarray(image, dtype=np.float64)

    for y in range(out_h):
        for x in range(out_w):
            sub = img_f[y:y + tpl_h, x:x + tpl_w]
            if image.ndim == 3:
                sub_zm = sub - np.mean(sub, axis=(0, 1), keepdims=True)
            else:
                sub_zm = sub - np.mean(sub)
            var_sub = float(np.sum(sub_zm ** 2))
            if var_sub <= zero_variance_eps:
                corr_map[y, x] = 0.0
                continue
            denom = math.sqrt(var_sub * var_tpl)
            val = float(np.sum(sub_zm * tpl_zm)) / denom
            corr_map[y, x] = max(-1.0, min(1.0, val))

    max_val = float(np.max(corr_map)) if corr_map.size > 0 else 0.0
    min_val = float(np.min(corr_map)) if corr_map.size > 0 else 0.0

    return {
        "ok": True,
        "status": "SUCCESS",
        "reason": None,
        "outShape": (out_h, out_w),
        "maxScore": round(max(0.0, min(1.0, max_val)), 4),
        "rawMaxNcc": round(max_val, 6),
        "rawMinNcc": round(min_val, 6),
        "correlationMap": corr_map,
        "estimatedBytes": naive_materialized_bytes,
        "memoryBudgetBytes": memory_budget_bytes,
    }
