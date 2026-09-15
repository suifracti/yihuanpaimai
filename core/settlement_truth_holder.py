# -*- coding: utf-8 -*-
"""Authoritative Runtime Holder and Validator for Settlement Truth Evidence v1.

Strictly bound to active matchId. Cleared on match reset, match init,
lobby egress, and immediately after archive.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from evidence_storage import verify_evidence_file

TRUTH_EVIDENCE_SCHEMA_VERSION = "settlement-truth-evidence.v1"
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_sha256(val: Any) -> bool:
    return isinstance(val, str) and bool(_SHA256_HEX_RE.match(val.strip().lower()))


def _positive_finite(val: Any) -> bool:
    return (
        isinstance(val, (int, float))
        and not isinstance(val, bool)
        and math.isfinite(val)
        and val > 0
    )


def _parse_aware_iso(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt


def build_truth_payload_sha256(
    *, match_id: str, actual_total: float, settlement_observed_at: str, truth_source: str
) -> str:
    """Compute canonical SHA-256 digest of truth payload."""
    payload = {
        "actualTotal": actual_total,
        "matchId": match_id,
        "settlementObservedAt": settlement_observed_at,
        "truthSource": truth_source,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_settlement_truth_evidence_v1(
    *,
    match_id: str,
    actual_total: float,
    settlement_observed_at: str,
    truth_source: str,
    truth_confidence: str = "medium",
    evidence_uri: Optional[str] = None,
    evidence_sha256: Optional[str] = None,
    verification_method: str = "vision_multiframe_stabilization_v1",
    verification_version: str = "settlement-stabilization.v1",
    verifier_type: str = "deterministic_verifier",
    verifier_id: str = "rapidocr_stabilizer_v1",
    unresolved_conflict: bool = False,
    inventory_scope_complete: Optional[bool] = None,
    ledger_verified: bool = False,
    ledger_deduplicated: bool = False,
    ledger_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a contract-compliant Settlement Truth Evidence v1 dictionary."""
    evidence_refs: List[Dict[str, str]] = []
    if evidence_uri and evidence_sha256:
        evidence_refs.append({"uri": str(evidence_uri).strip(), "sha256": str(evidence_sha256).strip().lower()})

    payload_hash = build_truth_payload_sha256(
        match_id=match_id,
        actual_total=actual_total,
        settlement_observed_at=settlement_observed_at,
        truth_source=truth_source,
    )

    return {
        "schemaVersion": TRUTH_EVIDENCE_SCHEMA_VERSION,
        "matchId": match_id,
        "actualTotal": actual_total,
        "settlementObservedAt": settlement_observed_at,
        "truthSource": truth_source,
        "truthConfidence": truth_confidence,
        "evidenceReferences": evidence_refs,
        "verification": {
            "method": verification_method,
            "version": verification_version,
            "verifier": {
                "type": verifier_type,
                "id": verifier_id,
            },
        },
        "truthPayloadSha256": payload_hash,
        "unresolvedTruthConflict": unresolved_conflict,
        "inventoryScope": {
            "complete": inventory_scope_complete,
        },
        "itemLedger": {
            "verified": ledger_verified,
            "deduplicated": ledger_deduplicated,
            "sha256": ledger_sha256,
        },
    }


def validate_settlement_truth_evidence(
    evidence: Any,
    *,
    match_id: Optional[str] = None,
    data_dir: Optional[Union[str, Path]] = None,
    check_disk_bytes: bool = True,
) -> Tuple[bool, List[str]]:
    """Strictly validate a Settlement Truth Evidence v1 structure against the contract.

    Returns:
        tuple[is_valid: bool, reasons: list[str]]
    """
    reasons: List[str] = []
    if not isinstance(evidence, Mapping):
        return False, ["TRUTH_EVIDENCE_NOT_MAPPING"]

    if evidence.get("schemaVersion") != TRUTH_EVIDENCE_SCHEMA_VERSION:
        reasons.append("TRUTH_EVIDENCE_CONTRACT_VERSION_INVALID")

    ev_match_id = str(evidence.get("matchId") or "").strip()
    if not ev_match_id:
        reasons.append("TRUTH_MATCH_ID_MISSING")
    elif match_id is not None and ev_match_id != str(match_id).strip():
        reasons.append("TRUTH_MATCH_ID_MISMATCH")

    actual_total = evidence.get("actualTotal")
    if not _positive_finite(actual_total):
        reasons.append("ACTUAL_TOTAL_INVALID")

    truth_source = str(evidence.get("truthSource") or "").strip()
    if not truth_source:
        reasons.append("TRUTH_SOURCE_MISSING")

    truth_conf = str(evidence.get("truthConfidence") or "").strip().lower()
    if truth_conf not in ("high", "medium", "low", "unverified"):
        reasons.append("TRUTH_CONFIDENCE_INVALID")

    observed_raw = evidence.get("settlementObservedAt")
    if not observed_raw or _parse_aware_iso(observed_raw) is None:
        reasons.append("SETTLEMENT_OBSERVED_AT_INVALID")

    references = evidence.get("evidenceReferences")
    if not isinstance(references, list) or not references:
        reasons.append("TRUTH_EVIDENCE_REFERENCE_MISSING")
    else:
        for ref in references:
            if not isinstance(ref, Mapping) or not str(ref.get("uri") or "").strip():
                reasons.append("TRUTH_EVIDENCE_REFERENCE_INVALID")
                continue
            uri = str(ref.get("uri")).strip()
            digest = str(ref.get("sha256") or "").strip().lower()
            if not _is_sha256(digest):
                reasons.append("TRUTH_EVIDENCE_HASH_INVALID")
                continue
            if check_disk_bytes and uri.startswith("evidence/"):
                if not verify_evidence_file(uri, digest, data_dir=data_dir):
                    reasons.append("TRUTH_EVIDENCE_DISK_FILE_CORRUPTED_OR_MISSING")

    verification = evidence.get("verification")
    if not isinstance(verification, Mapping):
        reasons.append("TRUTH_VERIFICATION_MISSING")
    else:
        if not str(verification.get("method") or "").strip():
            reasons.append("TRUTH_VERIFICATION_METHOD_MISSING")
        if not str(verification.get("version") or "").strip():
            reasons.append("TRUTH_VERIFICATION_VERSION_MISSING")
        verifier = verification.get("verifier")
        if (
            not isinstance(verifier, Mapping)
            or verifier.get("type") not in ("deterministic_verifier", "reviewer")
            or not str(verifier.get("id") or "").strip()
        ):
            reasons.append("TRUTH_VERIFIER_IDENTITY_MISSING")

    if evidence.get("unresolvedTruthConflict") is not False:
        reasons.append("UNRESOLVED_TRUTH_CONFLICT")

    payload_digest = str(evidence.get("truthPayloadSha256") or "").strip().lower()
    if not _is_sha256(payload_digest):
        reasons.append("TRUTH_PAYLOAD_HASH_INVALID")
    elif observed_raw and actual_total and ev_match_id and truth_source:
        expected = build_truth_payload_sha256(
            match_id=ev_match_id,
            actual_total=actual_total,
            settlement_observed_at=str(observed_raw),
            truth_source=truth_source,
        )
        if payload_digest != expected:
            reasons.append("TRUTH_PAYLOAD_HASH_MISMATCH")

    return len(reasons) == 0, reasons


class ActiveSettlementTruthHolder:
    """Authoritative singleton holding exactly one match-bound Settlement Truth Evidence."""

    def __init__(self) -> None:
        self._active_match_id: Optional[str] = None
        self._truth_evidence: Optional[Dict[str, Any]] = None

    def set_truth(self, match_id: str, truth_evidence: Dict[str, Any]) -> None:
        """Register a validated Truth Evidence object bound strictly to match_id."""
        clean_id = str(match_id or "").strip()
        if not clean_id or not isinstance(truth_evidence, dict):
            return
        is_valid, reasons = validate_settlement_truth_evidence(truth_evidence, match_id=clean_id, check_disk_bytes=False)
        if not is_valid:
            print(f"⚠️ [SettlementTruthHolder] Rejecting invalid truth evidence for {clean_id}: {reasons}")
            return
        self._active_match_id = clean_id
        self._truth_evidence = dict(truth_evidence)

    def get_truth_for_match(self, match_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve truth evidence only if match_id matches the active match exactly."""
        clean_id = str(match_id or "").strip()
        if clean_id and clean_id == self._active_match_id and self._truth_evidence is not None:
            return dict(self._truth_evidence)
        return None

    def clear(self) -> None:
        """Clear active truth evidence and active match binding."""
        self._active_match_id = None
        self._truth_evidence = None


ACTIVE_SETTLEMENT_TRUTH_HOLDER = ActiveSettlementTruthHolder()
