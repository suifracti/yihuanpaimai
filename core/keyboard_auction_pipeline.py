"""Production scene gate: one visual scene group, then only its data readers."""
import time
from auction_flow_evidence import AuctionFlowEvidence
from scene_roi_router import create_keyboard_router
from vision_pipeline import NTEVisionPipeline, PRE_AUCTION_NAV_SCENES


LABELS = {'WORLD_MAP':'地图','TOOL_REPLENISH':'道具补货','HELPER_SELECTION':'选择竞拍帮手',
          'TOOL_REPLENISH_CONFIRM':'确认补充消耗道具','AUCTION_LOADING':'加载中','UNKNOWN':'正在定位拍卖流程'}


class KeyboardAuctionPipeline(NTEVisionPipeline):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scene_roi_router = create_keyboard_router()
        self.flow_evidence = AuctionFlowEvidence()
        self.fast_live_intel = False
        self._route = None
        self._restock_read_at = 0
        self._observation_time = ''
        from keyboard_scene_hints import KeyboardSceneHints
        self._input_hints = KeyboardSceneHints()
        self._last_lobby_read = 0
        from concurrent.futures import ThreadPoolExecutor
        self._navigation_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='scene-details')
        self._navigation_future=None
        self._navigation_request=None
        self._keyboard_text_sig=None
        self._last_board_read_at=0

    def _should_run_auction_canvas_ocr(self, frame, force_refresh=False):
        import cv2
        import numpy as np
        if force_refresh or self.current_context.get('scene')!='IN_AUCTION':return True
        h,w=frame.shape[:2]
        crop=frame[int(h*.24):int(h*.82),int(w*.40):int(w*.65)]
        gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        mask=cv2.resize(cv2.inRange(gray,205,255),(160,240),interpolation=cv2.INTER_AREA)
        previous=self._keyboard_text_sig
        changed=previous is None or float(np.mean(np.abs(mask.astype(np.int16)-previous.astype(np.int16))))>3
        if not changed and time.monotonic()-self._last_board_read_at<3.5:
            self.ocr_skip_count+=1
            return False
        self._keyboard_text_sig=mask
        return True

    def _classify_scene_fast(self, frame):
        hints=self._input_hints.poll(frame,self.current_context.get('gameHwnd'),self.scene_roi_router.confirmed)
        if hints:self.scene_roi_router.hint(hints)
        route = self.scene_roi_router.observe(frame)
        self._route = route
        return {**route,'auctionEntryVisible':route['scene']=='AUCTION_LOBBY',
                'whiteCity':route['scene']=='CITY_TYCOON_HUB'}

    def process_frame(self, frame, captured_at=None, force_refresh=False,
                      record_stable_key=None, include_heavy_identity=True):
        self._bind_acquisition_record(record_stable_key)
        provider=getattr(self,'recognition_mode_provider',None)
        self.current_context['recognitionMode']=provider() if callable(provider) else 'manual'
        route = self._classify_scene_fast(frame)
        scene = route['scene']
        now = captured_at or time.strftime('%Y-%m-%dT%H:%M:%S%z')
        self._observation_time = now
        self._frame_seat_rows = []
        key = record_stable_key or self.current_context.get('recordStableKey') or ''
        self._finish_navigation_read(route)
        self.flow_evidence.scene(route.get('phase') or scene,now,key)
        if scene == 'UNKNOWN':
            self._pending_heavy_identity = None
            return {**self.current_context,'scene':'UNKNOWN','isSettlement':False,
                    'inAuction':False,'inLobby':False,'isLoading':False,'sceneLabel':LABELS['UNKNOWN'],
                    'settlementReady':False,'recognitionPaused':True,'sceneRouting':self._route}
        if scene in ('IN_AUCTION','SETTLEMENT'):
            if self._navigation_future is not None:
                # The one OCR engine is still reading a previous small crop.
                # Keep routing fresh while waiting; do not queue auction jobs.
                return {**self.current_context,'scene':scene,'recognitionPaused':True,
                        'isSettlement':False,'settlementReady':False,'sceneRouting':route}
            result = super().process_frame(frame,captured_at,force_refresh,record_stable_key,include_heavy_identity)
            if result.get('scene') == 'SETTLEMENT' and self.flow_evidence.data and self.flow_evidence.data.get('ownerMatchId') == key:
                self.flow_evidence.data.setdefault('acquisition', [])
                self.flow_evidence.add('acquisition', self._acquisition_names.evidence(), now, result.get('round'))
                self.flow_evidence.data['acquisition'] = self.flow_evidence.data['acquisition'][-32:]
                result['auctionEvidence'] = self.flow_evidence.snapshot()
            if result.get('scene')=='SETTLEMENT' and result.get('settlementReady'):
                from settlement_shape_observation import observe_settlement_shapes
                result['settlementShapeSlots']=observe_settlement_shapes(frame)
                self._record_warehouse(result)
            if result.get('scene') == 'IN_AUCTION':
                if getattr(self,'_frame_ocr_rows',[]):self._last_board_read_at=time.monotonic()
                round_number = result.get('round')
                self.flow_evidence.intel(getattr(self,'_frame_ocr_rows',[]),frame.shape[1],frame.shape[0],now,round_number)
                from seat_bid_observation import visible_seat_bids
                import copy
                from live_match_projection import empty_seats
                seats=copy.deepcopy(result.get('seats') or []) or empty_seats()
                raw=getattr(self,'_frame_seat_rows',[])
                observed=visible_seat_bids(raw,frame.shape[1],frame.shape[0],allow_zero=True)
                last_round_seats = None
                if self.flow_evidence.data and self.flow_evidence.data.get('bids'):
                    last_bid = self.flow_evidence.data['bids'][-1]
                    if last_bid.get('round') == round_number:
                        last_round_seats = {s.get('slot', i+1): s for i, s in enumerate(last_bid.get('seats') or []) if isinstance(s, dict)}
                for index,seat in enumerate(seats[:4]):
                    slot = seat.get('slot', index + 1)
                    if observed[index] is not None:
                        seat['currentBid']=observed[index]
                        seat['bid']=observed[index]
                        seat['observationStatus']='VISIBLE'
                    elif last_round_seats and slot in last_round_seats:
                        prev_s = last_round_seats[slot]
                        if prev_s.get('observationStatus') == 'VISIBLE' or prev_s.get('currentBid') is not None:
                            if seat.get('currentBid') is None:
                                seat['currentBid'] = prev_s.get('currentBid')
                                seat['bid'] = prev_s.get('bid')
                                seat['observationStatus'] = prev_s.get('observationStatus', 'VISIBLE')
                result['seats']=seats
                self.current_context['seats']=seats
                # Corroborate the final displayed roster only with fresh text
                # from this frame; cached names and nearby chat are not samples.
                items, _ = self._extract_seat_panel_items(raw, frame.shape[1], frame.shape[0])
                confident = {''.join(str(text).split()) for _, text, score in raw if score >= .85}
                for seat in seats:
                    name = seat.get('name')
                    if name in confident and any(item[0] == seat.get('slot') and item[-1] == name for item in items):
                        self._acquisition_names.observe_name(seat.get('slot'), name, self._acquisition_frame)
                self.flow_evidence.add('bids',{'seats':seats},now,round_number)
                if include_heavy_identity:
                    self._record_warehouse(result)
        else:
            self._pending_heavy_identity = None
            if scene in PRE_AUCTION_NAV_SCENES:
                self._apply_pre_auction_scene(route)
                if scene == 'AUCTION_LOBBY' and not self.flow_evidence.returned and (force_refresh or time.monotonic()-self._last_lobby_read>10):
                    # Existing small loadout readers belong to this group only.
                    h,w=frame.shape[:2]
                    if self._start_navigation_read(frame[int(h*.52):int(h*.90),int(w*.61):int(w*.98)],scene,now,route):
                        self._last_lobby_read=time.monotonic()
            else:
                self.current_context.update({'scene':scene,'sceneLabel':LABELS.get(scene,scene),
                    'inAuction':False,'inLobby':False,'isSettlement':False,
                    'isLoading':scene=='AUCTION_LOADING','settlementReady':False})
                if scene == 'AUCTION_LOADING':
                    self.current_context['loadingDirection']='to_lobby' if self.flow_evidence.returned else 'to_auction'
                if scene in ('TOOL_REPLENISH','TOOL_REPLENISH_CONFIRM') and time.monotonic()-self._restock_read_at > 1:
                    if self._ocr_engine is None:
                        self._warm_ocr_async()
                    else:
                        h,w=frame.shape[:2]
                        rect=frame[int(h*.38):int(h*.68),int(w*.30):int(w*.70)] if scene=='TOOL_REPLENISH_CONFIRM' else frame[int(h*.19):int(h*.85),:int(w*.58)]
                        if self._start_navigation_read(rect,scene,now,route):
                            self._restock_read_at=time.monotonic()
            result=self.current_context
        result['recognitionPaused']=False
        result['sceneRouting']=self._route
        result['auctionPhase']=route.get('phase') or scene
        if self.flow_evidence.data:
            result['auctionEvidence']=self.flow_evidence.snapshot()
        return result

    def _start_navigation_read(self,crop,scene,captured_at,route):
        if self._navigation_future is not None:return False
        image=crop.copy()
        self._navigation_request=(scene,captured_at,route['generation'],self.flow_evidence.data is not None,
                                  (self.flow_evidence.data or {}).get('ownerMatchId'))
        self._navigation_future=self._navigation_executor.submit(lambda:self.ocr(image)[0])
        return True

    def _finish_navigation_read(self,route):
        future=self._navigation_future
        if future is None or not future.done():return
        request=self._navigation_request
        self._navigation_future=None
        self._navigation_request=None
        try:rows=future.result()
        except Exception:return
        scene,at,generation,had_match,owner=request
        if scene=='AUCTION_LOBBY':
            if route['scene']==scene and route['generation']==generation:
                parsed=self._parse_lobby_loadout(rows or [])
                self._apply_lobby_loadout(parsed)
        elif not had_match:
            observation={'scene':scene,'capturedAt':at,'lines':[str(r[1]) for r in rows or []],
                         'ownership':'PRIOR_MATCH_UNRESOLVED'}
            if self.flow_evidence.data:self.flow_evidence.data['priorMatchActivity'].append(observation)
            else:self.flow_evidence.before_match.append(observation)
        elif self.flow_evidence.data and self.flow_evidence.data.get('ownerMatchId')==owner:
            self.flow_evidence.replenish(rows,at)

    def complete_heavy_identity(self):
        result=super().complete_heavy_identity()
        if result and result.get('scene') in ('IN_AUCTION','SETTLEMENT'):
            self._record_warehouse(result)
        return result

    def _record_warehouse(self,result):
        keys=('trackId','box','size','rarity','evidenceLevel','identityStatus','identifiedName','col','row','w','h')
        slots=[{key:s.get(key) for key in keys} for s in result.get('warehouseSlots') or []]
        if result.get('scene')=='SETTLEMENT':
            # Settlement has its own ledger. Auction outline tracks are stale
            # after reveal and must never stand in for the visible inventory.
            slots=[{'col':s.get('col'),'row':s.get('row'),'w':s.get('widthCells'),'h':s.get('heightCells'),
                    'box':s.get('bbox'),'rarity':s.get('rarity'),
                    'identityStatus':'EXACT' if s.get('status')=='exact' else 'UNKNOWN',
                    'identifiedName':s.get('name') if s.get('status')=='exact' else None,
                    'evidenceLevel':'IDENTIFIED' if s.get('status')=='exact' else 'RARITY_AND_SHAPE'}
                   for s in result.get('settlementItems') or []]
            if not slots:slots=result.get('settlementShapeSlots') or []
        if slots:
            self.flow_evidence.add('warehouse',{'scene':result.get('scene'),'slots':slots},self._observation_time,result.get('round'))
            result['auctionEvidence']=self.flow_evidence.snapshot()
