"""Read a saved Native record through Main's production review routers; no recognition."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'core')]
from main_window import MainWindowBridge, OverlayVisibilityController
from native_trial_drafts import NativeTrialDraftStore, resolve_native_trial_history_path
from native_warehouse_intake import (
    NativeWarehouseIntake, WarehouseReviewHistoryRouter, WarehouseIdentityReviewRouter,
)
from warehouse_identity_review_session import WarehouseIdentityReviewSession


class Overlay:
    Visible = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'build'):
        parser.error('Output must remain inside build/')
    drafts = NativeTrialDraftStore(resolve_native_trial_history_path(ROOT))
    before = hashlib.sha256(drafts.history_path.read_bytes()).hexdigest()
    record = drafts.lookup(args.record)
    if not record:
        parser.error('Saved Native DRAFT not found')
    packet = record['settlement']['warehouseReviewPacket']
    intake = NativeWarehouseIntake(draft_store=drafts, scope_provider=lambda: None,
        source_provider=lambda: None, auto_refine=False)
    history = WarehouseReviewHistoryRouter(None, intake)
    review = WarehouseIdentityReviewRouter(WarehouseIdentityReviewSession(), intake, history)
    bridge = MainWindowBridge(OverlayVisibilityController(Overlay()),
        warehouse_identity_review_session=review, warehouse_identity_review_history_store=history)

    def dispatch(**payload):
        reply = bridge.dispatch({'action': 'warehouse_identity_review', **payload})['warehouseIdentityReview']
        assert reply['available'], reply
        assert reply['recordStableKey'] == args.record
        assert reply['packetFingerprint'] == packet['sourceFingerprint']
        return reply

    opened = dispatch(op='open', recordId=args.record)
    assert review._active is review.native  # Same historical route selected by production Main.
    descriptors = {d['evidenceId']: d for d in intake.evidence_store.list_record_evidence(args.record)}
    unit = next(u for u in packet['reviewUnits'] if u['reviewUnitId'] == opened['currentTrackId'])
    images = [opened['bestObservation'], *opened['otherObservations']]
    assert all(i['imageAvailable'] and i['imageDataUrl'].startswith('data:image/png;base64,') for i in images)
    assert opened['hasLegalEvidence'] and {'CONFIRM_CANDIDATE', 'CONFIRM_CATALOG_OVERRIDE'} <= set(opened['availableActions'])
    checked = []
    for observation in unit['observations']:
        descriptor = descriptors[observation['evidenceId']]
        original = intake.evidence_store.load_original(descriptor)
        assert descriptor['recordStableKey'] == args.record and descriptor['kind'] == 'warehouse-segment'
        assert hashlib.sha256(original).hexdigest() == descriptor['sha256']
        source = cv2.imdecode(np.frombuffer(original, np.uint8), cv2.IMREAD_COLOR)
        assert source is not None
        x1, y1, x2, y2 = map(int, observation['bbox'])
        assert 0 <= x1 < x2 <= source.shape[1] and 0 <= y1 < y2 <= source.shape[0]
        # Independently check the unscaled featured crop against its bound original coordinates.
        expected = source[y1:y2, x1:x2]
        assert max(expected.shape[:2]) <= 360
        selected = dispatch(op='select_observation', observationId=observation['observationId'])
        featured = selected['bestObservation']
        assert featured['imageAvailable'] and featured['observationId'] == observation['observationId']
        actual = cv2.imdecode(np.frombuffer(base64.b64decode(featured['imageDataUrl'].split(',', 1)[1]), np.uint8), cv2.IMREAD_COLOR)
        assert np.array_equal(actual, expected), observation['observationId']
        checked.append({'observationId': observation['observationId'], 'evidenceId': observation['evidenceId'],
            'bbox': observation['bbox'], 'size': [actual.shape[1], actual.shape[0]], 'originalSha256': descriptor['sha256']})

    # Exercise the historical unresolved-unit route without supplying an identity or saving a decision.
    unknown = next(u for u in packet['reviewUnits'] if not u.get('candidates'))
    unresolved = dispatch(op='select_track', trackId=unknown['reviewUnitId'])
    assert unresolved['bestObservation']['imageAvailable'] and unresolved['hasLegalEvidence']
    assert not unresolved['candidates'] and 'CONFIRM_CATALOG_OVERRIDE' in unresolved['availableActions']
    assert hashlib.sha256(drafts.history_path.read_bytes()).hexdigest() == before
    summary = {'recordStableKey': args.record, 'packetFingerprint': packet['sourceFingerprint'],
        'evidenceRoot': str(drafts.root), 'productionNativeRoute': True,
        'liveScopeRequired': False, 'historyUnchanged': True, 'recognitionRun': False,
        'unitCount': opened['trackCount'], 'currentTrackId': opened['currentTrackId'],
        'imageCount': len(images), 'verifiedFeaturedCrops': checked,
        'hasLegalEvidence': opened['hasLegalEvidence'], 'availableActions': opened['availableActions'],
        'unresolvedUnit': {'id': unknown['reviewUnitId'], 'imageAvailable': True,
            'candidates': unresolved['candidates'], 'availableActions': unresolved['availableActions']},
        'coverageStatus': opened['coverageStatus'], 'identityResolution': opened['identityResolution']}
    output.mkdir(parents=True, exist_ok=True)
    (output / 'main-readback.json').write_text(json.dumps(opened, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'main-readback-check.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
