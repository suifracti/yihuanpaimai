"""Verify advanced fields through actual frozen Main DOM and native state."""
import argparse,asyncio,json
from pathlib import Path
import websockets
from verify_p1_real_ui import WS,eval_main,wait_main_match
from verify_p3_isolated_real_app_history import run_one_launch

FIELDS={'blue-count':('blueCount',3),'gold-count':('goldCount',2),'red-count':('redCount',1),'total-items':('totalItems',12),'purple-avg':('purpleAvg',12000),'total-grid':('totalGrid',40),'gold-grid':('goldGrid',8),'purple-grid':('purpleGrid',6)}

FIELDS.update({'white-count': ('whiteCount', 2), 'white-avg': ('whiteAvg', 175), 'white-grid': ('whiteGrid', 3), 'green-count': ('greenCount', 2), 'green-avg': ('greenAvg', 500), 'green-grid': ('greenGrid', 4), 'blue-avg': ('blueAvg', 2139), 'blue-grid': ('blueGrid', 6), 'red-grid': ('redGrid', 4)})

def verify(out,executable,keep_values=False):
 out=out.resolve();out.mkdir(parents=True,exist_ok=False)
 history=out/'data/history/异环拍卖数据.json';history.parent.mkdir(parents=True);history.write_text('{"schemaVersion":7,"records":[]}',encoding='utf-8')
 report={'status':'RUNNING'}
 async def interact(_zip,_export):
  async with websockets.connect(WS) as ws:
   await eval_main(ws,"showView('match');true")
   await wait_main_match(ws,lambda d:bool(d.get('matchId')))
   rows=[]
   for clear in ((False,) if keep_values else (False,True)):
    values={f'match-input-{suffix}':'' if clear else str(value) for suffix,(key,value) in FIELDS.items()}
    await eval_main(ws,'(()=>{for(const [id,value] of Object.entries('+json.dumps(values)+')){const el=document.getElementById(id);if(!el)throw Error(id);el.value=value;el.dispatchEvent(new Event("input",{bubbles:true}));el.dispatchEvent(new Event("change",{bubbles:true}));}return true;})()')
    current=await wait_main_match(ws,lambda d:all(d.get('facts',{}).get(key) is None if clear else d.get('facts',{}).get(key)==value for key,value in FIELDS.values()),timeout=20)
    dom=await eval_main(ws,'JSON.stringify(Object.fromEntries('+json.dumps(list(values))+'.map(id=>[id,document.getElementById(id).value])))')
    assert dom==values,(dom,values)
    rows.append({'dom':dom,'clear':clear,'facts':current.get('facts'),'matchId':current.get('matchId')})
   return rows
 try:
  dual,rows,clean=run_one_launch('fields',out/'data',out/'app.log',out,interactor=interact,frozen_executable=executable)
  assert dual and clean;report.update(status='PASS',rows=rows,cleanExit=clean)
 except Exception as exc:
  report.update(status='FAIL',error=repr(exc));raise
 finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--executable',type=Path);p.add_argument('--keep-values',action='store_true');a=p.parse_args();verify(a.output,a.executable,a.keep_values)
