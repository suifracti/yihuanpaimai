"""Delivery evidence only: never infer producer render time from a local read."""
import json
from pathlib import Path

STRICT = 'wgc-origin-strict-v1'
DELIVERY = 'wgc-delivery-v1'
POLICIES = frozenset((STRICT, DELIVERY))


def validate_delivery(proof, now_ns, *, session=None, max_age_ns=2_000_000_000,
                      require_progress=False):
    try:
        if (not isinstance(proof, dict) or proof.get('schemaVersion') != 'capture-delivery-proof.v2'
                or proof.get('capturePolicy') != DELIVERY or proof.get('deliveryQualified') is not True):
            return 'DELIVERY_PROOF_MISSING'
        fields = ('poolEpoch', 'acquisitionSequence', 'requestNs', 'deadlineNs', 'emptyBoundaryNs',
                  'dequeueBeforeNs', 'dequeueAfterNs', 'sourceTicks', 'repeatedSourceTicks', 'readbackSourceTicks',
                  'previousMarkerNs', 'readbackBeforeNs', 'readbackCompletedNs', 'sourceTimestampNs',
                  'releaseCompletedNs', 'poolBufferCount', 'drainTakeCount', 'boundaryHeldCount')
        if any(type(proof.get(k)) is not int for k in fields):
            return 'DELIVERY_PROOF_NUMBERS'
        if (proof.get('boundaryKind') != 'retained-pool-buffers.v1' or proof['poolBufferCount'] != 2
                or not 1 <= proof['drainTakeCount'] <= 3
                or proof['boundaryHeldCount'] != proof['drainTakeCount'] - 1):
            return 'DELIVERY_BOUNDARY_WITNESS'
        owner = proof['observationSessionId']
        if (not owner or (session is not None and owner != session)
                or proof['captureId'] != f"{owner}/{proof['poolEpoch']}/{proof['acquisitionSequence']}"
                or proof['poolEpoch'] <= 0 or proof['acquisitionSequence'] <= 0):
            return 'DELIVERY_IDENTITY'
        getter, compared = proof['getterBefore'], proof['comparison']
        for sample in (getter, compared):
            ticks, frequency = sample['rawTicks'], sample['frequencyHz']
            if (type(ticks) is not int or type(frequency) is not int or frequency <= 0
                    or sample['nanoseconds'] != (ticks // frequency) * 1_000_000_000
                    + (ticks % frequency) * 1_000_000_000 // frequency):
                return 'DELIVERY_CLOCK_CONVERSION'
        times = [proof['requestNs'], proof['emptyBoundaryNs'], proof['releaseCompletedNs'], proof['dequeueBeforeNs'],
                 proof['dequeueAfterNs'], getter['nanoseconds'], compared['nanoseconds'],
                 proof['readbackBeforeNs'], proof['readbackCompletedNs']]
        if (times[0] <= 0 or times != sorted(times) or getter['frequencyHz'] != compared['frequencyHz']
                or times[-1] >= proof['deadlineNs'] or type(now_ns) is not int
                or not 0 <= now_ns - times[-1] <= max_age_ns):
            return 'DELIVERY_LOCAL_ORDER_OR_EXPIRED'
        source = proof['sourceTicks'] * 100
        progress = source > proof['previousMarkerNs']
        if (source <= 0 or source != proof['sourceTimestampNs']
                or proof['sourceTicks'] != proof['repeatedSourceTicks'] or proof['sourceTicks'] != proof['readbackSourceTicks']
                or source < proof['previousMarkerNs'] or proof.get('sourceMarkerProgress') is not progress
                or (require_progress and not progress)):
            return 'DELIVERY_SOURCE_MARKER'
        status = 'FUTURE_AT_READ' if source > compared['nanoseconds'] else (
            'STALLED_OR_REORDERED' if not progress else 'CONSISTENT_AT_READ')
        strict = progress and source > proof['requestNs'] and source <= compared['nanoseconds']
        if proof.get('originStatus') != status or proof.get('originStrictQualified') is not strict:
            return 'DELIVERY_ORIGIN_CLASSIFICATION'
        return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return 'DELIVERY_PROOF_INVALID'


def independent_support(before, after):
    """Two post-empty deliveries, not two reads of a single saved file."""
    try:
        return (before['captureId'] != after['captureId']
                and before['observationSessionId'] == after['observationSessionId']
                and before['poolEpoch'] == after['poolEpoch']
                and after['acquisitionSequence'] > before['acquisitionSequence']
                and after['requestNs'] >= before['readbackCompletedNs'] + 250_000_000
                and after['emptyBoundaryNs'] >= after['requestNs']
                and after['sourceTimestampNs'] > before['sourceTimestampNs']
                and after.get('sourceMarkerProgress') is True)
    except (KeyError, TypeError):
        return False


def read_slot_proof(root, item, session, target, now_ns):
    path = Path(root) / 'capture-proofs' / f"{item['bufferIndex']}.json"
    with path.open('rb') as stream:
        raw = stream.read(16 * 1024 + 1)
    if len(raw) > 16 * 1024:
        raise ValueError('FRAME_PROOF_TOO_LARGE')
    binding = json.loads(raw)
    proof = binding.get('deliveryProof')
    rejection = validate_delivery(proof, now_ns, session=session, require_progress=False)
    if (rejection or binding.get('capturePolicy') != DELIVERY
            or binding.get('sessionId') != session or binding.get('targetInstance') != target
            or binding.get('bufferIndex') != item['bufferIndex']
            or binding.get('sequence') != item['header']['sequence']
            or binding.get('pixelSha256') != item['rawSha256']
            or proof['readbackCompletedNs'] != item['header']['captureTimestampNs']):
        raise ValueError(rejection or 'FRAME_PROOF_BINDING')
    return binding
