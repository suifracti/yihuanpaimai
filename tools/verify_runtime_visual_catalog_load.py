# -*- coding: utf-8 -*-
"""Production visual catalog load probe.

Uses visual_catalog + catalog_validator + OpenCV decode. Does not mutate assets.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

TZ = timezone(timedelta(hours=8))


def _sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _decode_ok(path: Path) -> Tuple[bool, str]:
    import cv2
    import numpy as np
    if not path.is_file():
        return False, "missing_file"
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return False, "decode_failed"
    h, w = image.shape[:2]
    if h < 1 or w < 1:
        return False, "empty_image"
    return True, f"{w}x{h}"


def _manifest_choice(root: Path) -> Dict[str, Any]:
    v2 = root / "assets/items/catalog_reference_manifest_v2.json"
    v1 = root / "assets/items/catalog_reference_manifest_v1.json"
    if v2.is_file():
        return {"selected": "v2", "path": str(v2), "reason": "catalog_reference_manifest_v2.json exists"}
    if v1.is_file():
        return {"selected": "v1", "path": str(v1), "reason": "v2 missing; fallback to v1"}
    return {"selected": None, "path": None, "reason": "neither manifest present"}


def _walk_visual(root: Path) -> Dict[str, Any]:
    from catalog_validator import validate_catalog_record, reset_catalog_cache
    reset_catalog_cache()
    path = root / "assets/items/visual_catalog_v2.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    accepted, rejected = [], []
    for rec in data.get("records", []):
        cid = rec.get("catalogId")
        src = root / rec.get("sourcePath", "")
        reasons = []
        if rec.get("reviewStatus") != "VISUALLY_CHECKED_SOURCE_CARD":
            reasons.append(f"reviewStatus={rec.get('reviewStatus')}")
        if not src.is_file():
            reasons.append("source_missing")
        elif _sha256(src) != rec.get("sourceSha256"):
            reasons.append("source_sha256_mismatch")
        else:
            ok, info = _decode_ok(src)
            if not ok:
                reasons.append(f"source_decode:{info}")
        try:
            validate_catalog_record(rec, root=root)
        except Exception as exc:
            reasons.append(f"validate_catalog_record:{type(exc).__name__}: {exc}")
        row = {
            "catalogId": cid,
            "name": rec.get("name"),
            "sourcePath": rec.get("sourcePath"),
            "legacyCatalogId": rec.get("legacyCatalogId"),
            "width": rec.get("width"),
            "height": rec.get("height"),
            "rarity": rec.get("rarity"),
        }
        if reasons:
            row["reasons"] = reasons
            rejected.append(row)
        else:
            accepted.append(row)
    return {
        "path": str(path),
        "declaredRecords": len(data.get("records", [])),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "acceptedIds": sorted(r["catalogId"] for r in accepted if r.get("catalogId")),
        "rejectedRows": rejected,
        "acceptedRows": accepted,
    }


def _walk_manifest(root: Path, manifest_path: Path, label: str) -> Dict[str, Any]:
    from catalog_validator import validate_catalog_record, reset_catalog_cache
    reset_catalog_cache()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    accepted, rejected, skipped = [], [], []
    for rec in data.get("records", []):
        cid = rec.get("catalogId")
        status = rec.get("status")
        crop_rel = str(rec.get("cropRelativePath") or "")
        crop = root / crop_rel
        shot_rel = str(rec.get("sourceScreenshot") or "")
        shot = root / shot_rel
        row = {
            "catalogId": cid,
            "name": rec.get("name"),
            "status": status,
            "cropRelativePath": crop_rel,
            "sourceScreenshot": shot_rel,
        }
        if status != "RECOVERED_DETERMINISTIC":
            row["reasons"] = [f"status={status}"]
            skipped.append(row)
            continue
        reasons = []
        try:
            validate_catalog_record(rec, root=root)
        except Exception as exc:
            reasons.append(f"validate_catalog_record:{type(exc).__name__}: {exc}")
        if not crop.is_file():
            reasons.append("crop_missing")
        elif _sha256(crop) != rec.get("cropSha256"):
            reasons.append("crop_sha256_mismatch")
        else:
            ok, info = _decode_ok(crop)
            if not ok:
                reasons.append(f"crop_decode:{info}")
        if shot_rel:
            if not shot.is_file():
                reasons.append("source_screenshot_missing")
            else:
                ok, info = _decode_ok(shot)
                if not ok:
                    reasons.append(f"source_screenshot_decode:{info}")
                expected = rec.get("sourceScreenshotSha256")
                if expected and _sha256(shot) != expected:
                    reasons.append("source_screenshot_sha256_mismatch")
        if reasons:
            row["reasons"] = reasons
            rejected.append(row)
        else:
            accepted.append(row)
    return {
        "label": label,
        "path": str(manifest_path),
        "declaredTotal": data.get("totalRecords"),
        "declaredRecovered": data.get("recoveredCount"),
        "declaredUnresolved": data.get("unresolvedCount"),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "skippedNonRecovered": len(skipped),
        "acceptedIds": sorted(r["catalogId"] for r in accepted if r.get("catalogId")),
        "rejectedRows": rejected,
        "skippedRows": skipped,
        "acceptedRows": accepted,
    }


def _call_production_loaders(root: Path) -> Dict[str, Any]:
    import visual_catalog
    from catalog_validator import reset_catalog_cache
    reset_catalog_cache()
    visual_catalog.verified_references.cache_clear()
    visual_catalog.deterministic_reference_crops.cache_clear()
    out: Dict[str, Any] = {"root": str(root)}
    try:
        refs = visual_catalog.verified_references(root=root)
        out["verified_references"] = {
            "ok": True,
            "count": len(refs),
            "ids": sorted({r.get("catalogId") for r in refs if r.get("catalogId")}),
        }
    except Exception as exc:
        out["verified_references"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=8),
        }
        refs = []
    try:
        crops = visual_catalog.deterministic_reference_crops(root=root)
        out["deterministic_reference_crops"] = {
            "ok": True,
            "count": len(crops),
            "ids": sorted({r.get("catalogId") for r in crops if r.get("catalogId")}),
        }
    except Exception as exc:
        out["deterministic_reference_crops"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=8),
        }
        crops = []
    try:
        templates = visual_catalog.load_visual_templates(include_development=False)
        out["load_visual_templates"] = {
            "ok": True,
            "keyCount": len(templates),
            "keys": sorted(templates.keys()),
        }
    except Exception as exc:
        out["load_visual_templates"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=8),
        }
        templates = {}
    try:
        from warehouse_placement_resolver import WarehousePlacementResolver
        placement = WarehousePlacementResolver(root=root)
        out["warehouse_placement_resolver"] = {
            "ok": True,
            "manifestPath": str(placement._manifest_path),
            "manifestName": Path(placement._manifest_path).name,
            "selectedV2": Path(placement._manifest_path).name.endswith("v2.json"),
            "cropsDir": str(placement._crops_dir),
            "refCacheCount": len(getattr(placement, "_ref_cache", {})),
        }
    except Exception as exc:
        out["warehouse_placement_resolver"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=8),
        }
    # Reconstruct templates from THIS root so packaged probes cannot silently
    # read D:\\yihuanpaimai\\assets via visual_catalog.asset_root().
    try:
        import cv2
        import numpy as np
        from visual_catalog import _catalog_reference_body
        templates = {}
        for record in refs:
            image = cv2.imdecode(np.fromfile(str(root / record["sourcePath"]), np.uint8), 1)
            if image is None:
                continue
            x, y, w, h = record["cardBbox"]
            body = image[y + round(h * .23):y + round(h * .74), x + round(w * .20):x + round(w * .80)]
            if body.size:
                templates[f"visual/{record['catalogId']}.png"] = True
            expanded = image[y + round(h * .18):y + round(h * .76), x + round(w * .20):x + round(w * .80)]
            if expanded.size:
                templates[f"visual/{record['catalogId']}@expanded.png"] = True
        for record in crops:
            image = cv2.imdecode(np.fromfile(str(root / record["cropRelativePath"]), np.uint8), 1)
            if image is None or not image.size:
                continue
            body = _catalog_reference_body(image)
            if body.size:
                templates[f"visual/{record['catalogId']}@catalog-reference-crop.png"] = True
        escaped = [
            str(root / rec.get("sourcePath", ""))
            for rec in refs
            if rec.get("sourcePath") and not str((root / rec["sourcePath"]).resolve()).startswith(str(root.resolve()))
        ]
        out["rootedTemplates"] = {
            "ok": True,
            "keyCount": len(templates),
            "keys": sorted(templates),
            "pathsEscapeRoot": escaped,
        }
    except Exception as exc:
        out["rootedTemplates"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return out


def _set_compare(v1_ids, v2_ids, visual_ids) -> Dict[str, Any]:
    v1, v2, vis = set(v1_ids), set(v2_ids), set(visual_ids)
    return {
        "v2_minus_v1": sorted(v2 - v1),
        "v1_minus_v2": sorted(v1 - v2),
        "v2_intersect_visual": sorted(v2 & vis),
        "visual_minus_v2": sorted(vis - v2),
        "v2_minus_visual": sorted(v2 - vis),
        "counts": {
            "v1": len(v1),
            "v2": len(v2),
            "visual": len(vis),
            "v2_minus_v1": len(v2 - v1),
            "v1_minus_v2": len(v1 - v2),
            "v2_intersect_visual": len(v2 & vis),
            "union_v2_visual": len(v2 | vis),
        },
        "note": "Do not treat len(v2)-len(v1) as net-new distinct collectibles. Overlap with visual_catalog_v2 and catalog_065 must be inspected by catalogId and verified name.",
    }


def probe(root: Path, label: str) -> Dict[str, Any]:
    choice = _manifest_choice(root)
    visual = _walk_visual(root)
    v2_path = root / "assets/items/catalog_reference_manifest_v2.json"
    v1_path = root / "assets/items/catalog_reference_manifest_v1.json"
    man_v2 = _walk_manifest(root, v2_path, "v2") if v2_path.is_file() else None
    man_v1 = _walk_manifest(root, v1_path, "v1") if v1_path.is_file() else None
    production = _call_production_loaders(root)
    compare = _set_compare(
        (man_v1 or {}).get("acceptedIds") or [],
        (man_v2 or {}).get("acceptedIds") or [],
        visual.get("acceptedIds") or [],
    )
    unresolved = []
    for block in (man_v2, man_v1):
        if not block:
            continue
        for row in block.get("skippedRows") or []:
            if row.get("catalogId") == "image2-1-1":
                unresolved.append({"manifest": block["label"], **row})
    blocking = []
    if not production.get("verified_references", {}).get("ok"):
        blocking.append("verified_references_loader_failed")
    if not production.get("deterministic_reference_crops", {}).get("ok"):
        blocking.append("deterministic_reference_crops_loader_failed")
    if not production.get("load_visual_templates", {}).get("ok"):
        blocking.append("load_visual_templates_failed")
    if visual["rejected"]:
        blocking.append(f"visual_records_rejected:{len(visual['rejected'])}")
    if man_v2 and man_v2["rejected"]:
        blocking.append(f"manifest_v2_recovered_rejected:{len(man_v2['rejected'])}")
    return {
        "label": label,
        "root": str(root),
        "generatedAt": datetime.now(TZ).isoformat(),
        "python": sys.version,
        "cv2Imported": True,
        "manifestChoice": choice,
        "visualCatalogV2": {
            k: visual[k] for k in
            ("path", "declaredRecords", "accepted", "rejected", "acceptedIds", "rejectedRows")
        },
        "manifestV2": None if man_v2 is None else {
            k: man_v2[k] for k in (
                "path", "declaredTotal", "declaredRecovered", "declaredUnresolved",
                "accepted", "rejected", "skippedNonRecovered", "acceptedIds",
                "rejectedRows", "skippedRows",
            )
        },
        "manifestV1": None if man_v1 is None else {
            k: man_v1[k] for k in (
                "path", "declaredTotal", "declaredRecovered", "declaredUnresolved",
                "accepted", "rejected", "skippedNonRecovered", "acceptedIds",
                "rejectedRows", "skippedRows",
            )
        },
        "setCompare": compare,
        "productionLoaders": production,
        "image2_1_1": unresolved,
        "blocking": blocking,
        "precheckPass": not blocking,
        "productionBranches": {
            "settlement_item_recognizer": "load_visual_templates() for pixel identity",
            "settlement_catalog_candidates": "verified_references + deterministic_reference_crops merged onto catalog_065",
            "warehouse_placement_resolver": "prefers manifest v2 if file exists else v1",
            "shape_matcher_item_identity_resolver": "catalog_065.json only; supplemental visual IDs are not in this geometry index",
        },
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--label", default="source")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = probe(args.root.resolve(), args.label)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(json.dumps({
        "label": payload["label"],
        "precheckPass": payload["precheckPass"],
        "blocking": payload["blocking"],
        "manifestChoice": payload["manifestChoice"],
        "visualAccepted": payload["visualCatalogV2"]["accepted"],
        "visualRejected": payload["visualCatalogV2"]["rejected"],
        "v2Accepted": None if payload["manifestV2"] is None else payload["manifestV2"]["accepted"],
        "v2Rejected": None if payload["manifestV2"] is None else payload["manifestV2"]["rejected"],
        "v1Accepted": None if payload["manifestV1"] is None else payload["manifestV1"]["accepted"],
        "setCompareCounts": payload["setCompare"]["counts"],
        "production": {
            k: {"ok": v.get("ok"), "count": v.get("count") or v.get("keyCount") or v.get("itemCount"),
                "error": v.get("error")}
            for k, v in payload["productionLoaders"].items() if k != "root"
        },
        "output": str(args.output) if args.output else None,
    }, ensure_ascii=False, indent=2))
    return 0 if payload["precheckPass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
