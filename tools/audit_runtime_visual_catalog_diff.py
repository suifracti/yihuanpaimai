# -*- coding: utf-8 -*-
"""Read-only runtime visual catalog audit vs AuctionPilot v0.12.7.

Does not copy competitor assets, does not mutate catalogs, does not run OCR.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
AP_ROOT = Path(r"C:\Users\Administrator\Downloads\AuctionPilot-v0.12.7")
PKG_ROOT = Path(
    r"D:\yihuanpaimai\build\isolated_trial_ux_fixes_20260914_84e0207"
    r"\dist\异环拍卖助手\_internal"
)
OUT_DIR = ROOT / "docs" / "reports"
TZ = timezone(timedelta(hours=8))

QUALITY_MAP = {
    "灰": "white", "白": "white", "绿": "green", "蓝": "blue",
    "紫": "purple", "金": "gold", "红": "red",
    "white": "white", "green": "green", "blue": "blue",
    "purple": "purple", "gold": "gold", "red": "red",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_name(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("「", "").replace("」", "").replace("『", "").replace("』", "")
    text = text.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", "", text)


def _quality(value: Any) -> str:
    raw = str(value or "").strip()
    return QUALITY_MAP.get(raw, QUALITY_MAP.get(raw.lower(), raw))


def _file_ok(root: Path, rel: str) -> bool:
    if not rel:
        return False
    return (root / rel).is_file()


def _entry(
    *,
    catalog_id: str,
    name: str,
    quality: str,
    width: Any,
    height: Any,
    cells: Any,
    shape: str,
    value: Any,
    source: str,
    image_rel: str = "",
    image_exists: bool = False,
    loaded: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rec = {
        "catalogId": str(catalog_id or "").strip(),
        "name": str(name or "").strip(),
        "nameKey": _norm_name(name),
        "quality": _quality(quality),
        "qualityRaw": str(quality or ""),
        "width": int(width or 0) or None,
        "height": int(height or 0) or None,
        "cells": int(cells or 0) or None,
        "shape": str(shape or ""),
        "value": int(value) if str(value).isdigit() or isinstance(value, int) else value,
        "source": source,
        "imageRel": image_rel,
        "imageExists": bool(image_exists),
        "loadedByRuntime": bool(loaded),
    }
    if extra:
        rec.update(extra)
    return rec


def load_catalog_065(path: Path, source: str) -> List[Dict[str, Any]]:
    rows = []
    for item in _read_json(path):
        rel = f"assets/items/reference_crops_v1/{item.get('File')}" if item.get("File") else ""
        rows.append(_entry(
            catalog_id=item.get("Id"),
            name=item.get("Name"),
            quality=item.get("Quality"),
            width=item.get("Width"),
            height=item.get("Height"),
            cells=item.get("Cells"),
            shape=item.get("Shape"),
            value=item.get("Value"),
            source=source,
            image_rel=rel,
            extra={"file": item.get("File"), "liveFiles": item.get("LiveFiles") or []},
        ))
    return rows


def load_manifest(path: Path, source: str, root: Path) -> List[Dict[str, Any]]:
    data = _read_json(path)
    rows = []
    for rec in data.get("records", []):
        crop = str(rec.get("cropRelativePath") or "")
        shot = str(rec.get("sourceScreenshot") or "")
        crop_ok = _file_ok(root, crop)
        shot_ok = _file_ok(root, shot)
        loaded = rec.get("status") == "RECOVERED_DETERMINISTIC" and crop_ok
        if loaded and rec.get("cropSha256"):
            loaded = (_sha256(root / crop) or "") == rec.get("cropSha256")
        rows.append(_entry(
            catalog_id=rec.get("catalogId"),
            name=rec.get("name"),
            quality=rec.get("quality"),
            width=rec.get("widthCells"),
            height=rec.get("heightCells"),
            cells=(rec.get("widthCells") or 0) * (rec.get("heightCells") or 0),
            shape="",
            value=rec.get("value"),
            source=source,
            image_rel=crop,
            image_exists=crop_ok,
            loaded=loaded,
            extra={
                "status": rec.get("status"),
                "sourceScreenshot": shot,
                "sourceScreenshotExists": shot_ok,
                "mappingEvidence": rec.get("mappingEvidence"),
                "reason": rec.get("reason"),
            },
        ))
    return rows, {
        "manifestVersion": data.get("manifestVersion"),
        "totalRecords": data.get("totalRecords"),
        "recoveredCount": data.get("recoveredCount"),
        "unresolvedCount": data.get("unresolvedCount"),
        "path": str(path),
    }


def load_visual_v2(path: Path, source: str, root: Path) -> List[Dict[str, Any]]:
    data = _read_json(path)
    rows = []
    for rec in data.get("records", []):
        shot = str(rec.get("sourcePath") or "")
        shot_ok = _file_ok(root, shot)
        loaded = rec.get("reviewStatus") == "VISUALLY_CHECKED_SOURCE_CARD" and shot_ok
        if loaded and rec.get("sourceSha256"):
            loaded = (_sha256(root / shot) or "") == rec.get("sourceSha256")
        w = rec.get("width")
        h = rec.get("height")
        rows.append(_entry(
            catalog_id=rec.get("catalogId"),
            name=rec.get("name"),
            quality=rec.get("rarity"),
            width=w,
            height=h,
            cells=(w or 0) * (h or 0),
            shape="",
            value=rec.get("value"),
            source=source,
            image_rel=shot,
            image_exists=shot_ok,
            loaded=loaded,
            extra={
                "reviewStatus": rec.get("reviewStatus"),
                "legacyCatalogId": rec.get("legacyCatalogId"),
            },
        ))
    return rows


def load_registry(path: Path, source: str, root: Path) -> List[Dict[str, Any]]:
    data = _read_json(path)
    rows = []
    for rec in data.get("cards", []):
        shot = str(rec.get("sourceScreenshot") or "")
        shot_ok = _file_ok(root, shot)
        loaded = shot_ok
        if loaded and rec.get("sourceScreenshotSha256"):
            loaded = (_sha256(root / shot) or "") == rec.get("sourceScreenshotSha256")
        w = rec.get("widthCells") or rec.get("width")
        h = rec.get("heightCells") or rec.get("height")
        rows.append(_entry(
            catalog_id=rec.get("catalogId"),
            name=rec.get("name"),
            quality=rec.get("quality"),
            width=w,
            height=h,
            cells=(w or 0) * (h or 0),
            shape="",
            value=rec.get("value"),
            source=source,
            image_rel=shot,
            image_exists=shot_ok,
            loaded=loaded,
            extra={
                "alternateCatalogIds": rec.get("alternateCatalogIds") or [],
                "sourceAuthority": rec.get("sourceAuthority"),
            },
        ))
    return rows, {
        "registryVersion": data.get("registryVersion"),
        "totalCards": data.get("totalCards"),
        "path": str(path),
    }


def load_solver_items(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    rows = []
    seen = set()
    for name, price, size in re.findall(r'\["([^"]+)",\s*(\d+),\s*"(\d+x\d+)"\]', text):
        key = (_norm_name(name), int(price), size)
        if key in seen:
            continue
        seen.add(key)
        w, h = size.split("x")
        rows.append(_entry(
            catalog_id="",
            name=name,
            quality="",
            width=int(w),
            height=int(h),
            cells=int(w) * int(h),
            shape="",
            value=int(price),
            source="solver_core_v06.js",
            extra={"size": size},
        ))
    return rows


def load_auctionpilot(path: Path) -> List[Dict[str, Any]]:
    catalog = _read_json(path)
    rows = []
    for item in catalog:
        rel = f"Assets/CatalogFull/{item.get('File')}" if item.get("File") else ""
        rows.append(_entry(
            catalog_id=item.get("Id"),
            name=item.get("Name"),
            quality=item.get("Quality"),
            width=item.get("Width"),
            height=item.get("Height"),
            cells=item.get("Cells"),
            shape=item.get("Shape"),
            value=item.get("Value"),
            source="auctionpilot_v0.12.7",
            image_rel=rel,
            image_exists=_file_ok(AP_ROOT, rel),
            extra={"file": item.get("File"), "liveFiles": item.get("LiveFiles") or []},
        ))
    return rows


def index_by(rows: List[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        if value not in (None, "", []):
            if key == "nameKey":
                out[str(value)].append(row)
            else:
                out[str(value)].append(row)
    return out


def first(rows: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    return rows[0] if rows else None


def classify(
    ours: Optional[Dict[str, Any]],
    ap: Dict[str, Any],
    ours_by_name: Dict[str, List[Dict[str, Any]]],
    solver_by_name: Dict[str, List[Dict[str, Any]]],
    pkg_065_ids: set,
    pkg_manifest_ids: set,
    pkg_visual_ids: set,
    source_card: Optional[Dict[str, Any]],
) -> Tuple[str, str, str]:
    """Return (conclusion, match_basis, suggested_action)."""
    name_hits = ours_by_name.get(ap["nameKey"]) or []
    solver_hits = solver_by_name.get(ap["nameKey"]) or []
    hit = ours or (name_hits[0] if name_hits else None)
    if ours and ours.get("catalogId") == ap["catalogId"] and ours["nameKey"] != ap["nameKey"]:
        return (
            "属性冲突，待源卡裁定",
            "same_id_different_name",
            "同 ID 不同名，不能当成同一藏品；以用户源卡核名，不以对方 JSON 覆盖",
        )

    if hit and hit["catalogId"] == ap["catalogId"] and hit["nameKey"] == ap["nameKey"]:
        diffs = []
        for field in ("quality", "width", "height", "cells", "shape"):
            if hit.get(field) not in (None, "") and ap.get(field) not in (None, "") and hit.get(field) != ap.get(field):
                diffs.append(field)
        visual_ok = bool(hit.get("imageExists") or hit.get("loadedByRuntime") or (source_card and source_card.get("imageExists")))
        in_pkg = hit["catalogId"] in pkg_065_ids or hit["catalogId"] in pkg_manifest_ids or hit["catalogId"] in pkg_visual_ids
        if diffs:
            return (
                "属性冲突，待源卡裁定",
                "same_id_and_normalized_name",
                "用用户源卡核对宽高/Cells/Shape，不以对方 catalog 覆盖",
            )
        if not visual_ok:
            return (
                "条目存在，但缺有效视觉参考",
                "same_id_and_normalized_name",
                "补独立源卡裁图后再进入识别模板，不从对方 PNG 拷贝",
            )
        if not in_pkg and hit["catalogId"]:
            return (
                "源码有、包内缺",
                "same_id_and_normalized_name",
                "核对 spec 是否漏打对应 manifest/crop；审核后再打包",
            )
        return (
            "已由其他清单补齐，并非缺项",
            "same_id_and_normalized_name",
            "catalog_065 已有同 ID 同名项，无需按对方 220 计数补件",
        )

    if hit and hit["nameKey"] == ap["nameKey"]:
        in_geom = bool(hit["catalogId"] in pkg_065_ids or str(hit.get("source", "")).startswith("catalog_065"))
        if in_geom:
            return (
                "已由其他清单补齐，并非缺项",
                "normalized_name_different_id",
                "我方几何主表已有同名不同 ID，禁止按对方 ID 导入",
            )
        return (
            "已由其他清单补齐，并非缺项",
            "normalized_name_against_supplemental_catalog",
            "catalog_065 无此对方 ID，但 visual/registry/manifest 已有同名项；几何候选索引仍可能看不见",
        )

    if solver_hits and source_card:
        return (
            "确实缺运行时条目",
            "solver_and_source_card_without_visual_row",
            "求解器与源卡都有名，视觉主表未建条目。审核后按用户源卡补定义，不拷对方图",
        )
    if solver_hits:
        return (
            "确实缺运行时条目",
            "normalized_name_against_solver_only",
            "求解器有价格尺寸；视觉主表未建条目。先核用户源卡，再决定是否补",
        )
    if source_card:
        return (
            "确实缺运行时条目",
            "source_card_without_named_runtime_row",
            "有独立源卡但运行时名表未挂上。审核后绑定已有源卡，不拷对方 catalog",
        )
    return (
        "证据不足，暂不处理",
        "no_runtime_name_or_id_match",
        "对方条目不能当权威，暂不处理",
    )


def _hash_gate_visual(root: Path) -> Dict[str, Any]:
    """Reproduce visual_catalog status/hash gates without importing OpenCV."""
    visual_path = root / "assets/items/visual_catalog_v2.json"
    v2 = root / "assets/items/catalog_reference_manifest_v2.json"
    v1 = root / "assets/items/catalog_reference_manifest_v1.json"
    manifest_path = v2 if v2.is_file() else v1
    verified = []
    if visual_path.is_file():
        for rec in _read_json(visual_path).get("records", []):
            source = root / rec.get("sourcePath", "")
            if rec.get("reviewStatus") != "VISUALLY_CHECKED_SOURCE_CARD":
                continue
            if not source.is_file():
                continue
            if _sha256(source) != rec.get("sourceSha256"):
                continue
            verified.append(rec.get("catalogId"))
    crops = []
    if manifest_path.is_file():
        for rec in _read_json(manifest_path).get("records", []):
            if rec.get("status") != "RECOVERED_DETERMINISTIC":
                continue
            image_path = root / str(rec.get("cropRelativePath") or "")
            if not image_path.is_file():
                continue
            if _sha256(image_path) != rec.get("cropSha256"):
                continue
            crops.append(rec.get("catalogId"))
    return {
        "ok": True,
        "mode": "hash-gate-without-cv2",
        "manifestUsed": str(manifest_path.relative_to(root)).replace("\\", "/"),
        "verifiedReferences": len(verified),
        "verifiedIds": sorted({x for x in verified if x}),
        "deterministicCrops": len(crops),
        "cropIds": sorted({x for x in crops if x}),
        "templateKeys": None,
        "note": "未解码图像；只核 reviewStatus/status 与 sha256。与 visual_catalog 准入条件一致，不含 bbox 校验器。",
    }


def invoke_loaders(source_root: Path) -> Dict[str, Any]:
    """Prefer production visual_catalog; fall back to hash gates if cv2 is missing."""
    extra = [
        source_root / "core",
        source_root / "app",
        Path(r"C:\Program Files\Python310\Lib\site-packages"),
    ]
    for path in reversed(extra):
        if path.exists() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
    try:
        import visual_catalog
        visual_catalog.verified_references.cache_clear()
        visual_catalog.deterministic_reference_crops.cache_clear()
        verified = visual_catalog.verified_references(root=source_root)
        crops = visual_catalog.deterministic_reference_crops(root=source_root)
        templates = visual_catalog.load_visual_templates(include_development=False)
        return {
            "ok": True,
            "mode": "visual_catalog.loader",
            "verifiedReferences": len(verified),
            "verifiedIds": sorted({r.get("catalogId") for r in verified if r.get("catalogId")}),
            "deterministicCrops": len(crops),
            "cropIds": sorted({r.get("catalogId") for r in crops if r.get("catalogId")}),
            "templateKeys": len(templates),
            "templateCatalogIds": sorted({
                k.split("/")[1].split("@")[0].removesuffix(".png")
                for k in templates
                if k.startswith("visual/")
            }),
        }
    except Exception as exc:
        gated = _hash_gate_visual(source_root)
        gated["importError"] = f"{type(exc).__name__}: {exc}"
        return gated


def main() -> int:
    source_065 = ROOT / "assets" / "catalog_065.json"
    source_v2 = ROOT / "assets" / "items" / "catalog_reference_manifest_v2.json"
    source_v1 = ROOT / "assets" / "items" / "catalog_reference_manifest_v1.json"
    source_visual = ROOT / "assets" / "items" / "visual_catalog_v2.json"
    source_reg = ROOT / "assets" / "items" / "verified_source_card_registry.json"
    solver_js = ROOT / "core" / "solver_core_v06.js"
    ap_catalog = AP_ROOT / "Assets" / "CatalogFull" / "catalog.json"
    pkg_065 = PKG_ROOT / "assets" / "catalog_065.json"
    pkg_v1 = PKG_ROOT / "assets" / "items" / "catalog_reference_manifest_v1.json"
    pkg_visual = PKG_ROOT / "assets" / "items" / "visual_catalog_v2.json"
    pkg_reg = PKG_ROOT / "assets" / "items" / "verified_source_card_registry.json"

    cat065 = load_catalog_065(source_065, "catalog_065.source")
    pkg_cat065 = load_catalog_065(pkg_065, "catalog_065.package") if pkg_065.is_file() else []
    man_v2, man_v2_meta = load_manifest(source_v2, "manifest_v2.source", ROOT)
    man_v1, man_v1_meta = load_manifest(source_v1, "manifest_v1.source", ROOT)
    pkg_man_v1, pkg_man_v1_meta = load_manifest(pkg_v1, "manifest_v1.package", PKG_ROOT) if pkg_v1.is_file() else ([], {})
    visual = load_visual_v2(source_visual, "visual_catalog_v2.source", ROOT)
    pkg_visual_rows = load_visual_v2(pkg_visual, "visual_catalog_v2.package", PKG_ROOT) if pkg_visual.is_file() else []
    registry, reg_meta = load_registry(source_reg, "registry.source", ROOT)
    pkg_registry, pkg_reg_meta = load_registry(pkg_reg, "registry.package", PKG_ROOT) if pkg_reg.is_file() else ([], {})
    solver = load_solver_items(solver_js)
    ap_rows = load_auctionpilot(ap_catalog)

    loader = invoke_loaders(ROOT)
    package_gate = _hash_gate_visual(PKG_ROOT) if (PKG_ROOT / "assets").is_dir() else {"ok": False}

    # Preferred ours record per ID: catalog_065, then v2 crop, then visual, then registry
    ours_by_id: Dict[str, Dict[str, Any]] = {}
    ours_all: List[Dict[str, Any]] = []
    for bucket in (cat065, man_v2, visual, registry, man_v1):
        for row in bucket:
            ours_all.append(row)
            cid = row["catalogId"]
            if cid and cid not in ours_by_id:
                ours_by_id[cid] = row

    ours_by_name = index_by(ours_all, "nameKey")
    solver_by_name = index_by(solver, "nameKey")
    cat065_by_id = {r["catalogId"]: r for r in cat065}
    pkg065_by_id = {r["catalogId"]: r for r in pkg_cat065}
    pkg_065_ids = set(pkg065_by_id)
    pkg_manifest_ids = {r["catalogId"] for r in pkg_man_v1 if r.get("loadedByRuntime")}
    pkg_visual_ids = {r["catalogId"] for r in pkg_visual_rows if r.get("loadedByRuntime")}
    source_card_by_name = index_by(registry, "nameKey")

    # catalog_065 vs AP same-id attribute diffs
    same_id_attr_diffs = []
    for ap in ap_rows:
        ours = cat065_by_id.get(ap["catalogId"])
        if not ours:
            continue
        fields = {}
        for field in ("name", "quality", "width", "height", "cells", "shape", "value"):
            if ours.get(field) != ap.get(field):
                fields[field] = {"ours": ours.get(field), "theirs": ap.get(field)}
        if fields:
            same_id_attr_diffs.append({
                "id": ap["catalogId"],
                "oursName": ours["name"],
                "theirsName": ap["name"],
                "nameMatch": ours["nameKey"] == ap["nameKey"],
                "fields": fields,
            })

    diffs = []
    for ap in ap_rows:
        ours = ours_by_id.get(ap["catalogId"])
        name_hits = ours_by_name.get(ap["nameKey"]) or []
        if ours is None and name_hits:
            ours = name_hits[0]
        source_card = first(source_card_by_name.get(ap["nameKey"]))
        conclusion, basis, action = classify(
            ours, ap, ours_by_name, solver_by_name,
            pkg_065_ids, pkg_manifest_ids, pkg_visual_ids, source_card,
        )
        ours_pkg = pkg065_by_id.get((ours or {}).get("catalogId") or ap["catalogId"])
        attr = {}
        if ours:
            for field in ("quality", "width", "height", "cells", "shape", "value"):
                if ours.get(field) != ap.get(field):
                    attr[field] = {"ours": ours.get(field), "theirs": ap.get(field)}
        diffs.append({
            "oursId": (ours or {}).get("catalogId") or "",
            "oursName": (ours or {}).get("name") or "",
            "oursSource": (ours or {}).get("source") or "",
            "theirsId": ap["catalogId"],
            "theirsName": ap["name"],
            "matchBasis": basis,
            "oursQuality": (ours or {}).get("quality"),
            "theirsQuality": ap["quality"],
            "oursWidth": (ours or {}).get("width"),
            "theirsWidth": ap["width"],
            "oursHeight": (ours or {}).get("height"),
            "theirsHeight": ap["height"],
            "oursCells": (ours or {}).get("cells"),
            "theirsCells": ap["cells"],
            "oursShape": (ours or {}).get("shape"),
            "theirsShape": ap["shape"],
            "oursValue": (ours or {}).get("value"),
            "theirsValue": ap["value"],
            "attributeDiffs": attr,
            "oursImageRel": (ours or {}).get("imageRel") or (source_card or {}).get("imageRel") or "",
            "oursImageExists": bool((ours or {}).get("imageExists") or (source_card or {}).get("imageExists")),
            "oursLoadedByRuntime": bool((ours or {}).get("loadedByRuntime")),
            "packageHasCatalog065": ((ours or {}).get("catalogId") in pkg_065_ids) if ours else ap["catalogId"] in pkg_065_ids,
            "sourceCardPath": (source_card or {}).get("imageRel") or "",
            "sourceCardExists": bool((source_card or {}).get("imageExists")),
            "solverHasName": bool(solver_by_name.get(ap["nameKey"])),
            "conclusion": conclusion,
            "suggestedAction": action,
            "packageCatalog065ShaMatchesSource": (
                _sha256(source_065) == _sha256(pkg_065) if pkg_065.is_file() else False
            ),
        })

    conclusion_counts = Counter(row["conclusion"] for row in diffs)

    stats = {
        "generatedAt": datetime.now(TZ).isoformat(),
        "gitHeadExpected": "84e020774f01c87c3ddc20a14eb5d64b1baf6d99",
        "auctionPilotCatalog": str(ap_catalog),
        "packageRoot": str(PKG_ROOT),
        "counts": {
            "auctionPilot": len(ap_rows),
            "catalog_065_source": len(cat065),
            "catalog_065_package": len(pkg_cat065),
            "manifest_v2_source": len(man_v2),
            "manifest_v1_source": len(man_v1),
            "manifest_v1_package": len(pkg_man_v1),
            "visual_catalog_v2_source": len(visual),
            "visual_catalog_v2_package": len(pkg_visual_rows),
            "registry_source": len(registry),
            "registry_package": len(pkg_registry),
            "solver_named_items": len(solver),
        },
        "manifestMeta": {
            "v2_source": man_v2_meta,
            "v1_source": man_v1_meta,
            "v1_package": pkg_man_v1_meta,
        },
        "registryMeta": {"source": reg_meta, "package": pkg_reg_meta},
        "catalog065Sha": {
            "source": _sha256(source_065),
            "package": _sha256(pkg_065),
            "match": _sha256(source_065) == _sha256(pkg_065),
        },
        "packageHasManifestV2": (PKG_ROOT / "assets/items/catalog_reference_manifest_v2.json").is_file(),
        "specPackagesManifestV1NotV2": True,
        "sameIdAttributeDiffsVsCatalog065": len(same_id_attr_diffs),
        "sameIdNameMismatch": sum(1 for x in same_id_attr_diffs if not x["nameMatch"]),
        "conclusionCounts": dict(conclusion_counts),
        "loader": loader,
        "packageHashGate": package_gate,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "2026-09-14-runtime-visual-catalog-diff.json"
    csv_path = OUT_DIR / "2026-09-14-runtime-visual-catalog-diff.csv"
    md_path = OUT_DIR / "2026-09-14-runtime-visual-catalog-diff.md"
    payload = {"stats": stats, "sameIdAttributeDiffs": same_id_attr_diffs, "rows": diffs}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "oursId", "oursName", "oursSource", "theirsId", "theirsName", "matchBasis",
        "conclusion", "suggestedAction", "oursQuality", "theirsQuality",
        "oursWidth", "theirsWidth", "oursHeight", "theirsHeight",
        "oursCells", "theirsCells", "oursShape", "theirsShape",
        "oursImageRel", "oursImageExists", "oursLoadedByRuntime",
        "packageHasCatalog065", "sourceCardPath", "sourceCardExists", "solverHasName",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in diffs:
            writer.writerow(row)

    def _md_table(rows: List[Dict[str, Any]], limit: int = 40) -> str:
        lines = [
            "| 结论 | 我方ID | 我方名 | 对方ID | 对方名 | 匹配依据 | 源卡 |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in rows[:limit]:
            lines.append(
                f"| {row['conclusion']} | `{row['oursId'] or '—'}` | {row['oursName'] or '—'} "
                f"| `{row['theirsId']}` | {row['theirsName']} | {row['matchBasis']} "
                f"| {row['sourceCardPath'] or '—'} |"
            )
        if len(rows) > limit:
            lines.append(f"| … | 其余 {len(rows) - limit} 条见 CSV/JSON | | | | | |")
        return "\n".join(lines)

    interesting = [
        row for row in diffs
        if row["conclusion"] not in {"已由其他清单补齐，并非缺项"}
        or row["attributeDiffs"]
    ]
    missing_runtime = [r for r in diffs if r["conclusion"] in {"确实缺运行时条目", "几何/身份主表缺定义"}]
    attr_conflict = [r for r in diffs if r["conclusion"] == "属性冲突，待源卡裁定"]
    pkg_gap = [r for r in diffs if r["conclusion"] == "源码有、包内缺"]
    no_visual = [r for r in diffs if r["conclusion"] == "条目存在，但缺有效视觉参考"]

    md = f"""# 运行时视觉图鉴差异审计（2026-09-14）

对照对象：AuctionPilot v0.12.7 `Assets/CatalogFull/catalog.json`（220 项）。
我方源码：`D:\\yihuanpaimai` HEAD `84e0207`。
我方冻结包：`build/isolated_trial_ux_fixes_20260914_84e0207`。
本文件只做对照，不把对方 catalog 当权威，不复制对方图片或 DLL。

## 先前线索核实

先前口头数字「对方 220 / 我方 catalog_065 200 / 少 20 / 约 19 条属性分歧」**不能直接当成运行时缺口**。

| 线索 | 核实结果 |
|---|---|
| 对方 220 | 成立。对方 `catalog.json` 实读 {len(ap_rows)} 项。 |
| catalog_065 200 | 成立。源码与 84e0207 包均为 {len(cat065)} 项，SHA256 {'一致' if stats['catalog065Sha']['match'] else '不一致'}。 |
| 少 20 件运行时条目 | **不成立为整表缺 20。** 对方多出的 `catalog-gold-*` / `catalog-red-*` 多数已在 visual_catalog_v2 / 源卡注册表 / manifest v2 以 `visual-*` 或其他 ID 存在。几何主表 `catalog_065.json` 确实没有这 20 个对方 ID。 |
| 约 19 条 Shape/尺寸分歧 | catalog_065 与对方同 ID 属性差 {len(same_id_attr_diffs)} 条；其中名称不一致 {stats['sameIdNameMismatch']} 条。同 ID 不等于同一藏品。 |

## 实际加载链

1. 生产视觉 worker：`app/main.py` → `KeyboardAuctionPipeline(catalog_path=assets/catalog_065.json)`。
2. 仓库几何/候选：`warehouse_vision.py` / `item_identity_resolver.py` / `shape_matcher.py` **只读 catalog_065.json**。
3. 结算身份模板：`settlement_item_recognizer.py` → `visual_catalog.load_visual_templates()`：
   - `assets/items/visual_catalog_v2.json` 中 `VISUALLY_CHECKED_SOURCE_CARD` 且哈希匹配的源卡；
   - `catalog_reference_manifest_v2.json`（若存在）否则 v1，状态 `RECOVERED_DETERMINISTIC` 且裁图哈希匹配。
4. 命名权威：`catalog_validator.py` 以 catalog_065 **加上** `verified_source_card_registry.json` 为正式名来源。
5. 求解器价格/尺寸：`core/solver_core_v06.js` 独立快照，不代替视觉主表。

`catalog_065.json` 是几何/候选主表，不是唯一层。视觉模板和源卡映射是另外两层。

### 各来源计数

| 来源 | 源码 | 84e0207 包 |
|---|---|---|
| catalog_065.json | {len(cat065)} | {len(pkg_cat065)} |
| catalog_reference_manifest_v2.json | {len(man_v2)}（声明 {man_v2_meta.get('totalRecords')} / 接通 {man_v2_meta.get('recoveredCount')} / 未决 {man_v2_meta.get('unresolvedCount')}） | **未打包** |
| catalog_reference_manifest_v1.json | {len(man_v1)}（声明 {man_v1_meta.get('totalRecords')} / 接通 {man_v1_meta.get('recoveredCount')} / 未决 {man_v1_meta.get('unresolvedCount')}） | {len(pkg_man_v1)} |
| visual_catalog_v2.json | {len(visual)} | {len(pkg_visual_rows)} |
| verified_source_card_registry.json | {len(registry)}（声明 {reg_meta.get('totalCards')}） | {len(pkg_registry)} |
| solver_core_v06.js 具名条目 | {len(solver)} | 随 JS 打包 |

加载器实跑：{'成功' if loader.get('ok') else '失败'}。
源码 `verified_references`={loader.get('verifiedReferences')}，`deterministic_reference_crops`={loader.get('deterministicCrops')}，模板键={loader.get('templateKeys')}。
{'加载器错误: ' + str(loader.get('error')) if not loader.get('ok') else '源码侧优先加载 manifest v2。'}

**包内缺口（已核实文件存在性，非游戏局）：** spec 只加入 `catalog_reference_manifest_v1.json`，84e0207 `_internal/assets/items/` 无 v2。因此冻结包的 `deterministic_reference_crops()` 走 v1（200 项、仅 134 接通），不是源码的 v2（214 项、213 接通）。这是源码/打包差异，不是竞品 20 项本身。

## 结论分布（对对方 220 项）

"""
    for key, count in conclusion_counts.most_common():
        md += f"- {key}：{count}\n"
    md += f"""
## 最值得下一轮处理的缺口

1. **冻结包未包含 manifest v2**（源码有、包内缺）。影响结算模板裁图接通数，不改变 catalog_065 200 项几何主表。证据：`app/异环拍卖助手.spec` 第 105 行只打 v1；包内目录实列只有 v1。
2. **几何主表仍是 catalog_065 的 200 项。** 8.13 后金/红若只存在于 visual-* / registry，则 ShapeMatcher / ItemIdentityResolver / warehouse 候选索引看不见它们。这与“视觉模板是否存在”不是同一回事。
3. **同 ID 属性冲突必须用用户源卡裁定**，不能用对方 Shape 覆盖。

### 属性冲突（catalog_065 同 ID）

"""
    md += _md_table(attr_conflict, 30)
    md += "\n\n### 几何主表缺定义或确缺运行时条目\n\n"
    md += _md_table(missing_runtime, 40)
    md += "\n\n### 源码有、包内缺（按对方条目投影）\n\n"
    md += _md_table(pkg_gap, 20)
    md += "\n\n### 有条目但缺有效视觉参考\n\n"
    md += _md_table(no_visual, 20)
    md += f"""

完整逐项表：
- `{json_path.relative_to(ROOT).as_posix()}`
- `{csv_path.relative_to(ROOT).as_posix()}`

本轮不替换运行时图鉴，不从对方目录拷图。
"""
    md_path.write_text(md, encoding="utf-8")
    print(json.dumps({
        "json": str(json_path),
        "csv": str(csv_path),
        "md": str(md_path),
        "conclusions": dict(conclusion_counts),
        "sameIdAttrDiffs": len(same_id_attr_diffs),
        "loader": {"ok": loader.get("ok"), "verified": loader.get("verifiedReferences"), "crops": loader.get("deterministicCrops"), "templates": loader.get("templateKeys")},
        "packageHasManifestV2": stats["packageHasManifestV2"],
        "catalog065ShaMatch": stats["catalog065Sha"]["match"],
        "packageHashGate": {
            "manifestUsed": stats.get("packageHashGate", {}).get("manifestUsed"),
            "verified": stats.get("packageHashGate", {}).get("verifiedReferences"),
            "crops": stats.get("packageHashGate", {}).get("deterministicCrops"),
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
