"""
Neverness to Everness (异环) - 对局全自动记账归档器 (v0.65)
功能：
  1. 终局结算大屏出现时，自动提取 [成交价]、[真实价值]、[净收益] 与场地词条
  2. 幂等去重防重复写入
  3. 原子写入异环拍卖数据.json，实现 100% 免人工记账！符合 Schema 6 规范
"""

import json
import os
import sys
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
import time
from datetime import datetime
from typing import Dict, Any, Optional

_CORE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_CORE_DIR, ".."))
_APP_DIR = os.path.join(_PROJECT_ROOT, "app")
for _p in (_CORE_DIR, _APP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from canonical_match_record import (
    ENVIRONMENT_CATALOG_FIELDS,
    build_canonical_match_record_v7,
    validate_finalized_match_record_v7,
    validate_canonical_match_record_v7,
)
from canonical_history_store import CanonicalHistoryStore
from evaluation_eligibility import validate_prediction_snapshot_for_storage
from prediction_snapshot_holder import ACTIVE_SNAPSHOT_HOLDER
from settlement_truth_holder import ACTIVE_SETTLEMENT_TRUTH_HOLDER, validate_settlement_truth_evidence
from version import APP_PRODUCT_VERSION
from runtime_data import resolve_runtime_history_path, runtime_data_paths
from acquisition_authority import acquisition_from_context

import base64
import hashlib
import cv2
import numpy as np

FORBIDDEN_WINNER_PLACEHOLDERS = frozenset({
    "玩家本人",
    "本人拍下",
    "其他人拍下",
    "他人拍下",
    "未知竞得者",
    "未知玩家",
    "未知",
    "未记录",
    "待确认",
})


def build_review_units_from_settlement_items(
    items: list,
    frame: Optional[np.ndarray] = None,
    data_dir: Optional[str] = None,
    blob_path: Optional[str] = None,
) -> list:
    if not items:
        return []
    img = frame
    if img is None and blob_path and os.path.isfile(blob_path):
        try:
            img = cv2.imdecode(np.fromfile(blob_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            img = None

    review_units = []
    for idx, s in enumerate(items):
        if not isinstance(s, dict):
            continue
        c_id = s.get("catalogId") or s.get("exactItemId")
        c_name = s.get("name") or s.get("identifiedName")
        is_exact = (
            s.get("status") in ("exact", "CONFIRMED")
            or s.get("identificationStatus") == "exact"
        ) and bool(c_name)
        bbox = s.get("bbox") or []
        crop_path = None
        crop_sha = None
        crop_data_url = None

        if img is not None and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            bx, by, bw, bh = [int(v) for v in bbox]
            if (
                by >= 0
                and bx >= 0
                and by + bh <= img.shape[0]
                and bx + bw <= img.shape[1]
                and bw > 0
                and bh > 0
            ):
                try:
                    crop = img[by : by + bh, bx : bx + bw]
                    ok, buf = cv2.imencode(".png", crop)
                    if ok:
                        b = buf.tobytes()
                        crop_sha = hashlib.sha256(b).hexdigest()
                        crop_path = f"evidence/settlement_v2/blobs/{crop_sha[:2]}/{crop_sha}.png"
                        if data_dir:
                            full_crop_path = os.path.join(
                                data_dir, "evidence", "settlement_v2", "blobs", crop_sha[:2], f"{crop_sha}.png"
                            )
                            if not os.path.isfile(full_crop_path):
                                os.makedirs(os.path.dirname(full_crop_path), exist_ok=True)
                                with open(full_crop_path, "wb") as f:
                                    f.write(b)
                        crop_data_url = "data:image/png;base64," + base64.b64encode(b).decode("ascii")
                except Exception:
                    pass

        candidates = []
        if s.get("candidates") and isinstance(s["candidates"], list):
            candidates = list(s["candidates"])
        elif s.get("candidateItemIds") and isinstance(s["candidateItemIds"], list):
            candidates = [{"catalogId": None, "name": n} for n in s["candidateItemIds"]]
        elif c_name:
            candidates = [{"catalogId": c_id, "name": c_name}]

        w_cells = s.get("widthCells") or s.get("w", 1)
        h_cells = s.get("heightCells") or s.get("h", 1)

        review_units.append({
            "reviewUnitId": f"settlement_item_{idx}",
            "placementStatus": "ALIGNED",
            "worldAnchor": {"row": s.get("row", 0), "col": s.get("col", 0)},
            "footprint": {"widthCells": w_cells, "heightCells": h_cells},
            "row": s.get("row", 0),
            "col": s.get("col", 0),
            "w": w_cells,
            "h": h_cells,
            "gridShape": s.get("shape") or f"{w_cells}x{h_cells}",
            "rarity": s.get("rarity"),
            "canonicalName": c_name,
            "name": c_name,
            "selectedCatalogId": c_id,
            "price": s.get("price"),
            "confirmationStatus": "CONFIRMED" if is_exact else "CANDIDATE_ONLY",
            "identityStatus": "EXACT_IDENTIFIED" if is_exact else "AMBIGUOUS_CANDIDATES",
            "confidence": float(s.get("confidence") or (1.0 if is_exact else 0.0)),
            "cells": s.get("cells") or [],
            "bbox": bbox,
            "candidates": candidates,
            "cropPath": crop_path,
            "cropSha256": crop_sha,
            "cropDataUrl": crop_data_url,
        })
    return review_units


class AutoArchiver:
    def __init__(self, db_paths=None):
        core_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(core_dir, ".."))

        if db_paths is None:
            self.db_paths = [str(resolve_runtime_history_path())]
        else:
            self.db_paths = list(dict.fromkeys(os.path.abspath(p) for p in db_paths))

        self.last_saved_signature = None
        self.last_save_time = 0
        self.last_failed_signature = None
        self.last_failed_time = 0
        self.last_draft_id = None

    def archive_match(self, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract settlement data and persist a Canonical MatchRecord v7 (lifecycle: FINALIZED)."""
        settlement_data = ctx.get("settlementData")
        if not settlement_data or not settlement_data.get("isSettlement"):
            return None

        clearing = settlement_data.get("clearingPrice")
        actual = settlement_data.get("actualTotal")
        profit = settlement_data.get("profit")

        if clearing is None or actual is None:
            return None
        if not ctx.get("settlementReady", False):
            return None
        if ctx.get("settlementFinalized"):
            return None

        # 60s duplicate signature gate
        observed_box = ctx.get("box")
        if observed_box in (None, "", "未知箱型"):
            observed_box = ctx.get("boxType")
        now = time.time()
        try:
            from current_match import CURRENT_MATCH
            cur_id = getattr(CURRENT_MATCH, "id", "")
        except Exception:
            cur_id = ""
        game_id = str(
            ctx.get("recordStableKey")
            or ctx.get("matchId")
            or ctx.get("id")
            or cur_id
            or f"auto_{int(now)}"
        ).strip()
        _, acquired = acquisition_from_context(ctx)
        from session_accounting import receipt_amount
        welfare_received = receipt_amount(ctx.get("welfareReceived") if "welfareReceived" in ctx else (settlement_data.get("welfare") or {}).get("received"))
        from session_accounting import strict_nonnegative_integer
        dark_controls = {key: strict_nonnegative_integer(ctx.get(key), label) for key, label in
                         (("privateBidCap", "私人出价上限"), ("bidActionCount", "可见出价次数"))}
        # A stronger stable observation is a real update, even when money is
        # unchanged. Pixel/time-only changes do not bypass the duplicate gate.
        item_signature = tuple(sorted((str(i.get('row')), str(i.get('col')),
                                       str(i.get('widthCells')), str(i.get('heightCells')),
                                       str(i.get('status')), str(i.get('exactItemId')), str(i.get('price')))
                                      for i in (ctx.get('settlementItems') or settlement_data.get('items') or [])
                                      if isinstance(i, dict)))
        from intel_evidence_record import intel_evidence_record
        intel_evidence = intel_evidence_record(ctx)
        sig = (game_id, clearing, actual, profit, welfare_received, tuple(dark_controls.values()), ctx.get("venue"), observed_box,
               ctx.get("winner") or settlement_data.get("winner"), acquired,
               tuple(ctx.get(key) for key in ENVIRONMENT_CATALOG_FIELDS), ctx.get("boxType"), item_signature,
               json.dumps(ctx.get("costs") or {}, sort_keys=True, default=str), ctx.get("lobbyEntryCost"),
               json.dumps(intel_evidence, sort_keys=True, default=str))
        if sig == self.last_saved_signature and (now - self.last_save_time) < 60:
            return None  # Duplicate settlement frame
        if sig == self.last_failed_signature and (now - self.last_failed_time) < 1:
            return None  # Brief backoff for transient storage failures, not a successful-save debounce.

        now_iso = datetime.now().astimezone().isoformat()

        my_final_bid = ctx.get("myBid", 0)
        from live_match_projection import project_four_seats
        opponents = project_four_seats(ctx.get("seats") or ctx.get("opponents"), evidence=ctx.get("auctionEvidence") if isinstance(ctx.get("auctionEvidence"), dict) else None)

        # Winner authority: Only accept explicitly proven, non-placeholder identities
        raw_winner = ctx.get("winner") or settlement_data.get("winner")

        candidate_winner = str(raw_winner or "").strip()
        if candidate_winner in FORBIDDEN_WINNER_PLACEHOLDERS or not candidate_winner:
            winner_name = None
        else:
            winner_name = candidate_winner

        if acquired is None:
            if ctx.get("isSelfWinner") is not None:
                acquired = bool(ctx.get("isSelfWinner"))
            elif winner_name and ctx.get("myName") and ctx.get("myName") not in FORBIDDEN_WINNER_PLACEHOLDERS:
                acquired = (str(winner_name).strip() == str(ctx.get("myName")).strip())
            elif raw_winner and ctx.get("myName") and ctx.get("myName") not in FORBIDDEN_WINNER_PLACEHOLDERS:
                acquired = (str(raw_winner).strip() == str(ctx.get("myName")).strip())
            elif winner_name and winner_name not in FORBIDDEN_WINNER_PLACEHOLDERS:
                acquired = False


        # Timeline rounds
        timeline_dict = ctx.get("roundTimeline", {})
        round_timeline = []
        if isinstance(timeline_dict, dict):
            for k in sorted(timeline_dict.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
                round_timeline.append(timeline_dict[k])
        elif isinstance(timeline_dict, list):
            round_timeline = timeline_dict

        costs_raw = ctx.get("costs") or {}
        def amount(value):
            if isinstance(value, bool) or value is None:
                return None
            if isinstance(value, str):
                return int(value) if value.isascii() and value.isdigit() else None
            if isinstance(value, (int, float)) and value >= 0 and value < float('inf') and value == int(value):
                return int(value)
            return None
        entry_cost = amount(costs_raw.get("entry", ctx.get("lobbyEntryCost")))
        intel_cost = amount(costs_raw.get("intel", costs_raw.get("info", 0)))
        other_cost = amount(costs_raw.get("other", 0))
        sunk_cost = None if None in (entry_cost, intel_cost, other_cost) else entry_cost + intel_cost + other_cost
        future_cost = amount(costs_raw.get("futureIncrementalCost", 0))
        all_costs = None if None in (sunk_cost, future_cost) else sunk_cost + future_cost

        solver_tool = ctx.get("solverToolGroup") or ctx.get("toolGroup") or "group1"

        # 1. Prediction Snapshot v1
        valid_snapshot = None
        candidate_snapshot = ctx.get("predictionSnapshot") or ACTIVE_SNAPSHOT_HOLDER.get_snapshot_for_match(game_id)
        if candidate_snapshot and isinstance(candidate_snapshot, dict):
            is_valid, _ = validate_prediction_snapshot_for_storage(candidate_snapshot, match_id=game_id)
            if is_valid:
                valid_snapshot = candidate_snapshot

        # 2. Settlement Truth Evidence v1
        valid_truth = None
        candidate_truth = (
            ctx.get("settlementTruthEvidence")
            or (ctx.get("settlement") if isinstance(ctx.get("settlement"), dict) else {}).get("truthEvidence")
            or ACTIVE_SETTLEMENT_TRUTH_HOLDER.get_truth_for_match(game_id)
        )
        if candidate_truth and isinstance(candidate_truth, dict):
            data_dir = runtime_data_paths().root
            if self.db_paths:
                db_dir = os.path.dirname(self.db_paths[0])
                if os.path.exists(os.path.join(db_dir, "evidence")):
                    data_dir = db_dir
                elif os.path.exists(os.path.join(os.path.dirname(db_dir), "evidence")):
                    data_dir = os.path.dirname(db_dir)
            is_valid, reasons = validate_settlement_truth_evidence(
                candidate_truth,
                match_id=game_id,
                data_dir=data_dir,
                check_disk_bytes=True,
            )
            if is_valid:
                valid_truth = candidate_truth
            else:
                print(f"⚠️ [AutoArchiver] Truth evidence validation failed for {game_id}: {reasons}")

        # 3. Canonical Warehouse Slots
        valid_warehouse = None
        candidate_warehouse = ctx.get("warehouse")
        if candidate_warehouse is None and isinstance(ctx.get("settlement"), dict):
            candidate_warehouse = ctx["settlement"].get("warehouse")
        if candidate_warehouse is None:
            try:
                from main import CURRENT_MATCH
                if CURRENT_MATCH and getattr(CURRENT_MATCH, "facts", None):
                    cur_id = str(getattr(CURRENT_MATCH, "id", "") or "").strip()
                    if cur_id == game_id or not game_id or game_id.startswith("auto_"):
                        candidate_warehouse = CURRENT_MATCH.facts.get("warehouse")
            except Exception:
                pass

        if candidate_warehouse and isinstance(candidate_warehouse, dict) and "slots" in candidate_warehouse:
            sanitized_slots = []
            for s in candidate_warehouse.get("slots") or []:
                if not isinstance(s, dict):
                    continue
                col = s.get("col")
                row = s.get("row")
                w = s.get("w")
                h = s.get("h")
                if col is None or row is None or w is None or h is None:
                    continue
                rarity = str(s.get("rarity") or "unknown")
                evidence = str(s.get("evidenceLevel") or "OUTLINE_ONLY")
                identified_name = s.get("identifiedName")
                if rarity == "unknown" or evidence == "OUTLINE_ONLY":
                    identified_name = None
                candidates = [
                    {
                        "catalogId": str(c.get("catalogId") or c.get("Id") or ""),
                        "name": str(c.get("name") or c.get("Name") or ""),
                    }
                    for c in (s.get("candidates") or [])
                    if isinstance(c, dict)
                ]
                identity_status = str(s.get("identityStatus") or ("CANDIDATE" if candidates else "UNKNOWN"))
                slot_dict = {
                    "col": int(col),
                    "row": int(row),
                    "w": int(w),
                    "h": int(h),
                    "rarity": rarity,
                    "evidenceLevel": evidence,
                    "identityStatus": identity_status,
                    "candidates": candidates,
                    "identifiedName": str(identified_name) if identified_name is not None and identity_status == "EXACT" else None,
                }
                if s.get("trackId") is not None:
                    slot_dict["trackId"] = int(s["trackId"])
                sanitized_slots.append(slot_dict)
            valid_warehouse = {"slots": sanitized_slots}

        # Assemble Canonical MatchRecord v7 structure
        environment_data = {
            **{key: ctx[key] for key in ENVIRONMENT_CATALOG_FIELDS if key in ctx},
            "venueTier": ctx.get("venueTier"),
            "venue": ctx.get("venue"),
            "venueName": ctx.get("venueName"),
            "box": observed_box or "未知箱型",
            "boxType": ctx.get("boxType"),
            "fieldCondition": ctx.get("fieldCondition") or "standard",
            "fieldConditionName": ctx.get("fieldConditionName"),
            "fieldConditionSource": ctx.get("fieldConditionSource") or "ocr_banner",
        }
        loadout_data = {
            "character": ctx.get("character") or ctx.get("lobbyCharacter") or "达芙蒂尔",
            "lobbyToolGroup": ctx.get("lobbyToolGroup"),
            "solverToolGroup": solver_tool,
        }
        costs_data = {
            "entry": entry_cost,
            "intel": intel_cost,
            "other": other_cost,
            "sunkCost": sunk_cost,
            "futureIncrementalCost": future_cost,
            "total": all_costs,
        }
        public_intel_data = {
            "q": ctx.get("q"),
            "totalItems": ctx.get("totalItems"),
            "totalGrid": ctx.get("totalGrid") or ctx.get("totalGrids"),
            "avgValueBasis": "all_inclusive",
        }

        # Build qualities
        shapes = ctx.get("identifiedShapes") or {}
        qualities_data = {
            "white": {
                "count": ctx.get("whiteCount"),
                "avg": ctx.get("whiteAvg"),
                "grid": ctx.get("whiteGrid"),
                "knownItems": shapes.get("knownWhite") or ctx.get("knownWhite") or [],
            },
            "green": {
                "count": ctx.get("greenCount"),
                "avg": ctx.get("greenAvg"),
                "grid": ctx.get("greenGrid"),
                "knownItems": shapes.get("knownGreen") or ctx.get("knownGreen") or [],
            },
            "blue": {
                "count": ctx.get("blueCount"),
                "avg": ctx.get("blueAvg"),
                "grid": ctx.get("blueGrid"),
                "knownItems": shapes.get("knownBlue") or ctx.get("knownBlue") or [],
            },
            "purple": {
                "count": ctx.get("purpleCount") or ctx.get("purple"),
                "minCount": ctx.get("purpleMinCount") or ctx.get("minPurple"),
                "avg": ctx.get("purpleAvg"),
                "grid": ctx.get("purpleGrid"),
                "knownItems": shapes.get("knownPurple") or ctx.get("knownPurple") or [],
            },
            "gold": {
                "count": ctx.get("goldCount"),
                "minCount": ctx.get("goldMinCount") or ctx.get("minGold"),
                "avg": ctx.get("goldAvg") or ctx.get("avg"),
                "total": ctx.get("goldTotal"),
                "grid": ctx.get("goldGrid"),
                "knownItems": shapes.get("knownGold") or ctx.get("knownGold") or [],
            },
            "red": {
                "count": ctx.get("redCount"),
                "minCount": ctx.get("redMinCount") or ctx.get("minRed"),
                "maxCount": ctx.get("redMaxCount"),
                "grid": ctx.get("redGrid"),
                "knownItems": shapes.get("knownRed") or ctx.get("knownRed") or [],
                "redInventoryComplete": ctx.get("redInventoryComplete"),
                "settlementVerifiedRedItems": ctx.get("settlementVerifiedRedItems") or "",
            },
        }

        clean_leader = str(ctx.get("leaderName") or "").strip()
        if clean_leader in FORBIDDEN_WINNER_PLACEHOLDERS or not clean_leader:
            clean_leader = None

        bidding_data = {
            "seats": opponents,
            "myName": ctx.get("myName") if ctx.get("myName") is not None else "玩家本人",
            **dark_controls,
            "myFinalBid": my_final_bid,
            "leaderName": clean_leader,
            "leaderBid": ctx.get("leaderBid") or clearing,
            "leaderTies": ctx.get("leaderTies") or [],
            "isMyLead": bool(ctx.get("isMyLead")),
            "historicalBids": ctx.get("historicalBids") or {},
            "finalBids": ctx.get("finalBids") or {},
            "rounds": round_timeline,
        }

        # Determine whether record has full proven facts for FINALIZED lifecycle
        has_proven_winner = bool(winner_name and str(winner_name).strip())
        is_finalized = bool(has_proven_winner and clearing is not None and actual is not None
                            and isinstance(acquired, bool) and (profit is not None or all_costs is not None))

        settlement_block = {
            "welfare": {"received": welfare_received},
            "status": "verified" if is_finalized else "pending",
            "verified": bool(is_finalized),
            "clearingPrice": float(clearing) if clearing is not None else None,
            "actualTotal": float(actual) if actual is not None else None,
            "realizedProfit": (
                float(profit)
                if profit is not None
                else None if all_costs is None or acquired is None
                else (
                    float(actual) - float(clearing) - all_costs
                    if (actual is not None and clearing is not None and acquired is True)
                    else -all_costs
                )
            ),
            "acquired": acquired,
            "winner": winner_name if has_proven_winner else None,
            "settlementWinnerName": (ctx.get("settlementWinnerName") or winner_name) if has_proven_winner else None,
            "settlementAuctionAssistantName": ctx.get("settlementAuctionAssistantName") or ctx.get("auctionAssistant") or (settlement_data or {}).get("auctionAssistant"),
            "auctionAssistant": ctx.get("auctionAssistant") or ctx.get("settlementAuctionAssistantName") or (settlement_data or {}).get("auctionAssistant"),
            "isSelfWinner": ctx.get("isSelfWinner") if ctx.get("isSelfWinner") is not None else acquired,
            "settlementItems": ctx.get("settlementItems") or settlement_data.get("items", []),
        }
        # Quality sell selection (Boundary 2)
        q_sel = ctx.get("qualitySellSelection")
        q_src = ctx.get("qualitySellSelectionSource")
        q_sources = ctx.get("qualitySellSelectionSources")
        if q_sel is None and isinstance(ctx.get("settlement"), dict):
            q_sel = ctx["settlement"].get("qualitySellSelection")
            q_src = ctx["settlement"].get("qualitySellSelectionSource")
            q_sources = ctx["settlement"].get("qualitySellSelectionSources")
        if q_sel is None and isinstance(settlement_data, dict):
            q_sel = settlement_data.get("qualitySellSelection")
            q_src = settlement_data.get("qualitySellSelectionSource")
            q_sources = settlement_data.get("qualitySellSelectionSources")
        if q_sel is None and acquired is True:
            from quality_sell_selection import resolve_default_quality_sell_selection
            q_sel = resolve_default_quality_sell_selection(True)
            q_src = "default_self_acquired"
        elif q_sel is None and (acquired is False or acquired is None):
            if q_src:
                from quality_sell_selection import resolve_default_quality_sell_selection
                q_sel = resolve_default_quality_sell_selection(acquired)
        if q_sel is not None:
            from quality_sell_selection import (
                aggregate_selection_source,
                normalize_quality_sell_selection,
                normalize_quality_sell_selection_sources,
                sources_from_aggregate,
            )
            norm_sources = (
                normalize_quality_sell_selection_sources(q_sources)
                if isinstance(q_sources, dict)
                else sources_from_aggregate(q_src)
            )
            settlement_block["qualitySellSelection"] = normalize_quality_sell_selection(q_sel)
            settlement_block["qualitySellSelectionSources"] = norm_sources
            settlement_block["qualitySellSelectionSource"] = aggregate_selection_source(norm_sources)

        if valid_truth is not None:
            settlement_block["truthEvidence"] = valid_truth

        # Resolve frame or blob path for settlement item review units
        settle_frame = ctx.get("frame")
        data_dir = runtime_data_paths().root
        if self.db_paths:
            db_dir = os.path.dirname(self.db_paths[0])
            if os.path.exists(os.path.join(db_dir, "evidence")):
                data_dir = db_dir
            elif os.path.exists(os.path.join(os.path.dirname(db_dir), "evidence")):
                data_dir = os.path.dirname(db_dir)

        blob_path = None
        if settle_frame is None and valid_truth:
            for orig in valid_truth.get("fileOriginals") or []:
                rel = orig.get("relativePath")
                if rel:
                    cand = os.path.join(data_dir, rel.replace("/", os.sep))
                    if os.path.isfile(cand):
                        blob_path = cand
                        break

        review_units = build_review_units_from_settlement_items(
            settlement_block["settlementItems"],
            frame=settle_frame,
            data_dir=data_dir,
            blob_path=blob_path,
        )
        if review_units:
            settlement_block["reviewUnits"] = review_units
            if valid_warehouse is None:
                conf_count = sum(1 for u in review_units if u.get("confirmationStatus") == "CONFIRMED")
                valid_warehouse = {
                    "itemCount": len(review_units),
                    "unknownCount": len(review_units) - conf_count,
                    "slots": [],
                }

        # Resolve data origin (live / replay / test)
        origin = ctx.get("dataOrigin") or ctx.get("executionOrigin")
        if not origin:
            try:
                from current_match import CURRENT_MATCH
                origin = getattr(CURRENT_MATCH, "data_origin", None)
            except Exception:
                origin = None
        if not origin:
            if game_id.startswith("replayfile_") or "replay" in str(ctx.get("mode") or "").lower():
                origin = "replay"
            elif game_id.startswith("test_") or "test" in str(ctx.get("mode") or "").lower():
                origin = "test"
            else:
                origin = "live"

        canonical_record = build_canonical_match_record_v7(
            match_id=game_id,
            played_at=now_iso,
            lifecycle_status="FINALIZED" if is_finalized else "DRAFT",
            source="vision-auto-archiver",
            data_origin=origin,
            environment=environment_data,
            loadout=loadout_data,
            costs=costs_data,
            public_intel=public_intel_data,
            qualities=qualities_data,
            bidding=bidding_data,
            settlement=settlement_block,
            prediction_snapshot=valid_snapshot,
            solver_result=ctx.get("solverResult"),
            warehouse=valid_warehouse,
            product_version=APP_PRODUCT_VERSION,
        )
        canonical_record["recordStableKey"] = game_id
        canonical_record["dataOrigin"] = origin
        if review_units:
            canonical_record["reviewUnits"] = review_units
            canonical_record["warehouseReviewUnits"] = review_units

        if isinstance(ctx.get('auctionEvidence'), dict) and ctx['auctionEvidence'].get('ownerMatchId') == game_id:
            import copy
            canonical_record['auctionEvidence'] = copy.deepcopy(ctx['auctionEvidence'])
        if intel_evidence is not None:
            canonical_record['intelCardEvidence'] = intel_evidence
        persisted = False
        persisted_record = None
        for db_p in self.db_paths:
            try:
                store = CanonicalHistoryStore(db_p)
                written = store.persist_record_transactional(
                    canonical_record, is_finalized=is_finalized, preserve_archive_sidecars=True)
                persisted = True
                persisted_record = written
                if is_finalized:
                    print(f"💾 [全自动记账] 成功归档至: {db_p}")
                else:
                    print(f"💾 [全自动记账] 结算证据已保存至草稿: {db_p}")
            except Exception as e:
                print(f"❌ 写入数据库失败 ({db_p}): {e}")

        if self.db_paths and not persisted:
            self.last_failed_signature = sig
            self.last_failed_time = now
            return None

        self.last_failed_signature = None
        self.last_saved_signature = sig
        self.last_save_time = now

        final_record = persisted_record or canonical_record
        if persisted and is_finalized:
            try:
                from live_shadow import ingest_archived_record
                ingest_archived_record(final_record, self.db_paths[0])
            except Exception as e:
                print(f"❌ 刷新 Live history snapshot 失败: {e}")

        ctx["settlementReady"] = False
        ctx["settlementFinalized"] = True
        if persisted:
            ACTIVE_SNAPSHOT_HOLDER.clear()
            ACTIVE_SETTLEMENT_TRUTH_HOLDER.clear()
        return final_record

    def save_draft(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Persist a live DRAFT. Must never ingest Historical Shadow."""
        if not isinstance(record, dict):
            return None
        rec_id = str(record.get("id") or "").strip()
        if not rec_id:
            return None
        draft = dict(record)
        draft["id"] = rec_id
        draft["lifecycleStatus"] = "DRAFT"
        draft["source"] = draft.get("source") or "manual"
        # Start without the copied sidecar; only validation may admit it.
        draft.pop("predictionSnapshot", None)
        if "predictionSnapshot" in record and isinstance(record["predictionSnapshot"], dict):
            is_valid, _ = validate_prediction_snapshot_for_storage(record["predictionSnapshot"], match_id=rec_id)
            if is_valid:
                draft["predictionSnapshot"] = record["predictionSnapshot"]

        persisted = None
        for db_p in self.db_paths:
            try:
                store = CanonicalHistoryStore(db_p)
                existing = store.lookup(rec_id)
                if existing and str(existing.get("lifecycleStatus") or "").upper() == "FINALIZED":
                    persisted = existing
                    continue
                persisted = store.persist_record_transactional(draft, is_finalized=False)
            except Exception as e:
                print(f"❌ DRAFT 写入失败 ({db_p}): {e}")

        if persisted is None and self.db_paths:
            return None
        self.last_draft_id = rec_id
        return persisted or draft

    def append_finalized_evidence(
        self,
        record_id: str,
        *,
        evidence_entry: Optional[Dict[str, Any]] = None,
        links: Optional[Dict[str, Any]] = None,
        review_update: Optional[Dict[str, Any]] = None,
        audit_reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Safely enrich an existing record (e.g. FINALIZED) with late evidence or review sidecars."""
        if not record_id or not str(record_id).strip():
            return None
        rec_id = str(record_id).strip()
        persisted = None
        for db_p in self.db_paths:
            try:
                store = CanonicalHistoryStore(db_p)
                persisted = store.append_finalized_evidence(
                    rec_id,
                    evidence_entry=evidence_entry,
                    links=links,
                    review_update=review_update,
                    audit_reason=audit_reason,
                )
            except Exception as e:
                print(f"❌ 追加已归档对局证据失败 ({db_p}): {e}")
        return persisted

if __name__ == "__main__":
    print("=== 全自动记账归档器测试 ===")
    archiver = AutoArchiver()
    
    mock_ctx = {
        "venue": "shanhu",
        "boxType": "glass",
        "box": "琉璃宝箱 · 宝石类概率提升",
        "fieldCondition": "dark",
        "settlementReady": True,
        "q": 15,
        "avg": 67571,
        "costs": {"entry": 5000, "intel": 45000},
        "settlementData": {
            "isSettlement": True,
            "clearingPrice": 454444,
            "actualTotal": 972970,
            "profit": 518526
        }
    }
    
    saved = archiver.archive_match(mock_ctx)
    if saved:
        print("✅ 测试归档成功:", json.dumps(saved, ensure_ascii=False, indent=2))
