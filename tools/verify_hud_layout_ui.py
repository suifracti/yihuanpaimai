"""Measure actual HUD content sizing and scrolling, and capture the rendered UI."""
import argparse,asyncio,json
from pathlib import Path
import websockets
from verify_p1_real_ui import WS,eval_overlay,recv_until
from verify_p3_isolated_real_app_history import run_one_launch
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--executable',type=Path);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);data=out/'data';h=data/'history/异环拍卖数据.json';h.parent.mkdir(parents=True);h.write_text('{"schemaVersion":7,"records":[]}',encoding='utf-8');report={'status':'RUNNING'}
async def interact(_zip,_export):
 async with websockets.connect(WS) as ws:
  rows=[]
  for phase in ('base','all-open','constrained','all-closed','collapsed'):
   if phase=='base':await eval_overlay(ws,'document.getElementById("toggleBtn").click();true')
   elif phase=='constrained':await eval_overlay(ws,'sendHost({action:"resize_hud",w:600,h:480});true')
   elif phase=='collapsed':await eval_overlay(ws,'document.getElementById("toggleBtn").click();true')
   else:await eval_overlay(ws,'document.querySelectorAll("#expandPane details").forEach(e=>e.open='+('true' if phase=='all-open' else 'false')+');true')
   await asyncio.sleep(.6)
   dims=await eval_overlay(ws,'JSON.stringify((()=>{const p=document.getElementById("expandPane");return {height:innerHeight,width:innerWidth,wanted:getExpandedHeight(),scrollHeight:p.scrollHeight,clientHeight:p.clientHeight,overflow:getComputedStyle(p).overflowY,screen:screen.availHeight}})())')
   hidden_visible=await eval_overlay(ws,'JSON.stringify([...document.querySelectorAll("[hidden]")].filter(e=>e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0).map(e=>e.id))');assert hidden_visible==[],hidden_visible
   if phase=='constrained':assert dims['height']==480 and dims['scrollHeight']>dims['clientHeight'],dims
   elif phase!='collapsed':assert abs(dims['height']-dims['wanted'])<=3,dims
   else:assert dims['height']==72,dims
   if phase in ('all-open','constrained'):
    if phase=='all-open':assert dims['height']>rows[0]['dims']['height'],dims
    assert dims['overflow']=='auto'
    visible=await eval_overlay(ws,'JSON.stringify((()=>{const p=document.getElementById("expandPane");p.scrollTop=p.scrollHeight;const b=p.lastElementChild.getBoundingClientRect();return {bottom:b.bottom,height:innerHeight,left:b.left,right:b.right,width:innerWidth}})())');assert visible['bottom']<=visible['height']+1 and visible['left']>=0 and visible['right']<=visible['width']+1,visible
    await eval_overlay(ws,'document.getElementById("expandPane").scrollTop=0;true')
    await ws.send(json.dumps({'type':'capture_overlay_preview','path':str(out/('expanded.png' if phase=='all-open' else 'constrained.png'))}));saved=await recv_until(ws,lambda r:r.get('type')=='overlay_preview_saved');assert saved.get('path')
   rows.append({'phase':phase,'dims':dims})
  assert abs(rows[0]['dims']['height']-rows[3]['dims']['height'])<=3,rows
  return rows
try:
 dual,rows,clean=run_one_launch('layout',data,out/'app.log',out,interactor=interact,frozen_executable=a.executable);assert dual and clean;report.update(status='PASS',rows=rows)
except Exception as exc:report.update(status='FAIL',error=repr(exc));raise
finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
