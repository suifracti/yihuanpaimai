# -*- coding: utf-8 -*-
"""Legacy Exploratory Eligibility Policy v1 for Research & Diagnostic Evaluation.

Classifies legacy/historical records for exploratory metrics, red-tail research,
and solver replay without polluting formal evaluation standards.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from history_admission import evaluate_history_admission


LEGACY_EXPLORATORY_POLICY_VERSION = 1


@dataclass(frozen=True)
class LegacyRecordClassification:
    record_id: str
    is_admitted: bool
    is_point_candidate: bool
    is_quantile_candidate: bool
    is_distribution_only: bool
    is_unusable: bool
    actual_total: Optional[float]
    point_estimate: Optional[float]
    p20: Optional[float]
    p50: Optional[float]
    p80: Optional[float]
    solver_version: Optional[str]
    model_version: Optional[str]
    catalog_version: Optional[str]
    quality_flags: Tuple[str, ...]


def classify_legacy_record(
    record: Mapping[str, Any],
    duplicate_index,
) -> LegacyRecordClassification:
    """Classify a single legacy record according to Legacy Exploratory Policy v1."""
    rec_id = str(record.get("id") or "").strip()
    adm = evaluate_history_admission(record, duplicate_index)

    quality_flags: List[str] = [
        "PROVENANCE_INCOMPLETE",
        "TRUTH_NOT_INDEPENDENTLY_VERIFIED",
    ]

    if not adm.admitted:
        return LegacyRecordClassification(
            record_id=rec_id,
            is_admitted=False,
            is_point_candidate=False,
            is_quantile_candidate=False,
            is_distribution_only=False,
            is_unusable=True,
            actual_total=None,
            point_estimate=None,
            p20=None,
            p50=None,
            p80=None,
            solver_version=None,
            model_version=None,
            catalog_version=None,
            quality_flags=tuple(quality_flags),
        )

    # Extract actualTotal
    raw_actual = record.get("actualTotal")
    if raw_actual is None and isinstance(record.get("settlement"), Mapping):
        raw_actual = record["settlement"].get("actualTotal")

    actual_val: Optional[float] = None
    if isinstance(raw_actual, (int, float)) and not isinstance(raw_actual, bool) and math.isfinite(raw_actual) and raw_actual > 0:
        actual_val = float(raw_actual)

    if actual_val is None:
        return LegacyRecordClassification(
            record_id=rec_id,
            is_admitted=True,
            is_point_candidate=False,
            is_quantile_candidate=False,
            is_distribution_only=False,
            is_unusable=True,
            actual_total=None,
            point_estimate=None,
            p20=None,
            p50=None,
            p80=None,
            solver_version=None,
            model_version=None,
            catalog_version=None,
            quality_flags=tuple(quality_flags),
        )

    # Extract prediction
    snap = record.get("predictionSnapshot")
    pred = record.get("prediction") or record.get("frozenPrediction")

    point_est: Optional[float] = None
    p20_val: Optional[float] = None
    p50_val: Optional[float] = None
    p80_val: Optional[float] = None
    solver_ver: Optional[str] = None
    model_ver: Optional[str] = None
    catalog_ver: Optional[str] = None

    if isinstance(snap, Mapping):
        quality_flags.append("SNAPSHOT_V1_FORMAT")
        prod = snap.get("producer") or {}
        solver_ver = prod.get("solverVersion")
        model_ver = prod.get("modelVersion")
        catalog_ver = prod.get("catalogVersion")

        fc = snap.get("forecast") or {}
        quantiles = fc.get("quantiles") or {}
        if isinstance(quantiles, Mapping):
            if isinstance(quantiles.get("p50"), (int, float)):
                p50_val = float(quantiles["p50"])
                point_est = p50_val
            if isinstance(quantiles.get("p20"), (int, float)):
                p20_val = float(quantiles["p20"])
            if isinstance(quantiles.get("p80"), (int, float)):
                p80_val = float(quantiles["p80"])

    elif isinstance(pred, Mapping):
        quality_flags.append("LEGACY_PREDICTION_FORMAT")
        quality_flags.append("TARGET_INFERRED")
        solver_ver = pred.get("solverVersion")
        model_ver = pred.get("modelVersion")
        catalog_ver = pred.get("catalogVersion")

        # Point estimate
        raw_est = pred.get("estimate") or pred.get("structuralCenter")
        if isinstance(raw_est, (int, float)) and not isinstance(raw_est, bool) and math.isfinite(raw_est) and raw_est > 0:
            point_est = float(raw_est)

        # Quantiles in probabilityProfile
        prof = pred.get("probabilityProfile")
        if isinstance(prof, Mapping):
            sw = prof.get("shadowWhole") or prof.get("quantiles")
            if isinstance(sw, Mapping):
                if isinstance(sw.get("p20"), (int, float)):
                    p20_val = float(sw["p20"])
                if isinstance(sw.get("p50"), (int, float)):
                    p50_val = float(sw["p50"])
                    if point_est is None:
                        point_est = p50_val
                if isinstance(sw.get("p80"), (int, float)):
                    p80_val = float(sw["p80"])

    is_point = (point_est is not None)
    is_quantile = (point_est is not None and p20_val is not None and p50_val is not None and p80_val is not None)
    is_dist = (point_est is None)

    return LegacyRecordClassification(
        record_id=rec_id,
        is_admitted=True,
        is_point_candidate=is_point,
        is_quantile_candidate=is_quantile,
        is_distribution_only=is_dist,
        is_unusable=False,
        actual_total=actual_val,
        point_estimate=point_est,
        p20=p20_val,
        p50=p50_val,
        p80=p80_val,
        solver_version=solver_ver,
        model_version=model_ver,
        catalog_version=catalog_ver,
        quality_flags=tuple(quality_flags),
    )
