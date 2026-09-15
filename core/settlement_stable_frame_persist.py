"""Persist a confirmed settlement frame into Evidence Store v2.

This adapter is fail-soft: store errors never invent descriptors or block
settlement recognition. It does not write History.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

import cv2
import numpy as np
from settlement_grid import settlement_grid_bounds

from settlement_evidence_store_v2 import (
    COVERAGE_UNPROVEN,
    KIND_MAIN,
    SettlementEvidenceStoreError,
    SettlementEvidenceStoreV2,
    detect_image_type,
    validate_record_stable_key,
)

STATUS_SAVED = "SAVED"
STATUS_IDEMPOTENT = "IDEMPOTENT"
STATUS_SKIPPED_NOT_SETTLEMENT = "SKIPPED_NOT_SETTLEMENT"
STATUS_MISSING_STABLE_KEY = "MISSING_STABLE_KEY"
STATUS_EVIDENCE_PERSIST_FAILED = "EVIDENCE_PERSIST_FAILED"


def resolve_record_stable_key(context: Optional[Dict[str, Any]]) -> Optional[str]:
    ctx = context or {}
    raw = str(
        ctx.get("recordStableKey")
        or ctx.get("id")
        or ctx.get("matchId")
        or ctx.get("gameId")
        or ""
    ).strip()
    if not raw:
        return None
    try:
        return validate_record_stable_key(raw)
    except SettlementEvidenceStoreError:
        return None


def encode_settlement_original(frame: Any) -> bytes:
    if isinstance(frame, (bytes, bytearray)):
        payload = bytes(frame)
        if detect_image_type(payload) is None:
            raise SettlementEvidenceStoreError("INVALID_IMAGE", "encoded bytes are not PNG or JPEG")
        return payload
    if not isinstance(frame, np.ndarray) or frame.size == 0:
        raise SettlementEvidenceStoreError("INVALID_IMAGE", "settlement frame is empty")
    ok, buf = cv2.imencode(".png", frame)
    if not ok or buf is None:
        raise SettlementEvidenceStoreError("INVALID_IMAGE", "lossless PNG encode failed")
    return buf.tobytes()


def derive_settlement_grouping_and_identity_evidence(
    *,
    frame: np.ndarray,
    parent_descriptor: Dict[str, Any],
    store: Optional[SettlementEvidenceStoreV2] = None,
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    """Derive physical grouping hypotheses and catalog identity evidence for a new settlement stable frame (4D2D1M-C3.6A).

    Reuses existing:
    - SettlementItemRecognizer
    - C3.2H physical grouping hypotheses
    - C3.2I identity evidence resolver

    Binds parent raw evidence provenance to every hypothesis and identity evidence.
    Returns (grouping_hypotheses, identity_evidences).
    """
    if not isinstance(frame, np.ndarray) or frame.size == 0:
        return [], []

    from settlement_catalog_candidates import get_global_catalog_candidate_resolver
    from settlement_item_recognizer import SettlementItemRecognizer

    rec = SettlementItemRecognizer()
    ledger = rec.parse_settlement_ledger(frame)
    grouping_hypotheses = ledger.get("physicalGroupingHypotheses") or []

    h, w = frame.shape[:2]
    gx1, gy1, gx2, gy2 = settlement_grid_bounds(frame)
    crop = frame[gy1:gy2, gx1:gx2] if gx2 > gx1 and gy2 > gy1 else frame

    resolver = get_global_catalog_candidate_resolver()
    identity_evidences = resolver.resolve_identity_evidence_for_hypotheses(
        grouping_hypotheses,
        crop_image=crop,
        templates=rec.templates,
    )

    record_key = parent_descriptor.get("recordStableKey")
    parent_ev_id = parent_descriptor.get("evidenceId")
    parent_sha = parent_descriptor.get("sha256")

    for ev, hyp in zip(identity_evidences, grouping_hypotheses):
        ev["recordStableKey"] = record_key
        ev["parentEvidenceId"] = parent_ev_id
        ev["parentSha256"] = parent_sha
        hyp["recordStableKey"] = record_key
        hyp["parentEvidenceId"] = parent_ev_id
        hyp["parentSha256"] = parent_sha
        bbox = hyp.get("bbox")
        if crop is not None and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            bx, by, bw, bh = bbox
            if by + bh <= crop.shape[0] and bx + bw <= crop.shape[1] and bw > 0 and bh > 0:
                item_roi = crop[by:by+bh, bx:bx+bw]
                ok_enc, buf = cv2.imencode(".png", item_roi)
                if ok_enc and buf is not None:
                    import base64
                    ev["cropDataUrl"] = "data:image/png;base64," + base64.b64encode(buf).decode("ascii")

    return grouping_hypotheses, identity_evidences


def persist_stable_settlement_original(
    *,
    store: Optional[SettlementEvidenceStoreV2],
    is_settlement: bool,
    record_stable_key: Optional[str],
    frame: Any,
    captured_at: Optional[str] = None,
    existing_descriptor: Optional[Dict[str, Any]] = None,
    extract_proposals: bool = True,
) -> Dict[str, Any]:
    """Save one main-settlement original and automatically derive grouping + identity machine evidence."""
    empty = {
        "ok": False,
        "status": None,
        "warning": None,
        "descriptor": None,
        "proposals": None,
        "proposalStatus": None,
        "proposalWarning": None,
        "candidates": None,
        "candidateStatus": None,
        "candidateWarning": None,
        "groupingHypotheses": None,
        "groupingStatus": None,
        "groupingWarning": None,
        "identityEvidence": None,
        "identityStatus": None,
        "identityWarning": None,
    }
    if not is_settlement:
        return {**empty, "status": STATUS_SKIPPED_NOT_SETTLEMENT}
    if not record_stable_key:
        return {
            **empty,
            "status": STATUS_MISSING_STABLE_KEY,
            "warning": "settlement original not saved: missing recordStableKey",
        }
    if store is None:
        return {
            **empty,
            "status": STATUS_EVIDENCE_PERSIST_FAILED,
            "warning": "settlement original not saved: evidence store unavailable",
        }
    try:
        payload = encode_settlement_original(frame)
        if isinstance(existing_descriptor, dict) and existing_descriptor.get("sha256"):
            if existing_descriptor.get("sha256") == hashlib.sha256(payload).hexdigest():
                return {
                    "ok": True,
                    "status": STATUS_IDEMPOTENT,
                    "warning": None,
                    "descriptor": dict(existing_descriptor),
                    "proposals": None,
                    "proposalStatus": "PROPOSALS_SKIPPED_IDEMPOTENT",
                    "proposalWarning": None,
                    "candidates": None,
                    "candidateStatus": "CANDIDATES_SKIPPED_IDEMPOTENT",
                    "candidateWarning": None,
                    "groupingHypotheses": None,
                    "groupingStatus": "GROUPING_SKIPPED_IDEMPOTENT",
                    "groupingWarning": None,
                    "identityEvidence": None,
                    "identityStatus": "IDENTITY_SKIPPED_IDEMPOTENT",
                    "identityWarning": None,
                }
        descriptor = store.save_original(
            record_stable_key=record_stable_key,
            kind=KIND_MAIN,
            image_bytes=payload,
            captured_at=captured_at,
            coverage_mode="viewport-segment",
            coverage_status=COVERAGE_UNPROVEN,
        )
        status = (
            STATUS_IDEMPOTENT
            if existing_descriptor and existing_descriptor.get("evidenceId") == descriptor.get("evidenceId")
            else STATUS_SAVED
        )

        # 4D2D1M-C3.2W / C3.3 / C3.6A: Wire proposal, candidate, grouping, and identity evidence derivation
        proposals = None
        proposal_status = None
        proposal_warning = None
        candidates = None
        candidate_status = None
        candidate_warning = None
        grouping_hypotheses = None
        grouping_status = None
        grouping_warning = None
        identity_evidences = None
        identity_status = None
        identity_warning = None

        if status == STATUS_SAVED and extract_proposals:
            try:
                from settlement_item_proposals import extract_settlement_warehouse_proposals

                proposals = extract_settlement_warehouse_proposals(
                    store=store,
                    parent_descriptor=descriptor,
                    save_crops=True,
                )
                proposal_status = "PROPOSALS_EXTRACTED"
            except Exception as p_exc:
                # Failure boundary: proposal failure NEVER rollbacks or blocks main-settlement evidence
                proposal_status = "PROPOSALS_EXTRACTION_FAILED"
                proposal_warning = f"PROPOSALS_EXTRACTION_FAILED: {p_exc}"
                proposals = None

            if proposals:
                try:
                    from settlement_catalog_candidates import resolve_settlement_catalog_candidate_evidence

                    candidates = resolve_settlement_catalog_candidate_evidence(proposals)
                    candidate_status = "CANDIDATES_RESOLVED"
                except Exception as c_exc:
                    candidate_status = "CANDIDATES_FAILED"
                    candidate_warning = f"CANDIDATES_FAILED: {c_exc}"
                    candidates = None

            try:
                img_array = frame if isinstance(frame, np.ndarray) else cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img_array is not None and img_array.size > 0:
                    grouping_hypotheses, identity_evidences = derive_settlement_grouping_and_identity_evidence(
                        frame=img_array,
                        parent_descriptor=descriptor,
                        store=store,
                    )
                    grouping_status = "GROUPING_HYPOTHESES_DERIVED"
                    identity_status = "IDENTITY_EVIDENCE_DERIVED"
            except Exception as g_exc:
                grouping_status = "GROUPING_HYPOTHESES_FAILED"
                grouping_warning = f"GROUPING_HYPOTHESES_FAILED: {g_exc}"
                identity_status = "IDENTITY_EVIDENCE_FAILED"
                identity_warning = f"IDENTITY_EVIDENCE_FAILED: {g_exc}"

        return {
            "ok": True,
            "status": status,
            "warning": None,
            "descriptor": descriptor,
            "proposals": proposals,
            "proposalStatus": proposal_status,
            "proposalWarning": proposal_warning,
            "candidates": candidates,
            "candidateStatus": candidate_status,
            "candidateWarning": candidate_warning,
            "groupingHypotheses": grouping_hypotheses,
            "groupingStatus": grouping_status,
            "groupingWarning": grouping_warning,
            "identityEvidence": identity_evidences,
            "identityStatus": identity_status,
            "identityWarning": identity_warning,
        }
    except Exception as exc:
        return {
            **empty,
            "status": STATUS_EVIDENCE_PERSIST_FAILED,
            "warning": f"EVIDENCE_PERSIST_FAILED: {exc}",
        }


def apply_persist_result(context: Dict[str, Any], result: Dict[str, Any]) -> None:
    context["settlementFileEvidenceStatus"] = result.get("status")
    context["settlementFileEvidenceWarning"] = result.get("warning")
    descriptor = result.get("descriptor")
    if result.get("ok") and isinstance(descriptor, dict):
        context["settlementFileEvidence"] = descriptor
        if result.get("proposals") is not None:
            context["settlementWarehouseProposals"] = result.get("proposals")
            context["settlementWarehouseProposalCount"] = len(result.get("proposals"))
        if result.get("proposalStatus") is not None:
            context["settlementWarehouseProposalStatus"] = result.get("proposalStatus")
        if result.get("proposalWarning") is not None:
            context["settlementWarehouseProposalWarning"] = result.get("proposalWarning")
        if result.get("candidates") is not None:
            context["settlementCatalogCandidateEvidence"] = result.get("candidates")
            context["settlementCatalogCandidateCount"] = len(result.get("candidates"))
        if result.get("candidateStatus") is not None:
            context["settlementCatalogCandidateStatus"] = result.get("candidateStatus")
        if result.get("candidateWarning") is not None:
            context["settlementCatalogCandidateWarning"] = result.get("candidateWarning")
        if result.get("groupingHypotheses") is not None:
            context["settlementGroupingHypotheses"] = result.get("groupingHypotheses")
            context["settlementGroupingHypothesisCount"] = len(result.get("groupingHypotheses"))
        if result.get("groupingStatus") is not None:
            context["settlementGroupingStatus"] = result.get("groupingStatus")
        if result.get("groupingWarning") is not None:
            context["settlementGroupingWarning"] = result.get("groupingWarning")
        if result.get("identityEvidence") is not None:
            context["settlementIdentityEvidence"] = result.get("identityEvidence")
            context["settlementIdentityEvidenceCount"] = len(result.get("identityEvidence"))
        if result.get("identityStatus") is not None:
            context["settlementIdentityStatus"] = result.get("identityStatus")
        if result.get("identityWarning") is not None:
            context["settlementIdentityWarning"] = result.get("identityWarning")
    elif "settlementFileEvidence" not in context:
        context["settlementFileEvidence"] = None
