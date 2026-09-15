# -*- coding: utf-8 -*-
"""High-Confidence Settlement Truth Review v1 & Tier 3 Projection.

Provides:
1. Canonical builder and validator for Settlement Truth Review v1 artifacts.
2. Content-addressed Review ID and deterministic reviewPayloadSha256 calculation.
3. ReviewStoreManager for atomic, immutable sidecar persistence (<data-root>/reviews/settlement/<matchId>/<reviewId>.json).
4. Pure functional Tier 3 Truth Evidence projection from (Tier 1 Evidence + Review Artifact).
5. Strict terminal semantics: confirmed/corrected -> Tier 3 candidate; rejected -> no Tier 3 candidate.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_CORE_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _CORE_DIR.parent
_APP_DIR = _ROOT_DIR / "app"
for _p in (str(_CORE_DIR), str(_APP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from evidence_storage import get_canonical_data_dir, verify_evidence_file
from runtime_revision import get_code_revision
from settlement_truth_holder import (
    build_truth_payload_sha256,
    validate_settlement_truth_evidence,
)

SETTLEMENT_TRUTH_REVIEW_SCHEMA_VERSION = "settlement-truth-review.v1"
SETTLEMENT_TRUTH_REVIEW_METHOD = "human_screenshot_audit_v1"
SETTLEMENT_TRUTH_REVIEW_VERSION = "1.0"


class ReviewError(Exception):
    """Base error for settlement truth review operations."""


class ReviewConflictError(ReviewError):
    """Raised when attempting to overwrite or duplicate a terminal review."""


def _sha256_canonical_json(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_review_payload_sha256(
    match_id: str,
    action: str,
    original_actual_total: float | int,
    reviewed_actual_total: Optional[float | int],
    source_truth_payload_sha256: str,
    evidence_sha256: str,
    reviewer_id: str,
    reviewed_at: str,
    review_method: str = SETTLEMENT_TRUTH_REVIEW_METHOD,
    review_version: str = SETTLEMENT_TRUTH_REVIEW_VERSION,
    code_revision: Optional[str] = None,
) -> str:
    code_rev = str(code_revision or get_code_revision()).strip()
    payload = {
        "action": action,
        "codeRevision": code_rev,
        "evidenceSha256": evidence_sha256,
        "matchId": str(match_id).strip(),
        "originalActualTotal": float(original_actual_total),
        "reviewedActualTotal": float(reviewed_actual_total) if reviewed_actual_total is not None else None,
        "reviewedAt": str(reviewed_at).strip(),
        "reviewer": {
            "id": str(reviewer_id).strip(),
            "type": "reviewer",
        },
        "reviewMethod": review_method,
        "reviewVersion": review_version,
        "sourceTruthPayloadSha256": str(source_truth_payload_sha256).strip(),
    }
    return _sha256_canonical_json(payload)


def build_settlement_truth_review_v1(
    match_id: str,
    action: str,
    original_actual_total: float | int,
    reviewed_actual_total: Optional[float | int],
    source_truth_payload_sha256: str,
    evidence_uri: str,
    evidence_sha256: str,
    reviewer_id: str,
    reviewed_at: str,
    review_method: str = SETTLEMENT_TRUTH_REVIEW_METHOD,
    review_version: str = SETTLEMENT_TRUTH_REVIEW_VERSION,
    code_revision: Optional[str] = None,
) -> Dict[str, Any]:
    if action not in {"confirmed", "corrected", "rejected"}:
        raise ValueError(f"Invalid review action: {action}. Must be confirmed, corrected, or rejected.")

    mid = str(match_id).strip()
    rev_id_str = str(reviewer_id).strip()
    if not rev_id_str:
        raise ValueError("reviewer_id must be a non-empty stable identifier.")

    if action == "confirmed":
        if reviewed_actual_total is not None and float(reviewed_actual_total) != float(original_actual_total):
            raise ValueError("For confirmed action, reviewed_actual_total must match original_actual_total.")
        final_reviewed_total = float(original_actual_total)
    elif action == "corrected":
        if reviewed_actual_total is None or float(reviewed_actual_total) <= 0:
            raise ValueError("For corrected action, reviewed_actual_total must be a positive number.")
        final_reviewed_total = float(reviewed_actual_total)
    else:  # rejected
        final_reviewed_total = None

    code_rev = str(code_revision or get_code_revision()).strip()
    payload_sha256 = build_review_payload_sha256(
        match_id=mid,
        action=action,
        original_actual_total=original_actual_total,
        reviewed_actual_total=final_reviewed_total,
        source_truth_payload_sha256=source_truth_payload_sha256,
        evidence_sha256=evidence_sha256,
        reviewer_id=rev_id_str,
        reviewed_at=reviewed_at,
        review_method=review_method,
        review_version=review_version,
        code_revision=code_rev,
    )

    # Content-addressed review ID based on the payload hash
    review_id = payload_sha256

    return {
        "schemaVersion": SETTLEMENT_TRUTH_REVIEW_SCHEMA_VERSION,
        "reviewId": review_id,
        "matchId": mid,
        "action": action,
        "originalActualTotal": float(original_actual_total),
        "reviewedActualTotal": final_reviewed_total,
        "sourceTruthPayloadSha256": str(source_truth_payload_sha256).strip(),
        "evidenceUri": str(evidence_uri).strip(),
        "evidenceSha256": str(evidence_sha256).strip(),
        "reviewer": {
            "type": "reviewer",
            "id": rev_id_str,
        },
        "reviewedAt": str(reviewed_at).strip(),
        "reviewMethod": review_method,
        "reviewVersion": review_version,
        "codeRevision": code_rev,
        "reviewPayloadSha256": payload_sha256,
    }


def validate_settlement_truth_review(
    artifact: Any,
    match_id: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if not isinstance(artifact, dict):
        return False, ["REVIEW_ARTIFACT_NOT_DICT"]

    if artifact.get("schemaVersion") != SETTLEMENT_TRUTH_REVIEW_SCHEMA_VERSION:
        reasons.append("REVIEW_SCHEMA_VERSION_INVALID")

    rid = str(artifact.get("reviewId") or "").strip()
    if not rid or len(rid) != 64:
        reasons.append("REVIEW_ID_INVALID")

    mid = str(artifact.get("matchId") or "").strip()
    if not mid:
        reasons.append("REVIEW_MATCH_ID_MISSING")
    elif match_id and mid != str(match_id).strip():
        reasons.append("REVIEW_MATCH_ID_MISMATCH")

    action = artifact.get("action")
    if action not in {"confirmed", "corrected", "rejected"}:
        reasons.append("REVIEW_ACTION_INVALID")

    orig_total = artifact.get("originalActualTotal")
    if orig_total is None or not isinstance(orig_total, (int, float)) or orig_total <= 0:
        reasons.append("REVIEW_ORIGINAL_ACTUAL_TOTAL_INVALID")

    reviewed_total = artifact.get("reviewedActualTotal")
    if action in {"confirmed", "corrected"}:
        if reviewed_total is None or not isinstance(reviewed_total, (int, float)) or reviewed_total <= 0:
            reasons.append("REVIEW_REVIEWED_ACTUAL_TOTAL_INVALID")
        if action == "confirmed" and orig_total is not None and reviewed_total is not None:
            if float(orig_total) != float(reviewed_total):
                reasons.append("REVIEW_CONFIRMED_TOTAL_MISMATCH")
    else:  # rejected
        if reviewed_total is not None:
            reasons.append("REVIEW_REJECTED_MUST_HAVE_NULL_TOTAL")

    source_hash = str(artifact.get("sourceTruthPayloadSha256") or "").strip()
    if not source_hash or len(source_hash) != 64:
        reasons.append("REVIEW_SOURCE_HASH_INVALID")

    ev_uri = str(artifact.get("evidenceUri") or "").strip()
    if not ev_uri:
        reasons.append("REVIEW_EVIDENCE_URI_MISSING")

    ev_hash = str(artifact.get("evidenceSha256") or "").strip()
    if not ev_hash or len(ev_hash) != 64:
        reasons.append("REVIEW_EVIDENCE_HASH_INVALID")

    reviewer = artifact.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("type") != "reviewer" or not str(reviewer.get("id") or "").strip():
        reasons.append("REVIEW_REVIEWER_INVALID")

    reviewed_at = artifact.get("reviewedAt")
    if not isinstance(reviewed_at, str) or not reviewed_at.strip():
        reasons.append("REVIEW_REVIEWED_AT_MISSING")
    else:
        try:
            datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except Exception:
            reasons.append("REVIEW_REVIEWED_AT_INVALID")

    if artifact.get("reviewMethod") != SETTLEMENT_TRUTH_REVIEW_METHOD:
        reasons.append("REVIEW_METHOD_INVALID")

    code_rev = str(artifact.get("codeRevision") or "").strip()
    if not code_rev:
        reasons.append("REVIEW_CODE_REVISION_MISSING")

    payload_hash = str(artifact.get("reviewPayloadSha256") or "").strip()
    if not payload_hash or len(payload_hash) != 64:
        reasons.append("REVIEW_PAYLOAD_HASH_INVALID")
    elif orig_total and reviewer and isinstance(reviewer, dict):
        expected_hash = build_review_payload_sha256(
            match_id=mid,
            action=action,
            original_actual_total=orig_total,
            reviewed_actual_total=reviewed_total,
            source_truth_payload_sha256=source_hash,
            evidence_sha256=ev_hash,
            reviewer_id=str(reviewer.get("id") or ""),
            reviewed_at=str(reviewed_at or ""),
            review_method=str(artifact.get("reviewMethod") or ""),
            review_version=str(artifact.get("reviewVersion") or ""),
            code_revision=code_rev,
        )
        if payload_hash != expected_hash:
            reasons.append("REVIEW_PAYLOAD_HASH_MISMATCH")
        if rid != payload_hash:
            reasons.append("REVIEW_ID_NOT_CONTENT_ADDRESSED")

    return len(reasons) == 0, reasons


def project_tier3_truth_evidence(
    tier1_evidence: Dict[str, Any],
    review_artifact: Dict[str, Any],
    data_dir: Optional[Path | str] = None,
) -> Optional[Dict[str, Any]]:
    """Pure functional projection of Tier 3 Truth Evidence from (Tier 1 Evidence + Review Artifact).

    Returns None if the review action is 'rejected' or validation fails.
    """
    if not isinstance(tier1_evidence, dict) or not isinstance(review_artifact, dict):
        return None

    # Review artifact must be valid
    is_rev_valid, _ = validate_settlement_truth_review(review_artifact, match_id=tier1_evidence.get("matchId"))
    if not is_rev_valid:
        return None

    action = review_artifact.get("action")
    if action == "rejected":
        # Rejected reviews explicitly do NOT project a Tier 3 Truth candidate
        return None

    if action not in {"confirmed", "corrected"}:
        return None

    # Must match sourceTruthPayloadSha256
    source_sha = tier1_evidence.get("truthPayloadSha256")
    if source_sha != review_artifact.get("sourceTruthPayloadSha256"):
        return None

    match_id = str(tier1_evidence.get("matchId") or "").strip()
    reviewed_total = review_artifact.get("reviewedActualTotal")
    if reviewed_total is None or reviewed_total <= 0:
        return None

    # settlementObservedAt strictly inherits the Tier 1 capture timestamp
    observed_at = str(tier1_evidence.get("settlementObservedAt") or "").strip()
    if not observed_at:
        return None

    truth_source = "manual_confirmed_against_screenshot"
    truth_confidence = "high"

    # Rebuild truthPayloadSha256 for Tier 3
    tier3_payload_sha256 = build_truth_payload_sha256(
        match_id=match_id,
        actual_total=reviewed_total,
        settlement_observed_at=observed_at,
        truth_source=truth_source,
    )

    reviewer_id = str(review_artifact.get("reviewer", {}).get("id") or "").strip()

    tier3_truth = {
        "schemaVersion": "settlement-truth-evidence.v1",
        "matchId": match_id,
        "actualTotal": float(reviewed_total),
        "settlementObservedAt": observed_at,
        "truthSource": truth_source,
        "truthConfidence": truth_confidence,
        "evidenceReferences": list(tier1_evidence.get("evidenceReferences") or []),
        "verification": {
            "method": SETTLEMENT_TRUTH_REVIEW_METHOD,
            "version": str(review_artifact.get("reviewVersion") or SETTLEMENT_TRUTH_REVIEW_VERSION),
            "verifier": {
                "type": "reviewer",
                "id": reviewer_id,
            },
        },
        "truthPayloadSha256": tier3_payload_sha256,
        "unresolvedTruthConflict": False,
        "inventoryScope": dict(tier1_evidence.get("inventoryScope") or {"complete": None}),
        "itemLedger": dict(tier1_evidence.get("itemLedger") or {"verified": False, "deduplicated": False, "sha256": None}),
    }

    # Validate against frozen Truth Evidence validator
    is_valid, _ = validate_settlement_truth_evidence(tier3_truth, match_id=match_id, data_dir=data_dir, check_disk_bytes=False)
    if not is_valid:
        return None

    return tier3_truth


class ReviewStoreManager:
    """Manages reading and atomic writing of Settlement Truth Review artifacts in sidecar store."""

    def __init__(self, data_root: Optional[Path | str] = None):
        self.data_root = Path(data_root).resolve() if data_root else Path(get_canonical_data_dir()).resolve()

    def get_review_dir(self, match_id: str) -> Path:
        return self.data_root / "reviews" / "settlement" / match_id

    def get_terminal_review(self, match_id: str, source_truth_payload_sha256: str) -> Optional[Dict[str, Any]]:
        review_dir = self.get_review_dir(match_id)
        if not review_dir.is_dir():
            return None

        target_source_hash = str(source_truth_payload_sha256).strip()
        for p in sorted(review_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("sourceTruthPayloadSha256") == target_source_hash:
                    is_valid, _ = validate_settlement_truth_review(data, match_id=match_id)
                    if is_valid:
                        return data
            except Exception:
                continue
        return None

    def save_review_artifact(self, review_artifact: Dict[str, Any]) -> Path:
        is_valid, reasons = validate_settlement_truth_review(review_artifact)
        if not is_valid:
            raise ReviewError(f"Cannot save invalid review artifact: {reasons}")

        match_id = review_artifact["matchId"]
        source_hash = review_artifact["sourceTruthPayloadSha256"]
        review_id = review_artifact["reviewId"]

        # Terminal check: fail closed if a review for this source Tier 1 hash already exists
        existing = self.get_terminal_review(match_id, source_hash)
        if existing is not None:
            raise ReviewConflictError(
                f"Terminal review already exists for match '{match_id}' and source truth hash '{source_hash}' "
                f"(existing reviewId={existing.get('reviewId')}). Overwrite is strictly forbidden."
            )

        review_dir = self.get_review_dir(match_id)
        review_dir.mkdir(parents=True, exist_ok=True)

        target_file = review_dir / f"{review_id}.json"
        if target_file.exists():
            raise ReviewConflictError(f"Target review artifact file already exists: {target_file}")

        tmp_file = review_dir / f"{review_id}.tmp_{os.getpid()}"
        content_str = json.dumps(review_artifact, ensure_ascii=False, indent=2)

        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(content_str)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(str(tmp_file), str(target_file))
        except Exception:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass
            raise

        return target_file
