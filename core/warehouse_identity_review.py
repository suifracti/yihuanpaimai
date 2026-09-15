"""Explicit human warehouse identity review contract.

Pure resolver: immutable review packet + explicit human decisions.
Does not write History, mutate packets, or auto-confirm candidates.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

from settlement_truth_evidence_contract import RECORD_KEY_RE
from warehouse_catalog_geometry import _geometry_faults, _load_catalog, application_asset_root
from warehouse_review_packet import (
    SCHEMA_VERSION as PACKET_SCHEMA,
    source_fingerprint_for,
    validate_warehouse_review_packet,
)

DECISION_SCHEMA = "warehouse-identity-review-decision.v1"
DECISION_SCHEMA_V2 = "warehouse-identity-review-decision.v2"
REVIEW_SCHEMA = "warehouse-identity-review.v1"
REVIEW_SCHEMA_V2 = "warehouse-identity-review.v2"
SHA256_RE = __import__("re").compile(r"^[0-9a-f]{64}$")

ACTION_CONFIRM = "CONFIRM_CANDIDATE"
ACTION_OVERRIDE = "CONFIRM_CATALOG_OVERRIDE"
ACTION_OUT_OF_CATALOG = "MARK_OUT_OF_CATALOG"
ACTION_DEFER = "DEFER"
ACTION_EXCLUDE = "EXCLUDE_FALSE_COMPONENT"
ACTION_EXCLUDE_V2 = "EXCLUDE_FALSE_PLACEMENT"
ACTION_FLAG = "FLAG_GEOMETRY_ERROR"
CONFIRM_ACTIONS = frozenset({ACTION_CONFIRM, ACTION_OVERRIDE})
NO_ID_ACTIONS = frozenset({ACTION_OUT_OF_CATALOG, ACTION_DEFER, ACTION_EXCLUDE, ACTION_EXCLUDE_V2, ACTION_FLAG})
OVERRIDE_REASONS = frozenset({
    "CLIPPED_GEOMETRY",
    "SEGMENTATION_ERROR",
    "CATALOG_GEOMETRY_MISMATCH",
    "HUMAN_VISUAL_IDENTIFICATION",
})
FORBIDDEN_CLIENT_FIELDS = frozenset({
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
})

DECISION_DOC_KEYS = frozenset({
    "schemaVersion",
    "recordStableKey",
    "packetFingerprint",
    "reviewedAt",
    "reviewerType",
    "decisions",
})
DECISION_ITEM_KEYS = frozenset({
    "decisionId",
    "trackId",
    "action",
    "selectedCatalogId",
    "confirmedByHuman",
    "overrideReason",
    "reason",
    "geometryErrorType",
})
DECISION_ITEM_V2_KEYS = frozenset({
    "decisionId",
    "reviewUnitId",
    "action",
    "selectedCatalogId",
    "confirmedByHuman",
    "overrideReason",
    "reason",
    "geometryErrorType",
})
REVIEW_KEYS = frozenset({
    "schemaVersion",
    "recordStableKey",
    "packetFingerprint",
    "reviewedAt",
    "reviewerType",
    "warehouseCoverageStatus",
    "reviewCompletion",
    "identityResolution",
    "resolvedItems",
    "unresolvedTracks",
    "excludedTracks",
    "decisions",
    "summary",
    "artifactFingerprint",
})
REVIEW_V2_KEYS = frozenset({
    "schemaVersion",
    "recordStableKey",
    "packetFingerprint",
    "reviewedAt",
    "reviewerType",
    "warehouseCoverageStatus",
    "reviewCompletion",
    "identityResolution",
    "resolvedItems",
    "unresolvedUnits",
    "excludedUnits",
    "decisions",
    "summary",
    "artifactFingerprint",
})


class WarehouseIdentityReviewError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _make_rect_shape(width: int, height: int) -> str:
    rows = []
    for r in range(5):
        if r < height:
            rows.append("1" * width + "0" * (5 - width))
        else:
            rows.append("0" * 5)
    return "".join(rows)


def _load_default_catalog_records(
    registry_path: Optional[Path] = None,
    root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    from catalog_validator import validate_verified_registry_card

    records = list(_load_catalog(None))
    known_ids = {str(item.get("Id") or "").strip() for item in records}

    base_root = root or application_asset_root()
    reg_path = registry_path or (base_root / "assets" / "items" / "verified_source_card_registry.json")
    if reg_path.is_file():
        try:
            rdata = json.loads(reg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("CatalogAuthority: failed to parse registry file %s: %s", reg_path, exc)
            raise

        cards = rdata.get("cards", []) if isinstance(rdata, dict) else []
        for card in cards:
            is_valid, reason = validate_verified_registry_card(card, root=base_root)
            if not is_valid:
                logger.warning(
                    "CatalogAuthority: rejecting invalid registry card %s: %s",
                    card.get("catalogId") if isinstance(card, dict) else "<unknown>",
                    reason,
                )
                continue

            cid = str(card.get("catalogId") or "").strip()
            name = str(card.get("name") or "").strip()
            if cid in known_ids:
                continue
            w = int(card.get("widthCells") or 1)
            h = int(card.get("heightCells") or 1)
            records.append({
                "Id": cid,
                "Name": name,
                "Quality": card.get("quality"),
                "Width": w,
                "Height": h,
                "Cells": w * h,
                "Shape": _make_rect_shape(w, h),
            })
            known_ids.add(cid)
    return records


class CatalogAuthority:
    """Id-keyed catalog metadata. Quality is never used for matching."""

    def __init__(
        self,
        records: Optional[Sequence[Mapping[str, Any]]] = None,
        registry_path: Optional[Path] = None,
        root: Optional[Path] = None,
    ):
        raw = list(records) if records is not None else _load_default_catalog_records(registry_path=registry_path, root=root)
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._by_name: Dict[str, Set[str]] = {}
        for item in raw:
            catalog_id = str(item.get("Id") or item.get("catalogId") or "").strip()
            if not catalog_id:
                continue
            name = str(item.get("Name") or item.get("name") or "").strip()
            faults = _geometry_faults(item)
            self._by_id[catalog_id] = {
                "catalogId": catalog_id,
                "name": name,
                "quality": item.get("Quality") or item.get("quality"),
                "width": item.get("Width") or item.get("widthCells") or item.get("width"),
                "height": item.get("Height") or item.get("heightCells") or item.get("height"),
                "cells": item.get("Cells") or item.get("cells"),
                "shape": item.get("Shape") or item.get("shape"),
                "catalogGeometryStatus": "QUARANTINED" if faults else "INDEXED",
            }
            if name:
                self._by_name.setdefault(name, set()).add(catalog_id)

    def get(self, catalog_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(str(catalog_id or "").strip())

    def get_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        cids = self._by_name.get(str(name or "").strip())
        if cids:
            return self._by_id.get(next(iter(cids)))
        return None

    def get_canonical_name(self, catalog_id: str) -> Optional[str]:
        rec = self.get(catalog_id)
        return rec.get("name") if rec else None

    def is_valid_catalog_id(self, catalog_id: str) -> bool:
        return str(catalog_id or "").strip() in self._by_id

    def is_valid_name(self, name: str) -> bool:
        return str(name or "").strip() in self._by_name


def canonical_identity_review(document: Mapping[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)


def artifact_fingerprint_for(document: Mapping[str, Any]) -> str:
    body = {key: document[key] for key in sorted(document) if key != "artifactFingerprint"}
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_identity_review_decision(document: Any) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if not isinstance(document, Mapping):
        return False, ["DECISION_NOT_OBJECT"]
    
    version = document.get("schemaVersion")
    if version not in (DECISION_SCHEMA, DECISION_SCHEMA_V2):
        reasons.append("SCHEMA_VERSION_INVALID")
        
    allowed_keys = DECISION_DOC_KEYS
    extra = [key for key in document.keys() if key not in allowed_keys]
    if extra:
        reasons.extend(f"UNKNOWN_FIELD_{key}" for key in extra)
        if extra and set(extra) & FORBIDDEN_CLIENT_FIELDS:
            reasons.append("FORBIDDEN_CLIENT_FIELD")
            
    if not RECORD_KEY_RE.fullmatch(str(document.get("recordStableKey") or "")):
        reasons.append("RECORD_STABLE_KEY_INVALID")
    if not SHA256_RE.fullmatch(str(document.get("packetFingerprint") or "")):
        reasons.append("PACKET_FINGERPRINT_INVALID")
    if not str(document.get("reviewedAt") or "").strip():
        reasons.append("REVIEWED_AT_MISSING")
    if document.get("reviewerType") != "HUMAN":
        reasons.append("REVIEWER_TYPE_INVALID")
    decisions = document.get("decisions")
    if not isinstance(decisions, list):
        reasons.append("DECISIONS_NOT_ARRAY")
        return len(reasons) == 0, reasons
    seen_ids: set[str] = set()
    seen_units: set[str] = set()
    for item in decisions:
        if not isinstance(item, Mapping):
            reasons.append("DECISION_ITEM_NOT_OBJECT")
            continue
        forbidden = set(item.keys()) & FORBIDDEN_CLIENT_FIELDS
        item_keys = DECISION_ITEM_V2_KEYS if version == DECISION_SCHEMA_V2 else DECISION_ITEM_KEYS
        extra_item = set(item.keys()) - item_keys
        if extra_item:
            reasons.append("UNKNOWN_DECISION_FIELD")
        if forbidden:
            reasons.append("FORBIDDEN_CLIENT_FIELD")
        decision_id = str(item.get("decisionId") or "").strip()
        unit_key = "reviewUnitId" if version == DECISION_SCHEMA_V2 else "trackId"
        unit_id = str(item.get(unit_key) or "").strip()
        action = str(item.get("action") or "")
        if not decision_id:
            reasons.append("DECISION_ID_MISSING")
        elif decision_id in seen_ids:
            reasons.append("DUPLICATE_DECISION_ID")
        seen_ids.add(decision_id)
        if not unit_id:
            reasons.append(f"{unit_key.upper()}_MISSING")
        elif unit_id in seen_units:
            reasons.append(f"DUPLICATE_{unit_key.upper()}_DECISION")
        seen_units.add(unit_id)
        if action not in {
            ACTION_CONFIRM,
            ACTION_OVERRIDE,
            ACTION_OUT_OF_CATALOG,
            ACTION_DEFER,
            ACTION_EXCLUDE,
            ACTION_EXCLUDE_V2,
            ACTION_FLAG,
        }:
            reasons.append("UNKNOWN_ACTION")
        catalog_id = item.get("selectedCatalogId")
        if action in CONFIRM_ACTIONS:
            if not str(catalog_id or "").strip():
                reasons.append("CATALOG_ID_REQUIRED")
        elif catalog_id not in (None, ""):
            reasons.append("UNEXPECTED_CATALOG_ID")
        if action == ACTION_OVERRIDE:
            if item.get("confirmedByHuman") is not True:
                reasons.append("HUMAN_CONFIRMATION_REQUIRED")
            if item.get("overrideReason") not in OVERRIDE_REASONS:
                reasons.append("OVERRIDE_REASON_REQUIRED")
        if action in {ACTION_OUT_OF_CATALOG, ACTION_EXCLUDE, ACTION_EXCLUDE_V2, ACTION_FLAG}:
            if not str(item.get("reason") or item.get("geometryErrorType") or "").strip():
                reasons.append("REASON_REQUIRED")
    return len(reasons) == 0, reasons


def validate_warehouse_identity_review(document: Any) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if not isinstance(document, Mapping):
        return False, ["ARTIFACT_NOT_OBJECT"]
    version = document.get("schemaVersion")
    if version not in (REVIEW_SCHEMA, REVIEW_SCHEMA_V2):
        reasons.append("SCHEMA_VERSION_INVALID")
    allowed_keys = REVIEW_V2_KEYS if version == REVIEW_SCHEMA_V2 else REVIEW_KEYS
    extra = set(document.keys()) - allowed_keys
    if extra:
        reasons.extend(f"UNKNOWN_FIELD_{k}" for k in extra)
    missing = [k for k in allowed_keys if k not in document]
    if missing:
        reasons.extend(f"MISSING_{k}" for k in missing)
    if not RECORD_KEY_RE.fullmatch(str(document.get("recordStableKey") or "")):
        reasons.append("RECORD_STABLE_KEY_INVALID")
    if not SHA256_RE.fullmatch(str(document.get("packetFingerprint") or "")):
        reasons.append("PACKET_FINGERPRINT_INVALID")
    if artifact_fingerprint_for(document) != str(document.get("artifactFingerprint") or ""):
        reasons.append("ARTIFACT_FINGERPRINT_MISMATCH")
    return len(reasons) == 0, reasons


def resolve_warehouse_identity_review(
    packet: Mapping[str, Any],
    decision_document: Mapping[str, Any],
    *,
    catalog: Optional[CatalogAuthority] = None,
) -> Dict[str, Any]:
    ok, reasons = validate_warehouse_review_packet(packet)
    if not ok:
        raise WarehouseIdentityReviewError("INVALID_PACKET", ",".join(reasons))
    ok, reasons = validate_identity_review_decision(decision_document)
    if not ok:
        raise WarehouseIdentityReviewError("INVALID_DECISION", ",".join(reasons))
    expected_fp = source_fingerprint_for(packet)
    submitted_fp = str(decision_document.get("packetFingerprint") or "")
    if submitted_fp != packet.get("sourceFingerprint") or submitted_fp != expected_fp:
        raise WarehouseIdentityReviewError("PACKET_FINGERPRINT_MISMATCH")
    key = str(packet.get("recordStableKey") or "")
    if str(decision_document.get("recordStableKey") or "") != key:
        raise WarehouseIdentityReviewError("RECORD_KEY_MISMATCH")

    is_v2 = packet.get("schemaVersion") == "warehouse-review-packet.v2"
    id_key = "reviewUnitId" if is_v2 else "trackId"
    items_list_key = "reviewUnits" if is_v2 else "tracks"

    units = [item for item in (packet.get(items_list_key) or []) if isinstance(item, Mapping)]
    unit_by_id = {str(item.get(id_key)): item for item in units}
    if len(unit_by_id) != len(units):
        raise WarehouseIdentityReviewError("DUPLICATE_REVIEW_UNIT_ID" if is_v2 else "DUPLICATE_TRACK_ID")
    segments = {
        str(item.get("evidenceId")): item
        for item in (packet.get("segments") or [])
        if isinstance(item, Mapping)
    }
    authority = catalog or CatalogAuthority()
    decisions = [item for item in decision_document.get("decisions") or [] if isinstance(item, Mapping)]

    resolved: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    echoed: List[Dict[str, Any]] = []

    for decision in decisions:
        unit_id = str(decision.get(id_key) or "")
        if unit_id not in unit_by_id:
            raise WarehouseIdentityReviewError("UNKNOWN_REVIEW_UNIT" if is_v2 else "UNKNOWN_TRACK")
        unit = unit_by_id[unit_id]
        action = str(decision.get("action") or "")
        echo_entry = {
            "decisionId": str(decision.get("decisionId") or ""),
            id_key: unit_id,
            "action": action,
            "selectedCatalogId": decision.get("selectedCatalogId") if decision.get("selectedCatalogId") else None,
            "overrideReason": decision.get("overrideReason") if decision.get("overrideReason") else None,
            "reason": str(decision.get("reason") or decision.get("geometryErrorType") or "") or None,
        }
        echoed.append(echo_entry)
        if action == ACTION_CONFIRM:
            resolved.append(_resolve_confirm(packet, unit, decision, authority, segments, override=False, is_v2=is_v2))
        elif action == ACTION_OVERRIDE:
            resolved.append(_resolve_confirm(packet, unit, decision, authority, segments, override=True, is_v2=is_v2))
        elif action in (ACTION_EXCLUDE, ACTION_EXCLUDE_V2):
            ex_entry = {
                id_key: unit_id,
                "action": ACTION_EXCLUDE_V2 if is_v2 else ACTION_EXCLUDE,
                "reason": str(decision.get("reason") or ""),
            }
            if is_v2:
                ex_entry["supportingTrackIds"] = list(unit.get("supportingTrackIds") or [])
            excluded.append(ex_entry)
        else:
            un_entry = {
                id_key: unit_id,
                "action": action,
                "reason": str(decision.get("reason") or decision.get("geometryErrorType") or "") or None,
                "identityStatus": "UNRESOLVED",
            }
            if is_v2:
                un_entry["supportingTrackIds"] = list(unit.get("supportingTrackIds") or [])
            unresolved.append(un_entry)

    decided = {item[id_key] for item in echoed}
    if is_v2:
        # Unedited machine confirmations remain machine evidence. A human
        # need only handle unresolved items; never relabel untouched AUTO
        # decisions as human confirmations or override an explicit deferral.
        from warehouse_auto_confirmation import evaluate_auto_confirmation
        automatic = build_auto_identity_review_artifact(
            packet, evaluate_auto_confirmation(units, list(segments.values())),
            catalog=authority, reviewed_at=str(decision_document.get("reviewedAt") or ""))
        automatic_items = {item[id_key]: item for item in automatic["resolvedItems"]
                           if item[id_key] not in decided}
        resolved.extend(automatic_items.values())
        echoed.extend(item for item in automatic["decisions"] if item[id_key] in automatic_items)
        decided.update(automatic_items)
    for unit_id in unit_by_id:
        if unit_id not in decided:
            un_entry = {
                id_key: unit_id,
                "action": None,
                "reason": None,
                "identityStatus": "UNRESOLVED",
            }
            if is_v2:
                un_entry["supportingTrackIds"] = list(unit_by_id[unit_id].get("supportingTrackIds") or [])
            unresolved.append(un_entry)

    echoed.sort(key=lambda item: item[id_key])
    resolved.sort(key=lambda item: item[id_key])
    unresolved.sort(key=lambda item: item[id_key])
    excluded.sort(key=lambda item: item[id_key])

    coverage = str((packet.get("warehouseCoverage") or {}).get("status") or "COVERAGE_UNPROVEN")
    review_completion = _review_completion(unit_by_id, echoed, id_key=id_key)
    identity_resolution = _identity_resolution(
        coverage,
        review_completion,
        units,
        echoed,
        unresolved,
        excluded,
        id_key=id_key,
    )
    
    summary_dict = {
        "decisionCount": len(echoed),
        "resolvedItemCount": len(resolved),
    }
    if is_v2:
        summary_dict["reviewUnitCount"] = len(unit_by_id)
        summary_dict["unresolvedUnitCount"] = len(unresolved)
        summary_dict["excludedUnitCount"] = len(excluded)
    else:
        summary_dict["trackCount"] = len(unit_by_id)
        summary_dict["unresolvedTrackCount"] = len(unresolved)
        summary_dict["excludedTrackCount"] = len(excluded)

    artifact = {
        "schemaVersion": REVIEW_SCHEMA_V2 if is_v2 else REVIEW_SCHEMA,
        "recordStableKey": key,
        "packetFingerprint": submitted_fp,
        "reviewedAt": str(decision_document.get("reviewedAt") or ""),
        "reviewerType": "HUMAN",
        "warehouseCoverageStatus": coverage,
        "reviewCompletion": review_completion,
        "identityResolution": identity_resolution,
        "resolvedItems": resolved,
        ("unresolvedUnits" if is_v2 else "unresolvedTracks"): unresolved,
        ("excludedUnits" if is_v2 else "excludedTracks"): excluded,
        "decisions": echoed,
        "summary": summary_dict,
        "artifactFingerprint": "0" * 64,
    }
    artifact["artifactFingerprint"] = artifact_fingerprint_for(artifact)
    allowed_review_keys = REVIEW_V2_KEYS if is_v2 else REVIEW_KEYS
    extra = set(artifact) - allowed_review_keys
    for field in extra:
        artifact.pop(field, None)
    return artifact


def _review_completion(units: Mapping[str, Any], decisions: Sequence[Mapping[str, Any]], *, id_key: str = "trackId") -> str:
    if not decisions:
        return "NOT_STARTED"
    by_unit = {str(item.get(id_key)): item for item in decisions}
    if len(by_unit) < len(units):
        return "PARTIAL"
    if any(item.get("action") == ACTION_DEFER for item in decisions):
        return "PARTIAL"
    return "COMPLETE"


def _identity_resolution(
    coverage: str,
    review_completion: str,
    units: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    unresolved: Sequence[Mapping[str, Any]],
    excluded: Sequence[Mapping[str, Any]],
    *,
    id_key: str = "trackId",
) -> str:
    if not any(item.get("action") in CONFIRM_ACTIONS for item in decisions):
        if not decisions:
            return "NONE"
        if all(item.get("action") in {ACTION_DEFER, None} or item.get("action") is None for item in unresolved) and not any(
            item.get("action") in CONFIRM_ACTIONS for item in decisions
        ):
            if not any(item.get("action") in {ACTION_EXCLUDE, ACTION_EXCLUDE_V2, ACTION_OUT_OF_CATALOG, ACTION_FLAG} for item in decisions):
                return "NONE"
    blocking = {ACTION_OUT_OF_CATALOG, ACTION_DEFER, ACTION_FLAG}
    if any(item.get("action") in blocking for item in decisions):
        return "PARTIAL"
    if unresolved:
        return "PARTIAL"
    if review_completion != "COMPLETE":
        return "PARTIAL"
    if coverage != "COMPLETE":
        return "PARTIAL"
    excluded_ids = {item[id_key] for item in excluded}
    for unit in units:
        unit_id = str(unit.get(id_key))
        decision = next((item for item in decisions if item.get(id_key) == unit_id), None)
        if unit.get("status") == "CONFLICT" and (decision is None or decision.get("action") not in CONFIRM_ACTIONS | {ACTION_EXCLUDE, ACTION_EXCLUDE_V2}):
            return "PARTIAL"
        if unit_id in excluded_ids:
            continue
        if decision is None or decision.get("action") not in CONFIRM_ACTIONS:
            return "PARTIAL"
    return "FULLY_RESOLVED"


def _resolve_confirm(
    packet: Mapping[str, Any],
    unit: Mapping[str, Any],
    decision: Mapping[str, Any],
    authority: CatalogAuthority,
    segments: Mapping[str, Mapping[str, Any]],
    *,
    override: bool,
    is_v2: bool = False,
) -> Dict[str, Any]:
    catalog_id = str(decision.get("selectedCatalogId") or "").strip()
    candidate_ids = {
        str(item.get("catalogId"))
        for item in (unit.get("candidates") or [])
        if isinstance(item, Mapping)
    }
    if override:
        record = authority.get(catalog_id)
        if record is None:
            raise WarehouseIdentityReviewError("UNKNOWN_CATALOG_ID")
        if catalog_id in candidate_ids and record.get("catalogGeometryStatus") != "QUARANTINED":
            raise WarehouseIdentityReviewError("OVERRIDE_ID_IN_CANDIDATES")
    else:
        if catalog_id not in candidate_ids:
            raise WarehouseIdentityReviewError("CATALOG_ID_NOT_CANDIDATE")
        record = authority.get(catalog_id)
        if record is None:
            raise WarehouseIdentityReviewError("UNKNOWN_CATALOG_ID")
        if record["catalogGeometryStatus"] == "QUARANTINED":
            raise WarehouseIdentityReviewError("QUARANTINED_REQUIRES_OVERRIDE")
    observation = _best_observation(unit)
    evidence_id = str(observation.get("evidenceId") or "")
    segment = segments.get(evidence_id) or {}
    digest = str(segment.get("sha256") or "")
    if not SHA256_RE.fullmatch(digest):
        raise WarehouseIdentityReviewError("EVIDENCE_HASH_MISSING")
    
    if is_v2:
        entry = {
            "reviewUnitId": str(unit.get("reviewUnitId") or ""),
            "physicalGroupId": unit.get("physicalGroupId"),
            "supportingTrackIds": list(unit.get("supportingTrackIds") or []),
            "catalogId": catalog_id,
            "name": record["name"],
            "quality": None if record.get("quality") in (None, "") else str(record.get("quality")),
            "action": ACTION_OVERRIDE if override else ACTION_CONFIRM,
            "packetFingerprint": str(packet.get("sourceFingerprint") or ""),
            "recordStableKey": str(packet.get("recordStableKey") or ""),
            "evidenceId": evidence_id,
            "sha256": digest,
            "bbox": [float(value) for value in (observation.get("bbox") or [0, 0, 0, 0])],
            "worldAnchor": dict(unit.get("worldAnchor") or {"row": 0, "col": 0}),
            "footprint": dict(unit.get("footprint") or {"widthCells": 1, "heightCells": 1}),
            "sequenceIndex": int(observation.get("sequenceIndex") or 0),
            "provenanceType": "HUMAN_REVIEWED_CATALOG_ID",
            "catalogGeometryStatus": record["catalogGeometryStatus"],
            "overrideReason": decision.get("overrideReason") if override else None,
        }
    else:
        entry = {
            "trackId": str(unit.get("trackId") or ""),
            "catalogId": catalog_id,
            "name": record["name"],
            "quality": None if record.get("quality") in (None, "") else str(record.get("quality")),
            "action": ACTION_OVERRIDE if override else ACTION_CONFIRM,
            "packetFingerprint": str(packet.get("sourceFingerprint") or ""),
            "recordStableKey": str(packet.get("recordStableKey") or ""),
            "evidenceId": evidence_id,
            "sha256": digest,
            "bbox": [float(value) for value in (observation.get("bbox") or [0, 0, 0, 0])],
            "sequenceIndex": int(observation.get("sequenceIndex") or 0),
            "provenanceType": "HUMAN_REVIEWED_CATALOG_ID",
            "catalogGeometryStatus": record["catalogGeometryStatus"],
            "overrideReason": decision.get("overrideReason") if override else None,
        }
    return entry


def _best_observation(track: Mapping[str, Any]) -> Mapping[str, Any]:
    observations = [item for item in (track.get("observations") or []) if isinstance(item, Mapping)]
    if not observations:
        raise WarehouseIdentityReviewError("MISSING_OBSERVATION")
    wanted = str(track.get("bestObservationId") or "")
    for item in observations:
        if str(item.get("observationId") or "") == wanted:
            return item
    raise WarehouseIdentityReviewError("BEST_OBSERVATION_MISSING")


def build_auto_identity_review_artifact(
    packet: Mapping[str, Any],
    review_units: Sequence[Mapping[str, Any]],
    *,
    catalog: Optional[CatalogAuthority] = None,
    reviewed_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Builds a compliant warehouse-identity-review.v2 artifact for automated confirmations.

    Strict rules:
    - reviewerType is 'AUTO'.
    - confirmedByHuman is False for all entries.
    - provenanceType is 'AUTO_CONFIRMED_EVIDENCE'.
    - Names must be authoritative names from CatalogAuthority; never IDs.
    - Evidence references (sha256, evidenceId, bbox) must be genuine.
    """
    if packet.get("schemaVersion"):
        ok, reasons = validate_warehouse_review_packet(packet)
        if not ok:
            raise WarehouseIdentityReviewError("INVALID_PACKET", ",".join(reasons))
    elif not RECORD_KEY_RE.fullmatch(str(packet.get("recordStableKey") or "")):
        raise WarehouseIdentityReviewError("INVALID_PACKET", "RECORD_STABLE_KEY_INVALID")

    authority = catalog or CatalogAuthority()
    segments = {
        str(item.get("evidenceId")): item
        for item in (packet.get("segments") or [])
        if isinstance(item, Mapping)
    }
    key = str(packet.get("recordStableKey") or "")
    fingerprint = str(packet.get("sourceFingerprint") or "")
    if not SHA256_RE.fullmatch(fingerprint):
        raw_fp = json.dumps({k: packet[k] for k in sorted(packet) if k != "sourceFingerprint"}, sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(raw_fp.encode("utf-8")).hexdigest()
    reviewed_ts = (
        reviewed_at
        or packet.get("reviewedAt")
        or packet.get("capturedAt")
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    resolved: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    decisions: List[Dict[str, Any]] = []

    for unit in review_units:
        uid = str(unit.get("reviewUnitId") or "").strip()
        status = unit.get("confirmationStatus")
        cat_id = str(unit.get("selectedCatalogId") or "").strip()

        if status == "CONFIRMED" and cat_id:
            cat_rec = authority.get(cat_id)
            if cat_rec is None:
                raise WarehouseIdentityReviewError(f"UNKNOWN_CATALOG_ID: {cat_id}")
            auth_name = str(cat_rec.get("name") or "").strip()
            if not auth_name or auth_name == cat_id:
                raise WarehouseIdentityReviewError(f"INVALID_CATALOG_NAME: {auth_name}")

            obs = None
            if isinstance(unit.get("observations"), list) and unit["observations"]:
                obs = unit["observations"][0]
            elif isinstance(unit.get("bestObservation"), dict):
                obs = unit["bestObservation"]
            else:
                try:
                    obs = _best_observation(unit)
                except Exception:
                    obs = None

            ev_id = str((obs.get("evidenceId") if obs else None) or unit.get("evidenceId") or "").strip()
            segment = segments.get(ev_id) or {}
            digest = str((obs.get("sha256") if obs else None) or segment.get("sha256") or unit.get("cropSha256") or "").strip()
            if not SHA256_RE.fullmatch(digest):
                raise WarehouseIdentityReviewError("EVIDENCE_HASH_MISSING")
            raw_bbox = (obs.get("bbox") if obs else None) or unit.get("bbox") or [0, 0, 0, 0]
            bbox = [float(v) for v in raw_bbox]

            resolved.append({
                "reviewUnitId": uid,
                "physicalGroupId": unit.get("physicalGroupId"),
                "supportingTrackIds": list(unit.get("supportingTrackIds") or []),
                "catalogId": cat_id,
                "name": auth_name,
                "quality": None if cat_rec.get("quality") in (None, "") else str(cat_rec.get("quality")),
                "action": "CONFIRM_CANDIDATE",
                "packetFingerprint": fingerprint,
                "recordStableKey": key,
                "evidenceId": ev_id,
                "sha256": digest,
                "bbox": bbox,
                "worldAnchor": dict(unit.get("worldAnchor") or {"row": 0, "col": 0}),
                "footprint": dict(unit.get("footprint") or {"widthCells": 1, "heightCells": 1}),
                "sequenceIndex": int(obs.get("sequenceIndex") if obs else (unit.get("sequenceIndex") or 0)),
                "provenanceType": "AUTO_CONFIRMED_EVIDENCE",
                "confirmedByHuman": False,
                "catalogGeometryStatus": cat_rec.get("catalogGeometryStatus", "INDEXED"),
            })
            decisions.append({
                "decisionId": f"dec-auto-{uid}",
                "reviewUnitId": uid,
                "action": "CONFIRM_CANDIDATE",
                "selectedCatalogId": cat_id,
                "canonicalName": auth_name,
                "confirmedByHuman": False,
                "reviewerType": "AUTO",
            })
        else:
            unresolved.append({
                "reviewUnitId": uid,
                "action": "DEFER",
                "identityStatus": "UNRESOLVED",
                "confirmedByHuman": False,
                "supportingTrackIds": list(unit.get("supportingTrackIds") or []),
            })
            decisions.append({
                "decisionId": f"dec-auto-{uid}",
                "reviewUnitId": uid,
                "action": "DEFER",
                "selectedCatalogId": None,
                "confirmedByHuman": False,
                "reviewerType": "AUTO",
            })

    total_units = len(review_units)
    res_count = len(resolved)
    unres_count = len(unresolved)
    # V1/V2 packets carry coverage in warehouseCoverage.status. The flat field
    # is only a legacy compatibility input; missing evidence is never complete.
    if "warehouseCoverage" in packet:
        coverage_document = packet.get("warehouseCoverage")
        coverage = coverage_document.get("status") if isinstance(coverage_document, Mapping) else None
    else:
        coverage = packet.get("warehouseCoverageStatus")
    if not isinstance(coverage, str) or coverage not in {"COMPLETE", "PARTIAL", "COVERAGE_UNPROVEN"}:
        coverage = "COVERAGE_UNPROVEN"
    completion = "COMPLETE" if unres_count == 0 and total_units > 0 else "PARTIAL"
    resolution = "RESOLVED" if completion == "COMPLETE" and coverage == "COMPLETE" else "PARTIAL"

    artifact = {
        "schemaVersion": REVIEW_SCHEMA_V2,
        "recordStableKey": key,
        "packetFingerprint": fingerprint,
        "reviewedAt": reviewed_ts,
        "reviewerType": "AUTO",
        "warehouseCoverageStatus": coverage,
        "reviewCompletion": completion,
        "identityResolution": resolution,
        "resolvedItems": resolved,
        "unresolvedUnits": unresolved,
        "excludedUnits": [],
        "decisions": decisions,
        "summary": {
            "resolvedItemCount": res_count,
            "unresolvedUnitCount": unres_count,
            "excludedUnitCount": 0,
            "decisionCount": len(decisions),
        },
    }
    artifact["artifactFingerprint"] = artifact_fingerprint_for(artifact)
    return artifact
