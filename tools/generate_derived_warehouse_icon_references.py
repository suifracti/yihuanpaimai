"""Build traceable, unverified in-game appearance references from catalog/game pairs.

The generated images are visual hypotheses, never in-game evidence or identity
confirmation. Inputs are existing visually checked catalog source cards and
independently annotated gameplay crops. No input image or catalog is modified.
"""

from __future__ import annotations

import hashlib
import argparse
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
    load_verified_warehouse_gameplay_templates,
    verified_references,
)
from warehouse_placement_resolver import WarehousePlacementResolver  # noqa: E402
from warehouse_vision import WarehouseTemplateMatcher, WarehouseVisionConfig  # noqa: E402


VISUAL_PATH = ROOT / "assets/items/visual_catalog_v2.json"
OFFICIAL_PATH = ROOT / "assets/catalog_065.json"
FIT_GT_PATH = ROOT / "assets/items/video_ground_truth_reference_134436_match2_visible.json"
FIT_REPLAY_PATH = ROOT / "build/codex_other_video_20260912/134436-small-icon-replay/evaluated_units.json"
CHECK_GT_PATH = ROOT / "assets/items/video_ground_truth_reference_144037.json"
OUT_DIR = ROOT / "assets/items/derived_warehouse_icon_references_v1"
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
    extracted, _method = _extract_catalog_foreground(image)
    if extracted is None:
        return None
    foreground, _mask = extracted
    pad = max(2, round(min(image.shape[:2]) * 0.08))
    cropped = image[pad:-pad, pad:-pad]
    scale = 256 / max(cropped.shape[:2])
    resized_w = max(1, round(cropped.shape[1] * scale))
    resized_h = max(1, round(cropped.shape[0] * scale))
    return foreground.shape[1] / resized_w, foreground.shape[0] / resized_h


def _extract_catalog_foreground(image: np.ndarray):
    """Use the shared extractor, then a conservative closed-edge fallback.

    The fallback is limited to catalog body crops where the shared color mask
    found nothing. It requires a closed, interior, central object contour and
    does not inspect or tune against any gameplay check image.
    """
    extracted = WarehousePlacementResolver._extract_foreground(image)
    if extracted is not None:
        return extracted, "WarehousePlacementResolver._extract_foreground"
    if image is None or min(image.shape[:2]) < 16:
        return None, "NONE"
    # Keep the source crop's pixel grid. Resizing before closing can break thin
    # outlines and make a valid object contour disappear.
    body = image
    gray = cv2.GaussianBlur(cv2.cvtColor(body, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    edges = cv2.Canny(gray, 30, 80)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape
    candidates = []
    for contour in contours:
        area = float(cv2.contourArea(contour)) / max(1, edges.size)
        x, y, cw, ch = cv2.boundingRect(contour)
        cx, cy = (x + cw / 2) / w, (y + ch / 2) / h
        if (.02 < area < .85 and x > 1 and y > 1 and x + cw < w - 1 and y + ch < h - 1
                and .15 < cx < .85 and .15 < cy < .85):
            candidates.append((area, contour))
    if not candidates:
        return None, "NONE"
    contour = max(candidates, key=lambda row: row[0])[1]
    mask = np.zeros_like(edges)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    if not .02 < float(mask.mean()) / 255 < .85:
        return None, "NONE"
    x, y, cw, ch = cv2.boundingRect(contour)
    return (body[y:y + ch, x:x + cw], mask[y:y + ch, x:x + cw]), "CATALOG_CLOSED_EDGE_FALLBACK"


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
    verified = load_verified_warehouse_gameplay_templates(root=ROOT)
    samples = [
        dict(reference["metadata"])
        for references in verified.values()
        for reference in references
    ]
    ids = {str(row["catalogId"]) for row in samples}
    return ids, samples


def fit_pairs(eligible: dict[str, dict[str, Any]], samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    prior_fit_group = "video_audit_20260908_134436_match2"
    supplemental_group = "video_audit_20260908_134043"
    for row in samples:
        catalog_id = str(row.get("catalogId") or "")
        width = int(row.get("widthCells") or 0)
        height = int(row.get("heightCells") or 0)
        source = eligible.get(catalog_id)
        selected_prior_pair = (
            row.get("groupId") == prior_fit_group
            and (catalog_id, width, height) in auto_confirmed
        )
        independently_checked_supplement = row.get("groupId") == supplemental_group
        if (
            source is None
            or catalog_id in seen
            or not (selected_prior_pair or independently_checked_supplement)
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
            "groundTruthPath": row["groundTruthPath"],
            "groupId": row["groupId"],
            "referenceId": row.get("referenceId"),
            "pairSelection": "retained prior confirmed fit subset" if selected_prior_pair else "new independently labelled match; one pair per catalog ID",
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
    visual = source.get("visual") or {}
    source_path = ROOT / str(visual.get("sourcePath") or "")
    if (not source_path.is_file()
            or sha256(source_path) != str(visual.get("sourceSha256") or "")):
        return None
    source_image = read_image(source_path)
    bbox = visual.get("cardBbox")
    if source_image is None or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        card_x, card_y, card_width, card_height = (int(value) for value in bbox)
    except (TypeError, ValueError):
        return None
    if (card_x < 0 or card_y < 0 or card_width <= 0 or card_height <= 0
            or card_x + card_width > source_image.shape[1]
            or card_y + card_height > source_image.shape[0]):
        return None
    source_card = source_image[card_y:card_y + card_height, card_x:card_x + card_width]
    if source_card.size == 0:
        return None
    body = _catalog_reference_body(source_card)
    extracted, extraction_method = _extract_catalog_foreground(body)
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
        "cropMethod": "verified_catalog_screenshot_card_bbox_then_reference_body",
        "sourceCardBbox": [card_x, card_y, card_width, card_height],
        "cropFractions": BODY_CROP_FRACTIONS,
        "foregroundMethod": extraction_method,
        "foregroundFallback": "source-resolution Canny 30/80; 5x5 close x2; largest closed contour within 2%-85% area and centered 15%-85% of catalog body; used only if shared extractor fails",
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
    direct_score, direct_source = matcher.score_direct_reference(roi, candidate)
    derived_score = matcher._template_match_score(roi, derived) if derived is not None else None
    if derived_score is None:
        return direct_score, "DIRECT" if direct_source != "NONE" else "NONE"
    if derived_score > direct_score:
        return derived_score, "DERIVED"
    return direct_score, "DIRECT" if direct_source != "NONE" else "NONE"


def evaluate_historical_transfer(
    eligible: dict[str, dict[str, Any]],
    derived: dict[str, np.ndarray],
    fit_pairs_used: list[dict[str, Any]],
) -> dict[str, Any]:
    check_data = read_json(CHECK_GT_PATH)
    matcher = WarehouseTemplateMatcher()
    config = WarehouseVisionConfig()

    counts = {
        "candidateEligible": 0,
        "truthNotInOfficialCandidateSet": 0,
        "directTopByOrderCorrect": 0,
        "directTopHasPositiveVisualScore": 0,
        "directPositiveVisualTopCorrect": 0,
        "directUniqueVisualWinnerCorrect": 0,
        "directTopScoreTies": 0,
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
            direct_score, direct_kind = score_one(matcher, roi, candidate, None)
            combined_score, combined_kind = score_one(matcher, roi, candidate, derived.get(cid))
            direct_ranked.append((direct_score, index, cid, direct_kind))
            combined_ranked.append((combined_score, index, cid, combined_kind))
        direct_ranked.sort(key=lambda row: (-row[0], row[1]))
        combined_ranked.sort(key=lambda row: (-row[0], row[1]))
        direct_top = direct_ranked[0] if direct_ranked else (0.0, 0, "", "NONE")
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
        if direct_top[0] == direct_second:
            counts["directTopScoreTies"] += 1
        if direct_top[2] == catalog_id:
            counts["directTopByOrderCorrect"] += 1
        if direct_top[0] > 0:
            counts["directTopHasPositiveVisualScore"] += 1
            if direct_top[2] == catalog_id:
                counts["directPositiveVisualTopCorrect"] += 1
            if direct_top[2] == catalog_id and direct_top[0] > direct_second:
                counts["directUniqueVisualWinnerCorrect"] += 1
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
        # Derived refs remain barred from exact identity; trusted direct refs
        # use the existing confidence and margin gate.
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
            "directReferenceKind": direct_top[3],
            "combinedTopCandidate": combined_top[2] or None,
            "combinedTopReferenceKind": combined_top[3],
            "combinedScore": round(combined_top[0], 4),
            "combinedThresholdWouldPassButStillUnverified": bool(not direct_confirmed and combined_confirmed and combined_top[3] == "DERIVED"),
        })
    exclusive = {
        "correctDirectConfirmed": counts["combinedCorrectConfirmations"],
        "correctDerivedCandidateBlocked": counts["derivedThresholdCorrectBlocked"],
        "incorrectConfirmed": counts["combinedWrongConfirmations"] + counts["derivedThresholdWrongBlocked"],
        "ordinaryUnresolved": counts["combinedUnresolved"],
        "eligibleTotal": counts["candidateEligible"],
    }
    if sum(exclusive[key] for key in (
        "correctDirectConfirmed", "correctDerivedCandidateBlocked",
        "incorrectConfirmed", "ordinaryUnresolved",
    )) != exclusive["eligibleTotal"]:
        raise ValueError(f"historical identity outcomes do not close: {exclusive}")
    return {
        "group": CHECK_GT_PATH.relative_to(ROOT).as_posix(),
        "groupUse": "historical cross-match check; previously used development material, not fresh unseen acceptance",
        "fitReferenceIds": sorted(str(row.get("referenceId") or "") for row in fit_pairs_used),
        "trainingGroups": sorted({str(row.get("groupId") or "") for row in fit_pairs_used}),
        "counts": counts,
        "exclusiveIdentityOutcomes": exclusive,
        "rows": rows,
        "rankingInterpretation": "Combined top-candidate ranking is correct for 19/22 items, but this is not identity accuracy. The mutually exclusive combined outcomes are 3 direct correct confirmations, 1 correct derived candidate that remains blocked from confirmation, 0 incorrect confirmations, and 18 ordinary unresolved. The historical 7/22 direct baseline was a deterministic order tie with zero positive scores and is not a valid visual baseline. The single raw top-candidate regression is ref_144037_29: its direct top score is tied at zero, so the order change is not a measured visual regression; the combined top remains incorrect.",
        "productionExactGate": "DERIVED_UNVERIFIED never upgrades to EXACT_IDENTIFIED; only trusted direct catalog or independently labelled gameplay references may pass the existing strict gate",
    }


def main(output_dir: Path = OUT_DIR) -> None:
    eligible, exclusions = verified_official_sources()
    gameplay_ids, gameplay_sources = gameplay_samples()
    pairs = fit_pairs(eligible, gameplay_sources)
    pooled, shape_models = fit_occupancy(pairs)
    missing_ids = sorted(set(eligible) - gameplay_ids)

    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(ROOT.resolve()):
        raise ValueError("derived output must remain inside the repository; use build/ for diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    generation_failures = []
    for catalog_id in missing_ids:
        source = eligible[catalog_id]
        width, height = int(source["visual"]["width"]), int(source["visual"]["height"])
        occupancy = shape_models.get((width, height), pooled)
        built = build_reference(catalog_id, source, occupancy)
        if built is None:
            generation_failures.append({"catalogId": catalog_id, "reason": "shared foreground extractor and closed-edge fallback found no bounded foreground"})
            continue
        image, transform = built
        image_name = f"{catalog_id}.png"
        image_path = output_dir / image_name
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
                "generationInput": "verified sourcePath + cardBbox",
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

    derived_images = {
        str(row["catalogId"]): read_image(output_dir / f"{row['catalogId']}.png")
        for row in records
    }
    history_check = evaluate_historical_transfer(eligible, derived_images, pairs)
    manifest = {
        "schemaVersion": "derived-warehouse-icon-references.v1",
        "status": "DERIVED_UNVERIFIED",
        "scope": "Predicted warehouse appearance from verified catalog sources and hash-checked, independently labelled cross-match training crops; never raw gameplay evidence, never self-confirming identity, never solver-eligible by itself.",
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
            "supplementalPath": "assets/items/video_ground_truth_reference_134043_visible.json",
            "priorOutcome": "Retains the previous 7 independently labelled fit pairs and adds one eligible, hash-verified pair per distinct catalog ID from the separate 134043 development match. Neither match is unseen acceptance material.",
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
            "verifiedGameplayCropCount": len(gameplay_sources),
            "verifiedGameplayIdsWithVisualCatalogSource": len(gameplay_ids & set(eligible)),
            "verifiedGameplayIdsWithoutVisualCatalogSource": len(gameplay_ids - set(eligible)),
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
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    referenced_images = {Path(row["imagePath"]).name for row in records}
    if output_dir == OUT_DIR.resolve():
        for stale_image in output_dir.glob("image*.png"):
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
        "manifest": manifest_path.relative_to(ROOT).as_posix(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUT_DIR)
    main(parser.parse_args().output_dir)
