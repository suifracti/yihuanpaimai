"""Source-backed visual references, separate from historical solver snapshots."""
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import math
import sys

import cv2
import numpy as np


def asset_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


@lru_cache(maxsize=1)
def verified_references(root=None):
    base_root = Path(root) if root else asset_root()
    path = base_root / "assets/items/visual_catalog_v2.json"
    if not path.is_file():
        return []
    records = json.loads(path.read_text(encoding="utf-8"))["records"]
    valid = []
    from catalog_validator import validate_catalog_record
    for record in records:
        source = base_root / record["sourcePath"]
        if (record.get("reviewStatus") != "VISUALLY_CHECKED_SOURCE_CARD"
                or not source.is_file()
                or hashlib.sha256(source.read_bytes()).hexdigest() != record["sourceSha256"]):
            continue
        validate_catalog_record(record, root=base_root)
        valid.append(record)
    return valid


@lru_cache(maxsize=1)
def development_references():
    """Load explicitly marked reveal-frame references, separate from catalog cards."""
    path = asset_root() / "assets/items/video_development_references_v1.json"
    if not path.is_file():
        return []
    try:
        records = json.loads(path.read_text(encoding="utf-8"))["records"]
    except (OSError, KeyError, TypeError, ValueError):
        return []
    valid = []
    for record in records:
        if record.get("sampleClass") != "development-reference":
            continue
        image_path = asset_root() / record.get("imagePath", "")
        if not image_path.is_file():
            continue
        if hashlib.sha256(image_path.read_bytes()).hexdigest() != record.get("imageSha256"):
            continue
        valid.append(record)
    return valid


@lru_cache(maxsize=4)
def deterministic_reference_crops(manifest_path=None, root=None):
    """Load source-backed catalog crops with manifest/hash provenance.

    These are formal catalog references recovered from the checked source
    screenshots, not video acceptance samples.  Unresolved manifest entries
    remain absent and therefore cannot influence identity matching.
    """
    base_root = Path(root) if root else asset_root()
    if manifest_path is None:
        path_v2 = base_root / "assets/items/catalog_reference_manifest_v2.json"
        path = path_v2 if path_v2.is_file() else (base_root / "assets/items/catalog_reference_manifest_v1.json")
    else:
        path = Path(manifest_path)
    if not path.is_file():
        return []
    records = json.loads(path.read_text(encoding="utf-8")).get("records", [])
    valid = []
    from catalog_validator import validate_catalog_record
    for record in records:
        if record.get("status") != "RECOVERED_DETERMINISTIC":
            continue
        validate_catalog_record(record, root=base_root)
        image_path = base_root / str(record.get("cropRelativePath") or "")
        if not image_path.is_file():
            continue
        if hashlib.sha256(image_path.read_bytes()).hexdigest() != record.get("cropSha256"):
            continue
        valid.append(record)
    try:
        label = "v2" if path.name.endswith("v2.json") else "v1"
        print(
            f"[WORKER:VISION] catalog_reference_manifest selected={label} path={path} recovered={len(valid)}",
            flush=True,
        )
    except Exception:
        pass
    return valid


def catalog_reference_for_template(template_reference):
    marker = "@catalog-reference-crop.png"
    value = str(template_reference or "")
    prefix = "visual/"
    if not value.startswith(prefix) or not value.endswith(marker):
        return None
    catalog_id = value[len(prefix):-len(marker)]
    return next((record for record in deterministic_reference_crops()
                 if record.get("catalogId") == catalog_id), None)


def _catalog_reference_body(image):
    """Keep the object region while excluding catalog title/price chrome."""
    h, w = image.shape[:2]
    body = image[round(h * .18):round(h * .76),
                 round(w * .20):round(w * .80)]
    return body if body.size else image


def load_visual_templates(include_development=False):
    templates = {}
    for record in verified_references():
        image = cv2.imdecode(np.fromfile(asset_root() / record["sourcePath"], np.uint8), 1)
        x, y, w, h = record["cardBbox"]
        # Exclude the title, price ribbon, favourite icon and footprint diagram.
        body = image[y + round(h * .23):y + round(h * .74),
                     x + round(w * .20):x + round(w * .80)]
        if body.size:
            templates[f"visual/{record['catalogId']}.png"] = body
        # Some taller icons reach above the standard body crop. Keep a second
        # view of the SAME source card so truncation does not erase their tips.
        expanded = image[y + round(h * .18):y + round(h * .76),
                         x + round(w * .20):x + round(w * .80)]
        if expanded.size:
            templates[f"visual/{record['catalogId']}@expanded.png"] = expanded
    for record in deterministic_reference_crops():
        image_path = asset_root() / record["cropRelativePath"]
        image = cv2.imdecode(np.fromfile(str(image_path), np.uint8), 1)
        if image is None or not image.size:
            continue
        body = _catalog_reference_body(image)
        if body.size:
            templates[f"visual/{record['catalogId']}@catalog-reference-crop.png"] = body
    if include_development:
        for record in development_references():
            image = cv2.imdecode(np.fromfile(asset_root() / record["imagePath"], np.uint8), 1)
            if image is not None and image.size:
                templates[f"video-dev/{record['catalogId']}.png"] = image
    return templates


@lru_cache(maxsize=4)
def load_verified_warehouse_gameplay_templates(root=None):
    """Load hash-checked, human-labelled warehouse crops from separate matches.

    Only the two reviewed visible-viewport records are admitted. Settlement
    reveals, the 144037 check group, and generated/derived pictures are not
    gameplay references here. Each loaded crop keeps its match, frame, source
    card, grid placement, and hashes so a direct match can be traced back.
    """
    base_root = Path(root).resolve() if root else asset_root().resolve()
    group_specs = (
        (
            "assets/items/video_ground_truth_reference_134436_match2_visible.json",
            "video_audit_20260908_134436_match2",
        ),
        (
            "assets/items/video_ground_truth_reference_134043_visible.json",
            "video_audit_20260908_134043",
        ),
    )
    official_path = base_root / "assets/catalog_065.json"
    try:
        official_rows = json.loads(official_path.read_text(encoding="utf-8-sig"))
        official = {str(row.get("Id") or ""): row for row in official_rows if row.get("Id")}
        registry_path = base_root / "assets/items/verified_source_card_registry.json"
        registry_rows = json.loads(registry_path.read_text(encoding="utf-8-sig")).get("cards", [])
    except (OSError, ValueError, TypeError):
        return {}
    registry = {str(row.get("cardKey") or ""): row for row in registry_rows if row.get("cardKey")}

    quality_alias = {
        "金": "gold", "gold": "gold",
        "紫": "purple", "purple": "purple",
        "红": "red", "red": "red",
        "蓝": "blue", "blue": "blue",
        "绿": "green", "green": "green",
        "白": "white", "灰": "white", "white": "white", "gray": "white", "grey": "white",
    }

    def safe_file(relative):
        candidate = (base_root / str(relative or "")).resolve()
        if not candidate.is_relative_to(base_root) or not candidate.is_file():
            return None
        return candidate

    output = {}
    for relative_json, expected_group in group_specs:
        json_path = safe_file(relative_json)
        if json_path is None:
            continue
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        group_meta = payload.get("metadata") or {}
        if (group_meta.get("recordStableKey") != expected_group
                or group_meta.get("annotationScope") != "VISIBLE_VIEWPORT_ONLY"
                or group_meta.get("coverageStatus") != "PARTIAL"):
            continue

        frame_path = safe_file(group_meta.get("sourceFramePath"))
        frame_sha = str(group_meta.get("sourceFrameSha256") or "").lower()
        # The development checkout has the original full frame. Frozen builds
        # need only the hash-pinned reviewed crop; they may not package build/.
        if frame_path is not None and frame_sha:
            if hashlib.sha256(frame_path.read_bytes()).hexdigest() != frame_sha:
                continue

        for row in payload.get("items") or []:
            catalog_id = str(row.get("catalogId") or "")
            model = official.get(catalog_id)
            geometry = row.get("gridBoundingBox") or {}
            width = int(geometry.get("width") or 0)
            height = int(geometry.get("height") or 0)
            if (not model or row.get("identityStatus") != "VISUALLY_CHECKED_SOURCE_CARD"
                    or str(row.get("canonicalName") or "") != str(model.get("Name") or "")
                    or width != int(model.get("Width") or 0)
                    or height != int(model.get("Height") or 0)
                    or quality_alias.get(str(row.get("quality") or "").strip().lower())
                    != quality_alias.get(str(model.get("Quality") or "").strip().lower())):
                continue

            crop_path = safe_file(row.get("localCropPath"))
            crop_sha = str(row.get("cropSha256") or "").lower()
            if (crop_path is None or len(crop_sha) != 64
                    or hashlib.sha256(crop_path.read_bytes()).hexdigest() != crop_sha):
                continue

            source_card_path = safe_file(row.get("sourceScreenshot"))
            source_card_sha = str(row.get("sourceScreenshotSha256") or "").lower()
            bbox = row.get("cardBbox") or []
            if (source_card_path is None or len(source_card_sha) != 64
                    or hashlib.sha256(source_card_path.read_bytes()).hexdigest() != source_card_sha
                    or len(bbox) != 4):
                continue
            source_key = f"{str(row.get('sourceScreenshot') or '').replace(chr(92), '/')}:" + ",".join(
                str(int(value)) for value in bbox
            )
            registered = registry.get(source_key)
            if (registered is None
                    or str(registered.get("catalogId") or "") != catalog_id
                    or str(registered.get("name") or "") != str(model.get("Name") or "")
                    or str(registered.get("sourceScreenshotSha256") or "").lower() != source_card_sha
                    or (int(registered.get("widthCells") or 0), int(registered.get("heightCells") or 0)) != (width, height)
                    or quality_alias.get(str(registered.get("quality") or "").strip().lower())
                    != quality_alias.get(str(model.get("Quality") or "").strip().lower())):
                continue
            card = cv2.imdecode(np.fromfile(str(source_card_path), np.uint8), cv2.IMREAD_COLOR)
            if card is None:
                continue
            x, y, w, h = (int(value) for value in bbox)
            if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > card.shape[1] or y + h > card.shape[0]:
                continue

            image = cv2.imdecode(np.fromfile(str(crop_path), np.uint8), cv2.IMREAD_COLOR)
            if image is None or not image.size:
                continue
            metadata = {
                "catalogId": catalog_id,
                "name": model.get("Name"),
                "widthCells": width,
                "heightCells": height,
                "quality": row.get("quality"),
                "groupId": expected_group,
                "groundTruthPath": relative_json,
                "referenceId": row.get("referenceId"),
                "localCropPath": str(row.get("localCropPath") or ""),
                "cropSha256": crop_sha,
                "sourceFramePath": group_meta.get("sourceFramePath"),
                "sourceFrameSha256": frame_sha,
                "sourceFrameTimeSec": row.get("sourceFrameTimeSec", group_meta.get("sourceFrameTimeSec")),
                "sourceFrameBbox": row.get("sourceFrameBbox", row.get("pixelBboxOnCanvas")),
                "sourceScreenshot": str(row.get("sourceScreenshot") or ""),
                "sourceScreenshotSha256": source_card_sha,
                "cardBbox": bbox,
                "labelAuthority": "independently visually checked stable catalog ID + verified source card + hash-pinned gameplay crop",
                "sampleClass": "development-training-reference",
            }
            output.setdefault(catalog_id, []).append({"image": image, "metadata": metadata})
    return output


def development_reference_for_template(template_reference):
    prefix = "video-dev/"
    if not str(template_reference or "").startswith(prefix):
        return None
    catalog_id = str(template_reference)[len(prefix):].removesuffix(".png")
    return next((record for record in development_references()
                 if record.get("catalogId") == catalog_id), None)


@lru_cache(maxsize=4)
def load_derived_warehouse_templates(root=None):
    """Load hash-checked catalog-derived warehouse templates as unverified refs.

    A derived picture may help rank candidates, but its provenance never makes
    the picture gameplay evidence or authorizes an exact identity by itself.
    Conflicting, display-only, stale, or unverified records are ignored.
    """
    base_root = Path(root) if root else asset_root()
    manifest_path = base_root / "assets/items/derived_warehouse_icon_references_v1/manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schemaVersion") != "derived-warehouse-icon-references.v1":
            return {}
        visuals = {row["catalogId"]: row for row in verified_references(root=base_root)}
        crops = {row["catalogId"]: row for row in deterministic_reference_crops(root=base_root)}
        official_path = base_root / "assets/catalog_065.json"
        official = {
            str(row.get("Id") or ""): row
            for row in json.loads(official_path.read_text(encoding="utf-8-sig"))
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {}

    quality_aliases = {
        "gold": {"金"}, "purple": {"紫"}, "red": {"红"},
        "blue": {"蓝"}, "green": {"绿"}, "white": {"白", "灰"},
    }
    output = {}
    for record in manifest.get("records", []):
        if not isinstance(record, dict):
            continue
        catalog_id = str(record.get("catalogId") or "")
        visual = visuals.get(catalog_id)
        crop = crops.get(catalog_id)
        model = official.get(catalog_id)
        source_meta = record.get("catalogSource") or {}
        if (
            record.get("status") != "DERIVED_UNVERIFIED"
            or record.get("isGameplayEvidence") is not False
            or record.get("solverIdentityEligible") is not False
            or not catalog_id or visual is None or crop is None or model is None
            or record.get("name") != visual.get("name")
            or int(record.get("widthCells") or 0) != int(visual.get("width") or 0)
            or int(record.get("heightCells") or 0) != int(visual.get("height") or 0)
            or record.get("rarity") != visual.get("rarity")
            or str(model.get("Name") or "") != str(visual.get("name") or "")
            or int(model.get("Width") or 0) != int(visual.get("width") or 0)
            or int(model.get("Height") or 0) != int(visual.get("height") or 0)
            or str(model.get("Quality") or "") not in quality_aliases.get(str(visual.get("rarity") or ""), set())
            or source_meta.get("sourcePath") != visual.get("sourcePath")
            or source_meta.get("sourceSha256") != visual.get("sourceSha256")
            or source_meta.get("cropPath") != crop.get("cropRelativePath")
            or source_meta.get("cropSha256") != crop.get("cropSha256")
        ):
            continue
        try:
            image_path = (base_root / str(record.get("imagePath") or "")).resolve()
            if not image_path.is_relative_to(base_root.resolve()) or not image_path.is_file():
                continue
            if hashlib.sha256(image_path.read_bytes()).hexdigest() != record.get("imageSha256"):
                continue
            pixels = cv2.imdecode(np.fromfile(str(image_path), np.uint8), cv2.IMREAD_COLOR)
            expected_shape = (
                int(record["heightCells"]) * 128,
                int(record["widthCells"]) * 128,
            )
            if pixels is None or pixels.shape[:2] != expected_shape:
                continue
        except (OSError, KeyError, TypeError, ValueError):
            continue
        output[catalog_id] = {"image": pixels, "metadata": record}
    return output


@lru_cache(maxsize=1024)
def _features(pixels, height, width):
    gray = np.frombuffer(pixels, np.uint8).reshape(height, width)
    keypoints, descriptors = cv2.SIFT_create(contrastThreshold=.008).detectAndCompute(gray, None)
    if descriptors is not None:
        # Root normalization reduces descriptor sensitivity to local contrast.
        # The reciprocal, geometry, coverage and identity-margin gates remain.
        descriptors = np.sqrt(descriptors / np.maximum(descriptors.sum(axis=1, keepdims=True), 1e-8))
    return keypoints, descriptors


def _feature_match_evidence(roi, reference):
    """Reciprocal matches plus nondegenerate similarity geometry, not raw counts.

    Score is an evidence strength, not a calibrated probability. Texture-poor
    items remain unresolved. Repeated descriptors may never vote many-to-one.
    """
    empty = {"score": 0.0, "inliers": 0, "matches": 0, "scale": None}
    if roi is None or reference is None or min(roi.shape[:2]) < 8:
        return empty
    pad = max(1, round(min(roi.shape[:2]) * .04))
    query = cv2.resize(roi[pad:-pad, pad:-pad], None, fx=3, fy=3)
    q = cv2.cvtColor(query, cv2.COLOR_BGR2GRAY)
    t = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    qk, qd = _features(q.tobytes(), *q.shape)
    tk, td = _features(t.tobytes(), *t.shape)
    if qd is None or td is None or min(len(qd), len(td)) < 4:
        return empty
    matcher = cv2.BFMatcher()
    backward = matcher.match(td, qd)
    good = [a for a, b in matcher.knnMatch(qd, td, k=2)
            if a.distance < .72 * b.distance and backward[a.trainIdx].trainIdx == a.queryIdx]
    if len(good) < 4:
        return {**empty, "matches": len(good)}
    src = np.float32([qk[m.queryIdx].pt for m in good])
    dst = np.float32([tk[m.trainIdx].pt for m in good])
    matrix, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3)
    if matrix is None or mask is None:
        return empty
    scale = float(np.hypot(matrix[0, 0], matrix[1, 0]))
    inliers = int(mask.sum())
    coverage = cv2.contourArea(cv2.convexHull(src[mask.ravel().astype(bool)])) / (q.shape[0] * q.shape[1])
    aligned = cv2.warpAffine(q, matrix, (t.shape[1], t.shape[0]))
    valid = cv2.warpAffine(np.full(q.shape, 255, np.uint8), matrix, (t.shape[1], t.shape[0]))
    valid = cv2.erode(valid, np.ones((5, 5), np.uint8)) > 250
    def gradient(image):
        gx = cv2.Sobel(image, cv2.CV_32F, 1, 0)
        gy = cv2.Sobel(image, cv2.CV_32F, 0, 1)
        return np.hypot(gx, gy)[valid]
    a, b = gradient(aligned), gradient(t)
    agreement = float(np.dot(a, b) / max(1e-8, float(np.linalg.norm(a) * np.linalg.norm(b))))
    if not (.08 < scale < 5) or inliers < 5 or coverage < .015 or inliers / len(good) < .55:
        score = 0.0
    else:
        score = 1 - math.exp(-inliers / 4)
        if agreement >= .75 and coverage >= .02:
            score = max(score, .9 + .1 * (agreement - .75) / .25)
    return {"score": round(score, 4), "inliers": inliers, "matches": len(good),
            "scale": round(scale, 4), "coverage": round(coverage, 4), "gradientAgreement": round(agreement, 4)}


def _appearance_alignment(roi, reference):
    """A second, independent check for low-texture unrotated objects.

    Both edge layout and color correlation must agree at the SAME translation
    and scale. Padding carries no edge evidence. No item name-specific rules.
    """
    def gradient(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return np.hypot(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    pad = max(1, round(min(roi.shape[:2]) * .05))
    query = cv2.resize(roi[pad:-pad, pad:-pad], None, fx=3, fy=3)
    qg = gradient(query)
    if float(np.linalg.norm(qg)) < 1:
        return {"score": 0.0}
    qg = cv2.copyMakeBorder(qg, 60, 60, 100, 100, cv2.BORDER_CONSTANT)
    query = cv2.copyMakeBorder(query, 60, 60, 100, 100, cv2.BORDER_REPLICATE)
    tg = gradient(reference)
    best = {"score": 0.0}
    for scale in np.linspace(.6, 1.8, 25):
        scaled = cv2.resize(tg, None, fx=float(scale), fy=float(scale))
        h, w = scaled.shape
        if h > qg.shape[0] or w > qg.shape[1]:
            continue
        _, edge_score, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(qg, scaled, cv2.TM_CCORR_NORMED))
        if not np.isfinite(edge_score) or edge_score < .80:
            continue
        color_score = float(cv2.matchTemplate(query[y:y+h, x:x+w],
            cv2.resize(reference, (w, h)), cv2.TM_CCOEFF_NORMED)[0, 0])
        if not np.isfinite(color_score) or color_score < .80:
            continue
        score = .85 + .15 * min(edge_score, color_score)
        if score > best["score"]:
            best = {"score": round(score, 4), "edgeAgreement": round(edge_score, 4),
                    "colorAgreement": round(color_score, 4), "appearanceScale": round(float(scale), 4),
                    "appearanceTranslation": [x, y], "method": "EDGE_AND_COLOR_ALIGNMENT"}
    return best


def _foreground_crop(image, occlusion=None):
    """Remove the card's hue before comparing an object's silhouette/color.

    Warehouse rarity backgrounds use different colors from the catalog. This
    path only supports a single connected, fully visible foreground component;
    it supplies no evidence when that component cannot be isolated.
    """
    pad = max(2, round(min(image.shape[:2]) * .08))
    image = image[pad:-pad, pad:-pad]
    if occlusion is not None:
        occlusion = occlusion[pad:-pad, pad:-pad]
    if min(image.shape[:2]) < 8:
        return None
    # Give morphology the same physical size for tiny video icons and large
    # source cards; otherwise a three-pixel closing changes their silhouettes.
    scale = 256 / max(image.shape[:2])
    image = cv2.resize(image, None, fx=scale, fy=scale)
    if occlusion is not None:
        occlusion = cv2.resize(occlusion, (image.shape[1], image.shape[0])) > 0
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    border = np.concatenate((hsv[1, ::3], hsv[-2, ::3], hsv[::3, 1], hsv[::3, -2]))
    hue, saturation, _ = np.median(border, axis=0)
    hue_distance = np.abs(hsv[:, :, 0] - hue)
    hue_distance = np.minimum(hue_distance, 180 - hue_distance)
    if saturation > 45:
        foreground = ((hue_distance > 12) & (hsv[:, :, 1] > 40)) | (hsv[:, :, 1] < saturation * .35)
    else:
        foreground = hsv[:, :, 1] > 45
    mask = foreground.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(contour) / mask.size
    if not .03 < area < .85:
        return None
    x, y, w, h = cv2.boundingRect(contour)
    mask[:] = 0
    cv2.drawContours(mask, [contour], -1, 255, -1)
    if occlusion is not None:
        ys, xs = np.where((mask > 0) & ~occlusion)
        if len(xs) < 40:
            return None
        x, y = int(xs.min()), int(ys.min())
        w, h = int(xs.max()) + 1 - x, int(ys.max()) + 1 - y
        return image[y:y+h, x:x+w], mask[y:y+h, x:x+w], ~occlusion[y:y+h, x:x+w]
    return image[y:y+h, x:x+w], mask[y:y+h, x:x+w]


def _foreground_alignment(roi, reference):
    query, template = _foreground_crop(roi), _foreground_crop(reference)
    if query is None or template is None:
        return {"score": 0.0}
    q, qm = query
    t, tm = template
    ratio = (q.shape[1] / q.shape[0]) / (t.shape[1] / t.shape[0])
    if not .8 < ratio < 1.25:
        return {"score": 0.0}
    q, t = (cv2.resize(i, (96, 96)).astype(np.float32) for i in (q, t))
    qm, tm = (cv2.resize(i, (96, 96)) > 127 for i in (qm, tm))
    overlap = qm & tm
    iou = float(overlap.sum() / max(1, (qm | tm).sum()))
    if iou < .85:
        return {"score": 0.0}
    a, b = q[overlap].ravel(), t[overlap].ravel()
    error = float(np.mean(np.abs(a - b)))
    a, b = a - a.mean(), b - b.mean()
    correlation = float(np.dot(a, b) / max(1e-8, float(np.linalg.norm(a) * np.linalg.norm(b))))
    if correlation < .85 or error > 25:
        return {"score": 0.0}
    return {"score": round(.9 + .1 * min(iou, correlation), 4),
            "method": "FOREGROUND_SHAPE_AND_COLOR", "foregroundIoU": round(iou, 4),
            "foregroundColorAgreement": round(correlation, 4),
            "foregroundColorError": round(error, 4)}


def _occluded_foreground_alignment(roi, reference):
    from selection_occlusion import selection_occlusion
    occlusion, detection = selection_occlusion(roi)
    if not occlusion.any():
        return {"score": 0.0}
    query, template = _foreground_crop(roi, occlusion), _foreground_crop(reference)
    if query is None or template is None:
        return {"score": 0.0}
    q, qm, valid = query
    t, tm = template
    ratio = (q.shape[1] / q.shape[0]) / (t.shape[1] / t.shape[0])
    if not .8 < ratio < 1.25:
        return {"score": 0.0}
    q, t = (cv2.resize(i, (96, 96)).astype(np.float32) for i in (q, t))
    qm, tm = (cv2.resize(i, (96, 96)) > 127 for i in (qm, tm))
    valid = cv2.resize(valid.astype(np.uint8), (96, 96)) > 0
    overlap = qm & tm & valid
    visible = float((tm & valid).sum() / max(1, tm.sum()))
    iou = float(overlap.sum() / max(1, ((qm | tm) & valid).sum()))
    if overlap.sum() < 100 or visible < .45 or iou < .90:
        return {"score": 0.0}
    a, b = q[overlap].ravel(), t[overlap].ravel()
    error = float(np.mean(np.abs(a - b)))
    a, b = a - a.mean(), b - b.mean()
    correlation = float(np.dot(a, b) / max(1e-8, float(np.linalg.norm(a) * np.linalg.norm(b))))
    if correlation < .85 or error > 25:
        return {"score": 0.0}
    return {"score": round(.9 + .1 * min(iou, correlation), 4),
            "method": "VISIBLE_FOREGROUND_WITH_SELECTION_MASK", "selectionMarker": detection,
            "visibleForegroundFraction": round(visible, 4), "foregroundIoU": round(iou, 4),
            "foregroundColorAgreement": round(correlation, 4), "foregroundColorError": round(error, 4)}


@lru_cache(maxsize=4096)
def _cached_match(query_bytes, query_shape, reference_bytes, reference_shape):
    query = np.frombuffer(query_bytes, np.uint8).reshape(query_shape)
    reference = np.frombuffer(reference_bytes, np.uint8).reshape(reference_shape)
    evidence = _feature_match_evidence(query, reference)
    if evidence["score"] < .85:
        appearance = _appearance_alignment(query, reference)
        if appearance["score"] > evidence["score"]:
            evidence = {**evidence, **appearance}
    if evidence["score"] < .85:
        foreground = _foreground_alignment(query, reference)
        if foreground["score"] > evidence["score"]:
            evidence = {**evidence, **foreground}
    if evidence["score"] < .85:
        visible = _occluded_foreground_alignment(query, reference)
        if visible["score"] > evidence["score"]:
            evidence = {**evidence, **visible}
    if evidence["score"] < .85:
        # Tiny compressed video icons cannot retain the sharp catalog edges.
        # Compare a mildly smoothed reference through the SAME evidence gates.
        soft = cv2.GaussianBlur(reference, (0, 0), 1.5)
        softened = _feature_match_evidence(query, soft)
        # Smoothing can create many matches on a shared pedestal or border.
        # Require the aligned image to agree, not merely the local descriptors.
        if softened.get('gradientAgreement', 0) < .70:
            softened = {'score': 0.0}
        if softened['score'] < .85:
            for matcher in (_foreground_alignment, _occluded_foreground_alignment):
                candidate = matcher(query, soft)
                if candidate['score'] > softened['score']:
                    softened = candidate
        if softened['score'] > evidence['score']:
            evidence = {**softened, 'referenceGaussianSigma': 1.5}
    return evidence


def feature_match_evidence(roi, reference):
    if roi is None or reference is None or min(roi.shape[:2]) < 8 or reference.size == 0:
        return {"score": 0.0, "inliers": 0, "matches": 0}
    return dict(_cached_match(roi.tobytes(), tuple(roi.shape), reference.tobytes(), tuple(reference.shape)))
