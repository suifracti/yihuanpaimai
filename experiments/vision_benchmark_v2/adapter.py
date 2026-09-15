#!/usr/bin/env python3
"""Build one validated Benchmark v2 admission slice from a reviewed fixture.

The adapter owns benchmark provenance and identity. Production vision outputs may
be future proposal inputs, but they never create benchmark instance identity.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import PIL
from PIL import Image


ADAPTER_VERSION = "benchmark-v2-adapter-slice-v1"
RESOLVER_VERSION = "parent-grouping-review-v1"
MATERIALIZER_VERSION = "exact-source-bbox-v1"
COORDINATE_SPACE = "source_pixel"


class AdapterError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_v1_validator(repo_root: Path):
    path = repo_root / "experiments" / "vision_benchmark_v1" / "validate_geometry_contract.py"
    spec = importlib.util.spec_from_file_location("benchmark_v1_geometry_validator_for_v2", path)
    if spec is None or spec.loader is None:
        raise AdapterError("E_VALIDATOR_LOAD", f"cannot load Geometry Contract validator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_grouping_review(repo_root: Path):
    path = repo_root / "experiments" / "vision_benchmark_v2" / "grouping_review.py"
    spec = importlib.util.spec_from_file_location("benchmark_v2_grouping_review_for_adapter", path)
    if spec is None or spec.loader is None:
        raise AdapterError("E_GROUPING_REVIEW_LOAD", f"cannot load grouping review validator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_digest(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _resolve_repo_path(repo_root: Path, relative_path: str, field: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise AdapterError("E_PATH", f"{field} must be a non-empty repository-relative path")
    raw = Path(relative_path)
    if raw.is_absolute():
        raise AdapterError("E_PATH", f"{field} cannot be absolute")
    resolved = (repo_root / raw).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise AdapterError("E_PATH", f"{field} escapes repository root") from exc
    return resolved


def _repo_relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise AdapterError("E_OUTPUT_PATH", f"output must remain inside repository root: {path}") from exc


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _validation_error(phase: str, result: Any) -> AdapterError:
    details = "; ".join(f"{issue.code} {issue.location}: {issue.message}" for issue in result.issues)
    return AdapterError(f"E_{phase.upper()}_VALIDATION", details or "validation failed")


def _read_fixture(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError("E_FIXTURE_READ", str(exc)) from exc
    if payload.get("adapterVersion") != ADAPTER_VERSION:
        raise AdapterError("E_ADAPTER_VERSION", f"fixture must target {ADAPTER_VERSION}")
    return payload


def _reviewed_parent(
    fixture: Dict[str, Any],
    *,
    repo_root: Path,
    source_sha256: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    scene = fixture.get("sceneAdmission") or {}
    if scene.get("inventoryEligible") is not True:
        raise AdapterError("E_SOURCE_NOT_ELIGIBLE", "reviewed source must be explicitly inventory-eligible")
    if scene.get("decisionMethod") != "reviewed_fixture":
        raise AdapterError("E_SCENE_PROVENANCE", "single-source slice requires an explicit reviewed_fixture decision")
    grouping_ref = fixture.get("groupingReview") or {}
    grouping_path = _resolve_repo_path(repo_root, grouping_ref.get("path"), "groupingReview.path")
    if not grouping_path.is_file():
        raise AdapterError("E_GROUPING_REVIEW_MISSING", f"grouping review does not exist: {grouping_path}")
    grouping_sha256 = _sha256(grouping_path)
    if grouping_sha256 != grouping_ref.get("expectedSha256"):
        raise AdapterError(
            "E_GROUPING_REVIEW_HASH",
            f"expected {grouping_ref.get('expectedSha256')}, got {grouping_sha256}",
        )
    grouping_review = _load_grouping_review(repo_root)
    try:
        grouping_result = grouping_review.load_and_validate_grouping(
            grouping_path,
            repo_root=repo_root,
            require_admission_review=True,
        )
    except grouping_review.GroupingError as exc:
        raise AdapterError(exc.code, exc.message) from exc
    artifact = grouping_result["proposalArtifact"]
    artifact_source = artifact["source"]
    if artifact_source["sha256"] != source_sha256:
        raise AdapterError("E_PROPOSAL_SOURCE_HASH", "proposal artifact source does not match the fixed source bytes")
    if artifact_source["coordinateSpace"] != COORDINATE_SPACE:
        raise AdapterError("E_PROPOSAL_COORDINATE_SPACE", "proposal artifact must use source_pixel")
    artifact_roi = artifact["roiProposal"]
    fixture_roi = fixture.get("inventoryRoi") or {}
    expected_roi_bbox = [
        fixture_roi.get("x"),
        fixture_roi.get("y"),
        fixture_roi.get("x", 0) + fixture_roi.get("width", 0),
        fixture_roi.get("y", 0) + fixture_roi.get("height", 0),
    ]
    if artifact_roi["bbox"] != expected_roi_bbox or artifact_roi["coordinateSpace"] != COORDINATE_SPACE:
        raise AdapterError("E_PROPOSAL_ROI_MISMATCH", "proposal ROI does not match the reviewed source-pixel ROI")
    if artifact["sceneProposal"]["proposedSceneType"] != scene.get("sceneType"):
        raise AdapterError("E_PROPOSAL_SCENE_MISMATCH", "proposal scene does not match reviewed scene admission")

    selected_group_id = grouping_ref.get("selectedGroupId")
    selected_group = next(
        (group for group in grouping_result["groups"] if group["groupId"] == selected_group_id),
        None,
    )
    if selected_group is None:
        raise AdapterError("E_PARENT_GROUP_UNKNOWN", f"selected groupId is absent: {selected_group_id}")
    member_ids = selected_group["memberProposalIds"]
    split_child_ids = selected_group.get("memberSplitChildIds", [])
    selected_proposals = [grouping_result["proposalMap"][proposal_id] for proposal_id in member_ids]
    selected_split_children = [grouping_result["splitChildMap"][child_id] for child_id in split_child_ids]
    if selected_split_children:
        selected_proposals = [grouping_result["splitResult"]["proposal"]]
    if selected_group["resolutionMethod"] == "single_proposal":
        footprint = selected_proposals[0]["footprintCandidate"]
    else:
        footprint = None
    review_evidence = selected_group["reviewEvidence"]
    parent = {
        "bbox": selected_group["resolvedParentBbox"],
        "bboxCoordinateSpace": selected_group["bboxCoordinateSpace"],
        "footprint": footprint,
        "canonicalItemId": None,
        "observationLabel": None,
        "contentVerification": {
            "contentVerified": True,
            "reviewStatus": selected_group["reviewStatus"],
            "evidenceType": "manual_review"
            if review_evidence["evidenceType"] == "manual_source_review"
            else "independent_evidence",
            "scope": "crop_instance_binding_only",
            "note": review_evidence["note"],
        },
    }
    primitive_records = {json.dumps(proposal["primitive"], sort_keys=True) for proposal in selected_proposals}
    provenance = {
        "artifactPath": _repo_relative(repo_root, grouping_result["proposalArtifactPath"]),
        "artifactSha256": grouping_result["grouping"]["proposalArtifactHash"],
        "schemaVersion": artifact["schemaVersion"],
        "groupingReviewPath": _repo_relative(repo_root, grouping_path),
        "groupingReviewSha256": grouping_sha256,
        "groupingVersion": grouping_result["grouping"]["groupingVersion"],
        "atomicityReviewPath": _repo_relative(repo_root, grouping_result["atomicityReviewPath"]),
        "atomicityReviewSha256": grouping_result["atomicityReviewHash"],
        "atomicityReviewVersion": grouping_result["atomicityReview"]["review"]["reviewVersion"],
        "atomicityClassifications": selected_group["atomicityClassifications"],
        "selectedGroupId": selected_group["groupId"],
        "selectedProposalIds": member_ids,
        "selectedProposalCount": len(member_ids),
        "selectedSplitChildIds": split_child_ids,
        "selectedSplitChildCount": len(split_child_ids),
        "selectedProposalTrackIds": [
            {"proposalId": proposal["proposalId"], "trackId": proposal["trackId"]}
            for proposal in selected_proposals
        ],
        "selectedProposalUnionBbox": selected_group["memberProposalUnionBbox"],
        "resolvedParentBbox": selected_group["resolvedParentBbox"],
        "bboxDerivation": selected_group["bboxDerivation"],
        "productionPrimitives": [json.loads(record) for record in sorted(primitive_records)],
        "parentResolutionOwner": "benchmark-v2-adapter",
        "parentResolutionMethod": selected_group["resolutionMethod"],
        "reviewStatus": selected_group["reviewStatus"],
        "reviewEvidence": review_evidence,
    }
    if selected_split_children:
        provenance["splitReviewPath"] = _repo_relative(repo_root, grouping_result["splitReviewPath"])
        provenance["splitReviewSha256"] = grouping_result["splitReviewHash"]
        provenance["splitVersion"] = grouping_result["splitResult"]["split"]["splitVersion"]
        provenance["splitSourceProposalId"] = grouping_result["splitResult"]["split"]["proposalId"]
        provenance["selectedSplitChildren"] = [
            {
                "childId": child["childId"],
                "sourcePixelBbox": child["sourcePixelBbox"],
                "sourceCells": child["sourceCells"],
                "coverageRole": child["coverageRole"],
            }
            for child in selected_split_children
        ]
    return parent, provenance


def _materialize_crop(snapshot_path: Path, bbox: Sequence[int], crop_path: Path) -> Tuple[int, int]:
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise AdapterError("E_BBOX", "bbox must be [x1, y1, x2, y2]")
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    temp = crop_path.with_suffix(".tmp.png")
    with Image.open(snapshot_path) as source:
        cropped = source.crop(tuple(bbox))
        cropped.save(temp, format="PNG", optimize=False, compress_level=9)
        dimensions = cropped.size
    os.replace(temp, crop_path)
    return dimensions


def run_slice(
    fixture_path: Path,
    output_dir: Path,
    *,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    repo_root = (repo_root or _repo_root()).resolve()
    fixture_path = fixture_path.resolve()
    output_dir = output_dir.resolve()
    _repo_relative(repo_root, output_dir)
    fixture = _read_fixture(fixture_path)
    validator = _load_v1_validator(repo_root)

    # 1. Freeze exact candidate bytes and verify their declared provenance.
    candidate_path = _resolve_repo_path(repo_root, fixture.get("candidateSourcePath"), "candidateSourcePath")
    if not candidate_path.is_file():
        raise AdapterError("E_SOURCE_MISSING", f"candidate source does not exist: {candidate_path}")
    source_sha256 = _sha256(candidate_path)
    expected_hash = str(fixture.get("expectedSourceSha256") or "").lower()
    if source_sha256 != expected_hash:
        raise AdapterError("E_SOURCE_HASH_MISMATCH", f"expected {expected_hash}, got {source_sha256}")
    source_id = f"src-{source_sha256[:20]}"
    suffix = candidate_path.suffix.lower() or ".png"
    snapshot_path = output_dir / "snapshots" / f"source-{source_sha256[:20]}{suffix}"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate_path, snapshot_path)
    if _sha256(snapshot_path) != source_sha256:
        raise AdapterError("E_SNAPSHOT_HASH_MISMATCH", "frozen snapshot bytes differ from candidate source")

    declared_width = fixture.get("expectedWidth")
    declared_height = fixture.get("expectedHeight")
    scene = fixture.get("sceneAdmission") or {}
    roi = fixture.get("inventoryRoi")
    if not isinstance(roi, dict):
        raise AdapterError("E_ROI", "inventoryRoi must be an object")
    proposal, proposal_provenance = _reviewed_parent(
        fixture,
        repo_root=repo_root,
        source_sha256=source_sha256,
    )

    # 2. Resolve one reviewed physical parent and create an opaque stable ID.
    identity_seed = {
        "sourceSha256": source_sha256,
        "inventoryRoi": roi,
        "bbox": proposal.get("bbox"),
        "resolverVersion": RESOLVER_VERSION,
    }
    instance_digest = _stable_digest(identity_seed)
    instance_id = f"inst-{instance_digest[:20]}"
    queue_id = f"queue-{instance_digest[:20]}"

    snapshot_rel = _repo_relative(repo_root, snapshot_path)
    contract_source = {
        "sourceId": source_id,
        "sourcePath": snapshot_rel,
        "width": declared_width,
        "height": declared_height,
        "sceneType": scene.get("sceneType"),
        "inventoryEligible": scene.get("inventoryEligible"),
        "inventoryRoi": roi,
        "coordinateSpace": COORDINATE_SPACE,
    }
    contract_instance = {
        "instanceId": instance_id,
        "sourceId": source_id,
        "bbox": proposal.get("bbox"),
        "bboxCoordinateSpace": proposal.get("bboxCoordinateSpace"),
        "footprint": proposal.get("footprint"),
        "canonicalItemId": None,
        "observationLabel": None,
        "contentVerification": proposal.get("contentVerification"),
    }
    contract_path = output_dir / "geometry_contract.json"
    preflight_contract = {
        "contractVersion": "geometry-contract-v1",
        "pathBase": "repository_root",
        "description": "Benchmark v2 single-source preflight; geometry precedes identity.",
        "sources": [contract_source],
        "instances": [contract_instance],
        "queueSlots": [],
    }
    preflight = validator.validate_contract_data(
        preflight_contract,
        contract_path=contract_path,
        repo_root=repo_root,
    )
    if not preflight.valid:
        raise _validation_error("preflight", preflight)

    # 3. Materialize exact source[bbox] with no padding, resize, or enhancement.
    crop_path = output_dir / "crops" / f"crop-{instance_digest[:20]}.png"
    crop_dimensions = _materialize_crop(snapshot_path, proposal["bbox"], crop_path)
    crop_sha256 = _sha256(crop_path)
    crop_rel = _repo_relative(repo_root, crop_path)

    # 4. Reuse Geometry Contract v1 for final queue admission.
    final_contract = dict(preflight_contract)
    final_contract["description"] = "Benchmark v2 single-source admitted geometry; identity remains null."
    final_contract["queueSlots"] = [
        {
            "queueId": queue_id,
            "instanceId": instance_id,
            "cropPath": crop_rel,
        }
    ]
    final_validation = validator.validate_contract_data(
        final_contract,
        contract_path=contract_path,
        repo_root=repo_root,
    )
    if not final_validation.valid:
        raise _validation_error("final", final_validation)

    fixture_rel = _repo_relative(repo_root, fixture_path)
    source_record = {
        "recordVersion": "benchmark-v2-source-record-v1",
        "sourceId": source_id,
        "candidateSourcePath": fixture["candidateSourcePath"],
        "snapshotPath": snapshot_rel,
        "sha256": source_sha256,
        "width": declared_width,
        "height": declared_height,
        "sceneType": scene["sceneType"],
        "inventoryEligible": True,
        "sceneAdmission": scene,
        "inventoryRoi": roi,
        "coordinateSpace": COORDINATE_SPACE,
        "fixturePath": fixture_rel,
        "fixtureSha256": _sha256(fixture_path),
        "snapshotOwner": ADAPTER_VERSION,
        "proposalProvenance": proposal_provenance,
    }
    queue_record = {
        "packVersion": "benchmark-v2-single-source-slice-v1",
        "admissionStatus": "PASS",
        "items": [
            {
                "queueId": queue_id,
                "instanceId": instance_id,
                "sourceId": source_id,
                "cropPath": crop_rel,
                "cropDimensions": {"width": crop_dimensions[0], "height": crop_dimensions[1]},
                "cropSha256": crop_sha256,
                "materializer": {
                    "name": "fixed_source_bbox_crop",
                    "version": MATERIALIZER_VERSION,
                    "library": f"Pillow {PIL.__version__}",
                    "padding": 0,
                    "resize": None,
                    "enhancement": None,
                    "sourceSha256": source_sha256,
                    "bbox": proposal["bbox"],
                    "coordinateSpace": COORDINATE_SPACE,
                },
            }
        ],
        "validation": {
            "validator": "experiments/vision_benchmark_v1/validate_geometry_contract.py",
            "geometryContractVersion": "geometry-contract-v1",
            "preflight": "PASS",
            "finalAdmission": "PASS",
        },
    }

    # Publish records only after final validation passes.
    _write_json(output_dir / "source_record.json", source_record)
    _write_json(contract_path, final_contract)
    _write_json(output_dir / "queue.json", queue_record)
    return {
        "sourceRecord": source_record,
        "geometryContract": final_contract,
        "queue": queue_record,
        "paths": {
            "sourceRecord": str(output_dir / "source_record.json"),
            "geometryContract": str(contract_path),
            "queue": str(output_dir / "queue.json"),
            "snapshot": str(snapshot_path),
            "crop": str(crop_path),
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).resolve().parent / "fixtures" / "reviewed_single_parent_v1.json",
    )
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args(argv)
    try:
        result = run_slice(args.fixture, args.output)
    except AdapterError as exc:
        print(f"[FAIL] {exc.code}: {exc.message}")
        return 1
    item = result["queue"]["items"][0]
    print(
        f"[PASS] source={result['sourceRecord']['sourceId']} "
        f"instance={item['instanceId']} queue={item['queueId']} cropSha256={item['cropSha256']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
