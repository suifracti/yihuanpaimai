"""Apply the production intel gate to already decoded replay observations."""
import sys,json,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'core'),str(ROOT/'app')]
def main():
    from auction_flow_evidence import AuctionFlowEvidence
    from canonical_history_store import CanonicalHistoryStore
    folder=Path(sys.argv[1]).resolve()
    record=json.loads((folder/'installed-record.json').read_text(encoding='utf8'))
    evidence=copy.deepcopy(record['auctionEvidence']);observations=evidence['intel'];evidence['intel']=[]
    collector=AuctionFlowEvidence();collector.data=evidence
    for observation in observations:
        rows=[(line['box'],line['text'],line['confidence']) for line in observation['lines']]
        collector.intel(rows,2560,1440,observation['capturedAt'],observation['round'])
    written=CanonicalHistoryStore().update_record_transactional(record['id'],{'auctionEvidence':collector.snapshot()})
    (folder/'installed-record.json').write_text(json.dumps(written,ensure_ascii=False,indent=2),encoding='utf8')
    print('Intel observations:',len(collector.data['intel']))
if __name__=='__main__':main()
