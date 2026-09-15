"""Replay explicit video frames through production warehouse reconstruction.

Configuration supplies a video, match key, sample times and optional gameBbox
(x1,y1,x2,y2). It supplies no identities, geometry answers or coverage claims.
Outputs are isolated evidence and review packets; user History is never opened.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'core')]

import cv2
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from warehouse_auto_confirmation import evaluate_auto_confirmation
from warehouse_catalog_geometry import CatalogGeometryIndex
from warehouse_coverage_ledger import WarehouseCoverageLedger
from warehouse_placement_resolver import WarehousePlacementResolver
from warehouse_reconstruction import WarehouseReconstructionProcessor
from warehouse_scrollbar_observation import WarehouseScrollbarObserver, warehouse_search_roi
from warehouse_segment_overlap import align_warehouse_segments
from warehouse_support_frame import stationary_support_proof


def replay(config, output):
    times = config['sampleTimesSec']
    if not times or any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0 for t in times):
        raise ValueError('Sample times must be finite nonnegative numbers')
    if times != sorted(set(times)):
        raise ValueError('Sample times must be strictly increasing')
    if output.exists():
        raise ValueError('Use a fresh output directory')
    video = Path(config['videoPath']).resolve(strict=True)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError('Video cannot be opened')
    fps = cap.get(cv2.CAP_PROP_FPS)
    count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if fps <= 0 or times[-1] >= count / fps:
        cap.release()
        raise ValueError('Sample outside video duration')
    output.mkdir(parents=True)
    started = time.monotonic()
    key = config['recordStableKey']
    store = SettlementEvidenceStoreV2(output / 'store')
    ledger = WarehouseCoverageLedger(key)
    observer = WarehouseScrollbarObserver()
    catalog = json.loads((ROOT / 'assets/catalog_065.json').read_text(encoding='utf-8'))
    processor = WarehouseReconstructionProcessor(key, catalog_index=CatalogGeometryIndex(catalog),
        placement_resolver=WarehousePlacementResolver())
    samples, descriptors, seen = [], [], set()
    previous = None
    try:
        for timestamp in times:
            cap.set(cv2.CAP_PROP_POS_FRAMES, round(timestamp * fps))
            ok, source = cap.read()
            if not ok:
                raise ValueError(f'Frame unavailable at {timestamp}')
            frame = source
            bbox = config.get('gameBbox')
            if bbox is not None:
                if len(bbox) != 4 or any(type(v) is not int for v in bbox):
                    raise ValueError('gameBbox must contain four integers')
                x1, y1, x2, y2 = bbox
                if not 0 <= x1 < x2 <= source.shape[1] or not 0 <= y1 < y2 <= source.shape[0]:
                    raise ValueError('gameBbox outside original frame')
                frame = source[y1:y2, x1:x2].copy()
            payload = cv2.imencode('.png', frame)[1].tobytes()
            digest = hashlib.sha256(payload).hexdigest()
            sample = {'timeSec': timestamp, 'decodedFrameIndex': int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1,
                'gameBbox': bbox, 'sha256': digest}
            samples.append(sample)
            if digest in seen:
                sample['accepted'] = False
                sample['reason'] = 'DUPLICATE_IMAGE'
                continue
            observation = observer.observe(frame, source_id=digest)
            state = observation.get('scrollState')
            sample['observation'] = observation
            if state not in {'TOP', 'MIDDLE', 'BOTTOM', 'NO_SCROLL'}:
                sample['accepted'] = False
                sample['reason'] = 'OBSERVER_UNKNOWN'
                break
            seen.add(digest)
            if not descriptors:
                store.save_original(record_stable_key=key, kind='main-settlement', image_bytes=payload)
            descriptor = store.save_original(record_stable_key=key, kind='warehouse-segment', image_bytes=payload)
            x1, y1, x2, y2 = warehouse_search_roi(frame.shape[1], frame.shape[0])
            roi = frame[y1:y2, x1:x2]
            overlap, reconstruction_overlap = None, None
            if previous:
                previous_roi, previous_descriptor = previous
                proof = stationary_support_proof(previous_roi, roi)
                if proof is None:
                    alignment = align_warehouse_segments(previous_roi, roi,
                        prev_id=previous_descriptor['evidenceId'], next_id=descriptor['evidenceId'], required_direction='DOWN')
                    sample['alignment'] = alignment
                    if alignment.get('status') == 'VERIFIED' and alignment.get('direction') == 'DOWN':
                        proof = alignment
                if proof is not None:
                    overlap = {'trusted': True, 'aligned': True,
                        'previousEvidenceId': previous_descriptor['evidenceId'],
                        'proofId': proof.get('proofId') or f"overlap:{previous_descriptor['sha256']}:{digest}"}
                    reconstruction_overlap = {**proof, **overlap}
            top = {'trusted': True, 'proofId': f'top:{digest}'} if state in {'TOP', 'NO_SCROLL'} else None
            bottom = {'trusted': True, 'proofId': f'bottom:{digest}'} if state in {'BOTTOM', 'NO_SCROLL'} else None
            ledger.add_segment(descriptor, sequence_index=len(descriptors), top_proof=top,
                bottom_proof=bottom, overlap_proof=overlap)
            accepted = processor.accept_segment(frame, descriptor, len(descriptors), observation,
                reconstruction_overlap, already_cropped=False)
            descriptors.append(descriptor)
            sample.update({'accepted': bool(accepted.get('accepted')), 'reconstruction': accepted})
            previous = roi.copy(), descriptor
            print(f"Frame {timestamp}: {state}, linked={overlap is not None}", flush=True)
    finally:
        cap.release()
    # The real ledger, rather than an expected item count, proves completeness.
    coverage = ledger.finalize('COMPLETE')
    print(f"Coverage {coverage['coverageStatus']}; resolving recorded evidence", flush=True)
    processor.finalize(coverage)
    packet = processor.packet_copy()
    if not packet:
        raise ValueError('No review packet produced')
    evaluated = evaluate_auto_confirmation(packet['reviewUnits'], packet['segments'])
    summary = {'config': config, 'coverage': coverage, 'samples': samples, 'unitCount': len(evaluated),
        'confirmedCount': sum(u.get('confirmationStatus') == 'CONFIRMED' for u in evaluated),
        'seconds': time.monotonic() - started, 'truthUsedDuringRecognition': False}
    for name, data in [('review_packet.json', packet), ('evaluated_units.json', evaluated), ('report.json', summary)]:
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ['unitCount', 'confirmedCount', 'seconds']}, ensure_ascii=False), flush=True)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    replay(json.loads(args.config.read_text(encoding='utf-8')), args.out_dir.resolve())
