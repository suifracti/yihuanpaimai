"""Fast visible inventory geometry; no catalog search or per-item OCR."""
import cv2
import numpy as np
from settlement_grid import settlement_grid_bounds, visible_card_rectangles

def observe_settlement_shapes(frame):
    x1,y1,x2,y2=settlement_grid_bounds(frame)
    crop=frame[y1:y2,x1:x2]
    if not crop.size:return []
    cw,ch=crop.shape[1]/10,crop.shape[0]/10
    rectangles=visible_card_rectangles(crop,cw,ch)
    slots=[]
    for row,col,width,height in rectangles:
        left,top,right,bottom=round(col*cw),round(row*ch),round((col+width)*cw),round((row+height)*ch)
        card=crop[top:bottom,left:right]
        if not card.size:continue
        pad=max(2,round(min(cw,ch)*.1));inset=max(1,round(min(cw,ch)*.035))
        ring=np.concatenate([card[inset:pad].reshape(-1,3),card[-pad:-inset].reshape(-1,3),
                             card[:,inset:pad].reshape(-1,3),card[:,-pad:-inset].reshape(-1,3)])
        hsv=cv2.cvtColor(ring.reshape(-1,1,3),cv2.COLOR_BGR2HSV).reshape(-1,3)
        h,s,v=hsv[:,0],hsv[:,1],hsv[:,2]
        masks={'gold':(h>=8)&(h<=32)&(s>=45)&(v>=45),
               'purple':(h>=120)&(h<=165)&(s>=35)&(v>=35),
               'blue':(h>=88)&(h<=125)&(s>=40)&(v>=40),
               'green':(h>=35)&(h<=85)&(s>=40)&(v>=40),
               'red':((h<=8)|(h>=168))&(s>=50)&(v>=50),'white':(s<=35)&(v>=85)}
        scores={name:float(mask.mean()) for name,mask in masks.items()}
        rarity=max(scores,key=scores.get)
        slots.append({'col':col,'row':row,'w':width,'h':height,'rarity':rarity if scores[rarity]>=.12 else 'unknown',
                      'box':[x1+left,y1+top,right-left,bottom-top], 'identityStatus':'UNKNOWN',
                      'identifiedName':None,'evidenceLevel':'RARITY_AND_SHAPE'})
    return slots
