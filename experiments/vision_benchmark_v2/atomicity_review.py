#!/usr/bin/env python3
"""Validate geometry-only atomicity reviews and enforce admission policy."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence


SCHEMA_VERSION = "atomicity-review-contract-v1"
REVIEW_VERSION = "atomicity-review-v1"
CLASSIFICATIONS = {
    "ATOMIC_CLEAR",
    "FRAGMENT_OF_ONE_PARENT",
    "MIXED_MULTI_PARENT",
    "AMBIGUOUS",
    "BACKGROUND_OR_NOISE",
}
REVIEW_STATUSES = {"pending_review", "reviewed_consistent", "rejected"}
BLOCKED_CLASSIFICATIONS = {"AMBIGUOUS", "BACKGROUND_OR_NOISE"}
FORBIDDEN_ATOMICITY_FIELDS = {
    "instanceId", "benchmarkInstanceId", "canonicalItemId", "semanticIdentity",
    "itemQuality", "quality", "verifiedIdentity", "verifiedTruth", "truthStatus", "queueId",
}


class AtomicityError(RuntimeError):
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
    spec = importlib.util.spec_from_file_location("benchmark_v2_proposal_boundary_for_atomicity", path)
    if spec is None or spec.loader is None:
        raise AtomicityError("E_PROPOSAL_BOUNDARY_LOAD", f"cannot load proposal boundary: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AtomicityError("E_ATOMICITY_READ", str(exc)) from exc
    if not isinstance(payload, dict):
        raise AtomicityError("E_ATOMICITY_SCHEMA", "top-level value must be an object")
    return payload


def _resolve_repo_path(repo_root: Path, raw_path: Any, field: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise AtomicityError("E_ATOMICITY_PATH", f"{field} must be a repository-relative path")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise AtomicityError("E_ATOMICITY_PATH", f"{field} cannot be absolute")
    resolved = (repo_root / candidate).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise AtomicityError("E_ATOMICITY_PATH", f"{field} escapes repository root") from exc
    return resolved


def _require_exact_keys(value: Any, required: Iterable[str], location: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise AtomicityError("E_ATOMICITY_SCHEMA", f"{location} must be an object")
    expected = set(required)
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        raise AtomicityError("E_ATOMICITY_SCHEMA", f"{location} missing fields: {', '.join(missing)}")
    if extra:
        raise AtomicityError("E_ATOMICITY_SCHEMA", f"{location} has unsupported fields: {', '.join(extra)}")
    return value


def _find_forbidden(value: Any, location: str = "$") -> Optional[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_ATOMICITY_FIELDS:
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


def load_and_validate_atomicity_review(
    review_path: Path,
    *,
    repo_root: Path,
    expected_proposal_artifact_path: Optional[Path] = None,
) -> Dict[str, Any]:
    review_path = review_path.resolve()
    payload = _read_json(review_path)
    forbidden = _find_forbidden(payload)
    if forbidden:
        raise AtomicityError("E_ATOMICITY_AUTHORITY", f"identity/truth authority is forbidden at {forbidden}")
    review = _require_exact_keys(
        payload,
        {"schemaVersion", "reviewVersion", "sourceId", "proposalArtifactPath", "proposalArtifactHash", "reviews", "reviewEvidence"},
        "$",
    )
    if review["schemaVersion"] != SCHEMA_VERSION:
        raise AtomicityError("E_ATOMICITY_SCHEMA_VERSION", f"expected {SCHEMA_VERSION}")
    if review["reviewVersion"] != REVIEW_VERSION:
        raise AtomicityError("E_ATOMICITY_REVIEW_VERSION", f"expected {REVIEW_VERSION}")

    proposal_path = _resolve_repo_path(repo_root, review["proposalArtifactPath"], "proposalArtifactPath")
    if expected_proposal_artifact_path is not None and proposal_path != expected_proposal_artifact_path.resolve():
        raise AtomicityError("E_ATOMICITY_PROPOSAL_ARTIFACT", "atomicity review references a different proposal artifact")
    if not proposal_path.is_file():
        raise AtomicityError("E_ATOMICITY_PROPOSAL_ARTIFACT_MISSING", f"proposal artifact does not exist: {proposal_path}")
    actual_proposal_hash = sha256_file(proposal_path)
    if actual_proposal_hash != review["proposalArtifactHash"]:
        raise AtomicityError(
            "E_ATOMICITY_PROPOSAL_HASH",
            f"declared {review['proposalArtifactHash']}, got {actual_proposal_hash}",
        )
    proposal_boundary = _load_proposal_boundary(repo_root)
    try:
        proposal_artifact = proposal_boundary.load_and_validate_artifact(proposal_path, repo_root=repo_root)
    except proposal_boundary.ProposalError as exc:
        raise AtomicityError(exc.code, exc.message) from exc
    expected_source_id = f"src-{proposal_artifact['source']['sha256'][:20]}"
    if review["sourceId"] != expected_source_id:
        raise AtomicityError("E_ATOMICITY_SOURCE", "sourceId does not match proposal artifact source provenance")

    reviews = review["reviews"]
    if not isinstance(reviews, list) or not reviews:
        raise AtomicityError("E_ATOMICITY_REVIEWS", "reviews must be a non-empty array")
    review_map: Dict[str, Dict[str, Any]] = {}
    required_review_fields = {"proposalId", "atomicityClassification", "reviewStatus"}
    for index, raw_record in enumerate(reviews):
        location = f"$.reviews[{index}]"
        record = _require_exact_keys(raw_record, required_review_fields, location)
        proposal_id = record["proposalId"]
        if not isinstance(proposal_id, str) or not proposal_id.startswith("proposal-"):
            raise AtomicityError("E_ATOMICITY_PROPOSAL_ID", f"{location}.proposalId must begin with proposal-")
        if proposal_id in review_map:
            raise AtomicityError("E_ATOMICITY_DUPLICATE_REVIEW", f"duplicate review for {proposal_id}")
        classification = record["atomicityClassification"]
        if classification not in CLASSIFICATIONS:
            raise AtomicityError("E_ATOMICITY_CLASSIFICATION", f"unsupported classification {classification!r}")
        if record["reviewStatus"] not in REVIEW_STATUSES:
            raise AtomicityError("E_ATOMICITY_REVIEW_STATUS", f"unsupported reviewStatus {record['reviewStatus']!r}")
        review_map[proposal_id] = dict(record)

    proposal_ids = {proposal["proposalId"] for proposal in proposal_artifact["itemProposals"]}
    missing = sorted(proposal_ids - set(review_map))
    extra = sorted(set(review_map) - proposal_ids)
    if missing:
        raise AtomicityError("E_ATOMICITY_REVIEW_MISSING", f"proposals lack atomicity review: {', '.join(missing)}")
    if extra:
        raise AtomicityError("E_ATOMICITY_REVIEW_UNKNOWN", f"reviews reference unknown proposals: {', '.join(extra)}")

    evidence = _require_exact_keys(
        review["reviewEvidence"],
        {"evidenceType", "sourceSnapshotPath", "reviewerRole", "note"},
        "$.reviewEvidence",
    )
    if evidence["evidenceType"] != "manual_source_geometry_review" or evidence["reviewerRole"] != "human_reviewer":
        raise AtomicityError("E_ATOMICITY_REVIEW_EVIDENCE", "atomicity review requires manual source geometry evidence")
    if not isinstance(evidence["note"], str) or not evidence["note"]:
        raise AtomicityError("E_ATOMICITY_REVIEW_EVIDENCE", "reviewEvidence.note must be non-empty")
    evidence_source = _resolve_repo_path(repo_root, evidence["sourceSnapshotPath"], "reviewEvidence.sourceSnapshotPath")
    proposal_source = _resolve_repo_path(repo_root, proposal_artifact["source"]["sourcePath"], "proposalArtifact.source.sourcePath")
    if evidence_source != proposal_source:
        raise AtomicityError("E_ATOMICITY_REVIEW_EVIDENCE", "review evidence must reference the exact proposal source snapshot")

    return {
        "review": review,
        "reviewMap": review_map,
        "proposalArtifact": proposal_artifact,
        "proposalArtifactPath": proposal_path,
    }


def require_reviewed_classification(
    review_result: Dict[str, Any],
    proposal_id: str,
) -> str:
    record = review_result["reviewMap"].get(proposal_id)
    if record is None:
        raise AtomicityError("E_ATOMICITY_REVIEW_MISSING", f"proposal lacks atomicity review: {proposal_id}")
    if record["reviewStatus"] != "reviewed_consistent":
        raise AtomicityError(
            "E_ATOMICITY_NOT_REVIEWED",
            f"{proposal_id} cannot be admitted with reviewStatus={record['reviewStatus']}",
        )
    classification = record["atomicityClassification"]
    if classification in BLOCKED_CLASSIFICATIONS:
        raise AtomicityError("E_ATOMICITY_BLOCKED_CLASS", f"{proposal_id} is fail-closed as {classification}")
    return classification


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviews", nargs="+", type=Path)
    args = parser.parse_args(argv)
    failed = False
    for path in args.reviews:
        try:
            result = load_and_validate_atomicity_review(path, repo_root=_repo_root())
        except AtomicityError as exc:
            failed = True
            print(f"[FAIL] {path}: {exc.code}: {exc.message}")
            continue
        counts: Dict[str, int] = {}
        for record in result["reviewMap"].values():
            key = record["atomicityClassification"]
            counts[key] = counts.get(key, 0) + 1
        print(f"[PASS] {path}: proposals={len(result['reviewMap'])} classifications={counts}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
