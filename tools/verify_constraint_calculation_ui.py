"""Inspect production calculation after actual field edits in an isolated app."""
import argparse,json,asyncio
from pathlib import Path
import websockets
from verify_p1_real_ui import WS,eval_main,eval_overlay,wait_overlay_payload,wait_main_match
from verify_p3_isolated_real_app_history import run_one_launch
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--executable',type=Path);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);data=out/'data';h=data/'history/异环拍卖数据.json';h.parent.mkdir(parents=True);h.write_text('{"schemaVersion":7,"records":[]}',encoding='utf-8');report={'status':'RUNNING'}
async def interact(_zip,_export):
 async with websockets.connect(WS) as ws:
  await eval_main(ws,"showView('match');true");await wait_main_match(ws,lambda d:bool(d.get('matchId')))
  await eval_overlay(ws,'document.getElementById("toggleBtn").click();document.getElementById("venueChip").click();[...document.querySelectorAll("#popoverList .popover-item")].find(e=>e.textContent.includes("珊瑚")).click();true')
  await wait_overlay_payload(ws,lambda d:d.get('venueId')=='venue-shanhu')
  await eval_overlay(ws,'document.getElementById("boxChip").click();[...document.querySelectorAll("#popoverList .popover-item")].find(e=>e.textContent.includes("琉璃")).click();true')
  await wait_overlay_payload(ws,lambda d:d.get('boxId')=='box-shanhu-glass')
  fields={'q':'1','gold-avg':'60040','purple-count':'0','gold-count':'1','red-count':'0','blue-count':'1','green-count':'0','white-count':'0','blue-grid':'2'}
  await eval_main(ws,'(()=>{for(const [s,v] of Object.entries('+json.dumps(fields)+')){const e=document.getElementById("match-input-"+s);e.value=v;e.dispatchEvent(new Event("change",{bubbles:true}));}for(const [c,v] of [["gold","算力面包"],["blue","断落的剑柄"]]){const e=document.getElementById("match-input-known-"+c);e.value=v;e.dispatchEvent(new Event("change",{bubbles:true}));}return true})()')
  rows=[]
  cases=[('blueGrid',2,1),('blueCount',1,0),('blueAvg',2139,2140),('totalItems',2,1),('totalGrid',4,3),('goldGrid',2,1),('purpleGrid',0,1),('redGrid',0,1)]
  baseline={'blueGrid':2,'blueCount':1,'blueAvg':None,'totalItems':None,'totalGrid':None,'goldGrid':None,'purpleGrid':None,'redGrid':None}
  for key,value,conflict in [(key,value,phase==1) for key,good,bad in cases for phase,value in enumerate((good,bad,None))]:
   inputs={k+'Input':'' if v is None else str(v) for k,v in {**baseline,key:value}.items()}
   await eval_overlay(ws,'(()=>{let last;for(const [id,value] of Object.entries('+json.dumps(inputs)+')){const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event("input",{bubbles:true}));last=e;}last.dispatchEvent(new FocusEvent("blur"));return true})()')
   await wait_main_match(ws,lambda d:all(d.get('facts',{}).get(k)==v for k,v in {**baseline,key:value}.items()),timeout=20)
   expected_status='no-match' if conflict else 'valid'
   await wait_overlay_payload(ws,lambda d: all(d.get(k)==v for k,v in {**baseline,key:value}.items()) and not d.get('shadowUpdating') and ((d.get('predictionSnapshot') or d.get('solverInput',{}).get('predictionSnapshot') or {}).get('status') or {}).get('solverStatus')==expected_status,timeout=30)
   payload=await eval_overlay(ws,'JSON.stringify(manualState.latestNativePayload)')
   assert bool((payload.get('shadowStates') or payload.get('solverInput',{}).get('shadowStates') or {}).get('exact')) == (not conflict),payload.get('shadowStates')
   rows.append({'key':key,'value':value,'conflict':conflict,'payload':payload,'dom':await eval_overlay(ws,'JSON.stringify({action:document.getElementById("actionText").textContent,status:document.getElementById("statusHint").textContent})')})
   assert ('约束冲突' in rows[-1]['dom']['action']) == conflict,rows[-1]['dom']
   current=await wait_main_match(ws,lambda d:(d.get('prediction') or {}).get('solverStatus')==expected_status,timeout=20)
   main_dom=await eval_main(ws,'JSON.stringify({value:document.getElementById("match-live-p50").textContent,action:document.getElementById("match-live-action-badge").textContent,reason:document.getElementById("match-live-action-reason").textContent})')
   assert ('约束冲突' in main_dom['action'])==conflict,main_dom
   assert (main_dom['value']=='无可行解')==conflict,main_dom
   rows[-1]['main']=main_dom
   (out/'observations.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
  return rows
try:
 dual,rows,clean=run_one_launch('calculation',data,out/'app.log',out,interactor=interact,frozen_executable=a.executable);assert dual and clean;report.update(status='PASS',rows=rows)
except Exception as exc:report.update(status='FAIL',error=repr(exc));raise
finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
