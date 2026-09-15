"""
大厅会场 / 仪器组闭集小图匹配。

只匹配当前选中胶囊，不扫整屏。没有真实样本的类（如真珠场）保持 OCR 兜底。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from roi_scaler import ROIScaler

DEFAULT_MIN_SCORE = 0.62
DEFAULT_MIN_MARGIN = 0.05
DEFAULT_SCALES = (0.90, 1.00, 1.10)


def asset_dir(name: str, catalog_path: Optional[str] = None) -> str:
    if catalog_path:
        sibling = os.path.join(os.path.dirname(os.path.abspath(catalog_path)), name)
        if os.path.isdir(sibling):
            return sibling
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "assets", name))


class LobbyChipMatcher:
    def __init__(
        self,
        template_dir: str,
        roi_key: str,
        result_key: str,
        min_score: float = DEFAULT_MIN_SCORE,
        min_margin: float = DEFAULT_MIN_MARGIN,
    ):
        self.template_dir = template_dir
        self.roi_key = roi_key
        self.result_key = result_key
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
        entries: List[Dict[str, Any]] = []
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                self.min_score = float(payload.get("minScore", self.min_score))
                self.min_margin = float(payload.get("minMargin", self.min_margin))
                if payload.get("roi"):
                    self.roi_key = payload["roi"]
                entries = list(payload.get("items") or [])
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
            gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
            item = dict(entry)
            item["image"] = gray
            item["id"] = entry.get("id") or os.path.splitext(entry.get("file") or "")[0]
            self.templates.append(item)

    def identify(self, frame: np.ndarray) -> Dict[str, Any]:
        self.scan_count += 1
        empty = {
            self.result_key: None,
            "score": 0.0,
            "secondScore": 0.0,
            "accepted": False,
            "source": "unrecognized",
            "scores": {},
            "meta": {},
        }
        if frame is None or frame.size == 0 or not self.templates:
            return empty

        h, w = frame.shape[:2]
        x1, y1, x2, y2 = ROIScaler.scale_roi(self.roi_key, w, h)
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
        meta = {}
        if accepted:
            for item in self.templates:
                if item["id"] == top_name:
                    meta = {k: v for k, v in item.items() if k not in ("image", "file")}
                    break
        return {
            self.result_key: top_name if accepted else None,
            "score": float(top_score),
            "secondScore": float(second_score),
            "accepted": accepted,
            "source": "template" if accepted else "unrecognized",
            "scores": {k: float(v) for k, v in scores.items()},
            "meta": meta,
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
