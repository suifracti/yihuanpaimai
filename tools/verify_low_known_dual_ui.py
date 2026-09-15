"""Verify actual Main/HUD low known expressions in both directions."""
import argparse,json,asyncio
from pathlib import Path
import websockets
from verify_p1_real_ui import WS,eval_main,eval_overlay,wait_main_match,wait_overlay_payload
from verify_p3_isolated_real_app_history import run_one_launch
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--executable',type=Path);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
data=out/'data';history=data/'history/异环拍卖数据.json';history.parent.mkdir(parents=True);history.write_text('{"schemaVersion":7,"records":[]}',encoding='utf-8');report={'status':'RUNNING'}
async def interact(_zip,_export):
 async with websockets.connect(WS) as ws:
  await eval_main(ws,"showView('match');true")
  await eval_overlay(ws,'document.getElementById("toggleBtn").click();window.testErrors=[];window.addEventListener("error",e=>window.testErrors.push(e.message));true')
  state=await wait_main_match(ws,lambda d:bool(d.get('matchId')));mid=state['matchId'];rows=[]
  for color in ('blue','green','white'):
   key='known'+color.title();names=await eval_main(ws,'JSON.stringify(getCatalogItems('+json.dumps(color)+').slice(0,2).map(x=>x.name))')
   await eval_main(ws,'(()=>{const e=document.getElementById("match-input-known-'+color+'");e.value='+json.dumps(names[0])+';e.dispatchEvent(new Event("change",{bubbles:true}));return true})()')
   await wait_overlay_payload(ws,lambda d:d.get(key)==names[0])
   assert await eval_overlay(ws,'document.getElementById('+json.dumps(key+'Input')+').value')==names[0]
   for value in (names[0]+'/'+names[1]+'+'+names[0]+'*3',''):
    await eval_overlay(ws,'(()=>{const e=document.getElementById('+json.dumps(key+'Input')+');e.closest("details").open=true;e.focus();e.value='+json.dumps(value)+';e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new Event("change",{bubbles:true}));e.dispatchEvent(new FocusEvent("blur"));return true})()')
    debug=await eval_overlay(ws,'JSON.stringify({errors:window.testErrors,dirty:manualState.dirty,composing:manualState.isComposing,facts:collectFacts(),synced:manualState.lastSyncedFacts,validation:validateKnownExpression(document.getElementById("'+key+'Input").value,"'+color+'"),suppress:manualState.suppress})')
    (out/'debug.json').write_text(json.dumps(debug,ensure_ascii=False,indent=2),encoding='utf-8')
    state=await wait_main_match(ws,lambda d:d.get('facts',{}).get(key)==value,timeout=20);assert state['matchId']==mid
    assert await eval_main(ws,'serializeKnownChips('+json.dumps(color)+')')==value
    await wait_overlay_payload(ws,lambda d:d.get(key)==value)
    rows.append({'color':color,'value':value,'matchId':mid})
  return rows
try:
 dual,rows,clean=run_one_launch('dual-known',data,out/'app.log',out,interactor=interact,frozen_executable=a.executable);assert dual and clean
 report.update(status='PASS',rows=rows,cleanExit=clean)
except Exception as exc:report.update(status='FAIL',error=repr(exc));raise
finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
