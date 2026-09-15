#!/usr/bin/env python3
"""Validate reviewed proposal groups without granting semantic authority."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


GROUPING_VERSION = "parent-grouping-review-v1"
COORDINATE_SPACE = "source_pixel"
RESOLUTION_METHODS = {"single_proposal", "reviewed_multi_proposal_group", "reviewed_split_child_parent"}
BBOX_DERIVATIONS = {"proposal_bbox", "union", "reviewed_override"}
REVIEW_STATUSES = {"pending_review", "reviewed_consistent", "rejected"}
FORBIDDEN_GROUPING_FIELDS = {
    "instanceId",
    "benchmarkInstanceId",
    "canonicalItemId",
    "semanticIdentity",
    "quality",
    "verifiedIdentity",
    "verifiedTruth",
    "truthStatus",
    "queueId",
}


class GroupingError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_proposal_boundary(repo_root: Path):
    path = repo_root / "experiments" / "vision_benchmark_v2" / "proposal_boundary.py"
    spec = importlib.util.spec_from_file_location("benchmark_v2_proposal_boundary_for_grouping", path)
    if spec is None or spec.loader is None:
        raise GroupingError("E_PROPOSAL_BOUNDARY_LOAD", f"cannot load proposal boundary: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_proposal_split(repo_root: Path):
    path = repo_root / "experiments" / "vision_benchmark_v2" / "proposal_split.py"
    spec = importlib.util.spec_from_file_location("benchmark_v2_proposal_split_for_grouping", path)
    if spec is None or spec.loader is None:
        raise GroupingError("E_PROPOSAL_SPLIT_LOAD", f"cannot load proposal split validator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_atomicity_review(repo_root: Path):
    path = repo_root / "experiments" / "vision_benchmark_v2" / "atomicity_review.py"
    spec = importlib.util.spec_from_file_location("benchmark_v2_atomicity_review_for_grouping", path)
    if spec is None or spec.loader is None:
        raise GroupingError("E_ATOMICITY_REVIEW_LOAD", f"cannot load atomicity review validator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GroupingError("E_GROUPING_READ", str(exc)) from exc
    if not isinstance(payload, dict):
        raise GroupingError("E_GROUPING_SCHEMA", "top-level value must be an object")
    return payload


def _resolve_repo_path(repo_root: Path, raw_path: Any, field: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise GroupingError("E_GROUPING_PATH", f"{field} must be a repository-relative path")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise GroupingError("E_GROUPING_PATH", f"{field} cannot be absolute")
    resolved = (repo_root / candidate).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise GroupingError("E_GROUPING_PATH", f"{field} escapes repository root") from exc
    return resolved


def _require_exact_keys(value: Any, required: Iterable[str], location: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise GroupingError("E_GROUPING_SCHEMA", f"{location} must be an object")
    expected = set(required)
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        raise GroupingError("E_GROUPING_SCHEMA", f"{location} missing fields: {', '.join(missing)}")
    if extra:
        raise GroupingError("E_GROUPING_SCHEMA", f"{location} has unsupported fields: {', '.join(extra)}")
    return value


def _require_keys(
    value: Any,
    *,
    required: Iterable[str],
    optional: Iterable[str],
    location: str,
) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise GroupingError("E_GROUPING_SCHEMA", f"{location} must be an object")
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise GroupingError("E_GROUPING_SCHEMA", f"{location} missing fields: {', '.join(missing)}")
    if extra:
        raise GroupingError("E_GROUPING_SCHEMA", f"{location} has unsupported fields: {', '.join(extra)}")
    return value


def _find_forbidden(value: Any, location: str = "$") -> Optional[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_GROUPING_FIELDS:
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


def _bbox(value: Any, location: str) -> Tuple[int, int, int, int]:
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(n, int) and not isinstance(n, bool) for n in value):
        raise GroupingError("E_GROUP_BBOX", f"{location} must be [x1,y1,x2,y2] integers")
    x1, y1, x2, y2 = value
    if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
        raise GroupingError("E_GROUP_BBOX", f"{location} has invalid extent")
    return x1, y1, x2, y2


def _union_bbox(proposals: List[Dict[str, Any]]) -> List[int]:
    boxes = [proposal["bbox"] for proposal in proposals]
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _intersects(first: Sequence[int], second: Sequence[int]) -> bool:
    return max(first[0], second[0]) < min(first[2], second[2]) and max(first[1], second[1]) < min(first[3], second[3])


def load_and_validate_grouping(
    grouping_path: Path,
    *,
    repo_root: Path,
    require_admission_review: bool = False,
) -> Dict[str, Any]:
    """Load the frozen proposal artifact and validate every reviewed group."""
    grouping_path = grouping_path.resolve()
    payload = _read_json(grouping_path)
    forbidden = _find_forbidden(payload)
    if forbidden:
        raise GroupingError("E_GROUPING_AUTHORITY", f"identity/truth authority is forbidden at {forbidden}")
    if "atomicityReviewPath" not in payload or "atomicityReviewHash" not in payload:
        raise GroupingError(
            "E_ATOMICITY_REVIEW_REQUIRED",
            "every parent grouping must bind an atomicity review artifact path and SHA-256",
        )
    grouping = _require_keys(
        payload,
        required={
            "groupingVersion", "sourceId", "proposalArtifactPath", "proposalArtifactHash",
            "atomicityReviewPath", "atomicityReviewHash", "groups",
        },
        optional={"splitReviewPath", "splitReviewHash"},
        location="$",
    )
    if grouping["groupingVersion"] != GROUPING_VERSION:
        raise GroupingError("E_GROUPING_VERSION", f"expected {GROUPING_VERSION}")
    if not isinstance(grouping["sourceId"], str) or not grouping["sourceId"]:
        raise GroupingError("E_GROUPING_SOURCE", "sourceId must be non-empty")

    proposal_path = _resolve_repo_path(repo_root, grouping["proposalArtifactPath"], "proposalArtifactPath")
    if not proposal_path.is_file():
        raise GroupingError("E_GROUPING_PROPOSAL_ARTIFACT_MISSING", f"proposal artifact does not exist: {proposal_path}")
    proposal_boundary = _load_proposal_boundary(repo_root)
    actual_artifact_hash = proposal_boundary.sha256_file(proposal_path)
    if actual_artifact_hash != grouping["proposalArtifactHash"]:
        raise GroupingError(
            "E_GROUPING_ARTIFACT_HASH",
            f"declared {grouping['proposalArtifactHash']}, got {actual_artifact_hash}",
        )
    try:
        proposal_artifact = proposal_boundary.load_and_validate_artifact(proposal_path, repo_root=repo_root)
    except proposal_boundary.ProposalError as exc:
        raise GroupingError(exc.code, exc.message) from exc
    expected_source_id = f"src-{proposal_artifact['source']['sha256'][:20]}"
    if grouping["sourceId"] != expected_source_id:
        raise GroupingError("E_GROUPING_SOURCE", "sourceId does not match proposal artifact source provenance")

    atomicity_review_path = _resolve_repo_path(repo_root, grouping["atomicityReviewPath"], "atomicityReviewPath")
    if not atomicity_review_path.is_file():
        raise GroupingError("E_ATOMICITY_REVIEW_MISSING", f"atomicity review does not exist: {atomicity_review_path}")
    atomicity_review_hash = _load_proposal_boundary(repo_root).sha256_file(atomicity_review_path)
    if atomicity_review_hash != grouping["atomicityReviewHash"]:
        raise GroupingError(
            "E_ATOMICITY_REVIEW_HASH",
            f"declared {grouping['atomicityReviewHash']}, got {atomicity_review_hash}",
        )
    atomicity_review = _load_atomicity_review(repo_root)
    try:
        atomicity_result = atomicity_review.load_and_validate_atomicity_review(
            atomicity_review_path,
            repo_root=repo_root,
            expected_proposal_artifact_path=proposal_path,
        )
    except atomicity_review.AtomicityError as exc:
        raise GroupingError(exc.code, exc.message) from exc

    proposal_map = {proposal["proposalId"]: proposal for proposal in proposal_artifact["itemProposals"]}
    roi_bbox = proposal_artifact["roiProposal"]["bbox"]
    source = proposal_artifact["source"]
    groups = grouping["groups"]
    if not isinstance(groups, list) or not groups:
        raise GroupingError("E_GROUP_REQUIRED", "groups must be a non-empty array")

    proposal_split = _load_proposal_split(repo_root)
    registry_path = repo_root / "experiments" / "vision_benchmark_v2" / "proposal_split_registry_v1.json"
    try:
        split_registry = proposal_split.load_split_registry(registry_path, repo_root=repo_root)
    except proposal_split.SplitError as exc:
        raise GroupingError(exc.code, exc.message) from exc
    registered_split_proposal_ids = set(split_registry)

    split_result = None
    split_child_map: Dict[str, Dict[str, Any]] = {}
    split_review_path = None
    split_review_hash = None
    has_split_path = "splitReviewPath" in grouping
    has_split_hash = "splitReviewHash" in grouping
    if has_split_path != has_split_hash:
        raise GroupingError("E_GROUPING_SPLIT_REFERENCE", "splitReviewPath and splitReviewHash must appear together")
    if has_split_path:
        split_review_path = _resolve_repo_path(repo_root, grouping["splitReviewPath"], "splitReviewPath")
        if not split_review_path.is_file():
            raise GroupingError("E_GROUPING_SPLIT_MISSING", f"split review does not exist: {split_review_path}")
        split_review_hash = proposal_split.sha256_file(split_review_path)
        if split_review_hash != grouping["splitReviewHash"]:
            raise GroupingError("E_GROUPING_SPLIT_HASH", f"declared {grouping['splitReviewHash']}, got {split_review_hash}")
        try:
            split_result = proposal_split.load_and_validate_split(
                split_review_path,
                repo_root=repo_root,
                require_admission_review=require_admission_review,
            )
        except proposal_split.SplitError as exc:
            raise GroupingError(exc.code, exc.message) from exc
        if split_result["split"]["sourceId"] != grouping["sourceId"]:
            raise GroupingError("E_GROUPING_SPLIT_SOURCE", "split review and grouping must use the same source")
        if split_result["proposalArtifactPath"] != proposal_path:
            raise GroupingError("E_GROUPING_SPLIT_ARTIFACT", "split review and grouping must use the same proposal artifact")
        split_child_map = {child["childId"]: child for child in split_result["children"]}

    normalized_groups = []
    group_ids = set()
    proposal_owner: Dict[str, str] = {}
    required_group_fields = {
        "groupId",
        "memberProposalIds",
        "resolvedParentBbox",
        "bboxCoordinateSpace",
        "bboxDerivation",
        "resolutionMethod",
        "reviewStatus",
        "reviewEvidence",
    }
    for index, raw_group in enumerate(groups):
        location = f"$.groups[{index}]"
        group = _require_keys(
            raw_group,
            required=required_group_fields,
            optional={"memberSplitChildIds"},
            location=location,
        )
        group_id = group["groupId"]
        if not isinstance(group_id, str) or not group_id.startswith("group-"):
            raise GroupingError("E_GROUP_ID", f"{location}.groupId must begin with group-")
        if group_id in group_ids:
            raise GroupingError("E_GROUP_ID_DUPLICATE", f"duplicate groupId {group_id}")
        group_ids.add(group_id)

        members = group["memberProposalIds"]
        if not isinstance(members, list) or not all(isinstance(member, str) and member for member in members):
            raise GroupingError("E_GROUP_MEMBERS", f"{location}.memberProposalIds must be an array of proposalIds")
        if len(set(members)) != len(members):
            raise GroupingError("E_GROUP_MEMBER_DUPLICATE", f"{location} repeats a proposalId")
        canonical_members = sorted(members)
        child_members = group.get("memberSplitChildIds", [])
        if not isinstance(child_members, list) or not all(isinstance(member, str) and member for member in child_members):
            raise GroupingError("E_GROUP_SPLIT_MEMBERS", f"{location}.memberSplitChildIds must be an array of childIds")
        if len(set(child_members)) != len(child_members):
            raise GroupingError("E_GROUP_SPLIT_MEMBER_DUPLICATE", f"{location} repeats a split childId")
        canonical_child_members = sorted(child_members)
        if not canonical_members and not canonical_child_members:
            raise GroupingError("E_GROUP_MEMBERS", f"{location} requires at least one proposal or split child")
        selected_proposals = []
        for proposal_id in canonical_members:
            proposal = proposal_map.get(proposal_id)
            if proposal is None:
                raise GroupingError("E_GROUP_PROPOSAL_UNKNOWN", f"{location} references unknown proposalId {proposal_id}")
            if proposal_id in registered_split_proposal_ids:
                raise GroupingError(
                    "E_SPLIT_PROPOSAL_DIRECT_PARENT",
                    f"reviewed-split proposalId {proposal_id} cannot be consumed as a complete parent member",
                )
            previous_owner = proposal_owner.get(proposal_id)
            if previous_owner is not None:
                raise GroupingError(
                    "E_PROPOSAL_MULTIPLE_PARENT_GROUPS",
                    f"proposalId {proposal_id} belongs to both {previous_owner} and {group_id}",
                )
            proposal_owner[proposal_id] = group_id
            selected_proposals.append(proposal)

        selected_children = []
        for child_id in canonical_child_members:
            child = split_child_map.get(child_id)
            if child is None:
                raise GroupingError("E_GROUP_SPLIT_CHILD_UNKNOWN", f"{location} references unknown split childId {child_id}")
            previous_owner = proposal_owner.get(child_id)
            if previous_owner is not None:
                raise GroupingError(
                    "E_SPLIT_CHILD_MULTIPLE_PARENT_GROUPS",
                    f"split childId {child_id} belongs to both {previous_owner} and {group_id}",
                )
            proposal_owner[child_id] = group_id
            selected_children.append(child)

        method = group["resolutionMethod"]
        if method not in RESOLUTION_METHODS:
            raise GroupingError("E_GROUP_RESOLUTION_METHOD", f"unsupported resolutionMethod {method!r}")
        if method == "single_proposal" and len(canonical_members) != 1:
            raise GroupingError("E_GROUP_RESOLUTION_METHOD", "single_proposal requires exactly one member")
        if method == "reviewed_multi_proposal_group" and len(canonical_members) < 2:
            raise GroupingError("E_GROUP_RESOLUTION_METHOD", "reviewed_multi_proposal_group requires at least two members")
        if method in {"single_proposal", "reviewed_multi_proposal_group"} and canonical_child_members:
            raise GroupingError("E_GROUP_RESOLUTION_METHOD", f"{method} cannot consume split children")
        if method == "reviewed_split_child_parent" and (canonical_members or len(canonical_child_members) != 1):
            raise GroupingError("E_GROUP_RESOLUTION_METHOD", "reviewed_split_child_parent requires exactly one split child")

        selected_classifications: Dict[str, str] = {}
        for proposal in selected_proposals:
            try:
                classification = atomicity_review.require_reviewed_classification(
                    atomicity_result,
                    proposal["proposalId"],
                )
            except atomicity_review.AtomicityError as exc:
                raise GroupingError(exc.code, exc.message) from exc
            selected_classifications[proposal["proposalId"]] = classification
            if classification == "MIXED_MULTI_PARENT":
                raise GroupingError(
                    "E_ATOMICITY_SPLIT_REQUIRED",
                    f"{proposal['proposalId']} is MIXED_MULTI_PARENT and requires an approved reviewed split",
                )
        if method == "single_proposal" and set(selected_classifications.values()) != {"ATOMIC_CLEAR"}:
            raise GroupingError(
                "E_ATOMICITY_SINGLE_REQUIRES_CLEAR",
                "single_proposal admission requires an ATOMIC_CLEAR proposal",
            )
        if method == "reviewed_multi_proposal_group" and set(selected_classifications.values()) != {"FRAGMENT_OF_ONE_PARENT"}:
            raise GroupingError(
                "E_ATOMICITY_GROUP_REQUIRES_FRAGMENT",
                "reviewed multi-proposal grouping accepts only FRAGMENT_OF_ONE_PARENT members",
            )
        if method == "reviewed_split_child_parent":
            source_proposal_id = split_result["split"]["proposalId"]
            try:
                source_classification = atomicity_review.require_reviewed_classification(
                    atomicity_result,
                    source_proposal_id,
                )
            except atomicity_review.AtomicityError as exc:
                raise GroupingError(exc.code, exc.message) from exc
            if source_classification != "MIXED_MULTI_PARENT":
                raise GroupingError(
                    "E_ATOMICITY_SPLIT_REQUIRES_MIXED",
                    "reviewed split path requires a MIXED_MULTI_PARENT source proposal",
                )
            selected_classifications[source_proposal_id] = source_classification
        if group["bboxCoordinateSpace"] != COORDINATE_SPACE:
            raise GroupingError("E_GROUP_COORDINATE_SPACE", f"{location} must use source_pixel")
        resolved_bbox = list(_bbox(group["resolvedParentBbox"], f"{location}.resolvedParentBbox"))
        if resolved_bbox[2] > source["width"] or resolved_bbox[3] > source["height"]:
            raise GroupingError("E_GROUP_BBOX_BOUNDS", f"{location}.resolvedParentBbox exceeds source bounds")
        if not (
            roi_bbox[0] <= resolved_bbox[0] < resolved_bbox[2] <= roi_bbox[2]
            and roi_bbox[1] <= resolved_bbox[1] < resolved_bbox[3] <= roi_bbox[3]
        ):
            raise GroupingError("E_GROUP_BBOX_ROI", f"{location}.resolvedParentBbox is outside proposal ROI")

        derivation = group["bboxDerivation"]
        if derivation not in BBOX_DERIVATIONS:
            raise GroupingError("E_GROUP_BBOX_DERIVATION", f"unsupported bboxDerivation {derivation!r}")
        member_geometries = selected_proposals + [
            {"bbox": child["sourcePixelBbox"]} for child in selected_children
        ]
        proposal_union = _union_bbox(member_geometries)
        if method == "single_proposal":
            if derivation != "proposal_bbox" or resolved_bbox != selected_proposals[0]["bbox"]:
                raise GroupingError("E_GROUP_BBOX_DERIVATION", "single proposal must use its exact proposal_bbox")
        elif method == "reviewed_split_child_parent":
            if derivation != "reviewed_override":
                raise GroupingError("E_GROUP_BBOX_DERIVATION", "split child parent must use reviewed_override")
            if not _intersects(resolved_bbox, selected_children[0]["sourcePixelBbox"]):
                raise GroupingError("E_GROUP_BBOX_DERIVATION", "reviewed parent bbox must intersect its split child")
            if any(
                _intersects(resolved_bbox, region["sourcePixelBbox"])
                for region in split_result["discardedRegions"]
            ):
                raise GroupingError(
                    "E_GROUP_DISCARDED_REGION_OWNERSHIP",
                    "reviewed parent bbox cannot reclaim pixels explicitly discarded by the split review",
                )
        elif derivation == "proposal_bbox":
            raise GroupingError("E_GROUP_BBOX_DERIVATION", "multi-proposal grouping cannot use proposal_bbox")
        elif derivation == "union" and resolved_bbox != proposal_union:
            raise GroupingError("E_GROUP_BBOX_DERIVATION", "union bbox does not equal the member proposal union")
        elif derivation == "reviewed_override" and not all(
            _intersects(resolved_bbox, proposal["bbox"]) for proposal in selected_proposals
        ):
            raise GroupingError("E_GROUP_BBOX_DERIVATION", "reviewed_override must intersect every member proposal")

        status = group["reviewStatus"]
        if status not in REVIEW_STATUSES:
            raise GroupingError("E_GROUP_REVIEW_STATUS", f"unsupported reviewStatus {status!r}")
        evidence = _require_exact_keys(
            group["reviewEvidence"],
            {"evidenceType", "sourceSnapshotPath", "reviewerRole", "note"},
            f"{location}.reviewEvidence",
        )
        if evidence["evidenceType"] not in {"manual_source_review", "independent_geometry_evidence"}:
            raise GroupingError("E_GROUP_REVIEW_EVIDENCE", f"{location} has unsupported evidenceType")
        if evidence["reviewerRole"] not in {"human_reviewer", "independent_geometry_reviewer"}:
            raise GroupingError("E_GROUP_REVIEW_EVIDENCE", f"{location} has unsupported reviewerRole")
        if not isinstance(evidence["note"], str) or not evidence["note"]:
            raise GroupingError("E_GROUP_REVIEW_EVIDENCE", f"{location}.reviewEvidence.note must be non-empty")
        evidence_source = _resolve_repo_path(repo_root, evidence["sourceSnapshotPath"], f"{location}.reviewEvidence.sourceSnapshotPath")
        proposal_source = _resolve_repo_path(repo_root, source["sourcePath"], "proposalArtifact.source.sourcePath")
        if evidence_source != proposal_source:
            raise GroupingError("E_GROUP_REVIEW_EVIDENCE", "review evidence must reference the exact proposal source snapshot")
        if require_admission_review and status != "reviewed_consistent":
            raise GroupingError("E_GROUP_NOT_REVIEWED", f"{group_id} cannot be admitted with reviewStatus={status}")

        normalized = dict(group)
        normalized["memberProposalIds"] = canonical_members
        normalized["memberSplitChildIds"] = canonical_child_members
        normalized["memberProposalUnionBbox"] = proposal_union
        normalized["atomicityClassifications"] = selected_classifications
        normalized_groups.append(normalized)

    return {
        "grouping": grouping,
        "groups": normalized_groups,
        "proposalArtifact": proposal_artifact,
        "proposalArtifactPath": proposal_path,
        "proposalMap": proposal_map,
        "splitResult": split_result,
        "splitChildMap": split_child_map,
        "splitReviewPath": split_review_path,
        "splitReviewHash": split_review_hash,
        "atomicityReview": atomicity_result,
        "atomicityReviewPath": atomicity_review_path,
        "atomicityReviewHash": atomicity_review_hash,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("groupings", nargs="+", type=Path)
    parser.add_argument("--allow-pending", action="store_true")
    args = parser.parse_args(argv)
    repo_root = _repo_root()
    failed = False
    for path in args.groupings:
        try:
            result = load_and_validate_grouping(
                path,
                repo_root=repo_root,
                require_admission_review=not args.allow_pending,
            )
        except GroupingError as exc:
            failed = True
            print(f"[FAIL] {path}: {exc.code}: {exc.message}")
            continue
        print(
            f"[PASS] {path}: groups={len(result['groups'])} "
            f"proposalArtifactHash={result['grouping']['proposalArtifactHash']}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
