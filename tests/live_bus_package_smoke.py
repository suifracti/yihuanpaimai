"""Native package regression: live facts, mode switching and settlement transport."""
import asyncio, json, os, pathlib, shutil, sys, time
from manual_advice_smoke import start, stop, recv_until
import websockets
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'core'))
from current_match import CurrentMatch
from live_match_transport import LiveMatchPublisher

async def flow():
    async with websockets.connect('ws://127.0.0.1:8766') as worker, websockets.connect('ws://127.0.0.1:8766') as observer:
        await worker.send(json.dumps({'type':'vision_worker_hello'}))
        await recv_until(worker,lambda d:d.get('action')=='worker_resume')
        match=CurrentMatch(); publisher=LiveMatchPublisher()
        match.apply_facts({'venue':'珊瑚场','box':'螺钿宝箱','q':21,'goldAvg':64836,'fieldCondition':'standard'},source='vision')
        delays=[]
        for index in range(12):
            packet=publisher.attach({'scene':'IN_AUCTION','inAuction':True,'q':21,'goldAvg':64836,'round':1,'warehousePresent':False,'gameHwnd':0},match)
            started=time.monotonic();await worker.send(json.dumps(packet))
            await recv_until(observer,lambda d:d.get('visionState',{}).get('sequence')==publisher.sequence,timeout=5)
            pong=await worker.ping();await asyncio.wait_for(pong,3)
            delays.append(time.monotonic()-started)
            await asyncio.sleep(.3)
        for mode in ('manual','auto'):
            script='window.chrome.webview.postMessage(JSON.stringify('+json.dumps({'action':'manual_facts','facts':{'recognitionMode':mode}})+'));true'
            await observer.send(json.dumps({'type':'eval_overlay_js','script':script}))
            await recv_until(observer,lambda d:d.get('recognitionMode')==mode,timeout=8)
        packet=publisher.attach({'scene':'SETTLEMENT','isSettlement':True,'settlementData':{'actualTotal':1050070,'clearingPrice':990000},'warehousePresent':False,'gameHwnd':0},match)
        # Native mode changes issue a control revision; acknowledge it just as
        # the real worker does before its next frame.
        while True:
            try:
                message=json.loads(await asyncio.wait_for(worker.recv(),.2))
                control=message.get('manualControl') or {}
                revision=control.get('revision',message.get('revision',0))
                publisher.control_revision=max(publisher.control_revision,revision or 0)
            except asyncio.TimeoutError:break
        packet['visionState']['controlRevision']=publisher.control_revision
        await worker.send(json.dumps(packet))
        await recv_until(observer,lambda d:d.get('scene')=='SETTLEMENT',timeout=5)
        return {'q':21,'goldAvg':64836,'modeRoundTrip':True,'settlementReceived':True,'maxTransportSeconds':round(max(delays),3)}

def main():
    exe=pathlib.Path(sys.argv[1]).resolve();out=pathlib.Path(sys.argv[2]).resolve();out.mkdir(parents=True,exist_ok=True)
    data=out/'data';(data/'history').mkdir(parents=True,exist_ok=True)
    if len(sys.argv)>3:shutil.copyfile(sys.argv[3],data/'history/异环拍卖数据.json')
    env={**os.environ,'YIHUAN_DATA_ROOT':str(data),'LOCALAPPDATA':str(out/'local'),'NTE_DISABLE_VISION':'1','NTE_DISABLE_ICON':'1','NTE_MAIN_UI_SMOKE':'1','NTE_ALLOW_HUD_CAPTURE':'1','NTE_LOG_FILE':str(out/'app.log')}
    proc,probe,window,_=start([str(exe)],env,out/'app.log')
    try:
        result=asyncio.run(flow());(out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(result)
    finally:stop(proc,probe,window)
if __name__=='__main__':main()

