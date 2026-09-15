"""Compare CPU OCR thread counts on identical production crops in fresh processes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))


def run(args):
    import cv2
    from rapidocr_onnxruntime import RapidOCR
    from roi_scaler import ROIScaler
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(args.video))
    crops = []
    try:
        for second, kind in [(110, 'seats'), (162, 'settlement')]:
            cap.set(cv2.CAP_PROP_POS_MSEC, (second - 1) * 1000)
            for _ in range(30):
                ok, frame = cap.read()
                assert ok
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = ROIScaler.scale_roi('seats_bids_panel', w, h) if kind == 'seats' else (0, 0, int(w*.65), h)
            crops.append((kind, frame[y1:y2, x1:x2]))
    finally:
        cap.release()
    started = time.monotonic()
    engine = RapidOCR() if args.threads == -1 else RapidOCR(intra_op_num_threads=args.threads, inter_op_num_threads=1)
    report = {'threads': args.threads, 'initializationSeconds': time.monotonic()-started, 'samples': []}
    for kind, crop in crops:
        for repeat in range(3):
            started = time.monotonic()
            result, timing = engine(crop)
            report['samples'].append({'kind': kind, 'repeat': repeat, 'elapsedSeconds': time.monotonic()-started,
                'cropSha256': hashlib.sha256(crop.tobytes()).hexdigest(), 'timing': timing,
                'rows': [{'box': box, 'text': text, 'confidence': score} for box, text, score in result or []]})
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--threads', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
