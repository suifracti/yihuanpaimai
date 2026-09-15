"""Real dual-window inputs plus explicitly synthetic solver/display boundaries."""
import argparse,asyncio,json,socket
from pathlib import Path
import websockets
from verify_p1_real_ui import WS,eval_main,eval_overlay,wait_overlay_payload,wait_main_match
from verify_p3_isolated_real_app_history import run_one_launch

OUT=None
async def interact(_zip,_export):
 async with websockets.connect(WS) as ws:
  await ws.send(json.dumps({'type':'manual_bootstrap','action':'manual_bootstrap'}))
  initial=await wait_overlay_payload(ws,lambda d:bool(d.get('matchId')))
  assert initial.get('targetProfit')==0,initial
  await eval_main(ws,"showView('match'); true")
  await eval_overlay(ws,"setOverlayExpanded(true); true")
  await eval_main(ws,"{const el=document.getElementById('match-input-q');el.focus();el.value='12';el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));true}")
  received=await wait_overlay_payload(ws,lambda d:d.get('q')==12)
  await eval_overlay(ws,"{const el=document.getElementById('goldAvgInput');el.focus();el.value='74379';handleLocalInput(el);true}")
  main=await wait_main_match(ws,lambda d:(d.get('facts') or {}).get('goldAvg')==74379)
  received=await wait_overlay_payload(ws,lambda d:d.get('goldAvg')==74379)
  assert received['targetProfit']==0
  inputs={'mainQToHud':received['q'],'hudGoldToMain':main['facts']['goldAvg'],'nativeTargetProfit':received['targetProfit']}
  bid_roundtrip=[]
  for value,expected in [('390000',390000),('',None)]:
   await eval_overlay(ws,"{const el=document.getElementById('leaderBidInput');el.focus();el.value="+json.dumps(value)+";handleLocalInput(el);true}")
   receipt=await wait_overlay_payload(ws,lambda d:d.get('leaderBid')==expected)
   bid_roundtrip.append({'input':value,'nativeBid':receipt.get('leaderBid'),'targetProfit':receipt.get('targetProfit')})
  inputs['bidAndClear']=bid_roundtrip
  assert all(row['targetProfit']==0 for row in bid_roundtrip)
  inputs['noVisibleTargetInput']=await eval_overlay(ws,"!document.getElementById('targetProfitInput')")
  assert inputs['noVisibleTargetInput']
  await eval_overlay(ws,"""{document.getElementById('venueChip').click();
   const item=[...document.querySelectorAll('#popoverList .popover-item')].find(el=>el.textContent.includes('珊瑚'));
   if(!item) throw 'missing venue';item.click();true}""")
  await wait_overlay_payload(ws,lambda d:d.get('venueId')=='venue-shanhu')
  await eval_main(ws,"{const el=document.getElementById('match-input-intel-cost');el.focus();el.value='1200';el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));true}")
  await wait_overlay_payload(ws,lambda d:d.get('intelCost')==1200)
  for field,value in [('otherCost',300),('futureIncrementalCost',700)]:
   await eval_overlay(ws,"{const el=document.getElementById("+json.dumps(field+'Input')+");el.focus();el.value="+json.dumps(str(value))+";handleLocalInput(el);true}")
   await wait_overlay_payload(ws,lambda d:d.get(field)==value)
  receipt=await wait_overlay_payload(ws,lambda d:(d.get('canonical') or {}).get('costs',{}).get('total')==7200)
  main=await wait_main_match(ws,lambda d:d.get('facts',{}).get('futureIncrementalCost')==700)
  assert receipt['canonical']['costs']==receipt['solverInput']['costs']
  assert main['facts']['intelCost']==1200 and main['facts']['otherCost']==300
  inputs['costRoundtrip']=receipt['canonical']['costs']
  await wait_overlay_payload(ws,lambda d:d.get('draftSaved') is True)
  inputs['recordId']=receipt['matchId']
  inputs['mainCostSummary']=await eval_main(ws,"document.getElementById('match-cost-summary').textContent")
  inputs['hudCostSummary']=await eval_overlay(ws,"document.getElementById('costSummary').textContent")
  assert inputs['mainCostSummary']==inputs['hudCostSummary']==receipt['costSummary']
  assert '7,200' in inputs['mainCostSummary'] and '6,500' in inputs['mainCostSummary']
  results=[]
  for bid,suffix in [(389999,'+1'),(390000,'0（保本）'),(390001,'-1'),(None,'—')]:
   # Deterministic support is a test fixture, not a claim about live history coverage.
   js='''JSON.stringify((()=>{
    const costs={entry:5000,intel:5000,other:0,sunkCost:10000,futureIncrementalCost:0,total:10000};
    const result=AuctionEngineV06.solveAuctionPipeline({q:12,goldAvg:74379,purple:7,costs,targetProfit:0,leaderBid:BID,
     probabilityProfile:{coverageRatio:1,supportedStateCount:2,totalStateCount:2,supportedWeight:1,totalWeight:1,shadowWhole:{p20:300000,p50:400000,p80:500000}}});
    const decision=result.decision;
    paintTrustedLiveResult({scene:'IN_AUCTION',predictionSnapshot:{id:'synthetic-ui',status:{solverStatus:'valid'},mode:{informationMode:'full_shadow'},forecast:{quantiles:{p20:300000,p50:400000,p80:500000}}},frozenPrediction:{decision}});
    return {decision,text:document.getElementById('expectedProfit').textContent};
   })())'''.replace('BID',json.dumps(bid))
   hud=await eval_overlay(ws,js)
   decision=hud['decision']
   maintext=await eval_main(ws,"""(()=>{const current=structuredClone(dashboard.lastCurrentMatch||{});
    current.prediction={hasSnapshot:true,mode:'full_shadow',p20:300000,p50:400000,p80:500000};
    current.decisionLines=DECISION;renderMatch(current,true);
    return document.getElementById('match-live-expected-profit').textContent;})()""".replace('DECISION',json.dumps(decision,ensure_ascii=False)))
   assert hud['text'].endswith(suffix),(bid,hud)
   assert maintext==hud['text'],(bid,maintext,hud)
   results.append({'bid':bid,'expectedProfit':decision.get('expectedProfit'),'main':maintext,'hud':hud['text']})
  return {'nativeInputRoundtrip':inputs,'syntheticSolverDisplayCases':results}

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--out-dir',type=Path,required=True);parser.add_argument('--executable',type=Path);args=parser.parse_args();OUT=args.out_dir.resolve()
 with socket.socket() as port:port.bind(('127.0.0.1',8766))
 OUT.mkdir(parents=True,exist_ok=False);data=OUT/'data';data.mkdir()
 history=data/'history/异环拍卖数据.json';history.parent.mkdir();history.write_text(json.dumps({'schemaVersion':7,'records':[]}),encoding='utf-8')
 report={'status':'RUNNING'}
 try:
  dual,result,clean=run_one_launch('profit',data,OUT/'app.log',OUT,interactor=interact,frozen_executable=args.executable)
  assert dual and clean
  saved=next(r for r in json.loads(history.read_text(encoding='utf-8'))['records'] if r['id']==result['nativeInputRoundtrip']['recordId'])
  assert saved['costs']==result['nativeInputRoundtrip']['costRoundtrip']
  result['persistedCosts']=saved['costs']
  async def reopen(_zip,_export):
   async with websockets.connect(WS) as ws:
    await ws.send(json.dumps({'type':'manual_bootstrap','action':'manual_bootstrap'}))
    await eval_main(ws,"showView('history');true")
    for _ in range(60):
     found=await eval_main(ws,'''(()=>{const row=[...document.querySelectorAll('#history-list .history-item')].find(el=>el.dataset.recordId===ID);if(!row)return false;row.click();return true;})()'''.replace('ID',json.dumps(saved['id'])))
     if found:break
     await asyncio.sleep(.2)
    assert found
    text=await eval_main(ws,"document.getElementById('detail-cost-summary').textContent")
    assert text==result['nativeInputRoundtrip']['mainCostSummary'],text
    return {'recordId':saved['id'],'historyCostSummary':text}
  dual2,reopened,clean2=run_one_launch('cost_reopen',data,OUT/'reopen.log',OUT,interactor=reopen,frozen_executable=args.executable)
  assert dual2 and clean2
  result['restart']={'dualLaunched':dual2,'cleanExit':clean2,**reopened}
  persisted_again=next(r for r in json.loads(history.read_text(encoding='utf-8'))['records'] if r['id']==saved['id'])
  assert persisted_again['costs']==saved['costs']
  report.update(status='PASS',dualLaunched=dual,cleanExit=clean,**result)
 except Exception as exc:
  report.update(status='FAIL',error=repr(exc));raise
 finally:(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
