"""Locate retained BGRA changes without fitting a model or granting content authority.

Rectangles below describe the manually inspected 1920x1080 retained scene,
not a production layout detector. Outputs and optional difference images stay
under build/. No capture, input, catalog matching, or runtime imports.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
REGIONS = {
    'protected_grid': (1315, 214, 1877, 776),
    'python_search_roi': (1315, 211, 1915, 847),
    'host_warehouse_hash_roi': (1280, 200, 1920, 1080),
    'host_scene_hash_roi': (60, 125, 355, 220),
    'exit_countdown': (1610, 965, 1880, 1038),
    'skip_button': (1350, 965, 1595, 1038),
    'necklace_tile': (1315, 214, 1369, 267),
    'armor_tile': (1485, 328, 1651, 492),
    'remote_tile': (1654, 552, 1709, 662),
    'lower_purple_reveal': (1541, 664, 1765, 776),
    'lower_white_reveal': (1824, 664, 1877, 719),
    'visible_dark_cells': (1316, 720, 1540, 774),
}


def original(desc):
    raw = Path(desc['bmpPath']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != desc['bmpSha256']:
        raise ValueError('ORIGINAL_HASH_CHANGED')
    if (len(raw) != 54 + 1920 * 1080 * 4 or raw[:2] != b'BM'
            or struct.unpack_from('<I', raw, 10)[0] != 54
            or struct.unpack_from('<ii', raw, 18) != (1920, -1080)
            or struct.unpack_from('<HHI', raw, 26) != (1, 32, 0)):
        raise ValueError('RETAINED_LAYOUT_UNPROVEN')
    pixels = np.frombuffer(raw[54:], np.uint8).reshape(1080, 1920, 4)
    if hashlib.sha256(raw[54:]).hexdigest() != desc['pixelSha256']:
        raise ValueError('PIXEL_HASH_CHANGED')
    return pixels


def contrast_neighbors(a, b):
    # Reuses the old model's high-contrast diagnostic scale. Never a pass gate:
    # a one-level semantic edge change can occupy exactly this same category.
    edge = np.zeros(a.shape[:2], np.uint8)
    for image in (a, b):
        rgb = image[:, :, :3].astype(np.int16)
        edge[:, :-1] |= (np.abs(rgb[:, 1:] - rgb[:, :-1]).max(axis=2) >= 32).astype(np.uint8)
        edge[:-1] |= (np.abs(rgb[1:] - rgb[:-1]).max(axis=2) >= 32).astype(np.uint8)
    return cv2.dilate(edge, np.ones((3, 3), np.uint8)) != 0


def describe(a, b, box):
    x, y, right, bottom = box
    aa, bb = a[y:bottom, x:right], b[y:bottom, x:right]
    delta = bb.astype(np.int16) - aa.astype(np.int16)
    amplitude = np.abs(delta[:, :, :3]).max(axis=2)
    changed, alpha_changed = amplitude != 0, delta[:, :, 3] != 0
    values, counts = np.unique(amplitude[changed], return_counts=True)
    neighbors = contrast_neighbors(aa, bb)
    n, _, components, _ = cv2.connectedComponentsWithStats(changed.astype(np.uint8), 8)
    components = sorted(components[1:n].tolist(), key=lambda s: s[4], reverse=True)
    return {
        'box': list(box), 'rgbChangedPixels': int(changed.sum()),
        'maxChannelDelta': int(amplitude.max()),
        'channelAmplitudeHistogram': dict(zip(map(str, values.tolist()), map(int, counts))),
        'alphaRange': [int(aa[:, :, 3].min()), int(aa[:, :, 3].max()),
                       int(bb[:, :, 3].min()), int(bb[:, :, 3].max())],
        'alphaChangedPixels': int(alpha_changed.sum()),
        'rgbChangedWithoutAlphaChange': int((changed & ~alpha_changed).sum()),
        'changedNearContrast32Pixels': int((changed & neighbors).sum()),
        'changedAwayFromContrast32Pixels': int((changed & ~neighbors).sum()),
        'largestRawChangeComponents': [dict(box=[s[0]+x, s[1]+y, s[0]+x+s[2], s[1]+y+s[3]],
                                          pixels=s[4]) for s in components[:8]],
        'meaning': 'descriptive change locations; no semantic completion, empty-cell or item-fact claim',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pairs', nargs='+', default=['7:8', '8:9', '12:13', '15:16'])
    parser.add_argument('--images', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if ROOT / 'build' not in output.parents:
        parser.error('output must be within this project build/')
    run = json.loads(args.manifest.read_text(encoding='utf-8'))
    result = {'schema': 'retained-change-localization.v1', 'productionChanged': False,
              'newCapture': False, 'grantsAuthority': False,
              'layoutProvenance': 'manually inspected retained 1920x1080 scene only', 'pairs': []}
    output.parent.mkdir(parents=True, exist_ok=True)
    for pair in args.pairs:
        i, j = map(int, pair.split(':'))
        if not 1 <= i < j <= len(run['verifiedOriginals']):
            raise ValueError('INVALID_ORDINAL_PAIR')
        before, after = [run['verifiedOriginals'][k-1] for k in (i, j)]
        a, b = original(before), original(after)
        regions = {name: describe(a, b, box) for name, box in REGIONS.items()}
        regions['host_warehouse_hash_roi']['changedOutsideProtectedGrid'] = (
            regions['host_warehouse_hash_roi']['rgbChangedPixels'] - regions['protected_grid']['rgbChangedPixels'])
        result['pairs'].append({'fromOrdinal': i, 'toOrdinal': j,
            'sourceHashes': [before['bmpSha256'], after['bmpSha256']],
            'readbackGapMs': (after['deliveryProof']['readbackCompletedNs']
                              - before['deliveryProof']['readbackCompletedNs']) / 1e6,
            'regions': regions})
        if args.images:
            x, y, right, bottom = REGIONS['protected_grid']
            aa, bb = a[y:bottom, x:right, :3], b[y:bottom, x:right, :3]
            d = np.abs(bb.astype(np.int16) - aa.astype(np.int16))
            mask = np.repeat(np.any(d != 0, axis=2)[:, :, None], 3, axis=2).astype(np.uint8) * 255
            # Display scaling only; original arrays and measurements are unchanged.
            montage = np.concatenate((aa, bb, mask, np.minimum(d * 40, 255).astype(np.uint8)), axis=1)
            if not cv2.imwrite(str(output.parent / f'pair-{i}-{j}.png'), montage):
                raise OSError('DIAGNOSTIC_IMAGE_WRITE_FAILED')
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'pairs': len(result['pairs']), 'output': str(output), 'grantsAuthority': False}))


if __name__ == '__main__':
    main()
