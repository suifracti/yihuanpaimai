# -*- coding: utf-8 -*-
"""Fail-closed Evaluation Eligibility Contracts v1.

This module validates provenance only.  It never imports or calls Solver,
Shadow, Vision, OCR, Main, or mutable runtime state, and it computes no model
performance metric.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

_APP_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _APP_DIR.parent
_CORE_DIR = _PROJECT_ROOT / "core"
for _p in (str(_CORE_DIR), str(_APP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from canonical_match_record import validate_canonical_match_record_v7
    from effective_truth_resolver import resolve_effective_record_truth
except ImportError:
    validate_canonical_match_record_v7 = None
    resolve_effective_record_truth = None

from history_admission import (
    HISTORY_ADMISSION_POLICY_VERSION,
    HistoryAdmissionDecision,
    HistoryAdmissionFlag,
    build_duplicate_index,
    evaluate_history_admission,
    positive_finite,
)


ELIGIBILITY_CONTRACT_VERSION = 1
PREDICTION_SNAPSHOT_SCHEMA_VERSION = "prediction-snapshot.v1"
TRUTH_EVIDENCE_SCHEMA_VERSION = "settlement-truth-evidence.v1"
FULL_VALUE_TARGET = "full_inventory_actual_total"
FULL_VALUE_SCOPE = "full_inventory"

ALLOWED_SNAPSHOT_ROLES = frozenset(("latest_valid_pre_settlement",))
ALLOWED_INFORMATION_MODES = frozenset(
    ("full_shadow", "partial_shadow", "structural_only")
)
ALLOWED_NORMALIZED_FACT_KEYS = frozenset(
    (
        "q",
        "goldCount",
        "purpleCount",
        "redCount",
        "minGold",
        "minPurple",
        "minRed",
        "goldAvg",
        "purpleAvg",
        "goldTotal",
        "costs",
        "knownGold",
        "knownPurple",
        "knownRed",
        "fieldCondition",
        "avgValueBasis",
        "roundingMode",
        "catalogVersion",
        "round",
        "targetProfit",
        "sparkle",
        "privateBidCap",
        "bidActionCount",
        "venue",
        "box",
        "character",
        "totalItems",
        "totalGrid",
        "qualities",
    )
)
FORBIDDEN_FACT_KEY_FRAGMENTS = (
    "ocr",
    "latestpayload",
    "currentmatch",
    "solverresult",
    "settlement",
    "actualtotal",
    "truth",
)


class EligibilityReason:
    DATA_ORIGIN_NOT_LIVE = "DATA_ORIGIN_NOT_LIVE"
    DATA_ORIGIN_MISSING = "DATA_ORIGIN_MISSING"
    RECORD_SCHEMA_VERSION_UNSUPPORTED = "RECORD_SCHEMA_VERSION_UNSUPPORTED"
    POTENTIAL_CONTENT_DUPLICATE = "POTENTIAL_CONTENT_DUPLICATE"
    TRUTH_EVIDENCE_MISSING = "TRUTH_EVIDENCE_MISSING"
    TRUTH_EVIDENCE_CONTRACT_VERSION_MISSING = (
        "TRUTH_EVIDENCE_CONTRACT_VERSION_MISSING"
    )
    TRUTH_MATCH_ID_MISSING = "TRUTH_MATCH_ID_MISSING"
    TRUTH_MATCH_ID_MISMATCH = "TRUTH_MATCH_ID_MISMATCH"
    SETTLEMENT_NOT_VERIFIED = "SETTLEMENT_NOT_VERIFIED"
    ACTUAL_TOTAL_INVALID = "ACTUAL_TOTAL_INVALID"
    TRUTH_SOURCE_MISSING = "TRUTH_SOURCE_MISSING"
    TRUTH_CONFIDENCE_NOT_HIGH = "TRUTH_CONFIDENCE_NOT_HIGH"
    SETTLEMENT_OBSERVED_AT_MISSING = "SETTLEMENT_OBSERVED_AT_MISSING"
    SETTLEMENT_OBSERVED_AT_INVALID = "SETTLEMENT_OBSERVED_AT_INVALID"
    TRUTH_EVIDENCE_REFERENCE_MISSING = "TRUTH_EVIDENCE_REFERENCE_MISSING"
    TRUTH_EVIDENCE_HASH_MISSING = "TRUTH_EVIDENCE_HASH_MISSING"
    TRUTH_EVIDENCE_HASH_INVALID = "TRUTH_EVIDENCE_HASH_INVALID"
    TRUTH_VERIFICATION_METHOD_MISSING = "TRUTH_VERIFICATION_METHOD_MISSING"
    TRUTH_VERIFICATION_VERSION_MISSING = "TRUTH_VERIFICATION_VERSION_MISSING"
    TRUTH_VERIFIER_IDENTITY_MISSING = "TRUTH_VERIFIER_IDENTITY_MISSING"
    TRUTH_PAYLOAD_HASH_MISSING = "TRUTH_PAYLOAD_HASH_MISSING"
    TRUTH_PAYLOAD_HASH_MISMATCH = "TRUTH_PAYLOAD_HASH_MISMATCH"
    UNRESOLVED_TRUTH_CONFLICT = "UNRESOLVED_TRUTH_CONFLICT"
    RED_TAIL_INVENTORY_SCOPE_INCOMPLETE = "RED_TAIL_INVENTORY_SCOPE_INCOMPLETE"
    RED_TAIL_ITEM_LEDGER_UNVERIFIED = "RED_TAIL_ITEM_LEDGER_UNVERIFIED"
    RED_TAIL_ITEM_LEDGER_NOT_DEDUPLICATED = (
        "RED_TAIL_ITEM_LEDGER_NOT_DEDUPLICATED"
    )
    RED_TAIL_ITEM_LEDGER_HASH_MISSING = "RED_TAIL_ITEM_LEDGER_HASH_MISSING"
    PREDICTION_SNAPSHOT_MISSING = "PREDICTION_SNAPSHOT_MISSING"
    PREDICTION_SNAPSHOT_VERSION_MISSING = "PREDICTION_SNAPSHOT_VERSION_MISSING"
    PREDICTION_ID_MISSING = "PREDICTION_ID_MISSING"
    MATCH_ID_MISSING = "MATCH_ID_MISSING"
    PREDICTION_MATCH_ID_MISMATCH = "PREDICTION_MATCH_ID_MISMATCH"
    SOLVED_AT_MISSING = "SOLVED_AT_MISSING"
    SOLVED_AT_INVALID = "SOLVED_AT_INVALID"
    INFORMATION_CUTOFF_AT_MISSING = "INFORMATION_CUTOFF_AT_MISSING"
    INFORMATION_CUTOFF_AT_INVALID = "INFORMATION_CUTOFF_AT_INVALID"
    SNAPSHOT_ROLE_MISSING = "SNAPSHOT_ROLE_MISSING"
    SNAPSHOT_ROLE_UNSUPPORTED = "SNAPSHOT_ROLE_UNSUPPORTED"
    SOLVER_VERSION_MISSING = "SOLVER_VERSION_MISSING"
    MODEL_VERSION_MISSING = "MODEL_VERSION_MISSING"
    CATALOG_VERSION_MISSING = "CATALOG_VERSION_MISSING"
    CODE_REVISION_MISSING = "CODE_REVISION_MISSING"
    PREDICTION_PRODUCER_MISSING = "PREDICTION_PRODUCER_MISSING"
    PREDICTION_SNAPSHOT_NOT_FROZEN = "PREDICTION_SNAPSHOT_NOT_FROZEN"
    INPUT_CONTRACT_VERSION_MISMATCH = "INPUT_CONTRACT_VERSION_MISMATCH"
    EXACT_NORMALIZED_INPUT_MISSING = "EXACT_NORMALIZED_INPUT_MISSING"
    NORMALIZED_INPUT_CONTAINS_FORBIDDEN_FIELD = (
        "NORMALIZED_INPUT_CONTAINS_FORBIDDEN_FIELD"
    )
    HASH_ALGORITHM_MISSING = "HASH_ALGORITHM_MISSING"
    HASH_ALGORITHM_UNSUPPORTED = "HASH_ALGORITHM_UNSUPPORTED"
    INPUT_HASH_MISSING = "INPUT_HASH_MISSING"
    INPUT_HASH_INVALID = "INPUT_HASH_INVALID"
    INPUT_HASH_MISMATCH = "INPUT_HASH_MISMATCH"
    LEGACY_WEAK_INPUT_HASH = "LEGACY_WEAK_INPUT_HASH"
    DATASET_REVISION_MISSING = "DATASET_REVISION_MISSING"
    DATASET_REVISION_INVALID = "DATASET_REVISION_INVALID"
    INFORMATION_MODE_MISSING = "INFORMATION_MODE_MISSING"
    INFORMATION_MODE_UNSUPPORTED = "INFORMATION_MODE_UNSUPPORTED"
    COVERAGE_RATIO_INVALID = "COVERAGE_RATIO_INVALID"
    SOLVER_STATUS_INCOMPLETE = "SOLVER_STATUS_INCOMPLETE"
    SOLVER_STATUS_FALLBACK = "SOLVER_STATUS_FALLBACK"
    SOLVER_STATUS_DIAGNOSTIC = "SOLVER_STATUS_DIAGNOSTIC"
    SOLVER_STATUS_NOT_VALID = "SOLVER_STATUS_NOT_VALID"
    FORECAST_TARGET_MISSING = "FORECAST_TARGET_MISSING"
    FORECAST_TARGET_MISMATCH = "FORECAST_TARGET_MISMATCH"
    FORECAST_SCOPE_MISSING = "FORECAST_SCOPE_MISSING"
    FORECAST_QUANTILES_INVALID = "FORECAST_QUANTILES_INVALID"
    PARTIAL_SHADOW_FULL_TRUTH_TARGET_MISMATCH = (
        "PARTIAL_SHADOW_FULL_TRUTH_TARGET_MISMATCH"
    )
    STRUCTURAL_ONLY_FULL_SHADOW_TARGET_MISMATCH = (
        "STRUCTURAL_ONLY_FULL_SHADOW_TARGET_MISMATCH"
    )
    FULL_SHADOW_COVERAGE_INCOMPLETE = "FULL_SHADOW_COVERAGE_INCOMPLETE"
    INFORMATION_CUTOFF_AFTER_SOLVE = "INFORMATION_CUTOFF_AFTER_SOLVE"
    PREDICTION_AFTER_SETTLEMENT = "PREDICTION_AFTER_SETTLEMENT"
    MODEL_COHORT_MISMATCH = "MODEL_COHORT_MISMATCH"


@dataclass(frozen=True)
class ModelCohort:
    solver_version: str
    model_version: str
    catalog_version: str
    code_revision: str
    information_mode: str
    forecast_target: str

    def key(self) -> str:
        return "|".join(
            (
                self.solver_version,
                self.model_version,
                self.catalog_version,
                self.code_revision,
                self.information_mode,
                self.forecast_target,
            )
        )

    def to_payload(self) -> dict:
        return {
            "solverVersion": self.solver_version,
            "modelVersion": self.model_version,
            "catalogVersion": self.catalog_version,
            "codeRevision": self.code_revision,
            "informationMode": self.information_mode,
            "forecastTarget": self.forecast_target,
        }


@dataclass(frozen=True)
class EligibilityResult:
    record_id: Optional[str]
    history: HistoryAdmissionDecision
    legacy_candidate: bool
    legacy_solver_valid: bool
    legacy_valid_full_coverage: bool
    formally_eligible: bool
    reasons: Tuple[str, ...]
    normalized_metadata: Tuple[Tuple[str, Any], ...]
    cohort: Optional[ModelCohort]

    @property
    def primary_reason(self) -> Optional[str]:
        return self.reasons[0] if self.reasons else None

    def metadata_payload(self) -> dict:
        return {key: value for key, value in self.normalized_metadata}


@dataclass(frozen=True)
class EligibilityScanSummary:
    source_sha256: str
    source_schema_version: Optional[int]
    record_count: int
    history_admitted_count: int
    history_excluded_count: int
    evaluation_candidate_count: int
    solver_valid_candidate_count: int
    valid_full_coverage_candidate_count: int
    formally_eligible_count: int
    history_exclusion_reason_counts: Tuple[Tuple[str, int], ...]
    history_flag_counts: Tuple[Tuple[str, int], ...]
    primary_rejection_reason_counts: Tuple[Tuple[str, int], ...]
    all_reason_counts: Tuple[Tuple[str, int], ...]
    eligible_cohort_counts: Tuple[Tuple[str, int], ...]
    potential_content_duplicate_group_count: int

    def to_payload(self) -> dict:
        primary = dict(self.primary_rejection_reason_counts)
        invariant_total = self.formally_eligible_count + sum(primary.values())
        return {
            "eligibilityContractVersion": ELIGIBILITY_CONTRACT_VERSION,
            "contracts": {
                "historyAdmissionPolicyVersion": HISTORY_ADMISSION_POLICY_VERSION,
                "predictionSnapshotSchemaVersion": PREDICTION_SNAPSHOT_SCHEMA_VERSION,
                "settlementTruthEvidenceSchemaVersion": TRUTH_EVIDENCE_SCHEMA_VERSION,
            },
            "sourceRevision": {
                "sourceId": "canonical_match_history",
                "schemaVersion": self.source_schema_version,
                "sha256": self.source_sha256,
                "recordCount": self.record_count,
            },
            "counts": {
                "recordCount": self.record_count,
                "historyAdmittedCount": self.history_admitted_count,
                "historyExcludedCount": self.history_excluded_count,
                "evaluationCandidateCount": self.evaluation_candidate_count,
                "solverValidCandidateCount": self.solver_valid_candidate_count,
                "validFullCoverageCandidateCount": self.valid_full_coverage_candidate_count,
                "formallyEligibleCount": self.formally_eligible_count,
                "primaryRejectionCount": sum(primary.values()),
            },
            "historyExclusionReasonCounts": dict(
                self.history_exclusion_reason_counts
            ),
            "historyFlagCounts": dict(self.history_flag_counts),
            "primaryRejectionReasonCounts": primary,
            "allReasonCounts": dict(self.all_reason_counts),
            "eligibleCohortCounts": dict(self.eligible_cohort_counts),
            "potentialContentDuplicateGroupCount": (
                self.potential_content_duplicate_group_count
            ),
            "invariants": {
                "primaryReasonsPlusEligibleEqualsRecordCount": (
                    invariant_total == self.record_count
                ),
                "primaryReasonsPlusEligible": invariant_total,
                "metricsComputed": False,
                "historyMutated": False,
            },
        }


def scan_history_file(
    history_path: Path | str,
    *,
    required_cohort: Optional[ModelCohort] = None,
    target_kind: str = "full_value",
    data_root: Optional[Path | str] = None,
) -> EligibilityScanSummary:
    path = Path(history_path).resolve()
    before = path.stat()
    raw_bytes = path.read_bytes()
    after = path.stat()
    if (
        before.st_mtime_ns != after.st_mtime_ns
        or before.st_size != after.st_size
        or len(raw_bytes) != after.st_size
    ):
        raise RuntimeError("History changed during eligibility scan")
    effective_root = data_root if data_root is not None else path.parent
    return scan_history_bytes(
        raw_bytes,
        required_cohort=required_cohort,
        target_kind=target_kind,
        data_root=effective_root,
    )


def scan_history_bytes(
    raw_bytes: bytes,
    *,
    required_cohort: Optional[ModelCohort] = None,
    target_kind: str = "full_value",
    data_root: Optional[Path | str] = None,
) -> EligibilityScanSummary:
    document = json.loads(raw_bytes.decode("utf-8"))
    if isinstance(document, list):
        records = document
        schema_version = None
    elif isinstance(document, Mapping):
        records = document.get("records") or []
        schema_version = document.get("schemaVersion")
    else:
        raise ValueError("History must be a JSON object or array")
    if not isinstance(records, list):
        raise ValueError("History records must be an array")
    return scan_records(
        records,
        source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        source_schema_version=(
            schema_version
            if isinstance(schema_version, int) and not isinstance(schema_version, bool)
            else None
        ),
        required_cohort=required_cohort,
        target_kind=target_kind,
        data_root=data_root,
    )


def scan_records(
    records: Sequence[Any],
    *,
    source_sha256: str = "fixture",
    source_schema_version: Optional[int] = None,
    required_cohort: Optional[ModelCohort] = None,
    target_kind: str = "full_value",
    data_root: Optional[Path | str] = None,
) -> EligibilityScanSummary:
    duplicate_index = build_duplicate_index(records)
    results = [
        evaluate_record_eligibility(
            record,
            duplicate_index,
            required_cohort=required_cohort,
            target_kind=target_kind,
            data_root=data_root,
        )
        for record in records
    ]

    history_exclusions = Counter(
        result.history.exclusion_reason
        for result in results
        if not result.history.admitted
    )
    flags = Counter(flag for result in results for flag in result.history.flags)
    primary_rejections = Counter(
        result.primary_reason for result in results if not result.formally_eligible
    )
    all_reasons = Counter(reason for result in results for reason in result.reasons)
    cohorts = Counter(
        result.cohort.key()
        for result in results
        if result.formally_eligible and result.cohort is not None
    )
    admitted = sum(result.history.admitted for result in results)
    return EligibilityScanSummary(
        source_sha256=source_sha256,
        source_schema_version=source_schema_version,
        record_count=len(records),
        history_admitted_count=admitted,
        history_excluded_count=len(records) - admitted,
        evaluation_candidate_count=sum(result.legacy_candidate for result in results),
        solver_valid_candidate_count=sum(result.legacy_solver_valid for result in results),
        valid_full_coverage_candidate_count=sum(
            result.legacy_valid_full_coverage for result in results
        ),
        formally_eligible_count=sum(result.formally_eligible for result in results),
        history_exclusion_reason_counts=tuple(sorted(history_exclusions.items())),
        history_flag_counts=tuple(sorted(flags.items())),
        primary_rejection_reason_counts=tuple(sorted(primary_rejections.items())),
        all_reason_counts=tuple(sorted(all_reasons.items())),
        eligible_cohort_counts=tuple(sorted(cohorts.items())),
        potential_content_duplicate_group_count=(
            duplicate_index.potential_content_group_count
        ),
    )


def evaluate_record_eligibility(
    record: Any,
    duplicate_index,
    *,
    required_cohort: Optional[ModelCohort] = None,
    target_kind: str = "full_value",
    data_root: Optional[Path | str] = None,
) -> EligibilityResult:
    if resolve_effective_record_truth is not None and isinstance(record, Mapping):
        effective_record = resolve_effective_record_truth(record, data_root=data_root)
    else:
        effective_record = record

    history = evaluate_history_admission(effective_record, duplicate_index)
    if not history.admitted:
        history_reasons = [history.exclusion_reason]
        if HistoryAdmissionFlag.POTENTIAL_CONTENT_DUPLICATE in history.flags:
            history_reasons.append(EligibilityReason.POTENTIAL_CONTENT_DUPLICATE)
        return EligibilityResult(
            record_id=history.record_id,
            history=history,
            legacy_candidate=False,
            legacy_solver_valid=False,
            legacy_valid_full_coverage=False,
            formally_eligible=False,
            reasons=tuple(history_reasons),
            normalized_metadata=(),
            cohort=None,
        )

    legacy_candidate, legacy_valid, legacy_full = _legacy_candidate_state(effective_record)
    reasons: list[str] = []
    origin = effective_record.get("dataOrigin") or effective_record.get("executionOrigin")
    if HistoryAdmissionFlag.POTENTIAL_CONTENT_DUPLICATE in history.flags:
        reasons.append(EligibilityReason.POTENTIAL_CONTENT_DUPLICATE)

    if effective_record.get("schemaVersion") != 7:
        reasons.append(EligibilityReason.RECORD_SCHEMA_VERSION_UNSUPPORTED)
    else:
        if validate_canonical_match_record_v7 is not None:
            is_canon_valid, _ = validate_canonical_match_record_v7(effective_record)
            if not is_canon_valid:
                reasons.append(EligibilityReason.RECORD_SCHEMA_VERSION_UNSUPPORTED)

        # Provenance / Data Origin Gate: Only unadulterated live matches qualify for formal evaluation
        if origin is None or not str(origin).strip():
            reasons.append(EligibilityReason.DATA_ORIGIN_MISSING)
        elif str(origin).strip().lower() != "live":
            reasons.append(EligibilityReason.DATA_ORIGIN_NOT_LIVE)

    truth_reasons, truth_meta = _validate_truth_evidence(effective_record, target_kind)
    prediction_reasons, prediction_meta, cohort = _validate_prediction_snapshot(effective_record)
    reasons.extend(truth_reasons)
    reasons.extend(prediction_reasons)

    solved_at = prediction_meta.get("solvedAt")
    cutoff_at = prediction_meta.get("informationCutoffAt")
    observed_at = truth_meta.get("settlementObservedAt")
    if isinstance(cutoff_at, datetime) and isinstance(solved_at, datetime):
        if cutoff_at > solved_at:
            reasons.append(EligibilityReason.INFORMATION_CUTOFF_AFTER_SOLVE)
    if isinstance(observed_at, datetime):
        if (
            isinstance(solved_at, datetime)
            and solved_at >= observed_at
        ) or (
            isinstance(cutoff_at, datetime)
            and cutoff_at >= observed_at
        ):
            reasons.append(EligibilityReason.PREDICTION_AFTER_SETTLEMENT)

    mode = prediction_meta.get("informationMode")
    forecast_target = prediction_meta.get("forecastTarget")
    if forecast_target == FULL_VALUE_TARGET and mode == "partial_shadow":
        reasons.append(
            EligibilityReason.PARTIAL_SHADOW_FULL_TRUTH_TARGET_MISMATCH
        )
    if forecast_target == FULL_VALUE_TARGET and mode == "structural_only":
        reasons.append(
            EligibilityReason.STRUCTURAL_ONLY_FULL_SHADOW_TARGET_MISMATCH
        )
    if (
        target_kind == "full_value"
        and forecast_target is not None
        and forecast_target != FULL_VALUE_TARGET
    ):
        reasons.append(EligibilityReason.FORECAST_TARGET_MISMATCH)
    if required_cohort is not None and cohort is not None and cohort != required_cohort:
        reasons.append(EligibilityReason.MODEL_COHORT_MISMATCH)

    reasons = list(dict.fromkeys(reasons))
    metadata = {
        "candidateStatus": "legacy_candidate" if legacy_candidate else "not_candidate",
        "dataOrigin": str(origin).strip().lower() if origin else None,
        "historyAdmissionPolicyVersion": HISTORY_ADMISSION_POLICY_VERSION,
        "predictionSnapshotSchemaVersion": prediction_meta.get("schemaVersion"),
        "truthEvidenceSchemaVersion": truth_meta.get("schemaVersion"),
        "informationMode": mode,
        "coverageRatio": prediction_meta.get("coverageRatio"),
        "forecastTarget": forecast_target,
        "solverStatus": prediction_meta.get("solverStatus"),
    }
    return EligibilityResult(
        record_id=history.record_id,
        history=history,
        legacy_candidate=legacy_candidate,
        legacy_solver_valid=legacy_valid,
        legacy_valid_full_coverage=legacy_full,
        formally_eligible=not reasons,
        reasons=tuple(reasons),
        normalized_metadata=tuple(sorted(metadata.items())),
        cohort=cohort,
    )


def _validate_truth_evidence(
    record: Mapping[str, Any], target_kind: str
) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    settlement = record.get("settlement")
    if not isinstance(settlement, Mapping):
        settlement = {}
    evidence = settlement.get("truthEvidence")
    if not isinstance(evidence, Mapping):
        reasons.extend(
            (
                EligibilityReason.TRUTH_EVIDENCE_MISSING,
                EligibilityReason.TRUTH_EVIDENCE_CONTRACT_VERSION_MISSING,
                EligibilityReason.SETTLEMENT_OBSERVED_AT_MISSING,
                EligibilityReason.TRUTH_EVIDENCE_REFERENCE_MISSING,
                EligibilityReason.TRUTH_EVIDENCE_HASH_MISSING,
                EligibilityReason.TRUTH_VERIFICATION_METHOD_MISSING,
                EligibilityReason.TRUTH_VERIFICATION_VERSION_MISSING,
                EligibilityReason.TRUTH_VERIFIER_IDENTITY_MISSING,
                EligibilityReason.TRUTH_PAYLOAD_HASH_MISSING,
            )
        )
        return reasons, {}

    if evidence.get("schemaVersion") != TRUTH_EVIDENCE_SCHEMA_VERSION:
        reasons.append(EligibilityReason.TRUTH_EVIDENCE_CONTRACT_VERSION_MISSING)
    rid = str(record.get("id") or "").strip()
    match_id = str(evidence.get("matchId") or "").strip()
    if not match_id:
        reasons.append(EligibilityReason.TRUTH_MATCH_ID_MISSING)
    elif match_id != rid:
        reasons.append(EligibilityReason.TRUTH_MATCH_ID_MISMATCH)
    if settlement.get("verified") is not True or str(
        settlement.get("status") or ""
    ).lower() != "verified":
        reasons.append(EligibilityReason.SETTLEMENT_NOT_VERIFIED)
    actual_total = evidence.get("actualTotal")
    if not positive_finite(actual_total) or actual_total != settlement.get("actualTotal"):
        reasons.append(EligibilityReason.ACTUAL_TOTAL_INVALID)
    truth_source = str(evidence.get("truthSource") or "").strip()
    if not truth_source:
        reasons.append(EligibilityReason.TRUTH_SOURCE_MISSING)
    if str(evidence.get("truthConfidence") or "").strip().lower() != "high":
        reasons.append(EligibilityReason.TRUTH_CONFIDENCE_NOT_HIGH)
    observed_raw = evidence.get("settlementObservedAt")
    observed_at = _parse_aware_iso(observed_raw)
    if not observed_raw:
        reasons.append(EligibilityReason.SETTLEMENT_OBSERVED_AT_MISSING)
    elif observed_at is None:
        reasons.append(EligibilityReason.SETTLEMENT_OBSERVED_AT_INVALID)

    references = evidence.get("evidenceReferences")
    if not isinstance(references, list) or not references:
        reasons.append(EligibilityReason.TRUTH_EVIDENCE_REFERENCE_MISSING)
        reasons.append(EligibilityReason.TRUTH_EVIDENCE_HASH_MISSING)
    else:
        for reference in references:
            if not isinstance(reference, Mapping) or not str(
                reference.get("uri") or reference.get("path") or ""
            ).strip():
                reasons.append(EligibilityReason.TRUTH_EVIDENCE_REFERENCE_MISSING)
                continue
            digest = reference.get("sha256")
            if not digest:
                reasons.append(EligibilityReason.TRUTH_EVIDENCE_HASH_MISSING)
            elif not _is_sha256(digest):
                reasons.append(EligibilityReason.TRUTH_EVIDENCE_HASH_INVALID)

    verification = evidence.get("verification")
    if not isinstance(verification, Mapping):
        verification = {}
    if not str(verification.get("method") or "").strip():
        reasons.append(EligibilityReason.TRUTH_VERIFICATION_METHOD_MISSING)
    if not str(verification.get("version") or "").strip():
        reasons.append(EligibilityReason.TRUTH_VERIFICATION_VERSION_MISSING)
    verifier = verification.get("verifier")
    if not isinstance(verifier, Mapping) or not str(
        verifier.get("type") or ""
    ).strip() or not str(verifier.get("id") or "").strip():
        reasons.append(EligibilityReason.TRUTH_VERIFIER_IDENTITY_MISSING)

    if evidence.get("unresolvedTruthConflict") is not False:
        reasons.append(EligibilityReason.UNRESOLVED_TRUTH_CONFLICT)

    payload_digest = evidence.get("truthPayloadSha256")
    if not payload_digest:
        reasons.append(EligibilityReason.TRUTH_PAYLOAD_HASH_MISSING)
    else:
        expected = _sha256_json(
            {
                "matchId": match_id,
                "actualTotal": actual_total,
                "settlementObservedAt": observed_raw,
                "truthSource": truth_source,
            }
        )
        if not _is_sha256(payload_digest) or payload_digest != expected:
            reasons.append(EligibilityReason.TRUTH_PAYLOAD_HASH_MISMATCH)

    if target_kind in {"red_tail", "item_level"}:
        scope = evidence.get("inventoryScope")
        if not isinstance(scope, Mapping) or scope.get("complete") is not True:
            reasons.append(EligibilityReason.RED_TAIL_INVENTORY_SCOPE_INCOMPLETE)
        ledger = evidence.get("itemLedger")
        if not isinstance(ledger, Mapping) or ledger.get("verified") is not True:
            reasons.append(EligibilityReason.RED_TAIL_ITEM_LEDGER_UNVERIFIED)
        if not isinstance(ledger, Mapping) or ledger.get("deduplicated") is not True:
            reasons.append(
                EligibilityReason.RED_TAIL_ITEM_LEDGER_NOT_DEDUPLICATED
            )
        if not isinstance(ledger, Mapping) or not _is_sha256(ledger.get("sha256")):
            reasons.append(EligibilityReason.RED_TAIL_ITEM_LEDGER_HASH_MISSING)

    return list(dict.fromkeys(reasons)), {
        "schemaVersion": evidence.get("schemaVersion"),
        "settlementObservedAt": observed_at,
    }


def _validate_prediction_snapshot(
    record: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any], Optional[ModelCohort]]:
    reasons: list[str] = []
    snapshot = record.get("predictionSnapshot")
    legacy_prediction = record.get("prediction")
    if not isinstance(snapshot, Mapping):
        reasons.append(EligibilityReason.PREDICTION_SNAPSHOT_MISSING)
        reasons.append(EligibilityReason.PREDICTION_SNAPSHOT_VERSION_MISSING)
        reasons.append(EligibilityReason.EXACT_NORMALIZED_INPUT_MISSING)
        reasons.append(EligibilityReason.HASH_ALGORITHM_MISSING)
        reasons.append(EligibilityReason.DATASET_REVISION_MISSING)
        if isinstance(legacy_prediction, Mapping):
            legacy_hash = str(legacy_prediction.get("inputHash") or "")
            if legacy_hash.startswith("sha1-"):
                reasons.append(EligibilityReason.LEGACY_WEAK_INPUT_HASH)
            if not legacy_prediction.get("solvedAt"):
                reasons.append(EligibilityReason.SOLVED_AT_MISSING)
            if not legacy_prediction.get("solverVersion"):
                reasons.append(EligibilityReason.SOLVER_VERSION_MISSING)
            if not legacy_prediction.get("modelVersion"):
                reasons.append(EligibilityReason.MODEL_VERSION_MISSING)
        else:
            reasons.extend(
                (
                    EligibilityReason.SOLVED_AT_MISSING,
                    EligibilityReason.SOLVER_VERSION_MISSING,
                    EligibilityReason.MODEL_VERSION_MISSING,
                )
            )
        return list(dict.fromkeys(reasons)), {}, None

    if snapshot.get("schemaVersion") != PREDICTION_SNAPSHOT_SCHEMA_VERSION:
        reasons.append(EligibilityReason.PREDICTION_SNAPSHOT_VERSION_MISSING)
    if snapshot.get("frozen") is not True:
        reasons.append(EligibilityReason.PREDICTION_SNAPSHOT_NOT_FROZEN)
    prediction_id = str(snapshot.get("predictionId") or "").strip()
    if not prediction_id:
        reasons.append(EligibilityReason.PREDICTION_ID_MISSING)
    match_id = str(snapshot.get("matchId") or "").strip()
    if not match_id:
        reasons.append(EligibilityReason.MATCH_ID_MISSING)
    elif match_id != str(record.get("id") or "").strip():
        reasons.append(EligibilityReason.PREDICTION_MATCH_ID_MISMATCH)

    solved_raw = snapshot.get("solvedAt")
    solved_at = _parse_aware_iso(solved_raw)
    if not solved_raw:
        reasons.append(EligibilityReason.SOLVED_AT_MISSING)
    elif solved_at is None:
        reasons.append(EligibilityReason.SOLVED_AT_INVALID)
    cutoff_raw = snapshot.get("informationCutoffAt")
    cutoff_at = _parse_aware_iso(cutoff_raw)
    if not cutoff_raw:
        reasons.append(EligibilityReason.INFORMATION_CUTOFF_AT_MISSING)
    elif cutoff_at is None:
        reasons.append(EligibilityReason.INFORMATION_CUTOFF_AT_INVALID)

    role = str(snapshot.get("snapshotRole") or "").strip()
    if not role:
        reasons.append(EligibilityReason.SNAPSHOT_ROLE_MISSING)
    elif role not in ALLOWED_SNAPSHOT_ROLES:
        reasons.append(EligibilityReason.SNAPSHOT_ROLE_UNSUPPORTED)

    producer = snapshot.get("producer")
    if not isinstance(producer, Mapping):
        producer = {}
    if not str(producer.get("runtime") or "").strip() or not str(
        producer.get("solverName") or ""
    ).strip():
        reasons.append(EligibilityReason.PREDICTION_PRODUCER_MISSING)
    solver_version = str(producer.get("solverVersion") or "").strip()
    model_version = str(producer.get("modelVersion") or "").strip()
    catalog_version = str(producer.get("catalogVersion") or "").strip()
    code_revision = str(producer.get("codeRevision") or "").strip()
    if not solver_version:
        reasons.append(EligibilityReason.SOLVER_VERSION_MISSING)
    if not model_version:
        reasons.append(EligibilityReason.MODEL_VERSION_MISSING)
    if not catalog_version:
        reasons.append(EligibilityReason.CATALOG_VERSION_MISSING)
    if not code_revision:
        reasons.append(EligibilityReason.CODE_REVISION_MISSING)

    input_contract = snapshot.get("input")
    if not isinstance(input_contract, Mapping):
        input_contract = {}
    if input_contract.get("contractVersion") != 1:
        reasons.append(EligibilityReason.INPUT_CONTRACT_VERSION_MISMATCH)
    facts = input_contract.get("normalizedFacts")
    if not isinstance(facts, Mapping):
        reasons.append(EligibilityReason.EXACT_NORMALIZED_INPUT_MISSING)
    elif _facts_have_forbidden_fields(facts):
        reasons.append(EligibilityReason.NORMALIZED_INPUT_CONTAINS_FORBIDDEN_FIELD)
    hash_algorithm = str(input_contract.get("hashAlgorithm") or "").strip().lower()
    if not hash_algorithm:
        reasons.append(EligibilityReason.HASH_ALGORITHM_MISSING)
    elif hash_algorithm != "sha256":
        reasons.append(EligibilityReason.HASH_ALGORITHM_UNSUPPORTED)
    input_hash = str(input_contract.get("inputHash") or "").strip()
    if not input_hash:
        reasons.append(EligibilityReason.INPUT_HASH_MISSING)
    elif not _is_sha256(input_hash):
        reasons.append(EligibilityReason.INPUT_HASH_INVALID)
    elif isinstance(facts, Mapping) and input_hash != _sha256_json(facts):
        reasons.append(EligibilityReason.INPUT_HASH_MISMATCH)
    dataset_revision = input_contract.get("datasetRevision")
    if not isinstance(dataset_revision, Mapping):
        reasons.append(EligibilityReason.DATASET_REVISION_MISSING)
    elif not _valid_dataset_revision(dataset_revision):
        reasons.append(EligibilityReason.DATASET_REVISION_INVALID)

    mode = snapshot.get("mode")
    if not isinstance(mode, Mapping):
        mode = {}
    information_mode = str(mode.get("informationMode") or "").strip()
    if not information_mode:
        reasons.append(EligibilityReason.INFORMATION_MODE_MISSING)
    elif information_mode not in ALLOWED_INFORMATION_MODES:
        reasons.append(EligibilityReason.INFORMATION_MODE_UNSUPPORTED)
    coverage_ratio = mode.get("coverageRatio")
    if not _finite_number(coverage_ratio) or not 0 <= coverage_ratio <= 1:
        reasons.append(EligibilityReason.COVERAGE_RATIO_INVALID)
    elif information_mode == "full_shadow" and coverage_ratio < 0.999999:
        reasons.append(EligibilityReason.FULL_SHADOW_COVERAGE_INCOMPLETE)

    status = snapshot.get("status")
    if not isinstance(status, Mapping):
        status = {}
    solver_status = str(status.get("solverStatus") or "").strip().lower()
    if solver_status == "incomplete":
        reasons.append(EligibilityReason.SOLVER_STATUS_INCOMPLETE)
    elif solver_status == "fallback":
        reasons.append(EligibilityReason.SOLVER_STATUS_FALLBACK)
    elif solver_status == "diagnostic" or status.get("diagnosticOnly") is True:
        reasons.append(EligibilityReason.SOLVER_STATUS_DIAGNOSTIC)
    elif solver_status != "valid" or status.get("provisional") is not False:
        reasons.append(EligibilityReason.SOLVER_STATUS_NOT_VALID)

    forecast = snapshot.get("forecast")
    if not isinstance(forecast, Mapping):
        forecast = {}
    forecast_target = str(forecast.get("target") or "").strip()
    forecast_scope = str(forecast.get("scope") or "").strip()
    if not forecast_target:
        reasons.append(EligibilityReason.FORECAST_TARGET_MISSING)
    if not forecast_scope:
        reasons.append(EligibilityReason.FORECAST_SCOPE_MISSING)
    quantiles = forecast.get("quantiles")
    if information_mode == "full_shadow" and not _valid_quantiles(quantiles):
        reasons.append(EligibilityReason.FORECAST_QUANTILES_INVALID)
    if forecast_target == FULL_VALUE_TARGET and forecast_scope != FULL_VALUE_SCOPE:
        reasons.append(EligibilityReason.FORECAST_SCOPE_MISSING)

    cohort = None
    if all(
        (
            solver_version,
            model_version,
            catalog_version,
            code_revision,
            information_mode,
            forecast_target,
        )
    ):
        cohort = ModelCohort(
            solver_version=solver_version,
            model_version=model_version,
            catalog_version=catalog_version,
            code_revision=code_revision,
            information_mode=information_mode,
            forecast_target=forecast_target,
        )
    return list(dict.fromkeys(reasons)), {
        "schemaVersion": snapshot.get("schemaVersion"),
        "solvedAt": solved_at,
        "informationCutoffAt": cutoff_at,
        "informationMode": information_mode or None,
        "coverageRatio": coverage_ratio if _finite_number(coverage_ratio) else None,
        "forecastTarget": forecast_target or None,
        "solverStatus": solver_status or None,
    }, cohort


def _legacy_candidate_state(record: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    prediction = record.get("prediction")
    settlement = record.get("settlement")
    if not isinstance(prediction, Mapping) or not isinstance(settlement, Mapping):
        return False, False, False
    calibrated = prediction.get("shadowCalibrated")
    calibrated_values = (
        calibrated.get("calibrated") if isinstance(calibrated, Mapping) else None
    )
    candidate = all(
        (
            settlement.get("verified") is True,
            str(settlement.get("status") or "").lower() == "verified",
            str(settlement.get("truthConfidence") or "").lower() == "high",
            positive_finite(settlement.get("actualTotal", record.get("actualTotal"))),
            bool(prediction.get("solvedAt")),
            bool(prediction.get("inputHash")),
            bool(prediction.get("solverVersion")),
            bool(prediction.get("modelVersion")),
            bool(prediction.get("catalogVersion")),
            _valid_quantiles(calibrated_values),
        )
    )
    if not candidate:
        return False, False, False
    solver_valid = str(prediction.get("solverStatus") or "").lower() == "valid"
    profile = prediction.get("probabilityProfile")
    coverage = profile.get("coverageRatio") if isinstance(profile, Mapping) else None
    full = solver_valid and _finite_number(coverage) and coverage >= 0.999999
    return True, solver_valid, full


def _parse_aware_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _facts_have_forbidden_fields(facts: Mapping[str, Any]) -> bool:
    for key in facts:
        normalized = str(key).replace("_", "").lower()
        if key not in ALLOWED_NORMALIZED_FACT_KEYS:
            return True
        if any(fragment in normalized for fragment in FORBIDDEN_FACT_KEY_FRAGMENTS):
            return True
    return _nested_value_has_forbidden_key(facts)


def _nested_value_has_forbidden_key(value: Any, *, top_level: bool = True) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).replace("_", "").lower()
            if not top_level and any(
                fragment in normalized for fragment in FORBIDDEN_FACT_KEY_FRAGMENTS
            ):
                return True
            if _nested_value_has_forbidden_key(child, top_level=False):
                return True
    elif isinstance(value, (list, tuple)):
        return any(
            _nested_value_has_forbidden_key(child, top_level=False) for child in value
        )
    return False


def _valid_dataset_revision(revision: Mapping[str, Any]) -> bool:
    return all(
        (
            str(revision.get("sourceId") or "").strip(),
            _is_sha256(revision.get("sha256")),
            isinstance(revision.get("recordCount"), int)
            and not isinstance(revision.get("recordCount"), bool)
            and revision.get("recordCount") >= 0,
            revision.get("admissionPolicyVersion")
            == HISTORY_ADMISSION_POLICY_VERSION,
            _parse_aware_iso(revision.get("cutoffExclusive")) is not None,
            _is_sha256(revision.get("eligibleRecordIdsSha256")),
        )
    )


def _valid_quantiles(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    q20, q50, q80 = value.get("p20"), value.get("p50"), value.get("p80")
    return all(_finite_number(v) and v >= 0 for v in (q20, q50, q80)) and q20 <= q50 <= q80


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return value == value.lower() and all(
        character in "0123456789abcdef" for character in value
    )


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_truth_payload_sha256(
    *, match_id: str, actual_total: float, settlement_observed_at: str, truth_source: str
) -> str:
    """Fixture/producer helper; it does not inspect or infer evidence."""
    return _sha256_json(
        {
            "matchId": match_id,
            "actualTotal": actual_total,
            "settlementObservedAt": settlement_observed_at,
            "truthSource": truth_source,
        }
    )


def build_input_sha256(normalized_facts: Mapping[str, Any]) -> str:
    """Fixture/producer helper for the exact normalized facts payload."""
    return _sha256_json(normalized_facts)


def validate_prediction_snapshot(
    record_or_snapshot: Mapping[str, Any], match_id: Optional[str] = None
) -> Tuple[bool, List[EligibilityReason]]:
    """Validate a Prediction Snapshot v1 against the formal evaluation eligibility contract.

    Returns:
        (is_valid, list_of_reasons)
    """
    if not isinstance(record_or_snapshot, Mapping):
        return False, [EligibilityReason.PREDICTION_SNAPSHOT_MISSING]
    if "predictionSnapshot" in record_or_snapshot:
        rec = dict(record_or_snapshot)
        if match_id and "id" not in rec:
            rec["id"] = match_id
    else:
        rec = {"id": match_id or record_or_snapshot.get("matchId"), "predictionSnapshot": record_or_snapshot}
    reasons, _, _ = _validate_prediction_snapshot(rec)
    return len(reasons) == 0, reasons


def validate_prediction_snapshot_for_storage(
    snapshot: Mapping[str, Any], match_id: Optional[str] = None
) -> Tuple[bool, list]:
    """Preserve authentic non-evaluable outputs without granting eligibility.

    Provenance, input hash, match identity and forecast checks remain mandatory.
    A known fallback/incomplete/diagnostic status alone is not data corruption.
    Formal evaluation must continue to use validate_prediction_snapshot.
    """
    valid, reasons = validate_prediction_snapshot(snapshot, match_id=match_id)
    if valid or not isinstance(snapshot, Mapping):
        return valid, reasons
    status = snapshot.get("status")
    if not isinstance(status, Mapping):
        return False, reasons
    allowed_reason = {
        "fallback": EligibilityReason.SOLVER_STATUS_FALLBACK,
        "incomplete": EligibilityReason.SOLVER_STATUS_INCOMPLETE,
        "diagnostic": EligibilityReason.SOLVER_STATUS_DIAGNOSTIC,
    }.get(status.get("solverStatus"))
    if (allowed_reason is None
            or not isinstance(status.get("provisional"), bool)
            or not isinstance(status.get("diagnosticOnly"), bool)):
        return False, reasons
    remaining = [reason for reason in reasons if reason != allowed_reason]
    return not remaining, remaining
