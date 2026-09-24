"""
Neverness to Everness (异环) - 拍卖视觉识别核心管道 (v0.65 全回合轨迹复盘版)
核心功能：
  1. 顶栏回合与倒计时识别 (Round 1~5 & Timer)
  2. 中间情报看板正则提取 (avg, Q, totalCells, venue, box, dark, sparkle, welfare)
  3. 4 人完整出价栏切片定位 (玩家本人出价 + 3位对手出价与姓名绑定)
  4. 领跑者与领跑价追踪 (Leader Bid & Leader Name)
  5. 1~5 回合完整出价与决策时序轨迹 (Full Round-by-Round Timeline for Replay & Research)
  6. 终局大结算账单提取 (Clearing Price, Actual Total, Realized Profit)
"""

import cv2
import numpy as np
import json
import re
import os
import time
import threading
from typing import Dict, Any, List, Optional, Tuple
from rapidocr_onnxruntime import RapidOCR
from settlement_item_recognizer import SettlementItemRecognizer
from warehouse_vision import WarehouseVisionV1, EvidenceLevel
from business_sot import extract_from_text, live_defaults
from vision_contract import VisionObservation, VisionIntel, VisionBids, VisionSettlement
from roi_scaler import ROIScaler
from character_matcher import CharacterMatcher, SettlementAssistantMatcher, CANONICAL_ROSTER, normalize_roster_name
from lobby_chip_matcher import LobbyChipMatcher, asset_dir

# 对局前导航 / 拍卖生命周期场景枚举
SCENE_UNKNOWN = "UNKNOWN"
SCENE_OPEN_WORLD = "OPEN_WORLD"                    # 大世界探索（按 F5 进都市大亨）
SCENE_CITY_TYCOON_HUB = "CITY_TYCOON_HUB"          # 都市大亨总览
SCENE_CITY_LEISURE_MENU = "CITY_LEISURE_MENU"      # 都市闲趣列表
SCENE_AUCTION_LOBBY = "AUCTION_LOBBY"              # 即刻落槌 · 拍卖大厅
SCENE_AUCTION_LOADING = "AUCTION_LOADING"          # 匹配/载入过场
SCENE_IN_AUCTION = "IN_AUCTION"                    # 局中竞拍
SCENE_SETTLEMENT = "SETTLEMENT"                    # 终局结算

SCENE_LABELS = {
    SCENE_UNKNOWN: "未知界面",
    SCENE_OPEN_WORLD: "大世界",
    SCENE_CITY_TYCOON_HUB: "都市大亨",
    SCENE_CITY_LEISURE_MENU: "都市闲趣",
    SCENE_AUCTION_LOBBY: "拍卖大厅",
    SCENE_AUCTION_LOADING: "对局载入中",
    SCENE_IN_AUCTION: "拍卖进行中",
    SCENE_SETTLEMENT: "结算界面",
}

# 对局前导航场景集合（未锁定局内/结算时，快检命中可直接返回）
PRE_AUCTION_NAV_SCENES = frozenset({
    SCENE_OPEN_WORLD,
    SCENE_CITY_TYCOON_HUB,
    SCENE_CITY_LEISURE_MENU,
    SCENE_AUCTION_LOBBY,
})
# 已由强证据确认的对局态：单帧弱导航快检不能直接推翻
LOCKED_MATCH_SCENES = frozenset({
    SCENE_IN_AUCTION,
    SCENE_SETTLEMENT,
})
MATCH_EXIT_HOLD_FRAMES = 8
SETTLEMENT_STABLE_FRAMES = 2
# The slow full-canvas pass is periodic; seat ROI runs on every auction frame.
AUCTION_DYNAMIC_OCR_INTERVAL_S = 3.5

def parse_bid_text(text: str) -> int:
    """
    解析《异环》特有的叫价文本，如 450K, 555.56K, 300,000, 886
    """
    text = text.strip().replace(",", "").replace("，", "").replace(" ", "").upper()
    if text.endswith("K"):
        num_part = text[:-1]
        try:
            if re.search(r"^\d+\.0{3,}$", num_part):
                num_part = num_part.replace(".", "")
            val = int(float(num_part) * 1000)
            rep = round(val / 111111) * 111111
            if abs(val - rep) <= 5 and rep > 0 and rep != 999999:
                return rep
            return val
        except Exception:
            return 0
    elif text.endswith("W"):
        num_part = text[:-1]
        try:
            return int(float(num_part) * 10000)
        except Exception:
            return 0
    elif text.endswith("M"):
        num_part = text[:-1]
        try:
            return int(float(num_part) * 1000000)
        except Exception:
            return 0
    else:
        cleaned = re.sub(r"[^\d]", "", text)
        if cleaned.isdigit():
            val = int(cleaned)
            if val > 5: # 过滤干扰数字
                return val
    return 0


def parse_money_amount(text: str, min_digits: int = 4) -> int:
    """
    解析均价/估价/结算金额。OCR 常把千分位读成 67,571 / 67.571 / 67，571。
    """
    if not text:
        return 0
    raw = str(text).strip()
    compact = re.sub(r"\s+", "", raw).upper()
    if compact.endswith("K") or compact.endswith("W"):
        return parse_bid_text(compact)
    normalized = compact.replace("，", ",").replace("．", ".").replace("、", ",")
    normalized = re.sub(r"['’‘`´]", ",", normalized)
    grouped = re.search(r"(\d{1,3}(?:[,.]\d{3})+)", normalized)
    if grouped:
        digits = re.sub(r"[,.]", "", grouped.group(1))
    else:
        m = re.search(rf"(\d{{{min_digits},}})", normalized)
        digits = m.group(1) if m else ""
    if digits.isdigit() and len(digits) >= min_digits:
        return int(digits)
    return 0

class NTEVisionPipeline:
    def __init__(self, catalog_path: Optional[str] = None):
        # RapidOCR / 结算器 / 仓库视觉都延后到真正进拍卖再加载。
        # 对局前场景走 OpenCV 小 ROI 快检（对齐 MaaNTE / AuctionPilot 的模板思路，不用整屏 OCR）。
        self._ocr_engine = None
        self._ocr_lock = threading.Lock()
        self._ocr_warming = False
        self._last_loadout_ts = 0.0
        self._settlement_recognizer = None
        self._settlement_evidence_store = None
        self._warehouse_vision = None
        self._prepared_warehouse_frame_id = None
        self._prepared_warehouse_state = None
        self._pending_heavy_identity = None
        self._character_matcher = None
        self._venue_matcher = None
        self._tool_matcher = None
        self._catalog_path = catalog_path
        self.ocr_call_count = 0
        self.ocr_skip_count = 0
        self._ocr_busy = False
        self._last_auction_ocr_ts = 0.0
        self._last_intel_sig = None
        self._full_canvas_frame_count = 0
        self.char_template_scan_count = 0
        self.venue_template_scan_count = 0
        self._df_shadow_estimate = None
        self._df_shadow_timer = None
        self._df_shadow_raw_text = {}
        self._df_shadow_conf = {}
        self._df_shadow_batch_count = 0
        self._df_shadow_seat_bids = [None, None, None, None]
        self._df_shadow_seat_bids_raw_text = ["", "", "", ""]
        self._df_shadow_seat_bids_conf = [0.0, 0.0, 0.0, 0.0]
        self._df_shadow_seat_bids_batch_count = 0
        self._async_intel_worker = None
        self._intel_ledger = None
        self._latest_intel_evidence = None
        self._round_intel_extracted = 0
        self._round_intel_scheduled = 0
        self._last_intel_card_sig = None
        self._last_intel_trigger_ts = 0.0
        self._session_generation = 0
        self._opening_seat_deferred = False
        self._defer_seat_heavy_once = False
        self._last_priority_seat_panel_ocr_sig = None
        self._priority_seat_panel_ocr_attempted = False
        self._confirmed_estimate = None
        self._estimate_candidate = {"val": None, "count": 0}
        self.catalog = []
        if catalog_path and os.path.exists(catalog_path):
            with open(catalog_path, 'r', encoding='utf-8') as f:
                self.catalog = json.load(f)
        
        self.current_context = {
            "round": 0,
            "timer": None,
            "scene": SCENE_UNKNOWN,
            "sceneLabel": SCENE_LABELS[SCENE_UNKNOWN],
            "auctionEntryVisible": False,  # 都市闲趣列表中是否看见「即刻落槌」入口卡
            "inAuction": False,
            "inLobby": False,
            "isLoading": False,
            "loadingPercent": None,
            "loadingVenue": None,
            # 大厅配置：仅在真正识别到大厅时写入，禁止用默认场地冒充当前画面
            "lobbyVenue": None,
            "lobbyVenueKey": None,
            "lobbyVenueLabel": None,
            "lobbyToolGroup": None,
            "lobbyCharacter": None,
            "lobbyCharacterScore": None,
            "lobbyCharacterSecondScore": None,
            "lobbyCharacterSource": None,
            "lobbyEntryCost": None,
            "character": None,
            "lobbyToolGroup": None,
            "solverToolGroup": live_defaults()["toolGroup"],
            "toolGroup": live_defaults()["toolGroup"],
            "totalItems": None,
            "q": None,
            "avg": None,
            "goldAvg": None,
            "purpleAvg": None,
            "blueAvg": None,
            "greenAvg": None,
            "whiteAvg": None,
            "redAvg": None,
            "currentEstimate": None,
            "goldTotal": None,
            "goldCount": None,
            "purple": None,
            "purpleCount": None,
            "blueCount": None,
            "greenCount": None,
            "whiteCount": None,
            "redCount": None,
            "totalGrids": None,
            "goldGrid": None,
            "purpleGrid": None,
            "blueGrid": None,
            "greenGrid": None,
            "whiteGrid": None,
            "redGrid": None,
            "boxType": None,
            "box": live_defaults()["box"],
            "venue": live_defaults()["venue"],
            "fieldCondition": live_defaults()["fieldCondition"],
            
            # 4人独立出价与领跑状态。未识别时保持 unknown，禁止伪造对手1/2/3。
            "myBid": 0,
            "myName": None,
            "seats": [
                {"slot": 1, "name": None, "bid": 0, "isMe": False},
                {"slot": 2, "name": None, "bid": 0, "isMe": False},
                {"slot": 3, "name": None, "bid": 0, "isMe": False},
                {"slot": 4, "name": None, "bid": 0, "isMe": False},
            ],
            "opponents": [],
            "currentLeaderBid": 0,
            "leaderName": None,
            "leaderTies": [],
            "isMyLead": False,
            "historicalBids": {},
            "finalBids": {},
            
            # 1~5 回合全时序复盘轨迹字典 (按回合归档)
            "roundTimeline": {},
            
            "knownGold": [],
            "knownPurple": [],
            "knownRed": [],
            "isSettlement": False,
            "settlementData": None,
            "leaderTies": [],
            "historicalBids": {},
            "finalBids": {},
            "settlementReady": False,
            "settlementFinalized": False,
            "settlementFileEvidence": None,
            "settlementFileEvidenceStatus": None,
            "settlementFileEvidenceWarning": None,
            "settlementWarehouseProposals": None,
            "settlementWarehouseProposalCount": 0,
            "settlementWarehouseProposalStatus": None,
            "settlementWarehouseProposalWarning": None,
            "settlementCatalogCandidateEvidence": None,
            "settlementCatalogCandidateCount": 0,
            "settlementCatalogCandidateStatus": None,
            "settlementCatalogCandidateWarning": None,
            "hadSettlement": False,
            "loadingDirection": None,
        }
        # 对局前场景短暂保持，避免单帧漏检闪回「待命」
        self._nav_hold_frames = 0
        # 已确认局内/结算时，弱导航快检需连续命中才允许离开
        self._match_exit_hold = 0
        self._last_loadout_ts = 0.0
        self._had_settlement = False
        self._settlement_sig = None
        if hasattr(self, '_best_settlement_observation'):
            del self._best_settlement_observation
        if hasattr(self, '_settlement_identity_memory'):
            del self._settlement_identity_memory
        self.current_context.pop('settlementIdentityFileOriginals', None)
        self._settlement_stable = 0
        self._settlement_finalized = False
        self._seat_round = 0
        self._slot_names = {1: None, 2: None, 3: None, 4: None}
        self._slot_finals = {1: {}, 2: {}, 3: {}, 4: {}}
        self._slot_cur_bids = {1: None, 2: None, 3: None, 4: None}
        self._slot_bid_candidates = {1: {"val": None, "count": 0}, 2: {"val": None, "count": 0}, 3: {"val": None, "count": 0}, 4: {"val": None, "count": 0}}
        self._slot_bid_evidence = {}
        self._frame_bid_captured_at = None
        self._leader_slot = None
        self._full_canvas_frame_count = 0
        self._df_shadow_estimate = None
        self._df_shadow_timer = None
        self._df_shadow_raw_text = {}
        self._df_shadow_conf = {}
        self._df_shadow_batch_count = 0
        self._df_shadow_seat_bids = [None, None, None, None]
        self._df_shadow_seat_bids_raw_text = ["", "", "", ""]
        self._df_shadow_seat_bids_conf = [0.0, 0.0, 0.0, 0.0]
        self._df_shadow_seat_bids_batch_count = 0
        self._match_gen = 0
        self._match_active = False
        self.current_context["matchGeneration"] = 0

    def _empty_seats(self) -> List[Dict[str, Any]]:
        return [
            {"slot": 1, "name": None, "bid": 0, "isMe": False},
            {"slot": 2, "name": None, "bid": 0, "isMe": False},
            {"slot": 3, "name": None, "bid": 0, "isMe": False},
            {"slot": 4, "name": None, "bid": 0, "isMe": False},
        ]

    def match_trunk_dirty(self) -> bool:
        c = self.current_context
        box = c.get("box")
        return bool(
            self._match_active
            or c.get("q") is not None
            or c.get("goldAvg") is not None
            or c.get("avg") is not None
            or c.get("purple") is not None
            or c.get("finalBids")
            or c.get("historicalBids")
            or c.get("settlementData")
            or c.get("settlementReady")
            or (box not in (None, "", "未知箱型"))
            or c.get("round")
            or (hasattr(self, "_intel_ledger") and self._intel_ledger is not None)
            or bool(c.get("publicCardEvents"))
        )

    def _should_preserve_trunk_for_archive(self) -> bool:
        return (bool(self.current_context.get("isSettlement") or self.current_context.get("scene") == SCENE_SETTLEMENT)
                and not self._settlement_finalized
                and not self.current_context.get("_clearTrunkAfterLeave"))

    def clear_match_trunk(self, reason: str = "") -> bool:
        """Clear one-match facts only. Keep lobby character / venue / tools."""
        if self._should_preserve_trunk_for_archive():
            return False
        if not self.match_trunk_dirty() and not self.current_context.get("settlementFinalized"):
            return False
        self._match_gen += 1
        self._pending_heavy_identity = None
        self._match_active = False
        lobby_venue = self.current_context.get("lobbyVenue")
        self.current_context.update({
            "matchGeneration": self._match_gen,
            "round": 0,
            "timer": None,
            "q": None,
            "totalItems": None,
            "totalGrids": None,
            "avg": None,
            "goldAvg": None,
            "purpleAvg": None,
            "blueAvg": None,
            "greenAvg": None,
            "whiteAvg": None,
            "redAvg": None,
            "goldTotal": None,
            "goldCount": None,
            "purple": None,
            "purpleCount": None,
            "blueCount": None,
            "greenCount": None,
            "whiteCount": None,
            "redCount": None,
            "goldGrid": None,
            "purpleGrid": None,
            "blueGrid": None,
            "greenGrid": None,
            "whiteGrid": None,
            "redGrid": None,
            "currentEstimate": None,
            "box": None,
            "boxType": None,
            "fieldCondition": None,
            "venue": lobby_venue or live_defaults()["venue"],
            "knownGold": [],
            "knownPurple": [],
            "knownRed": [],
            "myBid": 0,
            "myName": None,
            "seats": self._empty_seats(),
            "opponents": [],
            "currentLeaderBid": 0,
            "leaderName": None,
            "leaderTies": [],
            "isMyLead": False,
            "historicalBids": {},
            "finalBids": {},
            "roundTimeline": {},
            "isSettlement": False,
            "settlementData": None,
            "winner": None,
            "settlementReady": False,
            "settlementFinalized": False,
            "settlementItems": [],
            "settlementItemCount": 0,
            "settlementExactItemCount": 0,
            "settlementUnknownItemCount": 0,
            "settlementExactValueSum": 0,
            "settlementLedgerVerified": False,
            "settlementLedgerStatus": None,
            "settlementLedgerDelta": None,
            "settlementFileEvidence": None,
            "settlementFileEvidenceStatus": None,
            "settlementFileEvidenceWarning": None,
            "hadSettlement": False,
            "warehouseVision": {"slots": [], "totalExpectedVal": 0, "valRange": [0, 0]},
            "warehouseSlots": [],
            "warehouseExpectedVal": 0,
            "warehouseValRange": [0, 0],
            "probabilityProfile": None,
            "_clearTrunkAfterLeave": False,
            "intelFacts": None,
            "intelObservations": [],
            "intelCardReadings": [],
            "publicCardEvents": [],
        })
        self._intel_ledger = None
        self._latest_intel_evidence = None
        self._had_settlement = False
        self._settlement_sig = None
        self._settlement_stable = 0
        self._settlement_finalized = False
        self._seat_round = 0
        self._slot_names = {s: None for s in (1, 2, 3, 4)}
        self._slot_finals = {s: {} for s in (1, 2, 3, 4)}
        self._slot_cur_bids = {s: None for s in (1, 2, 3, 4)}
        self._slot_bid_candidates = {s: {"val": None, "count": 0} for s in (1, 2, 3, 4)}
        self._slot_bid_evidence = {}
        self._leader_slot = None
        self._reset_auction_ocr_scheduler()
        if self._warehouse_vision is not None:
            self._warehouse_vision.reset()
        self._prepared_warehouse_frame_id = None
        self._prepared_warehouse_state = None
        try:
            from live_shadow import invalidate_match_shadow
            invalidate_match_shadow(self._match_gen)
        except Exception:
            pass
        try:
            from settlement_truth_holder import ACTIVE_SETTLEMENT_TRUTH_HOLDER
            ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()
        except Exception:
            pass
        return True

    def _end_match_on_lobby_or_egress(self) -> None:
        if self._should_preserve_trunk_for_archive() and not self.current_context.get("_clearTrunkAfterLeave"):
            return
        self.clear_match_trunk()

    def reset_session_state(self) -> None:
        self._pending_heavy_identity = None
        if hasattr(self, "_acquisition_names"):
            self._acquisition_names.reset(None)
        self.current_context.pop("isAcquired", None)
        """强制刷新：丢掉粘住的大厅/场景，下一帧重新认。OCR 引擎保留。"""
        self.current_context.update({
            "_clearTrunkAfterLeave": False,
            "round": 0,
            "timer": None,
            "scene": SCENE_UNKNOWN,
            "sceneLabel": SCENE_LABELS[SCENE_UNKNOWN],
            "auctionEntryVisible": False,
            "inAuction": False,
            "inLobby": False,
            "isLoading": False,
            "loadingPercent": None,
            "loadingVenue": None,
            "hadSettlement": False,
            "loadingDirection": None,
            "lobbyVenue": None,
            "lobbyVenueKey": None,
            "lobbyVenueLabel": None,
            "lobbyToolGroup": None,
            "lobbyCharacter": None,
            "lobbyCharacterScore": None,
            "lobbyCharacterSecondScore": None,
            "lobbyCharacterSource": None,
            "lobbyEntryCost": None,
            "character": None,
            "lobbyToolGroup": None,
            "solverToolGroup": None,
            "toolGroup": None,
            "venue": live_defaults()["venue"],
            "box": live_defaults()["box"],
            "fieldCondition": live_defaults()["fieldCondition"],
            "boxType": None,
            "totalItems": None,
            "q": None,
            "avg": None,
            "goldAvg": None,
            "purpleAvg": None,
            "blueAvg": None,
            "greenAvg": None,
            "whiteAvg": None,
            "redAvg": None,
            "goldCount": None,
            "purple": None,
            "purpleCount": None,
            "blueCount": None,
            "currentEstimate": None,
            "isSettlement": False,
            "settlementData": None,
            "winner": None,
            "myName": None,
            "myBid": 0,
            "seats": self._empty_seats(),
            "opponents": [],
            "leaderName": None,
            "currentLeaderBid": 0,
            "isMyLead": False,
            "leaderTies": [],
            "historicalBids": {},
            "finalBids": {},
            "settlementReady": False,
            "settlementFinalized": False,
            "settlementFileEvidence": None,
            "settlementFileEvidenceStatus": None,
            "settlementFileEvidenceWarning": None,
            "settlementWarehouseProposals": None,
            "settlementWarehouseProposalCount": 0,
            "settlementWarehouseProposalStatus": None,
            "settlementWarehouseProposalWarning": None,
            "settlementCatalogCandidateEvidence": None,
            "settlementCatalogCandidateCount": 0,
            "settlementCatalogCandidateStatus": None,
            "settlementCatalogCandidateWarning": None,
            "warehouseVision": {"slots": [], "totalExpectedVal": 0, "valRange": [0, 0]},
            "warehouseSlots": [],
            "warehouseExpectedVal": 0,
            "warehouseValRange": [0, 0],
            "intelFacts": None,
            "intelObservations": [],
            "intelCardReadings": [],
            "publicCardEvents": [],
            "matchGeneration": self._match_gen + 1,
        })
        if self._warehouse_vision is not None:
            self._warehouse_vision.reset()
        self._prepared_warehouse_frame_id = None
        self._prepared_warehouse_state = None
        self._nav_hold_frames = 0
        self._match_exit_hold = 0
        self._last_loadout_ts = 0.0
        self._last_logged_scene_sig = None
        self._settlement_sig = None
        self._settlement_stable = 0
        self._settlement_finalized = False
        self._seat_round = 0
        self._slot_names = {1: None, 2: None, 3: None, 4: None}
        self._slot_finals = {1: {}, 2: {}, 3: {}, 4: {}}
        self._slot_cur_bids = {1: None, 2: None, 3: None, 4: None}
        self._slot_bid_candidates = {1: {"val": None, "count": 0}, 2: {"val": None, "count": 0}, 3: {"val": None, "count": 0}, 4: {"val": None, "count": 0}}
        self._slot_bid_evidence = {}
        self._leader_slot = None
        self._match_gen += 1
        self._df_shadow_estimate = None
        self._confirmed_estimate = None
        self._estimate_candidate = {"val": None, "count": 0}
        self._df_shadow_timer = None
        self._df_shadow_raw_text = {}
        self._df_shadow_conf = {}
        self._df_shadow_batch_count = 0
        self._df_shadow_seat_bids = [None, None, None, None]
        self._df_shadow_seat_bids_raw_text = ["", "", "", ""]
        self._df_shadow_seat_bids_conf = [0.0, 0.0, 0.0, 0.0]
        self._df_shadow_seat_bids_batch_count = 0
        self._session_generation = getattr(self, "_session_generation", 0) + 1
        self._intel_ledger = None
        self._latest_intel_evidence = None
        self._round_intel_extracted = 0
        self._round_intel_scheduled = 0
        self._last_intel_card_sig = None
        self._last_intel_trigger_ts = 0.0
        self._opening_seat_deferred = False
        self._defer_seat_heavy_once = False
        self._last_priority_seat_panel_ocr_sig = None
        self._priority_seat_panel_ocr_attempted = False
        if hasattr(self, "_async_intel_worker") and self._async_intel_worker is not None:
            try:
                extractor = self._async_intel_worker._get_extractor()
                if extractor is not None:
                    extractor.clear_card_cache()
            except Exception:
                pass
        self._reset_auction_ocr_scheduler()
        try:
            from live_shadow import invalidate_match_shadow
            invalidate_match_shadow(self._match_gen)
        except Exception:
            pass

    def _get_async_intel_worker(self):
        if not hasattr(self, "_async_intel_worker") or self._async_intel_worker is None:
            from intel_card_evidence import AsyncContinuousIntelWorker
            self._async_intel_worker = AsyncContinuousIntelWorker()
        return self._async_intel_worker

    def _get_priority_live_intel_extractor(self):
        if not hasattr(self, "_priority_live_intel_extractor") or self._priority_live_intel_extractor is None:
            from intel_card_evidence import IntelCardEvidenceExtractor
            self._priority_live_intel_extractor = IntelCardEvidenceExtractor(
                ocr_engine=self._ensure_ocr()
            )
        return self._priority_live_intel_extractor

    def _reset_auction_ocr_scheduler(self) -> None:
        self._ocr_busy = False
        self._last_auction_ocr_ts = 0.0
        self._last_intel_sig = None
        self._last_intel_card_sig = None
        self._full_canvas_frame_count = 0

    def _apply_estimate_observation(self, obs_val: Optional[int]) -> Optional[int]:
        """
        Estimate N=2 Candidate Confirmation Gate (4D2D1M-C2.26):
        - Filters single-frame legal-wrong transient jitter (e.g. 176535 -> 776535 -> 176535).
        - First valid observation: candidate (count = 1).
        - Consecutive second matching observation: commit to self._confirmed_estimate.
        - Differing observation: replace candidate (count = 1).
        - Invalid / None (< 1000 or None): clear candidate, hold self._confirmed_estimate.
        - Candidate before confirmation is NOT published.
        - Returns confirmed estimate (or None if never confirmed).
        """
        if obs_val is None or obs_val < 1000:
            self._estimate_candidate = {"val": None, "count": 0}
            return self._confirmed_estimate

        # If already equal to confirmed estimate
        if self._confirmed_estimate is not None and obs_val == self._confirmed_estimate:
            self._estimate_candidate = {"val": None, "count": 0}
            return self._confirmed_estimate

        cand = self._estimate_candidate
        if cand.get("val") == obs_val:
            cand["count"] += 1
            if cand["count"] >= 2:
                self._confirmed_estimate = obs_val
                cand["val"] = None
                cand["count"] = 0
        else:
            cand["val"] = obs_val
            cand["count"] = 1

        return self._confirmed_estimate

    def _official_quote_facts_ready(self) -> bool:
        """q + goldAvg only. This is the quote gate, not 'all intel collected'."""
        q = self.current_context.get("q")
        gold = self.current_context.get("goldAvg")
        if gold is None:
            gold = self.current_context.get("avg")
        try:
            return float(q) > 0 and float(gold) > 0
        except (TypeError, ValueError):
            return False

    def _intel_card_stack_sig(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Title / intel stack only. Excludes left seats to prevent seat bids from triggering intel OCR."""
        if frame is None or frame.size == 0:
            return None
        h, w = frame.shape[:2]
        bands = []
        for box in ((0.40, 0.14, 0.58, 0.22), (0.34, 0.13, 0.68, 0.80)):
            x1, y1, x2, y2 = int(w * box[0]), int(h * box[1]), int(w * box[2]), int(h * box[3])
            if y2 <= y1 or x2 <= x1:
                continue
            gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
            bands.append(cv2.resize(gray, (24, 12), interpolation=cv2.INTER_AREA).reshape(-1))
        if not bands:
            return None
        return np.stack(bands).astype(np.uint8)

    def _intel_card_stack_sig_changed(self, frame: np.ndarray) -> bool:
        sig = self._intel_card_stack_sig(frame)
        prev = getattr(self, "_last_intel_card_sig", None)
        if sig is None or prev is None or sig.shape != prev.shape:
            return True
        delta = np.mean(np.abs(sig.astype(np.int16) - prev.astype(np.int16)), axis=1)
        return bool(np.any(delta >= 1.5))

    def _priority_seat_panel_signature(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Build a compact signature for the existing seat names/current-bid ROI."""
        if frame is None or getattr(frame, "size", 0) == 0:
            return None
        panel = ROIScaler.crop_roi(frame, "seats_bids_panel")
        if panel.size == 0:
            return None
        gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY) if len(panel.shape) == 3 else panel
        return cv2.resize(gray, (72, 96), interpolation=cv2.INTER_AREA)

    def _intel_region_sig(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Title and intel cards; seat changes have their own fast ROI reader."""
        if frame is None or frame.size == 0:
            return None
        h, w = frame.shape[:2]
        bands = []
        # A bid change must not schedule a full-canvas OCR pass.
        for box in ((0.40, 0.14, 0.58, 0.22), (0.38, 0.28, 0.64, 0.68)):
            x1, y1, x2, y2 = int(w * box[0]), int(h * box[1]), int(w * box[2]), int(h * box[3])
            if y2 <= y1 or x2 <= x1:
                continue
            gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
            bands.append(cv2.resize(gray, (24, 12), interpolation=cv2.INTER_AREA).reshape(-1))
        if not bands:
            return None
        return np.stack(bands).astype(np.uint8)

    def _intel_sig_changed(self, frame: np.ndarray) -> bool:
        sig = self._intel_region_sig(frame)
        prev = self._last_intel_sig
        if sig is None or prev is None or sig.shape != prev.shape:
            return True
        delta = np.mean(np.abs(sig.astype(np.int16) - prev.astype(np.int16)), axis=1)
        return bool(np.any(delta >= 1.5))

    def _should_run_auction_canvas_ocr(self, frame: np.ndarray, force_refresh: bool = False) -> bool:
        """One RapidOCR at a time. Skip only after IN_AUCTION quote facts exist."""
        if force_refresh:
            return True
        if self._ocr_busy:
            self.ocr_skip_count += 1
            return False
        scene = self.current_context.get("scene")
        if scene != SCENE_IN_AUCTION or self.current_context.get("isSettlement"):
            # LOADING / 抽箱 still need canvas OCR: no non-OCR enter-auction hint.
            return True
        if not self._official_quote_facts_ready():
            return True
        now = time.monotonic()
        since = now - self._last_auction_ocr_ts if self._last_auction_ocr_ts else 1e9
        changed = self._intel_sig_changed(frame)
        if not changed and since < AUCTION_DYNAMIC_OCR_INTERVAL_S:
            self.ocr_skip_count += 1
            return False
        return True

    def _apply_confirmed_intel_facts(self, facts: Optional[Dict[str, Any]]) -> None:
        """Copy N=2 confirmed card fields into live context. Unknown does not clear."""
        if not isinstance(facts, dict):
            return
        mapping = {
            "q": "q",
            "goldAvg": "goldAvg",
            "purpleAvg": "purpleAvg",
            "goldCount": "goldCount",
            "purpleCount": "purple",
            "blueCount": "blueCount",
            "greenCount": "greenCount",
            "whiteCount": "whiteCount",
            "redCount": "redCount",
            "totalItems": "totalItems",
            "totalGrid": "totalGrids",
            "goldGrid": "goldGrid",
            "purpleGrid": "purpleGrid",
        }
        for src, dest in mapping.items():
            entry = facts.get(src)
            if not isinstance(entry, dict) or entry.get("status") != "OBSERVED":
                continue
            value = entry.get("value")
            if value is None:
                continue
            self.current_context[dest] = value
            if dest == "goldAvg":
                self.current_context["avg"] = value
            elif dest == "purple":
                self.current_context["purpleCount"] = value
            elif dest == "totalGrids":
                self.current_context["totalGrid"] = value

    @property
    def ocr(self):
        return self._ensure_ocr()

    @property
    def settlement_recognizer(self):
        if self._settlement_recognizer is None:
            self._settlement_recognizer = SettlementItemRecognizer()
        return self._settlement_recognizer

    @property
    def warehouse_vision(self):
        if self._warehouse_vision is None:
            self._warehouse_vision = WarehouseVisionV1(catalog_path=self._catalog_path)
        return self._warehouse_vision

    def prepare_warehouse_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """Run the existing warehouse recognizer before the heavyweight frame path.

        The live worker may use this result for an early HUD publish. Cache it by
        the exact frame object so the normal process_frame path consumes the
        result instead of advancing the temporal tracker twice for one capture.
        """
        state = self.warehouse_vision.process_frame(frame)
        self._prepared_warehouse_frame_id = id(frame)
        self._prepared_warehouse_state = state
        return state

    def _take_prepared_warehouse_frame(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        if self._prepared_warehouse_frame_id != id(frame):
            if self._prepared_warehouse_frame_id is not None:
                self._prepared_warehouse_frame_id = None
                self._prepared_warehouse_state = None
            return None
        state = self._prepared_warehouse_state
        self._prepared_warehouse_frame_id = None
        self._prepared_warehouse_state = None
        return state

    def _apply_warehouse_state(self, wh_state: Optional[Dict[str, Any]]) -> None:
        state = wh_state if isinstance(wh_state, dict) else {}
        self.current_context["warehouseVision"] = state
        self.current_context["warehouseSlots"] = state.get("slots", [])
        self.current_context["warehouseExpectedVal"] = state.get("totalExpectedVal", 0)
        self.current_context["warehouseValRange"] = state.get("valRange", [0, 0])

    def _attach_settlement_ledger(
        self,
        settlement: Dict[str, Any],
        *,
        frame: np.ndarray,
        captured_at: Optional[str],
        actual_total: Any,
    ) -> None:
        ledger = self.settlement_recognizer.parse_settlement_ledger(frame, actual_total=actual_total)
        settlement["items"] = ledger["settlementItems"]
        settlement["ledger"] = ledger
        self.current_context["settlementData"] = settlement
        self.current_context["settlementItems"] = ledger["settlementItems"]
        self.current_context["settlementItemCount"] = ledger["settlementItemCount"]
        self.current_context["settlementExactItemCount"] = ledger["settlementExactItemCount"]
        self.current_context["settlementUnknownItemCount"] = ledger["settlementUnknownItemCount"]
        self.current_context["settlementExactValueSum"] = ledger["settlementExactValueSum"]
        self.current_context["settlementLedgerVerified"] = ledger["settlementLedgerVerified"]
        self.current_context["settlementLedgerStatus"] = ledger["settlementLedgerStatus"]
        self.current_context["settlementLedgerDelta"] = ledger["settlementLedgerDelta"]
        # Boundary 2: the ledger's visual quality-sell detection must reach the product
        # surface. Without this promotion it stays buried in settlement["ledger"] and the
        # archiver/canonical/history/UI all fall back to the "unknown" default.
        for _qkey in (
            "qualitySellSelection",
            "qualitySellSelectionSource",
            "qualitySellSelectionSources",
        ):
            if ledger.get(_qkey) is not None:
                settlement[_qkey] = ledger[_qkey]
                self.current_context[_qkey] = ledger[_qkey]
        self._stabilize_settlement(settlement, frame=frame, captured_at=captured_at)

    def take_deferred_identity(self) -> Optional[Dict[str, Any]]:
        """Transfer the deferred frame descriptor to an external bounded worker.

        The caller must copy the pixels before releasing its frame ownership.
        This method does not run recognition or mutate the pipeline context.
        """
        pending = self._pending_heavy_identity
        self._pending_heavy_identity = None
        if not isinstance(pending, dict):
            return None
        return dict(pending)

    def complete_heavy_identity(self) -> Optional[Dict[str, Any]]:
        """Finish warehouse/settlement identity deferred from process_frame."""
        pending = self._pending_heavy_identity
        self._pending_heavy_identity = None
        if not isinstance(pending, dict):
            return None
        frame = pending.get("frame")
        kind = pending.get("kind")
        if frame is None or getattr(frame, "size", 0) == 0:
            return None
        if kind == "settlement":
            if self.current_context.get("scene") != SCENE_SETTLEMENT:
                return None
            settlement = self.current_context.get("settlementData")
            if not isinstance(settlement, dict):
                return None
            self._attach_settlement_ledger(
                settlement,
                frame=frame,
                captured_at=pending.get("captured_at"),
                actual_total=pending.get("actual_total"),
            )
            return self.current_context
        if kind == "warehouse":
            if self.current_context.get("scene") != SCENE_IN_AUCTION:
                return None
            self._apply_warehouse_state(self.warehouse_vision.process_frame(frame))
            return self.current_context
        return None

    @property
    def character_matcher(self) -> CharacterMatcher:
        if self._character_matcher is None:
            from character_matcher import default_template_dir
            self._character_matcher = CharacterMatcher(template_dir=default_template_dir(self._catalog_path))
        return self._character_matcher

    @property
    def settlement_assistant_matcher(self) -> SettlementAssistantMatcher:
        if getattr(self, "_settlement_assistant_matcher", None) is None:
            from character_matcher import default_template_dir
            self._settlement_assistant_matcher = SettlementAssistantMatcher(
                template_dir=default_template_dir(self._catalog_path)
            )
        return self._settlement_assistant_matcher

    @property
    def venue_matcher(self) -> LobbyChipMatcher:
        if self._venue_matcher is None:
            self._venue_matcher = LobbyChipMatcher(
                template_dir=asset_dir("lobby_venues", self._catalog_path),
                roi_key="lobby_venue_search",
                result_key="venueLabel",
            )
        return self._venue_matcher

    @property
    def tool_matcher(self) -> LobbyChipMatcher:
        if self._tool_matcher is None:
            self._tool_matcher = LobbyChipMatcher(
                template_dir=asset_dir("lobby_tools", self._catalog_path),
                roi_key="lobby_tool_search",
                result_key="toolGroup",
            )
        return self._tool_matcher

    def _ensure_ocr(self):
        if self._ocr_engine is None:
            with self._ocr_lock:
                if self._ocr_engine is None:
                    # Bound CPU contention across OCR sessions and the live UI.
                    self._ocr_engine = RapidOCR(intra_op_num_threads=min(4, os.cpu_count() or 1),
                                                inter_op_num_threads=1)
        return self._ocr_engine

    def _warm_ocr_async(self) -> None:
        if self._ocr_engine is not None or self._ocr_warming:
            return
        self._ocr_warming = True
        threading.Thread(target=self._ensure_ocr, name="warm-rapidocr", daemon=True).start()

    def _bind_acquisition_record(self, record_stable_key):
        from acquisition_authority import AcquisitionNameTracker
        from player_identity import get_player_name
        if not hasattr(self, "_acquisition_names"):
            self._acquisition_names = AcquisitionNameTracker()
        configured_name = get_player_name()
        identity_changed = self._acquisition_names.configured_name != configured_name
        self._acquisition_names.set_player_name(configured_name)
        key = str(record_stable_key) if record_stable_key else self.current_context.get("recordStableKey")
        if self._acquisition_names.key != key or identity_changed:
            # Also run before scene/worker early returns: those are still new-record outputs.
            for field in ("isAcquired", "didCurrentUserAcquire", "acquired", "winner"):
                self.current_context.pop(field, None)
            for field in ("settlement", "settlementData"):
                value = self.current_context.get(field)
                if isinstance(value, dict):
                    self.current_context[field] = {**value, "acquired": None,
                                                  "isAcquired": None, "didCurrentUserAcquire": None,
                                                  "winner": None}
            self._acquisition_names.bind(key)
        if record_stable_key:
            self.current_context.update(recordStableKey=key, id=key, matchId=key)

    def process_frame(
        self,
        frame: np.ndarray,
        captured_at: Optional[str] = None,
        force_refresh: bool = False,
        record_stable_key: Optional[str] = None,
        include_heavy_identity: bool = True,
        prioritize_live_facts: bool = False,
    ) -> Dict[str, Any]:
        """
        处理图像帧（支持局部 ROI 极速 OCR 解析 + 4人出价与全回合轨迹时序追踪）
        captured_at 必须由真实的 frame capture boundary 传入 aware ISO 时间戳。
        force_refresh=True 时绕过大厅齐套降频，并允许角色识别失败后清空旧值。
        include_heavy_identity=False skips warehouse/settlement identity so the
        live loop can publish OCR facts before the slow catalog match.
        prioritize_live_facts=True uses the strict round-title ROI to enter the
        live auction path and defers the optional detector-based estimate fallback.
        """
        self._bind_acquisition_record(record_stable_key)
        self._frame_bid_captured_at = captured_at
        self._acquisition_frame = getattr(self, "_acquisition_frame", 0) + 1
        self._frame_ocr_rows = []

        # A prepared warehouse observation is valid only for the exact frame
        # that was already inspected by the early-publish path.
        if self._prepared_warehouse_frame_id not in (None, id(frame)):
            self._prepared_warehouse_frame_id = None
            self._prepared_warehouse_state = None
        self._pending_heavy_identity = None

        h, w, _ = frame.shape

        # 0. 对局前：OpenCV 小图快检，毫秒级。禁止为了认大世界/都市大亨去跑 RapidOCR。
        fast = self._classify_scene_fast(frame)
        prev = self.current_context.get("scene")
        mode_provider = getattr(self, 'recognition_mode_provider', None)
        mode = mode_provider() if mode_provider else 'auto'
        self.current_context['recognitionMode'] = mode
        if mode == 'manual' and not force_refresh and fast['scene'] != SCENE_SETTLEMENT and prev != SCENE_SETTLEMENT:
            # No auction OCR in manual mode; settlement capture is independent.
            self.current_context['isSettlement'] = False
            if fast['scene'] in PRE_AUCTION_NAV_SCENES:
                self._apply_pre_auction_scene(fast)
            return self.current_context
        # 滞回：已在大世界时，除非明确看到白城都市大亨，否则不跳走
        if prev == SCENE_OPEN_WORLD and fast["scene"] == SCENE_CITY_TYCOON_HUB:
            if not fast.get("whiteCity"):
                fast = {"scene": SCENE_OPEN_WORLD, "auctionEntryVisible": False}
        if prev == SCENE_CITY_TYCOON_HUB and fast["scene"] == SCENE_OPEN_WORLD:
            # 白城菜单里的圆标不能把都市大亨打回大世界
            if fast.get("whiteCity"):
                fast = {"scene": SCENE_CITY_TYCOON_HUB, "auctionEntryVisible": False}
        # 已在拍卖大厅时，HUD 亮面板 / 展厅灯光不能把场景打回都市大亨
        if prev == SCENE_AUCTION_LOBBY and fast["scene"] == SCENE_CITY_TYCOON_HUB:
            fast = {"scene": SCENE_AUCTION_LOBBY, "auctionEntryVisible": True, "lobbySuspect": True}
        # 已确认局内/结算：弱导航快检只是候选，不能无条件 early-return。
        # 真正离开必须靠后面 OCR 的 LOADING / SETTLEMENT / 明确大厅，或连续若干帧导航证据。
        if prev in LOCKED_MATCH_SCENES:
            pass
        elif fast["scene"] == SCENE_OPEN_WORLD and prev in (
            SCENE_AUCTION_LOBBY, SCENE_AUCTION_LOADING, SCENE_SETTLEMENT
        ):
            # loading / 抽箱暗厅会被快检打成大世界；先走 OCR，禁止提前清掉本局
            pass
        elif fast["scene"] in PRE_AUCTION_NAV_SCENES:
            self._nav_hold_frames = 0
            self._match_exit_hold = 0
            self._apply_pre_auction_scene(fast)
            # 进都市大亨/闲趣就开始预热 OCR，进大厅后 1 秒内要扫到助手和仪器组
            if fast["scene"] in (SCENE_CITY_TYCOON_HUB, SCENE_CITY_LEISURE_MENU, SCENE_AUCTION_LOBBY):
                self._warm_ocr_async()
            if fast["scene"] == SCENE_AUCTION_LOBBY:
                self._refresh_lobby_loadout(frame, force=force_refresh)
            return self.current_context
        # 颜色快检漏掉的大厅/选场：先出大厅态，OCR 只扫小胶囊，禁止同步加载整引擎堵 6~20 秒
        elif (fast.get("venueOrange", 0) >= 0.03 or fast.get("lobbySuspect")) and prev not in LOCKED_MATCH_SCENES:
            self._nav_hold_frames = 0
            self._match_exit_hold = 0
            self._apply_pre_auction_scene({"scene": SCENE_AUCTION_LOBBY, "auctionEntryVisible": True})
            self._warm_ocr_async()
            self._refresh_lobby_loadout(frame, force=force_refresh)
            return self.current_context
        # 闲趣/大厅等菜单已离开白城时，不要把上一屏都市大亨粘住
        if prev not in LOCKED_MATCH_SCENES:
            if prev == SCENE_CITY_TYCOON_HUB and not fast.get("whiteCity") and fast["scene"] != SCENE_CITY_TYCOON_HUB:
                if fast["scene"] == SCENE_UNKNOWN:
                    self._clear_nav_scene()
                # 已由上面 fast 命中分支返回
            elif prev in PRE_AUCTION_NAV_SCENES:
                # 大厅之后的 loading/抽箱常被快检打成 UNKNOWN/OPEN_WORLD。
                # 不能 hold 住大厅直接 return，否则 OCR 永远看不到载入/局内。
                if prev == SCENE_AUCTION_LOBBY and fast["scene"] in (SCENE_UNKNOWN, SCENE_OPEN_WORLD):
                    pass
                else:
                    self._hold_nav_or_clear(max_hold=3)
                    if self.current_context.get("scene") in PRE_AUCTION_NAV_SCENES:
                        return self.current_context

        # 未命中对局前导航：可能已在局内 / 载入 / 结算。OCR 没就绪就先待命，不卡导航帧。
        # 已锁定的局内/结算保持原态，禁止被「OCR 未就绪」清成未知。
        if self._ocr_engine is None:
            self._warm_ocr_async()
            # OCR 未就绪不是退出证据：已锁定局内/结算保持原态
            return self.current_context

        # Increment frame counter for bounded stride
        self._full_canvas_frame_count += 1

        prev_timer = self.current_context.get("timer")
        is_auction_scene = (self.current_context.get("scene") == SCENE_IN_AUCTION or self.current_context.get("inAuction"))
        round_title_confirmed = False
        preflight_round = None
        if (
            prioritize_live_facts
            and not is_auction_scene
            and not self.current_context.get("isSettlement")
            and self.current_context.get("scene") != SCENE_SETTLEMENT
            and fast.get("scene") != SCENE_SETTLEMENT
        ):
            # The exact, high-confidence round title is sufficient evidence to
            # enter the existing live path. This avoids a blocking canvas scan
            # on the first auction frame while keeping settlement fail-closed.
            observed_round = self._read_df_auction_round_title(frame)
            previous_round = int(self.current_context.get("round") or 0)
            round_is_current = (
                observed_round is not None
                and (not self._match_active or previous_round <= 0 or observed_round >= previous_round)
            )
            if round_is_current:
                preflight_round = int(observed_round)
                round_title_confirmed = True
                self.current_context.update({
                    "scene": SCENE_IN_AUCTION,
                    "sceneLabel": SCENE_LABELS[SCENE_IN_AUCTION],
                    "round": preflight_round,
                    "inAuction": True,
                    "inLobby": False,
                    "isLoading": False,
                    "isSettlement": False,
                    "auctionEntryVisible": False,
                    "hadSettlement": False,
                    "loadingDirection": None,
                })
                self._match_exit_hold = 0
                if not self._match_active:
                    self._match_active = True
                    self._match_gen += 1
                    self.current_context["matchGeneration"] = self._match_gen
                self._had_settlement = False
                is_auction_scene = True

        df_est = None
        df_timer = None
        df_seat_bids = None
        df_seat_success = False
        priority_live_evidence = None
        priority_seat_panel_changed = None
        priority_seat_panel_signature = None
        frame_looks_settlement = bool(
            self.current_context.get("isSettlement")
            or self.current_context.get("scene") == SCENE_SETTLEMENT
            or fast.get("scene") == SCENE_SETTLEMENT
        )
        if is_auction_scene and prioritize_live_facts and not frame_looks_settlement:
            observed_round = preflight_round
            if observed_round is None:
                observed_round = self._read_df_auction_round_title(frame)
            if observed_round is not None:
                previous_round = int(self.current_context.get("round") or 0)
                if observed_round >= previous_round:
                    self.current_context["round"] = observed_round
                    round_title_confirmed = True

            cur_round = int(self.current_context.get("round") or 0)
            now_m = time.monotonic()
            since_intel_trig = now_m - getattr(self, "_last_intel_trigger_ts", 0.0)
            pending_fields = self._intel_ledger.get_pending_verify_fields() if self._intel_ledger else None
            needs_round_extraction = bool(cur_round > 0 and getattr(self, "_round_intel_scheduled", 0) != cur_round)
            intel_sig_changed = self._intel_card_stack_sig_changed(frame)
            priority_card_trigger = bool(
                not getattr(self, "fast_live_intel", False)
                and (
                    needs_round_extraction
                    or (intel_sig_changed and since_intel_trig >= 1.0)
                    or (pending_fields and since_intel_trig >= 0.1)
                )
            )
            if priority_card_trigger:
                if needs_round_extraction:
                    self._round_intel_scheduled = cur_round
                self._last_intel_card_sig = self._intel_card_stack_sig(frame)
                self._last_intel_trigger_ts = now_m

            # Keep all time-sensitive numeric regions in one recognizer batch.
            # On a card update, the card line crops join this same batch.
            priority_seat_panel_signature = self._priority_seat_panel_signature(frame)
            if priority_seat_panel_signature is not None:
                previous_seat_panel = getattr(self, "_last_priority_seat_panel_ocr_sig", None)
                priority_seat_panel_changed = (
                    previous_seat_panel is None
                    or previous_seat_panel.shape != priority_seat_panel_signature.shape
                    or float(np.mean(np.abs(
                        priority_seat_panel_signature.astype(np.int16)
                        - previous_seat_panel.astype(np.int16)
                    ))) >= 1.5
                )
            h, w = frame.shape[:2]
            tx1, ty1, tx2, ty2 = int(w * 0.483), int(h * 0.055), int(w * 0.525), int(h * 0.090)
            priority_crops = [frame[ty1:ty2, tx1:tx2]]
            priority_crops.extend(
                ROIScaler.crop_roi(frame, f"seat_current_bid_{slot}")
                for slot in (1, 2, 3, 4)
            )
            from bid_glyph_crop import compact_bid_glyph
            for index in range(1, len(priority_crops)):
                compact = compact_bid_glyph(priority_crops[index])
                if compact is not None:
                    priority_crops[index] = compact

            valid_crop_indices = [i for i, crop in enumerate(priority_crops) if getattr(crop, "size", 0) > 0]
            valid_crops = [priority_crops[i] for i in valid_crop_indices]
            aligned_results = [None, None, None, None, None]
            if valid_crops:
                external_results = []
                iso_id = captured_at or time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
                if priority_card_trigger:
                    try:
                        priority_live_evidence = self._get_priority_live_intel_extractor().extract_cards_fast(
                            frame,
                            frame_id=iso_id,
                            generation=self._match_gen,
                            known_round=cur_round,
                            known_timer=prev_timer,
                            pending_verify_fields=pending_fields,
                            projection_threshold=95,
                            projection_min_row_density=0.01,
                            allow_detector_fallback=False,
                            external_crops=valid_crops,
                            external_results_out=external_results,
                        )
                    except Exception:
                        priority_live_evidence = None
                else:
                    try:
                        external_results, _ = self._ocr_engine.text_rec(valid_crops)
                    except Exception:
                        external_results = []
                for crop_index, result in zip(valid_crop_indices, external_results):
                    aligned_results[crop_index] = result

            try:
                df_est, df_timer = self._read_df_numeric_batch(
                    frame,
                    include_estimate=False,
                    precomputed_results=[aligned_results[0]] if aligned_results[0] is not None else [],
                )
            except Exception:
                df_est = None
                df_timer = None
            try:
                df_seat_bids = self._run_df_seat_bids_shadow(frame, precomputed_results=aligned_results[1:5])
                df_seat_success = any(value is not None for value in df_seat_bids)
            except Exception:
                self._df_shadow_seat_bids = [None, None, None, None]
                df_seat_bids = None
                df_seat_success = False
            if priority_live_evidence is not None and priority_live_evidence.cards:
                # The timer result comes from the same recognizer call as these
                # cards, so attach its parsed value before recording provenance.
                priority_live_evidence.timer = df_timer if df_timer is not None else prev_timer
                for observation in priority_live_evidence.observations:
                    observation.timer = priority_live_evidence.timer
                for reading in priority_live_evidence.cardReadings:
                    reading["timer"] = priority_live_evidence.timer
                self._latest_intel_evidence = priority_live_evidence
                if self._intel_ledger is None:
                    from intel_card_evidence import IntelCardEvidenceLedger
                    self._intel_ledger = IntelCardEvidenceLedger()
                self._intel_ledger.merge(priority_live_evidence)
                if priority_live_evidence.round:
                    self._round_intel_extracted = priority_live_evidence.round
                has_priority_fact = False
                for observation in priority_live_evidence.observations:
                    if (
                        observation.status != "OBSERVED"
                        or observation.value is None
                        or observation.value == "UNKNOWN"
                        or float(observation.confidence or 0.0) < 0.90
                    ):
                        continue
                    if observation.field in {"q", "goldAvg", "purpleAvg"}:
                        self.current_context[observation.field] = observation.value
                        if observation.field == "goldAvg":
                            self.current_context["avg"] = observation.value
                        has_priority_fact = True
                if has_priority_fact:
                    # Seat number OCR remains live; defer player-name panel OCR
                    # for this frame so it cannot delay bids.
                    self._defer_seat_heavy_once = True
        elif is_auction_scene and not frame_looks_settlement:
            observed_round = preflight_round
            if observed_round is None:
                observed_round = self._read_df_auction_round_title(frame)
            if observed_round is not None:
                previous_round = int(self.current_context.get("round") or 0)
                if observed_round >= previous_round:
                    self.current_context["round"] = observed_round
                    round_title_confirmed = True
            try:
                df_est, df_timer = self._read_df_numeric_batch(frame)
            except Exception:
                df_est = None
                df_timer = None
            try:
                df_seat_bids = self._run_df_seat_bids_shadow(frame)
                df_seat_success = any(value is not None for value in df_seat_bids)
            except Exception:
                self._df_shadow_seat_bids = [None, None, None, None]
                df_seat_bids = None
                df_seat_success = False
        else:
            self._df_shadow_estimate = None
            self._df_shadow_timer = None
            self._df_shadow_raw_text = {}
            self._df_shadow_conf = {}
            self._df_shadow_seat_bids = [None, None, None, None]
            self._df_shadow_seat_bids_raw_text = ["", "", "", ""]
            self._df_shadow_seat_bids_conf = [0.0, 0.0, 0.0, 0.0]

        if is_auction_scene and df_timer is not None:
            roi_timer = df_timer
        else:
            roi_timer = None

        cur_timer = roi_timer if roi_timer is not None else prev_timer

        # Async Continuous Intel remains available to the non-priority paths.
        # The live worker performs card and numeric OCR in the shared batch above,
        # so creating a second RapidOCR worker here would contend for the CPU.
        intel_worker = None
        completed_intel_evs = []
        if not prioritize_live_facts:
            intel_worker = self._get_async_intel_worker()
            completed_intel_evs = intel_worker.poll_results(getattr(self, "_session_generation", 0))
        for ev in completed_intel_evs:
            current_round = int(self.current_context.get("round") or 0)
            if ev.round and current_round and int(ev.round) < current_round:
                # A previous round's late OCR cannot become this round's card.
                continue
            if self._intel_ledger is None:
                from intel_card_evidence import IntelCardEvidenceLedger
                self._intel_ledger = IntelCardEvidenceLedger()
            self._latest_intel_evidence = ev
            if ev.round:
                self._round_intel_extracted = ev.round
            self._intel_ledger.merge(ev)

        # 2. Check trigger conditions in auction scene
        is_settlement = bool(self.current_context.get("isSettlement") or self.current_context.get("scene") == SCENE_SETTLEMENT)
        if (
            is_auction_scene
            and not is_settlement
            and not prioritize_live_facts
            and not getattr(self, 'fast_live_intel', False)
        ):
            cur_round = int(self.current_context.get("round") or 0)
            now_m = time.monotonic()
            since_intel_trig = now_m - getattr(self, "_last_intel_trigger_ts", 0.0)

            # Check if ledger has unconfirmed/tentative/challenger fields that need verification
            pending_fields = self._intel_ledger.get_pending_verify_fields() if self._intel_ledger else None
            has_pending_verify = bool(pending_fields)

            needs_round_extraction = bool(cur_round > 0 and getattr(self, "_round_intel_scheduled", 0) != cur_round)
            intel_sig_changed = self._intel_card_stack_sig_changed(frame)
            can_trigger_by_sig = bool(intel_sig_changed and since_intel_trig >= 1.0)
            can_trigger_by_pending = bool(has_pending_verify and since_intel_trig >= 0.1)

            if needs_round_extraction or can_trigger_by_sig or can_trigger_by_pending:
                if needs_round_extraction:
                    self._round_intel_scheduled = cur_round
                self._last_intel_card_sig = self._intel_card_stack_sig(frame)
                self._last_intel_trigger_ts = now_m
                iso_id = captured_at or time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
                intel_worker.submit_frame(
                    frame,
                    frame_id=iso_id,
                    generation=getattr(self, "_session_generation", 0),
                    known_round=cur_round,
                    known_timer=cur_timer,
                    pending_verify_fields=pending_fields,
                )

        # =========================================================================
        # Full-Canvas Decision (4D2D1L-L3N.2: FULL_CANVAS_STRIDE = 2 + Safe Force Triggers)
        # =========================================================================
        is_first_frame = (self._full_canvas_frame_count <= 1)
        stride_due = (self._full_canvas_frame_count % 2 == 1)
        is_force = bool(force_refresh)

        # Visual change trigger (0ms lightweight mathematical difference check)
        visual_changed = self._intel_sig_changed(frame)

        # Timer transition trigger: timer <= 3 or timer upward jump >= 10s (new round reset)
        timer_jump = bool(roi_timer is not None and prev_timer is not None and (roi_timer - prev_timer) >= 10)
        timer_force = bool(cur_timer is not None and cur_timer <= 3) or timer_jump

        # In non-auction scenes (lobby, loading, world), full canvas is needed to detect match entrance
        non_auction_scene = (self.current_context.get("scene") != SCENE_IN_AUCTION and not self.current_context.get("inAuction"))

        should_run_full_canvas = (
            is_first_frame
            or stride_due
            or is_force
            or visual_changed
            or timer_force
            or non_auction_scene
        )
        if is_auction_scene and round_title_confirmed and not force_refresh:
            # The strict round ROI and priority card recognizer own the live
            # path; broad scene OCR would delay the current bid publication.
            should_run_full_canvas = False
            self.ocr_skip_count += 1
        elif is_auction_scene and not self._should_run_auction_canvas_ocr(frame, force_refresh):
            should_run_full_canvas = False

        detected_feature = False
        full_canvas_est = None
        full_canvas_timer = None
        mapped_res = []

        if should_run_full_canvas:
            # Unknown input may already be a settlement. Its title and value
            # labels lie outside the narrow opening ROI, so classify it first.
            use_focused_opening = bool(
                self.current_context.get("scene") == SCENE_AUCTION_LOADING
                and self.current_context.get("loadingDirection") == "to_auction"
                and not self.current_context.get("isSettlement")
            )
            canvas_roi_key = "focused_opening_canvas" if use_focused_opening else "auction_main_canvas"
            rx1, ry1, rx2, ry2 = ROIScaler.scale_roi(canvas_roi_key, w, h)
            # The center carries auction facts; seats have their own reader.
            # Keep full-frame scene discovery until auction is established.
            if getattr(self, 'fast_live_intel', False) and (is_auction_scene or fast['scene'] == SCENE_IN_AUCTION) and fast['scene'] != SCENE_SETTLEMENT:
                rx1, ry1, rx2, ry2 = int(w*.32), 0, int(w*.74), int(h*.97)
            elif getattr(self, 'scene_roi_router', None) is not None and fast['scene'] == SCENE_SETTLEMENT:
                rx1,ry1,rx2,ry2=0,0,int(w*.65),h
            roi = frame[ry1:ry2, rx1:rx2]

            self._ocr_busy = True
            try:
                res, _ = self.ocr(roi)
                self.ocr_call_count += 1
                self._last_auction_ocr_ts = time.monotonic()
                self._last_intel_sig = self._intel_region_sig(frame)
            finally:
                self._ocr_busy = False

            if not res and use_focused_opening and not (self.current_context.get("scene") in LOCKED_MATCH_SCENES):
                # Fallback to auction_main_canvas if focused opening returned nothing on unlocked scene
                rx1, ry1, rx2, ry2 = ROIScaler.scale_roi("auction_main_canvas", w, h)
                roi = frame[ry1:ry2, rx1:rx2]
                self._ocr_busy = True
                try:
                    res, _ = self.ocr(roi)
                    self.ocr_call_count += 1
                finally:
                    self._ocr_busy = False

            if not res:
                if self._try_release_locked_match(fast):
                    return self.current_context
                if (
                    self.current_context.get("scene") in LOCKED_MATCH_SCENES
                    and not (prioritize_live_facts and round_title_confirmed)
                ):
                    return self.current_context
                if self.current_context.get("scene") not in LOCKED_MATCH_SCENES:
                    self._hold_nav_or_clear(max_hold=1)
                    return self.current_context

            # 将 OCR 坐标映射回全屏空间
            for box, text, score in res:
                mapped_box = [[b[0] + rx1, b[1] + ry1] for b in box]
                mapped_res.append((mapped_box, text, score))
            self._frame_ocr_rows = mapped_res

            # 0b. 大厅/闲趣卡片等可能只在中屏
            scene_info = self._classify_pre_auction_scene(mapped_res, w, h)
            if scene_info["scene"] in PRE_AUCTION_NAV_SCENES:
                if not self._locked_match_blocks_ocr_nav(scene_info):
                    self._nav_hold_frames = 0
                    self._apply_pre_auction_scene(scene_info)
                    return self.current_context

            # 1. 拍卖大厅
            #
            # A locked IN_AUCTION frame may still contain a transient OCR
            # hallucination of a lobby anchor (for example, a button/venue
            # token from the animated side panels).  The old "absolute
            # priority" rule let that single OCR result overwrite a known
            # live round and made the Host pause the observation immediately.
            # A live-round anchor from this same frame is stronger evidence
            # than a conflicting lobby token, so keep the locked match and
            # let the normal round/intel parser consume the frame below.
            lobby_info = self._parse_lobby(mapped_res, w, h)
            live_round_evidence = (
                self.current_context.get("scene") == SCENE_IN_AUCTION
                and not self.current_context.get("isSettlement")
                and self._has_live_auction_evidence(mapped_res, w, h)
            )
            if lobby_info["inLobby"] and not live_round_evidence:
                self._apply_lobby_loadout(lobby_info)
                self._end_match_on_lobby_or_egress()
                return self.current_context

            # 2. 终局大结算界面
            settlement = self._parse_settlement(mapped_res, w, h, frame=frame)
            if settlement["isSettlement"]:
                actual_total = settlement.get("actualTotal")
                self._match_exit_hold = 0
                self._had_settlement = True
                self.current_context["scene"] = SCENE_SETTLEMENT
                self.current_context["sceneLabel"] = SCENE_LABELS[SCENE_SETTLEMENT]
                self.current_context["auctionEntryVisible"] = False
                self.current_context["isSettlement"] = True
                self.current_context["inAuction"] = True
                self.current_context["inLobby"] = False
                self.current_context["isLoading"] = False
                self.current_context["hadSettlement"] = True
                self.current_context["loadingDirection"] = "to_lobby"
                if settlement.get("winner"):
                    self.current_context["winner"] = settlement.get("winner")
                    self.current_context["settlementWinnerName"] = settlement.get("winner")
                elif self.current_context.get("winner"):
                    settlement["winner"] = self.current_context.get("winner")
                    self.current_context["settlementWinnerName"] = self.current_context.get("winner")
                if settlement.get("auctionAssistant"):
                    self.current_context["auctionAssistant"] = settlement.get("auctionAssistant")
                    self.current_context["settlementAuctionAssistantName"] = settlement.get("auctionAssistant")
                if settlement.get("isSelfWinner") is not None:
                    self.current_context["isSelfWinner"] = settlement.get("isSelfWinner")
                acquired = self._acquisition_names.observe_winner(
                    settlement.get("winner"), settlement.get("winnerConfidence", 0),
                    settlement.get("winnerAmbiguous", False), self._acquisition_frame)
                settlement["acquired"] = acquired
                self.current_context["isAcquired"] = acquired
                if settlement.get("clearingPrice") is not None:
                    self.current_context["clearingPrice"] = settlement.get("clearingPrice")
                if settlement.get("actualTotal") is not None:
                    self.current_context["actualTotal"] = settlement.get("actualTotal")
                if settlement.get("profit") is not None:
                    self.current_context["realizedProfit"] = settlement.get("profit")
                if settlement.get("welfareReceived") is not None:
                    self.current_context["welfareReceived"] = settlement.get("welfareReceived")
                self.current_context["settlementData"] = settlement

                if include_heavy_identity:
                    self._attach_settlement_ledger(
                        settlement, frame=frame, captured_at=captured_at, actual_total=actual_total
                    )
                else:
                    self._pending_heavy_identity = {
                        "kind": "settlement",
                        "frame": frame,
                        "captured_at": captured_at,
                        "actual_total": actual_total,
                        "round": self.current_context.get("round"),
                        "scene": SCENE_SETTLEMENT,
                        "matchGeneration": self._match_gen,
                        "sessionGeneration": self._session_generation,
                    }
                    self._stabilize_settlement(settlement, frame=frame, captured_at=captured_at)
                # Settlement returns before the in-auction warehouse block.
                # Do not let an early observation leak into a later frame.
                self._take_prepared_warehouse_frame(frame)
                return self.current_context

            # 3. 对局加载/匹配过渡界面
            loading_info = self._parse_loading(mapped_res, w, h)
            if loading_info["isLoading"]:
                self._match_exit_hold = 0
                self.current_context["scene"] = SCENE_AUCTION_LOADING
                self.current_context["sceneLabel"] = SCENE_LABELS[SCENE_AUCTION_LOADING]
                self.current_context["auctionEntryVisible"] = False
                self.current_context["isLoading"] = True
                self.current_context["inLobby"] = False
                self.current_context["inAuction"] = False
                self.current_context["isSettlement"] = False
                self.current_context["round"] = 0
                self.current_context["loadingPercent"] = loading_info["percent"] if loading_info["percent"] is not None else 100
                self.current_context["loadingVenue"] = loading_info.get("venue")
                direction = "to_lobby" if self._had_settlement else "to_auction"
                self.current_context["loadingDirection"] = direction
                self.current_context["hadSettlement"] = self._had_settlement
                if direction == "to_lobby":
                    self._end_match_on_lobby_or_egress()
                return self.current_context
            else:
                self.current_context["isLoading"] = False

            # 遍历 OCR 提取各个区域 (Round, Intel, Fallbacks)
            for box, text, score in mapped_res:
                x_min = min(b[0] for b in box)
                y_min = min(b[1] for b in box)
                nx = x_min / w
                ny = y_min / h

                # A. 回合识别
                m_round = re.search(r"(?:竞拍)?第\s*(\d)\s*回[合回合]", text)
                if not m_round:
                    m_round = re.search(r"第\s*(\d)\s*回合", text)
                if m_round:
                    self.current_context["round"] = int(m_round.group(1))
                    detected_feature = True
                elif "公开情报" in text or "千眼其一" in text:
                    detected_feature = True

                # B. 倒计时候选 (仅 fallback 用)
                m_timer = re.search(r"00[:：](\d{2})", text)
                if m_timer:
                    full_canvas_timer = int(m_timer.group(1))
                    detected_feature = True

                # C. 品质均价与全场均价
                m_gold_avg = re.search(r"(?:金色|金品|金色品质)[^\d]{0,15}(?:平均价值|均价)为?\s*([\d,，.．、]+)", text)
                m_purple_avg = re.search(r"(?:紫色|紫品|紫色品质)[^\d]{0,15}(?:平均价值|均价)为?\s*([\d,，.．、]+)", text)
                m_blue_avg = re.search(r"(?:蓝色|蓝品|蓝色品质)[^\d]{0,15}(?:平均价值|均价)为?\s*([\d,，.．、]+)", text)
                m_green_avg = re.search(r"(?:绿色|绿品|绿色品质)[^\d]{0,15}(?:平均价值|均价)为?\s*([\d,，.．、]+)", text)
                m_white_avg = re.search(r"(?:白色|白品|白色品质)[^\d]{0,15}(?:平均价值|均价)为?\s*([\d,，.．、]+)", text)
                m_red_avg = re.search(r"(?:红色|红品|红色品质)[^\d]{0,15}(?:平均价值|均价)为?\s*([\d,，.．、]+)", text)

                if m_gold_avg:
                    avg_val = parse_money_amount(m_gold_avg.group(1))
                    if avg_val >= 1000:
                        self.current_context["goldAvg"] = avg_val
                        detected_feature = True
                elif m_purple_avg:
                    avg_val = parse_money_amount(m_purple_avg.group(1))
                    if avg_val >= 1000:
                        self.current_context["purpleAvg"] = avg_val
                        detected_feature = True
                elif m_blue_avg:
                    avg_val = parse_money_amount(m_blue_avg.group(1))
                    if avg_val >= 1000:
                        self.current_context["blueAvg"] = avg_val
                        detected_feature = True
                elif m_green_avg:
                    avg_val = parse_money_amount(m_green_avg.group(1))
                    if avg_val >= 1000:
                        self.current_context["greenAvg"] = avg_val
                        detected_feature = True
                elif m_white_avg:
                    avg_val = parse_money_amount(m_white_avg.group(1))
                    if avg_val >= 1000:
                        self.current_context["whiteAvg"] = avg_val
                        detected_feature = True
                elif m_red_avg:
                    avg_val = parse_money_amount(m_red_avg.group(1))
                    if avg_val >= 1000:
                        self.current_context["redAvg"] = avg_val
                        detected_feature = True
                else:
                    m_gen_avg = re.search(r"平均价值为\s*([\d,，.．、]+)", text)
                    if m_gen_avg and not any(k in text for k in ["金色", "金品", "紫色", "紫品", "蓝色", "蓝品", "绿色", "绿品", "白色", "白品", "红色", "红品"]):
                        avg_val = parse_money_amount(m_gen_avg.group(1))
                        if avg_val >= 1000:
                            if self.current_context.get("avg") is None:
                                self.current_context["avg"] = avg_val
                            detected_feature = True

                # C2. 当前估价候选 (仅 fallback 用)
                m_est = re.search(r"当前估价[：:]\s*([\d,，.．、]+)", text)
                if m_est:
                    est_val = parse_money_amount(m_est.group(1))
                    if est_val >= 1000:
                        full_canvas_est = est_val
                        detected_feature = True
                elif "当前估价" in text:
                    nearby = []
                    for nbox, ntext, _ in mapped_res:
                        nx2 = min(p[0] for p in nbox) / w
                        ny2 = min(p[1] for p in nbox) / h
                        if abs(ny2 - ny) <= 0.04 and 0 <= (nx2 - nx) <= 0.18:
                            nearby.append(parse_money_amount(ntext))
                    est_val = next((v for v in nearby if v >= 1000), 0)
                    if est_val:
                        full_canvas_est = est_val
                        detected_feature = True

                # D. 全局全场总件数
                m_total_items = re.search(r"(?:本局内?)?所有藏品的总数量为\s*(\d+)件?", text)
                if m_total_items:
                    self.current_context["totalItems"] = int(m_total_items.group(1))
                    detected_feature = True

                # D2. 千眼其一 Q 值
                m_q = re.search(r"(?:本局内?)?(?:紫色[，,]金色和红色品质)?(?:藏品)?的总件数为\s*(\d+)件?", text)
                if not m_q:
                    m_q = re.search(r"(?:总件数|件数|想件数)为\s*(\d+)", text)
                if m_q:
                    self.current_context["q"] = int(m_q.group(1))
                    detected_feature = True

                # D3. 品质计数仪器
                m_purple = re.search(r"(?:紫色品质藏品的总数量为|紫色[^\d]{0,12}总数量为)\s*(\d+)", text)
                if m_purple:
                    cnt = int(m_purple.group(1))
                    self.current_context["purple"] = cnt
                    self.current_context["purpleCount"] = cnt
                    detected_feature = True

                m_blue_cnt = re.search(r"(?:蓝色品质藏品的总数量为|蓝色[^\d]{0,12}总数量为)\s*(\d+)", text)
                if m_blue_cnt:
                    self.current_context["blueCount"] = int(m_blue_cnt.group(1))
                    detected_feature = True

                m_gold_cnt = re.search(r"(?:金色品质藏品的总数量为|金色[^\d]{0,12}总数量为)\s*(\d+)", text)
                if m_gold_cnt:
                    self.current_context["goldCount"] = int(m_gold_cnt.group(1))
                    detected_feature = True

                m_green_cnt = re.search(r"(?:绿色品质藏品的总数量为|绿色[^\d]{0,12}总数量为)\s*(\d+)", text)
                if m_green_cnt:
                    self.current_context["greenCount"] = int(m_green_cnt.group(1))
                    detected_feature = True

                m_white_cnt = re.search(r"(?:白色品质藏品的总数量为|白色[^\d]{0,12}总数量为)\s*(\d+)", text)
                if m_white_cnt:
                    self.current_context["whiteCount"] = int(m_white_cnt.group(1))
                    detected_feature = True

                m_red_cnt = re.search(r"(?:红色品质藏品的总数量为|红色[^\d]{0,12}总数量为)\s*(\d+)", text)
                if m_red_cnt:
                    self.current_context["redCount"] = int(m_red_cnt.group(1))
                    detected_feature = True

                # E. 总格数与品质占格数
                m_grids = re.search(r"总格数为\s*(\d+)", text)
                if m_grids:
                    self.current_context["totalGrids"] = int(m_grids.group(1))
                    detected_feature = True

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
                        self.current_context[q_key] = int(m_q_grid.group(1))
                        detected_feature = True

                # F/G. 场地条件与箱型
                hit = extract_from_text(text)
                if hit.get("fieldCondition"):
                    self.current_context["fieldCondition"] = hit["fieldCondition"]
                    detected_feature = True
                if hit.get("box"):
                    box_hits = set()
                    for _, piece, _ in mapped_res:
                        piece_hit = extract_from_text(piece or "")
                        if piece_hit.get("box") and "未知" not in str(piece_hit.get("box")):
                            box_hits.add(piece_hit["box"])
                    spinning = len(box_hits) >= 2
                    stable_box = (
                        self.current_context.get("round", 0) > 0
                        or self.current_context.get("scene") == SCENE_IN_AUCTION
                        or detected_feature
                    )
                    if stable_box and not spinning:
                        self.current_context["box"] = hit["box"]
                        self.current_context["boxType"] = None
                        detected_feature = True

            self.current_context["inAuction"] = detected_feature or (self.current_context["round"] > 0)
            if self.current_context["inAuction"]:
                self._match_exit_hold = 0
                self.current_context["inLobby"] = False
                self.current_context["isLoading"] = False
                if not self.current_context.get("isSettlement"):
                    self.current_context["scene"] = SCENE_IN_AUCTION
                    self.current_context["sceneLabel"] = SCENE_LABELS[SCENE_IN_AUCTION]
                    self.current_context["auctionEntryVisible"] = False
                    if not self._match_active:
                        self._match_active = True
                        self._match_gen += 1
                        self.current_context["matchGeneration"] = self._match_gen
                    self._had_settlement = False
                    self.current_context["hadSettlement"] = False
                    self.current_context["loadingDirection"] = None
            elif self.current_context.get("scene") in LOCKED_MATCH_SCENES:
                if self._try_release_locked_match(fast):
                    return self.current_context
            else:
                self._hold_nav_or_clear()

            opening_facts_found = bool(
                self.current_context.get("goldAvg") is not None
                or self.current_context.get("q") is not None
                or (self.current_context.get("round", 0) > 0 and self.current_context.get("box"))
            )
            if use_focused_opening and opening_facts_found and not getattr(self, "_opening_seat_deferred", False):
                self._opening_seat_deferred = True
                self._defer_seat_heavy_once = True

        # =========================================================================
        # Fast ROI Tier (Runs on EVERY frame - with fresh round if full-scan, or sticky round if skip)
        # =========================================================================
        # 1. seats_bids_panel: DF Authority + Metadata Refresh Gate (4D2D1L-L3Z.7)
        # A skipped full scan can retain SETTLEMENT for several frames. Its
        # labels occupy the old seat panel, so keep the last auction identities.
        is_auction_scene = (
            self.current_context.get("scene") == SCENE_IN_AUCTION
            and not self.current_context.get("isSettlement")
        )
        panel_bound = True
        if is_auction_scene:
            panel_bound = self._handle_seat_binding_tier(
                frame,
                w,
                h,
                df_seat_bids,
                df_seat_success,
                bid_panel_changed=priority_seat_panel_changed if prioritize_live_facts else None,
                bid_panel_signature=priority_seat_panel_signature if prioritize_live_facts else None,
            )

        if not panel_bound:
            # Full-canvas fallback: if DF/panel binding failed
            if not mapped_res:
                rx1, ry1, rx2, ry2 = ROIScaler.scale_roi("auction_main_canvas", w, h)
                roi = frame[ry1:ry2, rx1:rx2]
                res_fb, _ = self.ocr(roi)
                self.ocr_call_count += 1
                if res_fb:
                    mapped_res = [([[b[0] + rx1, b[1] + ry1] for b in box], text, score) for box, text, score in res_fb]
            if mapped_res:
                self._bind_horizontal_seats(mapped_res, w, h)
                self._refresh_leader_from_seats()

        if is_auction_scene and df_est is None and df_timer is None and self._df_shadow_batch_count == 0:
            try:
                df_est, df_timer = self._read_df_numeric_batch(frame)
                if df_timer is not None:
                    roi_timer = df_timer
            except Exception:
                df_est = None
                df_timer = None
        if is_auction_scene and not df_seat_success and self._df_shadow_seat_bids_batch_count == 0:
            try:
                df_seat_bids = self._run_df_seat_bids_shadow(frame)
                df_seat_success = any(value is not None for value in df_seat_bids)
                if df_seat_success:
                    self._update_seat_current_bids_from_df(
                        df_seat_bids, int(self.current_context.get("round") or 0),
                        trusted_slots=self._trusted_df_bid_slots(df_seat_bids),
                    )
                    self._derive_seat_leader_and_context(int(self.current_context.get("round") or 0), self._slot_cur_bids)
            except Exception:
                self._df_shadow_seat_bids = [None, None, None, None]

        if is_auction_scene and roi_timer is None and df_timer is None:
            if full_canvas_timer is not None:
                roi_timer = full_canvas_timer
            elif not should_run_full_canvas:
                roi_timer = self._parse_header_timer_roi(frame)

        # 2. current_estimate_chip: Detection-Free Authority with legacy heavy ROI fallback (4D2D1L-L3W)
        if is_auction_scene:
            if df_est is not None and df_est >= 1000:
                roi_est = df_est
            elif full_canvas_est is not None and full_canvas_est >= 1000:
                roi_est = full_canvas_est
            elif not should_run_full_canvas:
                roi_est = None if prioritize_live_facts else self._parse_current_estimate_chip(frame)
            else:
                roi_est = None
        else:
            roi_est = None

        # =========================================================================
        # 4. Authoritative Assignment & Fallback (Strictly NO Stale Overwrite!)
        # =========================================================================
        if self.current_context.get("scene") == SCENE_IN_AUCTION or self.current_context.get("inAuction"):
            # CurrentEstimate (N=2 candidate confirmation gate - 4D2D1M-C2.26)
            raw_est = None
            if roi_est is not None and roi_est >= 1000:
                raw_est = roi_est
            elif full_canvas_est and full_canvas_est >= 1000:
                raw_est = full_canvas_est

            if prioritize_live_facts and raw_est is None:
                # No estimate was observed on this frame. Do not restamp a
                # previously confirmed value with the newer frame timestamp.
                self._apply_estimate_observation(None)
                self.current_context["currentEstimate"] = None
            else:
                self.current_context["currentEstimate"] = self._apply_estimate_observation(raw_est)

            # Timer
            if roi_timer is not None:
                self.current_context["timer"] = roi_timer
            elif full_canvas_timer is not None:
                self.current_context["timer"] = full_canvas_timer
        else:
            # Prohibit ROI estimates/timers in non-auction scenes
            if full_canvas_est and full_canvas_est >= 1000:
                self.current_context["currentEstimate"] = self._apply_estimate_observation(full_canvas_est)
            else:
                self.current_context["currentEstimate"] = self._confirmed_estimate
            if full_canvas_timer is not None:
                self.current_context["timer"] = full_canvas_timer

        # 5. 记录 1~5 回合全时序复盘快照 (Round Timeline)
        cur_round = self.current_context["round"]
        round_key = str(cur_round)
        
        round_snapshot = {
            "round": cur_round,
            "timer": self.current_context["timer"],
            "intel": {
                "q": self.current_context["q"],
                "avg": self.current_context["avg"],
                "goldAvg": self.current_context.get("goldAvg"),
                "totalGrids": self.current_context["totalGrids"],
                "condition": self.current_context["fieldCondition"],
                "box": self.current_context.get("box"),
            },
            "bids": {
                "myBid": self.current_context["myBid"],
                "myName": self.current_context["myName"],
                "leaderBid": self.current_context["currentLeaderBid"],
                "leaderName": self.current_context["leaderName"],
                "leaderTies": list(self.current_context.get("leaderTies") or []),
                "finalBids": self._round_final_bids(cur_round),
                "isMyLead": self.current_context["isMyLead"],
                "opponents": [dict(o) for o in self.current_context["opponents"]]
            }
        }

        if round_key not in self.current_context["roundTimeline"]:
            self.current_context["roundTimeline"][round_key] = round_snapshot
        else:
            # 持续更新当前回合更丰富的情报与出价
            existing = self.current_context["roundTimeline"][round_key]
            existing["timer"] = self.current_context["timer"]
            if self.current_context["q"]: existing["intel"]["q"] = self.current_context["q"]
            if self.current_context["avg"]: existing["intel"]["avg"] = self.current_context["avg"]
            if self.current_context.get("goldAvg") is not None: existing["intel"]["goldAvg"] = self.current_context.get("goldAvg")
            if self.current_context["totalGrids"]: existing["intel"]["totalGrids"] = self.current_context["totalGrids"]
            
            if self.current_context.get("myBid") is not None:
                existing["bids"]["myBid"] = self.current_context["myBid"]
            existing["bids"]["leaderBid"] = self.current_context["currentLeaderBid"]
            existing["bids"]["leaderName"] = self.current_context["leaderName"]
            existing["bids"]["leaderTies"] = list(self.current_context.get("leaderTies") or [])
            existing["bids"]["finalBids"] = self._round_final_bids(cur_round)
            existing["bids"]["isMyLead"] = self.current_context["isMyLead"]
            existing["bids"]["opponents"] = [dict(o) for o in self.current_context["opponents"]]
            existing["intel"]["condition"] = self.current_context.get("fieldCondition")
            existing["intel"]["box"] = self.current_context.get("box")
            if self.current_context.get("purple") is not None:
                existing["intel"]["purple"] = self.current_context.get("purple")

        # 6. 右侧物理仓库网格高置信证据分层感知 (Warehouse Vision v1)
        is_in_auction = (
            self.current_context.get("scene") == SCENE_IN_AUCTION
            and not self.current_context.get("isSettlement", False)
            and self.current_context.get("round", 0) > 0
        )
        board_ready = False
        if is_in_auction:
            rx1, ry1, rx2, ry2 = ROIScaler.scale_roi("warehouse_board", w, h)
            wh_crop = frame[ry1:max(ry1 + 1, ry2), rx1:max(rx1 + 1, rx2)]
            if wh_crop.size > 0:
                gray = cv2.cvtColor(wh_crop, cv2.COLOR_BGR2GRAY)
                edges = cv2.Canny(gray, 30, 90)
                edge_density = float((edges > 0).mean())
                board_ready = edge_density >= 0.035

        if is_in_auction and board_ready:
            if include_heavy_identity:
                wh_state = self._take_prepared_warehouse_frame(frame)
                if wh_state is None:
                    wh_state = self.warehouse_vision.process_frame(frame)
                self._apply_warehouse_state(wh_state)
            else:
                self._pending_heavy_identity = {
                    "kind": "warehouse",
                    "frame": frame,
                    "captured_at": captured_at,
                    "round": self.current_context.get("round"),
                    "scene": SCENE_IN_AUCTION,
                    "matchGeneration": self._match_gen,
                    "sessionGeneration": self._session_generation,
                }
        else:
            if self._warehouse_vision is not None:
                self._warehouse_vision.reset()
            self._apply_warehouse_state({"slots": [], "totalExpectedVal": 0, "valRange": [0, 0]})

        # 7. Intel Card Observation Payload & Ledger State (4D2D1M-C2 / C2.25W)
        if hasattr(self, "_latest_intel_evidence") and self._latest_intel_evidence is not None:
            self.current_context["intelEvidence"] = self._latest_intel_evidence.to_dict()
            self.current_context["intelObservations"] = [obs.to_dict() for obs in self._latest_intel_evidence.observations]
            self.current_context["intelCardReadings"] = self._latest_intel_evidence.to_dict().get('cardReadings', [])
            self.current_context["intelEvidenceSummary"] = {
                "round": self._latest_intel_evidence.round,
                "timer": self._latest_intel_evidence.timer,
                "cardsCount": len(self._latest_intel_evidence.cards),
                "fields": self._latest_intel_evidence.field_map(),
            }
        else:
            self.current_context["intelEvidence"] = None
            self.current_context["intelObservations"] = []
            self.current_context["intelCardReadings"] = []
            self.current_context["intelEvidenceSummary"] = None

        if hasattr(self, "_intel_ledger") and self._intel_ledger is not None:
            ledger_snap = self._intel_ledger.merge()
            facts = ledger_snap.get("facts")
            self.current_context["intelFacts"] = facts
            self.current_context['publicCardEvents'] = ledger_snap.get('publicCardEvents', [])
            self._apply_confirmed_intel_facts(facts)
        else:
            self.current_context["intelFacts"] = None
            self.current_context['publicCardEvents'] = []

        return self.current_context

    def _read_df_numeric_batch(
        self,
        frame: Optional[np.ndarray],
        *,
        include_estimate: bool = True,
        precomputed_results: Optional[List[Any]] = None,
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Detection-Free 2-field recognition batch for estimate and timer authority (4D2D1L-L3W).
        Runs strictly when scene == IN_AUCTION.
        Executes exactly 1 batch call (2 text crops) per auction frame.
        Results serve as primary authority, with legacy heavy ROI as fallback.
        """
        if frame is None or getattr(frame, "size", 0) == 0:
            self._df_shadow_estimate = None
            self._df_shadow_timer = None
            return None, None

        self._ensure_ocr()
        if not self._ocr_engine or not hasattr(self._ocr_engine, "text_rec"):
            return None, None

        h, w = frame.shape[:2]

        crop_est = None
        if include_estimate:
            # Current estimate is optional in the low-latency live path.
            ex1, ey1, ex2, ey2 = ROIScaler.scale_roi("current_estimate_digits", w, h)
            crop_est = frame[ey1:ey2, ex1:ex2]

        # Timer Numeric (0.483, 0.055, 0.525, 0.090)
        tx1, ty1, tx2, ty2 = int(w * 0.483), int(h * 0.055), int(w * 0.525), int(h * 0.090)
        crop_timer = frame[ty1:ty2, tx1:tx2]

        if (include_estimate and (crop_est is None or crop_est.size == 0)) or crop_timer.size == 0:
            self._df_shadow_estimate = None
            self._df_shadow_timer = None
            return None, None

        if precomputed_results is None:
            crops = [crop_est, crop_timer] if include_estimate else [crop_timer]
            batch_res, _ = self._ocr_engine.text_rec(crops)
        else:
            batch_res = precomputed_results
        self._df_shadow_batch_count += 1

        expected_results = 2 if include_estimate else 1
        if not batch_res or len(batch_res) < expected_results:
            self._df_shadow_estimate = None
            self._df_shadow_timer = None
            return None, None

        if include_estimate:
            raw_est, conf_est = batch_res[0]
            raw_timer, conf_timer = batch_res[1]
        else:
            raw_est, conf_est = None, 0.0
            raw_timer, conf_timer = batch_res[0]

        self._df_shadow_raw_text = {"estimate": raw_est, "timer": raw_timer}
        self._df_shadow_conf = {"estimate": float(conf_est or 0.0), "timer": float(conf_timer or 0.0)}

        # Parse Estimate (minimum 4 digits >= 1000)
        parsed_est = None
        if raw_est:
            val_est = parse_money_amount(raw_est, min_digits=4)
            if val_est >= 1000:
                parsed_est = val_est
        self._df_shadow_estimate = parsed_est

        # Parse Timer (0..99)
        parsed_timer = None
        if raw_timer:
            cleaned_timer = str(raw_timer).strip().replace("：", ":")
            m_t = re.search(r"(?:00[:：])?(\d{1,2})$", cleaned_timer)
            if m_t:
                val_t = int(m_t.group(1))
                if 0 <= val_t <= 99:
                    parsed_timer = val_t
            if parsed_timer is None:
                m_t2 = re.search(r"(\d{2})", cleaned_timer)
                if m_t2:
                    val_t2 = int(m_t2.group(1))
                    if 0 <= val_t2 <= 99:
                        parsed_timer = val_t2
        self._df_shadow_timer = parsed_timer

        return parsed_est, parsed_timer

    def _run_df_seat_bids_shadow(
        self,
        frame: Optional[np.ndarray],
        *,
        precomputed_results: Optional[List[Any]] = None,
    ) -> List[Optional[int]]:
        """
        Detection-Free 4-slot recognition shadow for seat current bids (4D2D1L-L3Z.2).
        Runs strictly when scene == IN_AUCTION.
        Executes exactly 1 batch call (4 text crops) per auction frame.
        Keeps raw OCR and confidence for the current-round seat projection.
        """
        if frame is None or getattr(frame, "size", 0) == 0:
            self._df_shadow_seat_bids = [None, None, None, None]
            self._df_shadow_seat_bids_raw_text = ["", "", "", ""]
            self._df_shadow_seat_bids_conf = [0.0, 0.0, 0.0, 0.0]
            return [None, None, None, None]

        self._ensure_ocr()
        if not self._ocr_engine or not hasattr(self._ocr_engine, "text_rec"):
            self._df_shadow_seat_bids = [None, None, None, None]
            self._df_shadow_seat_bids_raw_text = ["", "", "", ""]
            self._df_shadow_seat_bids_conf = [0.0, 0.0, 0.0, 0.0]
            return [None, None, None, None]

        if precomputed_results is None:
            h, w = frame.shape[:2]
            # Share the same viewport compensation as the full seats panel.
            crops = [ROIScaler.crop_roi(frame, f"seat_current_bid_{slot}") for slot in (1, 2, 3, 4)]

            if any(c.size == 0 for c in crops):
                self._df_shadow_seat_bids = [None, None, None, None]
                return [None, None, None, None]

            from bid_glyph_crop import compact_bid_glyph
            for index, crop in enumerate(crops):
                compact = compact_bid_glyph(crop)
                if compact is not None:
                    crops[index] = compact

            # Exactly 1 four-slot batch recognition call
            batch_res, _ = self._ocr_engine.text_rec(crops)
        else:
            batch_res = precomputed_results
        self._df_shadow_seat_bids_batch_count += 1

        parsed_bids: List[Optional[int]] = [None, None, None, None]
        raw_texts: List[str] = ["", "", "", ""]
        confs: List[float] = [0.0, 0.0, 0.0, 0.0]

        if batch_res:
            for i in range(min(4, len(batch_res))):
                item = batch_res[i]
                if not item:
                    continue
                raw, conf = item
                raw_str = str(raw or "")
                conf_flt = float(conf or 0.0)
                raw_texts[i] = raw_str
                confs[i] = conf_flt

                # Strict fail-closed semantic parsing (4D2D1L-L3Z.4: Whole-token numeric structure matching)
                if not raw_str or conf_flt < 0.40:
                    parsed_bids[i] = None
                    continue

                token = raw_str.strip().replace("，", ",").replace("．", ",").replace(".", ",").replace("、", ",").replace(" ", "")
                if not token:
                    parsed_bids[i] = None
                    continue

                # Explicit zero glyph check: token == "0"
                if token == "0":
                    parsed_bids[i] = 0 if conf_flt >= 0.70 else None
                    continue

                # Validate whole-token positive integer format:
                # 1) Standard thousands-grouped: e.g. 5,000 / 90,000 / 116,999 / 400,000 / 500,000 / 666,666
                # 2) Pure unsigned integer: e.g. 5000 / 90000 / 666666
                is_thousands = bool(re.fullmatch(r"\d{1,3}(?:,\d{3})+", token))
                is_pure_digits = bool(re.fullmatch(r"\d+", token))

                if not (is_thousands or is_pure_digits):
                    # Reject any mixed text, letters, Chinese characters, unit suffixes (5K), malformed commas (5,00)
                    parsed_bids[i] = None
                    continue

                digits = token.replace(",", "")
                val = int(digits)
                parsed_bids[i] = val if conf_flt >= 0.60 else None

        self._df_shadow_seat_bids = parsed_bids
        self._df_shadow_seat_bids_raw_text = raw_texts
        self._df_shadow_seat_bids_conf = confs
        return parsed_bids

    def _run_df_numeric_shadow(self, frame: Optional[np.ndarray]) -> None:
        """Backward-compatible helper calling _read_df_numeric_batch."""
        self._read_df_numeric_batch(frame)

    def _read_df_auction_round_title(self, frame: Optional[np.ndarray]) -> Optional[int]:
        """Accept only a high-confidence, whole-token visible auction title."""
        if frame is None or getattr(frame, "size", 0) == 0:
            return None
        self._ensure_ocr()
        if not self._ocr_engine or not hasattr(self._ocr_engine, "text_rec"):
            return None
        crop = ROIScaler.crop_roi(frame, "auction_round_title")
        if crop.size == 0:
            return None
        try:
            rows, _ = self._ocr_engine.text_rec([crop])
            if not rows or not rows[0]:
                return None
            raw, confidence = rows[0]
            if float(confidence or 0.0) < 0.90:
                return None
            match = re.fullmatch(r"竞拍第([1-5])回合", re.sub(r"\s+", "", str(raw or "")))
            return int(match.group(1)) if match else None
        except Exception:
            return None

    def _read_shadow_header_round_timer(self, frame: Optional[np.ndarray]) -> Dict[str, Any]:
        """Shadow dual-read of header_round_timer small ROI for diagnostics/testing without mutating production authority."""
        result: Dict[str, Any] = {
            "shadowRound": None,
            "shadowTimer": None,
            "rawText": "",
            "error": None,
        }
        if frame is None or getattr(frame, "size", 0) == 0:
            return result
        try:
            h, w = frame.shape[:2]
            hx1, hy1, hx2, hy2 = ROIScaler.scale_roi("header_round_timer", w, h)
            header_crop = frame[hy1:hy2, hx1:hx2]
            if header_crop.size > 0:
                header_res, _ = self.ocr(header_crop)
                if header_res:
                    texts = [str(t or "").strip() for _, t, _ in header_res if t]
                    raw_text = " ".join(texts)
                    result["rawText"] = raw_text

                    m_round = re.search(r"(?:竞拍)?第\s*(\d)\s*回[合回合]", raw_text)
                    if not m_round:
                        m_round = re.search(r"第\s*(\d)\s*回合", raw_text)
                    if m_round:
                        val = int(m_round.group(1))
                        if 1 <= val <= 5:
                            result["shadowRound"] = val

                    m_timer = re.search(r"00[:：](\d{2})", raw_text)
                    if m_timer:
                        result["shadowTimer"] = int(m_timer.group(1))
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    def _parse_header_timer_roi(self, frame: Optional[np.ndarray]) -> Optional[int]:
        """
        Authoritative parser for header_round_timer ROI (4D2D1L-L3M).
        Only active in IN_AUCTION scene. Returns integer timer (0..99) or None.
        Does NOT parse or modify round.
        """
        if frame is None or getattr(frame, "size", 0) == 0:
            return None
        try:
            h, w = frame.shape[:2]
            hx1, hy1, hx2, hy2 = ROIScaler.scale_roi("header_round_timer", w, h)
            header_crop = frame[hy1:hy2, hx1:hx2]
            if header_crop.size > 0:
                header_res, _ = self.ocr(header_crop)
                if header_res:
                    texts = [str(t or "").strip() for _, t, _ in header_res if t]
                    raw_text = " ".join(texts)
                    m_timer = re.search(r"00[:：](\d{2})", raw_text)
                    if m_timer:
                        val = int(m_timer.group(1))
                        if 0 <= val <= 99:
                            return val
        except Exception:
            pass
        return None

    def _parse_current_estimate_chip(self, frame: Optional[np.ndarray]) -> Optional[int]:
        """
        Authoritative parser for current_estimate_chip ROI (4D2D1L-L3L).
        Only active in IN_AUCTION scene. Returns integer estimate >= 1000 or None.
        """
        if frame is None or getattr(frame, "size", 0) == 0:
            return None
        try:
            h, w = frame.shape[:2]
            ex1, ey1, ex2, ey2 = ROIScaler.scale_roi("current_estimate_chip", w, h)
            est_crop = frame[ey1:ey2, ex1:ex2]
            if est_crop.size > 0:
                est_res, _ = self.ocr(est_crop)
                if est_res:
                    texts = [str(t or "").strip() for _, t, _ in est_res if t]
                    raw_text = " ".join(texts)
                    m_est = re.search(r"(?:当前)?估价[：:]?\s*([\d,，.．、]+)", raw_text)
                    if m_est:
                        val = parse_money_amount(m_est.group(1))
                        if val >= 1000:
                            return val
                    elif any(k in raw_text for k in ("当前估价", "估价")):
                        for _, piece_text, _ in est_res:
                            piece_val = parse_money_amount(piece_text)
                            if piece_val >= 1000:
                                return piece_val
        except Exception:
            pass
        return None

    def _read_shadow_current_estimate(self, frame: Optional[np.ndarray]) -> Dict[str, Any]:
        """Shadow dual-read of current_estimate_chip small ROI for diagnostics/testing without mutating production authority."""
        result: Dict[str, Any] = {
            "shadowCurrentEstimate": None,
            "rawText": "",
            "error": None,
        }
        if frame is None or getattr(frame, "size", 0) == 0:
            return result
        try:
            h, w = frame.shape[:2]
            ex1, ey1, ex2, ey2 = ROIScaler.scale_roi("current_estimate_chip", w, h)
            est_crop = frame[ey1:ey2, ex1:ex2]
            if est_crop.size > 0:
                est_res, _ = self.ocr(est_crop)
                if est_res:
                    texts = [str(t or "").strip() for _, t, _ in est_res if t]
                    raw_text = " ".join(texts)
                    result["rawText"] = raw_text

                    # 1. 尝试直接从单 box 或整段文本中匹配「当前估价：123,456」
                    m_est = re.search(r"(?:当前)?估价[：:]?\s*([\d,，.．、]+)", raw_text)
                    if m_est:
                        val = parse_money_amount(m_est.group(1))
                        if val >= 1000:
                            result["shadowCurrentEstimate"] = val
                    elif any(k in raw_text for k in ("当前估价", "估价")):
                        # 2. 如果标签与数字分词在不同 box，提取带有估价标签附近的金额数字
                        for _, piece_text, _ in est_res:
                            piece_val = parse_money_amount(piece_text)
                            if piece_val >= 1000:
                                result["shadowCurrentEstimate"] = piece_val
                                break
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    def _bind_horizontal_seats_isolated(
        self,
        ocr_results: List[Any],
        screen_w: int,
        screen_h: int,
        base_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Isolated seats/bids binder that executes in a sandbox dict without mutating production state."""
        bands = (
            (0.14, 0.29),
            (0.29, 0.44),
            (0.44, 0.58),
            (0.58, 0.74),
        )
        seats = self._empty_seats()
        prev_seats = base_context.get("seats") or []
        for i, prev in enumerate(prev_seats[:4]):
            if prev.get("name"):
                seats[i]["name"] = prev.get("name")
        skip = {"esc", "nte", "ul", "uid", "enter", "menu"}
        finals = self._final_bids_from_history(base_context.get("finalBids") or base_context.get("historicalBids"))
        cur_round = int(base_context.get("round") or 0)

        pending_hist: List[Tuple[int, int, int]] = []
        hist_xs: List[float] = []
        raw_items = []
        for box, text, _ in ocr_results:
            raw = re.sub(r"\s+", "", text or "")
            if not raw:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            nx = min(xs) / max(1, screen_w)
            ny = ((min(ys) + max(ys)) / 2.0) / max(1, screen_h)
            nh = (max(ys) - min(ys)) / max(1, screen_h)
            nw = (max(xs) - min(xs)) / max(1, screen_w)
            raw_items.append((nx, ny, nh, nw, raw))

            leftover = re.sub(r"[\d,，.．、KkWwMm万千%'\"`’]", "", raw)
            if leftover:
                continue
            tokens = self._split_hist_tokens(raw)
            if not tokens:
                continue
            compact_up = raw.upper().replace("万", "W")
            if re.search(r"[KWM]", compact_up) or nh <= 0.028:
                hist_xs.append(nx)

        hist_origin = min(hist_xs) if hist_xs else None

        for nx, ny, nh, nw, compact in raw_items:
            if nx < 0.02 or nx > 0.30 or ny < 0.12 or ny > 0.78:
                continue
            idx = next((i for i, (lo, hi) in enumerate(bands) if lo <= ny < hi), None)
            if idx is None:
                continue

            non_numeric = re.sub(r"[\d,，.．、KkWwMm万千%'\"`’.\-]", "", compact)
            has_chinese_name = bool(re.search(r"[\u4e00-\u9fa5]", non_numeric))

            tokens = self._split_hist_tokens(compact)
            leftover = re.sub(r"[\d,，.．、KkWwMm万千%'\"`’]", "", compact)
            numeric_like = bool(tokens) and not leftover and not has_chinese_name

            if numeric_like:
                compact_up = compact.upper().replace("万", "W")
                glued = len(tokens) >= 2
                is_hist_unit = bool(re.search(r"[KWM]", compact_up))
                is_history = glued or is_hist_unit or nh <= 0.028 or (nw >= 0.055 and nh <= 0.025)

                if is_history and cur_round >= 2:
                    if glued:
                        ended = max(0, cur_round - 1)
                        usable = tokens[:ended] if ended else []
                        for slot_i, tok in enumerate(usable):
                            bid_val = self._parse_seat_amount(tok)
                            if bid_val > 0:
                                pending_hist.append((idx, slot_i + 1, bid_val))
                    else:
                        bid_val = self._parse_seat_amount(tokens[0])
                        hist_round = self._hist_round_from_x(nx, cur_round, origin_x=hist_origin)
                        if bid_val > 0 and hist_round:
                            pending_hist.append((idx, hist_round, bid_val))
                elif cur_round > 0:
                    bid_val = self._parse_seat_amount(tokens[0] if tokens else compact)
                    if bid_val >= 10:
                        seats[idx]["currentBid"] = bid_val
                continue

            if compact.lower() in skip:
                continue
            if len(compact) < 1 or len(compact) > 14:
                continue
            if len(compact) == 1 and self._clean_settlement_winner_name(compact) is None:
                continue
            if re.fullmatch(r"[\d,，.．、KkWwMm万千%'\"`’.\-]+", compact):
                continue
            if any(tok in compact for tok in ("回合", "情报", "仪器", "出价", "放弃", "图鉴", "标准", "资产", "估价", "表情", "短语", "UID", "展示", "藏品", "概率", "宝箱", "随机", "品质", "轮廓")):
                continue
            seats[idx]["name"] = compact

        for idx, hist_round, bid_val in pending_hist:
            name = seats[idx].get("name")
            if name and bid_val > 0 and hist_round:
                self._commit_round_finals(finals, hist_round, {name: bid_val})

        if cur_round:
            live = {}
            for seat in seats:
                name = seat.get("name")
                current = seat.get("currentBid")
                if name and current:
                    live[name] = int(current)
            if live:
                self._commit_round_finals(finals, cur_round, live)

        for seat in seats:
            current = seat.get("currentBid")
            seat["bid"] = int(current or 0)

        out: Dict[str, Any] = {}
        out["finalBids"] = finals
        out["historicalBids"] = {
            name: {rk: int(rv) for rk, rv in rounds.items() if int(rk) < cur_round}
            for name, rounds in finals.items()
            if any(int(rk) < cur_round for rk in rounds)
        }
        out["seats"] = seats
        named = [s for s in seats if s.get("name")]
        out["opponents"] = [
            {"slot": s["slot"], "name": s["name"], "bid": s["bid"], "currentBid": s.get("currentBid")}
            for s in named
        ]
        me = next((s for s in seats if s.get("isMe") and s.get("name")), None)
        if me:
            out["myName"] = me["name"]
            out["myBid"] = me["bid"]
        else:
            out["myName"] = None
            out["myBid"] = 0

        # Isolated leader calculation
        round_finals = {}
        key = str(int(cur_round or 0))
        for name, rounds in finals.items():
            if int(rounds.get(key) or 0) > 0:
                round_finals[name] = int(rounds[key])
        if not round_finals:
            out["currentLeaderBid"] = 0
            out["leaderName"] = None
            out["leaderTies"] = []
            out["isMyLead"] = False
        else:
            top = max(round_finals.values())
            ties = [name for name, bid in round_finals.items() if bid == top]
            out["currentLeaderBid"] = top
            out["leaderTies"] = ties
            out["leaderName"] = ties[0] if len(ties) == 1 else None
            me_n = out.get("myName")
            out["isMyLead"] = bool(me_n and (me_n == ties[0] if len(ties) == 1 else me_n in ties))

        return out

    def _read_shadow_seats_bids(self, frame: Optional[np.ndarray]) -> Dict[str, Any]:
        """Shadow dual-read of seats_bids_panel small ROI for diagnostics/testing without mutating production authority."""
        result: Dict[str, Any] = {
            "tokenCount": 0,
            "seats": [],
            "opponents": [],
            "myName": None,
            "myBid": 0,
            "leaderName": None,
            "currentLeaderBid": 0,
            "leaderTies": [],
            "isMyLead": False,
            "historicalBids": {},
            "finalBids": {},
            "error": None,
        }
        if frame is None or getattr(frame, "size", 0) == 0:
            return result
        try:
            h, w = frame.shape[:2]
            px1, py1, px2, py2 = ROIScaler.scale_roi("seats_bids_panel", w, h)
            panel_crop = frame[py1:py2, px1:px2]
            if panel_crop.size > 0:
                panel_res, _ = self.ocr(panel_crop)
                mapped_panel_res = [
                    ([[pt[0] + px1, pt[1] + py1] for pt in box], text, score)
                    for box, text, score in (panel_res or [])
                ]
                result["tokenCount"] = len(mapped_panel_res)

                base_ctx = {
                    "seats": [dict(s) for s in (self.current_context.get("seats") or [])],
                    "finalBids": {k: dict(v) for k, v in (self.current_context.get("finalBids") or {}).items()},
                    "historicalBids": {k: dict(v) for k, v in (self.current_context.get("historicalBids") or {}).items()},
                    "round": self.current_context.get("round", 0),
                    "myName": self.current_context.get("myName"),
                    "myBid": self.current_context.get("myBid", 0),
                }
                isolated_out = self._bind_horizontal_seats_isolated(mapped_panel_res, w, h, base_ctx)
                result.update(isolated_out)
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    def _classify_scene_fast(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        对局前场景：小 ROI 颜色/几何快检（毫秒级）。
        都市大亨与大世界互斥：白城+橙钮优先；大世界必须是暗角雷达，不能把标题圆标当小地图。
        """
        h, w = frame.shape[:2]
        if h < 200 or w < 200:
            return {"scene": SCENE_UNKNOWN, "auctionEntryVisible": False}

        # Gold inventory cards plus Exit resemble the lobby's venue + Match
        # colors. On cold startup, first route the explicit settlement title
        # to full OCR; color heuristics may not keep returning lobby forever.
        from scene_anchors import settlement_title_visible
        if settlement_title_visible(frame):
            return {"scene": SCENE_SETTLEMENT, "auctionEntryVisible": False}

        def crop_norm(x1, y1, x2, y2):
            return frame[int(h * y1):max(int(h * y1) + 1, int(h * y2)), int(w * x1):max(int(w * x1) + 1, int(w * x2))]

        def hsv(img):
            if img.size == 0:
                return None
            return cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # —— 拍卖大厅：右下「开始匹配」灰白钮 + 右侧橙色会场卡 + 展厅 ——
        # 真实大厅左侧是暗色展厅，不能当 IDE 侧栏否决。IDE 侧栏是「又暗又干」。
        match_btn = crop_norm(0.62, 0.82, 0.96, 0.97)
        venue_card = crop_norm(0.58, 0.18, 0.96, 0.62)
        hall = crop_norm(0.18, 0.18, 0.58, 0.78)
        left_ide = crop_norm(0.00, 0.08, 0.16, 0.78)
        bh, vh, hhv, ih = hsv(match_btn), hsv(venue_card), hsv(hall), hsv(left_ide)
        btn_bright = float((bh[:, :, 2] > 180).mean()) if bh is not None else 0.0
        btn_low_sat = float((bh[:, :, 1] < 60).mean()) if bh is not None else 0.0
        venue_orange = 0.0
        if vh is not None:
            venue_orange = float((cv2.inRange(vh, (8, 80, 120), (30, 255, 255)) > 0).mean())
        hall_mid = float((hhv[:, :, 2] > 70).mean()) if hhv is not None else 0.0
        left_dark = float((ih[:, :, 2] < 70).mean()) if ih is not None else 0.0
        left_sat = float(ih[:, :, 1].mean()) if ih is not None else 0.0
        ide_sidebar = left_dark >= 0.55 and left_sat < 25.0
        # 都市大亨白城 + 金色建筑标也会摸到橙色，不能先于白城判定抢成大厅
        city_preview = hsv(crop_norm(0.08, 0.16, 0.62, 0.78))
        city_bright_preview = float((city_preview[:, :, 2] > 165).mean()) if city_preview is not None else 0.0
        city_low_sat_preview = float((city_preview[:, :, 1] < 90).mean()) if city_preview is not None else 0.0
        white_city_preview = city_bright_preview >= 0.32 and city_low_sat_preview >= 0.32
        # 橙色会场卡 + 开始匹配 是大厅独有。中间亮面板/重叠窗口不能一票否决。
        match_like = btn_low_sat >= 0.18 and (
            btn_bright >= 0.10 or (bh is not None and float(bh[:, :, 2].mean()) >= 90)
        )
        lobby_like = venue_orange >= 0.04 and match_like and not ide_sidebar
        if lobby_like:
            return {
                "scene": SCENE_AUCTION_LOBBY,
                "auctionEntryVisible": True,
                "venueOrange": venue_orange,
                "lobbySuspect": True,
            }

        # —— 都市闲趣必须先于都市大亨：浅色卡片格 + 黄 MENU 很像白城 ——
        menu_chip = crop_norm(0.06, 0.05, 0.28, 0.20)
        panel = crop_norm(0.10, 0.20, 0.88, 0.86)
        left_bar = crop_norm(0.00, 0.10, 0.07, 0.90)
        right_bar = crop_norm(0.93, 0.10, 1.00, 0.90)
        mh, ph, lh, rh = hsv(menu_chip), hsv(panel), hsv(left_bar), hsv(right_bar)
        yellow = cv2.inRange(mh, (14, 60, 110), (42, 255, 255)) if mh is not None else None
        yellow_ratio = float((yellow > 0).mean()) if yellow is not None else 0.0
        panel_light = float((ph[:, :, 2] > 145).mean()) if ph is not None else 0.0
        side_dark = 0.0
        if lh is not None and rh is not None:
            side_dark = 0.5 * (float((lh[:, :, 2] < 90).mean()) + float((rh[:, :, 2] < 90).mean()))
        is_leisure = yellow_ratio >= 0.02 and panel_light >= 0.18 and side_dark >= 0.28
        if is_leisure:
            return {"scene": SCENE_CITY_LEISURE_MENU, "auctionEntryVisible": False}

        # 避开右上角战术 HUD，只看游戏内容
        city = crop_norm(0.08, 0.16, 0.62, 0.78)
        upgrade = crop_norm(0.72, 0.62, 0.99, 0.96)
        ch, uh = hsv(city), hsv(upgrade)
        city_bright = float((ch[:, :, 2] > 165).mean()) if ch is not None else 0.0
        city_low_sat = float((ch[:, :, 1] < 90).mean()) if ch is not None else 0.0
        orange = cv2.inRange(uh, (8, 110, 160), (28, 255, 255)) if uh is not None else None
        orange_ratio = float((orange > 0).mean()) if orange is not None else 0.0
        gold = cv2.inRange(ch, (15, 80, 160), (40, 255, 255)) if ch is not None else None
        gold_ratio = float((gold > 0).mean()) if gold is not None else 0.0
        # 都市大亨必须是浅色城市场景。夜间大世界的路灯/技能钮橙色不能当升级钮。
        white_city = city_bright >= 0.32 and city_low_sat >= 0.32
        if white_city and (orange_ratio >= 0.06 or gold_ratio >= 0.02) and not is_leisure and venue_orange < 0.04:
            return {"scene": SCENE_CITY_TYCOON_HUB, "auctionEntryVisible": False, "whiteCity": True, "venueOrange": venue_orange}

        # —— 大世界：左上暗色雷达 + 底栏血条。不因技能钮橙色否决。 ——
        if white_city:
            return {"scene": SCENE_UNKNOWN, "auctionEntryVisible": False, "whiteCity": True}

        mini = crop_norm(0.00, 0.00, 0.18, 0.24)
        hp = crop_norm(0.30, 0.88, 0.70, 0.99)
        mi, hi = hsv(mini), hsv(hp)
        if mi is not None and hi is not None:
            mini_mean_v = float(mi[:, :, 2].mean())
            gray = cv2.cvtColor(mini, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray, (7, 7), 1.2)
            circles = cv2.HoughCircles(
                blur,
                cv2.HOUGH_GRADIENT,
                dp=1.1,
                minDist=max(10, gray.shape[0] // 4),
                param1=50,
                param2=22,
                minRadius=int(h * 0.055),
                maxRadius=int(h * 0.085),
            )
            has_minimap = False
            if circles is not None and len(circles[0]) >= 1:
                # 真实大世界雷达位于左上角特定位置，且具有圆形边界
                for c in circles[0]:
                    cx, cy, cr = c[0], c[1], c[2]
                    if 0.20 * mini.shape[1] <= cx <= 0.60 * mini.shape[1] and 0.20 * mini.shape[0] <= cy <= 0.60 * mini.shape[0]:
                        has_minimap = True
                        break
            if not has_minimap and mini_mean_v < 90:
                # 夜间雷达：中心明显更暗即可
                cy, cx = gray.shape[0] // 2, int(gray.shape[1] * 0.38)
                r = max(10, gray.shape[0] // 4)
                yy, xx = np.ogrid[:gray.shape[0], :gray.shape[1]]
                disk = (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r
                if disk.any() and float(gray[disk].mean()) < float(gray.mean()) - 8:
                    has_minimap = True
            hp_v = hi[:, :, 2]
            hp_bright = float((hp_v > 160).mean())
            hp_is_bar = 0.08 <= hp_bright <= 0.60

            # 局内席位/顶栏排除：避免局内元素被误判为大世界
            seats = crop_norm(0.02, 0.15, 0.28, 0.75)
            sh = hsv(seats)
            st_bright = float((sh[:, :, 2] > 140).mean()) if sh is not None else 0.0
            in_auction_seats = st_bright >= 0.20

            top_header = crop_norm(0.05, 0.00, 0.40, 0.10)
            th_hsv = hsv(top_header)
            tb_bright = float((th_hsv[:, :, 2] > 180).mean()) if th_hsv is not None else 0.0
            in_auction_header = tb_bright >= 0.025

            # 大厅底栏也有血条/角色条；有橙色会场卡或局内席位/顶栏时禁止打成大世界
            if has_minimap and hp_is_bar and mini_mean_v < 140 and venue_orange < 0.03 and not in_auction_seats and not in_auction_header:
                return {"scene": SCENE_OPEN_WORLD, "auctionEntryVisible": False, "whiteCity": False, "venueOrange": venue_orange}

        return {"scene": SCENE_UNKNOWN, "auctionEntryVisible": False, "whiteCity": white_city}

    def _ocr_rois(self, frame: np.ndarray, roi_keys: Tuple[str, ...]) -> List[Any]:
        """对若干小 ROI 做 OCR，坐标映射回全屏。比整屏快一个数量级。"""
        h, w = frame.shape[:2]
        mapped: List[Any] = []
        for key in roi_keys:
            x1, y1, x2, y2 = ROIScaler.scale_roi(key, w, h)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            res, _ = self.ocr(crop)
            self.ocr_call_count += 1
            if not res:
                continue
            for box, text, score in res:
                mapped.append(([[p[0] + x1, p[1] + y1] for p in box], text, score))
        return mapped

    def _ocr_downscaled(self, frame: np.ndarray, max_width: int = 720) -> List[Any]:
        """缩小整图再 OCR，用来抓「大亨等级 / 都市闲趣」等中屏大字，耗时远低于原分辨率。"""
        h, w = frame.shape[:2]
        if w <= 0 or h <= 0:
            return []
        scale = min(1.0, float(max_width) / float(w))
        if scale < 0.99:
            small = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        else:
            small, scale = frame, 1.0
        res, _ = self.ocr(small)
        self.ocr_call_count += 1
        if not res:
            return []
        mapped = []
        inv = 1.0 / scale
        for box, text, score in res:
            mapped.append(([[p[0] * inv, p[1] * inv] for p in box], text, score))
        return mapped

    def _clear_nav_scene(self) -> None:
        self._nav_hold_frames = 0
        self.current_context["inAuction"] = False
        self.current_context["inLobby"] = False
        self.current_context["isLoading"] = False
        self.current_context["scene"] = SCENE_UNKNOWN
        self.current_context["sceneLabel"] = SCENE_LABELS[SCENE_UNKNOWN]
        self.current_context["auctionEntryVisible"] = False

    def _hold_nav_or_clear(self, max_hold: int = 1) -> None:
        """单帧漏检时短暂保持上一导航场景；大世界不走这里。"""
        prev = self.current_context.get("scene")
        if prev == SCENE_OPEN_WORLD:
            self._clear_nav_scene()
            return
        if prev in PRE_AUCTION_NAV_SCENES and self._nav_hold_frames < max_hold:
            self._nav_hold_frames += 1
            return
        self._clear_nav_scene()

    def _filter_ocr_exclude_hud(self, ocr_results: List[Any], screen_w: int = 1920, screen_h: int = 1080) -> List[Any]:
        """过滤右上角战术 HUD 自回环区域。"""
        filtered = []
        for box, text, score in ocr_results:
            x_min = min(b[0] for b in box)
            y_min = min(b[1] for b in box)
            nx = x_min / max(1, screen_w)
            ny = y_min / max(1, screen_h)
            if nx >= 0.70 and ny <= 0.45:
                continue
            filtered.append((box, text, score))
        return filtered

    def _empty_seats(self) -> List[Dict[str, Any]]:
        return [
            {"slot": 1, "name": None, "bid": None, "currentBid": None, "observationStatus": "UNOBSERVED", "isMe": False},
            {"slot": 2, "name": None, "bid": None, "currentBid": None, "observationStatus": "UNOBSERVED", "isMe": False},
            {"slot": 3, "name": None, "bid": None, "currentBid": None, "observationStatus": "UNOBSERVED", "isMe": False},
            {"slot": 4, "name": None, "bid": None, "currentBid": None, "observationStatus": "UNOBSERVED", "isMe": False},
        ]

    def _trusted_df_bid_slots(self, df_bids: List[Optional[int]]) -> set[int]:
        """A full numeric ROI token with strong OCR confidence can be used now.

        Sparse live captures rarely contain two identical consecutive quotes. The
        older two-frame gate still applies to weaker readings and panel fallback.
        """
        raw_bids = getattr(self, "_df_shadow_seat_bids", [])
        confs = getattr(self, "_df_shadow_seat_bids_conf", [])
        return {
            i + 1 for i, value in enumerate(df_bids[:4])
            if value is not None and i < len(raw_bids) and raw_bids[i] == value
            and i < len(confs) and confs[i] >= 0.90
        }

    def _parse_seat_amount(self, compact: str) -> int:
        bid_val = parse_bid_text(compact)
        if bid_val <= 0:
            bid_val = parse_money_amount(compact, min_digits=1)
        if bid_val <= 0:
            digits = re.sub(r"[^\d]", "", compact)
            if digits.isdigit() and 0 <= int(digits) <= 999999999:
                bid_val = int(digits)
        return int(bid_val or 0)

    def _split_hist_tokens(self, compact: str) -> List[str]:
        raw = re.sub(r"\s+", "", compact or "")
        if not raw:
            return []
        raw = raw.replace("'", ",").replace("’", ",").replace("%", "K")
        tokens = re.findall(r"\d+(?:[,.，．]\d+)*[KkWwMm万]?", raw)
        return [tok for tok in tokens if tok]

    def _hist_round_from_x(self, nx: float, cur_round: int, origin_x: Optional[float] = None) -> Optional[int]:
        """历史小槽从左到右对应已结束的 R1..R{cur-1}，绝不映射当前回合。"""
        ended = max(0, int(cur_round or 0) - 1)
        if ended <= 0:
            return None
        origin = 0.082 if origin_x is None else float(origin_x)
        step = 0.040
        slot = int(round((nx - origin) / step))
        hist_round = slot + 1
        if hist_round < 1 or hist_round > ended:
            return None
        if abs(nx - (origin + slot * step)) > 0.024:
            return None
        return hist_round

    def _accept_hist_repair(self, existing: Optional[int], incoming: int) -> Optional[int]:
        incoming = int(incoming or 0)
        if incoming <= 0:
            return existing
        if not existing:
            return incoming
        existing = int(existing)
        if incoming == existing:
            return existing
        if existing == 999999 and incoming == 1000000:
            return 999999
        if existing == 666666 and incoming == 1000000:
            return 999999
        smaller, larger = sorted((existing, incoming))
        if larger % smaller == 0 and larger // smaller in (10, 100, 1000, 10000):
            return larger
        # 末位 OCR 抖动：888888 vs 888890、666666 vs 666670。只接受已有多位数被轻微改尾。
        if existing >= 1000 and incoming >= 1000:
            if abs(existing - incoming) <= max(2, int(existing * 0.005)):
                return existing
        return incoming

    def _commit_round_finals(self, finals: Dict[str, Any], round_no: int, bids: Dict[str, int]) -> None:
        key = str(int(round_no))
        for name, bid in bids.items():
            if not name or int(bid or 0) <= 0:
                continue
            player = dict(finals.get(name) or {})
            accepted = self._accept_hist_repair(player.get(key), int(bid))
            if accepted:
                player[key] = int(accepted)
                finals[name] = player

    def _commit_slot_finals(self, round_no: int, slot_bids: Dict[int, int]) -> None:
        key = str(int(round_no))
        for slot_id, bid in slot_bids.items():
            if slot_id not in (1, 2, 3, 4) or int(bid or 0) <= 0:
                continue
            entry = dict(self._slot_finals.get(slot_id) or {})
            accepted = self._accept_hist_repair(entry.get(key), int(bid))
            if accepted:
                entry[key] = int(accepted)
                self._slot_finals[slot_id] = entry

    def _extract_seat_panel_items(
        self,
        ocr_results: List[Any],
        screen_w: int,
        screen_h: int,
    ) -> Tuple[List[Tuple[int, float, float, float, float, str]], Optional[float]]:
        """Extract valid slot-bound text items and historical column origin X."""
        bands = (
            (0.14, 0.29),
            (0.29, 0.44),
            (0.44, 0.58),
            (0.58, 0.74),
        )
        hist_xs: List[float] = []
        slot_items: List[Tuple[int, float, float, float, float, str]] = []

        for box, text, _ in ocr_results:
            raw = re.sub(r"\s+", "", text or "")
            if not raw:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            nx = min(xs) / max(1, screen_w)
            ny = ((min(ys) + max(ys)) / 2.0) / max(1, screen_h)
            nh = (max(ys) - min(ys)) / max(1, screen_h)
            nw = (max(xs) - min(xs)) / max(1, screen_w)

            leftover = re.sub(r"[\d,\uff0c.\uff0e\u3001KkWwMm\u4e07\u5343%'\"\`\u2019]", "", raw)
            if not leftover:
                tokens = self._split_hist_tokens(raw)
                if tokens:
                    compact_up = raw.upper().replace("万", "W")
                    if re.search(r"[KWM]", compact_up) or nh <= 0.028:
                        hist_xs.append(nx)

            if nx < 0.02 or nx > 0.30 or ny < 0.12 or ny > 0.78:
                continue
            idx = next((i for i, (lo, hi) in enumerate(bands) if lo <= ny < hi), None)
            if idx is None:
                continue
            slot_id = idx + 1
            slot_items.append((slot_id, nx, ny, nh, nw, raw))

        hist_origin = min(hist_xs) if hist_xs else None
        return slot_items, hist_origin

    def _update_seat_names_and_finals_from_ocr(
        self,
        slot_items: List[Tuple[int, float, float, float, float, str]],
        cur_round: int,
        hist_origin: Optional[float],
    ) -> None:
        """
        Metadata & Finals Responsibility (4D2D1L-L3Z.6):
        Updates player names, historical round finals, and round archival strictly.
        Does not mutate current live bid authority.
        """
        skip = {"esc", "nte", "ul", "uid", "enter", "menu"}
        pending_hist: List[Tuple[int, int, int]] = []

        for slot_id, nx, ny, nh, nw, compact in slot_items:
            non_numeric = re.sub(r"[\d,\uff0c.\uff0e\u3001KkWwMm\u4e07\u5343%'\"\`\u2019.\-]", "", compact)
            has_chinese_name = bool(re.search(r"[\u4e00-\u9fa5]", non_numeric))
            tokens = self._split_hist_tokens(compact)
            leftover = re.sub(r"[\d,\uff0c.\uff0e\u3001KkWwMm\u4e07\u5343%'\"\`\u2019]", "", compact)
            numeric_like = bool(tokens) and not leftover and not has_chinese_name

            if numeric_like:
                compact_up = compact.upper().replace("万", "W")
                glued = len(tokens) >= 2
                is_hist_unit = bool(re.search(r"[KWM]", compact_up))
                is_history = glued or is_hist_unit or nh <= 0.028 or (nw >= 0.055 and nh <= 0.025)

                if is_history and cur_round >= 2:
                    if glued:
                        ended = max(0, cur_round - 1)
                        usable = tokens[:ended] if ended else []
                        for slot_i, tok in enumerate(usable):
                            bid_val = self._parse_seat_amount(tok)
                            if bid_val > 0:
                                pending_hist.append((slot_id, slot_i + 1, bid_val))
                    else:
                        bid_val = self._parse_seat_amount(tokens[0])
                        hist_round = self._hist_round_from_x(nx, cur_round, origin_x=hist_origin)
                        if bid_val > 0 and hist_round:
                            pending_hist.append((slot_id, hist_round, bid_val))
                continue

            if compact.lower() in skip:
                continue
            if len(compact) < 1 or len(compact) > 14:
                continue
            if len(compact) == 1 and self._clean_settlement_winner_name(compact) is None:
                continue
            if re.fullmatch(r"[\d,\uff0c.\uff0e\u3001KkWwMm\u4e07\u5343%'\"\`\u2019.\-]+", compact):
                continue
            if any(tok in compact for tok in ("回合", "情报", "仪器", "出价", "放弃", "图鉴", "标准", "资产", "估价", "表情", "短语", "UID", "展示", "藏品", "概率", "宝箱", "随机", "品质", "轮廓")):
                continue
            # Sticky name assignment: update presentation name label for slot
            self._slot_names[slot_id] = compact

        # Commit pending historical bids
        slot_hist_map: Dict[int, Dict[int, int]] = {}
        for slot_id, hist_round, bid_val in pending_hist:
            if hist_round not in slot_hist_map:
                slot_hist_map[hist_round] = {}
            slot_hist_map[hist_round][slot_id] = bid_val
        for hist_round, s_bids in slot_hist_map.items():
            self._commit_slot_finals(hist_round, s_bids)

    def _update_seat_current_bids_from_ocr(
        self,
        slot_items: List[Tuple[int, float, float, float, float, str]],
        cur_round: int,
    ) -> Dict[int, Optional[int]]:
        """
        Current-Bid OCR Authority (4D2D1L-L3Z.6):
        Extracts current live bid numeric values from panel OCR.
        Updates self._slot_cur_bids and commits live bids to _slot_finals[cur_round].
        """
        cur_bids: Dict[int, Optional[int]] = {1: None, 2: None, 3: None, 4: None}

        for slot_id, nx, ny, nh, nw, compact in slot_items:
            non_numeric = re.sub(r"[\d,\uff0c.\uff0e\u3001KkWwMm\u4e07\u5343%'\"\`\u2019.\-]", "", compact)
            has_chinese_name = bool(re.search(r"[\u4e00-\u9fa5]", non_numeric))
            tokens = self._split_hist_tokens(compact)
            leftover = re.sub(r"[\d,\uff0c.\uff0e\u3001KkWwMm\u4e07\u5343%'\"\`\u2019]", "", compact)
            numeric_like = bool(tokens) and not leftover and not has_chinese_name

            if numeric_like:
                compact_up = compact.upper().replace("万", "W")
                glued = len(tokens) >= 2
                is_hist_unit = bool(re.search(r"[KWM]", compact_up))
                is_history = glued or is_hist_unit or nh <= 0.028 or (nw >= 0.055 and nh <= 0.025)

                if not is_history and cur_round > 0:
                    bid_val = self._parse_seat_amount(tokens[0] if tokens else compact)
                    if bid_val >= 0:
                        self._apply_seat_bid_observation(slot_id, bid_val)

        if cur_round:
            live = {s: int(b) for s, b in self._slot_cur_bids.items() if b is not None}
            if live:
                self._commit_slot_finals(cur_round, live)

        return self._slot_cur_bids

    def _derive_seat_leader_and_context(
        self,
        cur_round: int,
        cur_bids: Dict[int, Optional[int]],
    ) -> None:
        """
        Pure In-Memory Leader & Context Packaging (4D2D1L-L3Z.6):
        Derives leader state and builds outward context dictionaries without OCR.
        """
        # Leader determination strictly based on slot finals
        cur_round_key = str(int(cur_round or 0))
        cur_round_bids = {
            s: int(self._slot_finals[s].get(cur_round_key) or 0)
            for s in (1, 2, 3, 4)
            if int(self._slot_finals[s].get(cur_round_key) or 0) > 0
        }
        if not cur_round_bids:
            cur_leader_bid = 0
            self._leader_slot = None
            leader_name = None
            leader_ties = []
        else:
            top_bid = max(cur_round_bids.values())
            tied_slots = [s for s, b in cur_round_bids.items() if b == top_bid]
            cur_leader_bid = top_bid
            if len(tied_slots) == 1:
                self._leader_slot = tied_slots[0]
                leader_name = self._slot_names.get(self._leader_slot)
                leader_ties = [leader_name] if leader_name else []
            else:
                self._leader_slot = None
                leader_name = None
                leader_ties = [self._slot_names.get(s) for s in tied_slots if self._slot_names.get(s)]

        # Context packaging (strictly matching existing schema)
        my_name = self._slot_names.get(4)
        seats = [
            {
                "slot": s,
                "name": self._slot_names.get(s),
                "bid": int(cur_bids.get(s)) if cur_bids.get(s) is not None else None,
                "currentBid": cur_bids.get(s),
                "observationStatus": "VISIBLE" if cur_bids.get(s) is not None else "UNOBSERVED",
                "isMe": bool(my_name and s == 4),
                **(self._slot_bid_evidence.get(s, {}) if cur_bids.get(s) is not None else {}),
            }
            for s in (1, 2, 3, 4)
        ]

        # Name-keyed export for legacy compatibility
        final_bids_by_name: Dict[str, Dict[str, int]] = {}
        hist_bids_by_name: Dict[str, Dict[str, int]] = {}
        for s, rounds in self._slot_finals.items():
            name_key = self._slot_names.get(s) or f"Player{s}"
            if rounds:
                final_bids_by_name[name_key] = dict(rounds)
            past = {rk: int(rv) for rk, rv in rounds.items() if int(rk) < cur_round}
            if past:
                hist_bids_by_name[name_key] = past

        self.current_context["seats"] = seats
        self.current_context["finalBids"] = final_bids_by_name
        self.current_context["historicalBids"] = hist_bids_by_name
        self.current_context["currentLeaderBid"] = cur_leader_bid
        self.current_context["leaderName"] = leader_name
        self.current_context["leaderTies"] = leader_ties
        self.current_context["myName"] = my_name
        self.current_context["myBid"] = int(cur_bids.get(4) or 0)
        self.current_context["isMyLead"] = bool(self._leader_slot == 4)
        self.current_context["opponents"] = [
            {"slot": s["slot"], "name": s["name"], "bid": s["bid"], "currentBid": s["currentBid"]}
            for s in seats if s["name"]
        ]

    def _apply_seat_bid_observation(self, slot_id: int, val: Optional[int]) -> None:
        """
        Mutable Seat-Bid Symmetric N=2 Candidate Confirmation Contract (4D2D1M-C2.22R):
        Confirms any change to the current quote (upward or downward) with consecutive N=2
        matching observations before committing to _slot_cur_bids.
        1. val is None or invalid (<= 0): Holds confirmed quote, clears candidate.
        2. val == confirmed: Holds confirmed quote, clears candidate.
        3. val != confirmed:
           - If candidate == val: count += 1; when count >= 2, commits _slot_cur_bids[slot] = val and clears candidate.
           - If candidate != val: candidate = val, count = 1.
        """
        if not hasattr(self, "_slot_bid_candidates") or self._slot_bid_candidates is None:
            self._slot_bid_candidates = {1: {"val": None, "count": 0}, 2: {"val": None, "count": 0}, 3: {"val": None, "count": 0}, 4: {"val": None, "count": 0}}

        st = self._slot_bid_candidates.setdefault(slot_id, {"val": None, "count": 0})
        confirmed = self._slot_cur_bids.get(slot_id)

        # Case 1: val is None or negative. Zero is a visible bid.
        if val is None or val < 0:
            # Confirmed quote is preserved (Hold-Last)
            # Clear candidate on miss to enforce strict consecutive confirmation
            st["val"] = None
            st["count"] = 0
            return

        # Case 2: val matches confirmed quote
        if confirmed is not None and val == confirmed:
            st["val"] = None
            st["count"] = 0
            return

        # Case 3: val differs from confirmed quote (or confirmed is None)
        if st["val"] == val:
            st["count"] += 1
        else:
            st["val"] = val
            st["count"] = 1

        if st["count"] >= 2:
            self._slot_cur_bids[slot_id] = val
            st["val"] = None
            st["count"] = 0

    def _update_seat_current_bids_from_df(
        self,
        df_bids: List[Optional[int]],
        cur_round: int,
        trusted_slots: Optional[set[int]] = None,
    ) -> Dict[int, Optional[int]]:
        """
        Detection-Free Current-Bid Authority (4D2D1L-L3Z.7) with N=2 Confirmation (4D2D1M-C2.22):
        Applies DF numeric bids to self._slot_cur_bids using N=2 candidate confirmation.
        """
        trusted_slots = trusted_slots or set()
        for i, val in enumerate(df_bids):
            slot_id = i + 1
            if slot_id in trusted_slots and val is not None and val >= 0:
                self._slot_cur_bids[slot_id] = val
                self._slot_bid_candidates[slot_id] = {"val": None, "count": 0}
            else:
                self._apply_seat_bid_observation(slot_id, val)
            if val is not None and self._slot_cur_bids.get(slot_id) == val:
                captured_at = getattr(self, "_frame_bid_captured_at", None)
                if captured_at:
                    self._slot_bid_evidence[slot_id] = {
                        "round": cur_round,
                        "capturedAt": captured_at,
                        "bidRawText": self._df_shadow_seat_bids_raw_text[i],
                        "bidOcrConfidence": self._df_shadow_seat_bids_conf[i],
                    }

        if cur_round:
            live = {s: int(b) for s, b in self._slot_cur_bids.items() if b is not None}
            if live:
                self._commit_slot_finals(cur_round, live)

        return self._slot_cur_bids

    def _handle_seat_binding_tier(
        self,
        frame: np.ndarray,
        w: int,
        h: int,
        df_seat_bids: Optional[List[Optional[int]]],
        df_seat_success: bool,
        *,
        bid_panel_changed: Optional[bool] = None,
        bid_panel_signature: Optional[np.ndarray] = None,
    ) -> bool:
        """
        Seat Binding Tier with DF Authority & Metadata Gate (4D2D1L-L3Z.7):
        - Primary Authority: DF 4-slot recognition batch for current bids.
        - Metadata Gate: Heavy seats_bids_panel OCR only runs if names are missing,
          round transition occurs, or DF batch threw an exception.
        """
        if not hasattr(self, "_slot_names") or self._slot_names is None:
            self._slot_names = {1: None, 2: None, 3: None, 4: None}
        if not hasattr(self, "_slot_finals") or self._slot_finals is None:
            self._slot_finals = {1: {}, 2: {}, 3: {}, 4: {}}
        if not hasattr(self, "_slot_cur_bids") or self._slot_cur_bids is None:
            self._slot_cur_bids = {1: None, 2: None, 3: None, 4: None}

        cur_round = int(self.current_context.get("round") or 0)
        prev_round = int(getattr(self, "_seat_round", 0) or 0)

        # 1. Round transition carryover and current bids reset
        if cur_round and prev_round and cur_round != prev_round:
            carried = {}
            for s in (1, 2, 3, 4):
                old_cur = self._slot_cur_bids.get(s)
                if old_cur:
                    carried[s] = int(old_cur)
            if carried:
                self._commit_slot_finals(prev_round, carried)
            self._slot_cur_bids = {1: None, 2: None, 3: None, 4: None}
            self._slot_bid_candidates = {1: {"val": None, "count": 0}, 2: {"val": None, "count": 0}, 3: {"val": None, "count": 0}, 4: {"val": None, "count": 0}}
            self._slot_bid_evidence = {}
        if cur_round:
            self._seat_round = cur_round

        # 2. Check metadata gate conditions
        needs_names = any(self._slot_names.get(s) is None for s in (1, 2, 3, 4))
        if hasattr(self, "_acquisition_names"):
            needs_names = needs_names or any(self._acquisition_names.names.get(s, (None, 0, None))[1] < 2 for s in (1, 2, 3, 4))
        is_round_transition = bool(cur_round and prev_round and cur_round != prev_round)
        needs_df_fallback = not df_seat_success or any(value is None for value in (df_seat_bids or [None]*4))
        is_mocked = (getattr(self._bind_seats_slot_authoritative, "__func__", self._bind_seats_slot_authoritative) != NTEVisionPipeline._bind_seats_slot_authoritative)

        if bid_panel_changed is None:
            should_run_heavy_panel = bool(needs_names or is_round_transition or needs_df_fallback or is_mocked)
        else:
            needs_initial_name_scan = bool(
                needs_names and (
                    bid_panel_changed
                    or not getattr(self, "_priority_seat_panel_ocr_attempted", False)
                )
            )
            needs_changed_bid_fallback = bool(needs_df_fallback and bid_panel_changed)
            should_run_heavy_panel = bool(
                needs_initial_name_scan
                or is_round_transition
                or needs_changed_bid_fallback
                or is_mocked
            )
        if getattr(self, "_defer_seat_heavy_once", False):
            self._defer_seat_heavy_once = False
            should_run_heavy_panel = False

        # 3. Conditional execution of heavy panel OCR
        panel_bound = True
        if should_run_heavy_panel:
            try:
                px1, py1, px2, py2 = ROIScaler.scale_roi("seats_bids_panel", w, h)
                panel_crop = frame[py1:py2, px1:px2]
                if panel_crop.size > 0:
                    if bid_panel_changed is not None:
                        self._priority_seat_panel_ocr_attempted = True
                        if bid_panel_signature is not None:
                            self._last_priority_seat_panel_ocr_sig = bid_panel_signature.copy()
                    panel_res, _ = self.ocr(panel_crop)
                    if panel_res:
                        mapped_panel_res = [
                            ([[pt[0] + px1, pt[1] + py1] for pt in box], text, score)
                            for box, text, score in panel_res
                        ]
                        self._frame_seat_rows = mapped_panel_res
                        if is_mocked:
                            panel_bound = self._bind_seats_slot_authoritative(mapped_panel_res, w, h)
                        else:
                            slot_items, hist_origin = self._extract_seat_panel_items(mapped_panel_res, w, h)
                            self._update_seat_names_and_finals_from_ocr(slot_items, cur_round, hist_origin)
                            if needs_df_fallback:
                                from seat_bid_observation import visible_seat_bids
                                observed = visible_seat_bids(mapped_panel_res, w, h, allow_zero=True)
                                if any(value is not None for value in observed):
                                    # Missing seats in a partial DF batch must not
                                    # erase the OCR candidate later in this frame.
                                    df_seat_bids = [a if a is not None else b for a,b in zip(df_seat_bids or [None]*4, observed)]
                                    df_seat_success = True
                                else:
                                    self._update_seat_current_bids_from_ocr(slot_items, cur_round)
                            panel_bound = True
                    else:
                        panel_bound = False
                else:
                    panel_bound = False
            except Exception:
                panel_bound = False

        # 4. Apply DF current-bid authority if DF succeeded (overrides OCR current bids)
        if df_seat_success and df_seat_bids is not None and not is_mocked:
            self._update_seat_current_bids_from_df(
                df_seat_bids, cur_round, trusted_slots=self._trusted_df_bid_slots(df_seat_bids)
            )
            self._derive_seat_leader_and_context(cur_round, self._slot_cur_bids)
            if not should_run_heavy_panel:
                panel_bound = True
        elif not panel_bound and is_mocked:
            pass
        else:
            self._derive_seat_leader_and_context(cur_round, self._slot_cur_bids)

        return panel_bound

    def _bind_seats_slot_authoritative(self, ocr_results: List[Any], screen_w: int, screen_h: int) -> bool:
        """
        Slot-Numeric Authority Backward-Compatible Coordinator (4D2D1L-L3K / 4D2D1L-L3Z.6):
        Used for full panel OCR binding in fallback/testing.
        """
        if not hasattr(self, "_slot_names") or self._slot_names is None:
            self._slot_names = {1: None, 2: None, 3: None, 4: None}
        if not hasattr(self, "_slot_finals") or self._slot_finals is None:
            self._slot_finals = {1: {}, 2: {}, 3: {}, 4: {}}
        if not hasattr(self, "_slot_cur_bids") or self._slot_cur_bids is None:
            self._slot_cur_bids = {1: None, 2: None, 3: None, 4: None}

        cur_round = int(self.current_context.get("round") or 0)
        prev_round = int(getattr(self, "_seat_round", 0) or 0)

        # 1. Round transition carryover
        if cur_round and prev_round and cur_round != prev_round:
            carried = {}
            for s in (1, 2, 3, 4):
                old_cur = self._slot_cur_bids.get(s)
                if old_cur:
                    carried[s] = int(old_cur)
            if carried:
                self._commit_slot_finals(prev_round, carried)
            self._slot_cur_bids = {1: None, 2: None, 3: None, 4: None}
            self._slot_bid_candidates = {1: {"val": None, "count": 0}, 2: {"val": None, "count": 0}, 3: {"val": None, "count": 0}, 4: {"val": None, "count": 0}}
            self._slot_bid_evidence = {}
        if cur_round:
            self._seat_round = cur_round

        # 2. Extract panel items
        slot_items, hist_origin = self._extract_seat_panel_items(ocr_results, screen_w, screen_h)

        # 3. Update names and historical finals
        self._update_seat_names_and_finals_from_ocr(slot_items, cur_round, hist_origin)

        # 4. Update current live bids
        cur_bids = self._update_seat_current_bids_from_ocr(slot_items, cur_round)

        # 5. Derive leader and context
        self._derive_seat_leader_and_context(cur_round, cur_bids)

        return True

    def _bind_horizontal_seats(self, ocr_results: List[Any], screen_w: int, screen_h: int) -> None:
        """名字 + 当前大数字 / 历史小槽位分开。历史槽只修已结束回合，不得改本轮 leader。"""
        bands = (
            (0.14, 0.29),
            (0.29, 0.44),
            (0.44, 0.58),
            (0.58, 0.74),
        )
        seats = self._empty_seats()
        prev_seats = self.current_context.get("seats") or []
        for i, prev in enumerate(prev_seats[:4]):
            if prev.get("name"):
                seats[i]["name"] = prev.get("name")
                # Fallback OCR must retain the identity already bound to this
                # seat; names alone cannot distinguish same-named players.
                seats[i]["isMe"] = prev.get("isMe") is True
        skip = {"esc", "nte", "ul", "uid", "enter", "menu"}
        finals = self._final_bids_from_history(self.current_context.get("finalBids") or self.current_context.get("historicalBids"))
        cur_round = int(self.current_context.get("round") or 0)
        prev_round = int(getattr(self, "_seat_round", 0) or 0)
        
        if cur_round and prev_round and cur_round != prev_round:
            carried = {}
            for prev in prev_seats:
                name = prev.get("name")
                old_cur = prev.get("currentBid")
                if name and old_cur:
                    carried[name] = int(old_cur)
            if carried:
                self._commit_round_finals(finals, prev_round, carried)

        if cur_round:
            self._seat_round = cur_round

        pending_hist: List[Tuple[int, int, int]] = []  # idx, round, bid
        hist_xs: List[float] = []
        raw_items = []
        for box, text, _ in ocr_results:
            raw = re.sub(r"\s+", "", text or "")
            if not raw:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            nx = min(xs) / max(1, screen_w)
            ny = ((min(ys) + max(ys)) / 2.0) / max(1, screen_h)
            nh = (max(ys) - min(ys)) / max(1, screen_h)
            nw = (max(xs) - min(xs)) / max(1, screen_w)
            raw_items.append((nx, ny, nh, nw, raw))
            
            leftover = re.sub(r"[\d,，.．、KkWwMm万千%'\"`’]", "", raw)
            if leftover:
                continue
            tokens = self._split_hist_tokens(raw)
            if not tokens:
                continue
            compact_up = raw.upper().replace("万", "W")
            if re.search(r"[KWM]", compact_up) or nh <= 0.028:
                hist_xs.append(nx)
                
        hist_origin = min(hist_xs) if hist_xs else None
        
        for nx, ny, nh, nw, compact in raw_items:
            if nx < 0.02 or nx > 0.30 or ny < 0.12 or ny > 0.78:
                continue
            idx = next((i for i, (lo, hi) in enumerate(bands) if lo <= ny < hi), None)
            if idx is None:
                continue
            
            non_numeric = re.sub(r"[\d,，.．、KkWwMm万千%'\"`’.\-]", "", compact)
            has_chinese_name = bool(re.search(r"[\u4e00-\u9fa5]", non_numeric))
            
            tokens = self._split_hist_tokens(compact)
            leftover = re.sub(r"[\d,，.．、KkWwMm万千%'\"`’]", "", compact)
            numeric_like = bool(tokens) and not leftover and not has_chinese_name
            
            if numeric_like:
                compact_up = compact.upper().replace("万", "W")
                glued = len(tokens) >= 2
                is_hist_unit = bool(re.search(r"[KWM]", compact_up))
                is_history = glued or is_hist_unit or nh <= 0.028 or (nw >= 0.055 and nh <= 0.025)
                
                if is_history and cur_round >= 2:
                    if glued:
                        ended = max(0, cur_round - 1)
                        usable = tokens[:ended] if ended else []
                        for slot_i, tok in enumerate(usable):
                            bid_val = self._parse_seat_amount(tok)
                            if bid_val > 0:
                                pending_hist.append((idx, slot_i + 1, bid_val))
                    else:
                        bid_val = self._parse_seat_amount(tokens[0])
                        hist_round = self._hist_round_from_x(nx, cur_round, origin_x=hist_origin)
                        if bid_val > 0 and hist_round:
                            pending_hist.append((idx, hist_round, bid_val))
                elif cur_round > 0:
                    bid_val = self._parse_seat_amount(tokens[0] if tokens else compact)
                    if bid_val >= 0:
                        prev_cur = seats[idx].get("currentBid")
                        seats[idx]["currentBid"] = max(int(prev_cur or 0), bid_val) if prev_cur is not None else bid_val
                continue
                
            if compact.lower() in skip:
                continue
            if len(compact) < 1 or len(compact) > 14:
                continue
            if len(compact) == 1 and self._clean_settlement_winner_name(compact) is None:
                continue
            if re.fullmatch(r"[\d,，.．、KkWwMm万千%'\"`’.\-]+", compact):
                continue
            if any(tok in compact for tok in ("回合", "情报", "仪器", "出价", "放弃", "图鉴", "标准", "资产", "估价", "表情", "短语", "UID", "展示", "藏品", "概率", "宝箱", "随机", "品质", "轮廓")):
                continue
            seats[idx]["name"] = compact

        for idx, hist_round, bid_val in pending_hist:
            name = seats[idx].get("name")
            if name and bid_val > 0 and hist_round:
                self._commit_round_finals(finals, hist_round, {name: bid_val})

        if cur_round:
            live = {}
            for seat in seats:
                name = seat.get("name")
                current = seat.get("currentBid")
                if name and current:
                    live[name] = int(current)
            if live:
                self._commit_round_finals(finals, cur_round, live)

        for seat in seats:
            current = seat.get("currentBid")
            seat["bid"] = int(current or 0)

        self.current_context["finalBids"] = finals
        self.current_context["historicalBids"] = {
            name: {rk: int(rv) for rk, rv in rounds.items() if int(rk) < cur_round}
            for name, rounds in finals.items()
            if any(int(rk) < cur_round for rk in rounds)
        }
        self.current_context["seats"] = seats
        named = [s for s in seats if s.get("name")]
        self.current_context["opponents"] = [
            {"slot": s["slot"], "name": s["name"], "bid": s["bid"], "currentBid": s.get("currentBid")}
            for s in named
        ]
        me = next((s for s in seats if s.get("isMe") and s.get("name")), None)
        if me:
            self.current_context["myName"] = me["name"]
            self.current_context["myBid"] = me["bid"]
        else:
            self.current_context["myName"] = None
            self.current_context["myBid"] = 0

    def _final_bids_from_history(self, hist: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, int]]:
        src = hist if hist is not None else (self.current_context.get("historicalBids") or {})
        out: Dict[str, Dict[str, int]] = {}
        for name, rounds in (src or {}).items():
            if not name or not isinstance(rounds, dict):
                continue
            cleaned = {}
            for key, val in rounds.items():
                try:
                    cleaned[str(int(key))] = int(val)
                except Exception:
                    continue
            if cleaned:
                out[name] = cleaned
        return out

    def _round_final_bids(self, round_no: int) -> Dict[str, int]:
        key = str(int(round_no or 0))
        finals = self.current_context.get("finalBids") or self._final_bids_from_history()
        return {
            name: int(rounds.get(key) or 0)
            for name, rounds in finals.items()
            if int(rounds.get(key) or 0) > 0
        }

    def _refresh_leader_from_seats(self) -> None:
        cur_round = int(self.current_context.get("round") or 0)
        finals = self._round_final_bids(cur_round) if cur_round > 0 else {}
        if not finals:
            self.current_context["currentLeaderBid"] = 0
            self.current_context["leaderName"] = None
            self.current_context["leaderTies"] = []
            self.current_context["isMyLead"] = False
            return
        top = max(finals.values())
        ties = [name for name, bid in finals.items() if bid == top]
        self.current_context["currentLeaderBid"] = top
        self.current_context["leaderTies"] = ties
        if len(ties) == 1:
            self.current_context["leaderName"] = ties[0]
            me = self.current_context.get("myName")
            self.current_context["isMyLead"] = bool(me and me == ties[0])
        else:
            self.current_context["leaderName"] = None
            me = self.current_context.get("myName")
            self.current_context["isMyLead"] = bool(me and me in ties)

    def _ocr_full_text(self, ocr_results: List[Any]) -> str:
        return " ".join([(t or "").strip() for _, t, _ in ocr_results if t])

    def _identify_lobby_character(self, frame: np.ndarray, force: bool = False) -> Dict[str, Any]:
        """角色热路径：闭集模板。只有模板失败才允许 OCR 兜底。"""
        hit = self.character_matcher.identify(frame)
        self.char_template_scan_count = self.character_matcher.scan_count
        if hit.get("accepted") and hit.get("character"):
            return hit
        if self._ocr_engine is None:
            self._warm_ocr_async()
            return hit
        char_ocr = self._ocr_rois(frame, ("lobby_character_chip",))
        parsed = self._parse_lobby_character(char_ocr)
        if parsed:
            hit = {
                "character": parsed,
                "score": hit.get("score") or 0.0,
                "secondScore": hit.get("secondScore") or 0.0,
                "accepted": True,
                "source": "ocr_fallback",
                "scores": hit.get("scores") or {},
            }
        return hit

    def _identify_lobby_venue(self, frame: np.ndarray) -> Dict[str, Any]:
        hit = self.venue_matcher.identify(frame)
        self.venue_template_scan_count = self.venue_matcher.scan_count
        if hit.get("accepted") and hit.get("venueLabel"):
            from business_sot import venue_entry_cost
            meta = hit.get("meta") or {}
            venue = meta.get("venue") or hit.get("venueLabel")
            return {
                "venue": venue,
                "venueKey": meta.get("venueKey"),
                "venueLabel": meta.get("venueLabel") or hit.get("venueLabel"),
                "entryCost": venue_entry_cost(venue),
                "score": hit.get("score"),
                "secondScore": hit.get("secondScore"),
                "source": "template",
            }
        if self._ocr_engine is None:
            self._warm_ocr_async()
            return {"source": hit.get("source") or "unrecognized", "score": hit.get("score"), "secondScore": hit.get("secondScore")}
        parsed = self._parse_lobby_loadout(self._ocr_rois(frame, ("lobby_venue_chip",)))
        if parsed.get("venue"):
            parsed["source"] = "ocr_fallback"
            parsed["score"] = hit.get("score")
            parsed["secondScore"] = hit.get("secondScore")
            return parsed
        return {"source": "unrecognized", "score": hit.get("score"), "secondScore": hit.get("secondScore")}

    def _identify_lobby_tool(self, frame: np.ndarray) -> Dict[str, Any]:
        hit = self.tool_matcher.identify(frame)
        self.tool_template_scan_count = self.tool_matcher.scan_count
        if hit.get("accepted") and hit.get("toolGroup"):
            return {
                "toolGroup": hit.get("toolGroup"),
                "score": hit.get("score"),
                "secondScore": hit.get("secondScore"),
                "source": "template",
            }
        if self._ocr_engine is None:
            self._warm_ocr_async()
            return {"source": hit.get("source") or "unrecognized", "score": hit.get("score"), "secondScore": hit.get("secondScore")}
        parsed = self._parse_lobby_loadout(self._ocr_rois(frame, ("lobby_tool_chip",)))
        if parsed.get("toolGroup"):
            return {
                "toolGroup": parsed.get("toolGroup"),
                "source": "ocr_fallback",
                "score": hit.get("score"),
                "secondScore": hit.get("secondScore"),
            }
        return {"source": "unrecognized", "score": hit.get("score"), "secondScore": hit.get("secondScore")}

    def _refresh_lobby_loadout(self, frame: np.ndarray, force: bool = False) -> None:
        """大厅已确认：角色/会场/仪器优先闭集模板，缺样本才 OCR。"""
        now = time.monotonic()
        have_all = (
            self.current_context.get("lobbyCharacter")
            and self.current_context.get("lobbyToolGroup")
            and self.current_context.get("lobbyVenue")
        )
        if not force and have_all and (now - getattr(self, "_last_loadout_ts", 0.0)) < 0.25:
            return
        parsed: Dict[str, Any] = {}
        char_hit = self._identify_lobby_character(frame, force=force)
        if char_hit.get("character"):
            parsed["character"] = char_hit["character"]
            parsed["characterScore"] = char_hit.get("score")
            parsed["characterSecondScore"] = char_hit.get("secondScore")
            parsed["characterSource"] = char_hit.get("source") or "template"
        elif force:
            parsed["character"] = None
            parsed["characterScore"] = char_hit.get("score")
            parsed["characterSecondScore"] = char_hit.get("secondScore")
            parsed["characterSource"] = char_hit.get("source") or "unrecognized"
            parsed["clearCharacter"] = True

        venue_hit = self._identify_lobby_venue(frame)
        if venue_hit.get("venue"):
            parsed.update({k: venue_hit[k] for k in ("venue", "venueKey", "venueLabel", "entryCost") if venue_hit.get(k) is not None})
            parsed["venueSource"] = venue_hit.get("source")
            parsed["venueScore"] = venue_hit.get("score")
        elif force:
            parsed["clearVenue"] = True
            parsed["venueSource"] = venue_hit.get("source") or "unrecognized"

        tool_hit = self._identify_lobby_tool(frame)
        if tool_hit.get("toolGroup"):
            parsed["toolGroup"] = tool_hit["toolGroup"]
            parsed["toolSource"] = tool_hit.get("source")
            parsed["toolScore"] = tool_hit.get("score")
        elif force:
            parsed["clearTool"] = True
            parsed["toolSource"] = tool_hit.get("source") or "unrecognized"

        if not any(parsed.get(k) for k in ("character", "venue", "toolGroup")) and not any(
            parsed.get(k) for k in ("clearCharacter", "clearVenue", "clearTool")
        ):
            return
        self._last_loadout_ts = now
        self._apply_lobby_loadout(parsed)

    def _apply_lobby_loadout(self, lobby_info: Dict[str, Any]) -> None:
        self._match_exit_hold = 0
        self.current_context["scene"] = SCENE_AUCTION_LOBBY
        self.current_context["sceneLabel"] = SCENE_LABELS[SCENE_AUCTION_LOBBY]
        self.current_context["auctionEntryVisible"] = True
        self.current_context["inLobby"] = True
        self.current_context["isLoading"] = False
        self.current_context["inAuction"] = False
        self.current_context["isSettlement"] = False
        self.current_context["round"] = 0
        self.current_context["loadingPercent"] = None
        self.current_context["loadingVenue"] = None
        if lobby_info.get("clearVenue"):
            self.current_context["venue"] = None
            self.current_context["lobbyVenue"] = None
            self.current_context["lobbyVenueKey"] = None
            self.current_context["lobbyVenueLabel"] = None
            self.current_context["lobbyEntryCost"] = None
            self.current_context["lobbyVenueSource"] = lobby_info.get("venueSource") or "unrecognized"
        elif lobby_info.get("venue"):
            from business_sot import canonicalize_venue, venue_entry_cost
            canonical_venue = canonicalize_venue(lobby_info.get("venue") or lobby_info.get("venueLabel") or lobby_info.get("venueKey"))
            self.current_context["venue"] = canonical_venue
            self.current_context["lobbyVenue"] = canonical_venue
            self.current_context["lobbyVenueKey"] = lobby_info.get("venueKey")
            self.current_context["lobbyVenueLabel"] = lobby_info.get("venueLabel") or canonical_venue
            self.current_context["lobbyEntryCost"] = venue_entry_cost(canonical_venue)
            if lobby_info.get("venueSource"):
                self.current_context["lobbyVenueSource"] = lobby_info.get("venueSource")
            if lobby_info.get("venueScore") is not None:
                self.current_context["lobbyVenueScore"] = lobby_info.get("venueScore")
        if lobby_info.get("clearTool"):
            self.current_context["lobbyToolGroup"] = None
            self.current_context["lobbyToolSource"] = lobby_info.get("toolSource") or "unrecognized"
        elif lobby_info.get("toolGroup"):
            observed = lobby_info["toolGroup"]
            self.current_context["lobbyToolGroup"] = observed
            from business_sot import canonicalize_tool_group
            canonical_tool = canonicalize_tool_group(observed)
            self.current_context["toolGroup"] = canonical_tool
            if lobby_info.get("toolSource"):
                self.current_context["lobbyToolSource"] = lobby_info.get("toolSource")
            if lobby_info.get("toolScore") is not None:
                self.current_context["lobbyToolScore"] = lobby_info.get("toolScore")
        if lobby_info.get("clearCharacter"):
            self.current_context["lobbyCharacter"] = None
            self.current_context["character"] = None
            self.current_context["lobbyCharacterScore"] = lobby_info.get("characterScore")
            self.current_context["lobbyCharacterSecondScore"] = lobby_info.get("characterSecondScore")
            self.current_context["lobbyCharacterSource"] = lobby_info.get("characterSource") or "unrecognized"
        elif lobby_info.get("character"):
            self.current_context["lobbyCharacter"] = lobby_info["character"]
            self.current_context["character"] = lobby_info["character"]
            if lobby_info.get("characterScore") is not None:
                self.current_context["lobbyCharacterScore"] = lobby_info.get("characterScore")
            if lobby_info.get("characterSecondScore") is not None:
                self.current_context["lobbyCharacterSecondScore"] = lobby_info.get("characterSecondScore")
            if lobby_info.get("characterSource"):
                self.current_context["lobbyCharacterSource"] = lobby_info.get("characterSource")

    def _try_release_locked_match(self, fast: Optional[Dict[str, Any]] = None) -> bool:
        """连续若干帧看到同一导航快检，才允许离开已确认的局内/结算。"""
        if self.current_context.get("scene") not in LOCKED_MATCH_SCENES:
            self._match_exit_hold = 0
            return False
        candidate = (fast or {}).get("scene")
        if candidate not in PRE_AUCTION_NAV_SCENES:
            self._match_exit_hold = 0
            return False
        self._match_exit_hold += 1
        if self._match_exit_hold < MATCH_EXIT_HOLD_FRAMES:
            return False
        self._match_exit_hold = 0
        self._nav_hold_frames = 0
        self._apply_pre_auction_scene(fast or {"scene": candidate})
        return True

    def _locked_match_blocks_ocr_nav(self, scene_info: Dict[str, Any]) -> bool:
        """OCR 导航分类同样不能单帧拆掉已确认局内/结算。大厅硬锚点走 _parse_lobby。"""
        if self.current_context.get("scene") not in LOCKED_MATCH_SCENES:
            return False
        candidate = scene_info.get("scene")
        if candidate not in PRE_AUCTION_NAV_SCENES:
            return False
        # 需要连续命中才放行；单帧闲趣/大世界字样不够
        return not self._try_release_locked_match(scene_info)

    def _apply_pre_auction_scene(self, scene_info: Dict[str, Any]) -> None:
        """写入都市大亨 / 都市闲趣等对局前场景，清空大厅/载入伪状态。"""
        self._match_exit_hold = 0
        scene = scene_info["scene"]
        self.current_context["scene"] = scene
        self.current_context["sceneLabel"] = SCENE_LABELS.get(scene, scene)
        self.current_context["auctionEntryVisible"] = bool(scene_info.get("auctionEntryVisible", False))
        self.current_context["inLobby"] = scene == SCENE_AUCTION_LOBBY
        self.current_context["isLoading"] = False
        self.current_context["inAuction"] = False
        self.current_context["isSettlement"] = False
        self.current_context["round"] = 0
        self.current_context["loadingPercent"] = None
        self.current_context["loadingVenue"] = None
        if scene == SCENE_AUCTION_LOBBY:
            self.current_context["loadingDirection"] = "to_auction"
        self._end_match_on_lobby_or_egress()

    def _classify_pre_auction_scene(self, ocr_results: List[Any], screen_w: int = 1920, screen_h: int = 1080) -> Dict[str, Any]:
        """
        对局前导航场景分类（与拍卖大厅互斥）:
          OPEN_WORLD         — 大世界探索（小地图 + F5 都市大亨入口）
          CITY_TYCOON_HUB    — 都市大亨总览（建筑点选：都市闲趣等）
          CITY_LEISURE_MENU  — 都市闲趣活动列表；滚到底可见「即刻落槌」入口卡

        注意：闲趣列表里的「即刻落槌」卡片 ≠ 拍卖大厅；大厅必须另有「开始匹配」等硬锚点。
        """
        filtered = self._filter_ocr_exclude_hud(ocr_results, screen_w, screen_h)
        full_text = self._ocr_full_text(filtered)
        compact = re.sub(r"\s+", "", full_text)

        # Loadout dialogs contain the same skill names as live intel cards.
        # Their explicit menu title is navigation evidence, not a live round.
        if "竞拍帮手列表" in compact and ("技能描述" in compact or "确认" in compact):
            return {"scene": SCENE_AUCTION_LOBBY, "auctionEntryVisible": False}

        has_start_match = "开始匹配" in compact
        has_select_venue = "选择会场" in compact
        has_exhibit = "展览柜收益" in compact
        # 大厅硬锚点已足够时，不再归类为上层菜单
        if has_start_match or (has_select_venue and ("当前" in compact or has_exhibit)):
            return {"scene": SCENE_UNKNOWN, "auctionEntryVisible": False}

        # 左上标题胶囊优先：都市大亨总览（不要等中屏建筑字）
        title_hub = self._has_top_left_title(ocr_results, screen_w, screen_h, ("都市大亨", "大亨等级"))
        if title_hub:
            return {"scene": SCENE_CITY_TYCOON_HUB, "auctionEntryVisible": False}

        # —— 都市闲趣列表 ——
        leisure_title = (
            "都市闲趣" in compact
            and (
                "MENU" in full_text.upper()
                or "大亨计划" in compact
                or "激励金" in compact
                or "本期剩余时间" in compact
            )
        )
        leisure_grid_hits = sum(
            1 for k in (
                "同城派送", "车辆赛事", "店长特供", "雨燕出行", "粉爪大劫案",
                "海上钓客", "小小麻将", "混除方块", "超强音", "格斗俱乐部",
                "排球之星", "徊影憧憧", "即刻落槌",
            ) if k in compact
        )
        if leisure_title or leisure_grid_hits >= 2:
            entry_visible = "即刻落槌" in compact
            return {
                "scene": SCENE_CITY_LEISURE_MENU,
                "auctionEntryVisible": entry_visible,
            }

        # —— 都市大亨总览 ——
        hub_hits = sum(
            1 for k in (
                "都市大亨", "大亨等级", "CITYTYCOON", "CITY TYCOON",
                "猎人交易所", "富爪榜", "车辆赛事", "车库", "房产",
            ) if k.replace(" ", "") in compact.replace(" ", "") or k in compact or k in full_text.upper()
        )
        # 「都市闲趣」在总览里是建筑名；在 MENU 列表里已被上面分支吃掉
        if "都市大亨" in compact or "大亨等级" in compact or hub_hits >= 2:
            # 排除已进入其它全屏玩法但偶然扫到残留字的情况
            if not any(k in compact for k in ("开始匹配", "第1回合", "第 1 回合", "竞拍结束")):
                return {
                    "scene": SCENE_CITY_TYCOON_HUB,
                    "auctionEntryVisible": False,
                }

        # —— 大世界探索（步行/载具通用 HUD）——
        open_world = self._classify_open_world(ocr_results, screen_w, screen_h, compact)
        if open_world:
            return open_world

        return {"scene": SCENE_UNKNOWN, "auctionEntryVisible": False}

    def _classify_open_world(
        self,
        ocr_results: List[Any],
        screen_w: int,
        screen_h: int,
        compact_filtered: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        大世界 HUD 特征（步行阳台/街道、骑乘载具均适用）:
          - 左上角小地图旁「F5」= 都市大亨入口
          - 顶栏快捷键 F1~F4 / B / C / ESC
          - 左下「Enter」聊天、UID
          - 底栏血量 n/n；载具时 KM/H

        注意：游戏自带顶栏快捷键在画面右上，不能用战术 HUD 过滤区域裁掉后再判。
        """
        # 已进入菜单/拍卖路径时不判大世界
        if any(k in (compact_filtered or "") for k in (
            "都市大亨", "大亨等级", "都市闲趣", "开始匹配", "即刻落槌",
            "选择会场", "MENU", "大亨计划", "激励金", "竞拍结束", "第1回合",
        )):
            return None

        has_f5 = False
        has_f5_top_left = False
        has_uid = False
        has_enter = False
        has_hp_bar = False
        has_speedo = False
        hotkey_hits = set()

        for box, text, _score in ocr_results:
            raw = (text or "").strip()
            if not raw:
                continue
            t_up = raw.upper().replace(" ", "")
            x_min = min(b[0] for b in box)
            y_min = min(b[1] for b in box)
            y_max = max(b[1] for b in box)
            nx = x_min / max(1, screen_w)
            ny = y_min / max(1, screen_h)
            ny_c = ((y_min + y_max) / 2.0) / max(1, screen_h)

            # 排除疑似本助手战术 HUD 浮层区（右上偏中），避免自回环
            # 但保留游戏原生顶栏热键带 (ny < 0.12)
            if nx >= 0.70 and 0.12 <= ny <= 0.50:
                continue

            if re.search(r"(?<!\w)F5(?!\w)", t_up) or t_up == "F5":
                has_f5 = True
                if nx <= 0.28 and ny <= 0.28:
                    has_f5_top_left = True

            for hk in ("F1", "F2", "F3", "F4"):
                if re.search(rf"(?<!\w){hk}(?!\w)", t_up) or t_up == hk:
                    if ny <= 0.18:
                        hotkey_hits.add(hk)

            if t_up in ("ESC", "ESCAPE") or re.search(r"(?<!\w)ESC(?!\w)", t_up):
                if ny <= 0.18:
                    hotkey_hits.add("ESC")
            if t_up in ("B", "C") and ny <= 0.18 and nx >= 0.55:
                hotkey_hits.add(t_up)

            if "UID" in t_up or re.search(r"UID[:：]?\s*\d{6,}", raw, re.I):
                has_uid = True
            if re.search(r"(?<!\w)ENTER(?!\w)", t_up) or raw in ("Enter", "enter"):
                if ny >= 0.85 and nx <= 0.25:
                    has_enter = True

            # 底栏 HP：任意角色的「当前/上限」，如 22101/22101、25139/25139
            if ny_c >= 0.82 and re.search(r"\d{3,5}\s*/\s*\d{3,5}", raw):
                has_hp_bar = True

            # 载具时速
            if any(k in t_up for k in ("KM/H", "KMH", "RPM")) or re.search(r"\bR0{2,4}\b", t_up):
                has_speedo = True

        score = 0
        if has_f5_top_left:
            score += 3
        elif has_f5:
            score += 2
        if has_uid:
            score += 2
        if has_enter:
            score += 1
        if has_hp_bar:
            score += 1
        if has_speedo:
            score += 1
        score += min(2, len(hotkey_hits))

        # 大世界必须看到 F5。UID 在都市大亨/闲趣也有，禁止无 F5 保底。
        strong = has_f5_top_left and (has_uid or has_enter or has_hp_bar or has_speedo or len(hotkey_hits) >= 1)
        medium = has_f5 and score >= 3
        if strong or medium:
            return {"scene": SCENE_OPEN_WORLD, "auctionEntryVisible": False}
        return None

    def _has_top_left_title(
        self,
        ocr_results: List[Any],
        screen_w: int,
        screen_h: int,
        keywords: Tuple[str, ...],
    ) -> bool:
        for box, text, _score in ocr_results:
            raw = (text or "").strip()
            if not raw or not any(k in raw for k in keywords):
                continue
            x_min = min(b[0] for b in box)
            y_min = min(b[1] for b in box)
            nx = x_min / max(1, screen_w)
            ny = y_min / max(1, screen_h)
            if nx <= 0.40 and ny <= 0.22:
                return True
        return False

    def _parse_loading(self, ocr_results: List[Any], screen_w: int = 1920, screen_h: int = 1080) -> Dict[str, Any]:
        """
        解析对局匹配/加载过场界面 (进度条 / 真实地图名)
        严格过滤右上角 HUD 区域，杜绝自身 OCR 自回环误判
        """
        data = {
            "isLoading": False,
            "percent": None,
            "venue": None
        }

        # 拍卖强信号（四席出价、倒计时、回合、已知拍卖HUD等）：一旦检测到，必须绝对否决 AUCTION_LOADING
        has_auction_strong_signal = False
        has_loading_layout_evidence = False

        # 已知合法场馆/venue whitelist（严禁将任意引号中文如「泪滴」「万花筒」当场馆）
        valid_loading_venues = {
            "初级场 · 海贝场", "海贝场", "海贝商会",
            "中级场 · 珊瑚场", "珊瑚场", "珊瑚商会",
            "高级场 · 真珠场", "真珠场", "真珠商会", "珍珠场",
            "普通场 · 绿洲场", "绿洲场", "绿洲商会",
            "高级场 · 极光场", "极光场", "极光商会", "极光拍卖行",
            "粉爪银行", "海特洛市",
        }

        for box, text, score in ocr_results:
            t = text.strip()
            x_min = min(b[0] for b in box)
            y_min = min(b[1] for b in box)
            nx = x_min / max(1, screen_w)
            ny = y_min / max(1, screen_h)

            # 拍卖强信号检测：回合标、拍卖倒计时、情报标、出价操作等
            if re.search(r"(?:竞拍)?第\s*[1-9]\s*回[合回合]", t) or re.search(r"第\s*[1-9]\s*回合", t):
                has_auction_strong_signal = True
            elif re.search(r"00[:：]\d{2}", t) and 0.15 <= nx <= 0.85 and ny <= 0.35:
                has_auction_strong_signal = True
            elif any(k in t for k in ["公开情报", "千眼其一", "品质均价", "平均价值", "出价", "放弃", "跟注", "加价"]):
                has_auction_strong_signal = True

            # 排除右上角 HUD 区域 (X >= 0.70, Y <= 0.45)
            if nx >= 0.70 and ny <= 0.45:
                continue

            # 1. 识别右下角 0%~100% 载入进度 (X >= 0.75, Y >= 0.70)
            m_pct = re.search(r"(\d{1,3})%", t)
            if m_pct and nx >= 0.75 and ny >= 0.70:
                val = int(m_pct.group(1))
                if 0 <= val <= 100:
                    data["percent"] = val
                    has_loading_layout_evidence = True

            # 2. 识别场地场馆名称 (必须匹配已知合法场馆白名单)
            m_venue = re.search(r"「([\u4e00-\u9fa5]{2,8})」", t)
            if m_venue:
                v_name = m_venue.group(1)
                if v_name in valid_loading_venues:
                    data["venue"] = v_name

            # 3. 识别过场特色背景词 / 右侧 Lore 姓名条
            if any(k in t for k in [
                "德沃夏克集团", "德沃夏克", "海特洛市", "正在进入对局",
                "乔望尼", "粉爪银行", "INFO",
            ]):
                has_loading_layout_evidence = True

        # 拍卖强信号必须否决 loading
        if has_auction_strong_signal:
            data["isLoading"] = False
            data["percent"] = None
            data["venue"] = None
            return data

        # loading 场景必须具备正向布局证据，或同时有进度与白名单场馆
        if has_loading_layout_evidence:
            data["isLoading"] = True
        elif data.get("venue") is not None and data.get("percent") is not None:
            data["isLoading"] = True
        else:
            data["isLoading"] = False
            data["venue"] = None
            data["percent"] = None

        return data

    def _parse_lobby(self, ocr_results: List[Any], screen_w: int = 1920, screen_h: int = 1080) -> Dict[str, Any]:
        """
        解析拍卖大厅/首页备战界面的前置配置 (会场、品鉴仪器组、助手角色)

        硬锚点（满足其一即可）:
          - 「开始匹配」
          - 「选择会场」+（「当前」会场 或 底部「展览柜收益/藏品图鉴」）
          - 「展览柜收益」+「藏品图鉴/藏品仓库」+ 会场相关

        禁止: 仅因闲趣列表出现「即刻落槌」卡片就判定为大厅。
        """
        data = {
            "inLobby": False,
            "venue": None,
            "venueKey": None,
            "venueLabel": None,
            "toolGroup": None,
            "character": None,
            "entryCost": None
        }

        filtered_results = self._filter_ocr_exclude_hud(ocr_results, screen_w, screen_h)
        full_text = self._ocr_full_text(filtered_results)
        compact = re.sub(r"\s+", "", full_text)

        # 都市闲趣列表优先排除：有 MENU/激励金 且 无开始匹配 → 不是大厅
        in_leisure_menu = (
            ("都市闲趣" in compact and ("MENU" in full_text.upper() or "激励金" in compact or "大亨计划" in compact))
            or sum(1 for k in ("同城派送", "粉爪大劫案", "小小麻将", "格斗俱乐部", "排球之星") if k in compact) >= 2
        )
        has_start_match = "开始匹配" in compact
        if in_leisure_menu and not has_start_match:
            return data

        has_select_venue = "选择会场" in compact
        has_exhibit_bar = "展览柜收益" in compact
        has_catalog_bar = ("藏品图鉴" in compact) or ("藏品仓库" in compact)
        has_current_venue = bool(re.search(r"当前[：:\s]*", compact)) and any(
            k in compact for k in ("海贝", "珊瑚", "真珠", "珍珠", "海贝场", "珊瑚场", "真珠场")
        )
        has_auction_title = "即刻落槌" in compact
        has_venue_picker = (
            "请选择一个拍卖场" in compact
            or "AUCTIONHOUSE" in compact.replace(" ", "").upper()
            or sum(1 for k in ("海贝场", "珊瑚场", "真珠场", "珍珠场") if k in compact) >= 2
        )

        hard_lobby = (
            has_start_match
            or has_venue_picker
            or (has_select_venue and (has_current_venue or has_exhibit_bar or has_auction_title))
            or (has_exhibit_bar and has_catalog_bar and (has_auction_title or has_current_venue or has_select_venue))
        )
        if not hard_lobby:
            return data

        data["inLobby"] = True
        data.update({k: v for k, v in self._parse_lobby_loadout(ocr_results).items() if v is not None})
        return data

    def _has_live_auction_evidence(
        self,
        ocr_results: List[Any],
        screen_w: int = 1920,
        screen_h: int = 1080,
    ) -> bool:
        """Return whether one OCR frame visibly belongs to a live round.

        This is deliberately an evidence gate, not a scene classifier.  It is
        used only to resolve a conflict while the prior frame is already a
        locked IN_AUCTION match.  Settlement/lobby frames without live-round
        text therefore keep the existing fail-closed boundary behavior.
        """
        for box, text, _score in ocr_results or []:
            raw = str(text or "")
            compact = re.sub(r"\s+", "", raw)
            x_min = min((point[0] for point in box), default=0)
            y_min = min((point[1] for point in box), default=0)
            nx = x_min / max(1, screen_w)
            ny = y_min / max(1, screen_h)

            # The round label and public-information cards are unique to the
            # in-auction canvas.  The action labels are included because the
            # user's fixed 1920x1080 scene visibly exposes 放弃/出价 even
            # before any non-zero bid exists.
            if re.search(r"(?:竞拍)?第\s*[1-9]\s*回[合回合]", raw):
                return True
            if any(marker in compact for marker in ("公开情报", "千眼其一")):
                return True
            if any(marker in compact for marker in ("放弃", "出价", "跟注", "加价")):
                return True
            if re.search(r"00[:：]\d{2}", compact) and 0.15 <= nx <= 0.85 and ny <= 0.40:
                return True
        return False

    def _parse_lobby_loadout(self, ocr_results: List[Any]) -> Dict[str, Any]:
        """从 OCR 文本提取会场 / 仪器组 / 助手。不依赖「开始匹配」硬锚点。"""
        data = {
            "venue": None,
            "venueKey": None,
            "venueLabel": None,
            "toolGroup": None,
            "character": None,
            "entryCost": None,
        }
        full_text = self._ocr_full_text(ocr_results)
        compact = re.sub(r"\s+", "", full_text)

        # 会场只认「当前：珊瑚场」这种当前选中行。选场页三列同时出现时禁止抓第一个场名。
        venue_aliases = (
            (("珊瑚场", "珊湖场", "理瑚场", "珊瑚场"), "shanhu", "中级场 · 珊瑚场", "珊瑚场"),
            (("海贝场",), "haibei", "初级场 · 海贝场", "海贝场"),
            (("真珠场", "珍珠场"), "zhenzhu", "高级场 · 真珠场", "真珠场"),
        )

        def apply_venue(key, venue, label):
            from business_sot import canonicalize_venue, venue_entry_cost
            data["venue"] = canonicalize_venue(venue or label)
            data["venueKey"] = key
            data["venueLabel"] = label
            data["entryCost"] = venue_entry_cost(data["venue"])

        m_venue = re.search(r"当前[：:\s]*([\u4e00-\u9fa5]{2,6}场?)", compact)
        if m_venue:
            v_text = m_venue.group(1)
            for aliases, key, venue, label in venue_aliases:
                if any(a in v_text or a.replace("场", "") in v_text for a in aliases):
                    apply_venue(key, venue, label)
                    break
        if not data["venue"]:
            for _, text, _ in ocr_results:
                clean_t = re.sub(r"\s+", "", text or "")
                if "当前" not in clean_t:
                    continue
                for aliases, key, venue, label in venue_aliases:
                    if any(a in clean_t for a in aliases):
                        apply_venue(key, venue, label)
                        break
                if data["venue"]:
                    break

        # 大厅仪器名是观测字段；0.6 solver 的 toolGroup 只有 group1/group2。
        # 「吸级」等只在识别容错层，不进业务闭集。
        instrument_aliases = (
            ("高级品鉴仪器组", ("高级品鉴仪器组", "高级品鉴", "吸级品鉴仪器组", "吸品鉴仪器组", "吸级品鉴")),
            ("基础品鉴仪器组", ("基础品鉴仪器组", "基础品鉴")),
            ("中级品鉴仪器组", ("中级品鉴仪器组", "中级品鉴")),
        )
        for name, aliases in instrument_aliases:
            if any(a in compact or a in full_text for a in aliases):
                data["toolGroup"] = name
                break
        if not data.get("toolGroup"):
            m_tool = re.search(r"([\u4e00-\u9fa5]{2,8}仪器组)", full_text)
            if m_tool and "品鉴" in m_tool.group(1) and "吸" not in m_tool.group(1):
                data["toolGroup"] = m_tool.group(1).strip()

        data["character"] = self._parse_lobby_character(ocr_results)
        return data

    def _parse_lobby_character(self, ocr_results: List[Any]) -> Optional[str]:
        """OCR 兜底：只认完整角色名，不做短词/单字猜测。"""
        known = (
            "哈尼亚",
            "哈尼娅",
            "达芙蒂尔",
            "达芙帝尔",
            "小吱",
            "埃德嘉",
            "哈索尔",
            "九原",
            "浔",
            "阿德勒",
        )
        canon = {
            "哈尼娅": "哈尼亚",
            "达芙帝尔": "达芙蒂尔",
        }
        for _, text, _ in ocr_results:
            t = re.sub(r"\s+", "", text or "")
            if not t:
                continue
            for name in known:
                if name in t:
                    return canon.get(name, name)
        compact = re.sub(r"\s+", "", self._ocr_full_text(ocr_results))
        for name in known:
            if name in compact:
                return canon.get(name, name)
        return None

    @staticmethod
    def _clean_settlement_winner_name(text: str) -> Optional[str]:
        raw = str(text or "").strip()
        if not raw:
            return None

        # Fail-closed: exclude numbers / amounts / currencies
        if parse_money_amount(raw) > 0:
            return None
        if re.search(r"^\d+$", raw):
            return None
        if re.search(r"^[-+−－]?\d{1,3}(,\d{3})*(\.\d+)?$", raw):
            return None

        # Fail-closed: exclude single grade letters
        if raw.upper() in {"S", "A", "B", "C", "D", "E", "F", "SS", "SSS"}:
            return None

        # Fail-closed: exclude fixed settlement UI labels & system keywords
        fixed_labels = (
            "竞拍结束", "成交价", "最终成交价", "实际价值", "实际总价值",
            "收益", "实际收益", "净利润", "竞拍表现", "竞拍帮手",
            "当前估价", "我的资产", "奖励金", "分享到", "呗果",
            "跳过", "动画", "退出", "藏品", "图鉴", "出售", "价值",
            "落槌无悔", "血本无归", "UID", "fps", "D3D", "FPS"
        )
        if any(lbl in raw for lbl in fixed_labels):
            return None

        # Fail-closed: exclude placeholder strings
        from auto_archiver import FORBIDDEN_WINNER_PLACEHOLDERS
        if raw in FORBIDDEN_WINNER_PLACEHOLDERS:
            return None

        # Strip common leading/trailing symbols/colons
        cleaned = re.sub(r"^[：:·\s]+|[：:·\s]+$", "", raw).strip()
        if not cleaned:
            return None
        if re.match(r"^[\W_]+$", cleaned):
            return None
        if len(cleaned) > 20:
            return None

        return cleaned

    def _parse_settlement(
        self,
        ocr_results: List[Any],
        screen_w: int = 1920,
        screen_h: int = 1080,
        frame: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        data = {"isSettlement": False, "clearingPrice": None, "actualTotal": None, "profit": None, "winner": None}
        full_text = " ".join([t for _, t, _ in ocr_results])

        if not ("竞拍结束" in full_text or "最终成交价" in full_text or "实际价值" in full_text):
            return data

        data["isSettlement"] = True
        # Running item-reveal totals can pause for multiple inference frames.
        # The payout footer / final grade appears only after that animation.
        # A stable intermediate number alone is not settlement truth.
        data['animationComplete'] = any(
            ((('奖励金' in re.sub(r'\s+', '', text) or '奖金获取' in re.sub(r'\s+', '', text))
              and (box[0][1] + box[2][1]) / (2 * max(1, screen_h)) > .84)
             or (str(text).strip().upper() in {'S', 'SS', 'SSS', 'A', 'B', 'C', 'D'}
                 and (box[0][1] + box[2][1]) / (2 * max(1, screen_h)) > .60
                 and (box[0][0] + box[2][0]) / (2 * max(1, screen_w)) < .28))
            for box, text, score in ocr_results if score >= .65)

        # Winner name recognition (bounded ROI: below "竞拍结束", above 3 metric cards, left of "竞拍帮手")
        winner_candidates = []
        for box, text, score in ocr_results:
            raw = (text or "").strip()
            if not raw:
                continue
            y_center = (box[0][1] + box[2][1]) / 2.0
            x_center = (box[0][0] + box[2][0]) / 2.0
            nx = x_center / max(1, screen_w)
            ny = y_center / max(1, screen_h)
            if 0.06 <= nx <= 0.42 and 0.20 <= ny <= 0.40:
                cleaned = self._clean_settlement_winner_name(raw)
                if cleaned:
                    winner_candidates.append((score, ny, cleaned))

        if not winner_candidates and frame is not None and getattr(frame, "size", 0) > 0:
            rx1 = int(0.06 * screen_w)
            rx2 = int(0.42 * screen_w)
            ry1 = int(0.20 * screen_h)
            ry2 = int(0.40 * screen_h)
            crop = frame[ry1:ry2, rx1:rx2]
            if crop.size > 0 and min(crop.shape[:2]) >= 10:
                crop_res, _ = self.ocr(crop)
                for cbox, ctext, cscore in (crop_res or []):
                    cleaned = self._clean_settlement_winner_name(ctext)
                    if cleaned:
                        cy_center = (cbox[0][1] + cbox[2][1]) / 2.0 / max(1, crop.shape[0])
                        winner_candidates.append((cscore, cy_center, cleaned))

        if winner_candidates:
            winner_candidates.sort(key=lambda item: (-item[0], item[1]))
            data["winner"] = winner_candidates[0][2]
            data["winnerConfidence"] = float(winner_candidates[0][0])
            data["winnerAmbiguous"] = len({item[2] for item in winner_candidates if item[0] >= .85}) > 1
        labeled = {"clearingPrice": None, "actualTotal": None, "profit": None}
        band_nums = []
        for box, text, _ in ocr_results:
            raw = (text or "").strip()
            if not raw:
                continue
            y_center = (box[0][1] + box[2][1]) / 2.0
            x_center = (box[0][0] + box[2][0]) / 2.0
            ny = y_center / max(1, screen_h)
            amount = parse_money_amount(raw)

            # 先按标签就近绑定：成交价 / 实际价值 / 收益
            if "成交价" in raw:
                labeled["clearingPrice"] = amount or labeled["clearingPrice"]
            elif "实际价值" in raw or "实际总价值" in raw:
                labeled["actualTotal"] = amount or labeled["actualTotal"]
            elif raw in ("收益", "实际收益", "净利润") or raw.endswith("收益"):
                labeled["profit"] = amount or labeled["profit"]

            # 结算三列大数字在同一水平带（归一化，兼容 540p / 1080p / 1440p）
            if amount >= 1000 and 0.38 <= ny <= 0.58:
                band_nums.append((x_center, amount))

        # 标签行本身可能不含数字，回看同一水平带里离标签最近的数
        if any(v is None for v in labeled.values()) and band_nums:
            for box, text, _ in ocr_results:
                raw = (text or "").strip()
                x_center = (box[0][0] + box[2][0]) / 2.0
                key = None
                if "成交价" in raw:
                    key = "clearingPrice"
                elif "实际价值" in raw or "实际总价值" in raw:
                    key = "actualTotal"
                elif raw in ("收益", "实际收益", "净利润") or (raw.endswith("收益") and "柜" not in raw):
                    key = "profit"
                if key and labeled[key] is None:
                    nearest = min(band_nums, key=lambda item: abs(item[0] - x_center))
                    labeled[key] = nearest[1]

        signed_profit = None
        if re.search(r"[-−－]\s*[\d,，.．]", full_text) and labeled.get("profit"):
            signed_profit = -abs(int(labeled["profit"]))
        if all(labeled.values()):
            data.update(labeled)
        else:
            band_nums.sort(key=lambda item: item[0])
            unique_vals = []
            for _, val in band_nums:
                if val not in unique_vals:
                    unique_vals.append(val)
            if len(unique_vals) >= 3:
                data["clearingPrice"] = labeled["clearingPrice"] or unique_vals[0]
                data["actualTotal"] = labeled["actualTotal"] or unique_vals[1]
                data["profit"] = labeled["profit"] or unique_vals[2]
            elif len(unique_vals) == 2:
                data["clearingPrice"] = labeled["clearingPrice"] or unique_vals[0]
                data["actualTotal"] = labeled["actualTotal"] or unique_vals[1]
            elif len(unique_vals) == 1:
                data["clearingPrice"] = labeled["clearingPrice"] or unique_vals[0]
            else:
                data.update({k: v for k, v in labeled.items() if v})

        if signed_profit is not None:
            data["profit"] = signed_profit

        # Auction assistant recognition:
        # Priority:
        # 1. Card visual area feature matching against canonical character reference templates.
        # 2. Secondary OCR text evidence, strictly validated against CANONICAL_ROSTER whitelist.
        # Free-text OCR (e.g. "小哎") is NEVER used directly as canonical assistant name.
        matcher = self.settlement_assistant_matcher
        assistant_res = matcher.identify(frame=frame, ocr_results=ocr_results)
        assistant_name = assistant_res.get("canonicalName")
        assistant_status = assistant_res.get("status", "UNKNOWN")

        data["auctionAssistant"] = assistant_name
        data["settlementAuctionAssistantName"] = assistant_name
        data["assistantIdentityStatus"] = assistant_status
        data["assistantCandidates"] = assistant_res.get("candidates", [])
        data["settlementWinnerName"] = data.get("winner")

        # Welfare recognition: strictly parse "奖励金获取：" or "福利金" amount
        welfare_received = None
        for box, text, _ in ocr_results:
            raw = (text or "").strip()
            if "吱果" in raw:
                continue
            # Match lines like "奖励金获取：101,350", "奖励金获取: 1,585", "奖励金：101,350", "福利金到账：5000"
            m = re.search(r'(?:奖励金获取|奖励金|福利金实际到账|福利金到账|福利到账|福利金实收|福利金)[：:\s]*([0-9,，.]+)', raw)
            if m:
                clean_num = m.group(1).replace(',', '').replace('，', '').replace('.', '')
                if clean_num.isdigit():
                    welfare_received = int(clean_num)
                    break
            elif any(k in raw for k in ("奖励金获取", "奖励金", "福利金实际到账", "福利金到账", "福利到账", "福利金实收", "福利金")):
                w_amt = parse_money_amount(raw, min_digits=1)
                if w_amt is not None and w_amt >= 0:
                    welfare_received = w_amt
                    break

        data["welfareReceived"] = welfare_received

        from player_identity import get_player_name, normalize_player_name
        try:
            cfg_name = normalize_player_name(get_player_name())
        except Exception:
            cfg_name = ""
        w_name = str(data.get("winner") or "").strip()
        data["isSelfWinner"] = bool(cfg_name and w_name and normalize_player_name(w_name) == cfg_name)

        return data

    def _settlement_looks_final(self, settlement: Dict[str, Any]) -> bool:
        if settlement.get('animationComplete') is False:
            return False
        clearing = settlement.get("clearingPrice")
        actual = settlement.get("actualTotal")
        profit = settlement.get("profit")
        if not clearing or actual in (None, 0):
            return False
        if profit is None:
            return False
        if actual == clearing:
            return False
        if abs(int(profit)) == int(clearing):
            return False
        return True

    def _get_settlement_evidence_store(self):
        if self._settlement_evidence_store is not None:
            return self._settlement_evidence_store
        try:
            from runtime_data import runtime_data_paths
            from settlement_evidence_store_v2 import SettlementEvidenceStoreV2

            self._settlement_evidence_store = SettlementEvidenceStoreV2(runtime_data_paths().root)
        except Exception:
            return None
        return self._settlement_evidence_store

    def _persist_stable_settlement_original(
        self,
        frame: Optional[np.ndarray],
        captured_at: Optional[str],
    ) -> None:
        try:
            from settlement_stable_frame_persist import (
                apply_persist_result,
                persist_stable_settlement_original,
                resolve_record_stable_key,
            )
        except Exception:
            self.current_context["settlementFileEvidenceStatus"] = "EVIDENCE_PERSIST_FAILED"
            self.current_context["settlementFileEvidenceWarning"] = "EVIDENCE_PERSIST_FAILED: adapter unavailable"
            return
        result = persist_stable_settlement_original(
            store=self._get_settlement_evidence_store(),
            is_settlement=True,
            record_stable_key=resolve_record_stable_key(self.current_context),
            frame=frame,
            captured_at=captured_at,
            existing_descriptor=self.current_context.get("settlementFileEvidence"),
            extract_proposals=False,
        )
        apply_persist_result(self.current_context, result)

    def _stabilize_settlement(
        self,
        settlement: Dict[str, Any],
        frame: Optional[np.ndarray] = None,
        captured_at: Optional[str] = None,
    ) -> None:
        """同一组成交/实际/收益连续若干帧不变后才允许归档。动画早期 0/顶格成交价不算终值。"""
        identity_key = (self.current_context.get('recordStableKey') or self.current_context.get('id'),
                        getattr(self, '_session_generation', 0))
        raw_ledger = settlement.get('ledger')
        if isinstance(raw_ledger, dict) and isinstance(frame, np.ndarray) and frame.size:
            from settlement_identity_memory import SettlementIdentityMemory
            if not hasattr(self, '_settlement_identity_memory'):
                self._settlement_identity_memory = SettlementIdentityMemory()
            self._settlement_identity_memory.observe(key=identity_key, ledger=raw_ledger,
                                                     frame=frame, captured_at=captured_at)
        if not self._settlement_looks_final(settlement):
            self.current_context["settlementReady"] = False
            self._settlement_sig = None
            self._settlement_stable = 0
            return
        sig = (
            settlement.get("clearingPrice"),
            settlement.get("actualTotal"),
            settlement.get("profit"),
        )
        if sig == self._settlement_sig:
            self._settlement_stable += 1
        else:
            self._settlement_sig = sig
            self._settlement_stable = 1
        ready = self._settlement_stable >= SETTLEMENT_STABLE_FRAMES and not self._settlement_finalized
        self.current_context["settlementReady"] = ready
        self.current_context["settlementFinalized"] = self._settlement_finalized
        self.current_context["settlementCandidate"] = {
            "clearingPrice": sig[0],
            "actualTotal": sig[1],
            "profit": sig[2],
            "stable": self._settlement_stable,
        }

        if ready and not self._settlement_finalized:
            light_bill_key = (*identity_key, *sig)
            if not isinstance(raw_ledger, dict) and getattr(self, '_light_bill_persisted_key', None) == light_bill_key:
                # The countdown changes pixels on every frame. Keep one stable
                # bill original; explicit screenshots still retain every view.
                self.current_context["settlementFileEvidenceStatus"] = "IDEMPOTENT"
                return
            # Keep item identities, original pixels and observation time from
            # the SAME stable viewport. Later scrolling can expose empty rows.
            if frame is not None and isinstance(frame, np.ndarray) and frame.size:
                from settlement_observation import SettlementObservation
                if not hasattr(self, '_best_settlement_observation'):
                    self._best_settlement_observation = SettlementObservation()
                ledger = settlement.get('ledger')
                if isinstance(ledger, dict):
                    if hasattr(self, '_settlement_identity_memory'):
                        def persist_identity_frame(source_frame, source_at):
                            from settlement_stable_frame_persist import persist_stable_settlement_original, resolve_record_stable_key
                            persisted = persist_stable_settlement_original(
                                store=self._get_settlement_evidence_store(), is_settlement=True,
                                record_stable_key=resolve_record_stable_key(self.current_context),
                                frame=source_frame, captured_at=source_at, extract_proposals=False)
                            return persisted.get('descriptor') if persisted.get('ok') else None
                        ledger = self._settlement_identity_memory.fuse(
                            key=identity_key, ledger=ledger, frame=frame, captured_at=captured_at,
                            persist=persist_identity_frame)
                    key = (self.current_context.get('recordStableKey') or self.current_context.get('id'),
                           self._session_generation, *sig)
                    selected = self._best_settlement_observation.select(
                        key=key, ledger=ledger, frame=frame, captured_at=captured_at)
                    frame, captured_at = selected['frame'], selected['capturedAt']
                    ledger = selected['ledger']
                    self.current_context['settlementIdentityFileOriginals'] = ledger.get('settlementIdentityFileOriginals') or []
                    settlement['ledger'] = ledger
                    settlement['items'] = ledger.get('settlementItems') or []
                    self.current_context.update({k: v for k, v in ledger.items() if k.startswith('settlement')})
                    self.current_context['settlementObservationAt'] = captured_at
            self._persist_stable_settlement_original(frame, captured_at)
            game_id = str(
                self.current_context.get("recordStableKey")
                or self.current_context.get("id")
                or self.current_context.get("matchId")
                or ""
            ).strip()
            actual_total = settlement.get("actualTotal")
            if (
                game_id
                and actual_total
                and captured_at
                and frame is not None
                and isinstance(frame, np.ndarray)
                and frame.size > 0
            ):
                try:
                    from evidence_storage import save_evidence_png
                    from settlement_truth_holder import ACTIVE_SETTLEMENT_TRUTH_HOLDER, build_settlement_truth_evidence_v1

                    rel_uri, digest = save_evidence_png(frame, game_id, subfolder="settlement")
                    truth_ev = build_settlement_truth_evidence_v1(
                        match_id=game_id,
                        actual_total=float(actual_total),
                        settlement_observed_at=captured_at,
                        truth_source="live_vision_stabilized_settlement",
                        truth_confidence="medium",
                        evidence_uri=rel_uri,
                        evidence_sha256=digest,
                        verification_method="vision_multiframe_stabilization_v1",
                        verification_version="settlement-stabilization.v1",
                        verifier_type="deterministic_verifier",
                        verifier_id="rapidocr_stabilizer_v1",
                        unresolved_conflict=False,
                    )
                    file_ev = self.current_context.get("settlementFileEvidence")
                    if file_ev and isinstance(file_ev, dict):
                        truth_ev["fileOriginals"] = [dict(file_ev)]
                        for source in self.current_context.get('settlementIdentityFileOriginals') or []:
                            if source.get('sha256') != file_ev.get('sha256'):
                                truth_ev['fileOriginals'].append(dict(source))
                    ACTIVE_SETTLEMENT_TRUTH_HOLDER.set_truth(game_id, truth_ev)
                    self.current_context["settlementTruthEvidence"] = truth_ev
                    if not isinstance(raw_ledger, dict):
                        self._light_bill_persisted_key = light_bill_key
                except Exception as e:
                    print(f"⚠️ [VisionPipeline] Failed to freeze settlement truth evidence: {e}")

    def mark_settlement_saved(self) -> None:
        """Disk has a recoverable record, even when its evidence is still DRAFT."""
        self.current_context["_clearTrunkAfterLeave"] = True

    def mark_settlement_finalized(self) -> None:
        self._settlement_finalized = True
        self.current_context["settlementReady"] = False
        self.current_context["settlementFinalized"] = True
        # Keep settlement facts until we actually leave the settlement scene so
        # a second archive attempt in the same frame still sees the frozen bill.
        self.current_context["_clearTrunkAfterLeave"] = True

    def flush_settlement_for_shutdown(self) -> bool:
        """关闭助手时：已有可信终值候选就放行一次 finalize。"""
        if self._settlement_finalized:
            return False
        settlement = self.current_context.get("settlementData") or {}
        if not settlement.get("isSettlement") or not self._settlement_looks_final(settlement):
            return False
        self.current_context["settlementReady"] = True
        return True

    def process_frame_observation(self, frame: np.ndarray, frame_index: int = 0) -> VisionObservation:
        """处理图像帧并直接输出标准化的 VisionObservation 契约对象"""
        ctx = self.process_frame(frame)
        h, w = frame.shape[:2]
        return VisionObservation.from_pipeline_context(ctx, frame_index=frame_index, resolution=(w, h))

    def to_v06_context(self) -> Dict[str, Any]:
        from business_sot import venue_entry_cost
        c = self.current_context
        entry = c.get("lobbyEntryCost")
        if entry is None:
            entry = venue_entry_cost(c.get("lobbyVenue") or c.get("venue"))
        return {
            "version": "0.65-vision-live",
            "scene": c.get("scene", SCENE_UNKNOWN),
            "sceneLabel": c.get("sceneLabel", SCENE_LABELS[SCENE_UNKNOWN]),
            "auctionEntryVisible": c.get("auctionEntryVisible", False),
            "inLobby": c.get("inLobby", False),
            "lobbyVenue": c.get("lobbyVenue"),
            "lobbyVenueKey": c.get("lobbyVenueKey"),
            "lobbyVenueLabel": c.get("lobbyVenueLabel"),
            "lobbyToolGroup": c.get("lobbyToolGroup"),
            "lobbyCharacter": c.get("lobbyCharacter"),
            "lobbyEntryCost": entry,
            "character": c.get("lobbyCharacter") or c.get("character"),
            "toolGroup": c.get("toolGroup"),
            "q": c["q"],
            "avg": c["avg"],
            "currentEstimate": c.get("currentEstimate"),
            "goldTotal": c["goldTotal"],
            "goldCount": c["goldCount"],
            "purple": c["purple"],
            "fieldCondition": c.get("fieldCondition") or "unknown",
            "venue": c.get("venue") or "未知场地",
            "box": c.get("box") or "未知箱型",
            "toolGroup": c.get("toolGroup"),
            "boxType": c.get("boxType"),
            "myBid": c["myBid"],
            "myName": c["myName"],
            "opponents": c["opponents"],
            "currentLeaderBid": c["currentLeaderBid"],
            "leaderName": c["leaderName"],
            "isMyLead": c["isMyLead"],
            "roundTimeline": c["roundTimeline"],
            "costs": {
                "entry": entry,
                "intel": 0,
                "other": 0
            }
        }
