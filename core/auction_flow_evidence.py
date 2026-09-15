"""Observed auction content, with explicit match ownership and no price inference."""
import copy
import hashlib
import json
import re


class AuctionFlowEvidence:
    def __init__(self):
        self.data = None
        self.last_scene = None
        self.returned = False
        self.before_match = []
        self.before_flow = []
        self._signatures = {}

    def scene(self, scene, captured_at, match_id):
        if scene == 'UNKNOWN':
            return
        if scene=='OPEN_WORLD' and self.last_scene=='AUCTION_LOADING' and not self.returned and self.data is None:
            self.before_flow.append({'scene':'LOAD_ABORTED','capturedAt':captured_at})
        started = bool(scene in ('IN_AUCTION', 'SETTLEMENT') and match_id and
                       (self.data is None or self.data.get('ownerMatchId') != match_id or
                        (scene == 'IN_AUCTION' and self.returned)))
        if started:
            self.data = {'version':1,'ownerMatchId':match_id,'intel':[], 'bids':[],
                         'warehouse':[], 'flow':copy.deepcopy(self.before_flow), 'replenishment':'UNOBSERVED',
                         'startedAtSettlement':scene == 'SETTLEMENT',
                         'priorMatchActivity':copy.deepcopy(self.before_match)}
            self.before_match=[]
            self.before_flow=[]
            self._signatures={}
            self.returned=False
        if not started and self.data and self.last_scene == 'SETTLEMENT' and scene != 'SETTLEMENT':
            self.returned = True
            self.data['hasReturned'] = True
        if self.data and scene=='TOOL_REPLENISH_CONFIRM':
            self.data['replenishment']='CONFIRMATION_SEEN'
        if started or scene != self.last_scene:
            event={'scene':scene,'capturedAt':captured_at}
            if self.data:
                self.data['flow'].append(event)
            elif scene == 'TOOL_REPLENISH':
                self.before_match.append({**event,'ownership':'PRIOR_MATCH_UNRESOLVED'})
            else:
                self.before_flow.append(event)
                self.before_flow=self.before_flow[-30:]
        self.last_scene=scene

    def add(self, kind, payload, captured_at, round_number=None):
        if not self.data:
            return False
        if kind == 'bids' and round_number is not None:
            existing = next((b for b in self.data.get('bids', []) if b.get('round') == round_number), None)
            if existing is not None:
                # Monotonic consolidation: merge newer OCR in-place into single round record
                existing['capturedAt'] = captured_at
                seat_by_slot = {s.get('slot'): s for s in existing.get('seats', []) if isinstance(s, dict)}
                for s in (payload.get('seats') or []):
                    if not isinstance(s, dict):
                        continue
                    slot = s.get('slot')
                    if slot not in seat_by_slot:
                        existing.setdefault('seats', []).append(copy.deepcopy(s))
                    else:
                        target = seat_by_slot[slot]
                        new_name = s.get('name')
                        if new_name and (not target.get('name') or '未识别' in str(target.get('name')) or target.get('name') == f"座位 {slot}"):
                            target['name'] = new_name
                        if s.get('currentBid') is not None:
                            target['currentBid'] = s['currentBid']
                        if s.get('bid') is not None and s.get('bid') >= 0:
                            target['bid'] = s['bid']
                        if s.get('observationStatus'):
                            target['observationStatus'] = s['observationStatus']
                        if s.get('isMe') is not None:
                            target['isMe'] = s['isMe']
                return True
        semantic = payload
        if kind == 'intel':
            semantic = [line['text'] for line in payload.get('lines',[])]
        elif kind == 'warehouse':
            semantic=[payload.get('scene'),[{k:s.get(k) for k in ('col','row','w','h','rarity','identityStatus','identifiedName')} for s in payload.get('slots',[])]]
        signature = json.dumps([round_number,semantic],sort_keys=True,ensure_ascii=False,default=str)
        digest=hashlib.sha256(signature.encode()).hexdigest()
        if self._signatures.get(kind)==digest:
            return False
        self._signatures[kind]=digest
        self.data[kind].append({'capturedAt':captured_at,'round':round_number,**copy.deepcopy(payload)})
        return True

    def intel(self, rows, width, height, captured_at, round_number):
        if any(any(marker in str(text) for marker in ('请输入你愿意','推荐出价参考','可输入范围')) for _,text,_ in rows or []):
            # The bidding dialog covers the board; its input is not intel.
            return False
        lines=[]
        for box,text,score in rows or []:
            x=sum(p[0] for p in box)/len(box)/width
            y=sum(p[1] for p in box)/len(box)/height
            if .32 <= x <= .75 and .23 <= y <= .86 and float(score)>=.60 and str(text).strip() not in ('NTE','ROUND2'):
                lines.append({'text':str(text),'confidence':round(float(score),3),
                              'box':[[round(float(x),1),round(float(y),1)] for x,y in box]})
        if lines:
            return self.add('intel',{'lines':lines},captured_at,round_number)
        return False

    def replenish(self, lines, captured_at):
        texts=[str(row[1]) for row in lines or []]
        observation={'scene':'TOOL_REPLENISH','capturedAt':captured_at,'lines':texts}
        if self.data:
            if self.data['flow'][-1:] != [observation]:
                # Keep the observation even when it cannot prove completion.
                if self._signatures.get('restock') != texts:
                    self.data['flow'].append(observation)
                    self._signatures['restock']=texts
            if any('已使用' in t for t in texts) and self.data['replenishment']=='UNOBSERVED':
                self.data['replenishment']='NEEDS_REPLENISHMENT'
            if any('一键补全' in t for t in texts):
                self.data['replenishment']='CONFIRMATION_SEEN'
            if any('补充成功' in t or '补全成功' in t for t in texts):
                self.data['replenishment']='COMPLETED'
        elif not self.before_match or self.before_match[-1].get('lines') != texts:
            self.before_match.append({**observation,'ownership':'PRIOR_MATCH_UNRESOLVED'})

    def snapshot(self):
        return copy.deepcopy(self.data)


class AuctionEvidencePersistence:
    """Append post-match observations to their explicit owner, after retirement."""
    def __init__(self, store):
        self.store=store
        self.saved=None

    def save(self, evidence):
        if not isinstance(evidence,dict) or not evidence.get('hasReturned'):
            return False
        owner=evidence.get('ownerMatchId')
        if not owner or evidence==self.saved:
            return False
        from canonical_history_store import HistoryStoreError
        try:
            self.store.update_record_transactional(owner,{'auctionEvidence':copy.deepcopy(evidence)})
        except HistoryStoreError as exc:
            if 'RECORD_NOT_FOUND' in str(exc):
                return False
            raise
        self.saved=copy.deepcopy(evidence)
        return True
