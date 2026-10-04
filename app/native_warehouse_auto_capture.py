"""Explicit bounded Native warehouse automation; pixels and wheels belong to the Host lease."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid

import cv2
import numpy as np

from warehouse_scrollbar_observation import WarehouseScrollbarObserver, warehouse_search_roi
from warehouse_segment_overlap import align_warehouse_segments, DIR_DOWN
from warehouse_support_frame import stationary_support_proof


class NativeWarehouseAutoCapture:
    def __init__(self, source, *, clock=None, timers=True, diagnostic_log=None):
        self.source = source
        self._diagnostic_log = diagnostic_log
        self._clock = clock or time.monotonic
        self._timers = timers
        self._lock = source.intake._scope_lock
        self._active = False
        self._phase, self._reason = 'IDLE', None
        self._generation = 0
        self._token = self._timer = None
        self._deadline = self._due = 0
        self._anchor = self._observation = None
        self._seen_pages = self._scroll_count = 0
        self._observer = WarehouseScrollbarObserver()

    def __getattr__(self, name):
        return getattr(self.source, name)

    def _diagnose(self, kind, **details):
        if self._diagnostic_log is not None:
            try:
                self._diagnostic_log(json.dumps({'kind': kind, 'observedMonotonicNs': time.monotonic_ns(),
                    'generation': self._generation, 'phase': self._phase, **details}, ensure_ascii=False))
            except Exception:
                pass  # Text diagnostics cannot grant authority or bypass a capture gate.

    @property
    def _running(self):
        return self._active

    def prepare(self):
        with self._lock:
            if self._active:
                return {'ok': False, 'reason': 'ALREADY_RUNNING'}
            ready = self.source.prepare_manual()
            if not ready.get('ok'):
                return ready
            token = uuid.uuid4().hex
            self._token = (token, self._clock() + 15, copy.deepcopy(self.source.intake.source_contract()['scope']))
            return {'ok': True, 'armingToken': token,
                'confirmCaption': '程序只在本局结算仓库内自动向下翻页；不激活游戏、不移动鼠标。最多16页、绝对70秒，滚动无效或证据不足即停止并保留原图。'}

    def confirm(self, token_id):
        with self._lock:
            token, self._token = self._token, None
            if (not token or token[0] != str(token_id) or self._clock() >= token[1]
                or self.source.intake.source_contract()['scope'] != token[2]):
                return {'ok': False, 'reason': 'ARMING_TOKEN_EXPIRED_OR_SCOPE_CHANGED'}
            if self._active:
                return {'ok': False, 'reason': 'ALREADY_RUNNING'}
            result = self.source.start_manual(token[2]['recordStableKey'], allow_window_scroll=True)
            if not result.get('ok'):
                return result
            self._generation += 1
            self._active, self._phase, self._reason = True, 'OPEN_SOURCE', None
            self._seen_pages = self._scroll_count = 0
            self._anchor = self._observation = None
            self._observer.reset()
            self._deadline = self._clock() + 70
            self._diagnose('started', scope=token[2], savedPages=0, deadline=self._deadline)
            return {'ok': True, 'reason': 'NATIVE_AUTO_STARTED'}

    def start(self, arming_token=None):
        return self.confirm(arming_token)

    def on_event(self, event):
        with self._lock:
            self.source.on_event(event)
            if self._active:
                self._diagnose('source-event', receivedEvent=event,
                    sourceState=self.source.source_session_snapshot())
            self._advance()

    def check_business_boundary(self, event):
        with self._lock:
            self.source.check_business_boundary(event)
            self._advance()

    def observation_ended(self, reason):
        with self._lock:
            self.source.observation_ended(reason)
            self._advance()

    def _advance(self):
        if not self._active:
            return
        snap = self.source.source_session_snapshot()
        if self._clock() >= self._deadline:
            self._stop('ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
            return
        if snap['state'] == 'CLOSED':
            self._stop(snap['reason'] or 'SOURCE_CLOSED')
            return
        if snap['state'] != 'OPEN':
            return
        self._deadline = min(self._deadline, snap['deadline'])
        if self._phase == 'OPEN_SOURCE':
            if snap['limits'].get('windowScrollSupported') is not True:
                self._stop('WINDOW_SCROLL_UNSUPPORTED')
            else:
                self._phase = 'WAIT_INITIAL'
                self._request_page()
            return
        if self._phase == 'WAIT_SCROLL':
            if snap['reason'] != 'WINDOW_WHEEL_MESSAGE_SENT':
                self._stop(snap['reason'] or 'WINDOW_SCROLL_FAILED')
            else:
                self._phase = 'WAIT_MOVED'
                self._schedule_page(.35)
            return
        if self._phase not in {'WAIT_INITIAL', 'WAIT_MOVED', 'WAIT_STABLE'}:
            return
        if snap['reason'] == 'PAGE_ACCEPTED':
            pages = self.source.pages_copy()
            if len(pages) <= self._seen_pages:
                return  # ACK/status events cannot process a saved page twice.
            self._seen_pages = len(pages)
            self._diagnose('original-saved', pageOrdinal=self._seen_pages, page=pages[-1])
            try:
                crop, observation = self._read_page(pages[-1])
                self._page(crop, observation)
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                self._stop('PAGE_PROOF_REJECTED:' + type(exc).__name__)
        elif snap['reason'] == 'DUPLICATE_PAGE':
            proof = snap.get('duplicateProof')
            saved = snap.get('savedSource')
            # An explicitly fresh equal frame can prove stationary pixels, never a new page/identity scene.
            if (self._phase == 'WAIT_STABLE' and proof and saved
                and proof['pixelSha256'] == saved['pixelSha256'] and self._clock() >= self._due):
                self._stable()
            else:
                self._stop('WINDOW_SCROLL_NO_PROGRESS' if self._phase == 'WAIT_MOVED' else 'STABILITY_UNPROVEN')
        elif snap['reason'] not in {'SOURCE_READY', 'SOURCE_REQUESTED', 'SAVED', 'WINDOW_WHEEL_MESSAGE_SENT'}:
            self._stop(snap['reason'] or 'SOURCE_FAILED')

    def _read_page(self, page):
        desc = page['descriptor']
        raw = self.source.intake.evidence_store.load_original(desc)
        if hashlib.sha256(raw).hexdigest() != desc['sha256']:
            raise ValueError('SOURCE_HASH_CHANGED')
        frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None or frame.shape[:2] != (desc['height'], desc['width']):
            raise ValueError('GEOMETRY_CHANGED')
        observation = self._observer.observe(frame, source_id=desc['evidenceId'])
        x1, y1, x2, y2 = warehouse_search_roi(desc['width'], desc['height'])
        return frame[y1:y2, x1:x2].copy(), observation

    def _page(self, crop, observation):
        state = observation.get('scrollState')
        self._diagnose('scrollbar-observation', pageOrdinal=self._seen_pages, observation=observation)
        if state not in {'TOP', 'MIDDLE', 'BOTTOM', 'NO_SCROLL'}:
            self._stop('OBSERVER_UNKNOWN')
            return
        if self._phase == 'WAIT_INITIAL':
            if state not in {'TOP', 'NO_SCROLL'}:
                self._stop('START_REQUIRES_TOP')
                return
        elif self._phase == 'WAIT_MOVED':
            motion = align_warehouse_segments(self._anchor, crop, required_direction=DIR_DOWN)
            self._diagnose('image-overlap', pageOrdinal=self._seen_pages, alignment=motion)
            offset = motion.get('verticalOffsetPx')
            if (motion.get('status') != 'VERIFIED' or motion.get('direction') != DIR_DOWN
                or not isinstance(offset, (int, float)) or isinstance(offset, bool)
                or not np.isfinite(offset) or offset >= 0):
                self._stop('OVERLAP_OR_SCROLL_PROGRESS_UNVERIFIED')
                return
        elif self._phase == 'WAIT_STABLE':
            equal = self._anchor.shape == crop.shape and np.array_equal(self._anchor, crop)
            supported = stationary_support_proof(self._anchor, crop) is not None
            if (state != self._observation['scrollState'] or self._clock() < self._due
                or not (equal or supported) or float(crop.std()) < 8):
                self._stop('STABILITY_UNPROVEN')
                return
            self._anchor, self._observation = crop, observation
            self._stable()
            return
        self._anchor, self._observation = crop, observation
        self._phase = 'WAIT_STABLE'
        self._schedule_page(.25)

    def _stable(self):
        self._diagnose('stable-page', pageOrdinal=self._seen_pages, observation=self._observation)
        if self._observation['scrollState'] in {'BOTTOM', 'NO_SCROLL'}:
            self._stop('COMPLETE', complete=True)  # only the existing ledger may grant complete coverage
        elif self._seen_pages >= 16:
            self._stop('SOURCE_LIMIT_REACHED')
        else:
            self._phase = 'WAIT_SCROLL'
            result = self.source.request_scroll_down()
            if not result.get('ok'):
                self._stop(result.get('reason') or 'WINDOW_SCROLL_FAILED')
            else:
                self._scroll_count += 1

    def _schedule_page(self, delay):
        if self._timer:
            self._timer.cancel()
        self._due = min(self._clock() + delay, self._deadline)
        generation = self._generation
        if self._timers:
            self._timer = threading.Timer(max(0, self._due - self._clock()), lambda: self.poll(generation))
            self._timer.daemon = True
            self._timer.start()

    def poll(self, generation=None):
        with self._lock:
            if not self._active or (generation is not None and generation != self._generation):
                return
            if self._clock() >= self._deadline:
                self._stop('ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
            elif self._clock() >= self._due:
                self._request_page()

    def _request_page(self):
        if not self._active:
            return
        if self._clock() >= self._deadline:
            self._stop('ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
            return
        result = self.source.capture_manual_page()
        if not result.get('ok'):
            self._stop(result.get('reason') or 'SOURCE_FAILED')

    def _stop(self, reason, *, complete=False):
        self._diagnose('capture-ended', reason=reason, savedPages=len(self.source.pages_copy()),
            scrollRequests=self._scroll_count, finalizationReason='COMPLETE' if complete else 'INCOMPLETE',
            completeCoverageMustBeGrantedByLedger=True)
        self._active, self._phase, self._reason = False, 'STOPPED', reason
        self._generation += 1
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self.source.close_source(reason)
        if self.source.pages_copy() and self.source.intake.source_contract()['state'] == 'MANUAL_CAPTURING':
            self.source.finish_manual_capture(termination_reason='COMPLETE' if complete else 'INCOMPLETE')

    def stop(self):
        with self._lock:
            if self._active:
                self._stop('USER_STOP')
                return {'ok': True, 'reason': 'STOP_REQUESTED'}
            return self.source.cancel_manual_capture()

    def presentation_payload(self):
        with self._lock:
            view = self.source.presentation_payload()
            if self._active:
                self._advance()
                view = self.source.presentation_payload()
                view.update(available=True, state='CAPTURING' if self._active else view['state'],
                    stopAvailable=self._active, automaticPhase=self._phase, scrollRequestCount=self._scroll_count)
                view['message'] = f'Native 自动收页 · 已保存 {len(self.source.pages_copy())} 页 · {self._phase}'
            else:
                ready = self.source.prepare_manual()
                view['available'] = bool(ready.get('ok'))
                if self._reason:
                    view['automaticTerminationReason'] = self._reason
                    messages = {'USER_STOP': '已停止自动收页，原图保留。',
                        'WINDOW_SCROLL_NO_PROGRESS': '滚动消息未产生可核实的位移，已停止；原图保留。',
                        'OVERLAP_OR_SCROLL_PROGRESS_UNVERIFIED': '无法证明跨页位移和重叠，已停止；原图保留。',
                        'STABILITY_UNPROVEN': '仓库画面稳定性证据不足，已停止；原图保留。',
                        'WINDOW_SCROLL_UNSUPPORTED': '当前原生采集入口不支持窗口滚动，未操作游戏。',
                        'ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED': '结算采集截止，未延长预算；原图保留。',
                        'COMPLETE': '自动翻页已结束，正在依据保存的原图核对覆盖。'}
                    view['message'] = messages.get(self._reason, f'自动收页已停止 · {self._reason} · 原图保留。')
                elif ready.get('ok') and view.get('state') == 'IDLE':
                    view['message'] = '结算仓库可自动翻页；点击“采集完整仓库”开始。'
            return view
