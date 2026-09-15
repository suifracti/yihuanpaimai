# -*- coding: utf-8 -*-
"""P1 video audit: box and Q must survive empty auto/manual patches.

Uses the same three 2026-09-09 clips and keyframe times as the v13 replay.
Isolates YIHUAN_DATA_ROOT. Does not package, train, or write user history.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "diagnosis_20260909" / "p1-field-authority-video"
CLIPS = [
    ("2026-09-09 00-29-50.mkv", [0, 20, 32, 40, 48, 60, 82, 100]),
    ("2026-09-09 00-31-38.mkv", [0, 12, 24, 46, 55]),
    ("2026-09-09 00-33-00.mkv", [0, 11, 22, 32, 43, 52]),
]
Q_ONLY_FORM = {
    "venueId": None,
    "venue": None,
    "boxId": None,
    "box": None,
    "fieldCondition": "standard",
    "q": 12,
    "goldAvg": None,
    "purpleCount": None,
    "purple": None,
    "purpleAvg": None,
    "blueCount": None,
    "goldCount": None,
    "redCount": None,
    "totalItems": None,
    "totalGrid": None,
    "goldGrid": None,
    "purpleGrid": None,
    "knownGold": "",
    "knownRed": "",
    "knownPurple": "",
}


def _row(clip, second, stage, ctx, match):
    state = (match.field_states.get("box") if hasattr(match, "field_states") else None)
    return {
        "clip": clip,
        "second": second,
        "stage": stage,
        "scene": ctx.get("scene"),
        "observedBox": ctx.get("box"),
        "observedQ": ctx.get("q"),
        "observedGoldAvg": ctx.get("goldAvg"),
        "matchBox": match.facts.get("box"),
        "matchQ": match.facts.get("q"),
        "matchGoldAvg": match.facts.get("goldAvg"),
        "boxSource": getattr(state, "source", None),
        "boxStatus": getattr(state, "status", None),
        "boxProtected": getattr(state, "protected", None),
        "boxRejects": [
            item["reason"]
            for item in match.field_audit()
            if item.get("field") == "box" and item.get("decision") in {"reject", "conflict"}
        ][-5:],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ["YIHUAN_DATA_ROOT"] = str(OUT / "data")
    os.environ["YIHUAN_UPPER_TAIL_CAPTURE_DIR"] = str(OUT / "captures")
    os.environ["NTE_LOG_FILE"] = str(OUT / "runtime.log")
    sys.path[:0] = [str(ROOT / "app"), str(ROOT / "core"), str(ROOT)]

    import cv2
    import main as app_main
    from current_match import CurrentMatch
    from keyboard_auction_pipeline import KeyboardAuctionPipeline
    from live_match_transport import LiveMatchPublisher, LiveMatchReceiver
    from recognition_mode import set_recognition_mode

    app_main.cancel_draft_save()
    set_recognition_mode("auto")
    app_main.CURRENT_MATCH.begin_next_match()
    match = app_main.CURRENT_MATCH
    pipeline = KeyboardAuctionPipeline()
    pipeline.recognition_mode_provider = lambda: "auto"
    pipeline._ensure_ocr()

    rows = []
    attacks = []
    started = time.monotonic()
    first_box_index = None

    for name, times in CLIPS:
        path = Path("D:/video") / name
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open {path}")
        for second in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError(f"{name} @{second}s")
            for _ in range(24):
                pipeline._classify_scene_fast(frame.copy())
            t0 = time.perf_counter()
            ctx = pipeline.process_frame(frame, record_stable_key="p1-video", include_heavy_identity=False)
            if pipeline._navigation_future is not None:
                pipeline._navigation_future.result()
            elapsed = round(time.perf_counter() - t0, 3)
            app_main.sync_vision_to_current_match(ctx)
            row = _row(name, second, "frame", ctx, match)
            row["elapsed"] = elapsed
            rows.append(row)
            if first_box_index is None and ctx.get("scene") == "IN_AUCTION" and match.facts.get("box"):
                first_box_index = len(rows) - 1
        cap.release()

    if first_box_index is None:
        status = "FAIL_NO_BOX_OBSERVED"
    else:
        held_box = match.facts.get("box")
        held_q = match.facts.get("q")
        empty_ctx = {
            "scene": "IN_AUCTION",
            "venue": "中级场 · 珊瑚场",
            "lobbyVenueKey": "shanhu",
            "box": "未知箱型",
            "q": None,
            "goldAvg": None,
        }
        app_main.sync_vision_to_current_match(empty_ctx)
        attacks.append(_row("synthetic", None, "empty-auto-observation", empty_ctx, match))

        form = dict(Q_ONLY_FORM)
        form["q"] = held_q if held_q is not None else 12
        payload = app_main.apply_manual_facts({"facts": form})
        attacks.append(_row("synthetic", None, "whole-form-q-only", form, match))
        attacks[-1]["controlHasBox"] = "box" in ((payload.get("manualControl") or {}).get("facts") or {})

        worker = CurrentMatch()
        worker.id = match.id
        worker.apply_facts({"q": match.facts.get("q")}, source="vision")
        publisher, receiver = LiveMatchPublisher(), LiveMatchReceiver()
        receiver.apply(publisher.attach({}, worker)["visionState"], match)
        attacks.append(_row("synthetic", None, "worker-snapshot-null-box", {"box": None, "q": worker.facts.get("q")}, match))

        status = "PASS" if match.facts.get("box") == held_box and match.facts.get("q") == held_q else "FAIL_CLEARED"

    report = {
        "status": status,
        "seconds": round(time.monotonic() - started, 3),
        "firstBoxIndex": first_box_index,
        "finalBox": match.facts.get("box"),
        "finalQ": match.facts.get("q"),
        "sourceSha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "core/current_match.py",
                "core/live_match_control.py",
                "core/live_match_transport.py",
                "app/main.py",
            )
        },
        "frames": rows,
        "attacks": attacks,
        "boxAudit": [item for item in match.field_audit() if item.get("field") in {"box", "q"}],
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": status, "finalBox": report["finalBox"], "finalQ": report["finalQ"],
                      "seconds": report["seconds"], "frames": len(rows)}, ensure_ascii=False))
    app_main.cancel_draft_save()
    if hasattr(pipeline, "_navigation_executor"):
        pipeline._navigation_executor.shutdown()
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
