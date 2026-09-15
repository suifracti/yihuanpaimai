# -*- coding: utf-8 -*-
"""Mathematical Metrics Calculation Library for Evaluation Artifacts.

Provides pure functions for calculating formal and exploratory metrics:
- Point metrics: MAE, Median AE, Signed Bias, MARE (Mean Absolute Relative Error).
- Underestimation metrics: Underestimation rate (>10%), Catastrophic underestimation rate (>20%).
- Quantile metrics: P20 lower-tail coverage, P80 upper-tail coverage, Central 60% prediction interval coverage.

Guarantees:
- Zero-sample input strictly returns None (never returns 0 or 0%).
- Div-by-zero safe.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence


def calculate_point_and_quantile_metrics(
    samples: Sequence[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Calculate point and quantile metrics from a sequence of sample records.

    Each sample mapping is expected to have:
    - 'actual': float (positive finite)
    - 'estimate': float (finite)
    - Optional 'p20': float
    - Optional 'p50': float
    - Optional 'p80': float
    """
    if not samples:
        return None

    valid_point_samples = []
    valid_quantile_samples = []

    for s in samples:
        actual = s.get("actual")
        estimate = s.get("estimate")

        if (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and math.isfinite(actual)
            and actual > 0
            and isinstance(estimate, (int, float))
            and not isinstance(estimate, bool)
            and math.isfinite(estimate)
        ):
            valid_point_samples.append((float(actual), float(estimate)))

            p20 = s.get("p20")
            p50 = s.get("p50")
            p80 = s.get("p80")
            if (
                isinstance(p20, (int, float))
                and isinstance(p50, (int, float))
                and isinstance(p80, (int, float))
                and not isinstance(p20, bool)
                and not isinstance(p50, bool)
                and not isinstance(p80, bool)
                and math.isfinite(p20)
                and math.isfinite(p50)
                and math.isfinite(p80)
            ):
                valid_quantile_samples.append((float(actual), float(p20), float(p50), float(p80)))

    n_point = len(valid_point_samples)
    if n_point == 0:
        return None

    # Point error calculations
    abs_errors = [abs(act - est) for act, est in valid_point_samples]
    signed_errors = [est - act for act, est in valid_point_samples]
    relative_errors = [abs(act - est) / act for act, est in valid_point_samples]
    underestimates = [max(0.0, (act - est) / act) for act, est in valid_point_samples]

    sorted_abs = sorted(abs_errors)
    mid = n_point // 2
    if n_point % 2 == 1:
        median_ae = sorted_abs[mid]
    else:
        median_ae = (sorted_abs[mid - 1] + sorted_abs[mid]) / 2.0

    mae = sum(abs_errors) / n_point
    signed_bias = sum(signed_errors) / n_point
    mare = sum(relative_errors) / n_point

    underestimate_rate_10 = sum(1 for u in underestimates if u > 0.10) / n_point
    underestimate_rate_20 = sum(1 for u in underestimates if u > 0.20) / n_point

    metrics_out: Dict[str, Any] = {
        "sampleCount": n_point,
        "mae": round(mae, 2),
        "medianAe": round(median_ae, 2),
        "signedBias": round(signed_bias, 2),
        "mare": round(mare, 4),
        "underestimateRate10": round(underestimate_rate_10, 4),
        "underestimateRate20": round(underestimate_rate_20, 4),
    }

    # Quantile calculations (P20, P80, Central 60% prediction interval)
    n_quantiles = len(valid_quantile_samples)
    if n_quantiles > 0:
        p20_tail_hits = sum(1 for act, p20, _, _ in valid_quantile_samples if act <= p20)
        p80_tail_hits = sum(1 for act, _, _, p80 in valid_quantile_samples if act <= p80)
        central_60_hits = sum(1 for act, p20, _, p80 in valid_quantile_samples if p20 <= act <= p80)

        metrics_out["quantileSampleCount"] = n_quantiles
        metrics_out["p20LowerTailCoverage"] = round(p20_tail_hits / n_quantiles, 4)
        metrics_out["p80UpperTailCoverage"] = round(p80_tail_hits / n_quantiles, 4)
        metrics_out["central60PredictionIntervalCoverage"] = round(central_60_hits / n_quantiles, 4)
    else:
        metrics_out["quantileSampleCount"] = 0
        metrics_out["p20LowerTailCoverage"] = None
        metrics_out["p80UpperTailCoverage"] = None
        metrics_out["central60PredictionIntervalCoverage"] = None

    return metrics_out
