"""Attach verified Store v2 originals onto Truth Evidence v2 for review save.

Does not accept client-supplied descriptors. History writes stay in the caller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from settlement_evidence_store_v2 import (
    SettlementEvidenceStoreError,
    SettlementEvidenceStoreV2,
    detect_image_type,
)
from settlement_truth_evidence_contract import (
    TRUTH_EVIDENCE_V2,
    validate_settlement_evidence_original_v2,
)
from settlement_truth_holder import build_truth_payload_sha256


class ReviewFileOriginalError(ValueError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def sanitize_evidence_references(refs: Any) -> List[Dict[str, str]]:
    cleaned: List[Dict[str, str]] = []
    seen = set()
    if not isinstance(refs, list):
        return cleaned
    for ref in refs:
        if not isinstance(ref, Mapping):
            continue
        uri = str(ref.get("uri") or "").strip()
        digest = str(ref.get("sha256") or "").strip().lower()
        if not uri or not digest:
            continue
        key = (uri, digest)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"uri": uri, "sha256": digest})
    return cleaned


def lookup_runtime_file_originals(record_id: str, data_root: Path) -> List[Dict[str, Any]]:
    try:
        store = SettlementEvidenceStoreV2(Path(data_root).resolve())
        return store.list_record_evidence(record_id)
    except (SettlementEvidenceStoreError, OSError, ValueError):
        return []


def verify_runtime_original(
    descriptor: Mapping[str, Any],
    *,
    record_id: str,
    data_root: Path,
) -> Dict[str, Any]:
    ok, reasons = validate_settlement_evidence_original_v2(descriptor)
    if not ok:
        raise ReviewFileOriginalError(
            "FILE_ORIGINAL_INVALID",
            "runtime descriptor failed contract: " + ",".join(reasons),
        )
    if str(descriptor.get("recordStableKey") or "") != str(record_id):
        raise ReviewFileOriginalError(
            "FILE_ORIGINAL_KEY_MISMATCH",
            "recordStableKey does not match the target History record",
        )
    store = SettlementEvidenceStoreV2(Path(data_root).resolve())
    checked = store.verify(dict(descriptor))
    if not checked.get("ok"):
        raise ReviewFileOriginalError(
            str(checked.get("status") or "FILE_ORIGINAL_VERIFY_FAILED"),
            f"runtime original failed disk verification: {checked.get('status')}",
        )
    payload = store.load_original(dict(descriptor))
    if len(payload) != int(descriptor["byteSize"]):
        raise ReviewFileOriginalError("FILE_ORIGINAL_SIZE_MISMATCH", "byteSize does not match file bytes")
    detected = detect_image_type(payload)
    if not detected or detected["mimeType"] != descriptor.get("mimeType"):
        raise ReviewFileOriginalError("FILE_ORIGINAL_TYPE_MISMATCH", "image type does not match descriptor")
    return dict(descriptor)


def merge_file_originals(
    existing: Sequence[Mapping[str, Any]],
    incoming: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    merged = [dict(item) for item in existing]
    for item in incoming:
        candidate = dict(item)
        matched = False
        for prev in merged:
            same_id = prev.get("evidenceId") == candidate.get("evidenceId")
            same_triple = (
                prev.get("recordStableKey") == candidate.get("recordStableKey")
                and prev.get("kind") == candidate.get("kind")
                and prev.get("sha256") == candidate.get("sha256")
            )
            if same_id:
                if prev.get("sha256") != candidate.get("sha256") or prev.get("relativePath") != candidate.get("relativePath"):
                    raise ReviewFileOriginalError(
                        "FILE_ORIGINAL_ID_CONFLICT",
                        "same evidenceId with different hash or path",
                    )
                matched = True
                break
            if same_triple:
                matched = True
                break
        if not matched:
            merged.append(candidate)
    return merged


def _copy_v1_fields(existing: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "matchId": existing.get("matchId"),
        "actualTotal": existing.get("actualTotal"),
        "settlementObservedAt": existing.get("settlementObservedAt"),
        "truthSource": existing.get("truthSource"),
        "truthConfidence": existing.get("truthConfidence"),
        "evidenceReferences": sanitize_evidence_references(existing.get("evidenceReferences")),
        "verification": existing.get("verification"),
        "truthPayloadSha256": existing.get("truthPayloadSha256"),
        "unresolvedTruthConflict": existing.get("unresolvedTruthConflict"),
        "inventoryScope": existing.get("inventoryScope"),
        "itemLedger": existing.get("itemLedger"),
    }


def build_truth_evidence_v2(
    *,
    record_id: str,
    existing: Optional[Mapping[str, Any]],
    settlement: Mapping[str, Any],
    originals: Sequence[Mapping[str, Any]],
    observed_at: str,
) -> Dict[str, Any]:
    if not originals:
        raise ReviewFileOriginalError("FILE_ORIGINALS_MISSING", "v2 requires a non-empty fileOriginals list")

    existing = existing or {}
    previous_originals = existing.get("fileOriginals") if existing.get("schemaVersion") == TRUTH_EVIDENCE_V2 else []
    if not isinstance(previous_originals, list):
        previous_originals = []
    merged_originals = merge_file_originals(previous_originals, originals)

    if existing.get("schemaVersion") in (None, "settlement-truth-evidence.v1", "settlement-truth-evidence.v2") and existing:
        body = _copy_v1_fields(existing)
    else:
        body = {
            "matchId": None,
            "actualTotal": None,
            "settlementObservedAt": None,
            "truthSource": None,
            "truthConfidence": None,
            "evidenceReferences": [],
            "verification": None,
            "truthPayloadSha256": None,
            "unresolvedTruthConflict": False,
            "inventoryScope": {"complete": None},
            "itemLedger": {"verified": False, "deduplicated": False, "sha256": None},
        }

    if not body.get("matchId"):
        body["matchId"] = record_id
    if body.get("actualTotal") in (None, 0):
        actual = settlement.get("actualTotal")
        body["actualTotal"] = float(actual) if actual not in (None, "") else None
    if not body.get("settlementObservedAt"):
        body["settlementObservedAt"] = observed_at
    if not body.get("truthSource"):
        body["truthSource"] = "review_save_file_original"
    if not body.get("truthConfidence"):
        body["truthConfidence"] = "high"
    if body.get("unresolvedTruthConflict") is None:
        body["unresolvedTruthConflict"] = False
    if not isinstance(body.get("inventoryScope"), dict):
        body["inventoryScope"] = {"complete": None}
    if not isinstance(body.get("itemLedger"), dict):
        body["itemLedger"] = {"verified": False, "deduplicated": False, "sha256": None}
    if not isinstance(body.get("verification"), dict):
        body["verification"] = {
            "method": "human_screenshot_audit_v1",
            "version": "settlement-review-save.v1",
            "verifier": {"type": "reviewer", "id": "user"},
        }

    refs = sanitize_evidence_references(body.get("evidenceReferences"))
    ordered_originals = sorted(merged_originals, key=lambda item: item.get("kind") != "main-settlement")
    original_refs = []
    for item in ordered_originals:
        pointer = {"uri": str(item["relativePath"]), "sha256": str(item["sha256"])}
        if pointer not in original_refs:
            original_refs.append(pointer)
    refs = original_refs + [ref for ref in refs if ref not in original_refs]
    body["evidenceReferences"] = refs

    if not body.get("truthPayloadSha256") and body.get("actualTotal") not in (None, "") and body.get("matchId"):
        body["truthPayloadSha256"] = build_truth_payload_sha256(
            match_id=str(body["matchId"]),
            actual_total=float(body["actualTotal"]),
            settlement_observed_at=str(body["settlementObservedAt"]),
            truth_source=str(body["truthSource"]),
        )

    if body.get("actualTotal") in (None, 0):
        raise ReviewFileOriginalError(
            "TRUTH_EVIDENCE_INCOMPLETE",
            "cannot upgrade to v2 without a positive actualTotal",
        )
    if not refs:
        raise ReviewFileOriginalError("EVIDENCE_REFERENCES_MISSING", "v2 requires evidenceReferences")

    body["schemaVersion"] = TRUTH_EVIDENCE_V2
    body["fileOriginals"] = merged_originals
    return body
