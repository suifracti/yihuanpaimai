#!/usr/bin/env python3
"""Validate reviewed splits of mixed production proposals.

This layer owns only geometry review. It cannot create benchmark instances,
semantic identity, quality, truth, or queue records.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SPLIT_VERSION = "reviewed-proposal-split-v1"
REGISTRY_VERSION = "proposal-split-registry-v1"
COORDINATE_SPACE = "source_pixel"
REVIEW_STATUSES = {"pending_review", "reviewed_consistent", "rejected"}
FORBIDDEN_SPLIT_FIELDS = {
    "instanceId", "benchmarkInstanceId", "canonicalItemId", "semanticIdentity",
    "quality", "verifiedIdentity", "verifiedTruth", "truthStatus", "queueId",
}


class SplitError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_proposal_boundary(repo_root: Path):
    path = repo_root / "experiments" / "vision_benchmark_v2" / "proposal_boundary.py"
    spec = importlib.util.spec_from_file_location("benchmark_v2_proposal_boundary_for_split", path)
    if spec is None or spec.loader is None:
        raise SplitError("E_PROPOSAL_BOUNDARY_LOAD", f"cannot load proposal boundary: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SplitError("E_SPLIT_READ", str(exc)) from exc
    if not isinstance(payload, dict):
        raise SplitError("E_SPLIT_SCHEMA", "top-level value must be an object")
    return payload


def _resolve_repo_path(repo_root: Path, raw_path: Any, field: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise SplitError("E_SPLIT_PATH", f"{field} must be a repository-relative path")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise SplitError("E_SPLIT_PATH", f"{field} cannot be absolute")
    resolved = (repo_root / candidate).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise SplitError("E_SPLIT_PATH", f"{field} escapes repository root") from exc
    return resolved


def _require_exact_keys(value: Any, required: Iterable[str], location: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise SplitError("E_SPLIT_SCHEMA", f"{location} must be an object")
    expected = set(required)
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        raise SplitError("E_SPLIT_SCHEMA", f"{location} missing fields: {', '.join(missing)}")
    if extra:
        raise SplitError("E_SPLIT_SCHEMA", f"{location} has unsupported fields: {', '.join(extra)}")
    return value


def _find_forbidden(value: Any, location: str = "$") -> Optional[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_SPLIT_FIELDS:
                return f"{location}.{key}"
            found = _find_forbidden(nested, f"{location}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _find_forbidden(nested, f"{location}[{index}]")
            if found:
                return found
    return None


def _bbox(value: Any, location: str) -> List[int]:
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(n, int) and not isinstance(n, bool) for n in value):
        raise SplitError("E_SPLIT_BBOX", f"{location} must be [x1,y1,x2,y2] integers")
    x1, y1, x2, y2 = value
    if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
        raise SplitError("E_SPLIT_BBOX", f"{location} has invalid extent")
    return list(value)


def _cells(value: Any, location: str, *, allow_empty: bool) -> List[Tuple[int, int]]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise SplitError("E_SPLIT_CELLS", f"{location} must be {'an' if allow_empty else 'a non-empty'} array")
    cells: List[Tuple[int, int]] = []
    for index, cell in enumerate(value):
        if not isinstance(cell, list) or len(cell) != 2 or not all(isinstance(n, int) and n >= 0 for n in cell):
            raise SplitError("E_SPLIT_CELLS", f"{location}[{index}] must be [row,col] non-negative integers")
        cells.append((cell[0], cell[1]))
    if len(set(cells)) != len(cells):
        raise SplitError("E_SPLIT_CELLS", f"{location} repeats a source cell")
    return cells


def _intersects(first: Sequence[int], second: Sequence[int]) -> bool:
    return max(first[0], second[0]) < min(first[2], second[2]) and max(first[1], second[1]) < min(first[3], second[3])


def _inside(inner: Sequence[int], outer: Sequence[int]) -> bool:
    return outer[0] <= inner[0] < inner[2] <= outer[2] and outer[1] <= inner[1] < inner[3] <= outer[3]


def _area(bbox: Sequence[int]) -> int:
    return (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])


def load_and_validate_split(
    split_path: Path,
    *,
    repo_root: Path,
    require_admission_review: bool = False,
) -> Dict[str, Any]:
    split_path = split_path.resolve()
    payload = _read_json(split_path)
    forbidden = _find_forbidden(payload)
    if forbidden:
        raise SplitError("E_SPLIT_AUTHORITY", f"identity/truth authority is forbidden at {forbidden}")
    split = _require_exact_keys(
        payload,
        {"splitVersion", "sourceId", "proposalArtifactPath", "proposalArtifactHash", "proposalId", "reviewStatus", "resolutionMethod", "children", "discardedRegions", "reviewEvidence"},
        "$",
    )
    if split["splitVersion"] != SPLIT_VERSION:
        raise SplitError("E_SPLIT_VERSION", f"expected {SPLIT_VERSION}")
    if split["resolutionMethod"] != "reviewed_split":
        raise SplitError("E_SPLIT_RESOLUTION_METHOD", "resolutionMethod must be reviewed_split")
    if split["reviewStatus"] not in REVIEW_STATUSES:
        raise SplitError("E_SPLIT_REVIEW_STATUS", f"unsupported reviewStatus {split['reviewStatus']!r}")
    if require_admission_review and split["reviewStatus"] != "reviewed_consistent":
        raise SplitError("E_SPLIT_NOT_REVIEWED", f"split cannot be admitted with reviewStatus={split['reviewStatus']}")

    proposal_path = _resolve_repo_path(repo_root, split["proposalArtifactPath"], "proposalArtifactPath")
    if not proposal_path.is_file():
        raise SplitError("E_SPLIT_PROPOSAL_ARTIFACT_MISSING", f"proposal artifact does not exist: {proposal_path}")
    actual_hash = sha256_file(proposal_path)
    if actual_hash != split["proposalArtifactHash"]:
        raise SplitError("E_SPLIT_ARTIFACT_HASH", f"declared {split['proposalArtifactHash']}, got {actual_hash}")
    proposal_boundary = _load_proposal_boundary(repo_root)
    try:
        artifact = proposal_boundary.load_and_validate_artifact(proposal_path, repo_root=repo_root)
    except proposal_boundary.ProposalError as exc:
        raise SplitError(exc.code, exc.message) from exc
    expected_source_id = f"src-{artifact['source']['sha256'][:20]}"
    if split["sourceId"] != expected_source_id:
        raise SplitError("E_SPLIT_SOURCE", "sourceId does not match proposal artifact source provenance")
    proposal = next((item for item in artifact["itemProposals"] if item["proposalId"] == split["proposalId"]), None)
    if proposal is None:
        raise SplitError("E_SPLIT_PROPOSAL_UNKNOWN", f"unknown proposalId {split['proposalId']}")
    if proposal["coordinateSpace"] != COORDINATE_SPACE:
        raise SplitError("E_SPLIT_COORDINATE_SPACE", "source proposal must use source_pixel")

    original_bbox = proposal["bbox"]
    original_cells = {tuple(cell) for cell in proposal["occupiedCells"]}
    children = split["children"]
    if not isinstance(children, list) or len(children) < 2:
        raise SplitError("E_SPLIT_CHILDREN", "reviewed split requires at least two children")
    normalized_children = []
    child_ids = set()
    authoritative_cells: Dict[Tuple[int, int], str] = {}
    coverage_boxes: List[Tuple[str, List[int]]] = []
    required_child = {"childId", "sourcePixelBbox", "sourceCells", "bboxCoordinateSpace", "coverageRole"}
    for index, raw_child in enumerate(children):
        location = f"$.children[{index}]"
        child = _require_exact_keys(raw_child, required_child, location)
        child_id = child["childId"]
        if not isinstance(child_id, str) or not child_id.startswith("split-child-"):
            raise SplitError("E_SPLIT_CHILD_ID", f"{location}.childId must begin with split-child-")
        if child_id in child_ids:
            raise SplitError("E_SPLIT_CHILD_ID_DUPLICATE", f"duplicate childId {child_id}")
        child_ids.add(child_id)
        if child["bboxCoordinateSpace"] != COORDINATE_SPACE:
            raise SplitError("E_SPLIT_COORDINATE_SPACE", f"{location} must use source_pixel")
        if child["coverageRole"] != "physical_parent_fragment":
            raise SplitError("E_SPLIT_COVERAGE_ROLE", f"unsupported coverageRole {child['coverageRole']!r}")
        bbox = _bbox(child["sourcePixelBbox"], f"{location}.sourcePixelBbox")
        if not _inside(bbox, original_bbox):
            raise SplitError("E_SPLIT_CHILD_BOUNDS", f"{child_id} bbox is outside the original proposal")
        cells = _cells(child["sourceCells"], f"{location}.sourceCells", allow_empty=False)
        for cell in cells:
            if cell not in original_cells:
                raise SplitError("E_SPLIT_CELL_UNKNOWN", f"{child_id} references cell {cell} outside the source proposal")
            previous = authoritative_cells.get(cell)
            if previous is not None:
                raise SplitError("E_SPLIT_CHILD_CELL_OVERLAP", f"cell {cell} belongs to both {previous} and {child_id}")
            authoritative_cells[cell] = child_id
        normalized = dict(child)
        normalized["sourceCells"] = [list(cell) for cell in sorted(cells)]
        normalized_children.append(normalized)
        coverage_boxes.append((child_id, bbox))

    discarded = split["discardedRegions"]
    if not isinstance(discarded, list):
        raise SplitError("E_SPLIT_DISCARDS", "discardedRegions must be an array")
    normalized_discards = []
    discard_ids = set()
    discarded_cells = set()
    required_discard = {"regionId", "sourcePixelBbox", "sourceCells", "bboxCoordinateSpace", "reason"}
    for index, raw_region in enumerate(discarded):
        location = f"$.discardedRegions[{index}]"
        region = _require_exact_keys(raw_region, required_discard, location)
        region_id = region["regionId"]
        if not isinstance(region_id, str) or not region_id.startswith("discard-"):
            raise SplitError("E_SPLIT_DISCARD_ID", f"{location}.regionId must begin with discard-")
        if region_id in discard_ids:
            raise SplitError("E_SPLIT_DISCARD_ID_DUPLICATE", f"duplicate regionId {region_id}")
        discard_ids.add(region_id)
        if region["bboxCoordinateSpace"] != COORDINATE_SPACE:
            raise SplitError("E_SPLIT_COORDINATE_SPACE", f"{location} must use source_pixel")
        bbox = _bbox(region["sourcePixelBbox"], f"{location}.sourcePixelBbox")
        if not _inside(bbox, original_bbox):
            raise SplitError("E_SPLIT_DISCARD_BOUNDS", f"{region_id} bbox is outside the original proposal")
        cells = _cells(region["sourceCells"], f"{location}.sourceCells", allow_empty=True)
        for cell in cells:
            if cell not in original_cells:
                raise SplitError("E_SPLIT_CELL_UNKNOWN", f"{region_id} references cell {cell} outside the source proposal")
            if cell in authoritative_cells:
                raise SplitError("E_SPLIT_DISCARD_CELL_CONFLICT", f"cell {cell} is both admitted and discarded")
            discarded_cells.add(cell)
        if not isinstance(region["reason"], str) or not region["reason"]:
            raise SplitError("E_SPLIT_DISCARD_REASON", f"{location}.reason must be non-empty")
        normalized = dict(region)
        normalized["sourceCells"] = [list(cell) for cell in sorted(cells)]
        normalized_discards.append(normalized)
        coverage_boxes.append((region_id, bbox))

    for index, (first_id, first_bbox) in enumerate(coverage_boxes):
        for second_id, second_bbox in coverage_boxes[index + 1:]:
            if _intersects(first_bbox, second_bbox):
                raise SplitError("E_SPLIT_PIXEL_OVERLAP", f"{first_id} and {second_id} overlap in source pixels")
    covered_area = sum(_area(bbox) for _, bbox in coverage_boxes)
    if covered_area != _area(original_bbox):
        raise SplitError("E_SPLIT_COVERAGE", "children plus discardedRegions must exactly cover the original proposal bbox")
    if set(authoritative_cells) | discarded_cells != original_cells:
        raise SplitError("E_SPLIT_CELL_COVERAGE", "every original occupied cell must be admitted or explicitly discarded")

    evidence = _require_exact_keys(
        split["reviewEvidence"],
        {"evidenceType", "sourceSnapshotPath", "reviewerRole", "note"},
        "$.reviewEvidence",
    )
    if evidence["evidenceType"] != "manual_source_review" or evidence["reviewerRole"] != "human_reviewer":
        raise SplitError("E_SPLIT_REVIEW_EVIDENCE", "split requires manual source review provenance")
    if not isinstance(evidence["note"], str) or not evidence["note"]:
        raise SplitError("E_SPLIT_REVIEW_EVIDENCE", "reviewEvidence.note must be non-empty")
    evidence_source = _resolve_repo_path(repo_root, evidence["sourceSnapshotPath"], "reviewEvidence.sourceSnapshotPath")
    proposal_source = _resolve_repo_path(repo_root, artifact["source"]["sourcePath"], "proposalArtifact.source.sourcePath")
    if evidence_source != proposal_source:
        raise SplitError("E_SPLIT_REVIEW_EVIDENCE", "review evidence must reference the exact proposal source snapshot")

    return {
        "split": split,
        "children": sorted(normalized_children, key=lambda child: child["childId"]),
        "discardedRegions": sorted(normalized_discards, key=lambda region: region["regionId"]),
        "proposalArtifact": artifact,
        "proposalArtifactPath": proposal_path,
        "proposal": proposal,
    }


def load_split_registry(registry_path: Path, *, repo_root: Path) -> Dict[str, Dict[str, Any]]:
    registry = _require_exact_keys(_read_json(registry_path), {"registryVersion", "splitReviews"}, "$")
    if registry["registryVersion"] != REGISTRY_VERSION:
        raise SplitError("E_SPLIT_REGISTRY_VERSION", f"expected {REGISTRY_VERSION}")
    entries = registry["splitReviews"]
    if not isinstance(entries, list):
        raise SplitError("E_SPLIT_REGISTRY_SCHEMA", "splitReviews must be an array")
    by_proposal: Dict[str, Dict[str, Any]] = {}
    for index, raw_entry in enumerate(entries):
        entry = _require_exact_keys(raw_entry, {"path", "sha256"}, f"$.splitReviews[{index}]")
        path = _resolve_repo_path(repo_root, entry["path"], f"$.splitReviews[{index}].path")
        if sha256_file(path) != entry["sha256"]:
            raise SplitError("E_SPLIT_REGISTRY_HASH", f"registered split hash mismatch: {entry['path']}")
        result = load_and_validate_split(path, repo_root=repo_root, require_admission_review=True)
        proposal_id = result["split"]["proposalId"]
        if proposal_id in by_proposal:
            raise SplitError("E_SPLIT_REGISTRY_DUPLICATE", f"multiple reviewed splits for {proposal_id}")
        by_proposal[proposal_id] = {"path": path, "sha256": entry["sha256"], "result": result}
    return by_proposal


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("splits", nargs="+", type=Path)
    parser.add_argument("--allow-pending", action="store_true")
    args = parser.parse_args(argv)
    failed = False
    for path in args.splits:
        try:
            result = load_and_validate_split(path, repo_root=_repo_root(), require_admission_review=not args.allow_pending)
        except SplitError as exc:
            failed = True
            print(f"[FAIL] {path}: {exc.code}: {exc.message}")
            continue
        print(f"[PASS] {path}: proposal={result['split']['proposalId']} children={len(result['children'])}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
