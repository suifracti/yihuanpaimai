#!/usr/bin/env python3
"""Validate Benchmark v1 source-relative physical item geometry contracts.

This validator is intentionally independent from the production vision pipeline.
It uses only the Python standard library and supports one coordinate space in v1:
stored-source pixels (`source_pixel`). It does not infer DPI, window offsets, or
resize transforms.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


CONTRACT_VERSION = "geometry-contract-v1"
COORDINATE_SPACE = "source_pixel"
CANONICAL_ITEM_ID = re.compile(r"^image[0-9]+-[0-9]+-[0-9]+$")
PHYSICAL_INSTANCE_ID = re.compile(r"^inst-[A-Za-z0-9][A-Za-z0-9._:-]*$")
SEMANTIC_ID_PREFIXES = (
    "red_",
    "gold_",
    "purple_",
    "blue_",
    "green_",
    "white_",
    "gray_",
    "grey_",
)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    location: str
    message: str


@dataclass
class ValidationResult:
    contract_path: str
    valid: bool
    pack_eligible: bool
    source_count: int
    instance_count: int
    queue_slot_count: int
    issues: List[ValidationIssue]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [asdict(issue) for issue in self.issues]
        return payload


def _issue(code: str, location: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, location=location, message=message)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _object_shape(
    value: Any,
    *,
    required: Iterable[str],
    allowed: Iterable[str],
    location: str,
) -> List[ValidationIssue]:
    if not isinstance(value, dict):
        return [_issue("E_SCHEMA_TYPE", location, "must be an object")]
    issues: List[ValidationIssue] = []
    required_set = set(required)
    allowed_set = set(allowed)
    for key in sorted(required_set - set(value)):
        issues.append(_issue("E_SCHEMA_REQUIRED", f"{location}.{key}", "required field is missing"))
    for key in sorted(set(value) - allowed_set):
        issues.append(_issue("E_SCHEMA_ADDITIONAL_PROPERTY", f"{location}.{key}", "field is not allowed by contract v1"))
    return issues


def _resolve_repo_path(repo_root: Path, raw_path: Any, location: str) -> Tuple[Optional[Path], List[ValidationIssue]]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, [_issue("E_SCHEMA_TYPE", location, "must be a non-empty repository-relative path")]
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return None, [_issue("E_PATH_OUTSIDE_ROOT", location, "absolute paths are not allowed")]
    resolved = (repo_root / candidate).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError:
        return None, [_issue("E_PATH_OUTSIDE_ROOT", location, "path escapes repository root")]
    return resolved, []


def _read_png_size(path: Path) -> Tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("invalid PNG header")
    return struct.unpack(">II", header[16:24])


def _read_jpeg_size(path: Path) -> Tuple[int, int]:
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            raise ValueError("invalid JPEG SOI marker")
        while True:
            byte = handle.read(1)
            if not byte:
                break
            if byte != b"\xff":
                continue
            while byte == b"\xff":
                byte = handle.read(1)
            if not byte:
                break
            marker = byte[0]
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                continue
            raw_length = handle.read(2)
            if len(raw_length) != 2:
                break
            segment_length = struct.unpack(">H", raw_length)[0]
            if segment_length < 2:
                raise ValueError("invalid JPEG segment length")
            if marker in sof_markers:
                payload = handle.read(5)
                if len(payload) != 5:
                    break
                height, width = struct.unpack(">HH", payload[1:5])
                return width, height
            handle.seek(segment_length - 2, 1)
    raise ValueError("JPEG dimensions not found")


def read_image_size(path: Path) -> Tuple[int, int]:
    with path.open("rb") as handle:
        signature = handle.read(8)
    if signature == b"\x89PNG\r\n\x1a\n":
        return _read_png_size(path)
    if signature[:2] == b"\xff\xd8":
        return _read_jpeg_size(path)
    raise ValueError("only PNG and JPEG images are supported by geometry contract v1")


def _valid_bbox(value: Any, location: str) -> Tuple[Optional[Tuple[int, int, int, int]], List[ValidationIssue]]:
    if not isinstance(value, list) or len(value) != 4 or not all(_is_int(item) for item in value):
        return None, [_issue("E_BBOX_FORMAT", location, "must be [x1, y1, x2, y2] with four integers")]
    x1, y1, x2, y2 = value
    if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
        return None, [_issue("E_BBOX_FORMAT", location, "requires x1>=0, y1>=0, x2>x1, and y2>y1")]
    return (x1, y1, x2, y2), []


def _validate_top_level(data: Any) -> List[ValidationIssue]:
    required = {"contractVersion", "pathBase", "sources", "instances", "queueSlots"}
    allowed = required | {"description"}
    issues = _object_shape(data, required=required, allowed=allowed, location="$" )
    if issues:
        return issues
    if data.get("contractVersion") != CONTRACT_VERSION:
        issues.append(_issue("E_CONTRACT_VERSION", "$.contractVersion", f"must equal {CONTRACT_VERSION!r}"))
    if data.get("pathBase") != "repository_root":
        issues.append(_issue("E_PATH_BASE", "$.pathBase", "must equal 'repository_root'"))
    for name in ("sources", "instances", "queueSlots"):
        if not isinstance(data.get(name), list):
            issues.append(_issue("E_SCHEMA_TYPE", f"$.{name}", "must be an array"))
    if isinstance(data.get("sources"), list) and not data["sources"]:
        issues.append(_issue("E_SOURCE_REQUIRED", "$.sources", "at least one source is required"))
    return issues


def _validate_sources(
    sources: Sequence[Any], repo_root: Path
) -> Tuple[Dict[str, Dict[str, Any]], List[ValidationIssue]]:
    required = {
        "sourceId",
        "sourcePath",
        "width",
        "height",
        "sceneType",
        "inventoryEligible",
        "inventoryRoi",
        "coordinateSpace",
    }
    source_map: Dict[str, Dict[str, Any]] = {}
    issues: List[ValidationIssue] = []
    for index, source in enumerate(sources):
        location = f"$.sources[{index}]"
        shape_issues = _object_shape(source, required=required, allowed=required, location=location)
        if shape_issues:
            issues.extend(shape_issues)
            continue

        source_id = source.get("sourceId")
        if not isinstance(source_id, str) or not source_id:
            issues.append(_issue("E_SOURCE_ID", f"{location}.sourceId", "must be a non-empty string"))
            continue
        if source_id in source_map:
            issues.append(_issue("E_SOURCE_ID_DUPLICATE", f"{location}.sourceId", f"duplicate sourceId {source_id!r}"))
            continue
        source_map[source_id] = source

        source_path, path_issues = _resolve_repo_path(repo_root, source.get("sourcePath"), f"{location}.sourcePath")
        issues.extend(path_issues)
        if source_path is None:
            continue
        if not source_path.is_file():
            issues.append(_issue("E_SOURCE_FILE_MISSING", f"{location}.sourcePath", f"source file does not exist: {source.get('sourcePath')!r}"))
            continue

        width = source.get("width")
        height = source.get("height")
        if not _is_int(width) or width <= 0 or not _is_int(height) or height <= 0:
            issues.append(_issue("E_SOURCE_DIMENSIONS", location, "width and height must be positive integers"))
            continue
        try:
            actual_width, actual_height = read_image_size(source_path)
        except (OSError, ValueError) as exc:
            issues.append(_issue("E_SOURCE_IMAGE_READ", f"{location}.sourcePath", str(exc)))
            continue
        if (actual_width, actual_height) != (width, height):
            issues.append(
                _issue(
                    "E_SOURCE_DIMENSIONS_MISMATCH",
                    location,
                    f"declared {width}x{height}, stored image is {actual_width}x{actual_height}",
                )
            )
            continue

        if source.get("inventoryEligible") is not True:
            issues.append(
                _issue(
                    "E_SOURCE_NOT_INVENTORY_ELIGIBLE",
                    f"{location}.inventoryEligible",
                    "source must be explicitly inventory-eligible before bbox or crop validation",
                )
            )
            continue
        scene_type = source.get("sceneType")
        if not isinstance(scene_type, str) or not scene_type:
            issues.append(_issue("E_SCENE_TYPE", f"{location}.sceneType", "must be a non-empty string"))
            continue
        if source.get("coordinateSpace") != COORDINATE_SPACE:
            issues.append(
                _issue(
                    "E_SOURCE_COORDINATE_SPACE",
                    f"{location}.coordinateSpace",
                    "v1 accepts only stored-source pixel coordinates ('source_pixel'); no transform is inferred",
                )
            )
            continue

        roi = source.get("inventoryRoi")
        roi_required = {"x", "y", "width", "height", "coordinateSpace"}
        roi_issues = _object_shape(roi, required=roi_required, allowed=roi_required, location=f"{location}.inventoryRoi")
        if roi_issues:
            issues.extend(roi_issues)
            continue
        if roi.get("coordinateSpace") != COORDINATE_SPACE:
            issues.append(
                _issue(
                    "E_ROI_COORDINATE_SPACE",
                    f"{location}.inventoryRoi.coordinateSpace",
                    "inventory ROI must already be expressed in stored-source pixels; no viewport/window transform is inferred",
                )
            )
            continue
        x, y, roi_width, roi_height = (roi.get("x"), roi.get("y"), roi.get("width"), roi.get("height"))
        if not all(_is_int(item) for item in (x, y, roi_width, roi_height)) or x < 0 or y < 0 or roi_width <= 0 or roi_height <= 0:
            issues.append(_issue("E_ROI_FORMAT", f"{location}.inventoryRoi", "x/y must be non-negative integers and width/height positive integers"))
            continue
        if x + roi_width > width or y + roi_height > height:
            issues.append(_issue("E_ROI_OUT_OF_BOUNDS", f"{location}.inventoryRoi", "inventory ROI exceeds stored source bounds"))
    return source_map, issues


def _validate_content_verification(value: Any, location: str) -> List[ValidationIssue]:
    required = {"contentVerified", "reviewStatus", "evidenceType", "scope", "note"}
    issues = _object_shape(value, required=required, allowed=required, location=location)
    if issues:
        return issues
    verified = value.get("contentVerified")
    status = value.get("reviewStatus")
    evidence = value.get("evidenceType")
    if not isinstance(verified, bool):
        issues.append(_issue("E_CONTENT_VERIFICATION_FORMAT", f"{location}.contentVerified", "must be boolean"))
    if status not in {"pending_review", "reviewed_consistent", "rejected"}:
        issues.append(_issue("E_CONTENT_VERIFICATION_FORMAT", f"{location}.reviewStatus", "unsupported review status"))
    if evidence not in {"none", "manual_review", "independent_evidence"}:
        issues.append(_issue("E_CONTENT_VERIFICATION_FORMAT", f"{location}.evidenceType", "unsupported evidence type"))
    if value.get("scope") != "crop_instance_binding_only":
        issues.append(_issue("E_CONTENT_VERIFICATION_SCOPE", f"{location}.scope", "must be 'crop_instance_binding_only'; it does not verify item identity"))
    if not isinstance(value.get("note"), str):
        issues.append(_issue("E_CONTENT_VERIFICATION_FORMAT", f"{location}.note", "must be a string"))
    if verified is True and (status != "reviewed_consistent" or evidence == "none"):
        issues.append(_issue("E_CONTENT_VERIFICATION_INCONSISTENT", location, "verified content requires reviewed_consistent status and non-none evidence"))
    if verified is False and status == "reviewed_consistent":
        issues.append(_issue("E_CONTENT_VERIFICATION_INCONSISTENT", location, "reviewed_consistent requires contentVerified=true"))
    return issues


def _validate_instances(
    instances: Sequence[Any], source_map: Dict[str, Dict[str, Any]]
) -> Tuple[Dict[str, Dict[str, Any]], List[ValidationIssue]]:
    required = {
        "instanceId",
        "sourceId",
        "bbox",
        "bboxCoordinateSpace",
        "footprint",
        "canonicalItemId",
        "observationLabel",
        "contentVerification",
    }
    instance_map: Dict[str, Dict[str, Any]] = {}
    issues: List[ValidationIssue] = []
    for index, instance in enumerate(instances):
        location = f"$.instances[{index}]"
        shape_issues = _object_shape(instance, required=required, allowed=required, location=location)
        if shape_issues:
            issues.extend(shape_issues)
            continue
        instance_id = instance.get("instanceId")
        if not isinstance(instance_id, str) or not PHYSICAL_INSTANCE_ID.fullmatch(instance_id):
            issues.append(_issue("E_INSTANCE_ID", f"{location}.instanceId", "must use an opaque physical ID beginning with 'inst-'"))
            continue
        if instance_id.lower().startswith(SEMANTIC_ID_PREFIXES):
            issues.append(_issue("E_INSTANCE_ID_SEMANTIC", f"{location}.instanceId", "semantic/model labels cannot identify physical instances"))
            continue
        if instance_id in instance_map:
            issues.append(_issue("E_INSTANCE_ID_DUPLICATE", f"{location}.instanceId", f"duplicate instanceId {instance_id!r}"))
            continue
        instance_map[instance_id] = instance

        source_id = instance.get("sourceId")
        source = source_map.get(source_id)
        if source is None:
            issues.append(_issue("E_INSTANCE_SOURCE_UNKNOWN", f"{location}.sourceId", f"unknown sourceId {source_id!r}"))
            continue
        if instance.get("bboxCoordinateSpace") != COORDINATE_SPACE:
            issues.append(_issue("E_BBOX_COORDINATE_SPACE", f"{location}.bboxCoordinateSpace", "bbox must be in stored-source pixels; no transform is inferred"))
            continue
        bbox, bbox_issues = _valid_bbox(instance.get("bbox"), f"{location}.bbox")
        issues.extend(bbox_issues)
        if bbox is None:
            continue
        x1, y1, x2, y2 = bbox
        if x2 > source["width"] or y2 > source["height"]:
            issues.append(_issue("E_BBOX_OUT_OF_SOURCE_BOUNDS", f"{location}.bbox", "bbox exceeds stored source bounds"))
            continue
        roi = source["inventoryRoi"]
        rx1, ry1 = roi["x"], roi["y"]
        rx2, ry2 = rx1 + roi["width"], ry1 + roi["height"]
        if not (rx1 <= x1 < x2 <= rx2 and ry1 <= y1 < y2 <= ry2):
            issues.append(_issue("E_BBOX_OUTSIDE_INVENTORY_ROI", f"{location}.bbox", "bbox must be fully contained by the source inventory ROI"))

        footprint = instance.get("footprint")
        if footprint is not None:
            fp_required = {"widthCells", "heightCells"}
            fp_issues = _object_shape(footprint, required=fp_required, allowed=fp_required, location=f"{location}.footprint")
            issues.extend(fp_issues)
            if not fp_issues:
                if not _is_int(footprint.get("widthCells")) or footprint["widthCells"] <= 0 or not _is_int(footprint.get("heightCells")) or footprint["heightCells"] <= 0:
                    issues.append(_issue("E_FOOTPRINT_FORMAT", f"{location}.footprint", "cell dimensions must be positive integers"))

        canonical_id = instance.get("canonicalItemId")
        if canonical_id is not None and (not isinstance(canonical_id, str) or not CANONICAL_ITEM_ID.fullmatch(canonical_id)):
            issues.append(_issue("E_CANONICAL_ITEM_ID", f"{location}.canonicalItemId", "must be null or a canonical imageN-R-C catalog ID"))
        observation = instance.get("observationLabel")
        if observation is not None and (not isinstance(observation, str) or not observation):
            issues.append(_issue("E_OBSERVATION_LABEL", f"{location}.observationLabel", "must be null or a non-empty description"))
        issues.extend(_validate_content_verification(instance.get("contentVerification"), f"{location}.contentVerification"))
    return instance_map, issues


def _validate_queue_slots(
    queue_slots: Sequence[Any],
    instance_map: Dict[str, Dict[str, Any]],
    source_map: Dict[str, Dict[str, Any]],
    repo_root: Path,
) -> List[ValidationIssue]:
    required = {"queueId", "instanceId", "cropPath"}
    allowed = required | {"legacyLocalOrdinal"}
    issues: List[ValidationIssue] = []
    queue_ids = set()
    instance_to_slots: Dict[str, List[str]] = {}
    structurally_valid_slots: List[Tuple[int, Dict[str, Any], Dict[str, Any]]] = []
    for index, slot in enumerate(queue_slots):
        location = f"$.queueSlots[{index}]"
        shape_issues = _object_shape(slot, required=required, allowed=allowed, location=location)
        if shape_issues:
            issues.extend(shape_issues)
            continue
        queue_id = slot.get("queueId")
        if not isinstance(queue_id, str) or not queue_id:
            issues.append(_issue("E_QUEUE_ID", f"{location}.queueId", "must be a non-empty string"))
            continue
        if queue_id in queue_ids:
            issues.append(_issue("E_QUEUE_ID_DUPLICATE", f"{location}.queueId", f"duplicate queueId {queue_id!r}"))
            continue
        queue_ids.add(queue_id)
        instance_id = slot.get("instanceId")
        if not isinstance(instance_id, str) or not instance_id:
            issues.append(_issue("E_QUEUE_INSTANCE_REQUIRED", f"{location}.instanceId", "queue slot must reference an explicit physical instanceId"))
            continue
        instance = instance_map.get(instance_id)
        if instance is None:
            issues.append(_issue("E_QUEUE_INSTANCE_UNKNOWN", f"{location}.instanceId", f"unknown instanceId {instance_id!r}"))
            continue
        instance_to_slots.setdefault(instance_id, []).append(queue_id)
        structurally_valid_slots.append((index, slot, instance))

    for instance_id, queue_ids_for_instance in sorted(instance_to_slots.items()):
        if len(queue_ids_for_instance) > 1:
            issues.append(
                _issue(
                    "E_INSTANCE_MULTIPLE_QUEUE_SLOTS",
                    "$.queueSlots",
                    f"physical instance {instance_id!r} is referenced by multiple benchmark slots: {', '.join(queue_ids_for_instance)}",
                )
            )
    if issues:
        return issues

    for index, slot, instance in structurally_valid_slots:
        location = f"$.queueSlots[{index}]"
        verification = instance["contentVerification"]
        if verification.get("contentVerified") is not True or verification.get("reviewStatus") != "reviewed_consistent":
            issues.append(
                _issue(
                    "E_CONTENT_NOT_VERIFIED",
                    f"{location}.instanceId",
                    "pack admission requires reviewed crop-to-instance binding; this is not item-identity truth",
                )
            )
            continue
        crop_path, path_issues = _resolve_repo_path(repo_root, slot.get("cropPath"), f"{location}.cropPath")
        issues.extend(path_issues)
        if crop_path is None:
            continue
        if not crop_path.is_file():
            issues.append(_issue("E_CROP_FILE_MISSING", f"{location}.cropPath", f"crop file does not exist: {slot.get('cropPath')!r}"))
            continue
        try:
            crop_width, crop_height = read_image_size(crop_path)
        except (OSError, ValueError) as exc:
            issues.append(_issue("E_CROP_IMAGE_READ", f"{location}.cropPath", str(exc)))
            continue
        x1, y1, x2, y2 = instance["bbox"]
        expected = (x2 - x1, y2 - y1)
        if (crop_width, crop_height) != expected:
            issues.append(
                _issue(
                    "E_CROP_DIMENSIONS_MISMATCH",
                    f"{location}.cropPath",
                    f"crop is {crop_width}x{crop_height}; instance bbox requires {expected[0]}x{expected[1]}",
                )
            )
    return issues


def validate_contract_data(data: Any, *, contract_path: Path, repo_root: Path) -> ValidationResult:
    top_issues = _validate_top_level(data)
    if top_issues:
        return ValidationResult(str(contract_path), False, False, 0, 0, 0, top_issues)

    sources = data["sources"]
    instances = data["instances"]
    queue_slots = data["queueSlots"]
    source_map, source_issues = _validate_sources(sources, repo_root)
    if source_issues:
        return ValidationResult(str(contract_path), False, False, len(sources), len(instances), len(queue_slots), source_issues)

    instance_map, instance_issues = _validate_instances(instances, source_map)
    if instance_issues:
        return ValidationResult(str(contract_path), False, False, len(sources), len(instances), len(queue_slots), instance_issues)

    queue_issues = _validate_queue_slots(queue_slots, instance_map, source_map, repo_root)
    valid = not queue_issues
    return ValidationResult(str(contract_path), valid, valid, len(sources), len(instances), len(queue_slots), queue_issues)


def validate_contract_file(contract_path: Path, *, repo_root: Optional[Path] = None) -> ValidationResult:
    contract_path = contract_path.resolve()
    repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    try:
        with contract_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return ValidationResult(
            str(contract_path),
            False,
            False,
            0,
            0,
            0,
            [_issue("E_CONTRACT_READ", "$", str(exc))],
        )
    return validate_contract_data(data, contract_path=contract_path, repo_root=repo_root)


def _print_human(result: ValidationResult) -> None:
    status = "PASS" if result.valid else "FAIL"
    print(
        f"[{status}] {result.contract_path} "
        f"(sources={result.source_count}, instances={result.instance_count}, queueSlots={result.queue_slot_count})"
    )
    for issue in result.issues:
        print(f"  {issue.code} {issue.location}: {issue.message}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contracts", nargs="+", type=Path, help="contract JSON file(s) to validate")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root used to resolve source/crop paths",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = parser.parse_args(argv)

    results = [validate_contract_file(path, repo_root=args.repo_root) for path in args.contracts]
    if args.json:
        print(json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2))
    else:
        for result in results:
            _print_human(result)
    return 0 if all(result.valid for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
