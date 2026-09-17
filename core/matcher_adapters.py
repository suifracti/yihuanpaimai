# -*- coding: utf-8 -*-
"""Matcher Adapters for Benchmark Comparison: Production Baseline vs Pure NumPy NCC.

Ensures strict parity in candidate generation, input geometry, candidate templates,
and decision thresholds between the formal production OpenCV matcher and the
experimental NumPy NCC matcher.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import cv2
import numpy as np

from experimental_template_ncc import numpy_ncc_score

SCHEMA_VERSION = "matcher-adapter.v1"
BASELINE_CODE_REVISION = "22db57fcad74ab48122250bba37c886d842becba"
TEMPLATE_SET_REVISION = "catalog-reference-crops.v1 (213 templates)"
CATALOG_REVISION = "catalog_065.v1+visual-catalog.v2"

DEFAULT_TOP1_THRESHOLD = 0.85
DEFAULT_MARGIN_THRESHOLD = 0.08
ACTUAL_PRODUCTION_ENTRY = "core.warehouse_vision.WarehouseVisionPipeline.process_frame"
CANDIDATE_GENERATOR = "core.warehouse_vision.WarehouseTemplateMatcher.get_candidates"
SCORE_AUTHORITY = "core.warehouse_vision.WarehouseTemplateMatcher.match_candidates (cv2.matchTemplate, cv2.TM_CCOEFF_NORMED)"
THRESHOLD_AUTHORITY = "core.warehouse_vision.WarehouseVisionConfig (MATCH_CONFIDENCE_THRESHOLD=0.85, MATCH_MARGIN_THRESHOLD=0.08)"
AMBIGUITY_AUTHORITY = "core.warehouse_vision.EvidenceLevel (EXACT_IDENTIFIED vs CANDIDATE_SET)"


def prepare_matching_pair(
    crop: np.ndarray,
    template: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Shared preprocessing: prepare crop and template pair to identical spatial dimensions.

    Standardizes spatial dimensions once using cv2.INTER_AREA on the template
    if template shape differs from crop shape. Produces immutable (read-only)
    arrays so neither downstream backend can mutate them or perform backend-specific
    resizing.

    Returns:
        (crop_prepared, template_prepared) with flags.writeable = False.
    """
    if crop is None or template is None or crop.size == 0 or template.size == 0:
        return crop, template

    crop_h, crop_w = crop.shape[:2]
    tpl_h, tpl_w = template.shape[:2]

    if (crop_h, crop_w) == (tpl_h, tpl_w):
        tpl_eval = template.copy()
    else:
        tpl_eval = cv2.resize(template, (crop_w, crop_h), interpolation=cv2.INTER_AREA)

    crop_eval = crop.copy()
    crop_eval.flags.writeable = False
    tpl_eval.flags.writeable = False
    return crop_eval, tpl_eval


class OpenCvScorerBaselineAdapter:
    """Scorer replica baseline of production OpenCV TM_CCOEFF_NORMED template matching.

    Classified as scorer_replica rather than direct production authority because it
    evaluates a pre-filtered candidate set instead of running the full warehouse pipeline.
    Thresholds and decision logic are identical to production WarehouseVisionConfig.
    """

    def __init__(
        self,
        *,
        top1_threshold: float = DEFAULT_TOP1_THRESHOLD,
        margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    ):
        self.backend_name = "opencv_scorer_baseline"
        self.top1_threshold = float(top1_threshold)
        self.margin_threshold = float(margin_threshold)
        self.baseline_code_revision = BASELINE_CODE_REVISION
        self.template_set_revision = TEMPLATE_SET_REVISION
        self.catalog_revision = CATALOG_REVISION
        self.crop_geometry_mode = "cell_aligned_or_source_bbox"
        self.adapter_reuse_mode = "scorer_replica"
        self.full_production_matcher_equivalent = False
        self.preprocessing_shared = True
        self.backend_specific_resize = False
        self.scorer_parity_scope = "scoring_kernel_after_candidate_generation"
        self.experimental = False
        self.production_eligible = True
        self.default_enabled = True

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "backendName": self.backend_name,
            "adapterReuseMode": self.adapter_reuse_mode,
            "fullProductionMatcherEquivalent": self.full_production_matcher_equivalent,
            "actualProductionEntry": ACTUAL_PRODUCTION_ENTRY,
            "candidateGenerator": CANDIDATE_GENERATOR,
            "scoreAuthority": SCORE_AUTHORITY,
            "thresholdAuthority": THRESHOLD_AUTHORITY,
            "ambiguityAuthority": AMBIGUITY_AUTHORITY,
            "scorerParityScope": self.scorer_parity_scope,
            "baselineCodeRevision": self.baseline_code_revision,
            "templateSetRevision": self.template_set_revision,
            "catalogRevision": self.catalog_revision,
            "thresholdProvenance": "core.warehouse_vision.WarehouseVisionConfig",
            "thresholds": {
                "top1ScoreThreshold": self.top1_threshold,
                "marginThreshold": self.margin_threshold,
            },
            "preprocessingShared": self.preprocessing_shared,
            "backendSpecificResize": self.backend_specific_resize,
            "cropGeometryMode": self.crop_geometry_mode,
            "experimental": self.experimental,
            "productionEligible": self.production_eligible,
            "defaultEnabled": self.default_enabled,
        }

    def score_single_pair(
        self,
        crop: np.ndarray,
        template: np.ndarray,
    ) -> Dict[str, Any]:
        """Compute score using shared preprocessed pair and OpenCV TM_CCOEFF_NORMED."""
        if crop is None or template is None or crop.size == 0 or template.size == 0:
            return {"score": 0.0, "rawNcc": 0.0, "valid": False, "status": "EMPTY_INPUT"}

        crop_h, crop_w = crop.shape[:2]
        if crop_h < 2 or crop_w < 2:
            return {"score": 0.0, "rawNcc": 0.0, "valid": False, "status": "ROI_TOO_SMALL"}

        try:
            crop_pre, tpl_pre = prepare_matching_pair(crop, template)
            res = cv2.matchTemplate(crop_pre, tpl_pre, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            raw_val = float(max_val)
            score = max(0.0, min(1.0, raw_val))
            return {
                "score": round(score, 4),
                "rawNcc": round(raw_val, 6),
                "valid": True,
                "status": "SUCCESS",
            }
        except Exception as exc:
            return {
                "score": 0.0,
                "rawNcc": 0.0,
                "valid": False,
                "status": "MATCH_ERROR",
                "reason": str(exc),
            }

    def evaluate_candidates(
        self,
        crop: np.ndarray,
        candidates: Sequence[Mapping[str, Any]],
        templates: Mapping[str, np.ndarray],
    ) -> Dict[str, Any]:
        """Evaluate and rank candidates using production OpenCV matcher."""
        t0 = time.perf_counter()
        ranked = []

        for cand in candidates:
            cid = cand.get("catalogId")
            tpl = templates.get(cid)
            name = cand.get("name") or cid
            val = cand.get("value") or cand.get("price") or 0

            if tpl is None:
                ranked.append({
                    "catalogId": cid,
                    "name": name,
                    "value": val,
                    "score": 0.0,
                    "rawNcc": 0.0,
                    "evidenceSource": "NO_TEMPLATE",
                    "valid": False,
                })
                continue

            pair_res = self.score_single_pair(crop, tpl)
            ranked.append({
                "catalogId": cid,
                "name": name,
                "value": val,
                "score": pair_res["score"],
                "rawNcc": pair_res["rawNcc"],
                "evidenceSource": "PIXEL_TEMPLATE_MATCH",
                "valid": pair_res["valid"],
            })

        # Sort descending by score, tie-break by catalogId for deterministic stability
        ranked.sort(key=lambda x: (-x["score"], str(x["catalogId"])))

        top1_score = ranked[0]["score"] if ranked else 0.0
        top2_score = ranked[1]["score"] if len(ranked) > 1 else 0.0
        margin = round(top1_score - top2_score, 4)

        status = "NO_CANDIDATES"
        exact_id = None
        exact_name = None

        if ranked:
            if top1_score >= self.top1_threshold and margin >= self.margin_threshold:
                status = "EXACT_IDENTIFIED"
                exact_id = ranked[0]["catalogId"]
                exact_name = ranked[0]["name"]
            else:
                status = "AMBIGUOUS_CANDIDATES"

        latency = time.perf_counter() - t0

        return {
            "backendName": self.backend_name,
            "status": status,
            "exactCatalogId": exact_id,
            "exactName": exact_name,
            "top1Score": top1_score,
            "top2Score": top2_score,
            "margin": margin,
            "candidateCount": len(candidates),
            "rankedCandidates": ranked,
            "latencySeconds": latency,
            "backendMetadata": self.get_metadata(),
        }


class NumpyNccMatcherAdapter:
    """Invokes pure NumPy NCC template matching.

    Experimental adapter. Guaranteed parity with candidate set and thresholds.
    Never promoted to default enabled in production.
    """

    def __init__(
        self,
        *,
        top1_threshold: float = DEFAULT_TOP1_THRESHOLD,
        margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    ):
        self.backend_name = "experimental_numpy_ncc"
        self.top1_threshold = float(top1_threshold)
        self.margin_threshold = float(margin_threshold)
        self.baseline_code_revision = BASELINE_CODE_REVISION
        self.template_set_revision = TEMPLATE_SET_REVISION
        self.catalog_revision = CATALOG_REVISION
        self.adapter_reuse_mode = "experimental_evaluator"
        self.full_production_matcher_equivalent = False
        self.math_kernel = "pure_numpy"
        self.preprocessing_shared = True
        self.backend_specific_resize = False
        self.crop_geometry_mode = "cell_aligned_or_source_bbox"
        self.scorer_parity_scope = "scoring_kernel_after_candidate_generation"
        self.experimental = True
        self.production_eligible = False
        self.default_enabled = False

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "backendName": self.backend_name,
            "adapterReuseMode": self.adapter_reuse_mode,
            "fullProductionMatcherEquivalent": self.full_production_matcher_equivalent,
            "mathKernel": self.math_kernel,
            "actualProductionEntry": ACTUAL_PRODUCTION_ENTRY,
            "candidateGenerator": CANDIDATE_GENERATOR,
            "scoreAuthority": SCORE_AUTHORITY,
            "thresholdAuthority": THRESHOLD_AUTHORITY,
            "ambiguityAuthority": AMBIGUITY_AUTHORITY,
            "scorerParityScope": self.scorer_parity_scope,
            "baselineCodeRevision": self.baseline_code_revision,
            "templateSetRevision": self.template_set_revision,
            "catalogRevision": self.catalog_revision,
            "thresholdProvenance": "core.warehouse_vision.WarehouseVisionConfig",
            "thresholds": {
                "top1ScoreThreshold": self.top1_threshold,
                "marginThreshold": self.margin_threshold,
            },
            "preprocessingShared": self.preprocessing_shared,
            "backendSpecificResize": self.backend_specific_resize,
            "cropGeometryMode": self.crop_geometry_mode,
            "experimental": self.experimental,
            "productionEligible": self.production_eligible,
            "defaultEnabled": self.default_enabled,
        }

    def score_single_pair(
        self,
        crop: np.ndarray,
        template: np.ndarray,
    ) -> Dict[str, Any]:
        """Compute score using shared preprocessed pair and pure NumPy NCC."""
        if crop is None or template is None or crop.size == 0 or template.size == 0:
            return {"score": 0.0, "rawNcc": 0.0, "valid": False, "status": "EMPTY_INPUT"}

        crop_h, crop_w = crop.shape[:2]
        if crop_h < 2 or crop_w < 2:
            return {"score": 0.0, "rawNcc": 0.0, "valid": False, "status": "ROI_TOO_SMALL"}

        try:
            crop_pre, tpl_pre = prepare_matching_pair(crop, template)
            res = numpy_ncc_score(crop_pre, tpl_pre, per_channel=True)
            return {
                "score": res["score"],
                "rawNcc": res["rawNcc"],
                "valid": res["valid"],
                "status": res["status"],
                "reason": res.get("reason"),
            }
        except Exception as exc:
            return {
                "score": 0.0,
                "rawNcc": 0.0,
                "valid": False,
                "status": "MATCH_ERROR",
                "reason": str(exc),
            }

    def evaluate_candidates(
        self,
        crop: np.ndarray,
        candidates: Sequence[Mapping[str, Any]],
        templates: Mapping[str, np.ndarray],
    ) -> Dict[str, Any]:
        """Evaluate and rank candidates using pure NumPy NCC matcher."""
        t0 = time.perf_counter()
        ranked = []

        for cand in candidates:
            cid = cand.get("catalogId")
            tpl = templates.get(cid)
            name = cand.get("name") or cid
            val = cand.get("value") or cand.get("price") or 0

            if tpl is None:
                ranked.append({
                    "catalogId": cid,
                    "name": name,
                    "value": val,
                    "score": 0.0,
                    "rawNcc": 0.0,
                    "evidenceSource": "NO_TEMPLATE",
                    "valid": False,
                })
                continue

            pair_res = self.score_single_pair(crop, tpl)
            ranked.append({
                "catalogId": cid,
                "name": name,
                "value": val,
                "score": pair_res["score"],
                "rawNcc": pair_res["rawNcc"],
                "evidenceSource": "NUMPY_NCC_MATCH",
                "valid": pair_res["valid"],
            })

        # Sort descending by score, tie-break by catalogId for deterministic stability
        ranked.sort(key=lambda x: (-x["score"], str(x["catalogId"])))

        top1_score = ranked[0]["score"] if ranked else 0.0
        top2_score = ranked[1]["score"] if len(ranked) > 1 else 0.0
        margin = round(top1_score - top2_score, 4)

        status = "NO_CANDIDATES"
        exact_id = None
        exact_name = None

        if ranked:
            if top1_score >= self.top1_threshold and margin >= self.margin_threshold:
                status = "EXACT_IDENTIFIED"
                exact_id = ranked[0]["catalogId"]
                exact_name = ranked[0]["name"]
            else:
                status = "AMBIGUOUS_CANDIDATES"

        latency = time.perf_counter() - t0

        return {
            "backendName": self.backend_name,
            "status": status,
            "exactCatalogId": exact_id,
            "exactName": exact_name,
            "top1Score": top1_score,
            "top2Score": top2_score,
            "margin": margin,
            "candidateCount": len(candidates),
            "rankedCandidates": ranked,
            "latencySeconds": latency,
            "backendMetadata": self.get_metadata(),
        }


# Backwards compatibility alias
CurrentMatcherAdapter = OpenCvScorerBaselineAdapter

