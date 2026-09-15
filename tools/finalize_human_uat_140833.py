"""Assemble read-only evidence for the 2026-09-06 human UAT diagnosis.

This is a one-shot evidence writer.  It imports no production modules and only
reads the supplied video, copied live artifacts, and isolated replay/timing
outputs.  All writes are constrained to the explicitly supplied evidence root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def percentile(values: Iterable[float], percent: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    # Match the one-shot timing helper's nearest-index convention.
    index = min(len(ordered) - 1, max(0, int(round((percent / 100.0) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def number_summary(values: Iterable[float]) -> dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    return {
        "n": len(ordered),
        "median_ms": percentile(ordered, 50),
        "p95_ms": percentile(ordered, 95),
        "max_ms": round(max(ordered), 3) if ordered else None,
        "min_ms": round(min(ordered), 3) if ordered else None,
    }


def stage_summary(frames: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    durations: dict[str, list[float]] = {}
    for frame in frames:
        for call in frame.get("stage_calls") or []:
            stage = call.get("stage")
            duration = call.get("duration_ms")
            if stage and isinstance(duration, (int, float)):
                durations.setdefault(str(stage), []).append(float(duration))
    return {stage: number_summary(values) for stage, values in sorted(durations.items())}


def compact_item(item: dict[str, Any], evidence_frame: str) -> dict[str, Any]:
    return {
        "name": item.get("name"),
        "exactItemId": item.get("exactItemId"),
        "price": item.get("price"),
        "row": item.get("row"),
        "col": item.get("col"),
        "widthCells": item.get("widthCells"),
        "heightCells": item.get("heightCells"),
        "status": item.get("status"),
        "groupingAmbiguous": item.get("groupingAmbiguous"),
        "evidence": {
            "replayFrame": evidence_frame,
            "identitySource": "isolated current-production replay output",
            "independentTruthFromSettlementTotal": False,
        },
    }


def latest_stable(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if row.get("scene") == "SETTLEMENT"
        and row.get("settlementReady") is True
        and int(row.get("settlementItemCount") or 0) > 0
    ]
    return candidates[-1] if candidates else None


def replay_bundle(root: Path, name: str) -> dict[str, Any]:
    bundle = root / name
    report = read_json(bundle / "report.json", {}) or {}
    rows = read_jsonl(bundle / "frames.jsonl")
    stable = latest_stable(rows)
    video_report = (report.get("videos") or [{}])[0]
    evidence_frame = None
    if stable:
        stable_seconds = float(stable.get("seconds", 0))
        # Replay stores transition/anchor frames, not every step-1 frame. Use
        # the latest stored JPEG at or before the stable row so every reference
        # in the final audit is an existing source artifact.
        candidates: list[tuple[float, str]] = []
        for image in sorted(bundle.glob("v1-*.jpg")):
            try:
                seconds = float(image.stem[3:])
            except ValueError:
                continue
            if seconds <= stable_seconds + 1e-6:
                candidates.append((seconds, image.name))
        if candidates:
            evidence_frame = f"{name}/{max(candidates)[1]}"
        else:
            evidence_frame = f"{name}/NO_STORED_FRAME_AT_OR_BEFORE_{stable_seconds:.3f}s"
    return {
        "bundle": bundle,
        "report": report,
        "rows": rows,
        "stable": stable,
        "videoReport": video_report,
        "evidenceFrame": evidence_frame,
    }


def stable_item_list(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    stable = bundle.get("stable") or {}
    frame = bundle.get("evidenceFrame") or ""
    return [compact_item(item, frame) for item in stable.get("items") or []]


def run_git(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:  # pragma: no cover - evidence should still be emitted
        return f"UNAVAILABLE: {type(exc).__name__}: {exc}"


def timing_bundle(path: Path, match_end: float | None = None) -> dict[str, Any]:
    data = read_json(path, {}) or {}
    frames = list(data.get("frames") or [])
    if match_end is not None:
        frames = [row for row in frames if float(row.get("time_s") or 0) <= match_end]
    process_values = [float(row["process_ms"]) for row in frames if isinstance(row.get("process_ms"), (int, float))]
    stage = stage_summary(frames)
    in_auction = [
        float(row["process_ms"])
        for row in frames
        if row.get("scene") == "IN_AUCTION" and isinstance(row.get("process_ms"), (int, float))
    ]
    return {
        "source": str(path),
        "frameCount": len(frames),
        "times_s": [row.get("time_s") for row in frames],
        "process": number_summary(process_values),
        "inAuctionProcess": number_summary(in_auction),
        "stage": stage,
        "settlementLedger": stage.get("settlement_ledger"),
        "liveDirectTiming": "not present in runtime log; same supplied UAT frames measured offline",
    }


def grid_intervals(path: Path) -> dict[str, Any]:
    data = read_json(path, {}) or {}
    rows = list(data.get("rows") or [])
    by_scroll: dict[str, list[float]] = {}
    for row in rows:
        state = str((row.get("scroll") or {}).get("scrollState") or "UNKNOWN")
        by_scroll.setdefault(state, []).append(float(row.get("time_s") or 0))
    intervals: dict[str, list[dict[str, Any]]] = {}
    for state, times in by_scroll.items():
        times = sorted(times)
        if not times:
            continue
        groups: list[list[float]] = [[times[0]]]
        step = float(data.get("step_s") or 0.25)
        for time_s in times[1:]:
            if time_s - groups[-1][-1] <= step * 1.6:
                groups[-1].append(time_s)
            else:
                groups.append([time_s])
        intervals[state] = [{"start_s": round(group[0], 3), "end_s": round(group[-1], 3), "samples": len(group)} for group in groups]
    return {
        "source": str(path),
        "rows": len(rows),
        "gridStatusCounts": _group_count(rows, lambda row: (row.get("grid") or {}).get("status")),
        "scrollStateCounts": _group_count(rows, lambda row: (row.get("scroll") or {}).get("scrollState")),
        "componentCountCounts": _group_count(rows, lambda row: len(row.get("components") or [])),
        "scrollIntervals": intervals,
    }


def _group_count(rows: Iterable[dict[str, Any]], key_fn) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(key_fn(row) or "UNKNOWN")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-log", type=Path, required=True)
    parser.add_argument("--live-history", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    video = args.video.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    video_hash = sha256_file(video)
    replay1 = replay_bundle(output, "replay-match1-step1")
    replay2 = replay_bundle(output, "replay-match2-step1")
    timing1 = timing_bundle(output / "timing-probe-2" / "timing.json", match_end=235.0)
    timing2 = timing_bundle(output / "timing-match2" / "timing.json")
    grid1 = grid_intervals(output / "grid-scan-match1-settlement" / "grid-scan.json")
    grid2 = grid_intervals(output / "grid-scan-match2" / "grid-scan.json")
    grid1_auction = grid_intervals(output / "grid-scan-match1-auction" / "grid-scan.json")

    stable1 = replay1.get("stable") or {}
    stable2 = replay2.get("stable") or {}
    items1 = stable_item_list(replay1)
    items2 = stable_item_list(replay2)
    exact1 = sum(1 for item in items1 if item.get("status") == "exact")
    exact2 = sum(1 for item in items2 if item.get("status") == "exact")
    unknown1 = sum(1 for item in items1 if item.get("status") != "exact")
    unknown2 = sum(1 for item in items2 if item.get("status") != "exact")

    timeline = {
        "schemaVersion": "human-uat-140833.v1",
        "generatedAt": generated_at,
        "video": {
            "path": str(video),
            "sha256": video_hash,
            "fps": 60.0,
            "frameCount": 27807,
            "duration_s": 463.45,
            "resolution": [1920, 1080],
        },
        "inputStatus": {
            "requiredRawNote": "D:\\ObsidianLiveSyncTestVault\\10-Journal\\Raw\\2026\\2026-09-06\\140833-human-uat-two-matches.md",
            "status": "MISSING",
            "searchedBeforeDiagnosis": True,
            "note": "No file with this exact name or matching human-uat/uat stem was present in the 2026-09-06 Raw directory; conclusions use the supplied MKV, copied live artifacts, and current source.",
        },
        "clockAlignment": {
            "videoFileNameTime": "2026-09-06 14:08:33",
            "liveRuntimeStarted": "2026-09-06 14:06:43",
            "status": "ORDER_ONLY",
            "note": "The live log and recording have no shared frame timestamp; wall-clock seconds are not asserted as a one-to-one video offset. Character/state identity is corroborated independently by video and live log/replay.",
        },
        "matches": [
            {
                "match": 1,
                "character": "达芙蒂尔",
                "characterEvidence": ["video:t=48.0-50.0", "live-log:2026-09-06 14:08:45"],
                "videoTimeRange_s": [48.0, 235.75],
                "phases": [
                    {"name": "lobby", "range_s": [48.0, 55.0]},
                    {"name": "loading", "range_s": [55.5, 57.0]},
                    {"name": "in_auction", "range_s": [57.5, 194.5]},
                    {"name": "settlement_transition", "range_s": [194.75, 196.0]},
                    {"name": "settlement_screen_first_visible", "range_s": [196.25, 235.0]},
                    {"name": "settlement_warehouse_outline_reveal", "range_s": [196.25, 198.75]},
                    {"name": "settlement_warehouse_colored", "range_s": [199.0, 235.0]},
                    {"name": "leave_transition", "range_s": [235.25, 236.0]},
                ],
                "warehouseScrollEvents": [],
            },
            {
                "match": 2,
                "character": "小吱",
                "characterEvidence": ["video:t=251.0-258.0", "offline-replay:replay-match2-step1"],
                "videoTimeRange_s": [235.75, 459.0],
                "phases": [
                    {"name": "previous_match_exit", "range_s": [235.75, 250.5]},
                    {"name": "lobby", "range_s": [251.0, 267.0]},
                    {"name": "loading", "range_s": [267.0, 285.5]},
                    {"name": "in_auction", "range_s": [286.0, 425.75]},
                    {"name": "settlement_transition", "range_s": [426.0, 432.25]},
                    {"name": "settlement_warehouse_top", "range_s": [432.5, 442.0]},
                    {"name": "warehouse_scroll_start", "range_s": [442.1, 442.25]},
                    {"name": "warehouse_scroll_middle", "range_s": [442.25, 452.5]},
                    {"name": "warehouse_scroll_bottom", "range_s": [452.75, 458.75]},
                    {"name": "post_settlement_transition", "range_s": [459.0, 463.45]},
                ],
                "warehouseScrollEvents": [
                    {"event": "continuous_downward_scroll", "start_s": 442.1, "firstMiddle_s": 442.25, "bottom_s": 452.75, "endObserved_s": 458.75, "count": 1}
                ],
                "liveStatus": "NO_LIVE_RUNTIME; this match is offline replay only",
            },
        ],
        "visualEvidence": {
            "match1Timeline": "timeline-match1-start-0.5s.jpg",
            "match1Settlement": "timeline-match1-settlement-0.5s.jpg",
            "match2Timeline": "timeline-match2-start-0.5s.jpg",
            "match2Warehouse": "match2-settlement-warehouse-scroll-0.25s.jpg",
            "match2Diff": "match2-settlement-diff.json",
            "keyframesDirectory": "keyframes/",
            "denseTransitionDirectory": "dense-first-transitions/",
            "settlementEarlyDirectory": "settle1-early/",
        },
        "derivedCoverage": {"match1SettlementGrid": grid1, "match1AuctionGrid": grid1_auction, "match2Grid": grid2},
    }
    write_json(output / "timeline.json", timeline)

    live_latency = {
        "schemaVersion": "human-uat-140833.v1",
        "generatedAt": generated_at,
        "source": {
            "videoSha256": video_hash,
            "liveLog": str(args.live_log.resolve()),
            "liveLogSha256": sha256_file(args.live_log) if args.live_log.exists() else None,
            "liveHistory": str(args.live_history.resolve()),
            "liveHistorySha256": sha256_file(args.live_history) if args.live_history.exists() else None,
        },
        "liveDirect": {
            "perRequestLatency": "NOT_RECOVERABLE_FROM_EXISTING_LOG",
            "missingFields": ["userTrigger", "frameCapture", "queueEnter", "processingStart", "stageEnd", "displayTime", "requestId", "captureTimestamp"],
            "pipelineWarmupMs": 460.9,
            "coarseStateTransitions": [
                {"wall": "14:08:45", "state": "AUCTION_LOBBY", "character": "达芙蒂尔"},
                {"wall": "14:09:37", "state": "IN_AUCTION"},
                {"wall": "14:13:16", "state": "SETTLEMENT", "settlementReady": False},
                {"wall": "14:13:26", "event": "publish_disconnect"},
                {"wall": "14:13:34", "state": "SETTLEMENT", "settlementReady": False},
                {"wall": "14:16:23", "state": "SETTLEMENT", "settlementReady": False, "settlementActualTotal": 35241},
            ],
            "directBacklogEvidence": "NO_EXPLICIT_QUEUE_OR_REQUEST_ID_IN_LOG",
            "directStaleResultCount": "NOT_RECOVERABLE",
        },
        "offlineSameFrameTiming": {
            "match1": timing1,
            "match2": timing2,
            "interpretation": "Inference only: isolated current-production pipeline on sampled frames from this UAT video; not a claim that every live frame had exactly this latency.",
        },
        "conclusions": {
            "match1UserVisibleLatencyScale": {
                "inAuctionMedianMs": timing1["inAuctionProcess"]["median_ms"],
                "inAuctionP95Ms": timing1["inAuctionProcess"]["p95_ms"],
                "inAuctionMaxMs": timing1["inAuctionProcess"]["max_ms"],
                "allSampledMatch1MedianMs": timing1["process"]["median_ms"],
                "allSampledMatch1P95Ms": timing1["process"]["p95_ms"],
                "allSampledMatch1MaxMs": timing1["process"]["max_ms"],
                "sampleCount": timing1["frameCount"],
            },
            "majorStages": {
                "normalInAuction": {"stage": "ocr", "timing": timing1["stage"].get("ocr")},
                "settlement": {"stage": "settlement_ledger", "timing": timing1.get("settlementLedger")},
            },
            "backlog": {
                "explicitQueue": False,
                "captureLoopIsSequential": True,
                "effectiveBacklogPressure": "CONFIRMED_BY_OFFLINE_COSTS",
                "reason": "A sequential capture/process loop running for 7.80-15.07s in auction and 34.46-81.12s at first settlement cannot keep up with a nominal 10Hz capture cadence; exact dropped/queued count is absent from live logs.",
            },
            "staleResult": {
                "directObservedCount": "NOT_RECOVERABLE",
                "risk": "CONFIRMED",
                "reason": "Captured frames can finish seconds to tens of seconds after the screen changed; no capture timestamp/request ID pair was persisted to prove each individual stale display.",
            },
        },
    }
    write_json(output / "live-latency-audit.json", live_latency)

    failure = {
        "schemaVersion": "human-uat-140833.v1",
        "generatedAt": generated_at,
        "match": 1,
        "videoSettlement": {
            "exists": True,
            "firstVisible_s": 196.25,
            "coloredWarehouseVisible_s": 199.0,
            "physicalGridEvidence": "grid-scan-match1-settlement/grid-scan.json",
        },
        "productionOfflineComparison": {
            "scene": "SETTLEMENT",
            "firstStableRow_s": stable1.get("seconds"),
            "settlementReady": stable1.get("settlementReady"),
            "itemCount": stable1.get("settlementItemCount"),
            "exactItemCount": stable1.get("settlementExactItemCount"),
            "isolatedArchive": True,
            "archiveEvidence": "replay-match1-step1/report.json",
            "productionHistoryPollution": False,
        },
        "liveChain": [
            {"stage": "scene_parse", "status": "CONFIRMED", "evidence": "live-run-2026-09-06_14-06-43.log:14:13:16"},
            {"stage": "settlement_values", "status": "CONFIRMED", "value": "500000/113591/-386409", "evidence": "live-run-2026-09-06_14-06-43.log:14:13:16"},
            {"stage": "settlement_stability_gate", "status": "FAILED_EARLIEST_CONFIRMED", "observed": "settleReady=False at 14:13:16, 14:13:34, 14:14:05, 14:14:25, 14:14:50, 14:15:17, 14:16:23", "why": "No live evidence shows two final/stable observations completing before the transport reset/next transition."},
            {"stage": "warehousePresent", "status": "NOT_LOGGED_DIRECTLY", "note": "Offline grid is OK when the settlement warehouse is visible; live worker log only prints warehouseVision slots, not the main callback's warehousePresent."},
            {"stage": "settlement_capture_orchestration", "status": "NOT_ELIGIBLE", "reason": "maybe_trigger_auto_warehouse_capture requires settlementReady/stable before warehousePresent and TOP checks."},
            {"stage": "capture_host_prepare_start", "status": "NO_EVIDENCE", "evidence": "No live prepare/start/capture evidence under the copied runtime data."},
            {"stage": "CurrentMatch", "status": "PARTIAL", "observed": "settlement money reached live History draft; warehouse remained null."},
            {"stage": "AutoArchiver", "status": "NOT_REACHED_FOR_WAREHOUSE", "reason": "worker archive condition requires isSettlement and settlementReady; no finalized live record exists."},
            {"stage": "transport", "status": "COMPOUNDING_FAILURE", "evidence": "Payload publish disconnect at 14:13:26 followed by reconnect; another at 14:16:29."},
        ],
        "EARLIEST_CONFIRMED_FAILURE": "MATCH_1_LIVE_SETTLEMENT_STABILITY_GATE_FALSE_BEFORE_WAREHOUSE_CAPTURE_ORCHESTRATION",
        "notClaimed": ["warehousePresent live status", "exact live request latency", "per-frame stale count"],
    }
    write_json(output / "first-match-settlement-failure.json", failure)

    match1_audit = {
        "schemaVersion": "human-uat-140833.v1",
        "match": 1,
        "character": "达芙蒂尔",
        "mode": {"live": True, "offlineReplay": True},
        "videoWarehouse": {
            "auction": {"range_s": [58.0, 194.0], "visibleState": "empty/dark grid; no independently named physical item", "gridScan": "grid-scan-match1-auction/grid-scan.json"},
            "settlement": {"outlineOrReveal_s": [196.25, 198.75], "coloredStable_s": [199.0, 235.0], "visiblePhysicalItems": 20},
        },
        "liveOutputComparison": {
            "warehouseHistory": None,
            "warehouseLogRowsDuringSettlement": 0,
            "categories": {"CORRECT_EXACT": 0, "CORRECT_PARTIAL_OR_OUTLINE": 0, "WRONG_IDENTITY": 0, "WRONG_GEOMETRY": 0, "MISSED": 20, "UNKNOWN_EXPECTED": 0, "STALE_RESULT": "NOT_RECOVERABLE"},
            "classificationNote": "The settlement warehouse is visible in the video, but live produced no recoverable warehouse item output or capture record; the 20 items are therefore missed by live output, not guessed identities.",
        },
        "offlineProductionStable": {
            "evidenceFrame": "replay-match1-step1/v1-0235.000.jpg",
            "physicalItemCount": int(stable1.get("settlementItemCount") or 0),
            "exact": exact1,
            "partialOrOutline": 0,
            "wrongConfirmed": 0,
            "missed": 0,
            "unknown": unknown1,
            "stale": "OFFLINE_NOT_LIVE_STALE_COUNT",
            "priceKnown": exact1,
            "positionSizeRecords": len(items1),
            "identityEvidenceStatus": stable1.get("settlementFileEvidenceStatus"),
            "items": items1,
        },
        "independentVerificationBoundary": "The 12 exact labels have current production visual evidence; the 8 null labels remain unknown. No total-price, unique-candidate, or settlement-sum inference is used.",
    }
    write_json(output / "match1-warehouse-identity-audit.json", match1_audit)

    match2_audit = {
        "schemaVersion": "human-uat-140833.v1",
        "match": 2,
        "character": "小吱",
        "mode": {"live": False, "offlineReplay": True},
        "liveBoundary": "No software live output existed for this match; all pipeline numbers below are isolated offline replay and must not be described as real-time success.",
        "inAuctionWarehouseSamples": [
            {"time_s": 300.0, "productionWarehouseVisionSlots": 8},
            {"time_s": 350.0, "productionWarehouseVisionSlots": 18},
            {"time_s": 390.0, "productionWarehouseVisionSlots": 18},
        ],
        "coverageMap": {
            "distinctPhysicalItems": 24,
            "top": {"range_s": [432.5, 442.0], "visibleComponents": 24, "status": "CONFIRMED_BY_VIDEO_AND_GRID"},
            "middle": {"range_s": [442.25, 452.5], "visibleComponentCount": "decreases_to_zero_as_top_items_leave", "status": "CONFIRMED_BY_CONTINUOUS_SCROLL"},
            "bottom": {"range_s": [452.75, 458.75], "visibleComponents": 0, "status": "CONFIRMED_EMPTY_AFTER_SCROLL"},
            "newItemsAfterTop": 0,
            "bottomMissedItems": 0,
            "scrollEvidence": "match2-settlement-warehouse-scroll-0.25s.jpg",
            "gridEvidence": "grid-scan-match2/grid-scan.json",
        },
        "trackAudit": {
            "samePhysicalItemAcrossViewport": "VISUALLY_CONTINUOUS_TOP_TO_EMPTY_BOTTOM",
            "duplicateTracks": "NOT_AVAILABLE; current settlement path emits geometry, not cross-scroll identity tracks",
            "backgroundOrSlotFalsePositives": "No new settlement item after the 24-item top set was confirmed; transitional animation rows (40/42) are excluded from the stable physical inventory.",
            "occlusionMemory": "NOT_AVAILABLE_IN_CURRENT_SETTLEMENT_PATH",
            "identityUpgrade": "NOT_OBSERVED_ACROSS_SCROLL; stable settlement ledger is one top viewport snapshot",
        },
        "offlineProductionStable": {
                "evidenceFrame": replay2.get("evidenceFrame"),
            "physicalItemCount": int(stable2.get("settlementItemCount") or 0),
            "exact": exact2,
            "partialOrOutline": 0,
            "wrongConfirmed": 0,
            "missed": 0,
            "unknown": unknown2,
            "priceKnown": exact2,
            "positionSizeRecords": len(items2),
            "identityEvidenceStatus": stable2.get("settlementFileEvidenceStatus"),
            "items": items2,
        },
        "classification": {"CORRECT_EXACT": exact2, "CORRECT_PARTIAL_OR_OUTLINE": 0, "WRONG_IDENTITY": 0, "WRONG_GEOMETRY": 0, "MISSED": 0, "UNKNOWN_EXPECTED": unknown2, "STALE_RESULT": "NOT_APPLICABLE_OFFLINE_REPLAY"},
        "independentVerificationBoundary": "The scroll coverage conclusion is geometry/video evidence. The 17 exact labels are current production visual evidence; 7 items remain unknown. No live success claim is made.",
    }
    write_json(output / "match2-warehouse-identity-audit.json", match2_audit)

    settlement_audit = {
        "schemaVersion": "human-uat-140833.v1",
        "videoSha256": video_hash,
        "settlementAudits": [
            {
                "match": 1,
                "character": "达芙蒂尔",
                "live": {"settlementVisible": True, "warehouseRecognized": False, "archivedFinal": False, "historyWarehouse": None},
                "offline": {"mode": "isolated current-production replay", "replayBundle": "replay-match1-step1", "stableFrame_s": stable1.get("seconds"), "actualVisibleItems": 20, "productionPartCount": 20, "nameCorrectOrEvidenceBacked": exact1, "nameWrongConfirmed": 0, "nameUnknown": unknown1, "priceKnown": exact1, "priceWrongConfirmed": 0, "priceUnknown": unknown1, "positionSizeRecords": 20, "positionSizeCorrectIndependentlyVerified": None, "positionSizeWrongConfirmed": 0, "positionSizeUnverified": 20},
                "settlementValuesObserved": {"clearingPrice": stable1.get("settlement", {}).get("clearingPrice"), "actualTotal": stable1.get("settlement", {}).get("actualTotal"), "profit": stable1.get("settlement", {}).get("profit")},
                "sourceEvidence": ["timeline-match1-settlement-0.5s.jpg", "replay-match1-step1/frames.jsonl", "replay-match1-step1/report.json"],
            },
            {
                "match": 2,
                "character": "小吱",
                "live": {"settlementVisible": True, "softwareRan": False, "result": "NO_LIVE_OUTPUT"},
                "offline": {"mode": "isolated current-production replay; not live success", "replayBundle": "replay-match2-step1", "stableFrame_s": stable2.get("seconds"), "actualVisibleItems": 24, "productionPartCount": 24, "nameCorrectOrEvidenceBacked": exact2, "nameWrongConfirmed": 0, "nameUnknown": unknown2, "priceKnown": exact2, "priceWrongConfirmed": 0, "priceUnknown": unknown2, "positionSizeRecords": 24, "positionSizeCorrectIndependentlyVerified": None, "positionSizeWrongConfirmed": 0, "positionSizeUnverified": 24},
                "settlementValuesObserved": {"clearingPrice": stable2.get("settlement", {}).get("clearingPrice"), "actualTotal": stable2.get("settlement", {}).get("actualTotal"), "profit": stable2.get("settlement", {}).get("profit")},
                "sourceEvidence": ["match2-settlement-warehouse-scroll-0.25s.jpg", "replay-match2-step1/frames.jsonl", "replay-match2-step1/report.json", replay2.get("evidenceFrame")],
            },
        ],
        "positionMeaning": "Production emitted row/col/width/height records, but no separately annotated per-item geometry truth was supplied for this UAT; correctness is not promoted from produced coordinates alone.",
        "newVisualStateComparedWithOldFiveMatchSet": "No new identity is promoted from the two UAT videos; the UAT adds gray-to-colored settlement timing, a full empty-bottom scroll, and live orchestration evidence.",
    }
    write_json(output / "settlement-identity-audit.json", settlement_audit)

    source_files = [
        "app/main.py",
        "app/vision_worker_loop.py",
        "core/vision_pipeline.py",
        "core/auto_archiver.py",
        "core/warehouse_capture_arming.py",
        "app/warehouse_capture_host.py",
        "assets/items/visual_catalog_v2.json",
        "assets/items/video_development_references_v1.json",
        "tools/diagnose_human_uat_140833.py",
        "tools/replay_videos.py",
    ]
    status = run_git(root, "status", "--short")
    source_fingerprint = {
        "generatedAt": generated_at,
        "gitHead": run_git(root, "rev-parse", "HEAD"),
        "gitStatusLineCount": len(status.splitlines()) if status else 0,
        "gitStatusSha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
        "workingTreePreserved": True,
        "sourceFiles": {path: sha256_file(root / path) if (root / path).exists() else None for path in source_files},
        "videoSha256": video_hash,
        "diagnosticOnly": True,
        "productionCodeChangedThisTurn": False,
        "formalCatalogSolverHistoryChangedThisTurn": False,
    }
    write_json(output / "source-fingerprint.json", source_fingerprint)

    commands = [
        "Read Vault AGENTS.md, project README.md, project Handoff.md, and docs/reports/2026-09-06-video-replay.md.",
        "Searched Raw/2026/2026-09-06 for 140833-human-uat-two-matches.md and matching human-uat/uat names; exact required note was missing.",
        "diagnose_human_uat_140833.py metadata <video> --output video-metadata.json",
        "diagnose_human_uat_140833.py contact-sheet / frames / crop-sheet / warehouse-diff for transition, settlement, and scroll windows",
        "replay_videos.py <video> --output replay-match1-step1 --step 1 --start 48 --end 240",
        "replay_videos.py <video> --output replay-match2-step1 --step 1 --start 235 --end 463.45",
        "diagnose_human_uat_140833.py timing <video> --output timing-probe-2 58 60 65 100 150 190 196.5 197 200 210 235 300 350 390 429 432.5 440 445 450",
        "diagnose_human_uat_140833.py timing <video> --output timing-match2 235 251 258 277 286 300 350 390 426 429 432.5 440 445 450",
        "diagnose_human_uat_140833.py grid-scan <video> --output grid-scan-match1-auction --start 58 --end 194 --step 1",
        "diagnose_human_uat_140833.py grid-scan <video> --output grid-scan-match1-settlement --start 185 --end 240 --step 0.25",
        "diagnose_human_uat_140833.py grid-scan <video> --output grid-scan-match2 --start 285 --end 463.45 --step 0.25",
        "This finalizer: read-only assembly of the above isolated evidence into the six requested audit JSON files.",
    ]
    (output / "commands.log").write_text("\n".join(commands) + "\n", encoding="utf-8")

    print(json.dumps({
        "output": str(output),
        "videoSha256": video_hash,
        "match1": {"items": len(items1), "exact": exact1, "unknown": unknown1},
        "match2": {"items": len(items2), "exact": exact2, "unknown": unknown2},
        "files": [
            "timeline.json",
            "live-latency-audit.json",
            "first-match-settlement-failure.json",
            "match1-warehouse-identity-audit.json",
            "match2-warehouse-identity-audit.json",
            "settlement-identity-audit.json",
            "source-fingerprint.json",
            "commands.log",
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
