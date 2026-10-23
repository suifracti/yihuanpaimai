"""Current game UI readback consumed by the existing vision/match pipeline.

The file is a transient observation channel, never a history store. Missing or
interrupted readback leaves the normal image readers in charge.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from pathlib import Path


def snapshot_path():
    return Path(os.environ.get("NTE_UE4SS_SNAPSHOT") or
                Path(__file__).resolve().parents[1] / "build/ue4ss/auction.json")


def read_snapshot(path=None):
    try:
        data = json.loads(Path(path or snapshot_path()).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        # The producer writes a heartbeat even when displayed values don't change.
        # This is source availability, unrelated to image qualification/coverage.
        if data.get("source") != "ue4ss_ui" or not 0 <= time.time() - data["sampledAt"] < 10:
            return None
        if data.get("scene") not in ("IN_AUCTION", "SETTLEMENT") or not data.get("instance"):
            return None
        return data
    except (OSError, ValueError, TypeError, KeyError):
        return None


def text_facts(data):
    from business_sot import extract_from_text
    from intel_card_evidence import route_card_text

    labels = [re.sub(r"<[^>]*>", "", row.get("text", "")) for row in data.get("texts", [])]
    facts = {k: v for k, v in extract_from_text(" ".join(labels)).items() if v is not None}
    for card in data.get("cards", []):
        raw = re.sub(r"<[^>]*>", "", " ".join((card.get("title") or "", card.get("content") or "")))
        for key, value, _confidence in route_card_text(raw):
            # Existing OCR parser handles full amounts. A shortened UI token is
            # useful evidence but cannot become an exact average by truncation.
            if key.endswith("Avg") and re.search(r"\d\s*[kKmMbB万亿]", raw):
                continue
            facts[key] = value
    if data.get("scene") == "IN_AUCTION" and type(data.get("curRoundIndex")) is int and data["curRoundIndex"] >= 0:
        facts["round"] = data["curRoundIndex"] + 1
    if "goldAvg" in facts:
        facts["avg"] = facts["goldAvg"]
    if "purpleCount" in facts:
        facts["purple"] = facts["purpleCount"]
    return facts


def displayed_amount(text):
    token = re.sub(r"\s+", "", str(text or "")).replace("，", ",")
    if re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)", token):
        return int(token.replace(",", ""))
    return None


def apply_snapshot(context, data):
    """Overlay only values actually obtained; keep all other recognition facts."""
    patch = text_facts(data)
    if data["scene"] == "IN_AUCTION":
        from venue_box_catalog import load_catalog, normalize_vision_venue, normalize_venue_from_box
        catalog = load_catalog()
        if patch.get("venue"):
            normalized = normalize_vision_venue(catalog, patch["venue"])
            if normalized.get("venueId"):
                patch["venueId"] = normalized["venueId"]
        boxes = [normalize_venue_from_box(catalog, row.get("text")) for row in data.get("texts", [])]
        boxes = {row["boxId"]: row for row in boxes if row.get("status") == "NORMALIZED"}
        if len(boxes) == 1:
            box = next(iter(boxes.values()))
            if patch.get("venueId") in (None, box["venueId"]):
                patch.update(boxId=box["boxId"], venueId=box["venueId"])
    context.update(patch)
    if data["scene"] == "IN_AUCTION":
        seats = {s.get("slot"): copy.deepcopy(s) for s in context.get("seats", []) if isinstance(s, dict)}
        for row in data.get("seats", []):
            slot = row.get("slot")
            if type(slot) is not int or not 1 <= slot <= 4:
                continue
            seat = seats.setdefault(slot, {"slot": slot})
            if row.get("name"):
                seat["name"] = row["name"]
            amount = displayed_amount(row.get("bidText"))
            if amount is not None and amount >= 0:
                seat.update(currentBid=amount, bid=amount, observationStatus="VISIBLE")
            if type(row.get("isMe")) is bool:
                seat["isMe"] = row["isMe"]
        if seats:
            context["seats"] = [seats[k] for k in sorted(seats)]
    elif data["scene"] == "SETTLEMENT":
        bill = data.get("bill") or {}
        settlement = context.setdefault("settlementData", {})
        for field, target in (("bidText", "clearingPrice"), ("valueText", "actualTotal"), ("incomeText", "profit")):
            amount = displayed_amount(bill.get(field))
            if amount is not None:
                settlement[target] = amount
                context[{"profit": "realizedProfit"}.get(target, target)] = amount
        if bill.get("winner"):
            settlement["winner"] = context["winner"] = bill["winner"]
        # No direct warehouse -> COMPLETE conversion, final-animation guess, or
        # acquired-player inference. Existing image capture/truth stays intact.
    owner = context.get("recordStableKey") or context.get("matchId") or context.get("id")
    evidence = context.get("auctionEvidence")
    if not isinstance(evidence, dict) or evidence.get("ownerMatchId") not in (None, owner):
        evidence = {}
    evidence = copy.deepcopy(evidence)
    evidence.update(version=1, ownerMatchId=owner)
    raw = copy.deepcopy(data)
    raw.pop("sampledAt", None)
    raw.pop("readUtc", None)
    # Timer/cash glyph changes must not duplicate the entire readback every
    # second. Keep actual environment labels; cards, bids and bill are separate.
    from business_sot import extract_from_text
    raw["texts"] = [row for row in raw.get("texts", []) if any(extract_from_text(row.get("text")).values())]
    history = evidence.setdefault("ue4ss", [])
    if not history or history[-1].get("data") != raw:
        history.append({"capturedAt": data.get("readUtc"), "data": raw})
    context["auctionEvidence"] = evidence
    readings = context.setdefault("intelCardReadings", [])
    for card in data.get("cards", []):
        raw_text = " ".join((card.get("title") or "", card.get("content") or "")).strip()
        if raw_text and not any(r.get("source") == "ue4ss_ui" and r.get("rawText") == raw_text for r in readings):
            readings.append({"source": "ue4ss_ui", "is_physical_ocr": False,
                             "rawText": raw_text, "round": patch.get("round"),
                             "frameId": "ue4ss:" + str(data.get("session")) + ":" + str(card.get("instance"))
                             + ":" + hashlib.sha256(raw_text.encode()).hexdigest()[:16], "cardBox": [],
                             "instance": card.get("instance"), "infoID": card.get("infoID")})
    return context
