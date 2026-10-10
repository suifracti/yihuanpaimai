"""Explicit Host-local warehouse source requests, separate from business FRAMEs."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import re
import threading
import time
import uuid

from native_capture_delivery import DELIVERY, STRICT, validate_delivery, independent_support

SCHEMA = 'native-warehouse-source.v1'
SCHEMA_V2 = 'native-warehouse-source.v2'
CONTROL_TYPE = 'native_warehouse_evidence_control'
EVENT_TYPE = 'native_warehouse_evidence'
PNG_ENCODING = 'opencv-bgr8-png-bound.v1'
MAX_TRIGGER_PROBES = 32
MIN_TRIGGER_PROBE_INTERVAL_NS = 600_000_000


class NativeWarehouseSourceCoordinator:
    def __init__(self, intake, *, send_control, source_root_provider,
                 clock=None, qpc=None, timers=True, evidence_only=False):
        self.intake = intake
        self._send_control = send_control
        self._root_provider = source_root_provider
        self._clock = clock or time.monotonic
        self._qpc = qpc or time.perf_counter_ns
        self._timers = timers
        self._evidence_only = evidence_only is True
        self._lock = threading.RLock()
        self._source = None
        self._binding = self._lease = self._pending = self._last_closed = None
        self._state, self._reason = 'IDLE', None
        self._ordinal = 0
        self._last_scroll_ns = 0
        self._deadline = self._pending_until = 0
        self._timer = None
        self._host_limits = {}
        self._saved_source = self._duplicate_proof = None
        self._scroll_recheck = None
        self._trigger_watch = None
        # The evidence callback is the only producer. Ordinary business FRAME leases are not consulted.
        intake._source_provider = self.source_copy
        intake._source_validator = self._source_is_current

    def __getattr__(self, name):
        return getattr(self.intake, name)

    def _delivery(self):
        return bool(self._binding and self._binding['scope'].get('capturePolicy') == DELIVERY)

    def _schema(self):
        return SCHEMA_V2 if self._delivery() else SCHEMA

    def source_copy(self):
        with self._lock:
            return copy.deepcopy(self._source)

    def prepare_manual(self):
        result = self.intake.prepare_manual()
        if result.get('ok'):
            result['capturePolicy'] = self.intake.source_contract()['scope'].get('capturePolicy', STRICT)
            result['confirmCaption'] = ('每次手动请求保全原游戏窗口客户端的一张新原帧；'
                '会话受16帧和绝对70秒预算限制，窗口不合格、映射变化或过期将停止。')
        if result.get('ok') and result.get('capturePolicy') == DELIVERY:
            result['confirmCaption'] = '交付时序原帧：先保存再核对；不能证明请求后渲染或来源绝对年龄。16张来源／32次请求／70秒，不自动降级。'
        return result

    def _source_is_current(self):
        return bool(self._state == 'REQUEST_PENDING' and self._pending and self._source
            and self._clock() < self._pending_until and self._clock() < self._deadline
            and (validate_delivery(self._source.get('deliveryProof'), self._qpc(),
                    session=self._binding['scope']['observationSessionId'], require_progress=True) is None
                if self._delivery() else 0 <= self._qpc() - self._source['sourceTimestampNs'] <= 2_000_000_000)
            and self._same_contract(self.intake.source_contract()))

    def _reply(self, ok, reason):
        self._reason = reason
        return {'ok': ok, 'reason': reason, 'pageCount': len(self.intake.pages_copy())}

    def _command(self, operation, *, nonce=None):
        b = self._binding
        return {'type': CONTROL_TYPE, 'schemaVersion': self._schema(), 'operation': operation,
            'commandId': uuid.uuid4().hex, 'nonce': nonce or uuid.uuid4().hex,
            'observationSessionId': b['scope']['observationSessionId'],
            'reviewSessionId': b['sessionId'], 'reviewGeneration': b['generation'],
            'recordStableKey': b['scope']['recordStableKey'],
            'expectedTargetInstance': copy.deepcopy(b['scope']['targetInstance']),
            'leaseToken': self._lease, 'requestOrdinal': self._ordinal,
            'matchGeneration': b['scope']['matchGeneration']}

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

    def start_manual(self, record_key=None, *, allow_window_scroll=False, retain_independent_originals=False):
        with self.intake._scope_lock, self._lock:
            if self._evidence_only and (allow_window_scroll or not retain_independent_originals):
                return self._reply(False, 'EVIDENCE_ONLY_SOURCE_REQUIRED')
            if retain_independent_originals and self.intake.source_contract()['scope'].get('capturePolicy') != DELIVERY:
                return self._reply(False, 'EVIDENCE_ONLY_SOURCE_REQUIRED')
            result = self.intake.start_manual(record_key,
                **({'retain_independent_originals': True} if retain_independent_originals else {}))
            if not result['ok']:
                return result
            self._binding = self.intake.source_contract()
            # Keep the watch scope through prepare/start_manual; the normal OPEN below
            # revokes the Host-side probe slot after this SOURCE binding exists.
            self._trigger_watch = None
            self._lease = self._pending = self._source = None
            self._ordinal = 0
            self._last_scroll_ns = 0
            self._host_limits = {}
            self._saved_source = self._duplicate_proof = None
            self._scroll_recheck = None
            self._state = 'OPEN_PENDING'
            command = self._command('OPEN')
            command['allowWindowScroll'] = allow_window_scroll is True
            command['retainIndependentOriginals'] = retain_independent_originals is True
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
            if self._evidence_only and self._ordinal >= 14:
                self._close('EVIDENCE_REQUEST_LIMIT_REACHED')
                return self._reply(False, 'EVIDENCE_REQUEST_LIMIT_REACHED')
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
            self._scroll_recheck = None
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
                'requestAttempts': self._ordinal,
                'binding': copy.deepcopy(self._binding), 'savedSource': copy.deepcopy(self._saved_source),
                'duplicateProof': copy.deepcopy(self._duplicate_proof),
                'scrollRecheck': copy.deepcopy(self._scroll_recheck), 'limits': copy.deepcopy(self._host_limits)}

    def lease_scope_is_current(self, scope):
        """Independent active SOURCE authority; never renew ordinary FRAME health."""
        with self._lock:
            return bool(self._binding and self._state in {'OPEN_PENDING', 'OPEN', 'REQUEST_PENDING', 'SCROLL_PENDING'}
                and self._clock() < self._deadline and all(scope.get(k) == self._binding['scope'].get(k)
                for k in ('recordStableKey', 'observationSessionId', 'targetInstance', 'matchGeneration')))

    def arm_trigger_watch(self, scope, *, deadline_ns, client_map):
        with self.intake._scope_lock, self._lock:
            self.check_timeout()
            if (not isinstance(scope, dict) or scope.get('scene') != 'SETTLEMENT'
                    or not isinstance(client_map, str) or not client_map
                    or type(deadline_ns) is not int):
                return {'ok': False, 'reason': 'TRIGGER_CONTEXT_INVALID'}
            remaining = deadline_ns - self._qpc()
            if not 0 < remaining <= 70_000_000_000:
                return {'ok': False, 'reason': 'TRIGGER_DEADLINE_EXPIRED'}
            current = self.intake.source_contract()['scope']
            if not self._same_scope_authority(scope, current):
                return {'ok': False, 'reason': 'TRIGGER_SCOPE_CHANGED'}
            if self._binding is not None or self._state not in {'IDLE', 'CLOSED'}:
                return {'ok': False, 'reason': 'SOURCE_ALREADY_ACTIVE'}
            if self._trigger_watch is not None:
                if (self._trigger_watch['scope'] == scope and self._trigger_watch['deadlineNs'] == deadline_ns
                        and self._trigger_watch['clientMap'] == client_map):
                    return {'ok': True, 'reason': 'TRIGGER_WATCH_ALREADY_ARMED',
                        'watchId': self._trigger_watch['watchId']}
                return {'ok': False, 'reason': 'TRIGGER_WATCH_ALREADY_ACTIVE'}
            watch_id = uuid.uuid4().hex
            watch = {'watchId': watch_id, 'scope': copy.deepcopy(scope), 'deadlineNs': deadline_ns,
                'clientMap': client_map, 'armed': False, 'lastOrdinal': 0, 'lastSequence': 0,
                'pendingProbeId': None, 'pendingOrdinal': None,
                'deadlineAt': self._clock() + remaining / 1_000_000_000}
            schema = SCHEMA_V2 if scope.get('capturePolicy') == DELIVERY else SCHEMA
            command = {'type': CONTROL_TYPE, 'schemaVersion': schema, 'operation': 'WATCH_TRIGGER',
                'commandId': uuid.uuid4().hex, 'nonce': uuid.uuid4().hex,
                'observationSessionId': scope['observationSessionId'], 'watchId': watch_id,
                'recordStableKey': scope['recordStableKey'], 'expectedTargetInstance': copy.deepcopy(scope['targetInstance']),
                'matchGeneration': scope['matchGeneration'], 'clientMap': client_map,
                'maxProbes': MAX_TRIGGER_PROBES, 'minimumIntervalNs': MIN_TRIGGER_PROBE_INTERVAL_NS}
            watch['armCommandId'] = command['commandId']
            self._trigger_watch = watch
            if not self._send(command):
                self._trigger_watch = None
                return {'ok': False, 'reason': 'TRIGGER_WATCH_SEND_FAILED'}
            self._schedule(remaining / 1_000_000_000)
            return {'ok': True, 'reason': 'TRIGGER_WATCH_REQUESTED', 'watchId': watch_id,
                'deadlineNs': deadline_ns, 'probeLimit': MAX_TRIGGER_PROBES,
                'minimumIntervalNs': MIN_TRIGGER_PROBE_INTERVAL_NS}

    @staticmethod
    def _same_scope_authority(left, right):
        return all(left.get(key) == right.get(key) for key in (
            'recordStableKey', 'observationSessionId', 'targetInstance', 'matchGeneration')) \
            and left.get('capturePolicy', STRICT) == right.get('capturePolicy', STRICT)

    def trigger_watch_scope_is_current(self, scope):
        with self._lock:
            watch = self._trigger_watch
            return bool(watch and watch['armed'] and self._clock() < watch['deadlineAt']
                and self._same_scope_authority(scope, watch['scope']))

    def trigger_probe_file(self, event):
        with self._lock:
            watch = self._trigger_watch
            details = event.get('details') if isinstance(event, dict) else None
            if (not watch or not isinstance(details, dict) or not self._valid_trigger_event(event, watch)
                    or details.get('probeId') != watch.get('pendingProbeId')
                    or details.get('probeOrdinal') != watch.get('pendingOrdinal')):
                return None
            relative = details.get('relativePath')
            if not isinstance(relative, str) or relative.replace('\\', '/').split('/') != [
                    'warehouse-trigger-probes', watch['watchId'], details['probeId'] + '.bmp']:
                return None
            root = Path(self._root_provider()).resolve(strict=True)
            path = (root / Path(relative)).resolve(strict=True)
            expected_root = (root / 'warehouse-trigger-probes' / watch['watchId']).resolve(strict=True)
            if path.parent != expected_root or path.name != details['probeId'] + '.bmp':
                return None
            return {'path': path, 'sourceRoot': expected_root, 'scope': copy.deepcopy(watch['scope']),
                'watchId': watch['watchId'], 'probeId': details['probeId'],
                'probeOrdinal': details['probeOrdinal'], 'deadlineNs': watch['deadlineNs'],
                'frameSequence': details.get('frameSequence'), 'sourceTimestampNs': details.get('sourceTimestampNs'),
                'readbackTimestampNs': details.get('readbackTimestampNs'), 'width': details.get('width'),
                'height': details.get('height'), 'stride': details.get('stride'),
                'bmpSha256': details.get('bmpSha256'), 'pixelSha256': details.get('pixelSha256'),
                'deliveryProof': copy.deepcopy(details.get('deliveryProof'))}

    def _valid_trigger_event(self, event, watch):
        details = event.get('details') if isinstance(event, dict) else None
        return bool(event.get('type') == EVENT_TYPE and event.get('event') == 'TRIGGER_PROBE'
            and event.get('scene') == 'UNCLASSIFIED_CURRENT_PROBE'
            and event.get('watchId') == watch['watchId']
            and event.get('observationSessionId') == watch['scope']['observationSessionId']
            and event.get('recordStableKey') == watch['scope']['recordStableKey']
            and event.get('matchGeneration') == watch['scope']['matchGeneration']
            and event.get('targetInstance') == watch['scope']['targetInstance']
            and event.get('clientMap') == watch['clientMap']
            and event.get('deadlineNs') == watch['deadlineNs']
            and event.get('capturePolicy', STRICT) == watch['scope'].get('capturePolicy', STRICT)
            and event.get('sourceKind') == 'native_wgc' and event.get('inputActions') is False
            and event.get('formalHistoryWriter') is False and isinstance(details, dict))

    def accept_trigger_probe(self, event):
        with self.intake._scope_lock, self._lock:
            self.check_timeout()
            watch = self._trigger_watch
            if not watch or not watch['armed']:
                return {'ok': False, 'reason': 'TRIGGER_WATCH_NOT_ARMED'}
            details = event.get('details') if isinstance(event, dict) else None
            if not self._valid_trigger_event(event, watch):
                return {'ok': False, 'reason': 'TRIGGER_PROBE_SCOPE_MISMATCH'}
            ordinal = details.get('probeOrdinal')
            sequence = details.get('frameSequence')
            probe_id = details.get('probeId')
            if (watch['pendingProbeId'] is not None or type(ordinal) is not int
                    or ordinal != watch['lastOrdinal'] + 1 or type(sequence) is not int
                    or sequence <= watch['lastSequence'] or not isinstance(probe_id, str)
                    or not re.fullmatch('[0-9a-f]{32}', probe_id)):
                return {'ok': False, 'reason': 'TRIGGER_PROBE_DUPLICATE_OR_OUT_OF_ORDER'}
            if self._qpc() >= watch['deadlineNs']:
                self.cancel_trigger_watch('ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
                return {'ok': False, 'reason': 'TRIGGER_PROBE_EXPIRED'}
            current = self.intake.source_contract()['scope']
            if not self._same_scope_authority(watch['scope'], current) or current.get('scene') != 'SETTLEMENT':
                self.cancel_trigger_watch('TRIGGER_SCOPE_CHANGED')
                return {'ok': False, 'reason': 'TRIGGER_SCOPE_CHANGED'}
            watch['pendingProbeId'], watch['pendingOrdinal'] = probe_id, ordinal
            watch['lastOrdinal'], watch['lastSequence'] = ordinal, sequence
            return {'ok': True, 'reason': 'TRIGGER_PROBE_ACCEPTED'}

    def acknowledge_trigger_probe(self, event, *, result, reason_codes=()):
        with self.intake._scope_lock, self._lock:
            watch = self._trigger_watch
            details = event.get('details') if isinstance(event, dict) else None
            if (not watch or not isinstance(details, dict) or event.get('watchId') != watch['watchId']
                    or details.get('probeId') != watch['pendingProbeId']
                    or details.get('probeOrdinal') != watch['pendingOrdinal']):
                return False
            scope = watch['scope']
            schema = SCHEMA_V2 if scope.get('capturePolicy') == DELIVERY else SCHEMA
            command = {'type': CONTROL_TYPE, 'schemaVersion': schema, 'operation': 'ACK_TRIGGER_PROBE',
                'commandId': uuid.uuid4().hex, 'nonce': uuid.uuid4().hex,
                'observationSessionId': scope['observationSessionId'], 'watchId': watch['watchId'],
                'recordStableKey': scope['recordStableKey'], 'expectedTargetInstance': copy.deepcopy(scope['targetInstance']),
                'matchGeneration': scope['matchGeneration'], 'clientMap': watch['clientMap'],
                'probeId': watch['pendingProbeId'], 'result': result,
                'reason': ';'.join(reason_codes), 'reasonCodes': list(reason_codes)}
            sent = self._send(command)
            watch['pendingProbeId'] = watch['pendingOrdinal'] = None
            return sent

    def cancel_trigger_watch(self, reason='TRIGGER_WATCH_CANCELLED', *, notify=True):
        with self.intake._scope_lock, self._lock:
            watch = self._trigger_watch
            if not watch:
                return False
            scope = watch['scope']
            if notify:
                schema = SCHEMA_V2 if scope.get('capturePolicy') == DELIVERY else SCHEMA
                self._send({'type': CONTROL_TYPE, 'schemaVersion': schema, 'operation': 'CANCEL_TRIGGER_WATCH',
                    'commandId': uuid.uuid4().hex, 'nonce': uuid.uuid4().hex,
                    'observationSessionId': scope['observationSessionId'], 'watchId': watch['watchId'],
                    'recordStableKey': scope['recordStableKey'], 'expectedTargetInstance': copy.deepcopy(scope['targetInstance']),
                    'matchGeneration': scope['matchGeneration'], 'clientMap': watch['clientMap'], 'reason': reason})
            self._trigger_watch = None
            self._cancel_timer()
            self._reason = reason
            return True

    def request_scroll_down(self, *, stable_proof=None, base_proof=None, wheel_delta=-120):
        if type(wheel_delta) is not int or not -1440 <= wheel_delta <= -120 or wheel_delta % 120:
            return self._reply(False, 'WINDOW_SCROLL_DELTA_REJECTED')
        if self._evidence_only:
            return self._reply(False, 'EVIDENCE_ONLY_INPUT_DISABLED')
        with self.intake._scope_lock, self._lock:
            self.check_timeout()
            if (self._state != 'OPEN' or self._pending or not self._saved_source
                    or self._host_limits.get('windowScrollSupported') is not True):
                return self._reply(False, 'WINDOW_SCROLL_UNAVAILABLE')
            if not self._same_contract(self.intake.source_contract()):
                self._close('SOURCE_SCOPE_CHANGED', cancel_intake=True)
                return self._reply(False, self._reason)
            command = self._command('SCROLL_DOWN')
            command['wheelDelta'] = wheel_delta
            command.update(sourceLeaseId=self._saved_source['sourceLeaseId'], pixelSha256=self._saved_source['pixelSha256'])
            if self._delivery():
                saved_proof = base_proof or self._saved_source.get('deliveryProof')
                if not independent_support(saved_proof, stable_proof):
                    return self._reply(False, 'INDEPENDENT_STABILITY_UNPROVEN')
                command.update(savedCaptureId=saved_proof['captureId'], stableCaptureId=stable_proof['captureId'])
            self._scroll_recheck = None
            self._pending, self._state = command, 'SCROLL_PENDING'
            self._pending_until = min(self._clock() + 2, self._deadline)
            if not self._send(command):
                self._close('WINDOW_SCROLL_SEND_FAILED')
                return self._reply(False, self._reason)
            self._schedule(max(0, self._pending_until - self._clock()))
            return self._reply(True, 'WINDOW_SCROLL_REQUESTED')

    def read_content_hint(self, event):
        """Read one volatile observation ROI; never append a source or grant scroll."""
        import cv2
        import numpy as np
        from warehouse_scrollbar_observation import warehouse_search_roi
        with self.intake._scope_lock, self._lock:
            d = event.get('details') or {}
            if (self._evidence_only or self._state != 'OPEN' or not self._delivery()
                    or event.get('type') != EVENT_TYPE or event.get('event') != 'CONTENT_HINT'
                    or not self._matches(event, self._binding) or event.get('leaseToken') != self._lease
                    or event.get('schemaVersion') != SCHEMA_V2 or event.get('capturePolicy') != DELIVERY
                    or event.get('matchGeneration') != self._binding['scope']['matchGeneration']
                    or event.get('inputActions') is not False or d.get('sourceAuthority') is not False
                    or d.get('formalFactsQualified') is not False or d.get('clientMap') != self._host_limits.get('clientMap')
                    or not self._same_contract(self.intake.source_contract())
                    or not isinstance(d.get('captureId'),str)
                    or not d['captureId'].startswith(self._binding['scope']['observationSessionId']+'/')
                    or type(d.get('readbackNs')) is not int or not 0 <= self._qpc()-d['readbackNs'] <= 2_000_000_000):
                return None
            try:
                root = Path(self._root_provider()).resolve()
                path = Path(d['path']).resolve(strict=True)
                if path != root / 'warehouse-sources' / 'content-observation.bmp':
                    return None
                box = warehouse_search_roi(self._host_limits['clientWidth'], self._host_limits['clientHeight'])
                w, h = box[2]-box[0], box[3]-box[1]
                if (d.get('width'),d.get('height')) != (w,h):
                    return None
                with path.open('rb') as stream:
                    raw = stream.read(54 + 4*w*h + 1)
                if len(raw) != 54+4*w*h or hashlib.sha256(raw).hexdigest() != d['sha256']:
                    return None  # Slot changed while queued/read: discard, never use as an original.
                image = cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
                return image if image is not None and image.shape[:2] == (h,w) else None
            except (OSError, KeyError, ValueError, TypeError):
                return None

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
            if isinstance(event, dict) and event.get('type') == EVENT_TYPE \
                    and isinstance(event.get('event'), str) and event['event'].startswith('TRIGGER_'):
                self._on_trigger_status_event(event)
                return
            if self._on_trigger_status_event(event):
                return
            if (not isinstance(event, dict) or event.get('type') != EVENT_TYPE
                or event.get('schemaVersion') != self._schema() or event.get('sourceKind') != 'native_wgc'
                or event.get('formalHistoryWriter') is not False):
                return
            if self._delivery() and (event.get('capturePolicy') != DELIVERY
                    or event.get('matchGeneration') != self._binding['scope']['matchGeneration']):
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
                if self._pending.get('retainIndependentOriginals') and details.get('retainIndependentOriginals') is not True:
                    self._close('INDEPENDENT_ORIGINAL_RETENTION_UNSUPPORTED', cancel_intake=True)
                    return
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
                self._scroll_recheck = None
                if (event.get('reason') == 'SCROLL_CONTENT_CHANGED_BEFORE_SEND'
                    and self._delivery() and self._state == 'SCROLL_PENDING'
                    and self._pending.get('operation') == 'SCROLL_DOWN'
                    and counters.get('classification') == 'NOT_SENT_CONTENT_SUPPORT_RECHECK'
                    and counters.get('sendInterfaceInvoked') is False
                    and counters.get('failedChecks') == ['scrollContentQuantizationSupported']
                    and counters.get('sourceLeaseId') == self._pending.get('sourceLeaseId')):
                    self._scroll_recheck = copy.deepcopy(counters)
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
                        or (validate_delivery(counters.get('deliveryProof'), now,
                            session=self._binding['scope']['observationSessionId'], require_progress=True) is not None
                            if self._delivery() else not 0 < counters['requestGateNs'] < counters['sourceTimestampNs'] <= now
                            or now - counters['sourceTimestampNs'] > 2_000_000_000)
                        or counters['frameSequence'] <= self._saved_source['frameSequence']):
                        raise ValueError()
                    if self._delivery() and (counters['deliveryProof']['requestNs'] != counters['requestGateNs']
                            or counters['deliveryProof']['sourceTimestampNs'] != counters['sourceTimestampNs']
                            or counters['deliveryProof']['acquisitionSequence'] != counters['frameSequence']):
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
                if (self._delivery() and (type(counters.get('messageCompletedNs')) is not int
                        or not 0 < counters['messageCompletedNs'] <= self._qpc())):
                    self._close('WINDOW_SCROLL_COMPLETION_CLOCK_REJECTED')
                    return
                if (counters.get('direction') != 'DOWN' or type(counters.get('delta')) is not int
                    or counters.get('delta') != self._pending.get('wheelDelta', -120)
                    or not self._saved_source or counters.get('sourceLeaseId') != self._saved_source['sourceLeaseId']):
                    self._close('WINDOW_SCROLL_PROOF_REJECTED')
                    return
                self._pending = None
                self._last_scroll_ns = counters.get('messageCompletedNs', 0)
                self._state, self._reason = 'OPEN', 'WINDOW_WHEEL_MESSAGE_SENT'
                self._schedule(max(0, self._deadline - self._clock()))

    def _on_trigger_status_event(self, event):
        if not isinstance(event, dict) or event.get('type') != EVENT_TYPE:
            return False
        if event.get('event') not in {'TRIGGER_WATCH_ARMED', 'TRIGGER_WATCH_ENDED',
                                      'TRIGGER_PROBE_ACKED', 'REJECTED'}:
            return False
        # SOURCE/SCROLL rejections have no watchId. They belong to the
        # command-bound lease path below, even when no trigger watch exists.
        if event.get('event') == 'REJECTED' and not event.get('watchId'):
            return False
        watch = self._trigger_watch
        if not watch or event.get('watchId') != watch['watchId']:
            return True
        scope = watch['scope']
        expected_schema = SCHEMA_V2 if scope.get('capturePolicy') == DELIVERY else SCHEMA
        if (event.get('schemaVersion') != expected_schema
                or event.get('observationSessionId') != scope['observationSessionId']
                or event.get('recordStableKey') != scope['recordStableKey']
                or event.get('targetInstance') != scope['targetInstance']
                or event.get('capturePolicy', scope.get('capturePolicy', STRICT)) != scope.get('capturePolicy', STRICT)
                or event.get('inputActions') is not False or event.get('formalHistoryWriter') is not False):
            return True
        kind = event.get('event')
        if kind == 'TRIGGER_WATCH_ARMED':
            if (event.get('matchGeneration') != scope['matchGeneration']
                    or event.get('clientMap') != watch['clientMap']
                    or event.get('deadlineNs') != watch['deadlineNs']):
                self.cancel_trigger_watch('TRIGGER_ARM_BINDING_REJECTED', notify=False)
                return True
            watch['armed'] = True
            self._schedule(max(0, watch['deadlineAt'] - self._clock()))
        elif kind == 'TRIGGER_PROBE_ACKED':
            details = event.get('details') or {}
            if details.get('probeAttempts', 0) >= MAX_TRIGGER_PROBES:
                self._reason = 'TRIGGER_PROBE_LIMIT_REACHED'
        elif kind == 'TRIGGER_WATCH_ENDED':
            self._reason = event.get('reason') or 'TRIGGER_WATCH_ENDED'
            self._trigger_watch = None
            self._cancel_timer()
        elif kind == 'REJECTED' and event.get('commandId') == watch.get('armCommandId'):
            self._reason = event.get('reason') or 'TRIGGER_WATCH_REJECTED'
            self._trigger_watch = None
            self._cancel_timer()
        return True

    def _request_matches(self, event):
        return bool(self._pending and type(event.get('requestOrdinal')) is int
            and event.get('commandId') == self._pending['commandId']
            and event.get('nonce') == self._pending['nonce']
            and event.get('requestOrdinal') == self._pending['requestOrdinal'])

    def _accept_source(self, event):
        source = event.get('source') or {}
        result = {'ok': False, 'reason': 'SOURCE_PROOF_REJECTED'}
        try:
            required = ('width', 'height', 'stride', 'sourceTimestampNs', 'requestGateNs', 'frameSequence', 'byteCount')
            if not self._delivery():
                required += ('workerFrameSequence',)
            for key in required:
                if type(source[key]) is not int or source[key] <= 0:
                    raise ValueError()
            w, h = source['width'], source['height']
            if (w != self._host_limits['clientWidth'] or h != self._host_limits['clientHeight']
                or source['stride'] != 4 * w or source['byteCount'] != 54 + 4 * w * h
                or source.get('clientMap') != self._host_limits['clientMap']
                or (validate_delivery(source.get('deliveryProof'), self._qpc(),
                        session=self._binding['scope']['observationSessionId'], require_progress=True) is not None
                    or source.get('capturePolicy') != DELIVERY
                    or source.get('matchGeneration') != self._binding['scope']['matchGeneration']
                    or source.get('formalFactsQualified') is not False
                    or source['deliveryProof']['requestNs'] < self._last_scroll_ns
                    or source['deliveryProof']['requestNs'] != source['requestGateNs']
                    or source['deliveryProof']['sourceTimestampNs'] != source['sourceTimestampNs']
                    or source['deliveryProof']['readbackCompletedNs'] != source.get('readbackTimestampNs')
                    or source['deliveryProof']['acquisitionSequence'] != source['frameSequence']
                    if self._delivery() else source['workerFrameSequence'] != source['frameSequence']
                    or not source['requestGateNs'] < source['sourceTimestampNs'] <= self._qpc()
                    or self._qpc() - source['sourceTimestampNs'] > 2_000_000_000)):
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
                'capturePolicy': DELIVERY if self._delivery() else STRICT,
                'deliveryProof': copy.deepcopy(source.get('deliveryProof')), 'bmpSha256': source['bmpSha256'],
                'clientMap': source['clientMap'],
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
        self._send({'type': CONTROL_TYPE, 'schemaVersion': SCHEMA_V2 if b['scope'].get('capturePolicy') == DELIVERY else SCHEMA, 'operation': 'CLOSE',
            'commandId': uuid.uuid4().hex, 'nonce': uuid.uuid4().hex,
            'observationSessionId': b['scope']['observationSessionId'], 'reviewSessionId': b['sessionId'],
            'reviewGeneration': b['generation'], 'recordStableKey': b['scope']['recordStableKey'],
            'expectedTargetInstance': b['scope']['targetInstance'], 'matchGeneration': b['scope']['matchGeneration'], 'leaseToken': event.get('leaseToken')})

    def _close(self, reason, *, cancel_intake=False, notify=True):
        self._last_closed = copy.deepcopy(self._binding)
        if notify and self._binding:
            self._send(self._command('CLOSE'))
        self._cancel_timer()
        self._pending = self._source = None
        self._state, self._reason = 'CLOSED', reason
        if cancel_intake:
            self.intake.end_collection(reason)

    def check_timeout(self):
        with self.intake._scope_lock, self._lock:
            if self._trigger_watch is not None and self._clock() >= self._trigger_watch['deadlineAt']:
                self.cancel_trigger_watch('ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
            elif self._state == 'OPEN_PENDING' and self._clock() >= self._pending_until:
                self._close('SOURCE_PUBLISH_UNSUPPORTED_OR_TIMEOUT')
            elif self._state in {'OPEN', 'REQUEST_PENDING', 'SCROLL_PENDING'} and self._clock() >= self._deadline:
                self._close('ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED')
            elif self._state in {'REQUEST_PENDING', 'SCROLL_PENDING'} and self._clock() >= self._pending_until:
                self._close('SOURCE_REQUEST_TIMEOUT')

    def close_source(self, reason):
        with self.intake._scope_lock, self._lock:
            self.cancel_trigger_watch(reason)
            self._close(reason)

    def finish_manual_capture(self, *, termination_reason='COMPLETE', qualified_evidence_ids=None):
        with self.intake._scope_lock, self._lock:
            if self._evidence_only:
                return self._reply(False, 'EVIDENCE_ONLY_PROCESSING_DISABLED')
            if qualified_evidence_ids is not None and not getattr(self, 'offline_test_adapter', False):
                supported = {p['descriptor']['evidenceId'] for p in self.intake.pages_copy()
                    if p.get('contentRole') == 'STABLE_SUPPORT'
                    and (p.get('contentCertificate') or {}).get('schema') == 'visible-content-support.v1'}
                if any(eid not in supported for eid in qualified_evidence_ids):
                    return self._reply(False, 'QUALIFIED_PAGE_SELECTION_UNPROVEN')
            if self._pending is not None:
                return self._reply(False, 'SOURCE_REQUEST_PENDING')
            self._close('MANUAL_FINISHED')
            options = ({'qualified_evidence_ids': qualified_evidence_ids}
                if qualified_evidence_ids is not None else {})
            return self.intake.finish_manual_capture(termination_reason=termination_reason, **options)

    def cancel_manual_capture(self):
        with self.intake._scope_lock, self._lock:
            self.cancel_trigger_watch('USER_CANCEL')
            self._close('USER_CANCEL')
            return self.intake.cancel_manual_capture()

    def observation_ended(self, reason):
        with self.intake._scope_lock, self._lock:
            self.cancel_trigger_watch(reason)
            if self._state not in {'IDLE', 'CLOSED'}:
                self._close(reason, cancel_intake=True)

    def check_business_boundary(self, event):
        """Called after the unchanged ordinary handler; never refresh business health/facts."""
        with self.intake._scope_lock, self._lock:
            if self._trigger_watch is not None:
                contract = self.intake.source_contract()
                if (contract.get('scope', {}).get('scene') != 'SETTLEMENT'
                        or not self._same_scope_authority(self._trigger_watch['scope'], contract.get('scope', {}))):
                    self.cancel_trigger_watch('TRIGGER_SCOPE_CHANGED')
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
            if self._delivery():
                view['captureFreshnessPolicy'] = DELIVERY
                messages['SOURCE_REQUESTED'] = '等待池空边界后的交付原帧；不证明请求后渲染，尚未保存页面。'
            if self._reason in messages:
                view['message'] = messages[self._reason]
            elif self._reason:
                view['message'] += ' · ' + self._reason
            return view
