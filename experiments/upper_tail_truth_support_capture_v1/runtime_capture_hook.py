# -*- coding: utf-8 -*-
"""Fail-closed runtime hook for prediction-time support capture.

This module is deliberately downstream of the production solve.  It only
normalizes the private support envelope emitted beside an already completed
prediction, validates it against the frozen contract, and atomically persists
a sidecar artifact.  It never calls the Solver and never reads/writes history.
"""

from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional

from .capture_contract import (
    ContractError,
    atomic_write_json,
    build_prediction_capture,
    canonical_json_bytes,
    sha256_json,
    validate_prediction_capture,
)


CAPTURE_HOOK_VERSION = "upper-tail-runtime-capture-hook.v1"
CAPTURE_PHASE = "PREDICTION_COMPLETED_PRE_SETTLEMENT"
RUNTIME_COLLECTION_CLASSES = frozenset(("RUNTIME_SMOKE_CAPTURE", "NATURAL_RUNTIME_CAPTURE"))
FORBIDDEN_POST_SETTLEMENT_KEYS = frozenset(
    (
        "actualtotal",
        "settlement",
        "settlementitems",
        "reviewedtruth",
        "truthartifact",
        "postmatchcorrection",
        "clearingprice",
        "purchasespend",
        "realizedprofit",
        "acquired",
    )
)
DEFAULT_STORE_PARTS = (
    "异环拍卖助手",
    "experiment_captures",
    "upper_tail_truth_support_capture_v1",
    "predictions",
)


@dataclass(frozen=True)
class CaptureHookResult:
    status: str
    reason: Optional[str] = None
    path: Optional[str] = None
    capture_id: Optional[str] = None
    prediction_hash: Optional[str] = None

    def as_immutable_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "status": self.status,
                "reason": self.reason,
                "path": self.path,
                "captureId": self.capture_id,
                "predictionHash": self.prediction_hash,
            }
        )


def resolve_capture_store(output_dir: Optional[os.PathLike[str] | str] = None) -> Path:
    """Resolve the same writable sidecar location in source and frozen runs."""
    if output_dir is not None:
        return Path(output_dir).expanduser().resolve()
    override = os.environ.get("YIHUAN_UPPER_TAIL_CAPTURE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    return Path(local_app_data).joinpath(*DEFAULT_STORE_PARTS).resolve()


def _aware_datetime(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(code)
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(code) from exc
    if parsed.tzinfo is None:
        raise ContractError(code)
    return parsed


def _number(value: Any, code: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(code)
    return value


def _integer(value: Any, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(code)
    parsed = int(value)
    if parsed != value or parsed < 0:
        raise ContractError(code)
    return parsed


def _mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(code)
    return value


def _reject_post_settlement_fields(value: Any, path: str = "envelope") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            if normalized in FORBIDDEN_POST_SETTLEMENT_KEYS:
                raise ContractError(f"POST_SETTLEMENT_FIELD_FORBIDDEN:{path}.{key}")
            _reject_post_settlement_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_post_settlement_fields(child, f"{path}[{index}]")


def _state_geometry(state: Mapping[str, Any], prefix: str) -> tuple[int, int, int]:
    return (
        _integer(state.get("g", state.get("G")), f"{prefix}_G_INVALID"),
        _integer(state.get("p", state.get("P")), f"{prefix}_P_INVALID"),
        _integer(state.get("r", state.get("R")), f"{prefix}_R_INVALID"),
    )


def _component_range(component: Any, category: str, version: str) -> dict[str, Any]:
    source = _mapping(component, f"{category.upper()}_COMPONENT_MISSING")
    lower = _number(source.get("lower"), f"{category.upper()}_LOWER_INVALID")
    mid = _number(source.get("mid"), f"{category.upper()}_MID_INVALID")
    upper = _number(source.get("upper"), f"{category.upper()}_UPPER_INVALID")
    if not (0 <= lower <= mid <= upper):
        raise ContractError(f"{category.upper()}_COMPONENT_RANGE_INVALID")
    return {
        "category": category,
        "lower": lower,
        "mid": mid,
        "upper": upper,
        "provenance": {
            "method": "production_state_component",
            "version": version,
            "sourceLabel": str(source.get("source") or "unspecified"),
        },
    }


def _tail_provenance(
    state: Mapping[str, Any],
    geometry: tuple[int, int, int],
    evidence_sha256: str,
) -> dict[str, Any]:
    red_rows = state.get("redByR")
    if not isinstance(red_rows, list):
        raise ContractError("TAIL_STATE_MAPPING_MISSING")
    matching = [
        row for row in red_rows
        if isinstance(row, Mapping) and row.get("r") == geometry[2]
    ]
    if len(matching) != 1:
        raise ContractError("TAIL_STATE_MAPPING_MISSING")
    row = matching[0]
    mode = str(row.get("mode") or state.get("redMode") or "").strip()
    if mode not in {"direct", "bootstrap", "mixed"}:
        raise ContractError("TAIL_MODE_INVALID")
    return {
        "mode": mode,
        "method": "existing_shadow_state_distribution",
        "version": "shadow-profile-v06",
        "directGameCount": _integer(row.get("directGames", 0), "TAIL_DIRECT_GAMES_INVALID"),
        "bootstrapSampleCount": _integer(row.get("bootstrapN", 0), "TAIL_BOOTSTRAP_COUNT_INVALID"),
        "evidenceReferences": [
            {
                "uri": f"artifact://live-shadow-tail/g{geometry[0]}-p{geometry[1]}-r{geometry[2]}",
                "sha256": evidence_sha256,
            }
        ],
    }


def build_capture_input_from_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Convert an already-produced support envelope; never reconstruct it."""
    source = deepcopy(dict(envelope))
    _reject_post_settlement_fields(source)
    if source.get("capturePhase") != CAPTURE_PHASE:
        raise ContractError("CAPTURE_PHASE_INVALID")
    captured_at = source.get("capturedAt")
    captured_dt = _aware_datetime(captured_at, "CAPTURE_TIMESTAMP_NOT_TIMEZONE_AWARE")
    snapshot = _mapping(source.get("predictionSnapshot"), "PREDICTION_SNAPSHOT_MISSING")
    solved_dt = _aware_datetime(snapshot.get("solvedAt"), "SOLVED_AT_NOT_TIMEZONE_AWARE")
    if captured_dt < solved_dt:
        raise ContractError("CAPTURE_PRECEDES_PREDICTION_SOLVE")
    if source.get("predictionSnapshotSha256") != sha256_json(snapshot):
        raise ContractError("ENVELOPE_PREDICTION_SNAPSHOT_HASH_MISMATCH")
    runtime_match_id = str(source.get("runtimeMatchId") or "").strip()
    if not runtime_match_id or runtime_match_id == "unknown_match":
        raise ContractError("RUNTIME_MATCH_ID_MISSING")
    collection_class = str(source.get("collectionClass") or "").strip()
    if collection_class not in RUNTIME_COLLECTION_CLASSES:
        raise ContractError("RUNTIME_COLLECTION_CLASS_INVALID")

    forecast = _mapping(snapshot.get("forecast"), "PREDICTION_FORECAST_MISSING")
    snapshot_quantiles = forecast.get("quantiles")
    if not isinstance(snapshot_quantiles, Mapping):
        raise ContractError("PREDICTION_QUANTILES_UNAVAILABLE")

    raw_full = source.get("fullCandidateStates")
    raw_valuation = source.get("valuationStates")
    if not isinstance(raw_full, list) or not raw_full:
        raise ContractError("FULL_CANDIDATE_STATES_MISSING")
    if not isinstance(raw_valuation, list) or not raw_valuation:
        raise ContractError("VALUATION_STATES_MISSING")

    full_rows: list[dict[str, Any]] = []
    full_by_geometry: dict[tuple[int, int, int], str] = {}
    for ordinal, raw_state in enumerate(raw_full):
        row = _mapping(raw_state, "FULL_STATE_NOT_MAPPING")
        geometry = _state_geometry(row, "FULL_STATE")
        if geometry in full_by_geometry:
            raise ContractError("FULL_STATE_GEOMETRY_DUPLICATE")
        state_id = f"full-g{geometry[0]}-p{geometry[1]}-r{geometry[2]}"
        full_by_geometry[geometry] = state_id
        full_rows.append(
            {
                "stateId": state_id,
                "g": geometry[0],
                "p": geometry[1],
                "r": geometry[2],
                "provenance": {
                    "source": "production_expanded_candidate_state",
                    "solverStateOrdinal": ordinal,
                },
            }
        )

    evidence = source.get("tailEvidence")
    evidence_sha256 = sha256_json(evidence if evidence is not None else {})
    producer = _mapping(snapshot.get("producer"), "PREDICTION_PRODUCER_MISSING")
    component_version = str(producer.get("solverVersion") or "unknown-solver-version")
    valuation_rows: list[dict[str, Any]] = []
    seen_geometries: set[tuple[int, int, int]] = set()
    weight_sum = 0.0
    for raw_state in raw_valuation:
        state = _mapping(raw_state, "VALUATION_STATE_NOT_MAPPING")
        geometry = _state_geometry(state, "VALUATION_STATE")
        source_id = full_by_geometry.get(geometry)
        if source_id is None:
            raise ContractError("STATE_MAPPING_MISSING")
        if geometry in seen_geometries:
            raise ContractError("VALUATION_STATE_GEOMETRY_DUPLICATE")
        seen_geometries.add(geometry)
        normalized_weight = _number(state.get("relativeWeight"), "NORMALIZED_WEIGHT_MISSING")
        if normalized_weight < 0:
            raise ContractError("NORMALIZED_WEIGHT_INVALID")
        weight_sum += float(normalized_weight)

        raw_components = _mapping(state.get("component"), "VALUATION_COMPONENTS_MISSING")
        components = [
            _component_range(raw_components.get(category), category, component_version)
            for category in ("gold", "purple", "red", "lowTier")
        ]
        total = {
            key: sum(float(component[key]) for component in components)
            for key in ("lower", "mid", "upper")
        }
        raw_shadow = state.get("shadow")
        if raw_shadow is None:
            tail = {
                "supportStatus": "UNSUPPORTED",
                "reasonCode": "PRODUCTION_STATE_DISTRIBUTION_UNAVAILABLE",
                "distribution": None,
            }
        else:
            shadow = _mapping(raw_shadow, "TAIL_DISTRIBUTION_INVALID")
            tail = {
                "supportStatus": "SUPPORTED",
                "distribution": {
                    "p20": _number(shadow.get("p20"), "TAIL_P20_INVALID"),
                    "p50": _number(shadow.get("p50"), "TAIL_P50_INVALID"),
                    "p80": _number(shadow.get("p80"), "TAIL_P80_INVALID"),
                    "p95": _number(shadow.get("p95"), "TAIL_P95_INVALID"),
                    "max": _number(shadow.get("max"), "TAIL_MAX_INVALID"),
                },
                "provenance": _tail_provenance(state, geometry, evidence_sha256),
            }
        valuation_rows.append(
            {
                "stateId": f"value-g{geometry[0]}-p{geometry[1]}-r{geometry[2]}",
                "sourceFullStateIds": [source_id],
                "g": geometry[0],
                "p": geometry[1],
                "r": geometry[2],
                "normalizedWeight": normalized_weight,
                "valuationBreakdown": {"components": components, "total": total},
                "tailContribution": tail,
            }
        )

    if set(full_by_geometry) != seen_geometries:
        raise ContractError("STATE_MAPPING_INCOMPLETE")
    if abs(weight_sum - 1.0) > 1e-9:
        raise ContractError("NORMALIZED_WEIGHT_SUM_INVALID")

    raw_aggregate = _mapping(source.get("aggregateDistribution"), "AGGREGATE_DISTRIBUTION_MISSING")
    aggregate_quantiles = {
        key: _number(raw_aggregate.get(key), f"AGGREGATE_{key.upper()}_INVALID")
        for key in ("p20", "p50", "p80")
    }
    if aggregate_quantiles != dict(snapshot_quantiles):
        raise ContractError("AGGREGATE_FORECAST_QUANTILES_MISMATCH")

    return {
        "capturedAt": captured_at,
        "matchId": runtime_match_id,
        "collectionClass": collection_class,
        "predictionSnapshot": deepcopy(snapshot),
        "candidateSpace": {
            "fullStateCount": len(full_rows),
            "valuationStateCount": len(valuation_rows),
            "compressionApplied": len(valuation_rows) < len(full_rows),
            "resolverVersion": "production-expanded-state-map.v1",
            "fullCandidateStates": full_rows,
            "valuationStates": valuation_rows,
        },
        "aggregateDistribution": {
            "quantiles": aggregate_quantiles,
            "quantileProvenance": {
                "method": "existing_shadow_weighted_empirical_mixture",
                "version": "shadow-profile-v06",
            },
        },
    }


def load_and_validate_capture(path: os.PathLike[str] | str) -> dict[str, Any]:
    """Reject corruption; this is also the offline replay/read boundary."""
    artifact = json.loads(Path(path).read_text(encoding="utf-8"))
    reasons = validate_prediction_capture(artifact)
    if reasons:
        raise ContractError(f"CORRUPTED_CAPTURE_ARTIFACT:{reasons[0]}")
    return artifact


def capture_prediction_support_envelope(
    envelope: Mapping[str, Any],
    output_dir: Optional[os.PathLike[str] | str] = None,
) -> CaptureHookResult:
    """Validate then persist exactly once; invalid input never reaches disk."""
    try:
        capture_input = build_capture_input_from_envelope(envelope)
        artifact = build_prediction_capture(capture_input)
    except (ContractError, KeyError, TypeError, ValueError) as exc:
        return CaptureHookResult(status="REJECTED", reason=str(exc))

    store = resolve_capture_store(output_dir)
    target = store / f"{artifact['captureId']}.json"
    if target.exists():
        try:
            existing = load_and_validate_capture(target)
        except (ContractError, json.JSONDecodeError, OSError, ValueError) as exc:
            return CaptureHookResult(status="REJECTED", reason=str(exc), path=str(target))
        # captureId is content-addressed from predictionHash.  A replay after
        # process restart may have a later capturedAt, but must not rewrite the
        # first valid prediction-time artifact.
        if (
            existing.get("predictionHash") != artifact.get("predictionHash")
            or existing.get("predictionSnapshotSha256")
            != artifact.get("predictionSnapshotSha256")
        ):
            return CaptureHookResult(
                status="REJECTED",
                reason="DUPLICATE_CAPTURE_CONTENT_MISMATCH",
                path=str(target),
            )
        return CaptureHookResult(
            status="DUPLICATE",
            path=str(target),
            capture_id=artifact["captureId"],
            prediction_hash=artifact["predictionHash"],
        )

    try:
        atomic_write_json(target, artifact)
        persisted = load_and_validate_capture(target)
        if canonical_json_bytes(persisted) != canonical_json_bytes(artifact):
            raise ContractError("PERSISTED_CAPTURE_CONTENT_MISMATCH")
    except (ContractError, json.JSONDecodeError, OSError, ValueError) as exc:
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
        return CaptureHookResult(status="REJECTED", reason=str(exc), path=str(target))
    return CaptureHookResult(
        status="WRITTEN",
        path=str(target),
        capture_id=artifact["captureId"],
        prediction_hash=artifact["predictionHash"],
    )


def source_package_parity_signature() -> str:
    """Stable signature used by source/frozen smoke without touching data."""
    return sha256_json(
        {
            "hookVersion": CAPTURE_HOOK_VERSION,
            "capturePhase": CAPTURE_PHASE,
            "defaultStoreParts": list(DEFAULT_STORE_PARTS),
        }
    )
