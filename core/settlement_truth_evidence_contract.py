"""Closed validators for Settlement Truth Evidence v1/v2 contracts.

Does not write History or Review. v1 schema documents stay unchanged.
Version discrimination uses schemaVersion; v2 additionally requires fileOriginals.
"""

from __future__ import annotations

import sys
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

TRUTH_EVIDENCE_V1 = "settlement-truth-evidence.v1"
TRUTH_EVIDENCE_V2 = "settlement-truth-evidence.v2"
ORIGINAL_V2 = "settlement-evidence-original-v2"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RECORD_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RELATIVE_PATH_RE = re.compile(
    r"^evidence/settlement_v2/blobs/[0-9a-f]{2}/[0-9a-f]{64}\.(png|jpg)$"
)

V1_KEYS = frozenset({
    "schemaVersion",
    "matchId",
    "actualTotal",
    "settlementObservedAt",
    "truthSource",
    "truthConfidence",
    "evidenceReferences",
    "verification",
    "truthPayloadSha256",
    "unresolvedTruthConflict",
    "inventoryScope",
    "itemLedger",
})
V2_KEYS = V1_KEYS | {"fileOriginals"}
ORIGINAL_V2_KEYS = frozenset({
    "schemaVersion",
    "evidenceId",
    "recordStableKey",
    "kind",
    "capturedAt",
    "storageMode",
    "relativePath",
    "sha256",
    "byteSize",
    "mimeType",
    "width",
    "height",
    "coverageMode",
    "coverageStatus",
})

CONTRACTS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "docs" / "contracts"


def load_contract_schema(name: str) -> Dict[str, Any]:
    path = CONTRACTS_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def classify_truth_evidence_version(evidence: Any) -> Optional[str]:
    if not isinstance(evidence, Mapping):
        return None
    version = evidence.get("schemaVersion")
    if version == TRUTH_EVIDENCE_V1:
        return TRUTH_EVIDENCE_V1
    if version == TRUTH_EVIDENCE_V2:
        return TRUTH_EVIDENCE_V2
    return None


def _unknown_keys(payload: Mapping[str, Any], allowed: frozenset) -> List[str]:
    extra = [key for key in payload.keys() if key not in allowed]
    return [f"UNKNOWN_FIELD_{key}" for key in extra]


def _validate_reference_item(ref: Any, reasons: List[str]) -> None:
    if not isinstance(ref, Mapping):
        reasons.append("EVIDENCE_REFERENCE_NOT_OBJECT")
        return
    reasons.extend(_unknown_keys(ref, frozenset({"uri", "sha256"})))
    if not str(ref.get("uri") or "").strip():
        reasons.append("EVIDENCE_REFERENCE_URI_MISSING")
    digest = str(ref.get("sha256") or "")
    if not SHA256_RE.fullmatch(digest):
        reasons.append("EVIDENCE_REFERENCE_SHA256_INVALID")


def _validate_shared_truth_fields(evidence: Mapping[str, Any], reasons: List[str]) -> None:
    if not str(evidence.get("matchId") or "").strip():
        reasons.append("MATCH_ID_MISSING")
    actual = evidence.get("actualTotal")
    if not isinstance(actual, (int, float)) or isinstance(actual, bool) or actual <= 0:
        reasons.append("ACTUAL_TOTAL_INVALID")
    if not str(evidence.get("settlementObservedAt") or "").strip():
        reasons.append("SETTLEMENT_OBSERVED_AT_MISSING")
    if not str(evidence.get("truthSource") or "").strip():
        reasons.append("TRUTH_SOURCE_MISSING")
    if evidence.get("truthConfidence") != "high":
        reasons.append("TRUTH_CONFIDENCE_NOT_HIGH")
    refs = evidence.get("evidenceReferences")
    if not isinstance(refs, list) or not refs:
        reasons.append("EVIDENCE_REFERENCES_MISSING")
    else:
        for ref in refs:
            _validate_reference_item(ref, reasons)
    verification = evidence.get("verification")
    if not isinstance(verification, Mapping):
        reasons.append("VERIFICATION_MISSING")
    else:
        reasons.extend(_unknown_keys(verification, frozenset({"method", "version", "verifier"})))
        if not str(verification.get("method") or "").strip():
            reasons.append("VERIFICATION_METHOD_MISSING")
        if not str(verification.get("version") or "").strip():
            reasons.append("VERIFICATION_VERSION_MISSING")
        verifier = verification.get("verifier")
        if not isinstance(verifier, Mapping):
            reasons.append("VERIFIER_MISSING")
        else:
            reasons.extend(_unknown_keys(verifier, frozenset({"type", "id"})))
            if verifier.get("type") not in ("reviewer", "deterministic_verifier"):
                reasons.append("VERIFIER_TYPE_INVALID")
            if not str(verifier.get("id") or "").strip():
                reasons.append("VERIFIER_ID_MISSING")
    if not SHA256_RE.fullmatch(str(evidence.get("truthPayloadSha256") or "")):
        reasons.append("TRUTH_PAYLOAD_SHA256_INVALID")
    if evidence.get("unresolvedTruthConflict") is not False:
        reasons.append("UNRESOLVED_TRUTH_CONFLICT")
    scope = evidence.get("inventoryScope")
    if not isinstance(scope, Mapping) or "complete" not in scope:
        reasons.append("INVENTORY_SCOPE_INVALID")
    elif set(scope.keys()) - {"complete"}:
        reasons.append("UNKNOWN_FIELD_inventoryScope")
    ledger = evidence.get("itemLedger")
    if not isinstance(ledger, Mapping):
        reasons.append("ITEM_LEDGER_MISSING")
    else:
        reasons.extend(_unknown_keys(ledger, frozenset({"verified", "deduplicated", "sha256"})))
        if not isinstance(ledger.get("verified"), bool) or not isinstance(ledger.get("deduplicated"), bool):
            reasons.append("ITEM_LEDGER_FLAGS_INVALID")
        digest = ledger.get("sha256")
        if digest is not None and not SHA256_RE.fullmatch(str(digest)):
            reasons.append("ITEM_LEDGER_SHA256_INVALID")


def validate_settlement_evidence_original_v2(item: Any) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if not isinstance(item, Mapping):
        return False, ["ORIGINAL_NOT_OBJECT"]
    reasons.extend(_unknown_keys(item, ORIGINAL_V2_KEYS | {"evidenceOrigin"}))
    if "evidenceOrigin" in item and item["evidenceOrigin"] not in ("runtime-capture", "user-import"):
        reasons.append("EVIDENCE_ORIGIN_INVALID")
    missing = [key for key in ORIGINAL_V2_KEYS if key not in item]
    if missing:
        reasons.extend(f"ORIGINAL_FIELD_MISSING_{key}" for key in missing)
    if item.get("schemaVersion") != ORIGINAL_V2:
        reasons.append("ORIGINAL_SCHEMA_VERSION_INVALID")
    if not str(item.get("evidenceId") or "").strip():
        reasons.append("EVIDENCE_ID_MISSING")
    if not RECORD_KEY_RE.fullmatch(str(item.get("recordStableKey") or "")):
        reasons.append("RECORD_STABLE_KEY_INVALID")
    if item.get("kind") not in ("main-settlement", "warehouse-supplement", "warehouse-segment", "manual-game"):
        reasons.append("KIND_INVALID")
    if not str(item.get("capturedAt") or "").strip():
        reasons.append("CAPTURED_AT_MISSING")
    if item.get("storageMode") != "file":
        reasons.append("STORAGE_MODE_INVALID")
    relative = str(item.get("relativePath") or "")
    if relative.startswith("/") or relative.startswith("\\") or ":" in relative or ".." in relative:
        reasons.append("RELATIVE_PATH_TRAVERSAL")
    elif not RELATIVE_PATH_RE.fullmatch(relative):
        reasons.append("RELATIVE_PATH_INVALID")
    if not SHA256_RE.fullmatch(str(item.get("sha256") or "")):
        reasons.append("ORIGINAL_SHA256_INVALID")
    byte_size = item.get("byteSize")
    if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size <= 0:
        reasons.append("BYTE_SIZE_INVALID")
    if item.get("mimeType") not in ("image/png", "image/jpeg"):
        reasons.append("MIME_TYPE_INVALID")
    if not isinstance(item.get("width"), int) or item.get("width") < 1:
        reasons.append("WIDTH_INVALID")
    if not isinstance(item.get("height"), int) or item.get("height") < 1:
        reasons.append("HEIGHT_INVALID")
    if item.get("coverageMode") not in ("viewport-segment", "unspecified"):
        reasons.append("COVERAGE_MODE_INVALID")
    if item.get("coverageStatus") == "COMPLETE":
        reasons.append("COVERAGE_STATUS_COMPLETE_FORBIDDEN")
    elif item.get("coverageStatus") not in ("PARTIAL", "COVERAGE_UNPROVEN"):
        reasons.append("COVERAGE_STATUS_INVALID")
    return len(reasons) == 0, reasons


def validate_truth_evidence_contract(evidence: Any) -> Tuple[bool, List[str], Optional[str]]:
    """Return (ok, reasons, version). A document never validates as both v1 and v2."""
    if not isinstance(evidence, Mapping):
        return False, ["TRUTH_EVIDENCE_NOT_OBJECT"], None
    version = classify_truth_evidence_version(evidence)
    if version == TRUTH_EVIDENCE_V1:
        reasons = _unknown_keys(evidence, V1_KEYS)
        _validate_shared_truth_fields(evidence, reasons)
        return len(reasons) == 0, reasons, TRUTH_EVIDENCE_V1
    if version == TRUTH_EVIDENCE_V2:
        reasons = _unknown_keys(evidence, V2_KEYS)
        _validate_shared_truth_fields(evidence, reasons)
        originals = evidence.get("fileOriginals")
        if not isinstance(originals, list) or not originals:
            reasons.append("FILE_ORIGINALS_MISSING")
        else:
            for item in originals:
                ok, item_reasons = validate_settlement_evidence_original_v2(item)
                if not ok:
                    reasons.extend(item_reasons)
        return len(reasons) == 0, reasons, TRUTH_EVIDENCE_V2
    return False, ["TRUTH_EVIDENCE_CONTRACT_VERSION_INVALID"], None


def matches_truth_evidence_versions(evidence: Any) -> List[str]:
    """Used to prove v1/v2 oneOf never double-matches."""
    hits: List[str] = []
    ok, _, version = validate_truth_evidence_contract(evidence)
    if ok and version:
        hits.append(version)
    return hits
