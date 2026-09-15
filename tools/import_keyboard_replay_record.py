"""Install the reviewed video record as a draft, preserving replay provenance."""
import sys,json,hashlib,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'core'),str(ROOT/'app')]

def main():
    folder=Path(sys.argv[1]).resolve()
    from canonical_history_store import CanonicalHistoryStore
    from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
    from settlement_truth_holder import build_settlement_truth_evidence_v1
    from runtime_data import runtime_data_paths
    audit=json.loads((folder/'audit.json').read_text(encoding='utf8'))
    records=json.loads((folder/'history.json').read_text(encoding='utf8'))['records']
    record=copy.deepcopy(next(r for r in records if r['id']==audit['evidence']['ownerMatchId']))
    digest=hashlib.sha256(Path(audit['video']).read_bytes()).hexdigest()
    record.update(source='video-replay',lifecycleStatus='DRAFT',playedAt='2026-09-08T14:42:03.633+08:00')
    record['auctionEvidence']=copy.deepcopy(audit['evidence'])
    record['auctionEvidence']['videoSource']={'path':audit['video'],'sha256':digest,'method':'production-pipeline-replay'}
    record['productVersion']='v0.68-alpha'
    record['environment'].update(venue='珊瑚场',venueName='珊瑚场',box='琉璃宝箱',fieldConditionName='标准对局')
    old_truth=record['settlement']['truthEvidence']
    originals=old_truth.get('fileOriginals') or []
    root=runtime_data_paths().root
    store=CanonicalHistoryStore()
    existing=next((r for r in store.read_database().get('records',[]) if r.get('id')==record['id']),None)
    if existing:
        print('Record already installed:',record['id']);return
    (folder/'history-before-install.json').write_text(json.dumps(store.read_database(),ensure_ascii=False,indent=2),encoding='utf8')
    evidence_store=SettlementEvidenceStoreV2(root)
    installed=[]
    for original in originals:
        source=(folder/'isolated-data'/original['relativePath']).resolve()
        source.relative_to((folder/'isolated-data').resolve())
        payload=source.read_bytes()
        if hashlib.sha256(payload).hexdigest()!=original['sha256']:raise RuntimeError('Original hash mismatch')
        installed.append(evidence_store.save_original(record_stable_key=record['id'],kind=original['kind'],
            image_bytes=payload,captured_at=original['capturedAt'],evidence_origin='user-import'))
    truth=build_settlement_truth_evidence_v1(match_id=record['id'],actual_total=record['settlement']['actualTotal'],
        settlement_observed_at=old_truth['settlementObservedAt'],truth_source='user_video_replay_multiframe',
        evidence_uri=installed[0]['relativePath'] if installed else None,
        evidence_sha256=installed[0]['sha256'] if installed else None)
    truth['schemaVersion']='settlement-truth-evidence.v2';truth['fileOriginals']=installed
    record['settlement']['truthEvidence']=truth
    # The video proves the visible bill; complete inventory and acquisition
    # admission remain unconfirmed, so this is intentionally a draft.
    record['settlement']['status']='pending';record['settlement']['verified']=False
    written=store.persist_record_transactional(record,is_finalized=False)
    (folder/'installed-record.json').write_text(json.dumps(written,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'id':written['id'],'originals':len(installed),'history':str(store.db_path)},ensure_ascii=False))

if __name__=='__main__':main()
