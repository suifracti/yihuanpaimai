"""Read-only replay of the user's September 8 recordings."""
import json
from pathlib import Path
import sys
import time
import cv2
import numpy as np
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root/'core'),str(root/'app')]
from snapshot_recognizer import SingleFrameSnapshotRecognizer
from scene_anchors import settlement_title_visible
from warehouse_grid_geometry import observe_warehouse_grid
from warehouse_scrollbar_observation import observe_warehouse_scrollbar

folder = root/'build/diagnosis_20260908_sessions'
recognizer = SingleFrameSnapshotRecognizer(focused=True, include_card_evidence=False)
results = []
for filename, second, settle in [('2026-09-08 13-40-43',90,False),('2026-09-08 13-40-43',150,True),('2026-09-08 13-44-36',270,True),('2026-09-08 13-44-36',570,True)]:
    path = folder/f'{filename}-{second:03d}.jpg'
    frame = cv2.imdecode(np.fromfile(path,np.uint8),1)
    started = time.perf_counter()
    if settle:
        result = {'settlement':settlement_title_visible(frame), 'grid':observe_warehouse_grid(frame, already_cropped=False), 'scroll':observe_warehouse_scrollbar(frame, already_cropped=False)}
    else:
        result = recognizer.process_frame(frame)
    results.append({'frame':str(path),'seconds':time.perf_counter()-started,'result':result})
    print(json.dumps(results[-1],ensure_ascii=False,default=str),flush=True)
(folder/'focused-replay.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
