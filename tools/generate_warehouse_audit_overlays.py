# -*- coding: utf-8 -*-
"""Generate frame-level overlay comparisons between Ground Truth bboxes and Predicted Review Units."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    'C:/Program Files/Python310/Lib/site-packages',
    str(ROOT / 'core'),
    str(ROOT / 'app'),
    str(ROOT / 'tools'),
]

import json
import cv2
import numpy as np

from warehouse_scrollbar_observation import warehouse_search_roi
from warehouse_grid_geometry import observe_warehouse_grid

def generate_overlays():
    audit_report_path = ROOT / "build" / "diagnosis_20260909" / "p3-warehouse" / "video_audit" / "audit_report.json"
    gt_path = ROOT / "assets" / "items" / "video_ground_truth_reference_144037.json"
    out_dir = ROOT / "build" / "diagnosis_20260909" / "p3-warehouse" / "video_audit" / "overlays"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not audit_report_path.is_file() or not gt_path.is_file():
        print("Missing audit report or ground truth json.")
        return

    audit_data = json.loads(audit_report_path.read_text(encoding="utf-8"))
    gt_data = json.loads(gt_path.read_text(encoding="utf-8"))
    gt_items = gt_data["items"]
    pred_units = audit_data.get("item_audit", {}).get("units_list", [])

    video_path = "D:/video/2026-09-08 14-40-37.mkv"
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0

    print(f"Generating overlays for {len(gt_items)} GT items...")

    # Index predicted units by world coords
    pred_by_coord = {}
    for u in pred_units:
        wa = u.get("anchor") or {}
        r = wa.get("row")
        c = wa.get("col")
        if r is not None and c is not None:
            pred_by_coord[(r, c)] = u

    # Build keyframe offset lookup based on timestamp
    # Top keyframe (158s): row_offset = 0
    # Middle keyframes: row_offset increments
    summary_records = []
    for idx, item in enumerate(gt_items):
        gid = item["referenceId"]
        bb = item["gridBoundingBox"]
        gr, gc = bb["row"], bb["col"]
        gw, gh = bb["width"], bb["height"]
        t_sec = float(item.get("videoSourceFrameTimeSec", 158.0))

        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t_sec * fps))
        ok, frame = cap.read()
        if not ok:
            continue

        h, w = frame.shape[:2]
        x1, y1, x2, y2 = warehouse_search_roi(w, h)
        crop = frame[y1:y2, x1:x2].copy()

        g_obs = observe_warehouse_grid(crop, already_cropped=True)
        grid = g_obs.get("grid") or {}
        x_lines = grid.get("xLines") or [0, 75, 150, 225, 300, 375, 450, 525, 600, 675, 750]
        y_lines = grid.get("yLines") or [0, 75, 150, 225, 300, 375, 450, 525, 600, 675, 750]

        vis = crop.copy()
        
        # Determine local row offset for this timestamp
        # Calculate approximate row offset from scroll position:
        # 158s: 0 rows
        # 160s: ~1 rows
        # 164s: ~3 rows
        # 165s: ~5 rows
        # 167s: ~8 rows
        # 168s: ~11 rows
        # 170s: ~14 rows
        # 171s: ~15 rows
        approx_row_offset = 0
        if t_sec >= 171.0:
            approx_row_offset = 15
        elif t_sec >= 170.0:
            approx_row_offset = 14
        elif t_sec >= 168.0:
            approx_row_offset = 11
        elif t_sec >= 167.0:
            approx_row_offset = 8
        elif t_sec >= 165.0:
            approx_row_offset = 5
        elif t_sec >= 164.0:
            approx_row_offset = 3
        elif t_sec >= 160.0:
            approx_row_offset = 1

        local_r = gr - approx_row_offset
        if 0 <= local_r < len(y_lines) - 1 and 0 <= gc < len(x_lines) - 1:
            lr2 = min(len(y_lines) - 1, local_r + gh)
            lc2 = min(len(x_lines) - 1, gc + gw)
            gt_px1, gt_py1 = x_lines[gc], y_lines[local_r]
            gt_px2, gt_py2 = x_lines[lc2], y_lines[lr2]
            
            # Draw GT in bright GREEN
            cv2.rectangle(vis, (gt_px1, gt_py1), (gt_px2, gt_py2), (0, 255, 0), 2)
            cv2.putText(vis, f"GT: {gid} ({gw}x{gh})", (gt_px1 + 4, gt_py1 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

            # Draw overlapping predicted units in BLUE/RED
            for (pr, pc), pu in pred_by_coord.items():
                pshape = pu.get("shape", "1x1").split("x")
                pw, ph = int(pshape[0]), int(pshape[1])
                p_local_r = pr - approx_row_offset
                if 0 <= p_local_r < len(y_lines) - 1 and 0 <= pc < len(x_lines) - 1:
                    plr2 = min(len(y_lines) - 1, p_local_r + ph)
                    plc2 = min(len(x_lines) - 1, pc + pw)
                    p_px1, p_py1 = x_lines[pc], y_lines[p_local_r]
                    p_px2, p_py2 = x_lines[plc2], y_lines[plr2]
                    # If nearby or overlaps
                    if not (plc2 <= gc or pc >= lc2 or plr2 <= local_r or p_local_r >= lr2):
                        is_match = (pr == gr and pc == gc and pw == gw and ph == gh)
                        color = (255, 120, 0) if is_match else (0, 0, 255) # Cyan if match, Red if split/diff
                        cv2.rectangle(vis, (p_px1 + 2, p_py1 + 2), (p_px2 - 2, p_py2 - 2), color, 2)
                        cv2.putText(vis, f"Pred: {pu['unitId']}", (p_px1 + 4, p_py2 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        out_name = f"{gid}_{bb['shape']}_t{int(t_sec)}s.png"
        cv2.imwrite(str(out_dir / out_name), vis)
        summary_records.append({
            "referenceId": gid,
            "gridBoundingBox": bb,
            "timeSec": t_sec,
            "overlayPath": str(out_dir / out_name),
        })

    cap.release()
    print(f"Exported {len(summary_records)} overlay references to {out_dir}")

if __name__ == "__main__":
    generate_overlays()
