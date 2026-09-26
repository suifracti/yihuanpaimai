# -*- coding: utf-8 -*-
"""Shared current-match owner for Manual / later Vision adapters.

Holds one live DRAFT at a time. Does not talk to Solver, OCR, or Shadow.
The process that constructs CurrentMatch owns the instance — never import a
module-level singleton from here.
"""

from __future__ import annotations

import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional

from acquisition_authority import acquired_bool


FACT_KEYS = (
    "privateBidCap",
    "bidActionCount",
    "welfareReceived",
    "sparkle",
    "venueId",
    "venueTier",
    "venue",
    "boxId",
    "box",
    "boxType",
    "fieldCondition",
    "fieldConditionName",
    "q",
    "goldAvg",
    "purpleCount",
    "purple",
    "purpleAvg",
    "goldCount",
    "goldTotal",
    "goldMinCount",
    "goldGrid",
    "purpleMinCount",
    "purpleGrid",
    "redCount",
    "redMinCount",
    "redMaxCount",
    "redGrid",
    "redInventoryComplete",
    "settlementVerifiedRedItems",
    "whiteCount",
    "whiteAvg",
    "whiteGrid",
    "greenCount",
    "greenAvg",
    "greenGrid",
    "blueCount",
    "blueAvg",
    "blueGrid",
    "totalItems",
    "totalGrid",
    "totalGrids",
    "avgValueBasis",
    "knownGold",
    "knownPurple",
    "knownRed",
    "knownWhite",
    "knownGreen",
    "knownBlue",
    "leaderBid",
    "seats",
    "roundNo",
    "historicalBids",
    "finalBids",
    "leaderName",
    "leaderTies",
    "myName",
    "isMyLead",
    "myBid",
    "intelFacts",
    "intelObservations",
    "intelCardReadings",
    "publicCardEvents",
    "targetProfit",
    "character",
    "entryCost",
    "intelCost", "otherCost", "futureIncrementalCost",
    "catalogVersion",
    "catalogApprovalStatus",
    "catalogSha256",
    "gameEvidenceCohort",
    "venueEvidenceClass",
    "boxEvidenceClass",
    "clearingPrice",
    "actualTotal",
    "realizedProfit",
    "didCurrentUserAcquire",
    "isAcquired",
    "winner",
    "settlementWinnerName",
    "settlementAuctionAssistantName",
    "auctionAssistant",
    "isSelfWinner",
    "settlementItems",
    "settlementTruthEvidence",
    "settlementEvidence",
    "settlementReady",
    "settlementFinalized",
    "settlementLedgerVerified",
    "settlementLedgerStatus",
    "settlementLedgerDelta",
    "warehouse",
    "warehouseOccupancy",
    "auctionEvidence",
    "qualitySellSelection",
    "qualitySellSelectionSource",
    "qualitySellSelectionSources",
)

KNOWN_KEYS = ("knownGold", "knownPurple", "knownRed", "knownWhite", "knownGreen", "knownBlue")
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
INT_KEYS = (
    "q", "goldAvg", "purpleCount", "purple", "purpleAvg", "goldCount",
    "goldTotal", "goldMinCount", "goldGrid", "purpleMinCount", "purpleGrid",
    "redCount", "redMinCount", "redMaxCount", "redGrid",
    "whiteCount", "whiteAvg", "whiteGrid",
    "greenCount", "greenAvg", "greenGrid",
    "blueCount", "blueAvg", "blueGrid",
    "totalItems", "totalGrid", "totalGrids", "entryCost", "intelCost", "otherCost", "futureIncrementalCost", "leaderBid",
    "targetProfit", "clearingPrice", "actualTotal", "realizedProfit",
    "roundNo", "myBid",
)
FIXED_FACT_KEYS = frozenset({
    "venueId",
    "venueTier",
    "venue",
    "boxId",
    "box",
    "boxType",
    "fieldCondition",
    "fieldConditionName",
    "entryCost",
    "catalogVersion",
    "catalogApprovalStatus",
    "catalogSha256",
    "gameEvidenceCohort",
    "venueEvidenceClass",
    "boxEvidenceClass",
})
USER_CONFIRMED_FACT_KEYS = frozenset({
    "venueId", "venueTier", "venue", "venueName",
    "boxId", "box", "boxType",
    "fieldCondition", "fieldConditionName",
    "q", "totalItems", "totalGrid", "totalGrids",
    "whiteCount", "whiteAvg", "whiteGrid", "knownWhite",
    "greenCount", "greenAvg", "greenGrid", "knownGreen",
    "blueCount", "blueAvg", "blueGrid", "knownBlue",
    "purpleCount", "purple", "purpleAvg", "purpleGrid", "knownPurple",
    "goldCount", "goldAvg", "goldGrid", "knownGold",
    "redCount", "redGrid", "knownRed",
    "sparkle",
    "privateBidCap", "bidActionCount",
    "qualitySellSelection",
})
MISSING_BOX_VALUES = frozenset({
    None,
    "",
    "未知箱型",
    "未知/其他",
    "未知 / 其他",
    "unknown",
    "未选择",
    "等待选择宝箱",
    "请选择宝箱",
})
MISSING_VENUE_VALUES = frozenset({
    None,
    "",
    "未知会场",
    "未知场地",
    "unknown",
    "未选择",
    "等待选择会场",
    "请选择会场",
})
AUDIT_LOG_LIMIT = 200


@dataclass
class FieldState:
    value: Any = None
    source: str = "manual"
    status: str = "empty"
    observed_at: str = ""
    evidence_refs: Any = None
    match_generation: int = 0
    revision: int = 0
    protected: bool = False
    candidate: Any = None


def _blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _as_int(value: Any) -> Optional[int]:
    value = _blank_to_none(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return int(number)


def _as_known_expr(value: Any) -> str:
    """Keep the 0.6 constraint expression intact. Never parse/rebuild."""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for it in value:
            if isinstance(it, dict) and it.get("name"):
                parts.append(str(it["name"]).strip())
            elif isinstance(it, str) and it.strip():
                parts.append(it.strip())
        return "+".join(parts)
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def is_missing_observation(key: str, value: Any) -> bool:
    """True when a patch value is absence, not an observed/confirmed fact."""
    if key in KNOWN_KEYS:
        return value is None or value == ""
    if key in {"box", "boxId", "boxType"}:
        if value is None:
            return True
        if isinstance(value, str) and value.strip() in MISSING_BOX_VALUES:
            return True
        return False
    if key in {"venue", "venueId", "venueTier"}:
        if value is None:
            return True
        if isinstance(value, str) and value.strip() in MISSING_VENUE_VALUES:
            return True
        return False
    if key in {"fieldCondition", "fieldConditionName"}:
        if value is None:
            return True
        if isinstance(value, str) and value.strip().lower() in {"unknown", "未选择", "未知", "none", ""}:
            return True
        return False
    if key in {"seats", "intelObservations", "intelCardReadings", "publicCardEvents"}:
        if key == "seats":
            if value is None or value == []:
                return True
            if isinstance(value, list):
                has_any_bid = any(
                    isinstance(s, dict) and (
                        s.get("observationStatus") == "VISIBLE"
                        or s.get("currentBid") is not None
                        or (s.get("bid") is not None and s.get("observationStatus") != "UNOBSERVED")
                    )
                    for s in value
                )
                return not has_any_bid
        return value is None or value == []
    if key in {"historicalBids", "finalBids", "intelFacts", "auctionEvidence"}:
        return value is None or value == {}
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _now_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _normalize_intent(source: str, intent: Optional[str]) -> str:
    if intent in {"observe", "confirm", "clear", "restore_auto", "snapshot"}:
        return intent
    if source in {"vision", "triggered_snapshot", "capture", "replay"}:
        return "observe"
    if source == "manual":
        return "confirm"
    return "observe"


def empty_facts() -> Dict[str, Any]:
    return {
        "privateBidCap": None,
        "bidActionCount": None,
        "welfareReceived": None,
        "sparkle": None,
        "venueId": None,
        "venueTier": None,
        "venue": None,
        "boxId": None,
        "box": None,
        "boxType": None,
        "fieldCondition": None,
        "fieldConditionName": None,
        "q": None,
        "goldAvg": None,
        "purpleCount": None,
        "purple": None,
        "purpleAvg": None,
        "goldCount": None,
        "goldTotal": None,
        "goldMinCount": None,
        "goldGrid": None,
        "purpleMinCount": None,
        "purpleGrid": None,
        "redCount": None,
        "redMinCount": None,
        "redMaxCount": None,
        "redGrid": None,
        "redInventoryComplete": None,
        "settlementVerifiedRedItems": "",
        "whiteCount": None,
        "whiteAvg": None,
        "whiteGrid": None,
        "greenCount": None,
        "greenAvg": None,
        "greenGrid": None,
        "blueCount": None,
        "blueAvg": None,
        "blueGrid": None,
        "totalItems": None,
        "totalGrid": None,
        "totalGrids": None,
        "avgValueBasis": None,
        "knownGold": "",
        "knownPurple": "",
        "knownRed": "",
        "knownWhite": "",
        "knownGreen": "",
        "knownBlue": "",
        "leaderBid": None,
        "seats": [],
        "roundNo": None,
        "historicalBids": {},
        "finalBids": {},
        "leaderName": None,
        "leaderTies": [],
        "myName": None,
        "isMyLead": None,
        "myBid": None,
        "intelFacts": None,
        "intelObservations": [],
        "intelCardReadings": [],
        "publicCardEvents": [],
        "auctionEvidence": None,
        "targetProfit": None,
        "character": None,
        "entryCost": None,
        "intelCost": 0, "otherCost": 0, "futureIncrementalCost": 0,
        "catalogVersion": None,
        "catalogApprovalStatus": None,
        "catalogSha256": None,
        "gameEvidenceCohort": None,
        "venueEvidenceClass": None,
        "boxEvidenceClass": None,
        "clearingPrice": None,
        "actualTotal": None,
        "realizedProfit": None,
        "didCurrentUserAcquire": None,
        "isAcquired": None,
        "winner": None,
        "settlementItems": [],
        "settlementTruthEvidence": None,
        "settlementEvidence": None,
        "settlementReady": False,
        "settlementFinalized": False,
        "settlementLedgerVerified": False,
        "settlementLedgerStatus": "pending",
        "settlementLedgerDelta": None,
        "warehouse": None,
        "warehouseOccupancy": None,
        "qualitySellSelection": None,
        "qualitySellSelectionSource": None,
        "qualitySellSelectionSources": None,
    }


class CurrentMatch:
    def __init__(self) -> None:
        self._seq = 0
        self.id = ""
        self.lifecycle_status = "DRAFT"
        self.source = "manual"
        self.data_origin = "live"
        self.created_at = ""
        self.updated_at = ""
        self.facts: Dict[str, Any] = empty_facts()
        self.field_states: Dict[str, FieldState] = {}
        self.facts_revision = 0
        self.audit_log: List[Dict[str, Any]] = []
        self._seats_round_no: Optional[int] = None
        self.begin_next_match()

    def begin_next_match(self) -> Dict[str, Any]:
        """Start a new DRAFT. Box / fieldCondition are never inherited."""
        self._seq += 1
        now = time.time()
        self.id = f"draft_{uuid.uuid4().hex}"
        self.lifecycle_status = "DRAFT"
        self.source = "manual"
        self.data_origin = getattr(self, "data_origin", "live") or "live"
        self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
        self.updated_at = self.created_at
        self.facts = empty_facts()
        self.field_states = {}
        self.facts_revision = 0
        self.audit_log = []
        self._seats_round_no = None
        return self.snapshot()

    def field_audit(self) -> List[Dict[str, Any]]:
        return list(self.audit_log)

    def restore_field_states(self, raw_states: Optional[Dict[str, Any]]) -> None:
        if not isinstance(raw_states, dict):
            return
        restored: Dict[str, FieldState] = {}
        for key, payload in raw_states.items():
            if key not in FACT_KEYS or not isinstance(payload, dict):
                continue
            restored[key] = FieldState(
                value=payload.get("value"),
                source=str(payload.get("source") or "manual"),
                status=str(payload.get("status") or "empty"),
                observed_at=str(payload.get("observed_at") or payload.get("observedAt") or ""),
                evidence_refs=payload.get("evidence_refs", payload.get("evidenceRefs")),
                match_generation=int(payload.get("match_generation") or payload.get("matchGeneration") or self._seq),
                revision=int(payload.get("revision") or 0),
                protected=bool(payload.get("protected")),
                candidate=payload.get("candidate"),
            )
            if key in self.facts and restored[key].status in {"observed", "confirmed", "cleared"}:
                self.facts[key] = restored[key].value
        if restored:
            self.field_states.update(restored)

    def _record_audit(self, row: Dict[str, Any]) -> None:
        self.audit_log.append(row)
        if len(self.audit_log) > AUDIT_LOG_LIMIT:
            self.audit_log = self.audit_log[-AUDIT_LOG_LIMIT:]

    def _coerce_value(self, key: str, raw: Any) -> Any:
        if key in ("privateBidCap", "bidActionCount"):
            from session_accounting import strict_nonnegative_integer
            return strict_nonnegative_integer(raw, "私人出价上限" if key == "privateBidCap" else "可见出价次数")
        if key == "welfareReceived":
            from session_accounting import receipt_amount
            return receipt_amount(raw)
        if key == "sparkle":
            # Preserve invalid evidence for the solver to reject; never coerce
            # fractional counts or discard contradictory named items.
            return deepcopy(raw)
        if key in {"intelFacts", "intelObservations", "intelCardReadings"}:
            return deepcopy(raw)
        if key == "publicCardEvents":
            from public_intel_ledger import admit_public_card_events
            return admit_public_card_events(raw)
        if key in KNOWN_KEYS:
            return _as_known_expr(raw)
        if key in INT_KEYS:
            return _as_int(raw)
        if key in {
            "settlementItems", "settlementTruthEvidence", "settlementEvidence",
            "warehouse", "warehouseOccupancy", "seats", "historicalBids", "finalBids",
            "leaderTies", "intelFacts", "intelObservations", "auctionEvidence",
        }:
            return raw
        if key == "qualitySellSelection":
            if raw is None:
                return None
            from quality_sell_selection import normalize_quality_sell_selection
            return normalize_quality_sell_selection(raw)
        if key == "qualitySellSelectionSource":
            return str(raw).strip() if raw is not None else None
        if key == "qualitySellSelectionSources":
            if raw is None:
                return None
            from quality_sell_selection import normalize_quality_sell_selection_sources
            if not isinstance(raw, dict):
                return None
            return normalize_quality_sell_selection_sources(raw)
        if key in {"isAcquired", "didCurrentUserAcquire", "isMyLead"}:
            return acquired_bool(raw) if key != "isMyLead" else (bool(raw) if raw is not None else None)
        if key in {"settlementReady", "settlementFinalized", "settlementLedgerVerified", "redInventoryComplete"}:
            return bool(raw) if raw is not None else None
        value = _blank_to_none(raw)
        if isinstance(value, str):
            return value.strip()
        return value

    def _write_field(
        self,
        next_facts: Dict[str, Any],
        key: str,
        value: Any,
        *,
        source: str,
        status: str,
        protected: bool,
        observed_at: str,
        evidence_refs: Any,
        candidate: Any = None,
    ) -> None:
        self.facts_revision += 1
        next_facts[key] = value
        self.field_states[key] = FieldState(
            value=value,
            source=source,
            status=status,
            observed_at=observed_at,
            evidence_refs=evidence_refs,
            match_generation=self._seq,
            revision=self.facts_revision,
            protected=protected,
            candidate=candidate,
        )

    def apply_warehouse_identity_projection(
        self,
        patch: Optional[Dict[str, Any]],
        *,
        command_id: Optional[str] = None,
        observed_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply the worker's multiset projection of physical warehouse identities.

        The projection may recompose a manually protected known-items field
        from its preserved user entries and the current warehouse ledger. Keep
        the protection bit while recording that the combined value now comes
        from the instance ledger.
        """
        if not isinstance(patch, dict):
            return self.snapshot()
        allowed = {"knownGold", "knownPurple", "knownRed"}
        if any(key not in allowed for key in patch):
            raise ValueError("warehouse identity projection contains an unsupported fact")
        stamp = observed_at or _now_stamp()
        cmd_id = command_id or uuid.uuid4().hex
        for key, raw in patch.items():
            value = self._coerce_value(key, raw)
            old_value = self.facts.get(key)
            if value == old_value:
                continue
            previous = self.field_states.get(key)
            self.facts_revision += 1
            self.facts[key] = value
            self.field_states[key] = FieldState(
                value=value,
                source="warehouse_identity_ledger",
                status=previous.status if previous and previous.status not in {"empty", "cleared"} else "observed",
                observed_at=(previous.observed_at if previous and previous.observed_at else stamp),
                evidence_refs=previous.evidence_refs if previous else None,
                match_generation=self._seq,
                revision=self.facts_revision,
                protected=bool(previous.protected) if previous else False,
                candidate=previous.candidate if previous else None,
            )
            self._record_audit({
                "commandId": cmd_id,
                "field": key,
                "decision": "accept",
                "reason": "WAREHOUSE_IDENTITY_LEDGER_PROJECTION",
                "oldValue": old_value,
                "newValue": value,
                "source": "warehouse_identity_ledger",
                "intent": "projection",
                "matchId": self.id,
                "matchGeneration": self._seq,
                "factsRevision": self.facts_revision,
                "sceneGeneration": None,
                "observedAt": stamp,
            })
        self.updated_at = stamp
        return self.snapshot()

    def apply_facts(
        self,
        patch: Optional[Dict[str, Any]],
        source: str = "manual",
        *,
        intent: Optional[str] = None,
        cleared_fields: Optional[Iterable[str]] = None,
        restore_auto_fields: Optional[Iterable[str]] = None,
        command_id: Optional[str] = None,
        scene_generation: Any = None,
        observed_at: Optional[str] = None,
        evidence_refs: Any = None,
    ) -> Dict[str, Any]:
        if not isinstance(patch, dict) and not cleared_fields and not restore_auto_fields:
            return self.snapshot()
        # Validate before any field/audit mutation so bad receipts cannot partly
        # apply an otherwise valid multi-field command.
        from session_accounting import receipt_amount
        if isinstance(patch, dict):
            patch = dict(patch)
            bidding = patch.get("bidding") or {}
            for key in ("privateBidCap", "bidActionCount"):
                if key not in patch and isinstance(bidding, dict) and key in bidding:
                    patch[key] = bidding[key]
                if key in patch:
                    patch[key] = self._coerce_value(key, patch[key])
            st = patch.get("settlement") or {}
            if "welfareReceived" not in patch and isinstance(st, dict):
                if isinstance(st.get("welfare"), dict) and "received" in st["welfare"]:
                    patch["welfareReceived"] = st["welfare"]["received"]
                elif "welfareReceived" in st:
                    patch["welfareReceived"] = st["welfareReceived"]
            if "welfareReceived" in patch:
                patch["welfareReceived"] = receipt_amount(patch["welfareReceived"])
        flat_patch = dict(patch or {})
        from intel_evidence_record import restore_intel_evidence
        for key, value in restore_intel_evidence(flat_patch).items():
            flat_patch.setdefault(key, value)
        if isinstance(flat_patch.get("publicIntel"), dict):
            pub = flat_patch["publicIntel"]
            for k in ("q", "totalItems", "totalGrid", "totalGrids", "avgValueBasis"):
                if k in pub and k not in flat_patch:
                    flat_patch[k] = pub[k]
        if isinstance(flat_patch.get("qualities"), dict):
            quals = flat_patch["qualities"]
            for q_name in ("white", "green", "blue", "purple", "gold", "red"):
                if isinstance(quals.get(q_name), dict):
                    q_data = quals[q_name]
                    for sub_k in ("count", "avg", "grid", "knownItems", "minCount", "total", "maxCount", "redInventoryComplete", "settlementVerifiedRedItems"):
                        if sub_k in q_data:
                            target_key = f"{q_name}{sub_k.capitalize()}" if sub_k != "knownItems" else f"known{q_name.capitalize()}"
                            if sub_k == "total" and q_name == "gold":
                                target_key = "goldTotal"
                            elif sub_k == "redInventoryComplete":
                                target_key = "redInventoryComplete"
                            elif sub_k == "settlementVerifiedRedItems":
                                target_key = "settlementVerifiedRedItems"
                            if target_key not in flat_patch:
                                flat_patch[target_key] = q_data[sub_k]
        if isinstance(flat_patch.get("environment"), dict):
            env = flat_patch["environment"]
            for k in ("venueId", "venueTier", "venue", "boxId", "box", "boxType", "fieldCondition", "fieldConditionName"):
                if k in env and k not in flat_patch:
                    flat_patch[k] = env[k]
        if isinstance(flat_patch.get("loadout"), dict):
            ld = flat_patch["loadout"]
            if "character" in ld and "character" not in flat_patch:
                flat_patch["character"] = ld["character"]
        if isinstance(flat_patch.get("settlement"), dict):
            st = flat_patch["settlement"]
            for k in ("clearingPrice", "actualTotal", "realizedProfit", "profit", "isAcquired", "acquired", "winner", "settlementWinnerName", "settlementAuctionAssistantName", "auctionAssistant", "isSelfWinner", "settlementItems", "truthEvidence", "settlementTruthEvidence", "warehouseOccupancy", "qualitySellSelection", "qualitySellSelectionSource"):
                if k in st:
                    if k == "profit" and "realizedProfit" not in flat_patch:
                        flat_patch["realizedProfit"] = st[k]
                    elif k == "truthEvidence" and "settlementTruthEvidence" not in flat_patch:
                        flat_patch["settlementTruthEvidence"] = st[k]
                    elif k == "isAcquired" and "isAcquired" not in flat_patch:
                        flat_patch["isAcquired"] = st[k]
                    elif k == "acquired" and "isAcquired" not in flat_patch and "didCurrentUserAcquire" not in flat_patch:
                        flat_patch["isAcquired"] = st[k]
                    elif k not in flat_patch:
                        flat_patch[k] = st[k]
        if "acquired" in flat_patch and "isAcquired" not in flat_patch and "didCurrentUserAcquire" not in flat_patch:
            flat_patch["isAcquired"] = flat_patch["acquired"]
        if "winner" in flat_patch and "settlementWinnerName" not in flat_patch:
            flat_patch["settlementWinnerName"] = flat_patch["winner"]
        if "auctionAssistant" in flat_patch and "settlementAuctionAssistantName" not in flat_patch:
            flat_patch["settlementAuctionAssistantName"] = flat_patch["auctionAssistant"]

        # OCR animation values are observations, not a verified settlement bill.
        # Manual/review corrections retain their existing explicit authority.
        is_settlement_truth = bool(
            flat_patch.get("settlementReady")
            or flat_patch.get("settlementFinalized")
            or (flat_patch.get("clearingPrice") is not None and flat_patch.get("actualTotal") is not None)
        )
        if source == "vision" and not is_settlement_truth:
            for key in ("clearingPrice", "actualTotal", "realizedProfit", "settlementTruthEvidence"):
                flat_patch.pop(key, None)

        resolved_intent = _normalize_intent(source, intent)
        stamp = observed_at or _now_stamp()
        cmd_id = command_id or uuid.uuid4().hex
        cleared_set = {key for key in (cleared_fields or []) if key in FACT_KEYS}
        restore_set = {key for key in (restore_auto_fields or []) if key in FACT_KEYS}
        accepted: Dict[str, Any] = {}
        next_facts = dict(self.facts)
        incoming_round = flat_patch.get("roundNo")
        previous_round = next_facts.get("roundNo")
        vision_round_rollover = (
            source == "vision" and incoming_round is not None and previous_round is not None
            and incoming_round != previous_round
        )

        def audit(field_name: str, decision: str, reason: str, old: Any, new: Any) -> None:
            self._record_audit({
                "commandId": cmd_id,
                "field": field_name,
                "decision": decision,
                "reason": reason,
                "oldValue": old,
                "newValue": new,
                "source": source,
                "intent": resolved_intent,
                "matchId": self.id,
                "matchGeneration": self._seq,
                "factsRevision": self.facts_revision,
                "sceneGeneration": scene_generation,
                "observedAt": stamp,
            })

        for key in restore_set:
            state = self.field_states.get(key) or FieldState(value=next_facts.get(key))
            state.protected = False
            state.source = "auto"
            if state.status == "cleared":
                state.status = "empty"
            self.field_states[key] = state
            audit(key, "accept", "RESTORE_AUTO", state.value, state.value)

        for key in FACT_KEYS:
            if key in restore_set and key not in cleared_set and key not in flat_patch:
                continue
            if key in cleared_set:
                old = next_facts.get(key)
                cleared_value = "" if key in KNOWN_KEYS else ([] if key == "publicCardEvents" else None)
                self._write_field(
                    next_facts, key, cleared_value, source=source, status="cleared",
                    protected=True, observed_at=stamp, evidence_refs=evidence_refs,
                )
                accepted[key] = cleared_value
                audit(key, "accept", "EXPLICIT_CLEAR", old, cleared_value)
                continue
            if key not in flat_patch:
                continue
            raw = flat_patch[key]
            new_value = self._coerce_value(key, raw)
            old_value = next_facts.get(key)
            if key == "publicCardEvents":
                from public_intel_ledger import admit_public_card_events
                incoming = raw if isinstance(raw, list) else []
                new_value = admit_public_card_events(incoming, existing=old_value)
            if key == "intelCardReadings" and source == "vision" and isinstance(new_value, list):
                # This field is the DRAFT's read-only OCR evidence, not a
                # current-frame fact. Keep transient text when later OCR is
                # blank; no reading here grants solver or cost authority.
                readings = {}
                for reading in list(old_value or []) + new_value:
                    if not isinstance(reading, dict):
                        continue
                    raw_text = reading.get("rawText")
                    if not isinstance(raw_text, str) or not raw_text.strip():
                        continue
                    round_no = reading.get("round") if type(reading.get("round")) is int else None
                    identity = (round_no, "".join(raw_text.split()))
                    prior = readings.get(identity)
                    if prior is None or (reading.get("is_physical_ocr") is True
                                         and prior.get("is_physical_ocr") is not True):
                        readings[identity] = deepcopy(reading)
                new_value = list(readings.values())[-64:]

            if key == "seats" and isinstance(new_value, list):
                inc_round_raw = (
                    flat_patch.get("round")
                    or flat_patch.get("roundNo")
                    or next_facts.get("roundNo")
                    or next_facts.get("round")
                )
                inc_scene = flat_patch.get("scene") or next_facts.get("scene")
                is_settlement = (
                    inc_scene == "SETTLEMENT"
                    or flat_patch.get("isSettlement")
                    or next_facts.get("isSettlement")
                )

                has_incoming_bids = any(
                    isinstance(s, dict) and (
                        s.get("observationStatus") == "VISIBLE"
                        or s.get("currentBid") is not None
                    )
                    for s in new_value
                )
                if is_settlement and not has_incoming_bids and isinstance(old_value, list) and old_value:
                    audit(key, "reject", "SETTLEMENT_EMPTY_PRESERVES_FINAL_BIDS", old_value, new_value)
                    continue

                round_changed = False
                if inc_round_raw is not None:
                    try:
                        inc_r = int(inc_round_raw)
                    except (ValueError, TypeError):
                        inc_r = None
                    if inc_r is not None and self._seats_round_no is not None and inc_r != self._seats_round_no:
                        # New round started: clear live bids for the new round while preserving names
                        round_changed = True
                        old_value = [
                            {**s, "bid": None, "currentBid": None, "observationStatus": "UNOBSERVED"}
                            if isinstance(s, dict) else s
                            for s in (old_value or [])
                        ]
                    if inc_r is not None:
                        self._seats_round_no = inc_r

                if isinstance(old_value, list) and old_value:
                    old_by_slot = {
                        s.get("slot", i + 1): s
                        for i, s in enumerate(old_value)
                        if isinstance(s, dict)
                    }
                    merged_seats = []
                    for i, ns in enumerate(new_value):
                        if not isinstance(ns, dict):
                            merged_seats.append(ns)
                            continue
                        slot = ns.get("slot", i + 1)
                        os = old_by_slot.get(slot, {})
                        ms = dict(ns)
                        if not ms.get("name") and os.get("name"):
                            ms["name"] = os.get("name")
                        if "isMe" not in ms and os.get("isMe"):
                            ms["isMe"] = os.get("isMe")
                        incoming_observed = (
                            ms.get("observationStatus") == "VISIBLE"
                            or ms.get("currentBid") is not None
                        )
                        if not incoming_observed:
                            old_observed = (
                                os.get("observationStatus") == "VISIBLE"
                                or os.get("currentBid") is not None
                            )
                            if old_observed:
                                ms["currentBid"] = os.get("currentBid")
                                ms["bid"] = os.get("bid")
                                ms["observationStatus"] = os.get("observationStatus", "VISIBLE")
                        merged_seats.append(ms)
                    new_value = merged_seats

            state = self.field_states.get(key)
            if (vision_round_rollover and key in {"leaderBid", "myBid", "leaderName", "isMyLead"}
                    and new_value is None and not (state and state.protected)):
                # A new round has no current leader until a visible quote arrives.
                # This does not clear manually protected facts or past-round bids.
                self._write_field(
                    next_facts, key, None, source=source, status="empty",
                    protected=False, observed_at=stamp, evidence_refs=evidence_refs,
                )
                accepted[key] = None
                audit(key, "accept", "ROUND_ROLLOVER_EMPTY", old_value, None)
                continue
            missing = is_missing_observation(key, raw if key in KNOWN_KEYS else new_value)
            if key == "seats" and locals().get("round_changed"):
                missing = False

            if missing and resolved_intent != "clear":
                if old_value not in (None, "") or (state and state.status in {"observed", "confirmed"}):
                    audit(key, "reject", "MISSING_DOES_NOT_CLEAR", old_value, new_value)
                    continue
                if resolved_intent == "snapshot":
                    audit(key, "reject", "SNAPSHOT_NULL_NOT_OVERRIDE", old_value, new_value)
                    continue
                if old_value in (None, "") and not (state and state.status in {"observed", "confirmed", "cleared"}):
                    continue

            if resolved_intent == "clear":
                cleared_val = [] if key == "publicCardEvents" else None
                self._write_field(
                    next_facts, key, cleared_val, source=source, status="cleared",
                    protected=True, observed_at=stamp, evidence_refs=evidence_refs,
                )
                if key == "qualitySellSelection":
                    self._write_field(
                        next_facts, "qualitySellSelectionSources", None, source=source,
                        status="cleared", protected=True, observed_at=stamp,
                        evidence_refs=evidence_refs,
                    )
                    self._write_field(
                        next_facts, "qualitySellSelectionSource", None, source=source,
                        status="cleared", protected=True, observed_at=stamp,
                        evidence_refs=evidence_refs,
                    )
                accepted[key] = cleared_val
                audit(key, "accept", "EXPLICIT_CLEAR", old_value, cleared_val)
                continue

            # Boundary 2: per-color provenance.
            # qualitySellSelection is protected PER COLOR, never as one atomic
            # dict.  A manual toggle of one color must not freeze the other five,
            # and a vision observation must not relabel untouched colors.
            if key == "qualitySellSelection":
                from quality_sell_selection import (
                    aggregate_selection_source,
                    manual_override_colors,
                    merge_quality_sell_selection,
                    normalize_quality_sell_selection_sources,
                    sources_from_aggregate,
                )
                cur_sel = self.facts.get("qualitySellSelection")
                raw_sources = self.facts.get("qualitySellSelectionSources")
                if isinstance(raw_sources, dict):
                    cur_sources = normalize_quality_sell_selection_sources(raw_sources)
                else:
                    cur_sources = sources_from_aggregate(self.facts.get("qualitySellSelectionSource"))
                incoming_sources = flat_patch.get("qualitySellSelectionSources")
                explicit_manual = (
                    manual_override_colors(incoming_sources)
                    if isinstance(incoming_sources, dict) else ()
                )
                merged_sel, merged_sources = merge_quality_sell_selection(
                    cur_sel, cur_sources, new_value,
                    intent=resolved_intent,
                    explicit_manual_colors=explicit_manual,
                )
                merged_status = "confirmed" if resolved_intent == "confirm" else "observed"
                any_manual = bool(manual_override_colors(merged_sources))
                self._write_field(
                    next_facts, "qualitySellSelection", merged_sel, source=source,
                    status=merged_status, protected=any_manual,
                    observed_at=stamp, evidence_refs=evidence_refs,
                )
                self._write_field(
                    next_facts, "qualitySellSelectionSources", merged_sources, source=source,
                    status=merged_status, protected=False,
                    observed_at=stamp, evidence_refs=evidence_refs,
                )
                self._write_field(
                    next_facts, "qualitySellSelectionSource",
                    aggregate_selection_source(merged_sources), source=source,
                    status=merged_status, protected=False,
                    observed_at=stamp, evidence_refs=evidence_refs,
                )
                accepted[key] = merged_sel
                flat_patch.pop("qualitySellSelectionSource", None)
                flat_patch.pop("qualitySellSelectionSources", None)
                audit(key, "accept", "PER_COLOR_MERGE", cur_sel, merged_sel)
                continue

            if key in ("qualitySellSelectionSource", "qualitySellSelectionSources"):
                # Derived provenance is never accepted as a direct patch write.
                audit(key, "reject", "DERIVED_PROVENANCE_NOT_DIRECT_WRITABLE", old_value, new_value)
                continue

            # Unified provenance / authority:
            # MANUAL_CONFIRMED > VISION_CONFIRMED > VISION_OBSERVED > MISSING
            is_manual_confirmed = bool(
                (key in USER_CONFIRMED_FACT_KEYS or key in FIXED_FACT_KEYS)
                and state
                and state.status not in {"empty", "cleared"}
                and (
                    state.protected
                    or (state.status == "confirmed" and state.source == "manual")
                )
            )
            if is_manual_confirmed and resolved_intent in {"observe", "snapshot"}:
                if new_value != old_value:
                    state.candidate = new_value
                    self.field_states[key] = state
                    audit(key, "conflict", "MANUAL_CONFIRMED_PROTECTED", old_value, new_value)
                else:
                    audit(key, "reject", "MANUAL_CONFIRMED_SAME_VALUE", old_value, new_value)
                continue

            if (
                state
                and (state.protected or state.status == "confirmed")
                and resolved_intent == "observe"
                and (key in FIXED_FACT_KEYS or key in USER_CONFIRMED_FACT_KEYS)
                and new_value != old_value
            ):
                state.candidate = new_value
                self.field_states[key] = state
                audit(key, "conflict", "CONFIRMED_FACT_PROTECTED", old_value, new_value)
                continue

            if (
                resolved_intent == "confirm"
                and state
                and state.protected
                and new_value == old_value
                and not missing
            ):
                audit(key, "reject", "CONFIRM_SAME_ALREADY", old_value, new_value)
                continue

            protected = bool(resolved_intent == "confirm" or source == "manual")
            status = "confirmed" if protected else "observed"
            candidate = None if new_value == old_value else (state.candidate if state else None)
            self._write_field(
                next_facts, key, new_value, source=source, status=status,
                protected=protected, observed_at=stamp, evidence_refs=evidence_refs,
                candidate=candidate,
            )
            accepted[key] = new_value
            reason = "CONFIRM_PROTECT" if protected else "OBSERVE_ACCEPT"
            if protected and new_value == old_value:
                reason = "CONFIRM_SAME_VALUE"
            audit(key, "accept", reason, old_value, new_value)

        if "totalGrids" in accepted:
            next_facts["totalGrid"] = next_facts.get("totalGrids")
        elif "totalGrid" in accepted:
            next_facts["totalGrids"] = next_facts.get("totalGrid")
        if "purpleCount" in accepted:
            next_facts["purple"] = next_facts.get("purpleCount")
        elif "purple" in accepted:
            next_facts["purpleCount"] = next_facts.get("purple")
        if "isAcquired" in accepted:
            next_facts["didCurrentUserAcquire"] = next_facts.get("isAcquired")
        elif "didCurrentUserAcquire" in accepted:
            next_facts["isAcquired"] = next_facts.get("didCurrentUserAcquire")
        if "isAcquired" in accepted or "didCurrentUserAcquire" in accepted:
            if "qualitySellSelection" not in accepted and "qualitySellSelection" not in flat_patch:
                from quality_sell_selection import (
                    CANONICAL_QUALITIES,
                    aggregate_selection_source,
                    manual_override_colors,
                    normalize_quality_sell_selection_sources,
                    resolve_default_quality_sell_selection,
                    sources_from_aggregate,
                )
                raw_sources = next_facts.get("qualitySellSelectionSources")
                if isinstance(raw_sources, dict):
                    cur_sources = normalize_quality_sell_selection_sources(raw_sources)
                else:
                    cur_sources = sources_from_aggregate(next_facts.get("qualitySellSelectionSource"))
                acq_val = next_facts.get("isAcquired")
                default_sel = resolve_default_quality_sell_selection(acq_val)
                default_src = "default_self_acquired" if acq_val is True else "unknown"
                cur_sel = next_facts.get("qualitySellSelection")
                cur_sel = dict(cur_sel) if isinstance(cur_sel, dict) else {}
                # Per-color refresh: an acquisition refresh may (re)apply the
                # default ONLY to colors that carry no visual/manual provenance.
                refreshed_sel: Dict[str, Any] = {}
                refreshed_sources: Dict[str, str] = {}
                for q in CANONICAL_QUALITIES:
                    if cur_sources[q] in ("visual_observed", "manual_override"):
                        refreshed_sel[q] = cur_sel.get(q, default_sel[q])
                        refreshed_sources[q] = cur_sources[q]
                    else:
                        refreshed_sel[q] = default_sel[q]
                        refreshed_sources[q] = default_src
                if refreshed_sel != (cur_sel or None) or refreshed_sources != cur_sources:
                    self._write_field(
                        next_facts, "qualitySellSelection", refreshed_sel,
                        source=source or "auto",
                        status=("confirmed" if manual_override_colors(refreshed_sources) else "observed"),
                        protected=bool(manual_override_colors(refreshed_sources)),
                        observed_at=stamp, evidence_refs=evidence_refs,
                    )
                    self._write_field(
                        next_facts, "qualitySellSelectionSources", refreshed_sources,
                        source=source or "auto",
                        status=("confirmed" if manual_override_colors(refreshed_sources) else "observed"),
                        protected=False, observed_at=stamp, evidence_refs=evidence_refs,
                    )
                    self._write_field(
                        next_facts, "qualitySellSelectionSource",
                        aggregate_selection_source(refreshed_sources),
                        source=source or "auto",
                        status=("confirmed" if manual_override_colors(refreshed_sources) else "observed"),
                        protected=False, observed_at=stamp, evidence_refs=evidence_refs,
                    )
                    self._record_audit({
                        "commandId": cmd_id,
                        "field": "qualitySellSelection",
                        "decision": "accept",
                        "reason": "ACQUISITION_PER_COLOR_DEFAULT",
                        "oldValue": cur_sel or None,
                        "newValue": refreshed_sel,
                        "source": source or "auto",
                        "intent": resolved_intent,
                        "matchId": self.id,
                        "matchGeneration": self._seq,
                        "factsRevision": self.facts_revision,
                        "sceneGeneration": scene_generation,
                        "observedAt": stamp,
                    })
        self.facts = next_facts
        if source:
            self.source = source
        self.updated_at = stamp
        if isinstance(flat_patch.get("fieldStates"), dict) and resolved_intent == "snapshot":
            self.restore_field_states(flat_patch.get("fieldStates"))
        return self.snapshot()

    def update_quality_sell_selection_color(self, quality: str, new_state: str) -> Dict[str, Any]:
        """Update sell selection state for a single quality color with manual override.

        Only the touched color's provenance becomes manual_override; the other
        five colors keep their own provenance and remain updatable by vision.
        """
        from quality_sell_selection import apply_single_color_override
        curr = self.facts.get("qualitySellSelection")
        raw_sources = self.facts.get("qualitySellSelectionSources")
        if not isinstance(raw_sources, dict):
            from quality_sell_selection import sources_from_aggregate
            raw_sources = sources_from_aggregate(self.facts.get("qualitySellSelectionSource"))
        updated, sources = apply_single_color_override(curr, raw_sources, quality, new_state)
        return self.apply_facts(
            {
                "qualitySellSelection": updated,
                "qualitySellSelectionSources": sources,
            },
            source="manual",
            intent="confirm",
        )

    def has_any_fact(self) -> bool:
        facts = self.facts
        if any(facts.get(key) is not None for key in ("privateBidCap", "bidActionCount")):
            return True
        if facts.get("welfareReceived") is not None:
            return True
        if facts.get("sparkle") is not None:
            return True
        if facts.get("box") or facts.get("fieldCondition") or facts.get("venue") or facts.get("venueTier") or facts.get("character"):
            return True
        # A raw settlement capture is itself a useful DRAFT fact.  It must be
        # durable even when the user has not filled the settlement form yet.
        if facts.get("settlementEvidence") or facts.get("settlementTruthEvidence"):
            return True
        for key in INT_KEYS:
            if key in ("intelCost", "otherCost", "futureIncrementalCost") and facts.get(key) == 0:
                state = self.field_states.get(key)
                if state is None or state.status in ("empty", "cleared"):
                    continue
            if facts.get(key) is not None:
                return True
        return any(facts.get(key) for key in KNOWN_KEYS)

    def snapshot(self) -> Dict[str, Any]:
        field_states = {}
        for key, state in self.field_states.items():
            payload = asdict(state)
            payload["observedAt"] = state.observed_at
            payload["evidenceRefs"] = state.evidence_refs
            payload["matchGeneration"] = state.match_generation
            field_states[key] = payload
        return {
            "id": self.id,
            "lifecycleStatus": self.lifecycle_status,
            "source": self.source,
            "dataOrigin": getattr(self, "data_origin", "live") or "live",
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "schemaVersion": 7,
            "factsRevision": self.facts_revision,
            "fieldStates": field_states,
            **dict(self.facts),
            "sparkle": deepcopy(self.facts.get("sparkle")),
        }

    def to_canonical(self) -> Dict[str, Any]:
        """Canonical v7 facts only. No Solver input, no guessed defaults."""
        snap = self.snapshot()
        known_gold = snap.get("knownGold") or ""
        known_purple = snap.get("knownPurple") or ""
        known_red = snap.get("knownRed") or ""
        known_white = snap.get("knownWhite") or ""
        known_green = snap.get("knownGreen") or ""
        known_blue = snap.get("knownBlue") or ""
        field = snap.get("fieldCondition")
        from session_costs import costs_from_facts

        def _to_items(raw):
            if isinstance(raw, list):
                return raw
            if isinstance(raw, str) and raw.strip():
                parts = [p.strip() for p in raw.split("+") if p.strip()]
                return [{"name": p} for p in parts]
            return []

        clearing = snap.get("clearingPrice")
        actual = snap.get("actualTotal")
        profit = snap.get("realizedProfit")
        raw_acquired = snap.get("isAcquired") if snap.get("isAcquired") is not None else snap.get("didCurrentUserAcquire")
        if raw_acquired is None and snap.get("acquired") is not None:
            raw_acquired = snap.get("acquired")
        if raw_acquired is None and isinstance(snap.get("settlement"), dict):
            raw_acquired = snap.get("settlement", {}).get("acquired")
        acquired = bool(raw_acquired) if raw_acquired is not None else None
        raw_winner = snap.get("winner")
        winner_candidate = str(raw_winner).strip() if raw_winner is not None and str(raw_winner).strip() else None
        winner = winner_candidate if (winner_candidate and winner_candidate not in FORBIDDEN_WINNER_PLACEHOLDERS) else None
        raw_leader = snap.get("leaderName")
        leader_candidate = str(raw_leader).strip() if raw_leader is not None and str(raw_leader).strip() else None
        leader_name = winner or (leader_candidate if (leader_candidate and leader_candidate not in FORBIDDEN_WINNER_PLACEHOLDERS) else None)
        truth_ev = snap.get("settlementTruthEvidence") or snap.get("settlementEvidence")
        settlement_items = snap.get("settlementItems") or []

        winner_name = snap.get("settlementWinnerName") or winner
        assistant_name = snap.get("settlementAuctionAssistantName") or snap.get("auctionAssistant")
        is_self_winner = snap.get("isSelfWinner")
        if is_self_winner is None and acquired is not None:
            is_self_winner = acquired

        settlement_dict: Dict[str, Any] = {
            "welfare": {"received": snap.get("welfareReceived")},
            "status": "verified" if (clearing is not None and actual is not None) else "pending",
            "verified": bool(clearing is not None and actual is not None),
            "clearingPrice": clearing,
            "actualTotal": actual,
            "realizedProfit": profit,
            "acquired": acquired,
            "winner": winner,
            "settlementWinnerName": winner_name,
            "settlementAuctionAssistantName": assistant_name,
            "auctionAssistant": assistant_name,
            "isSelfWinner": is_self_winner,
            "settlementItems": list(settlement_items),
        }
        if truth_ev and isinstance(truth_ev, dict):
            settlement_dict["truthEvidence"] = truth_ev
        capture_links = snap.get("settlementEvidence")
        if capture_links and isinstance(capture_links, dict):
            # Raw capture linkage is provenance metadata, not settlement truth;
            # it never changes DRAFT/FINALIZED or any business fact.
            settlement_dict["evidenceAttachments"] = dict(capture_links)
        occ = snap.get("warehouseOccupancy")
        if occ and isinstance(occ, dict):
            settlement_dict["warehouseOccupancy"] = dict(occ)
        # Boundary 2: bottom quality sell selection + per-color provenance.
        q_sel = snap.get("qualitySellSelection")
        if q_sel is not None:
            from quality_sell_selection import (
                aggregate_selection_source,
                normalize_quality_sell_selection,
                normalize_quality_sell_selection_sources,
                sources_from_aggregate,
            )
            norm_sel = normalize_quality_sell_selection(q_sel)
            if norm_sel is not None:
                raw_sources = snap.get("qualitySellSelectionSources")
                if isinstance(raw_sources, dict):
                    norm_sources = normalize_quality_sell_selection_sources(raw_sources)
                else:
                    norm_sources = sources_from_aggregate(snap.get("qualitySellSelectionSource"))
                settlement_dict["qualitySellSelection"] = norm_sel
                settlement_dict["qualitySellSelectionSources"] = norm_sources
                settlement_dict["qualitySellSelectionSource"] = aggregate_selection_source(norm_sources)

        canonical_record = {
            "sparkle": deepcopy(snap.get("sparkle")),
            "schemaVersion": 7,
            "productVersion": "v0.67-alpha",
            "id": snap["id"],
            "lifecycleStatus": self.lifecycle_status,
            "source": self.source,
            "dataOrigin": getattr(self, "data_origin", "live") or "live",
            "fillDefaults": False,
            "playedAt": snap.get("updatedAt") or snap.get("createdAt") or "",
            "environment": {
                "venueId": snap.get("venueId"),
                "venueTier": snap.get("venueTier"),
                "venue": snap.get("venue"),
                "venueName": None,
                "boxId": snap.get("boxId"),
                "box": snap.get("box"),
                "boxType": snap.get("boxType"),
                "fieldCondition": field,
                "fieldConditionName": snap.get("fieldConditionName"),
                "fieldConditionSource": "user_override" if field else None,
                "catalogVersion": snap.get("catalogVersion"),
                "catalogApprovalStatus": snap.get("catalogApprovalStatus"),
                "catalogSha256": snap.get("catalogSha256"),
                "gameEvidenceCohort": snap.get("gameEvidenceCohort"),
                "venueEvidenceClass": snap.get("venueEvidenceClass"),
                "boxEvidenceClass": snap.get("boxEvidenceClass"),
            },
            "loadout": {
                "character": snap.get("character"),
                "lobbyToolGroup": None,
                "solverToolGroup": None,
            },
            "costs": costs_from_facts(snap),
            "publicIntel": {
                "q": snap.get("q"),
                "totalItems": snap.get("totalItems"),
                "totalGrid": snap.get("totalGrid") if snap.get("totalGrid") is not None else snap.get("totalGrids"),
                "avgValueBasis": snap.get("avgValueBasis") or "all_inclusive",
            },
            "qualities": {
                "white": {
                    "count": snap.get("whiteCount"),
                    "avg": snap.get("whiteAvg"),
                    "grid": snap.get("whiteGrid"),
                    "knownItems": _to_items(known_white),
                },
                "green": {
                    "count": snap.get("greenCount"),
                    "avg": snap.get("greenAvg"),
                    "grid": snap.get("greenGrid"),
                    "knownItems": _to_items(known_green),
                },
                "blue": {
                    "count": snap.get("blueCount"),
                    "avg": snap.get("blueAvg"),
                    "grid": snap.get("blueGrid"),
                    "knownItems": _to_items(known_blue),
                },
                "purple": {
                    "count": snap.get("purpleCount") or snap.get("purple"),
                    "minCount": snap.get("purpleMinCount"),
                    "avg": snap.get("purpleAvg"),
                    "grid": snap.get("purpleGrid"),
                    "knownItems": _to_items(known_purple),
                },
                "gold": {
                    "count": snap.get("goldCount"),
                    "minCount": snap.get("goldMinCount"),
                    "avg": snap.get("goldAvg"),
                    "total": snap.get("goldTotal"),
                    "grid": snap.get("goldGrid"),
                    "knownItems": _to_items(known_gold),
                },
                "red": {
                    "count": snap.get("redCount"),
                    "minCount": snap.get("redMinCount"),
                    "maxCount": snap.get("redMaxCount"),
                    "grid": snap.get("redGrid"),
                    "knownItems": _to_items(known_red),
                    "redInventoryComplete": snap.get("redInventoryComplete"),
                    "settlementVerifiedRedItems": snap.get("settlementVerifiedRedItems") or "",
                },
            },
            "bidding": {
                "privateBidCap": snap.get("privateBidCap"),
                "bidActionCount": snap.get("bidActionCount"),
                "seats": list(snap.get("seats") or []),
                "myName": snap.get("myName") or "玩家本人",
                "myFinalBid": snap.get("myBid") if snap.get("myBid") is not None else (clearing if acquired is True else None),
                "leaderName": leader_name or snap.get("leaderName"),
                "leaderBid": snap.get("leaderBid") or clearing,
                "leaderTies": list(snap.get("leaderTies") or []),
                "isMyLead": bool(snap.get("isMyLead") if snap.get("isMyLead") is not None else acquired),
                "historicalBids": dict(snap.get("historicalBids") or {}),
                "finalBids": dict(snap.get("finalBids") or {}),
                "rounds": [],
            },
            "settlement": settlement_dict,
            "knownGold": known_gold,
            "knownPurple": known_purple,
            "knownRed": known_red,
            "leaderBid": snap.get("leaderBid"),
            "targetProfit": snap.get("targetProfit"),
            "q": snap.get("q"),
            "goldAvg": snap.get("goldAvg"),
            "purpleCount": snap.get("purpleCount"),
            "purple": snap.get("purpleCount"),
            "box": snap.get("box"),
            "fieldCondition": field,
            "catalogVersion": snap.get("catalogVersion"),
        }
        wh = snap.get("warehouse")
        if isinstance(wh, dict) and "slots" in wh:
            canonical_record["warehouse"] = {
                "slots": [
                    {
                        "col": int(s["col"]),
                        "row": int(s["row"]),
                        "w": int(s["w"]),
                        "h": int(s["h"]),
                        "rarity": str(s.get("rarity") or "unknown"),
                        "evidenceLevel": str(s.get("evidenceLevel") or "OUTLINE_ONLY"),
                        "identityStatus": "EXACT" if (s.get("identityStatus") == "EXACT" or (s.get("identifiedName") and s.get("identityStatus") != "CANDIDATE")) and s.get("identifiedName") and s.get("rarity") != "unknown" and s.get("evidenceLevel") != "OUTLINE_ONLY" else str(s.get("identityStatus") or ("CANDIDATE" if s.get("candidates") else "UNKNOWN")),
                        "candidates": [
                            {
                                "catalogId": str(c.get("catalogId") or c.get("Id") or ""),
                                "name": str(c.get("name") or c.get("Name") or ""),
                            }
                            for c in (s.get("candidates") or [])
                            if isinstance(c, dict)
                        ],
                        **({"manualDecision": deepcopy(s["manualDecision"])} if isinstance(s.get("manualDecision"), dict) else {}),
                        "identifiedName": str(s["identifiedName"]) if (s.get("identityStatus") == "EXACT" or (s.get("identifiedName") and s.get("identityStatus") != "CANDIDATE")) and s.get("identifiedName") and s.get("rarity") != "unknown" and s.get("evidenceLevel") != "OUTLINE_ONLY" else None,
                        **({"trackId": int(s["trackId"])} if s.get("trackId") is not None else {}),
                    }
                    for s in wh.get("slots") or []
                    if isinstance(s, dict) and s.get("col") is not None and s.get("row") is not None and s.get("w") is not None and s.get("h") is not None
                ]
            }
        if isinstance(snap.get('auctionEvidence'), dict):
            import copy
            canonical_record['auctionEvidence'] = copy.deepcopy(snap['auctionEvidence'])
        from intel_evidence_record import intel_evidence_record
        evidence = intel_evidence_record(snap)
        if evidence is not None:
            canonical_record['intelCardEvidence'] = evidence
        return canonical_record

    def finalize(
        self,
        played_at: Optional[str] = None,
        store_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically finalize and persist this match to CanonicalHistoryStore exactly once."""
        from canonical_history_store import CanonicalHistoryStore
        from canonical_match_record import build_canonical_match_record_v7, FORBIDDEN_ROOT_LEGACY_FIELDS
        from runtime_data import resolve_runtime_history_path

        self.lifecycle_status = "FINALIZED"
        self.facts["settlementFinalized"] = True
        self.facts["settlementReady"] = False

        canonical = self.to_canonical()
        # FINALIZED records must not carry legacy flat root fields that the
        # v7 FINALIZED profile explicitly forbids.  These live in their
        # namespaced siblings (environment / publicIntel / qualities / bidding).
        canonical = {
            k: v
            for k, v in canonical.items()
            if k not in FORBIDDEN_ROOT_LEGACY_FIELDS
        }
        db_path = store_path or str(resolve_runtime_history_path())
        store = CanonicalHistoryStore(db_path)
        written = store.persist_record_transactional(canonical, is_finalized=True)
        return written


CURRENT_MATCH = CurrentMatch()
