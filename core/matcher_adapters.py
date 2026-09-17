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


class CurrentMatcherAdapter:
    """Invokes current production OpenCV TM_CCOEFF_NORMED template matching.

    Frozen baseline adapter. Guaranteed not to modify production thresholds,
    crop geometry, or candidate resolution.
    """

    def __init__(
        self,
        *,
        top1_threshold: float = DEFAULT_TOP1_THRESHOLD,
        margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    ):
        self.backend_name = "current_opencv_matcher"
        self.top1_threshold = float(top1_threshold)
        self.margin_threshold = float(margin_threshold)
        self.baseline_code_revision = BASELINE_CODE_REVISION
        self.template_set_revision = TEMPLATE_SET_REVISION
        self.catalog_revision = CATALOG_REVISION
        self.crop_geometry_mode = "cell_aligned_or_source_bbox"
        self.experimental = False
        self.production_eligible = True
        self.default_enabled = True

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "backendName": self.backend_name,
            "baselineCodeRevision": self.baseline_code_revision,
            "templateSetRevision": self.template_set_revision,
            "catalogRevision": self.catalog_revision,
            "thresholds": {
                "top1ScoreThreshold": self.top1_threshold,
                "marginThreshold": self.margin_threshold,
            },
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
        """Compute score using exact production logic."""
        if crop is None or template is None or crop.size == 0 or template.size == 0:
            return {"score": 0.0, "rawNcc": 0.0, "valid": False, "status": "EMPTY_INPUT"}

        crop_h, crop_w = crop.shape[:2]
        if crop_h < 2 or crop_w < 2:
            return {"score": 0.0, "rawNcc": 0.0, "valid": False, "status": "ROI_TOO_SMALL"}

        try:
            tpl_resized = cv2.resize(template, (crop_w, crop_h), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(crop, tpl_resized, cv2.TM_CCOEFF_NORMED)
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
        self.crop_geometry_mode = "cell_aligned_or_source_bbox"
        self.experimental = True
        self.production_eligible = False
        self.default_enabled = False

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "backendName": self.backend_name,
            "baselineCodeRevision": self.baseline_code_revision,
            "templateSetRevision": self.template_set_revision,
            "catalogRevision": self.catalog_revision,
            "thresholds": {
                "top1ScoreThreshold": self.top1_threshold,
                "marginThreshold": self.margin_threshold,
            },
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
        """Compute score using pure NumPy NCC."""
        if crop is None or template is None or crop.size == 0 or template.size == 0:
            return {"score": 0.0, "rawNcc": 0.0, "valid": False, "status": "EMPTY_INPUT"}

        crop_h, crop_w = crop.shape[:2]
        if crop_h < 2 or crop_w < 2:
            return {"score": 0.0, "rawNcc": 0.0, "valid": False, "status": "ROI_TOO_SMALL"}

        res = numpy_ncc_score(crop, template, per_channel=True, resize_template=True)
        return {
            "score": res["score"],
            "rawNcc": res["rawNcc"],
            "valid": res["valid"],
            "status": res["status"],
            "reason": res.get("reason"),
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
