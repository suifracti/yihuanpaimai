"""
Neverness to Everness (异环) - Warehouse Vision v1
右侧仓库高置信物理视觉分析引擎

核心设计原则：
1. 严格遵循 SlotKnowledge / Evidence 证据分层模型 (OUTLINE_ONLY -> RARITY_ONLY -> RARITY_AND_SHAPE -> CANDIDATE_SET -> UNIQUE_IN_CATALOG / EXACT_IDENTIFIED)
2. 引入具备 trackId 的时序稳定追踪器 (Temporal Stability Filter)，杜绝单帧光效误判
3. UNIQUE_IN_CATALOG 仅在 rarity+shape 达到连续稳定确认后才允许锁定
4. 候选 > 1 时执行真像素级 Template Matching，严格杜绝 candidates[0] 盲选
5. 无法高置信确认时忠实输出 candidate_set 与价格区间 [min_price, max_price]
"""

import os
import cv2
import json
import numpy as np
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional

# ==============================================================================
# 0. 待真人对局实拍数据校准的初始基准超参数
# ==============================================================================
@dataclass
class WarehouseVisionConfig:
    """
    [超参数校准标记]: 包含所有待真人对局实拍数据校准的初始基准参数。
    后续根据实战录像对照误差逐步迭代微调。
    """
    # 像素级模板匹配最小置信度 (TM_CCOEFF_NORMED)
    MATCH_CONFIDENCE_THRESHOLD: float = 0.85
    # Top1 与 Top2 置信度优势最小差值 (区分同尺寸候选)
    MATCH_MARGIN_THRESHOLD: float = 0.08
    # 物理槽位空间重合追踪阈值 (IoU)
    IOU_TRACK_THRESHOLD: float = 0.70
    # 槽位时序稳定连续确认帧数
    TEMPORAL_CONFIRM_FRAMES: int = 4
    # 槽位最大丢失容忍帧数
    MAX_TRACK_LOST_FRAMES: int = 6
    # 高价值重尾藏品判定门槛 (单价高于此值触发高价值加权通道)
    HIGH_VALUE_THRESHOLD: int = 50000

# ==============================================================================
# 1. 证据层级枚举 (Evidence Level)
# ==============================================================================
class EvidenceLevel(str, Enum):
    UNKNOWN = "UNKNOWN"                         # 未知/未揭示/暗色/背景
    OUTLINE_ONLY = "OUTLINE_ONLY"               # 仅已知物理连通块长宽，未知品质
    RARITY_ONLY = "RARITY_ONLY"                 # 仅已知品质颜色，边界未闭合
    RARITY_AND_SHAPE = "RARITY_AND_SHAPE"       # 获得品质与尺寸，但尚未达到时序稳定
    CANDIDATE_SET = "CANDIDATE_SET"             # 稳定获取品质+尺寸后得到的候选集合 (CandidateCount > 1)
    UNIQUE_IN_CATALOG = "UNIQUE_IN_CATALOG"     # 稳定品质+尺寸在全图鉴中唯一 (CandidateCount == 1)
    EXACT_IDENTIFIED = "EXACT_IDENTIFIED"       # 候选>1 经高置信模板匹配确认具体身份

# ==============================================================================
# 2. 槽位知识结构体 (Tracked Slot Knowledge)
# ==============================================================================
@dataclass
class TrackedSlotBlob:
    track_id: int
    first_seen_frame: int
    last_seen_frame: int
    consecutive_stable_frames: int
    is_confirmed: bool
    
    # 空间与网格属性
    box: Tuple[int, int, int, int] # (x, y, w, h) 像素坐标
    width_cells: int
    height_cells: int
    cell_count: int
    
    # 品质与证据状态
    rarity: str # "white", "green", "blue", "purple", "gold", "red", "unknown"
    evidence_level: EvidenceLevel
    has_glow: bool = False          # 边缘绕光：品质+完整轮廓
    shape_locked: bool = False      # 完整轮廓已确认，可按长宽检索图鉴
    surround_locked: bool = False   # 1x1 被四周占满，即使无光也可锁 1 格
    
    # 候选与识别身份
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    identified_item: Optional[Dict[str, Any]] = None
    match_score: float = 0.0
    margin_score: float = 0.0
    identified_catalog_id: Optional[str] = None
    best_candidate_id: Optional[str] = None
    best_candidate_name: Optional[str] = None
    identity_reference_kind: Optional[str] = None
    
    # 估值与价格区间
    min_price: int = 0
    max_price: int = 0
    expected_price: int = 0
    col: Optional[int] = None  # viewport 列
    row: Optional[int] = None  # viewport 行

    def to_dict(self) -> Dict[str, Any]:
        has_cands = bool(self.candidates)
        is_exact = self.evidence_level == EvidenceLevel.EXACT_IDENTIFIED and self.identified_item is not None
        identity_status = "EXACT" if is_exact else ("CANDIDATE" if has_cands else "UNKNOWN")
        identified_name = self.identified_item.get("Name") if is_exact else None

        normalized_cands = [
            {
                "catalogId": str(c.get("catalogId") or c.get("Id") or ""),
                "name": str(c.get("name") or c.get("Name") or ""),
            }
            for c in self.candidates
        ]

        return {
            "trackId": self.track_id,
            "box": self.box,
            "size": f"{self.width_cells}x{self.height_cells}",
            "rarity": self.rarity,
            "evidenceLevel": self.evidence_level.value,
            "hasGlow": self.has_glow,
            "shapeLocked": self.shape_locked,
            "surroundLocked": self.surround_locked,
            "isConfirmed": self.is_confirmed,
            "stableFrames": self.consecutive_stable_frames,
            "identityStatus": identity_status,
            "candidates": normalized_cands,
            "identifiedName": identified_name,
            "identifiedCatalogId": self.identified_catalog_id if is_exact else None,
            "bestCandidateId": self.best_candidate_id,
            "bestCandidateName": self.best_candidate_name,
            "identityReferenceKind": self.identity_reference_kind,
            "candidateCount": len(self.candidates),
            "priceRange": [self.min_price, self.max_price],
            "expectedPrice": self.expected_price,
            "matchScore": round(self.match_score, 3),
            "marginScore": round(self.margin_score, 3),
            "col": self.col,
            "row": self.row,
            "w": self.width_cells,
            "h": self.height_cells,
        }

# ==============================================================================
# 3. 模板匹配与图鉴引擎
# ==============================================================================
class WarehouseTemplateMatcher:
    def __init__(self, catalog_path: Optional[str] = None, tpl_root: Optional[str] = None):
        self.catalog: List[Dict[str, Any]] = []
        self.catalog_by_shape_rarity: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self.templates: Dict[str, np.ndarray] = {}
        self.gameplay_templates_by_id: Dict[str, List[Dict[str, Any]]] = {}
        self.derived_templates_by_id: Dict[str, Dict[str, Any]] = {}
        
        # 确定路径
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(base_dir, ".."))
        if not catalog_path:
            catalog_path = os.path.join(project_root, "assets", "catalog_065.json")
        if not tpl_root:
            tpl_root = os.path.join(project_root, "assets", "items", "catalog_screenshots")

        self.catalog_path = catalog_path
        self.tpl_root = tpl_root

        self._load_catalog()
        self._load_templates()
        try:
            from visual_catalog import load_derived_warehouse_templates
            self.derived_templates_by_id = load_derived_warehouse_templates()
        except Exception:
            self.derived_templates_by_id = {}
        try:
            from visual_catalog import load_verified_warehouse_gameplay_templates
            self.gameplay_templates_by_id = load_verified_warehouse_gameplay_templates()
        except Exception:
            self.gameplay_templates_by_id = {}

    def _load_catalog(self):
        if os.path.exists(self.catalog_path):
            try:
                with open(self.catalog_path, 'r', encoding='utf-8') as f:
                    self.catalog = json.load(f)
                for item in self.catalog:
                    q = item.get("Quality", "金")
                    # 映射中英文品质
                    rarity_map = {"白": "white", "灰": "white", "绿": "green", "蓝": "blue", "紫": "purple", "金": "gold", "红": "red"}
                    r_key = rarity_map.get(q, q.lower())
                    w = item.get("Width", 1)
                    h = item.get("Height", 1)
                    key = (f"{w}x{h}", r_key)
                    if key not in self.catalog_by_shape_rarity:
                        self.catalog_by_shape_rarity[key] = []
                    self.catalog_by_shape_rarity[key].append(item)
            except Exception:
                pass

    def _load_templates(self):
        if os.path.exists(self.tpl_root):
            for root, _, files in os.walk(self.tpl_root):
                for f in files:
                    if f.lower().endswith(('.png', '.jpg')):
                        p = os.path.join(root, f)
                        try:
                            im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
                            if im is not None:
                                self.templates[f] = im
                        except Exception:
                            pass

    def get_candidates(self, rarity: str, width: int, height: int) -> List[Dict[str, Any]]:
        """
        根据品质与尺寸索引可能候选 (考虑长宽旋转)。
        委托共享 ItemIdentityResolver，同时支持测试中对 catalog_by_shape_rarity 的显式注入。
        """
        rarity_map = {"白": "white", "灰": "white", "绿": "green", "蓝": "blue", "紫": "purple", "金": "gold", "红": "red"}
        r_norm = rarity_map.get(rarity, str(rarity or "").lower())
        
        # If test specifically mock-injected candidates into self.catalog_by_shape_rarity:
        has_mock = False
        if hasattr(self, "catalog_by_shape_rarity"):
            for w_k, h_k in [(width, height), (height, width)]:
                if (f"{w_k}x{h_k}", r_norm) in self.catalog_by_shape_rarity:
                    has_mock = True
                    break
        if has_mock:
            candidates = []
            for (w, h) in [(width, height), (height, width)]:
                key = (f"{w}x{h}", r_norm)
                if key in self.catalog_by_shape_rarity:
                    for it in self.catalog_by_shape_rarity[key]:
                        if it not in candidates:
                            candidates.append(it)
            return candidates

        from item_identity_resolver import get_global_item_identity_resolver
        resolver = get_global_item_identity_resolver(self.catalog_path)
        return resolver.resolve_candidates(width, height, rarity)

    def match_candidates(self, roi_img: np.ndarray, candidates: List[Dict[str, Any]], config: WarehouseVisionConfig) -> Tuple[Optional[Dict[str, Any]], float, float]:
        """
        对候选集执行真正像素级 Template Matching。
        严禁使用 candidates[0]！
        返回: (best_item, top1_score, margin_score)
        """
        best, score, margin, evidence = self.match_candidate_evidence(roi_img, candidates, config)
        if best is not None and evidence.get("accepted") and evidence.get("referenceKind") == "DIRECT":
            return {key: value for key, value in best.items() if key != "_matchReferenceKind"}, score, margin
        # A derived appearance is useful for candidate ranking only. It can
        # never self-promote into the old exact-identity authorization.
        return None, score, margin

    def match_candidate_evidence(
        self,
        roi_img: np.ndarray,
        candidates: List[Dict[str, Any]],
        config: WarehouseVisionConfig,
    ) -> Tuple[Optional[Dict[str, Any]], float, float, Dict[str, Any]]:
        """Return the strict winner and its reference provenance.

        DIRECT means a pre-existing legacy template or a hash-verified,
        independently labelled real-match crop. Settlement provenance remains
        attached to the reference and never supplies facts for the current match.
        DERIVED_UNVERIFIED may rank a candidate, but the caller must keep it unresolved.
        """
        if not candidates or roi_img is None or roi_img.size == 0:
            return None, 0.0, 0.0, {"referenceKind": "NONE", "accepted": False}

        scores: List[Tuple[float, Optional[float], int, Dict[str, Any]]] = []
        direct_sources: Dict[int, str] = {}
        for index, candidate in enumerate(candidates):
            catalog_id = str(candidate.get("Id") or candidate.get("catalogId") or "")
            derived_entry = self.derived_templates_by_id.get(catalog_id)
            derived = derived_entry.get("image") if isinstance(derived_entry, dict) else None
            direct_score, direct_source = self.score_direct_reference(roi_img, candidate)
            derived_score: Optional[float] = None
            if direct_source != "NONE":
                direct_sources[index] = direct_source
            if derived is not None:
                derived_score = self._template_match_score(roi_img, derived)
            scores.append((direct_score, derived_score, index, candidate))

        # Keep the pre-existing confidence and margin gate for all trusted
        # direct references. Derived images are considered only when direct
        # references do not already produce an exact result.
        direct_ranked = sorted(scores, key=lambda row: (-row[0], row[2]))
        direct_top = direct_ranked[0]
        direct_second = direct_ranked[1][0] if len(direct_ranked) > 1 else 0.0
        direct_margin = direct_top[0] - direct_second
        if (direct_top[0] >= config.MATCH_CONFIDENCE_THRESHOLD
                and direct_margin >= config.MATCH_MARGIN_THRESHOLD):
            direct_item = direct_top[3]
            return {**direct_item, "_matchReferenceKind": "DIRECT"}, direct_top[0], direct_margin, {
                "referenceKind": "DIRECT",
                "referenceSource": direct_sources.get(direct_top[2], "LEGACY_CATALOG_TEMPLATE"),
                "accepted": True,
                "catalogId": str(direct_item.get("Id") or direct_item.get("catalogId") or ""),
            }

        combined_value = lambda row: max(row[0], row[1]) if row[1] is not None else row[0]
        scores.sort(key=lambda row: (-combined_value(row), row[2]))
        if not scores:
            return None, 0.0, 0.0, {"referenceKind": "NONE", "accepted": False}
        top_direct, top_derived, _, top_item = scores[0]
        top_score = max(top_direct, top_derived) if top_derived is not None else top_direct
        if top_derived is not None and top_derived > top_direct:
            reference_kind = "DERIVED_UNVERIFIED"
        elif top_direct > 0:
            reference_kind = "DIRECT"
        elif top_derived is not None and top_derived > 0:
            reference_kind = "DERIVED_UNVERIFIED"
        else:
            reference_kind = "NONE"
        second_score = combined_value(scores[1]) if len(scores) > 1 else 0.0
        margin = top_score - second_score
        accepted = top_score >= config.MATCH_CONFIDENCE_THRESHOLD and margin >= config.MATCH_MARGIN_THRESHOLD
        evidence = {
            "referenceKind": reference_kind,
            "referenceSource": direct_sources.get(scores[0][2]) if reference_kind == "DIRECT" else (
                "DERIVED_CATALOG_REFERENCE" if reference_kind == "DERIVED_UNVERIFIED" else "NONE"
            ),
            "accepted": accepted,
            "catalogId": str(top_item.get("Id") or top_item.get("catalogId") or ""),
        }
        return {**top_item, "_matchReferenceKind": reference_kind}, top_score, margin, evidence

    def score_direct_reference(self, roi_img: np.ndarray, candidate: Dict[str, Any]) -> Tuple[float, str]:
        """Score only references permitted to produce an exact identity."""
        img_file = candidate.get("File") or candidate.get("ImageFile")
        direct = getattr(self, "templates", {}).get(img_file) if img_file else None
        if direct is None:
            cand_name = str(candidate.get("Name") or "")
            direct = next((image for filename, image in getattr(self, "templates", {}).items()
                           if cand_name and cand_name in filename), None)
        best_score = self._template_match_score(roi_img, direct) if direct is not None else 0.0
        best_source = "LEGACY_CATALOG_TEMPLATE" if best_score > 0 else "NONE"

        catalog_id = str(candidate.get("Id") or candidate.get("catalogId") or "")
        roi_h, roi_w = roi_img.shape[:2]
        roi_aspect = roi_w / max(1, roi_h)
        for reference in getattr(self, "gameplay_templates_by_id", {}).get(catalog_id, []):
            template = reference.get("image") if isinstance(reference, dict) else None
            metadata = reference.get("metadata") if isinstance(reference, dict) else None
            if template is None or not isinstance(metadata, dict):
                continue
            ref_width = int(metadata.get("widthCells") or 0)
            ref_height = int(metadata.get("heightCells") or 0)
            if ref_width <= 0 or ref_height <= 0:
                continue
            # Do not squash a 1x2 sample into a 2x1 slot. Only compare a
            # stored crop in the orientation in which it was annotated.
            ref_aspect = ref_width / ref_height
            if abs(np.log(max(roi_aspect, 1e-8) / ref_aspect)) > 0.18:
                continue
            score = self._template_match_score(roi_img, template)
            if score > best_score:
                best_score = score
                best_source = (
                    "VERIFIED_SETTLEMENT_REFERENCE"
                    if str(metadata.get("sourceSceneKind") or "").upper() == "SETTLEMENT"
                    else "VERIFIED_GAMEPLAY_REFERENCE"
                )
        return best_score, best_source

    @staticmethod
    def _template_match_score(roi_img: np.ndarray, template: np.ndarray) -> float:
        if roi_img is None or template is None or not roi_img.size or not template.size:
            return 0.0
        try:
            resized = cv2.resize(template, (roi_img.shape[1], roi_img.shape[0]))
            result = cv2.matchTemplate(roi_img, resized, cv2.TM_CCOEFF_NORMED)
            return float(cv2.minMaxLoc(result)[1])
        except Exception:
            return 0.0

# ==============================================================================
# 4. Warehouse Vision v1 主引擎与时序追踪器
# ==============================================================================
class WarehouseVisionV1:
    def __init__(self, config: Optional[WarehouseVisionConfig] = None, catalog_path: Optional[str] = None):
        self.config = config or WarehouseVisionConfig()
        self.matcher = WarehouseTemplateMatcher(catalog_path=catalog_path)
        self.tracked_blobs: Dict[int, TrackedSlotBlob] = {}
        self.next_track_id: int = 1
        self.frame_index: int = 0
        self.last_grid: Optional[Dict[str, Any]] = None

    def reset(self):
        """重置所有追踪状态 (换局或刷新时调用)"""
        self.tracked_blobs.clear()
        self.next_track_id = 1
        self.frame_index = 0
        self.last_grid = None

    def process_frame(self, frame: np.ndarray, grid_roi_norm: Optional[Tuple[float, float, float, float]] = None) -> Dict[str, Any]:
        """
        处理单帧画面，更新时序追踪与证据分层
        grid_roi_norm: 归一化右侧网格区域 (X1, Y1, X2, Y2)，默认覆盖 10x25 仓库可视区
        """
        self.frame_index += 1
        h, w = frame.shape[:2]

        if grid_roi_norm is None:
            # 真实仓库在「我的资产」标题下。HUD 应从捕获层排除，这里用完整可见网格。
            try:
                from roi_scaler import ROIScaler, NORMALIZED_ROIS
                if "warehouse_board" in NORMALIZED_ROIS:
                    grid_roi_norm = NORMALIZED_ROIS["warehouse_board"]
                else:
                    grid_roi_norm = (0.685, 0.20, 0.978, 0.755)
            except Exception:
                grid_roi_norm = (0.685, 0.20, 0.978, 0.755)

        gx1, gy1 = int(w * grid_roi_norm[0]), int(h * grid_roi_norm[1])
        gx2, gy2 = int(w * grid_roi_norm[2]), int(h * grid_roi_norm[3])

        crop = frame[gy1:gy2, gx1:gx2]
        if crop.size == 0:
            return self._build_output([])

        grid = self._measure_board_grid(crop, gx1, gy1)
        self.last_grid = grid

        # 1. 视口格子占用 -> 静止 Slot（同色相邻格合并，不再用外接矩形估尺寸）
        detected_blobs = self._extract_viewport_slots(crop, gx1, gy1, grid)

        # 2. 空间关联 (Blob Association with TrackId)
        self._associate_and_update_tracks(detected_blobs, crop, gx1, gy1)

        # 3. 证据分层评估与估值计算
        confirmed_slots, unconfirmed_slots = self._evaluate_all_tracks(crop, gx1, gy1)

        return self._build_output(confirmed_slots + unconfirmed_slots)

    def _measure_board_grid(self, crop: np.ndarray, offset_x: int, offset_y: int) -> Dict[str, Any]:
        """在 Board 内测量规则网格。用边缘周期，不假定 crop 里恰好 10 列。"""
        ch, cw = crop.shape[:2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        col_edge = np.abs(gx).mean(axis=0)
        row_edge = np.abs(gy).mean(axis=1)

        # 完整 Board 约 10 列；装满藏品时 2 格谐波会更强，必须优先基频。
        fallback_w = max(16.0, min(cw / 8.0, ch / 10.0))
        fallback_h = fallback_w
        min_span = float(min(cw, ch))
        lo = max(16, int(min_span * 0.05))
        hi = max(lo + 8, int(min_span * 0.28))

        cell_w, score_w = self._acf_period(col_edge, lo, hi, preferred=cw / 10.0)
        cell_h, score_h = self._acf_period(row_edge, lo, hi, preferred=ch / 10.0)
        if score_w < 0.18:
            cell_w = fallback_w
        if score_h < 0.18:
            cell_h = fallback_h
        # 仓库格是方的。列周期通常比行更干净，行轴跟列。
        if score_w >= 0.18:
            if score_h < 0.18 or abs(cell_w - cell_h) / max(cell_w, cell_h) > 0.04:
                cell_h = cell_w
        elif score_h >= 0.18:
            cell_w = cell_h
        cell_w = max(16.0, float(cell_w))
        cell_h = max(16.0, float(cell_h))

        origin_x = self._grid_phase(col_edge, cell_w)
        origin_y = self._grid_phase(row_edge, cell_h)
        # ROI 左/上贴着网格时，相位不应滑进第一格中间。
        if origin_x > 0.35 * cell_w:
            origin_x = max(0.0, origin_x - cell_w)
        if origin_y > 0.45 * cell_h:
            origin_y = max(0.0, origin_y - cell_h)
        # Only complete cells support a physical slot; rounding up samples scene
        # background beyond the board as an extra bottom row or right column.
        cols = max(1, int((cw - origin_x) / cell_w))
        rows = max(1, int((ch - origin_y) / cell_h))
        cols = min(12, max(1, cols))
        rows = min(20, max(1, rows))
        col_centers = [offset_x + origin_x + (i + 0.5) * cell_w for i in range(cols)]
        row_centers = [offset_y + origin_y + (j + 0.5) * cell_h for j in range(rows)]
        return {
            "cols": cols,
            "rows": rows,
            "cell_w": float(cell_w),
            "cell_h": float(cell_h),
            "origin": (offset_x + origin_x, offset_y + origin_y),
            "col_centers": col_centers,
            "row_centers": row_centers,
            "score": (round(float(score_w), 3), round(float(score_h), 3)),
        }

    def _acf_period(self, profile: np.ndarray, lo: int, hi: int, preferred: Optional[float] = None) -> Tuple[float, float]:
        x = profile.astype(np.float32)
        x = x - float(x.mean())
        if float(np.linalg.norm(x)) < 1e-3 or profile.size < lo + 2:
            return 0.0, 0.0
        ac = np.correlate(x, x, mode="full")[len(x) - 1:]
        if float(ac[0]) <= 1e-6:
            return 0.0, 0.0
        ac = ac / ac[0]
        hi = min(hi, len(ac) - 1)
        if hi <= lo:
            return 0.0, 0.0
        window = ac[lo:hi + 1]
        peaks = []
        for i in range(1, len(window) - 1):
            if window[i] >= window[i - 1] and window[i] >= window[i + 1] and window[i] >= 0.18:
                peaks.append((float(window[i]), float(lo + i)))
        if not peaks:
            peak_i = int(np.argmax(window))
            return float(lo + peak_i), float(window[peak_i])
        peaks.sort(reverse=True)
        best_score, best_p = peaks[0]
        # 装满时 2x 谐波更强：若存在约一半周期的基频，用基频。
        for score, period in sorted(peaks, key=lambda t: t[1]):
            if period >= best_p * 0.72:
                continue
            if score < 0.18:
                continue
            ratio = best_p / period
            nearest = round(ratio)
            if 2 <= nearest <= 4 and abs(ratio - nearest) <= 0.18:
                best_score, best_p = score, period
                break
        if preferred and preferred > 0:
            near = [(abs(period - preferred), score, period) for score, period in peaks if score >= 0.18]
            if near:
                near.sort()
                _dist, score, period = near[0]
                if abs(period - preferred) <= max(6.0, 0.22 * preferred):
                    return period, score
        return best_p, best_score

    def _grid_phase(self, edge_prof: np.ndarray, period: float) -> float:
        if period < 8 or edge_prof.size < int(period) * 2:
            return 0.0
        n = len(edge_prof)
        step = float(period)
        best_o, best_s = 0.0, -1.0
        samples = max(8, int(period))
        for k in range(samples):
            origin = step * k / samples
            idxs = np.arange(origin, n, step)
            ii = np.clip(np.round(idxs).astype(int), 0, n - 1)
            score = float(edge_prof[ii].mean()) if ii.size else 0.0
            if score > best_s:
                best_s, best_o = score, float(origin)
        return best_o

    def _map_box_to_cells(self, local_box: Tuple[int, int, int, int], grid: Optional[Dict[str, Any]], offset_x: int, offset_y: int) -> Tuple[int, int, int, int]:
        x, y, bw, bh = local_box
        grid = grid or {}
        cell_w = max(8.0, float(grid.get("cell_w") or 32.0))
        cell_h = max(8.0, float(grid.get("cell_h") or 32.0))
        ox, oy = grid.get("origin") or (offset_x, offset_y)
        ox_l = float(ox) - offset_x
        oy_l = float(oy) - offset_y
        cols = max(1, int(grid.get("cols") or 1))
        rows = max(1, int(grid.get("rows") or 1))
        inset_x = 0.18 * cell_w
        inset_y = 0.18 * cell_h
        left, right = x + inset_x, x + bw - inset_x
        top, bottom = y + inset_y, y + bh - inset_y
        if right <= left:
            left, right = float(x), float(x + bw)
        if bottom <= top:
            top, bottom = float(y), float(y + bh)
        col0 = int(np.floor((left - ox_l) / cell_w))
        col1 = int(np.floor((right - 1e-3 - ox_l) / cell_w))
        row0 = int(np.floor((top - oy_l) / cell_h))
        row1 = int(np.floor((bottom - 1e-3 - oy_l) / cell_h))
        col0 = max(0, min(cols - 1, col0))
        col1 = max(0, min(cols - 1, col1))
        row0 = max(0, min(rows - 1, row0))
        row1 = max(0, min(rows - 1, row1))
        if col1 < col0:
            col1 = col0
        if row1 < row0:
            row1 = row0
        return col0, row0, col1 - col0 + 1, row1 - row0 + 1

    def _blob_has_edge_glow(self, crop: np.ndarray, box: Tuple[int, int, int, int]) -> bool:
        """边缘绕光 = 品质+完整轮廓。只知道品质时色块无光，不能锁形状。"""
        x, y, bw, bh = box
        if bw < 6 or bh < 6:
            return False
        pad = 2
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(crop.shape[1], x + bw + pad)
        y2 = min(crop.shape[0], y + bh + pad)
        roi = crop[y1:y2, x1:x2]
        if roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        bright = float((gray > 170).mean())
        sat = float(hsv[:, :, 1].mean())
        # 绕光：外圈更亮，且不是整块高饱和填色
        ring = np.ones(gray.shape, dtype=bool)
        inn = gray.copy()
        m = 3
        if gray.shape[0] > m * 2 and gray.shape[1] > m * 2:
            ring[m:-m, m:-m] = False
            inner = gray[m:-m, m:-m]
            ring_mean = float(gray[ring].mean()) if ring.any() else 0.0
            inner_mean = float(inner.mean()) if inner.size else 0.0
            return (ring_mean - inner_mean) >= 12.0 or (bright >= 0.08 and sat >= 40)
        return bright >= 0.12

    def _extract_viewport_slots(self, crop: np.ndarray, offset_x: int, offset_y: int, grid: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """按真实格子采样占用，再把同色 4-连通格收成一件。"""
        grid = grid or self.last_grid or {}
        cols = max(1, int(grid.get("cols") or 1))
        rows = max(1, int(grid.get("rows") or 1))
        cell_w = max(8.0, float(grid.get("cell_w") or 32.0))
        cell_h = max(8.0, float(grid.get("cell_h") or 32.0))
        ox, oy = grid.get("origin") or (offset_x, offset_y)
        occ = [[None for _ in range(cols)] for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                occ[r][c] = self._classify_grid_cell(crop, offset_x, offset_y, ox, oy, c, r, cell_w, cell_h)
        return self._group_occupied_cells(occ, crop, offset_x, offset_y, ox, oy, cell_w, cell_h)

    def _cell_rect(self, ox: float, oy: float, col: int, row: int, cell_w: float, cell_h: float, inset: float = 0.22) -> Tuple[int, int, int, int]:
        x1 = int(round(ox + col * cell_w + inset * cell_w))
        y1 = int(round(oy + row * cell_h + inset * cell_h))
        x2 = int(round(ox + (col + 1) * cell_w - inset * cell_w))
        y2 = int(round(oy + (row + 1) * cell_h - inset * cell_h))
        if x2 <= x1:
            x1 = int(round(ox + col * cell_w))
            x2 = int(round(ox + (col + 1) * cell_w))
        if y2 <= y1:
            y1 = int(round(oy + row * cell_h))
            y2 = int(round(oy + (row + 1) * cell_h))
        return x1, y1, x2, y2

    def _classify_grid_cell(self, crop: np.ndarray, offset_x: int, offset_y: int, ox: float, oy: float, col: int, row: int, cell_w: float, cell_h: float) -> Optional[Dict[str, Any]]:
        gx1, gy1, gx2, gy2 = self._cell_rect(ox, oy, col, row, cell_w, cell_h, inset=0.10)
        x1 = max(0, gx1 - offset_x)
        y1 = max(0, gy1 - offset_y)
        x2 = min(crop.shape[1], gx2 - offset_x)
        y2 = min(crop.shape[0], gy2 - offset_y)
        if x2 - x1 < 6 or y2 - y1 < 6:
            return None
        roi = crop[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hh, ww = hsv.shape[:2]
        core = hsv[int(hh * 0.32):int(hh * 0.68), int(ww * 0.32):int(ww * 0.68)]
        core_v = float(core[:, :, 2].mean()) if core.size else float(hsv[:, :, 2].mean())
        core_s = float(core[:, :, 1].mean()) if core.size else float(hsv[:, :, 1].mean())
        side_votes = []
        t = max(2, int(min(hh, ww) * 0.16))
        for side in (hsv[:t, :], hsv[-t:, :], hsv[:, :t], hsv[:, -t:]):
            sat = (side[:, :, 1] >= 55) & (side[:, :, 2] >= 55)
            hues = side[:, :, 0][sat]
            if hues.size < 6:
                continue
            side_votes.append(self._hue_to_rarity(float(np.median(hues))))
        rarity = None
        agree = 0
        fill = 0.0
        if side_votes:
            rarity = max(set(side_votes), key=side_votes.count)
            agree = side_votes.count(rarity)
            fill = agree / 4.0
        mean_v = float(hsv[:, :, 2].mean())
        # 至少两边同色才算占用。单边是邻格漏框。
        if rarity is None or agree < 3:
            if core_v >= 50 and core_s <= 70:
                return {"rarity": "unknown", "fill": 1.0, "has_glow": False, "mean_v": mean_v}
            return None
        if core_v < 42.0:
            return None
        has_glow = self._blob_has_edge_glow(crop, (x1, y1, x2 - x1, y2 - y1))
        interior_hue = None
        if core.size:
            sat_core = (core[:, :, 1] >= 50) & (core[:, :, 2] >= 55)
            hues = core[:, :, 0][sat_core]
            if hues.size >= 6:
                interior_hue = float(np.median(hues))
        return {
            "rarity": rarity,
            "fill": fill,
            "has_glow": has_glow,
            "mean_v": mean_v,
            "interior_hue": interior_hue,
        }

    def _hue_to_rarity(self, hue: float) -> str:
        if hue <= 10 or hue >= 168:
            return "red"
        if hue < 34:
            return "gold"
        if hue < 88:
            return "green"
        if hue < 125:
            return "blue"
        return "purple"

    def _group_occupied_cells(self, occ: List[List[Optional[Dict[str, Any]]]], crop: np.ndarray, offset_x: int, offset_y: int, ox: float, oy: float, cell_w: float, cell_h: float) -> List[Dict[str, Any]]:
        rows = len(occ)
        cols = len(occ[0]) if occ else 0
        self._absorb_interior_highlights(occ)
        seen = [[False] * cols for _ in range(rows)]
        slots = []
        for r0 in range(rows):
            for c0 in range(cols):
                seed = occ[r0][c0]
                if not seed or seen[r0][c0]:
                    continue
                rarity = seed["rarity"]
                w_cells, h_cells = self._grow_solid_rect(
                    occ, crop, offset_x, offset_y, ox, oy, cell_w, cell_h, c0, r0, rarity
                )
                cells = [(r0 + dr, c0 + dc) for dr in range(h_cells) for dc in range(w_cells)]
                for r, c in cells:
                    seen[r][c] = True
                row, col = r0, c0
                cell_count = w_cells * h_cells
                shape_locked = (
                    rarity == "unknown"
                    or any(occ[r][c].get("has_glow") for r, c in cells)
                    or cell_count >= 2
                )
                gx1 = int(round(ox + col * cell_w))
                gy1 = int(round(oy + row * cell_h))
                gx2 = int(round(ox + (col + w_cells) * cell_w))
                gy2 = int(round(oy + (row + h_cells) * cell_h))
                local = (gx1 - offset_x, gy1 - offset_y, gx2 - gx1, gy2 - gy1)
                has_glow = any(bool(occ[r][c].get("has_glow")) for r, c in cells)
                surround_locked = False
                if w_cells == 1 and h_cells == 1 and rarity != "unknown" and not shape_locked:
                    neighbors = 0
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nr, nc = row + dr, col + dc
                        if 0 <= nr < rows and 0 <= nc < cols and occ[nr][nc] is not None:
                            neighbors += 1
                    if neighbors >= 2:
                        shape_locked = True
                        surround_locked = True
                fill_mean = float(np.mean([occ[r][c].get("fill") or 0 for r, c in cells]))
                if rarity == "unknown" and fill_mean < 0.50:
                    continue
                if fill_mean < 0.50 and not surround_locked:
                    continue
                if w_cells >= 6 or h_cells >= 6:
                    continue
                slots.append({
                    "local_box": local,
                    "global_box": (gx1, gy1, gx2 - gx1, gy2 - gy1),
                    "rarity": rarity,
                    "col": col,
                    "row": row,
                    "w_cells": w_cells,
                    "h_cells": h_cells,
                    "cell_count": cell_count,
                    "has_glow": has_glow,
                    "shape_locked": shape_locked,
                    "surround_locked": surround_locked,
                    "cells": cells,
                })
        return slots

    def _grow_solid_rect(
        self,
        occ: List[List[Optional[Dict[str, Any]]]],
        crop: np.ndarray,
        offset_x: int,
        offset_y: int,
        ox: float,
        oy: float,
        cell_w: float,
        cell_h: float,
        col: int,
        row: int,
        rarity: str,
    ) -> Tuple[int, int]:
        """从左上格向右/向下扩张成实心矩形；遇到不同色或格缝就停。"""
        rows = len(occ)
        cols = len(occ[0]) if occ else 0

        def same(c: int, r: int) -> bool:
            cell = occ[r][c] if 0 <= r < rows and 0 <= c < cols else None
            return bool(cell) and cell["rarity"] == rarity and float(cell.get("fill") or 0) >= 0.70

        def grow(first_right: bool) -> Tuple[int, int, float]:
            width, height = 1, 1
            order = (True, False) if first_right else (False, True)
            changed = True
            while changed:
                changed = False
                for do_right in order:
                    if do_right and col + width < cols and all(
                        same(col + width, row + rr)
                        and self._shared_edge_is_interior(
                            crop, offset_x, offset_y, ox, oy, cell_w, cell_h,
                            col + width - 1, row + rr, col + width, row + rr,
                        )
                        and not self._has_item_gutter(
                            crop, offset_x, offset_y, ox, oy, cell_w, cell_h,
                            col + width - 1, row + rr, col + width, row + rr,
                        )
                        for rr in range(height)
                    ):
                        width += 1
                        changed = True
                    if (not do_right) and row + height < rows and all(
                        same(col + cc, row + height)
                        and self._shared_edge_is_interior(
                            crop, offset_x, offset_y, ox, oy, cell_w, cell_h,
                            col + cc, row + height - 1, col + cc, row + height,
                        )
                        and not self._has_item_gutter(
                            crop, offset_x, offset_y, ox, oy, cell_w, cell_h,
                            col + cc, row + height - 1, col + cc, row + height,
                        )
                        for cc in range(width)
                    ):
                        height += 1
                        changed = True
            fills = [
                float(occ[row + rr][col + cc].get("fill") or 0)
                for rr in range(height) for cc in range(width)
            ]
            return width, height, float(np.mean(fills)) if fills else 0.0

        a = grow(True)
        b = grow(False)
        # 先取更大的实心矩形，避免先往下吃到另一件。
        pick = a if (a[0] * a[1], a[2]) >= (b[0] * b[1], b[2]) else b
        return pick[0], pick[1]

    def _absorb_interior_highlights(self, occ: List[List[Optional[Dict[str, Any]]]]) -> None:
        """同一件内部的白边/高光格并回邻接主色，不当第二件。"""
        rows = len(occ)
        cols = len(occ[0]) if occ else 0
        changed = True
        while changed:
            changed = False
            for r in range(rows):
                for c in range(cols):
                    cell = occ[r][c]
                    if not cell:
                        continue
                    neigh = []
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < rows and 0 <= nc < cols and occ[nr][nc]:
                            neigh.append(occ[nr][nc]["rarity"])
                    hosts = [q for q in neigh if q not in ("white", "unknown") and q != cell["rarity"]]
                    if not hosts:
                        continue
                    host = max(set(hosts), key=hosts.count)
                    # 被同一主色至少三面围住：内部高光/金属反光，不是另一件。
                    if hosts.count(host) >= 3 and all(q == host for q in hosts):
                        cell["rarity"] = host
                        cell["fill"] = max(float(cell.get("fill") or 0), 0.75)
                        changed = True

    def _side_frame_strength(
        self,
        crop: np.ndarray,
        offset_x: int,
        offset_y: int,
        ox: float,
        oy: float,
        cell_w: float,
        cell_h: float,
        col: int,
        row: int,
        side: str,
    ) -> float:
        gx1, gy1, gx2, gy2 = self._cell_rect(ox, oy, col, row, cell_w, cell_h, inset=0.10)
        x1 = max(0, gx1 - offset_x)
        y1 = max(0, gy1 - offset_y)
        x2 = min(crop.shape[1], gx2 - offset_x)
        y2 = min(crop.shape[0], gy2 - offset_y)
        if x2 - x1 < 6 or y2 - y1 < 6:
            return 0.0
        roi = crop[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hh, ww = hsv.shape[:2]
        t = max(2, int(min(hh, ww) * 0.16))
        if side == "top":
            band = hsv[:t, t:ww - t] if ww > t * 2 else hsv[:t, :]
        elif side == "bottom":
            band = hsv[-t:, t:ww - t] if ww > t * 2 else hsv[-t:, :]
        elif side == "left":
            band = hsv[t:hh - t, :t] if hh > t * 2 else hsv[:, :t]
        else:
            band = hsv[t:hh - t, -t:] if hh > t * 2 else hsv[:, -t:]
        if band.size == 0:
            return 0.0
        core = hsv[int(hh * 0.32):int(hh * 0.68), int(ww * 0.32):int(ww * 0.68)]
        if core.size == 0:
            return 0.0
        sat = (band[:, :, 1] >= 55) & (band[:, :, 2] >= 55)
        if float(np.count_nonzero(sat)) / float(band[:, :, 0].size) < 0.35:
            return 0.0
        side_h = float(np.median(band[:, :, 0][sat])) if np.any(sat) else 0.0
        core_sat = (core[:, :, 1] >= 40) & (core[:, :, 2] >= 40)
        if np.count_nonzero(core_sat) >= 6:
            core_h = float(np.median(core[:, :, 0][core_sat]))
            # 边框色和内部图标/填色接近：这是大件内部，不是另一张卡。
            if abs(side_h - core_h) <= 14 or abs(side_h - core_h) >= 166:
                return 0.15
        return float(np.count_nonzero(sat)) / float(band[:, :, 0].size or 1)

    def _shared_edge_is_interior(
        self,
        crop: np.ndarray,
        offset_x: int,
        offset_y: int,
        ox: float,
        oy: float,
        cell_w: float,
        cell_h: float,
        c0: int,
        r0: int,
        c1: int,
        r1: int,
    ) -> bool:
        """两张独立卡的对贴边都有品质框；同一件内部对贴边很弱。"""
        if c0 == c1:
            a = self._side_frame_strength(crop, offset_x, offset_y, ox, oy, cell_w, cell_h, c0, min(r0, r1), "bottom")
            b = self._side_frame_strength(crop, offset_x, offset_y, ox, oy, cell_w, cell_h, c1, max(r0, r1), "top")
        else:
            a = self._side_frame_strength(crop, offset_x, offset_y, ox, oy, cell_w, cell_h, min(c0, c1), r0, "right")
            b = self._side_frame_strength(crop, offset_x, offset_y, ox, oy, cell_w, cell_h, max(c0, c1), r1, "left")
        # 两张独立卡：对贴的两边都是完整品质框。同一件内部至少有一边很弱。
        return not (a >= 0.78 and b >= 0.78)

    def _rect_has_unified_frame(
        self,
        crop: np.ndarray,
        offset_x: int,
        offset_y: int,
        ox: float,
        oy: float,
        cell_w: float,
        cell_h: float,
        col: int,
        row: int,
        width: int,
        height: int,
        rarity: str,
    ) -> bool:
        """多格要像同一张卡：外圈连续品质框，中间没有第二条卡缝。"""
        if width == 1 and height == 1:
            return True
        gx1 = int(round(ox + col * cell_w))
        gy1 = int(round(oy + row * cell_h))
        gx2 = int(round(ox + (col + width) * cell_w))
        gy2 = int(round(oy + (row + height) * cell_h))
        x1 = max(0, gx1 - offset_x)
        y1 = max(0, gy1 - offset_y)
        x2 = min(crop.shape[1], gx2 - offset_x)
        y2 = min(crop.shape[0], gy2 - offset_y)
        if x2 - x1 < 8 or y2 - y1 < 8:
            return False
        roi = crop[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hh, ww = hsv.shape[:2]
        t = max(2, int(min(hh, ww) * 0.08))
        ring = np.zeros((hh, ww), dtype=bool)
        ring[:t, :] = True
        ring[-t:, :] = True
        ring[:, :t] = True
        ring[:, -t:] = True
        sat = ring & (hsv[:, :, 1] >= 45) & (hsv[:, :, 2] >= 45)
        hues = hsv[:, :, 0][sat]
        if hues.size < 12:
            return False
        agree = float(np.mean([self._hue_to_rarity(float(h)) == rarity for h in hues]))
        return agree >= 0.40

    def _cell_interior_mean(self, crop: np.ndarray, offset_x: int, offset_y: int, ox: float, oy: float, col: int, row: int, cell_w: float, cell_h: float) -> float:
        gx1, gy1, gx2, gy2 = self._cell_rect(ox, oy, col, row, cell_w, cell_h, inset=0.32)
        x1 = max(0, gx1 - offset_x)
        y1 = max(0, gy1 - offset_y)
        x2 = min(crop.shape[1], gx2 - offset_x)
        y2 = min(crop.shape[0], gy2 - offset_y)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        return float(cv2.cvtColor(crop[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY).mean())

    def _has_item_gutter(self, crop: np.ndarray, offset_x: int, offset_y: int, ox: float, oy: float, cell_w: float, cell_h: float, c0: int, r0: int, c1: int, r1: int) -> bool:
        """只看格子交界 5px：两件之间是暗缝，同一件内部是连续填色。"""
        if abs(c1 - c0) + abs(r1 - r0) != 1:
            return False
        if c0 == c1:
            y = int(round(oy + max(r0, r1) * cell_h))
            x1 = int(round(ox + c0 * cell_w + 0.28 * cell_w))
            x2 = int(round(ox + (c0 + 1) * cell_w - 0.28 * cell_w))
            ly = y - offset_y
            if ly < 1 or ly >= crop.shape[0] - 1 or x2 <= x1:
                return False
            band = crop[max(0, ly - 2):min(crop.shape[0], ly + 3), max(0, x1 - offset_x):max(0, x2 - offset_x)]
        else:
            x = int(round(ox + max(c0, c1) * cell_w))
            y1 = int(round(oy + r0 * cell_h + 0.28 * cell_h))
            y2 = int(round(oy + (r0 + 1) * cell_h - 0.28 * cell_h))
            lx = x - offset_x
            if lx < 1 or lx >= crop.shape[1] - 1 or y2 <= y1:
                return False
            band = crop[max(0, y1 - offset_y):max(0, y2 - offset_y), max(0, lx - 2):min(crop.shape[1], lx + 3)]
        if band.size == 0:
            return False
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        # Bright borders flank the dark gap. Averaging the entire strip can
        # erase a real separator; require a majority of dark cross-gap lines.
        line_means = gray.mean(axis=1 if c0 == c1 else 0)
        return float(np.median(line_means)) < 50.0

    def _extract_raw_blobs(self, crop: np.ndarray, offset_x: int, offset_y: int, grid: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """兼容旧测试：无网格时退回连通域；有网格时走视口 Slot。"""
        if grid or self.last_grid:
            return self._extract_viewport_slots(crop, offset_x, offset_y, grid)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        cell_w = max(12.0, crop.shape[1] / 10.0)
        cell_h = cell_w

        masks = {
            'red': cv2.bitwise_or(cv2.inRange(hsv, (0, 70, 70), (8, 255, 255)), cv2.inRange(hsv, (168, 70, 70), (180, 255, 255))),
            'gold': cv2.inRange(hsv, (8, 70, 70), (28, 255, 255)),
            'purple': cv2.inRange(hsv, (120, 45, 40), (165, 255, 255)),
            'blue': cv2.inRange(hsv, (90, 50, 50), (120, 255, 255)),
            'green': cv2.inRange(hsv, (35, 50, 50), (85, 255, 255)),
            'white': cv2.inRange(hsv, (0, 0, 160), (180, 40, 255)),
            'outline': cv2.inRange(hsv, (0, 0, 55), (180, 55, 150)),
        }

        raw_blobs = []
        occupied = []
        for rarity, mask in masks.items():
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in cnts:
                x, y, bw, bh = cv2.boundingRect(c)
                min_w = max(12.0, 0.40 * cell_w)
                min_h = max(12.0, 0.40 * cell_h)
                if bw < min_w or bh < min_h:
                    continue
                col, row, w_cells, h_cells = self._map_box_to_cells((x, y, bw, bh), grid, offset_x, offset_y)
                if w_cells >= 6 or h_cells >= 6:
                    continue
                has_glow = False if rarity == "outline" else self._blob_has_edge_glow(crop, (x, y, bw, bh))
                shape_locked = (rarity == "outline") or has_glow
                blob = {
                    "local_box": (x, y, bw, bh),
                    "global_box": (offset_x + x, offset_y + y, bw, bh),
                    "rarity": "unknown" if rarity == "outline" else rarity,
                    "col": col,
                    "row": row,
                    "w_cells": w_cells,
                    "h_cells": h_cells,
                    "cell_count": w_cells * h_cells,
                    "has_glow": has_glow,
                    "shape_locked": shape_locked,
                    "surround_locked": False,
                }
                raw_blobs.append(blob)
                occupied.append((x, y, bw, bh, w_cells, h_cells))

        # 被四周占满的 1x1 有色格：即使无光也可锁 1 格（用户指出的左上红）
        for blob in raw_blobs:
            if blob["w_cells"] != 1 or blob["h_cells"] != 1 or blob["rarity"] == "unknown":
                continue
            if blob["shape_locked"]:
                continue
            x, y, bw, bh = blob["local_box"]
            cx, cy = x + bw / 2.0, y + bh / 2.0
            neighbors = 0
            for ox, oy, ow, oh, *_ in occupied:
                if (ox, oy, ow, oh) == blob["local_box"]:
                    continue
                ocx, ocy = ox + ow / 2.0, oy + oh / 2.0
                dx, dy = abs(ocx - cx), abs(ocy - cy)
                if (dx <= bw * 1.35 and dy <= bh * 0.65) or (dy <= bh * 1.35 and dx <= bw * 0.65):
                    neighbors += 1
            if neighbors >= 2:
                blob["shape_locked"] = True
                blob["surround_locked"] = True
                blob["w_cells"] = 1
                blob["h_cells"] = 1
                blob["cell_count"] = 1
        return raw_blobs

    def _compute_iou(self, boxA: Tuple[int, int, int, int], boxB: Tuple[int, int, int, int]) -> float:
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
        yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])

        interArea = max(0, xB - xA) * max(0, yB - yA)
        boxAArea = boxA[2] * boxA[3]
        boxBArea = boxB[2] * boxB[3]
        denom = float(boxAArea + boxBArea - interArea)
        return interArea / denom if denom > 0 else 0.0

    def _associate_and_update_tracks(self, detected_blobs: List[Dict[str, Any]], crop: np.ndarray, offset_x: int, offset_y: int):
        """
        基于 IoU 与品质匹配的 TrackId 时序关联算法
        """
        matched_track_ids = set()
        matched_det_indices = set()

        def _slot_key(obj) -> Tuple:
            if isinstance(obj, dict):
                return (obj.get("col"), obj.get("row"), obj.get("rarity"), obj.get("w_cells"), obj.get("h_cells"))
            return (obj.col, obj.row, obj.rarity, obj.width_cells, obj.height_cells)

        # 1. 先按视口格子身份匹配，静止画面同一件应对上同一 track。
        for det_idx, det in enumerate(detected_blobs):
            best_iou = 0.0
            best_track_id = None
            key = _slot_key(det)
            for track_id, track in self.tracked_blobs.items():
                if track_id in matched_track_ids:
                    continue
                if key == _slot_key(track) and None not in key[:3]:
                    best_track_id = track_id
                    best_iou = 1.0
                    break
                iou = self._compute_iou(det["global_box"], track.box)
                if iou > best_iou and iou >= self.config.IOU_TRACK_THRESHOLD:
                    best_iou = iou
                    best_track_id = track_id

            if best_track_id is not None:
                matched_track_ids.add(best_track_id)
                matched_det_indices.add(det_idx)
                track = self.tracked_blobs[best_track_id]
                
                # 检查属性是否连续一致
                same_shape = track.width_cells == det["w_cells"] and track.height_cells == det["h_cells"]
                same_rarity = track.rarity == det["rarity"]
                if same_shape and same_rarity:
                    track.consecutive_stable_frames += 1
                else:
                    # 发生突变，重置稳定计数
                    track.consecutive_stable_frames = 1
                    track.rarity = det["rarity"]
                    track.width_cells = det["w_cells"]
                    track.height_cells = det["h_cells"]
                    track.cell_count = det["cell_count"]
                    track.is_confirmed = False

                track.has_glow = bool(det.get("has_glow"))
                track.shape_locked = bool(det.get("shape_locked"))
                track.surround_locked = bool(det.get("surround_locked"))
                track.box = det["global_box"]
                track.col = det.get("col")
                track.row = det.get("row")
                track.last_seen_frame = self.frame_index
                if track.consecutive_stable_frames >= self.config.TEMPORAL_CONFIRM_FRAMES:
                    track.is_confirmed = True

        # 2. 对未匹配的新检测项创建新 Track
        for det_idx, det in enumerate(detected_blobs):
            if det_idx not in matched_det_indices:
                if det.get("has_glow") or det.get("surround_locked"):
                    ev = EvidenceLevel.RARITY_AND_SHAPE
                elif det.get("rarity") == "unknown":
                    ev = EvidenceLevel.OUTLINE_ONLY
                else:
                    ev = EvidenceLevel.RARITY_ONLY
                new_track = TrackedSlotBlob(
                    track_id=self.next_track_id,
                    first_seen_frame=self.frame_index,
                    last_seen_frame=self.frame_index,
                    consecutive_stable_frames=1,
                    is_confirmed=False,
                    box=det["global_box"],
                    width_cells=det["w_cells"],
                    height_cells=det["h_cells"],
                    cell_count=det["cell_count"],
                    rarity=det["rarity"],
                    evidence_level=ev,
                    has_glow=bool(det.get("has_glow")),
                    shape_locked=bool(det.get("shape_locked")),
                    surround_locked=bool(det.get("surround_locked")),
                    col=det.get("col"),
                    row=det.get("row"),
                )
                self.tracked_blobs[self.next_track_id] = new_track
                self.next_track_id += 1

        # 3. 清理长期丢失的 Track
        lost_track_ids = [
            t_id for t_id, t in self.tracked_blobs.items()
            if (self.frame_index - t.last_seen_frame) > self.config.MAX_TRACK_LOST_FRAMES
        ]
        for t_id in lost_track_ids:
            del self.tracked_blobs[t_id]

    def _evaluate_all_tracks(self, crop: np.ndarray, offset_x: int, offset_y: int) -> Tuple[List[TrackedSlotBlob], List[TrackedSlotBlob]]:
        """
        对所有存活的 Track 评估 Evidence 证据等级与价格区间
        """
        confirmed = []
        unconfirmed = []

        for track_id, track in self.tracked_blobs.items():
            track.identified_catalog_id = None
            track.best_candidate_id = None
            track.best_candidate_name = None
            track.identity_reference_kind = None
            track.match_score = 0.0
            track.margin_score = 0.0
            # 没锁形状：只报品质，不按长宽检索图鉴（避免把未展示完的紫/红当成完整件）
            if not track.shape_locked:
                track.candidates = []
                track.min_price = track.max_price = track.expected_price = 0
                track.identified_item = None
                track.evidence_level = EvidenceLevel.RARITY_ONLY if track.rarity != "unknown" else EvidenceLevel.UNKNOWN
                unconfirmed.append(track)
                continue

            from item_identity_resolver import merge_candidates
            raw_candidates = self.matcher.get_candidates(track.rarity, track.width_cells, track.height_cells)
            candidates = merge_candidates(track.candidates, raw_candidates)
            track.candidates = candidates

            prices = [c.get("Value", 0) for c in candidates if "Value" in c]
            if prices:
                track.min_price = min(prices)
                track.max_price = max(prices)
                track.expected_price = int(np.median(prices))
            else:
                track.min_price = track.max_price = track.expected_price = 0

            if track.rarity == "unknown":
                track.identified_item = None
                track.evidence_level = EvidenceLevel.OUTLINE_ONLY
                if track.is_confirmed:
                    confirmed.append(track)
                else:
                    unconfirmed.append(track)
                continue

            # 证据分级流转 (Evidence Tiering)
            if not track.is_confirmed:
                track.evidence_level = EvidenceLevel.RARITY_AND_SHAPE
                unconfirmed.append(track)
                continue

            # 已达时序稳定确认 (Confirmed)
            if len(candidates) == 1:
                # [关键规则]: 仅在 rarity+shape 达到稳定确认后，才允许锁定 UNIQUE_IN_CATALOG
                track.evidence_level = EvidenceLevel.UNIQUE_IN_CATALOG
                # Phase 19: 即使唯一候选，严禁直接升级为 EXACT，必须保留 CANDIDATE 语义且 identifiedName 维持 None
                track.identified_item = None
                track.min_price = track.max_price = track.expected_price = candidates[0].get("Value", 0)
                confirmed.append(track)
            elif len(candidates) > 1:
                # 候选 > 1: 提取局部 ROI 进行真像素级 Template Matching
                lx = max(0, track.box[0] - offset_x)
                ly = max(0, track.box[1] - offset_y)
                lw = min(crop.shape[1] - lx, track.box[2])
                lh = min(crop.shape[0] - ly, track.box[3])
                roi = crop[ly:ly+lh, lx:lx+lw]

                best_item, top1_score, margin, evidence = self.matcher.match_candidate_evidence(
                    roi, candidates, self.config
                )
                track.match_score = top1_score
                track.margin_score = margin

                reference_kind = str(evidence.get("referenceKind") or "NONE")
                best_candidate_id = str(evidence.get("catalogId") or "")
                if best_item is not None and top1_score > 0:
                    track.best_candidate_id = best_candidate_id or str(best_item.get("Id") or "") or None
                    track.best_candidate_name = str(best_item.get("Name") or "") or None
                    track.identity_reference_kind = reference_kind

                if best_item is not None and evidence.get("accepted") and reference_kind == "DIRECT":
                    # 达高置信度门槛
                    track.evidence_level = EvidenceLevel.EXACT_IDENTIFIED
                    track.identified_item = best_item
                    track.identified_catalog_id = str(best_item.get("Id") or best_item.get("catalogId") or "") or None
                    track.identity_reference_kind = "DIRECT"
                    track.min_price = track.max_price = track.expected_price = best_item.get("Value", 0)
                else:
                    # 无法可靠区分：严禁选 candidates[0]，忠实标记为 CANDIDATE_SET
                    track.evidence_level = EvidenceLevel.CANDIDATE_SET
                    track.identified_item = None
                    if reference_kind == "DERIVED_UNVERIFIED" and best_item is not None:
                        # Display the derived-reference rank as an unverified
                        # candidate only; it is not an exact identity or solver fact.
                        winner_id = str(best_item.get("Id") or best_item.get("catalogId") or "")
                        track.candidates = sorted(
                            candidates,
                            key=lambda row: str(row.get("Id") or row.get("catalogId") or "") != winner_id,
                        )

                confirmed.append(track)
            else:
                # 无图鉴候选
                track.evidence_level = EvidenceLevel.OUTLINE_ONLY
                confirmed.append(track)

        return confirmed, unconfirmed

    def _build_output(self, slots: List[TrackedSlotBlob]) -> Dict[str, Any]:
        """构建结构化输出"""
        total_min = sum(s.min_price for s in slots if s.is_confirmed)
        total_max = sum(s.max_price for s in slots if s.is_confirmed)
        total_expected = sum(s.expected_price for s in slots if s.is_confirmed)

        out = {
            "frameCount": self.frame_index,
            "totalSlots": len(slots),
            "confirmedSlots": len([s for s in slots if s.is_confirmed]),
            "totalExpectedVal": total_expected,
            "valRange": [total_min, total_max],
            "slots": [s.to_dict() for s in slots],
        }
        if self.last_grid:
            out["grid"] = {
                "cols": self.last_grid.get("cols"),
                "rows": self.last_grid.get("rows"),
                "cellW": round(float(self.last_grid.get("cell_w") or 0), 2),
                "cellH": round(float(self.last_grid.get("cell_h") or 0), 2),
                "origin": self.last_grid.get("origin"),
                "colCenters": [round(float(x), 1) for x in (self.last_grid.get("col_centers") or [])],
                "rowCenters": [round(float(y), 1) for y in (self.last_grid.get("row_centers") or [])],
            }
        return out
