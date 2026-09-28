# -*- coding: utf-8 -*-
"""Dense video sampling, gap attribution, observer-verified keyframe reconstruction, and screen-by-screen item audit."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    'C:/Program Files/Python310/Lib/site-packages',
    str(ROOT / 'core'),
    str(ROOT / 'app'),
    str(ROOT / 'tools'),
]

import copy
import hashlib
import json
import os
import cv2
import numpy as np
import time

from warehouse_scrollbar_observation import WarehouseScrollbarObserver, warehouse_search_roi
from warehouse_segment_overlap import align_warehouse_segments, DIR_DOWN, DIR_NONE, STATUS_VERIFIED, REASON_NO_MOVEMENT
from warehouse_physical_ledger import PhysicalComponentLedger
from warehouse_coverage_ledger import WarehouseCoverageLedger
from warehouse_reconstruction import WarehouseReconstructionProcessor
from warehouse_placement_resolver import WarehousePlacementResolver
from warehouse_catalog_geometry import CatalogGeometryIndex
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from catalog_validator import validate_catalog_record, validate_item_identity
from warehouse_support_frame import stationary_support_proof


def run_dense_audit(video_path: Path, out_dir: Path) -> dict:
    t_start = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    start_frame = int(157.0 * fps)
    end_frame = int(171.5 * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    observer = WarehouseScrollbarObserver()

    print(f"Reading video from frame {start_frame} to {end_frame} (fps={fps})...", flush=True)

    raw_samples = []
    cur_idx = start_frame
    while cur_idx <= end_frame:
        ok, frame = cap.read()
        if not ok:
            break
        # Sample at 10 fps (every 6 frames at 60fps)
        if (cur_idx - start_frame) % 6 == 0:
            t = round(cur_idx / fps, 2)
            obs = observer.observe(frame)
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = warehouse_search_roi(w, h)
            crop = frame[y1:y2, x1:x2].copy()
            raw_samples.append({
                'idx': cur_idx,
                'time': t,
                'frame': frame,
                'crop': crop,
                'scroll_state': obs.get('scrollState'),
                'thumb_position': obs.get('thumbPosition'),
            })
        cur_idx += 1
    cap.release()

    print(f"Collected {len(raw_samples)} raw 10fps samples.", flush=True)

    # -------------------------------------------------------------
    # Part 1: Analyze Sparse vs Dense Gaps
    # -------------------------------------------------------------
    sparse_times = [158.0, 160.0, 162.0, 164.0, 166.0, 168.0, 170.0, 171.0]
    sparse_map = {}
    for st in sparse_times:
        closest = min(raw_samples, key=lambda x: abs(x['time'] - st))
        sparse_map[st] = closest

    print("\n--- Part 1: Sparse Sampling Gaps Analysis ---", flush=True)
    sparse_results = []
    for i in range(len(sparse_times) - 1):
        t_prev = sparse_times[i]
        t_next = sparse_times[i+1]
        s_prev = sparse_map[t_prev]
        s_next = sparse_map[t_next]
        
        align = align_warehouse_segments(
            s_prev['crop'],
            s_next['crop'],
            prev_id=f"{t_prev}s",
            next_id=f"{t_next}s",
            required_direction=DIR_DOWN,
        )
        
        status = align.get("status")
        offset = align.get("verticalOffsetPx")
        conf = round(float(align.get("confidence") or 0.0), 3)
        
        # Save preview crops for gap attribution evidence
        p_prev_path = out_dir / f"sparse_{i}_from_{t_prev}s.png"
        p_next_path = out_dir / f"sparse_{i}_to_{t_next}s.png"
        cv2.imwrite(str(p_prev_path), s_prev['crop'])
        cv2.imwrite(str(p_next_path), s_next['crop'])
        
        # Intermediate dense check
        dense_in_gap = [s for s in raw_samples if t_prev - 0.01 <= s['time'] <= t_next + 0.01]
        dense_steps = []
        dense_all_verified = True
        dense_accum_offset = 0
        movements_count = 0
        
        for k in range(len(dense_in_gap) - 1):
            d_p = dense_in_gap[k]
            d_n = dense_in_gap[k+1]
            diff = float(np.mean(np.abs(d_p['crop'].astype(float) - d_n['crop'].astype(float))))
            if diff < 1.0:
                continue
            movements_count += 1
            d_align = align_warehouse_segments(
                d_p['crop'],
                d_n['crop'],
                prev_id=f"{d_p['time']}s",
                next_id=f"{d_n['time']}s",
                required_direction=DIR_DOWN,
            )
            d_st = d_align.get("status")
            d_off = d_align.get("verticalOffsetPx") or 0
            d_cf = round(float(d_align.get("confidence") or 0.0), 3)
            dense_accum_offset += d_off
            if d_st != STATUS_VERIFIED:
                if d_align.get("reason") in (REASON_NO_MOVEMENT, "NO_MOVEMENT") or d_align.get("direction") == DIR_NONE:
                    pass
                else:
                    dense_all_verified = False
            dense_steps.append({
                'from': d_p['time'],
                'to': d_n['time'],
                'diff': round(diff, 2),
                'status': d_st,
                'offset': d_off,
                'conf': d_cf,
            })
            
        if movements_count == 0:
            attribution = "STATIONARY_DUPLICATE"
        elif status == STATUS_VERIFIED:
            attribution = "VERIFIED"
        elif dense_all_verified:
            attribution = "SAMPLING_OMISSION_LEAP"
        else:
            attribution = "ALIGNMENT_OR_VIDEO_FAILURE"
            
        sparse_results.append({
            'gap_index': i + 1,
            'from_time': t_prev,
            'to_time': t_next,
            'sparse_status': status,
            'sparse_offset': offset,
            'sparse_conf': conf,
            'dense_intermediate_frames': len(dense_in_gap),
            'dense_movements_count': movements_count,
            'dense_accum_offset': dense_accum_offset,
            'dense_all_verified': dense_all_verified,
            'dense_steps': dense_steps,
            'attribution': attribution,
        })
        print(f"Gap {i+1} ({t_prev}s -> {t_next}s): sparse={status}, offset={offset}px, conf={conf} | dense_moves={movements_count}, accum={dense_accum_offset}px, all_verified={dense_all_verified} -> Attribution: {attribution}", flush=True)

    # -------------------------------------------------------------
    # Part 2: Dense Keyframe Reconstruction with Genuine Observer Endpoints
    # -------------------------------------------------------------
    print("\n--- Part 2: Dense Keyframe Selection & Reconstruction ---", flush=True)
    keyframes = [raw_samples[0]]
    # Preserve a real, distinct stationary support frame before top items clip.
    # It adds identity evidence, never scroll progression or endpoint proof.
    for sample in raw_samples[1:]:
        elapsed = sample['time'] - raw_samples[0]['time']
        if elapsed > 1.0:
            break
        if elapsed >= 0.3 and sample['scroll_state'] == raw_samples[0]['scroll_state'] == 'TOP':
            if stationary_support_proof(raw_samples[0]['crop'], sample['crop']):
                keyframes.append(sample)
                break
    accum_since_key = 0

    for i in range(len(raw_samples) - 1):
        s_curr = raw_samples[i]
        s_next = raw_samples[i+1]
        diff = float(np.mean(np.abs(s_curr['crop'].astype(float) - s_next['crop'].astype(float))))
        if diff < 1.0:
            continue
        
        al = align_warehouse_segments(
            s_curr['crop'],
            s_next['crop'],
            prev_id=f"{s_curr['time']}",
            next_id=f"{s_next['time']}",
            required_direction=DIR_DOWN,
        )
        off = abs(al.get("verticalOffsetPx") or 0)
        accum_since_key += off
        
        # When accumulated shift is ~90-120px (about 1.5 cells), keep next keyframe
        if accum_since_key >= 95:
            keyframes.append(s_next)
            accum_since_key = 0

    if keyframes[-1]['idx'] != raw_samples[-1]['idx']:
        keyframes.append(raw_samples[-1])

    print(f"Selected {len(keyframes)} keyframes covering entire scroll sequence.", flush=True)

    store_dense = SettlementEvidenceStoreV2(out_dir.parent / "store_dense")
    match_id = "dense_audit_20260908_144037"
    desc_main = store_dense.save_original(
        record_stable_key=match_id,
        kind="main-settlement",
        image_bytes=cv2.imencode(".png", keyframes[0]['frame'])[1].tobytes(),
    )

    ledger = WarehouseCoverageLedger(match_id)
    catalog_path = ROOT / "assets" / "catalog_065.json"
    catalog_data = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.is_file() else []
    cat_index = CatalogGeometryIndex(catalog_data)
    resolver = WarehousePlacementResolver()

    proc = WarehouseReconstructionProcessor(
        match_id,
        catalog_index=cat_index,
        placement_resolver=resolver,
    )

    prev_k = None
    prev_k_desc = None
    keyframe_alignments = []

    for idx, k in enumerate(keyframes):
        t_sec = k['time']
        img_bytes = cv2.imencode(".png", k['frame'])[1].tobytes()
        k_desc = store_dense.save_original(
            record_stable_key=match_id,
            kind="warehouse-segment",
            image_bytes=img_bytes,
        )
        
        ledger_overlap = None
        recon_overlap = None
        if prev_k is not None:
            al = align_warehouse_segments(
                prev_k['crop'],
                k['crop'],
                prev_id=f"k_{idx-1}",
                next_id=f"k_{idx}",
                required_direction=DIR_DOWN,
            )
            keyframe_alignments.append({
                'from_idx': idx - 1,
                'to_idx': idx,
                'from_time': prev_k['time'],
                'to_time': k['time'],
                'status': al.get("status"),
                'offset': al.get("verticalOffsetPx"),
                'conf': round(float(al.get("confidence") or 0.0), 3),
            })
            print(f"  Keyframe {idx-1} -> {idx} ({prev_k['time']}s -> {k['time']}s): status={al.get('status')}, offset={al.get('verticalOffsetPx')}px, conf={al.get('confidence'):.3f}", flush=True)
            stationary = stationary_support_proof(prev_k['crop'], k['crop'])
            if al.get("status") == STATUS_VERIFIED or stationary:
                ledger_overlap = {
                    "trusted": True,
                    "aligned": True,
                    "proofId": f"overlap_k_{idx-1}_k_{idx}",
                    "previousEvidenceId": prev_k_desc["evidenceId"],
                }
                recon_overlap = {
                    **ledger_overlap,
                    "verticalOffsetPx": al.get("verticalOffsetPx"),
                    "direction": al.get("direction"),
                }
                if stationary:
                    recon_overlap.update(stationary)
        
        # Genuine scrollbar observer evaluation - never hardcode idx == 0 or idx == len - 1
        obs_state = k.get("scroll_state") or "MIDDLE"
        top_proof = {
            "trusted": True,
            "proofId": f"top_{k_desc['evidenceId']}",
        } if obs_state == "TOP" else None

        bottom_proof = {
            "trusted": True,
            "proofId": f"bottom_{k_desc['evidenceId']}",
        } if obs_state == "BOTTOM" else None
        
        ledger.add_segment(
            k_desc,
            sequence_index=idx,
            top_proof=top_proof,
            bottom_proof=bottom_proof,
            overlap_proof=ledger_overlap,
        )
        
        proc.accept_segment(
            k['frame'],
            k_desc,
            sequence_index=idx,
            observer_result={"scrollState": obs_state, "segmentChange": "CHANGED"},
            overlap_proof=recon_overlap,
            already_cropped=False,
        )
        
        prev_k = k
        prev_k_desc = k_desc

    # Ledger finalize will compute whether the path is truly COMPLETE based on observer endpoints and overlaps
    ledger_snap = ledger.finalize("COMPLETE")
    cov_status = ledger_snap.get("coverageStatus")
    term_reason = ledger_snap.get("terminationReason")
    print(f"\nLedger coverageStatus: {cov_status} (terminationReason={term_reason})", flush=True)

    proc_snap = proc.finalize(ledger_snap)
    packet = proc.packet_copy()
    if packet:
        (out_dir / "audit_review_packet.json").write_text(json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8")
    units = packet.get("reviewUnits", []) if packet else []

    print(f"Reconstructed Review Units count: {len(units)}", flush=True)

    # -------------------------------------------------------------
    # Part 3: Spatial Screen-by-Screen Item Audit against Ground Truth
    # -------------------------------------------------------------
    ref_path = ROOT / "assets" / "items" / "video_ground_truth_reference_144037.json"
    has_ground_truth = ref_path.is_file()

    gt_items = []
    if has_ground_truth:
        ref_json = json.loads(ref_path.read_text(encoding="utf-8"))
        gt_items = ref_json.get("items") or []

    # Map predicted units to their cell footprints
    pred_unit_records = []
    for u in units:
        uid = u.get("reviewUnitId")
        wa = u.get("worldAnchor") or {}
        r = wa.get("row")
        c = wa.get("col")
        footprint = u.get("footprint") or {}
        pw = int(footprint.get("widthCells") or 1)
        ph = int(footprint.get("heightCells") or 1)
        shape = f"{pw}x{ph}"

        cands = u.get("candidates") or []
        cells = set((r + kr, c + kc) for kr in range(ph) for kc in range(pw)) if (r is not None and c is not None) else set()
        
        pred_unit_records.append({
            'unitId': uid,
            'anchor': {'row': r, 'col': c},
            'shape': shape,
            'w': pw,
            'h': ph,
            'cells': cells,
            'candidates': cands,
            'hasCandidates': len(cands) > 0,
            'observationsCount': len(u.get("observations") or []),
            'topCandidate': cands[0] if cands else None,
        })

    # Metric: units with candidates vs units without candidates
    units_with_candidates = sum(1 for p in pred_unit_records if p['hasCandidates'])
    units_without_candidates = sum(1 for p in pred_unit_records if not p['hasCandidates'])

    if not has_ground_truth:
        print("WARNING: Ground truth reference not found. Quality audit marked NOT_VERIFIED.")
        item_audit = {
            'ground_truth_status': 'NOT_VERIFIED',
            'total_predicted_units': len(units),
            'units_with_candidates': units_with_candidates,
            'units_without_candidates': units_without_candidates,
            'missing_items_ground_truth': None,
            'false_merges_detected': None,
            'false_splits_detected': None,
            'empty_area_false_positives': None,
            'one_to_one_matched': None,
            'recognition_quality_status': 'NOT_VERIFIED',
        }
    else:
        # Prepare GT cells and empty area cells
        gt_item_records = []
        all_gt_cells = set()
        for g in gt_items:
            validate_catalog_record(g)
            gid = g.get("referenceId")
            bb = g.get("gridBoundingBox") or {}
            gr, gc = bb.get("row", 0), bb.get("col", 0)
            gw, gh = bb.get("width", 1), bb.get("height", 1)
            g_cells = set((gr + kr, gc + kc) for kr in range(gh) for kc in range(gw))
            all_gt_cells.update(g_cells)
            gt_item_records.append({
                'referenceId': gid,
                'gridBoundingBox': bb,
                'cells': g_cells,
                'quality': g.get("quality"),
                'desc': g.get("visualDescription"),
            })

        confirmed_empty_cells = set(
            (r, c) for r in range(25) for c in range(10) if (r, c) not in all_gt_cells
        )

        # 1. Detect predicted items falling into confirmed empty area (False Positives)
        empty_area_false_positives = []
        for p in pred_unit_records:
            if not p['cells']:
                continue
            empty_overlap = p['cells'].intersection(confirmed_empty_cells)
            # If 50% or more of the unit's cells are confirmed empty
            if len(empty_overlap) >= 0.5 * len(p['cells']) or p['cells'].issubset(confirmed_empty_cells):
                empty_area_false_positives.append({
                    'unitId': p['unitId'],
                    'anchor': p['anchor'],
                    'shape': p['shape'],
                    'emptyOverlapCells': [list(c) for c in sorted(empty_overlap)],
                })

        # 2. Check overlap, union coverage, missed cells, and spurious cells for each GT item
        completely_missing = []
        partially_missing = []
        false_splits = []
        one_to_one_matches = []
        exact_boundary_matches = []
        boundary_deviations = []
        per_item_coverage_audit = {}

        for g in gt_item_records:
            gid = g['referenceId']
            g_cells = g['cells']
            g_count = len(g_cells)

            overlapping_preds = [
                p for p in pred_unit_records
                if len(g_cells.intersection(p['cells'])) > 0
            ]

            pred_union = set()
            for p in overlapping_preds:
                pred_union.update(p['cells'])

            covered_cells = g_cells.intersection(pred_union)
            missed_cells = g_cells - pred_union
            spurious_cells = pred_union - g_cells
            coverage_ratio = len(covered_cells) / max(1, g_count)

            item_detail = {
                'referenceId': gid,
                'gridBoundingBox': g['gridBoundingBox'],
                'desc': g['desc'],
                'totalCells': g_count,
                'coveredCellsCount': len(covered_cells),
                'missedCellsCount': len(missed_cells),
                'spuriousCellsCount': len(spurious_cells),
                'coverageRatio': round(coverage_ratio, 4),
                'missedCells': [list(c) for c in sorted(missed_cells)],
                'spuriousCells': [list(c) for c in sorted(spurious_cells)],
                'overlappingPredUnitsCount': len(overlapping_preds),
                'overlappingPredUnitIds': [p['unitId'] for p in overlapping_preds],
            }

            if len(overlapping_preds) == 0:
                item_detail['classification'] = 'COMPLETELY_MISSING'
                completely_missing.append(item_detail)
            else:
                if len(missed_cells) > 0:
                    partially_missing.append(item_detail)

                if len(overlapping_preds) > 1:
                    item_detail['classification'] = 'FALSE_SPLIT'
                    false_splits.append(item_detail)
                else:
                    p = overlapping_preds[0]
                    # Check 1-to-1 match IoU
                    intersection = len(g_cells.intersection(p['cells']))
                    union = len(g_cells.union(p['cells']))
                    iou = intersection / max(1, union)
                    item_detail['iou'] = round(iou, 4)
                    item_detail['matchedUnitId'] = p['unitId']

                    if g_cells == p['cells']:
                        item_detail['classification'] = 'EXACT_MATCH'
                        exact_boundary_matches.append(item_detail)
                        one_to_one_matches.append(item_detail)
                    else:
                        item_detail['classification'] = 'BOUNDARY_DEVIATION'
                        boundary_deviations.append(item_detail)
                        if iou >= 0.60:
                            one_to_one_matches.append(item_detail)

            per_item_coverage_audit[gid] = item_detail

        # 3. Check False Merges (multi-to-one: multiple GTs overlapping the same predicted unit)
        false_merges = []
        for p in pred_unit_records:
            overlapping_gts = [
                g for g in gt_item_records
                if len(g['cells'].intersection(p['cells'])) > 0
            ]
            if len(overlapping_gts) > 1:
                false_merges.append({
                    'unitId': p['unitId'],
                    'anchor': p['anchor'],
                    'shape': p['shape'],
                    'cells': [list(c) for c in sorted(p['cells'])],
                    'mergedReferenceIds': [g['referenceId'] for g in overlapping_gts],
                })

        # 4. Check Duplicates among predicted units (pairwise IoU >= 0.60)
        duplicates = []
        for i in range(len(pred_unit_records)):
            for j in range(i + 1, len(pred_unit_records)):
                p1, p2 = pred_unit_records[i], pred_unit_records[j]
                if not p1['cells'] or not p2['cells']:
                    continue
                inter = len(p1['cells'] & p2['cells'])
                if inter > 0:
                    u = len(p1['cells'] | p2['cells'])
                    iou = inter / u
                    if iou >= 0.60:
                        duplicates.append({
                            'unitId1': p1['unitId'],
                            'unitId2': p2['unitId'],
                            'iou': round(iou, 3),
                        })

        # Recognition Quality Pass Condition:
        # STRICT FAIL-CLOSED:
        # 1. Coverage is COMPLETE
        # 2. ZERO completely missing items
        # 3. ZERO partially missing items (all reference cells covered)
        # 4. ZERO false splits (no fragmented items)
        # 5. ZERO false merges (no merged items)
        # 6. ZERO empty area false positives
        # 7. ZERO duplicates
        # 8. All GT items matched one-to-one (one_to_one_matches == len(gt_items))
        has_quality_failures = (
            cov_status != "COMPLETE"
            or len(completely_missing) > 0
            or len(partially_missing) > 0
            or len(false_splits) > 0
            or len(false_merges) > 0
            or len(empty_area_false_positives) > 0
            or len(duplicates) > 0
            or len(one_to_one_matches) < len(gt_items)
        )
        quality_pass = not has_quality_failures

        for p in pred_unit_records:
            if p.get('topCandidate'):
                c = p['topCandidate']
                validate_item_identity(c.get('catalogId'), c.get('name'), c.get('identityStatus', 'CANDIDATE_ONLY'))

        total_missing = len(completely_missing) + len(partially_missing)
        item_audit = {
            'ground_truth_status': 'VERIFIED',
            'ground_truth_total_items': len(gt_items),
            'total_predicted_units': len(units),
            'units_with_candidates': units_with_candidates,
            'units_without_candidates': units_without_candidates,
            'completely_missing_count': len(completely_missing),
            'completely_missing_items': completely_missing,
            'partially_missing_count': len(partially_missing),
            'partially_missing_items': partially_missing,
            'missing_items_ground_truth': total_missing,
            'missing_items_details': completely_missing + partially_missing,
            'false_splits_detected': len(false_splits),
            'false_splits_details': false_splits,
            'false_merges_detected': len(false_merges),
            'false_merges_details': false_merges,
            'duplicates_detected': len(duplicates),
            'duplicates_details': duplicates,
            'boundary_deviations_detected': len(boundary_deviations),
            'boundary_deviations_details': boundary_deviations,
            'exact_boundary_matches_count': len(exact_boundary_matches),
            'exact_boundary_matches': exact_boundary_matches,
            'one_to_one_matches_count': len(one_to_one_matches),
            'one_to_one_matches': one_to_one_matches,
            'empty_area_false_positives': len(empty_area_false_positives),
            'empty_area_false_positives_details': empty_area_false_positives,
            'recognition_quality_status': "PASS" if quality_pass else "FAIL",
            'per_item_coverage_audit': per_item_coverage_audit,
            'units_list': [
                {
                    'unitId': p['unitId'],
                    'anchor': p['anchor'],
                    'shape': p['shape'],
                    'hasCandidates': p['hasCandidates'],
                    'topCandidate': (p['topCandidate'].get("name") or "待辨认") if p['topCandidate'] else None,
                    'observationsCount': p['observationsCount'],
                }
                for p in pred_unit_records
            ],
        }

    report = {
        'execution_status': "SUCCESS",
        'sparse_gaps_analysis': sparse_results,
        'total_keyframes': len(keyframes),
        'keyframe_alignments_verified': sum(1 for a in keyframe_alignments if a['status'] == STATUS_VERIFIED),
        'keyframe_alignments_total': len(keyframe_alignments),
        'reconstruction_coverage': cov_status,
        'coverage_termination_reason': term_reason,
        'item_audit': item_audit,
    }

    report_path = out_dir / "audit_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nAudit complete! Report written to: {report_path}", flush=True)
    print(f"Summary: Coverage={cov_status} | QualityStatus={item_audit.get('recognition_quality_status')} | GT={item_audit.get('ground_truth_total_items')} | PredUnits={item_audit.get('total_predicted_units')} | EmptyFPs={item_audit.get('empty_area_false_positives')}", flush=True)

    # Write audit provenance
    import datetime, subprocess, hashlib
    manifest_path = ROOT / "assets" / "items" / "catalog_reference_manifest_v2.json"
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path.is_file() else None
    packet_path = out_dir / "audit_review_packet.json"
    packet_sha = hashlib.sha256(packet_path.read_bytes()).hexdigest() if packet_path.is_file() else None
    report_sha = hashlib.sha256(report_path.read_bytes()).hexdigest()
    try:
        git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True, encoding="utf-8", errors="replace", check=True).stdout.strip()
        status_out = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT), capture_output=True, encoding="utf-8", errors="replace", check=True).stdout
        diff_out = subprocess.run(["git", "diff", "HEAD"], cwd=str(ROOT), capture_output=True, encoding="utf-8", errors="replace", check=True).stdout
        is_dirty = bool(status_out.strip())
        diff_sha = hashlib.sha256(diff_out.encode("utf-8")).hexdigest() if is_dirty else None
    except Exception:
        git_commit = "UNKNOWN"
        is_dirty = None
        diff_sha = None

    prov = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsedSeconds": round(time.time() - t_start, 2),
        "gitCommit": git_commit,
        "workingTreeDirty": is_dirty,
        "workingTreeDiffSha256": diff_sha,
        "videoPath": str(video_path),
        "videoByteSize": video_path.stat().st_size if video_path.is_file() else 0,
        "manifestPath": str(manifest_path.relative_to(ROOT)) if manifest_path.is_file() else None,
        "manifestSha256": manifest_sha,
        "outputDirectory": str(out_dir.relative_to(ROOT)),
        "auditReviewPacketSha256": packet_sha,
        "auditReportSha256": report_sha,
        "itemAuditSummary": {
            "groundTruthTotal": item_audit.get("ground_truth_total_items", 0),
            "predictedUnitsTotal": item_audit.get("total_predicted_units", 0),
            "unitsWithCandidates": item_audit.get("units_with_candidates", 0),
            "unitsWithoutCandidates": item_audit.get("units_without_candidates", 0),
            "recognitionQualityStatus": item_audit.get("recognition_quality_status", "UNKNOWN"),
            "exactBoundaryMatches": item_audit.get("exact_boundary_matches_count", 0),
        }
    }
    (out_dir / "audit_provenance_20260911.json").write_text(json.dumps(prov, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run dense audit on warehouse scroll video.")
    parser.add_argument("--video", type=str, default=r"D:\yihuanpaimai\data\videos\2026-09-08 14-40-37.mkv", help="Path to video file")
    parser.add_argument("--out-dir", type=str, default=r"build\diagnosis_20260911\p3-warehouse\video_audit_retest_v2", help="Path to output directory")
    args = parser.parse_args()

    v_path = Path(args.video)
    o_dir = Path(args.out_dir) if Path(args.out_dir).is_absolute() else (ROOT / args.out_dir)
    run_dense_audit(v_path, o_dir)
