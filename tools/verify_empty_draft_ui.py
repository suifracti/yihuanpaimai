"""Real UI empty startup, history-only and edited shutdown persistence checks."""
import argparse,asyncio,json
from pathlib import Path
import websockets
from verify_p1_real_ui import WS,eval_main,wait_main_match
from verify_p3_isolated_real_app_history import run_one_launch
from verify_advanced_fields_ui import verify as edit_fields

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--executable',type=Path);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 data=out/'empty/data';history=data/'history/异环拍卖数据.json';history.parent.mkdir(parents=True);history.write_text('{"schemaVersion":7,"records":[]}',encoding='utf-8');report={'status':'RUNNING','checks':[]}
 async def idle(_zip,_export):
  async with websockets.connect(WS) as ws:
   await wait_main_match(ws,lambda d:bool(d.get('matchId')))
   await eval_main(ws,"showView('history');true")
   return True
 try:
  before=history.read_bytes()
  for tag in ('empty-start','history-only'):
   dual,_,clean=run_one_launch(tag,data,out/(tag+'.log'),out,interactor=idle,frozen_executable=a.executable)
   assert dual and clean and history.read_bytes()==before
   report['checks'].append(tag)
  edit_fields(out/'edited',a.executable,True)
  edited=out/'edited/data';path=edited/'history/异环拍卖数据.json';before=path.read_bytes();records=json.loads(before)['records'];assert len(records)==1 and records[0]['publicIntel']['totalItems']==12
  dual,_,clean=run_one_launch('edited-reopen',edited,out/'edited-reopen.log',out,interactor=idle,frozen_executable=a.executable)
  assert dual and clean and path.read_bytes()==before
  report.update(status='PASS');report['checks'].extend(['edited-save','history-reopen-no-extra-draft'])
 except Exception as exc:report.update(status='FAIL',error=repr(exc));raise
 finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
