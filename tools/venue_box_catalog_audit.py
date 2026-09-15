#!/usr/bin/env python3
"""Read-only legacy venue/box classifier for Venue / Box Catalog Contract v1.

The registry below describes legacy namespaces found in this repository.  It is
not a game-truth alias map and must never be used for production normalization.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


CLASSIFICATIONS = (
    "CATALOG_VALID_CURRENT",
    "LEGACY_ALIAS",
    "UNVERIFIED",
    "CONFLICT",
    "UNKNOWN",
)

UNKNOWN_VALUES = {None, "", "unknown", "未知", "未知场地", "未知箱型"}
LEGACY_VENUE_VALUES = {
    "海贝场", "珊瑚场", "真珠场", "初级场 · 海贝场", "中级场 · 珊瑚场",
    "初级场·海贝场", "中级场·珊瑚场", "haibei", "shanhu", "zhenzhu",
    "密林", "白夜", "海沫", "milin", "baiye", "haimo", "gaoji",
}
LEGACY_TIER_VALUES = {"chuji", "zhongji", "gaoji", "dingji"}
LEGACY_BOX_MARKERS = (
    "包裹", "宝箱", "保险箱", "纸箱", "铁皮箱", "金库保险箱",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _value(record: Mapping[str, Any], key: str) -> Any:
    environment = record.get("environment")
    if isinstance(environment, Mapping) and key in environment:
        return environment.get(key)
    return record.get(key)


def _normalized(value: Any) -> Optional[str]:
    if value in UNKNOWN_VALUES:
        return None
    text = str(value).strip()
    return None if text.casefold() in {"unknown"} else text


def classify_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    environment = record.get("environment")
    environment = environment if isinstance(environment, Mapping) else {}
    conflicts = []
    for field in ("venue", "venueTier", "box"):
        if field in record and field in environment and record[field] != environment[field]:
            conflicts.append(f"TOP_LEVEL_ENVIRONMENT_MISMATCH:{field}")

    venue = _normalized(_value(record, "venue"))
    tier = _normalized(_value(record, "venueTier"))
    box = _normalized(_value(record, "box"))
    if conflicts:
        classification = "CONFLICT"
        reasons = conflicts
    elif venue is None and tier is None and box is None:
        classification = "UNKNOWN"
        reasons = ["NO_USABLE_VENUE_TIER_OR_BOX"]
    else:
        legacy_hits = []
        if venue in LEGACY_VENUE_VALUES:
            legacy_hits.append("LEGACY_VENUE_NAMESPACE")
        if tier in LEGACY_TIER_VALUES:
            legacy_hits.append("LEGACY_TIER_NAMESPACE")
        if box and any(marker in box for marker in LEGACY_BOX_MARKERS):
            legacy_hits.append("LEGACY_BOX_NAMESPACE")
        if legacy_hits:
            classification = "LEGACY_ALIAS"
            reasons = legacy_hits + ["NO_APPROVED_CURRENT_CATALOG"]
        else:
            classification = "UNVERIFIED"
            reasons = ["VALUE_NOT_IN_LEGACY_REGISTRY", "NO_APPROVED_CURRENT_CATALOG"]

    return {
        "classification": classification,
        "reasonCodes": reasons,
        "hasVenue": venue is not None,
        "hasVenueTier": tier is not None,
        "hasBox": box is not None,
    }


def audit_history(path: Path) -> Dict[str, Any]:
    before_hash = _sha256(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload if isinstance(payload, list) else payload.get("records")
    if not isinstance(records, list):
        raise ValueError("HISTORY_RECORDS_NOT_ARRAY")

    counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    for record in records:
        if not isinstance(record, Mapping):
            counts["UNVERIFIED"] += 1
            reason_counts["RECORD_NOT_OBJECT"] += 1
            continue
        result = classify_record(record)
        counts[result["classification"]] += 1
        reason_counts.update(result["reasonCodes"])

    after_hash = _sha256(path)
    if before_hash != after_hash:
        raise RuntimeError("HISTORY_CHANGED_DURING_READ_ONLY_AUDIT")
    return {
        "auditVersion": "venue-box-legacy-history-classification.v1",
        "sourcePath": path.name,
        "sourceSha256": before_hash,
        "recordCount": len(records),
        "approvedCatalogAvailable": False,
        "counts": {name: counts.get(name, 0) for name in CLASSIFICATIONS},
        "reasonCounts": dict(sorted(reason_counts.items())),
        "interpretation": {
            "CATALOG_VALID_CURRENT": "Validated against an approved current-game catalog; impossible until such a catalog exists.",
            "LEGACY_ALIAS": "Matches a historical repository namespace only; this does not assert game truth or a canonical alias.",
            "UNVERIFIED": "Contains a value with no current approved catalog interpretation.",
            "CONFLICT": "The same record contains contradictory duplicate representations.",
            "UNKNOWN": "No usable venue, tier, or box observation is present."
        },
        "historyMutated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("history", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_history(args.history.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
