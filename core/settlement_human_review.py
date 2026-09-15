"""Settlement human review confirmation bridge.

Connects visible warehouse candidate evidence to explicit human confirmation.
Produces traceable HUMAN_REVIEWED_CATALOG_ID records only upon explicit user action.
Never writes to canonical knownItems or Solver input; warehouse coverage remains PARTIAL (4D2D1M-C3.4).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from settlement_catalog_candidates import (
    STATUS_AMBIGUOUS_CANDIDATES,
    STATUS_NO_CATALOG_MATCH,
    STATUS_UNIQUE_IN_CATALOG,
    get_global_catalog_candidate_resolver,
)
from settlement_evidence_store_v2 import (
    COVERAGE_UNPROVEN,
    STORE_RELATIVE_ROOT,
    SettlementEvidenceStoreError,
    SettlementEvidenceStoreV2,
    validate_record_stable_key,
)

SCHEMA_VERSION = "settlement-human-reviewed-truth.v1"
SOURCE_HUMAN_REVIEWED = "HUMAN_REVIEWED_CATALOG_ID"

ACTION_CONFIRM_CANDIDATE = "CONFIRM_CANDIDATE"
ACTION_CONFIRM_OVERRIDE = "CONFIRM_CATALOG_OVERRIDE"
ALLOWED_ACTIONS = frozenset({ACTION_CONFIRM_CANDIDATE, ACTION_CONFIRM_OVERRIDE})

REVIEW_RELATIVE_DIR = f"{STORE_RELATIVE_ROOT}/reviews"


class SettlementHumanReviewError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _review_relative(record_key: str) -> str:
    return f"{REVIEW_RELATIVE_DIR}/{record_key}.json"


def load_settlement_reviewed_truth(
    store: SettlementEvidenceStoreV2,
    record_stable_key: str,
) -> List[Dict[str, Any]]:
    """Load persisted human-reviewed settlement item truths for a match record."""
    key = validate_record_stable_key(record_stable_key)
    rel_path = _review_relative(key)
    full_path = store.root / rel_path
    if not full_path.is_file():
        return []
    try:
        doc = json.loads(full_path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("reviewedItems"), list):
            return [it for it in doc["reviewedItems"] if isinstance(it, dict)]
    except Exception:
        return []
    return []


def save_settlement_reviewed_truth(
    store: SettlementEvidenceStoreV2,
    record_stable_key: str,
    reviewed_items: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Persist human-reviewed settlement item truths to file-backed Evidence Store v2."""
    key = validate_record_stable_key(record_stable_key)
    rel_path = _review_relative(key)
    full_path = store.root / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)

    document = {
        "schemaVersion": SCHEMA_VERSION,
        "recordStableKey": key,
        "reviewedCount": len(reviewed_items),
        "warehouseCoverage": "PARTIAL",
        "coverageStatus": COVERAGE_UNPROVEN,
        "reviewedItems": [dict(it) for it in reviewed_items],
        "updatedAt": _utc_now(),
    }
    payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")

    # Atomic write to store
    temporary = full_path.with_name(f".{full_path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_bytes(payload)
        os.replace(str(temporary), str(full_path))
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass

    return document


def apply_settlement_human_review_action(
    *,
    store: SettlementEvidenceStoreV2,
    candidate_evidence_list: Sequence[Mapping[str, Any]],
    action_payload: Mapping[str, Any],
    proposals: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Apply an explicit human review action to confirm or override a grouping hypothesis / proposal identity.

    Rules (4D2D1M-C3.4A):
    - No user action = No reviewed truth.
    - CONFIRM_CANDIDATE:
        - Unique candidate / Exact: confirms the candidate (selectedCatalogId optional if 1 candidate).
        - Ambiguous: selectedCatalogId MUST be explicitly provided and must be in candidate set.
        - Non-candidate ID is rejected.
    - CONFIRM_CATALOG_OVERRIDE:
        - selectedCatalogId MUST exist in the official catalog.
        - Invalid catalog ID is rejected.
    - Always records full provenance back to groupingHypothesisId/proposal, crop, and parent evidence.
    - Coverage strictly remains PARTIAL / COVERAGE_UNPROVEN.
    - Never writes knownItems, Solver input, or History.
    - Returns the created reviewed item truth record.
    """
    if not isinstance(action_payload, Mapping):
        raise SettlementHumanReviewError("INVALID_ACTION_PAYLOAD", "action_payload must be an object")

    target_id = str(
        action_payload.get("groupingHypothesisId")
        or action_payload.get("proposalId")
        or ""
    ).strip()
    if not target_id:
        raise SettlementHumanReviewError("HYPOTHESIS_ID_MISSING", "action_payload missing groupingHypothesisId or proposalId")

    action = str(action_payload.get("action") or "").strip()
    if action not in ALLOWED_ACTIONS:
        raise SettlementHumanReviewError("INVALID_ACTION", f"action must be one of {sorted(ALLOWED_ACTIONS)}")

    # 1. Find target candidate / identity evidence
    target_cand: Optional[Mapping[str, Any]] = None
    for cand in candidate_evidence_list:
        cand_id = str(
            cand.get("groupingHypothesisId")
            or cand.get("proposalId")
            or ""
        ).strip()
        if cand_id == target_id:
            target_cand = cand
            break

    if target_cand is None:
        raise SettlementHumanReviewError("HYPOTHESIS_NOT_FOUND", f"groupingHypothesisId/proposalId {target_id} not found in evidence")

    record_key = validate_record_stable_key(str(target_cand.get("recordStableKey") or ""))
    parent_ev_id = str(target_cand.get("parentEvidenceId") or "")
    parent_sha = str(target_cand.get("parentSha256") or "")
    crop_ev_id = target_cand.get("cropEvidenceId")
    crop_rel = target_cand.get("cropRelativePath")
    crop_sha = target_cand.get("cropSha256")
    cand_status = str(
        target_cand.get("identityStatus")
        or target_cand.get("candidateStatus")
        or target_cand.get("status")
        or ""
    )
    candidate_items = list(target_cand.get("rankedCandidates") or target_cand.get("candidates") or [])
    candidate_ids = list(
        target_cand.get("candidateCatalogIds")
        or [c["catalogId"] for c in candidate_items if isinstance(c, dict) and "catalogId" in c]
    )

    # Find proposal / hypothesis bbox and cells
    cells = target_cand.get("cells")
    bbox = target_cand.get("bbox")
    if proposals:
        for p in proposals:
            p_id = str(p.get("groupingHypothesisId") or p.get("proposalId") or "").strip()
            if p_id == target_id:
                if bbox is None:
                    bbox = p.get("bbox")
                if cells is None:
                    cells = p.get("cells")
                break

    selected_catalog_id = str(action_payload.get("selectedCatalogId") or "").strip()
    selected_item: Optional[Dict[str, Any]] = None

    resolver = get_global_catalog_candidate_resolver()

    # 2. Evaluate action
    if action == ACTION_CONFIRM_CANDIDATE:
        if cand_status in (STATUS_UNIQUE_IN_CATALOG, "EXACT_IDENTIFIED"):
            if selected_catalog_id:
                if candidate_ids and selected_catalog_id != candidate_ids[0] and selected_catalog_id not in candidate_ids:
                    raise SettlementHumanReviewError(
                        "CATALOG_ID_MISMATCH",
                        f"selectedCatalogId {selected_catalog_id} does not match candidate {candidate_ids[0]}",
                    )
            selected_item = candidate_items[0] if candidate_items else None
            if not selected_item and candidate_ids:
                selected_item = next((it for it in resolver.catalog_items if it["catalogId"] == candidate_ids[0]), None)
            if not selected_item:
                raise SettlementHumanReviewError("CANDIDATE_DATA_MISSING", "candidate data not found")

        elif cand_status in (STATUS_AMBIGUOUS_CANDIDATES, "AMBIGUOUS_GROUPING"):
            if not selected_catalog_id:
                raise SettlementHumanReviewError(
                    "SELECTED_CATALOG_ID_REQUIRED",
                    "Ambiguous hypothesis requires explicit selectedCatalogId to CONFIRM_CANDIDATE",
                )
            if selected_catalog_id not in candidate_ids:
                raise SettlementHumanReviewError(
                    "SELECTED_CATALOG_ID_NOT_IN_CANDIDATES",
                    f"selectedCatalogId {selected_catalog_id} is not in candidates for {target_id}",
                )
            selected_item = next((it for it in candidate_items if it.get("catalogId") == selected_catalog_id or it.get("candidateCatalogId") == selected_catalog_id), None)
            if not selected_item:
                selected_item = next((it for it in resolver.catalog_items if it["catalogId"] == selected_catalog_id), None)

        elif cand_status in (STATUS_NO_CATALOG_MATCH, "UNRESOLVED_NOISE"):
            raise SettlementHumanReviewError(
                "CANNOT_CONFIRM_EMPTY_CANDIDATES",
                "Hypothesis has 0 candidates; use CONFIRM_CATALOG_OVERRIDE to assign a catalog item",
            )
        else:
            # Fallback check if candidates exist
            if candidate_ids:
                if not selected_catalog_id:
                    selected_item = candidate_items[0] if candidate_items else next((it for it in resolver.catalog_items if it["catalogId"] == candidate_ids[0]), None)
                else:
                    if selected_catalog_id not in candidate_ids:
                        raise SettlementHumanReviewError("SELECTED_CATALOG_ID_NOT_IN_CANDIDATES", f"selectedCatalogId {selected_catalog_id} not in candidates")
                    selected_item = next((it for it in resolver.catalog_items if it["catalogId"] == selected_catalog_id), None)
            else:
                raise SettlementHumanReviewError("CANNOT_CONFIRM_EMPTY_CANDIDATES", f"unsupported candidateStatus: {cand_status}")

    elif action == ACTION_CONFIRM_OVERRIDE:
        if not selected_catalog_id:
            raise SettlementHumanReviewError(
                "SELECTED_CATALOG_ID_REQUIRED",
                "CONFIRM_CATALOG_OVERRIDE requires explicit selectedCatalogId",
            )
        selected_item = next((it for it in resolver.catalog_items if it["catalogId"] == selected_catalog_id), None)
        if not selected_item:
            raise SettlementHumanReviewError(
                "INVALID_OVERRIDE_CATALOG_ID",
                f"selectedCatalogId {selected_catalog_id} does not exist in catalog",
            )

    if not selected_item:
        raise SettlementHumanReviewError("SELECTION_RESOLVE_FAILED", "failed to resolve selected catalog item")

    # 3. Construct reviewed truth record
    grouping_hyp_id = str(target_cand.get("groupingHypothesisId") or target_id)
    proposal_id = str(target_cand.get("proposalId") or grouping_hyp_id)
    review_id = f"rev_{grouping_hyp_id}_{uuid.uuid4().hex[:8]}"
    reviewed_at = str(action_payload.get("reviewedAt") or "").strip() or _utc_now()
    reviewer = str(action_payload.get("reviewer") or "user").strip()

    reviewed_item = {
        "schemaVersion": SCHEMA_VERSION,
        "source": SOURCE_HUMAN_REVIEWED,
        "reviewId": review_id,
        "groupingHypothesisId": grouping_hyp_id,
        "proposalId": proposal_id,
        "sequenceIndex": target_cand.get("sequenceIndex", 0),
        "recordStableKey": record_key,
        "parentEvidenceId": parent_ev_id,
        "parentSha256": parent_sha,
        "cropEvidenceId": crop_ev_id,
        "cropRelativePath": crop_rel,
        "cropSha256": crop_sha,
        "cells": cells,
        "bbox": bbox,
        "widthCells": target_cand.get("widthCells"),
        "heightCells": target_cand.get("heightCells"),
        "gridShape": target_cand.get("gridShape"),
        "selectedCatalogId": selected_item["catalogId"],
        "catalogName": selected_item["name"],
        "quality": selected_item.get("quality"),
        "rarity": selected_item.get("rarity"),
        "catalogValue": selected_item.get("value"),
        "catalogFingerprint": target_cand.get("catalogFingerprint") or resolver.catalog_fingerprint,
        "reviewAction": action,
        "overrideReason": action_payload.get("overrideReason"),
        "reviewedAt": reviewed_at,
        "reviewer": reviewer,
        "warehouseCoverage": "PARTIAL",
        "coverageStatus": COVERAGE_UNPROVEN,
    }

    # 4. Atomic update to persistent reviewed truth store
    existing_items = load_settlement_reviewed_truth(store, record_key)
    # Deduplicate / replace existing review for this groupingHypothesisId / proposalId if any
    updated_items = [
        it for it in existing_items
        if it.get("groupingHypothesisId") != grouping_hyp_id and it.get("proposalId") != proposal_id
    ]
    updated_items.append(reviewed_item)
    updated_items.sort(key=lambda it: it.get("sequenceIndex", 0))

    save_settlement_reviewed_truth(store, record_key, updated_items)

    return reviewed_item
