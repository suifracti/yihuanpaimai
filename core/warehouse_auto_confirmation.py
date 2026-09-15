# -*- coding: utf-8 -*-
"""Evidence-backed warehouse automatic confirmation and crop export engine.

Provides:
1. Strict multi-dimensional evidence confirmation gate (geometry, multi-frame hash deduplication,
   feature inliers, competition margin, conflict rejection).
2. Protection of prior human decisions (human override protection).
3. Raw crop export and provenance packaging for auditability.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import cv2
import numpy as np

from catalog_validator import get_official_name, is_valid_catalog_id, validate_item_identity

# Evidence Gate Thresholds (Empirically validated against benchmark ground truth)
MIN_SIFT_INLIERS = 7
MIN_SIFT_MARGIN = 5
MIN_FG_SCORE = 0.90
MIN_FG_MARGIN = 0.05
MIN_INDEPENDENT_FRAMES = 2

STATUS_CONFIRMED = "EXACT_IDENTIFIED"
STATUS_UNCONFIRMED = "REVIEW_REQUIRED"
CONFIRMATION_STATUS_CONFIRMED = "CONFIRMED"
CONFIRMATION_STATUS_CANDIDATE = "CANDIDATE_ONLY"


def extract_human_decisions(record: Optional[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Extract existing human decisions from canonical history record to protect them."""
    if not isinstance(record, Mapping):
        return {}
    settlement = record.get("settlement") or {}
    if not isinstance(settlement, Mapping):
        return {}

    human_decisions: Dict[str, Dict[str, Any]] = {}

    # 1. From warehouseIdentityReview if reviewerType == 'HUMAN' or individual decisions are HUMAN
    identity_rev = settlement.get("warehouseIdentityReview")
    if isinstance(identity_rev, Mapping):
        # 1a. Standard decisions list
        is_ir_human = identity_rev.get("reviewerType") == "HUMAN"
        for item in identity_rev.get("decisions") or []:
            if (isinstance(item, Mapping) and item.get("reviewerType") != "AUTO"
                    and item.get("provenanceType") != "AUTO_CONFIRMED_EVIDENCE"
                    and (is_ir_human or item.get("reviewerType") == "HUMAN")):
                uid = str(item.get("reviewUnitId") or item.get("trackId") or "").strip()
                if uid:
                    action = str(item.get("action") or "").upper()
                    cat_id = item.get("catalogId") or item.get("selectedCatalogId")
                    is_confirm = action in ("CONFIRM_CANDIDATE", "OVERRIDE_CATALOG_ID", "CONFIRM_CATALOG_OVERRIDE") and bool(cat_id)
                    human_decisions[uid] = {
                        "action": action if is_confirm else "DEFER",
                        "catalogId": cat_id if is_confirm else None,
                        "canonicalName": item.get("canonicalName") or item.get("name") if is_confirm else None,
                        "confirmedByHuman": True,
                        "reviewerType": "HUMAN",
                        "provenanceType": item.get("provenanceType", "HUMAN_REVIEWED_CATALOG_ID" if is_confirm else "HUMAN_DEFERRED"),
                    }
        # 1b. Legacy resolvedItems / unresolvedUnits
        if is_ir_human:
            for item in identity_rev.get("resolvedItems") or []:
                if item.get("provenanceType") == "AUTO_CONFIRMED_EVIDENCE" or item.get("reviewerType") == "AUTO":
                    continue
                uid = item.get("reviewUnitId") or item.get("trackId")
                if uid:
                    human_decisions[str(uid)] = {
                        "action": "CONFIRM_CANDIDATE",
                        "catalogId": item.get("catalogId"),
                        "canonicalName": item.get("name"),
                        "confirmedByHuman": True,
                        "reviewerType": "HUMAN",
                        "provenanceType": item.get("provenanceType", "HUMAN_REVIEWED_CATALOG_ID"),
                    }
            for item in identity_rev.get("unresolvedUnits") or []:
                if not item.get("action") or item.get("reviewerType") == "AUTO":
                    continue
                uid = item.get("reviewUnitId") or item.get("trackId")
                if uid:
                    human_decisions[str(uid)] = {
                        "action": item.get("action", "DEFER"),
                        "catalogId": None,
                        "canonicalName": None,
                        "confirmedByHuman": True,
                        "reviewerType": "HUMAN",
                        "provenanceType": "HUMAN_DEFERRED",
                    }

    # 2. From settlement.reviewUnits if flagged
    for u in settlement.get("reviewUnits") or []:
        if isinstance(u, Mapping):
            uid = str(u.get("reviewUnitId") or "").strip()
            if uid and (u.get("confirmedByHuman") or u.get("userOverride")):
                human_decisions[uid] = {
                    "action": "CONFIRM_CANDIDATE" if u.get("selectedCatalogId") else "DEFER",
                    "catalogId": u.get("selectedCatalogId"),
                    "canonicalName": u.get("canonicalName") or u.get("identifiedName"),
                    "confirmedByHuman": True,
                    "reviewerType": "HUMAN",
                    "provenanceType": "HUMAN_REVIEWED",
                }

    return human_decisions


def evaluate_auto_confirmation(
    review_units: Sequence[Mapping[str, Any]],
    segments: Optional[Sequence[Mapping[str, Any]]] = None,
    existing_record: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Evaluate evidence-backed automatic confirmation for warehouse review units.

    Strict Rules:
    - Never read independent ground truth or answer keys.
    - Never confirm by total price, valuation, or because candidate count == 1.
    - Deduplicate frames by underlying image SHA-256 hash (same image re-indexed cannot add votes).
    - Require each supporting frame to independently match the same identity. Cross-frame conflicts reject.
    - Require at least MIN_INDEPENDENT_FRAMES (2) independent frames; no single-frame exception in this phase.
    - Require SIFT inliers >= 7 with margin >= 5, or Foreground score >= 0.90 with margin >= 0.05.
    - Protect prior human decisions in existing_record from being overwritten.
    """
    human_decisions = extract_human_decisions(existing_record)
    seg_sha_map: Dict[str, str] = {}
    if segments:
        for s in segments:
            if isinstance(s, Mapping):
                eid = str(s.get("evidenceId") or "").strip()
                sha = str(s.get("sha256") or "").strip()
                if eid and sha:
                    seg_sha_map[eid] = sha

    evaluated_units: List[Dict[str, Any]] = []

    for raw_u in review_units:
        u = copy.deepcopy(dict(raw_u))
        uid = str(u.get("reviewUnitId") or "").strip()

        # Step 0: Check human override protection
        if uid in human_decisions:
            h_dec = human_decisions[uid]
            if h_dec.get("catalogId"):
                u["confirmationStatus"] = CONFIRMATION_STATUS_CONFIRMED
                u["identityStatus"] = STATUS_CONFIRMED
                u["selectedCatalogId"] = h_dec["catalogId"]
                u["canonicalName"] = h_dec.get("canonicalName") or get_official_name(h_dec["catalogId"])
                u["confirmedByHuman"] = True
                u["confirmationReasons"] = ["HUMAN_REVIEWED_PRIOR_DECISION_PROTECTED"]
            else:
                u["confirmationStatus"] = CONFIRMATION_STATUS_CANDIDATE
                u["identityStatus"] = STATUS_UNCONFIRMED
                u["selectedCatalogId"] = None
                u["canonicalName"] = None
                u["confirmedByHuman"] = True
                u["unconfirmedReasons"] = ["HUMAN_DEFERRED_PRIOR_DECISION_PROTECTED"]
            evaluated_units.append(u)
            continue

        placement_status = str(u.get("placementStatus") or "UNKNOWN").upper()
        candidates = list(u.get("candidates") or [])
        observations = list(u.get("observations") or [])
        unconfirmed_reasons: List[str] = []

        # Step 1: Geometry & Placement Sanity
        if placement_status != "RESOLVED":
            unconfirmed_reasons.append(f"PLACEMENT_{placement_status}")

        if not candidates:
            unconfirmed_reasons.append("NO_MACHINE_CANDIDATE")

        top_cand: Optional[Dict[str, Any]] = None
        target_cid: Optional[str] = None
        target_name: Optional[str] = None
        cand_inliers = 0
        cand_margin = 0
        cand_fg_score = 0.0
        cand_fg_margin = 0.0

        if candidates:
            top_cand = candidates[0]
            target_cid = str(top_cand.get("catalogId") or "").strip()
            target_name = str(top_cand.get("name") or top_cand.get("canonicalName") or "").strip()
            if not target_cid or not is_valid_catalog_id(target_cid):
                unconfirmed_reasons.append("INVALID_CATALOG_ID")
            else:
                try:
                    validate_item_identity(target_cid, target_name, CONFIRMATION_STATUS_CANDIDATE)
                except Exception as exc:
                    unconfirmed_reasons.append(f"NAME_MISMATCH_{exc}")

            cand_geom = top_cand.get("geometry") or {}
            cand_shape = str(cand_geom.get("shape") or "")
            unit_fp = u.get("footprint") or {}
            unit_w = unit_fp.get("widthCells")
            unit_h = unit_fp.get("heightCells")
            expected_shape = f"{unit_w}x{unit_h}" if unit_w and unit_h else ""
            if cand_shape and expected_shape and cand_shape != expected_shape:
                unconfirmed_reasons.append(f"GEOMETRY_CONTRADICTION_{cand_shape}_VS_{expected_shape}")

            # Parse feature match metrics directly from candidate (no guessing or fallback)
            cand_inliers = int(top_cand.get("inliers") or 0)
            cand_margin = int(top_cand.get("margin") or 0)
            cand_fg_score = float(top_cand.get("bestFgScore") or top_cand.get("fgScore") or 0.0)
            cand_fg_margin = float(top_cand.get("fgMargin") or 0.0)

        # Step 2: Multi-Frame Observation Evaluation, Identity Conflict Check, and Deduplication
        # 1. Group observations by valid 64-hex image SHA-256
        obs_by_sha: Dict[str, List[Dict[str, Any]]] = {}
        for obs in observations:
            ev_id = str(obs.get("evidenceId") or "").strip()
            raw_sha = str(obs.get("sha256") or seg_sha_map.get(ev_id) or "").strip()
            if len(raw_sha) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw_sha):
                sha = raw_sha.lower()
                obs_by_sha.setdefault(sha, []).append(obs)

        # 2. Check for identity conflicts across ALL observations first (order-independent)
        # Any observation asserting an identity different from target_cid conflicts
        conflicting_frame_shas: Set[str] = set()
        supporting_frame_shas: Set[str] = set()

        for sha, frame_obs_list in obs_by_sha.items():
            frame_has_conflict = False
            for obs in frame_obs_list:
                matched_cid = obs.get("matchedCandidateId")
                if matched_cid:
                    matched_cid = str(matched_cid).strip()
                    if matched_cid != target_cid:
                        frame_has_conflict = True
                        conflicting_frame_shas.add(sha)

            if frame_has_conflict:
                # Conflicting frame cannot cast a supporting vote
                continue

            # 3. For frames without conflict, verify if at least one observation meets supporting criteria:
            # - Visible status must be "FULL" (CLIPPED observations cannot vote)
            # - matchedCandidateId must explicitly match target_cid
            # - Per-frame feature thresholds must be independently satisfied:
            #   (SIFT: inliers >= 7 and margin >= 5) OR (Foreground: bestFgScore >= 0.90 and fgMargin >= 0.05)
            frame_has_valid_support = False
            for obs in frame_obs_list:
                status = str(obs.get("status") or "").upper()
                if status != "FULL":
                    continue

                matched_cid = obs.get("matchedCandidateId")
                if not matched_cid or str(matched_cid).strip() != target_cid:
                    continue

                # SIFT per-frame gate
                obs_inliers = int(obs.get("inliers") or 0)
                obs_margin = obs.get("margin")
                obs_sift_ok = (
                    obs_inliers >= MIN_SIFT_INLIERS
                    and obs_margin is not None
                    and int(obs_margin) >= MIN_SIFT_MARGIN
                )

                # Foreground per-frame gate
                obs_fg_score = obs.get("bestFgScore") or obs.get("fgScore")
                obs_fg_margin = obs.get("fgMargin")
                obs_fg_ok = (
                    obs_fg_score is not None
                    and float(obs_fg_score) >= MIN_FG_SCORE
                    and obs_fg_margin is not None
                    and float(obs_fg_margin) >= MIN_FG_MARGIN
                )

                if obs_sift_ok or obs_fg_ok:
                    frame_has_valid_support = True
                    break

            if frame_has_valid_support:
                supporting_frame_shas.add(sha)

        if conflicting_frame_shas:
            unconfirmed_reasons.append("CROSS_FRAME_IDENTITY_CONFLICT")

        effective_supporting_frames = len(supporting_frame_shas)
        if effective_supporting_frames < MIN_INDEPENDENT_FRAMES:
            unconfirmed_reasons.append(f"INSUFFICIENT_INDEPENDENT_FRAMES_{effective_supporting_frames}")

        # Step 3: Match Evidence Thresholds
        sift_passed = (cand_inliers >= MIN_SIFT_INLIERS and cand_margin >= MIN_SIFT_MARGIN)
        fg_passed = (cand_fg_score >= MIN_FG_SCORE and cand_fg_margin >= MIN_FG_MARGIN)

        if not (sift_passed or fg_passed):
            if cand_inliers > 0 and cand_inliers < MIN_SIFT_INLIERS:
                unconfirmed_reasons.append(f"INSUFFICIENT_INLIERS_{cand_inliers}_MIN_{MIN_SIFT_INLIERS}")
            if cand_inliers >= MIN_SIFT_INLIERS and cand_margin < MIN_SIFT_MARGIN:
                unconfirmed_reasons.append(f"LOW_COMPETITION_MARGIN_{cand_margin}_MIN_{MIN_SIFT_MARGIN}")
            if cand_fg_score > 0.0 and cand_fg_score < MIN_FG_SCORE:
                unconfirmed_reasons.append(f"INSUFFICIENT_FG_SCORE_{cand_fg_score:.4f}_MIN_{MIN_FG_SCORE}")
            if cand_fg_score >= MIN_FG_SCORE and cand_fg_margin < MIN_FG_MARGIN:
                unconfirmed_reasons.append(f"LOW_FG_MARGIN_{cand_fg_margin:.4f}_MIN_{MIN_FG_MARGIN:.4f}")
            if not unconfirmed_reasons:
                unconfirmed_reasons.append("WEAK_FEATURE_MATCH")

        # Step 4: Final Assignment
        if not unconfirmed_reasons and top_cand and target_cid and target_name:
            validate_item_identity(target_cid, target_name, STATUS_CONFIRMED)
            u["confirmationStatus"] = CONFIRMATION_STATUS_CONFIRMED
            u["identityStatus"] = STATUS_CONFIRMED
            u["selectedCatalogId"] = target_cid
            u["canonicalName"] = target_name
            u["confirmedByHuman"] = False
            u["confirmationReasons"] = [
                "EVIDENCE_BACKED_AUTO_CONFIRMATION",
                f"INLIERS_{cand_inliers}_MARGIN_{cand_margin}" if sift_passed else f"FG_{cand_fg_score:.4f}_MARGIN_{cand_fg_margin:.4f}",
                f"INDEPENDENT_FRAMES_{effective_supporting_frames}",
            ]
        else:
            u["confirmationStatus"] = CONFIRMATION_STATUS_CANDIDATE
            u["identityStatus"] = STATUS_UNCONFIRMED
            u["selectedCatalogId"] = None
            u["canonicalName"] = None
            u["confirmedByHuman"] = False
            u["unconfirmedReasons"] = unconfirmed_reasons or ["INSUFFICIENT_EVIDENCE"]

        evaluated_units.append(u)

    return evaluated_units


def export_warehouse_evidence_crops(
    *,
    record_id: str,
    review_units: Sequence[Mapping[str, Any]],
    store: Any,
    output_dir: Path | str,
    segments: Optional[Sequence[Mapping[str, Any]]] = None,
    frames: Optional[Sequence[np.ndarray]] = None,
) -> Dict[str, Any]:
    """Export per-review-unit original crop images and audit metadata manifest.

    Reads from SettlementEvidenceStoreV2 or raw frames, cuts exact observation bboxes,
    writes PNG files to output_dir / 'crops', and returns a full export manifest.
    """
    out_dir = Path(output_dir).resolve()
    crops_dir = out_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    seg_desc_map: Dict[str, Any] = {}
    if segments:
        for s in segments:
            if isinstance(s, Mapping):
                eid = str(s.get("evidenceId") or "").strip()
                if eid:
                    seg_desc_map[eid] = s

    store_evidence_by_id: Dict[str, Any] = {}
    if store is not None and hasattr(store, "list_record_evidence"):
        try:
            for desc in store.list_record_evidence(record_id):
                eid = desc.get("evidenceId")
                if eid:
                    store_evidence_by_id[eid] = desc
        except Exception:
            pass

    exported_samples: List[Dict[str, Any]] = []

    for u in review_units:
        uid = str(u.get("reviewUnitId") or "").strip()
        obs_list = u.get("observations") or []
        if not obs_list:
            continue

        best_obs = next((o for o in obs_list if o.get("status") == "FULL"), obs_list[0])
        ev_id = str(best_obs.get("evidenceId") or "").strip()
        bbox = best_obs.get("bbox")
        seq = best_obs.get("sequenceIndex", 0)

        crop_img: Optional[np.ndarray] = None

        # 1. Try loading from frames buffer
        if frames is not None and isinstance(seq, int) and 0 <= seq < len(frames):
            frame = frames[seq]
            if isinstance(frame, np.ndarray) and frame.size > 0 and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                h_img, w_img = frame.shape[:2]
                bx1 = max(0, min(w_img - 1, int(round(float(bbox[0])))))
                by1 = max(0, min(h_img - 1, int(round(float(bbox[1])))))
                bx2 = max(bx1 + 1, min(w_img, int(round(float(bbox[2])))))
                by2 = max(by1 + 1, min(h_img, int(round(float(bbox[3])))))
                crop_img = frame[by1:by2, bx1:bx2]

        # 2. Try loading from SettlementEvidenceStoreV2
        if crop_img is None and store is not None and hasattr(store, "load_original"):
            desc = store_evidence_by_id.get(ev_id) or seg_desc_map.get(ev_id)
            if desc:
                try:
                    payload = store.load_original(desc)
                    img = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if img is not None and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                        h_img, w_img = img.shape[:2]
                        bx1 = max(0, min(w_img - 1, int(round(float(bbox[0])))))
                        by1 = max(0, min(h_img - 1, int(round(float(bbox[1])))))
                        bx2 = max(bx1 + 1, min(w_img, int(round(float(bbox[2])))))
                        by2 = max(by1 + 1, min(h_img, int(round(float(bbox[3])))))
                        crop_img = img[by1:by2, bx1:bx2]
                except Exception:
                    crop_img = None

        crop_rel_path = None
        crop_sha256 = None
        if crop_img is not None and crop_img.size > 0:
            crop_filename = f"{record_id}_{uid}.png"
            crop_file_path = crops_dir / crop_filename
            cv2.imencode(".png", crop_img)[1].tofile(str(crop_file_path))
            crop_rel_path = f"crops/{crop_filename}"
            crop_sha256 = hashlib.sha256(crop_file_path.read_bytes()).hexdigest()

        exported_samples.append({
            "reviewUnitId": uid,
            "recordId": record_id,
            "confirmationStatus": u.get("confirmationStatus"),
            "identityStatus": u.get("identityStatus"),
            "selectedCatalogId": u.get("selectedCatalogId"),
            "canonicalName": u.get("canonicalName"),
            "worldAnchor": u.get("worldAnchor"),
            "footprint": u.get("footprint"),
            "evidenceId": ev_id,
            "bbox": bbox,
            "cropPath": crop_rel_path,
            "cropSha256": crop_sha256,
            "candidates": u.get("candidates") or [],
            "reasons": u.get("confirmationReasons") or u.get("unconfirmedReasons") or [],
        })

    manifest = {
        "schemaVersion": "warehouse-evidence-export.v1",
        "recordId": record_id,
        "sampleCount": len(exported_samples),
        "confirmedCount": sum(1 for s in exported_samples if s["confirmationStatus"] == CONFIRMATION_STATUS_CONFIRMED),
        "unresolvedCount": sum(1 for s in exported_samples if s["confirmationStatus"] != CONFIRMATION_STATUS_CONFIRMED),
        "samples": exported_samples,
    }

    manifest_path = out_dir / f"warehouse_evidence_manifest_{record_id}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
