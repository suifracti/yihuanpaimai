# -*- coding: utf-8 -*-
"""Project live four-seat bids and intel observations for UI and history.

Main/HUD only display this projection. Missing names stay unnamed slots;
zero is a visible bid, not “未识别”.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


VALUATION_INTEL_FIELDS = frozenset({
    "q", "goldAvg", "purpleAvg", "purpleCount", "goldCount", "totalItems", "totalGrid",
})


def bids_hidden_now(facts):
    """Live display policy only; settlement prices and raw evidence stay intact."""
    condition = facts.get("fieldCondition")
    if isinstance(condition, dict):
        condition = condition.get("id") or condition.get("name")
    settled = (facts.get("isSettlement") is True or facts.get("scene") == "SETTLEMENT"
               or facts.get("settlementFinalized") is True or facts.get("lifecycleStatus") == "FINALIZED")
    return condition in ("dark", "天黑了") and not settled


def empty_seats() -> List[Dict[str, Any]]:
    return [
        {
            "slot": i,
            "seat": i,
            "name": None,
            "isMe": False,
            "bid": None,
            "currentBid": None,
            "observationStatus": "UNOBSERVED",
        }
        for i in range(1, 5)
    ]


def _shown_bid(raw: Dict[str, Any]) -> Optional[int]:
    if "currentBid" in raw and raw.get("currentBid") is not None:
        try:
            return int(raw["currentBid"])
        except (TypeError, ValueError):
            return None
    if raw.get("observationStatus") == "UNOBSERVED":
        return None
    bid = raw.get("bid")
    if bid is None:
        return None
    try:
        return int(bid)
    except (TypeError, ValueError):
        return None


def _slot_of(raw: Dict[str, Any], fallback: int) -> int:
    for key in ("slot", "seat"):
        try:
            slot = int(raw.get(key))
        except (TypeError, ValueError):
            continue
        if 1 <= slot <= 4:
            return slot
    return fallback


def project_four_seats(
    seats: Optional[List[Any]] = None,
    *,
    evidence: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Always return four seats. Unknown names stay None; 0 remains 0."""
    source = seats if isinstance(seats, list) and seats else None
    evidence_last_seats = None
    if isinstance(evidence, dict):
        rows = evidence.get("bids") or []
        if rows:
            final_round = rows[-1].get("round") if isinstance(rows[-1], dict) else None
            by_slot_ev = {}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                if final_round is not None and r.get("round") != final_round:
                    continue
                for idx, s in enumerate(r.get("seats") or []):
                    if not isinstance(s, dict):
                        continue
                    slot = _slot_of(s, idx + 1)
                    if s.get("observationStatus") == "VISIBLE" or s.get("currentBid") is not None:
                        by_slot_ev[slot] = s
            last_seats = rows[-1].get("seats") if isinstance(rows[-1], dict) else None
            if isinstance(last_seats, list):
                evidence_last_seats = []
                for idx, s in enumerate(last_seats):
                    ms = dict(s)
                    slot = _slot_of(ms, idx + 1)
                    if slot in by_slot_ev and (ms.get("observationStatus") != "VISIBLE" and ms.get("currentBid") is None):
                        ms.update({
                            "currentBid": by_slot_ev[slot].get("currentBid"),
                            "bid": by_slot_ev[slot].get("bid"),
                            "observationStatus": by_slot_ev[slot].get("observationStatus", "VISIBLE"),
                        })
                    evidence_last_seats.append(ms)
            else:
                evidence_last_seats = list(by_slot_ev.values())
    if source is None:
        source = evidence_last_seats
    by_slot: Dict[int, Dict[str, Any]] = {}
    if isinstance(source, list):
        for index, raw in enumerate(source[:4]):
            if not isinstance(raw, dict):
                continue
            slot = _slot_of(raw, index + 1)
            by_slot[slot] = raw
    ev_by_slot: Dict[int, Dict[str, Any]] = {}
    if isinstance(evidence_last_seats, list):
        for index, raw in enumerate(evidence_last_seats[:4]):
            if not isinstance(raw, dict):
                continue
            slot = _slot_of(raw, index + 1)
            ev_by_slot[slot] = raw
    out = empty_seats()
    for seat in out:
        slot = seat["slot"]
        raw = by_slot.get(slot) or {}
        ev_raw = ev_by_slot.get(slot) or {}
        name = raw.get("name") or ev_raw.get("name")
        name = str(name).strip() if name not in (None, "") else None
        shown = _shown_bid(raw)
        status = raw.get("observationStatus")
        if shown is None and ev_raw:
            ev_shown = _shown_bid(ev_raw)
            if ev_shown is not None:
                shown = ev_shown
                status = ev_raw.get("observationStatus", "VISIBLE")
        if not status:
            status = "VISIBLE" if shown is not None else "UNOBSERVED"
        seat.update({
            "name": name,
            "isMe": bool(raw.get("isMe") or ev_raw.get("isMe")),
            "bid": shown,
            "currentBid": shown,
            "observationStatus": status,
        })
    return out


def _intel_line_text(line: Any) -> str:
    if isinstance(line, dict):
        return str(line.get("text") or "").strip()
    return str(line or "").strip()


def project_intel(
    evidence: Optional[Dict[str, Any]] = None,
    intel_facts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full visible intel: raw board lines plus structured card fields."""
    blob = evidence if isinstance(evidence, dict) else {}
    observations: List[Dict[str, Any]] = []
    for row in blob.get("intel") or []:
        if not isinstance(row, dict):
            continue
        lines = row.get("lines") or []
        texts = [text for text in (_intel_line_text(line) for line in lines) if text]
        if not texts:
            continue
        observations.append({
            "round": row.get("round"),
            "capturedAt": row.get("capturedAt"),
            "text": "；".join(texts),
            "lines": lines,
            "participation": "recorded",
        })
    structured: List[Dict[str, Any]] = []
    if isinstance(intel_facts, dict):
        for field, entry in intel_facts.items():
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status") or "UNKNOWN")
            if status == "UNKNOWN" and entry.get("value") is None and not entry.get("tentative"):
                continue
            if status == "OBSERVED":
                participation = "valuation" if field in VALUATION_INTEL_FIELDS else "recorded"
            elif status == "CONFLICT":
                participation = "pending"
            else:
                participation = "pending"
            structured.append({
                "field": field,
                "value": entry.get("value"),
                "status": status,
                "tentative": entry.get("tentative"),
                "participation": participation,
            })
    return {
        "observations": observations,
        "structured": structured,
        "observationCount": len(observations),
    }


def project_bidding_summary(
    facts: Optional[Dict[str, Any]] = None,
    ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    facts = facts if isinstance(facts, dict) else {}
    ctx = ctx if isinstance(ctx, dict) else {}
    evidence = facts.get("auctionEvidence") or ctx.get("auctionEvidence")
    seats = project_four_seats(
        ctx.get("seats") or facts.get("seats"),
        evidence=evidence if isinstance(evidence, dict) else None,
    )
    round_no = ctx.get("round") or facts.get("roundNo") or 1
    leader = ctx.get("leaderName") or facts.get("leaderName")
    return {
        "seats": seats,
        "hiddenBids": bids_hidden_now({**facts, **ctx}),
        "roundNo": round_no,
        "leader": leader,
        "leaderBid": ctx.get("currentLeaderBid") if ctx.get("currentLeaderBid") is not None else facts.get("leaderBid"),
        "leaderTies": list(ctx.get("leaderTies") or facts.get("leaderTies") or []),
        "myName": ctx.get("myName") or facts.get("myName"),
        "isMyLead": bool(ctx.get("isMyLead") if "isMyLead" in ctx else facts.get("isMyLead")),
        "historicalBids": dict(ctx.get("historicalBids") or facts.get("historicalBids") or {}),
        "finalBids": ctx.get("finalBids") if ctx.get("finalBids") is not None else (facts.get("finalBids") or {}),
    }
