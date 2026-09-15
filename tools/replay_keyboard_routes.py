"""Read-only scene routing replay, without input hints or game data writes."""
import sys, json, time
from pathlib import Path
import cv2
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'core'))
from scene_roi_router import create_keyboard_router

def main():
    video=Path(sys.argv[1]); out=Path(sys.argv[2]); router=create_keyboard_router()
    cap=cv2.VideoCapture(str(video)); fps=cap.get(cv2.CAP_PROP_FPS)
    step=max(1,round(fps/30)); n=0; rows=[]; last=None
    while True:
        ok=cap.grab()
        if not ok: break
        if n%step==0:
            ok,frame=cap.retrieve()
            if ok:
                r=router.observe(frame)
                if r['scene'] != last:
                    rows.append({'seconds':round(n/fps,3),**r});last=r['scene']
        n+=1
    cap.release();out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([r for r in rows if r['confirmed']],ensure_ascii=True),flush=True)

if __name__=='__main__':main()
