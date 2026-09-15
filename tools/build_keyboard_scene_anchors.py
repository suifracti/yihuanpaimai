"""Extract only unannotated anchor interiors from user-provided references."""
import json
from pathlib import Path
import cv2
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
TEMP = Path('C:/Users/Administrator/AppData/Local/Temp')
OUT = ROOT/'assets/scene_anchors/keyboard'
SOURCES = {
    'world':'0beb004d-0486-49f3-9b10-870c7abba461',
    'city':'583e451b-f71b-4f77-8dd1-8412d838a17e',
    'leisure':'f2757656-f922-47e7-a188-d4809a7acf40',
    'lobby':'f3a47354-31b4-4e28-8248-4e0dd60414af',
    'map':'01a9503c-0a89-492d-90f1-b215d2d863ae',
}
GROUPS = {
    'OPEN_WORLD': [('world',[1504,79,1535,101],'gray'),('world',[1587,79,1618,101],'gray')],
    'CITY_TYCOON_HUB':[('city',[112,39,251,83],'gray')],
    'CITY_LEISURE_MENU':[('leisure',[406,137,650,196],'gray')],
    'WORLD_MAP':[('map',[61,923,156,1003],'gray'),('map',[1503,36,1555,82],'gray')],
    'AUCTION_LOBBY':[('lobby',[113,42,246,82],'gray'),('lobby',[887,49,980,79],'gray')],
    'IN_AUCTION':[('auction',[838,170,930,203],'gray'),('auction',[992,170,1026,203],'gray')],
    'SETTLEMENT':[('settlement',[78,145,329,203],'gray')],
    'AUCTION_LOADING':[('loading',[1480,937,1720,1040],'gray')],
    'TOOL_REPLENISH':[('restock',[48,137,162,179],'gray')],
    'TOOL_REPLENISH_CONFIRM':[('restock_confirm',[1050,495,1199,538],'gray')],
    'HELPER_SELECTION':[('helper',[215,106,430,149],'gray')],
}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    paths = {k:TEMP/f'codex-clipboard-{v}.png' for k,v in SOURCES.items()}
    paths['auction'] = ROOT/'build/diagnosis_20260908_sessions/2026-09-08 13-40-43-090.jpg'
    paths['settlement'] = ROOT/'build/diagnosis_20260908_sessions/2026-09-08 13-40-43-150.jpg'
    paths['loading'] = ROOT/'build/diagnosis_20260908_sessions/keyboard/2026-09-08 14-40-37-075.jpg'
    paths['restock'] = ROOT/'build/diagnosis_20260908_sessions/keyboard/detail-194.jpg'
    paths['helper'] = ROOT/'build/diagnosis_20260908_sessions/keyboard/detail-062.jpg'
    paths['restock_confirm'] = ROOT/'build/diagnosis_20260908_sessions/keyboard/detail-196.jpg'
    groups = {}
    for name, anchors in GROUPS.items():
        output = []
        for index,(source,rect,mode) in enumerate(anchors):
            image = cv2.imdecode(np.fromfile(paths[source],np.uint8),1)
            image = cv2.resize(image,(1920,1080))
            x1,y1,x2,y2 = rect
            filename = f'{name.lower()}-{index}.png'
            cv2.imencode('.png',image[y1:y2,x1:x2])[1].tofile(OUT/filename)
            output.append({'image':filename,'rect':rect,'mode':mode,'source':str(paths[source])})
        groups[name] = {'anchors':output,'threshold':.83}
        if name == 'TOOL_REPLENISH': groups[name]['padding'] = 48
        if name == 'AUCTION_LOADING': groups[name]['threshold'] = .74
    image=cv2.imdecode(np.fromfile(ROOT/'build/diagnosis_20260908_sessions/keyboard/detail-068.jpg',np.uint8),1)
    image=cv2.resize(image,(1920,1080))
    rect=[922,94,1008,121]
    cv2.imencode('.png',image[94:121,922:1008])[1].tofile(OUT/'matching-success.png')
    groups['AUCTION_LOBBY']['phaseAnchors']=[{'image':'matching-success.png','rect':rect,'phase':'MATCHING_SUCCESS'}]
    (OUT/'groups.json').write_text(json.dumps({'version':1,'referenceSize':[1920,1080],'groups':groups},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__ == '__main__':
    main()
