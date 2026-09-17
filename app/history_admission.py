# -*- coding: utf-8 -*-
"""Shared, read-only History Admission Policy v1.

This module is the only authority for deciding whether a persisted record may
enter read-only History views/counts.  It does not assert that every field in
an admitted record is evaluation-grade truth.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence, Tuple


HISTORY_ADMISSION_POLICY_VERSION = 1
TIME_ZONE_NAME = "Asia/Shanghai"
LOCAL_TIME_ZONE = timezone(timedelta(hours=8), name=TIME_ZONE_NAME)


class HistoryExclusionReason:
    INVALID_RECORD = "INVALID_RECORD"
    MISSING_RECORD_ID = "MISSING_RECORD_ID"
    DUPLICATE_RECORD_ID = "DUPLICATE_RECORD_ID"
    DRAFT = "DRAFT"
    CANCELLED = "CANCELLED"
    DIAGNOSTIC = "DIAGNOSTIC"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    UNSUPPORTED_LIFECYCLE = "UNSUPPORTED_LIFECYCLE"
    LEGACY_WITHOUT_SETTLEMENT_EVIDENCE = "LEGACY_WITHOUT_SETTLEMENT_EVIDENCE"


class HistoryAdmissionFlag:
    LEGACY_TIMESTAMP_ASSUMED_ASIA_SHANGHAI = (
        "LEGACY_TIMESTAMP_ASSUMED_ASIA_SHANGHAI"
    )
    LEGACY_VERIFIED_SETTLEMENT_COMPATIBILITY = (
        "LEGACY_VERIFIED_SETTLEMENT_COMPATIBILITY"
    )
    TRUSTED_AUTO_ARCHIVE_COMPATIBILITY = "TRUSTED_AUTO_ARCHIVE_COMPATIBILITY"
    POTENTIAL_CONTENT_DUPLICATE = "POTENTIAL_CONTENT_DUPLICATE"


@dataclass(frozen=True)
class NormalizedTimestamp:
    local_time: datetime
    utc_time: datetime
    source_field: str
    assumption: str

    def to_metadata(self) -> dict:
        return {
            "playedAt": self.utc_time.isoformat().replace("+00:00", "Z"),
            "localPlayedAt": self.local_time.isoformat(),
            "sourceField": self.source_field,
            "assumption": self.assumption,
        }


@dataclass(frozen=True)
class DuplicateIndex:
    duplicate_record_ids: frozenset[str]
    potential_content_duplicate_ids: frozenset[str]
    potential_content_group_count: int


@dataclass(frozen=True)
class HistoryAdmissionDecision:
    admitted: bool
    record_id: Optional[str]
    normalized_time: Optional[NormalizedTimestamp]
    exclusion_reason: Optional[str]
    flags: Tuple[str, ...]
    lifecycle: str

    def normalized_metadata(self) -> dict:
        return {
            "historyAdmissionPolicyVersion": HISTORY_ADMISSION_POLICY_VERSION,
            "recordId": self.record_id,
            "admitted": self.admitted,
            "exclusionReason": self.exclusion_reason,
            "flags": list(self.flags),
            "lifecycle": self.lifecycle,
            "timestamp": (
                self.normalized_time.to_metadata()
                if self.normalized_time is not None
                else None
            ),
        }


def record_id(record: Mapping[str, Any]) -> Optional[str]:
    value = record.get("id")
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    normalized = str(value).strip()
    return normalized or None


def normalize_record_timestamp(record: Mapping[str, Any]) -> Optional[NormalizedTimestamp]:
    source_field = "playedAt" if record.get("playedAt") else "timestamp"
    raw_value = record.get(source_field)
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    text = raw_value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        local_time = parsed.replace(tzinfo=LOCAL_TIME_ZONE)
        assumption = "legacy_naive_asia_shanghai"
    else:
        local_time = parsed.astimezone(LOCAL_TIME_ZONE)
        assumption = "explicit_offset"
    return NormalizedTimestamp(
        local_time=local_time,
        utc_time=local_time.astimezone(timezone.utc),
        source_field=source_field,
        assumption=assumption,
    )


def build_duplicate_index(records: Sequence[Any]) -> DuplicateIndex:
    id_counts = Counter(
        rid
        for record in records
        if isinstance(record, Mapping)
        for rid in (record_id(record),)
        if rid is not None
    )
    duplicate_ids = frozenset(rid for rid, count in id_counts.items() if count > 1)

    content_groups: dict[str, list[str]] = defaultdict(list)
    for record in records:
        if not isinstance(record, Mapping):
            continue
        rid = record_id(record)
        if rid is None or rid in duplicate_ids:
            continue
        fingerprint = _potential_content_fingerprint(record)
        if fingerprint is not None:
            content_groups[fingerprint].append(rid)

    duplicate_content_groups = [
        tuple(sorted(set(group)))
        for group in content_groups.values()
        if len(set(group)) > 1
    ]
    potential_ids = frozenset(
        rid for group in duplicate_content_groups for rid in group
    )
    return DuplicateIndex(
        duplicate_record_ids=duplicate_ids,
        potential_content_duplicate_ids=potential_ids,
        potential_content_group_count=len(duplicate_content_groups),
    )


def evaluate_history_admission(
    record: Any,
    duplicate_index: DuplicateIndex,
) -> HistoryAdmissionDecision:
    if not isinstance(record, Mapping):
        return HistoryAdmissionDecision(
            admitted=False,
            record_id=None,
            normalized_time=None,
            exclusion_reason=HistoryExclusionReason.INVALID_RECORD,
            flags=(),
            lifecycle="",
        )

    normalized_time = normalize_record_timestamp(record)
    rid = record_id(record)
    lifecycle, status = _effective_lifecycle(record)
    flags: list[str] = []
    if normalized_time is not None and normalized_time.assumption.startswith("legacy_"):
        flags.append(HistoryAdmissionFlag.LEGACY_TIMESTAMP_ASSUMED_ASIA_SHANGHAI)
    if rid in duplicate_index.potential_content_duplicate_ids:
        flags.append(HistoryAdmissionFlag.POTENTIAL_CONTENT_DUPLICATE)

    reason: Optional[str] = None
    if lifecycle == "DRAFT":
        reason = HistoryExclusionReason.DRAFT
    elif lifecycle in {"CANCELLED", "CANCELED"}:
        reason = HistoryExclusionReason.CANCELLED
    elif (
        record.get("diagnosticOnly") is True
        or status == "DIAGNOSTIC"
        or str(record.get("solverStatus") or "").strip().lower() == "diagnostic"
    ):
        reason = HistoryExclusionReason.DIAGNOSTIC
    elif rid is None:
        reason = HistoryExclusionReason.MISSING_RECORD_ID
    elif rid in duplicate_index.duplicate_record_ids:
        reason = HistoryExclusionReason.DUPLICATE_RECORD_ID
    elif normalized_time is None:
        reason = HistoryExclusionReason.INVALID_TIMESTAMP
    elif lifecycle:
        if lifecycle != "FINALIZED":
            reason = HistoryExclusionReason.UNSUPPORTED_LIFECYCLE
    elif has_verified_legacy_settlement(record):
        flags.append(HistoryAdmissionFlag.LEGACY_VERIFIED_SETTLEMENT_COMPATIBILITY)
    elif is_trusted_auto_archive(record):
        flags.append(HistoryAdmissionFlag.TRUSTED_AUTO_ARCHIVE_COMPATIBILITY)
    else:
        reason = HistoryExclusionReason.LEGACY_WITHOUT_SETTLEMENT_EVIDENCE

    return HistoryAdmissionDecision(
        admitted=reason is None,
        record_id=rid,
        normalized_time=normalized_time,
        exclusion_reason=reason,
        flags=tuple(sorted(set(flags))),
        lifecycle=lifecycle or "LEGACY_UNSPECIFIED",
    )


def has_verified_legacy_settlement(record: Mapping[str, Any]) -> bool:
    settlement = record.get("settlement")
    if not isinstance(settlement, Mapping):
        return False
    actual_total = settlement.get("actualTotal", record.get("actualTotal"))
    return (
        settlement.get("verified") is True
        and str(settlement.get("status") or "").strip().lower() == "verified"
        and positive_finite(actual_total)
    )


def is_trusted_auto_archive(record: Mapping[str, Any]) -> bool:
    return (
        record.get("source") == "0.65-vision-auto-archiver"
        and positive_finite(record.get("actualTotal"))
        and positive_finite(record.get("clearingPrice"))
    )


def positive_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _effective_lifecycle(record: Mapping[str, Any]) -> tuple[str, str]:
    lifecycle = str(record.get("lifecycleStatus") or "").strip().upper()
    status = str(record.get("status") or "").strip().upper()
    if not lifecycle and status in {"DRAFT", "FINALIZED", "CANCELLED", "CANCELED"}:
        lifecycle = status
    return lifecycle, status


def _potential_content_fingerprint(record: Mapping[str, Any]) -> Optional[str]:
    timestamp = normalize_record_timestamp(record)
    environment = record.get("environment")
    if not isinstance(environment, Mapping):
        environment = {}
    venue = record.get("venue") or environment.get("venue")
    box = record.get("box") or environment.get("box")
    if timestamp is None or not venue or not box:
        return None
    settlement = record.get("settlement")
    if not isinstance(settlement, Mapping):
        settlement = {}
    payload = {
        "playedAt": timestamp.utc_time.isoformat(),
        "actualTotal": settlement.get("actualTotal", record.get("actualTotal")),
        "clearingPrice": settlement.get("clearingPrice", record.get("clearingPrice")),
        "venue": str(venue).strip(),
        "box": str(box).strip(),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def potential_content_duplicate_group_key(record: Mapping[str, Any]) -> Optional[str]:
    """Expose content fingerprint used for potential content duplicate detection."""
    return _potential_content_fingerprint(record)

