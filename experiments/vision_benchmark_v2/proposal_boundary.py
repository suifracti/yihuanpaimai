#!/usr/bin/env python3
"""Export and validate replayable production observations for Benchmark v2.

The saved artifact is observation provenance only. It deliberately has no
benchmark instance, parent, canonical identity, truth, or queue authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np


SCHEMA_VERSION = "production-proposal-contract-v1"
COORDINATE_SPACE = "source_pixel"
EXPORTER_VERSION = "settlement-component-export-v1"
SOURCE_ROLE_VERSION = "fixed-inventory-crop-role-v1"
PRODUCTION_PRIMITIVE_NAME = "SettlementItemRecognizer._segment_occupied_components"
PRODUCTION_IMPLEMENTATION_PATH = "core/settlement_item_recognizer.py"

FORBIDDEN_AUTHORITY_FIELDS = {
    "instanceId",
    "benchmarkInstanceId",
    "authoritativeParentGrouping",
    "canonicalItemId",
    "verifiedIdentity",
    "verifiedTruth",
    "truthStatus",
    "queueId",
}


class ProposalError(RuntimeError):
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


def sha256_json(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _resolve_repo_path(repo_root: Path, raw_path: Any, field: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ProposalError("E_PATH", f"{field} must be a repository-relative path")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ProposalError("E_PATH", f"{field} cannot be absolute")
    resolved = (repo_root / candidate).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ProposalError("E_PATH", f"{field} escapes repository root") from exc
    return resolved


def _repo_relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ProposalError("E_PATH", f"path must remain inside repository root: {path}") from exc


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _read_json(path: Path, code: str) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalError(code, str(exc)) from exc
    if not isinstance(payload, dict):
        raise ProposalError(code, "top-level value must be an object")
    return payload


def _require_exact_keys(value: Any, required: Iterable[str], location: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ProposalError("E_SCHEMA", f"{location} must be an object")
    required_set = set(required)
    missing = sorted(required_set - set(value))
    extra = sorted(set(value) - required_set)
    if missing:
        raise ProposalError("E_SCHEMA", f"{location} missing fields: {', '.join(missing)}")
    if extra:
        raise ProposalError("E_SCHEMA", f"{location} has unsupported fields: {', '.join(extra)}")
    return value


def _find_forbidden_authority(value: Any, location: str = "$") -> Optional[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_AUTHORITY_FIELDS:
                return f"{location}.{key}"
            found = _find_forbidden_authority(nested, f"{location}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _find_forbidden_authority(nested, f"{location}[{index}]")
            if found:
                return found
    return None


def _bbox(value: Any, location: str) -> Tuple[int, int, int, int]:
    if not isinstance(value, list) or len(value) != 4 or not all(isinstance(n, int) and not isinstance(n, bool) for n in value):
        raise ProposalError("E_PROPOSAL_BBOX", f"{location} must be [x1,y1,x2,y2] integers")
    x1, y1, x2, y2 = value
    if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
        raise ProposalError("E_PROPOSAL_BBOX", f"{location} has invalid extent")
    return x1, y1, x2, y2


def _validate_primitive(value: Any, location: str) -> Dict[str, Any]:
    primitive = _require_exact_keys(
        value,
        {
            "name",
            "version",
            "implementationPath",
            "implementationSha256",
            "invocationVersion",
            "runtimeDependencies",
        },
        location,
    )
    for field in ("name", "version", "implementationPath", "implementationSha256", "invocationVersion"):
        if not isinstance(primitive[field], str) or not primitive[field]:
            raise ProposalError("E_PRIMITIVE_PROVENANCE", f"{location}.{field} must be non-empty")
    if not isinstance(primitive["runtimeDependencies"], dict):
        raise ProposalError("E_PRIMITIVE_PROVENANCE", f"{location}.runtimeDependencies must be an object")
    return primitive


def validate_artifact(payload: Dict[str, Any], *, repo_root: Path) -> Dict[str, Any]:
    """Fail closed on proposal provenance and geometry without importing production."""
    forbidden = _find_forbidden_authority(payload)
    if forbidden:
        raise ProposalError("E_PROPOSAL_AUTHORITY", f"benchmark authority field is forbidden at {forbidden}")
    artifact = _require_exact_keys(
        payload,
        {"schemaVersion", "source", "sceneProposal", "roiProposal", "itemProposals"},
        "$",
    )
    if artifact["schemaVersion"] != SCHEMA_VERSION:
        raise ProposalError("E_PROPOSAL_SCHEMA_VERSION", f"expected {SCHEMA_VERSION}")

    source = _require_exact_keys(
        artifact["source"],
        {"sourcePath", "sha256", "width", "height", "coordinateSpace"},
        "$.source",
    )
    if source["coordinateSpace"] != COORDINATE_SPACE:
        raise ProposalError("E_PROPOSAL_COORDINATE_SPACE", "source must use source_pixel")
    if not isinstance(source["width"], int) or source["width"] <= 0 or not isinstance(source["height"], int) or source["height"] <= 0:
        raise ProposalError("E_PROPOSAL_SOURCE_DIMENSIONS", "source dimensions must be positive integers")
    source_path = _resolve_repo_path(repo_root, source["sourcePath"], "source.sourcePath")
    if not source_path.is_file():
        raise ProposalError("E_PROPOSAL_SOURCE_MISSING", f"source does not exist: {source['sourcePath']}")
    actual_hash = sha256_file(source_path)
    if actual_hash != source["sha256"]:
        raise ProposalError("E_PROPOSAL_SOURCE_HASH", f"declared {source['sha256']}, got {actual_hash}")
    image = cv2.imdecode(np.fromfile(source_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ProposalError("E_PROPOSAL_SOURCE_READ", "source image cannot be decoded")
    actual_height, actual_width = image.shape[:2]
    if (actual_width, actual_height) != (source["width"], source["height"]):
        raise ProposalError(
            "E_PROPOSAL_SOURCE_DIMENSIONS",
            f"declared {source['width']}x{source['height']}, got {actual_width}x{actual_height}",
        )

    scene = _require_exact_keys(
        artifact["sceneProposal"],
        {"proposedSceneType", "confidence", "primitive", "rawProposalEvidence"},
        "$.sceneProposal",
    )
    if not isinstance(scene["proposedSceneType"], str) or not scene["proposedSceneType"]:
        raise ProposalError("E_SCENE_PROPOSAL", "scene type must be a non-empty proposal")
    if scene["confidence"] is not None and not isinstance(scene["confidence"], (int, float)):
        raise ProposalError("E_SCENE_PROPOSAL", "confidence must be numeric or null")
    _validate_primitive(scene["primitive"], "$.sceneProposal.primitive")
    if not isinstance(scene["rawProposalEvidence"], dict):
        raise ProposalError("E_SCENE_PROPOSAL", "rawProposalEvidence must be an object")

    roi = _require_exact_keys(
        artifact["roiProposal"],
        {"bbox", "coordinateSpace", "primitive", "rawProposalEvidence"},
        "$.roiProposal",
    )
    if roi["coordinateSpace"] != COORDINATE_SPACE:
        raise ProposalError("E_PROPOSAL_COORDINATE_SPACE", "ROI must use source_pixel")
    rx1, ry1, rx2, ry2 = _bbox(roi["bbox"], "$.roiProposal.bbox")
    if rx2 > source["width"] or ry2 > source["height"]:
        raise ProposalError("E_PROPOSAL_ROI_BOUNDS", "ROI exceeds source bounds")
    _validate_primitive(roi["primitive"], "$.roiProposal.primitive")
    if not isinstance(roi["rawProposalEvidence"], dict):
        raise ProposalError("E_ROI_PROPOSAL", "rawProposalEvidence must be an object")

    proposals = artifact["itemProposals"]
    if not isinstance(proposals, list) or not proposals:
        raise ProposalError("E_ITEM_PROPOSALS", "itemProposals must be a non-empty array")
    proposal_ids = set()
    required_proposal_fields = {
        "proposalId",
        "bbox",
        "coordinateSpace",
        "occupiedCells",
        "footprintCandidate",
        "trackId",
        "primitive",
        "rawProposalEvidence",
    }
    for index, raw in enumerate(proposals):
        location = f"$.itemProposals[{index}]"
        proposal = _require_exact_keys(raw, required_proposal_fields, location)
        proposal_id = proposal["proposalId"]
        if not isinstance(proposal_id, str) or not proposal_id.startswith("proposal-"):
            raise ProposalError("E_PROPOSAL_ID", f"{location}.proposalId must begin with proposal-")
        if proposal_id in proposal_ids:
            raise ProposalError("E_PROPOSAL_ID_DUPLICATE", f"duplicate proposalId {proposal_id}")
        proposal_ids.add(proposal_id)
        if proposal["coordinateSpace"] != COORDINATE_SPACE:
            raise ProposalError("E_PROPOSAL_COORDINATE_SPACE", f"{location} must use source_pixel")
        x1, y1, x2, y2 = _bbox(proposal["bbox"], f"{location}.bbox")
        if x2 > source["width"] or y2 > source["height"]:
            raise ProposalError("E_PROPOSAL_BBOX_BOUNDS", f"{location}.bbox exceeds source bounds")
        if not (rx1 <= x1 < x2 <= rx2 and ry1 <= y1 < y2 <= ry2):
            raise ProposalError("E_PROPOSAL_BBOX_ROI", f"{location}.bbox is outside proposed ROI")
        cells = proposal["occupiedCells"]
        if not isinstance(cells, list) or not all(
            isinstance(cell, list)
            and len(cell) == 2
            and all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in cell)
            for cell in cells
        ):
            raise ProposalError("E_PROPOSAL_CELLS", f"{location}.occupiedCells is invalid")
        footprint = proposal["footprintCandidate"]
        if footprint is not None:
            footprint = _require_exact_keys(footprint, {"widthCells", "heightCells"}, f"{location}.footprintCandidate")
            if not all(isinstance(footprint[key], int) and footprint[key] > 0 for key in footprint):
                raise ProposalError("E_PROPOSAL_FOOTPRINT", f"{location}.footprintCandidate is invalid")
        if proposal["trackId"] is not None and not isinstance(proposal["trackId"], (str, int)):
            raise ProposalError("E_PROPOSAL_TRACK", f"{location}.trackId must be provenance-only scalar or null")
        _validate_primitive(proposal["primitive"], f"{location}.primitive")
        if not isinstance(proposal["rawProposalEvidence"], dict):
            raise ProposalError("E_PROPOSAL_EVIDENCE", f"{location}.rawProposalEvidence must be an object")
    return artifact


def load_and_validate_artifact(path: Path, *, repo_root: Path) -> Dict[str, Any]:
    return validate_artifact(_read_json(path, "E_PROPOSAL_ARTIFACT_READ"), repo_root=repo_root)


def _primitive_record(implementation_sha256: str) -> Dict[str, Any]:
    return {
        "name": PRODUCTION_PRIMITIVE_NAME,
        "version": f"source-sha256:{implementation_sha256}",
        "implementationPath": PRODUCTION_IMPLEMENTATION_PATH,
        "implementationSha256": implementation_sha256,
        "invocationVersion": EXPORTER_VERSION,
        "runtimeDependencies": {
            "opencv": cv2.__version__,
            "numpy": np.__version__,
        },
    }


def _source_role_primitive(repo_root: Path) -> Dict[str, Any]:
    implementation_path = repo_root / "experiments" / "vision_benchmark_v2" / "proposal_boundary.py"
    return {
        "name": "experiment.fixed_inventory_crop_input_role",
        "version": SOURCE_ROLE_VERSION,
        "implementationPath": "experiments/vision_benchmark_v2/proposal_boundary.py",
        "implementationSha256": sha256_file(implementation_path),
        "invocationVersion": EXPORTER_VERSION,
        "runtimeDependencies": {},
    }


def export_artifact(config_path: Path, *, repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Run one stateless production primitive and normalize its observations."""
    repo_root = (repo_root or _repo_root()).resolve()
    config = _read_json(config_path.resolve(), "E_PROPOSAL_EXPORT_CONFIG")
    _require_exact_keys(
        config,
        {
            "exportVersion",
            "sourcePath",
            "expectedSourceSha256",
            "expectedWidth",
            "expectedHeight",
            "sceneInputRole",
            "inventoryRoi",
            "productionPrimitive",
        },
        "$exportConfig",
    )
    if config["exportVersion"] != EXPORTER_VERSION:
        raise ProposalError("E_EXPORT_VERSION", f"expected {EXPORTER_VERSION}")
    source_path = _resolve_repo_path(repo_root, config["sourcePath"], "sourcePath")
    if not source_path.is_file():
        raise ProposalError("E_PROPOSAL_SOURCE_MISSING", f"source does not exist: {config['sourcePath']}")
    source_hash = sha256_file(source_path)
    if source_hash != config["expectedSourceSha256"]:
        raise ProposalError("E_PROPOSAL_SOURCE_HASH", f"expected {config['expectedSourceSha256']}, got {source_hash}")
    image = cv2.imdecode(np.fromfile(source_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ProposalError("E_PROPOSAL_SOURCE_READ", "source image cannot be decoded")
    height, width = image.shape[:2]
    if (width, height) != (config["expectedWidth"], config["expectedHeight"]):
        raise ProposalError("E_PROPOSAL_SOURCE_DIMENSIONS", f"expected {config['expectedWidth']}x{config['expectedHeight']}, got {width}x{height}")

    primitive_config = _require_exact_keys(
        config["productionPrimitive"],
        {"name", "expectedImplementationSha256"},
        "$exportConfig.productionPrimitive",
    )
    if primitive_config["name"] != PRODUCTION_PRIMITIVE_NAME:
        raise ProposalError("E_PRIMITIVE_NAME", f"only {PRODUCTION_PRIMITIVE_NAME} is admitted in boundary v1")
    implementation_path = repo_root / PRODUCTION_IMPLEMENTATION_PATH
    implementation_hash = sha256_file(implementation_path)
    if implementation_hash != primitive_config["expectedImplementationSha256"]:
        raise ProposalError(
            "E_PRIMITIVE_VERSION",
            f"production implementation changed: expected {primitive_config['expectedImplementationSha256']}, got {implementation_hash}",
        )

    roi = config["inventoryRoi"]
    if roi != {"bbox": [0, 0, width, height], "coordinateSpace": COORDINATE_SPACE}:
        raise ProposalError("E_EXPORT_ROI", "single-source v1 exporter accepts only the full fixed inventory crop")
    if config["sceneInputRole"] != "inventory_crop":
        raise ProposalError("E_EXPORT_SCENE", "single-source v1 exporter requires the declared inventory_crop input role")

    core_path = str(repo_root / "core")
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
    from settlement_item_recognizer import SettlementItemRecognizer

    recognizer = SettlementItemRecognizer()
    cell_width = width / 10.0
    cell_height = height / 10.0
    raw_components = recognizer._segment_occupied_components(image, cell_width, cell_height)
    primitive = _primitive_record(implementation_hash)
    proposals: List[Dict[str, Any]] = []
    for component in raw_components:
        cells = [list(cell) for cell in component.get("cells") or []]
        rects = [recognizer._cell_rect(row, col, cell_width, cell_height) for row, col in component["cells"]]
        x1 = min(rect[0] for rect in rects)
        y1 = min(rect[1] for rect in rects)
        x2 = max(rect[2] for rect in rects)
        y2 = max(rect[3] for rect in rects)
        proposal_seed = {
            "sourceSha256": source_hash,
            "bbox": [x1, y1, x2, y2],
            "occupiedCells": cells,
            "primitiveVersion": primitive["version"],
            "invocationVersion": EXPORTER_VERSION,
        }
        proposal_id = f"proposal-{sha256_json(proposal_seed)[:20]}"
        proposals.append(
            {
                "proposalId": proposal_id,
                "bbox": [x1, y1, x2, y2],
                "coordinateSpace": COORDINATE_SPACE,
                "occupiedCells": cells,
                "footprintCandidate": {
                    "widthCells": component["widthCells"],
                    "heightCells": component["heightCells"],
                },
                "trackId": None,
                "primitive": primitive,
                "rawProposalEvidence": {
                    "row": component["row"],
                    "col": component["col"],
                    "shape": component["shape"],
                    "occupiedCount": component["occupiedCount"],
                    "rarityObservation": component["rarity"],
                    "rarityScore": round(float(component["score"]), 6),
                },
            }
        )

    source_role_primitive = _source_role_primitive(repo_root)
    artifact = {
        "schemaVersion": SCHEMA_VERSION,
        "source": {
            "sourcePath": _repo_relative(repo_root, source_path),
            "sha256": source_hash,
            "width": width,
            "height": height,
            "coordinateSpace": COORDINATE_SPACE,
        },
        "sceneProposal": {
            "proposedSceneType": "inventory_crop",
            "confidence": None,
            "primitive": source_role_primitive,
            "rawProposalEvidence": {
                "evidenceType": "declared_fixed_source_input_role",
                "automaticSceneClassificationPerformed": False,
            },
        },
        "roiProposal": {
            "bbox": [0, 0, width, height],
            "coordinateSpace": COORDINATE_SPACE,
            "primitive": source_role_primitive,
            "rawProposalEvidence": {
                "evidenceType": "full_extent_of_fixed_inventory_crop",
                "automaticRoiDetectionPerformed": False,
            },
        },
        "itemProposals": proposals,
    }
    return validate_artifact(artifact, repo_root=repo_root)


def main(argv: Optional[Sequence[str]] = None) -> int:
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=base / "fixtures" / "proposal_export_single_source_v1.json")
    parser.add_argument("--output", type=Path, default=base / "proposal_artifact.json")
    args = parser.parse_args(argv)
    try:
        artifact = export_artifact(args.config)
        _write_json(args.output, artifact)
    except ProposalError as exc:
        print(f"[FAIL] {exc.code}: {exc.message}")
        return 1
    print(
        f"[PASS] schema={artifact['schemaVersion']} source={artifact['source']['sha256']} "
        f"proposals={len(artifact['itemProposals'])} artifactSha256={sha256_file(args.output)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
