"""Fail-closed Venue / Box Catalog v1 contract primitives.

This module is the single authority boundary consumed by the Alpha Manual UI.
Catalog approval and per-fact evidence classification deliberately remain
separate: Alpha approval never upgrades operator assertions into game capture.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


EVIDENCE_SCHEMA_VERSION = "venue-box-catalog-evidence.v1"
CATALOG_SCHEMA_VERSION = "venue-box-catalog.v1"
UNKNOWN_TOKENS = frozenset({"", "unknown", "unverified", "未知", "未知场地", "未知箱型"})
CURRENT_EVIDENCE_TYPES = frozenset({"CURRENT_GAME_FULL_UI", "CURRENT_GAME_SESSION"})
EVIDENCE_TYPES = CURRENT_EVIDENCE_TYPES | frozenset({
    "LEGACY_GAME_CAPTURE", "PROJECT_DERIVED_CROP", "USER_PROVIDED_STATEMENT",
    "OPERATOR_ASSERTION", "CURRENT_GAME_BOX_OBSERVATION",
})
EVIDENCE_CLASSIFICATIONS = frozenset({
    "CURRENT_GAME_VALID", "LEGACY_GAME_EVIDENCE", "DERIVED_ONLY",
    "USER_PROVIDED_TRUTH_CLUE", "OPERATOR_ASSERTED_CURRENT",
    "CURRENT_GAME_OBSERVED", "UNVERIFIED",
})
REVIEW_STATUSES = frozenset({"APPROVED", "REJECTED", "PENDING"})
OPERATOR_CONFIDENCES = frozenset({"CONFIRMED", "PROBABLE"})
CATALOG_STATUSES = frozenset({"DRAFT", "APPROVED_FOR_ALPHA", "APPROVED_FOR_PRODUCTION"})
COMPATIBILITY_CONSUMERS = frozenset({"v06_python_adapter", "v06_js_adapter", "v06_solver"})
SOLVER_COMPATIBILITY_SCHEMA_VERSION = "v06-solver-compatibility.v1"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: Tuple[str, ...]


class CatalogContractError(ValueError):
    pass


def _application_asset_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None
    return Path(frozen_root).resolve() if frozen_root else Path(__file__).resolve().parents[1]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_timezone_aware(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _is_unknown(value: Any) -> bool:
    return value is None or str(value).strip().lower() in UNKNOWN_TOKENS


def _dedupe_errors(errors: Iterable[str]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(errors))


def validate_evidence(
    evidence: Mapping[str, Any],
    *,
    repo_root: Optional[Path] = None,
    require_current: bool = False,
) -> ValidationResult:
    errors = []
    required = (
        "schemaVersion",
        "evidenceId",
        "gameBuild",
        "capturedAt",
        "evidenceType",
        "sourcePath",
        "sourceSha256",
        "reviewer",
        "reviewStatus",
        "classification",
        "claims",
    )
    for key in required:
        if key not in evidence:
            errors.append(f"EVIDENCE_REQUIRED_FIELD_MISSING:{key}")

    if evidence.get("schemaVersion") != EVIDENCE_SCHEMA_VERSION:
        errors.append("EVIDENCE_SCHEMA_VERSION_UNSUPPORTED")
    if _is_unknown(evidence.get("evidenceId")):
        errors.append("EVIDENCE_ID_MISSING")
    if _is_unknown(evidence.get("gameBuild")):
        errors.append("EVIDENCE_GAME_BUILD_UNKNOWN")
    if not _is_timezone_aware(evidence.get("capturedAt")):
        errors.append("EVIDENCE_CAPTURED_AT_NOT_TIMEZONE_AWARE")
    if _is_unknown(evidence.get("reviewer")):
        errors.append("EVIDENCE_REVIEWER_MISSING")
    if evidence.get("evidenceType") not in EVIDENCE_TYPES:
        errors.append("EVIDENCE_TYPE_INVALID")
    if evidence.get("reviewStatus") not in REVIEW_STATUSES:
        errors.append("EVIDENCE_REVIEW_STATUS_INVALID")
    if evidence.get("classification") not in EVIDENCE_CLASSIFICATIONS:
        errors.append("EVIDENCE_CLASSIFICATION_INVALID")
    if evidence.get("classification") == "OPERATOR_ASSERTED_CURRENT":
        if evidence.get("evidenceType") != "OPERATOR_ASSERTION":
            errors.append("OPERATOR_ASSERTION_EVIDENCE_TYPE_REQUIRED")
        if evidence.get("operatorConfidence") not in OPERATOR_CONFIDENCES:
            errors.append("OPERATOR_ASSERTION_CONFIDENCE_REQUIRED")
    elif evidence.get("operatorConfidence") is not None:
        errors.append("OPERATOR_CONFIDENCE_ONLY_FOR_ASSERTION")

    source_hash = str(evidence.get("sourceSha256") or "").lower()
    if len(source_hash) != 64 or any(ch not in "0123456789abcdef" for ch in source_hash):
        errors.append("EVIDENCE_SOURCE_SHA256_INVALID")

    source_path = str(evidence.get("sourcePath") or "").strip()
    if not source_path:
        errors.append("EVIDENCE_SOURCE_PATH_MISSING")
    elif repo_root is not None:
        resolved = (repo_root / source_path).resolve()
        try:
            resolved.relative_to(repo_root.resolve())
        except ValueError:
            errors.append("EVIDENCE_SOURCE_PATH_OUTSIDE_REPO")
        else:
            if not resolved.is_file():
                errors.append("EVIDENCE_SOURCE_FILE_MISSING")
            elif source_hash and file_sha256(resolved) != source_hash:
                errors.append("EVIDENCE_SOURCE_HASH_MISMATCH")

    claims = evidence.get("claims")
    if not isinstance(claims, list) or not claims:
        errors.append("EVIDENCE_CLAIMS_EMPTY")
    else:
        for index, claim in enumerate(claims):
            if not isinstance(claim, Mapping):
                errors.append(f"EVIDENCE_CLAIM_INVALID:{index}")
                continue
            claim_type = str(claim.get("claimType") or "")
            raw_text = str(claim.get("rawGameText") or "").strip()
            if not claim_type:
                errors.append(f"EVIDENCE_CLAIM_TYPE_MISSING:{index}")
            if not raw_text:
                errors.append(f"EVIDENCE_RAW_GAME_TEXT_MISSING:{index}")
            if claim_type.startswith("VENUE_") and claim_type != "VENUE_OPTION_SET" and not claim.get("venueDisplayName"):
                errors.append(f"EVIDENCE_VENUE_NAME_MISSING:{index}")
            if claim_type.startswith("BOX_") and not claim.get("boxDisplayName"):
                errors.append(f"EVIDENCE_BOX_NAME_MISSING:{index}")
            if claim_type == "VENUE_BOX_MEMBERSHIP":
                if not claim.get("venueDisplayName") or not claim.get("boxDisplayName"):
                    errors.append(f"EVIDENCE_MEMBERSHIP_ENDPOINT_MISSING:{index}")

    is_current = evidence.get("classification") == "CURRENT_GAME_VALID"
    if is_current or require_current:
        if evidence.get("reviewStatus") != "APPROVED":
            errors.append("CURRENT_EVIDENCE_NOT_APPROVED")
        if evidence.get("evidenceType") not in CURRENT_EVIDENCE_TYPES:
            errors.append("CURRENT_EVIDENCE_TYPE_NOT_ALLOWED")
        if evidence.get("classification") != "CURRENT_GAME_VALID":
            errors.append("CURRENT_EVIDENCE_CLASSIFICATION_REQUIRED")

    return ValidationResult(not errors, _dedupe_errors(errors))


def evidence_bundle_sha256(evidence_records: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(
        (dict(record) for record in evidence_records),
        key=lambda item: str(item.get("evidenceId") or ""),
    )
    return canonical_sha256(ordered)


def _validate_nullable_fact(
    value: Any,
    *,
    label: str,
    evidence_ids: set[str],
    current_evidence_ids: set[str],
) -> list[str]:
    errors = []
    if not isinstance(value, Mapping):
        return [f"{label}_FACT_INVALID"]
    status = value.get("status")
    fact_value = value.get("value")
    refs = value.get("evidenceRefs")
    if status not in {"VERIFIED", "UNKNOWN", "NOT_APPLICABLE", "NOT_GAME_AUTHORITY"}:
        errors.append(f"{label}_STATUS_INVALID")
    if not isinstance(refs, list):
        errors.append(f"{label}_EVIDENCE_REFS_INVALID")
        refs = []
    for ref in refs:
        if ref not in evidence_ids:
            errors.append(f"{label}_EVIDENCE_REF_UNKNOWN:{ref}")
    if status == "VERIFIED":
        if fact_value is None:
            errors.append(f"{label}_VERIFIED_VALUE_MISSING")
        if not refs:
            errors.append(f"{label}_VERIFIED_EVIDENCE_MISSING")
        if any(ref not in current_evidence_ids for ref in refs):
            errors.append(f"{label}_VERIFIED_EVIDENCE_NOT_CURRENT")
    elif fact_value is not None:
        errors.append(f"{label}_NONVERIFIED_VALUE_MUST_BE_NULL")
    return errors


def validate_catalog(
    catalog: Mapping[str, Any],
    evidence_records: Sequence[Mapping[str, Any]],
    *,
    repo_root: Optional[Path] = None,
    require_production: bool = False,
) -> ValidationResult:
    errors = []
    if catalog.get("schemaVersion") != CATALOG_SCHEMA_VERSION:
        errors.append("CATALOG_SCHEMA_VERSION_UNSUPPORTED")
    if _is_unknown(catalog.get("catalogVersion")):
        errors.append("CATALOG_VERSION_MISSING")
    if catalog.get("catalogStatus") not in CATALOG_STATUSES:
        errors.append("CATALOG_STATUS_INVALID")
    if _is_unknown(catalog.get("gameBuild")):
        errors.append("CATALOG_GAME_BUILD_UNKNOWN")
    if not _is_timezone_aware(catalog.get("generatedAt")):
        errors.append("CATALOG_GENERATED_AT_NOT_TIMEZONE_AWARE")

    evidence_by_id: Dict[str, Mapping[str, Any]] = {}
    current_evidence_ids: set[str] = set()
    operator_evidence_ids: set[str] = set()
    for evidence in evidence_records:
        evidence_id = str(evidence.get("evidenceId") or "")
        if not evidence_id:
            errors.append("CATALOG_EVIDENCE_ID_MISSING")
            continue
        if evidence_id in evidence_by_id:
            errors.append(f"CATALOG_EVIDENCE_ID_DUPLICATE:{evidence_id}")
            continue
        evidence_by_id[evidence_id] = evidence
        result = validate_evidence(evidence, repo_root=repo_root)
        if not result.ok:
            errors.extend(f"CATALOG_EVIDENCE_INVALID:{evidence_id}:{item}" for item in result.errors)
        if evidence.get("classification") == "CURRENT_GAME_VALID" and result.ok:
            current_evidence_ids.add(evidence_id)
        if evidence.get("classification") == "OPERATOR_ASSERTED_CURRENT" and result.ok:
            operator_evidence_ids.add(evidence_id)

    expected_bundle_hash = evidence_bundle_sha256(evidence_records)
    if catalog.get("evidenceBundleSha256") != expected_bundle_hash:
        errors.append("CATALOG_EVIDENCE_BUNDLE_HASH_MISMATCH")

    venues = catalog.get("venues")
    if not isinstance(venues, list) or not venues:
        errors.append("CATALOG_VENUES_EMPTY")
        venues = []

    venue_ids: set[str] = set()
    venue_aliases: Dict[str, str] = {}
    box_ids: set[str] = set()
    box_aliases: Dict[str, str] = {}
    all_evidence_ids = set(evidence_by_id)

    for index, venue in enumerate(venues):
        if not isinstance(venue, Mapping):
            errors.append(f"CATALOG_VENUE_INVALID:{index}")
            continue
        venue_id = str(venue.get("venueId") or "").strip()
        if not venue_id:
            errors.append(f"CATALOG_VENUE_ID_MISSING:{index}")
            continue
        if venue_id in venue_ids:
            errors.append(f"CATALOG_VENUE_ID_DUPLICATE:{venue_id}")
        venue_ids.add(venue_id)
        display_name = str(venue.get("displayName") or "").strip()
        if not display_name:
            errors.append(f"CATALOG_VENUE_DISPLAY_NAME_MISSING:{venue_id}")
        if not isinstance(venue.get("selectable"), bool):
            errors.append(f"CATALOG_VENUE_SELECTABLE_INVALID:{venue_id}")
        refs = venue.get("evidenceRefs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"CATALOG_VENUE_EVIDENCE_MISSING:{venue_id}")
            refs = []
        for ref in refs:
            if ref not in current_evidence_ids:
                errors.append(f"CATALOG_VENUE_EVIDENCE_NOT_CURRENT:{venue_id}:{ref}")

        errors.extend(_validate_nullable_fact(
            venue.get("tier"),
            label=f"CATALOG_VENUE_TIER:{venue_id}",
            evidence_ids=all_evidence_ids,
            current_evidence_ids=current_evidence_ids,
        ))
        errors.extend(_validate_nullable_fact(
            venue.get("assetRequirement"),
            label=f"CATALOG_VENUE_ASSET_REQUIREMENT:{venue_id}",
            evidence_ids=all_evidence_ids,
            current_evidence_ids=current_evidence_ids,
        ))
        errors.extend(_validate_nullable_fact(
            venue.get("entryCost"),
            label=f"CATALOG_VENUE_ENTRY_COST:{venue_id}",
            evidence_ids=all_evidence_ids,
            current_evidence_ids=current_evidence_ids,
        ))

        for alias in [display_name, *(venue.get("observationAliases") or [])]:
            key = str(alias).strip().casefold()
            if not key:
                continue
            owner = venue_aliases.get(key)
            if owner and owner != venue_id:
                errors.append(f"CATALOG_VENUE_ALIAS_AMBIGUOUS:{alias}")
            venue_aliases[key] = venue_id

        boxes = venue.get("boxes")
        if not isinstance(boxes, list):
            errors.append(f"CATALOG_BOXES_INVALID:{venue_id}")
            continue
        for box in boxes:
            if not isinstance(box, Mapping):
                errors.append(f"CATALOG_BOX_INVALID:{venue_id}")
                continue
            box_id = str(box.get("boxId") or "").strip()
            if not box_id:
                errors.append(f"CATALOG_BOX_ID_MISSING:{venue_id}")
                continue
            if box_id in box_ids:
                errors.append(f"CATALOG_BOX_ID_DUPLICATE:{box_id}")
            box_ids.add(box_id)
            box_name = str(box.get("displayName") or "").strip()
            if not box_name:
                errors.append(f"CATALOG_BOX_DISPLAY_NAME_MISSING:{box_id}")
            box_refs = box.get("evidenceRefs")
            if not isinstance(box_refs, list) or not box_refs:
                errors.append(f"CATALOG_BOX_EVIDENCE_MISSING:{box_id}")
                box_refs = []
            for ref in box_refs:
                if ref not in all_evidence_ids:
                    errors.append(f"CATALOG_BOX_EVIDENCE_UNKNOWN:{box_id}:{ref}")
            membership_class = box.get("membershipEvidenceClass")
            text_class = box.get("textEvidenceClass")
            if membership_class not in EVIDENCE_CLASSIFICATIONS:
                errors.append(f"CATALOG_BOX_MEMBERSHIP_CLASS_INVALID:{box_id}")
            if text_class not in EVIDENCE_CLASSIFICATIONS:
                errors.append(f"CATALOG_BOX_TEXT_CLASS_INVALID:{box_id}")
            confidence = box.get("operatorConfidence")
            if membership_class == "OPERATOR_ASSERTED_CURRENT":
                if confidence not in OPERATOR_CONFIDENCES:
                    errors.append(f"CATALOG_BOX_OPERATOR_CONFIDENCE_REQUIRED:{box_id}")
                if not any(ref in operator_evidence_ids for ref in box_refs):
                    errors.append(f"CATALOG_BOX_OPERATOR_EVIDENCE_MISSING:{box_id}")
            elif confidence is not None:
                errors.append(f"CATALOG_BOX_OPERATOR_CONFIDENCE_UNEXPECTED:{box_id}")
            effect = box.get("effect")
            if not isinstance(effect, Mapping):
                errors.append(f"CATALOG_BOX_EFFECT_INVALID:{box_id}")
            else:
                for field in ("rawGameText", "normalizedSemantic", "normalizationEvidenceRefs"):
                    if field not in effect:
                        errors.append(f"CATALOG_BOX_EFFECT_FIELD_MISSING:{box_id}:{field}")
                normalized = effect.get("normalizedSemantic")
                normalization_refs = effect.get("normalizationEvidenceRefs")
                if normalized is not None:
                    if not isinstance(normalization_refs, list) or not normalization_refs:
                        errors.append(f"CATALOG_BOX_NORMALIZATION_EVIDENCE_MISSING:{box_id}")
                    elif any(ref not in current_evidence_ids for ref in normalization_refs):
                        errors.append(f"CATALOG_BOX_NORMALIZATION_EVIDENCE_NOT_CURRENT:{box_id}")
            for alias in [box_name, *(box.get("observationAliases") or [])]:
                key = str(alias).strip().casefold()
                if not key:
                    continue
                owner = box_aliases.get(key)
                if owner and owner != box_id:
                    errors.append(f"CATALOG_BOX_ALIAS_AMBIGUOUS:{alias}")
                box_aliases[key] = box_id

    translations = catalog.get("compatibilityTranslations")
    if not isinstance(translations, list):
        errors.append("CATALOG_COMPATIBILITY_TRANSLATIONS_INVALID")
        translations = []
    translation_keys = set()
    for row in translations:
        if not isinstance(row, Mapping):
            errors.append("CATALOG_COMPATIBILITY_TRANSLATION_INVALID")
            continue
        key = (row.get("consumer"), row.get("catalogVenueId"))
        if key in translation_keys:
            errors.append(f"CATALOG_COMPATIBILITY_TRANSLATION_DUPLICATE:{key[0]}:{key[1]}")
        translation_keys.add(key)
        if row.get("consumer") not in COMPATIBILITY_CONSUMERS:
            errors.append(f"CATALOG_COMPATIBILITY_CONSUMER_INVALID:{row.get('consumer')}")
        if row.get("status") not in {"EXPLICIT", "COMPATIBILITY_TRANSLATION", "UNRESOLVED"}:
            errors.append(f"CATALOG_COMPATIBILITY_STATUS_INVALID:{key[0]}:{key[1]}")
        if row.get("catalogVenueId") not in venue_ids:
            errors.append(f"CATALOG_COMPATIBILITY_VENUE_UNKNOWN:{row.get('catalogVenueId')}")
        if row.get("status") in {"EXPLICIT", "COMPATIBILITY_TRANSLATION"} and _is_unknown(row.get("compatibilityValue")):
            errors.append(f"CATALOG_COMPATIBILITY_VALUE_MISSING:{key[0]}:{key[1]}")
        if row.get("status") == "COMPATIBILITY_TRANSLATION":
            for field in (
                "catalogVersion", "currentId", "translationVersion", "sourceAuthority",
                "sourceReference", "translationRef",
            ):
                if _is_unknown(row.get(field)):
                    errors.append(f"CATALOG_COMPATIBILITY_PROVENANCE_MISSING:{key[0]}:{key[1]}:{field}")
            if row.get("catalogVersion") != catalog.get("catalogVersion"):
                errors.append(f"CATALOG_COMPATIBILITY_VERSION_MISMATCH:{key[0]}:{key[1]}")
            if row.get("currentId") != row.get("catalogVenueId"):
                errors.append(f"CATALOG_COMPATIBILITY_CURRENT_ID_MISMATCH:{key[0]}:{key[1]}")
        if row.get("status") == "UNRESOLVED" and row.get("compatibilityValue") is not None:
            errors.append(f"CATALOG_COMPATIBILITY_UNRESOLVED_VALUE_PRESENT:{key[0]}:{key[1]}")

    alpha_gate = catalog.get("catalogStatus") in {"APPROVED_FOR_ALPHA", "APPROVED_FOR_PRODUCTION"}
    if alpha_gate:
        if not current_evidence_ids:
            errors.append("CATALOG_HAS_NO_CURRENT_GAME_EVIDENCE")
        for venue in venues:
            if not isinstance(venue, Mapping):
                continue
            venue_id = str(venue.get("venueId") or "")
            boxes = venue.get("boxes")
            if not isinstance(boxes, list) or not boxes:
                errors.append(f"CATALOG_ALPHA_BOX_SET_EMPTY:{venue_id}")

    production_gate = require_production or catalog.get("catalogStatus") == "APPROVED_FOR_PRODUCTION"
    if production_gate:
        if catalog.get("catalogStatus") != "APPROVED_FOR_PRODUCTION":
            errors.append("CATALOG_NOT_APPROVED_FOR_PRODUCTION")
        if not current_evidence_ids:
            errors.append("CATALOG_HAS_NO_CURRENT_GAME_EVIDENCE")
        if any(evidence_by_id[ref].get("gameBuild") != catalog.get("gameBuild") for ref in current_evidence_ids):
            errors.append("CATALOG_CURRENT_EVIDENCE_GAME_BUILD_MISMATCH")
        for venue in venues:
            if not isinstance(venue, Mapping):
                continue
            venue_id = str(venue.get("venueId") or "")
            boxes = venue.get("boxes")
            if not isinstance(boxes, list) or not boxes:
                errors.append(f"CATALOG_PRODUCTION_BOX_SET_EMPTY:{venue_id}")
                continue
            for box in boxes:
                if not isinstance(box, Mapping):
                    continue
                if box.get("membershipEvidenceClass") != "CURRENT_GAME_VALID":
                    errors.append(f"CATALOG_PRODUCTION_BOX_MEMBERSHIP_NOT_CURRENT:{box.get('boxId')}")
                if box.get("textEvidenceClass") != "CURRENT_GAME_VALID":
                    errors.append(f"CATALOG_PRODUCTION_BOX_TEXT_NOT_CURRENT:{box.get('boxId')}")
                effect = box.get("effect")
                if not isinstance(effect, Mapping) or _is_unknown(effect.get("rawGameText")):
                    errors.append(f"CATALOG_PRODUCTION_BOX_EFFECT_TEXT_MISSING:{box.get('boxId')}")

    return ValidationResult(not errors, _dedupe_errors(errors))


def immutable_snapshot(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return an immutable JSON-safe mapping without leaking caller references."""

    def freeze(item: Any) -> Any:
        if isinstance(item, Mapping):
            return MappingProxyType({str(key): freeze(val) for key, val in item.items()})
        if isinstance(item, list):
            return tuple(freeze(val) for val in item)
        return item

    return freeze(json.loads(_canonical_bytes(value).decode("utf-8")))


def _require_approved(catalog: Mapping[str, Any]) -> None:
    if catalog.get("catalogStatus") not in {"APPROVED_FOR_ALPHA", "APPROVED_FOR_PRODUCTION"}:
        raise CatalogContractError("CATALOG_NOT_APPROVED")


def manual_options(catalog: Mapping[str, Any]) -> Tuple[Mapping[str, Any], ...]:
    """Derive exact-venue UI options; never expose a synthetic tier selector."""
    _require_approved(catalog)
    options = []
    for venue in catalog.get("venues") or []:
        if venue.get("selectable") is not True:
            continue
        options.append({
            "venueId": venue["venueId"],
            "displayName": venue["displayName"],
            "entryCost": venue.get("entryCost", {}).get("value"),
            "venueEvidenceClass": "CURRENT_GAME_VALID",
            "boxes": tuple({
                "boxId": box["boxId"],
                "displayName": box["displayName"],
                "effectText": box.get("effect", {}).get("rawGameText"),
                "evidenceClass": box.get("membershipEvidenceClass"),
            } for box in venue.get("boxes") or []) + ({
                "boxId": None,
                "displayName": "未知 / 其他",
                "effectText": None,
                "evidenceClass": "UNRECOGNIZED_CURRENT_BOX",
            },),
        })
    return tuple(immutable_snapshot(option) for option in options)


def validate_environment(
    catalog: Mapping[str, Any],
    *,
    venue_id: Optional[str],
    box_id: Optional[str],
) -> Mapping[str, Any]:
    """Validate exact venue/box membership while preserving unknown semantics."""
    _require_approved(catalog)
    if _is_unknown(venue_id):
        if _is_unknown(box_id):
            return immutable_snapshot({"ok": True, "status": "UNKNOWN", "venueId": None, "boxId": None})
        return immutable_snapshot({"ok": False, "status": "BOX_WITHOUT_VENUE", "venueId": None, "boxId": box_id})
    venues = {venue["venueId"]: venue for venue in catalog.get("venues") or []}
    venue = venues.get(str(venue_id))
    if venue is None:
        return immutable_snapshot({"ok": False, "status": "INVALID_VENUE", "venueId": venue_id, "boxId": box_id})
    if _is_unknown(box_id):
        return immutable_snapshot({"ok": True, "status": "BOX_UNKNOWN", "venueId": venue_id, "boxId": None})
    allowed = {box["boxId"] for box in venue.get("boxes") or []}
    if box_id not in allowed:
        return immutable_snapshot({"ok": False, "status": "INVALID_VENUE_BOX_PAIR", "venueId": venue_id, "boxId": box_id})
    return immutable_snapshot({"ok": True, "status": "VALIDATED", "venueId": venue_id, "boxId": box_id})


def normalize_vision_venue(catalog: Mapping[str, Any], observation: Optional[str]) -> Mapping[str, Any]:
    """Map a Vision observation only through explicit catalog aliases."""
    _require_approved(catalog)
    if _is_unknown(observation):
        return immutable_snapshot({"status": "UNKNOWN", "venueId": None, "provenance": "VISION_OBSERVATION"})
    needle = str(observation).strip().casefold()
    matches = []
    for venue in catalog.get("venues") or []:
        aliases = [venue.get("displayName"), *(venue.get("observationAliases") or [])]
        if needle in {str(alias).strip().casefold() for alias in aliases if alias}:
            matches.append(venue["venueId"])
    if len(matches) != 1 and "·" in needle:
        clean_needle = needle.split("·")[-1].strip()
        if clean_needle:
            for venue in catalog.get("venues") or []:
                aliases = [venue.get("displayName"), *(venue.get("observationAliases") or [])]
                if clean_needle in {str(alias).strip().casefold() for alias in aliases if alias}:
                    matches.append(venue["venueId"])
    if len(matches) != 1:
        return immutable_snapshot({"status": "REJECTED", "venueId": None, "provenance": "VISION_OBSERVATION"})
    return immutable_snapshot({"status": "NORMALIZED", "venueId": matches[0], "provenance": "VISION_OBSERVATION"})


def normalize_vision_box(catalog: Mapping[str, Any], *, venue_id: Optional[str], observation: Optional[str]) -> Mapping[str, Any]:
    """Normalize an observed box only inside the selected exact venue."""
    _require_approved(catalog)
    if _is_unknown(observation) or _is_unknown(venue_id):
        return immutable_snapshot({"status": "UNKNOWN", "boxId": None, "provenance": "VISION_OBSERVATION"})
    venue = next((item for item in catalog.get("venues") or [] if item.get("venueId") == venue_id), None)
    if venue is None:
        return immutable_snapshot({"status": "REJECTED", "boxId": None, "provenance": "VISION_OBSERVATION"})
    needle = str(observation).strip().casefold()
    matches = []
    for box in venue.get("boxes") or []:
        aliases = [box.get("displayName"), *(box.get("observationAliases") or [])]
        if needle in {str(alias).strip().casefold() for alias in aliases if alias}:
            matches.append(box["boxId"])
    if len(matches) != 1:
        return immutable_snapshot({"status": "UNKNOWN", "boxId": None, "provenance": "VISION_OBSERVATION"})
    return immutable_snapshot({"status": "NORMALIZED", "boxId": matches[0], "provenance": "VISION_OBSERVATION"})


def load_solver_compatibility(path: Optional[Path] = None) -> Mapping[str, Any]:
    resolved = Path(path) if path is not None else (
        _application_asset_root()
        / "assets"
        / "venue_box_catalog_v1"
        / "v06_solver_compatibility_v1.json"
    )
    return json.loads(resolved.read_text(encoding="utf-8"))


def validate_solver_compatibility(
    catalog: Mapping[str, Any],
    compatibility: Mapping[str, Any],
    *,
    repo_root: Optional[Path] = None,
) -> ValidationResult:
    """Validate v0.6 identifiers without promoting them to current game truth."""
    errors = []
    required = (
        "schemaVersion", "translationVersion", "catalogVersion", "consumer",
        "sourceAuthorities", "venueTranslations", "boxTranslations", "unknownBox",
    )
    for field in required:
        if field not in compatibility:
            errors.append(f"SOLVER_COMPATIBILITY_REQUIRED_FIELD_MISSING:{field}")
    if compatibility.get("schemaVersion") != SOLVER_COMPATIBILITY_SCHEMA_VERSION:
        errors.append("SOLVER_COMPATIBILITY_SCHEMA_VERSION_UNSUPPORTED")
    if compatibility.get("catalogVersion") != catalog.get("catalogVersion"):
        errors.append("SOLVER_COMPATIBILITY_CATALOG_VERSION_MISMATCH")
    if compatibility.get("consumer") != "v06_solver":
        errors.append("SOLVER_COMPATIBILITY_CONSUMER_INVALID")

    root = Path(repo_root) if repo_root is not None else _application_asset_root()
    source_authorities = compatibility.get("sourceAuthorities")
    authority_names = set()
    if not isinstance(source_authorities, list) or not source_authorities:
        errors.append("SOLVER_COMPATIBILITY_SOURCE_AUTHORITIES_EMPTY")
        source_authorities = []
    for source in source_authorities:
        if not isinstance(source, Mapping):
            errors.append("SOLVER_COMPATIBILITY_SOURCE_AUTHORITY_INVALID")
            continue
        authority = str(source.get("authority") or "")
        authority_names.add(authority)
        source_path = str(source.get("path") or "")
        expected_sha = str(source.get("sha256") or "")
        if not authority or not source_path or len(expected_sha) != 64:
            errors.append(f"SOLVER_COMPATIBILITY_SOURCE_PROVENANCE_INVALID:{authority or 'unknown'}")
            continue
        resolved = root / source_path
        if not resolved.is_file():
            errors.append(f"SOLVER_COMPATIBILITY_SOURCE_MISSING:{source_path}")
        elif file_sha256(resolved) != expected_sha:
            errors.append(f"SOLVER_COMPATIBILITY_SOURCE_HASH_MISMATCH:{source_path}")

    venues = {
        str(venue.get("venueId")): venue
        for venue in catalog.get("venues") or []
        if isinstance(venue, Mapping) and venue.get("selectable") is True
    }
    catalog_rows = {
        str(row.get("catalogVenueId")): row
        for row in catalog.get("compatibilityTranslations") or []
        if isinstance(row, Mapping) and row.get("consumer") == "v06_solver"
    }
    venue_rows = compatibility.get("venueTranslations")
    venue_by_id = {}
    if not isinstance(venue_rows, list):
        errors.append("SOLVER_COMPATIBILITY_VENUE_TRANSLATIONS_INVALID")
        venue_rows = []
    for row in venue_rows:
        if not isinstance(row, Mapping):
            errors.append("SOLVER_COMPATIBILITY_VENUE_TRANSLATION_INVALID")
            continue
        current_id = str(row.get("currentId") or "")
        if current_id in venue_by_id:
            errors.append(f"SOLVER_COMPATIBILITY_VENUE_DUPLICATE:{current_id}")
        venue_by_id[current_id] = row
        venue = venues.get(current_id)
        if venue is None:
            errors.append(f"SOLVER_COMPATIBILITY_VENUE_UNKNOWN:{current_id}")
            continue
        if row.get("status") != "COMPATIBILITY_TRANSLATION":
            errors.append(f"SOLVER_COMPATIBILITY_VENUE_STATUS_INVALID:{current_id}")
        if row.get("consumer") != "v06_solver" or row.get("catalogVersion") != catalog.get("catalogVersion"):
            errors.append(f"SOLVER_COMPATIBILITY_VENUE_PROVENANCE_INVALID:{current_id}")
        if row.get("currentDisplayName") != venue.get("displayName") or _is_unknown(row.get("legacyIdentifier")):
            errors.append(f"SOLVER_COMPATIBILITY_VENUE_IDENTITY_INVALID:{current_id}")
        if row.get("translationVersion") != compatibility.get("translationVersion"):
            errors.append(f"SOLVER_COMPATIBILITY_VENUE_VERSION_MISMATCH:{current_id}")
        if row.get("sourceAuthority") not in authority_names or _is_unknown(row.get("sourceReference")):
            errors.append(f"SOLVER_COMPATIBILITY_VENUE_SOURCE_INVALID:{current_id}")
        catalog_row = catalog_rows.get(current_id)
        if not catalog_row or catalog_row.get("status") != "COMPATIBILITY_TRANSLATION":
            errors.append(f"SOLVER_COMPATIBILITY_CATALOG_ROW_NOT_FROZEN:{current_id}")
        elif catalog_row.get("compatibilityValue") != row.get("legacyIdentifier"):
            errors.append(f"SOLVER_COMPATIBILITY_CATALOG_VALUE_MISMATCH:{current_id}")
    if set(venue_by_id) != set(venues):
        errors.append("SOLVER_COMPATIBILITY_VENUE_COVERAGE_INCOMPLETE")

    catalog_boxes = {}
    for venue_id, venue in venues.items():
        for box in venue.get("boxes") or []:
            if isinstance(box, Mapping):
                catalog_boxes[str(box.get("boxId"))] = (venue_id, box)
    box_rows = compatibility.get("boxTranslations")
    box_by_id = {}
    if not isinstance(box_rows, list):
        errors.append("SOLVER_COMPATIBILITY_BOX_TRANSLATIONS_INVALID")
        box_rows = []
    for row in box_rows:
        if not isinstance(row, Mapping):
            errors.append("SOLVER_COMPATIBILITY_BOX_TRANSLATION_INVALID")
            continue
        current_id = str(row.get("currentId") or "")
        if current_id in box_by_id:
            errors.append(f"SOLVER_COMPATIBILITY_BOX_DUPLICATE:{current_id}")
        box_by_id[current_id] = row
        owner = catalog_boxes.get(current_id)
        if owner is None:
            errors.append(f"SOLVER_COMPATIBILITY_BOX_UNKNOWN:{current_id}")
            continue
        venue_id, _box = owner
        if row.get("catalogVenueId") != venue_id:
            errors.append(f"SOLVER_COMPATIBILITY_BOX_VENUE_MISMATCH:{current_id}")
        for field in ("legacyIdentifier", "semantic", "sourceReference"):
            if _is_unknown(row.get(field)):
                errors.append(f"SOLVER_COMPATIBILITY_BOX_FIELD_MISSING:{current_id}:{field}")
        if row.get("status") != "COMPATIBILITY_TRANSLATION":
            errors.append(f"SOLVER_COMPATIBILITY_BOX_STATUS_INVALID:{current_id}")
        if row.get("consumer") != "v06_solver" or row.get("catalogVersion") != catalog.get("catalogVersion"):
            errors.append(f"SOLVER_COMPATIBILITY_BOX_PROVENANCE_INVALID:{current_id}")
        if row.get("translationVersion") != compatibility.get("translationVersion"):
            errors.append(f"SOLVER_COMPATIBILITY_BOX_VERSION_MISMATCH:{current_id}")
        if row.get("sourceAuthority") not in authority_names:
            errors.append(f"SOLVER_COMPATIBILITY_BOX_SOURCE_INVALID:{current_id}")
    if set(box_by_id) != set(catalog_boxes):
        errors.append("SOLVER_COMPATIBILITY_BOX_COVERAGE_INCOMPLETE")

    unknown_box = compatibility.get("unknownBox")
    if not isinstance(unknown_box, Mapping):
        errors.append("SOLVER_COMPATIBILITY_UNKNOWN_BOX_INVALID")
    elif (
        unknown_box.get("status") != "UNKNOWN_NO_BOX_EFFECT"
        or unknown_box.get("semantic") != "NO_BOX_EFFECT"
        or unknown_box.get("legacyIdentifier") is not None
    ):
        errors.append("SOLVER_COMPATIBILITY_UNKNOWN_BOX_NOT_FAIL_CLOSED")
    return ValidationResult(not errors, _dedupe_errors(errors))


def solver_context_translation(
    catalog: Mapping[str, Any],
    *,
    venue_id: Optional[str],
    box_id: Optional[str],
    consumer: str = "v06_solver",
    compatibility: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Translate catalog identity to a legacy Solver key, or fail closed."""
    environment = validate_environment(catalog, venue_id=venue_id, box_id=box_id)
    if environment["ok"] is not True or venue_id is None:
        return immutable_snapshot({"status": "SOLVER_CONTEXT_MAPPING_UNRESOLVED", "venue": None, "box": None})
    rows = [
        row for row in catalog.get("compatibilityTranslations") or []
        if row.get("consumer") == consumer and row.get("catalogVenueId") == venue_id
    ]
    if len(rows) != 1 or rows[0].get("status") not in {"EXPLICIT", "COMPATIBILITY_TRANSLATION"}:
        return immutable_snapshot({"status": "SOLVER_CONTEXT_MAPPING_UNRESOLVED", "venue": None, "box": None})
    venue = next(item for item in catalog["venues"] if item["venueId"] == venue_id)
    row = rows[0]
    if row.get("status") == "COMPATIBILITY_TRANSLATION":
        resolved = compatibility if compatibility is not None else load_solver_compatibility()
        checked = validate_solver_compatibility(catalog, resolved)
        if checked.ok is not True:
            return immutable_snapshot({
                "status": "SOLVER_CONTEXT_COMPATIBILITY_INVALID",
                "venue": None,
                "box": None,
                "reasonCodes": checked.errors,
            })
        venue_row = next(
            item for item in resolved["venueTranslations"]
            if item.get("currentId") == venue_id
        )
        if box_id is None:
            box_name = None
            box_status = "UNKNOWN_NO_BOX_EFFECT"
            box_semantic = "NO_BOX_EFFECT"
        else:
            box_row = next(
                (item for item in resolved["boxTranslations"] if item.get("currentId") == box_id),
                None,
            )
            if box_row is None or box_row.get("catalogVenueId") != venue_id:
                return immutable_snapshot({"status": "SOLVER_CONTEXT_MAPPING_UNRESOLVED", "venue": None, "box": None})
            box_name = box_row["legacyIdentifier"]
            box_status = "COMPATIBILITY_TRANSLATION"
            box_semantic = box_row["semantic"]
        return immutable_snapshot({
            "status": "COMPATIBILITY_TRANSLATION",
            "venue": venue_row["legacyIdentifier"],
            "box": box_name,
            "boxStatus": box_status,
            "boxSemantic": box_semantic,
            "catalogVersion": catalog["catalogVersion"],
            "translationVersion": resolved["translationVersion"],
        })
    box_name = None
    if box_id is not None:
        box_name = next(item["displayName"] for item in venue.get("boxes") or [] if item["boxId"] == box_id)
    return immutable_snapshot({
        "status": "COMPATIBILITY_TRANSLATION",
        "venue": row["compatibilityValue"],
        "box": box_name,
        "catalogVersion": catalog["catalogVersion"],
    })


def canonical_catalog_provenance(catalog: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_approved(catalog)
    return immutable_snapshot({
        "catalogVersion": catalog["catalogVersion"],
        "catalogApprovalStatus": catalog["catalogStatus"],
        "gameBuild": catalog["gameBuild"],
        "catalogSha256": canonical_sha256(catalog),
        "gameEvidenceCohort": "CURRENT_VENUE_OPERATOR_BOX_BOOTSTRAP_2026_08_22",
    })


def load_catalog(path: Optional[Path] = None) -> Mapping[str, Any]:
    resolved = Path(path) if path is not None else _application_asset_root() / "assets" / "venue_box_catalog_v1" / "venue_box_catalog_v1.json"
    return json.loads(resolved.read_text(encoding="utf-8"))


def catalog_selection(catalog: Mapping[str, Any], venue_id: Any, box_id: Any) -> Mapping[str, Any]:
    """Resolve a Manual selection to presentation-ready canonical scalars."""
    checked = validate_environment(catalog, venue_id=venue_id, box_id=box_id)
    if checked["ok"] is not True:
        raise CatalogContractError(str(checked["status"]))
    if checked["venueId"] is None:
        return immutable_snapshot({
            "status": "UNKNOWN", "venueId": None, "venue": None, "entryCost": None,
            "boxId": None, "box": None, "venueEvidenceClass": "UNVERIFIED",
            "boxEvidenceClass": "UNRECOGNIZED_CURRENT_BOX",
        })
    venue = next(v for v in catalog["venues"] if v["venueId"] == checked["venueId"])
    box = next((b for b in venue.get("boxes") or [] if b["boxId"] == checked["boxId"]), None)
    return immutable_snapshot({
        "status": checked["status"],
        "venueId": venue["venueId"],
        "venue": venue["displayName"],
        "entryCost": venue["entryCost"]["value"],
        "boxId": box["boxId"] if box else None,
        "box": box["displayName"] if box else None,
        "venueEvidenceClass": "CURRENT_GAME_VALID",
        "boxEvidenceClass": box["membershipEvidenceClass"] if box else "UNRECOGNIZED_CURRENT_BOX",
    })


def validate_box_observation(observation: Mapping[str, Any]) -> ValidationResult:
    errors = []
    required = ("schemaVersion", "observedAt", "venueId", "rawDisplayName", "reviewer", "catalogVersion", "collectionMode")
    for key in required:
        if key not in observation:
            errors.append(f"BOX_OBSERVATION_REQUIRED_FIELD_MISSING:{key}")
    if observation.get("schemaVersion") != "box-observation.v1":
        errors.append("BOX_OBSERVATION_SCHEMA_VERSION_UNSUPPORTED")
    if not _is_timezone_aware(observation.get("observedAt")):
        errors.append("BOX_OBSERVATION_TIMESTAMP_INVALID")
    if observation.get("collectionMode") != "PASSIVE_NATURAL_COLLECTION":
        errors.append("BOX_OBSERVATION_COLLECTION_MODE_INVALID")
    if _is_unknown(observation.get("venueId")) or _is_unknown(observation.get("rawDisplayName")):
        errors.append("BOX_OBSERVATION_IDENTITY_MISSING")
    return ValidationResult(not errors, _dedupe_errors(errors))


def progressive_evidence_class(current: str, *, approved_observation: bool, explicit_validation: bool = False) -> str:
    """Versioned progression with no count-based automatic promotion."""
    if explicit_validation:
        return "CURRENT_GAME_VALID"
    if approved_observation and current in {"OPERATOR_ASSERTED_CURRENT", "CURRENT_GAME_OBSERVED"}:
        return "CURRENT_GAME_OBSERVED"
    return current


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "EVIDENCE_SCHEMA_VERSION",
    "SOLVER_COMPATIBILITY_SCHEMA_VERSION",
    "CatalogContractError",
    "ValidationResult",
    "canonical_catalog_provenance",
    "catalog_selection",
    "canonical_sha256",
    "evidence_bundle_sha256",
    "file_sha256",
    "immutable_snapshot",
    "manual_options",
    "load_catalog",
    "load_solver_compatibility",
    "normalize_vision_venue",
    "normalize_vision_box",
    "solver_context_translation",
    "validate_solver_compatibility",
    "validate_catalog",
    "validate_environment",
    "validate_evidence",
    "validate_box_observation",
    "progressive_evidence_class",
]
