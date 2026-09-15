"""Offline candidate comparison; does not change production recognition."""
import cv2, json, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from vision_pipeline import NTEVisionPipeline
from roi_scaler import ROIScaler
from bid_glyph_crop import compact_bid_glyph

if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--video',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 args.output.mkdir(parents=True,exist_ok=False)
 pipe=NTEVisionPipeline();pipe._ensure_ocr();cap=cv2.VideoCapture(str(args.video));rows=[]
 try:
  for second in range(108,118):
   cap.set(cv2.CAP_PROP_POS_MSEC,second*1000);ok,frame=cap.read();assert ok
   original=pipe._run_df_seat_bids_shadow(frame)
   for slot in range(1,5):
    crop=ROIScaler.crop_roi(frame,f'seat_current_bid_{slot}');candidate=compact_bid_glyph(crop)
    row={'second':second,'slot':slot,'original':original[slot-1],'candidate':None}
    if candidate is not None:
     start=time.perf_counter();result,_=pipe._ocr_engine.text_rec([candidate]);row.update(candidate=result,elapsed=time.perf_counter()-start)
     cv2.imwrite(str(args.output/f'{second}-{slot}.png'),crop)
    rows.append(row)
 finally:
  cap.release();(args.output/'report.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps([r for r in rows if r['candidate'] is not None],ensure_ascii=False))
