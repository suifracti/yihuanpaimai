"""Bound two immutable SOURCE originals to visible support, never item facts."""
import copy
import hashlib
import time

from native_capture_delivery import independent_support
from native_warehouse_content_stability import content_stability, content_observation
from scene_anchors import settlement_title_visible
from warehouse_scrollbar_observation import warehouse_search_roi


class VisibleContentGate:
    offline_only = False

    def __init__(self):
        self._frames, self._representatives = {}, []
        self._sampling_required, self._sampling_ready = False, False
        self._hint = None
        self._hint_floor = self._hint_until = 0

    def reset(self):
        self._frames.clear()
        self._representatives.clear()
        self._sampling_required, self._sampling_ready = False, False
        self._hint = None
        self._hint_floor = self._hint_until = 0

    def read_page(self, frame, page, scope, mapping, *, role, review_binding):
        if not mapping or page.get('clientMap') != mapping:
            raise ValueError('CONTENT_MAPPING_UNPROVEN')
        key = page['deliveryProof']['captureId']
        self._frames[key] = frame.copy()
        while len(self._frames) > 2:
            self._frames.pop(next(iter(self._frames)))
        x,y,r,b = warehouse_search_roi(frame.shape[1],frame.shape[0])
        if not content_observation(frame[y:b,x:r])['qualified']:
            self.require_sampling_hint(page['deliveryProof']['readbackCompletedNs'])
        return {'scope': copy.deepcopy(scope), 'mapping': mapping,
                'reviewBinding': copy.deepcopy(review_binding), 'evidenceId': page['descriptor']['evidenceId'],
                'sha256': page['descriptor']['sha256'], 'captureId': page['deliveryProof']['captureId'],
                'pixelSha256': page['pixelSha256'], 'bmpSha256': page['bmpSha256'],
                'rawBgrSha256': hashlib.sha256(frame.tobytes()).hexdigest()}

    def request_eligible(self):
        return not self._sampling_required or (self._sampling_ready and time.perf_counter_ns() <= self._hint_until)

    def require_sampling_hint(self, floor_ns):
        self._sampling_required, self._sampling_ready = True, False
        self._hint = None
        self._hint_floor = floor_ns

    def sampling_hint(self, crop, *, capture_id, readback_ns):
        if readback_ns <= self._hint_floor:
            return False
        previous = self._hint
        self._hint = (capture_id, readback_ns, crop.copy())
        self._sampling_ready = bool(previous and previous[0] != capture_id and previous[1] < readback_ns
            and content_stability(previous[2],crop)['qualified'])
        self._hint_until = readback_ns + 2_000_000_000
        return self._sampling_ready

    def compare(self, before, after):
        a, b = before['contentProfile'], after['contentProfile']
        if (a['scope'] != b['scope'] or a['mapping'] != b['mapping']
                or a['reviewBinding'] != b['reviewBinding']
                or not independent_support(before['deliveryProof'], after['deliveryProof'])):
            return {'qualified': False, 'reason': 'CONTENT_SCOPE_OR_INDEPENDENCE_UNPROVEN'}
        frames = [self._frames.get(p['captureId']) for p in (a, b)]
        if any(f is None or hashlib.sha256(f.tobytes()).hexdigest() != p['rawBgrSha256']
               for f, p in zip(frames, (a, b))):
            return {'qualified': False, 'reason': 'CONTENT_ORIGINAL_UNAVAILABLE'}
        if any(not settlement_title_visible(f) for f in frames):
            return {'qualified': False, 'reason': 'CONTENT_SCENE_UNPROVEN'}
        if frames[0].shape != frames[1].shape:
            return {'qualified': False, 'reason': 'CONTENT_GEOMETRY_UNPROVEN'}
        x, y, r, bottom = warehouse_search_roi(frames[0].shape[1], frames[0].shape[0])
        result = content_stability(*(f[y:bottom, x:r] for f in frames))
        if result['qualified']:
            def ref(p):
                return {k:p[k] for k in ('evidenceId','sha256','captureId','pixelSha256','bmpSha256')}
            result['certificate'] = {'schema': 'visible-content-support.v1', 'scope': a['scope'],
                'mapping': a['mapping'], 'reviewBinding': a['reviewBinding'],
                'anchor': ref(a), 'support': ref(b), 'protectedBox': [x,y,r,bottom],
                'coverageHoles': 0, 'maxChannelDelta': result['maxChannelDelta'],
                'beyondQuantizationPixels': 0, 'sceneProtected': True,
                'formalFactsQualified': False, 'completionState': 'UNKNOWN'}
        return result

    def final_support(self, observation):
        result = observation.get('contentStability') or {}
        certificate = result.get('certificate') or {}
        current = observation.get('contentProfile') or {}
        frame = self._frames.get(current.get('captureId'))
        if (not result.get('qualified') or any(certificate.get('support', {}).get(k) != current.get(k)
                for k in ('evidenceId', 'sha256', 'captureId', 'pixelSha256', 'bmpSha256'))
                or certificate.get('scope') != current.get('scope') or certificate.get('mapping') != current.get('mapping')
                or frame is None or hashlib.sha256(frame.tobytes()).hexdigest() != current.get('rawBgrSha256')):
            return {'qualified': False, 'reason': 'CONTENT_CERTIFICATE_UNPROVEN'}
        return result

    def commit_support(self, intake, observation):
        result = self.final_support(observation)
        if not result['qualified']:
            raise ValueError(result['reason'])
        intake.annotate_visible_content_support(result['certificate'])
        key = result['certificate']['support']['evidenceId']
        if key not in self._representatives:
            self._representatives.append(key)

    def representatives(self):
        return list(self._representatives)

    def release(self):
        self._frames.clear()
        self._hint = None
        self._sampling_ready = False
