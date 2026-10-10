"""Explicit bounded Native warehouse automation; pixels and wheels belong to the Host lease."""
from __future__ import annotations

from native_capture_delivery import DELIVERY, independent_support

import copy
import hashlib
import json
import threading
import time
import uuid

import cv2
import numpy as np

from warehouse_scrollbar_observation import WarehouseScrollbarObserver, warehouse_search_roi
from warehouse_segment_overlap import align_warehouse_segments, DIR_DOWN, TerminalContinuity
from warehouse_support_frame import stationary_support_proof
from scene_anchors import settlement_title_visible
from native_warehouse_content_stability import content_stability
from native_warehouse_reveal_marker import RevealMarker
from native_warehouse_visible_content_gate import VisibleContentGate


class NativeWarehouseAutoCapture:
    def __init__(self, source, *, clock=None, timers=True, diagnostic_log=None,
                 claim_attempt=None, offline_content_gate=None, content_gate=None):
        self.source = source
        if offline_content_gate is not None and (not getattr(offline_content_gate, 'offline_only', False)
                or not getattr(source, 'offline_test_adapter', False)
                or source.intake.source_contract()['scope'].get('capturePolicy') != DELIVERY):
            raise ValueError('OFFLINE_CONTENT_ADAPTER_REQUIRED')
        if content_gate is not None and (not isinstance(content_gate, VisibleContentGate) or offline_content_gate is not None):
            raise ValueError('VISIBLE_CONTENT_ADAPTER_REQUIRED')
        self._configured_content_gate = content_gate
        self._content_gate = offline_content_gate
        self._diagnostic_log = diagnostic_log
        self._claim_attempt = claim_attempt
        self._clock = clock or time.monotonic
        self._timers = timers
        self._lock = source.intake._scope_lock
        self._active = False
        self._phase, self._reason = 'IDLE', None
        self._generation = 0
        self._token = self._timer = None
        self._timer_ticket = None
        self._deadline = self._due = 0
        self._anchor = self._observation = None
        self._seen_pages = self._scroll_count = 0
        self._post_scroll_frame_received = False
        self._observer = WarehouseScrollbarObserver()
        self._marker = None  # Lazy: strict mode does not depend on the reveal asset.
        self._retry_scope = self._support_floor = self._consumed_duplicate = None
        self._pixels_per_notch = None
        self._last_wheel_delta = -120
        self._tail_stationary = False
        self._terminal_continuity = TerminalContinuity()

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
                'confirmCaption': '程序只在本局结算仓库内自动向下翻页；不激活游戏、不移动鼠标。最多16张来源／32次请求、绝对70秒，滚动无效或证据不足即停止并保留原图。'}

    def confirm(self, token_id):
        with self._lock:
            token, self._token = self._token, None
            if (not token or token[0] != str(token_id) or self._clock() >= token[1]
                or self.source.intake.source_contract()['scope'] != token[2]):
                return {'ok': False, 'reason': 'ARMING_TOKEN_EXPIRED_OR_SCOPE_CHANGED'}
            if self._active:
                return {'ok': False, 'reason': 'ALREADY_RUNNING'}
            if self._claim_attempt is not None:
                try:
                    claim = self._claim_attempt(token[2])
                except Exception as exc:
                    return {'ok': False, 'reason': 'ATTEMPT_NOT_SAVED:' + type(exc).__name__}
                if not claim:
                    return {'ok': False, 'reason': 'RECORD_ALREADY_ATTEMPTED'}
            # Main is assembled before observation chooses its policy. Bind the
            # live gate to this armed SOURCE scope, not Main's startup default.
            if self._configured_content_gate is not None:
                self._content_gate = (self._configured_content_gate
                    if token[2].get('capturePolicy') == DELIVERY else None)
            source_options = ({'retain_independent_originals': True}
                if isinstance(self._content_gate, VisibleContentGate) and token[2].get('capturePolicy') == DELIVERY else {})
            result = self.source.start_manual(token[2]['recordStableKey'], allow_window_scroll=True, **source_options)
            if not result.get('ok'):
                return result
            if isinstance(self._content_gate, VisibleContentGate):
                self._content_gate.reset()
            self._generation += 1
            self._active, self._phase, self._reason = True, 'OPEN_SOURCE', None
            self._seen_pages = self._scroll_count = 0
            self._post_scroll_frame_received = False
            self._anchor = self._observation = None
            self._retry_scope = copy.deepcopy(token[2])
            self._support_floor = self._consumed_duplicate = None
            self._observer.reset()
            self._pixels_per_notch = None
            self._tail_stationary = False
            self._terminal_continuity = TerminalContinuity()
            self._deadline = self._clock() + 70
            self._diagnose('started', scope=token[2], savedPages=0, deadline=self._deadline)
            return {'ok': True, 'reason': 'NATIVE_AUTO_STARTED'}

    def start(self, arming_token=None):
        return self.confirm(arming_token)

    def on_event(self, event):
        with self._lock:
            if event.get('event') == 'CONTENT_HINT':
                if isinstance(self._content_gate, VisibleContentGate) and self._active and self._guard():
                    frame = self.source.read_content_hint(event)
                    if frame is not None:
                        hint = event['details']
                        ready = self._content_gate.sampling_hint(frame,
                            capture_id=hint['captureId'], readback_ns=hint['readbackNs'])
                        self._diagnose('sampling-hint', requestEligible=ready, sourceAuthority=False,
                            captureId=hint['captureId'], savedOriginals=self._seen_pages)
                return
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

    def note_offline_observation_hint(self, frame, *, scope, mapping, proof):
        """Offline staging seam. FRAME can time a request, never authorize a page.

        The live observer does not call this entry. It reuses WAIT_STABLE and
        the existing timer/lease instead of creating another observation FSM.
        """
        with self._lock:
            if (self._content_gate is None or not self._content_gate.offline_only
                    or not self._active or not self._guard()):
                return False
            accepted = self._content_gate.hint(frame, scope=scope, mapping=mapping,
                proof=proof, now_ns=round(self._clock()*1e9))
            self._diagnose('offline-observation-hint', accepted=accepted,
                requestEligible=self._content_gate.request_eligible(),
                sourceAuthority=False, scrollAllowed=False, coverageQualified=False)
            return accepted

    def _advance(self):
        if not self._active:
            return
        snap = self.source.source_session_snapshot()
        if self._delivery() and not self._guard(snap):
            return
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
            if (snap['reason'] == 'SCROLL_CONTENT_CHANGED_BEFORE_SEND' and snap.get('scrollRecheck')):
                # A validated Host receipt proves no adapter invocation. The
                # saved viewport stays evidence; no movement/bottom is inferred.
                self._wait_again(snap['reason'], self._anchor, self._observation,
                    self._observation['deliveryProof'])
            elif snap['reason'] != 'WINDOW_WHEEL_MESSAGE_SENT':
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
            if self._phase == 'WAIT_MOVED':
                self._post_scroll_frame_received = True
                self._diagnose('post-scroll-frame', pageOrdinal=self._seen_pages, duplicate=False,
                    deliveryProof=pages[-1].get('deliveryProof'), displacementVerified=False)
            try:
                crop, observation = self._read_page(pages[-1])
                self._page(crop, observation)
            except (ValueError, RuntimeError, OSError, KeyError, cv2.error) as exc:
                self._stop('PAGE_PROOF_REJECTED:' + str(exc))
            except Exception as exc:
                if self._content_gate is None:
                    raise
                prefix = 'OFFLINE_CONTENT_CALLBACK_FAILED' if self._content_gate.offline_only else 'CONTENT_CALLBACK_FAILED'
                self._stop(prefix + ':' + type(exc).__name__)
        elif snap['reason'] == 'DUPLICATE_PAGE':
            proof = snap.get('duplicateProof')
            saved = snap.get('savedSource')
            if self._delivery() and proof:
                receipt = (snap['requestAttempts'], (proof.get('deliveryProof') or {}).get('captureId'))
                if receipt == self._consumed_duplicate:
                    return  # The same accepted callback/status cannot renew a wait or scroll twice.
                self._consumed_duplicate = receipt
            if self._phase == 'WAIT_MOVED':
                self._post_scroll_frame_received = True
                self._diagnose('post-scroll-frame', duplicate=True, duplicateProof=proof, displacementVerified=False)
            # An explicitly fresh equal frame can prove stationary pixels, never a new page/identity scene.
            if (self._phase == 'WAIT_STABLE' and proof and saved
                and proof['pixelSha256'] == saved['pixelSha256'] and self._clock() >= self._due
                and (saved.get('capturePolicy') != DELIVERY
                    or independent_support(self._support_floor, proof.get('deliveryProof')))):
                self._observation['stableDeliveryProof'] = proof.get('deliveryProof')
                self._stable()
            else:
                self._stop('WINDOW_SCROLL_NO_PROGRESS' if self._phase == 'WAIT_MOVED' else
                    'INDEPENDENT_STABILITY_UNPROVEN' if self._delivery() and proof and
                    not independent_support(self._support_floor, proof.get('deliveryProof')) else 'STABILITY_UNPROVEN')
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
        if not settlement_title_visible(frame):
            raise ValueError('FRESH_PAGE_NOT_SETTLEMENT')
        observation = self._observer.observe(frame, source_id=desc['evidenceId'])
        observation['deliveryProof'] = copy.deepcopy(page.get('deliveryProof'))
        observation['capturePolicy'] = page.get('capturePolicy')
        if page.get('capturePolicy') == DELIVERY:
            if self._marker is None:
                self._marker = RevealMarker()
            observation['revealMarker'] = self._marker.observe(frame)
            observation['revealMarker'].update(originalSha256=desc['sha256'],
                captureId=page['deliveryProof']['captureId'])
        if self._content_gate is not None:
            profile_key = 'offlineContentProfile' if self._content_gate.offline_only else 'contentProfile'
            observation[profile_key] = self._content_gate.read_page(
                frame, page, self.source.intake.source_contract()['scope'],
                self.source.source_session_snapshot()['limits'].get('clientMap'),
                role='POST_SCROLL_PENDING' if self._phase == 'WAIT_MOVED' else 'UNQUALIFIED_OBSERVATION',
                review_binding={k:self.source.intake.source_contract()[k] for k in ('sessionId','generation')})
        x1, y1, x2, y2 = warehouse_search_roi(desc['width'], desc['height'])
        return frame[y1:y2, x1:x2].copy(), observation

    def _page(self, crop, observation):
        if self._delivery():
            if observation.get('capturePolicy') != DELIVERY:
                self._stop('SOURCE_POLICY_CHANGED')
                return
            if not self._guard() or not self._has_request_budget(
                    allow_consumed_frame=self._content_gate is not None) or not self._valid_marker(observation):
                return
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
            progress = self._scrollbar_progress(self._observation, observation)
            self._diagnose('scrollbar-progress', pageOrdinal=self._seen_pages, progress=progress)
            # BOTTOM is a localized endpoint candidate, not proof that a small
            # remaining tail cannot move. A sent tail probe must also preserve
            # the viewport and visible business content before collecting its
            # second independent support original.
            self._tail_stationary = False
            if (progress == 'WINDOW_SCROLL_NO_PROGRESS' and state == 'BOTTOM'
                    and self._observation['scrollState'] == 'BOTTOM'
                    and isinstance(self._content_gate, VisibleContentGate)
                    and all(observation.get(k) == self._observation.get(k)
                            for k in ('trackBox', 'thumbBox', 'thumbPosition'))):
                stationary = self._content_gate.compare(self._observation, observation)
                self._diagnose('tail-probe-content', qualification=stationary)
                if not stationary['qualified']:
                    self._stop('TAIL_STATIONARITY_UNPROVEN')
                    return
                self._tail_stationary = True
            elif progress != 'DOWN':
                self._stop(progress)
                return
            if not self._tail_stationary:
                motion = align_warehouse_segments(self._anchor, crop, required_direction=DIR_DOWN,
                    prev_id=self._observation.get('sourceId', ''), next_id=observation.get('sourceId', ''),
                    terminal_continuity=self._terminal_continuity)
                self._diagnose('image-overlap', pageOrdinal=self._seen_pages, alignment=motion)
                offset = motion.get('verticalOffsetPx')
                if (motion.get('status') != 'VERIFIED' or motion.get('direction') != DIR_DOWN
                    or not isinstance(offset, (int, float)) or isinstance(offset, bool)
                    or not np.isfinite(offset) or offset >= 0):
                    self._stop('OVERLAP_OR_SCROLL_PROGRESS_UNVERIFIED')
                    return
                self._pixels_per_notch = abs(offset) / (abs(self._last_wheel_delta) / 120)
        elif self._phase == 'WAIT_STABLE':
            if (observation.get('capturePolicy') == DELIVERY and state != 'NO_SCROLL'
                and (not self._observation.get('thumbBox') or not observation.get('thumbBox')
                    or any(self._observation.get(k) != observation.get(k)
                           for k in ('trackBox', 'thumbBox', 'thumbPosition')))):
                self._stop('STABLE_VIEWPORT_UNPROVEN')
                return
            if (observation.get('capturePolicy') == DELIVERY and not independent_support(
                    self._support_floor, observation.get('deliveryProof'))):
                self._stop('INDEPENDENT_STABILITY_UNPROVEN')
                return
            observation['stableBaseDeliveryProof'] = self._observation.get('deliveryProof')
            observation['stableDeliveryProof'] = observation.get('deliveryProof')
            if observation.get('capturePolicy') == DELIVERY:
                content = (self._content_gate.compare(self._observation, observation)
                    if self._content_gate is not None else content_stability(self._anchor, crop))
                observation['contentStability'] = content
                self._diagnose('content-stability', pageOrdinal=self._seen_pages, qualification=content)
                if not content['qualified']:
                    if content['reason'] in {'CONTENT_CHANGING', 'CONTENT_UNREVEALED_OR_UNKNOWN'}:
                        self._wait_again(content['reason'], crop, observation, observation['deliveryProof'])
                        return
                    self._stop(content['reason'])
                    return
            equal = self._anchor.shape == crop.shape and np.array_equal(self._anchor, crop)
            supported = (content['qualified'] if self._content_gate is not None
                else stationary_support_proof(self._anchor, crop) is not None)
            if (state != self._observation['scrollState'] or self._clock() < self._due
                or not (equal or supported) or float(crop.std()) < 8):
                self._stop('STABILITY_UNPROVEN')
                return
            self._anchor, self._observation = crop, observation
            self._stable()
            return
        self._anchor, self._observation = crop, observation
        self._support_floor = copy.deepcopy(observation.get('deliveryProof'))
        self._phase = 'WAIT_STABLE'
        self._schedule_page(.6 if self._delivery() else .25)

    @staticmethod
    def _scrollbar_progress(before, after):
        """Pixel/normalized thumb motion, independent of content fingerprint or message ACK."""
        try:
            track0, track1 = before['trackBox'], after['trackBox']
            thumb0, thumb1 = before['thumbBox'], after['thumbBox']
            pos0, pos1 = before['thumbPosition'], after['thumbPosition']
            values = [*track0, *track1, *thumb0, *thumb1, pos0, pos1]
            if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v)
                    for v in values) or any(len(box) != 4 for box in (track0, track1, thumb0, thumb1))
                    or track0 != track1 or track0[3] <= track0[1]
                    # Integer endpoint localization can round the same thumb
                    # length to adjacent pixels at a new scroll position.
                    or abs((thumb0[3] - thumb0[1]) - (thumb1[3] - thumb1[1])) > 1
                    or thumb0[3] <= thumb0[1] or thumb0[0::2] != thumb1[0::2]
                    or not (0 <= pos0 <= 1 and 0 <= pos1 <= 1)
                    or not (track0[1] <= thumb0[1] < thumb0[3] <= track0[3]
                            and track1[1] <= thumb1[1] < thumb1[3] <= track1[3])):
                return 'SCROLLBAR_PROGRESS_UNKNOWN'
            dy = thumb1[1] - thumb0[1]
            if dy < 0 or pos1 < pos0:
                return 'SCROLLBAR_REVERSED'
            if dy < 1 or pos1 <= pos0:
                return 'WINDOW_SCROLL_NO_PROGRESS'
            return 'DOWN'
        except (KeyError, TypeError, ValueError):
            return 'SCROLLBAR_PROGRESS_UNKNOWN'

    def _stable(self):
        # The fresh duplicate path also needs content qualification: unchanged
        # unrevealed silhouettes are not a stable page suitable for scrolling.
        if self._observation.get('capturePolicy') == DELIVERY:
            if not self._guard() or not self._has_request_budget(
                    allow_consumed_frame=self._content_gate is not None) or not self._valid_marker(self._observation):
                return
            support = self._observation.get('stableDeliveryProof')
            if not independent_support(self._support_floor, support):
                self._stop('INDEPENDENT_STABILITY_UNPROVEN')
                return
            if self._content_gate is not None:
                content = self._content_gate.final_support(self._observation)
                self._diagnose('content-stability-final', pageOrdinal=self._seen_pages, qualification=content)
                if not content['qualified']:
                    self._stop(content['reason'])
                    return
            if self._content_gate is None:
                content = content_stability(self._anchor, self._anchor)
                self._diagnose('content-stability-final', pageOrdinal=self._seen_pages, qualification=content)
                if not content['qualified']:
                    self._wait_again(content['reason'], self._anchor, self._observation, support)
                    return
                # Exact pixels/no detected outline establish only visible support.
                # Neither skip text nor its absence establishes reveal completion.
                self._observation['contentCompletionState'] = 'UNKNOWN'
                self._wait_again('CONTENT_COMPLETION_UNKNOWN', self._anchor, self._observation, support)
                return
        self._diagnose('stable-page', pageOrdinal=self._seen_pages, observation=self._observation)
        if self._content_gate is not None:
            self._content_gate.commit_support(self.source.intake, self._observation)
        state = self._observation['scrollState']
        if state == 'NO_SCROLL' or (state == 'BOTTOM' and
                (not isinstance(self._content_gate, VisibleContentGate) or self._tail_stationary)):
            self._stop('COMPLETE', complete=True)  # only the existing ledger may grant complete coverage
        elif self._seen_pages >= 16:
            self._stop('SOURCE_LIMIT_REACHED')
        elif self._content_gate is not None and self._request_attempts >= 32:
            self._stop('SOURCE_REQUEST_LIMIT_REACHED')
        else:
            self._phase = 'WAIT_SCROLL'
            self._post_scroll_frame_received = False
            delta = -120
            if self._observation.get('capturePolicy') == DELIVERY and state != 'BOTTOM':
                delta = self._scroll_delta()
            self._last_wheel_delta = delta
            self._diagnose('scroll-step', wheelDelta=delta, pixelsPerNotch=self._pixels_per_notch,
                predictedOnly=True, actualOverlapStillRequired=True, tailProbe=state == 'BOTTOM')
            result = (self.source.request_scroll_down(stable_proof=self._observation.get('stableDeliveryProof'),
                    base_proof=self._observation.get('stableBaseDeliveryProof') or self._observation.get('deliveryProof'),
                    wheel_delta=delta)
                if self._observation.get('capturePolicy') == DELIVERY else self.source.request_scroll_down())
            if not result.get('ok'):
                self._stop(result.get('reason') or 'WINDOW_SCROLL_FAILED')
            else:
                self._scroll_count += 1

    def _scroll_delta(self):
        track = self._observation['trackBox']; thumb = self._observation['thumbBox']
        visible = track[3] - track[1]
        # This build's retained real receipts: -120 moved 30px in a 560px viewport.
        # A prediction sizes one message; only the next actual alignment grants progression.
        unit = self._pixels_per_notch or 30 * visible / 560
        remaining = max(0, track[3] - thumb[3]) * visible / (thumb[3] - thumb[1])
        target = min(.5 * visible, remaining)
        return -120 * max(1, min(12, int(target / unit)))

    def _schedule_page(self, delay):
        self._cancel_page_timer('REPLACED_BY_NEW_PAGE_WAIT')
        self._due = min(self._clock() + delay, self._deadline)
        if self._timers:
            self._arm_due_timer()

    def _cancel_page_timer(self, reason):
        timer, ticket = self._timer, self._timer_ticket
        self._timer = self._timer_ticket = None  # Revoke even an already-entered callback.
        if timer is not None:
            timer.cancel()
            self._diagnose('page-timer-cancelled', timerId=ticket, reason=reason,
                due=self._due, deadline=self._deadline)

    def _arm_due_timer(self):
        # Preserve the original due/deadline. A coarse monotonic clock can still
        # report before due when a one-shot kernel wait wakes; do not lose that wait.
        ticket, generation = uuid.uuid4().hex, self._generation
        delay = max(.001, time.get_clock_info('monotonic').resolution, self._due - self._clock())
        self._timer_ticket = ticket
        try:
            self._timer = threading.Timer(delay, lambda: self._page_timer_fired(generation, ticket))
            self._timer.daemon = True
            self._diagnose('page-timer-registered', timerId=ticket, callbackGeneration=generation,
                clock=self._clock(), due=self._due, deadline=self._deadline, waitSeconds=delay)
            self._timer.start()
        except Exception as exc:
            self._diagnose('page-timer-start-failed', timerId=ticket, exceptionType=type(exc).__name__)
            self._stop('STABILITY_TIMER_START_FAILED:' + type(exc).__name__)

    def _page_timer_fired(self, generation, ticket):
        entered = time.perf_counter_ns()
        self._diagnose('page-timer-entered', timerId=ticket, callbackGeneration=generation,
            clock=self._clock(), due=self._due, deadline=self._deadline)
        with self._lock:
            self._diagnose('page-timer-lock-acquired', timerId=ticket,
                lockWaitMs=(time.perf_counter_ns() - entered) / 1e6)
            if not self._active or generation != self._generation or ticket != self._timer_ticket:
                self._diagnose('page-timer-obsolete', timerId=ticket, callbackGeneration=generation)
                return
            self._timer = self._timer_ticket = None
            try:
                self.poll(generation)
            except Exception as exc:
                # Unknown callback errors are terminal, never a reason to renew a lease.
                self._diagnose('page-timer-callback-failed', timerId=ticket, exceptionType=type(exc).__name__)
                self._stop('STABILITY_TIMER_CALLBACK_FAILED:' + type(exc).__name__)

    def _delivery(self):
        return bool(self._retry_scope and self._retry_scope.get('capturePolicy') == DELIVERY)

    @property
    def _request_attempts(self):
        return self.source.source_session_snapshot()['requestAttempts']

    def _guard(self, snap=None):
        """Rechecks keep the same SOURCE authority; no retry can renew it."""
        snap = snap if snap is not None else self.source.source_session_snapshot()
        if snap['state'] == 'CLOSED':
            self._stop(snap.get('reason') or 'SOURCE_CLOSED')
            return False
        contract = self.source.intake.source_contract()
        binding = snap.get('binding')
        if (contract['scope'] != self._retry_scope or (binding and
                any(contract.get(k) != binding.get(k) for k in ('sessionId', 'generation', 'scope', 'state')))):
            self._stop('SOURCE_SCOPE_CHANGED')
            return False
        count = snap.get('requestAttempts')
        if type(count) is not int or not 0 <= count <= 32:
            self._stop('SOURCE_REQUEST_COUNTER_UNPROVEN')
            return False
        # OPEN_PENDING has no negotiated Host deadline yet.
        if snap['state'] != 'OPEN_PENDING':
            self._deadline = min(self._deadline, snap['deadline'])
        if self._clock() >= self._deadline:
            self._stop('ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
            return False
        return True

    def _valid_marker(self, observation):
        marker = observation.get('revealMarker')
        if not isinstance(marker, dict) or marker.get('status') not in {'PRESENT', 'NOT_DETECTED'}:
            self._stop('REVEAL_MARKER_READ_UNPROVEN')
            return False
        return True

    def _has_request_budget(self, *, allow_consumed_frame=False):
        if allow_consumed_frame:
            return True  # _guard validates the counters; no new request/action is granted here.
        if self._request_attempts >= 32:
            self._stop('SOURCE_REQUEST_LIMIT_REACHED')
            return False
        if len(self.source.pages_copy()) >= 16:
            self._stop('SOURCE_LIMIT_REACHED')
            return False
        return True

    def _wait_again(self, cause, crop, observation, support):
        if not self._guard() or not self._has_request_budget():
            return
        self._anchor = crop.copy()
        self._observation = copy.deepcopy(observation)
        self._observation.pop('stableDeliveryProof', None)
        self._observation.pop('stableBaseDeliveryProof', None)
        self._support_floor = copy.deepcopy(support)
        self._phase = 'WAIT_STABLE'
        if isinstance(self._content_gate, VisibleContentGate):
            self._content_gate.require_sampling_hint(support['readbackCompletedNs'])
        remaining = min(16 - len(self.source.pages_copy()), 32 - self._request_attempts)
        delay = (.6 if isinstance(self._content_gate, VisibleContentGate)
            else max(.6, (self._deadline - self._clock()) / (2 * remaining)))
        self._diagnose('stability-recheck', cause=cause, captureId=support['captureId'],
            requestAttempts=self._request_attempts, savedOriginals=len(self.source.pages_copy()),
            deadline=self._deadline, nextRequestDelaySeconds=delay,
            scrollAllowed=False, coverageQualified=False)
        self._schedule_page(delay)  # Only requests another independent frame; elapsed time never grants stability.

    def poll(self, generation=None):
        with self._lock:
            if not self._active or (generation is not None and generation != self._generation):
                return
            if self._delivery() and not self._guard():
                return
            self._diagnose('page-wait-checked', clock=self._clock(), due=self._due,
                deadline=self._deadline, sourceState=self.source.source_session_snapshot()['state'])
            if self._clock() >= self._deadline:
                self._stop('ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
            elif self._clock() >= self._due:
                self._cancel_page_timer('DUE_REQUEST_TAKES_OWNERSHIP')
                self._request_page()
            elif self._timers and self._timer is None:
                self._diagnose('page-timer-early-wake', clock=self._clock(), due=self._due,
                    deadline=self._deadline)
                self._arm_due_timer()

    def _request_page(self):
        if not self._active:
            return
        if self._delivery():
            if not self._guard() or not self._has_request_budget():
                return
            if self.source.source_session_snapshot()['state'] != 'OPEN':
                return  # One existing SOURCE request owns the slot until its result/timeout.
            if (self._content_gate is not None and self._seen_pages
                    and self._phase == 'WAIT_STABLE' and not self._content_gate.request_eligible()):
                self._diagnose('sampling-hint-awaiting', sourceAuthority=False, deadline=self._deadline)
                self._schedule_page(.6)  # No time-based release; poll still enforces the original deadline.
                return
            self._diagnose('stability-request', nextRequestAttempt=self._request_attempts + 1,
                deadline=self._deadline)
        if self._clock() >= self._deadline:
            self._stop('ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
            return
        result = self.source.capture_manual_page()
        self._diagnose('page-request-result', ok=result.get('ok'), reason=result.get('reason'),
            sourceState=self.source.source_session_snapshot(), deadline=self._deadline)
        if not result.get('ok'):
            self._stop(result.get('reason') or 'SOURCE_FAILED')

    def _stop(self, reason, *, complete=False):
        self._diagnose('capture-ended', reason=reason, savedPages=len(self.source.pages_copy()),
            scrollRequests=self._scroll_count, finalizationReason='COMPLETE' if complete else 'INCOMPLETE',
            postScrollFrameReceived=self._post_scroll_frame_received, completeCoverageMustBeGrantedByLedger=True)
        self._active, self._phase, self._reason = False, 'STOPPED', reason
        self._generation += 1
        self._cancel_page_timer(reason)
        self._anchor = self._observation = self._support_floor = self._retry_scope = None
        self._consumed_duplicate = None
        self.source.close_source(reason)
        if self._content_gate is not None:
            self._content_gate.release()
        if self.source.pages_copy() and self.source.intake.source_contract()['state'] == 'MANUAL_CAPTURING':
            options = ({'qualified_evidence_ids': self._content_gate.representatives()}
                if self._content_gate is not None else {})
            result = self.source.finish_manual_capture(termination_reason='COMPLETE' if complete else 'INCOMPLETE', **options)
            self._diagnose('finalization-request', result=result)

    def stop(self):
        with self._lock:
            if self._active:
                self._stop('USER_STOP')
                return {'ok': True, 'reason': 'STOP_REQUESTED'}
            return self.source.cancel_manual_capture()

    def presentation_payload(self):
        with self._lock:
            if self._active:
                self._advance()
            view = self.source.presentation_payload()
            if self._active:
                view.update(available=True, state='CAPTURING',
                    stopAvailable=self._active, automaticPhase=self._phase, scrollRequestCount=self._scroll_count)
                view['message'] = f'Native 自动收页 · 已保存 {len(self.source.pages_copy())} 页 · {self._phase}'
                if self._active and self._phase == 'WAIT_STABLE' and self._delivery():
                    view['message'] = (f'交付时序自动收页 · 原图 {len(self.source.pages_copy())} 张 · '
                        f'当前可见内容尚无独立支持，尚未证明覆盖 · 请求 {self._request_attempts}/32')
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
