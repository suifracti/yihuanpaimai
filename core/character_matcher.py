"""
大厅助手闭集模板识别。

角色身份用固定头像卡做 matchTemplate，不走名字 OCR。
模板来源：assets/lobby_characters（由「拍卖角色头像」登记）。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from roi_scaler import ROIScaler

DEFAULT_MIN_SCORE = 0.55
DEFAULT_MIN_MARGIN = 0.04
DEFAULT_SCALES = (0.78, 0.90, 1.02)


def default_template_dir(catalog_path: Optional[str] = None) -> str:
    if catalog_path:
        sibling = os.path.join(os.path.dirname(os.path.abspath(catalog_path)), "lobby_characters")
        if os.path.isdir(sibling):
            return sibling
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "assets", "lobby_characters"))


def crop_inner_portrait(image: np.ndarray) -> np.ndarray:
    """去掉卡片边框和底部姓名条，只留立绘。"""
    h, w = image.shape[:2]
    y1, y2 = int(h * 0.10), max(int(h * 0.10) + 8, int(h * 0.76))
    x1, x2 = int(w * 0.07), max(int(w * 0.07) + 8, int(w * 0.93))
    return image[y1:y2, x1:x2]


class CharacterMatcher:
    def __init__(
        self,
        template_dir: Optional[str] = None,
        min_score: float = DEFAULT_MIN_SCORE,
        min_margin: float = DEFAULT_MIN_MARGIN,
    ):
        self.template_dir = template_dir or default_template_dir()
        self.min_score = min_score
        self.min_margin = min_margin
        self.templates: List[Dict[str, Any]] = []
        self.scan_count = 0
        self._load_templates()

    def _load_templates(self) -> None:
        self.templates = []
        if not os.path.isdir(self.template_dir):
            return
        manifest_path = os.path.join(self.template_dir, "manifest.json")
        entries: List[Dict[str, str]] = []
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                self.min_score = float(payload.get("minScore", self.min_score))
                self.min_margin = float(payload.get("minMargin", self.min_margin))
                entries = list(payload.get("characters") or [])
            except Exception:
                entries = []
        if not entries:
            for name in sorted(os.listdir(self.template_dir)):
                if name.lower().endswith((".png", ".jpg", ".jpeg")):
                    entries.append({"id": os.path.splitext(name)[0], "file": name})
        for entry in entries:
            path = os.path.join(self.template_dir, entry.get("file") or "")
            if not os.path.exists(path):
                continue
            raw = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if raw is None or raw.size == 0:
                continue
            portrait = crop_inner_portrait(raw)
            if portrait.size == 0:
                continue
            gray = cv2.cvtColor(portrait, cv2.COLOR_BGR2GRAY)
            self.templates.append({
                "id": entry.get("id") or os.path.splitext(entry["file"])[0],
                "file": entry.get("file"),
                "image": gray,
            })

    def identify(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        在大厅右下角色卡搜索区做闭集匹配。
        返回 character / score / secondScore / accepted / scores。
        """
        self.scan_count += 1
        empty = {
            "character": None,
            "score": 0.0,
            "secondScore": 0.0,
            "accepted": False,
            "source": "unrecognized",
            "scores": {},
        }
        if frame is None or frame.size == 0 or not self.templates:
            return empty

        h, w = frame.shape[:2]
        x1, y1, x2, y2 = ROIScaler.scale_roi("lobby_character_search", w, h)
        search = frame[y1:y2, x1:x2]
        if search.size == 0:
            return empty
        if search.ndim == 3:
            search = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)

        scores: Dict[str, float] = {}
        for item in self.templates:
            scores[item["id"]] = self._best_score(search, item["image"])

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_name, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        accepted = top_score >= self.min_score and (top_score - second_score) >= self.min_margin
        return {
            "character": top_name if accepted else None,
            "score": float(top_score),
            "secondScore": float(second_score),
            "accepted": accepted,
            "source": "template" if accepted else "unrecognized",
            "scores": {k: float(v) for k, v in scores.items()},
        }

    def _best_score(self, search: np.ndarray, template: np.ndarray) -> float:
        th, tw = template.shape[:2]
        best = -1.0
        for scale in DEFAULT_SCALES:
            nw = max(8, int(tw * scale))
            nh = max(8, int(th * scale))
            if nw >= search.shape[1] or nh >= search.shape[0]:
                continue
            resized = cv2.resize(template, (nw, nh), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val > best:
                best = float(max_val)
        return max(0.0, best)


CANONICAL_ROSTER: Tuple[str, ...] = (
    "达芙蒂尔",
    "哈尼亚",
    "哈索尔",
    "小吱",
    "九原",
    "汐",
    "阿德勒",
    "埃德嘉",
)

ROSTER_ALIASES: Dict[str, str] = {
    "浔": "汐",
    "哈尼娅": "哈尼亚",
    "达芙帝尔": "达芙蒂尔",
}


def normalize_roster_name(name: Optional[str]) -> Optional[str]:
    """Validate and normalize candidate name against canonical roster whitelist."""
    if not name:
        return None
    raw = str(name).strip()
    if raw in CANONICAL_ROSTER:
        return raw
    if raw in ROSTER_ALIASES:
        return ROSTER_ALIASES[raw]
    for canon in CANONICAL_ROSTER:
        if canon in raw:
            return canon
    for alias, canon in ROSTER_ALIASES.items():
        if alias in raw:
            return canon
    return None


class SettlementAssistantMatcher:
    """
    Settlement assistant identity matcher.
    Priority:
    1. Card visual area feature matching against canonical character reference templates.
    2. OCR text evidence strictly validated against canonical roster whitelist.
    Free-text OCR (e.g. '小哎') is strictly rejected.
    """

    def __init__(
        self,
        template_dir: Optional[str] = None,
        min_matches: int = 15,
        min_margin: int = 8,
    ):
        self.template_dir = template_dir or default_template_dir()
        self.min_matches = min_matches
        self.min_margin = min_margin
        self.orb = cv2.ORB_create(nfeatures=500)
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.templates: Dict[str, Tuple[np.ndarray, Any, Any]] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        if not os.path.isdir(self.template_dir):
            return
        for name in CANONICAL_ROSTER:
            file_name = f"{name}.png"
            path = os.path.join(self.template_dir, file_name)
            if not os.path.exists(path) and name == "汐":
                path = os.path.join(self.template_dir, "浔.png")
            if not os.path.exists(path):
                continue
            raw = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if raw is None or raw.size == 0:
                continue
            kp, des = self.orb.detectAndCompute(raw, None)
            if des is not None and len(des) > 0:
                self.templates[name] = (raw, kp, des)

    def extract_card_crop(
        self, frame: np.ndarray, ocr_results: Optional[List[Any]] = None
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        label_box = None
        if ocr_results:
            for box, text, _ in ocr_results:
                raw = (text or "").strip()
                if "竞拍帮手" in raw or "帮手" in raw:
                    label_box = box
                    break
        if label_box is not None:
            x_min = min(pt[0] for pt in label_box)
            y_min = min(pt[1] for pt in label_box)
            crop_x1 = max(0, int(x_min - 0.03 * w))
            crop_x2 = min(w, int(x_min + 0.17 * w))
            crop_y1 = max(0, int(y_min - 0.22 * h))
            crop_y2 = min(h, int(y_min + 0.05 * h))
        else:
            crop_x1 = int(0.44 * w)
            crop_x2 = int(0.63 * w)
            crop_y1 = int(0.12 * h)
            crop_y2 = int(0.41 * h)
        return frame[crop_y1:crop_y2, crop_x1:crop_x2]

    def identify(
        self,
        frame: Optional[np.ndarray],
        ocr_results: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        empty = {
            "canonicalName": None,
            "status": "UNKNOWN",
            "confidence": 0.0,
            "candidates": [],
            "cardCrop": None,
        }
        if frame is None or frame.size == 0 or not self.templates:
            ocr_name = self._extract_ocr_roster_name(ocr_results)
            if ocr_name:
                return {
                    "canonicalName": ocr_name,
                    "status": "CONFIRMED",
                    "confidence": 0.5,
                    "candidates": [{"name": ocr_name, "matches": 0, "score": 0.5}],
                    "cardCrop": None,
                }
            return empty

        card_crop = self.extract_card_crop(frame, ocr_results)
        if card_crop.size == 0:
            ocr_name = self._extract_ocr_roster_name(ocr_results)
            if ocr_name:
                return {
                    "canonicalName": ocr_name,
                    "status": "CONFIRMED",
                    "confidence": 0.5,
                    "candidates": [{"name": ocr_name, "matches": 0, "score": 0.5}],
                    "cardCrop": card_crop,
                }
            return empty

        ch, cw = card_crop.shape[:2]
        illustration = card_crop[0 : max(1, int(ch * 0.75)), :]
        kp1, des1 = self.orb.detectAndCompute(illustration, None)

        candidates: List[Dict[str, Any]] = []
        if des1 is not None and len(des1) >= 10:
            scores = {}
            for name, (_, _, des2) in self.templates.items():
                matches = self.bf.match(des1, des2)
                good = [m for m in matches if m.distance < 50]
                scores[name] = len(good)
            ranked = sorted(scores.items(), key=lambda item: -item[1])
            for name, m_count in ranked:
                score = round(float(m_count / (m_count + 10)), 3) if m_count > 0 else 0.0
                candidates.append({"name": name, "matches": m_count, "score": score})

        top_name = candidates[0]["name"] if candidates else None
        top_matches = candidates[0]["matches"] if candidates else 0
        second_matches = candidates[1]["matches"] if len(candidates) > 1 else 0
        norm_score = candidates[0]["score"] if candidates else 0.0

        if top_matches >= self.min_matches and (top_matches - second_matches) >= self.min_margin:
            return {
                "canonicalName": top_name,
                "status": "CONFIRMED",
                "confidence": norm_score,
                "candidates": candidates,
                "cardCrop": card_crop,
            }

        ocr_valid_name = self._extract_ocr_roster_name(ocr_results)
        if ocr_valid_name and ocr_valid_name == top_name and top_matches >= 10:
            return {
                "canonicalName": top_name,
                "status": "CONFIRMED",
                "confidence": norm_score,
                "candidates": candidates,
                "cardCrop": card_crop,
            }
        if ocr_valid_name and not top_name:
            return {
                "canonicalName": ocr_valid_name,
                "status": "CONFIRMED",
                "confidence": 0.5,
                "candidates": candidates,
                "cardCrop": card_crop,
            }

        return {
            "canonicalName": None,
            "status": "UNKNOWN",
            "confidence": norm_score,
            "candidates": candidates,
            "cardCrop": card_crop,
        }

    def _extract_ocr_roster_name(
        self, ocr_results: Optional[List[Any]]
    ) -> Optional[str]:
        if not ocr_results:
            return None
        for box, text, _ in ocr_results:
            raw = (text or "").strip()
            if "竞拍帮手" in raw or "帮手" in raw:
                cleaned = re.sub(r"(?:竞拍帮手|帮手)[：:\s]*", "", raw).strip()
                normalized = normalize_roster_name(cleaned)
                if normalized:
                    return normalized
        for _, text, _ in ocr_results:
            raw = (text or "").strip()
            normalized = normalize_roster_name(raw)
            if normalized:
                return normalized
        return None
