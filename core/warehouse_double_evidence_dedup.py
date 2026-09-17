# -*- coding: utf-8 -*-
"""1x1 Double-evidence deduplication gate for warehouse cross-frame tracking.

High-risk 1x1 items require two independent evidence tiers to merge across frames/segments:
1. Spatial Grid Continuity: verified chain, verified overlap offset, cell-aligned bounding box.
2. Feature Invariance & Margin: high-confidence feature match (>= 0.88) and distinctive margin (>= 0.15).

Approximate visual similarity alone is strictly prohibited from merging 1x1 items.
Ambiguous items are retained as AMBIGUOUS without forced exact collapse.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "warehouse-1x1-double-evidence.v1"

STATUS_ADMITTED = "DOUBLE_EVIDENCE_ADMITTED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_REJECTED = "REJECTED"

REASON_1X1_DOUBLE_EVIDENCE_MET = "1X1_DOUBLE_EVIDENCE_MET"
REASON_1X1_APPROXIMATE_ONLY_REJECTED = "1X1_APPROXIMATE_ONLY_REJECTED"
REASON_1X1_SPATIAL_CONTINUITY_MISSING = "1X1_SPATIAL_CONTINUITY_MISSING"
REASON_1X1_FEATURE_INVARIANCE_INSUFFICIENT = "1X1_FEATURE_INVARIANCE_INSUFFICIENT"
REASON_1X1_AMBIGUOUS_COMPETITOR = "1X1_AMBIGUOUS_COMPETITOR"

MIN_1X1_FEATURE_SIMILARITY = 0.88
MIN_1X1_DISTINCTIVENESS_GAP = 0.15
MAX_1X1_SPATIAL_ALIGN_ERROR_PX = 12.0


def is_1x1_item(obs_or_dims: Mapping[str, Any]) -> bool:
    """Return True if item has a 1x1 footprint (widthCells==1 and heightCells==1 or spanCells==1)."""
    w = obs_or_dims.get("widthCells")
    h = obs_or_dims.get("heightCells")
    span = obs_or_dims.get("spanCells")
    if w == 1 and h == 1:
        return True
    if span == 1:
        return True
    return False


class WarehouseDoubleEvidenceDedupGate:
    """Evaluates cross-segment candidate merges with strict 1x1 double-evidence gating."""

    def __init__(
        self,
        min_feature_similarity: float = MIN_1X1_FEATURE_SIMILARITY,
        min_distinctiveness_gap: float = MIN_1X1_DISTINCTIVENESS_GAP,
        max_spatial_align_error_px: float = MAX_1X1_SPATIAL_ALIGN_ERROR_PX,
    ):
        self.min_feature_similarity = min_feature_similarity
        self.min_distinctiveness_gap = min_distinctiveness_gap
        self.max_spatial_align_error_px = max_spatial_align_error_px
        self._gate_evaluations: List[Dict[str, Any]] = []

    def evaluate_1x1_dedup(
        self,
        candidate_track: Mapping[str, Any],
        new_obs: Mapping[str, Any],
        segment_context: Mapping[str, Any],
        competing_candidate_scores: Optional[Sequence[float]] = None,
        raw_visual_similarity: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Evaluate whether a 1x1 observation may be merged into an existing track.

        Returns:
            {
                "admitted": bool,
                "status": "DOUBLE_EVIDENCE_ADMITTED" | "AMBIGUOUS" | "REJECTED",
                "reason": str,
                "spatialEvidencePassed": bool,
                "featureEvidencePassed": bool,
                "ambiguityPreserved": bool,
            }
        """
        # Non-1x1 items bypass the high-risk 1x1 gate
        if not (is_1x1_item(candidate_track) or is_1x1_item(new_obs)):
            return {
                "admitted": True,
                "status": "NON_1X1_STANDARD_EVAL",
                "reason": "NON_1X1_ITEM",
                "spatialEvidencePassed": True,
                "featureEvidencePassed": True,
                "ambiguityPreserved": False,
            }

        # --- Tier 1: Spatial Grid Continuity ---
        chain_ok = bool(segment_context.get("chainOk"))
        overlap_verified = bool(
            segment_context.get("overlapVerified") or segment_context.get("status") == "VERIFIED"
        )
        # Compute spatial coordinate distance
        t_box = candidate_track.get("globalBoundingBox") or candidate_track.get("_searchBox") or [0, 0, 0, 0]
        o_box = new_obs.get("globalBox") or new_obs.get("localBox") or [0, 0, 0, 0]

        dx = abs(float(t_box[0]) - float(o_box[0]))
        dy = abs(float(t_box[1]) - float(o_box[1]))
        spatial_dist = (dx**2 + dy**2) ** 0.5
        spatial_ok = chain_ok and overlap_verified and (spatial_dist <= self.max_spatial_align_error_px)

        # --- Tier 2: Feature Invariance & Distinctiveness ---
        if raw_visual_similarity is not None:
            sim = float(raw_visual_similarity)
        else:
            t_digest = candidate_track.get("contentDigest") or candidate_track.get("_digest")
            o_digest = new_obs.get("contentDigest")
            if t_digest and o_digest and t_digest == o_digest:
                sim = 1.0
            else:
                sim = 0.0

        feature_high = sim >= self.min_feature_similarity

        # Competitor gap check
        competitor_ok = True
        if competing_candidate_scores and len(competing_candidate_scores) > 1:
            scores_sorted = sorted(competing_candidate_scores, reverse=True)
            best = scores_sorted[0]
            second = scores_sorted[1]
            if (best - second) < self.min_distinctiveness_gap:
                competitor_ok = False

        feature_ok = feature_high and competitor_ok

        # Decision
        if spatial_ok and feature_ok:
            decision = {
                "admitted": True,
                "status": STATUS_ADMITTED,
                "reason": REASON_1X1_DOUBLE_EVIDENCE_MET,
                "spatialEvidencePassed": True,
                "featureEvidencePassed": True,
                "ambiguityPreserved": False,
                "visualSimilarity": round(sim, 4),
                "spatialDistance": round(spatial_dist, 2),
            }
        else:
            # Preserve ambiguity! Never force exact collapse.
            if not feature_ok and not spatial_ok:
                r = REASON_1X1_APPROXIMATE_ONLY_REJECTED
            elif not spatial_ok:
                r = REASON_1X1_SPATIAL_CONTINUITY_MISSING
            elif not competitor_ok:
                r = REASON_1X1_AMBIGUOUS_COMPETITOR
            else:
                r = REASON_1X1_FEATURE_INVARIANCE_INSUFFICIENT

            decision = {
                "admitted": False,
                "status": STATUS_AMBIGUOUS,
                "reason": r,
                "spatialEvidencePassed": spatial_ok,
                "featureEvidencePassed": feature_ok,
                "ambiguityPreserved": True,
                "visualSimilarity": round(sim, 4),
                "spatialDistance": round(spatial_dist, 2),
            }

        self._gate_evaluations.append(decision)
        return decision
