"""Read existing images once per case; write isolated offline diagnostic evidence.

The manifest contains independent visual expectations, never recognizer answers.
Reserved cases are not passed to recognition. A still image never supplies four
temporal observations. No application, capture, history or label store is opened.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iou(a, b):
    x, y, w, h = a
    u, v, s, t = b
    intersection = max(0, min(x + w, u + s) - max(x, u)) * max(0, min(y + h, v + t) - max(y, v))
    return intersection / max(1, w * h + s * t - intersection)


def associated(expected_box, actual_box):
    # A fragment enclosed by a known object is a segmentation error, even
    # when its IoU is small. It is not a false detection in an empty cell.
    x, y, w, h = expected_box
    u, v, s, t = actual_box
    return iou(expected_box, actual_box) >= 0.15 or (x <= u + s / 2 <= x + w and y <= v + t / 2 <= y + h)


def classify(record):
    expected = record.get('expectedSlots')
    if expected is None or 'actual' not in record:
        return []
    scale = float(record.get('scale', 1))
    actual = record['actual']
    issues = []
    for target in expected:
        box = [v * scale for v in target['sourceBoxXYWH']]
        hits = [s for s in actual['slots'] if associated(box, s['box'])]
        if not hits:
            issues.append({'group': '漏检', 'expected': target, 'actual': []})
        elif len(hits) != 1 or iou(box, hits[0]['box']) < 0.8 or [hits[0]['w'], hits[0]['h']] != target['sizeCells']:
            issues.append({'group': '定位偏差', 'expected': target, 'actual': hits})
        elif target.get('rarity') and hits[0]['rarity'] != target['rarity']:
            issues.append({'group': '品质偏差', 'expected': target, 'actual': hits})
    if record.get('exhaustiveVisibleSlots'):
        for slot in actual['slots']:
            if not any(associated([v * scale for v in t['sourceBoxXYWH']], slot['box']) for t in expected):
                issues.append({'group': '误检', 'expected': 'No visible item or quality block here', 'actual': slot})
    return issues


def run(args):
    source_root = args.source_root.resolve(strict=True)
    algorithm_root = args.algorithm_root.resolve(strict=True)
    output = args.output.resolve()
    output.relative_to(source_root / 'build')
    if output.exists():
        raise ValueError('Use a fresh evidence directory; prior results are immutable')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    cases = manifest['cases']
    if args.case:
        wanted = set(args.case)
        if wanted - {case['id'] for case in cases}:
            raise ValueError('Unknown case ID')
        cases = [case for case in cases if case['id'] in wanted]
    sys.path.insert(0, str(algorithm_root / 'core'))
    import cv2
    import numpy as np
    from warehouse_vision import WarehouseVisionV1
    from roi_scaler import NORMALIZED_ROIS
    from warehouse_scrollbar_observation import WarehouseScrollbarObserver

    output.mkdir(parents=True)
    baseline = {name: digest(algorithm_root / name) for name in [
        'core/warehouse_vision.py', 'core/warehouse_scrollbar_observation.py',
        'core/roi_scaler.py', 'core/visual_catalog.py', 'assets/catalog_065.json']}
    vision = None
    records = []
    for case in cases:
        source = source_root / case['source']
        record = {**case, 'sourceFileSha256': digest(source)}
        if case['role'] == 'RESERVED_VALIDATION' and not args.allow_reserved:
            record['recognitionStatus'] = 'NOT_RUN_RESERVED'
            records.append(record)
            continue
        if case['scene'] != 'IN_AUCTION' and not args.diagnose_wrong_scene:
            record.update(recognitionStatus='SKIPPED_WRONG_SCENE',
                          reason='Offline case scene is independently indexed; this entry only accepts IN_AUCTION',
                          recognitionInvoked=False)
            records.append(record)
            continue
        image = cv2.imdecode(np.fromfile(str(source), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f'Unreadable source: {source}')
        original_h, original_w = image.shape[:2]
        scale = float(case.get('scale', 1))
        if scale != 1:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if case.get('cropRightPx'):
            image = image[:, :-int(case['cropRightPx'])]
        # A cropped ROI retains the original board location rather than
        # re-normalizing the whole scene into the narrowed image dimensions.
        h, w = image.shape[:2]
        roi = NORMALIZED_ROIS['warehouse_board']
        x1, y1 = int(original_w * scale * roi[0]), int(original_h * scale * roi[1])
        x2 = min(w, math.ceil(original_w * scale * roi[2]))
        y2 = min(h, math.ceil(original_h * scale * roi[3]))
        normalized = (x1 / w, y1 / h, x2 / w, y2 / h)
        if vision is None:
            vision = WarehouseVisionV1()
        vision.reset()
        started = time.perf_counter()
        actual = vision.process_frame(image, grid_roi_norm=normalized)
        elapsed = time.perf_counter() - started
        record.update(recognitionStatus='SINGLE_FRAME_BASELINE', elapsedSeconds=elapsed,
                      sourceSizeWH=[original_w, original_h], inputSizeWH=[w, h],
                      boardCropXYXY=[x1, y1, x2, y2], actual=actual,
                      observer=WarehouseScrollbarObserver().observe(image), issues=[])
        expected = case.get('expectedSlots')
        record['issues'] = classify(record)
        # Names and quantities remain unknown without independent evidence.
        record['identityEvaluation'] = 'NOT_SCORED_NO_INDEPENDENT_NAMES_OR_SINGLE_FRAME_GATE'
        record['quantityEvaluation'] = 'UNKNOWN_NO_VERIFIED_STACK_DIGITS'
        overlay = image.copy()
        for target in expected or []:
            x, y, bw, bh = [round(v * scale) for v in target['sourceBoxXYWH']]
            cv2.rectangle(overlay, (x, y), (x + bw, y + bh), (0, 220, 0), 2)
        for slot in actual['slots']:
            x, y, bw, bh = slot['box']
            cv2.rectangle(overlay, (x, y), (x + bw, y + bh), (0, 0, 255), 1)
            cv2.putText(overlay, f"{slot['trackId']}:{slot['size']}:{slot['rarity']}",
                        (x + 2, max(12, y + 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
        board_name = case['id'] + '-board.png'
        overlay_name = case['id'] + '-overlay.png'
        (output / board_name).write_bytes(cv2.imencode('.png', image[y1:y2, x1:x2])[1].tobytes())
        (output / overlay_name).write_bytes(cv2.imencode('.png', overlay[max(0, y1-8):min(h, y2+8), max(0, x1-8):min(w, x2+8)])[1].tobytes())
        record.update(boardImage=board_name, overlayImage=overlay_name)
        records.append(record)
        print(json.dumps({'id': case['id'], 'scene': case['scene'], 'slots': actual['totalSlots'],
                          'grid': actual.get('grid'), 'issues': [v['group'] for v in record['issues']]}, ensure_ascii=False), flush=True)
    # Source changes during evaluation invalidate the baseline; never claim success.
    unchanged = all(digest(algorithm_root / name) == value for name, value in baseline.items())
    result = dict(schema='offline-right-warehouse-diagnostic-v1', sourceRoot=str(source_root),
                  algorithmRoot=str(algorithm_root), algorithmHashes=baseline, sourceUnchanged=unchanged,
                  evaluationLabel=args.evaluation_label,
                  originalManifest=manifest, cases=records, liveCaptureUsed=False,
                  formalHistoryTouched=False, formalLabelsTouched=False,
                  temporalEvidence='Each recognized input was processed once after reset',
                  independentAccuracyClaim=False)
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if not unchanged:
        raise RuntimeError('Shared algorithm changed during evaluation; evidence is unpinned')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--algorithm-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review-existing', type=Path,
                        help='Reclassify existing raw results without importing or running recognition')
    parser.add_argument('--case', action='append', help='Only evaluate these case IDs')
    parser.add_argument('--allow-reserved', action='store_true',
                        help='Evaluate reserved cases after freezing; repeat runs are not unseen validation')
    parser.add_argument('--evaluation-label', default='development',
                        help='Traceable run purpose, especially when repeating a former reserved case')
    parser.add_argument('--diagnose-wrong-scene', action='store_true',
                        help='Explicitly bypass offline scene admission for a raw-engine control')
    args = parser.parse_args()
    if args.review_existing:
        raw = json.loads(args.review_existing.read_text(encoding='utf-8'))
        output = args.output.resolve()
        output.relative_to(args.source_root.resolve() / 'build')
        if output.exists():
            raise ValueError('Use a fresh review output directory')
        output.mkdir(parents=True)
        reviewed = dict(rawResults=str(args.review_existing.resolve()), recognitionRerun=False,
                        reason='Enclosed item fragments belong to localization/segmentation, not empty-cell false positives',
                        cases=[dict(id=r['id'], issues=classify(r)) for r in raw['cases']])
        (output / 'reviewed-error-groups.json').write_text(
            json.dumps(reviewed, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        run(args)
