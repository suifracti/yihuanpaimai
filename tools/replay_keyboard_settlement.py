"""Supplement the full replay with the production settlement inventory ledger."""
import os,sys,json,copy
from pathlib import Path
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'core'),str(ROOT/'app')]

def main():
    import cv2
    folder=Path(sys.argv[1]).resolve()
    os.environ['YIHUAN_DATA_ROOT']=str(folder/'isolated-data')
    from keyboard_auction_pipeline import KeyboardAuctionPipeline
    from canonical_history_store import CanonicalHistoryStore
    audit=json.loads((folder/'audit.json').read_text(encoding='utf8'))
    p=KeyboardAuctionPipeline();p.recognition_mode_provider=lambda:'auto';p._ensure_ocr()
    p.flow_evidence.data=copy.deepcopy(audit['evidence'])
    p.flow_evidence.data['warehouse']=[x for x in p.flow_evidence.data['warehouse'] if x.get('scene')!='SETTLEMENT']
    p.flow_evidence.last_scene='SETTLEMENT';p.flow_evidence.returned=True
    owner=p.flow_evidence.data['ownerMatchId'];p.current_context['round']=2
    cap=cv2.VideoCapture(audit['video'])
    start=datetime.strptime(Path(audit['video']).stem,'%Y-%m-%d %H-%M-%S')
    counts=[]
    for second in (159,162,165,168,170):
        cap.set(cv2.CAP_PROP_POS_MSEC,second*1000);ok,frame=cap.read()
        if not ok:raise RuntimeError('Missing video frame')
        p.scene_roi_router.hint(['SETTLEMENT']);p._classify_scene_fast(frame.copy())
        ctx=p.process_frame(frame,(start+timedelta(seconds=second)).isoformat()+'+08:00',True,owner,False)
        ctx=p.complete_heavy_identity() or ctx
        p._record_warehouse(ctx)
        observations=p.flow_evidence.data['warehouse']
        counts.append({'second':second,'slots':len(observations[-1]['slots']) if observations else 0})
    cap.release();p._navigation_executor.shutdown(wait=True)
    audit['evidence']=p.flow_evidence.snapshot();audit['settlementInventoryReplay']=counts
    (folder/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    store=CanonicalHistoryStore();store.update_record_transactional(owner,{'auctionEvidence':audit['evidence']})
    (folder/'history.json').write_text(json.dumps(store.read_database(),ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(counts))

if __name__=='__main__':main()
