# -*- coding: utf-8 -*-
"""Build a clean, hash-bound V2-2C offline evidence bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


EXPECTED_EVIDENCE_FILES = [
    "contract.md",
    "scenarios.json",
    "native_extension_expectations.json",
    "python_results.json",
    "native_results.json",
    "native_summary.json",
    "parity_report.json",
    "python_raw.ndjson",
    "native_raw.ndjson",
    "compare_raw.ndjson",
    "negative_probe_report.json",
    "negative_probe_raw.ndjson",
    "negative_probe_exit.json",
    "exit_codes.json",
    "acceptance_matrix.json",
]

SOURCE_FILES = [
    "architecture/v2/host/NteHost.Freeze/FreezeCoordinator.cs",
    "architecture/v2/host/NteHost.Freeze/FreezeEvents.cs",
    "architecture/v2/host/NteHost.Freeze/FreezeReasons.cs",
    "architecture/v2/host/NteHost.Freeze/FreezeTrace.cs",
    "architecture/v2/host/NteHost.Freeze/NteHost.Freeze.csproj",
    "architecture/v2/host/freeze_verifier/FreezeCoordinatorVerifier.cs",
    "architecture/v2/host/freeze_verifier/FreezeCoordinatorVerifier.csproj",
    "architecture/v2/host/freeze_parity/run_python_reference.py",
    "architecture/v2/host/freeze_parity/compare_results.py",
    "architecture/v2/host/freeze_parity/build_evidence_manifest.py",
    "architecture/v2/host/freeze_parity/scenarios.json",
    "architecture/v2/host/freeze_parity/native_extension_expectations.json",
    "architecture/v2/host/freeze_parity/V2-2C_FREEZE_COORDINATOR_CONTRACT.md",
    "core/warehouse_active_scan_freeze.py",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def file_record(path: Path, relative: str) -> dict[str, Any]:
    return {
        "path": relative.replace("\\", "/"),
        "size": path.stat().st_size,
        "sha256": sha256(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--native-exit", required=True, type=int)
    parser.add_argument("--python-exit", required=True, type=int)
    parser.add_argument("--compare-exit", required=True, type=int)
    parser.add_argument("--negative-probe-exit", required=True, type=int)
    parser.add_argument("--build-exit", required=True, type=int)
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    evidence = Path(args.evidence).resolve()
    native_summary = json.loads((evidence / "native_summary.json").read_text(encoding="utf-8"))
    parity = json.loads((evidence / "parity_report.json").read_text(encoding="utf-8"))
    native_results = json.loads((evidence / "native_results.json").read_text(encoding="utf-8"))
    python_results = json.loads((evidence / "python_results.json").read_text(encoding="utf-8"))
    negative_probe = json.loads((evidence / "negative_probe_report.json").read_text(encoding="utf-8"))
    native_scenarios = native_results.get("results", native_results.get("Results", []))

    matrix = {
        "schemaVersion": "v2.2c.freeze.acceptance-matrix.v2",
        "nativeVerifier": {
            "executed": native_summary["totalTests"],
            "passed": native_summary["passedTests"],
            "failed": native_summary["failedTests"],
            "allPassed": native_summary["allPassed"],
            "names": [item["Name"] for item in native_summary["results"]],
        },
        "pythonReferenceScenarios": {
            "executed": len(python_results["results"]),
            "unsupportedExpectedNativeExtensions": sum(
                1 for item in python_results["results"] if not item["supportedByPython"]
            ),
        },
        "nativeScenarioExecutions": {
            "executed": len(native_scenarios),
            "unsupported": sum(
                1 for item in native_scenarios if not item["supportedByNative"]
            ),
        },
        "stepwiseComparison": {
            "parityScenarios": parity["parityScenarioCount"],
            "nativeExtensionScenarios": parity["nativeExtensionScenarioCount"],
            "divergenceScenarios": parity["divergenceScenarioCount"],
            "expectedDifferences": parity["expectedDifferenceCount"],
            "observedExpectedDifferences": parity["expectedObservedDifferenceCount"],
            "unexpectedDifferences": parity["unexpectedDifferenceCount"],
            "allPassed": parity["allPassed"],
        },
        "negativeComparatorProbe": {
            "executed": True,
            "mutation": negative_probe.get("mutation"),
            "comparatorAllPassed": negative_probe.get("allPassed"),
            "actualExit": args.negative_probe_exit,
            "expectedExit": 1,
            "passed": args.negative_probe_exit == 1 and not negative_probe.get("allPassed", True),
        },
        "productionReachable": False,
        "realInputExecuted": False,
    }
    (evidence / "acceptance_matrix.json").write_text(
        json.dumps(matrix, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    exit_codes = {
        "build": args.build_exit,
        "nativeVerifier": args.native_exit,
        "pythonReference": args.python_exit,
        "stepwiseComparison": args.compare_exit,
        "negativeComparatorProbe": args.negative_probe_exit,
    }
    (evidence / "exit_codes.json").write_text(
        json.dumps(exit_codes, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (evidence / "negative_probe_exit.json").write_text(
        json.dumps({
            "expectedExit": 1,
            "actualExit": args.negative_probe_exit,
            "passed": args.negative_probe_exit == 1 and not negative_probe.get("allPassed", True),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    evidence_records = []
    for relative in EXPECTED_EVIDENCE_FILES:
        path = evidence / relative
        if path.exists():
            evidence_records.append(file_record(path, relative))

    actual_files = sorted(
        path.name for path in evidence.iterdir() if path.is_file() and path.name != "evidence_manifest.json"
    )
    expected_files = sorted(EXPECTED_EVIDENCE_FILES)
    # The two generated files are now present; this check remains explicit and deterministic.
    missing = [name for name in expected_files if not (evidence / name).exists()]
    unexpected = [name for name in actual_files if name not in expected_files]

    source_records = []
    missing_sources = []
    for relative in SOURCE_FILES:
        path = repo / relative
        if not path.exists():
            missing_sources.append(relative)
        else:
            source_records.append(file_record(path, relative))

    manifest = {
        "schemaVersion": "v2.2c.freeze.evidence-manifest.v2",
        "phase": "V2-2C_OFFLINE",
        "repo": str(repo),
        "branch": git(repo, "branch", "--show-current"),
        "head": git(repo, "rev-parse", "HEAD"),
        "parent": git(repo, "rev-parse", "HEAD^"),
        "worktreeStatus": git(repo, "status", "--short").splitlines(),
        "productionReachable": False,
        "realInputExecuted": False,
        "fakeActuatorOnly": True,
        "exitCodes": exit_codes,
        "expectedEvidenceFiles": expected_files,
        "missingEvidenceFiles": missing,
        "unexpectedEvidenceFiles": unexpected,
        "expectedSourceFiles": SOURCE_FILES,
        "missingSourceFiles": missing_sources,
        "sourceFiles": source_records,
        "evidenceFiles": evidence_records,
        "acceptanceMatrix": matrix,
        "clean": not missing and not unexpected and not missing_sources,
    }
    (evidence / "evidence_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({
        "head": manifest["head"],
        "clean": manifest["clean"],
        "missing": missing,
        "unexpected": unexpected,
        "missingSources": missing_sources,
    }, ensure_ascii=False))
    return 0 if manifest["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
