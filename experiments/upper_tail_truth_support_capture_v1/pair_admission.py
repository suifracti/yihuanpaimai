# -*- coding: utf-8 -*-
"""Deterministic admission gate for future real upper-tail pairs.

This module validates provenance and linkage only.  It computes no accuracy,
error, score, model verdict, or algorithm recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from .capture_contract import validate_prediction_capture, validate_truth_capture


PAIR_GATE_VERSION = "valid-upper-tail-pair.v1"
VALID_PAIR_STATUS = "VALID_UPPER_TAIL_PAIR_V1"


def _parse_aware(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


@dataclass(frozen=True)
class PairAdmissionResult:
    admitted: bool
    status: str
    reason_codes: tuple[str, ...]
    collection_class: str
    truth_review_class: str
    realized_state_relation: str
    value_model_error_eligible: bool

    def as_immutable_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "gateVersion": PAIR_GATE_VERSION,
                "admitted": self.admitted,
                "status": self.status,
                "reasonCodes": self.reason_codes,
                "collectionClass": self.collection_class,
                "truthReviewClass": self.truth_review_class,
                "realizedStateRelation": self.realized_state_relation,
                "valueModelErrorEligible": self.value_model_error_eligible,
            }
        )


def validate_upper_tail_pair(
    prediction_capture: Mapping[str, Any],
    truth_capture: Mapping[str, Any],
) -> PairAdmissionResult:
    """Fail closed; only natural + independently reviewed complete pairs admit."""
    reasons: list[str] = []
    prediction_reasons = validate_prediction_capture(prediction_capture)
    if prediction_reasons:
        reasons.extend(f"PREDICTION_INVALID:{reason}" for reason in prediction_reasons)
    truth_reasons = validate_truth_capture(truth_capture, prediction_capture)
    if truth_reasons:
        reasons.extend(f"TRUTH_INVALID:{reason}" for reason in truth_reasons)

    collection_class = str(prediction_capture.get("collectionClass") or "")
    review_class = str(truth_capture.get("reviewClass") or "")
    if collection_class != "NATURAL_RUNTIME_CAPTURE":
        reasons.append("PREDICTION_NOT_NATURAL_RUNTIME_CAPTURE")
    if review_class != "INDEPENDENT_REVIEWED_SETTLEMENT":
        reasons.append("TRUTH_NOT_INDEPENDENT_REVIEW")

    captured_at = _parse_aware(prediction_capture.get("capturedAt"))
    reviewed_at = _parse_aware(truth_capture.get("reviewedAt"))
    if captured_at is None or reviewed_at is None or reviewed_at < captured_at:
        reasons.append("TRUTH_REVIEW_PRECEDES_PREDICTION_CAPTURE")

    decomposition = truth_capture.get("actualValueDecomposition")
    decomposition_status = (
        decomposition.get("decompositionStatus")
        if isinstance(decomposition, Mapping)
        else None
    )
    if decomposition_status != "COMPLETE":
        reasons.append("TRUTH_DECOMPOSITION_NOT_COMPLETE")

    realized = truth_capture.get("verifiedState")
    realized_geometry = None
    if isinstance(realized, Mapping):
        values = tuple(realized.get(key) for key in ("g", "p", "r"))
        if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
            realized_geometry = values
    valuation_states = (
        prediction_capture.get("candidateSpace", {}).get("valuationStates", [])
        if isinstance(prediction_capture.get("candidateSpace"), Mapping)
        else []
    )
    valuation_geometries = {
        (row.get("g"), row.get("p"), row.get("r"))
        for row in valuation_states
        if isinstance(row, Mapping)
    }
    if realized_geometry is None:
        relation = "INVALID_REALIZED_STATE"
    elif realized_geometry in valuation_geometries:
        relation = "MATCHED_VALUATION_STATE"
    else:
        relation = "STATE_SPACE_MISSING"

    canonical_reasons = tuple(dict.fromkeys(reasons))
    admitted = not canonical_reasons
    return PairAdmissionResult(
        admitted=admitted,
        status=VALID_PAIR_STATUS if admitted else "REJECTED",
        reason_codes=canonical_reasons,
        collection_class=collection_class,
        truth_review_class=review_class,
        realized_state_relation=relation,
        value_model_error_eligible=(
            admitted
            and decomposition_status == "COMPLETE"
            and relation == "MATCHED_VALUATION_STATE"
        ),
    )
