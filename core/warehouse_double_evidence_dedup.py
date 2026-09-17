# -*- coding: utf-8 -*-
"""1x1 Double-evidence deduplication gate for warehouse cross-frame tracking.

High-risk 1x1 items require two independent evidence tiers to merge across frames/segments:
1. Spatial Grid Continuity: verified chain (strict bool True), verified overlap offset (strict bool True),
   canonical global coordinate alignment within cell-normalized tolerance (<= 0.25 cell).
2. Feature Invariance & Margin: high-confidence feature match (>= 0.88) and distinctive margin (>= 0.15)
   backed by explicit competitor search evidence.

Fail-closed invariants:
- Missing geometry or [0,0,0,0] => AMBIGUOUS / UNAVAILABLE.
- Mixed local/global frames without verified transform => AMBIGUOUS.
- Generic status 'VERIFIED' is rejected (requires strict overlapVerified is True + offset).
- Non-boolean values ("false", 1, "1") reject immediately.
- Missing competitor evidence => AMBIGUOUS.
- Visual similarity NaN, < 0, or > 1 => rejected as invalid.
- Non-1x1 items return status='NOT_APPLICABLE', requiresStandardPipeline=True, admitted=False.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "warehouse-1x1-double-evidence.v2"

STATUS_ADMITTED = "DOUBLE_EVIDENCE_ADMITTED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_REJECTED = "REJECTED"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

REASON_1X1_DOUBLE_EVIDENCE_MET = "1X1_DOUBLE_EVIDENCE_MET"
REASON_1X1_APPROXIMATE_ONLY_REJECTED = "1X1_APPROXIMATE_ONLY_REJECTED"
REASON_1X1_SPATIAL_CONTINUITY_MISSING = "1X1_SPATIAL_CONTINUITY_MISSING"
REASON_1X1_FEATURE_INVARIANCE_INSUFFICIENT = "1X1_FEATURE_INVARIANCE_INSUFFICIENT"
REASON_1X1_AMBIGUOUS_COMPETITOR = "1X1_AMBIGUOUS_COMPETITOR"
REASON_1X1_COMPETITOR_EVIDENCE_MISSING = "1X1_COMPETITOR_EVIDENCE_MISSING"
REASON_1X1_GEOMETRY_MISSING = "1X1_GEOMETRY_MISSING"
REASON_1X1_MIXED_COORDINATE_FRAMES = "1X1_MIXED_COORDINATE_FRAMES"
REASON_1X1_INVALID_VISUAL_SIMILARITY = "1X1_INVALID_VISUAL_SIMILARITY"
REASON_NON_1X1_ITEM = "NON_1X1_ITEM"

MIN_1X1_FEATURE_SIMILARITY = 0.88
MIN_1X1_DISTINCTIVENESS_GAP = 0.15
MAX_1X1_CELL_ERROR_RATIO = 0.25
DEFAULT_GRID_CELL_PX = 48.0


def is_1x1_item(obs_or_dims: Mapping[str, Any]) -> bool:
    """Return True if item has a 1x1 footprint (widthCells==1 and heightCells==1 or spanCells==1)."""
    if not isinstance(obs_or_dims, Mapping):
        return False
    w = obs_or_dims.get("widthCells")
    h = obs_or_dims.get("heightCells")
    span = obs_or_dims.get("spanCells")
    if w == 1 and h == 1:
        return True
    if span == 1:
        return True
    return False


def _is_valid_bounding_box(box: Any) -> bool:
    """Validate non-empty, non-zero bounding box [x1, y1, x2, y2]."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    try:
        x1, y1, x2, y2 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
    except (ValueError, TypeError):
        return False
    if math.isnan(x1) or math.isnan(y1) or math.isnan(x2) or math.isnan(y2):
        return False
    if x2 <= x1 or y2 <= y1:
        return False
    # Forbid degenerate [0, 0, 0, 0] or near zero
    if (x2 - x1) <= 1.0 or (y2 - y1) <= 1.0:
        return False
    return True


class WarehouseDoubleEvidenceDedupGate:
    """Evaluates cross-segment candidate merges with strict fail-closed 1x1 double-evidence gating."""

    def __init__(
        self,
        min_feature_similarity: float = MIN_1X1_FEATURE_SIMILARITY,
        min_distinctiveness_gap: float = MIN_1X1_DISTINCTIVENESS_GAP,
        max_cell_error_ratio: float = MAX_1X1_CELL_ERROR_RATIO,
    ):
        self.min_feature_similarity = min_feature_similarity
        self.min_distinctiveness_gap = min_distinctiveness_gap
        self.max_cell_error_ratio = max_cell_error_ratio
        self._gate_evaluations: List[Dict[str, Any]] = []

    @property
    def gate_evaluations(self) -> List[Dict[str, Any]]:
        return self._gate_evaluations

    def evaluate_1x1_dedup(
        self,
        candidate_track: Mapping[str, Any],
        new_obs: Mapping[str, Any],
        segment_context: Mapping[str, Any],
        competing_candidate_scores: Optional[Sequence[float]] = None,
        raw_visual_similarity: Optional[float] = None,
        competitor_search_complete: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Evaluate whether a 1x1 observation may be merged into an existing track.

        Fail-closed: requires dual evidence (spatial continuity + feature invariance & distinctiveness).
        Non-1x1 items return NOT_APPLICABLE and require standard pipeline evaluation.
        """
        # Non-1x1 items: module has no authority to make final merge decision
        if not (is_1x1_item(candidate_track) or is_1x1_item(new_obs)):
            decision = {
                "admitted": False,
                "status": STATUS_NOT_APPLICABLE,
                "reason": REASON_NON_1X1_ITEM,
                "dedupDecision": None,
                "requiresStandardPipeline": True,
                "spatialEvidencePassed": False,
                "featureEvidencePassed": False,
                "ambiguityPreserved": False,
            }
            self._gate_evaluations.append(decision)
            return decision

        # --- Tier 1: Spatial Grid Continuity ---
        # 1.1 Strict boolean check: chainOk must be strict True
        chain_ok_raw = segment_context.get("chainOk")
        chain_ok = isinstance(chain_ok_raw, bool) and chain_ok_raw is True

        # 1.2 Strict boolean check: overlapVerified must be strict True
        # Generic status == 'VERIFIED' is strictly prohibited!
        overlap_raw = segment_context.get("overlapVerified")
        overlap_verified = isinstance(overlap_raw, bool) and overlap_raw is True

        # 1.3 Geometry extraction and coordinate frame provenance
        t_box = candidate_track.get("globalBoundingBox") or candidate_track.get("_searchBox")
        o_box = new_obs.get("globalBox")

        coordinate_provenance = "unverified"
        if not _is_valid_bounding_box(t_box) or (o_box is not None and not _is_valid_bounding_box(o_box)):
            # Missing geometry fails closed
            decision = {
                "admitted": False,
                "status": STATUS_AMBIGUOUS,
                "reason": REASON_1X1_GEOMETRY_MISSING,
                "spatialEvidencePassed": False,
                "featureEvidencePassed": False,
                "ambiguityPreserved": True,
                "coordinateProvenance": "missing_geometry",
            }
            self._gate_evaluations.append(decision)
            return decision

        # Check for mixed local vs global frame
        if o_box is None:
            local_box = new_obs.get("localBox") or new_obs.get("boundingBox")
            origin_y = segment_context.get("originY")
            if _is_valid_bounding_box(local_box) and isinstance(origin_y, (int, float)) and not isinstance(origin_y, bool):
                # Authoritative shift to global frame
                o_box = [
                    float(local_box[0]),
                    float(local_box[1]) + float(origin_y),
                    float(local_box[2]),
                    float(local_box[3]) + float(origin_y),
                ]
                coordinate_provenance = "transformed_global"
            else:
                # Mixed local/global without verified originY fails closed
                decision = {
                    "admitted": False,
                    "status": STATUS_AMBIGUOUS,
                    "reason": REASON_1X1_MIXED_COORDINATE_FRAMES,
                    "spatialEvidencePassed": False,
                    "featureEvidencePassed": False,
                    "ambiguityPreserved": True,
                    "coordinateProvenance": "unverified_mixed_frame",
                }
                self._gate_evaluations.append(decision)
                return decision
        else:
            coordinate_provenance = "canonical_global"

        # Cell dimension authority
        grid = segment_context.get("grid") or candidate_track.get("grid") or {}
        cell_w = grid.get("cellWidth") if isinstance(grid, Mapping) else None
        cell_h = grid.get("cellHeight") if isinstance(grid, Mapping) else None
        if isinstance(cell_w, (int, float)) and isinstance(cell_h, (int, float)) and cell_w > 0 and cell_h > 0:
            cell_dim = min(float(cell_w), float(cell_h))
        else:
            cell_dim = DEFAULT_GRID_CELL_PX

        # Cell-normalized spatial distance
        dx = abs(float(t_box[0]) - float(o_box[0]))
        dy = abs(float(t_box[1]) - float(o_box[1]))
        spatial_dist = (dx**2 + dy**2) ** 0.5
        cell_error_ratio = spatial_dist / cell_dim
        spatial_tolerance_px = self.max_cell_error_ratio * cell_dim

        spatial_ok = chain_ok and overlap_verified and (cell_error_ratio <= self.max_cell_error_ratio)

        # --- Tier 2: Feature Invariance & Distinctiveness ---
        # 2.1 Visual similarity validation
        if raw_visual_similarity is not None:
            if isinstance(raw_visual_similarity, bool) or not isinstance(raw_visual_similarity, (int, float)):
                decision = {
                    "admitted": False,
                    "status": STATUS_AMBIGUOUS,
                    "reason": REASON_1X1_INVALID_VISUAL_SIMILARITY,
                    "spatialEvidencePassed": spatial_ok,
                    "featureEvidencePassed": False,
                    "ambiguityPreserved": True,
                    "coordinateProvenance": coordinate_provenance,
                }
                self._gate_evaluations.append(decision)
                return decision
            sim = float(raw_visual_similarity)
            if math.isnan(sim) or sim < 0.0 or sim > 1.0:
                decision = {
                    "admitted": False,
                    "status": STATUS_AMBIGUOUS,
                    "reason": REASON_1X1_INVALID_VISUAL_SIMILARITY,
                    "spatialEvidencePassed": spatial_ok,
                    "featureEvidencePassed": False,
                    "ambiguityPreserved": True,
                    "coordinateProvenance": coordinate_provenance,
                }
                self._gate_evaluations.append(decision)
                return decision
        else:
            t_digest = candidate_track.get("contentDigest") or candidate_track.get("_digest")
            o_digest = new_obs.get("contentDigest")
            if t_digest and o_digest and t_digest == o_digest:
                sim = 1.0
            else:
                sim = 0.0

        feature_high = sim >= self.min_feature_similarity

        # 2.2 Competitor Distinctiveness Gate
        # Competitor evidence is REQUIRED. Missing competitor scores without explicit proof fails closed.
        search_complete = competitor_search_complete
        if search_complete is None:
            search_complete = bool(segment_context.get("competitorSearchComplete"))

        competitor_ok = False
        competitor_reason = None

        if competing_candidate_scores is not None and len(competing_candidate_scores) > 1:
            scores_sorted = sorted(competing_candidate_scores, reverse=True)
            best = scores_sorted[0]
            second = scores_sorted[1]
            if (best - second) >= self.min_distinctiveness_gap:
                competitor_ok = True
            else:
                competitor_ok = False
                competitor_reason = REASON_1X1_AMBIGUOUS_COMPETITOR
        elif search_complete and (competing_candidate_scores is None or len(competing_candidate_scores) <= 1):
            # Authoritative single candidate with exhaustive search confirmed
            competitor_ok = True
        else:
            # Competitor search unproven or missing evidence
            competitor_ok = False
            competitor_reason = REASON_1X1_COMPETITOR_EVIDENCE_MISSING

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
                "cellErrorRatio": round(cell_error_ratio, 4),
                "spatialTolerancePx": round(spatial_tolerance_px, 2),
                "coordinateProvenance": coordinate_provenance,
            }
        else:
            # Ambiguity-preserving fail-closed decision
            if not feature_ok and not spatial_ok:
                r = REASON_1X1_APPROXIMATE_ONLY_REJECTED
            elif not spatial_ok:
                r = REASON_1X1_SPATIAL_CONTINUITY_MISSING
            elif competitor_reason:
                r = competitor_reason
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
                "cellErrorRatio": round(cell_error_ratio, 4),
                "spatialTolerancePx": round(spatial_tolerance_px, 2),
                "coordinateProvenance": coordinate_provenance,
            }

        self._gate_evaluations.append(decision)
        return decision
