"""Exercise low-tier known entries through actual Main DOM and persisted canonical data."""
import argparse,json,asyncio
from pathlib import Path
import websockets
from verify_p1_real_ui import WS,eval_main,wait_main_match
from verify_p3_isolated_real_app_history import run_one_launch
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--clear',action='store_true');p.add_argument('--executable',type=Path);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
data=out/'data';history=data/'history/异环拍卖数据.json';history.parent.mkdir(parents=True);history.write_text('{"schemaVersion":7,"records":[]}',encoding='utf-8')
report={'status':'RUNNING'}
async def interact(_zip,_export):
 async with websockets.connect(WS) as ws:
  await eval_main(ws,"showView('match');true")
  await wait_main_match(ws,lambda d:bool(d.get('matchId')))
  expected={}
  for color in ('gold','purple','red','blue','green','white'):
   names=await eval_main(ws,'JSON.stringify(getCatalogItems('+json.dumps(color)+').slice(0,2).map(x=>x.name))')
   expression=names[0]+'/'+names[1]+'+'+names[0]+('*3' if color in ('blue','green','white') else '');key='known'+color.title();expected[key]=expression
   await eval_main(ws,'(()=>{const e=document.getElementById("match-input-known-'+color+'");e.value='+json.dumps(expression)+';e.dispatchEvent(new Event("input",{bubbles:true}));e.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",bubbles:true}));return true})()')
   state=await wait_main_match(ws,lambda d:all(d.get('facts',{}).get(k)==v for k,v in expected.items()),timeout=20)
   observed=await eval_main(ws,'serializeKnownChips('+json.dumps(color)+')');assert observed==expression,(observed,expression)
  await asyncio.sleep(1)
  # Invalid names must remain in the input with feedback and never become a fact.
  await eval_main(ws,'(()=>{const e=document.getElementById("match-input-known-blue");e.value="__invalid__";e.dispatchEvent(new Event("change",{bubbles:true}));return true})()')
  valid=await eval_main(ws,'document.getElementById("match-input-known-blue").validationMessage');assert valid
  if a.clear:
   for color in ('gold','purple','red','blue','green','white'):
    await eval_main(ws,'(()=>{for(const e of [...document.querySelectorAll("#match-chips-'+color+' .chip-remove")].reverse())e.click();return true})()')
    expected['known'+color.title()]=''
    await wait_main_match(ws,lambda d:all(d.get('facts',{}).get(k)==v for k,v in expected.items()),timeout=20)
   await asyncio.sleep(1)
  return expected
try:
 dual,expected,clean=run_one_launch('known',data,out/'app.log',out,interactor=interact,frozen_executable=a.executable);assert dual and clean
 records=json.loads(history.read_text(encoding='utf-8'))['records'];assert len(records)==1
 from sys import path
 path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
 from v06_adapter import canonical_to_v06_solver_input
 stored=canonical_to_v06_solver_input(records[0])
 for k,v in expected.items():assert stored[k]==v,(k,stored[k],v)
 async def reopen(_zip,_export):
  async with websockets.connect(WS) as ws:
   await eval_main(ws,"showView('history');true")
   for _ in range(60):
    clicked=await eval_main(ws,'(()=>{const el=document.querySelector('+json.dumps('[data-record-id="'+records[0]['id']+'"].history-item')+');if(!el)return false;el.click();return true})()')
    if clicked:break
    await asyncio.sleep(.25)
   assert clicked
   values=await eval_main(ws,'JSON.stringify(Object.fromEntries(["gold","purple","red","blue","green","white"].map(c=>["known"+c[0].toUpperCase()+c.slice(1),document.getElementById("detail-known-"+c).textContent])))')
   assert values=={k:v or '未记录' for k,v in expected.items()},(values,expected)
   return values
 dual,values,clean=run_one_launch('known-reopen',data,out/'reopen.log',out,interactor=reopen,frozen_executable=a.executable);assert dual and clean
 report['historyDetails']=values
 report.update(status='PASS' ,expected=expected,recordId=records[0]['id'],invalidRejected=True,cleanExit=clean)
finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
