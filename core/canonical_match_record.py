# -*- coding: utf-8 -*-
"""Canonical MatchRecord v7 builder and validators.

Provides:
1. build_canonical_match_record_v7(): Constructs a clean, contract-compliant MatchRecord v7.
2. validate_canonical_match_record_v7(): Base schema and namespace validator for all v7 records (including DRAFT).
3. validate_finalized_match_record_v7(): FINALIZED profile validator for terminal archived matches.
"""

from __future__ import annotations

import copy
import math
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

from version import APP_PRODUCT_VERSION, CANONICAL_SCHEMA_VERSION

VALID_LIFECYCLES = frozenset({"DRAFT", "FINALIZED", "CANCELLED", "CANCELED"})
REQUIRED_NAMESPACES = (
    "environment",
    "loadout",
    "costs",
    "publicIntel",
    "qualities",
    "bidding",
    "settlement",
)
QUALITY_NAMES = ("white", "green", "blue", "purple", "gold", "red")
ENVIRONMENT_CATALOG_FIELDS = (
    "venueId", "boxId", "catalogVersion", "catalogApprovalStatus", "catalogSha256",
    "gameEvidenceCohort", "venueEvidenceClass", "boxEvidenceClass",
)

# Root fields that are strictly forbidden in Canonical v7 to prevent flat legacy contamination
FORBIDDEN_ROOT_LEGACY_FIELDS = frozenset({
    "venue",
    "venueTier",
    "venueName",
    "box",
    "boxType",
    "fieldCondition",
    "fieldConditionName",
    "fieldConditionSource",
    "character",
    "lobbyToolGroup",
    "solverToolGroup",
    "toolGroup",
    "q",
    "totalItems",
    "totalGrid",
    "totalGrids",
    "avg",
    "goldAvg",
    "purpleAvg",
    "blueAvg",
    "greenAvg",
    "whiteAvg",
    "redAvg",
    "purple",
    "purpleCount",
    "goldCount",
    "blueCount",
    "redCount",
    "knownGold",
    "knownPurple",
    "knownRed",
    "identifiedShapes",
    "cost",
    "purchaseSpend",
    "isAcquired",
    "winnerName",
    "opponents",
    "historicalBids",
    "finalBids",
    "roundTimeline",
    "rounds",
    "seats",
    "myFinalBid",
    "myName",
    "leaderName",
    "leaderBid",
    "leaderTies",
    "isMyLead",
    "qualitySellSelection",
    "qualitySellSelectionSource",
    "qualitySellSelectionSources",
})


def _is_positive_finite(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val) and val > 0


def _is_finite_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val)


def _parse_known_items(raw: Any) -> List[Dict[str, Any]]:
    """Normalize raw known items (list of dicts, or string expression) into List[Dict[str, Any]]."""
    if isinstance(raw, list):
        items = []
        for it in raw:
            if isinstance(it, dict):
                items.append(dict(it))
            elif isinstance(it, str) and it.strip():
                items.append({"name": it.strip()})
        return items
    if isinstance(raw, str) and raw.strip():
        parts = [p.strip() for p in raw.split("+") if p.strip()]
        return [{"name": p} for p in parts]
    return []


def build_canonical_match_record_v7(
    match_id: Any,
    played_at: Optional[str] = None,
    lifecycle_status: str = "FINALIZED",
    source: str = "vision-auto-archiver",
    data_origin: Optional[str] = "live",
    environment: Optional[Mapping[str, Any]] = None,
    loadout: Optional[Mapping[str, Any]] = None,
    costs: Optional[Mapping[str, Any]] = None,
    public_intel: Optional[Mapping[str, Any]] = None,
    qualities: Optional[Mapping[str, Any]] = None,
    bidding: Optional[Mapping[str, Any]] = None,
    settlement: Optional[Mapping[str, Any]] = None,
    prediction_snapshot: Optional[Mapping[str, Any]] = None,
    solver_result: Optional[Mapping[str, Any]] = None,
    warehouse: Optional[Mapping[str, Any]] = None,
    product_version: str = APP_PRODUCT_VERSION,
) -> Dict[str, Any]:
    """Construct a clean, non-flattened Canonical MatchRecord v7 dictionary."""
    if isinstance(match_id, Mapping) and played_at is None:
        raw_rec = dict(match_id)
        match_id = raw_rec.get("id") or ""
        played_at = raw_rec.get("playedAt") or ""
        lifecycle_status = raw_rec.get("lifecycleStatus") or lifecycle_status
        source = raw_rec.get("source") or source
        data_origin = raw_rec.get("dataOrigin") if "dataOrigin" in raw_rec else data_origin
        environment = raw_rec.get("environment") if environment is None else environment
        loadout = raw_rec.get("loadout") if loadout is None else loadout
        costs = raw_rec.get("costs") if costs is None else costs
        public_intel = raw_rec.get("publicIntel") if public_intel is None else public_intel
        qualities = raw_rec.get("qualities") if qualities is None else qualities
        bidding = raw_rec.get("bidding") if bidding is None else bidding
        settlement = raw_rec.get("settlement") if settlement is None else settlement
        prediction_snapshot = raw_rec.get("predictionSnapshot") if prediction_snapshot is None else prediction_snapshot
        solver_result = raw_rec.get("solverResult") if solver_result is None else solver_result
        warehouse = raw_rec.get("warehouse") if warehouse is None else warehouse
        product_version = raw_rec.get("productVersion") or product_version

    env = dict(environment or {})
    ld = dict(loadout or {})
    cs = dict(costs or {})
    pub = dict(public_intel or {})
    ql = dict(qualities or {})
    bd = dict(bidding or {})
    st = dict(settlement or {})

    # Build standardized 6 qualities
    qualities_obj: Dict[str, Any] = {}
    for q_name in QUALITY_NAMES:
        q_data = dict(ql.get(q_name) or {})
        raw_items = q_data.get("knownItems") or []
        items_list = _parse_known_items(raw_items)
        q_entry = {
            "count": q_data.get("count"),
            "avg": q_data.get("avg"),
            "grid": q_data.get("grid"),
            "knownItems": items_list,
        }
        if q_name in {"purple", "gold", "red"}:
            q_entry["minCount"] = q_data.get("minCount")
        if q_name == "gold":
            q_entry["total"] = q_data.get("total")
        if q_name == "red":
            q_entry["maxCount"] = q_data.get("maxCount")
            q_entry["redInventoryComplete"] = q_data.get("redInventoryComplete")
            q_entry["settlementVerifiedRedItems"] = q_data.get("settlementVerifiedRedItems") or ""
        qualities_obj[q_name] = q_entry

    record: Dict[str, Any] = {
        "schemaVersion": CANONICAL_SCHEMA_VERSION,
        "productVersion": product_version,
        "id": str(match_id).strip(),
        "playedAt": str(played_at).strip(),
        "lifecycleStatus": lifecycle_status.upper(),
        "source": str(source).strip(),
        "dataOrigin": str(data_origin).strip().lower() if data_origin else None,
        "environment": {
            **{key: env[key] for key in ENVIRONMENT_CATALOG_FIELDS if key in env},
            "venueTier": env.get("venueTier"),
            "venue": env.get("venue"),
            "venueName": env.get("venueName"),
            "box": env.get("box"),
            "boxType": env.get("boxType"),
            "fieldCondition": env.get("fieldCondition"),
            "fieldConditionName": env.get("fieldConditionName"),
            "fieldConditionSource": env.get("fieldConditionSource"),
        },
        "loadout": {
            "character": ld.get("character"),
            "lobbyToolGroup": ld.get("lobbyToolGroup"),
            "solverToolGroup": ld.get("solverToolGroup") or "group1",
        },
        "costs": {
            "entry": cs.get("entry", 5000),
            "intel": cs.get("intel", 0),
            "other": cs.get("other", 0),
            "sunkCost": cs.get("sunkCost", (cs.get("entry", 5000) or 0) + (cs.get("intel", 0) or 0) + (cs.get("other", 0) or 0)),
            "futureIncrementalCost": cs.get("futureIncrementalCost", 0),
            "total": cs.get("total", (cs.get("sunkCost", 5000) or 0) + (cs.get("futureIncrementalCost", 0) or 0)),
        },
        "publicIntel": {
            "q": pub.get("q"),
            "totalItems": pub.get("totalItems"),
            "totalGrid": pub.get("totalGrid"),
            "avgValueBasis": pub.get("avgValueBasis") or "all_inclusive",
        },
        "qualities": qualities_obj,
        "bidding": {
            "seats": list(bd.get("seats") or []),
            "myName": bd.get("myName"),
            "myFinalBid": bd.get("myFinalBid"),
            "leaderName": bd.get("leaderName"),
            "leaderBid": bd.get("leaderBid"),
            "leaderTies": list(bd.get("leaderTies") or []),
            "isMyLead": bd.get("isMyLead"),
            "historicalBids": dict(bd.get("historicalBids") or {}),
            "finalBids": dict(bd.get("finalBids") or {}),
            "rounds": list(bd.get("rounds") or []),
        },
        "settlement": {
            "status": st.get("status"),
            "verified": st.get("verified"),
            "clearingPrice": st.get("clearingPrice"),
            "actualTotal": st.get("actualTotal"),
            "realizedProfit": st.get("realizedProfit"),
            "acquired": st.get("acquired"),
            "winner": st.get("winner"),
            "settlementWinnerName": st.get("settlementWinnerName") or st.get("winner"),
            "settlementAuctionAssistantName": st.get("settlementAuctionAssistantName") or st.get("auctionAssistant"),
            "isSelfWinner": st.get("isSelfWinner") if st.get("isSelfWinner") is not None else st.get("acquired"),
            "auctionAssistant": st.get("auctionAssistant") or st.get("settlementAuctionAssistantName"),
            "settlementItems": list(st.get("settlementItems") or []),
        },
    }

    if "truthEvidence" in st and isinstance(st["truthEvidence"], dict):
        record["settlement"]["truthEvidence"] = st["truthEvidence"]
    from session_accounting import strict_nonnegative_integer
    for key, label in (("privateBidCap", "私人出价上限"), ("bidActionCount", "可见出价次数")):
        if key in bd:
            record["bidding"][key] = strict_nonnegative_integer(bd[key], label)
    if isinstance(st.get("welfare"), dict) and "received" in st["welfare"]:
        from session_accounting import receipt_amount
        record["settlement"]["welfare"] = {"received": receipt_amount(st["welfare"]["received"])}
    if "warehouseIdentityReview" in st and isinstance(st["warehouseIdentityReview"], dict):
        record["settlement"]["warehouseIdentityReview"] = st["warehouseIdentityReview"]
    if "warehouseIdentityReviewHistory" in st:
        record["settlement"]["warehouseIdentityReviewHistory"] = st["warehouseIdentityReviewHistory"]
    if "warehouseReviewPacket" in st:
        record["settlement"]["warehouseReviewPacket"] = st["warehouseReviewPacket"]
    if "warehouseOccupancy" in st and isinstance(st["warehouseOccupancy"], dict):
        record["settlement"]["warehouseOccupancy"] = dict(st["warehouseOccupancy"])

    if "reviewUnits" in st and isinstance(st["reviewUnits"], list):
        record["settlement"]["reviewUnits"] = list(st["reviewUnits"])
        record["reviewUnits"] = list(st["reviewUnits"])
        record["warehouseReviewUnits"] = list(st["reviewUnits"])

    q_sel = st.get("qualitySellSelection")
    q_src = st.get("qualitySellSelectionSource")
    q_sources = st.get("qualitySellSelectionSources")
    from quality_sell_selection import (
        DEFAULT_SELF_ACQUIRED_SELECTION,
        DEFAULT_UNKNOWN_SELECTION,
        SOURCE_DEFAULT_SELF_ACQUIRED,
        SOURCE_UNKNOWN,
        aggregate_selection_source,
        normalize_quality_sell_selection,
        normalize_quality_sell_selection_sources,
        resolve_default_quality_sell_selection,
        sources_from_aggregate,
    )
    if q_sel is not None:
        norm_sel = normalize_quality_sell_selection(q_sel)
        record["settlement"]["qualitySellSelection"] = norm_sel
        if isinstance(q_sources, Mapping):
            norm_sources = normalize_quality_sell_selection_sources(q_sources)
        else:
            norm_sources = sources_from_aggregate(q_src)
        record["settlement"]["qualitySellSelectionSources"] = norm_sources
        record["settlement"]["qualitySellSelectionSource"] = aggregate_selection_source(norm_sources)
    elif record["settlement"].get("acquired") is True:
        record["settlement"]["qualitySellSelection"] = copy.deepcopy(DEFAULT_SELF_ACQUIRED_SELECTION)
        if isinstance(q_sources, Mapping):
            norm_sources = normalize_quality_sell_selection_sources(q_sources)
        else:
            norm_sources = sources_from_aggregate(q_src or SOURCE_DEFAULT_SELF_ACQUIRED)
        record["settlement"]["qualitySellSelectionSources"] = norm_sources
        record["settlement"]["qualitySellSelectionSource"] = aggregate_selection_source(norm_sources)
    else:
        # acquired is False or None (or q_src provided)
        record["settlement"]["qualitySellSelection"] = resolve_default_quality_sell_selection(record["settlement"].get("acquired"))
        if isinstance(q_sources, Mapping):
            norm_sources = normalize_quality_sell_selection_sources(q_sources)
        else:
            norm_sources = sources_from_aggregate(q_src or SOURCE_UNKNOWN)
        record["settlement"]["qualitySellSelectionSources"] = norm_sources
        record["settlement"]["qualitySellSelectionSource"] = aggregate_selection_source(norm_sources)

    if prediction_snapshot is not None:
        record["predictionSnapshot"] = dict(prediction_snapshot)

    if solver_result is not None:
        record["solverResult"] = dict(solver_result)

    if warehouse is not None and isinstance(warehouse, Mapping):
        record["warehouse"] = dict(warehouse)
    elif "reviewUnits" in record["settlement"]:
        ru = record["settlement"]["reviewUnits"]
        conf_count = sum(
            1
            for u in ru
            if isinstance(u, dict)
            and (
                u.get("confirmationStatus") == "CONFIRMED"
                or u.get("status") == "CONFIRMED"
                or u.get("confirmed")
            )
        )
        record["warehouse"] = {
            "itemCount": len(ru),
            "unknownCount": len(ru) - conf_count,
            "slots": [],
        }

    return record


def validate_canonical_match_record_v7(
    record: Any,
    match_id: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """Base schema and namespace validator for MatchRecord v7 (accepts both DRAFT and FINALIZED)."""
    reasons: List[str] = []
    if not isinstance(record, Mapping):
        return False, ["RECORD_NOT_DICT"]

    if record.get("schemaVersion") != CANONICAL_SCHEMA_VERSION:
        reasons.append("RECORD_SCHEMA_VERSION_UNSUPPORTED")

    prod_ver = record.get("productVersion")
    if not isinstance(prod_ver, str) or not prod_ver.strip():
        reasons.append("PRODUCT_VERSION_MISSING")

    rec_id = str(record.get("id") or "").strip()
    if not rec_id:
        reasons.append("RECORD_ID_MISSING")
    elif match_id and rec_id != str(match_id).strip():
        reasons.append("RECORD_ID_MISMATCH")

    played_at = record.get("playedAt")
    if not isinstance(played_at, str) or not played_at.strip():
        reasons.append("PLAYED_AT_MISSING")
    else:
        try:
            datetime.fromisoformat(played_at.replace("Z", "+00:00"))
        except Exception:
            reasons.append("PLAYED_AT_INVALID_ISO")

    lifecycle = str(record.get("lifecycleStatus") or "").strip().upper()
    if lifecycle not in VALID_LIFECYCLES:
        reasons.append("LIFECYCLE_STATUS_INVALID")

    src = record.get("source")
    if not isinstance(src, str) or not src.strip():
        reasons.append("SOURCE_MISSING")

    data_origin = record.get("dataOrigin")
    if data_origin is not None and (not isinstance(data_origin, str) or not data_origin.strip()):
        reasons.append("DATA_ORIGIN_INVALID")

    # Check required namespaces
    for ns in REQUIRED_NAMESPACES:
        if ns not in record:
            reasons.append(f"NAMESPACE_MISSING_{ns.upper()}")
        elif not isinstance(record[ns], Mapping):
            reasons.append(f"NAMESPACE_NOT_DICT_{ns.upper()}")

    # Qualities subdict validation
    qualities = record.get("qualities")
    if isinstance(qualities, Mapping):
        for q_name in QUALITY_NAMES:
            q_entry = qualities.get(q_name)
            if not isinstance(q_entry, Mapping):
                reasons.append(f"QUALITY_ENTRY_NOT_DICT_{q_name.upper()}")
            else:
                items = q_entry.get("knownItems")
                if items is not None and not isinstance(items, (list, str)):
                    reasons.append(f"KNOWN_ITEMS_NOT_LIST_{q_name.upper()}")

    # Optional Prediction Snapshot validation if present
    if "predictionSnapshot" in record:
        snap = record["predictionSnapshot"]
        if not isinstance(snap, Mapping):
            reasons.append("PREDICTION_SNAPSHOT_NOT_DICT")

    # Optional Settlement Truth Evidence validation if present
    settlement = record.get("settlement")
    if isinstance(settlement, Mapping) and "warehouseReviewPacket" in settlement:
        from warehouse_review_packet import validate_warehouse_review_packet, source_fingerprint_for
        packet = settlement["warehouseReviewPacket"]
        valid, _ = validate_warehouse_review_packet(packet)
        if (not valid or packet.get("recordStableKey") != record.get("id")
                or packet.get("sourceFingerprint") != source_fingerprint_for(packet)):
            reasons.append("WAREHOUSE_REVIEW_PACKET_INVALID")
    if isinstance(settlement, Mapping) and "warehouseIdentityReviewHistory" in settlement:
        from warehouse_identity_review import validate_warehouse_identity_review
        revisions = settlement["warehouseIdentityReviewHistory"]
        if not isinstance(revisions, list):
            reasons.append("WAREHOUSE_REVIEW_HISTORY_INVALID")
        else:
            for revision in revisions:
                valid, _ = validate_warehouse_identity_review(revision)
                if not valid or revision.get("recordStableKey") != record.get("id"):
                    reasons.append("WAREHOUSE_REVIEW_HISTORY_INVALID")
    if isinstance(settlement, Mapping) and "truthEvidence" in settlement:
        truth = settlement["truthEvidence"]
        if not isinstance(truth, Mapping):
            reasons.append("SETTLEMENT_TRUTH_NOT_DICT")
    if isinstance(settlement, Mapping) and "warehouseIdentityReview" in settlement:
        review = settlement["warehouseIdentityReview"]
        if not isinstance(review, Mapping):
            reasons.append("WAREHOUSE_IDENTITY_REVIEW_NOT_DICT")
        else:
            version = review.get("schemaVersion")
            if version not in ("warehouse-identity-review.v1", "warehouse-identity-review.v2"):
                reasons.append("WAREHOUSE_IDENTITY_REVIEW_SCHEMA_INVALID")
            else:
                from warehouse_identity_review import validate_warehouse_identity_review

                ok, review_reasons = validate_warehouse_identity_review(review)
                if not ok:
                    reasons.append("WAREHOUSE_IDENTITY_REVIEW_INVALID")
                    reasons.extend(f"WAREHOUSE_IDENTITY_REVIEW_{r}" for r in review_reasons)
    if isinstance(settlement, Mapping) and "warehouseOccupancy" in settlement:
        occ = settlement["warehouseOccupancy"]
        if not isinstance(occ, Mapping):
            reasons.append("SETTLEMENT_WAREHOUSE_OCCUPANCY_NOT_DICT")
        else:
            from warehouse_occupancy_adapter import validate_warehouse_occupancy

            ok, occ_reasons = validate_warehouse_occupancy(occ)
            if not ok:
                reasons.append("SETTLEMENT_WAREHOUSE_OCCUPANCY_INVALID")
                reasons.extend(f"SETTLEMENT_WAREHOUSE_OCCUPANCY_{r}" for r in occ_reasons)
    if isinstance(settlement, Mapping) and "qualitySellSelection" in settlement:
        q_sel = settlement["qualitySellSelection"]
        if q_sel is not None and not isinstance(q_sel, Mapping):
            reasons.append("SETTLEMENT_QUALITY_SELL_SELECTION_NOT_DICT")
        elif isinstance(q_sel, Mapping):
            from quality_sell_selection import CANONICAL_QUALITIES, VALID_SELECTION_STATES
            for qk, qv in q_sel.items():
                if qk not in CANONICAL_QUALITIES:
                    reasons.append(f"SETTLEMENT_QUALITY_SELL_SELECTION_INVALID_COLOR_{qk.upper()}")
                if qv not in VALID_SELECTION_STATES:
                    reasons.append(f"SETTLEMENT_QUALITY_SELL_SELECTION_INVALID_STATE_{qk.upper()}")
    if isinstance(settlement, Mapping) and "qualitySellSelectionSource" in settlement:
        q_src = settlement["qualitySellSelectionSource"]
        if q_src is not None and (not isinstance(q_src, str) or not q_src.strip()):
            reasons.append("SETTLEMENT_QUALITY_SELL_SELECTION_SOURCE_INVALID")
    if isinstance(settlement, Mapping) and "qualitySellSelectionSources" in settlement:
        q_sources = settlement["qualitySellSelectionSources"]
        if q_sources is not None:
            if not isinstance(q_sources, Mapping):
                reasons.append("SETTLEMENT_QUALITY_SELL_SELECTION_SOURCES_NOT_DICT")
            else:
                from quality_sell_selection import (
                    CANONICAL_QUALITIES,
                    VALID_SELECTION_SOURCES,
                    aggregate_selection_source,
                )
                missing_colors = [qk for qk in CANONICAL_QUALITIES if qk not in q_sources]
                if missing_colors:
                    reasons.append("SETTLEMENT_QUALITY_SELL_SELECTION_SOURCES_INCOMPLETE")
                for qk, qv in q_sources.items():
                    if qk not in CANONICAL_QUALITIES:
                        reasons.append(f"SETTLEMENT_QUALITY_SELL_SELECTION_SOURCES_INVALID_COLOR_{qk.upper()}")
                    if qv not in VALID_SELECTION_SOURCES:
                        reasons.append(f"SETTLEMENT_QUALITY_SELL_SELECTION_SOURCES_INVALID_SOURCE_{qk.upper()}")
                if not missing_colors and all(qv in VALID_SELECTION_SOURCES for qv in q_sources.values()):
                    expected_agg = aggregate_selection_source(q_sources)
                    actual_agg = settlement.get("qualitySellSelectionSource")
                    if actual_agg != expected_agg:
                        reasons.append("SETTLEMENT_QUALITY_SELL_SELECTION_SOURCE_MISMATCH")

    # Optional Warehouse Namespace validation if present
    if "warehouse" in record:
        wh = record["warehouse"]
        if not isinstance(wh, Mapping):
            reasons.append("WAREHOUSE_NOT_DICT")
        else:
            slots = wh.get("slots")
            if not isinstance(slots, list):
                reasons.append("WAREHOUSE_SLOTS_NOT_LIST")
            else:
                for idx, slot in enumerate(slots):
                    if not isinstance(slot, Mapping):
                        reasons.append(f"WAREHOUSE_SLOT_{idx}_NOT_DICT")
                    else:
                        for req_f in ("col", "row", "w", "h", "rarity", "evidenceLevel"):
                            if req_f not in slot:
                                reasons.append(f"WAREHOUSE_SLOT_{idx}_MISSING_{req_f.upper()}")
                        if "identifiedName" in slot and slot["identifiedName"] is not None:
                            if not isinstance(slot["identifiedName"], str):
                                reasons.append(f"WAREHOUSE_SLOT_{idx}_IDENTIFIED_NAME_NOT_STRING")
                            if slot.get("rarity") == "unknown" or slot.get("evidenceLevel") == "OUTLINE_ONLY":
                                reasons.append(f"WAREHOUSE_SLOT_{idx}_UNKNOWN_WITH_IDENTIFIED_NAME")
                        if "identityStatus" in slot and slot["identityStatus"] is not None:
                            if slot["identityStatus"] not in ("UNKNOWN", "CANDIDATE", "EXACT"):
                                reasons.append(f"WAREHOUSE_SLOT_{idx}_IDENTITY_STATUS_INVALID")
                        if "candidates" in slot and slot["candidates"] is not None:
                            if not isinstance(slot["candidates"], list):
                                reasons.append(f"WAREHOUSE_SLOT_{idx}_CANDIDATES_NOT_LIST")

    return len(reasons) == 0, reasons


def validate_finalized_match_record_v7(
    record: Any,
    match_id: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """FINALIZED profile validator for MatchRecord v7.

    Requires full Base validation + lifecycleStatus == FINALIZED + verified settlement facts.
    """
    is_base_valid, base_reasons = validate_canonical_match_record_v7(record, match_id=match_id)
    reasons: List[str] = list(base_reasons)

    if not isinstance(record, Mapping):
        return False, reasons

    # Forbid root-level legacy flatten fields on FINALIZED records
    for forbidden in FORBIDDEN_ROOT_LEGACY_FIELDS:
        if forbidden in record:
            reasons.append(f"FORBIDDEN_LEGACY_FLAT_FIELD_{forbidden.upper()}")

    lifecycle = str(record.get("lifecycleStatus") or "").strip().upper()
    if lifecycle != "FINALIZED":
        reasons.append("FINALIZED_PROFILE_LIFECYCLE_NOT_FINALIZED")

    settlement = record.get("settlement")
    if not isinstance(settlement, Mapping):
        reasons.append("FINALIZED_PROFILE_SETTLEMENT_MISSING")
    else:
        if settlement.get("verified") is not True:
            reasons.append("FINALIZED_PROFILE_SETTLEMENT_NOT_VERIFIED")
        if str(settlement.get("status") or "").lower() != "verified":
            reasons.append("FINALIZED_PROFILE_SETTLEMENT_STATUS_NOT_VERIFIED")
        if not _is_positive_finite(settlement.get("actualTotal")):
            reasons.append("FINALIZED_PROFILE_ACTUAL_TOTAL_INVALID")
        if not _is_positive_finite(settlement.get("clearingPrice")):
            reasons.append("FINALIZED_PROFILE_CLEARING_PRICE_INVALID")
        if not _is_finite_number(settlement.get("realizedProfit")):
            reasons.append("FINALIZED_PROFILE_REALIZED_PROFIT_INVALID")
        if not isinstance(settlement.get("acquired"), bool):
            reasons.append("FINALIZED_PROFILE_ACQUIRED_INVALID")
        if not str(settlement.get("winner") or "").strip():
            reasons.append("FINALIZED_PROFILE_WINNER_MISSING")

    env = record.get("environment")
    if isinstance(env, Mapping):
        if not str(env.get("box") or "").strip():
            reasons.append("FINALIZED_PROFILE_BOX_MISSING")
        if not str(env.get("fieldCondition") or "").strip():
            reasons.append("FINALIZED_PROFILE_FIELD_CONDITION_MISSING")

    reasons = list(dict.fromkeys(reasons))
    return len(reasons) == 0, reasons
