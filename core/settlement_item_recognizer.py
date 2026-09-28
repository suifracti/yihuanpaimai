# -*- coding: utf-8 -*-
"""
Neverness to Everness (异环) - 终局结算藏品与 Ground Truth 账本识别器 (Settlement Item Recognizer)
功能：
  1. 深度解析收录的全部 200 件红/金/紫/蓝/绿/白藏品全图鉴数据库
  2. 提取结算画面右侧背包仓库网格 (10x10 Warehouse Grid)
  3. 基于多边框几何及色相空间检测每一个独立露出的真实藏品
  4. 产出结构化 Stage 1 Settlement Ledger (严格区分 exact 与 ambiguous，禁止价格中位数注入)
  5. 进行总账一致性校验 (settlementLedgerVerified / settlementLedgerDelta)
"""

import os
import re
import cv2
import json
import numpy as np
from settlement_grid import settlement_grid_bounds, visible_card_rectangles
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

class SettlementItemRecognizer:
    def __init__(
        self,
        catalog_path: Optional[str] = None,
        tpl_dir: Optional[str] = None,
        include_development: bool = False,
    ):
        self.catalog: List[Dict[str, Any]] = []
        self.catalog_by_shape_rarity: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self.valid_shapes_by_rarity: Dict[str, set] = {}
        self.templates: Dict[str, Any] = {}
        self.include_development = bool(include_development)
        
        core_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(core_dir, ".."))
        
        # 1. 优先从 solver_core_v06.js / lab/index.html 加载完整 200 藏品库
        js_path = os.path.join(project_root, "core", "solver_core_v06.js")
        lab_path = os.path.join(project_root, "lab", "index.html")
        
        if os.path.exists(js_path):
            self._load_catalog_from_js(js_path)
        elif os.path.exists(lab_path):
            self._load_catalog_from_html(lab_path)
            
        # 构建几何形状查询表
        for (sz, rar), cands in self.catalog_by_shape_rarity.items():
            try:
                wc, hc = map(int, sz.split("x"))
                self.valid_shapes_by_rarity.setdefault(rar, set()).add((wc, hc))
                self.valid_shapes_by_rarity.setdefault(rar, set()).add((hc, wc))
            except Exception:
                pass

        # Explicit custom templates keep their existing contract. Production
        # references are source-backed object regions indexed by catalog ID.
        # Production default strictly excludes development references.
        self.tpl_dir = tpl_dir
        if tpl_dir:
            self._load_templates(tpl_dir)
        else:
            from visual_catalog import load_visual_templates
            self.templates = load_visual_templates(include_development=self.include_development)

        # 3. 候选与身份证据解析器 (4D2D1M-C3.2I)
        try:
            from settlement_catalog_candidates import get_global_catalog_candidate_resolver
            self.candidate_resolver = get_global_catalog_candidate_resolver()
        except Exception:
            self.candidate_resolver = None
        self._trusted_gameplay_matcher = None

    def _load_catalog_from_js(self, js_path: str):
        try:
            with open(js_path, "r", encoding="utf-8") as f:
                text = f.read()
            patterns = [
                (r'PRE_0813_RED_ITEMS\s*=\s*(\[.*?\]);', 'red'),
                (r'PRE_0813_GOLD_ITEMS\s*=\s*(\[.*?\]);', 'gold'),
                (r'PRE_0813_PURPLE_ITEMS\s*=\s*(\[.*?\]);', 'purple'),
                (r'PRE_0813_BLUE_ITEMS\s*=\s*(\[.*?\]);', 'blue'),
                (r'PRE_0813_GREEN_ITEMS\s*=\s*(\[.*?\]);', 'green'),
                (r'PRE_0813_WHITE_ITEMS\s*=\s*(\[.*?\]);', 'white'),
            ]
            for pat, rarity in patterns:
                m = re.search(pat, text, re.DOTALL)
                if m:
                    arr_str = m.group(1)
                    items = re.findall(r'\[\s*["\']([^"\']+)["\']\s*,\s*(\d+)\s*,\s*["\']([^"\']+)["\']\s*\]', arr_str)
                    for name, price_s, size_s in items:
                        item_obj = {
                            "name": name,
                            "price": int(price_s),
                            "size": size_s.lower(),
                            "rarity": rarity
                        }
                        self.catalog.append(item_obj)
                        key = (item_obj["size"], rarity)
                        self.catalog_by_shape_rarity.setdefault(key, []).append(item_obj)
        except Exception:
            pass

    def _load_catalog_from_html(self, html_path: str):
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                text = f.read()
            patterns = [
                (r'PRE_0813_RED_ITEMS\s*=\s*(\[.*?\]);', 'red'),
                (r'PRE_0813_GOLD_ITEMS\s*=\s*(\[.*?\]);', 'gold'),
                (r'PRE_0813_PURPLE_ITEMS\s*=\s*(\[.*?\]);', 'purple'),
                (r'PRE_0813_BLUE_ITEMS\s*=\s*(\[.*?\]);', 'blue'),
                (r'PRE_0813_GREEN_ITEMS\s*=\s*(\[.*?\]);', 'green'),
                (r'PRE_0813_WHITE_ITEMS\s*=\s*(\[.*?\]);', 'white'),
            ]
            for pat, rarity in patterns:
                m = re.search(pat, text, re.DOTALL)
                if m:
                    arr_str = m.group(1)
                    items = re.findall(r'\[\s*["\']([^"\']+)["\']\s*,\s*(\d+)\s*,\s*["\']([^"\']+)["\']\s*\]', arr_str)
                    for name, price_s, size_s in items:
                        item_obj = {
                            "name": name,
                            "price": int(price_s),
                            "size": size_s.lower(),
                            "rarity": rarity
                        }
                        self.catalog.append(item_obj)
                        key = (item_obj["size"], rarity)
                        self.catalog_by_shape_rarity.setdefault(key, []).append(item_obj)
        except Exception:
            pass

    def _load_templates(self, tpl_dir: str):
        for root, _, files in os.walk(tpl_dir):
            for f in files:
                if f.lower().endswith(('.png', '.jpg')):
                    p = os.path.join(root, f)
                    try:
                        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if im is not None:
                            self.templates[f] = im
                            rel_p = os.path.relpath(p, tpl_dir).replace("\\", "/")
                            self.templates[rel_p] = im
                    except Exception:
                        pass

    def _match_side_color(self, band: np.ndarray, rar: str) -> float:
        if band.size == 0:
            return 0.0
        hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV).reshape(-1, 3)
        if rar == "gold":
            sat = (hsv[:, 0] >= 8) & (hsv[:, 0] <= 32) & (hsv[:, 1] >= 45) & (hsv[:, 2] >= 45)
        elif rar == "purple":
            sat = (hsv[:, 0] >= 120) & (hsv[:, 0] <= 165) & (hsv[:, 1] >= 35) & (hsv[:, 2] >= 35)
        elif rar == "blue":
            sat = (hsv[:, 0] >= 88) & (hsv[:, 0] <= 125) & (hsv[:, 1] >= 40) & (hsv[:, 2] >= 40)
        elif rar == "green":
            sat = (hsv[:, 0] >= 35) & (hsv[:, 0] <= 85) & (hsv[:, 1] >= 40) & (hsv[:, 2] >= 40)
        elif rar == "red":
            sat = ((hsv[:, 0] <= 8) | (hsv[:, 0] >= 168)) & (hsv[:, 1] >= 50) & (hsv[:, 2] >= 50)
        elif rar == "white":
            sat = (hsv[:, 1] <= 35) & (hsv[:, 2] >= 85)
        else:
            return 0.0
        return float(np.count_nonzero(sat)) / float(hsv.shape[0])

    def _cell_rect(self, r: int, c: int, cell_w: float, cell_h: float) -> Tuple[int, int, int, int]:
        return (
            int(round(c * cell_w)),
            int(round(r * cell_h)),
            int(round((c + 1) * cell_w)),
            int(round((r + 1) * cell_h)),
        )

    def _cell_is_empty(self, hsv: np.ndarray, r: int, c: int, cell_w: float, cell_h: float) -> bool:
        x1, y1, x2, y2 = self._cell_rect(r, c, cell_w, cell_h)
        pad_x = max(1, int(0.22 * (x2 - x1)))
        pad_y = max(1, int(0.22 * (y2 - y1)))
        inner = hsv[y1 + pad_y:y2 - pad_y, x1 + pad_x:x2 - pad_x]
        if inner.size == 0:
            return True
        val = inner[:, :, 2]
        gray = cv2.cvtColor(cv2.cvtColor(inner, cv2.COLOR_HSV2BGR), cv2.COLOR_BGR2GRAY)
        dark = float((val < 32).mean())
        if dark > 0.45 and float(val.mean()) < 62:
            return True
        rar, score = self._cell_rarity(hsv, r, c, cell_w, cell_h)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        grad = float(np.mean(np.hypot(gx, gy)))
        # 无描边 + 低纹理 = 底板空格，不是物品内部填色。
        return rar is None and float(gray.std()) < 10.0 and grad < 20.0

    def _cell_rarity(self, hsv: np.ndarray, r: int, c: int, cell_w: float, cell_h: float) -> Tuple[Optional[str], float]:
        x1, y1, x2, y2 = self._cell_rect(r, c, cell_w, cell_h)
        cell = hsv[y1:y2, x1:x2]
        if cell.size == 0:
            return None, 0.0
        hh, ww = cell.shape[:2]
        t = max(2, int(min(hh, ww) * 0.16))
        ring = np.concatenate([
            cell[:t].reshape(-1, 3),
            cell[-t:].reshape(-1, 3),
            cell[:, :t].reshape(-1, 3),
            cell[:, -t:].reshape(-1, 3),
        ])
        bgr = cv2.cvtColor(ring.reshape(-1, 1, 3), cv2.COLOR_HSV2BGR)
        scores = {rar: self._match_side_color(bgr, rar) for rar in ("gold", "purple", "blue", "green", "red", "white")}
        rar = max(scores, key=scores.get)
        return (rar, scores[rar]) if scores[rar] >= 0.12 else (None, scores[rar])

    def _shared_edge_allows_merge(
        self,
        hsv: np.ndarray,
        gray: np.ndarray,
        r1: int,
        c1: int,
        r2: int,
        c2: int,
        rar: str,
        cell_w: float,
        cell_h: float,
    ) -> bool:
        ax1, ay1, ax2, ay2 = self._cell_rect(r1, c1, cell_w, cell_h)
        if r1 == r2:
            x = ax2
            band = hsv[ay1 + 5:ay2 - 5, max(0, x - 2):x + 2]
            gutter = gray[ay1 + 5:ay2 - 5, max(0, x - 2):x + 2]
        else:
            y = ay2
            band = hsv[max(0, y - 2):y + 2, ax1 + 5:ax2 - 5]
            gutter = gray[max(0, y - 2):y + 2, ax1 + 5:ax2 - 5]
        if band.size == 0 or gutter.size == 0:
            return False
        fill = self._match_side_color(cv2.cvtColor(band, cv2.COLOR_HSV2BGR), rar)
        dark_ratio = float((gutter < 40).mean())
        mean_v = float(gutter.mean())
        # 真缝：黑、且几乎没有当前稀有度描边。件内共享边更亮。
        if mean_v < 40 or dark_ratio >= 0.55:
            return False
        return fill >= 0.22 and mean_v >= 50

    def generate_physical_grouping_hypotheses(
        self,
        crop: np.ndarray,
        cell_w: float,
        cell_h: float,
        raw_items: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate candidate-guided physical item grouping hypotheses (4D2D1M-C3.2H).

        Preserves ambiguity across competing grouping interpretations without arbitrary winner selection.
        """
        raw_hypotheses = []
        source_items = raw_items if raw_items is not None else self._segment_occupied_components(crop, cell_w, cell_h)
        for item in source_items:
            x1, y1 = round(item["col"] * cell_w), round(item["row"] * cell_h)
            x2 = round((item["col"] + item["widthCells"]) * cell_w)
            y2 = round((item["row"] + item["heightCells"]) * cell_h)
            raw_hypotheses.append({
                **item, "gridShape": item.get("gridShape") or item.get("shape", "1x1"),
                "bbox": [x1, y1, x2 - x1, y2 - y1],
                "isNoiseCandidate": False,
            })

        raw_hypotheses.sort(key=lambda h: (h["row"], h["col"], -h["occupiedCount"], h["widthCells"]))

        hypotheses: List[Dict[str, Any]] = []
        for idx, h_item in enumerate(raw_hypotheses):
            h_item["groupingHypothesisId"] = f"ghyp_{idx:03d}"

        for idx, h_item in enumerate(raw_hypotheses):
            h_cells = set(tuple(c) for c in h_item["cells"])
            competing = []
            for other_idx, other in enumerate(raw_hypotheses):
                if other_idx == idx:
                    continue
                if h_cells & set(tuple(c) for c in other["cells"]):
                    competing.append(other["groupingHypothesisId"])

            status = "AMBIGUOUS_GROUPING" if h_item.get("groupingAmbiguous") else "BOUNDARY_OBSERVED"
            bx, by, bw_px, bh_px = h_item["bbox"]
            roi_crop = crop[by:by + bh_px, bx:bx + bw_px] if (crop is not None and crop.size > 0) else None

            if h_item.get("identityEvidence"):
                identity_evidence = h_item["identityEvidence"]
            elif self.candidate_resolver:
                identity_evidence = self.candidate_resolver.resolve_identity_evidence(
                    hypothesis=h_item,
                    crop_image=roi_crop,
                    templates=self.templates,
                )
            else:
                identity_evidence = {
                    "schemaVersion": "settlement-identity-evidence.v1",
                    "status": "NO_CATALOG_MATCH",
                    "identityStatus": "NO_CATALOG_MATCH",
                    "groupingHypothesisId": h_item["groupingHypothesisId"],
                    "candidateCatalogId": None,
                    "candidateCount": 0,
                    "candidateCatalogIds": [],
                    "templateScore": 0.0,
                    "top1Score": 0.0,
                    "top2Score": 0.0,
                    "margin": 0.0,
                    "evidenceSource": "NO_RESOLVER",
                    "templateReference": None,
                    "rankedCandidates": [],
                    "thresholds": {"top1ScoreThreshold": 0.85, "marginThreshold": 0.08},
                }

            hypotheses.append({
                "groupingHypothesisId": h_item["groupingHypothesisId"],
                "cells": [list(c) for c in h_item["cells"]],
                "row": h_item["row"],
                "col": h_item["col"],
                "widthCells": h_item["widthCells"],
                "heightCells": h_item["heightCells"],
                "gridShape": h_item["gridShape"],
                "occupiedCount": h_item["occupiedCount"],
                "rarity": h_item["rarity"],
                "status": status,
                "groupingAmbiguous": bool(h_item.get("groupingAmbiguous")),
                "bbox": h_item["bbox"],
                "geometryEvidence": {
                    "shape": h_item["gridShape"],
                    "isCatalogShape": (h_item["widthCells"], h_item["heightCells"]) in self.valid_shapes_by_rarity.get(h_item["rarity"], set()),
                    "matchedFootprint": h_item["gridShape"],
                },
                "boundaryEvidence": {
                    "score": round(float(h_item.get("score") if h_item.get("score") is not None else (h_item.get("confidence") or 1.0)), 3),
                },
                "competingHypothesisIds": sorted(competing),
                "identityEvidence": identity_evidence,
            })

        return hypotheses

    def resolve_hypothesis_identity_evidence(
        self,
        hypothesis: Mapping[str, Any],
        crop_image: Optional[np.ndarray] = None,
        top1_threshold: float = 0.85,
        margin_threshold: float = 0.08,
    ) -> Dict[str, Any]:
        """Disambiguate identity evidence for a given hypothesis."""
        if not self.candidate_resolver:
            from settlement_catalog_candidates import get_global_catalog_candidate_resolver
            self.candidate_resolver = get_global_catalog_candidate_resolver()
        return self.candidate_resolver.resolve_identity_evidence(
            hypothesis=hypothesis,
            crop_image=crop_image,
            templates=self.templates,
            top1_threshold=top1_threshold,
            margin_threshold=margin_threshold,
        )

    def _segment_occupied_components(
        self,
        crop: np.ndarray,
        cell_w: float,
        cell_h: float,
    ) -> List[Dict[str, Any]]:
        """Segment closed visible card borders; preserve unresolved cells separately."""
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        rows = round(crop.shape[0] / cell_h)
        cols = round(crop.shape[1] / cell_w)
        result, assigned = [], set()
        for row, col, width, height in visible_card_rectangles(crop, cell_w, cell_h):
            cells = [(r, c) for r in range(row, row + height) for c in range(col, col + width)]
            if assigned.intersection(cells):
                continue
            x1, y1 = round(col * cell_w), round(row * cell_h)
            x2, y2 = round((col + width) * cell_w), round((row + height) * cell_h)
            card = crop[y1:y2, x1:x2]
            # Card perimeter avoids the object's own colors and selection checkmark.
            pad = max(2, round(min(cell_w, cell_h) * .10))
            inset = max(1, round(min(cell_w, cell_h) * .035))
            ring = np.concatenate([card[inset:pad].reshape(-1, 3),
                card[-pad:-inset].reshape(-1, 3), card[:, inset:pad].reshape(-1, 3),
                card[:, -pad:-inset].reshape(-1, 3)])
            scores = {rar: self._match_side_color(ring.reshape(-1, 1, 3), rar)
                      for rar in ("gold", "purple", "blue", "green", "red", "white")}
            rarity = max(scores, key=scores.get)
            score = scores[rarity]
            # At the viewport's lower edge there is no visible outside gutter
            # proving that the card ends here. Keep its visible region, but do
            # not treat its apparent height as a complete physical footprint.
            viewport_clipped = row + height == rows
            result.append({"row": row, "col": col, "widthCells": width,
                "heightCells": height, "shape": f"{width}x{height}", "cells": cells,
                "rarity": rarity if score >= .12 else "unknown", "score": score,
                "occupiedCount": len(cells), "groupingAmbiguous": viewport_clipped,
                "viewportClipped": viewport_clipped})
            assigned.update(cells)
        for row in range(rows):
            for col in range(cols):
                if (row, col) in assigned or self._cell_is_empty(hsv, row, col, cell_w, cell_h):
                    continue
                rarity, score = self._cell_rarity(hsv, row, col, cell_w, cell_h)
                result.append({"row": row, "col": col, "widthCells": 1, "heightCells": 1,
                    "shape": "1x1", "cells": [(row, col)], "rarity": rarity or "unknown",
                    "score": score, "occupiedCount": 1, "groupingAmbiguous": True,
                    "partitionCandidates": []})
        return self._merge_adjacent_fragments_with_visual_evidence(
            crop,
            hsv,
            cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY),
            cell_w,
            cell_h,
            result,
        )

    def _merge_adjacent_fragments_with_visual_evidence(
        self,
        crop: np.ndarray,
        hsv: np.ndarray,
        gray: np.ndarray,
        cell_w: float,
        cell_h: float,
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge only fragment pairs confirmed by both geometry and identity.

        A pair of unresolved 1x1 cells remains unresolved unless its shared edge
        looks like an item's internal edge and the combined footprint receives a
        normal, independent visual identity match. This keeps segmentation
        fail-closed while allowing a clear multi-cell item to be recovered.
        """
        ordered = sorted(items, key=lambda item: (item["row"], item["col"]))
        consumed = set()
        merged_items: List[Dict[str, Any]] = []
        visual_sources = {"VISUAL_FEATURE_MATCH", "VIDEO_DEVELOPMENT_REFERENCE_MATCH"}

        for index, item in enumerate(ordered):
            if index in consumed:
                continue
            if (
                not item.get("groupingAmbiguous")
                or item.get("widthCells") != 1
                or item.get("heightCells") != 1
                or item.get("rarity") in (None, "unknown")
            ):
                merged_items.append(item)
                continue

            selected = None
            for other_index in range(index + 1, len(ordered)):
                other = ordered[other_index]
                if other_index in consumed or not other.get("groupingAmbiguous"):
                    continue
                if (
                    other.get("widthCells") != 1
                    or other.get("heightCells") != 1
                    or other.get("rarity") != item.get("rarity")
                ):
                    continue

                r1, c1 = int(item["row"]), int(item["col"])
                r2, c2 = int(other["row"]), int(other["col"])
                if not (
                    (r1 == r2 and abs(c1 - c2) == 1)
                    or (c1 == c2 and abs(r1 - r2) == 1)
                ):
                    continue
                if not self._shared_edge_allows_merge(
                    hsv,
                    gray,
                    r1,
                    c1,
                    r2,
                    c2,
                    str(item["rarity"]),
                    cell_w,
                    cell_h,
                ):
                    continue

                row = min(r1, r2)
                col = min(c1, c2)
                width = 2 if r1 == r2 else 1
                height = 1 if r1 == r2 else 2
                shape = f"{width}x{height}"
                if (width, height) not in self.valid_shapes_by_rarity.get(item["rarity"], set()):
                    continue
                x1, y1 = round(col * cell_w), round(row * cell_h)
                x2, y2 = round((col + width) * cell_w), round((row + height) * cell_h)
                combined = crop[y1:y2, x1:x2]
                hypothesis = {
                    "row": row,
                    "col": col,
                    "widthCells": width,
                    "heightCells": height,
                    "gridShape": shape,
                    "shape": shape,
                    "cells": [(row, col), (r2, c2)],
                    "rarity": item["rarity"],
                    "bbox": [0, 0, x2 - x1, y2 - y1],
                    "groupingAmbiguous": False,
                }
                evidence = self.resolve_hypothesis_identity_evidence(hypothesis, combined)
                if (
                    evidence.get("status") == "EXACT_IDENTIFIED"
                    and evidence.get("evidenceSource") in visual_sources
                    and float(evidence.get("top1Score") or 0.0) >= 0.85
                    and float(evidence.get("margin") or 0.0) >= 0.08
                ):
                    selected = (other_index, hypothesis, evidence)
                    break

            if selected is None:
                merged_items.append(item)
                continue

            other_index, hypothesis, evidence = selected
            consumed.add(other_index)
            merged_items.append({
                "row": hypothesis["row"],
                "col": hypothesis["col"],
                "widthCells": hypothesis["widthCells"],
                "heightCells": hypothesis["heightCells"],
                "shape": hypothesis["shape"],
                "cells": hypothesis["cells"],
                "rarity": hypothesis["rarity"],
                "score": round(float(item.get("score") or 0.0) + float(ordered[other_index].get("score") or 0.0), 4) / 2,
                "occupiedCount": 2,
                "groupingAmbiguous": False,
                "partitionCandidates": [],
                "geometryMergeEvidence": {
                    "method": "ADJACENT_FRAGMENT_VISUAL_CONFIRMATION",
                    "candidateCatalogId": evidence.get("candidateCatalogId"),
                    "top1Score": evidence.get("top1Score"),
                    "margin": evidence.get("margin"),
                    "evidenceSource": evidence.get("evidenceSource"),
                    "templateReference": evidence.get("templateReference"),
                },
            })

        return sorted(merged_items, key=lambda item: (item["row"], item["col"]))

    def parse_settlement_ledger(self, frame: np.ndarray, actual_total: Optional[int] = None) -> Dict[str, Any]:
        """
        从结算静态画面中提取高置信度的最终藏品 Ground Truth 账本。
        严格契约：
          - exact: exactItemId / name / price 均为确切真实图鉴事实
          - ambiguous: price = None, candidateItemIds / candidatePrices 完整保留
          - 严禁任何价格中位数或猜测数值混入 price 或 settlementExactValueSum
          - 物理分件未与真人格子一一对应前，不把 rarity+shape 唯一桶升为 exact
        """
        h, w = frame.shape[:2]
        gx1, gy1, gx2, gy2 = settlement_grid_bounds(frame)

        crop = frame[gy1:gy2, gx1:gx2]
        if crop.size == 0:
            return {
                "settlementItems": [],
                "settlementItemCount": 0,
                "settlementExactItemCount": 0,
                "settlementUnknownItemCount": 0,
                "settlementExactValueSum": 0,
                "settlementLedgerVerified": False,
                "settlementLedgerStatus": "partial",
                "settlementLedgerDelta": None
            }

        ch, cw = crop.shape[:2]
        cell_w = cw / 10.0
        cell_h = ch / 10.0
        raw_items = self._segment_occupied_components(crop, cell_w, cell_h)
        for it in raw_items:
            it["bbox"] = [
                gx1 + round(it["col"] * cell_w),
                gy1 + round(it["row"] * cell_h),
                round((it["col"] + it["widthCells"]) * cell_w) - round(it["col"] * cell_w),
                round((it["row"] + it["heightCells"]) * cell_h) - round(it["row"] * cell_h),
            ]

        # 视觉排序：从上到下，从左到右
        raw_items.sort(key=lambda x: (x["row"], x["col"]))

        settlement_items = []
        for i, it in enumerate(raw_items):
            shape_str = it["shape"]
            shape_rev = f"{it['heightCells']}x{it['widthCells']}"
            cands = self.catalog_by_shape_rarity.get((shape_str, it["rarity"])) or self.catalog_by_shape_rarity.get((shape_rev, it["rarity"])) or []
            cand_names = [c["name"] for c in cands]
            cand_prices = [c["price"] for c in cands]

            exact_id = None
            name = None
            price = None
            status = "unknown"

            evidence = self.resolve_hypothesis_identity_evidence(
                {**it, "gridShape": it["shape"]},
                crop[it["bbox"][1] - gy1:it["bbox"][1] - gy1 + it["bbox"][3],
                     it["bbox"][0] - gx1:it["bbox"][0] - gx1 + it["bbox"][2]])
            ranked = evidence.get("rankedCandidates") or []
            cand_names = [c["name"] for c in ranked]
            cand_prices = [c["value"] for c in ranked]
            status = "ambiguous" if ranked else "unknown"
            if evidence.get("status") == "EXACT_IDENTIFIED" and not it.get("groupingAmbiguous"):
                match = next(c for c in ranked if c["catalogId"] == evidence["candidateCatalogId"])
                exact_id, name, price = match["catalogId"], match["name"], match["value"]
                status = "exact"

            # Production catalog-card pictures are derived references. Reuse
            # the activity matcher's hash-checked real-gameplay references for
            # settlement exact identity; the derived rank remains a candidate.
            qualified_ids = []
            if not self.tpl_dir and ranked:
                if self._trusted_gameplay_matcher is None:
                    from warehouse_vision import WarehouseTemplateMatcher
                    self._trusted_gameplay_matcher = WarehouseTemplateMatcher(
                        trusted_gameplay_only=True)
                qualified_ids = [c["catalogId"] for c in ranked
                                 if self._trusted_gameplay_matcher.gameplay_templates_by_id.get(c["catalogId"])]
            if not self.tpl_dir and not it.get("groupingAmbiguous") and qualified_ids:
                from warehouse_vision import WarehouseVisionConfig
                local_bbox = it["bbox"]
                roi = crop[local_bbox[1] - gy1:local_bbox[1] - gy1 + local_bbox[3],
                           local_bbox[0] - gx1:local_bbox[0] - gx1 + local_bbox[2]]
                candidates = [{"catalogId": c["catalogId"]} for c in ranked]
                direct, direct_score, direct_margin, direct_evidence = (
                    self._trusted_gameplay_matcher.match_candidate_evidence(
                        roi, candidates, WarehouseVisionConfig()))
                if (direct is not None and direct_evidence.get("accepted")
                        and direct_evidence.get("referenceKind") == "DIRECT"):
                    match = next((c for c in ranked if c["catalogId"] == direct_evidence.get("catalogId")), None)
                    if match is not None:
                        exact_id, name, price = match["catalogId"], match["name"], match["value"]
                        status = "exact"
                        evidence = {**evidence, "status": "EXACT_IDENTIFIED",
                                    "identityStatus": "EXACT_IDENTIFIED", "candidateCatalogId": exact_id,
                                    "evidenceSource": direct_evidence.get("referenceSource"),
                                    "directReference": direct_evidence,
                                    "top1Score": direct_score, "margin": direct_margin}

            if status != "exact":
                if not self.tpl_dir:
                    from settlement_catalog_candidates import explain_unresolved_settlement_evidence
                    evidence = explain_unresolved_settlement_evidence(
                        evidence, grouping_ambiguous=bool(it.get("groupingAmbiguous")),
                        qualified_catalog_ids=qualified_ids)

            settlement_items.append({
                "slotIndex": i + 1,
                "rarity": it["rarity"],
                "shape": it["shape"],
                "col": it["col"],
                "row": it["row"],
                "widthCells": it["widthCells"],
                "heightCells": it["heightCells"],
                "cells": [list(cell) for cell in (it.get("cells") or [])],
                "occupiedCount": it.get("occupiedCount") or len(it.get("cells") or []),
                "bbox": it["bbox"],
                "exactItemId": exact_id,
                "catalogId": exact_id,
                "name": name,
                "price": price,
                "candidateItemIds": cand_names,
                "candidatePrices": cand_prices,
                "status": status,
                "identificationStatus": status,
                "confidence": round(float(evidence.get("top1Score") or 0.0), 4),
                "identityEvidence": evidence,
                "groupingAmbiguous": bool(it.get("groupingAmbiguous")),
                "viewportClipped": bool(it.get("viewportClipped")),
                "partitionCandidates": list(it.get("partitionCandidates") or []),
                "geometryMergeEvidence": it.get("geometryMergeEvidence"),
                "score": it.get("score"),
            })

        exact_items = [it for it in settlement_items if it["identificationStatus"] == "exact"]
        exact_count = len(exact_items)
        unknown_count = len(settlement_items) - exact_count
        exact_sum = sum(it["price"] for it in exact_items if it["price"] is not None)

        is_verified = (
            len(settlement_items) > 0
            and unknown_count == 0
            and actual_total is not None
            and exact_sum == actual_total
        )
        ledger_status = "verified" if is_verified else "partial"
        delta = (exact_sum - actual_total) if actual_total is not None else None

        hypotheses = self.generate_physical_grouping_hypotheses(crop, cell_w, cell_h, raw_items=settlement_items)

        from quality_sell_selection import detect_quality_sell_selection_from_frame
        try:
            q_selection = detect_quality_sell_selection_from_frame(frame)
        except Exception:
            q_selection = None

        out = {
            "settlementItems": settlement_items,
            "settlementItemCount": len(settlement_items),
            "settlementExactItemCount": exact_count,
            "settlementUnknownItemCount": unknown_count,
            "settlementExactValueSum": exact_sum,
            "settlementLedgerVerified": is_verified,
            "settlementLedgerStatus": ledger_status,
            "settlementLedgerDelta": delta,
            "physicalGroupingHypotheses": hypotheses,
        }
        if q_selection is not None:
            out["qualitySellSelection"] = q_selection
            out["qualitySellSelectionSource"] = "visual_observed"
        return out

    def parse_settlement_grid(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """向后兼容接口：返回 settlementItems 列表"""
        return self.parse_settlement_ledger(frame)["settlementItems"]
