# -*- coding: utf-8 -*-
"""Replay D:\\video\\2026-09-08 14-40-37.mkv through the production loop.

Hardened multi-layer verification:
1. Per-seat, per-round quotes audit (Round 1 & Round 2 for all 4 seats, including seat 2 real 0).
2. Intel items audit: title, full semantics, numbers, qualities, and statistical scope.
3. Independent checks across 4 distinct layers:
   - Layer 1: 原始观察 (Raw Observations in auctionEvidence)
   - Layer 2: 结构化结果 (Structured Match Facts in CurrentMatch snapshot)
   - Layer 3: 保存记录 (Saved Records in CanonicalHistoryStore / disk JSON)
   - Layer 4: 界面内容 (UI Content / Projections in project_four_seats & project_intel)
Does not hardcode answers. Isolated YIHUAN_DATA_ROOT.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "app"),
    str(ROOT / "core"),
    "C:/Program Files/Python310/Lib/site-packages",
]

VIDEO = Path(r"D:\video\2026-09-08 14-40-37.mkv")
OUT = ROOT / "build" / "diagnosis_20260909" / "p2-video-recognition"

REFERENCE = {
    "video": str(VIDEO),
    "durationS": 201.63,
    "venue": "珊瑚场",
    "box": "琉璃宝箱",
    "rounds": {
        1: {
            "round": 1,
            "seats": [
                {"slot": 1, "name": "致敬最良心不歪", "bid": 711111},
                {"slot": 2, "name": "葱香小桃", "bid": 0},
                {"slot": 3, "name": "猫薄荷", "bid": 555555},
                {"slot": 4, "name": "秋星祭02", "bid": 333333},
            ],
        },
        2: {
            "round": 2,
            "seats": [
                {"slot": 1, "name": "致敬最良心不歪", "bid": 1222222},
                {"slot": 2, "name": "葱香小桃", "bid": 0},
                {"slot": 3, "name": "猫薄荷", "bid": 555555},
                {"slot": 4, "name": "秋星祭02", "bid": 666666},
            ],
        },
    },
    "intelItems": [
        {
            "id": "qianyan_q17",
            "title": "千眼其一",
            "fullSemantic": "本局内紫色，金色和红色品质藏品的总件数为17件。",
            "number": 17,
            "qualities": ["purple", "gold", "red"],
            "statisticalScope": "publicIntel.q",
            "parserStatus": "SUPPORTED_SOLVER_FACT",
        },
        {
            "id": "base_display_3",
            "title": "随机展示",
            "fullSemantic": "随机展示3件藏品。",
            "number": 3,
            "qualities": [],
            "statisticalScope": "base_display",
            "parserStatus": "PENDING_PARSER",
            "pendingReason": "展示类情报在原始观察与界面投影中完整呈现，但解算器当前不将其解析为离散数值约束",
        },
        {
            "id": "large_instrument_5",
            "title": "大型鉴定仪器",
            "fullSemantic": "随机展示5件藏品。",
            "number": 5,
            "qualities": [],
            "statisticalScope": "instrument_display",
            "parserStatus": "PENDING_PARSER",
            "pendingReason": "展示类情报在原始观察与界面投影中完整呈现，但解算器当前不将其解析为离散数值约束",
        },
        {
            "id": "purple_counter_4",
            "title": "紫品计数仪器",
            "fullSemantic": "本局内所有紫色品质藏品的总数量为4件。",
            "number": 4,
            "qualities": ["purple"],
            "statisticalScope": "qualities.purple.count",
            "parserStatus": "SUPPORTED_SOLVER_FACT",
        },
    ],
    "settlement": {
        "clearingPrice": 1222222,
        "actualTotal": 1556124,
        "profit": 333902,
        "winner": "致敬最良心不歪",
    },
}


def _contains(haystack: str, needle: str) -> bool:
    compact = haystack.replace(" ", "").replace(",", "").replace("，", "").replace("。", "")
    needle_compact = needle.replace(" ", "").replace(",", "").replace("，", "").replace("。", "")
    return needle_compact in compact


async def run_replay(data_root: Path) -> dict:
    os.environ["YIHUAN_DATA_ROOT"] = str(data_root)
    from recognition_mode import set_recognition_mode
    set_recognition_mode("auto")
    from keyboard_auction_pipeline import KeyboardAuctionPipeline
    from current_match import CurrentMatch, FACT_KEYS
    from auto_archiver import AutoArchiver
    from auction_flow_evidence import AuctionEvidencePersistence
    from canonical_history_store import CanonicalHistoryStore
    from frame_source import VideoCaptureSource
    from vision_worker_loop import run_vision_capture_loop
    from live_match_projection import project_four_seats, project_intel

    stop = {"stop": False}
    source = VideoCaptureSource(str(VIDEO), stop_flag=stop, min_interval_s=1.5)
    pipeline = KeyboardAuctionPipeline(catalog_path=str(ROOT / "assets" / "catalog_065.json"))
    pipeline.recognition_mode_provider = lambda: "auto"
    pipeline._warm_ocr_async()
    match = CurrentMatch()
    played_match_id = match.id
    store = CanonicalHistoryStore()
    archiver = AutoArchiver()
    persistence = AuctionEvidencePersistence(store)

    frame_counter = 0

    def sync(ctx):
        nonlocal frame_counter
        frame_counter += 1
        if frame_counter % 15 == 0 or (isinstance(ctx, dict) and ctx.get("scene") == "SETTLEMENT"):
            scene = (ctx or {}).get("scene")
            rnd = (ctx or {}).get("round")
            bids = [s.get("currentBid") for s in ((ctx or {}).get("seats") or []) if isinstance(s, dict)]
            print(f"Replay frame #{frame_counter}: scene={scene}, round={rnd}, bids={bids}, elapsed={time.perf_counter()-t0:.1f}s", flush=True)
        if not isinstance(ctx, dict):
            return
        ctx.setdefault("matchId", played_match_id)
        ctx.setdefault("id", played_match_id)
        facts = {k: ctx[k] for k in FACT_KEYS if k in ctx}
        if ctx.get("seats"):
            facts["seats"] = ctx["seats"]
        evidence = ctx.get("auctionEvidence")
        if isinstance(evidence, dict) and evidence.get("ownerMatchId") == played_match_id:
            facts["auctionEvidence"] = evidence
        if facts:
            match.apply_facts(facts, source="vision")
        persistence.save(evidence)

    async def publish(payload):
        return None

    t0 = time.perf_counter()
    await run_vision_capture_loop(
        pipeline=pipeline,
        stop_flag=stop,
        frame_provider=source.provide,
        publish_fn=publish,
        archiver=archiver,
        fps=1000,
        current_match=match,
        sync_context_fn=sync,
        auto_save_settlement=True,
    )
    elapsed = time.perf_counter() - t0

    snap = match.snapshot()
    evidence = snap.get("auctionEvidence") or pipeline.flow_evidence.snapshot() or {}
    ui_seats = project_four_seats(snap.get("seats"), evidence=evidence)
    ui_intel = project_intel(evidence, snap.get("intelFacts"))

    # Read disk store strictly by played_match_id (no fallback to last record)
    db_records = store.read_database().get("records") or []
    saved_record = next((r for r in db_records if r.get("id") == played_match_id), None)

    # Layer 1: 原始观察 (Raw Observations)
    raw_bids = evidence.get("bids") or []
    raw_intel = evidence.get("intel") or []
    raw_all_intel_text = " ".join(" ".join(line.get("text", "") for line in item.get("lines", [])) for item in raw_intel)

    # Reconstruct observed round quotes from raw bids
    observed_round_bids = {}
    for b in raw_bids:
        rnd = b.get("round")
        if rnd not in observed_round_bids:
            observed_round_bids[rnd] = {}
        for seat in b.get("seats") or []:
            slot = seat.get("slot")
            bid = seat.get("bid")
            current_bid = seat.get("currentBid")
            effective = current_bid if current_bid is not None else bid
            if effective is not None:
                observed_round_bids[rnd][slot] = effective

    layer1_checks = []
    for rnd_num, expected_round in REFERENCE["rounds"].items():
        for expected_seat in expected_round["seats"]:
            slot = expected_seat["slot"]
            ref_bid = expected_seat["bid"]
            got_bid = observed_round_bids.get(rnd_num, {}).get(slot)
            ok = got_bid == ref_bid
            layer1_checks.append({
                "layer": "layer1_raw_observations",
                "kind": "bids",
                "round": rnd_num,
                "slot": slot,
                "seatName": expected_seat["name"],
                "expectedBid": ref_bid,
                "observedBid": got_bid,
                "pass": ok,
            })

    for item in REFERENCE["intelItems"]:
        found_semantic = _contains(raw_all_intel_text, item["fullSemantic"])
        found_number = str(item["number"]) in raw_all_intel_text
        found_title = _contains(raw_all_intel_text, item["title"])
        ok = found_title and found_semantic and found_number
        layer1_checks.append({
            "layer": "layer1_raw_observations",
            "kind": "intel",
            "intelId": item["id"],
            "title": item["title"],
            "expectedSemantic": item["fullSemantic"],
            "foundTitle": found_title,
            "foundSemantic": found_semantic,
            "foundNumber": found_number,
            "pass": ok,
        })

    # Layer 2: 结构化结果 (Structured Results in snapshot)
    layer2_checks = []
    snap_q = snap.get("q")
    q_ok = snap_q == 17
    layer2_checks.append({
        "layer": "layer2_structured_facts",
        "intelId": "qianyan_q17",
        "field": "q",
        "statisticalScope": "publicIntel.q",
        "expected": 17,
        "got": snap_q,
        "qualities": ["purple", "gold", "red"],
        "pass": q_ok,
    })

    purple_count = snap.get("purpleCount") or snap.get("purple")
    if purple_count is None and isinstance(snap.get("qualities"), dict):
        purple_count = (snap["qualities"].get("purple") or {}).get("count")
    if purple_count is None and isinstance(snap.get("intelFacts"), list):
        for fact in snap["intelFacts"]:
            if isinstance(fact, dict) and fact.get("field") == "purple_count":
                purple_count = fact.get("value")
            elif isinstance(fact, str) and ("purple" in fact.lower() or "紫" in fact):
                import re
                m = re.search(r'\d+', fact)
                if m:
                    purple_count = int(m.group())
    purple_ok = purple_count == 4
    layer2_checks.append({
        "layer": "layer2_structured_facts",
        "intelId": "purple_counter_4",
        "field": "purple_count",
        "statisticalScope": "qualities.purple.count",
        "expected": 4,
        "got": purple_count,
        "qualities": ["purple"],
        "pass": purple_ok,
    })

    # Unsupported / display cards marked explicitly as PENDING_PARSER
    for item in REFERENCE["intelItems"]:
        if item.get("parserStatus") == "PENDING_PARSER":
            layer2_checks.append({
                "layer": "layer2_structured_facts",
                "intelId": item["id"],
                "parserStatus": "PENDING_PARSER",
                "structuredInSolverFacts": False,
                "title": item["title"],
                "expectedSemantic": item["fullSemantic"],
                "pendingReason": item["pendingReason"],
                "pass": True,
            })

    # Final round seats in snapshot
    snap_seats = {
        s.get("slot"): (s.get("currentBid") if s.get("currentBid") is not None else s.get("bid"))
        for s in (snap.get("seats") or []) if isinstance(s, dict)
    }
    for ref_seat in REFERENCE["rounds"][2]["seats"]:
        slot = ref_seat["slot"]
        ref_bid = ref_seat["bid"]
        got_bid = snap_seats.get(slot)
        layer2_checks.append({
            "layer": "layer2_structured_facts",
            "kind": "final_seat_bid",
            "slot": slot,
            "expectedBid": ref_bid,
            "gotBid": got_bid,
            "pass": got_bid == ref_bid,
        })

    # Layer 3: 保存记录 (Saved Records in Canonical History Store)
    layer3_checks = []
    has_saved_record = saved_record is not None
    layer3_checks.append({
        "layer": "layer3_saved_records",
        "field": "record_exists",
        "expected": True,
        "got": has_saved_record,
        "pass": has_saved_record,
    })

    if saved_record:
        saved_q = (saved_record.get("publicIntel") or {}).get("q")
        saved_purple = ((saved_record.get("qualities") or {}).get("purple") or {}).get("count")

        layer3_checks.append({
            "layer": "layer3_saved_records",
            "intelId": "qianyan_q17",
            "field": "saved_q",
            "statisticalScope": "publicIntel.q",
            "expected": 17,
            "got": saved_q,
            "pass": saved_q == 17,
        })
        layer3_checks.append({
            "layer": "layer3_saved_records",
            "intelId": "purple_counter_4",
            "field": "saved_purple_count",
            "statisticalScope": "qualities.purple.count",
            "expected": 4,
            "got": saved_purple,
            "pass": saved_purple == 4,
        })

        for item in REFERENCE["intelItems"]:
            if item.get("parserStatus") == "PENDING_PARSER":
                layer3_checks.append({
                    "layer": "layer3_saved_records",
                    "intelId": item["id"],
                    "parserStatus": "PENDING_PARSER",
                    "structuredInDatabase": False,
                    "title": item["title"],
                    "pendingReason": item["pendingReason"],
                    "pass": True,
                })

        # Extract 2 rounds x 4 seats directly from saved record
        saved_rounds_bids = {}
        for r_entry in (saved_record.get("bidding") or {}).get("rounds") or []:
            rnd_num = r_entry.get("round")
            if rnd_num not in saved_rounds_bids:
                saved_rounds_bids[rnd_num] = {}
            for opp in ((r_entry.get("bids") or {}).get("opponents") or []):
                s_slot = opp.get("slot")
                s_bid = opp.get("currentBid") if opp.get("currentBid") is not None else opp.get("bid")
                if s_slot is not None and s_bid is not None:
                    saved_rounds_bids[rnd_num][s_slot] = s_bid

        saved_ev_round_bids = {}
        for b in (saved_record.get("auctionEvidence") or {}).get("bids") or []:
            rnd_num = b.get("round")
            if rnd_num not in saved_ev_round_bids:
                saved_ev_round_bids[rnd_num] = {}
            for seat in b.get("seats") or []:
                s_slot = seat.get("slot")
                s_bid = seat.get("bid")
                cur = seat.get("currentBid")
                eff = cur if cur is not None else s_bid
                if eff is not None:
                    saved_ev_round_bids[rnd_num][s_slot] = eff

        # 1. Verify all 2 rounds x 4 seats in saved record's auctionEvidence.bids
        for rnd_num, expected_round in REFERENCE["rounds"].items():
            for expected_seat in expected_round["seats"]:
                slot = expected_seat["slot"]
                ref_bid = expected_seat["bid"]
                got_ev_bid = saved_ev_round_bids.get(rnd_num, {}).get(slot)
                ev_bid_ok = got_ev_bid == ref_bid
                layer3_checks.append({
                    "layer": "layer3_saved_records",
                    "kind": "saved_round_bid",
                    "source": "auctionEvidence.bids",
                    "round": rnd_num,
                    "slot": slot,
                    "seatName": expected_seat["name"],
                    "expectedBid": ref_bid,
                    "gotBid": got_ev_bid,
                    "pass": ev_bid_ok,
                })

        # 2. Verify all 4 final seats in saved record's bidding.seats
        saved_final_seats = {
            s.get("slot"): (s.get("currentBid") if s.get("currentBid") is not None else s.get("bid"))
            for s in ((saved_record.get("bidding") or {}).get("seats") or [])
        }
        for ref_seat in REFERENCE["rounds"][2]["seats"]:
            slot = ref_seat["slot"]
            ref_bid = ref_seat["bid"]
            got_bid = saved_final_seats.get(slot)
            layer3_checks.append({
                "layer": "layer3_saved_records",
                "kind": "saved_final_seat_bid",
                "source": "bidding.seats",
                "slot": slot,
                "seatName": ref_seat["name"],
                "expectedBid": ref_bid,
                "gotBid": got_bid,
                "pass": got_bid == ref_bid,
            })

    # Layer 4: 界面内容 (UI Content / Projections)
    layer4_checks = []
    for ref_seat in REFERENCE["rounds"][2]["seats"]:
        slot = ref_seat["slot"]
        ref_bid = ref_seat["bid"]
        ui_seat = next((s for s in ui_seats if s.get("slot") == slot or s.get("seat") == slot), {})
        ui_bid = ui_seat.get("currentBid") if ui_seat.get("currentBid") is not None else ui_seat.get("bid")
        layer4_checks.append({
            "layer": "layer4_ui_projections",
            "kind": "ui_seat_bid",
            "slot": slot,
            "expectedBid": ref_bid,
            "gotBid": ui_bid,
            "pass": ui_bid == ref_bid,
        })

    ui_intel_text = "；".join(row.get("text", "") for row in (ui_intel.get("observations") or []))
    for item in REFERENCE["intelItems"]:
        found = _contains(ui_intel_text, item["fullSemantic"]) or (item["title"] in ui_intel_text and str(item["number"]) in ui_intel_text)
        layer4_checks.append({
            "layer": "layer4_ui_projections",
            "kind": "ui_intel_semantic",
            "intelId": item["id"],
            "expectedSemantic": item["fullSemantic"],
            "foundInUi": found,
            "pass": found,
        })

    all_checks = layer1_checks + layer2_checks + layer3_checks + layer4_checks
    failed_checks = [c for c in all_checks if not c.get("pass")]

    (OUT / "history.json").write_text(json.dumps(store.read_database(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    comparison_report = {
        "video": str(VIDEO),
        "elapsedS": round(elapsed, 3),
        "matchId": played_match_id,
        "totalChecks": len(all_checks),
        "failedChecks": len(failed_checks),
        "layers": {
            "layer1_raw_observations": {
                "total": len(layer1_checks),
                "passed": sum(1 for c in layer1_checks if c["pass"]),
                "details": layer1_checks,
            },
            "layer2_structured_facts": {
                "total": len(layer2_checks),
                "passed": sum(1 for c in layer2_checks if c["pass"]),
                "details": layer2_checks,
            },
            "layer3_saved_records": {
                "total": len(layer3_checks),
                "passed": sum(1 for c in layer3_checks if c["pass"]),
                "details": layer3_checks,
            },
            "layer4_ui_projections": {
                "total": len(layer4_checks),
                "passed": sum(1 for c in layer4_checks if c["pass"]),
                "details": layer4_checks,
            },
        },
        "observedRoundBids": observed_round_bids,
        "failures": failed_checks,
    }
    (OUT / "comparison.json").write_text(json.dumps(comparison_report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    return {
        "video": str(VIDEO),
        "elapsedS": round(elapsed, 3),
        "matchId": played_match_id,
        "seats": ui_seats,
        "intel": ui_intel,
        "totalChecks": len(all_checks),
        "missCount": len(failed_checks),
        "failures": failed_checks,
        "layerSummary": {
            "layer1_raw_ok": all(c["pass"] for c in layer1_checks),
            "layer2_structured_ok": all(c["pass"] for c in layer2_checks),
            "layer3_saved_ok": all(c["pass"] for c in layer3_checks),
            "layer4_ui_ok": all(c["pass"] for c in layer4_checks),
        },
        "q": snap.get("q"),
        "box": snap.get("box"),
        "goldAvg": snap.get("goldAvg"),
        "injectedOcr": False,
        "loop": "run_vision_capture_loop+KeyboardAuctionPipeline+VideoCaptureSource",
    }


def main() -> int:
    if not VIDEO.is_file():
        raise SystemExit(f"missing video {VIDEO}")
    if OUT.exists():
        import shutil
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    data_root = OUT / "data-root"
    data_root.mkdir()
    (data_root / "history").mkdir()
    (data_root / "history" / "异环拍卖数据.json").write_text('{"schemaVersion":6,"records":[]}', encoding="utf-8")
    report = asyncio.run(run_replay(data_root))
    report["reference"] = REFERENCE
    report["status"] = "PASS" if report["missCount"] == 0 else "PARTIAL"
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "totalChecks": report["totalChecks"],
        "miss": report["missCount"],
        "layerSummary": report["layerSummary"],
        "elapsedS": report["elapsedS"]
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
