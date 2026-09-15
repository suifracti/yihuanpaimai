"""Replay the production auction pipeline into an isolated audit directory."""
import os, sys, json, time, copy
from pathlib import Path
from datetime import datetime, timedelta
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'core'),str(ROOT/'app')]

def main():
    import cv2
    video=Path(sys.argv[1]); out=Path(sys.argv[2]).resolve();out.mkdir(parents=True,exist_ok=True)
    os.environ['YIHUAN_DATA_ROOT']=str(out/'isolated-data')
    from keyboard_auction_pipeline import KeyboardAuctionPipeline
    from current_match import CurrentMatch, FACT_KEYS
    from live_match_transport import LiveMatchSession
    from auto_archiver import AutoArchiver
    from canonical_history_store import CanonicalHistoryStore
    from auction_flow_evidence import AuctionEvidencePersistence
    p=KeyboardAuctionPipeline();p.recognition_mode_provider=lambda:'auto';p._ensure_ocr()
    match=CurrentMatch();session=LiveMatchSession()
    store=CanonicalHistoryStore();archiver=AutoArchiver();persistence=AuctionEvidencePersistence(store)
    cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS);step=max(1,round(fps/30))
    start=datetime.strptime(video.stem,'%Y-%m-%d %H-%M-%S')
    n=0;last_read=-100;last_scene=None; rows=[];timings=[]
    while cap.grab():
        if n%step==0:
            ok,frame=cap.retrieve();second=n/fps
            if ok:
                route=p._classify_scene_fast(frame)
                scene=route['scene']
                if route['confirmed'] and (scene!=last_scene or second-last_read>=1.5):
                    at=(start+timedelta(seconds=second)).isoformat(timespec='milliseconds')+'+08:00'
                    t=time.perf_counter()
                    ctx=p.process_frame(frame,at,record_stable_key=match.id,include_heavy_identity=False)
                    # Resolve async crop work before advancing this offline
                    # fixture's clock; production resolves it on incoming frames.
                    if p._navigation_future is not None:p._navigation_future.result()
                    heavy=p.complete_heavy_identity()
                    if heavy:ctx=heavy
                    session.observe(ctx,match)
                    facts={k:copy.deepcopy(ctx[k]) for k in FACT_KEYS if k in ctx and k!='auctionEvidence'}
                    evidence=ctx.get('auctionEvidence')
                    if evidence and evidence.get('ownerMatchId')==match.id:facts['auctionEvidence']=evidence
                    match.apply_facts(facts,source='vision')
                    if ctx.get('settlementReady'):archiver.archive_match(ctx)
                    persistence.save(evidence)
                    elapsed=time.perf_counter()-t;timings.append(elapsed)
                    row={'second':round(second,3),'elapsed':round(elapsed,3),**{k:copy.deepcopy(ctx.get(k)) for k in ('scene','auctionPhase','round','q','purple','goldAvg','seats','settlementData','settlementReady')}}
                    rows.append(row);last_read=second;last_scene=scene
                    (out/'audit.json').write_text(json.dumps({'video':str(video),'frames':rows,'evidence':p.flow_evidence.snapshot()},ensure_ascii=False,indent=2,default=str),encoding='utf8')
                    print(round(second,2),scene,round(elapsed,2),flush=True)
        n+=1
    cap.release()
    (out/'history.json').write_text(json.dumps(store.read_database(),ensure_ascii=False,indent=2),encoding='utf8')
    p._navigation_executor.shutdown(wait=True)
    print('DONE',len(rows),max(timings,default=0),flush=True)

if __name__=='__main__':main()
