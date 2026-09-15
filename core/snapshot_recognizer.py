"""
Neverness to Everness (异环) - Triggered Snapshot Assist v1
============================================================
Single-shot on-demand game frame recognition and fail-closed fact merger.

Design invariants:
1. Single-shot only: executes once upon trigger, zero continuous background polling.
2. Scene gate: only applies to valid in-auction / lobby scenes; rejects settlement / unknown.
3. Provenance & Precedence: Explicit user Manual > High-confidence snapshot > Unknown.
4. Fail-closed: missing OCR facts remain None/null, never default to 0.
5. Strict separation: totalItems != totalGrid != q.
6. Settlement facts (redInventoryComplete, settlementVerifiedRedItems, settlementItems)
   are strictly excluded from live auction snapshot facts.
"""

import re
import time
from typing import Optional, Dict, Any, List, Tuple
import numpy as np

from business_sot import extract_from_text
from vision_pipeline import parse_money_amount, parse_bid_text
from seat_bid_observation import visible_seat_bids


class SnapshotFactPatch:
    def __init__(self, key: str, value: Any, confidence: str, parser: str, raw_text: str = ""):
        self.key = key
        self.value = value
        self.confidence = confidence  # "high" | "medium" | "low"
        self.parser = parser
        self.raw_text = raw_text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "parser": self.parser,
            "rawText": self.raw_text,
        }


class SingleFrameSnapshotRecognizer:
    def __init__(self, ocr_engine: Any = None, *, include_card_evidence: bool = True, focused: bool = False):
        self._ocr_engine = ocr_engine
        self.include_card_evidence = include_card_evidence
        self.focused = focused

    def _get_ocr(self):
        if self._ocr_engine is not None:
            return self._ocr_engine
        try:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr_engine = RapidOCR()
            return self._ocr_engine
        except Exception:
            return None

    def run_ocr(self, frame: np.ndarray) -> List[Tuple[List[List[float]], str, float]]:
        """Run OCR on frame. Returns list of (box, text, score)."""
        engine = self._get_ocr()
        if engine is None or frame is None or frame.size == 0:
            return []
        try:
            if self.focused:
                h, w = frame.shape[:2]
                mapped = []
                for x1, y1, x2, y2 in ((.32, 0, .74, .97), (.02, .12, .32, .78)):
                    left, top, right, bottom = int(x1*w), int(y1*h), int(x2*w), int(y2*h)
                    rows, _ = engine(frame[top:bottom, left:right], use_cls=False)
                    mapped.extend(([[x+left, y+top] for x,y in box], text, score) for box,text,score in (rows or []))
                return mapped
            res, _ = engine(frame)
            if not res:
                return []
            return res
        except Exception:
            return []

    def parse_ocr_results(self, mapped_res: List[Tuple[List[List[float]], str, float]]) -> Tuple[str, List[SnapshotFactPatch]]:
        """
        Parse OCR bounding boxes and text lines into scene classification and candidate patches.
        """
        if not mapped_res:
            return "UNKNOWN", []

        all_text = " ".join(t.strip() for _, t, _ in mapped_res if t and t.strip())
        
        # 1. Scene Detection (Fail-closed)
        if any(w in all_text for w in ["拍卖结算", "最终成交价", "本次拍卖已结束", "本局收益"]):
            return "SETTLEMENT", []

        is_auction = False
        patches: List[SnapshotFactPatch] = []

        # 2. Extract venue, box, fieldCondition via business_sot closed-set
        env_hit = extract_from_text(all_text)
        if env_hit.get("venue"):
            patches.append(SnapshotFactPatch("venue", env_hit["venue"], "high", "sot:venue", all_text))
            is_auction = True
        if env_hit.get("box"):
            patches.append(SnapshotFactPatch("box", env_hit["box"], "high", "sot:box", all_text))
            is_auction = True
        if env_hit.get("fieldCondition"):
            patches.append(SnapshotFactPatch("fieldCondition", env_hit["fieldCondition"], "high", "sot:fieldCondition", all_text))
            is_auction = True

        # 3. Line-by-line regex parsing
        for _, raw_line, score in mapped_res:
            text = str(raw_line).strip()
            if not text:
                continue

            # --- A. Total Items (全场总件数) ---
            # Explicitly: "所有藏品的总数量为66件" or "所有藏品总数量为66" -> totalItems
            m_tot_items = re.search(r"(?:本局内?)?所有藏品的?总数量为\s*(\d+)件?", text)
            if m_tot_items:
                cnt = int(m_tot_items.group(1))
                if 1 <= cnt <= 200:
                    patches.append(SnapshotFactPatch("totalItems", cnt, "high", "regex:total_items_card", text))
                    is_auction = True

            # --- B. Total Grids (总格数) ---
            # Explicitly: "总格数为32" -> totalGrid
            m_tot_grids = re.search(r"总格数为\s*(\d+)", text)
            if m_tot_grids:
                grids = int(m_tot_grids.group(1))
                if 1 <= grids <= 250:
                    patches.append(SnapshotFactPatch("totalGrid", grids, "high", "regex:total_grids_card", text))
                    is_auction = True

            # --- C. Q Value (箱体紫金红高阶总件数) ---
            # Explicitly: "紫色，金色和红色品质藏品的总件数为39件" or "总件数为39件" (when not "所有藏品")
            if "所有藏品" not in text:
                m_q = re.search(r"(?:本局内?)?(?:紫色[，,]金色和红色品质)?(?:藏品)?的总件数为\s*(\d+)件?", text)
                if not m_q:
                    m_q = re.search(r"(?:件数|想件数)为\s*(\d+)", text)
                if m_q:
                    q_val = int(m_q.group(1))
                    if 1 <= q_val <= 100:
                        patches.append(SnapshotFactPatch("q", q_val, "high", "regex:q_instrument_card", text))
                        is_auction = True

            # --- D. Quality Counts ---
            # Purple count: "紫色品质藏品的总数量为2"
            m_purple_cnt = re.search(r"(?:紫色品质藏品的?总数量为|紫色[^\d]{0,12}总数量为)\s*(\d+)", text)
            if m_purple_cnt:
                cnt = int(m_purple_cnt.group(1))
                if 0 <= cnt <= 50:
                    patches.append(SnapshotFactPatch("purpleCount", cnt, "high", "regex:purple_count_card", text))
                    is_auction = True

            # Blue count: "蓝色品质藏品的总数量为4"
            m_blue_cnt = re.search(r"(?:蓝色品质藏品的?总数量为|蓝色[^\d]{0,12}总数量为)\s*(\d+)", text)
            if m_blue_cnt:
                cnt = int(m_blue_cnt.group(1))
                if 0 <= cnt <= 50:
                    patches.append(SnapshotFactPatch("blueCount", cnt, "high", "regex:blue_count_card", text))
                    is_auction = True

            # Green count: "绿色品质藏品的总数量为3"
            m_green_cnt = re.search(r"(?:绿色品质藏品的?总数量为|绿色[^\d]{0,12}总数量为)\s*(\d+)", text)
            if m_green_cnt:
                cnt = int(m_green_cnt.group(1))
                if 0 <= cnt <= 50:
                    patches.append(SnapshotFactPatch("greenCount", cnt, "high", "regex:green_count_card", text))
                    is_auction = True

            # White count: "白色品质藏品的总数量为5"
            m_white_cnt = re.search(r"(?:白色品质藏品的?总数量为|白色[^\d]{0,12}总数量为)\s*(\d+)", text)
            if m_white_cnt:
                cnt = int(m_white_cnt.group(1))
                if 0 <= cnt <= 50:
                    patches.append(SnapshotFactPatch("whiteCount", cnt, "high", "regex:white_count_card", text))
                    is_auction = True

            # Red count: "红色品质藏品的总数量为1"
            m_red_cnt = re.search(r"(?:红色品质藏品的?总数量为|红色[^\d]{0,12}总数量为)\s*(\d+)", text)
            if m_red_cnt:
                cnt = int(m_red_cnt.group(1))
                if 0 <= cnt <= 50:
                    patches.append(SnapshotFactPatch("redCount", cnt, "high", "regex:red_count_card", text))
                    is_auction = True

            # Gold count: "金色品质藏品的总数量为2"
            m_gold_cnt = re.search(r"(?:金色品质藏品的?总数量为|金色[^\d]{0,12}总数量为)\s*(\d+)", text)
            if m_gold_cnt:
                cnt = int(m_gold_cnt.group(1))
                if 0 <= cnt <= 50:
                    patches.append(SnapshotFactPatch("goldCount", cnt, "high", "regex:gold_count_card", text))
                    is_auction = True

            # --- E. Quality Averages ---
            # Gold avg: "金色品质...平均价值为58,000"
            m_gold_avg = re.search(r"(?:金色|金品).*平均.*为\s*([\d,，.．、]+)", text)
            if m_gold_avg:
                val = parse_money_amount(m_gold_avg.group(1))
                if val >= 1000:
                    patches.append(SnapshotFactPatch("goldAvg", val, "high", "regex:gold_avg_card", text))
                    is_auction = True
            else:
                # Generic average: "平均价值为58,000" (when no quality name)
                m_gen_avg = re.search(r"平均价值为\s*([\d,，.．、]+)", text)
                if m_gen_avg and not any(k in text for k in ["金色", "金品", "紫色", "紫品", "蓝色", "蓝品", "绿色", "绿品", "白色", "白品", "红色", "红品"]):
                    val = parse_money_amount(m_gen_avg.group(1))
                    if val >= 1000:
                        patches.append(SnapshotFactPatch("goldAvg", val, "high", "regex:generic_avg_card", text))
                        is_auction = True

            # Purple avg: "紫色品质...平均价值为3,904"
            m_purple_avg = re.search(r"(?:紫色|紫品).*平均.*为\s*([\d,，.．、]+)", text)
            if m_purple_avg:
                val = parse_money_amount(m_purple_avg.group(1))
                if val >= 100:
                    patches.append(SnapshotFactPatch("purpleAvg", val, "high", "regex:purple_avg_card", text))
                    is_auction = True

            # Blue avg: "蓝色品质...平均价值为1,200"
            m_blue_avg = re.search(r"(?:蓝色|蓝品).*平均.*为\s*([\d,，.．、]+)", text)
            if m_blue_avg:
                val = parse_money_amount(m_blue_avg.group(1))
                if val >= 100:
                    patches.append(SnapshotFactPatch("blueAvg", val, "high", "regex:blue_avg_card", text))
                    is_auction = True

            # Green avg: "绿色品质...平均价值为800"
            m_green_avg = re.search(r"(?:绿色|绿品).*平均.*为\s*([\d,，.．、]+)", text)
            if m_green_avg:
                val = parse_money_amount(m_green_avg.group(1), min_digits=2)
                if val >= 10:
                    patches.append(SnapshotFactPatch("greenAvg", val, "high", "regex:green_avg_card", text))
                    is_auction = True

            # White avg: "白色品质...平均价值为350"
            m_white_avg = re.search(r"(?:白色|白品).*平均.*为\s*([\d,，.．、]+)", text)
            if m_white_avg:
                val = parse_money_amount(m_white_avg.group(1), min_digits=2)
                if val >= 10:
                    patches.append(SnapshotFactPatch("whiteAvg", val, "high", "regex:white_avg_card", text))
                    is_auction = True

            # --- F. Quality Grids (品质占格数) ---
            for q_pat, q_key in [
                ("金色|金品", "goldGrid"),
                ("紫色|紫品", "purpleGrid"),
                ("蓝色|蓝品", "blueGrid"),
                ("绿色|绿品", "greenGrid"),
                ("白色|白品", "whiteGrid"),
                ("红色|红品", "redGrid"),
            ]:
                m_q_grid = re.search(rf"(?:{q_pat})[^\d]{{0,15}}(?:所占格数?|占格数?)为?\s*(\d+)", text)
                if m_q_grid:
                    grids = int(m_q_grid.group(1))
                    if 1 <= grids <= 250:
                        patches.append(SnapshotFactPatch(q_key, grids, "high", f"regex:{q_key}_card", text))
                        is_auction = True

        # Determine scene
        if is_auction or patches:
            scene = "IN_AUCTION"
        elif any(k in all_text for k in ["即刻落槌", "拍卖会场", "匹配成功", "选择角色"]):
            scene = "AUCTION_LOBBY"
        else:
            scene = "UNKNOWN"

        return scene, patches

    def process_frame(
        self,
        frame: Optional[np.ndarray],
        existing_facts: Optional[Dict[str, Any]] = None,
        captured_at: str = "",
    ) -> Dict[str, Any]:
        """
        Main entrypoint: single-shot frame processing with fail-closed merge against existing facts.
        """
        now_iso = captured_at or time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        empty_cards = {
            "cardObservations": [],
            "intelCards": [],
            "intelRound": None,
            "intelTimer": None,
        }
        if frame is None or getattr(frame, "size", 0) == 0:
            return {
                "ok": False,
                "scene": "UNKNOWN",
                "capturedAt": now_iso,
                "appliedFacts": {},
                "conflicts": [],
                "summary": "画面为空或未获取到游戏截图",
                **empty_cards,
            }

        existing = dict(existing_facts or {})
        if self.focused:
            from scene_anchors import settlement_title_visible
            if settlement_title_visible(frame):
                return {"ok": False, "scene": "SETTLEMENT", "capturedAt": now_iso,
                        "appliedFacts": {}, "conflicts": [],
                        "summary": "当前画面为终局结算，请使用结算核验", **empty_cards}
        mapped_res = self.run_ocr(frame)
        scene, patches = self.parse_ocr_results(mapped_res)
        if scene == 'IN_AUCTION':
            bids = visible_seat_bids(mapped_res, frame.shape[1], frame.shape[0])
            if any(bid is not None for bid in bids):
                patches.append(SnapshotFactPatch('leaderBid', max(b for b in bids if b is not None), 'high', 'seat-current-price-roi'))

        if scene in ("UNKNOWN", "SETTLEMENT"):
            msg = "当前画面为终局结算，请使用结算核验" if scene == "SETTLEMENT" else "未在当前画面识别到对局信息"
            return {
                "ok": False,
                "scene": scene,
                "capturedAt": now_iso,
                "appliedFacts": {},
                "conflicts": [],
                "summary": msg,
                **empty_cards,
            }

        applied_facts: Dict[str, Any] = {}
        conflicts: List[Dict[str, Any]] = []
        unchanged_count = 0

        for patch in patches:
            k = patch.key
            v = patch.value
            if patch.confidence != "high":
                continue

            current_val = existing.get(k)
            # 1. If currently unknown/None, accept high-confidence candidate
            if current_val is None or current_val == "":
                applied_facts[k] = v
                existing[k] = v
            # 2. If identical value, treat as already aligned
            elif current_val == v:
                unchanged_count += 1
            # 3. If conflicting with existing value, manual/existing keeps authority
            else:
                conflicts.append({
                    "key": k,
                    "existing": current_val,
                    "detected": v,
                    "parser": patch.parser,
                })

        updated_count = len(applied_facts)
        if updated_count > 0:
            fact_names = ", ".join(f"{k}: {v}" for k, v in applied_facts.items())
            summary = f"快照识别成功：更新 {updated_count} 项 ({fact_names})"
        elif unchanged_count > 0 and not conflicts:
            summary = f"快照识别完成：{unchanged_count} 项与当前事实一致"
        elif conflicts:
            conflict_names = ", ".join(f"{c['key']}(现有:{c['existing']} vs 识别:{c['detected']})" for c in conflicts)
            summary = f"快照识别完成：{len(conflicts)} 项存在冲突已保留现有值 ({conflict_names})"
        else:
            summary = "快照未解析出新的有效对局事实"

        payload = {
            "ok": True,
            "scene": scene,
            "capturedAt": now_iso,
            "appliedFacts": applied_facts,
            "conflicts": conflicts,
            "summary": summary,
            "cardObservations": [],
            "intelCards": [],
            "intelRound": None,
            "intelTimer": None,
        }
        card_ev = self.extract_intel_card_evidence(frame, frame_id=now_iso) if self.include_card_evidence else None
        if card_ev is not None:
            payload["cardObservations"] = [obs.to_dict() for obs in card_ev.observations]
            payload["intelCards"] = [list(box) for box in card_ev.cards]
            payload["intelRound"] = card_ev.round
            payload["intelTimer"] = card_ev.timer
        return payload

    def extract_intel_card_evidence(self, frame: Optional[np.ndarray], frame_id: str = ""):
        """Optional single-shot card extractor. Does not write CurrentMatch."""
        if frame is None or getattr(frame, "size", 0) == 0:
            return None
        if min(frame.shape[:2]) < 400:
            return None
        try:
            from intel_card_evidence import IntelCardEvidenceExtractor
        except Exception:
            return None
        try:
            return IntelCardEvidenceExtractor(ocr_engine=self._ocr_engine).extract_frame(
                frame, frame_id=frame_id
            )
        except Exception:
            return None
