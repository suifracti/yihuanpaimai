"""Explicit Host-local warehouse source requests, separate from business FRAMEs."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import re
import threading
import time
import uuid

SCHEMA = 'native-warehouse-source.v1'
CONTROL_TYPE = 'native_warehouse_evidence_control'
EVENT_TYPE = 'native_warehouse_evidence'
PNG_ENCODING = 'opencv-bgr8-png-bound.v1'


class NativeWarehouseSourceCoordinator:
    def __init__(self, intake, *, send_control, source_root_provider,
                 clock=None, qpc=None, timers=True):
        self.intake = intake
        self._send_control = send_control
        self._root_provider = source_root_provider
        self._clock = clock or time.monotonic
        self._qpc = qpc or time.perf_counter_ns
        self._timers = timers
        self._lock = threading.RLock()
        self._source = None
        self._binding = self._lease = self._pending = self._last_closed = None
        self._state, self._reason = 'IDLE', None
        self._ordinal = 0
        self._deadline = self._pending_until = 0
        self._timer = None
        self._host_limits = {}
        self._saved_source = self._duplicate_proof = None
        # The evidence callback is the only producer. Ordinary business FRAME leases are not consulted.
        intake._source_provider = self.source_copy
        intake._source_validator = self._source_is_current

    def __getattr__(self, name):
        return getattr(self.intake, name)

    def source_copy(self):
        with self._lock:
            return copy.deepcopy(self._source)

    def prepare_manual(self):
        result = self.intake.prepare_manual()
        if result.get('ok'):
            result['confirmCaption'] = ('每次手动请求保全原游戏窗口客户端的一张新原帧；'
                '会话受16帧和绝对70秒预算限制，窗口不合格、映射变化或过期将停止。')
        return result

    def _source_is_current(self):
        return bool(self._state == 'REQUEST_PENDING' and self._pending and self._source
            and self._clock() < self._pending_until and self._clock() < self._deadline
            and 0 <= self._qpc() - self._source['sourceTimestampNs'] <= 2_000_000_000
            and self._same_contract(self.intake.source_contract()))

    def _reply(self, ok, reason):
        self._reason = reason
        return {'ok': ok, 'reason': reason, 'pageCount': len(self.intake.pages_copy())}

    def _command(self, operation, *, nonce=None):
        b = self._binding
        return {'type': CONTROL_TYPE, 'schemaVersion': SCHEMA, 'operation': operation,
            'commandId': uuid.uuid4().hex, 'nonce': nonce or uuid.uuid4().hex,
            'observationSessionId': b['scope']['observationSessionId'],
            'reviewSessionId': b['sessionId'], 'reviewGeneration': b['generation'],
            'recordStableKey': b['scope']['recordStableKey'],
            'expectedTargetInstance': copy.deepcopy(b['scope']['targetInstance']),
            'leaseToken': self._lease, 'requestOrdinal': self._ordinal}

    def _send(self, command):
        try:
            return bool(self._send_control(command))
        except Exception:
            return False

    def _schedule(self, seconds):
        if self._timer:
            self._timer.cancel()
        if self._timers:
            self._timer = threading.Timer(seconds, self.check_timeout)
            self._timer.daemon = True
            self._timer.start()

    def _cancel_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def start_manual(self, record_key=None, *, allow_window_scroll=False):
        with self.intake._scope_lock, self._lock:
            result = self.intake.start_manual(record_key)
            if not result['ok']:
                return result
            self._binding = self.intake.source_contract()
            self._lease = self._pending = self._source = None
            self._ordinal = 0
            self._host_limits = {}
            self._saved_source = self._duplicate_proof = None
            self._state = 'OPEN_PENDING'
            command = self._command('OPEN')
            command['allowWindowScroll'] = allow_window_scroll is True
            self._pending = command
            self._pending_until = self._clock() + 2
            if not self._send(command):
                self._close('NATIVE_SOURCE_HOST_UNAVAILABLE', cancel_intake=True)
                return self._reply(False, self._reason)
            self._schedule(2)
            return self._reply(True, 'SOURCE_OPEN_REQUESTED')

    def capture_manual_page(self):
        with self.intake._scope_lock, self._lock:
            self.check_timeout()
            if self._state != 'OPEN' or self._pending is not None:
                return self._reply(False, 'SOURCE_REQUEST_PENDING' if self._pending else 'NO_ACTIVE_SOURCE_LEASE')
            contract = self.intake.source_contract()
            if not self._same_contract(contract):
                self._close('SOURCE_SCOPE_CHANGED', cancel_intake=True)
                return self._reply(False, self._reason)
            w, h = self._host_limits['clientWidth'], self._host_limits['clientHeight']
            if contract['remainingPages'] <= 0 or self._host_limits['remainingSourcePages'] <= 0:
                self._close('SOURCE_LIMIT_REACHED')
                return self._reply(False, 'SOURCE_LIMIT_REACHED')
            if self._host_limits['remainingRawBytes'] < 54 + 4 * w * h:
                self._close('SOURCE_LIMIT_REACHED')
                return self._reply(False, 'SOURCE_LIMIT_REACHED')
            # Different counters: original BMP output vs exact accepted lossless PNG bytes.
            # A conservative BGR8-PNG reserve prevents writing an upstream original that cannot fit downstream.
            if contract['remainingPngBytes'] < 4 * w * h + 65536:
                self._close('PNG_BUDGET_INSUFFICIENT')
                return self._reply(False, 'PNG_BUDGET_INSUFFICIENT')
            self._ordinal += 1
            self._duplicate_proof = None
            command = self._command('REQUEST_PAGE')
            command.update(remainingPages=min(contract['remainingPages'], self._host_limits['remainingSourcePages']),
                remainingPngBytes=min(contract['remainingPngBytes'], self._host_limits['maxPngBytes']),
                pngEncoding=PNG_ENCODING)
            self._pending = command
            self._state = 'REQUEST_PENDING'
            self._pending_until = min(self._clock() + 5, self._deadline)
            if not self._send(command):
                self._close('NATIVE_SOURCE_SEND_FAILED', cancel_intake=True)
                return self._reply(False, self._reason)
            self._schedule(max(0, self._pending_until - self._clock()))
            return self._reply(True, 'SOURCE_REQUESTED')

    def source_session_snapshot(self):
        with self.intake._scope_lock, self._lock:
            self.check_timeout()
            return {'state': self._state, 'reason': self._reason, 'deadline': self._deadline,
                'binding': copy.deepcopy(self._binding), 'savedSource': copy.deepcopy(self._saved_source),
                'duplicateProof': copy.deepcopy(self._duplicate_proof), 'limits': copy.deepcopy(self._host_limits)}

    def lease_scope_is_current(self, scope):
        """Independent active SOURCE authority; never renew ordinary FRAME health."""
        with self._lock:
            return bool(self._binding and self._state in {'OPEN', 'REQUEST_PENDING', 'SCROLL_PENDING'}
                and self._clock() < self._deadline and all(scope.get(k) == self._binding['scope'].get(k)
                for k in ('recordStableKey', 'observationSessionId', 'targetInstance', 'matchGeneration')))

    def request_scroll_down(self):
        with self.intake._scope_lock, self._lock:
            self.check_timeout()
            if (self._state != 'OPEN' or self._pending or not self._saved_source
                    or self._host_limits.get('windowScrollSupported') is not True):
                return self._reply(False, 'WINDOW_SCROLL_UNAVAILABLE')
            if not self._same_contract(self.intake.source_contract()):
                self._close('SOURCE_SCOPE_CHANGED', cancel_intake=True)
                return self._reply(False, self._reason)
            command = self._command('SCROLL_DOWN')
            command.update(sourceLeaseId=self._saved_source['sourceLeaseId'], pixelSha256=self._saved_source['pixelSha256'])
            self._pending, self._state = command, 'SCROLL_PENDING'
            self._pending_until = min(self._clock() + 2, self._deadline)
            if not self._send(command):
                self._close('WINDOW_SCROLL_SEND_FAILED')
                return self._reply(False, self._reason)
            self._schedule(max(0, self._pending_until - self._clock()))
            return self._reply(True, 'WINDOW_SCROLL_REQUESTED')

    def _same_contract(self, contract):
        return bool(self._binding and contract['sessionId'] == self._binding['sessionId']
            and contract['generation'] == self._binding['generation']
            and contract['scope'] == self._binding['scope']
            and contract['state'] == 'MANUAL_CAPTURING')

    @staticmethod
    def _matches(event, binding):
        return bool(binding and type(event.get('reviewGeneration')) is int
            and event.get('reviewSessionId') == binding['sessionId']
            and event.get('reviewGeneration') == binding['generation']
            and event.get('observationSessionId') == binding['scope']['observationSessionId']
            and event.get('recordStableKey') == binding['scope']['recordStableKey']
            and event.get('targetInstance') == binding['scope']['targetInstance'])

    def on_event(self, event):
        with self.intake._scope_lock, self._lock:
            if (not isinstance(event, dict) or event.get('type') != EVENT_TYPE
                or event.get('schemaVersion') != SCHEMA or event.get('sourceKind') != 'native_wgc'
                or event.get('formalHistoryWriter') is not False):
                return
            scroll_event = (event.get('event') == 'SCROLLED' and event.get('inputActions') is True
                and self._state == 'SCROLL_PENDING' and self._pending
                and self._pending.get('operation') == 'SCROLL_DOWN' and self._request_matches(event))
            if event.get('inputActions') is not False and not scroll_event:
                return
            self.check_timeout()
            if self._state in {'CLOSED', 'ERROR', 'IDLE'} or not self._matches(event, self._binding):
                self._close_late_open(event)
                return
            if not self._same_contract(self.intake.source_contract()):
                self._close('SOURCE_SCOPE_CHANGED', cancel_intake=True)
                self._close_late_open(event)
                return
            kind = event.get('event')
            if kind == 'REJECTED' and self._state == 'OPEN_PENDING' and self._request_matches(event):
                self._close(event.get('reason') or 'SOURCE_OPEN_REJECTED')
                return
            if kind == 'OPENED':
                if self._state != 'OPEN_PENDING' or not self._request_matches(event):
                    return
                details = event.get('details') or {}
                try:
                    token = event['leaseToken']
                    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token):
                        raise ValueError()
                    for key in ('deadlineNs', 'clientWidth', 'clientHeight', 'remainingSourcePages', 'remainingRawBytes', 'maxPngBytes'):
                        if type(details[key]) is not int or details[key] <= 0:
                            raise ValueError()
                    if (details.get('pngEncoding') != PNG_ENCODING or details['clientWidth'] > 1920
                        or details['clientHeight'] > 1080 or details['remainingSourcePages'] > 16
                        or details['remainingRawBytes'] > 128 * 1024 * 1024
                        or details['maxPngBytes'] > 64 * 1024 * 1024):
                        raise ValueError()
                    remaining = (details['deadlineNs'] - self._qpc()) / 1_000_000_000
                    if not 0 < remaining <= 70:
                        raise ValueError()
                except (KeyError, TypeError, ValueError):
                    self._close('SOURCE_NEGOTIATION_REJECTED', cancel_intake=True)
                    self._close_late_open(event)
                    return
                self._lease = token
                self._host_limits = copy.deepcopy(details)
                self._deadline = self._clock() + remaining
                self._pending = None
                self._state, self._reason = 'OPEN', 'SOURCE_READY'
                self._schedule(remaining)
                return
            if event.get('leaseToken') != self._lease:
                return
            counters = event.get('details') or {}
            for key, maximum in (('remainingSourcePages', 16), ('remainingRawBytes', 128 * 1024 * 1024)):
                if type(counters.get(key)) is int and 0 <= counters[key] <= maximum:
                    self._host_limits[key] = counters[key]
            if kind == 'CLOSED':
                self._close(event.get('reason') or 'HOST_SOURCE_CLOSED', notify=False)
                return
            if not self._request_matches(event):
                return
            if kind == 'REJECTED':
                self._pending = None
                self._state, self._reason = 'OPEN', event.get('reason') or 'SOURCE_REJECTED'
                self._schedule(max(0, self._deadline - self._clock()))
            elif kind == 'RESULT' and event.get('reason') == 'DUPLICATE_PAGE':
                self._duplicate_proof = None
                try:
                    now = self._qpc()
                    if (self._state != 'REQUEST_PENDING' or not self._saved_source
                        or counters.get('pixelSha256') != self._saved_source['pixelSha256']
                        or counters.get('clientMap') != self._host_limits.get('clientMap')
                        or any(type(counters.get(k)) is not int for k in ('requestGateNs', 'sourceTimestampNs', 'frameSequence'))
                        or not 0 < counters['requestGateNs'] < counters['sourceTimestampNs'] <= now
                        or now - counters['sourceTimestampNs'] > 2_000_000_000
                        or counters['frameSequence'] <= self._saved_source['frameSequence']):
                        raise ValueError()
                    self._duplicate_proof = copy.deepcopy(counters)
                except (KeyError, TypeError, ValueError):
                    pass
                self._pending = None
                self._state, self._reason = 'OPEN', 'DUPLICATE_PAGE'
                self._schedule(max(0, self._deadline - self._clock()))
            elif kind == 'SOURCE' and self._state == 'REQUEST_PENDING':
                self._accept_source(event)
            elif kind == 'SCROLLED' and scroll_event:
                if (counters.get('direction') != 'DOWN' or counters.get('delta') != -120
                    or not self._saved_source or counters.get('sourceLeaseId') != self._saved_source['sourceLeaseId']):
                    self._close('WINDOW_SCROLL_PROOF_REJECTED')
                    return
                self._pending = None
                self._state, self._reason = 'OPEN', 'WINDOW_WHEEL_MESSAGE_SENT'
                self._schedule(max(0, self._deadline - self._clock()))

    def _request_matches(self, event):
        return bool(self._pending and type(event.get('requestOrdinal')) is int
            and event.get('commandId') == self._pending['commandId']
            and event.get('nonce') == self._pending['nonce']
            and event.get('requestOrdinal') == self._pending['requestOrdinal'])

    def _accept_source(self, event):
        source = event.get('source') or {}
        result = {'ok': False, 'reason': 'SOURCE_PROOF_REJECTED'}
        try:
            for key in ('width', 'height', 'stride', 'sourceTimestampNs', 'requestGateNs', 'frameSequence', 'workerFrameSequence', 'byteCount'):
                if type(source[key]) is not int or source[key] <= 0:
                    raise ValueError()
            w, h = source['width'], source['height']
            if (w != self._host_limits['clientWidth'] or h != self._host_limits['clientHeight']
                or source['stride'] != 4 * w or source['byteCount'] != 54 + 4 * w * h
                or source.get('clientMap') != self._host_limits['clientMap']
                or source['workerFrameSequence'] != source['frameSequence']
                or not source['requestGateNs'] < source['sourceTimestampNs'] <= self._qpc()
                or self._qpc() - source['sourceTimestampNs'] > 2_000_000_000):
                raise ValueError()
            if any(not re.fullmatch('[0-9a-f]{64}', source.get(key, '')) for key in ('bmpSha256', 'pixelSha256')):
                raise ValueError()
            if not re.fullmatch('[0-9a-f]{32}', source.get('sourceLeaseId', '')):
                raise ValueError()
            root = Path(self._root_provider()).resolve(strict=True)
            source_root = (root / 'warehouse-sources').resolve(strict=True)
            path = Path(source['path']).resolve(strict=True)
            if path.parent != source_root or path.name != source['sourceLeaseId'] + '.bmp':
                raise ValueError()
            with path.open('rb') as stream:
                raw = stream.read(8_294_454 + 1)
            if len(raw) != source['byteCount'] or hashlib.sha256(raw).hexdigest() != source['bmpSha256']:
                raise ValueError()
            del raw
            self._source = {'path': str(path), 'sourceRoot': str(source_root),
                'width': w, 'height': h, 'frameSequence': source['frameSequence'],
                'capturedAt': source['capturedAtUtc'], 'pixelSha256': source['pixelSha256'],
                'sourceTimestampNs': source['sourceTimestampNs'],
                'receivedAt': self._clock(), 'scope': copy.deepcopy(self._binding['scope'])}
            result = self.intake.capture_manual_page()
            if result['ok'] and not result.get('duplicate'):
                self._saved_source = copy.deepcopy(source)
        except (KeyError, OSError, TypeError, ValueError):
            pass
        finally:
            self._source = None
        ack = self._command('ACK_SOURCE', nonce=self._pending['nonce'])
        ack.update(sourceLeaseId=source.get('sourceLeaseId'), bmpSha256=source.get('bmpSha256'),
            pixelSha256=source.get('pixelSha256'),
            result='DUPLICATE' if result.get('duplicate') else 'SAVED' if result['ok'] else 'REJECTED')
        self._send(ack)
        self._pending = None
        self._state, self._reason = 'OPEN', result['reason']
        self._schedule(max(0, self._deadline - self._clock()))

    def _close_late_open(self, event):
        if event.get('event') != 'OPENED' or not self._matches(event, self._last_closed):
            return
        b = self._last_closed
        self._send({'type': CONTROL_TYPE, 'schemaVersion': SCHEMA, 'operation': 'CLOSE',
            'commandId': uuid.uuid4().hex, 'nonce': uuid.uuid4().hex,
            'observationSessionId': b['scope']['observationSessionId'], 'reviewSessionId': b['sessionId'],
            'reviewGeneration': b['generation'], 'recordStableKey': b['scope']['recordStableKey'],
            'expectedTargetInstance': b['scope']['targetInstance'], 'leaseToken': event.get('leaseToken')})

    def _close(self, reason, *, cancel_intake=False, notify=True):
        self._last_closed = copy.deepcopy(self._binding)
        if notify and self._binding:
            self._send(self._command('CLOSE'))
        self._cancel_timer()
        self._pending = self._source = None
        self._state, self._reason = 'CLOSED', reason
        if cancel_intake:
            self.intake.cancel_manual_capture()

    def check_timeout(self):
        with self.intake._scope_lock, self._lock:
            if self._state == 'OPEN_PENDING' and self._clock() >= self._pending_until:
                self._close('SOURCE_PUBLISH_UNSUPPORTED_OR_TIMEOUT')
            elif self._state in {'OPEN', 'REQUEST_PENDING', 'SCROLL_PENDING'} and self._clock() >= self._deadline:
                self._close('ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
            elif self._state in {'REQUEST_PENDING', 'SCROLL_PENDING'} and self._clock() >= self._pending_until:
                self._close('SOURCE_REQUEST_TIMEOUT')

    def close_source(self, reason):
        with self.intake._scope_lock, self._lock:
            self._close(reason)

    def finish_manual_capture(self, *, termination_reason='COMPLETE'):
        with self.intake._scope_lock, self._lock:
            if self._pending is not None:
                return self._reply(False, 'SOURCE_REQUEST_PENDING')
            self._close('MANUAL_FINISHED')
            return self.intake.finish_manual_capture(termination_reason=termination_reason)

    def cancel_manual_capture(self):
        with self.intake._scope_lock, self._lock:
            self._close('USER_CANCEL')
            return self.intake.cancel_manual_capture()

    def observation_ended(self, reason):
        with self.intake._scope_lock, self._lock:
            if self._state not in {'IDLE', 'CLOSED'}:
                self._close(reason, cancel_intake=True)

    def check_business_boundary(self, event):
        """Called after the unchanged ordinary handler; never refresh business health/facts."""
        with self.intake._scope_lock, self._lock:
            if self._state in {'IDLE', 'CLOSED'} or not self._binding:
                return
            incoming = event.get('observationSessionId')
            if event.get('status') == 'STARTING' and incoming != self._binding['scope']['observationSessionId']:
                self._close('OBSERVATION_SESSION_CHANGED', cancel_intake=True)
            elif incoming == self._binding['scope']['observationSessionId']:
                if event.get('status') in {'PAUSED', 'ERROR', 'STOPPED'}:
                    self._close(event.get('reason') or 'OBSERVATION_ENDED', cancel_intake=True)
                elif not self._same_contract(self.intake.source_contract()):
                    self._close('SOURCE_SCOPE_CHANGED', cancel_intake=True)
            # Launcher exit errors may lack a session id; the ordinary handler has
            # already invalidated health/scope. An ignored old event cannot change this contract.
            if self._state not in {'IDLE', 'CLOSED'} and not self._same_contract(self.intake.source_contract()):
                self._close('SOURCE_SCOPE_CHANGED', cancel_intake=True)

    def presentation_payload(self):
        with self.intake._scope_lock, self._lock:
            self.check_timeout()
            view = self.intake.presentation_payload()
            view['limits']['pixelsPerFrame'] = 1920 * 1080
            view.update(sourceState=self._state, sourceReason=self._reason, sourceLimits=copy.deepcopy(self._host_limits))
            messages = {'SOURCE_OPEN_REQUESTED': '正在建立手动原帧会话，尚未保存页面。',
                'SOURCE_REQUESTED': '正在等待本次手动请求之后的新原帧，尚未保存页面。',
                'SOURCE_PUBLISH_UNSUPPORTED_OR_TIMEOUT': 'Host 原帧能力未响应或不支持，未重发冻结帧。',
                'PNG_BUDGET_INSUFFICIENT': '剩余图片预算不足，未请求或保存新原图。',
                'SOURCE_LEASE_EXPIRED': '原帧租约已过期，保留已保存材料，未追加页面。',
                'SOURCE_LIMIT_REACHED': '已达本次原图数量或保存预算上限，未追加页面。',
                'SOURCE_PROOF_REJECTED': '原帧时序或保存证据校验失败，未接受页面。'}
            if self._reason in messages:
                view['message'] = messages[self._reason]
            elif self._reason:
                view['message'] += ' · ' + self._reason
            return view
