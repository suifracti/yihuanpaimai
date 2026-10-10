"""Explicit Native settlement-page intake; no capture or game-input authority."""
from __future__ import annotations

import copy
import hashlib
import math
import json
import os
from pathlib import Path
import re
import struct
import threading
import tempfile
import time
import uuid

import cv2
import numpy as np

from canonical_history_store import CanonicalHistoryStore
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from settlement_stable_frame_persist import encode_settlement_original
from settlement_truth_evidence_contract import validate_settlement_evidence_original_v2
from warehouse_capture_host import WarehouseCaptureHost
from native_capture_delivery import DELIVERY, STRICT

MAX_PAGES = 16
MAX_PIXELS = 8_388_608
MAX_BMP_BYTES = 54 + 4 * MAX_PIXELS
MAX_ENCODED_BYTES = 64 * 1024 * 1024
MAX_FRAME_AGE_SECONDS = 2.0
MAX_MANIFEST_BYTES = 64 * 1024


class IntakeRejected(RuntimeError):
    pass


def _anchor(scope):
    if not isinstance(scope, dict):
        raise IntakeRejected('NATIVE_SCOPE_UNAVAILABLE')
    anchor = {k: copy.deepcopy(scope.get(k)) for k in (
        'recordStableKey', 'observationSessionId', 'targetInstance', 'matchGeneration')}
    if (not anchor['recordStableKey'] or not anchor['observationSessionId']
            or not isinstance(anchor['targetInstance'], dict)
            or not anchor['targetInstance'] or type(anchor['matchGeneration']) is not int):
        raise IntakeRejected('NATIVE_SCOPE_UNAVAILABLE')
    if scope.get('capturePolicy') == DELIVERY:
        anchor['capturePolicy'] = DELIVERY
    return anchor


class _SessionHistory:
    def __init__(self, owner, generation):
        self.owner, self.generation = owner, generation

    def persist_warehouse_evidence(self, record_key, **kwargs):
        owner = self.owner
        # Same lock order as intake and Main's accepted-frame updates.
        with owner._scope_lock, owner._lock:
            if (owner._generation != self.generation or owner._state != 'ALIGNING'
                    or owner._processing_binding != owner._binding
                    or record_key != owner._binding['recordStableKey']
                    or owner.draft_store.lookup(record_key) is None):
                raise IntakeRejected('STALE_NATIVE_INTAKE_SESSION')
            return owner.history_store.persist_warehouse_evidence(record_key,
                record_stable_key=owner._processing_binding['recordStableKey'], **kwargs)


class NativeWarehouseIntake:
    def __init__(self, *, draft_store, scope_provider, source_provider, scope_lock=None, clock=None,
                 auto_refine=True):
        self.draft_store = draft_store
        self.evidence_store = SettlementEvidenceStoreV2(draft_store.root)
        self.history_store = CanonicalHistoryStore(draft_store.history_path)
        self._scope_provider, self._source_provider = scope_provider, source_provider
        self._scope_lock = scope_lock or threading.RLock()
        self._lock = threading.RLock()
        self._clock = clock or time.monotonic
        self._source_validator = None
        self._generation = 0
        self._state, self._reason = 'IDLE', None
        self._binding, self._session_id = None, None
        self._pages, self._encoded_bytes = [], 0
        self._worker, self._processor = None, None
        self._coverage, self._packet = 'COVERAGE_UNPROVEN', None
        self._processing_binding, self._processing_evidence_ids = None, None
        self._resolve_placements = False
        from native_warehouse_refinement import SavedWarehouseRefinement
        self._refiner = SavedWarehouseRefinement(self) if auto_refine else None

    def _reply(self, ok, reason=None, **extra):
        self._reason = reason
        return {'ok': ok, 'reason': reason, 'pageCount': len(self._pages), **extra}

    def _write_manifest(self, pages):
        path = self.draft_store.root / 'warehouse-intake' / (self._session_id + '.json')
        refinement = None
        if path.is_file():
            refinement = json.loads(path.read_text(encoding='utf-8')).get('refinement')
        raw = json.dumps({'schemaVersion': 'native-warehouse-intake.v1',
            'sessionId': self._session_id, 'generation': self._generation,
            'scope': self._binding, 'pages': pages, 'state': self._state,
            'terminationReason': self._reason,
            'resultSourceFingerprint': (self._packet or {}).get('sourceFingerprint'),
            'processingEvidenceIds': self._processing_evidence_ids,
            'refinement': refinement,
            'placementRefinementPending': not (self._resolve_placements and self._packet
                and self._state in {'PARTIAL','COMPLETE'}),
            'rejectedOriginals': getattr(self, '_rejected_originals', [])}, ensure_ascii=False).encode('utf-8')
        if len(raw) > MAX_MANIFEST_BYTES:
            raise IntakeRejected('LIMIT_REACHED')
        directory = self.draft_store.root / 'warehouse-intake'
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.intake-', suffix='.tmp', delete=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = stream.name
        os.replace(temporary, directory / (self._session_id + '.json'))

    def source_contract(self):
        with self._scope_lock, self._lock:
            scope = self._scope_provider()
            try:
                current = _anchor(scope)
            except IntakeRejected:
                current = {}
            current['scene'] = scope.get('scene') if isinstance(scope, dict) else None
            return {'sessionId': self._session_id, 'generation': self._generation,
                'state': self._state, 'scope': current,
                'remainingPages': max(0, MAX_PAGES - len(self._pages)),
                'remainingPngBytes': max(0, MAX_ENCODED_BYTES - self._encoded_bytes)}

    def prepare_manual(self):
        with self._scope_lock, self._lock:
            try:
                scope = self._scope_provider()
                binding = _anchor(scope)
                if scope.get('scene') != 'SETTLEMENT':
                    raise IntakeRejected('NATIVE_NOT_SETTLEMENT')
                if self.draft_store.lookup(binding['recordStableKey']) is None:
                    raise IntakeRejected('NATIVE_DRAFT_NOT_SAVED')
                if self._worker and self._worker.is_alive():
                    raise IntakeRejected('PROCESSING_CANCEL_PENDING')
                return {'ok': True, 'recordStableKey': binding['recordStableKey'],
                        'confirmCaption': '只接收本局已观察的结算原帧；请自行滚动，程序不会操作游戏。稳定结算后若无新帧将明确拒绝追加。'}
            except IntakeRejected as exc:
                return self._reply(False, str(exc))

    def start_manual(self, record_key=None, *, retain_independent_originals=False):
        with self._scope_lock, self._lock:
            if self._state == 'MANUAL_CAPTURING':
                return self._reply(False, 'ALREADY_RUNNING')
            prep = self.prepare_manual()
            if not prep['ok']:
                return prep
            if record_key is not None and record_key != prep['recordStableKey']:
                return self._reply(False, 'NATIVE_RECORD_MISMATCH')
            self._generation += 1
            self._session_id = uuid.uuid4().hex
            self._binding = _anchor(self._scope_provider())
            self._pages, self._encoded_bytes = [], 0
            self._retain_independent_originals = retain_independent_originals is True
            self._rejected_originals = []
            self._state, self._reason = 'MANUAL_CAPTURING', None
            self._coverage, self._packet = 'COVERAGE_UNPROVEN', None
            self._processor = None
            self._processing_binding, self._processing_evidence_ids = None, None
            return self._reply(True, 'MANUAL_READY')

    def capture_manual_page(self):
        with self._scope_lock, self._lock:
            if self._state != 'MANUAL_CAPTURING':
                return self._reply(False, 'NOT_IN_MANUAL_MODE')
            try:
                scope = self._scope_provider()
                if _anchor(scope) != self._binding or scope.get('scene') != 'SETTLEMENT':
                    raise IntakeRejected('NATIVE_SCOPE_CHANGED')
                source = self._source_provider()
                if not isinstance(source, dict):
                    raise IntakeRejected('NO_FRESH_NATIVE_FRAME')
                age = self._clock() - float(source.get('receivedAt', float('-inf')))
                if not math.isfinite(age) or age < 0 or age > MAX_FRAME_AGE_SECONDS:
                    raise IntakeRejected('NO_FRESH_NATIVE_FRAME')
                if _anchor(source.get('scope')) != self._binding or source['scope'].get('scene') != 'SETTLEMENT':
                    raise IntakeRejected('FRAME_LEASE_MISMATCH')
                sequence = source.get('frameSequence')
                if type(sequence) is not int or sequence <= 0:
                    raise IntakeRejected('FRAME_LEASE_MISMATCH')
                if self._pages and sequence <= self._pages[-1]['sourceSequence']:
                    raise IntakeRejected('NO_NEW_NATIVE_FRAME')
                w, h = source.get('width'), source.get('height')
                if type(w) is not int or type(h) is not int or w <= 0 or h <= 0 or w * h > MAX_PIXELS:
                    raise IntakeRejected('LIMIT_REACHED')
                pixel_hash = source.get('pixelSha256')
                if not isinstance(pixel_hash, str) or not re.fullmatch('[0-9a-f]{64}', pixel_hash):
                    raise IntakeRejected('FRAME_LEASE_MISMATCH')
                if (not self._retain_independent_originals
                        and any(p['pixelSha256'] == pixel_hash for p in self._pages)):
                    return self._reply(True, 'DUPLICATE_PAGE', duplicate=True)
                if len(self._pages) >= MAX_PAGES:
                    raise IntakeRejected('LIMIT_REACHED')
                path = Path(source['path']).resolve(strict=True)
                path.relative_to(Path(source['sourceRoot']).resolve(strict=True))
                with path.open('rb') as stream:
                    raw = stream.read(MAX_BMP_BYTES + 1)
                if (len(raw) != 54 + w * h * 4 or raw[:2] != b'BM'
                        or struct.unpack_from('<I', raw, 10)[0] != 54
                        or struct.unpack_from('<ii', raw, 18) != (w, -h)
                        or raw[28:30] != b'\x20\x00'
                        or hashlib.sha256(raw[54:]).hexdigest() != pixel_hash):
                    raise IntakeRejected('ORIGINAL_FRAME_LEASE_MISMATCH')
                # Reject an actual encoded-size overflow before writing another Native original.
                frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None or frame.shape[:2] != (h, w):
                    raise IntakeRejected('ORIGINAL_FRAME_LEASE_MISMATCH')
                payload = encode_settlement_original(frame)
                del frame
                if self._encoded_bytes + len(payload) > MAX_ENCODED_BYTES:
                    raise IntakeRejected('LIMIT_REACHED')
                # Keep the exact Native BMP, then derive a legal shared-Store
                # descriptor. The Native source descriptor remains unchanged.
                native_source = self.draft_store.capture_frame(path, {
                    'width': w, 'height': h, 'capturedAtUtc': source['capturedAt'],
                    'frameSequence': sequence,
                    'observationSessionId': self._binding['observationSessionId'],
                    'targetInstance': self._binding['targetInstance'],
                    'matchGeneration': self._binding['matchGeneration'],
                    'capturePolicy': source.get('capturePolicy', STRICT),
                    'deliveryProof': copy.deepcopy(source.get('deliveryProof')),
                }, expected_pixel_sha256=pixel_hash, max_bytes=MAX_BMP_BYTES)
                verified = self.draft_store.read_source_image_descriptor(native_source)
                if verified.get('error') or verified.get('data') != raw:
                    raise IntakeRejected('ORIGINAL_FRAME_LEASE_MISMATCH')
                del raw, verified
                if source.get('capturePolicy') == DELIVERY:
                    from scene_anchors import settlement_title_visible
                    original = self.draft_store.read_source_image_descriptor(native_source)['data']
                    source_frame = cv2.imdecode(np.frombuffer(original, np.uint8), cv2.IMREAD_COLOR)
                    if source_frame is None or not settlement_title_visible(source_frame):
                        self._rejected_originals.append({'nativeSource': native_source,
                            'deliveryProof': source.get('deliveryProof'), 'reason': 'SAVED_ORIGINAL_NOT_SETTLEMENT'})
                        self._write_manifest(self._pages)
                        raise IntakeRejected('SAVED_ORIGINAL_NOT_SETTLEMENT')
                    del source_frame, original
                descriptor = self.evidence_store.save_original(
                    record_stable_key=self._binding['recordStableKey'], kind='warehouse-segment',
                    image_bytes=payload, captured_at=source['capturedAt'],
                    coverage_mode='viewport-segment', coverage_status='COVERAGE_UNPROVEN')
                valid, _ = validate_settlement_evidence_original_v2(descriptor)
                if (not valid or descriptor['sha256'] != hashlib.sha256(payload).hexdigest()
                        or not self.evidence_store.verify(descriptor).get('ok')):
                    raise IntakeRejected('ORIGINAL_NOT_VERIFIED')
                page = {'descriptor': descriptor, 'nativeSource': native_source,
                    'pixelSha256': pixel_hash, 'sourceSequence': sequence,
                    'capturePolicy': source.get('capturePolicy', STRICT), 'bmpSha256': source.get('bmpSha256'),
                    'clientMap': source.get('clientMap'),
                    'deliveryProof': copy.deepcopy(source.get('deliveryProof'))}
                # Durable, bounded provenance is separate from first/latest
                # sourceFrames and single-frame settlement inventoryArchive.
                if self._source_validator is not None and not self._source_validator():
                    raise IntakeRejected('SOURCE_LEASE_EXPIRED')
                self._write_manifest(self._pages + [page])
                self._pages.append(page)
                self._encoded_bytes += len(payload)
                return self._reply(True, 'PAGE_ACCEPTED')
            except IntakeRejected as exc:
                return self._reply(False, str(exc))
            except (OSError, ValueError, KeyError, RuntimeError, TypeError) as exc:
                return self._reply(False, 'STORE_FAILED', error=type(exc).__name__)

    def annotate_offline_content_support(self, certificate):
        """Offline experiment only: bind representative/support to immutable saved originals.

        No production caller selects this path; it neither freezes a bill nor
        creates item facts. Late/stale certificates cannot annotate a new intake.
        """
        if (certificate.get('schema') != 'offline-content-support.v1'
                    or certificate.get('formalFactsQualified') is not False
                    or certificate.get('rendererContractEstablishedForGame') is not False
                    or certificate.get('topologySupported') is not True
                    or certificate.get('unexplainedPixels') != 0 or not certificate.get('mapping')):
            raise IntakeRejected('CONTENT_CERTIFICATE_UNPROVEN')
        self._annotate_content_support(certificate, 'offlineContentRole', 'offlineContentCertificate')

    def annotate_visible_content_support(self, certificate):
        """Visible page support only; does not assert reveal completion or item facts."""
        if (certificate.get('schema') != 'visible-content-support.v1'
                or certificate.get('formalFactsQualified') is not False
                or certificate.get('completionState') != 'UNKNOWN'
                or certificate.get('sceneProtected') is not True
                or certificate.get('coverageHoles') != 0
                or certificate.get('beyondQuantizationPixels') != 0
                or type(certificate.get('maxChannelDelta')) is not int
                or not 0 <= certificate['maxChannelDelta'] <= 1 or not certificate.get('mapping')):
            raise IntakeRejected('CONTENT_CERTIFICATE_UNPROVEN')
        self._annotate_content_support(certificate, 'contentRole', 'contentCertificate')

    def _annotate_content_support(self, certificate, role_key, certificate_key):
        with self._scope_lock, self._lock:
            if (self._state != 'MANUAL_CAPTURING' or _anchor(self._scope_provider()) != self._binding
                    or _anchor(certificate.get('scope')) != self._binding
                    or certificate.get('reviewBinding') != {'sessionId':self._session_id,'generation':self._generation}
                    or certificate['scope'].get('scene') != 'SETTLEMENT'):
                raise IntakeRejected('STALE_CONTENT_CERTIFICATE')
            # Identical pixels can have the same content-addressed descriptor
            # while remaining independently acquired SOURCE originals.
            indexed = {(p['descriptor']['evidenceId'], p['deliveryProof']['captureId']): p for p in self._pages}
            updates = []
            for role, key in (('STABLE_ANCHOR', 'anchor'), ('STABLE_SUPPORT', 'support')):
                ref = certificate[key]
                page = indexed.get((ref['evidenceId'], ref['captureId']))
                if (not page or page['descriptor']['sha256'] != ref['sha256']
                        or page.get('clientMap') != certificate['mapping']
                        or page['deliveryProof']['captureId'] != ref['captureId']
                        or page.get('pixelSha256') != ref.get('pixelSha256')
                        or page.get('bmpSha256') != ref.get('bmpSha256')
                        or not self.evidence_store.verify(page['descriptor']).get('ok')):
                    raise IntakeRejected('CONTENT_CERTIFICATE_ORIGINAL_CHANGED')
                updates.append((page, role))
            for page, role in updates:
                page[role_key] = role
                page[certificate_key] = copy.deepcopy(certificate)
            self._write_manifest(self._pages)

    def finish_manual_capture(self, *, termination_reason='COMPLETE', qualified_evidence_ids=None,
                              resolve_placements=False):
        with self._scope_lock, self._lock:
            if self._state != 'MANUAL_CAPTURING' or not self._pages:
                return self._reply(False, 'NO_PAGES' if not self._pages else 'NOT_IN_MANUAL_MODE')
            generation = self._generation
            selected = self._pages
            if qualified_evidence_ids is not None:
                if (len(set(qualified_evidence_ids)) != len(qualified_evidence_ids)
                        or any(not any(p['descriptor']['evidenceId'] == eid and
                            (p.get('offlineContentRole') == 'STABLE_SUPPORT'
                             or p.get('contentRole') == 'STABLE_SUPPORT') for p in self._pages)
                            for eid in qualified_evidence_ids)):
                    return self._reply(False, 'QUALIFIED_PAGE_SELECTION_UNPROVEN')
                selected = [p for eid in qualified_evidence_ids for p in self._pages if p['descriptor']['evidenceId'] == eid]
                if not selected:
                    self._state, self._reason = 'PARTIAL', 'NO_QUALIFIED_PAGES'
                    self._write_manifest(self._pages)
                    return self._reply(False, 'NO_QUALIFIED_PAGES')
            descriptors = [copy.deepcopy(p['descriptor']) for p in selected]
            record_key = self._binding['recordStableKey']
            self._processing_binding = copy.deepcopy(self._binding)
            self._resolve_placements = resolve_placements is True
            self._processing_evidence_ids = [d['evidenceId'] for d in descriptors]
            processor = WarehouseCaptureHost(store_factory=lambda: self.evidence_store, driver_available=False)
            self._processor, self._state = processor, 'ALIGNING'
            self._reason = termination_reason
            try:
                self._write_manifest(self._pages)
            except (OSError, IntakeRejected):
                self._state = 'ERROR'
                return self._reply(False, 'PARTIAL_MANIFEST_WRITE_FAILED')
            self._worker = threading.Thread(target=self._process,
                args=(generation, processor, record_key, descriptors, termination_reason), name='native-warehouse-intake', daemon=True)
            try:
                self._worker.start()
            except Exception:
                self._state = 'ERROR'
                self._reason = 'PROCESSING_START_FAILED'
                self._write_manifest(self._pages)
                return self._reply(False, 'PROCESSING_FAILED')
            return self._reply(True, 'PROCESSING')

    def _process(self, generation, processor, record_key, descriptors, termination_reason):
        try:
            # Recognition uses exactly the pixels derived from each saved Native original.
            # Hash/file integrity is checked again AFTER collection, before any OCR/result write.
            with self._scope_lock, self._lock:
                if (generation != self._generation or self._state != 'ALIGNING'
                        or self._processing_binding != self._binding):
                    raise IntakeRejected('STALE_NATIVE_INTAKE_SESSION')
                pages = copy.deepcopy(self._pages)
            self._verify_saved_pages(pages)
            result = processor._process_saved_pages(record_key, descriptors,
                history_store=_SessionHistory(self, generation), finalization_reason=termination_reason,
                resolve_placements=self._resolve_placements)
        except Exception as exc:
            result = {'ok': False, 'reason': 'PROCESSING_FAILED:' + str(exc)[:120], 'error': type(exc).__name__}
        with self._scope_lock, self._lock:
            if (generation != self._generation or self._state != 'ALIGNING'
                    or self._processing_binding != self._binding):
                return
            self._coverage = result.get('coverageStatus', 'COVERAGE_UNPROVEN')
            self._packet = result.get('packet')
            self._reason = result.get('reason')
            self._state = ('COMPLETE' if self._coverage == 'COMPLETE' else 'PARTIAL') if result.get('ok') else 'ERROR'
            try:
                self._write_manifest(self._pages)
                if result.get('ok') and self._refiner and not self._resolve_placements:
                    self._refiner.enqueue(self._session_id)
            except (OSError, IntakeRejected):
                self._state, self._reason = 'ERROR', 'RESULT_PROVENANCE_WRITE_FAILED'
                self._packet = None

    def _verify_saved_pages(self, pages, *, binding=None):
        binding = _anchor(binding or self._binding)
        for page in pages:
            if (page['descriptor'].get('recordStableKey') != binding['recordStableKey']
                    or page['nativeSource'].get('observationSessionId') != binding['observationSessionId']
                    or page['nativeSource'].get('targetInstance') != binding['targetInstance']):
                raise IntakeRejected('ORIGINAL_FRAME_LEASE_MISMATCH')
            verified = self.draft_store.read_source_image_descriptor(page['nativeSource'])
            raw = verified.get('data')
            if (verified.get('error') or not isinstance(raw, bytes)
                    or hashlib.sha256(raw[54:]).hexdigest() != page['pixelSha256']
                    or (page.get('bmpSha256') and hashlib.sha256(raw).hexdigest() != page['bmpSha256'])):
                raise IntakeRejected('ORIGINAL_FRAME_LEASE_MISMATCH')
            original = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            derived = cv2.imdecode(np.frombuffer(self.evidence_store.load_original(page['descriptor']),np.uint8),cv2.IMREAD_COLOR)
            if original is None or derived is None or not np.array_equal(original,derived):
                raise IntakeRejected('ORIGINAL_DERIVATION_MISMATCH')

    def end_collection(self, reason):
        """Revoke live collection; immutable old-match work keeps its own lease."""
        with self._scope_lock, self._lock:
            if self._state in {'ALIGNING', 'PARTIAL', 'COMPLETE', 'ERROR'}:
                return self._reply(True, self._reason)
            if self._state == 'MANUAL_CAPTURING' and self._pages:
                try:
                    ids = self._saved_support_ids() if self._binding.get('capturePolicy') == DELIVERY else None
                except IntakeRejected as exc:
                    return self.fail_processing(str(exc))
                return self.finish_manual_capture(termination_reason='INCOMPLETE', qualified_evidence_ids=ids)
            return self.cancel_manual_capture(reason=reason)

    def fail_processing(self, reason):
        """Persist a terminal failure and revoke an unfinished worker's write lease."""
        with self._scope_lock, self._lock:
            self._state, self._reason, self._packet = 'ERROR', reason, None
            if self._pages:
                self._write_manifest(self._pages)
            return self._reply(False, reason)

    def _saved_support_ids(self):
        ids = []
        indexed = {p['descriptor']['evidenceId']: p for p in self._pages}
        for page in self._pages:
            if page.get('contentRole') != 'STABLE_SUPPORT':
                continue
            cert = page.get('contentCertificate') or {}
            if (cert.get('schema') != 'visible-content-support.v1'
                    or _anchor(cert.get('scope')) != self._binding
                    or cert.get('reviewBinding') != {'sessionId':self._session_id, 'generation':self._generation}
                    or cert.get('formalFactsQualified') is not False
                    or cert.get('completionState') != 'UNKNOWN' or cert.get('sceneProtected') is not True
                    or cert.get('coverageHoles') != 0 or cert.get('beyondQuantizationPixels') != 0
                    or type(cert.get('maxChannelDelta')) is not int or not 0 <= cert['maxChannelDelta'] <= 1):
                raise IntakeRejected('CONTENT_CERTIFICATE_UNPROVEN')
            for key in ('anchor', 'support'):
                ref = cert.get(key) or {}; saved = indexed.get(ref.get('evidenceId'))
                if (not saved or any(ref.get(k) != saved.get(k) for k in ('pixelSha256','bmpSha256'))
                        or ref.get('sha256') != saved['descriptor']['sha256']
                        or ref.get('captureId') != saved['deliveryProof']['captureId']
                        or cert.get('mapping') != saved.get('clientMap')):
                    raise IntakeRejected('CONTENT_CERTIFICATE_ORIGINAL_CHANGED')
            if cert['support']['evidenceId'] != page['descriptor']['evidenceId']:
                raise IntakeRejected('CONTENT_CERTIFICATE_ORIGINAL_CHANGED')
            ids.append(page['descriptor']['evidenceId'])
        return ids

    def _saved_identity_ids(self):
        support_ids = self._saved_support_ids()
        selected = set(support_ids)
        for page in self._pages:
            if page['descriptor']['evidenceId'] in support_ids:
                selected.add(page['contentCertificate']['anchor']['evidenceId'])
        # Both originals get independently matched. A certificate is not an identity vote.
        return [p['descriptor']['evidenceId'] for p in self._pages if p['descriptor']['evidenceId'] in selected]

    def recover_saved_capture(self, session_id, *, refine_placements=False):
        """Resume a bounded durable intake without a Host or current game scope."""
        with self._scope_lock, self._lock:
            if self._state == 'MANUAL_CAPTURING' or (self._worker and self._worker.is_alive()):
                return self._reply(False, 'PROCESSING_CANCEL_PENDING')
            adopted = False
            try:
                if not re.fullmatch('[0-9a-f]{32}', str(session_id)):
                    raise IntakeRejected('INVALID_INTAKE_SESSION')
                path = self.draft_store.root / 'warehouse-intake' / (session_id + '.json')
                raw = path.read_bytes()
                if len(raw) > MAX_MANIFEST_BYTES:
                    raise IntakeRejected('LIMIT_REACHED')
                manifest = json.loads(raw)
                if (manifest.get('schemaVersion') != 'native-warehouse-intake.v1'
                        or manifest.get('sessionId') != session_id
                        or manifest.get('state') not in {'ALIGNING','ERROR','PARTIAL','COMPLETE'}
                        or type(manifest.get('generation')) is not int or manifest['generation'] <= 0
                        or not 0 < len(manifest.get('pages', [])) <= MAX_PAGES):
                    raise IntakeRejected('INVALID_INTAKE_MANIFEST')
                binding = _anchor(manifest['scope'])
                if self.draft_store.lookup(binding['recordStableKey']) is None:
                    raise IntakeRejected('NATIVE_DRAFT_NOT_SAVED')
                if any(p['descriptor'].get('recordStableKey') != binding['recordStableKey']
                       or p['nativeSource'].get('observationSessionId') != binding['observationSessionId']
                       or p['nativeSource'].get('targetInstance') != binding['targetInstance']
                       for p in manifest['pages']):
                    raise IntakeRejected('ORIGINAL_FRAME_LEASE_MISMATCH')
                self._session_id, self._generation = session_id, manifest['generation']
                self._binding, self._pages = binding, manifest['pages']
                adopted = True
                self._rejected_originals = manifest.get('rejectedOriginals', [])
                self._encoded_bytes = sum(p['descriptor']['byteSize'] for p in self._pages)
                ids = self._saved_support_ids() if binding.get('capturePolicy') == DELIVERY else None
                expected_ids = ids if ids is not None else [p['descriptor']['evidenceId'] for p in self._pages]
                if manifest.get('processingEvidenceIds') is not None and expected_ids != manifest['processingEvidenceIds']:
                    raise IntakeRejected('QUALIFIED_PAGE_SELECTION_UNPROVEN')
                saved = self.draft_store.lookup(binding['recordStableKey'])
                packet = ((saved or {}).get('settlement') or {}).get('warehouseReviewPacket')
                if (manifest['state'] in {'PARTIAL','COMPLETE'} and packet
                        and packet.get('sourceFingerprint') == manifest.get('resultSourceFingerprint')):
                    self._verify_saved_pages(self._pages)
                    self._packet, self._state = copy.deepcopy(packet), manifest['state']
                    self._coverage = (packet.get('warehouseCoverage') or {}).get('status','PARTIAL')
                    self._reason = manifest.get('terminationReason')
                    self._resolve_placements = packet.get('schemaVersion') == 'warehouse-review-packet.v2'
                    self._processing_evidence_ids = expected_ids
                    if self._refiner and (manifest.get('placementRefinementPending') or refine_placements):
                        self._refiner.enqueue(session_id,resume=True)
                    return self._reply(True,'SAVED_ARCHIVE_RESUMED')
                self._state = 'MANUAL_CAPTURING'
                return self.finish_manual_capture(termination_reason='INCOMPLETE', qualified_evidence_ids=ids,
                    resolve_placements=refine_placements and self._refiner is None)
            except (OSError, ValueError, KeyError, IntakeRejected) as exc:
                if adopted:
                    self._state, self._reason = 'ERROR', str(exc)[:160]
                    self._write_manifest(self._pages)
                return self._reply(False, str(exc)[:160])

    def resume_pending(self):
        directory = self.draft_store.root / 'warehouse-intake'
        queued = 0
        for path in sorted(directory.glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True):
            if path.stat().st_size <= MAX_MANIFEST_BYTES:
                try:
                    manifest = json.loads(path.read_text(encoding='utf-8'))
                    if manifest.get('state') == 'ALIGNING':
                        return self.recover_saved_capture(path.stem)
                    if (self._refiner and manifest.get('state') in {'PARTIAL','COMPLETE'}
                            and manifest.get('placementRefinementPending')):
                        reply = self._refiner.enqueue(path.stem)
                        queued += reply.get('reason') == 'REFINEMENT_QUEUED'
                except (ValueError, OSError):
                    continue
        return {'ok': True, 'reason': 'SAVED_REFINEMENT_QUEUED' if queued else 'NO_PENDING_INTAKE', 'queued':queued}

    def cancel_manual_capture(self, *, reason='USER_CANCEL'):
        with self._scope_lock, self._lock:
            if self._refiner and self._session_id and self._state in {'PARTIAL','COMPLETE'}:
                return self._refiner.cancel(self._session_id)
            self._generation += 1
            self._state, self._reason = 'CANCELLED', reason
            self._packet = None
            if self._pages:
                try:
                    self._write_manifest(self._pages)
                except (OSError, IntakeRejected):
                    return self._reply(False, 'PARTIAL_MANIFEST_WRITE_FAILED')
            return self._reply(True, reason)

    def resume_refinement(self, session_id):
        return self._refiner.enqueue(session_id,resume=True) if self._refiner else self._reply(False,'REFINEMENT_UNAVAILABLE')

    def cancel_refinement(self, session_id):
        return self._refiner.cancel(session_id) if self._refiner else self._reply(False,'REFINEMENT_UNAVAILABLE')

    def wait_refinement(self, timeout):
        if self._refiner: self._refiner.wait(timeout)

    def refinement_payload(self, record_key=None):
        with self._scope_lock, self._lock:
            directory = self.draft_store.root/'warehouse-intake'
            paths = ([directory/(self._session_id+'.json')] if not record_key and self._session_id
                     else sorted(directory.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True))
            for path in paths:
                if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES: continue
                try:
                    manifest = json.loads(path.read_text(encoding='utf-8'))
                    if record_key and manifest['scope']['recordStableKey'] != record_key: continue
                except (OSError,ValueError,KeyError,TypeError):
                    continue
                return {**(manifest.get('refinement') or {'state':'PENDING'}),
                    'sessionId':manifest['sessionId'],'recordStableKey':manifest['scope']['recordStableKey'],
                    'pending':manifest.get('placementRefinementPending',False)}
            return None

    def pages_copy(self):
        with self._lock:
            return copy.deepcopy(self._pages)

    def review_packet_copy(self):
        with self._lock:
            return copy.deepcopy(self._packet)

    def wait_processing(self, timeout):
        worker = self._worker
        if worker:
            worker.join(timeout)
            if worker.is_alive():
                raise TimeoutError('Native intake processing still running')

    def presentation_payload(self):
        with self._lock:
            reasons = {'NO_FRESH_NATIVE_FRAME': '没有新鲜 Native 原帧；稳定结算后现有接口不再发布新页。',
                'NO_NEW_NATIVE_FRAME': '没有新的 Native 原帧，未重复追加。',
                'LIMIT_REACHED': '已达到页面或内存输入上限，未追加；已保存页面可完成处理。',
                'STORE_FAILED': '原图保存失败，未追加页面。',
                'HISTORY_NOT_SAVED': '审阅包尚未保存，已保全原图保持可用。',
                'USER_CANCEL': '已取消接收；原图保留，旧处理失去提交资格。'}
            return {'available': False, 'state': self._state, 'segmentCount': len(self._pages),
                'coverageStatus': self._coverage, 'reason': self._reason,
                'message': reasons.get(self._reason, f'Native 只读手动接收 · 已保存 {len(self._pages)} 页' + (f' · {self._reason}' if self._reason else '')),
                'packetAvailable': self._packet is not None,
                'refinement': self.refinement_payload(),
                'placementRefinementPending': bool(self._packet) and not self._resolve_placements,
                'packetFingerprint': (self._packet or {}).get('sourceFingerprint'),
                'stopAvailable': False, 'sessionId': self._session_id,
                'limits': {'pages': MAX_PAGES, 'pixelsPerFrame': MAX_PIXELS, 'encodedBytes': MAX_ENCODED_BYTES}}


class WarehouseCaptureRouter:
    """Native selected commands never fall through to the legacy capture/input path."""
    def __init__(self, legacy, native, native_selected):
        self.legacy, self.native, self.native_selected = legacy, native, native_selected

    def _manual(self):
        return self.native if self.native_selected() else self.legacy

    @property
    def window_message_only(self):
        return bool(self.native_selected())

    def __getattr__(self, name):
        if name in {'prepare_manual', 'start_manual', 'capture_manual_page', 'finish_manual_capture',
                    'resume_refinement', 'cancel_refinement', 'refinement_payload',
                    'cancel_manual_capture', 'presentation_payload', 'review_packet_copy', 'prepare', 'confirm', 'start', '_running'}:
            return getattr(self._manual(), name)
        return getattr(self.legacy, name)

    def stop(self):
        if self.native_selected():
            stop = getattr(self.native, 'stop', None)
            return stop() if stop else self.native.cancel_manual_capture()
        return self.legacy.stop()


class WarehouseReviewHistoryRouter:
    """Keep Native DRAFT review writes isolated and preserve normal history access."""
    def __init__(self, legacy, native_intake):
        self.legacy, self.native_intake = legacy, native_intake
        self.native = native_intake.history_store
        self._native_keys = set()

    def _route(self, key):
        binding = self.native_intake._binding or {}
        known = key in self._native_keys or key == binding.get('recordStableKey')
        native_record = self.native.lookup(key)
        if native_record is not None:
            self._native_keys.add(key)
            if self.legacy is not None and self.legacy.lookup(key) is not None:
                raise IntakeRejected('AMBIGUOUS_REVIEW_RECORD_SOURCE')
            return self.native
        if known:
            return self.native  # Never fall back after a Native record disappears.
        return self.legacy

    def lookup(self, key):
        store = self._route(key)
        return store.lookup(key) if store is not None else None

    def update_record_transactional(self, key, patch, **conditions):
        store = self._route(key)
        if store is None:
            raise IntakeRejected('REVIEW_HISTORY_UNAVAILABLE')
        return store.update_record_transactional(key, patch, **conditions)


class WarehouseIdentityReviewRouter:
    def __init__(self, legacy_session, native_intake, history_router):
        from warehouse_identity_review_session import WarehouseIdentityReviewSession
        self.legacy = legacy_session
        self.native = WarehouseIdentityReviewSession(store=native_intake.evidence_store,
            packet_provider=native_intake.review_packet_copy)
        self.history = history_router
        self._active = legacy_session

    def open(self, packet=None, **kwargs):
        key = (packet or {}).get('recordStableKey')
        self._active = self.native if key and self.history._route(key) is self.history.native else self.legacy
        return self._active.open(packet, **kwargs)

    def __getattr__(self, name):
        return getattr(self._active, name)
