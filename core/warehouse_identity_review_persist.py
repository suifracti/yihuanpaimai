"""Atomic Canonical History adapter for warehouse identity review artifacts.

Writes Native-owned review artifacts and their per-item identity projection atomically.
Does not accept client packets, artifacts, paths, hashes, bboxes, names, or qualities.
Does not change lifecycle, settlement verification, or History admission.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Mapping, Optional

from canonical_history_store import CanonicalHistoryStore, HistoryStoreError
from canonical_match_record import (
    validate_canonical_match_record_v7,
    validate_finalized_match_record_v7,
)
from warehouse_identity_review import (
    REVIEW_KEYS,
    REVIEW_V2_KEYS,
    REVIEW_SCHEMA,
    REVIEW_SCHEMA_V2,
    SHA256_RE,
    artifact_fingerprint_for,
)
from warehouse_identity_review_session import WarehouseIdentityReviewSession

RECORD_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
FORBIDDEN_CLIENT_FIELDS = frozenset({
    "packet",
    "artifact",
    "Name",
    "name",
    "Quality",
    "quality",
    "Value",
    "price",
    "sha256",
    "relativePath",
    "bbox",
    "evidenceId",
    "File",
    "LiveFiles",
    "imageBytes",
    "hash",
    "imageDataUrl",
    "path",
})
FORBIDDEN_ARTIFACT_KEYS = frozenset({
    "relativePath",
    "File",
    "LiveFiles",
    "imageBytes",
    "imageDataUrl",
    "path",
    "absolutePath",
})
IDEMPOTENCY_FIELDS = ("packetFingerprint", "artifactFingerprint")
PERSIST_STATUS_KEYS = (
    "persistenceAvailable",
    "persisted",
    "persistStatus",
    "persistenceCaption",
    "persistMessage",
)
SUMMARY_KEYS = frozenset({
    "saved",
    "readable",
    "warehouseCoverage",
    "reviewCompletion",
    "identityResolution",
    "resolvedCount",
    "excludedCount",
    "unresolvedCount",
    "caption",
})
PERSIST_ERROR_COPY = {
    "ARTIFACT_CONFLICT": "本局已有不同审阅结果，未覆盖",
    "SESSION_MISMATCH": "审阅会话已失效，未写入",
    "PACKET_FINGERPRINT_MISMATCH": "审阅会话已失效，未写入",
    "NO_ARTIFACT": "尚未生成审阅结果，未写入",
    "RECORD_NOT_FOUND": "本局记录不存在，未写入",
    "LEGACY_SOURCE_FORBIDDEN": "旧版记录不能写入仓库审阅结果",
    "HISTORY_WRITE_FAILED": "写入失败，记录未改动",
    "FORBIDDEN_CLIENT_FIELD": "请求包含非法字段，未写入",
    "RECORD_KEY_MISMATCH": "记录键不一致，未写入",
    "CANCELLED_RECORD": "已取消的对局不能写入",
    "INVALID_ARTIFACT": "审阅结果不合法，未写入",
    "EVIDENCE_REF_MISMATCH": "证据引用不一致，未写入",
    "HISTORY_UNAVAILABLE": "历史记录不可用，未写入",
}


class WarehouseIdentityReviewPersistError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _replaceable_auto_review(existing, binding):
    if not isinstance(existing, Mapping) or existing.get("reviewerType") != "AUTO":
        return False
    try:
        _validate_artifact(existing)
    except WarehouseIdentityReviewPersistError:
        return False
    return (existing.get("schemaVersion") == REVIEW_SCHEMA_V2
            and existing.get("recordStableKey") == binding.get("recordStableKey")
            and existing.get("packetFingerprint") == binding.get("packetFingerprint")
            and all(isinstance(d, Mapping) and d.get("reviewerType") == "AUTO" and d.get("confirmedByHuman") is False
                    for d in existing.get("decisions", []))
            and all(isinstance(i, Mapping) and i.get("provenanceType") == "AUTO_CONFIRMED_EVIDENCE"
                    and i.get("confirmedByHuman") is False for i in existing.get("resolvedItems", [])))


def _replaceable_review(existing, binding):
    if _replaceable_auto_review(existing, binding):
        return True
    return (isinstance(existing, Mapping)
            and existing.get("schemaVersion") == REVIEW_SCHEMA_V2
            and existing.get("recordStableKey") == binding.get("recordStableKey")
            and existing.get("packetFingerprint") == binding.get("packetFingerprint")
            and bool(binding.get("baseArtifactFingerprint"))
            and existing.get("artifactFingerprint") == binding.get("baseArtifactFingerprint"))


def persist_warehouse_identity_review(
    *,
    session: WarehouseIdentityReviewSession,
    history_store: CanonicalHistoryStore,
    session_id: str,
    packet_fingerprint: str,
    record_stable_key: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    if extra:
        raise WarehouseIdentityReviewPersistError("FORBIDDEN_CLIENT_FIELD")

    binding = session.persist_binding()
    artifact = session.artifact_copy()
    if binding is None or artifact is None:
        raise WarehouseIdentityReviewPersistError("NO_ARTIFACT")
    if str(session_id or "").strip() != binding["sessionId"]:
        raise WarehouseIdentityReviewPersistError("SESSION_MISMATCH")
    submitted_fp = str(packet_fingerprint or "").strip()
    if submitted_fp != binding["packetFingerprint"] or submitted_fp != str(artifact.get("packetFingerprint") or ""):
        raise WarehouseIdentityReviewPersistError("PACKET_FINGERPRINT_MISMATCH")
    _validate_artifact(artifact)
    key = str(artifact.get("recordStableKey") or "")
    if record_stable_key is not None and str(record_stable_key).strip() != key:
        raise WarehouseIdentityReviewPersistError("RECORD_KEY_MISMATCH")

    try:
        record = history_store.lookup(key)
    except HistoryStoreError as exc:
        raise WarehouseIdentityReviewPersistError("HISTORY_UNAVAILABLE", str(exc)) from exc
    if record is None:
        raise WarehouseIdentityReviewPersistError("RECORD_NOT_FOUND")
    _assert_current_source(record, key)

    settlement = record.get("settlement") if isinstance(record.get("settlement"), Mapping) else {}
    existing = settlement.get("warehouseIdentityReview") if isinstance(settlement, Mapping) else None
    if isinstance(existing, Mapping):
        if (
            str(existing.get("packetFingerprint") or "") == str(artifact.get("packetFingerprint") or "")
            and str(existing.get("artifactFingerprint") or "") == str(artifact.get("artifactFingerprint") or "")
        ):
            return {
                "ok": True,
                "recordId": key,
                "packetFingerprint": str(artifact.get("packetFingerprint") or ""),
                "artifactFingerprint": str(artifact.get("artifactFingerprint") or ""),
                "idempotent": True,
                "written": False,
            }
        if not _replaceable_review(existing, binding):
            raise WarehouseIdentityReviewPersistError("ARTIFACT_CONFLICT")

    preview = copy.deepcopy(dict(record))
    preview_settlement = dict(preview.get("settlement") or {})
    lifecycle = str(preview.get("lifecycleStatus") or "")
    verified = preview_settlement.get("verified")
    status = preview_settlement.get("status")
    preview_settlement["warehouseIdentityReview"] = artifact
    if isinstance(existing, Mapping):
        revisions = copy.deepcopy(preview_settlement.get("warehouseIdentityReviewHistory") or [])
        revisions.append(copy.deepcopy(dict(existing)))
        preview_settlement["warehouseIdentityReviewHistory"] = revisions
    if artifact.get("schemaVersion") == REVIEW_SCHEMA_V2 and preview_settlement.get("reviewUnits"):
        resolved = {i["reviewUnitId"]: i for i in artifact["resolvedItems"]}
        decisions = {i["reviewUnitId"]: i for i in artifact["decisions"]}
        for unit in preview_settlement["reviewUnits"]:
            uid = unit.get("reviewUnitId")
            item = resolved.get(uid)
            if item:
                human = item.get("provenanceType") == "HUMAN_REVIEWED_CATALOG_ID"
                unit.update(selectedCatalogId=item["catalogId"], canonicalName=item["name"],
                            confirmationStatus="CONFIRMED", identityStatus="EXACT_IDENTIFIED",
                            confirmedByHuman=human, unconfirmedReasons=[])
                if human:
                    unit["confirmationReasons"] = ["HUMAN_REVIEWED_CATALOG_ID"]
            else:
                unit.update(selectedCatalogId=None, canonicalName=None,
                            confirmationStatus="CANDIDATE_ONLY", identityStatus="REVIEW_REQUIRED",
                            confirmedByHuman=uid in decisions, confirmationReasons=[],
                            unconfirmedReasons=["HUMAN_REVIEW_UNRESOLVED" if uid in decisions else "REVIEW_NOT_CONFIRMED"])
    preview["settlement"] = preview_settlement
    ok, reasons = validate_canonical_match_record_v7(preview, match_id=key)
    if not ok:
        raise WarehouseIdentityReviewPersistError("INVALID_RECORD", ",".join(reasons))
    if str(preview.get("lifecycleStatus") or "").upper() == "FINALIZED":
        ok, reasons = validate_finalized_match_record_v7(preview, match_id=key)
        if not ok:
            raise WarehouseIdentityReviewPersistError("INVALID_RECORD", ",".join(reasons))
    if str(preview.get("lifecycleStatus") or "") != lifecycle:
        raise WarehouseIdentityReviewPersistError("LIFECYCLE_MUTATION_FORBIDDEN")
    if preview["settlement"].get("verified") != verified or preview["settlement"].get("status") != status:
        raise WarehouseIdentityReviewPersistError("SETTLEMENT_MUTATION_FORBIDDEN")

    try:
        written = history_store.update_record_transactional(
            key,
            {"settlement": {k: preview_settlement[k] for k in ("warehouseIdentityReview", "reviewUnits", "warehouseIdentityReviewHistory")
                            if k in preview_settlement}},
            expected_warehouse_review_fingerprint=str((existing or {}).get("artifactFingerprint") or ""),
        )
    except HistoryStoreError as exc:
        if str(exc) == "WAREHOUSE_REVIEW_CHANGED":
            raise WarehouseIdentityReviewPersistError("ARTIFACT_CONFLICT", str(exc)) from exc
        raise WarehouseIdentityReviewPersistError("HISTORY_WRITE_FAILED", str(exc)) from exc

    stored = ((written.get("settlement") or {}) if isinstance(written.get("settlement"), Mapping) else {}).get(
        "warehouseIdentityReview"
    )
    if not isinstance(stored, Mapping) or str(stored.get("artifactFingerprint") or "") != str(artifact.get("artifactFingerprint") or ""):
        raise WarehouseIdentityReviewPersistError("HISTORY_WRITE_FAILED")
    if str(written.get("lifecycleStatus") or "") != lifecycle:
        raise WarehouseIdentityReviewPersistError("LIFECYCLE_MUTATION_FORBIDDEN")
    written_settlement = written.get("settlement") if isinstance(written.get("settlement"), Mapping) else {}
    if written_settlement.get("verified") != verified or written_settlement.get("status") != status:
        raise WarehouseIdentityReviewPersistError("SETTLEMENT_MUTATION_FORBIDDEN")
    session.mark_persisted(str(artifact.get("artifactFingerprint") or ""))
    return {
        "ok": True,
        "recordId": key,
        "packetFingerprint": str(artifact.get("packetFingerprint") or ""),
        "artifactFingerprint": str(artifact.get("artifactFingerprint") or ""),
        "idempotent": False,
        "written": True,
    }


def _assert_current_source(record: Mapping[str, Any], key: str) -> None:
    record_id = str(record.get("id") or "").strip()
    source = str(record.get("source") or "").strip()
    if record_id.startswith("legacy:") or source.lower().startswith("legacy"):
        raise WarehouseIdentityReviewPersistError("LEGACY_SOURCE_FORBIDDEN")
    if record.get("schemaVersion") != 7:
        raise WarehouseIdentityReviewPersistError("LEGACY_SOURCE_FORBIDDEN")
    if record_id != key:
        raise WarehouseIdentityReviewPersistError("RECORD_KEY_MISMATCH")
    lifecycle = str(record.get("lifecycleStatus") or "").strip().upper()
    if lifecycle in {"CANCELLED", "CANCELED"}:
        raise WarehouseIdentityReviewPersistError("CANCELLED_RECORD")


def _validate_artifact(artifact: Mapping[str, Any]) -> None:
    version = artifact.get("schemaVersion")
    if version not in (REVIEW_SCHEMA, REVIEW_SCHEMA_V2):
        raise WarehouseIdentityReviewPersistError("INVALID_ARTIFACT")
    allowed_keys = REVIEW_V2_KEYS if version == REVIEW_SCHEMA_V2 else REVIEW_KEYS
    if set(artifact) - allowed_keys:
        raise WarehouseIdentityReviewPersistError("INVALID_ARTIFACT")
    missing = [key for key in allowed_keys if key not in artifact]
    if missing:
        raise WarehouseIdentityReviewPersistError("INVALID_ARTIFACT")
    if not RECORD_KEY_RE.fullmatch(str(artifact.get("recordStableKey") or "")):
        raise WarehouseIdentityReviewPersistError("INVALID_ARTIFACT")
    if not SHA256_RE.fullmatch(str(artifact.get("packetFingerprint") or "")):
        raise WarehouseIdentityReviewPersistError("INVALID_ARTIFACT")
    if artifact_fingerprint_for(artifact) != str(artifact.get("artifactFingerprint") or ""):
        raise WarehouseIdentityReviewPersistError("INVALID_ARTIFACT")
    if _contains_forbidden_payload(artifact):
        raise WarehouseIdentityReviewPersistError("INVALID_ARTIFACT")
    key = str(artifact.get("recordStableKey") or "")
    fingerprint = str(artifact.get("packetFingerprint") or "")
    for item in artifact.get("resolvedItems") or []:
        if not isinstance(item, Mapping):
            raise WarehouseIdentityReviewPersistError("EVIDENCE_REF_MISMATCH")
        if str(item.get("recordStableKey") or "") != key:
            raise WarehouseIdentityReviewPersistError("EVIDENCE_REF_MISMATCH")
        if str(item.get("packetFingerprint") or "") != fingerprint:
            raise WarehouseIdentityReviewPersistError("EVIDENCE_REF_MISMATCH")
        if not SHA256_RE.fullmatch(str(item.get("sha256") or "")):
            raise WarehouseIdentityReviewPersistError("EVIDENCE_REF_MISMATCH")
        if not str(item.get("evidenceId") or "").strip():
            raise WarehouseIdentityReviewPersistError("EVIDENCE_REF_MISMATCH")
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise WarehouseIdentityReviewPersistError("EVIDENCE_REF_MISMATCH")
        cat_id = str(item.get("catalogId") or "").strip()
        name = str(item.get("name") or "").strip()
        if not cat_id or not name or name == cat_id:
            raise WarehouseIdentityReviewPersistError("CANONICAL_NAME_INVALID")

    for decision in artifact.get("decisions") or []:
        if isinstance(decision, Mapping):
            d_name = str(decision.get("canonicalName") or decision.get("name") or "").strip()
            d_cat = str(decision.get("selectedCatalogId") or decision.get("catalogId") or "").strip()
            if d_name and d_cat and d_name == d_cat:
                raise WarehouseIdentityReviewPersistError("CANONICAL_NAME_INVALID")


validate_review_artifact = _validate_artifact


def review_persistence_status(
    session: Optional[WarehouseIdentityReviewSession],
    history_store: Optional[CanonicalHistoryStore],
) -> Dict[str, Any]:
    unavailable = {
        "persistenceAvailable": False,
        "persisted": False,
        "persistStatus": "UNAVAILABLE",
        "persistenceCaption": "尚未写入历史记录",
        "persistMessage": None,
    }
    if session is None or history_store is None:
        return unavailable
    binding = session.persist_binding()
    if binding is None:
        return {
            "persistenceAvailable": False,
            "persisted": False,
            "persistStatus": "NOT_READY",
            "persistenceCaption": "尚未写入历史记录",
            "persistMessage": None,
        }
    try:
        record = history_store.lookup(binding["recordStableKey"])
    except HistoryStoreError:
        return dict(unavailable)
    if record is None:
        return {
            "persistenceAvailable": False,
            "persisted": False,
            "persistStatus": "RECORD_MISSING",
            "persistenceCaption": "尚未写入历史记录",
            "persistMessage": "本局记录不存在，无法写入",
        }
    try:
        _assert_current_source(record, binding["recordStableKey"])
    except WarehouseIdentityReviewPersistError as exc:
        return {
            "persistenceAvailable": False,
            "persisted": False,
            "persistStatus": exc.code,
            "persistenceCaption": "尚未写入历史记录",
            "persistMessage": PERSIST_ERROR_COPY.get(exc.code, "无法写入本局记录"),
        }
    settlement = record.get("settlement") if isinstance(record.get("settlement"), Mapping) else {}
    existing = settlement.get("warehouseIdentityReview") if isinstance(settlement, Mapping) else None
    if isinstance(existing, Mapping):
        same = (
            str(existing.get("packetFingerprint") or "") == binding["packetFingerprint"]
            and str(existing.get("artifactFingerprint") or "") == binding["artifactFingerprint"]
        )
        if same:
            return {
                "persistenceAvailable": False,
                "persisted": True,
                "persistStatus": "SAVED",
                "persistenceCaption": "已写入本局记录",
                "persistMessage": "已写入本局记录",
            }
        if not _replaceable_review(existing, binding):
            return {
                "persistenceAvailable": False,
                "persisted": False,
                "persistStatus": "CONFLICT",
                "persistenceCaption": PERSIST_ERROR_COPY["ARTIFACT_CONFLICT"],
                "persistMessage": PERSIST_ERROR_COPY["ARTIFACT_CONFLICT"],
            }
    return {
        "persistenceAvailable": True,
        "persisted": False,
        "persistStatus": "READY",
        "persistenceCaption": "尚未写入历史记录",
        "persistMessage": None,
    }


def persist_error_copy(code: str) -> str:
    return PERSIST_ERROR_COPY.get(str(code or ""), "未写入本局记录")


def summarize_persisted_identity_review(record: Any) -> Dict[str, Any]:
    empty = {
        "saved": False,
        "readable": False,
        "warehouseCoverage": None,
        "reviewCompletion": None,
        "identityResolution": None,
        "resolvedCount": None,
        "excludedCount": None,
        "unresolvedCount": None,
        "caption": "尚未写入仓库身份审阅",
    }
    if not isinstance(record, Mapping):
        return dict(empty)
    record_id = str(record.get("id") or "").strip()
    source = str(record.get("source") or "").strip()
    if record_id.startswith("legacy:") or source.lower().startswith("legacy"):
        empty["caption"] = "旧版记录没有仓库身份审阅"
        return empty
    if record.get("schemaVersion") != 7:
        empty["caption"] = "旧版记录没有仓库身份审阅"
        return empty
    settlement = record.get("settlement")
    if not isinstance(settlement, Mapping) or "warehouseIdentityReview" not in settlement:
        return empty
    artifact = settlement.get("warehouseIdentityReview")
    if not isinstance(artifact, Mapping):
        empty["caption"] = "仓库审阅结果不可读取"
        return empty
    try:
        _validate_artifact(artifact)
        if str(artifact.get("recordStableKey") or "") != record_id:
            raise WarehouseIdentityReviewPersistError("RECORD_KEY_MISMATCH")
    except WarehouseIdentityReviewPersistError:
        empty["caption"] = "仓库审阅结果不可读取"
        return empty
    stats = artifact.get("summary") if isinstance(artifact.get("summary"), Mapping) else {}
    payload = {
        "saved": True,
        "readable": True,
        "warehouseCoverage": artifact.get("warehouseCoverageStatus"),
        "reviewCompletion": artifact.get("reviewCompletion"),
        "identityResolution": artifact.get("identityResolution"),
        "resolvedCount": int(stats.get("resolvedItemCount") or 0),
        "excludedCount": int(stats.get("excludedUnitCount") if "excludedUnitCount" in stats else (stats.get("excludedTrackCount") or 0)),
        "unresolvedCount": int(stats.get("unresolvedUnitCount") if "unresolvedUnitCount" in stats else (stats.get("unresolvedTrackCount") or 0)),
        "caption": "已写入本局记录",
    }
    extra = set(payload) - SUMMARY_KEYS
    for key in extra:
        payload.pop(key, None)
    return payload


def _contains_forbidden_payload(value: Any) -> bool:
    if isinstance(value, Mapping):
        if set(value) & FORBIDDEN_ARTIFACT_KEYS:
            return True
        return any(_contains_forbidden_payload(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_payload(item) for item in value)
    if isinstance(value, str):
        text = value.replace("\\", "/").casefold()
        if text.startswith("data:image"):
            return True
        if len(value) >= 3 and value[1:3] in {":\\", ":/"}:
            return True
    return False
