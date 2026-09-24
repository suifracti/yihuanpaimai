"""Build traceable, unverified in-game appearance references from catalog/game pairs.

The generated images are visual hypotheses, never in-game evidence or identity
confirmation. Inputs are existing visually checked catalog source cards and
independently annotated gameplay crops. No input image or catalog is modified.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from visual_catalog import (  # noqa: E402
    _catalog_reference_body,
    deterministic_reference_crops,
    verified_references,
)
from warehouse_placement_resolver import WarehousePlacementResolver  # noqa: E402
from warehouse_vision import WarehouseTemplateMatcher, WarehouseVisionConfig  # noqa: E402


VISUAL_PATH = ROOT / "assets/items/visual_catalog_v2.json"
OFFICIAL_PATH = ROOT / "assets/catalog_065.json"
FIT_GT_PATH = ROOT / "assets/items/video_ground_truth_reference_134436_match2_visible.json"
FIT_REPLAY_PATH = ROOT / "build/codex_other_video_20260912/134436-small-icon-replay/evaluated_units.json"
CHECK_GT_PATH = ROOT / "assets/items/video_ground_truth_reference_144037.json"
DEV_PATH = ROOT / "assets/items/video_development_references_v1.json"
OUT_DIR = ROOT / "assets/items/derived_warehouse_icon_references_v1"
MANIFEST_PATH = OUT_DIR / "manifest.json"
_FOREGROUND_ALIGNMENT = WarehousePlacementResolver.__new__(WarehousePlacementResolver)

RARITY_TO_QUALITY = {
    "gold": {"金"},
    "purple": {"紫"},
    "red": {"红"},
    "blue": {"蓝"},
    "green": {"绿"},
    "white": {"白", "灰"},
}
BODY_CROP_FRACTIONS = {"x": [0.20, 0.80], "y": [0.18, 0.76]}
CANVAS_PIXELS_PER_CELL = 128


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_image(path: Path) -> np.ndarray:
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def foreground_fraction(image: np.ndarray) -> tuple[float, float] | None:
    extracted = WarehousePlacementResolver._extract_foreground(image)
    if extracted is None:
        return None
    foreground, _mask = extracted
    pad = max(2, round(min(image.shape[:2]) * 0.08))
    cropped = image[pad:-pad, pad:-pad]
    scale = 256 / max(cropped.shape[:2])
    resized_w = max(1, round(cropped.shape[1] * scale))
    resized_h = max(1, round(cropped.shape[0] * scale))
    return foreground.shape[1] / resized_w, foreground.shape[0] / resized_h


def verified_official_sources() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    visual_rows = {row["catalogId"]: row for row in verified_references(root=ROOT)}
    crop_rows = {row["catalogId"]: row for row in deterministic_reference_crops(root=ROOT)}
    official_rows = {str(row.get("Id") or ""): row for row in read_json(OFFICIAL_PATH)}
    eligible: dict[str, dict[str, Any]] = {}
    exclusions: Counter[str] = Counter()

    for catalog_id, visual in visual_rows.items():
        official = official_rows.get(catalog_id)
        crop = crop_rows.get(catalog_id)
        if official is None:
            exclusions["no_official_id"] += 1
            continue
        if (
            str(official.get("Name") or "") != str(visual.get("name") or "")
            or int(official.get("Width") or 0) != int(visual.get("width") or 0)
            or int(official.get("Height") or 0) != int(visual.get("height") or 0)
            or str(official.get("Quality") or "") not in RARITY_TO_QUALITY.get(str(visual.get("rarity") or ""), set())
        ):
            exclusions["official_identity_or_size_conflict"] += 1
            continue
        if crop is None or (
            int(crop.get("widthCells") or 0), int(crop.get("heightCells") or 0)
        ) != (int(visual["width"]), int(visual["height"])):
            exclusions["missing_or_conflicting_source_crop"] += 1
            continue
        eligible[catalog_id] = {
            "visual": visual,
            "official": official,
            "crop": crop,
        }
    return eligible, dict(exclusions)


def gameplay_samples() -> tuple[set[str], list[dict[str, Any]]]:
    ids: set[str] = set()
    samples: list[dict[str, Any]] = []
    for path in (FIT_GT_PATH, CHECK_GT_PATH):
        payload = read_json(path)
        group_id = str((payload.get("metadata") or {}).get("recordStableKey") or path.stem)
        for row in payload.get("items") or []:
            catalog_id = str(row.get("catalogId") or "")
            crop_rel = str(row.get("localCropPath") or "")
            crop_path = ROOT / crop_rel
            declared_sha = str(row.get("cropSha256") or "")
            if not catalog_id or not crop_rel or not crop_path.is_file():
                continue
            current_sha = sha256(crop_path)
            if declared_sha and current_sha != declared_sha:
                raise ValueError(f"game crop hash mismatch: {crop_rel}")
            ids.add(catalog_id)
            samples.append({
                "catalogId": catalog_id,
                "groupId": group_id,
                "groundTruthPath": path.relative_to(ROOT).as_posix(),
                "referenceId": row.get("referenceId"),
                "localCropPath": crop_rel,
                "cropSha256": current_sha,
                "cropShaWasDeclared": bool(declared_sha),
                "gameSourceFrameTimeSec": row.get("sourceFrameTimeSec", row.get("videoSourceFrameTimeSec")),
                "gameSourceFramePath": (payload.get("metadata") or {}).get("sourceFramePath"),
                "gameSourceBbox": row.get("sourceFrameBbox", row.get("pixelBboxOnCanvas")),
            })

    if DEV_PATH.is_file():
        for row in (read_json(DEV_PATH).get("records") or []):
            if row.get("sampleClass") != "development-reference":
                continue
            catalog_id = str(row.get("catalogId") or "")
            image_path = ROOT / str(row.get("imagePath") or "")
            declared_sha = str(row.get("imageSha256") or "")
            if catalog_id and image_path.is_file() and declared_sha and sha256(image_path) == declared_sha:
                ids.add(catalog_id)
                samples.append({
                    "catalogId": catalog_id,
                    "groupId": "video_development_references_v1",
                    "imagePath": str(row["imagePath"]),
                    "imageSha256": declared_sha,
                    "sampleClass": row["sampleClass"],
                })
    return ids, samples


def fit_pairs(eligible: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    gt = read_json(FIT_GT_PATH)
    replay = read_json(FIT_REPLAY_PATH)
    auto_confirmed = set()
    for unit in replay:
        if unit.get("confirmationStatus") != "CONFIRMED" or unit.get("confirmedByHuman") is not False:
            continue
        footprint = unit.get("footprint") or {}
        auto_confirmed.add((
            str(unit.get("selectedCatalogId") or ""),
            int(footprint.get("widthCells") or 0),
            int(footprint.get("heightCells") or 0),
        ))

    pairs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in gt.get("items") or []:
        catalog_id = str(row.get("catalogId") or "")
        geometry = row.get("gridBoundingBox") or {}
        width, height = int(geometry.get("width") or 0), int(geometry.get("height") or 0)
        source = eligible.get(catalog_id)
        if (
            source is None
            or catalog_id in seen
            or row.get("identityStatus") != "VISUALLY_CHECKED_SOURCE_CARD"
            or (catalog_id, width, height) not in auto_confirmed
            or (width, height) != (int(source["visual"]["width"]), int(source["visual"]["height"]))
        ):
            continue

        game_crop_rel = str(row.get("localCropPath") or "")
        game_crop_path = ROOT / game_crop_rel
        if not game_crop_path.is_file() or sha256(game_crop_path) != str(row.get("cropSha256") or ""):
            raise ValueError(f"fit game crop missing or hash mismatch: {game_crop_rel}")
        source_crop_path = ROOT / source["crop"]["cropRelativePath"]
        source_card_path = ROOT / source["visual"]["sourcePath"]
        if sha256(source_card_path) != str(source["visual"]["sourceSha256"]):
            raise ValueError(f"visual catalog source hash mismatch: {source_card_path}")
        source_img = read_image(source_crop_path)
        game_img = read_image(game_crop_path)
        if source_img is None or game_img is None:
            continue
        source_fraction = foreground_fraction(_catalog_reference_body(source_img))
        target_fraction = foreground_fraction(game_img)
        if source_fraction is None or target_fraction is None:
            continue
        registration = _FOREGROUND_ALIGNMENT._compute_foreground_alignment(game_img, source_img)
        pairs.append({
            "catalogId": catalog_id,
            "widthCells": width,
            "heightCells": height,
            "groundTruthPath": FIT_GT_PATH.relative_to(ROOT).as_posix(),
            "referenceId": row.get("referenceId"),
            "pairAuthority": "independent visually checked ground truth ID + hash-verified catalog source and gameplay crop",
            "catalogScreenshotPath": source["visual"]["sourcePath"],
            "catalogScreenshotSha256": source["visual"]["sourceSha256"],
            "catalogCardBbox": source["visual"]["cardBbox"],
            "catalogCropPath": source["crop"]["cropRelativePath"],
            "catalogCropSha256": source["crop"]["cropSha256"],
            "gameCropPath": game_crop_rel,
            "gameCropSha256": row["cropSha256"],
            "targetForegroundFraction": [round(target_fraction[0], 8), round(target_fraction[1], 8)],
            "sourceForegroundFraction": [round(source_fraction[0], 8), round(source_fraction[1], 8)],
            "existingForegroundRegistration": registration,
        })
        seen.add(catalog_id)
    return pairs


def fit_occupancy(pairs: list[dict[str, Any]]) -> tuple[tuple[float, float], dict[tuple[int, int], tuple[float, float]]]:
    values = [tuple(float(v) for v in row["targetForegroundFraction"]) for row in pairs]
    if not values:
        raise ValueError("no trusted catalog/game pairs available")
    pooled = tuple(float(np.median([value[i] for value in values])) for i in range(2))
    by_shape: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for row in pairs:
        by_shape[(int(row["widthCells"]), int(row["heightCells"]))].append(
            tuple(float(v) for v in row["targetForegroundFraction"])
        )
    models = {
        shape: tuple(float(np.median([value[i] for value in rows])) for i in range(2))
        for shape, rows in by_shape.items()
        if len(rows) >= 2
    }
    return pooled, models


def build_reference(
    catalog_id: str,
    source: dict[str, Any],
    occupancy: tuple[float, float],
) -> tuple[np.ndarray, dict[str, Any]] | None:
    source_image = read_image(ROOT / source["crop"]["cropRelativePath"])
    if source_image is None:
        return None
    body = _catalog_reference_body(source_image)
    extracted = WarehousePlacementResolver._extract_foreground(body)
    if extracted is None:
        return None
    foreground, mask = extracted
    width = int(source["visual"]["width"])
    height = int(source["visual"]["height"])
    canvas_w = CANVAS_PIXELS_PER_CELL * width
    canvas_h = CANVAS_PIXELS_PER_CELL * height
    target_w, target_h = occupancy
    scale = min(canvas_w * target_w / foreground.shape[1], canvas_h * target_h / foreground.shape[0])
    out_w = max(1, round(foreground.shape[1] * scale))
    out_h = max(1, round(foreground.shape[0] * scale))
    obj = cv2.resize(foreground, (out_w, out_h), interpolation=cv2.INTER_AREA)
    alpha = cv2.resize(mask, (out_w, out_h), interpolation=cv2.INTER_NEAREST) > 0

    hsv = cv2.cvtColor(body, cv2.COLOR_BGR2HSV)
    edge = np.concatenate((
        hsv[:3, :, :].reshape(-1, 3), hsv[-3:, :, :].reshape(-1, 3),
        hsv[:, :3, :].reshape(-1, 3), hsv[:, -3:, :].reshape(-1, 3),
    ))
    background_hsv = np.median(edge, axis=0).astype(np.uint8).reshape(1, 1, 3)
    background_bgr = cv2.cvtColor(background_hsv, cv2.COLOR_HSV2BGR)[0, 0]
    canvas = np.empty((canvas_h, canvas_w, 3), dtype=np.uint8)
    canvas[:] = background_bgr
    x = (canvas_w - out_w) // 2
    y = (canvas_h - out_h) // 2
    target = canvas[y:y + out_h, x:x + out_w]
    target[alpha] = obj[alpha]
    transform = {
        "cropMethod": "catalog_reference_body",
        "cropFractions": BODY_CROP_FRACTIONS,
        "foregroundMethod": "WarehousePlacementResolver._extract_foreground",
        "scaleMethod": "fit pooled-or-shape median gameplay foreground occupancy into exact grid-cell canvas",
        "rotationDegrees": 0,
        "targetForegroundFraction": [round(float(target_w), 8), round(float(target_h), 8)],
        "sourceForegroundPixels": [int(foreground.shape[1]), int(foreground.shape[0])],
        "outputCanvasPixels": [canvas_w, canvas_h],
        "outputObjectRect": [x, y, out_w, out_h],
        "backgroundSource": "median HSV edge of catalog body crop",
    }
    return canvas, transform


def score_one(matcher: WarehouseTemplateMatcher, roi: np.ndarray, candidate: dict[str, Any], derived: np.ndarray | None) -> tuple[float, str]:
    roi_h, roi_w = roi.shape[:2]
    file_name = candidate.get("File") or candidate.get("ImageFile")
    direct = matcher.templates.get(file_name) if file_name else None
    if direct is None:
        name = str(candidate.get("Name") or "")
        direct = next((image for filename, image in matcher.templates.items() if name and name in filename), None)
    direct_score = 0.0
    derived_score = None
    for image, kind in ((direct, "DIRECT"), (derived, "DERIVED")):
        if image is None:
            continue
        try:
            resized = cv2.resize(image, (roi_w, roi_h))
            score = float(cv2.minMaxLoc(cv2.matchTemplate(roi, resized, cv2.TM_CCOEFF_NORMED))[1])
        except Exception:
            continue
        if kind == "DIRECT":
            direct_score = score
        else:
            derived_score = score
    if derived_score is None:
        return direct_score, "DIRECT" if direct is not None else "NONE"
    combined_score = max(direct_score, derived_score)
    if derived_score > direct_score:
        return combined_score, "DERIVED"
    if direct is not None and direct_score > 0:
        return combined_score, "DIRECT"
    if derived_score > 0:
        return combined_score, "DERIVED"
    return combined_score, "NONE"


def evaluate_historical_transfer(
    eligible: dict[str, dict[str, Any]],
    pooled: tuple[float, float],
    shape_models: dict[tuple[int, int], tuple[float, float]],
    fit_ids: set[str],
) -> dict[str, Any]:
    check_data = read_json(CHECK_GT_PATH)
    matcher = WarehouseTemplateMatcher()
    config = WarehouseVisionConfig()
    # These refs are generated only from catalog sources and the fit group.
    # Building all eligible rows in memory permits transfer evaluation on the
    # separate historical match without promoting those images to training.
    derived: dict[str, np.ndarray] = {}
    for catalog_id, source in eligible.items():
        shape = (int(source["visual"]["width"]), int(source["visual"]["height"]))
        image = build_reference(catalog_id, source, shape_models.get(shape, pooled))
        if image is not None:
            derived[catalog_id] = image[0]

    counts = {
        "candidateEligible": 0,
        "truthNotInOfficialCandidateSet": 0,
        "directTopCandidateCorrect": 0,
        "directCorrectConfirmations": 0,
        "directWrongConfirmations": 0,
        "directUnresolved": 0,
        "combinedTopCandidateCorrect": 0,
        "topCandidateImproved": 0,
        "topCandidateRegressed": 0,
        "combinedCorrectConfirmations": 0,
        "combinedWrongConfirmations": 0,
        "derivedThresholdCorrectBlocked": 0,
        "derivedThresholdWrongBlocked": 0,
        "combinedUnresolved": 0,
    }
    rows = []
    for item in check_data.get("items") or []:
        catalog_id = str(item.get("catalogId") or "")
        if catalog_id in fit_ids:
            continue
        geom = item.get("gridBoundingBox") or {}
        width, height = int(geom.get("width") or 0), int(geom.get("height") or 0)
        if catalog_id not in eligible:
            continue
        if (width, height) != (int(eligible[catalog_id]["visual"]["width"]), int(eligible[catalog_id]["visual"]["height"])):
            continue
        crop_path = ROOT / str(item.get("localCropPath") or "")
        declared_game_sha = str(item.get("cropSha256") or "")
        if not crop_path.is_file() or (declared_game_sha and sha256(crop_path) != declared_game_sha):
            raise ValueError(f"historical check crop hash mismatch: {crop_path}")
        roi = read_image(crop_path)
        if roi is None:
            continue
        candidates = matcher.get_candidates(str(item.get("quality") or ""), width, height)
        by_id = {str(c.get("Id") or c.get("catalogId") or ""): c for c in candidates}
        if catalog_id not in by_id:
            counts["truthNotInOfficialCandidateSet"] += 1
            continue
        direct_ranked = []
        combined_ranked = []
        for index, candidate in enumerate(candidates):
            cid = str(candidate.get("Id") or candidate.get("catalogId") or "")
            direct_score, _ = score_one(matcher, roi, candidate, None)
            combined_score, combined_kind = score_one(matcher, roi, candidate, derived.get(cid))
            direct_ranked.append((direct_score, index, cid))
            combined_ranked.append((combined_score, index, cid, combined_kind))
        direct_ranked.sort(key=lambda row: (-row[0], row[1]))
        combined_ranked.sort(key=lambda row: (-row[0], row[1]))
        direct_top = direct_ranked[0] if direct_ranked else (0.0, 0, "")
        direct_second = direct_ranked[1][0] if len(direct_ranked) > 1 else 0.0
        combined_top = combined_ranked[0] if combined_ranked else (0.0, 0, "", "NONE")
        combined_second = combined_ranked[1][0] if len(combined_ranked) > 1 else 0.0
        direct_confirmed = direct_top[0] >= config.MATCH_CONFIDENCE_THRESHOLD and direct_top[0] - direct_second >= config.MATCH_MARGIN_THRESHOLD
        combined_confirmed = combined_top[0] >= config.MATCH_CONFIDENCE_THRESHOLD and combined_top[0] - combined_second >= config.MATCH_MARGIN_THRESHOLD
        # New imagery cannot displace an exact result already authorized by
        # the unchanged legacy direct-template gate.
        combined_exact_allowed = direct_confirmed or (combined_confirmed and combined_top[3] == "DIRECT")
        combined_exact_id = direct_top[2] if direct_confirmed else combined_top[2]
        counts["candidateEligible"] += 1
        if direct_top[2] == catalog_id:
            counts["directTopCandidateCorrect"] += 1
        if direct_confirmed and direct_top[2] == catalog_id:
            counts["directCorrectConfirmations"] += 1
        elif direct_confirmed:
            counts["directWrongConfirmations"] += 1
        else:
            counts["directUnresolved"] += 1
        if combined_top[2] == catalog_id:
            counts["combinedTopCandidateCorrect"] += 1
        if direct_top[2] != catalog_id and combined_top[2] == catalog_id:
            counts["topCandidateImproved"] += 1
        elif direct_top[2] == catalog_id and combined_top[2] != catalog_id:
            counts["topCandidateRegressed"] += 1
        # Generated refs are deliberately barred from self-confirmation in
        # production; direct-only winners retain the existing strict gate.
        if not direct_confirmed and combined_confirmed and combined_top[3] == "DERIVED" and combined_top[2] == catalog_id:
            counts["derivedThresholdCorrectBlocked"] += 1
        elif not direct_confirmed and combined_confirmed and combined_top[3] == "DERIVED":
            counts["derivedThresholdWrongBlocked"] += 1
        elif combined_exact_allowed and combined_exact_id == catalog_id:
            counts["combinedCorrectConfirmations"] += 1
        elif combined_exact_allowed:
            counts["combinedWrongConfirmations"] += 1
        else:
            counts["combinedUnresolved"] += 1
        rows.append({
            "referenceId": item.get("referenceId"),
            "catalogId": catalog_id,
            "size": f"{width}x{height}",
            "directRawTopCandidate": direct_top[2] or None,
            "directTop": direct_top[2] if direct_confirmed else None,
            "directScore": round(direct_top[0], 4),
            "combinedTopCandidate": combined_top[2] or None,
            "combinedTopReferenceKind": combined_top[3],
            "combinedScore": round(combined_top[0], 4),
            "combinedThresholdWouldPassButStillUnverified": bool(not direct_confirmed and combined_confirmed and combined_top[3] == "DERIVED"),
        })
    return {
        "group": CHECK_GT_PATH.relative_to(ROOT).as_posix(),
        "groupUse": "historical cross-match check; previously used development material, not fresh unseen acceptance",
        "fitIdsExcluded": sorted(fit_ids),
        "counts": counts,
        "rows": rows,
        "productionExactGate": "DERIVED_UNVERIFIED never upgrades to EXACT_IDENTIFIED; only direct legacy references may pass the existing strict gate",
    }


def main() -> None:
    eligible, exclusions = verified_official_sources()
    gameplay_ids, gameplay_sources = gameplay_samples()
    pairs = fit_pairs(eligible)
    pooled, shape_models = fit_occupancy(pairs)
    fit_ids = {str(row["catalogId"]) for row in pairs}
    missing_ids = sorted(set(eligible) - gameplay_ids)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    generation_failures = []
    for catalog_id in missing_ids:
        source = eligible[catalog_id]
        width, height = int(source["visual"]["width"]), int(source["visual"]["height"])
        occupancy = shape_models.get((width, height), pooled)
        built = build_reference(catalog_id, source, occupancy)
        if built is None:
            generation_failures.append({"catalogId": catalog_id, "reason": "existing foreground extractor found no usable foreground"})
            continue
        image, transform = built
        image_name = f"{catalog_id}.png"
        image_path = OUT_DIR / image_name
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            raise RuntimeError(f"failed to encode derived reference: {catalog_id}")
        image_path.write_bytes(encoded.tobytes())
        visual = source["visual"]
        crop = source["crop"]
        records.append({
            "catalogId": catalog_id,
            "name": visual["name"],
            "widthCells": width,
            "heightCells": height,
            "rarity": visual["rarity"],
            "status": "DERIVED_UNVERIFIED",
            "isGameplayEvidence": False,
            "solverIdentityEligible": False,
            "imagePath": image_path.relative_to(ROOT).as_posix(),
            "imageSha256": sha256(image_path),
            "catalogSource": {
                "sourcePath": visual["sourcePath"],
                "sourceSha256": visual["sourceSha256"],
                "cardBbox": visual["cardBbox"],
                "cropPath": crop["cropRelativePath"],
                "cropSha256": crop["cropSha256"],
            },
            "fitModel": {
                "source": f"shape:{width}x{height}" if (width, height) in shape_models else "pooled",
                "pairCount": sum(1 for row in pairs if (row["widthCells"], row["heightCells"]) == (width, height))
                    if (width, height) in shape_models else len(pairs),
            },
            "transform": transform,
        })

    history_check = evaluate_historical_transfer(eligible, pooled, shape_models, fit_ids)
    manifest = {
        "schemaVersion": "derived-warehouse-icon-references.v1",
        "status": "DERIVED_UNVERIFIED",
        "scope": "Predicted warehouse appearance from verified catalog sources and fit-group appearance transform; never raw gameplay evidence, never self-confirming identity, never solver-eligible by itself.",
        "generator": "tools/generate_derived_warehouse_icon_references.py",
        "officialCatalogPath": OFFICIAL_PATH.relative_to(ROOT).as_posix(),
        "visualCatalogPath": VISUAL_PATH.relative_to(ROOT).as_posix(),
        "includedSourceRecordCount": len(eligible),
        "exclusionSummary": exclusions,
        "gameplaySourceGroups": gameplay_sources,
        "gameplaySampleCatalogIds": sorted(gameplay_ids),
        "fitGroup": {
            "path": FIT_GT_PATH.relative_to(ROOT).as_posix(),
            "priorResultPath": FIT_REPLAY_PATH.relative_to(ROOT).as_posix(),
            "priorOutcome": "23 annotated physical items, 21 previous automatic exact confirmations, 2 unresolved; fit subset uses independently visually checked pair IDs within those prior confirmations.",
            "recordCount": len(pairs),
            "method": "median foreground occupancy, no per-item fitting; shape-specific only at n>=2",
            "pooledForegroundFraction": [round(float(v), 8) for v in pooled],
            "shapeModels": {
                f"{w}x{h}": {
                    "foregroundFraction": [round(float(v), 8) for v in occupancy],
                    "pairCount": sum(1 for row in pairs if (row["widthCells"], row["heightCells"]) == (w, h)),
                }
                for (w, h), occupancy in sorted(shape_models.items())
            },
            "pairs": pairs,
        },
        "generation": {
            "gameplaySamplesAlreadyAvailable": len(gameplay_ids),
            "eligibleMissingGameplaySamples": len(missing_ids),
            "generated": len(records),
            "generationFailures": generation_failures,
            "sourceFieldConflictsRemainExcluded": True,
            "displayOnlyEntriesIncluded": False,
            "rotation": "not applied; exact official width/height orientation retained. Existing foreground registration is recorded per fit pair; it did not support one consistent rotation across the small fit subset.",
        },
        "historicalTransferCheck": history_check,
        "records": records,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    referenced_images = {Path(row["imagePath"]).name for row in records}
    for stale_image in OUT_DIR.glob("image*.png"):
        if stale_image.name not in referenced_images:
            stale_image.unlink()
    print(json.dumps({
        "verifiedSourceRecords": len(eligible),
        "sourceExclusions": exclusions,
        "fitPairs": len(pairs),
        "pooledForegroundFraction": pooled,
        "shapeModels": {f"{w}x{h}": value for (w, h), value in shape_models.items()},
        "knownGameplayIds": len(gameplay_ids),
        "missingGameplayIds": len(missing_ids),
        "generated": len(records),
        "historicalCheck": history_check["counts"],
        "manifest": MANIFEST_PATH.relative_to(ROOT).as_posix(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
