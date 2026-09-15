"""Save the supplied video's distinct settlement views under its imported record."""
import sys,json
from pathlib import Path
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'core'),str(ROOT/'app')]
def main():
    import cv2
    from canonical_history_store import CanonicalHistoryStore
    from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
    from runtime_data import runtime_data_paths
    folder=Path(sys.argv[1]).resolve();record=json.loads((folder/'installed-record.json').read_text(encoding='utf8'))
    evidence=SettlementEvidenceStoreV2(runtime_data_paths().root)
    cap=cv2.VideoCapture(record['auctionEvidence']['videoSource']['path'])
    added=[]
    for second in (162,165,170):
        cap.set(cv2.CAP_PROP_POS_MSEC,second*1000);ok,frame=cap.read()
        if not ok:raise RuntimeError('Cannot decode settlement view')
        payload=cv2.imencode('.png',frame)[1].tobytes()
        added.append(evidence.save_original(record_stable_key=record['id'],kind='warehouse-segment',image_bytes=payload,
            captured_at=(datetime(2026,9,8,14,40,37)+timedelta(seconds=second)).isoformat()+'+08:00',evidence_origin='user-import'))
    cap.release()
    truth=record['settlement']['truthEvidence'];seen={x['evidenceId'] for x in truth['fileOriginals']}
    truth['fileOriginals'].extend(x for x in added if x['evidenceId'] not in seen)
    written=CanonicalHistoryStore().update_record_transactional(record['id'],{'settlement':{'truthEvidence':truth}})
    (folder/'installed-record.json').write_text(json.dumps(written,ensure_ascii=False,indent=2),encoding='utf8')
    print('Original views:',len(truth['fileOriginals']))
if __name__=='__main__':main()
