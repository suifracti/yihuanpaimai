"""Reopen UI-written advanced fields and inspect actual history detail DOM."""
import asyncio,json,argparse,time,socket
from pathlib import Path
import websockets
from verify_p1_real_ui import WS,eval_main
from verify_p3_isolated_real_app_history import run_one_launch
from verify_advanced_fields_ui import FIELDS

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--executable',type=Path);p.add_argument('--record-id');a=p.parse_args();a.data=a.data.resolve();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
 with socket.socket() as probe:
  probe.settimeout(1)
  assert probe.connect_ex(('127.0.0.1',8766)) != 0, 'Existing app occupies verification port'
 records=json.loads((a.data/'history/异环拍卖数据.json').read_text(encoding='utf-8'))['records']
 selected=[r for r in records if r['id']==a.record_id] if a.record_id else records
 assert len(selected)==1
 record=selected[0];rid=record['id'];report={'status':'RUNNING'}
 async def interact(_zip,_export):
  async with websockets.connect(WS) as ws:
   await eval_main(ws,"showView('history');true")
   deadline=time.monotonic()+15
   while time.monotonic()<deadline:
    clicked=await eval_main(ws,'(()=>{const el=document.querySelector('+json.dumps('[data-record-id="'+rid+'"].history-item')+');if(!el)return false;el.click();return true;})()')
    if clicked:break
    await asyncio.sleep(.25)
   assert clicked,'history record absent'
   observed=await eval_main(ws,'JSON.stringify(Object.fromEntries('+json.dumps(list(FIELDS))+'.map(key=>[key,document.getElementById("detail-"+key)?.textContent])))')
   for suffix,(key,value) in FIELDS.items():
    assert observed.get(suffix,'').replace(',','').replace('¥','').replace('￥','').strip()==str(value),(suffix,observed)
   return observed
 try:
  dual,values,clean=run_one_launch('reopen',a.data,a.output/'app.log',a.output,interactor=interact,frozen_executable=a.executable)
  assert dual and clean;report.update(status='PASS',values=values,recordId=rid,cleanExit=clean)
 except Exception as exc:report.update(status='FAIL',error=repr(exc));raise
 finally:(a.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
