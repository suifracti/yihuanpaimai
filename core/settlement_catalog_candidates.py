"""Derive catalog candidate evidence for settlement warehouse proposals.

Never selects candidates[0], never promotes to canonical knownItems,
never claims COMPLETE warehouse coverage (4D2D1M-C3.3).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import cv2
import numpy as np

from settlement_evidence_store_v2 import COVERAGE_UNPROVEN

SCHEMA_VERSION = "settlement-catalog-candidate.v1"
IDENTITY_EVIDENCE_SCHEMA_VERSION = "settlement-identity-evidence.v1"

STATUS_NO_CATALOG_MATCH = "NO_CATALOG_MATCH"
STATUS_UNIQUE_IN_CATALOG = "UNIQUE_IN_CATALOG"
STATUS_AMBIGUOUS_CANDIDATES = "AMBIGUOUS_CANDIDATES"
STATUS_EXACT_IDENTIFIED = "EXACT_IDENTIFIED"
STATUS_UNKNOWN = "UNKNOWN"

DEFAULT_TOP1_SCORE_THRESHOLD = 0.85
DEFAULT_MARGIN_THRESHOLD = 0.08


def explain_unresolved_settlement_evidence(evidence, *, grouping_ambiguous, qualified_catalog_ids):
    """Describe a missing identity without promoting a catalog candidate."""
    result = dict(evidence or {})
    if result.get("status") == STATUS_EXACT_IDENTIFIED:
        return result
    qualified = list(qualified_catalog_ids or [])
    ranked = result.get("rankedCandidates") or []
    if float(result.get("top1Score") or 0) <= 0 and result.get("evidenceSource") == "DERIVED_REFERENCE_CANDIDATE_ONLY":
        result["evidenceSource"] = "NO_USABLE_VISUAL_SCORE"
        result["templateReference"] = None
    if grouping_ambiguous:
        reason = "PHYSICAL_BOUNDARY_UNRESOLVED"
    elif not ranked:
        reason = "NO_CATALOG_CANDIDATES"
    elif not qualified:
        reason = "NO_QUALIFIED_GAMEPLAY_REFERENCE"
    else:
        reason = "QUALIFIED_REFERENCE_NOT_ACCEPTED"
    result["qualificationReason"] = reason
    result["qualifiedReferenceCandidateCount"] = len(qualified)
    return result

CATALOG_RELATIVE_PATH = Path("assets") / "catalog_065.json"

RARITY_CN_TO_CANONICAL = {
    "金": "gold",
    "紫": "purple",
    "蓝": "blue",
    "绿": "green",
    "白": "white",
    "灰": "white",
    "红": "red",
    "橙": "red",
}


def _asset_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[1]


def default_catalog_path() -> Path:
    return _asset_root() / CATALOG_RELATIVE_PATH


class SettlementCatalogCandidateResolver:
    def __init__(self, catalog_path: Optional[Union[str, Path]] = None):
        path = Path(catalog_path).resolve() if catalog_path else default_catalog_path()
        if not path.is_file():
            # Fallback check relative to project root
            fallback = Path(__file__).resolve().parents[1] / "assets" / "catalog_065.json"
            if fallback.is_file():
                path = fallback

        self.catalog_path = path
        self.catalog_items: List[Dict[str, Any]] = []
        self.catalog_fingerprint: str = ""
        self._by_shape_rarity: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

        self._load_catalog(path)
        self.catalog_version = "catalog_065.v1"
        if catalog_path is None:
            # Recognition uses inspected card geometry; the historical catalog
            # and solver price snapshot remain unchanged.
            from visual_catalog import deterministic_reference_crops, verified_references
            references = verified_references()
            reference_crops = deterministic_reference_crops()
            self.catalog_version = "catalog_065.v1+visual-catalog.v2+catalog-reference-crops.v1"
            self.catalog_fingerprint = hashlib.sha256((
                self.catalog_fingerprint
                + json.dumps(references, sort_keys=True, ensure_ascii=False)
                + json.dumps(reference_crops, sort_keys=True, ensure_ascii=False)
            ).encode("utf-8")).hexdigest()
            by_id = {item["catalogId"]: item for item in self.catalog_items}
            for ref in references:
                item = {**by_id.get(ref["catalogId"], {}), **ref,
                        "quality": {"gold": "金", "purple": "紫", "blue": "蓝",
                                    "green": "绿", "red": "红", "white": "灰"}[ref["rarity"]],
                        "cells": ref["width"] * ref["height"],
                        "file": ref["catalogId"] + ".png", "liveFiles": [],
                        "shape": f"{ref['width']}x{ref['height']}"}
                by_id[ref["catalogId"]] = item
            self.catalog_items = list(by_id.values())
            self._by_shape_rarity = {}
            for item in self.catalog_items:
                for w, h in {(item["width"], item["height"]), (item["height"], item["width"])}:
                    self._by_shape_rarity.setdefault((f"{w}x{h}", item["rarity"]), []).append(item)


    def _load_catalog(self, path: Path) -> None:
        if not path.is_file():
            return
        payload = path.read_bytes()
        self.catalog_fingerprint = hashlib.sha256(payload).hexdigest()
        try:
            raw = json.loads(payload.decode("utf-8"))
        except Exception:
            return

        if not isinstance(raw, list):
            return

        for item in raw:
            if not isinstance(item, dict):
                continue
            cat_id = str(item.get("Id") or "").strip()
            name = str(item.get("Name") or "").strip()
            cn_qual = str(item.get("Quality") or "").strip()
            rarity = RARITY_CN_TO_CANONICAL.get(cn_qual, "unknown")
            w = int(item.get("Width") or 0)
            h = int(item.get("Height") or 0)
            cells = int(item.get("Cells") or (w * h))
            val = int(item.get("Value") or 0)
            shape = str(item.get("Shape") or "")

            entry = {
                "catalogId": cat_id,
                "name": name,
                "quality": cn_qual,
                "rarity": rarity,
                "width": w,
                "height": h,
                "cells": cells,
                "value": val,
                "shape": shape,
                "file": str(item.get("File") or "").strip(),
                "liveFiles": list(item.get("LiveFiles") or []),
            }
            self.catalog_items.append(entry)

            sz1 = f"{w}x{h}"
            sz2 = f"{h}x{w}"
            self._by_shape_rarity.setdefault((sz1, rarity), []).append(entry)
            if sz1 != sz2:
                self._by_shape_rarity.setdefault((sz2, rarity), []).append(entry)

    def resolve_candidates_for_hypothesis(
        self,
        hypothesis: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Filter catalog candidates for a physical grouping hypothesis.

        Delegates to shared ItemIdentityResolver (Phase 19).
        """
        rarity = str(hypothesis.get("rarity") or hypothesis.get("rarityObservation") or "unknown").lower()
        w = int(hypothesis.get("widthCells") or 1)
        h = int(hypothesis.get("heightCells") or 1)
        return sorted([item for item in self.catalog_items
            if (item["width"], item["height"]) in ((w, h), (h, w))
            and (rarity == "unknown" or item["rarity"] == rarity)], key=lambda item: item["catalogId"])

    def resolve_identity_evidence(
        self,
        hypothesis: Mapping[str, Any],
        crop_image: Optional[np.ndarray] = None,
        templates: Optional[Mapping[str, Any]] = None,
        top1_threshold: float = DEFAULT_TOP1_SCORE_THRESHOLD,
        margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    ) -> Dict[str, Any]:
        """
        Disambiguate physical grouping hypothesis identity via catalog candidates and pixel/template matching.

        Rules (4D2D1M-C3.2I):
        1. Filters catalog candidates by rarity, widthCells/heightCells, gridShape.
        2. CandidateCount:
           - 0 -> NO_CATALOG_MATCH
           - 1 -> UNIQUE_IN_CATALOG
           - >1 -> Enters pixel/template comparison
        3. Multi-candidates (>1):
           - Runs pixel/template matching for each candidate against ROI crop.
           - Deterministically ranks candidates by templateScore descending.
           - Calculates top1Score, top2Score, margin = top1Score - top2Score.
           - If top1Score >= top1_threshold AND margin >= margin_threshold:
               -> EXACT_IDENTIFIED
             Else:
               -> AMBIGUOUS_CANDIDATES
        4. Full candidate pool and scores are strictly preserved.
        5. Absolutely NO candidates[0] blind picking, and NO truth writing.
        """
        matched_sorted = self.resolve_candidates_for_hypothesis(hypothesis)
        count = len(matched_sorted)

        # Extract ROI if crop_image is given and hypothesis has bbox
        roi: Optional[np.ndarray] = crop_image
        bbox = hypothesis.get("bbox")
        if roi is not None and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            bx, by, bw, bh = bbox
            if roi.shape[0] > bh and roi.shape[1] > bw and by + bh <= roi.shape[0] and bx + bw <= roi.shape[1]:
                roi = roi[by:by + bh, bx:bx + bw]

        # Fragment boundaries are unresolved: retain metadata candidates but do
        # not spend visual matching time or imply that the fragment is an item.
        if hypothesis.get("groupingAmbiguous") or hypothesis.get("status") == "AMBIGUOUS_GROUPING":
            roi = None

        proposal_id = str(hypothesis.get("proposalId") or hypothesis.get("groupingHypothesisId") or "")
        hypothesis_id = str(hypothesis.get("groupingHypothesisId") or proposal_id)

        if count == 0:
            return {
                "schemaVersion": IDENTITY_EVIDENCE_SCHEMA_VERSION,
                "status": STATUS_NO_CATALOG_MATCH,
                "identityStatus": STATUS_NO_CATALOG_MATCH,
                "groupingHypothesisId": hypothesis_id,
                "proposalId": proposal_id,
                "recordStableKey": hypothesis.get("recordStableKey"),
                "parentEvidenceId": hypothesis.get("parentEvidenceId"),
                "parentSha256": hypothesis.get("parentSha256"),
                "cropEvidenceId": hypothesis.get("cropEvidenceId"),
                "cropRelativePath": hypothesis.get("cropRelativePath"),
                "cropSha256": hypothesis.get("cropSha256"),
                "candidateCatalogId": None,
                "candidateCount": 0,
                "candidateCatalogIds": [],
                "templateScore": 0.0,
                "top1Score": 0.0,
                "top2Score": 0.0,
                "margin": 0.0,
                "evidenceSource": "NO_CATALOG_MATCH",
                "templateReference": None,
                "rankedCandidates": [],
                "cells": hypothesis.get("cells"),
                "bbox": hypothesis.get("bbox"),
                "widthCells": hypothesis.get("widthCells"),
                "heightCells": hypothesis.get("heightCells"),
                "gridShape": hypothesis.get("gridShape"),
                "rarity": hypothesis.get("rarity"),
                "thresholds": {
                    "top1ScoreThreshold": top1_threshold,
                    "marginThreshold": margin_threshold,
                },
                "catalogVersion": self.catalog_version,
                "catalogFingerprint": self.catalog_fingerprint,
            }

        # Evaluate pixel/template scores for all candidates
        scored_candidates: List[Dict[str, Any]] = []
        for cand in matched_sorted:
            tpl_img, tpl_ref = _find_candidate_template(cand, templates or {})
            score, final_ref, ev_src = _match_template_score(roi, tpl_img, tpl_ref)
            # Different crops of one catalog card compete within that identity,
            # never as separate top-1/top-2 candidates.
            prefix = f"visual/{cand['catalogId']}@"
            for view_ref, view_image in (templates or {}).items():
                if not view_ref.startswith(prefix) or not isinstance(view_image, np.ndarray):
                    continue
                view_score, view_final_ref, view_source = _match_template_score(roi, view_image, view_ref)
                if view_score > score:
                    score, final_ref, ev_src = view_score, view_final_ref, view_source
                    tpl_img, tpl_ref = view_image, view_ref
            scored_entry = {
                "candidateCatalogId": cand["catalogId"],
                "catalogId": cand["catalogId"],
                "name": cand["name"],
                "quality": cand["quality"],
                "rarity": cand["rarity"],
                "width": cand["width"],
                "height": cand["height"],
                "cells": cand["cells"],
                "value": cand["value"],
                "templateScore": score,
                "evidenceSource": ev_src,
                "templateReference": final_ref,
            }
            if str(tpl_ref or "").startswith(("visual/", "video-dev/")):
                from visual_catalog import feature_match_evidence
                scored_entry["visualEvidence"] = feature_match_evidence(roi, tpl_img)
                if str(tpl_ref).startswith("video-dev/"):
                    from visual_catalog import development_reference_for_template
                    scored_entry["videoDevelopmentReference"] = development_reference_for_template(tpl_ref)
                else:
                    scored_entry["sourcePath"] = cand.get("sourcePath")
                    scored_entry["sourceSha256"] = cand.get("sourceSha256")
                    scored_entry["sourceCardBbox"] = cand.get("cardBbox")
                    if str(tpl_ref).endswith("@catalog-reference-crop.png"):
                        from visual_catalog import catalog_reference_for_template
                        scored_entry["catalogReference"] = catalog_reference_for_template(tpl_ref)
            scored_candidates.append(scored_entry)

        # Stable sort: primary key is templateScore descending, secondary key is catalogId ascending
        ranked = sorted(
            scored_candidates,
            key=lambda c: (-c["templateScore"], str(c["catalogId"]))
        )

        top1 = ranked[0]
        top1_score = top1["templateScore"]
        top2_score = ranked[1]["templateScore"] if len(ranked) > 1 else 0.0
        margin = round(top1_score - top2_score, 4)

        visual_sources = {"VISUAL_FEATURE_MATCH", "VIDEO_DEVELOPMENT_REFERENCE_MATCH"}
        if count == 1 and not (top1["evidenceSource"] in visual_sources and top1_score >= top1_threshold):
            # 1 candidate is UNIQUE_IN_CATALOG (catalog uniqueness only, never auto-write truth)
            status = STATUS_UNIQUE_IN_CATALOG
            candidate_catalog_id = top1["catalogId"]
            ev_source = top1["evidenceSource"] if top1["evidenceSource"] == "PIXEL_TEMPLATE_MATCH" else "CATALOG_UNIQUENESS"
            tpl_reference = top1["templateReference"]
        else:
            # Multi candidates (>1): must satisfy BOTH thresholds for EXACT_IDENTIFIED
            # Catalog-card crops and development pictures rank candidates but
            # are not independently labelled gameplay evidence for this item.
            derived_reference = str(top1.get("templateReference") or "").startswith(("visual/", "video-dev/"))
            if top1_score >= top1_threshold and margin >= margin_threshold and not derived_reference:
                status = STATUS_EXACT_IDENTIFIED
                candidate_catalog_id = top1["catalogId"]
                ev_source = top1["evidenceSource"]
                tpl_reference = top1["templateReference"]
            else:
                status = STATUS_AMBIGUOUS_CANDIDATES
                candidate_catalog_id = None
                ev_source = ("NO_USABLE_VISUAL_SCORE" if top1_score <= 0 else
                             "DERIVED_REFERENCE_CANDIDATE_ONLY" if derived_reference else
                             "PIXEL_TEMPLATE_AMBIGUOUS")
                tpl_reference = top1["templateReference"] if top1_score > 0 else None

        if status == STATUS_EXACT_IDENTIFIED and (
                hypothesis.get("groupingAmbiguous") or hypothesis.get("status") == "AMBIGUOUS_GROUPING"):
            status = STATUS_AMBIGUOUS_CANDIDATES
            candidate_catalog_id = None
            ev_source = "UNRESOLVED_PHYSICAL_BOUNDARY"

        return {
            "schemaVersion": IDENTITY_EVIDENCE_SCHEMA_VERSION,
            "status": status,
            "identityStatus": status,
            "groupingHypothesisId": hypothesis_id,
            "proposalId": proposal_id,
            "recordStableKey": hypothesis.get("recordStableKey"),
            "parentEvidenceId": hypothesis.get("parentEvidenceId"),
            "parentSha256": hypothesis.get("parentSha256"),
            "cropEvidenceId": hypothesis.get("cropEvidenceId"),
            "cropRelativePath": hypothesis.get("cropRelativePath"),
            "cropSha256": hypothesis.get("cropSha256"),
            "candidateCatalogId": candidate_catalog_id,
            "candidateCount": count,
            "candidateCatalogIds": [c["catalogId"] for c in ranked],
            "rankedCandidates": ranked,
            "candidates": ranked,
            "top1Score": top1_score,
            "top2Score": top2_score,
            "margin": margin,
            "evidenceSource": ev_source,
            "templateReference": tpl_reference,
            "cells": hypothesis.get("cells"),
            "bbox": hypothesis.get("bbox"),
            "widthCells": hypothesis.get("widthCells"),
            "heightCells": hypothesis.get("heightCells"),
            "gridShape": hypothesis.get("gridShape"),
            "rarity": hypothesis.get("rarity"),
            "thresholds": {
                "top1ScoreThreshold": top1_threshold,
                "marginThreshold": margin_threshold,
            },
            "catalogVersion": self.catalog_version,
            "catalogFingerprint": self.catalog_fingerprint,
        }

    def resolve_identity_evidence_for_hypotheses(
        self,
        hypotheses: Sequence[Mapping[str, Any]],
        crop_image: Optional[np.ndarray] = None,
        templates: Optional[Mapping[str, Any]] = None,
        top1_threshold: float = DEFAULT_TOP1_SCORE_THRESHOLD,
        margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    ) -> List[Dict[str, Any]]:
        return [
            self.resolve_identity_evidence(
                h,
                crop_image=crop_image,
                templates=templates,
                top1_threshold=top1_threshold,
                margin_threshold=margin_threshold,
            )
            for h in hypotheses
        ]

    def resolve_candidates_for_proposal(self, proposal: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Derive candidate evidence for one visible warehouse proposal.

        Classification:
        - 0 candidates: NO_CATALOG_MATCH
        - 1 candidate: UNIQUE_IN_CATALOG
        - >1 candidates: AMBIGUOUS_CANDIDATES

        Preserves the full candidate set. Never picks candidates[0].
        """
        rarity = str(proposal.get("rarityObservation") or proposal.get("qualityObservation") or "unknown").strip().lower()
        w_cells = int(proposal.get("widthCells") or 1)
        h_cells = int(proposal.get("heightCells") or 1)
        shape_str = str(proposal.get("gridShape") or f"{w_cells}x{h_cells}").strip().lower()

        # Match against catalog
        matched: List[Dict[str, Any]] = list(self._by_shape_rarity.get((shape_str, rarity), []))
        if not matched:
            rev_shape = f"{h_cells}x{w_cells}"
            matched = list(self._by_shape_rarity.get((rev_shape, rarity), []))

        # Deduplicate while preserving deterministic order by catalogId
        dedup_map: Dict[str, Dict[str, Any]] = {}
        for it in matched:
            cid = it["catalogId"]
            if cid not in dedup_map:
                dedup_map[cid] = it
        matched_sorted = [dedup_map[cid] for cid in sorted(dedup_map.keys())]

        count = len(matched_sorted)
        if count == 0:
            status = STATUS_NO_CATALOG_MATCH
        elif count == 1:
            status = STATUS_UNIQUE_IN_CATALOG
        else:
            status = STATUS_AMBIGUOUS_CANDIDATES

        proposal_id = str(proposal.get("proposalId") or "")
        parent_ev_id = str(proposal.get("parentEvidenceId") or "")
        parent_sha = str(proposal.get("parentSha256") or "")
        record_key = str(proposal.get("recordStableKey") or "")

        candidate_evidence = {
            "schemaVersion": SCHEMA_VERSION,
            "candidateEvidenceId": f"cand_{proposal_id}" if proposal_id else "",
            "proposalId": proposal_id,
            "sequenceIndex": proposal.get("sequenceIndex", 0),
            "cropEvidenceId": proposal.get("cropEvidenceId"),
            "cropRelativePath": proposal.get("cropRelativePath"),
            "cropSha256": proposal.get("cropSha256"),
            "parentEvidenceId": parent_ev_id,
            "parentSha256": parent_sha,
            "recordStableKey": record_key,
            "candidateStatus": status,
            "candidateCount": count,
            "candidateCatalogIds": [c["catalogId"] for c in matched_sorted],
            "candidates": [
                {
                    "catalogId": c["catalogId"],
                    "name": c["name"],
                    "quality": c["quality"],
                    "rarity": c["rarity"],
                    "width": c["width"],
                    "height": c["height"],
                    "cells": c["cells"],
                    "value": c["value"],
                }
                for c in matched_sorted
            ],
            "observedConstraints": {
                "quality": proposal.get("qualityObservation"),
                "rarity": proposal.get("rarityObservation"),
                "widthCells": w_cells,
                "heightCells": h_cells,
                "gridShape": shape_str,
                "occupiedCount": proposal.get("occupiedCount"),
            },
            "catalogVersion": self.catalog_version,
            "catalogFingerprint": self.catalog_fingerprint,
            "warehouseCoverage": "PARTIAL",
            "coverageStatus": COVERAGE_UNPROVEN,
        }
        return candidate_evidence

    def resolve_candidates_for_proposals(
        self, proposals: Sequence[Mapping[str, Any]]
    ) -> List[Dict[str, Any]]:
        return [self.resolve_candidates_for_proposal(p) for p in proposals]


def _find_candidate_template(
    cand: Mapping[str, Any],
    templates: Mapping[str, Any],
) -> Tuple[Optional[np.ndarray], Optional[str]]:
    if not templates:
        return None, None

    # 1. Direct template array if attached
    if "template" in cand and isinstance(cand["template"], np.ndarray):
        return cand["template"], str(cand.get("templateReference") or "candidate_direct_template")
    if "templateImage" in cand and isinstance(cand["templateImage"], np.ndarray):
        return cand["templateImage"], str(cand.get("templateReference") or "candidate_direct_template")

    cat_id = str(cand.get("catalogId") or cand.get("Id") or "").strip()
    cand_file = str(cand.get("file") or cand.get("File") or "").strip()
    cand_name = str(cand.get("name") or cand.get("Name") or "").strip()
    live_files = [str(f).strip() for f in (cand.get("liveFiles") or cand.get("LiveFiles") or []) if f]

    # 2. Check exact keys in templates
    if cand_file and cand_file in templates and isinstance(templates[cand_file], np.ndarray):
        return templates[cand_file], cand_file
    if cat_id and cat_id in templates and isinstance(templates[cat_id], np.ndarray):
        return templates[cat_id], cat_id
    if cat_id and f"{cat_id}.png" in templates and isinstance(templates[f"{cat_id}.png"], np.ndarray):
        return templates[f"{cat_id}.png"], f"{cat_id}.png"
    dev_key = f"video-dev/{cat_id}.png"
    if cat_id and dev_key in templates and isinstance(templates[dev_key], np.ndarray):
        return templates[dev_key], dev_key

    # 3. Check live files
    for lf in live_files:
        if lf in templates and isinstance(templates[lf], np.ndarray):
            return templates[lf], lf

    # 4. Check name match or substring match
    for k, v in templates.items():
        if not isinstance(v, np.ndarray):
            continue
        k_norm = k.replace("\\", "/")
        k_base = os.path.basename(k_norm)
        if cat_id and (cat_id == k_base or cat_id in k_norm):
            return v, k
        if cand_file and (cand_file == k_base or cand_file in k_norm):
            return v, k
        if cand_name and len(cand_name) >= 2 and (cand_name in k_base or cand_name in k_norm):
            return v, k

    return None, None


def _match_template_score(
    roi_crop: Optional[np.ndarray],
    tpl: Optional[np.ndarray],
    tpl_ref: Optional[str],
) -> Tuple[float, Optional[str], str]:
    if roi_crop is None or tpl is None or roi_crop.size == 0 or tpl.size == 0:
        return 0.0, tpl_ref, "NO_TEMPLATE" if tpl is None else "EMPTY_ROI"

    roi_h, roi_w = roi_crop.shape[:2]
    if roi_h < 2 or roi_w < 2:
        return 0.0, tpl_ref, "ROI_TOO_SMALL"

    if str(tpl_ref or "").startswith(("visual/", "video-dev/")):
        from visual_catalog import feature_match_evidence
        evidence = feature_match_evidence(roi_crop, tpl)
        source = "VIDEO_DEVELOPMENT_REFERENCE_MATCH" if str(tpl_ref).startswith("video-dev/") else "VISUAL_FEATURE_MATCH"
        return evidence["score"], tpl_ref, source

    try:
        tpl_resized = cv2.resize(tpl, (roi_w, roi_h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(roi_crop, tpl_resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        score = max(0.0, min(1.0, float(max_val)))
        return round(score, 4), tpl_ref, "PIXEL_TEMPLATE_MATCH"
    except Exception:
        return 0.0, tpl_ref, "MATCH_ERROR"


_GLOBAL_RESOLVER: Optional[SettlementCatalogCandidateResolver] = None


def get_global_catalog_candidate_resolver() -> SettlementCatalogCandidateResolver:
    global _GLOBAL_RESOLVER
    if _GLOBAL_RESOLVER is None:
        _GLOBAL_RESOLVER = SettlementCatalogCandidateResolver()
    return _GLOBAL_RESOLVER


def resolve_settlement_catalog_candidate_evidence(
    proposals: Sequence[Mapping[str, Any]],
    resolver: Optional[SettlementCatalogCandidateResolver] = None,
) -> List[Dict[str, Any]]:
    """Convenience helper to resolve candidate evidence for a proposal sequence."""
    res = resolver or get_global_catalog_candidate_resolver()
    return res.resolve_candidates_for_proposals(proposals)


def resolve_settlement_identity_evidence(
    hypothesis: Mapping[str, Any],
    crop_image: Optional[np.ndarray] = None,
    templates: Optional[Mapping[str, Any]] = None,
    resolver: Optional[SettlementCatalogCandidateResolver] = None,
    top1_threshold: float = DEFAULT_TOP1_SCORE_THRESHOLD,
    margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
) -> Dict[str, Any]:
    """Convenience helper to resolve identity evidence for a physical grouping hypothesis."""
    res = resolver or get_global_catalog_candidate_resolver()
    return res.resolve_identity_evidence(
        hypothesis,
        crop_image=crop_image,
        templates=templates,
        top1_threshold=top1_threshold,
        margin_threshold=margin_threshold,
    )

