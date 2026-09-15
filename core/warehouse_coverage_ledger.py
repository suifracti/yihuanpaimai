"""Fail-closed warehouse-segment coverage ledger.

Does not capture, scroll, OCR, or write History. Completeness is never inferred
from segment count, expected grid size, or “looks near the bottom”.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from settlement_truth_evidence_contract import (
    RECORD_KEY_RE,
    validate_settlement_evidence_original_v2,
)

SCHEMA_VERSION = "warehouse-coverage-ledger.v1"
KIND_WAREHOUSE_SEGMENT = "warehouse-segment"

STATUS_UNPROVEN = "COVERAGE_UNPROVEN"
STATUS_PARTIAL = "PARTIAL"
STATUS_COMPLETE = "COMPLETE"

REASON_COMPLETE = "COMPLETE"
REASON_USER_STOP = "USER_STOP"
REASON_TIMEOUT = "TIMEOUT"
REASON_WINDOW_LOST = "WINDOW_LOST"
REASON_MISSING_TOP = "MISSING_TOP"
REASON_MISSING_BOTTOM = "MISSING_BOTTOM"
REASON_MISSING_OVERLAP = "MISSING_OVERLAP"
REASON_ORDER_CONFLICT = "ORDER_CONFLICT"
REASON_HASH_CONFLICT = "HASH_CONFLICT"
REASON_INCOMPLETE = "INCOMPLETE"

FORCE_PARTIAL_REASONS = frozenset({
    REASON_USER_STOP,
    REASON_TIMEOUT,
    REASON_WINDOW_LOST,
    REASON_MISSING_TOP,
    REASON_MISSING_BOTTOM,
    REASON_MISSING_OVERLAP,
    REASON_ORDER_CONFLICT,
    REASON_HASH_CONFLICT,
    REASON_INCOMPLETE,
})

LEDGER_KEYS = frozenset({
    "schemaVersion",
    "recordStableKey",
    "coverageStatus",
    "finalized",
    "finalizedAt",
    "terminationReason",
    "segments",
    "topEndpoint",
    "bottomEndpoint",
    "overlapProofs",
    "conflicts",
    "gaps",
})


class WarehouseCoverageLedgerError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trusted_endpoint(proof: Optional[Mapping[str, Any]], role: str) -> Optional[Dict[str, Any]]:
    if proof is None:
        return None
    if not isinstance(proof, Mapping):
        raise WarehouseCoverageLedgerError("INVALID_ENDPOINT_PROOF", f"{role} proof must be an object")
    trusted = bool(proof.get("trusted"))
    proof_id = str(proof.get("proofId") or "").strip()
    if trusted and not proof_id:
        raise WarehouseCoverageLedgerError("INVALID_ENDPOINT_PROOF", f"{role} trusted proof requires proofId")
    if extra := set(proof.keys()) - {"trusted", "proofId", "role"}:
        raise WarehouseCoverageLedgerError("UNKNOWN_FIELD", f"unknown endpoint proof field: {sorted(extra)}")
    return {"trusted": trusted, "proofId": proof_id}


def _trusted_overlap(proof: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if proof is None:
        return None
    if not isinstance(proof, Mapping):
        raise WarehouseCoverageLedgerError("INVALID_OVERLAP_PROOF", "overlap proof must be an object")
    extra = set(proof.keys()) - {"trusted", "aligned", "proofId", "previousEvidenceId"}
    if extra:
        raise WarehouseCoverageLedgerError("UNKNOWN_FIELD", f"unknown overlap proof field: {sorted(extra)}")
    return {
        "trusted": bool(proof.get("trusted")),
        "aligned": bool(proof.get("aligned")),
        "proofId": str(proof.get("proofId") or "").strip(),
        "previousEvidenceId": str(proof.get("previousEvidenceId") or "").strip() or None,
    }


class WarehouseCoverageLedger:
    def __init__(self, record_stable_key: str):
        key = str(record_stable_key or "").strip()
        if not RECORD_KEY_RE.fullmatch(key):
            raise WarehouseCoverageLedgerError("INVALID_RECORD_KEY", "recordStableKey rejected")
        self.record_stable_key = key
        self._segments: List[Dict[str, Any]] = []
        self._overlaps: List[Dict[str, Any]] = []
        self._conflicts: List[Dict[str, Any]] = []
        self._gaps: List[Dict[str, Any]] = []
        self._finalized = False
        self._finalized_at: Optional[str] = None
        self._termination_reason: Optional[str] = None
        self._frozen_status: Optional[str] = None
        self._top_proofs: Dict[str, str] = {}
        self._bottom_proofs: Dict[str, str] = {}

    def _reject_if_frozen(self) -> None:
        if self._finalized and self._frozen_status == STATUS_COMPLETE:
            raise WarehouseCoverageLedgerError("LEDGER_IMMUTABLE", "COMPLETE ledger cannot be mutated")
        if self._finalized:
            raise WarehouseCoverageLedgerError("LEDGER_IMMUTABLE", "finalized ledger cannot be mutated")

    def add_segment(
        self,
        file_original: Mapping[str, Any],
        *,
        sequence_index: int,
        top_proof: Optional[Mapping[str, Any]] = None,
        bottom_proof: Optional[Mapping[str, Any]] = None,
        overlap_proof: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._reject_if_frozen()
        if not isinstance(sequence_index, int) or isinstance(sequence_index, bool):
            raise WarehouseCoverageLedgerError("INVALID_SEQUENCE_INDEX", "sequenceIndex must be an integer")

        ok, reasons = validate_settlement_evidence_original_v2(file_original)
        if not ok:
            raise WarehouseCoverageLedgerError("INVALID_FILE_ORIGINAL", ",".join(reasons))
        if file_original.get("kind") != KIND_WAREHOUSE_SEGMENT:
            raise WarehouseCoverageLedgerError("INVALID_KIND", "ledger only accepts warehouse-segment")
        if str(file_original.get("recordStableKey") or "") != self.record_stable_key:
            raise WarehouseCoverageLedgerError("RECORD_KEY_MISMATCH", "segment recordStableKey does not match ledger")
        if file_original.get("coverageStatus") not in (STATUS_PARTIAL, STATUS_UNPROVEN):
            raise WarehouseCoverageLedgerError("INVALID_SEGMENT_COVERAGE", "segment itself cannot be COMPLETE")

        evidence_id = str(file_original["evidenceId"])
        digest = str(file_original["sha256"])
        for existing in self._segments:
            if existing["evidenceId"] == evidence_id:
                if existing["sha256"] != digest:
                    self._conflicts.append({"code": "HASH_CONFLICT", "evidenceId": evidence_id})
                    return self.snapshot()
                return self.snapshot()

        if self._segments:
            previous = self._segments[-1]
            if sequence_index <= previous["sequenceIndex"]:
                self._conflicts.append({"code": "ORDER_CONFLICT", "evidenceId": evidence_id})
                return self.snapshot()

        top = _trusted_endpoint(top_proof, "top")
        bottom = _trusted_endpoint(bottom_proof, "bottom")
        overlap = _trusted_overlap(overlap_proof)

        segment = {
            "evidenceId": evidence_id,
            "sha256": digest,
            "sequenceIndex": sequence_index,
            "coverageStatus": file_original.get("coverageStatus") or STATUS_UNPROVEN,
            "topEndpointTrusted": bool(top and top["trusted"] and top["proofId"]),
            "bottomEndpointTrusted": bool(bottom and bottom["trusted"] and bottom["proofId"]),
            "fileOriginal": dict(file_original),
        }
        self._segments.append(segment)

        if segment["topEndpointTrusted"] and top:
            self._top_proofs[evidence_id] = top["proofId"]
        if segment["bottomEndpointTrusted"] and bottom:
            self._bottom_proofs[evidence_id] = bottom["proofId"]

        if overlap and self._segments[:-1]:
            previous = self._segments[-2]
            expected_prev = overlap.get("previousEvidenceId") or previous["evidenceId"]
            aligned = bool(overlap["trusted"] and overlap["aligned"] and overlap["proofId"])
            if expected_prev != previous["evidenceId"] or not aligned:
                self._gaps.append({
                    "code": "MISSING_OVERLAP",
                    "fromEvidenceId": previous["evidenceId"],
                    "toEvidenceId": evidence_id,
                })
            else:
                self._overlaps.append({
                    "fromEvidenceId": previous["evidenceId"],
                    "toEvidenceId": evidence_id,
                    "trusted": True,
                    "aligned": True,
                    "proofId": overlap["proofId"],
                })
        elif self._segments[:-1]:
            previous = self._segments[-2]
            self._gaps.append({
                "code": "MISSING_OVERLAP",
                "fromEvidenceId": previous["evidenceId"],
                "toEvidenceId": evidence_id,
            })

        return self.snapshot()

    def _top_endpoint(self) -> Optional[Dict[str, Any]]:
        for segment in self._segments:
            proof_id = self._top_proofs.get(segment["evidenceId"])
            if segment["topEndpointTrusted"] and proof_id:
                return {
                    "evidenceId": segment["evidenceId"],
                    "trusted": True,
                    "proofId": proof_id,
                }
        return None

    def _bottom_endpoint(self) -> Optional[Dict[str, Any]]:
        for segment in reversed(self._segments):
            proof_id = self._bottom_proofs.get(segment["evidenceId"])
            if segment["bottomEndpointTrusted"] and proof_id:
                return {
                    "evidenceId": segment["evidenceId"],
                    "trusted": True,
                    "proofId": proof_id,
                }
        return None

    def _path_is_complete(self) -> bool:
        if self._conflicts:
            return False
        if self._gaps:
            return False
        if not self._segments:
            return False
        ordered = sorted(self._segments, key=lambda item: item["sequenceIndex"])
        if [item["sequenceIndex"] for item in ordered] != [item["sequenceIndex"] for item in self._segments]:
            return False
        for previous, current in zip(ordered, ordered[1:]):
            if current["sequenceIndex"] <= previous["sequenceIndex"]:
                return False
            has_overlap = any(
                proof["fromEvidenceId"] == previous["evidenceId"]
                and proof["toEvidenceId"] == current["evidenceId"]
                and proof["trusted"]
                and proof["aligned"]
                for proof in self._overlaps
            )
            if not has_overlap:
                return False
        top = self._top_endpoint()
        bottom = self._bottom_endpoint()
        if not (top and top["trusted"] and bottom and bottom["trusted"]):
            return False
        if ordered[0]["evidenceId"] != top["evidenceId"]:
            return False
        if ordered[-1]["evidenceId"] != bottom["evidenceId"]:
            return False
        return True

    def evaluate(self) -> str:
        if self._finalized and self._frozen_status:
            return self._frozen_status
        if not self._segments:
            return STATUS_UNPROVEN
        return STATUS_PARTIAL

    def finalize(self, termination_reason: str) -> Dict[str, Any]:
        reason = str(termination_reason or "").strip()
        if self._finalized:
            return self.snapshot()
        eligible = self._path_is_complete()
        if reason == REASON_COMPLETE and eligible:
            self._frozen_status = STATUS_COMPLETE
            self._termination_reason = REASON_COMPLETE
        else:
            self._frozen_status = STATUS_PARTIAL if self._segments else STATUS_UNPROVEN
            if reason == REASON_COMPLETE:
                if self._conflicts:
                    self._termination_reason = REASON_HASH_CONFLICT if any(
                        item["code"] == "HASH_CONFLICT" for item in self._conflicts
                    ) else REASON_ORDER_CONFLICT
                elif not self._top_endpoint():
                    self._termination_reason = REASON_MISSING_TOP
                elif not self._bottom_endpoint():
                    self._termination_reason = REASON_MISSING_BOTTOM
                elif self._gaps:
                    self._termination_reason = REASON_MISSING_OVERLAP
                else:
                    self._termination_reason = REASON_INCOMPLETE
            elif reason in FORCE_PARTIAL_REASONS:
                self._termination_reason = reason
            else:
                raise WarehouseCoverageLedgerError("INVALID_TERMINATION_REASON", "unknown terminationReason")
            if self._frozen_status == STATUS_COMPLETE:
                self._frozen_status = STATUS_PARTIAL
        self._finalized = True
        self._finalized_at = _utc_now()
        return self.snapshot()

    def snapshot(self) -> Dict[str, Any]:
        status = self.evaluate()
        if status == STATUS_COMPLETE and not self._finalized:
            status = STATUS_PARTIAL
        document = {
            "schemaVersion": SCHEMA_VERSION,
            "recordStableKey": self.record_stable_key,
            "coverageStatus": status,
            "finalized": self._finalized,
            "finalizedAt": self._finalized_at,
            "terminationReason": self._termination_reason,
            "segments": [dict(item) for item in self._segments],
            "topEndpoint": self._top_endpoint(),
            "bottomEndpoint": self._bottom_endpoint(),
            "overlapProofs": [dict(item) for item in self._overlaps],
            "conflicts": [dict(item) for item in self._conflicts],
            "gaps": [dict(item) for item in self._gaps],
        }
        extra = set(document.keys()) - LEDGER_KEYS
        if extra:
            raise WarehouseCoverageLedgerError("UNKNOWN_FIELD", str(sorted(extra)))
        if document["coverageStatus"] == STATUS_COMPLETE and (
            not document["finalized"] or document["terminationReason"] != REASON_COMPLETE
        ):
            document["coverageStatus"] = STATUS_PARTIAL
        return document


def validate_warehouse_coverage_ledger(document: Any) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    if not isinstance(document, Mapping):
        return False, ["LEDGER_NOT_OBJECT"]
    extra = [key for key in document.keys() if key not in LEDGER_KEYS]
    reasons.extend(f"UNKNOWN_FIELD_{key}" for key in extra)
    if document.get("schemaVersion") != SCHEMA_VERSION:
        reasons.append("SCHEMA_VERSION_INVALID")
    if not RECORD_KEY_RE.fullmatch(str(document.get("recordStableKey") or "")):
        reasons.append("RECORD_STABLE_KEY_INVALID")
    status = document.get("coverageStatus")
    if status not in (STATUS_UNPROVEN, STATUS_PARTIAL, STATUS_COMPLETE):
        reasons.append("COVERAGE_STATUS_INVALID")
    if status == STATUS_COMPLETE and not document.get("finalized"):
        reasons.append("COMPLETE_WITHOUT_FINALIZE")
    return len(reasons) == 0, reasons
