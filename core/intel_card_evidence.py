"""
Auction intel-card evidence extractor and multi-frame ledger (Visual Cut 1).

Single-shot only. Observations are not Canonical Facts and not Solver input.
Missing fields stay UNKNOWN and are never filled with 0.
Card boxes are detected inside the large intel_card_stack ROI; rows are not pinned.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from roi_scaler import ROIScaler

SUPPORTED_FIELDS = (
    "q",
    "goldAvg",
    "purpleAvg",
    "goldCount",
    "purpleCount",
    "blueCount",
    "greenCount",
    "whiteCount",
    "redCount",
    "totalItems",
    "totalGrid",
    "goldGrid",
    "purpleGrid",
    "blueGrid",
    "greenGrid",
    "whiteGrid",
    "redGrid",
)

STATUS_OBSERVED = "OBSERVED"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_CONFLICT = "CONFLICT"

INTEL_STACK_ROI = "intel_card_stack"
HEADER_ROI = "header_round_timer"

_MIN_FRAME_EDGE = 400


def parse_intel_amount(text: str, min_digits: int = 3) -> Optional[int]:
    """Parse a displayed money/count group. Failure is None, never a fake 0."""
    if not text:
        return None
    compact = re.sub(r"\s+", "", str(text)).upper()
    normalized = compact.replace("，", ",").replace("．", ".").replace("、", ",")
    grouped = re.search(r"(\d{1,3}(?:[,.]\d{3})+)", normalized)
    if grouped:
        digits = re.sub(r"[,.]", "", grouped.group(1))
    else:
        m = re.search(rf"(\d{{{min_digits},}})", normalized)
        digits = m.group(1) if m else ""
    if digits.isdigit() and len(digits) >= min_digits:
        value = int(digits)
        return value if value > 0 else None
    return None


def parse_intel_count(text: str, lo: int, hi: int) -> Optional[int]:
    if not text:
        return None
    compact = re.sub(r"\s+", "", str(text))
    m = re.search(r"(\d{1,3})", compact)
    if not m:
        return None
    value = int(m.group(1))
    if lo <= value <= hi:
        return value
    return None


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).replace("：", ":").replace("，", ",")


@dataclass
class IntelCardObservation:
    field: str
    value: Any
    status: str
    frameId: str
    round: Optional[int]
    timer: Optional[int]
    cardBox: List[int]
    rawText: str
    confidence: float
    is_physical_ocr: bool = True

    def to_dict(self) -> Dict[str, Any]:
        from intel_card_source import card_source
        return {**asdict(self), 'cardSource': card_source(self.rawText)}


@dataclass
class FrameIntelEvidence:
    frameId: str
    round: Optional[int] = None
    timer: Optional[int] = None
    cards: List[List[int]] = field(default_factory=list)
    observations: List[IntelCardObservation] = field(default_factory=list)
    rawHeaderText: str = ""
    rawTitleText: str = ""
    cardReadings: List[Dict[str, Any]] = field(default_factory=list)

    def field_map(self) -> Dict[str, Any]:
        found = {obs.field: obs.value for obs in self.observations if obs.status == STATUS_OBSERVED}
        return {name: found.get(name, STATUS_UNKNOWN) for name in SUPPORTED_FIELDS}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frameId": self.frameId,
            "round": self.round,
            "timer": self.timer,
            "cards": [list(box) for box in self.cards],
            "observations": [obs.to_dict() for obs in self.observations],
            "fields": self.field_map(),
            "rawHeaderText": self.rawHeaderText,
            "rawTitleText": self.rawTitleText,
            "cardReadings": deepcopy(self.cardReadings),
        }


def strip_recording_chrome(frame: np.ndarray) -> Tuple[np.ndarray, Dict[str, int]]:
    """Drop a bright video-player bar under the game viewport. No-op on live captures."""
    if frame is None or frame.size == 0:
        return frame, {"strippedPx": 0, "y2": 0}
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
    row = gray.mean(axis=1)
    region_start = int(h * 0.82)
    y = h - 1
    dark_sliver = 0
    while y >= region_start and row[y] < 80:
        dark_sliver += 1
        y -= 1
    if dark_sliver > int(h * 0.08):
        return frame, {"strippedPx": 0, "y2": h}
    bright_run = 0
    while y >= region_start and row[y] > 140:
        bright_run += 1
        y -= 1
    if bright_run < 8:
        return frame, {"strippedPx": 0, "y2": h}
    y2 = y + 1
    return frame[:y2], {"strippedPx": h - y2, "y2": y2}


def detect_card_boxes(stack: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Detect actual card rectangles inside the intel stack crop. Count is not fixed."""
    if stack is None or stack.size == 0:
        return []
    sh, sw = stack.shape[:2]
    if sh < 40 or sw < 40:
        return []

    hsv = cv2.cvtColor(stack, cv2.COLOR_BGR2HSV)
    body = hsv[:, int(sw * 0.40) :]
    blue = cv2.inRange(body, (90, 25, 30), (140, 255, 190))
    proj = blue.mean(axis=1).astype(np.float32)
    kernel = np.ones(11, dtype=np.float32) / 11.0
    smooth = np.convolve(proj, kernel, mode="same")
    thr = max(20.0, float(np.median(smooth)) * 0.8 + 8.0)
    on = smooth > thr

    min_h = max(28, int(sh * 0.055))
    max_h = max(min_h + 8, int(sh * 0.24))
    raw_runs: List[Tuple[int, int]] = []
    start = None
    for i, flag in enumerate(on):
        if flag and start is None:
            start = i
        elif (not flag) and start is not None:
            if i - start >= min_h:
                raw_runs.append((start, i))
            start = None
    if start is not None and sh - start >= min_h:
        raw_runs.append((start, sh))

    runs: List[Tuple[int, int]] = []
    for a, b in raw_runs:
        if not runs:
            runs.append((a, b))
            continue
        pa, pb = runs[-1]
        if a - pb <= max(6, int(sh * 0.02)):
            runs[-1] = (pa, b)
        else:
            runs.append((a, b))

    split_runs: List[Tuple[int, int]] = []
    for a, b in runs:
        height = b - a
        if height <= max_h:
            split_runs.append((a, b))
            continue
        window = smooth[a:b]
        mid_lo = a + int(height * 0.35)
        mid_hi = a + int(height * 0.65)
        if mid_hi <= mid_lo or window.size == 0:
            split_runs.append((a, b))
            continue
        local = window[int(height * 0.35) : int(height * 0.65)]
        split_at = mid_lo + int(np.argmin(local))
        if split_at - a >= min_h and b - split_at >= min_h:
            split_runs.append((a, split_at))
            split_runs.append((split_at, b))
        else:
            split_runs.append((a, b))

    cards: List[Tuple[int, int, int, int]] = []
    for i, (a, b) in enumerate(split_runs):
        prev_b = split_runs[i - 1][1] if i else 0
        next_a = split_runs[i + 1][0] if i + 1 < len(split_runs) else sh
        top = (prev_b + a) // 2 if i else max(0, a - max(12, int(sh * 0.025)))
        bot = (b + next_a) // 2 if i + 1 < len(split_runs) else min(sh, b + max(12, int(sh * 0.025)))
        band = stack[a:b]
        if band.size == 0:
            continue
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        occupancy = (gray > 40).mean(axis=0)
        left = 0
        for x, val in enumerate(occupancy):
            if val > 0.12:
                left = max(0, x - 6)
                break
        right = sw - 2
        if bot - top >= min_h and right - left >= 48:
            cards.append((left, top, right, bot))
    return cards


def route_card_text(text: str) -> List[Tuple[str, int, float]]:
    """Map one card's OCR text to zero or more supported fields. Never emits 0."""
    raw = str(text or "").strip()
    if not raw:
        return []
    compact = _compact_text(raw)
    hits: List[Tuple[str, int, float]] = []

    def add(name: str, value: Optional[int], confidence: float = 0.9) -> None:
        if value is None:
            return
        if any(existing[0] == name for existing in hits):
            return
        hits.append((name, value, confidence))

    if "所有藏品" in compact and "总数量" in compact:
        add("totalItems", parse_intel_count(compact.split("总数量", 1)[-1], 1, 200), 0.92)

    q_like = (
        ("总件数" in compact)
        and ("所有藏品" not in compact)
        and (
            ("千眼" in compact)
            or ("红色" in compact and "金色" in compact and "紫色" in compact)
            or ("紫色" in compact and "金色" in compact)
        )
    )
    if q_like:
        add("q", parse_intel_count(compact.split("总件数", 1)[-1], 1, 120), 0.95)

    if "总格数" in compact:
        add("totalGrid", parse_intel_count(compact.split("总格数", 1)[-1], 1, 250), 0.9)

    if "所占格" in compact or "占格数" in compact or "所占格数" in compact:
        if "所占格" in compact:
            tail = compact.split("所占格", 1)[-1]
        elif "所占格数" in compact:
            tail = compact.split("所占格数", 1)[-1]
        else:
            tail = compact.split("占格数", 1)[-1]
        if "金色" in compact or "金品" in compact:
            add("goldGrid", parse_intel_count(tail, 1, 250), 0.9)
        elif "紫色" in compact or "紫品" in compact:
            add("purpleGrid", parse_intel_count(tail, 1, 250), 0.9)
        elif "蓝色" in compact or "蓝品" in compact:
            add("blueGrid", parse_intel_count(tail, 1, 250), 0.9)
        elif "绿色" in compact or "绿品" in compact:
            add("greenGrid", parse_intel_count(tail, 1, 250), 0.9)
        elif "白色" in compact or "白品" in compact:
            add("whiteGrid", parse_intel_count(tail, 1, 250), 0.9)
        elif "红色" in compact or "红品" in compact:
            add("redGrid", parse_intel_count(tail, 1, 250), 0.9)

    is_avg = "平均" in compact or "均价" in compact
    is_count = "总数量" in compact and "所有藏品" not in compact
    if is_avg:
        amount = parse_intel_amount(compact)
        if "金色" in compact or "金品" in compact:
            add("goldAvg", amount, 0.93)
        elif "紫色" in compact or "紫品" in compact:
            add("purpleAvg", amount, 0.93)
    if is_count and "所占格" not in compact and "占格" not in compact and not is_avg:
        tail = compact.split("总数量", 1)[-1]
        if "金色" in compact or "金品" in compact:
            add("goldCount", parse_intel_count(tail, 1, 80), 0.92)
        elif "紫色" in compact or "紫品" in compact:
            add("purpleCount", parse_intel_count(tail, 1, 80), 0.92)
        elif "蓝色" in compact or "蓝品" in compact:
            add("blueCount", parse_intel_count(tail, 1, 80), 0.9)
        elif "绿色" in compact or "绿品" in compact:
            add("greenCount", parse_intel_count(tail, 1, 80), 0.9)
        elif "白色" in compact or "白品" in compact:
            add("whiteCount", parse_intel_count(tail, 1, 80), 0.9)
        elif "红色" in compact or "红品" in compact:
            add("redCount", parse_intel_count(tail, 1, 80), 0.9)

    return hits


def parse_round_and_timer(*texts: str) -> Tuple[Optional[int], Optional[int]]:
    blob = _compact_text(" ".join(t for t in texts if t))
    round_no = None
    timer = None
    m_round = re.search(r"(?:竞拍)?第\s*(\d)\s*回[合回合]", blob)
    if m_round:
        value = int(m_round.group(1))
        if 1 <= value <= 5:
            round_no = value
    m_timer = re.search(r"00[:：](\d{2})", blob)
    if m_timer:
        timer = int(m_timer.group(1))
    return round_no, timer


@dataclass
class CachedCardEvidence:
    sig_raw: np.ndarray
    badge_hue: float
    badge_sat: float
    text_patch: np.ndarray
    global_box: List[int]
    raw_text: str
    routed_items: List[Tuple[str, int, float]]
    generation: int
    round_no: Optional[int] = None

    @property
    def sig(self) -> np.ndarray:
        return self.sig_raw


class IntelCardEvidenceExtractor:
    def __init__(self, ocr_engine: Any = None):
        self._ocr_engine = ocr_engine
        self._cached_cards: List[CachedCardEvidence] = []
        self._cache_generation: int = 0

    def _get_ocr(self):
        if self._ocr_engine is not None:
            return self._ocr_engine
        try:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr_engine = RapidOCR()
            return self._ocr_engine
        except Exception:
            return None

    def run_ocr(self, image: Optional[np.ndarray]) -> List[Tuple[List[List[float]], str, float]]:
        engine = self._get_ocr()
        if engine is None or image is None or getattr(image, "size", 0) == 0:
            return []
        if min(image.shape[:2]) < 8:
            return []
        try:
            res, _ = engine(image)
            return res or []
        except Exception:
            return []

    def _ocr_text(self, image: Optional[np.ndarray]) -> str:
        parts = []
        for _, text, _ in self.run_ocr(image):
            piece = str(text or "").strip()
            if piece:
                parts.append(piece)
        return " ".join(parts)

    def _extract_text_lines_projected(
        self,
        crop: np.ndarray,
        *,
        threshold: int = 140,
        min_row_density: float = 0.02,
    ) -> List[np.ndarray]:
        """
        Segment individual text lines from a card crop using 1D vertical projection (4D2D1M-C2.13).
        Bypasses DBNet text detection completely.
        """
        if crop is None or crop.size == 0 or min(crop.shape[:2]) < 10:
            return []

        h, w = crop.shape[:2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if (len(crop.shape) == 3 and crop.shape[2] == 3) else crop

        # High-contrast thresholding on bright text pixels
        _, bin_img = cv2.threshold(gray, int(threshold), 255, cv2.THRESH_BINARY)

        # Exclude left badge: text spans x in [0.18*w, 0.95*w]
        x1 = int(w * 0.18)
        x2 = int(w * 0.95)

        if x2 <= x1:
            return []

        # 1D row profile (vertical projection)
        row_sums = np.sum(bin_img[:, x1:x2] > 0, axis=1)

        min_pixels = int((x2 - x1) * float(min_row_density))
        active_rows = row_sums > min_pixels

        lines = []
        in_line = False
        start_y = 0
        for y, active in enumerate(active_rows):
            if active and not in_line:
                in_line = True
                start_y = y
            elif not active and in_line:
                in_line = False
                line_h = y - start_y
                if line_h >= 10:  # Valid line height
                    pad_y1 = max(0, start_y - 2)
                    pad_y2 = min(h, y + 2)
                    # Tighten X boundary for this specific line
                    line_bin = bin_img[start_y:y, x1:x2]
                    col_sums = np.sum(line_bin > 0, axis=0)
                    active_cols = np.where(col_sums > 0)[0]
                    if len(active_cols) > 10:
                        lx1 = max(x1, x1 + int(active_cols[0]) - 4)
                        lx2 = min(w, x1 + int(active_cols[-1]) + 4)
                    else:
                        lx1, lx2 = x1, x2
                    lines.append(crop[pad_y1:pad_y2, lx1:lx2])

        if in_line:
            line_h = h - start_y
            if line_h >= 10:
                pad_y1 = max(0, start_y - 2)
                pad_y2 = h
                lines.append(crop[pad_y1:pad_y2, x1:x2])

        return lines

    def _ocr_card_fast_projected(self, crop: np.ndarray) -> Tuple[str, List[Tuple[str, int, float]], bool]:
        """
        Fast projected recognizer-only card OCR with fail-closed full OCR fallback (4D2D1M-C2.13).
        Returns: (raw_text, routed_items, is_projected_rec)
        """
        engine = self._get_ocr()
        # 1. Try projected recognition-only if text_rec is available
        if engine is not None and hasattr(engine, "text_rec"):
            try:
                line_crops = self._extract_text_lines_projected(crop)
                if line_crops:
                    rec_res, _ = engine.text_rec(line_crops)
                    proj_texts = [str(r[0]).strip() for r in (rec_res or []) if r and r[0]]
                    combined_text = " ".join(proj_texts)
                    routed = route_card_text(combined_text)
                    if routed:
                        return combined_text, routed, True
            except Exception:
                pass

        # 2. Fail-closed fallback to full-card RapidOCR (Detection + Recognition)
        raw_text = self._ocr_text(crop)
        routed = route_card_text(raw_text)
        return raw_text, routed, False

    def _compute_card_signature(self, crop: np.ndarray) -> np.ndarray:
        if crop is None or crop.size == 0:
            return np.zeros((16, 32), dtype=np.uint8)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
        return cv2.resize(gray, (32, 16), interpolation=cv2.INTER_AREA)

    def _compute_multimodal_signature(
        self, crop: np.ndarray
    ) -> Tuple[np.ndarray, float, float, np.ndarray]:
        """
        Extract multimodal scale-invariant card signature (4D2D1M-C2.8):
        1. sig_raw: 32x16 raw grayscale thumbnail (for quick same-layout match).
        2. badge_hue, badge_sat: Left badge color characteristics.
        3. text_patch: 128x24 normalized tight text-line patch via 1D vertical projection.
        """
        if crop is None or crop.size == 0:
            return (
                np.zeros((16, 32), dtype=np.uint8),
                0.0,
                0.0,
                np.zeros((24, 128), dtype=np.uint8),
            )

        h, w = crop.shape[:2]
        is_color = (len(crop.shape) == 3 and crop.shape[2] == 3)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if is_color else crop
        sig_raw = cv2.resize(gray, (32, 16), interpolation=cv2.INTER_AREA)

        # 1. Left badge color
        if is_color and h > 10 and w > 20:
            badge_crop = crop[int(h * 0.2) : int(h * 0.8), int(w * 0.05) : int(w * 0.18)]
            if badge_crop.size > 0:
                badge_hsv = cv2.cvtColor(badge_crop, cv2.COLOR_BGR2HSV)
                sat_mask = badge_hsv[:, :, 1] > 60
                if np.sum(sat_mask) > 10:
                    badge_hue = float(np.mean(badge_hsv[:, :, 0][sat_mask]))
                    badge_sat = float(np.mean(badge_hsv[:, :, 1][sat_mask]))
                else:
                    badge_hue = float(np.mean(badge_hsv[:, :, 0]))
                    badge_sat = float(np.mean(badge_hsv[:, :, 1]))
            else:
                badge_hue, badge_sat = 0.0, 0.0
        else:
            badge_hue, badge_sat = 0.0, 0.0

        # 2. Text line patch via 1D vertical projection
        _, bin_img = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        x_start = int(w * 0.15)
        x_end = int(w * 0.80)
        if x_end > x_start and h > 10:
            v_proj = np.sum(bin_img[:, x_start:x_end], axis=1)
            text_rows = np.where(v_proj > 0)[0]
            if len(text_rows) > 5:
                y1, y2 = text_rows[0], text_rows[-1]
                text_line = gray[y1:y2, x_start:x_end]
            else:
                text_line = gray[:, x_start:x_end]
        else:
            text_line = gray
        text_patch = cv2.resize(text_line, (128, 24), interpolation=cv2.INTER_AREA)

        return sig_raw, badge_hue, badge_sat, text_patch

    def _card_distance(
        self,
        sig_cur: Tuple[np.ndarray, float, float, np.ndarray],
        cached: CachedCardEvidence,
    ) -> float:
        _, cur_hue, _, cur_text = sig_cur
        text_diff = float(np.mean(np.abs(cur_text.astype(np.int16) - cached.text_patch.astype(np.int16))))
        hue_diff = min(abs(cur_hue - cached.badge_hue), 180.0 - abs(cur_hue - cached.badge_hue))
        return text_diff + (hue_diff / 90.0) * 30.0

    def _match_cards_to_cache(
        self,
        current_signatures: List[Tuple[np.ndarray, float, float, np.ndarray]],
        generation: int,
        match_threshold: float = 8.0,
        margin_threshold: float = 10.0,
        max_hue_tolerance: float = 25.0,
    ) -> Tuple[Dict[int, CachedCardEvidence], List[int]]:
        """
        Fail-closed one-to-one card matcher across layouts & scale (4D2D1M-C2.8):
        - Stage 1: Quick same-layout check (0 overhead for steady frames).
        - Stage 2: Scale-invariant one-to-one distance matching with strict margin & hue gating.
        """
        if generation != self._cache_generation or not self._cached_cards or not current_signatures:
            return {}, list(range(len(current_signatures)))

        # Fast Stage 1: Exact same layout check
        if len(current_signatures) == len(self._cached_cards):
            all_match = True
            direct_matches = {}
            for i, (sig_raw, _, _, _) in enumerate(current_signatures):
                cached = self._cached_cards[i]
                diff = float(np.mean(np.abs(sig_raw.astype(np.int16) - cached.sig_raw.astype(np.int16))))
                if diff < 3.5:
                    direct_matches[i] = cached
                else:
                    all_match = False
                    break
            if all_match:
                return direct_matches, []

        # Stage 2: Scale-invariant one-to-one distance matching
        proposals = []
        for j, sig_cur in enumerate(current_signatures):
            dists = []
            for i, cached in enumerate(self._cached_cards):
                hue_diff = min(abs(sig_cur[1] - cached.badge_hue), 180.0 - abs(sig_cur[1] - cached.badge_hue))
                if hue_diff > max_hue_tolerance:
                    dists.append((999.0, i))
                else:
                    d = self._card_distance(sig_cur, cached)
                    dists.append((d, i))

            dists.sort(key=lambda x: x[0])
            best_d, best_i = dists[0]
            second_d = dists[1][0] if len(dists) > 1 else 999.0

            if best_d <= match_threshold and (second_d - best_d) >= margin_threshold:
                proposals.append((j, best_i, best_d))

        reused_matches: Dict[int, CachedCardEvidence] = {}
        claimed_cached_indices = set()
        proposals.sort(key=lambda x: x[2])  # Lowest distance first
        for cur_idx, cached_idx, dist in proposals:
            if cached_idx not in claimed_cached_indices:
                claimed_cached_indices.add(cached_idx)
                reused_matches[cur_idx] = self._cached_cards[cached_idx]

        unmatched = [j for j in range(len(current_signatures)) if j not in reused_matches]
        return reused_matches, unmatched

    def _find_cached_card(
        self,
        sig: np.ndarray,
        box: List[int],
        generation: int,
        diff_threshold: float = 3.5,
    ) -> Optional[CachedCardEvidence]:
        if generation != self._cache_generation:
            return None
        for cached in self._cached_cards:
            diff = float(np.mean(np.abs(sig.astype(np.int16) - cached.sig_raw.astype(np.int16))))
            if diff < diff_threshold:
                return cached
        return None

    def clear_card_cache(self) -> None:
        self._cached_cards.clear()

    def extract_cards_fast(
        self,
        frame: Optional[np.ndarray],
        frame_id: str = "",
        known_round: Optional[int] = None,
        known_timer: Optional[int] = None,
        generation: int = 0,
        pending_verify_fields: Optional[Any] = None,
        projection_threshold: int = 140,
        projection_min_row_density: float = 0.02,
        allow_detector_fallback: bool = True,
        external_crops: Optional[List[np.ndarray]] = None,
        external_results_out: Optional[List[Any]] = None,
    ) -> FrameIntelEvidence:
        """
        Continuous incremental fast-path extractor (4D2D1M-C2.8 / C2.25):
        - Skips header and title OCR (uses known_round/known_timer from caller authority).
        - Runs OpenCV card bbox detection inside intel_card_stack ROI.
        - Employs scale-invariant multimodal signature matching to safely reuse cached cards across layout scaling.
        - Selectively bypasses cache for unconfirmed / pending verify cards to guarantee cross-frame physical OCR.
        - Returns full FrameIntelEvidence with explicit is_physical_ocr parity.
        """
        evidence = FrameIntelEvidence(
            frameId=frame_id,
            round=known_round,
            timer=known_timer,
        )
        if frame is None or getattr(frame, "size", 0) == 0:
            return evidence
        if min(frame.shape[:2]) < _MIN_FRAME_EDGE:
            return evidence

        if generation != self._cache_generation:
            self._cached_cards.clear()
            self._cache_generation = generation

        game, _chrome = strip_recording_chrome(frame)
        gh, gw = game.shape[:2]
        vx, vy, vw, vh = ROIScaler.get_viewport_rect(gw, gh)
        viewport = game[vy : vy + vh, vx : vx + vw]
        stack = ROIScaler.crop_roi(viewport, INTEL_STACK_ROI)
        sx1, sy1, _, _ = ROIScaler.scale_roi(INTEL_STACK_ROI, viewport.shape[1], viewport.shape[0])
        origin = (int(vx + sx1), int(vy + sy1))
        ox, oy = origin

        if external_results_out is not None:
            external_results_out.clear()
        external_crops = [crop for crop in (external_crops or []) if getattr(crop, "size", 0) > 0]
        local_boxes = detect_card_boxes(stack)
        if not local_boxes:
            engine = self._get_ocr() if external_crops else None
            if engine is not None and hasattr(engine, "text_rec"):
                try:
                    rows, _ = engine.text_rec(external_crops)
                    if external_results_out is not None:
                        external_results_out.extend(rows or [])
                except Exception:
                    pass
            return evidence

        crops = [stack[y1:y2, x1:x2] for x1, y1, x2, y2 in local_boxes]
        signatures = [self._compute_multimodal_signature(c) for c in crops]

        reused_matches, unmatched_indices = self._match_cards_to_cache(signatures, generation)

        # Selectively bypass cache for cards with unconfirmed/pending verify fields
        if pending_verify_fields and reused_matches:
            verify_set = set(pending_verify_fields)
            to_unmatch = []
            for cur_idx, cached in reused_matches.items():
                from public_intel_ledger import public_card_key
                if public_card_key(cached.raw_text) in verify_set or any(item[0] in verify_set for item in cached.routed_items):
                    to_unmatch.append(cur_idx)
            for cur_idx in to_unmatch:
                del reused_matches[cur_idx]

        projected_groups: Dict[int, List[np.ndarray]] = {}
        projected_text: Dict[int, str] = {}
        ocr_engine = self._get_ocr() if (unmatched_indices or external_crops) else None
        if ocr_engine is not None and hasattr(ocr_engine, "text_rec"):
            line_crops: List[np.ndarray] = list(external_crops)
            external_count = len(line_crops)
            for idx in unmatched_indices:
                group = self._extract_text_lines_projected(
                    crops[idx],
                    threshold=projection_threshold,
                    min_row_density=projection_min_row_density,
                )
                projected_groups[idx] = group
                line_crops.extend(group)
            if line_crops:
                try:
                    rec_rows, _ = ocr_engine.text_rec(line_crops)
                    rec_rows = list(rec_rows or [])
                    if external_results_out is not None:
                        external_results_out.extend(rec_rows[:external_count])
                        external_results_out.extend(
                            [("", 0.0)] * max(0, external_count - len(external_results_out))
                        )
                    recognized = [
                        str(row[0]).strip() if row and row[0] else ""
                        for row in rec_rows[external_count:]
                    ]
                    cursor = 0
                    for idx in unmatched_indices:
                        group = projected_groups.get(idx) or []
                        projected_text[idx] = " ".join(recognized[cursor:cursor + len(group)])
                        cursor += len(group)
                except Exception:
                    projected_text = {}

        new_cache_entries: List[CachedCardEvidence] = []

        for idx, local in enumerate(local_boxes):
            x1, y1, x2, y2 = local
            global_box = [int(ox + x1), int(oy + y1), int(ox + x2), int(oy + y2)]
            evidence.cards.append(global_box)
            crop = crops[idx]
            sig_raw, b_hue, b_sat, t_patch = signatures[idx]
            is_phys = (idx not in reused_matches)

            if idx in reused_matches:
                cached = reused_matches[idx]
                raw_text = cached.raw_text
                routed = cached.routed_items
                # Create updated cached entry with current global_box and signature
                entry = CachedCardEvidence(
                    sig_raw=sig_raw,
                    badge_hue=b_hue,
                    badge_sat=b_sat,
                    text_patch=t_patch,
                    global_box=global_box,
                    raw_text=raw_text,
                    routed_items=routed,
                    generation=generation,
                    round_no=known_round,
                )
                new_cache_entries.append(entry)
            else:
                raw_text = projected_text.get(idx, "")
                routed = route_card_text(raw_text)
                if not routed and allow_detector_fallback:
                    raw_text, routed, _ = self._ocr_card_fast_projected(crop)
                entry = CachedCardEvidence(
                    sig_raw=sig_raw,
                    badge_hue=b_hue,
                    badge_sat=b_sat,
                    text_patch=t_patch,
                    global_box=global_box,
                    raw_text=raw_text,
                    routed_items=routed,
                    generation=generation,
                    round_no=known_round,
                )
                new_cache_entries.append(entry)

            from intel_card_source import card_source
            evidence.cardReadings.append({
                'frameId': frame_id, 'round': known_round, 'timer': known_timer,
                'cardBox': global_box, 'rawText': raw_text,
                'is_physical_ocr': is_phys, 'cardSource': card_source(raw_text),
            })
            for name, value, confidence in routed:
                evidence.observations.append(
                    IntelCardObservation(
                        field=name,
                        value=value,
                        status=STATUS_OBSERVED,
                        frameId=frame_id,
                        round=known_round,
                        timer=known_timer,
                        cardBox=global_box,
                        rawText=raw_text,
                        confidence=float(confidence),
                        is_physical_ocr=is_phys,
                    )
                )

        self._cached_cards = new_cache_entries
        return evidence

    def extract_stack(
        self,
        stack: np.ndarray,
        header: Optional[np.ndarray] = None,
        frame_id: str = "",
        stack_origin: Tuple[int, int] = (0, 0),
    ) -> FrameIntelEvidence:
        evidence = FrameIntelEvidence(frameId=frame_id)
        if stack is None or getattr(stack, "size", 0) == 0:
            return evidence

        header_text = self._ocr_text(header)
        local_boxes = detect_card_boxes(stack)
        title = stack[: local_boxes[0][1], :] if local_boxes else stack[: max(1, stack.shape[0] // 6), :]
        title_text = self._ocr_text(title)
        evidence.rawHeaderText = header_text
        evidence.rawTitleText = title_text
        evidence.round, evidence.timer = parse_round_and_timer(header_text, title_text)

        ox, oy = stack_origin
        for local in local_boxes:
            x1, y1, x2, y2 = local
            global_box = [int(ox + x1), int(oy + y1), int(ox + x2), int(oy + y2)]
            evidence.cards.append(global_box)
            crop = stack[y1:y2, x1:x2]
            raw_text = self._ocr_text(crop)
            from intel_card_source import card_source
            evidence.cardReadings.append({
                'frameId': frame_id, 'round': evidence.round, 'timer': evidence.timer,
                'cardBox': global_box, 'rawText': raw_text,
                'is_physical_ocr': True, 'cardSource': card_source(raw_text),
            })
            for name, value, confidence in route_card_text(raw_text):
                evidence.observations.append(
                    IntelCardObservation(
                        field=name,
                        value=value,
                        status=STATUS_OBSERVED,
                        frameId=frame_id,
                        round=evidence.round,
                        timer=evidence.timer,
                        cardBox=global_box,
                        rawText=raw_text,
                        confidence=float(confidence),
                    )
                )
        return evidence

    def extract_frame(self, frame: Optional[np.ndarray], frame_id: str = "") -> FrameIntelEvidence:
        if frame is None or getattr(frame, "size", 0) == 0:
            return FrameIntelEvidence(frameId=frame_id)
        if min(frame.shape[:2]) < _MIN_FRAME_EDGE:
            return FrameIntelEvidence(frameId=frame_id)

        game, _chrome = strip_recording_chrome(frame)
        gh, gw = game.shape[:2]
        vx, vy, vw, vh = ROIScaler.get_viewport_rect(gw, gh)
        viewport = game[vy : vy + vh, vx : vx + vw]
        stack = ROIScaler.crop_roi(viewport, INTEL_STACK_ROI)
        header = ROIScaler.crop_roi(viewport, HEADER_ROI)
        sx1, sy1, _, _ = ROIScaler.scale_roi(INTEL_STACK_ROI, viewport.shape[1], viewport.shape[0])
        origin = (int(vx + sx1), int(vy + sy1))
        return self.extract_stack(stack, header=header, frame_id=frame_id, stack_origin=origin)


class IntelCardEvidenceLedger:
    """
    Cross-Frame Independent Intel Confirmation Ledger (4D2D1M-C2.25):
    - Confirmed canonical facts require N=2 distinct source frame physical OCR confirmations.
    - Tentative facts are recorded on the first physical observation, but remain unconfirmed.
    - Subsequent distinct source frame physical OCR with matching value commits canonical STATUS_OBSERVED.
    - Confirmed facts are protected against single-frame legal-wrong outliers (which only register as transient challengers).
    - Cache reuse and repeated OCR on the same frame do NOT advance tentative/challenger confirmation counts.
    """

    def __init__(self):
        from public_intel_ledger import PublicIntelLedger
        self._public_cards = PublicIntelLedger()
        self._confirmed: Dict[str, Dict[str, Any]] = {
            name: {
                "field": name,
                "status": STATUS_UNKNOWN,
                "value": None,
                "sources": [],
                "candidates": [],
            }
            for name in SUPPORTED_FIELDS
        }
        self._tentative: Dict[str, Dict[str, Any]] = {}   # name -> {"val": int, "frame_id": str, "source": Dict}
        self._challenger: Dict[str, Dict[str, Any]] = {}  # name -> {"val": int, "frame_id": str, "source": Dict}
        self._frame_history: List[Dict[str, Any]] = []

    def clear(self) -> None:
        from public_intel_ledger import PublicIntelLedger
        self._public_cards = PublicIntelLedger()
        self._confirmed = {
            name: {
                "field": name,
                "status": STATUS_UNKNOWN,
                "value": None,
                "sources": [],
                "candidates": [],
            }
            for name in SUPPORTED_FIELDS
        }
        self._tentative.clear()
        self._challenger.clear()
        self._frame_history.clear()

    def get_pending_verify_fields(self) -> set:
        """Returns set of fields that currently need cross-frame physical verification (tentative or challenger)."""
        return set(self._tentative.keys()) | set(self._challenger.keys()) | self._public_cards.pending_keys()

    def merge(self, *frames: FrameIntelEvidence) -> Dict[str, Any]:
        for ev in frames:
            self._public_cards.update(ev.cardReadings)
            self._frame_history.append({"frameId": ev.frameId, "round": ev.round, "timer": ev.timer})

            frame_obs_by_field: Dict[str, List[IntelCardObservation]] = {name: [] for name in SUPPORTED_FIELDS}
            for obs in ev.observations:
                if obs.field in frame_obs_by_field:
                    frame_obs_by_field[obs.field].append(obs)

            for name in SUPPORTED_FIELDS:
                obs_list = frame_obs_by_field[name]
                st_conf = self._confirmed[name]
                st_tent = self._tentative.get(name)
                st_chal = self._challenger.get(name)

                # If no observation in this frame (Miss / Out of view)
                if not obs_list:
                    # Clear tentative on miss to enforce strict consecutive valid confirmation
                    if st_tent is not None:
                        self._tentative.pop(name, None)
                    continue

                obs = obs_list[0]
                val = obs.value
                frame_id = ev.frameId
                is_physical = getattr(obs, "is_physical_ocr", True)

                # Invalid value
                if val is None or (isinstance(val, (int, float)) and val <= 0):
                    if st_tent is not None:
                        self._tentative.pop(name, None)
                    continue

                # Case 1: Cache Reuse (not fresh physical OCR)
                if not is_physical:
                    # Cache reuse observation reinforces existing confirmed fact, but CANNOT advance counts
                    if st_conf["status"] == STATUS_OBSERVED and val == st_conf["value"]:
                        obs_d = obs.to_dict()
                        if not any(s.get("frameId") == frame_id for s in st_conf["sources"]):
                            st_conf["sources"].append(obs_d)
                    continue

                # Case 2: Field is NOT yet confirmed
                if st_conf["status"] != STATUS_OBSERVED:
                    if st_tent is not None and st_tent["val"] == val:
                        if frame_id != st_tent["frame_id"]:
                            # 2nd distinct source frame confirmed!
                            st_conf["status"] = STATUS_OBSERVED
                            st_conf["value"] = val
                            st_conf["sources"] = [st_tent["source"], obs.to_dict()]
                            st_conf["candidates"] = [val]
                            self._tentative.pop(name, None)
                        else:
                            # Same frame repeat -> Ignored for count
                            pass
                    else:
                        # Establish or mutate tentative
                        self._tentative[name] = {
                            "val": val,
                            "frame_id": frame_id,
                            "source": obs.to_dict(),
                        }
                    continue

                # Case 3: Field IS already confirmed (val matches confirmed)
                if val == st_conf["value"]:
                    # Clean reinforcement -> clear any pending challenger
                    if st_chal is not None:
                        self._challenger.pop(name, None)
                    obs_d = obs.to_dict()
                    if not any(s.get("frameId") == frame_id for s in st_conf["sources"]):
                        st_conf["sources"].append(obs_d)
                    continue

                # Case 4: Field IS already confirmed, but incoming physical OCR dissents (Challenger)
                if st_chal is not None and st_chal["val"] == val:
                    if frame_id != st_chal["frame_id"]:
                        # 2nd distinct source frame confirmed the challenger!
                        # Mark persistent conflict in immutable domain
                        st_conf["status"] = STATUS_CONFLICT
                        st_conf["value"] = None
                        if val not in st_conf["candidates"]:
                            st_conf["candidates"].append(val)
                        st_conf["sources"].append(obs.to_dict())
                        self._challenger.pop(name, None)
                    else:
                        # Same frame challenger repeat -> Ignored
                        pass
                else:
                    # New challenger candidate
                    self._challenger[name] = {
                        "val": val,
                        "frame_id": frame_id,
                        "source": obs.to_dict(),
                    }

        facts = {}
        for name in SUPPORTED_FIELDS:
            f_dict = dict(self._confirmed[name])
            f_dict["sources"] = list(self._confirmed[name]["sources"])
            f_dict["candidates"] = list(self._confirmed[name]["candidates"])
            if name in self._tentative:
                f_dict["tentative"] = self._tentative[name]["val"]
            if name in self._challenger:
                f_dict["challenger"] = self._challenger[name]["val"]
            facts[name] = f_dict

        return {"frames": list(self._frame_history), "facts": facts, "publicCardEvents": self._public_cards.snapshot()}

    def observed(self, snapshot: Dict[str, Any], name: str) -> Any:
        fact = (snapshot.get("facts") or {}).get(name) or {}
        if fact.get("status") == STATUS_OBSERVED:
            return fact.get("value")
        return STATUS_UNKNOWN


class AsyncContinuousIntelWorker:
    """
    Bounded single-flight async extractor for central intel card evidence (4D2D1M-C2.4).
    - Max 1 in-flight extraction thread.
    - Max 1 pending latest frame (latest-wins).
    - Thread-safe result queue consumed by main pipeline thread.
    - Generation token to safely discard cross-session stale results.
    - Fast incremental card extraction (skips header/title OCR, reuses visually unchanged cards).
    - Strictly produces observation/evidence without authority mutation.
    """

    def __init__(self, extractor_factory: Optional[Any] = None):
        import threading
        self._extractor_factory = extractor_factory
        self._extractor = None
        self._lock = threading.Lock()
        self._in_flight = False
        self._pending_task: Optional[Tuple[np.ndarray, str, int, Optional[int], Optional[int]]] = None
        self._completed_results: List[Tuple[Any, int]] = []
        self._worker_thread: Optional[Any] = None
        self.scheduled_count = 0
        self.pending_replacement_count = 0
        self.completed_count = 0

    @property
    def in_flight(self) -> bool:
        with self._lock:
            return self._in_flight

    @property
    def is_in_flight(self) -> bool:
        with self._lock:
            return self._in_flight

    def _get_extractor(self):
        if self._extractor is None:
            if self._extractor_factory:
                self._extractor = self._extractor_factory()
            else:
                self._extractor = IntelCardEvidenceExtractor()
        return self._extractor

    def submit_frame(
        self,
        frame: np.ndarray,
        frame_id: str,
        generation: int,
        known_round: Optional[int] = None,
        known_timer: Optional[int] = None,
        pending_verify_fields: Optional[Any] = None,
    ) -> bool:
        """
        Submit a candidate frame for async extraction with known round & timer authority.
        If idle, immediately starts worker thread on a private frame copy.
        If busy, stores/replaces pending frame (latest-wins bounded buffer).
        """
        import threading

        if frame is None or getattr(frame, "size", 0) == 0:
            return False

        frame_copy = frame.copy()
        with self._lock:
            if not self._in_flight:
                self._in_flight = True
                self.scheduled_count += 1
                self._worker_thread = threading.Thread(
                    target=self._run_worker,
                    args=(frame_copy, frame_id, generation, known_round, known_timer, pending_verify_fields),
                    name="async-continuous-intel-worker",
                    daemon=True,
                )
                self._worker_thread.start()
                return True
            else:
                if self._pending_task is not None:
                    self.pending_replacement_count += 1
                self._pending_task = (frame_copy, frame_id, generation, known_round, known_timer, pending_verify_fields)
                self.scheduled_count += 1
                return True

    def _run_worker(
        self,
        frame: np.ndarray,
        frame_id: str,
        generation: int,
        known_round: Optional[int] = None,
        known_timer: Optional[int] = None,
        pending_verify_fields: Optional[Any] = None,
    ) -> None:
        current_frame = frame
        current_id = frame_id
        current_gen = generation
        current_round = known_round
        current_timer = known_timer
        current_pending = pending_verify_fields

        while True:
            ev = None
            try:
                extractor = self._get_extractor()
                if extractor:
                    if hasattr(extractor, "extract_cards_fast"):
                        ev = extractor.extract_cards_fast(
                            current_frame,
                            frame_id=current_id,
                            known_round=current_round,
                            known_timer=current_timer,
                            generation=current_gen,
                            pending_verify_fields=current_pending,
                        )
                    else:
                        ev = extractor.extract_frame(current_frame, frame_id=current_id)
            except Exception:
                ev = None

            with self._lock:
                if ev is not None:
                    self._completed_results.append((ev, current_gen))
                    self.completed_count += 1

                if self._pending_task is not None:
                    current_frame, current_id, current_gen, current_round, current_timer, current_pending = self._pending_task
                    self._pending_task = None
                else:
                    self._in_flight = False
                    break

    def poll_results(self, current_generation: int) -> List[FrameIntelEvidence]:
        """
        Main-thread consumer: drain completed results matching current generation.
        Discards results from previous generations.
        """
        valid_evidences = []
        with self._lock:
            if not self._completed_results:
                return []
            raw = self._completed_results
            self._completed_results = []

        for ev, gen in raw:
            if gen == current_generation and ev is not None:
                valid_evidences.append(ev)
        return valid_evidences

    @property
    def is_in_flight(self) -> bool:
        with self._lock:
            return self._in_flight

    @property
    def has_pending(self) -> bool:
        with self._lock:
            return self._pending_task is not None
