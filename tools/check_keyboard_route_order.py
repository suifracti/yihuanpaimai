"""Check shuffled navigation against the supplied real reference frames."""
import sys,json,random
from pathlib import Path
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'core'))
from scene_roi_router import create_keyboard_router

def main():
    folder=ROOT/'build/diagnosis_20260908_sessions/keyboard'
    cases={'OPEN_WORLD':folder/'2026-09-08 14-40-37-200.jpg',
           'CITY_LEISURE_MENU':folder/'detail-024.jpg','AUCTION_LOBBY':folder/'detail-028.jpg',
           'TOOL_REPLENISH':folder/'detail-194.jpg','TOOL_REPLENISH_CONFIRM':folder/'detail-196.jpg',
           'HELPER_SELECTION':folder/'detail-062.jpg','AUCTION_LOADING':folder/'2026-09-08 14-40-37-075.jpg',
           'IN_AUCTION':folder/'2026-09-08 14-40-37-150.jpg','SETTLEMENT':folder/'2026-09-08 14-40-37-165.jpg',
           'CITY_TYCOON_HUB':Path('C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-583e451b-f71b-4f77-8dd1-8412d838a17e.png'),
           'WORLD_MAP':Path('C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-01a9503c-0a89-492d-90f1-b215d2d863ae.png')}
    cases['OPEN_WORLD']=folder/'detail-200.jpg'
    router=create_keyboard_router();order=list(cases)*3;random.Random(908).shuffle(order);results=[]
    for scene in order:
        frame=cv2.imdecode(np.fromfile(cases[scene],np.uint8),1)
        for n in range(len(cases)+4):
            result=router.observe(frame.copy())
            if result['confirmed']:break
        results.append({'expected':scene,'actual':result['scene'],'frames':n+1})
    (folder/'shuffled-routes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    assert all(r['actual']==r['expected'] for r in results),results
    print('PASS',len(results),'shuffled real-frame transitions; max recovery',max(r['frames'] for r in results))

if __name__=='__main__':main()
