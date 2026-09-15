# -*- coding: utf-8 -*-
"""Offline Quantile Calibration Experiment v1.

Harness for evaluating time-safe, out-of-sample calibration methods for historical
Neverness to Everness (异环) auction prediction quantiles.

Proper Scoring Rules:
- Quantile Pinball Loss (tau = 0.20, 0.50, 0.80)
- Winkler Interval Score for central 60% interval (alpha = 0.40)
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
sys.path.insert(0, str(CORE_DIR))
sys.path.insert(0, str(APP_DIR))

from history_admission import build_duplicate_index
from legacy_exploratory_policy import classify_legacy_record


# -----------------------------------------------------------------------------
# 1. Proper Scoring Rules & Evaluation Utilities
# -----------------------------------------------------------------------------

def pinball_loss(y: float, q: float, tau: float) -> float:
    """Quantile pinball loss: (y - q) * (tau - I(y < q))."""
    diff = y - q
    if diff >= 0:
        return tau * diff
    else:
        return (tau - 1.0) * diff


def winkler_interval_score(lower: float, upper: float, y: float, alpha: float = 0.40) -> float:
    """Winkler proper interval score for (1-alpha) central prediction interval.

    For central 60% interval, alpha = 0.40.
    Score = (upper - lower) + (2/alpha) * (lower - y) * I(y < lower) + (2/alpha) * (y - upper) * I(y > upper).
    """
    width = max(0.0, upper - lower)
    penalty_multiplier = 2.0 / alpha  # 5.0 for alpha=0.40
    if y < lower:
        return width + penalty_multiplier * (lower - y)
    elif y > upper:
        return width + penalty_multiplier * (y - upper)
    else:
        return width


def wilson_score_interval(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score 95% confidence interval for binomial proportion."""
    if n <= 0:
        return (0.0, 0.0)
    p_hat = k / n
    denom = 1.0 + (z**2) / n
    center = (p_hat + (z**2) / (2.0 * n)) / denom
    margin = (z * math.sqrt((p_hat * (1.0 - p_hat) / n) + (z**2) / (4.0 * (n**2)))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


# -----------------------------------------------------------------------------
# 2. Data Ingestion & Sample Provenance Audit
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class QuantileSample:
    sample_id: str
    played_at: str
    timestamp_epoch: float
    actual: float
    p20: float
    p50: float
    p80: float
    model_version: str
    solver_version: str
    catalog_version: str
    target_provenance: str
    solver_status: str
    q: Optional[int]
    venue: Optional[str]
    box: Optional[str]
    box_type: Optional[str]
    field_condition: Optional[str]
    known_gold_count: Optional[int]
    known_red_count: Optional[int]


def load_all_exploratory_samples(db_path: Path) -> Tuple[List[QuantileSample], List[Dict[str, Any]], Dict[str, Any]]:
    """Load and audit all legacy records, separating quantile samples and point samples."""
    raw_data = json.loads(db_path.read_text(encoding="utf-8"))
    records = raw_data.get("records") or []

    dup_idx = build_duplicate_index(records)
    classifications = [classify_legacy_record(r, dup_idx) for r in records]

    all_point_samples: List[Dict[str, Any]] = []
    quantile_samples: List[QuantileSample] = []

    for r, c in zip(records, classifications):
        if not c.is_point_candidate:
            continue

        sv = c.solver_version or "unknown"
        mv = c.model_version or "unknown"
        cv = c.catalog_version or "unknown"

        if mv == "v0.5-field-conditions" or sv == "v0.6-reliability":
            target_prov = "TARGET_PROVEN_COMPATIBLE"
        elif mv in ("v0.3-dynamic-walkforward", "v7-hard-floor-residual"):
            target_prov = "TARGET_LIKELY_COMPATIBLE"
        else:
            target_prov = "TARGET_AMBIGUOUS"

        played_at_str = r.get("playedAt") or "1970-01-01T00:00:00"
        try:
            # Parse ISO or simple timestamp
            cleaned_ts = played_at_str.replace("Z", "+00:00")
            epoch = datetime.fromisoformat(cleaned_ts).timestamp()
        except Exception:
            epoch = 0.0

        top_ss = r.get("solverStatus")
        pred_dict = r.get("prediction") or r.get("frozenPrediction") or {}
        pred_ss = pred_dict.get("solverStatus") if isinstance(pred_dict, dict) else None
        eff_solver_status = top_ss or pred_ss or "unknown"

        point_entry = {
            "id": c.record_id,
            "playedAt": played_at_str,
            "epoch": epoch,
            "actual": c.actual_total,
            "estimate": c.point_estimate,
            "p20": c.p20,
            "p50": c.p50,
            "p80": c.p80,
            "modelVersion": mv,
            "solverVersion": sv,
            "targetProvenance": target_prov,
            "solverStatus": eff_solver_status,
            "isQuantile": c.is_quantile_candidate,
            "q": r.get("q"),
            "venue": r.get("venue"),
            "box": r.get("box"),
            "fieldCondition": r.get("fieldCondition"),
        }
        all_point_samples.append(point_entry)

        if c.is_quantile_candidate and c.p20 is not None and c.p50 is not None and c.p80 is not None:
            # Extract ex-ante features
            q_val = r.get("q")
            known_g = len((r.get("knownGold") or "").split()) if r.get("knownGold") else 0
            known_r = len((r.get("knownRed") or "").split()) if r.get("knownRed") else 0

            qs = QuantileSample(
                sample_id=c.record_id,
                played_at=played_at_str,
                timestamp_epoch=epoch,
                actual=float(c.actual_total),
                p20=float(c.p20),
                p50=float(c.p50),
                p80=float(c.p80),
                model_version=mv,
                solver_version=sv,
                catalog_version=cv,
                target_provenance=target_prov,
                solver_status=eff_solver_status,
                q=q_val if isinstance(q_val, int) else None,
                venue=r.get("venue"),
                box=r.get("box"),
                box_type=r.get("boxType"),
                field_condition=r.get("fieldCondition"),
                known_gold_count=known_g,
                known_red_count=known_r,
            )
            quantile_samples.append(qs)

    # Sort chronological
    quantile_samples.sort(key=lambda s: s.timestamp_epoch)
    all_point_samples.sort(key=lambda s: s["epoch"])

    audit_summary = {
        "totalRecords": len(records),
        "admittedCount": sum(1 for c in classifications if c.is_admitted),
        "pointCandidateCount": len(all_point_samples),
        "quantileCandidateCount": len(quantile_samples),
        "targetProvenanceCounts": dict(Counter(s["targetProvenance"] for s in all_point_samples)),
        "cohortDistribution": dict(Counter(s.model_version for s in quantile_samples)),
    }

    return quantile_samples, all_point_samples, audit_summary


# -----------------------------------------------------------------------------
# 3. Methodological Closeout: Detailed Linear & Robust Regressions
# -----------------------------------------------------------------------------

def compute_detailed_calibration_regression(samples: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute OLS slope/intercept with parametric, bootstrap, and Theil-Sen CIs."""
    n = len(samples)
    if n < 3:
        return {"n": n, "status": "INSUFFICIENT_SAMPLES"}

    xs = [s["estimate"] for s in samples]
    ys = [s["actual"] for s in samples]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    ss_xx = sum((x - mean_x)**2 for x in xs)
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    ss_yy = sum((y - mean_y)**2 for y in ys)

    slope_ols = ss_xy / ss_xx if ss_xx > 0 else 1.0
    int_ols = mean_y - slope_ols * mean_x

    # Residuals & OLS standard errors
    residuals = [y - (int_ols + slope_ols * x) for x, y in zip(xs, ys)]
    s2 = sum(r**2 for r in residuals) / (n - 2)
    se_slope = math.sqrt(s2 / ss_xx) if ss_xx > 0 and s2 > 0 else 0.0
    se_int = math.sqrt(s2 * (1.0 / n + (mean_x**2) / ss_xx)) if ss_xx > 0 and s2 > 0 else 0.0

    t_crit = 2.086 if n <= 20 else (2.00 if n <= 60 else 1.96)
    ols_slope_ci = (slope_ols - t_crit * se_slope, slope_ols + t_crit * se_slope)
    ols_int_ci = (int_ols - t_crit * se_int, int_ols + t_crit * se_int)

    # Bootstrap 95% CI (2,000 replicates)
    random.seed(42)
    boot_slopes = []
    boot_ints = []
    for _ in range(2000):
        b_sample = [random.choice(samples) for _ in range(n)]
        bx = [s["estimate"] for s in b_sample]
        by = [s["actual"] for s in b_sample]
        bmx = sum(bx) / n
        bmy = sum(by) / n
        bss_xx = sum((x - bmx)**2 for x in bx)
        bss_xy = sum((x - bmx) * (y - bmy) for x, y in zip(bx, by))
        bs = bss_xy / bss_xx if bss_xx > 0 else slope_ols
        bi = bmy - bs * bmx
        boot_slopes.append(bs)
        boot_ints.append(bi)

    boot_slopes.sort()
    boot_ints.sort()
    boot_slope_ci = (boot_slopes[50], boot_slopes[1950])
    boot_int_ci = (boot_ints[50], boot_ints[1950])

    # Theil-Sen Robust Estimator
    ts_slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[j] - xs[i]
            if abs(dx) > 1e-5:
                ts_slopes.append((ys[j] - ys[i]) / dx)
    ts_slope = sorted(ts_slopes)[len(ts_slopes)//2] if ts_slopes else slope_ols
    ts_intercept = sorted([y - ts_slope * x for x, y in zip(xs, ys)])[n//2]

    # Pearson & Spearman
    r_pearson = ss_xy / (math.sqrt(ss_xx) * math.sqrt(ss_yy)) if ss_xx > 0 and ss_yy > 0 else 0.0

    def rank_array(arr):
        indexed = sorted(enumerate(arr), key=lambda x: x[1])
        ranks = [0.0] * len(arr)
        for r_idx, (orig_i, _) in enumerate(indexed, 1):
            ranks[orig_i] = float(r_idx)
        return ranks

    rx = rank_array(xs)
    ry = rank_array(ys)
    m_rx = (n + 1) / 2.0
    ss_rxry = sum((a - m_rx) * (b - m_rx) for a, b in zip(rx, ry))
    ss_rx = sum((a - m_rx)**2 for a in rx)
    ss_ry = sum((b - m_rx)**2 for b in ry)
    rho_spearman = ss_rxry / (math.sqrt(ss_rx) * math.sqrt(ss_ry)) if ss_rx > 0 and ss_ry > 0 else 0.0

    # Verdict on slope > 1:
    slope_strictly_gt_1 = (ols_slope_ci[0] > 1.0 and boot_slope_ci[0] > 1.0 and ts_slope > 1.0)
    slope_includes_1 = (ols_slope_ci[0] <= 1.0 <= ols_slope_ci[1] or boot_slope_ci[0] <= 1.0 <= boot_slope_ci[1])

    if slope_strictly_gt_1:
        slope_verdict = "SUPPORTED_RANGE_COMPRESSION"
    elif slope_includes_1:
        slope_verdict = "SLOPE_INCLUDES_1_INSUFFICIENT_STANDALONE_COMPRESSION_EVIDENCE"
    else:
        slope_verdict = "PROVISIONAL"

    return {
        "n": n,
        "ols": {
            "slope": round(slope_ols, 4),
            "intercept": round(int_ols, 2),
            "slope_95_ci": [round(ols_slope_ci[0], 4), round(ols_slope_ci[1], 4)],
            "intercept_95_ci": [round(ols_int_ci[0], 2), round(ols_int_ci[1], 2)],
        },
        "bootstrap": {
            "slope_95_ci": [round(boot_slope_ci[0], 4), round(boot_slope_ci[1], 4)],
            "intercept_95_ci": [round(boot_int_ci[0], 2), round(boot_int_ci[1], 2)],
        },
        "theil_sen_robust": {
            "slope": round(ts_slope, 4),
            "intercept": round(ts_intercept, 2),
        },
        "correlations": {
            "pearson_r": round(r_pearson, 4),
            "spearman_rho": round(rho_spearman, 4),
        },
        "slope_verdict": slope_verdict,
    }


# -----------------------------------------------------------------------------
# 4. Error Concentration & Heavy-Tail Breakdown
# -----------------------------------------------------------------------------

def analyze_heavy_tail_and_error_concentration(samples: Sequence[QuantileSample]) -> Dict[str, Any]:
    """Analyze residual distribution, tail percentiles, and top-tail absolute error contribution."""
    n = len(samples)
    if n == 0:
        return {}

    abs_errors = [abs(s.actual - s.p50) for s in samples]
    signed_residuals = [s.p50 - s.actual for s in samples]  # prediction - actual
    sorted_abs = sorted(abs_errors, reverse=True)
    sorted_signed = sorted(signed_residuals)

    total_abs_err = sum(abs_errors)
    top1_share = (sorted_abs[0] / total_abs_err) if total_abs_err > 0 else 0.0
    top5_share = (sum(sorted_abs[:5]) / total_abs_err) if total_abs_err > 0 else 0.0
    top10_share = (sum(sorted_abs[:10]) / total_abs_err) if total_abs_err > 0 else 0.0

    p50_signed_res = sorted_signed[int(0.50 * n)]
    p80_abs_err = sorted_abs[int(0.20 * n)]
    p90_abs_err = sorted_abs[int(0.10 * n)]
    p95_abs_err = sorted_abs[int(0.05 * n)]

    underestimates = [max(0.0, (s.actual - s.p50) / s.actual) for s in samples]
    max_underest = max(underestimates) if underestimates else 0.0

    return {
        "sampleCount": n,
        "meanAbsoluteError": round(total_abs_err / n, 2),
        "medianSignedResidual": round(p50_signed_res, 2),
        "meanSignedResidual": round(sum(signed_residuals) / n, 2),
        "errorConcentration": {
            "top1WorstMissShare": round(top1_share, 4),
            "top5WorstMissShare": round(top5_share, 4),
            "top10WorstMissShare": round(top10_share, 4),
        },
        "tailPercentiles": {
            "p80AbsoluteError": round(p80_abs_err, 2),
            "p90AbsoluteError": round(p90_abs_err, 2),
            "p95AbsoluteError": round(p95_abs_err, 2),
            "maxUnderestimationRate": round(max_underest, 4),
        },
    }


# -----------------------------------------------------------------------------
# 5. Out-of-Sample Calibration Models (E0 ~ E4)
# -----------------------------------------------------------------------------

def evaluate_predictions_proper_scores(
    actuals: Sequence[float],
    p20s: Sequence[float],
    p50s: Sequence[float],
    p80s: Sequence[float],
) -> Dict[str, Any]:
    """Compute all proper scores and calibration statistics on a batch of test predictions."""
    n = len(actuals)
    if n == 0:
        return {}

    pb20 = [pinball_loss(y, q, 0.20) for y, q in zip(actuals, p20s)]
    pb50 = [pinball_loss(y, q, 0.50) for y, q in zip(actuals, p50s)]
    pb80 = [pinball_loss(y, q, 0.80) for y, q in zip(actuals, p80s)]
    mean_pb = [(a + b + c) / 3.0 for a, b, c in zip(pb20, pb50, pb80)]

    winkler_scores = [winkler_interval_score(l, u, y, alpha=0.40) for l, u, y in zip(p20s, p80s, actuals)]

    k20 = sum(1 for y, q in zip(actuals, p20s) if y <= q)
    k50 = sum(1 for y, q in zip(actuals, p50s) if y <= q)
    k80 = sum(1 for y, q in zip(actuals, p80s) if y <= q)
    kc60 = sum(1 for y, l, u in zip(actuals, p20s, p80s) if l <= y <= u)

    widths = [max(0.0, u - l) for l, u in zip(p20s, p80s)]
    norm_widths = [w / p for w, p in zip(widths, p50s) if p > 0]

    abs_errs = [abs(y - p) for y, p in zip(actuals, p50s)]
    rel_errs = [abs(y - p) / y for y, p in zip(actuals, p50s) if y > 0]
    underests = [max(0.0, (y - p) / y) for y, p in zip(actuals, p50s) if y > 0]

    ci20 = wilson_score_interval(k20, n)
    ci50 = wilson_score_interval(k50, n)
    ci80 = wilson_score_interval(k80, n)
    cic60 = wilson_score_interval(kc60, n)

    return {
        "n": n,
        "meanPinballLoss20": round(sum(pb20) / n, 2),
        "meanPinballLoss50": round(sum(pb50) / n, 2),
        "meanPinballLoss80": round(sum(pb80) / n, 2),
        "meanTotalPinballLoss": round(sum(mean_pb) / n, 2),
        "meanWinklerIntervalScore": round(sum(winkler_scores) / n, 2),
        "empiricalFP20": round(k20 / n, 4),
        "empiricalFP50": round(k50 / n, 4),
        "empiricalFP80": round(k80 / n, 4),
        "central60Coverage": round(kc60 / n, 4),
        "wilson95CiCentral60": [round(cic60[0], 4), round(cic60[1], 4)],
        "wilson95CiP80": [round(ci80[0], 4), round(ci80[1], 4)],
        "medianWidth": round(sorted(widths)[n//2], 2),
        "medianNormalizedWidth": round(sorted(norm_widths)[len(norm_widths)//2], 4) if norm_widths else 0.0,
        "p50Mae": round(sum(abs_errs) / n, 2),
        "p50Mare": round(sum(rel_errs) / len(rel_errs), 4) if rel_errs else 0.0,
        "underestimateRate10": round(sum(1 for u in underests if u > 0.10) / len(underests), 4) if underests else 0.0,
        "underestimateRate20": round(sum(1 for u in underests if u > 0.20) / len(underests), 4) if underests else 0.0,
    }


def run_time_safe_walk_forward_experiment(
    samples: List[QuantileSample],
    min_train_size: int = 15,
) -> Dict[str, Any]:
    """Execute time-safe walk-forward cross-validation comparing E0 ~ E4.

    Evaluates across sequential folds: train on historical samples, test on future batch.
    Never leaks future samples to training folds.
    """
    n_total = len(samples)
    if n_total < min_train_size + 5:
        return {"status": "INSUFFICIENT_SAMPLES_FOR_WALK_FORWARD", "n": n_total}

    # Split into 4 expanding walk-forward test folds
    step = max(5, (n_total - min_train_size) // 4)
    fold_splits = []
    curr_train = min_train_size
    while curr_train < n_total:
        test_end = min(n_total, curr_train + step)
        fold_splits.append((curr_train, test_end))
        if test_end == n_total:
            break
        curr_train = test_end

    results_by_model: Dict[str, List[Dict[str, Any]]] = {
        "E0_Baseline": [],
        "E1_SymmetricWidthScaling": [],
        "E2_AsymmetricUpperTailScaling": [],
        "E3_EmpiricalResidualCalibration": [],
        "E4_FeatureConditionedScaling": [],
    }

    # Record all out-of-sample predictions across folds
    test_actuals: List[float] = []
    oos_preds: Dict[str, Dict[str, List[float]]] = {
        m: {"p20": [], "p50": [], "p80": []} for m in results_by_model
    }

    for fold_idx, (train_end, test_end) in enumerate(fold_splits, 1):
        train_set = samples[:train_end]
        test_set = samples[train_end:test_end]

        test_actuals.extend([s.actual for s in test_set])

        # --- E0: Baseline ---
        for s in test_set:
            oos_preds["E0_Baseline"]["p20"].append(s.p20)
            oos_preds["E0_Baseline"]["p50"].append(s.p50)
            oos_preds["E0_Baseline"]["p80"].append(s.p80)

        # --- E1: Symmetric Width Scaling (Learn scale 'a' on train set to optimize Winkler Score) ---
        best_a = 1.0
        best_e1_score = float("inf")
        for candidate_a_10 in range(8, 32, 2):  # a = 0.8 ~ 3.0
            a_val = candidate_a_10 / 10.0
            train_scores = [
                winkler_interval_score(
                    s.p50 - a_val * (s.p50 - s.p20),
                    s.p50 + a_val * (s.p80 - s.p50),
                    s.actual,
                    alpha=0.40,
                )
                for s in train_set
            ]
            mean_sc = sum(train_scores) / len(train_scores)
            if mean_sc < best_e1_score:
                best_e1_score = mean_sc
                best_a = a_val

        for s in test_set:
            oos_preds["E1_SymmetricWidthScaling"]["p20"].append(max(0.0, s.p50 - best_a * (s.p50 - s.p20)))
            oos_preds["E1_SymmetricWidthScaling"]["p50"].append(s.p50)
            oos_preds["E1_SymmetricWidthScaling"]["p80"].append(s.p50 + best_a * (s.p80 - s.p50))

        # --- E2: Asymmetric Upper-Tail Scaling (Learn a_L and a_U separately on train set) ---
        best_a_l = 1.0
        best_a_u = 1.0
        best_e2_score = float("inf")
        for al_10 in [8, 10, 12]:
            al_val = al_10 / 10.0
            for au_10 in [10, 14, 18, 22, 26, 30]:
                au_val = au_10 / 10.0
                train_scores = [
                    winkler_interval_score(
                        s.p50 - al_val * (s.p50 - s.p20),
                        s.p50 + au_val * (s.p80 - s.p50),
                        s.actual,
                        alpha=0.40,
                    )
                    for s in train_set
                ]
                mean_sc = sum(train_scores) / len(train_scores)
                if mean_sc < best_e2_score:
                    best_e2_score = mean_sc
                    best_a_l = al_val
                    best_a_u = au_val

        for s in test_set:
            oos_preds["E2_AsymmetricUpperTailScaling"]["p20"].append(max(0.0, s.p50 - best_a_l * (s.p50 - s.p20)))
            oos_preds["E2_AsymmetricUpperTailScaling"]["p50"].append(s.p50)
            oos_preds["E2_AsymmetricUpperTailScaling"]["p80"].append(s.p50 + best_a_u * (s.p80 - s.p50))

        # --- E3: Empirical Residual Calibration (Use train residuals q20 and q80) ---
        train_res = [s.actual - s.p50 for s in train_set]
        sorted_res = sorted(train_res)
        n_tr = len(sorted_res)
        res_q20 = sorted_res[int(0.20 * n_tr)]
        res_q80 = sorted_res[int(0.80 * n_tr)]

        for s in test_set:
            oos_preds["E3_EmpiricalResidualCalibration"]["p20"].append(max(0.0, s.p50 + res_q20))
            oos_preds["E3_EmpiricalResidualCalibration"]["p50"].append(s.p50)
            oos_preds["E3_EmpiricalResidualCalibration"]["p80"].append(s.p50 + res_q80)

        # --- E4: Feature-Conditioned Calibration (Higher upper expansion for q >= 12 or high-tier boxes) ---
        # Learn high-Q vs low-Q upper scale
        train_high_q = [s for s in train_set if (s.q or 0) >= 12 or s.box == "珠宝箱"]
        train_low_q = [s for s in train_set if (s.q or 0) < 12 and s.box != "珠宝箱"]

        def opt_au(sub):
            if len(sub) < 3:
                return best_a_u
            b_sc = float("inf")
            b_u = 1.0
            for u_10 in [10, 14, 18, 22, 26, 30]:
                u_val = u_10 / 10.0
                scs = [winkler_interval_score(s.p50 - 1.0 * (s.p50 - s.p20), s.p50 + u_val * (s.p80 - s.p50), s.actual, alpha=0.40) for s in sub]
                m_sc = sum(scs) / len(scs)
                if m_sc < b_sc:
                    b_sc = m_sc
                    b_u = u_val
            return b_u

        au_high = opt_au(train_high_q)
        au_low = opt_au(train_low_q)

        for s in test_set:
            is_high = ((s.q or 0) >= 12 or s.box == "珠宝箱")
            au_chosen = au_high if is_high else au_low
            oos_preds["E4_FeatureConditionedScaling"]["p20"].append(max(0.0, s.p50 - 1.0 * (s.p50 - s.p20)))
            oos_preds["E4_FeatureConditionedScaling"]["p50"].append(s.p50)
            oos_preds["E4_FeatureConditionedScaling"]["p80"].append(s.p50 + au_chosen * (s.p80 - s.p50))

    # Evaluate Overall Out-of-Sample Proper Scores
    overall_evaluation = {}
    for model_name, preds in oos_preds.items():
        scores = evaluate_predictions_proper_scores(
            test_actuals,
            preds["p20"],
            preds["p50"],
            preds["p80"],
        )
        overall_evaluation[model_name] = scores

    return {
        "totalSamplesEvaluated": len(test_actuals),
        "foldCount": len(fold_splits),
        "foldSplits": fold_splits,
        "models": overall_evaluation,
    }


# -----------------------------------------------------------------------------
# 6. Main Execution Pipeline & Reporting
# -----------------------------------------------------------------------------

def run_experiment_suite():
    db_path = PROJECT_ROOT / "异环拍卖数据.json"
    quantile_samples, point_samples, audit_summary = load_all_exploratory_samples(db_path)

    # 1. Cleaner Subset Exact Audit & Regressions
    cleaner_point_samples = [s for s in point_samples if s["targetProvenance"] in ("TARGET_PROVEN_COMPATIBLE", "TARGET_LIKELY_COMPATIBLE") and s["solverStatus"] == "valid"]
    proven_point_samples = [s for s in point_samples if s["targetProvenance"] == "TARGET_PROVEN_COMPATIBLE"]
    proven_likely_point_samples = [s for s in point_samples if s["targetProvenance"] in ("TARGET_PROVEN_COMPATIBLE", "TARGET_LIKELY_COMPATIBLE")]

    reg_cleaner = compute_detailed_calibration_regression(cleaner_point_samples)
    reg_proven = compute_detailed_calibration_regression(proven_point_samples)
    reg_proven_likely = compute_detailed_calibration_regression(proven_likely_point_samples)
    reg_broad = compute_detailed_calibration_regression(point_samples)

    # 2. Out-of-Sample Calibration Experiments on All Quantile Samples (N=63)
    oos_all_quantiles = run_time_safe_walk_forward_experiment(quantile_samples, min_train_size=15)

    # 3. Out-of-Sample Calibration by Cohort
    cohort_experiments = {}
    for cohort_name in ("v0.3-dynamic-walkforward", "v0.5-field-conditions", "v0.6-reliability"):
        c_sub = [s for s in quantile_samples if s.model_version == cohort_name or s.solver_version == cohort_name]
        if len(c_sub) >= 12:
            cohort_experiments[cohort_name] = run_time_safe_walk_forward_experiment(c_sub, min_train_size=7)

    # 4. Heavy Tail Analysis
    tail_analysis = analyze_heavy_tail_and_error_concentration(quantile_samples)

    # Compile Complete Results JSON
    complete_results = {
        "metadata": {
            "generatedAt": datetime.now().isoformat(),
            "experimentVersion": "offline-quantile-calibration-v1",
            "source": str(db_path),
        },
        "auditCloseouts": {
            "cleanerSubsetCount": len(cleaner_point_samples),
            "cleanerQuantileCount": sum(1 for s in quantile_samples if s.target_provenance in ("TARGET_PROVEN_COMPATIBLE", "TARGET_LIKELY_COMPATIBLE") and s.solver_status == "valid"),
            "auditSummary": audit_summary,
            "regressions": {
                "cleanerSubset": reg_cleaner,
                "provenOnly": reg_proven,
                "provenLikely": reg_proven_likely,
                "broadSubset": reg_broad,
            },
        },
        "heavyTailAnalysis": tail_analysis,
        "outOfSampleCalibrationOverall": oos_all_quantiles,
        "cohortSpecificCalibration": cohort_experiments,
    }

    # Save outputs
    out_dir = PROJECT_ROOT / "experiments" / "quantile_calibration_v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    results_file = out_dir / "results.json"
    results_file.write_text(json.dumps(complete_results, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_file = out_dir / "dataset_manifest.json"
    manifest_payload = {
        "schemaVersion": "quantile-calibration-dataset-manifest.v1",
        "sampleCount": len(quantile_samples),
        "pointSampleCount": len(point_samples),
        "provenanceBreakdown": audit_summary["targetProvenanceCounts"],
        "cohortBreakdown": audit_summary["cohortDistribution"],
        "samples": [asdict(s) for s in quantile_samples],
    }
    manifest_file.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Experiment completed successfully!")
    print(f"Results written to: {results_file}")
    print(f"Manifest written to: {manifest_file}")

    return complete_results


if __name__ == "__main__":
    run_experiment_suite()
