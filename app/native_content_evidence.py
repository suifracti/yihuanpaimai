"""One bounded SOURCE session for content evidence, with no scroll/processing authority."""
import threading
import time

from native_capture_delivery import DELIVERY


class NativeContentEvidenceSession:
    MAX_REQUESTS = 14

    def __init__(self, source, *, qpc=None):
        self.source = source
        self.qpc = qpc or time.perf_counter_ns
        self._lock = threading.RLock()
        self.started = False
        self.ended = False
        self.visible_content_ready_ns = None
        self.manual_scroll_ns = None

    def handle(self, operation):
        with self.source.intake._scope_lock, self._lock:
            if operation == 'prepare':
                if self.started:
                    return {'ok': False, 'reason': 'EVIDENCE_SESSION_ALREADY_USED'}
                contract = self.source.intake.source_contract()
                if contract['scope'].get('capturePolicy') != DELIVERY:
                    return {'ok': False, 'reason': 'DELIVERY_SOURCE_REQUIRED'}
                return self.source.prepare_manual()
            if operation == 'begin':
                if self.started:
                    return {'ok': False, 'reason': 'EVIDENCE_SESSION_ALREADY_USED'}
                ready = self.handle('prepare')
                if not ready['ok']:
                    return ready
                self.started = True  # no restart, even after an OPEN failure
                return self.source.start_manual(retain_independent_originals=True)
            if operation == 'end':
                self.ended = True
                # Cancellation keeps originals/manifest and does not start item processing.
                return self.source.cancel_manual_capture() if self.started else {'ok': True}
            if not self.started or self.ended:
                return {'ok': False, 'reason': 'NO_ACTIVE_EVIDENCE_SESSION'}
            snapshot = self.source.source_session_snapshot()
            pages = self.source.pages_copy()
            if operation == 'status':
                return {'ok': True, 'snapshot': snapshot, 'pages': pages,
                    'userVisibleContentReadyNs': self.visible_content_ready_ns,
                    'manualScrollAcknowledgedNs': self.manual_scroll_ns,
                    'formalFactsQualified': False, 'coverageQualified': False}
            if operation == 'visible-content-ready':
                if snapshot['state'] != 'OPEN' or snapshot['requestAttempts'] != 4 or len(pages) != 4:
                    return {'ok': False, 'reason': 'VISIBLE_CONTENT_STAGE_NOT_READY'}
                if not self.source.lease_scope_is_current(self.source.intake.source_contract()['scope']):
                    return {'ok': False, 'reason': 'SOURCE_SCOPE_CHANGED'}
                if self.visible_content_ready_ns is not None:
                    return {'ok': False, 'reason': 'VISIBLE_CONTENT_ALREADY_ACKNOWLEDGED'}
                self.visible_content_ready_ns = self.qpc()
                return {'ok': True, 'marker': 'USER_VISIBLE_CONTENT_READY',
                    'acknowledgedNs': self.visible_content_ready_ns,
                    'formalFactsQualified': False, 'coverageQualified': False,
                    'meaning': 'development observation only; not a product stability/completion certificate'}
            if operation == 'manual-scroll-done':
                if snapshot['state'] != 'OPEN' or snapshot['requestAttempts'] != 10 or len(pages) != 10:
                    return {'ok': False, 'reason': 'MANUAL_SCROLL_STAGE_NOT_READY'}
                if self.manual_scroll_ns is not None:
                    return {'ok': False, 'reason': 'MANUAL_SCROLL_ALREADY_ACKNOWLEDGED'}
                self.manual_scroll_ns = self.qpc()
                return {'ok': True, 'acknowledgedNs': self.manual_scroll_ns,
                    'meaning': 'user event only; displacement must be checked offline'}
            if operation != 'page':
                return {'ok': False, 'reason': 'UNKNOWN_EVIDENCE_OPERATION'}
            if snapshot['state'] != 'OPEN':
                return {'ok': False, 'reason': snapshot['reason'] or 'SOURCE_NOT_OPEN'}
            attempts = snapshot['requestAttempts']
            if attempts >= self.MAX_REQUESTS:
                return {'ok': False, 'reason': 'EVIDENCE_REQUEST_LIMIT_REACHED'}
            if attempts != len(pages):
                return {'ok': False, 'reason': 'EVIDENCE_ORIGINAL_NOT_SAVED'}
            if attempts >= 4 and self.visible_content_ready_ns is None:
                return {'ok': False, 'reason': 'USER_VISIBLE_CONTENT_READY_REQUIRED'}
            if attempts >= 10 and self.manual_scroll_ns is None:
                return {'ok': False, 'reason': 'ONE_MANUAL_SCROLL_REQUIRED'}
            if pages:
                proof = pages[-1]['deliveryProof']
                if self.qpc() < proof['readbackCompletedNs'] + 250_000_000:
                    return {'ok': False, 'reason': 'INDEPENDENT_REQUEST_INTERVAL_PENDING'}
            # The coordinator still enforces original deadline, scope and raw/PNG budgets.
            return self.source.capture_manual_page()
