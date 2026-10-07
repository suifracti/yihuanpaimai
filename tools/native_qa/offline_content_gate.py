"""Offline adapter to the existing collector. Cannot be enabled by live UI.

Only the most recent two decoded originals are held. Records and certificates
are bounded by the existing SOURCE limit. No frame capture or input API here.
"""
import copy
import hashlib

import numpy as np

from native_capture_delivery import independent_support, validate_delivery
from native_warehouse_sampling_model import CommonSamplingModel


class OfflineContentGate:
    offline_only = True

    def __init__(self, layout):
        self.model = CommonSamplingModel(layout)
        self._frames, self._representatives = {}, []
        self.comparisons = []
        self._scope = self._mapping = None
        self._eligible, self._last_hint_ns = True, 0
        self._last_hint_sequence = 0

    def read_page(self, frame, page, scope, mapping, *, role='UNQUALIFIED_OBSERVATION', review_binding):
        if not mapping or page.get('clientMap') != mapping:
            raise ValueError('CONTENT_MAPPING_UNPROVEN')
        p = page['deliveryProof']
        d = page['descriptor']
        key = d['evidenceId']
        self._scope, self._mapping = copy.deepcopy(scope), mapping
        self._frames[key] = frame.copy()
        while len(self._frames) > 2:
            self._frames.pop(next(iter(self._frames)))
        button = frame[984:1011, 1440:1558]
        profile = self.model.profile(frame)
        self._eligible = profile['unrevealed']['qualified']
        return {'scope': copy.deepcopy(scope), 'mapping': mapping, 'temporalRole': role,
                'reviewBinding':copy.deepcopy(review_binding),
                'evidenceId': key, 'sha256': d['sha256'], 'captureId': p['captureId'],
                'pixelSha256': page['pixelSha256'], 'bmpSha256': page['bmpSha256'],
                'rawBgrSha256': hashlib.sha256(frame.tobytes()).hexdigest(),
                'button': {'rawSha256': hashlib.sha256(button.tobytes()).hexdigest(),
                           'appearance': 'UNKNOWN', 'textMeaning': 'separate diagnostic; not reveal completion'},
                'protected': profile}

    def hint(self, frame, *, scope, mapping, proof, now_ns):
        if (scope != self._scope or mapping != self._mapping or now_ns-self._last_hint_ns < 600_000_000
                or validate_delivery(proof, now_ns, session=scope.get('observationSessionId'), require_progress=True)
                or proof.get('acquisitionSequence', 0) <= self._last_hint_sequence):
            return False
        self._last_hint_ns, self._last_hint_sequence = now_ns, proof['acquisitionSequence']
        self._eligible = self.model.profile(frame)['unrevealed']['qualified']
        return True

    def request_eligible(self):
        return self._eligible

    def compare(self, before, after):
        a, b = before['offlineContentProfile'], after['offlineContentProfile']
        if (a['scope'] != b['scope'] or a['mapping'] != b['mapping'] or a['reviewBinding'] != b['reviewBinding']
                or a['evidenceId'] == b['evidenceId'] or not independent_support(
                    before['deliveryProof'], after['deliveryProof'])):
            return {'qualified': False, 'reason': 'CONTENT_SCOPE_OR_INDEPENDENCE_UNPROVEN'}
        frames = [self._frames.get(p['evidenceId']) for p in (a, b)]
        if any(f is None or hashlib.sha256(f.tobytes()).hexdigest() != p['rawBgrSha256']
               for f, p in zip(frames, (a, b))):
            return {'qualified': False, 'reason': 'CONTENT_ORIGINAL_UNAVAILABLE'}
        result = self.model.compare(*frames)
        if len(self.comparisons) < 32:
            self.comparisons.append(result)
        if result['qualified']:
            def reference(p):
                return {k: p[k] for k in ('evidenceId', 'sha256', 'captureId', 'pixelSha256', 'bmpSha256')}
            result['certificate'] = {'schema': 'offline-content-support.v1', 'scope': a['scope'],
                'mapping': a['mapping'], 'reviewBinding':a['reviewBinding'], 'anchor': reference(a), 'support': reference(b),
                'protectedBox': list(self.model.layout.protected), 'coverageHoles': 0,
                'phaseQ5': result['phaseQ5'], 'unexplainedPixels': 0,
                'topologySupported': True, 'formalFactsQualified': False,
                'meaning': result['meaning'], 'rendererContractEstablishedForGame': False}
        return result

    def final_support(self, observation):
        result = observation.get('contentStability') or {}
        certificate = result.get('certificate') or {}
        current = observation.get('offlineContentProfile') or {}
        if (not result.get('qualified') or certificate.get('support', {}).get('evidenceId') != current.get('evidenceId')
                or certificate.get('scope') != current.get('scope') or certificate.get('mapping') != current.get('mapping')):
            return {'qualified': False, 'reason': 'CONTENT_CERTIFICATE_UNPROVEN'}
        return result

    def commit_support(self, intake, observation):
        certificate = self.final_support(observation)
        if not certificate['qualified']:
            raise ValueError(certificate['reason'])
        intake.annotate_offline_content_support(certificate['certificate'])
        key = certificate['certificate']['support']['evidenceId']
        if key not in self._representatives:
            self._representatives.append(key)

    def representatives(self):
        return list(self._representatives)

    def release(self):
        self._frames.clear()
        self._scope = self._mapping = None
        self._eligible = False
