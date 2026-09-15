"""Profile real sequential recognition without changing production OCR results."""
import argparse
import cProfile
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import pstats
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'core'), str(ROOT/'app')]


def run(args):
    assert 0 <= args.start < args.end
    import cv2
    from keyboard_auction_pipeline import KeyboardAuctionPipeline
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    pipe = KeyboardAuctionPipeline(); pipe.recognition_mode_provider = lambda: 'auto'
    pipe._ensure_ocr()
    cap = cv2.VideoCapture(str(args.video.resolve(strict=True)))
    report = {'scope': 'Continuous decode and scene routing; OCR once per video second; source pipeline only; not real-time UI latency', 'video': str(args.video.resolve()), 'start': args.start, 'end': args.end, 'frames': []}
    profiler = cProfile.Profile()
    try:
        assert cap.isOpened()
        fps = cap.get(cv2.CAP_PROP_FPS)
        assert fps > 0
        cap.set(cv2.CAP_PROP_POS_MSEC, args.start*1000)
        for i in range(round((args.end-args.start)*fps)):
            ok, frame = cap.read(); assert ok
            pipe._classify_scene_fast(frame)
            if (i+1) % round(fps): continue
            second = args.start+(i+1)/fps
            stamp = (datetime(2026,9,8,14,40,37)+timedelta(seconds=second)).isoformat()+'+08:00'
            started=time.perf_counter()
            profiler.enable()
            ctx=pipe.process_frame(frame,stamp,False,'continuous-profile-144037',False)
            profiler.disable()
            report['frames'].append({'second':second,'elapsedSeconds':time.perf_counter()-started,
                'sha256':hashlib.sha256(frame.tobytes()).hexdigest(),'scene':ctx.get('scene'),
                'acquired':ctx.get('isAcquired'),'settlement':ctx.get('settlementData')})
            (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        report['completed']=True
    finally:
        profiler.disable(); cap.release(); pipe._navigation_executor.shutdown(wait=True)
        profiler.dump_stats(str(out/'recognition.prof'))
        with (out/'profile.txt').open('w',encoding='utf-8') as stream:
            pstats.Stats(profiler,stream=stream).strip_dirs().sort_stats('cumulative').print_stats(45)
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--start',type=int,required=True)
    parser.add_argument('--end',type=int,required=True)
    run(parser.parse_args())
