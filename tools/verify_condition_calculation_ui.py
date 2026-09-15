"""Inspect production calculation after actual field edits in an isolated app."""
import argparse,json,asyncio
from pathlib import Path
import websockets
from verify_p1_real_ui import WS,eval_main,eval_overlay,wait_overlay_payload,wait_main_match
from verify_p3_isolated_real_app_history import run_one_launch
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--executable',type=Path);p.add_argument('--purple',action='store_true');a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);data=out/'data';h=data/'history/异环拍卖数据.json';h.parent.mkdir(parents=True);h.write_text('{"schemaVersion":7,"records":[]}',encoding='utf-8');report={'status':'RUNNING'}
async def interact(_zip,_export):
 async with websockets.connect(WS) as ws:
  await eval_main(ws,"showView('match');true");await wait_main_match(ws,lambda d:bool(d.get('matchId')))
  await eval_overlay(ws,'document.getElementById("toggleBtn").click();document.getElementById("venueChip").click();[...document.querySelectorAll("#popoverList .popover-item")].find(e=>e.textContent.includes("珊瑚")).click();true')
  await wait_overlay_payload(ws,lambda d:d.get('venueId')=='venue-shanhu')
  await eval_overlay(ws,'document.getElementById("boxChip").click();[...document.querySelectorAll("#popoverList .popover-item")].find(e=>e.textContent.includes("琉璃")).click();true')
  await wait_overlay_payload(ws,lambda d:d.get('boxId')=='box-shanhu-glass')
  fields={'q':'1','gold-avg':'60040','purple-count':'0','gold-count':'1','red-count':'0','blue-count':'1','green-count':'0','white-count':'0','blue-grid':'2'}
  await eval_main(ws,'(()=>{for(const [s,v] of Object.entries('+json.dumps(fields)+')){const e=document.getElementById("match-input-"+s);e.value=v;e.dispatchEvent(new Event("change",{bubbles:true}));}for(const [c,v] of [["gold","算力面包"],["blue","断落的剑柄"]]){const e=document.getElementById("match-input-known-"+c);e.value=v;e.dispatchEvent(new Event("change",{bubbles:true}));}return true})()')
  avg_key='goldAvg';input_id='match-input-gold-avg';base_avg=60040;double='goldDouble'
  if a.purple:
   item=await eval_main(ws,'JSON.stringify(getCatalogItems("purple")[0])')
   await eval_main(ws,'(()=>{for(const [id,value] of [["match-input-q","2"],["match-input-purple-count","1"],["match-input-known-purple",'+json.dumps(item['name'])+']]){const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event("change",{bubbles:true}));}return true})()')
   await wait_main_match(ws,lambda d:d.get('facts',{}).get('q')==2 and d.get('facts',{}).get('purpleCount')==1 and d.get('facts',{}).get('knownPurple')==item['name'])
   avg_key='purpleAvg';input_id='match-input-purple-avg';base_avg=item['price'];double='purpleDouble'
  rows=[]
  for condition,avg,conflict in [('standard',base_avg,False),(double,base_avg,True),(double,base_avg*2,False),('standard',base_avg*2,True),('standard',base_avg,False)]:
   await eval_overlay(ws,'(()=>{document.getElementById("fieldChip").click();const e=document.querySelector('+json.dumps('#popoverList .popover-item[data-val="'+condition+'"]')+');if(!e)throw Error("condition absent");e.click();return true})()')
   await wait_overlay_payload(ws,lambda d:d.get('fieldCondition')==condition)
   await eval_main(ws,'(()=>{const e=document.getElementById('+json.dumps(input_id)+');e.focus();e.value='+json.dumps(str(avg))+';e.dispatchEvent(new Event("change",{bubbles:true}));return true})()')
   expected_status='no-match' if conflict else 'valid'
   await wait_overlay_payload(ws,lambda d:d.get('fieldCondition')==condition and d.get(avg_key)==avg and not d.get('shadowUpdating') and ((d.get('predictionSnapshot') or d.get('solverInput',{}).get('predictionSnapshot') or {}).get('status') or {}).get('solverStatus')==expected_status,timeout=30)
   payload=await eval_overlay(ws,'JSON.stringify(manualState.latestNativePayload)')
   assert (payload['solverInput']['fieldCondition'] or 'standard')==condition
   assert bool((payload.get('shadowStates') or payload.get('solverInput',{}).get('shadowStates') or {}).get('exact'))== (not conflict)
   await wait_main_match(ws,lambda d:(d.get('prediction') or {}).get('solverStatus')==expected_status and d.get('facts',{}).get('fieldCondition')==condition and d.get('facts',{}).get(avg_key)==avg,timeout=20)
   dom=await eval_main(ws,'JSON.stringify({value:document.getElementById("match-live-p50").textContent,action:document.getElementById("match-live-action-badge").textContent})')
   hud=await eval_overlay(ws,'document.getElementById("actionText").textContent')
   assert ('约束冲突' in dom['action'])==conflict,dom
   assert ('约束冲突' in hud)==conflict,hud
   rows.append({'condition':condition,'avg':avg,'conflict':conflict,'payload':payload,'main':dom,'hud':hud})
   (out/'observations.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
  return rows
try:
 dual,rows,clean=run_one_launch('calculation',data,out/'app.log',out,interactor=interact,frozen_executable=a.executable);assert dual and clean;report.update(status='PASS',rows=rows)
except Exception as exc:report.update(status='FAIL',error=repr(exc));raise
finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
