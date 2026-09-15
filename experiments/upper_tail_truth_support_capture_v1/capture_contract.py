# -*- coding: utf-8 -*-
"""Experiment-only Upper-tail Truth/Support Capture Contract v1.

This module freezes prediction-time state support and later links reviewed
settlement truth.  It does not import, call, tune, or modify the production
Solver and it never reads or writes canonical history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional, Sequence


PREDICTION_SCHEMA_VERSION = "upper-tail-prediction-support-capture.v1"
TRUTH_SCHEMA_VERSION = "upper-tail-settlement-truth.v1"
CONTRACT_VERSION = 1
PREDICTION_CAPTURE_PHASE = "PREDICTION_COMPLETED_PRE_SETTLEMENT"
PREDICTION_COLLECTION_CLASSES = frozenset(
    ("CONTRACT_VALID_FIXTURE", "RUNTIME_SMOKE_CAPTURE", "NATURAL_RUNTIME_CAPTURE")
)
TRUTH_REVIEW_CLASSES = frozenset(
    ("CONTRACT_VALID_FIXTURE", "INDEPENDENT_REVIEWED_SETTLEMENT")
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_COMPONENT_CATEGORIES = frozenset(
    ("gold", "purple", "red", "lowTier", "welfare", "other")
)
ALLOWED_TAIL_MODES = frozenset(("direct", "bootstrap", "mixed", "deterministic"))
ALLOWED_SUPPORT_STATUS = frozenset(("SUPPORTED", "UNSUPPORTED"))


class ContractError(ValueError):
    """Fail-closed contract violation."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _nonnegative(value: Any) -> bool:
    return _finite(value) and value >= 0


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _aware_iso(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def _require_mapping(value: Any, code: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), code)
    return value


def _validate_ref(reference: Any, prefix: str) -> None:
    ref = _require_mapping(reference, f"{prefix}_NOT_MAPPING")
    _require(bool(str(ref.get("uri") or "").strip()), f"{prefix}_URI_MISSING")
    _require(_is_sha256(ref.get("sha256")), f"{prefix}_SHA256_INVALID")


def _state_geometry(state: Mapping[str, Any]) -> tuple[int, int, int]:
    values = tuple(state.get(key) for key in ("g", "p", "r"))
    _require(all(_positive_int(value) for value in values), "STATE_GEOMETRY_INVALID")
    return values  # type: ignore[return-value]


def _validate_quantiles(value: Any, prefix: str, *, extended: bool = False) -> None:
    quantiles = _require_mapping(value, f"{prefix}_NOT_MAPPING")
    keys = ("p20", "p50", "p80", "p95", "max") if extended else ("p20", "p50", "p80")
    values = [quantiles.get(key) for key in keys]
    _require(all(_nonnegative(item) for item in values), f"{prefix}_VALUE_INVALID")
    _require(values == sorted(values), f"{prefix}_NOT_MONOTONIC")


def _validate_prediction_snapshot(snapshot: Any) -> None:
    snap = _require_mapping(snapshot, "PREDICTION_SNAPSHOT_NOT_MAPPING")
    _require(snap.get("schemaVersion") == "prediction-snapshot.v1", "PREDICTION_SNAPSHOT_VERSION_INVALID")
    _require(snap.get("frozen") is True, "PREDICTION_SNAPSHOT_NOT_FROZEN")
    _require(bool(str(snap.get("predictionId") or "").strip()), "PREDICTION_ID_MISSING")
    _require(bool(str(snap.get("matchId") or "").strip()), "MATCH_ID_MISSING")
    input_contract = _require_mapping(snap.get("input"), "PREDICTION_INPUT_MISSING")
    _require(_is_sha256(input_contract.get("inputHash")), "PREDICTION_INPUT_HASH_INVALID")
    facts = _require_mapping(input_contract.get("normalizedFacts"), "PREDICTION_NORMALIZED_FACTS_MISSING")
    _require(input_contract.get("inputHash") == sha256_json(facts), "PREDICTION_INPUT_HASH_MISMATCH")
    dataset_revision = _require_mapping(input_contract.get("datasetRevision"), "DATASET_REVISION_MISSING")
    _require(_is_sha256(dataset_revision.get("sha256")), "DATASET_REVISION_HASH_INVALID")
    _require(_is_sha256(dataset_revision.get("eligibleRecordIdsSha256")), "DATASET_ELIGIBLE_IDS_HASH_INVALID")
    mode = _require_mapping(snap.get("mode"), "PREDICTION_MODE_MISSING")
    _require(_finite(mode.get("coverageRatio")), "PREDICTION_COVERAGE_INVALID")
    _require(0 <= mode["coverageRatio"] <= 1, "PREDICTION_COVERAGE_INVALID")
    forecast = _require_mapping(snap.get("forecast"), "PREDICTION_FORECAST_MISSING")
    _require(forecast.get("target") == "full_inventory_actual_total", "PREDICTION_TARGET_UNSUPPORTED")
    _require(forecast.get("scope") == "full_inventory", "PREDICTION_SCOPE_UNSUPPORTED")
    _validate_quantiles(forecast.get("quantiles"), "PREDICTION_QUANTILES")


def _validate_breakdown(breakdown: Any) -> None:
    block = _require_mapping(breakdown, "VALUATION_BREAKDOWN_MISSING")
    components = block.get("components")
    _require(isinstance(components, list) and bool(components), "VALUATION_COMPONENTS_MISSING")
    categories: set[str] = set()
    sums = {"lower": 0.0, "mid": 0.0, "upper": 0.0}
    for component in components:
        row = _require_mapping(component, "VALUATION_COMPONENT_NOT_MAPPING")
        category = str(row.get("category") or "")
        _require(category in ALLOWED_COMPONENT_CATEGORIES, "VALUATION_CATEGORY_INVALID")
        _require(category not in categories, "VALUATION_CATEGORY_DUPLICATE")
        categories.add(category)
        for key in sums:
            value = row.get(key)
            _require(_nonnegative(value), f"VALUATION_{key.upper()}_INVALID")
            sums[key] += float(value)
        _require(row["lower"] <= row["mid"] <= row["upper"], "VALUATION_COMPONENT_RANGE_INVALID")
        provenance = _require_mapping(row.get("provenance"), "VALUATION_PROVENANCE_MISSING")
        _require(bool(str(provenance.get("method") or "").strip()), "VALUATION_METHOD_MISSING")
        _require(bool(str(provenance.get("version") or "").strip()), "VALUATION_VERSION_MISSING")
    total = _require_mapping(block.get("total"), "VALUATION_TOTAL_MISSING")
    for key, expected in sums.items():
        _require(_nonnegative(total.get(key)), f"VALUATION_TOTAL_{key.upper()}_INVALID")
        _require(abs(float(total[key]) - expected) <= 0.01, f"VALUATION_TOTAL_{key.upper()}_MISMATCH")
    _require(total["lower"] <= total["mid"] <= total["upper"], "VALUATION_TOTAL_RANGE_INVALID")


def _validate_tail(tail: Any) -> None:
    block = _require_mapping(tail, "TAIL_CONTRIBUTION_MISSING")
    status = block.get("supportStatus")
    _require(status in ALLOWED_SUPPORT_STATUS, "TAIL_SUPPORT_STATUS_INVALID")
    if status == "UNSUPPORTED":
        _require(bool(str(block.get("reasonCode") or "").strip()), "TAIL_UNSUPPORTED_REASON_MISSING")
        _require(block.get("distribution") is None, "TAIL_UNSUPPORTED_DISTRIBUTION_PRESENT")
        return
    _validate_quantiles(block.get("distribution"), "TAIL_DISTRIBUTION", extended=True)
    provenance = _require_mapping(block.get("provenance"), "TAIL_PROVENANCE_MISSING")
    _require(provenance.get("mode") in ALLOWED_TAIL_MODES, "TAIL_MODE_INVALID")
    _require(bool(str(provenance.get("method") or "").strip()), "TAIL_METHOD_MISSING")
    _require(bool(str(provenance.get("version") or "").strip()), "TAIL_VERSION_MISSING")
    _require(_positive_int(provenance.get("directGameCount")), "TAIL_DIRECT_GAME_COUNT_INVALID")
    _require(_positive_int(provenance.get("bootstrapSampleCount")), "TAIL_BOOTSTRAP_COUNT_INVALID")
    references = provenance.get("evidenceReferences")
    _require(isinstance(references, list) and bool(references), "TAIL_EVIDENCE_REFERENCE_MISSING")
    for reference in references:
        _validate_ref(reference, "TAIL_EVIDENCE_REFERENCE")


def _capture_hash_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in artifact.items() if key != "artifactSha256"}


def validate_prediction_capture(artifact: Any) -> list[str]:
    """Return fail-closed reason codes.  Empty means valid."""
    try:
        payload = _require_mapping(artifact, "CAPTURE_NOT_MAPPING")
        _require(payload.get("schemaVersion") == PREDICTION_SCHEMA_VERSION, "CAPTURE_SCHEMA_VERSION_INVALID")
        _require(payload.get("contractVersion") == CONTRACT_VERSION, "CAPTURE_CONTRACT_VERSION_INVALID")
        _require(bool(str(payload.get("captureId") or "").strip()), "CAPTURE_ID_MISSING")
        _require(bool(str(payload.get("matchId") or "").strip()), "MATCH_ID_MISSING")
        _require(payload.get("collectionClass") in PREDICTION_COLLECTION_CLASSES, "COLLECTION_CLASS_INVALID")
        _require(payload.get("capturePhase") == PREDICTION_CAPTURE_PHASE, "CAPTURE_PHASE_INVALID")
        _require(_aware_iso(payload.get("capturedAt")), "CAPTURED_AT_INVALID")
        snapshot = _require_mapping(payload.get("predictionSnapshot"), "PREDICTION_SNAPSHOT_MISSING")
        _validate_prediction_snapshot(snapshot)
        captured_at = datetime.fromisoformat(str(payload["capturedAt"]).replace("Z", "+00:00"))
        solved_at = datetime.fromisoformat(str(snapshot["solvedAt"]).replace("Z", "+00:00"))
        _require(captured_at >= solved_at, "CAPTURE_PRECEDES_PREDICTION_SOLVE")
        binding = _require_mapping(payload.get("matchBinding"), "MATCH_BINDING_MISSING")
        _require(binding.get("runtimeMatchId") == payload.get("matchId"), "RUNTIME_MATCH_ID_MISMATCH")
        _require(binding.get("predictionSnapshotMatchId") == snapshot.get("matchId"), "SNAPSHOT_MATCH_ID_BINDING_MISMATCH")
        if snapshot.get("matchId") == payload.get("matchId"):
            _require(binding.get("status") == "EXACT_SNAPSHOT_MATCH", "MATCH_BINDING_STATUS_INVALID")
        else:
            _require(snapshot.get("matchId") == "unknown_match", "PREDICTION_MATCH_ID_MISMATCH")
            _require(binding.get("status") == "RUNTIME_CONTEXT_BINDING", "MATCH_BINDING_STATUS_INVALID")
        _require(_is_sha256(payload.get("predictionSnapshotSha256")), "PREDICTION_SNAPSHOT_HASH_INVALID")
        _require(payload["predictionSnapshotSha256"] == sha256_json(snapshot), "PREDICTION_SNAPSHOT_HASH_MISMATCH")

        candidate_space = _require_mapping(payload.get("candidateSpace"), "CANDIDATE_SPACE_MISSING")
        full_states = candidate_space.get("fullCandidateStates")
        valuation_states = candidate_space.get("valuationStates")
        _require(isinstance(full_states, list) and bool(full_states), "FULL_CANDIDATE_STATES_MISSING")
        _require(isinstance(valuation_states, list) and bool(valuation_states), "VALUATION_STATES_MISSING")
        _require(candidate_space.get("fullStateCount") == len(full_states), "FULL_STATE_COUNT_MISMATCH")
        _require(candidate_space.get("valuationStateCount") == len(valuation_states), "VALUATION_STATE_COUNT_MISMATCH")

        full_ids: set[str] = set()
        full_geometry: set[tuple[int, int, int]] = set()
        full_geometry_by_id: dict[str, tuple[int, int, int]] = {}
        for state in full_states:
            row = _require_mapping(state, "FULL_STATE_NOT_MAPPING")
            state_id = str(row.get("stateId") or "")
            _require(bool(state_id), "FULL_STATE_ID_MISSING")
            _require(state_id not in full_ids, "FULL_STATE_ID_DUPLICATE")
            full_ids.add(state_id)
            geometry = _state_geometry(row)
            _require(geometry not in full_geometry, "FULL_STATE_GEOMETRY_DUPLICATE")
            full_geometry.add(geometry)
            full_geometry_by_id[state_id] = geometry
            provenance = _require_mapping(row.get("provenance"), "FULL_STATE_PROVENANCE_MISSING")
            _require(bool(str(provenance.get("source") or "").strip()), "FULL_STATE_SOURCE_MISSING")

        valuation_ids: set[str] = set()
        referenced_full_ids: list[str] = []
        weight_sum = 0.0
        supported_ids: list[str] = []
        for state in valuation_states:
            row = _require_mapping(state, "VALUATION_STATE_NOT_MAPPING")
            state_id = str(row.get("stateId") or "")
            _require(bool(state_id), "VALUATION_STATE_ID_MISSING")
            _require(state_id not in valuation_ids, "VALUATION_STATE_ID_DUPLICATE")
            valuation_ids.add(state_id)
            geometry = _state_geometry(row)
            source_ids = row.get("sourceFullStateIds")
            _require(isinstance(source_ids, list) and bool(source_ids), "SOURCE_FULL_STATE_IDS_MISSING")
            _require(source_ids == sorted(set(source_ids)), "SOURCE_FULL_STATE_IDS_NOT_CANONICAL")
            _require(all(source_id in full_ids for source_id in source_ids), "SOURCE_FULL_STATE_ID_UNKNOWN")
            if len(source_ids) == 1:
                _require(geometry == full_geometry_by_id[source_ids[0]], "VALUATION_SOURCE_GEOMETRY_MISMATCH")
            else:
                _require(bool(str(row.get("aggregationMethod") or "").strip()), "VALUATION_AGGREGATION_METHOD_MISSING")
            referenced_full_ids.extend(source_ids)
            weight = row.get("normalizedWeight")
            _require(_nonnegative(weight), "NORMALIZED_WEIGHT_INVALID")
            weight_sum += float(weight)
            _validate_breakdown(row.get("valuationBreakdown"))
            _validate_tail(row.get("tailContribution"))
            if row["tailContribution"]["supportStatus"] == "SUPPORTED":
                supported_ids.append(state_id)

        _require(sorted(referenced_full_ids) == sorted(full_ids), "FULL_STATE_MAPPING_INCOMPLETE_OR_DUPLICATE")
        _require(abs(weight_sum - 1.0) <= 1e-9, "NORMALIZED_WEIGHT_SUM_INVALID")
        _require(
            candidate_space.get("compressionApplied") == (len(valuation_states) < len(full_states)),
            "COMPRESSION_FLAG_MISMATCH",
        )
        mode = snapshot["mode"]
        supported_weight = sum(
            float(row["normalizedWeight"])
            for row in valuation_states
            if row["tailContribution"]["supportStatus"] == "SUPPORTED"
        )
        _require(abs(supported_weight - float(mode["coverageRatio"])) <= 1e-9, "SUPPORTED_WEIGHT_COVERAGE_MISMATCH")
        _require(mode.get("totalStateCount") == len(full_states), "SNAPSHOT_TOTAL_STATE_COUNT_MISMATCH")
        _require(mode.get("supportedStateCount") == len(supported_ids), "SNAPSHOT_SUPPORTED_STATE_COUNT_MISMATCH")

        integrity = _require_mapping(payload.get("supportIntegrity"), "SUPPORT_INTEGRITY_MISSING")
        expected_hashes = {
            "fullCandidateStatesSha256": sha256_json(full_states),
            "valuationStatesSha256": sha256_json(valuation_states),
            "normalizedWeightsSha256": sha256_json(
                [{"stateId": row["stateId"], "normalizedWeight": row["normalizedWeight"]} for row in valuation_states]
            ),
            "valuationBreakdownsSha256": sha256_json(
                [{"stateId": row["stateId"], "valuationBreakdown": row["valuationBreakdown"]} for row in valuation_states]
            ),
            "tailContributionsSha256": sha256_json(
                [{"stateId": row["stateId"], "tailContribution": row["tailContribution"]} for row in valuation_states]
            ),
        }
        for key, expected in expected_hashes.items():
            _require(integrity.get(key) == expected, f"{key.upper()}_MISMATCH")
        mixture_input = {
            "normalizedWeightsSha256": expected_hashes["normalizedWeightsSha256"],
            "valuationBreakdownsSha256": expected_hashes["valuationBreakdownsSha256"],
            "tailContributionsSha256": expected_hashes["tailContributionsSha256"],
        }
        mixture_hash = sha256_json(mixture_input)
        _require(integrity.get("mixtureInputSha256") == mixture_hash, "MIXTURE_INPUT_HASH_MISMATCH")

        distribution = _require_mapping(payload.get("aggregateDistribution"), "AGGREGATE_DISTRIBUTION_MISSING")
        _validate_quantiles(distribution.get("quantiles"), "AGGREGATE_QUANTILES")
        forecast_quantiles = snapshot["forecast"]["quantiles"]
        _require(distribution.get("quantiles") == forecast_quantiles, "AGGREGATE_FORECAST_QUANTILES_MISMATCH")
        source_state_ids = distribution.get("sourceStateIds")
        _require(source_state_ids == sorted(supported_ids), "AGGREGATE_SOURCE_STATES_MISMATCH")
        provenance = _require_mapping(distribution.get("quantileProvenance"), "QUANTILE_PROVENANCE_MISSING")
        _require(bool(str(provenance.get("method") or "").strip()), "QUANTILE_METHOD_MISSING")
        _require(bool(str(provenance.get("version") or "").strip()), "QUANTILE_VERSION_MISSING")
        _require(provenance.get("mixtureInputSha256") == mixture_hash, "QUANTILE_MIXTURE_HASH_MISMATCH")
        for key in ("p20", "p50", "p80"):
            trace = _require_mapping(provenance.get(key), f"{key.upper()}_TRACE_MISSING")
            _require(trace.get("sourceStateIds") == sorted(supported_ids), f"{key.upper()}_SOURCE_STATES_MISMATCH")
            _require(trace.get("mixtureInputSha256") == mixture_hash, f"{key.upper()}_MIXTURE_HASH_MISMATCH")

        prediction_body = {
            "predictionSnapshotSha256": payload["predictionSnapshotSha256"],
            "collectionClass": payload["collectionClass"],
            "matchBinding": binding,
            "candidateSpace": candidate_space,
            "supportIntegrity": integrity,
            "aggregateDistribution": distribution,
        }
        expected_prediction_hash = sha256_json(prediction_body)
        _require(payload.get("predictionHash") == expected_prediction_hash, "PREDICTION_HASH_MISMATCH")
        _require(payload.get("captureId") == f"utsc_{expected_prediction_hash[:32]}", "CAPTURE_ID_MISMATCH")
        _require(_is_sha256(payload.get("artifactSha256")), "ARTIFACT_HASH_INVALID")
        _require(payload["artifactSha256"] == sha256_json(_capture_hash_payload(payload)), "ARTIFACT_HASH_MISMATCH")
        return []
    except (ContractError, KeyError, TypeError, ValueError) as error:
        return [str(error)]


def build_prediction_capture(capture_input: Mapping[str, Any]) -> dict[str, Any]:
    """Build a content-addressed prediction-time support artifact."""
    source = deepcopy(dict(capture_input))
    snapshot = deepcopy(source.get("predictionSnapshot"))
    candidate_space = deepcopy(source.get("candidateSpace"))
    aggregate = deepcopy(source.get("aggregateDistribution"))
    _validate_prediction_snapshot(snapshot)
    _require(isinstance(candidate_space, Mapping), "CANDIDATE_SPACE_MISSING")
    _require(isinstance(aggregate, Mapping), "AGGREGATE_DISTRIBUTION_MISSING")

    full_states = candidate_space.get("fullCandidateStates") or []
    valuation_states = candidate_space.get("valuationStates") or []
    candidate_space = {
        "fullStateCount": candidate_space.get("fullStateCount"),
        "valuationStateCount": candidate_space.get("valuationStateCount"),
        "compressionApplied": bool(candidate_space.get("compressionApplied")),
        "resolverVersion": str(candidate_space.get("resolverVersion") or "").strip(),
        "fullCandidateStates": full_states,
        "valuationStates": valuation_states,
    }
    _require(bool(candidate_space["resolverVersion"]), "RESOLVER_VERSION_MISSING")
    support_integrity = {
        "fullCandidateStatesSha256": sha256_json(full_states),
        "valuationStatesSha256": sha256_json(valuation_states),
        "normalizedWeightsSha256": sha256_json(
            [{"stateId": row.get("stateId"), "normalizedWeight": row.get("normalizedWeight")} for row in valuation_states]
        ),
        "valuationBreakdownsSha256": sha256_json(
            [{"stateId": row.get("stateId"), "valuationBreakdown": row.get("valuationBreakdown")} for row in valuation_states]
        ),
        "tailContributionsSha256": sha256_json(
            [{"stateId": row.get("stateId"), "tailContribution": row.get("tailContribution")} for row in valuation_states]
        ),
    }
    support_integrity["mixtureInputSha256"] = sha256_json(
        {
            "normalizedWeightsSha256": support_integrity["normalizedWeightsSha256"],
            "valuationBreakdownsSha256": support_integrity["valuationBreakdownsSha256"],
            "tailContributionsSha256": support_integrity["tailContributionsSha256"],
        }
    )
    supported_ids = sorted(
        str(row.get("stateId"))
        for row in valuation_states
        if isinstance(row.get("tailContribution"), Mapping)
        and row["tailContribution"].get("supportStatus") == "SUPPORTED"
    )
    aggregate["sourceStateIds"] = supported_ids
    provenance = deepcopy(aggregate.get("quantileProvenance") or {})
    provenance["mixtureInputSha256"] = support_integrity["mixtureInputSha256"]
    for key in ("p20", "p50", "p80"):
        provenance[key] = {
            "sourceStateIds": supported_ids,
            "mixtureInputSha256": support_integrity["mixtureInputSha256"],
        }
    aggregate["quantileProvenance"] = provenance
    snapshot_hash = sha256_json(snapshot)
    runtime_match_id = str(source.get("matchId") or snapshot.get("matchId") or "").strip()
    _require(bool(runtime_match_id), "MATCH_ID_MISSING")
    snapshot_match_id = str(snapshot.get("matchId") or "").strip()
    if snapshot_match_id == runtime_match_id:
        binding_status = "EXACT_SNAPSHOT_MATCH"
    else:
        _require(snapshot_match_id == "unknown_match", "PREDICTION_MATCH_ID_MISMATCH")
        binding_status = "RUNTIME_CONTEXT_BINDING"
    match_binding = {
        "status": binding_status,
        "runtimeMatchId": runtime_match_id,
        "predictionSnapshotMatchId": snapshot_match_id,
    }
    prediction_body = {
        "predictionSnapshotSha256": snapshot_hash,
        "collectionClass": source.get("collectionClass") or "CONTRACT_VALID_FIXTURE",
        "matchBinding": match_binding,
        "candidateSpace": candidate_space,
        "supportIntegrity": support_integrity,
        "aggregateDistribution": aggregate,
    }
    prediction_hash = sha256_json(prediction_body)
    artifact: dict[str, Any] = {
        "schemaVersion": PREDICTION_SCHEMA_VERSION,
        "contractVersion": CONTRACT_VERSION,
        "captureId": f"utsc_{prediction_hash[:32]}",
        "matchId": runtime_match_id,
        "collectionClass": source.get("collectionClass") or "CONTRACT_VALID_FIXTURE",
        "matchBinding": match_binding,
        "capturePhase": PREDICTION_CAPTURE_PHASE,
        "capturedAt": source.get("capturedAt"),
        "predictionSnapshot": snapshot,
        "predictionSnapshotSha256": snapshot_hash,
        "candidateSpace": candidate_space,
        "supportIntegrity": support_integrity,
        "aggregateDistribution": aggregate,
        "predictionHash": prediction_hash,
        "artifactSha256": "",
    }
    artifact["artifactSha256"] = sha256_json(_capture_hash_payload(artifact))
    reasons = validate_prediction_capture(artifact)
    if reasons:
        raise ContractError(reasons[0])
    return artifact


def _truth_hash_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in artifact.items()
        if key not in {"truthId", "truthHash", "artifactSha256"}
    }


def validate_truth_capture(artifact: Any, prediction_capture: Any) -> list[str]:
    try:
        truth = _require_mapping(artifact, "TRUTH_NOT_MAPPING")
        prediction = _require_mapping(prediction_capture, "PREDICTION_CAPTURE_NOT_MAPPING")
        prediction_reasons = validate_prediction_capture(prediction)
        _require(not prediction_reasons, f"PREDICTION_CAPTURE_INVALID:{prediction_reasons[0] if prediction_reasons else ''}")
        _require(truth.get("schemaVersion") == TRUTH_SCHEMA_VERSION, "TRUTH_SCHEMA_VERSION_INVALID")
        _require(truth.get("contractVersion") == CONTRACT_VERSION, "TRUTH_CONTRACT_VERSION_INVALID")
        _require(truth.get("reviewClass") in TRUTH_REVIEW_CLASSES, "TRUTH_REVIEW_CLASS_INVALID")
        _require(_aware_iso(truth.get("reviewedAt")), "TRUTH_REVIEWED_AT_INVALID")
        _require(truth.get("matchId") == prediction.get("matchId"), "TRUTH_MATCH_ID_MISMATCH")
        link = _require_mapping(truth.get("predictionCaptureRef"), "PREDICTION_CAPTURE_REF_MISSING")
        _require(link.get("captureId") == prediction.get("captureId"), "PREDICTION_CAPTURE_ID_MISMATCH")
        _require(link.get("predictionHash") == prediction.get("predictionHash"), "PREDICTION_HASH_LINK_MISMATCH")
        _require(link.get("artifactSha256") == prediction.get("artifactSha256"), "PREDICTION_ARTIFACT_HASH_LINK_MISMATCH")

        state = _require_mapping(truth.get("verifiedState"), "VERIFIED_STATE_MISSING")
        _require(state.get("verificationStatus") == "VERIFIED", "STATE_NOT_VERIFIED")
        verified_geometry = _state_geometry(state)
        facts = prediction["predictionSnapshot"]["input"]["normalizedFacts"]
        q = facts.get("q") if isinstance(facts, Mapping) else None
        if _positive_int(q):
            _require(sum(verified_geometry) == q, "VERIFIED_STATE_Q_MISMATCH")
        verification = _require_mapping(state.get("verification"), "STATE_VERIFICATION_MISSING")
        _require(bool(str(verification.get("method") or "").strip()), "STATE_VERIFICATION_METHOD_MISSING")
        _require(bool(str(verification.get("version") or "").strip()), "STATE_VERIFICATION_VERSION_MISSING")
        reviewer = _require_mapping(verification.get("reviewer"), "STATE_REVIEWER_MISSING")
        _require(reviewer.get("type") == "reviewer", "STATE_REVIEWER_TYPE_INVALID")
        _require(bool(str(reviewer.get("id") or "").strip()), "STATE_REVIEWER_ID_MISSING")
        evidence_refs = truth.get("truthEvidenceReferences")
        _require(isinstance(evidence_refs, list) and bool(evidence_refs), "TRUTH_EVIDENCE_REFERENCES_MISSING")
        for reference in evidence_refs:
            _validate_ref(reference, "TRUTH_EVIDENCE_REFERENCE")
            _require(_is_sha256(reference.get("truthPayloadSha256")), "TRUTH_PAYLOAD_HASH_INVALID")

        decomposition = _require_mapping(truth.get("actualValueDecomposition"), "ACTUAL_DECOMPOSITION_MISSING")
        _require(decomposition.get("scope") == "full_inventory", "ACTUAL_DECOMPOSITION_SCOPE_INVALID")
        actual_total = decomposition.get("actualTotal")
        _require(_nonnegative(actual_total) and actual_total > 0, "ACTUAL_TOTAL_INVALID")
        components = decomposition.get("components")
        _require(isinstance(components, list) and bool(components), "ACTUAL_COMPONENTS_MISSING")
        component_ids: set[str] = set()
        component_sum = 0.0
        for component in components:
            row = _require_mapping(component, "ACTUAL_COMPONENT_NOT_MAPPING")
            component_id = str(row.get("componentId") or "")
            _require(bool(component_id), "ACTUAL_COMPONENT_ID_MISSING")
            _require(component_id not in component_ids, "ACTUAL_COMPONENT_ID_DUPLICATE")
            component_ids.add(component_id)
            _require(row.get("category") in ALLOWED_COMPONENT_CATEGORIES, "ACTUAL_COMPONENT_CATEGORY_INVALID")
            _require(_nonnegative(row.get("value")), "ACTUAL_COMPONENT_VALUE_INVALID")
            component_sum += float(row["value"])
            refs = row.get("evidenceReferences")
            _require(isinstance(refs, list) and bool(refs), "ACTUAL_COMPONENT_EVIDENCE_MISSING")
            for reference in refs:
                _validate_ref(reference, "ACTUAL_COMPONENT_EVIDENCE")
        unattributed = decomposition.get("unattributedValue")
        _require(_nonnegative(unattributed), "UNATTRIBUTED_VALUE_INVALID")
        reconciliation = float(actual_total) - component_sum - float(unattributed)
        _require(abs(reconciliation) <= 0.01, "ACTUAL_DECOMPOSITION_SUM_MISMATCH")
        _require(abs(float(decomposition.get("reconciliationDelta", math.inf)) - reconciliation) <= 0.01, "RECONCILIATION_DELTA_MISMATCH")
        if decomposition.get("decompositionStatus") == "COMPLETE":
            _require(float(unattributed) == 0.0, "COMPLETE_DECOMPOSITION_HAS_UNATTRIBUTED_VALUE")
        else:
            _require(decomposition.get("decompositionStatus") == "PARTIAL", "DECOMPOSITION_STATUS_INVALID")

        expected_truth_hash = sha256_json(_truth_hash_payload(truth))
        _require(truth.get("truthHash") == expected_truth_hash, "TRUTH_HASH_MISMATCH")
        _require(truth.get("truthId") == f"utst_{expected_truth_hash[:32]}", "TRUTH_ID_MISMATCH")
        _require(_is_sha256(truth.get("artifactSha256")), "TRUTH_ARTIFACT_HASH_INVALID")
        _require(truth["artifactSha256"] == sha256_json(_capture_hash_payload(truth)), "TRUTH_ARTIFACT_HASH_MISMATCH")
        return []
    except (ContractError, KeyError, TypeError, ValueError) as error:
        return [str(error)]


def build_truth_capture(truth_input: Mapping[str, Any], prediction_capture: Mapping[str, Any]) -> dict[str, Any]:
    prediction_reasons = validate_prediction_capture(prediction_capture)
    if prediction_reasons:
        raise ContractError(f"PREDICTION_CAPTURE_INVALID:{prediction_reasons[0]}")
    source = deepcopy(dict(truth_input))
    decomposition = deepcopy(source.get("actualValueDecomposition"))
    _require(isinstance(decomposition, MutableMapping), "ACTUAL_DECOMPOSITION_MISSING")
    component_sum = sum(float(row.get("value", 0)) for row in decomposition.get("components") or [])
    actual_total = float(decomposition.get("actualTotal", 0))
    unattributed = float(decomposition.get("unattributedValue", 0))
    decomposition["reconciliationDelta"] = actual_total - component_sum - unattributed
    artifact: dict[str, Any] = {
        "schemaVersion": TRUTH_SCHEMA_VERSION,
        "contractVersion": CONTRACT_VERSION,
        "truthId": "",
        "matchId": prediction_capture.get("matchId"),
        "reviewClass": source.get("reviewClass"),
        "reviewedAt": source.get("reviewedAt"),
        "predictionCaptureRef": {
            "captureId": prediction_capture.get("captureId"),
            "predictionHash": prediction_capture.get("predictionHash"),
            "artifactSha256": prediction_capture.get("artifactSha256"),
        },
        "verifiedState": deepcopy(source.get("verifiedState")),
        "truthEvidenceReferences": deepcopy(source.get("truthEvidenceReferences")),
        "actualValueDecomposition": decomposition,
        "truthHash": "",
        "artifactSha256": "",
    }
    artifact["truthHash"] = sha256_json(_truth_hash_payload(artifact))
    artifact["truthId"] = f"utst_{artifact['truthHash'][:32]}"
    artifact["artifactSha256"] = sha256_json(_capture_hash_payload(artifact))
    reasons = validate_truth_capture(artifact, prediction_capture)
    if reasons:
        raise ContractError(reasons[0])
    return artifact


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prediction = sub.add_parser("capture-prediction")
    prediction.add_argument("--input", required=True)
    prediction.add_argument("--output", required=True)
    truth = sub.add_parser("capture-truth")
    truth.add_argument("--input", required=True)
    truth.add_argument("--prediction", required=True)
    truth.add_argument("--output", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--artifact", required=True)
    validate.add_argument("--prediction")
    args = parser.parse_args(argv)
    if args.command == "capture-prediction":
        artifact = build_prediction_capture(_load(args.input))
        atomic_write_json(Path(args.output), artifact)
    elif args.command == "capture-truth":
        prediction_artifact = _load(args.prediction)
        artifact = build_truth_capture(_load(args.input), prediction_artifact)
        atomic_write_json(Path(args.output), artifact)
    else:
        artifact = _load(args.artifact)
        if artifact.get("schemaVersion") == PREDICTION_SCHEMA_VERSION:
            reasons = validate_prediction_capture(artifact)
        else:
            _require(bool(args.prediction), "PREDICTION_PATH_REQUIRED_FOR_TRUTH")
            reasons = validate_truth_capture(artifact, _load(args.prediction))
        if reasons:
            raise ContractError(reasons[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
