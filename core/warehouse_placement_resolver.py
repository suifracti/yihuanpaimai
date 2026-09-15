"""Production placement resolver for warehouse review packet v2.

Resolves physical component fragments into discrete world-anchored item placements
using gutter geometry, visual evidence against catalog reference crops,
temporal multi-frame consistency, and global non-overlapping selection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import cv2
import numpy as np

from catalog_validator import validate_catalog_record, validate_item_identity
from warehouse_grid_geometry import STATUS_OK as GRID_OK, observe_warehouse_grid


def application_asset_root() -> Path:
    """Source repo root, or the PyInstaller resource root when frozen."""
    frozen_root = getattr(sys, "_MEIPASS", None) if getattr(sys, "frozen", False) else None
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT = application_asset_root()
DEFAULT_MANIFEST_PATH_V2 = PROJECT_ROOT / "assets" / "items" / "catalog_reference_manifest_v2.json"
DEFAULT_MANIFEST_PATH = DEFAULT_MANIFEST_PATH_V2 if DEFAULT_MANIFEST_PATH_V2.is_file() else (PROJECT_ROOT / "assets" / "items" / "catalog_reference_manifest_v1.json")
DEFAULT_CROPS_DIR = PROJECT_ROOT / "assets" / "items" / "reference_crops_v1"


def pure_valley_gutter(
    img: np.ndarray,
    p_bound: int,
    p_range: Tuple[int, int],
    orientation: str = "v",
    e1: bool = False,
    e2: bool = False,
) -> float:
    """Measures the physical groove / valley along a grid line."""
    if e1 and e2:
        return 0.0
    if e1 or e2:
        return 1.0  # True boundary against empty grid slot

    if orientation == "v":
        x_bound, (y_top, y_bot) = p_bound, p_range
        if y_bot - y_top < 12:
            return 0.5
        if x_bound - 12 < 0 or x_bound + 13 > img.shape[1]:
            return 0.5
        strip = img[y_top + 6 : y_bot - 6, x_bound - 12 : x_bound + 13]
        if strip.size == 0:
            return 0.0
        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        prof = gray.mean(axis=0)
        L = len(prof)
        if L < 15:
            return 0.0
        mid = L // 2
        search_range = prof[mid - 6 : mid + 7]
        min_val = min(search_range)
        min_idx = mid - 6 + list(search_range).index(min_val)
        bank1 = prof[max(0, min_idx - 10) : max(1, min_idx - 3)]
        bank2 = prof[min(L - 1, min_idx + 4) : min(L, min_idx + 11)]
        if len(bank1) == 0 or len(bank2) == 0:
            return 0.0
        valley = min(bank1.mean(), bank2.mean()) - min_val
        if valley > 9.5 and min_val <= 38.0:
            return float(min(1.0, 0.4 + (valley - 9.5) / 25.0))
        return 0.0
    else:  # orientation == "h"
        y_bound, (x_left, x_right) = p_bound, p_range
        if x_right - x_left < 12:
            return 0.5
        if y_bound - 12 < 0 or y_bound + 13 > img.shape[0]:
            return 0.5
        strip = img[y_bound - 12 : y_bound + 13, x_left + 6 : x_right - 6]
        if strip.size == 0:
            return 0.0
        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        prof = gray.mean(axis=1)
        L = len(prof)
        if L < 15:
            return 0.0
        mid = L // 2
        search_range = prof[mid - 6 : mid + 7]
        min_val = min(search_range)
        min_idx = mid - 6 + list(search_range).index(min_val)
        bank1 = prof[max(0, min_idx - 10) : max(1, min_idx - 3)]
        bank2 = prof[min(L - 1, min_idx + 4) : min(L, min_idx + 11)]
        if len(bank1) == 0 or len(bank2) == 0:
            return 0.0
        valley = min(bank1.mean(), bank2.mean()) - min_val
        if valley > 9.5 and min_val <= 38.0:
            return float(min(1.0, 0.4 + (valley - 9.5) / 25.0))
        return 0.0


class WarehousePlacementResolver:
    """Resolves raw fragment tracks into discrete world-anchored Review Units."""

    def __init__(
        self,
        *,
        manifest_path: Optional[Path | str] = None,
        crops_dir: Optional[Path | str] = None,
        root: Optional[Path | str] = None,
    ):
        self._root = Path(root) if root else PROJECT_ROOT
        if manifest_path:
            self._manifest_path = Path(manifest_path)
        else:
            manifest_v2 = self._root / "assets" / "items" / "catalog_reference_manifest_v2.json"
            self._manifest_path = manifest_v2 if manifest_v2.is_file() else (self._root / "assets" / "items" / "catalog_reference_manifest_v1.json")
        self._crops_dir = Path(crops_dir) if crops_dir else (self._root / "assets" / "items" / "reference_crops_v1")
        self._sift = cv2.SIFT_create()
        self._matcher = cv2.BFMatcher()
        self._ref_cache: Dict[str, Dict[str, Any]] = {}
        self._small_icon_sift = cv2.SIFT_create(sigma=0.8)
        self._small_icon_reference_features = {}
        self._load_reference_cache()

    def _load_reference_cache(self) -> None:
        if not self._manifest_path.is_file():
            return
        from visual_catalog import _catalog_reference_body
        manifest_data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        for rec in manifest_data.get("records", []):
            cid = str(rec.get("catalogId") or "")
            rel = rec.get("cropRelativePath")
            if not cid or not rel:
                continue
            validate_catalog_record(rec, root=self._root)
            crop_path = self._root / rel
            if not crop_path.is_file():
                continue
            data = np.fromfile(str(crop_path), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None:
                continue
            kp, des = self._sift.detectAndCompute(img, None)
            body = _catalog_reference_body(img)
            kp_body, des_body = self._sift.detectAndCompute(body, None)
            self._ref_cache[cid] = {
                "entry": rec,
                "img": img,
                "body": body,
                "kp": kp,
                "des": des,
                "kp_body": kp_body,
                "des_body": des_body,
                "widthCells": int(rec.get("widthCells") or 1),
                "heightCells": int(rec.get("heightCells") or 1),
            }

    @staticmethod
    def _distinct_feature_matches(matches, source_keypoints, target_keypoints):
        """Count spatial correspondences, not SIFT orientation descriptors.

        SIFT may describe one location at multiple orientations. Both ends of
        a correspondence must be unique before fitting or counting a model.
        """
        selected = []
        source_points, target_points = [], []
        for match in sorted(matches, key=lambda m: (m.distance, m.queryIdx, m.trainIdx)):
            source = np.asarray(source_keypoints[match.queryIdx].pt)
            target = np.asarray(target_keypoints[match.trainIdx].pt)
            if any(np.linalg.norm(source - point) <= 0.5 for point in source_points):
                continue
            if any(np.linalg.norm(target - point) <= 0.5 for point in target_points):
                continue
            selected.append(match)
            source_points.append(source)
            target_points.append(target)
        return selected

    def _compute_sift_inliers(
        self,
        roi: np.ndarray,
        ref_entry: Dict[str, Any],
        roi_kp_des: Optional[Tuple[Any, Any]] = None,
    ) -> int:
        if roi is None or roi.size == 0:
            return 0
        if roi_kp_des is not None:
            kp2, des2 = roi_kp_des
        else:
            kp2, des2 = self._sift.detectAndCompute(roi, None)
        if des2 is None or len(des2) < 4:
            return 0

        best_inl = 0
        ref_views = []
        if ref_entry.get("des_body") is not None:
            ref_views.append((ref_entry["kp_body"], ref_entry["des_body"]))
        if ref_entry.get("des") is not None:
            ref_views.append((ref_entry["kp"], ref_entry["des"]))

        for kp1, des1 in ref_views:
            if des1 is None or len(des1) < 4:
                continue
            matches = self._matcher.knnMatch(des1, des2, k=2)
            good = [pair[0] for pair in matches if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance]
            good = self._distinct_feature_matches(good, kp1, kp2)
            if len(good) < 4:
                continue
            src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

            # 1. Similarity transformation via RANSAC (scale, rotation, translation)
            M, m_mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=5.0)
            if M is not None and m_mask is not None:
                det_m = M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]
                if det_m > 0:
                    scale_m = np.sqrt(det_m)
                    # Non-degenerate UI scale limits:
                    # 1x1 on ~56-75px cell vs 366px card -> s ~ 0.15-0.20
                    # 5x5 on ~375px cell vs 366px card -> s ~ 1.0-2.5
                    if 0.08 <= scale_m <= 3.0:
                        inlier_dst = dst[m_mask.ravel() == 1].reshape(-1, 2)
                        inlier_matches = [good[i] for i in range(len(good)) if m_mask.ravel()[i]]
                        uniq_dst = len(set(m.trainIdx for m in inlier_matches))
                        if uniq_dst >= 4 and max(np.std(inlier_dst[:, 0]), np.std(inlier_dst[:, 1])) >= 2.0:
                            best_inl = max(best_inl, uniq_dst)

            # 2. Planar homography via RANSAC with strict normalization, perspective bounds, and aspect preservation
            H, h_mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
            if H is not None and h_mask is not None and abs(H[2, 2]) > 1e-7:
                H_norm = H / H[2, 2]
                det_h = H_norm[0, 0] * H_norm[1, 1] - H_norm[0, 1] * H_norm[1, 0]
                if det_h > 0:
                    scale_h = np.sqrt(det_h)
                    # Perspective distortion limits for 2D UI plane
                    if 0.08 <= scale_h <= 3.0 and abs(H_norm[2, 0]) < 0.015 and abs(H_norm[2, 1]) < 0.015:
                        A = H_norm[:2, :2]
                        U, S, Vt = np.linalg.svd(A)
                        if S[1] >= 1e-5 and (S[0] / S[1]) <= 1.40:
                            inlier_dst = dst[h_mask.ravel() == 1].reshape(-1, 2)
                            inlier_matches = [good[i] for i in range(len(good)) if h_mask.ravel()[i]]
                            uniq_dst = len(set(m.trainIdx for m in inlier_matches))
                            if uniq_dst >= 4 and max(np.std(inlier_dst[:, 0]), np.std(inlier_dst[:, 1])) >= 2.0:
                                best_inl = max(best_inl, uniq_dst)

        return best_inl

    @staticmethod
    def _extract_foreground(image: np.ndarray) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        if image is None or min(image.shape[:2]) < 8:
            return None
        pad = max(2, round(min(image.shape[:2]) * .08))
        image = image[pad:-pad, pad:-pad]
        if min(image.shape[:2]) < 8:
            return None
        scale = 256 / max(image.shape[:2])
        image = cv2.resize(image, None, fx=scale, fy=scale)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
        border = np.concatenate((hsv[1, ::3], hsv[-2, ::3], hsv[::3, 1], hsv[::3, -2]))
        hue, saturation, val = np.median(border, axis=0)
        hue_distance = np.abs(hsv[:, :, 0] - hue)
        hue_distance = np.minimum(hue_distance, 180 - hue_distance)
        if saturation > 45:
            foreground = ((hue_distance > 12) & (hsv[:, :, 1] > 40)) | (hsv[:, :, 1] < saturation * .35)
        else:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            lum_fg = (th > 0) if (th > 0).mean() < 0.5 else (th == 0)
            foreground = (hsv[:, :, 1] > 45) | lum_fg
        mask = foreground.astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        sig_contours = [c for c in contours if (cv2.contourArea(c) / mask.size) > 0.01]
        if not sig_contours:
            sig_contours = [max(contours, key=cv2.contourArea)]
        main_c = max(sig_contours, key=cv2.contourArea)
        grouped = [main_c]
        x0, y0, w0, h0 = cv2.boundingRect(main_c)
        for c in sig_contours:
            if c is main_c:
                continue
            x1, y1, w1, h1 = cv2.boundingRect(c)
            dx = max(0, max(x0, x1) - min(x0 + w0, x1 + w1))
            dy = max(0, max(y0, y1) - min(y0 + h0, y1 + h1))
            if dx <= 8 and dy <= 8:
                grouped.append(c)
                nx0 = min(x0, x1)
                ny0 = min(y0, y1)
                w0 = max(x0 + w0, x1 + w1) - nx0
                h0 = max(y0 + h0, y1 + h1) - ny0
                x0, y0 = nx0, ny0

        total_area = sum(cv2.contourArea(c) for c in grouped) / mask.size
        if not .03 < total_area < .85:
            return None
        all_pts = np.vstack(grouped)
        x, y, w, h = cv2.boundingRect(all_pts)
        out_mask = np.zeros_like(mask)
        cv2.drawContours(out_mask, grouped, -1, 255, -1)
        return image[y:y+h, x:x+w], out_mask[y:y+h, x:x+w]

    @staticmethod
    def _normalize_foreground_axis(pair):
        """Normalize orientation only when the mask has a clear long axis."""
        image, mask = pair
        ys, xs = np.where(mask > 127)
        if len(xs) < 8:
            return None
        points = np.stack([xs, ys], axis=1).astype(np.float32)
        center, axes, values = cv2.PCACompute2(points, mean=None)
        if values[1, 0] <= 0 or values[0, 0] / values[1, 0] < 4.0:
            return None
        angle = float(np.degrees(np.arctan2(axes[0, 1], axes[0, 0])))
        side = 2 * max(mask.shape)
        transform = cv2.getRotationMatrix2D(tuple(center[0]), angle, 1)
        transform[:, 2] += side / 2 - center[0]
        rotated = cv2.warpAffine(image, transform, (side, side))
        rotated_mask = cv2.warpAffine(mask, transform, (side, side))
        ys, xs = np.where(rotated_mask > 127)
        if not len(xs):
            return None
        box = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
        return rotated[box], rotated_mask[box]

    def _compute_foreground_alignment(
        self, roi: np.ndarray, ref_img: np.ndarray,
    ) -> Optional[Dict[str, Any]]:
        result = self._compute_legacy_foreground_alignment(roi, ref_img)
        if result is not None:
            return result
        from visual_catalog import _catalog_reference_body
        from warehouse_neutral_foreground import match_neutral_foreground
        return match_neutral_foreground(roi, _catalog_reference_body(ref_img))

    def _compute_legacy_foreground_alignment(
        self,
        roi: np.ndarray,
        ref_img: np.ndarray,
    ) -> Optional[Dict[str, Any]]:
        from visual_catalog import _catalog_reference_body
        query = self._extract_foreground(roi)
        template = self._extract_foreground(_catalog_reference_body(ref_img))
        if query is None or template is None:
            return None
        direct = self._compare_foreground_pairs(query, template)
        if direct is not None:
            return direct
        normalized_query = self._normalize_foreground_axis(query)
        normalized_template = self._normalize_foreground_axis(template)
        if normalized_query is None or normalized_template is None:
            return None
        t, tm = normalized_template
        matches = []
        for candidate in ((t, tm), (t[::-1, ::-1], tm[::-1, ::-1])):
            result = self._compare_foreground_pairs(normalized_query, candidate)
            if result is not None:
                matches.append({**result, "axisNormalized": True})
        return max(matches, key=lambda result: result["score"]) if matches else None

    @staticmethod
    def _compare_foreground_pairs(query, template):
        q, qm = query
        t, tm = template
        ratio = (q.shape[1] / q.shape[0]) / (t.shape[1] / t.shape[0])
        if not 0.75 < ratio < 1.33:
            return None
        q96, t96 = (cv2.resize(i, (96, 96)).astype(np.float32) for i in (q, t))
        qm96, tm96 = (cv2.resize(i, (96, 96)) > 127 for i in (qm, tm))
        overlap = qm96 & tm96
        iou = float(overlap.sum() / max(1, (qm96 | tm96).sum()))
        # Note on threshold calibration:
        # The IoU threshold was calibrated from 0.80 to 0.75 based on empirical evidence from
        # multi-component furniture items (e.g. 复古圆桌 ref_144037_05 / image14-0-2), where
        # thin structures (narrow table legs, ~1-2px wide on warehouse grid crops) undergo
        # unavoidable discrete boundary quantization when resized, yielding IoU ~ 0.77-0.83.
        # Strict false-positive suppression is maintained by requiring correlation >= 0.85
        # (measured 0.9427 on table) and error <= 22.0 (measured 11.96 on table), which
        # strongly rejects same-size competing items, empty background, badges, and occlusions.
        if iou < 0.75:
            return None
        a, b = q96[overlap].ravel(), t96[overlap].ravel()
        error = float(np.mean(np.abs(a - b)))
        a, b = a - a.mean(), b - b.mean()
        norm_ab = float(np.linalg.norm(a) * np.linalg.norm(b))
        correlation = float(np.dot(a, b) / max(1e-8, norm_ab))
        if correlation < 0.85 or error > 22.0:
            return None
        score = round(0.9 + 0.1 * min(iou, correlation), 4)
        return {
            "score": score,
            "iou": iou,
            "correlation": correlation,
            "error": error,
        }

    def match_catalog_candidates(
        self,
        roi: Optional[np.ndarray],
        w: int,
        h: int,
        is_empty: bool = False,
    ) -> Tuple[float, List[Dict[str, Any]], int]:
        """Direct production recognition and admission path for catalog candidate assignment.
        Returns (catalog_score, candidates_list, best_inliers).
        Admission rules:
        1. SIFT admission requires best_inliers >= 5 and margin >= 4.
        2. Low-texture fallback requires best_fg_score >= 0.85 and fg_margin >= 0.03.
           (Foreground IoU threshold is 0.75, with correlation >= 0.85 and error <= 22.0).
        """
        if roi is None or roi.size == 0 or is_empty:
            return 0.0, [], 0

        matching_refs = [
            entry for entry in self._ref_cache.values()
            if entry["widthCells"] == w and entry["heightCells"] == h
        ]
        if not matching_refs:
            return 0.0, [], 0

        best_inliers = 0
        best_ref = None
        second_inliers = 0

        roi_kp_des = self._sift.detectAndCompute(roi, None)
        if roi_kp_des[1] is not None and len(roi_kp_des[1]) >= 4:
            for ref_entry in matching_refs:
                inls = self._compute_sift_inliers(roi, ref_entry, roi_kp_des=roi_kp_des)
                if inls > best_inliers:
                    second_inliers = best_inliers
                    best_inliers = inls
                    best_ref = ref_entry
                elif inls > second_inliers:
                    second_inliers = inls

        catalog_score = 0.0
        margin = best_inliers - second_inliers
        candidates_list = []

        if best_ref is not None and best_inliers >= 5 and margin >= 4:
            catalog_score = min(1.0, best_inliers / 20.0)
            rec = best_ref["entry"]
            cand = {
                "catalogId": rec["catalogId"],
                "name": rec["name"],
                "identityStatus": "CANDIDATE_ONLY",
                "geometry": {
                    "width": w,
                    "height": h,
                    "cells": w * h,
                    "shape": f"{w}x{h}",
                },
                "matchReasons": ["WHOLE_CARD_MATCH", f"SIFT_INLIERS_{best_inliers}"],
                "score": round(float(catalog_score), 4),
                "inliers": int(best_inliers),
                "margin": int(margin),
            }
            validate_item_identity(cand["catalogId"], cand["name"], cand["identityStatus"])
            candidates_list.append(cand)
        if not candidates_list or best_inliers < 7 or margin < 5:
            # A weak SIFT candidate must not suppress independent foreground
            # evidence. Disagreement between admitted identities fails closed.
            best_fg_score = 0.0
            best_fg_ref = None
            second_fg_score = 0.0
            for ref_entry in matching_refs:
                fg_res = self._compute_foreground_alignment(roi, ref_entry["img"])
                if fg_res and fg_res.get("score", 0.0) > 0:
                    s = fg_res["score"]
                    if s > best_fg_score:
                        second_fg_score = best_fg_score
                        best_fg_score = s
                        best_fg_ref = ref_entry
                    elif s > second_fg_score:
                        second_fg_score = s
            if best_fg_ref is not None and best_fg_score >= 0.85:
                fg_margin = best_fg_score - second_fg_score
                if fg_margin >= 0.03:
                    rec = best_fg_ref["entry"]
                    if candidates_list and candidates_list[0]["catalogId"] != rec["catalogId"]:
                        return 0.0, [], best_inliers
                    catalog_score = 0.80
                    cand = {
                        "catalogId": rec["catalogId"],
                        "name": rec["name"],
                        "identityStatus": "CANDIDATE_ONLY",
                        "geometry": {
                            "width": w,
                            "height": h,
                            "cells": w * h,
                            "shape": f"{w}x{h}",
                        },
                        "matchReasons": ["FOREGROUND_SHAPE_AND_COLOR", f"SCORE_{best_fg_score:.4f}"],
                        "score": round(float(catalog_score), 4),
                        "bestFgScore": round(float(best_fg_score), 4),
                        "fgMargin": round(float(fg_margin), 4),
                    }
                    validate_item_identity(cand["catalogId"], cand["name"], cand["identityStatus"])
                    if candidates_list:
                        previous = candidates_list[0]
                        cand["inliers"] = previous["inliers"]
                        cand["margin"] = previous["margin"]
                        cand["matchReasons"] = previous["matchReasons"] + cand["matchReasons"]
                    candidates_list = [cand]

        admitted = bool(candidates_list and (
            (candidates_list[0].get("inliers", 0) >= 7 and candidates_list[0].get("margin", 0) >= 5)
            or (candidates_list[0].get("bestFgScore", 0) >= .90 and candidates_list[0].get("fgMargin", 0) >= .05)))
        if not admitted:
            normalized = self._match_footprint_normalized_icon(roi, w, h, matching_refs)
            if normalized is not None:
                if candidates_list and candidates_list[0]["catalogId"] != normalized["catalogId"]:
                    return 0.0, [], best_inliers
                return normalized["score"], [normalized], normalized["inliers"]
            small = self._match_small_icon(roi, w, h, matching_refs)
            if small is not None:
                if candidates_list and candidates_list[0]["catalogId"] != small["catalogId"]:
                    return 0.0, [], best_inliers
                return small["score"], [small], small["inliers"]
        return catalog_score, candidates_list, best_inliers

    def _match_small_icon(self, roi, w, h, matching_refs):
        """Retain fine native-pixel features in small, complete inventory tiles.

        Default SIFT smoothing removes detail at small desktop capture scales.
        Use one fixed finer scale on both source cards and the unchanged query;
        never combine feature counts across scales or resize the source evidence.
        """
        if roi is None or roi.size == 0 or w <= 0 or h <= 0:
            return None
        height, width = roi.shape[:2]
        pitch_x, pitch_y = width / w, height / h
        if not (28 <= pitch_x <= 48 and 28 <= pitch_y <= 48
                and .9 <= pitch_x / pitch_y <= 1.1):
            return None
        features = self._small_icon_sift.detectAndCompute(roi, None)
        ranked = []
        for ref in matching_refs:
            cid = ref["entry"]["catalogId"]
            if cid not in self._small_icon_reference_features:
                kp, des = self._small_icon_sift.detectAndCompute(ref["img"], None)
                kp_body, des_body = self._small_icon_sift.detectAndCompute(ref["body"], None)
                self._small_icon_reference_features[cid] = {
                    "kp": kp, "des": des, "kp_body": kp_body, "des_body": des_body}
            count = self._compute_sift_inliers(
                roi, self._small_icon_reference_features[cid], roi_kp_des=features)
            ranked.append((count, ref))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        if not ranked:
            return None
        count, ref = ranked[0]
        margin = count - (ranked[1][0] if len(ranked) > 1 else 0)
        if count < 7 or margin < 5:
            return None
        rec = ref["entry"]
        from warehouse_icon_registration import verify_registered_icon
        fine_ref = self._small_icon_reference_features[rec["catalogId"]]
        registration = verify_registered_icon(
            roi, ref["body"], (fine_ref["kp_body"], fine_ref["des_body"]),
            features, self._matcher, self._distinct_feature_matches)
        if registration is None:
            return None
        validate_item_identity(rec["catalogId"], rec["name"], "CANDIDATE_ONLY")
        return {"catalogId": rec["catalogId"], "name": rec["name"],
                "identityStatus": "CANDIDATE_ONLY",
                "geometry": {"width": w, "height": h, "cells": w * h, "shape": f"{w}x{h}"},
                "matchReasons": ["SMALL_ICON_NATIVE_SIFT", "REGISTERED_ICON_COLOR", f"SIFT_INLIERS_{count}"],
                "registration": registration,
                "score": round(min(1.0, count / 20.0), 4), "inliers": count, "margin": margin}

    def _match_footprint_normalized_icon(self, roi, w, h, matching_refs):
        """Try a square icon viewport for a non-square physical tile.

        Some inventory icons fill their tile while the catalog uses a square
        icon viewport. Shrink the longer side, never enlarge the image, and
        retain the original source bbox and physical footprint. No arbitrary
        aspect search or accumulation of votes from multiple views is used.
        """
        if w <= 0 or h <= 0 or w == h or roi is None or roi.size == 0:
            return None
        height, width = roi.shape[:2]
        if not .9 <= (width / height) / (w / h) <= 1.1:
            return None
        side = min(height, width)
        if side < 28:
            return None
        image = cv2.resize(roi, (side, side), interpolation=cv2.INTER_AREA)
        features = self._sift.detectAndCompute(image, None)
        ranked = sorted(((self._compute_sift_inliers(image, ref, roi_kp_des=features), ref)
                         for ref in matching_refs), key=lambda pair: pair[0], reverse=True)
        if not ranked:
            return None
        inliers, reference = ranked[0]
        margin = inliers - (ranked[1][0] if len(ranked) > 1 else 0)
        if inliers < 7 or margin < 5:
            return None
        rec = reference["entry"]
        candidate = {
            "catalogId": rec["catalogId"], "name": rec["name"],
            "identityStatus": "CANDIDATE_ONLY",
            "geometry": {"width": w, "height": h, "cells": w * h, "shape": f"{w}x{h}"},
            "matchReasons": ["FOOTPRINT_NORMALIZED_SIFT", f"SIFT_INLIERS_{inliers}"],
            "score": round(min(1.0, inliers / 20.0), 4), "inliers": inliers, "margin": margin,
        }
        validate_item_identity(candidate["catalogId"], candidate["name"], candidate["identityStatus"])
        return candidate

    def resolve(
        self,
        *,
        physical_ledger: Mapping[str, Any],
        descriptors: Sequence[Mapping[str, Any]],
        frames: Optional[Mapping[str, np.ndarray]] = None,
    ) -> List[Dict[str, Any]]:
        raw_tracks = [t for t in (physical_ledger.get("tracks") or []) if isinstance(t, Mapping)]
        raw_segments = [s for s in (physical_ledger.get("segments") or []) if isinstance(s, Mapping)]
        desc_map = {str(d.get("evidenceId")): d for d in descriptors if isinstance(d, Mapping)}

        if not raw_segments or not frames:
            return []

        # 1. Analyze grid lines and gutters for each segment frame
        # Identify canonical x_lines from verified anchor if available
        canonical_x_lines = None
        for seg in sorted(raw_segments, key=lambda s: int(s.get("sequenceIndex") or 0)):
            s_img = frames.get(str(seg.get("segmentId") or ""))
            if s_img is not None and s_img.size > 0:
                g_obs = observe_warehouse_grid(s_img, already_cropped=True, source_id=str(seg.get("segmentId") or ""))
                g = g_obs.get("grid") or {}
                if g.get("status") == "OK" and g.get("xLines") and len(g["xLines"]) >= 11:
                    canonical_x_lines = list(g["xLines"][:11])
                    break

        segment_analyses = {}
        for seg in raw_segments:
            seg_id = str(seg.get("segmentId") or "")
            seq = int(seg.get("sequenceIndex") or 0)
            img = frames.get(seg_id)
            if img is None or img.size == 0:
                continue

            grid_obs = observe_warehouse_grid(img, already_cropped=True, source_id=seg_id)
            grid = grid_obs.get("grid") or {}
            grid_status = grid.get("status")

            chain_ok = bool(seg.get("chainOk", True))
            if canonical_x_lines is not None and chain_ok:
                x_lines = list(canonical_x_lines)
            else:
                x_lines = grid.get("xLines") or [3, 59, 115, 171, 227, 283, 339, 395, 451, 507, 563]

            y_lines = grid.get("yLines") or [0, 57, 114, 171, 228, 285, 342, 399, 456, 513]

            if len(x_lines) > 11:
                x_lines = x_lines[:11]
            num_cols = min(10, len(x_lines) - 1)

            # Drop clipped partial cell at top of scrolled frame
            if len(y_lines) >= 3 and (y_lines[1] - y_lines[0]) < 0.85 * (y_lines[2] - y_lines[1]):
                y_lines = y_lines[1:]

            if img.shape[0] >= 750:
                max_board_y = int(round(0.88 * img.shape[0]))
                valid_y_lines = [yl for yl in y_lines if yl <= max_board_y + 6]
                if len(valid_y_lines) >= 4:
                    y_lines = valid_y_lines
            num_rows = len(y_lines) - 1

            empty_map = np.zeros((num_rows, num_cols), dtype=bool)
            for r in range(num_rows):
                for c in range(num_cols):
                    y1, y2 = y_lines[r], y_lines[r + 1]
                    x1, x2 = x_lines[c], x_lines[c + 1]
                    cell_crop = img[y1:y2, x1:x2]
                    if cell_crop.size == 0:
                        empty_map[r, c] = True
                    else:
                        gray = cv2.cvtColor(cell_crop, cv2.COLOR_BGR2GRAY)
                        bgr_mean = cell_crop.mean(axis=(0, 1))
                        channel_spread = float(np.ptp(bgr_mean))
                        # Empty slot:
                        # 1. Dark empty tabletop in real video: mean <= 26.0 and channel_spread < 14.0
                        # 2. Achromatic flat slot in synthetic tests: channel_spread < 3.0 and gray.std() < 2.5 and gray.mean() <= 45.0
                        is_dark_empty = bool(gray.mean() <= 26.0 and channel_spread < 14.0)
                        is_flat_empty = bool(channel_spread < 3.0 and gray.std() < 2.5 and gray.mean() <= 45.0)
                        empty_map[r, c] = is_dark_empty or is_flat_empty

            # Insufficient evidence: grid failed and frame has no internal structure
            insufficient_evidence = bool(grid_status != "OK" and (empty_map.all() or float(np.std(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))) < 2.0))

            v_gutters = np.zeros((num_rows, num_cols - 1), dtype=np.float32)
            for r in range(num_rows):
                for c in range(num_cols - 1):
                    v_gutters[r, c] = pure_valley_gutter(
                        img, x_lines[c + 1], (y_lines[r], y_lines[r + 1]), "v", empty_map[r, c], empty_map[r, c + 1]
                    )

            h_gutters = np.zeros((num_rows - 1, num_cols), dtype=np.float32)
            for r in range(num_rows - 1):
                for c in range(num_cols):
                    h_gutters[r, c] = pure_valley_gutter(
                        img, y_lines[r + 1], (x_lines[c], x_lines[c + 1]), "h", empty_map[r, c], empty_map[r + 1, c]
                    )

            origin_y = float(seg.get("originY") or 0.0)
            chain_ok = bool(seg.get("chainOk", True))
            scroll_state = seg.get("scrollState") or ("TOP" if seq == 0 else "BOTTOM" if seq == len(raw_segments) - 1 else "MIDDLE")

            segment_analyses[seq] = {
                "seg_id": seg_id,
                "seq": seq,
                "img": img,
                "x_lines": x_lines,
                "y_lines": y_lines,
                "num_rows": num_rows,
                "num_cols": num_cols,
                "empty_map": empty_map,
                "v_gutters": v_gutters,
                "h_gutters": h_gutters,
                "origin_y": origin_y,
                "chain_ok": chain_ok,
                "insufficient_evidence": insufficient_evidence,
                "scroll_state": scroll_state,
            }

        # If all frames have insufficient evidence (e.g. uniform empty test frame), resolve to UNKNOWN without hallucinating items
        if segment_analyses and all(analysis.get("insufficient_evidence", False) for analysis in segment_analyses.values()):
            unknown_units: List[Dict[str, Any]] = []
            for seq, analysis in sorted(segment_analyses.items(), key=lambda item: item[0]):
                unknown_units.append({
                    "reviewUnitId": f"unit-unknown-seq{seq}",
                    "placementStatus": "UNKNOWN",
                    "visibility": "CLIPPED",
                    "worldAnchor": {"row": None, "col": None},
                    "footprint": {"widthCells": 1, "heightCells": 1},
                    "physicalGroupId": None,
                    "geometryEvidenceStatus": "INSUFFICIENT_EVIDENCE",
                    "identityStatus": "REVIEW_REQUIRED",
                    "selectedCatalogId": None,
                    "bestObservationId": f"obs-unknown-seq{seq}",
                    "supportingTrackIds": [],
                    "observations": [{
                        "observationId": f"obs-unknown-seq{seq}",
                        "evidenceId": analysis["seg_id"],
                        "sequenceIndex": seq,
                        "bbox": [0.0, 0.0, 56.0, 56.0],
                        "status": "UNKNOWN",
                        "localGridBbox": [0, 0, 1, 1],
                    }],
                    "candidateStatus": "UNKNOWN",
                    "candidates": [],
                    "widthCandidates": [1],
                    "heightCandidates": [1],
                    "spanCandidates": [1],
                })
            return unknown_units

        # Anchor segment geometry
        anchor = min(segment_analyses.values(), key=lambda s: s["seq"]) if segment_analyses else None
        if anchor is not None:
            anchor_y_start = float(anchor["y_lines"][0])
            anchor_x_start = float(anchor["x_lines"][0])
            h_diffs = [
                anchor["y_lines"][i + 1] - anchor["y_lines"][i]
                for i in range(anchor["num_rows"])
            ]
            w_diffs = [
                anchor["x_lines"][i + 1] - anchor["x_lines"][i]
                for i in range(anchor["num_cols"])
            ]
            cell_h = float(np.median(h_diffs)) if h_diffs else 56.0
            cell_w = float(np.median(w_diffs)) if w_diffs else 56.0
        else:
            anchor_y_start = 0.0
            anchor_x_start = 3.0
            cell_h = 56.0
            cell_w = 56.0

        for seq, analysis in segment_analyses.items():
            origin_y = analysis["origin_y"]
            chain_ok = analysis["chain_ok"]
            y_lines = analysis["y_lines"]
            residuals = []
            for yl in y_lines:
                wy = origin_y + float(yl) - anchor_y_start
                cr = wy / cell_h
                residuals.append(abs(cr - round(cr)))
            avg_res = float(np.mean(residuals)) if residuals else 0.0
            analysis["is_aligned"] = chain_ok and (avg_res <= 0.22)
            analysis["avg_res"] = avg_res

        # 2. Generate candidate placement hypotheses across distinct rectangular shapes
        # Include linear and rectangular catalog shapes
        candidate_shapes = [
            (5, 5),
            (4, 5), (5, 4),
            (4, 4),
            (4, 3), (3, 4),
            (2, 4), (4, 2),
            (3, 3),
            (1, 5), (5, 1),
            (4, 1), (1, 4),
            (3, 2), (2, 3),
            (3, 1), (1, 3),
            (2, 2),
            (2, 1), (1, 2),
            (1, 1),
        ]
        
        all_hypotheses: List[Dict[str, Any]] = []

        for seq, analysis in segment_analyses.items():
            img = analysis["img"]
            x_lines = analysis["x_lines"]
            y_lines = analysis["y_lines"]
            num_rows = analysis["num_rows"]
            num_cols = analysis["num_cols"]
            v_gutters = analysis["v_gutters"]
            h_gutters = analysis["h_gutters"]
            origin_y = analysis["origin_y"]
            seg_id = analysis["seg_id"]
            empty_map = analysis["empty_map"]

            for w, h in candidate_shapes:
                for r in range(num_rows - h + 1):
                    for c in range(num_cols - w + 1):
                        empty_cells_count = int(empty_map[r : r + h, c : c + w].sum())
                        empty_ratio = empty_cells_count / (w * h)
                        # A valid warehouse item cannot contain confirmed empty tabletop slots inside its rectangular boundary
                        if empty_ratio > 0.15:
                            continue

                        # World row estimate for board boundary evaluation
                        if analysis["is_aligned"]:
                            y_top = origin_y + float(y_lines[r]) - anchor_y_start
                            cont_r = y_top / cell_h
                            est_world_r = int(round(cont_r))
                        else:
                            est_world_r = None

                        scroll_state = analysis.get("scroll_state", "MIDDLE")
                        is_top_board = (est_world_r == 0) if est_world_r is not None else (scroll_state == "TOP" and r == 0)
                        is_bot_board = (est_world_r is not None and est_world_r + h >= 25) or (scroll_state == "BOTTOM" and r + h == num_rows)

                        # Evaluate outer support
                        outer_sum, outer_count = 0.0, 0
                        if r == 0:
                            if is_top_board:
                                outer_sum += w
                            outer_count += w
                        else:
                            outer_sum += float(h_gutters[r - 1, c : c + w].sum())
                            outer_count += w

                        if r + h == num_rows:
                            if is_bot_board:
                                outer_sum += w
                            outer_count += w
                        else:
                            outer_sum += float(h_gutters[r + h - 1, c : c + w].sum())
                            outer_count += w

                        if c == 0:
                            outer_sum += h
                            outer_count += h
                        else:
                            outer_sum += float(v_gutters[r : r + h, c - 1].sum())
                            outer_count += h

                        if c + w == num_cols:
                            outer_sum += h
                            outer_count += h
                        else:
                            outer_sum += float(v_gutters[r : r + h, c + w - 1].sum())
                            outer_count += h

                        outer_sup = outer_sum / max(1, outer_count)

                        # Evaluate internal contradiction
                        int_sum = float(h_gutters[r : r + h - 1, c : c + w].sum()) + float(
                            v_gutters[r : r + h, c : c + w - 1].sum()
                        )
                        int_edges = (h - 1) * w + h * (w - 1)
                        int_density = (int_sum / int_edges) if int_edges > 0 else 0.0

                        # Check for continuous unbroken gutter cuts
                        max_h_cut = 0.0
                        for k in range(h - 1):
                            avg_cut = float(h_gutters[r + k, c : c + w].mean())
                            if avg_cut > max_h_cut:
                                max_h_cut = avg_cut
                        max_v_cut = 0.0
                        for j in range(w - 1):
                            avg_cut = float(v_gutters[r : r + h, c + j].mean())
                            if avg_cut > max_v_cut:
                                max_v_cut = avg_cut
                        max_continuous_cut = max(max_h_cut, max_v_cut)

                        # Strict fail-closed for continuous gutter slicing (shelf grooves >= 0.85, internal dividers ~0.58)
                        if max_continuous_cut >= 0.72:
                            continue

                        # Confirmed empty border grounding
                        empty_border_count = 0
                        if r > 0 and empty_map[r - 1, c : c + w].all():
                            empty_border_count += 1
                        if r + h < num_rows and empty_map[r + h, c : c + w].all():
                            empty_border_count += 1
                        if c > 0 and empty_map[r : r + h, c - 1].all():
                            empty_border_count += 1
                        if c + w < num_cols and empty_map[r : r + h, c + w - 1].all():
                            empty_border_count += 1

                        geom_score = outer_sup * max(0.0, 1.0 - 1.8 * int_density) + 0.03 * empty_border_count

                        if empty_ratio > 0.0:
                            geom_score *= max(0.0, 1.0 - 2.0 * empty_ratio)

                        if geom_score <= 0.05:
                            continue

                        # Extract ROI
                        x1, y1 = x_lines[c], y_lines[r]
                        x2, y2 = x_lines[c + w], y_lines[r + h]
                        roi = img[y1:y2, x1:x2]

                        is_all_empty = bool(empty_map[r : r + h, c : c + w].all())
                        catalog_score, candidates_list, best_inliers = self.match_catalog_candidates(
                            roi, w, h, is_empty=is_all_empty
                        )

                        if analysis["is_aligned"]:
                            y_top = origin_y + float(y_lines[r]) - anchor_y_start
                            cont_r = y_top / cell_h
                            world_r = int(round(cont_r))
                            x_left = float(x_lines[c]) - anchor_x_start
                            cont_c = x_left / cell_w
                            world_c = int(round(cont_c))
                            cell_res = abs(cont_r - world_r)
                            is_hyp_aligned = (cell_res <= 0.22)
                        else:
                            is_hyp_aligned = False

                        total_score = geom_score + (2.0 * catalog_score)

                        if is_hyp_aligned:
                            if world_c < 0 or world_c + w > 10:
                                continue
                            if world_r < 0 or world_r + h > 25:
                                continue
                            group_key = ("ALIGNED", world_r, world_c, w, h)
                            cells = set((world_r + kr, world_c + kc) for kr in range(h) for kc in range(w))
                        else:
                            group_key = ("UNALIGNED", seq, r, c, w, h)
                            world_r = None
                            world_c = None
                            cells = set()

                        all_hypotheses.append({
                            "seq": seq,
                            "seg_id": seg_id,
                            "local_r": r,
                            "local_c": c,
                            "world_r": world_r,
                            "world_c": world_c,
                            "w": w,
                            "h": h,
                            "bbox": [float(x1), float(y1), float(x2), float(y2)],
                            "geom_score": geom_score,
                            "catalog_score": catalog_score,
                            "total_score": total_score,
                            "best_inliers": best_inliers,
                            "candidates": candidates_list,
                            "cells": cells,
                            "group_key": group_key,
                            "is_aligned": is_hyp_aligned,
                        })

        # 3. Aggregate hypotheses across frames by world placement
        grouped_by_world: Dict[Any, List[Dict[str, Any]]] = {}
        for hyp in all_hypotheses:
            grouped_by_world.setdefault(hyp["group_key"], []).append(hyp)

        consolidated: List[Dict[str, Any]] = []
        for group_key, hyps in grouped_by_world.items():
            best_hyp = max(hyps, key=lambda x: x["total_score"])
            is_aligned = (group_key[0] == "ALIGNED")
            world_r = best_hyp["world_r"]
            world_c = best_hyp["world_c"]
            w = best_hyp["w"]
            h = best_hyp["h"]
            
            # Temporal linking: boundary items at top/bottom viewports cannot physically appear in all scrolled frames.
            # Items near top (world_r <= 2) or bottom (world_r + h >= 16) with strong geometry get temporal evidence.
            is_boundary_item = is_aligned and (
                ((world_r is not None and world_r <= 2) or (world_r is not None and world_r + h >= 16))
                and best_hyp["geom_score"] >= 0.60
            )
            temporal_score = 1.0 if len(hyps) > 1 or best_hyp["catalog_score"] > 0.5 or is_boundary_item else 0.0
            total_evidence = best_hyp["total_score"] + temporal_score

            # Collect observations across frames with immutable image sha256 and per-frame matching
            seg_sha_map = {}
            for d in (descriptors or []):
                if isinstance(d, Mapping):
                    eid = str(d.get("evidenceId") or "").strip()
                    sha = str(d.get("sha256") or "").strip()
                    if eid and sha:
                        seg_sha_map[eid] = sha
                    seq_idx = d.get("sequenceIndex")
                    if seq_idx is not None and sha:
                        seg_sha_map[f"seq_{seq_idx}"] = sha
                        seg_sha_map[str(seq_idx)] = sha
            obs_list = []
            seen_seqs = set()
            for h_item in hyps:
                seq = h_item["seq"]
                if seq in seen_seqs:
                    continue
                seen_seqs.add(seq)
                obs_id = (
                    f"obs-{world_r}-{world_c}-seq{seq}"
                    if is_aligned
                    else f"obs-unaligned-seq{seq}-r{h_item['local_r']}-c{h_item['local_c']}"
                )
                cand0 = h_item["candidates"][0] if h_item.get("candidates") else None
                seg_id = str(h_item["seg_id"])
                obs_sha = seg_sha_map.get(seg_id) or seg_sha_map.get(f"seq_{seq}") or seg_sha_map.get(str(seq))
                obs_list.append({
                    "observationId": obs_id,
                    "evidenceId": seg_id,
                    "sequenceIndex": seq,
                    "sha256": obs_sha,
                    "bbox": h_item["bbox"],
                    "status": "FULL",
                    "localGridBbox": [h_item["local_r"], h_item["local_c"], w, h],
                    "matchedCandidateId": cand0.get("catalogId") if cand0 else None,
                    "matchedCandidateName": cand0.get("name") if cand0 else None,
                    "inliers": int(cand0.get("inliers", h_item.get("best_inliers", 0))) if cand0 else 0,
                    "margin": cand0.get("margin") if cand0 else None,
                    "bestFgScore": cand0.get("bestFgScore") if cand0 else None,
                    "fgMargin": cand0.get("fgMargin") if cand0 else None,
                })

            # Check if an earlier frame (or adjacent frame) had a CLIPPED observation for this world placement
            if is_aligned and world_r is not None and world_c is not None:
                for seq, analysis in segment_analyses.items():
                    if analysis["is_aligned"] and seq not in seen_seqs:
                        seg_top = analysis["origin_y"] + float(analysis["y_lines"][0]) - anchor_y_start
                        r_top = seg_top / cell_h
                        if world_r < r_top < world_r + h:
                            clip_h = int(round(world_r + h - r_top))
                            if 0 < clip_h < h:
                                x1 = analysis["x_lines"][world_c]
                                y1 = analysis["y_lines"][0]
                                x2 = analysis["x_lines"][world_c + w]
                                y2 = analysis["y_lines"][clip_h]
                                seg_id_c = str(analysis["seg_id"])
                                clip_sha = seg_sha_map.get(seg_id_c) or seg_sha_map.get(f"seq_{seq}") or seg_sha_map.get(str(seq))
                                obs_list.append({
                                    "observationId": f"obs-{world_r}-{world_c}-seq{seq}",
                                    "evidenceId": analysis["seg_id"],
                                    "sequenceIndex": seq,
                                    "sha256": clip_sha,
                                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                                    "status": "CLIPPED",
                                    "localGridBbox": [0, world_c, w, clip_h],
                                    "matchedCandidateId": None,
                                    "matchedCandidateName": None,
                                    "inliers": 0,
                                    "margin": None,
                                    "bestFgScore": None,
                                    "fgMargin": None,
                                })

            consolidated.append({
                "world_r": world_r,
                "world_c": world_c,
                "w": w,
                "h": h,
                "cells": best_hyp["cells"],
                "total_evidence": total_evidence,
                "candidates": best_hyp["candidates"],
                "observations": obs_list,
                "is_aligned": is_aligned,
                "best_hyp": best_hyp,
            })

        # 4. Spatial Non-Maximum Suppression with cohesive multi-cell preference
        def _hyp_sort_key(h_item):
            w, h = h_item["w"], h_item["h"]
            has_catalog = bool(h_item.get("candidates"))
            area_bonus = (0.22 if has_catalog else 0.04) * min(16, w * h - 1)
            return h_item["total_evidence"] + area_bonus

        consolidated.sort(key=_hyp_sort_key, reverse=True)
        nms_survivors: List[Dict[str, Any]] = []
        for hyp in consolidated:
            hyp_cids = {c["catalogId"] for c in hyp.get("candidates", []) if c.get("catalogId")}
            suppressed = False
            if hyp_cids:
                for survivor in nms_survivors:
                    surv_cids = {c["catalogId"] for c in survivor.get("candidates", []) if c.get("catalogId")}
                    if hyp_cids & surv_cids:
                        intersection = len(hyp["cells"] & survivor["cells"])
                        union = len(hyp["cells"] | survivor["cells"])
                        if union > 0 and (intersection / union) > 0.35:
                            suppressed = True
                            break
            if not suppressed:
                nms_survivors.append(hyp)

        # Global non-overlapping selection with near-tie ambiguity detection
        AMBIGUITY_MARGIN = 0.30
        selected: List[Dict[str, Any]] = []
        occupied_cells: Set[Tuple[int, int]] = set()

        for idx, hyp in enumerate(nms_survivors):
            if not hyp["cells"].isdisjoint(occupied_cells) or hyp["total_evidence"] <= 0.3:
                continue

            # Check if there is a competing overlapping hypothesis with near-tie evidence
            near_tie_competitor = None
            if hyp["total_evidence"] >= 0.7:
                hyp_cids = {c["catalogId"] for c in hyp.get("candidates", []) if c.get("catalogId")}
                for other_idx, other in enumerate(nms_survivors):
                    if other_idx == idx:
                        continue
                    if not hyp["cells"].isdisjoint(other["cells"]) and other["total_evidence"] >= 0.7:
                        other_cids = {c["catalogId"] for c in other.get("candidates", []) if c.get("catalogId")}
                        if hyp_cids and hyp_cids == other_cids and (hyp["w"], hyp["h"]) == (other["w"], other["h"]):
                            continue
                        margin = abs(hyp["total_evidence"] - other["total_evidence"])
                        if margin < AMBIGUITY_MARGIN:
                            near_tie_competitor = other
                            break

            if near_tie_competitor is not None:
                # Ambiguous region between two competing placement interpretations
                hyp["is_ambiguous_region"] = True
                hyp["competitor"] = near_tie_competitor
                combined_cands = list(hyp["candidates"])
                hyp_shape = f"{hyp['w']}x{hyp['h']}"
                for c in near_tie_competitor.get("candidates", []):
                    c_shape = c.get("geometry", {}).get("shape")
                    # Preserve geometric ambiguity without polluting candidate list with cross-size shapes
                    if c_shape == hyp_shape and not any(x.get("catalogId") == c.get("catalogId") for x in combined_cands):
                        combined_cands.append(c)
                hyp["candidates"] = combined_cands
                selected.append(hyp)
                occupied_cells.update(hyp["cells"])
            else:
                hyp["is_ambiguous_region"] = False
                selected.append(hyp)
                occupied_cells.update(hyp["cells"])

        # 5. Build Review Units conforming strictly to Review Packet V2 schema
        review_units: List[Dict[str, Any]] = []
        for hyp in selected:
            world_r = hyp["world_r"]
            world_c = hyp["world_c"]
            w = hyp["w"]
            h = hyp["h"]
            candidates = hyp["candidates"]
            observations = hyp["observations"]

            # Associate supporting raw tracks
            supporting_track_ids: List[str] = []
            for t in raw_tracks:
                tid = str(t.get("trackId") or "")
                t_obs = t.get("observations") or []
                for to in t_obs:
                    t_box = to.get("localBox")
                    if isinstance(t_box, (list, tuple)) and len(t_box) == 4:
                        bx1, by1, bx2, by2 = t_box
                        seg_id = str(to.get("segmentId") or "")
                        for p_obs in observations:
                            if p_obs["evidenceId"] == seg_id:
                                px1, py1, px2, py2 = p_obs["bbox"]
                                if not (bx2 <= px1 or bx1 >= px2 or by2 <= py1 or by1 >= py2):
                                    if tid not in supporting_track_ids:
                                        supporting_track_ids.append(tid)

            if not supporting_track_ids:
                supporting_track_ids.append(f"raw-track-{world_r}-{world_c}")

            is_aligned = hyp.get("is_aligned", True)
            is_ambiguous = hyp.get("is_ambiguous_region", False)
            has_strong_evidence = hyp["total_evidence"] >= 1.0 and not is_ambiguous

            if not is_aligned:
                placement_status = "UNKNOWN"
                candidate_status = "UNKNOWN"
                physical_group_id = None
                evidence_status = "UNALIGNED"
                best_h = hyp.get("best_hyp", hyp)
                unit_id = f"unit-unaligned-seq{best_h.get('seq', 0)}-r{best_h.get('local_r', 0)}-c{best_h.get('local_c', 0)}-{w}x{h}"
            elif is_ambiguous:
                placement_status = "AMBIGUOUS_REGION"
                candidate_status = "AMBIGUOUS"
                physical_group_id = None
                evidence_status = "EXACT"
                unit_id = f"unit-world-{world_r}-{world_c}-{w}x{h}"
            elif has_strong_evidence:
                placement_status = "RESOLVED"
                candidate_status = (
                    "UNIQUE_IN_CATALOG" if len(candidates) == 1
                    else "AMBIGUOUS" if len(candidates) > 1
                    else "UNKNOWN"
                )
                physical_group_id = f"group-world-{world_r}-{world_c}"
                evidence_status = "EXACT"
                unit_id = f"unit-world-{world_r}-{world_c}-{w}x{h}"
            else:
                placement_status = "UNKNOWN"
                candidate_status = "UNKNOWN"
                physical_group_id = None
                evidence_status = "EXACT"
                unit_id = f"unit-world-{world_r}-{world_c}-{w}x{h}"

            all_full = all(obs.get("status") == "FULL" for obs in observations)
            visibility = "FULL" if all_full else "CLIPPED"

            unit = {
                "reviewUnitId": unit_id,
                "placementStatus": placement_status,
                "visibility": visibility,
                "worldAnchor": {"row": world_r, "col": world_c},
                "footprint": {"widthCells": w, "heightCells": h},
                "physicalGroupId": physical_group_id,
                "geometryEvidenceStatus": evidence_status,
                "identityStatus": "REVIEW_REQUIRED",
                "selectedCatalogId": None,
                "bestObservationId": observations[0]["observationId"],
                "supportingTrackIds": supporting_track_ids,
                "observations": observations,
                "candidateStatus": candidate_status,
                "candidates": candidates,
                "widthCandidates": [w],
                "heightCandidates": [h],
                "spanCandidates": [w * h],
            }
            review_units.append(unit)

        return review_units
