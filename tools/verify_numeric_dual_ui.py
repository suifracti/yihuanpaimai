"""Actual Main/HUD numeric roundtrip, including zero and clear."""
import argparse,json
from pathlib import Path
import websockets
from verify_p1_real_ui import WS,eval_main,eval_overlay,wait_main_match,wait_overlay_payload
from verify_p3_isolated_real_app_history import run_one_launch
from verify_advanced_fields_ui import FIELDS
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--executable',type=Path);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);data=out/'data';history=data/'history/异环拍卖数据.json';history.parent.mkdir(parents=True);history.write_text('{"schemaVersion":7,"records":[]}',encoding='utf-8');report={'status':'RUNNING'}
async def interact(_zip,_export):
 async with websockets.connect(WS) as ws:
  await eval_main(ws,"showView('match');true")
  state=await wait_main_match(ws,lambda d:bool(d.get('matchId')));mid=state['matchId']
  values={'match-input-'+slug:str(value) for slug,(key,value) in FIELDS.items()};expected={key:value for key,value in FIELDS.values()}
  await eval_main(ws,'(()=>{for(const [id,value] of Object.entries('+json.dumps(values)+')){const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event("change",{bubbles:true}));}return true})()')
  await wait_overlay_payload(ws,lambda d:all(d.get(k)==v for k,v in expected.items()))
  dom=await eval_overlay(ws,'JSON.stringify(Object.fromEntries('+json.dumps(list(expected))+'.map(k=>[k,document.getElementById(k+"Input").value])))');assert dom=={k:str(v) for k,v in expected.items()}
  rows=[{'direction':'Main to HUD','values':dom}]
  await eval_overlay(ws,'document.getElementById("toggleBtn").click();document.getElementById("extraNumericFields").open=true;true')
  for phase in ('edit','zero','clear'):
   target={k:None if phase=='clear' else 0 if phase=='zero' else v+1 for k,v in expected.items()}
   values={k+'Input':'' if v is None else str(v) for k,v in target.items()}
   await eval_overlay(ws,'(()=>{let last;for(const [id,value] of Object.entries('+json.dumps(values)+')){const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event("input",{bubbles:true}));last=e;}last.dispatchEvent(new FocusEvent("blur"));return true})()')
   state=await wait_main_match(ws,lambda d:all(d.get('facts',{}).get(k)==v for k,v in target.items()),timeout=20);assert state['matchId']==mid
   dom=await eval_main(ws,'JSON.stringify(Object.fromEntries('+json.dumps(list(FIELDS))+'.map(s=>[s,document.getElementById("match-input-"+s).value])))')
   assert dom=={slug:'' if target[key] is None else str(target[key]) for slug,(key,_) in FIELDS.items()},dom
   await wait_overlay_payload(ws,lambda d:all(d.get(k)==v for k,v in target.items()))
   rows.append({'direction':'HUD to Main','phase':phase,'values':dom})
  return rows
try:
 dual,rows,clean=run_one_launch('numeric-dual',data,out/'app.log',out,interactor=interact,frozen_executable=a.executable);assert dual and clean;report.update(status='PASS',rows=rows)
except Exception as exc:report.update(status='FAIL',error=repr(exc));raise
finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
