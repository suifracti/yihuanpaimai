"""Compare a production review packet with a separately authored reference.

This audit never changes the packet, candidates, or confirmation decisions.
Visible-viewport references cannot prove whole-warehouse acceptance.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from warehouse_auto_confirmation import evaluate_auto_confirmation
from catalog_validator import validate_catalog_record


def audit(packet, reference):
    metadata = reference['metadata']
    if metadata['annotationScope'] not in {'VISIBLE_VIEWPORT_ONLY', 'WHOLE_WAREHOUSE'}:
        raise ValueError('Reference scope must be explicit')
    if packet['recordStableKey'] != metadata['recordStableKey']:
        raise ValueError('Reference and packet belong to different matches')
    if not reference['items']:
        raise ValueError('An empty reference cannot establish item acceptance')
    expected = {}
    for item in reference['items']:
        box = item['gridBoundingBox']
        validate_catalog_record({'catalogId': item['catalogId'], 'name': item['canonicalName'],
            'widthCells': box['width'], 'heightCells': box['height'], 'quality': item['quality'],
            'sourceScreenshot': item['sourceScreenshot'], 'sourceScreenshotSha256': item['sourceScreenshotSha256'],
            'bbox': item['cardBbox']}, root=ROOT)
        key = tuple(box[k] for k in ('row', 'col', 'width', 'height'))
        if key in expected:
            raise ValueError('Duplicate reference placement')
        expected[key] = item
    units = evaluate_auto_confirmation(packet['reviewUnits'], packet['segments'])
    matched, extras, wrong, unknown, duplicates = [], [], [], [], []
    seen = set()
    for unit in units:
        anchor, footprint = unit.get('worldAnchor') or {}, unit.get('footprint') or {}
        key = (anchor.get('row'), anchor.get('col'), footprint.get('widthCells'), footprint.get('heightCells'))
        uid = unit['reviewUnitId']
        if key not in expected:
            extras.append({'unitId': uid, 'placement': key})
            continue
        if key in seen:
            duplicates.append(uid)
            continue
        seen.add(key)
        item = expected[key]
        matched.append({'unitId': uid, 'referenceId': item['referenceId']})
        if unit.get('confirmationStatus') != 'CONFIRMED':
            unknown.append({'unitId': uid, 'referenceId': item['referenceId'],
                'reasons': unit.get('unconfirmedReasons', [])})
        elif unit.get('canonicalName') != item['canonicalName'] or unit.get('selectedCatalogId') != item['catalogId']:
            wrong.append({'unitId': uid, 'expectedId': item['catalogId'],
                'actualId': unit.get('selectedCatalogId'), 'actualName': unit.get('canonicalName')})
    missing = [item['referenceId'] for key, item in expected.items() if key not in seen]
    geometry_pass = not (missing or extras or duplicates)
    identity_pass = geometry_pass and not (wrong or unknown)
    coverage = packet.get('warehouseCoverage') or {}
    return {'referenceScope': metadata['annotationScope'], 'expectedCount': len(expected),
        'predictedCount': len(units), 'exactGeometryCount': len(matched),
        'confirmedCorrectCount': len(matched) - len(wrong) - len(unknown),
        'visibleGeometryPass': geometry_pass, 'visibleIdentityPass': identity_pass,
        'wholeWarehouseAcceptance': bool(metadata['annotationScope'] == 'WHOLE_WAREHOUSE' and identity_pass and coverage.get('status') == 'COMPLETE'),
        'missing': missing, 'extraRegions': extras, 'duplicateUnits': duplicates,
        'wrongIdentities': wrong, 'unconfirmedUnits': unknown, 'matched': matched}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packet', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a fresh report path')
    result = audit(json.loads(args.packet.read_text(encoding='utf-8')), json.loads(args.reference.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
