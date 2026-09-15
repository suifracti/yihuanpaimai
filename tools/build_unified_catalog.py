"""Build unified, verified catalog manifest and reference crops from user-organized screenshots.

Provenance:
- Sources: 48 screenshots in assets/items/catalog_screenshots/<shape>/
- Metadata: assets/catalog_065.json (200 records), assets/items/visual_catalog_v2.json (107 records)
- Destination: assets/items/catalog_reference_manifest_v2.json, assets/items/reference_crops_v1/
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS_DIR = PROJECT_ROOT / "assets" / "items" / "catalog_screenshots"
CATALOG_065_PATH = PROJECT_ROOT / "assets" / "catalog_065.json"
MANIFEST_V1_PATH = PROJECT_ROOT / "assets" / "items" / "catalog_reference_manifest_v1.json"
VISUAL_V2_PATH = PROJECT_ROOT / "assets" / "items" / "visual_catalog_v2.json"
CROPS_DIR = PROJECT_ROOT / "assets" / "items" / "reference_crops_v1"
DRAFT_PATH = PROJECT_ROOT / "build" / "takeover_20260905" / "visual-catalog-draft.json"
REGISTRY_PATH = PROJECT_ROOT / "assets" / "items" / "verified_source_card_registry.json"
HISTORICAL_BASELINE_PATH = PROJECT_ROOT / "assets" / "items" / "catalog_unresolved_47_audit.json"
OUTPUT_MANIFEST = PROJECT_ROOT / "assets" / "items" / "catalog_reference_manifest_v2.json"

CROPS_DIR.mkdir(parents=True, exist_ok=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_text(text: str) -> str:
    if not text:
        return ""
    # Punctuation normalization
    s = text.replace("『", "「").replace("』", "」").replace("【", "「").replace("】", "」")
    s = s.replace("（", "(").replace("）", ")").replace("!", "！")
    s = re.sub(r"\s+", "", s)
    return s


def load_inputs():
    cat065 = json.loads(CATALOG_065_PATH.read_text(encoding="utf-8"))
    manifest_v1 = json.loads(MANIFEST_V1_PATH.read_text(encoding="utf-8"))
    vcat2 = json.loads(VISUAL_V2_PATH.read_text(encoding="utf-8"))
    draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8")) if DRAFT_PATH.is_file() else []
    return cat065, manifest_v1, vcat2, draft


def build_unified_manifest():
    cat065, manifest_v1, vcat2, draft = load_inputs()
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8")) if REGISTRY_PATH.is_file() else {"cards": []}
    baseline_data = json.loads(HISTORICAL_BASELINE_PATH.read_text(encoding="utf-8")) if HISTORICAL_BASELINE_PATH.is_file() else {"unresolvedCatalogItems": []}
    baseline_47_ids = {it["catalogId"] for it in baseline_data.get("unresolvedCatalogItems", [])}

    reg_by_id = {}
    for c in registry.get("cards", []):
        cid = c.get("catalogId")
        if cid in baseline_47_ids or cid == "image12-1-0":
            reg_by_id[cid] = c

    cat065_by_id = {c["Id"]: c for c in cat065}
    cat065_by_norm_name: Dict[str, List[Dict[str, Any]]] = {}
    for c in cat065:
        nn = normalize_text(c["Name"])
        cat065_by_norm_name.setdefault(nn, []).append(c)

    manifest_v1_by_id = {r["catalogId"]: r for r in manifest_v1.get("records", [])}
    vcat2_by_id = {r["catalogId"]: r for r in vcat2.get("records", [])}

    records: List[Dict[str, Any]] = []
    seen_ids = set()

    # 1. First, preserve and update all records from manifest_v1
    for r in manifest_v1.get("records", []):
        cid = r["catalogId"]
        entry = dict(r)
        cat_info = cat065_by_id.get(cid)
        if cat_info:
            entry["name"] = cat_info["Name"]
            entry["quality"] = cat_info.get("Quality")
            entry["widthCells"] = int(cat_info.get("Width") or entry.get("widthCells") or 1)
            entry["heightCells"] = int(cat_info.get("Height") or entry.get("heightCells") or 1)
            entry["value"] = cat_info.get("Value")

        # Check sourceScreenshot parent folder for authoritative shape
        src_shot = entry.get("sourceScreenshot") or ""
        folder_match = re.search(r"catalog_screenshots/([0-9]+)[xX]([0-9]+)/", src_shot)
        if folder_match:
            folder_w = int(folder_match.group(1))
            folder_h = int(folder_match.group(2))
            entry["widthCells"] = folder_w
            entry["heightCells"] = folder_h

        # 1X5 recovery from user screenshot
        if cid == "image27-1-2":
            qiangshen_shot = "assets/items/catalog_screenshots/1X5/{DE334641-DA72-4330-9D2A-0D11AE3A8AB4}.png"
            qiangshen_full = PROJECT_ROOT / qiangshen_shot
            if qiangshen_full.is_file():
                src_bytes = qiangshen_full.read_bytes()
                src_img = cv2.imdecode(np.frombuffer(src_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                cbox = [0, 0, 409, 309]
                crop_rel = "assets/items/reference_crops_v1/image27-1-2.png"
                crop_full = PROJECT_ROOT / crop_rel
                if src_img is not None:
                    bx, by, bw, bh = cbox
                    cv2.imencode(".png", src_img[by : by + bh, bx : bx + bw])[1].tofile(str(crop_full))
                crop_sha = sha256_bytes(crop_full.read_bytes()) if crop_full.is_file() else None
                entry["sourceScreenshot"] = qiangshen_shot
                entry["sourceScreenshotSha256"] = sha256_bytes(src_bytes)
                entry["slotRow"] = 0
                entry["slotCol"] = 0
                entry["bbox"] = cbox
                entry["cropRelativePath"] = crop_rel if crop_full.is_file() else None
                entry["cropSha256"] = crop_sha
                entry["mappingEvidence"] = "USER_SCREENSHOT_VERIFIED:'「强身好伙伴！」'"
                entry["status"] = "RECOVERED_DETERMINISTIC" if crop_full.is_file() else "MISSING_UNRESOLVED"
                entry["widthCells"] = 1
                entry["heightCells"] = 5
        elif cid == "image29-0-2":
            jieyun_shot = "assets/items/catalog_screenshots/1X5/{DE334641-DA72-4330-9D2A-0D11AE3A8AB4}.png"
            jieyun_full = PROJECT_ROOT / jieyun_shot
            if jieyun_full.is_file():
                src_bytes = jieyun_full.read_bytes()
                src_img = cv2.imdecode(np.frombuffer(src_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                cbox = [409, 0, 409, 309]
                crop_rel = "assets/items/reference_crops_v1/image29-0-2.png"
                crop_full = PROJECT_ROOT / crop_rel
                if src_img is not None:
                    bx, by, bw, bh = cbox
                    cv2.imencode(".png", src_img[by : by + bh, bx : bx + bw])[1].tofile(str(crop_full))
                crop_sha = sha256_bytes(crop_full.read_bytes()) if crop_full.is_file() else None
                entry["sourceScreenshot"] = jieyun_shot
                entry["sourceScreenshotSha256"] = sha256_bytes(src_bytes)
                entry["slotRow"] = 0
                entry["slotCol"] = 1
                entry["bbox"] = cbox
                entry["cropRelativePath"] = crop_rel if crop_full.is_file() else None
                entry["cropSha256"] = crop_sha
                entry["mappingEvidence"] = "USER_SCREENSHOT_VERIFIED:'「截云」'"
                entry["status"] = "RECOVERED_DETERMINISTIC" if crop_full.is_file() else "MISSING_UNRESOLVED"
                entry["widthCells"] = 1
                entry["heightCells"] = 5
        elif (cid in baseline_47_ids or cid == "image12-1-0") and cid in reg_by_id:
            # 47 missing items connection from verified source cards
            card = reg_by_id[cid]
            src_rel = card["sourceScreenshot"]
            src_full = PROJECT_ROOT / src_rel
            cbox = card["bbox"]
            crop_rel = f"assets/items/reference_crops_v1/{cid}.png"
            crop_full = PROJECT_ROOT / crop_rel

            if src_full.is_file():
                src_bytes = src_full.read_bytes()
                src_img = cv2.imdecode(np.frombuffer(src_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                if src_img is not None:
                    bx, by, bw, bh = cbox
                    crop_patch = src_img[by : by + bh, bx : bx + bw]
                    if crop_patch.size > 0:
                        cv2.imencode(".png", crop_patch)[1].tofile(str(crop_full))

            entry["sourceScreenshot"] = src_rel
            entry["sourceScreenshotSha256"] = card["sourceScreenshotSha256"]
            entry["bbox"] = cbox
            entry["cropRelativePath"] = crop_rel if crop_full.is_file() else None
            entry["cropSha256"] = sha256_bytes(crop_full.read_bytes()) if crop_full.is_file() else None
            entry["mappingEvidence"] = f"USER_SCREENSHOT_VERIFIED:'{entry.get('name')}'"
            entry["status"] = "RECOVERED_DETERMINISTIC" if crop_full.is_file() else "MISSING_UNRESOLVED"
        elif cid == "image2-1-1":
            crop_file = CROPS_DIR / f"{cid}.png"
            if crop_file.is_file():
                crop_file.unlink()
            entry["sourceScreenshot"] = None
            entry["sourceScreenshotSha256"] = None
            entry["bbox"] = None
            entry["cropRelativePath"] = None
            entry["cropSha256"] = None
            entry["status"] = "MISSING_UNRESOLVED"
            entry["reason"] = (
                "EMPTY_SLOT_TITLE_MISMATCH: Screenshot 2X1/{48710325-8642-4753-AAFD-302E079D2B93}.png "
                "contains card '锻刀石' (visual-65250f2f6c5a, value 167) in middle slot; candidate slot "
                "[781, 285, 366, 236] is empty. No genuine '磨刀石' card exists in screenshots."
            )

        # Check if crop exists in reference_crops_v1
        crop_file = CROPS_DIR / f"{cid}.png"
        if crop_file.is_file():
            crop_bytes = crop_file.read_bytes()
            entry["cropRelativePath"] = f"assets/items/reference_crops_v1/{cid}.png"
            entry["cropSha256"] = sha256_bytes(crop_bytes)
            entry["status"] = "RECOVERED_DETERMINISTIC"

        records.append(entry)
        seen_ids.add(cid)

    # 2. Add visual- catalog entries from visual_catalog_v2
    for r in vcat2.get("records", []):
        cid = r["catalogId"]
        if cid in seen_ids:
            continue
        src_rel = r.get("sourcePath")
        if not src_rel:
            continue
        src_full = PROJECT_ROOT / src_rel
        if not src_full.is_file():
            continue

        src_bytes = src_full.read_bytes()
        src_sha = sha256_bytes(src_bytes)
        cbox = r.get("cardBbox") or [0, 0, 100, 100]

        # Extract crop if not exists
        crop_rel = f"assets/items/reference_crops_v1/{cid}.png"
        crop_full = PROJECT_ROOT / crop_rel
        if not crop_full.is_file():
            src_img = cv2.imdecode(np.frombuffer(src_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            if src_img is not None:
                bx, by, bw, bh = cbox
                crop_patch = src_img[by : by + bh, bx : bx + bw]
                if crop_patch.size > 0:
                    cv2.imencode(".png", crop_patch)[1].tofile(str(crop_full))

        crop_sha = sha256_bytes(crop_full.read_bytes()) if crop_full.is_file() else None

        entry = {
            "catalogId": cid,
            "name": r.get("name"),
            "quality": r.get("rarity"),
            "widthCells": int(r.get("width") or 1),
            "heightCells": int(r.get("height") or 1),
            "sourceScreenshot": src_rel,
            "sourceScreenshotSha256": src_sha,
            "slotRow": None,
            "slotCol": None,
            "bbox": cbox,
            "cropRelativePath": crop_rel if crop_full.is_file() else None,
            "cropSha256": crop_sha,
            "mappingEvidence": f"VISUAL_CATALOG_V2_CHECKED:'{r.get('name')}'",
            "status": "RECOVERED_DETERMINISTIC" if crop_full.is_file() else "MISSING_UNRESOLVED",
            "value": r.get("value"),
        }
        records.append(entry)
        seen_ids.add(cid)

    # 3. Add any additional verified items discovered from the 5 screenshots
    # 酷辣辣辣条 (1x2, red)
    latiao_shot = "assets/items/catalog_screenshots/1X2/{343D8F72-4689-4286-AFFD-80CEC2496DC7}.png"
    latiao_full = PROJECT_ROOT / latiao_shot
    if latiao_full.is_file() and "visual-latiao-1x2" not in seen_ids:
        src_bytes = latiao_full.read_bytes()
        src_img = cv2.imdecode(np.frombuffer(src_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        cbox = [0, 0, 383, 278]
        crop_rel = "assets/items/reference_crops_v1/visual-latiao-1x2.png"
        crop_full = PROJECT_ROOT / crop_rel
        if not crop_full.is_file() and src_img is not None:
            bx, by, bw, bh = cbox
            cv2.imencode(".png", src_img[by : by + bh, bx : bx + bw])[1].tofile(str(crop_full))
        crop_sha = sha256_bytes(crop_full.read_bytes()) if crop_full.is_file() else None
        records.append({
            "catalogId": "visual-latiao-1x2",
            "name": "酷辣辣辣条",
            "quality": "红",
            "widthCells": 1,
            "heightCells": 2,
            "sourceScreenshot": latiao_shot,
            "sourceScreenshotSha256": sha256_bytes(src_bytes),
            "slotRow": 0,
            "slotCol": 0,
            "bbox": cbox,
            "cropRelativePath": crop_rel if crop_full.is_file() else None,
            "cropSha256": crop_sha,
            "mappingEvidence": "USER_SCREENSHOT_VERIFIED:'酷辣辣辣条'",
            "status": "RECOVERED_DETERMINISTIC" if crop_full.is_file() else "MISSING_UNRESOLVED",
            "value": 280000,
        })
        seen_ids.add("visual-latiao-1x2")

    # 储钱小哼 (5x5, red)
    xiaoheng_shot = "assets/items/catalog_screenshots/5X5/{5325ABB2-6E85-4169-9C65-98431204CBEE}.png"
    xiaoheng_full = PROJECT_ROOT / xiaoheng_shot
    if xiaoheng_full.is_file() and "visual-xiaoheng-5x5" not in seen_ids:
        src_bytes = xiaoheng_full.read_bytes()
        src_img = cv2.imdecode(np.frombuffer(src_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        cbox = [385, 0, 384, 272]
        crop_rel = "assets/items/reference_crops_v1/visual-xiaoheng-5x5.png"
        crop_full = PROJECT_ROOT / crop_rel
        if not crop_full.is_file() and src_img is not None:
            bx, by, bw, bh = cbox
            cv2.imencode(".png", src_img[by : by + bh, bx : bx + bw])[1].tofile(str(crop_full))
        crop_sha = sha256_bytes(crop_full.read_bytes()) if crop_full.is_file() else None
        records.append({
            "catalogId": "visual-xiaoheng-5x5",
            "name": "储钱小哼",
            "quality": "红",
            "widthCells": 5,
            "heightCells": 5,
            "sourceScreenshot": xiaoheng_shot,
            "sourceScreenshotSha256": sha256_bytes(src_bytes),
            "slotRow": 0,
            "slotCol": 1,
            "bbox": cbox,
            "cropRelativePath": crop_rel if crop_full.is_file() else None,
            "cropSha256": crop_sha,
            "mappingEvidence": "USER_SCREENSHOT_VERIFIED:'储钱小哼'",
            "status": "RECOVERED_DETERMINISTIC" if crop_full.is_file() else "MISSING_UNRESOLVED",
            "value": 500001,
        })
        seen_ids.add("visual-xiaoheng-5x5")


    # 琉璃尾 (4x1, gold)
    liuliwei_shot = "assets/items/catalog_screenshots/4X1/{7DB91AEB-261E-41F0-831D-424EEDA94025}.png"
    liuliwei_full = PROJECT_ROOT / liuliwei_shot
    if liuliwei_full.is_file() and "visual-liuliwei-4x1" not in seen_ids:
        src_bytes = liuliwei_full.read_bytes()
        src_img = cv2.imdecode(np.frombuffer(src_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        cbox = [404, 36, 366, 236]
        crop_rel = "assets/items/reference_crops_v1/visual-liuliwei-4x1.png"
        crop_full = PROJECT_ROOT / crop_rel
        if not crop_full.is_file() and src_img is not None:
            bx, by, bw, bh = cbox
            cv2.imencode(".png", src_img[by : by + bh, bx : bx + bw])[1].tofile(str(crop_full))
        crop_sha = sha256_bytes(crop_full.read_bytes()) if crop_full.is_file() else None
        records.append({
            "catalogId": "visual-liuliwei-4x1",
            "name": "琉璃尾",
            "quality": "gold",
            "widthCells": 4,
            "heightCells": 1,
            "sourceScreenshot": liuliwei_shot,
            "sourceScreenshotSha256": sha256_bytes(src_bytes),
            "slotRow": 0,
            "slotCol": 1,
            "bbox": cbox,
            "cropRelativePath": crop_rel if crop_full.is_file() else None,
            "cropSha256": crop_sha,
            "mappingEvidence": "USER_SCREENSHOT_VERIFIED:'琉璃尾'",
            "status": "RECOVERED_DETERMINISTIC" if crop_full.is_file() else "MISSING_UNRESOLVED",
            "value": 101403,
        })
        seen_ids.add("visual-liuliwei-4x1")


    # Sort records stably
    records.sort(key=lambda r: str(r.get("catalogId")))

    rec_count = sum(1 for r in records if r.get("status") == "RECOVERED_DETERMINISTIC")
    unres_count = len(records) - rec_count

    # Validate all records strictly before saving
    sys.path.insert(0, str(PROJECT_ROOT / "core"))
    from catalog_validator import validate_catalog_record
    for r in records:
        validate_catalog_record(r)

    manifest_v2 = {
        "manifestVersion": "catalog-reference-manifest.v2",
        "totalRecords": len(records),
        "recoveredCount": rec_count,
        "unresolvedCount": unres_count,
        "records": records,
    }

    OUTPUT_MANIFEST.write_text(json.dumps(manifest_v2, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Unified manifest v2 validated and saved to {OUTPUT_MANIFEST}")
    print(f"Total records: {len(records)}, Recovered: {rec_count}, Unresolved: {unres_count}")


if __name__ == "__main__":
    build_unified_manifest()
