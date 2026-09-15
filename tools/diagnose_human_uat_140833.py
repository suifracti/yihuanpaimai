"""One-time, read-only evidence helper for the 2026-09-06 human UAT.

This module is intentionally outside the production import path.  It only
reads the supplied video and writes derived evidence under the caller's
explicit output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Iterable

import cv2
import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_video(path: Path):
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video: {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if fps <= 0 or count <= 0:
        capture.release()
        raise RuntimeError(f"video has no usable fps/frame count: {path}")
    return capture, fps, count


def read_at(capture, fps: float, seconds: float):
    frame_index = max(0, int(round(seconds * fps)))
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = capture.read()
    if not ok or frame is None:
        return None, frame_index
    return frame, frame_index


def fit_tile(frame, width: int = 320, height: int = 180):
    tile = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    return tile


def put_label(tile, label: str):
    result = tile.copy()
    cv2.rectangle(result, (0, 0), (result.shape[1], 24), (0, 0, 0), -1)
    cv2.putText(
        result,
        label,
        (6, 17),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return result


def write_contact_sheet(video: Path, output: Path, step: float, columns: int = 4):
    capture, fps, count = open_video(video)
    duration = count / fps
    times = [min(i * step, max(0.0, duration - 1.0 / fps)) for i in range(math.ceil(duration / step))]
    tiles = []
    for seconds in times:
        frame, frame_index = read_at(capture, fps, seconds)
        if frame is None:
            continue
        tiles.append(put_label(fit_tile(frame), f"{seconds:7.2f}s  f={frame_index}"))
    capture.release()
    if not tiles:
        raise RuntimeError("no frames decoded")
    rows = math.ceil(len(tiles) / columns)
    tile_h, tile_w = tiles[0].shape[:2]
    sheet = np.full((rows * tile_h, columns * tile_w, 3), 20, dtype=np.uint8)
    for index, tile in enumerate(tiles):
        row, col = divmod(index, columns)
        sheet[row * tile_h : (row + 1) * tile_h, col * tile_w : (col + 1) * tile_w] = tile
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), sheet):
        raise RuntimeError(f"cannot write {output}")
    return {"output": str(output), "step_s": step, "duration_s": duration, "frame_count": count, "fps": fps, "tiles": len(tiles)}


def write_frames(video: Path, output_dir: Path, times: Iterable[float]):
    output_dir.mkdir(parents=True, exist_ok=True)
    capture, fps, count = open_video(video)
    duration = count / fps
    rows = []
    for seconds in times:
        frame, frame_index = read_at(capture, fps, float(seconds))
        if frame is None:
            rows.append({"time_s": float(seconds), "frame_index": frame_index, "ok": False})
            continue
        target = output_dir / f"t-{float(seconds):010.3f}.png"
        ok = bool(cv2.imwrite(str(target), frame))
        rows.append({"time_s": float(seconds), "frame_index": frame_index, "ok": ok, "path": str(target)})
    capture.release()
    return {"duration_s": duration, "fps": fps, "frame_count": count, "frames": rows}


def _warehouse_signature(frame):
    """Small read-only signature for finding Warehouse viewport changes."""
    h, w = frame.shape[:2]
    x0, x1 = int(w * 0.64), int(w * 0.995)
    y0, y1 = int(h * 0.13), int(h * 0.78)
    crop = frame[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (96, 72), interpolation=cv2.INTER_AREA), (x0, y0, x1, y1)


def warehouse_diff_events(video: Path, output: Path, start: float, end: float, step: float):
    """Decode one sequential pass and report large right-Warehouse changes."""
    capture, fps, count = open_video(video)
    duration = count / fps
    start = max(0.0, start)
    end = min(duration, end)
    capture.set(cv2.CAP_PROP_POS_FRAMES, int(round(start * fps)))
    previous = None
    rows = []
    next_sample = start
    frame_index = int(round(start * fps)) - 1
    while next_sample <= end + 1e-9:
        target = int(round(next_sample * fps))
        while frame_index < target:
            ok, frame = capture.read()
            if not ok:
                break
            frame_index += 1
        if frame_index < target:
            break
        signature, bbox = _warehouse_signature(frame)
        diff = None if previous is None else float(cv2.absdiff(signature, previous).mean())
        rows.append({"time_s": round(frame_index / fps, 3), "frame_index": frame_index, "mean_abs_diff": diff, "bbox": bbox})
        previous = signature
        next_sample += step
    capture.release()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"video": str(video), "start_s": start, "end_s": end, "step_s": step, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"output": str(output), "rows": len(rows)}


def write_crop_sheet(video: Path, output: Path, step: float, start: float, end: float, crop_name: str = "warehouse"):
    capture, fps, count = open_video(video)
    duration = count / fps
    start = max(0.0, start)
    end = min(duration, end)
    times = []
    cursor = start
    while cursor <= end + 1e-9:
        times.append(cursor)
        cursor += step
    tiles = []
    for seconds in times:
        frame, frame_index = read_at(capture, fps, seconds)
        if frame is None:
            continue
        if crop_name == "warehouse":
            _, (x0, y0, x1, y1) = _warehouse_signature(frame)
            crop = frame[y0:y1, x0:x1]
        elif crop_name == "settlement":
            crop = frame[int(frame.shape[0] * 0.12):int(frame.shape[0] * 0.86), int(frame.shape[1] * 0.54):int(frame.shape[1] * 0.995)]
        else:
            raise ValueError(f"unknown crop {crop_name}")
        tiles.append(put_label(fit_tile(crop), f"{seconds:7.2f}s f={frame_index}"))
    capture.release()
    if not tiles:
        raise RuntimeError("no crop frames decoded")
    columns = 4
    rows = math.ceil(len(tiles) / columns)
    tile_h, tile_w = tiles[0].shape[:2]
    sheet = np.full((rows * tile_h, columns * tile_w, 3), 20, dtype=np.uint8)
    for index, tile in enumerate(tiles):
        row, col = divmod(index, columns)
        sheet[row * tile_h:(row + 1) * tile_h, col * tile_w:(col + 1) * tile_w] = tile
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), sheet):
        raise RuntimeError(f"cannot write {output}")
    return {"output": str(output), "start_s": start, "end_s": end, "step_s": step, "tiles": len(tiles), "crop": crop_name}


def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    index = min(len(ordered) - 1, max(0, int(round((percentile / 100.0) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def run_timing_probe(video: Path, output: Path, times: Iterable[float]):
    """Time the existing production pipeline on real UAT frames, read-only."""
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=True)
    os.environ["YIHUAN_DATA_ROOT"] = str(output / "data")
    os.environ["NTE_LOG_FILE"] = str(output / "timing-runtime.log")
    sys.path[:0] = [str(root / p) for p in ("app", "core")] + [str(root)]
    from vision_pipeline import NTEVisionPipeline
    from warehouse_grid_geometry import observe_warehouse_grid
    from warehouse_scrollbar_observation import observe_warehouse_scrollbar

    pipe = NTEVisionPipeline(catalog_path=str(root / "assets" / "catalog_065.json"))
    pipe._warm_ocr_async()
    capture, fps, count = open_video(video)
    frame_rows = []
    stage_rows = []

    def wrap(obj, name, stage):
        original = getattr(obj, name)
        def timed(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                stage_rows.append({"stage": stage, "duration_ms": round((time.perf_counter() - started) * 1000.0, 3)})
        setattr(obj, name, timed)

    # These wrappers do not alter outputs; they only collect inclusive timing.
    # RapidOCR is exposed as a read-only property, so proxy its callable and
    # text_rec methods instead of assigning to ``pipe.ocr``.
    pipe._ensure_ocr()
    ocr_engine = pipe._ocr_engine
    class TimedOCREngine:
        def __init__(self, inner):
            self._inner = inner

        def __call__(self, *args, **kwargs):
            started = time.perf_counter()
            try:
                return self._inner(*args, **kwargs)
            finally:
                stage_rows.append({"stage": "ocr", "duration_ms": round((time.perf_counter() - started) * 1000.0, 3)})

        def text_rec(self, *args, **kwargs):
            started = time.perf_counter()
            try:
                return self._inner.text_rec(*args, **kwargs)
            finally:
                stage_rows.append({"stage": "ocr_text_rec", "duration_ms": round((time.perf_counter() - started) * 1000.0, 3)})

        def __getattr__(self, name):
            return getattr(self._inner, name)

    pipe._ocr_engine = TimedOCREngine(ocr_engine)
    for name, stage in (
        ("_classify_scene_fast", "scene_fast"),
        ("_read_df_numeric_batch", "df_numeric"),
        ("_run_df_seat_bids_shadow", "df_seat_bids"),
        ("_parse_settlement", "settlement_parse"),
    ):
        if hasattr(pipe, name):
            wrap(pipe, name, stage)
    recognizer = pipe.settlement_recognizer
    if hasattr(recognizer, "parse_settlement_ledger"):
        wrap(recognizer, "parse_settlement_ledger", "settlement_ledger")
    character = pipe.character_matcher
    if hasattr(character, "identify"):
        wrap(character, "identify", "character_template")

    for seconds in sorted(float(value) for value in times):
        frame, frame_index = read_at(capture, fps, seconds)
        if frame is None:
            frame_rows.append({"time_s": seconds, "frame_index": frame_index, "ok": False})
            continue
        before = len(stage_rows)
        started = time.perf_counter()
        ctx = pipe.process_frame(
            frame,
            captured_at=f"2026-09-06T14:08:33+08:00",
            record_stable_key="human-uat-140833-timing",
        )
        process_ms = (time.perf_counter() - started) * 1000.0
        stage_slice = stage_rows[before:]
        grid_ms = None
        scroll_ms = None
        grid_result = None
        scroll_result = None
        if ctx.get("isSettlement") or ctx.get("scene") in ("SETTLEMENT", "IN_AUCTION"):
            started_grid = time.perf_counter()
            grid_result = observe_warehouse_grid(frame, already_cropped=False)
            grid_ms = (time.perf_counter() - started_grid) * 1000.0
            started_scroll = time.perf_counter()
            scroll_result = observe_warehouse_scrollbar(frame, already_cropped=False)
            scroll_ms = (time.perf_counter() - started_scroll) * 1000.0
        settlement = ctx.get("settlementData") or {}
        frame_rows.append({
            "time_s": seconds,
            "frame_index": frame_index,
            "ok": True,
            "process_ms": round(process_ms, 3),
            "stage_calls": stage_slice,
            "scene": ctx.get("scene"),
            "isSettlement": bool(ctx.get("isSettlement")),
            "settlementReady": bool(ctx.get("settlementReady")),
            "settlement": {k: settlement.get(k) for k in ("clearingPrice", "actualTotal", "profit", "animationComplete")},
            "settlementItemCount": ctx.get("settlementItemCount"),
            "settlementExactItemCount": ctx.get("settlementExactItemCount"),
            "warehouseSlotCount": len((ctx.get("warehouseVision") or {}).get("slots") or []),
            "grid_ms": round(grid_ms, 3) if grid_ms is not None else None,
            "grid_status": (grid_result or {}).get("grid", {}).get("status") if grid_result else None,
            "scroll_ms": round(scroll_ms, 3) if scroll_ms is not None else None,
            "scroll_state": (scroll_result or {}).get("scrollState") if scroll_result else None,
            "ocr_call_count": getattr(pipe, "ocr_call_count", None),
        })
    capture.release()
    stage_summary = {}
    for stage in sorted({row["stage"] for row in stage_rows}):
        values = [row["duration_ms"] for row in stage_rows if row["stage"] == stage]
        stage_summary[stage] = {"n": len(values), "median_ms": _percentile(values, 50), "p95_ms": _percentile(values, 95), "max_ms": round(max(values), 3)}
    process_values = [row["process_ms"] for row in frame_rows if row.get("ok")]
    payload = {
        "video": str(video.resolve()),
        "mode": "offline-production-pipeline-timing",
        "sourceSha256": sha256(video),
        "times_s": [float(value) for value in times],
        "frames": frame_rows,
        "stageSummary": stage_summary,
        "processSummary": {"n": len(process_values), "median_ms": _percentile(process_values, 50), "p95_ms": _percentile(process_values, 95), "max_ms": round(max(process_values), 3) if process_values else None},
        "liveDirectTiming": "not present in runtime log; these are offline measurements on the same supplied UAT frames",
    }
    output_file = output / "timing.json"
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"output": str(output_file), "frames": len(frame_rows), "stageCount": len(stage_rows)}


def run_grid_scan(video: Path, output: Path, start: float, end: float, step: float):
    """Scan Warehouse geometry/scroll evidence without changing production state."""
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(root / p) for p in ("app", "core")] + [str(root)]
    from warehouse_grid_geometry import observe_warehouse_grid
    from warehouse_scrollbar_observation import observe_warehouse_scrollbar

    capture, fps, count = open_video(video)
    duration = count / fps
    start = max(0.0, start)
    end = min(duration, end)
    next_sample = start
    target = int(round(start * fps))
    capture.set(cv2.CAP_PROP_POS_FRAMES, target)
    decoded = target - 1
    previous_scroll = None
    rows = []
    while next_sample <= end + 1e-9:
        target = int(round(next_sample * fps))
        frame = None
        while decoded < target:
            ok, candidate = capture.read()
            if not ok:
                break
            decoded += 1
            frame = candidate
        if frame is None or decoded < target:
            break
        grid = observe_warehouse_grid(frame, already_cropped=False, source_id="human-uat-140833", timecode=decoded / fps)
        scroll = observe_warehouse_scrollbar(frame, previous=previous_scroll, already_cropped=False, source_id="human-uat-140833")
        if scroll.get("scrollState") != "UNKNOWN":
            previous_scroll = scroll
        rows.append({
            "time_s": round(decoded / fps, 3),
            "frame_index": decoded,
            "grid": grid.get("grid"),
            "components": grid.get("components") or [],
            "scroll": scroll,
        })
        next_sample += step
    capture.release()
    output_file = output / "grid-scan.json"
    output_file.write_text(json.dumps({"video": str(video.resolve()), "start_s": start, "end_s": end, "step_s": step, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"output": str(output_file), "rows": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    meta = sub.add_parser("metadata")
    meta.add_argument("video", type=Path)
    meta.add_argument("--output", type=Path, required=True)
    sheet = sub.add_parser("contact-sheet")
    sheet.add_argument("video", type=Path)
    sheet.add_argument("output", type=Path)
    sheet.add_argument("--step", type=float, required=True)
    sheet.add_argument("--start", type=float, default=0.0)
    sheet.add_argument("--end", type=float, default=None)
    frames = sub.add_parser("frames")
    frames.add_argument("video", type=Path)
    frames.add_argument("output_dir", type=Path)
    frames.add_argument("times", nargs="+", type=float)
    diff = sub.add_parser("warehouse-diff")
    diff.add_argument("video", type=Path)
    diff.add_argument("--output", type=Path, required=True)
    diff.add_argument("--start", type=float, required=True)
    diff.add_argument("--end", type=float, required=True)
    diff.add_argument("--step", type=float, default=0.25)
    crop = sub.add_parser("crop-sheet")
    crop.add_argument("video", type=Path)
    crop.add_argument("output", type=Path)
    crop.add_argument("--step", type=float, required=True)
    crop.add_argument("--start", type=float, required=True)
    crop.add_argument("--end", type=float, required=True)
    crop.add_argument("--crop", choices=("warehouse", "settlement"), default="warehouse")
    timing = sub.add_parser("timing")
    timing.add_argument("video", type=Path)
    timing.add_argument("--output", type=Path, required=True)
    timing.add_argument("times", nargs="+", type=float)
    scan = sub.add_parser("grid-scan")
    scan.add_argument("video", type=Path)
    scan.add_argument("--output", type=Path, required=True)
    scan.add_argument("--start", type=float, required=True)
    scan.add_argument("--end", type=float, required=True)
    scan.add_argument("--step", type=float, default=0.5)
    args = parser.parse_args()
    if args.command == "metadata":
        capture, fps, count = open_video(args.video)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        capture.release()
        payload = {
            "path": str(args.video),
            "size_bytes": args.video.stat().st_size,
            "sha256": sha256(args.video),
            "fps": fps,
            "frame_count": count,
            "width": width,
            "height": height,
            "duration_s": count / fps,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "contact-sheet":
        payload = write_contact_sheet(args.video, args.output, args.step)
        if args.start != 0.0 or args.end is not None:
            # Rebuild the requested bounded sheet; the helper above remains
            # useful for whole-video orientation sheets.
            capture, fps, count = open_video(args.video)
            duration = count / fps
            start = max(0.0, args.start)
            end = min(duration, args.end if args.end is not None else duration)
            times = []
            cursor = start
            while cursor <= end + 1e-9:
                times.append(cursor)
                cursor += args.step
            capture.release()
            # Reuse the same rendering path with a temporary bounded reader.
            capture, fps, count = open_video(args.video)
            tiles = []
            for seconds in times:
                frame, frame_index = read_at(capture, fps, seconds)
                if frame is not None:
                    tiles.append(put_label(fit_tile(frame), f"{seconds:7.2f}s  f={frame_index}"))
            capture.release()
            columns = 4
            rows = math.ceil(len(tiles) / columns)
            tile_h, tile_w = tiles[0].shape[:2]
            sheet_image = np.full((rows * tile_h, columns * tile_w, 3), 20, dtype=np.uint8)
            for index, tile in enumerate(tiles):
                row, col = divmod(index, columns)
                sheet_image[row * tile_h : (row + 1) * tile_h, col * tile_w : (col + 1) * tile_w] = tile
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(args.output), sheet_image):
                raise RuntimeError(f"cannot write {args.output}")
            payload.update({"start_s": start, "end_s": end, "tiles": len(tiles)})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "warehouse-diff":
        payload = warehouse_diff_events(args.video, args.output, args.start, args.end, args.step)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "crop-sheet":
        payload = write_crop_sheet(args.video, args.output, args.step, args.start, args.end, args.crop)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "timing":
        payload = run_timing_probe(args.video, args.output, args.times)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "grid-scan":
        payload = run_grid_scan(args.video, args.output, args.start, args.end, args.step)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    payload = write_frames(args.video, args.output_dir, args.times)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
