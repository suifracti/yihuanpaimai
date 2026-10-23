"""Merge return-scene bill copies using the saved frame sequence, never prices alone."""
import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
from canonical_history_store import CanonicalHistoryStore


def recover(history, frames):
    store = CanonicalHistoryStore(Path(history))
    active = None
    owners, scenes = {}, {}
    for line in Path(frames).read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        key, scene = row.get('stateMatchId'), row.get('scene')
        scenes.setdefault(key, set()).add(scene)
        if scene == 'IN_AUCTION':
            active = key
        elif active and key != active:
            owners.setdefault(key, set()).add(active)
    merged = []
    for duplicate, candidates in owners.items():
        if len(candidates) != 1 or scenes[duplicate] & {'IN_AUCTION', 'SETTLEMENT'}:
            continue
        owner = next(iter(candidates))
        source, target = store.lookup(duplicate), store.lookup(owner)
        if not source or not target:
            continue
        if any(r.get('lifecycleStatus') != 'DRAFT' or r.get('dataOrigin') != 'live-trial' for r in (source, target)):
            continue
        bill, original = source.get('settlement') or {}, target.get('settlement') or {}
        if bill.get('actualTotal') is None or (source.get('bidding') or {}).get('rounds') or bill.get('reviewUnits'):
            continue
        if any(bill.get(k) != original.get(k) for k in ('actualTotal', 'clearingPrice', 'realizedProfit')):
            raise ValueError('Return-scene bill conflicts with its preceding auction: ' + duplicate)
        a, b = [(r.get('auctionEvidence') or {}).get('nativeObservation') or {} for r in (source, target)]
        if not a.get('observationSessionId') or a.get('observationSessionId') != b.get('observationSessionId'):
            continue
        evidence = copy.deepcopy(target.get('auctionEvidence') or {})
        copies = evidence.setdefault('mergedReturnSceneDrafts', [])
        if not any(r.get('id') == duplicate for r in copies):
            # Preserve original IDs/descriptors and every field for later review.
            copies.append(source)
        store.update_record_transactional(owner, {'auctionEvidence': evidence})
        store.delete_record_transactional(duplicate, write_rolling_backup=False)
        merged.append({'duplicate': duplicate, 'owner': owner})
    return merged


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('history')
    parser.add_argument('frames')
    args = parser.parse_args()
    print(json.dumps(recover(args.history, args.frames), ensure_ascii=False, indent=2))
