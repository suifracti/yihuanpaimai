# -*- coding: utf-8 -*-
"""Build the clean, source-hash-bound I1 offline evidence bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


EXPECTED_EVIDENCE = [
    "contract.md",
    "scenario_matrix.json",
    "source_map.json",
    "integration_summary.json",
    "integration_raw.ndjson",
    "build_identity.json",
    "exit_codes.json",
    "acceptance_matrix.json",
]

INTEGRATION_SOURCE_FILES = [
    "architecture/v2/integration/NteHost.Integration/NteHost.Integration.csproj",
    "architecture/v2/integration/NteHost.Integration/IntegrationContracts.cs",
    "architecture/v2/integration/NteHost.Integration/AWindowFocusAdapter.cs",
    "architecture/v2/integration/NteHost.Integration/IntegrationCoordinator.cs",
    "architecture/v2/integration/NteHost.Integration/CArbitratedRawInputBackend.cs",
    "architecture/v2/integration/verifier/NteIntegrationVerifier.csproj",
    "architecture/v2/integration/verifier/Program.cs",
    "architecture/v2/integration/verifier/FakeWindowObservationSource.cs",
    "architecture/v2/integration/verifier/CallbackRawInputBackend.cs",
    "architecture/v2/integration/contracts/V2-2-INTEGRATION-I1_OFFLINE_CONTRACT.md",
    "architecture/v2/integration/contracts/integration_scenarios.json",
    "tools/v2/build_v2_2_integration_source_map.py",
    "tools/v2/build_v2_2_integration_evidence.py",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(repo: Path, relative: str) -> dict[str, Any]:
    path = repo / relative
    return {
        "path": relative.replace("\\", "/"),
        "size": path.stat().st_size,
        "sha256": sha256(path),
    }


def external_file_record(path: Path, label: str) -> dict[str, Any]:
    return {
        "path": label,
        "absolutePath": str(path),
        "size": path.stat().st_size,
        "sha256": sha256(path),
    }


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--source-map", required=True)
    parser.add_argument(
        "--build-root",
        required=False,
        help="Optional external BaseOutputPath used for the final build.",
    )
    parser.add_argument("--build-exit", required=True, type=int)
    parser.add_argument("--verifier-exit", required=True, type=int)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    evidence = Path(args.evidence).resolve()
    summary = json.loads((evidence / "integration_summary.json").read_text(encoding="utf-8"))
    source_map = json.loads((evidence / "source_map.json").read_text(encoding="utf-8"))
    scenario_matrix = json.loads((evidence / "scenario_matrix.json").read_text(encoding="utf-8"))

    imported_paths = [
        item["path"]
        for component in source_map["components"]
        for item in component["files"]
    ]
    source_paths = list(dict.fromkeys(imported_paths + INTEGRATION_SOURCE_FILES))
    missing_sources = [relative for relative in source_paths if not (repo / relative).exists()]
    source_records = [file_record(repo, relative) for relative in source_paths if (repo / relative).exists()]

    assembly_paths = [
        "architecture/v2/integration/verifier/bin/Debug/net8.0/NteIntegrationVerifier.dll",
        "architecture/v2/integration/NteHost.Integration/bin/Debug/net8.0/NteHost.Integration.dll",
        "architecture/v2/host/NteHost.WindowMonitor/bin/Debug/net8.0/NteHost.WindowMonitor.dll",
        "architecture/v2/input/NteHost.Input/bin/Debug/net8.0/NteHost.Input.dll",
        "architecture/v2/host/NteHost.Freeze/bin/Debug/net8.0/NteHost.Freeze.dll",
    ]
    if args.build_root:
        build_root = Path(args.build_root).resolve()
        assembly_names = [Path(relative).name for relative in assembly_paths]
        build_assemblies = [
            (build_root / "Debug" / "net8.0" / name, f"external-build/Debug/net8.0/{name}")
            for name in assembly_names
        ]
    else:
        build_root = None
        build_assemblies = [
            (repo / relative, relative)
            for relative in assembly_paths
        ]
    build_identity = {
        "configuration": "Debug",
        "targetFramework": "net8.0",
        "buildRoot": str(build_root) if build_root else "repository-default-output-paths",
        "dotnetVersion": subprocess.check_output(["dotnet", "--version"], text=True).strip(),
        "repository": str(repo),
        "branch": git(repo, "branch", "--show-current"),
        "head": git(repo, "rev-parse", "HEAD"),
        "assemblies": [
            external_file_record(path, label) if build_root else file_record(repo, label)
            for path, label in build_assemblies
            if path.exists()
        ],
    }
    missing_build_assemblies = [
        label
        for path, label in build_assemblies
        if not path.exists()
    ]
    (evidence / "build_identity.json").write_text(
        json.dumps(build_identity, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    exit_codes = {"build": args.build_exit, "verifier": args.verifier_exit}
    (evidence / "exit_codes.json").write_text(
        json.dumps(exit_codes, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    raw_records = sum(1 for _ in (evidence / "integration_raw.ndjson").open(encoding="utf-8"))
    matrix = {
        "schemaVersion": "v2.2.integration.i1.acceptance-matrix.v1",
        "scope": "Integration I1 offline only",
        "sourceHeads": summary["sourceHeads"],
        "commonBase": summary["commonBase"],
        "verifier": {
            "executed": summary["totalScenarios"],
            "passed": summary["passedScenarios"],
            "failed": summary["failedScenarios"],
            "allPassed": summary["allPassed"],
            "scenarioIds": [item["Id"] for item in summary["results"]],
        },
        "rawRecords": raw_records,
        "scenarioMatrixCount": len(scenario_matrix["scenarios"]),
        "sourceImport": {
            "allImportedFilesMatch": source_map["allImportedFilesMatch"],
            "missingFiles": source_map["missingFiles"],
            "hashMismatches": source_map["hashMismatches"],
        },
        "productionReachable": False,
        "realInputExecuted": False,
    }
    (evidence / "acceptance_matrix.json").write_text(
        json.dumps(matrix, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    expected_files = sorted(EXPECTED_EVIDENCE)
    actual_files = sorted(
        path.name for path in evidence.iterdir()
        if path.is_file() and path.name != "evidence_manifest.json"
    )
    missing_evidence = [name for name in expected_files if not (evidence / name).exists()]
    unexpected_evidence = [name for name in actual_files if name not in expected_files]
    raw_worktree_status = git(repo, "status", "--short").splitlines()
    generated_status = []
    worktree_status = []
    for line in raw_worktree_status:
        status_path = line[3:].replace("\\", "/") if len(line) >= 4 else line
        path_parts = set(status_path.split("/"))
        if "bin" in path_parts or "obj" in path_parts:
            generated_status.append(line)
        else:
            worktree_status.append(line)

    manifest = {
        "schemaVersion": "v2.2.integration.i1.evidence-manifest.v1",
        "phase": "V2-2_INTEGRATION_I1_OFFLINE",
        "repository": str(repo),
        "branch": git(repo, "branch", "--show-current"),
        "head": git(repo, "rev-parse", "HEAD"),
        "parent": git(repo, "rev-parse", "HEAD^"),
        "commonBase": summary["commonBase"],
        "sourceHeads": summary["sourceHeads"],
        "worktreeStatus": worktree_status,
        "generatedBuildArtifactsExcludedFromStatus": generated_status,
        "productionReachable": False,
        "realInputExecuted": False,
        "fakeSourceOnly": True,
        "fakeObserverOnly": True,
        "fakeActuatorOnly": True,
        "exitCodes": exit_codes,
        "expectedEvidenceFiles": expected_files,
        "missingEvidenceFiles": missing_evidence,
        "unexpectedEvidenceFiles": unexpected_evidence,
        "missingBuildAssemblies": missing_build_assemblies,
        "expectedSourceFiles": source_paths,
        "missingSourceFiles": missing_sources,
        "sourceFiles": source_records,
        "acceptanceMatrix": matrix,
        "clean": (
            not missing_evidence
            and not unexpected_evidence
            and not missing_sources
            and not missing_build_assemblies
            and not worktree_status
            and source_map["allImportedFilesMatch"]
            and summary["allPassed"]
            and args.build_exit == 0
            and args.verifier_exit == 0
        ),
    }
    (evidence / "evidence_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({
        "head": manifest["head"],
        "clean": manifest["clean"],
        "sources": len(source_records),
        "evidence": len(expected_files),
        "missing": missing_evidence + missing_sources,
        "unexpectedEvidence": unexpected_evidence,
    }, ensure_ascii=False))
    return 0 if manifest["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
