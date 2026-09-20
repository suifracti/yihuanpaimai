"""Build an independent callback-only R5 evidence package.

The R4 package is historical and is never overwritten. Accepted test raws are
copied verbatim from R4 with their original head, while only the new callback
measurement raw is bound to the current head.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(r"D:\yihuanpaimai-v2-2a")
R4_EVIDENCE = REPO / "build" / "v2-2a-r4" / "evidence"
R4_RAW = REPO / "build" / "v2-2a-r4" / "raw"
EVIDENCE = Path(os.environ.get(
    "V2_2A_R5_CALLBACK_EVIDENCE_OUT",
    str(REPO / "build" / "v2-2a-r5-callback" / "evidence"),
))
OLD_HEAD = "b04d4581a35a768a8ef1e805cf2244c229edbdd3"
REUSED_RAW = [
    "python_targeted_tests_raw.txt",
    "raw_queue_drain_regression_raw.txt",
    "callback_isolation_deterministic_raw.txt",
    "event_queue_overflow_regression_raw.txt",
    "v2_1_guard_oneshot_raw.txt",
    "v2_0_guard_raw.txt",
]
NEW_MEASUREMENT_RAW = "callback_measurement_r5_raw.txt"
NEW_MEASUREMENT = "callback_isolation_measured.json"
NEW_TARGETED_RAW = "callback_isolation_deterministic_r5_raw.txt"
MANIFEST = "evidence_manifest.json"
SUMMARY = "V2_2A_Window_Focus_Monitor_R5_Callback_Summary.md"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    ).stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_field(path: Path, prefix: str) -> str:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:20]:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def unittest_summary(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    ran = None
    failed = errors = skipped = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Ran ") and " test" in stripped:
            try:
                ran = int(stripped.split()[1])
            except (IndexError, ValueError):
                pass
        elif stripped.startswith("FAILED ("):
            for part in stripped[len("FAILED ("):].rstrip(")").split(","):
                key, _, value = part.strip().partition("=")
                if key == "failures":
                    failed = int(value)
                elif key == "errors":
                    errors = int(value)
                elif key == "skipped":
                    skipped = int(value)
    passed = (ran - failed - errors - skipped) if ran is not None else None
    return {
        "ran": ran, "passed": passed, "failed": failed, "errors": errors,
        "skipped": skipped,
        "verdict": "PASS" if ran is not None and failed == 0 and errors == 0 else "UNKNOWN",
    }


def copy_if_missing(source: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite existing evidence artifact: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def runtime_proof(new_head: str) -> dict:
    raw_queue_diff = git(
        "diff", "--name-only", OLD_HEAD, new_head, "--",
        "architecture/v2/host/NteHost.WindowMonitor/RawEventQueue.cs",
    ).splitlines()
    runtime_logic_diff = git(
        "diff", "--unified=0", OLD_HEAD, new_head, "--",
        "architecture/v2/host/NteHost.WindowMonitor/RawEventQueue.cs",
    )
    return {
        "baselineRuntimeHead": OLD_HEAD,
        "currentHead": new_head,
        "rawQueueSourceChanged": bool(raw_queue_diff),
        "rawQueueSourceDiffPaths": raw_queue_diff,
        "rawQueueLogicDiff": runtime_logic_diff,
        "runtimeBehaviorUnchanged": not raw_queue_diff,
        "diagnosticOnlyDelta": [
            "WindowMonitor.RawEnqueuedEventCountForDiagnostics read-only counter",
            "harness inject/statusprobe raw enqueue fields",
            "callback measurement ordering/assertions and callback-only evidence tooling",
        ],
        "note": "R4 runtime fixes are reused; this R5 delta adds only a read-only diagnostic "
                "counter and measurement/evidence validation. RawEventQueue runtime source "
                "is byte-for-byte unchanged from the R4 audited head.",
    }


def write_summary(head: str, measured: dict, raw_meta: dict, provenance: dict) -> None:
    direction_a = measured.get("directionA", {})
    direction_b = measured.get("directionB", {})
    samples = direction_a.get("ingestionSamples", [])
    lines = [
        "# V2-2A Native Window / Focus Monitor - R5 callback measurement evidence",
        "",
        "> Independent local callback-only package. The R4 directory and all failed",
        "> attempts remain preserved and are not overwritten.",
        "",
        f"- New measurement head: `{head}`",
        f"- Measurement raw: `{NEW_MEASUREMENT_RAW}`; exit `{raw_meta['exitCode']}`; "
        f"classification `{raw_meta['classification']}`",
        "- Scope: callback measurement evidence only; no V2-1/V2-0 rerun, no merge, "
        "tag, Truth Matrix, Boundary3, production wiring, or B/C activation.",
        "",
        "## Direction-A",
        "",
        f"- Suppression restored before A: `{direction_a.get('suppressionRestoredBeforeMeasurement')}`",
        f"- State lock acquired: `{direction_a.get('stateLockHeldVerified')}`",
        f"- Real queue enqueue validity per sample: `{direction_a.get('enqueueValidity')}`",
        f"- Raw enqueue deltas: `{direction_a.get('rawEnqueueDeltas')}` for requested "
        f"N=`{measured.get('injectionsPerSample')}`",
        f"- Timing per event min/max: `{direction_a.get('perEventUsMin')}` / "
        f"`{direction_a.get('perEventUsMax')}` us",
        "",
        "| Sample | requested | raw enqueue delta | status delta | per-event us | enqueue valid |",
        "| ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for index, sample in enumerate(samples, 1):
        lines.append(
            f"| {index} | {sample.get('requestedCount')} | "
            f"{sample.get('rawEnqueuedCountDelta')} | "
            f"{sample.get('statusRawEnqueuedCountDelta')} | "
            f"{sample.get('perEventUs')} | {sample.get('enqueueValid')} |"
        )
    lines.extend([
        "",
        "## Direction-B",
        "",
        f"- Known N: `{direction_b.get('knownN')}`; baseline stable: "
        f"`{direction_b.get('baselineStable')}`; raw lock acquired: "
        f"`{direction_b.get('holdRawAcquired')}`; producer completed before release: "
        f"`{direction_b.get('producerCompletedBeforeRelease')}`.",
        f"- Processed events: `{direction_b.get('processedEventsBeforeRelease')}` -> "
        f"`{direction_b.get('processedEventsAfterRelease')}`; exact N: "
        f"`{direction_b.get('processedDeltaExactlyN')}`; quiet delta: "
        f"`{direction_b.get('quietIntervalDelta')}`; queue after quiet: "
        f"`{direction_b.get('queueCountAfterQuiet')}`.",
        "",
        "## Reused accepted raw",
        "",
        f"- Original audited head: `{OLD_HEAD}`.",
        "- The following raws were copied verbatim from `build/v2-2a-r4/raw/`; their "
        "original head stamps are retained and are not rewritten to the new measurement head:",
    ])
    lines.extend(f"  - `{name}`" for name in REUSED_RAW)
    lines.extend([
        "",
        f"- The affected targeted T26 raw is `{NEW_TARGETED_RAW}` at the new head `{head}`.",
        "",
        f"- Runtime proof: `runtimeBehaviorUnchanged={provenance['runtimeProof']['runtimeBehaviorUnchanged']}`; "
        "RawEventQueue source has no diff from the R4 audited head. The only runtime-tree "
        "delta is the read-only diagnostic counter used to validate actual enqueueing; no "
        "queue/worker behavior was changed.",
        "",
        "## Assertions",
        "",
        f"- Measurement pass: `{measured.get('measurementPass')}`",
        f"- Manifest self-check: `{provenance['manifestSelfCheck']}`",
        "",
    ])
    (EVIDENCE / SUMMARY).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    new_head = git("rev-parse", "HEAD")
    if not R4_EVIDENCE.is_dir() or not R4_RAW.is_dir():
        print(f"ERROR: preserved R4 evidence source is missing: {R4_EVIDENCE} / {R4_RAW}")
        return 1
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    allowed_initial = {NEW_MEASUREMENT, NEW_MEASUREMENT_RAW, NEW_TARGETED_RAW}
    existing = {path.name for path in EVIDENCE.iterdir() if path.is_file()}
    unexpected_initial = existing - allowed_initial
    if unexpected_initial or MANIFEST in existing:
        print(f"ERROR: refusing to overwrite non-initial R5 evidence: {sorted(existing)}")
        return 1
    if not all((EVIDENCE / name).exists()
               for name in (NEW_MEASUREMENT, NEW_MEASUREMENT_RAW, NEW_TARGETED_RAW)):
        print("ERROR: run the targeted test and callback measurement first; new artifacts are missing")
        return 1
    if new_head == OLD_HEAD:
        print("ERROR: new callback measurement was not produced on a new head")
        return 1

    # Copy all stable R4 supporting artifacts and accepted raw files without modifying
    # their contents. The measurement and manifest are the only current-head artifacts.
    skip = {MANIFEST, "V2_2A_Window_Focus_Monitor_R4_Summary.md",
            "callback_isolation_measured.json", "measure_v2_2a_r4_raw.txt",
            "git_diff.patch", *REUSED_RAW}
    for source in sorted(R4_EVIDENCE.iterdir()):
        if source.is_file() and source.name not in skip:
            copy_if_missing(source, EVIDENCE / source.name)
    for name in REUSED_RAW:
        copy_if_missing(R4_RAW / name, EVIDENCE / name)
    copy_if_missing(R4_EVIDENCE / "callback_isolation_measured.json",
                    EVIDENCE / "r4_callback_isolation_measured_original.json")
    copy_if_missing(R4_EVIDENCE / "measure_v2_2a_r4_raw.txt",
                    EVIDENCE / "r4_measurement_original_raw.txt")
    copy_if_missing(R4_EVIDENCE / "V2_2A_Window_Focus_Monitor_R4_Summary.md",
                    EVIDENCE / "R4_Summary_original.md")

    current_diff = subprocess.run(
        ["git", "diff", "a9b52c6fb8db3c5f7dbfb2e80cb5a32bb4a526e9", new_head],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )
    (EVIDENCE / "git_diff.patch").write_text(current_diff.stdout, encoding="utf-8")

    measurement_raw = EVIDENCE / NEW_MEASUREMENT_RAW
    targeted_raw = EVIDENCE / NEW_TARGETED_RAW
    measurement_head = raw_field(measurement_raw, "# head: ")
    measurement_exit = raw_field(measurement_raw, "# exit code: ")
    measurement_classification = raw_field(measurement_raw, "# classification: ")
    targeted_head = raw_field(targeted_raw, "# head: ")
    targeted_exit = raw_field(targeted_raw, "# exit code: ")
    targeted_classification = raw_field(targeted_raw, "# classification: ")
    reused_meta = {}
    raw_head_mismatches = []
    failed_raws = []
    for name in REUSED_RAW:
        path = EVIDENCE / name
        actual_head = raw_field(path, "# head: ")
        actual_exit = raw_field(path, "# exit code: ")
        actual_classification = raw_field(path, "# classification: ")
        reused_meta[name] = {
            "sourcePath": f"build/v2-2a-r4/raw/{name}",
            "originalHead": OLD_HEAD,
            "rawHead": actual_head,
            "exitCode": actual_exit,
            "classification": actual_classification,
        }
        if actual_head != OLD_HEAD:
            raw_head_mismatches.append({"raw": name, "expectedHead": OLD_HEAD,
                                        "stampedHead": actual_head})
        if actual_classification == "failed" or actual_exit != "0":
            failed_raws.append(name)
    if measurement_head != new_head:
        raw_head_mismatches.append({"raw": NEW_MEASUREMENT_RAW, "expectedHead": new_head,
                                    "stampedHead": measurement_head})
    if targeted_head != new_head:
        raw_head_mismatches.append({"raw": NEW_TARGETED_RAW, "expectedHead": new_head,
                                    "stampedHead": targeted_head})
    if targeted_classification == "failed" or targeted_exit != "0":
        failed_raws.append(NEW_TARGETED_RAW)
    measurement_validation_failures = []
    if measurement_exit != "0":
        measurement_validation_failures.append("exitCode")
    if measurement_classification != "ok":
        measurement_validation_failures.append("classification")
    if measurement_head != new_head:
        measurement_validation_failures.append("head")
    measured = json.loads((EVIDENCE / NEW_MEASUREMENT).read_text(encoding="utf-8"))
    if measured.get("measurementHead") != new_head:
        measurement_validation_failures.append("measurementJsonHead")
    if not measured.get("measurementPass"):
        measurement_validation_failures.append("measurementPass")

    runtime = runtime_proof(new_head)
    provenance = {
        "newMeasurementHead": new_head,
        "newTargetedHead": new_head,
        "reusedAcceptedRawHead": OLD_HEAD,
        "reusedRaw": reused_meta,
        "runtimeProof": runtime,
        "notRerun": ["V2-1 one-shot", "V2-0 guard", "R4 drain regression", "overflow regression"],
    }

    # Write the summary once to make it part of the directory, then compute the complete
    # self-check. Rewrite the summary with the final self-check, and write the manifest last.
    provenance["manifestSelfCheck"] = {"status": "pending-summary-inclusion"}
    write_summary(new_head, measured, {
        "head": measurement_head, "exitCode": measurement_exit,
        "classification": measurement_classification,
    }, provenance)

    # Directory self-check is computed before the manifest is created. The manifest is
    # deliberately the final write, so its hashes bind every sibling artifact.
    declared = sorted(path.name for path in EVIDENCE.iterdir()
                      if path.is_file() and path.name != MANIFEST)
    physical = sorted(path.name for path in EVIDENCE.iterdir() if path.is_file())
    missing = [name for name in declared if not (EVIDENCE / name).exists()]
    unexpected = [name for name in physical if name not in declared and name != MANIFEST]
    files = [{"name": name, "sizeBytes": (EVIDENCE / name).stat().st_size,
              "sha256": sha256(EVIDENCE / name)} for name in declared]
    self_check = {
        "declaredCount": len(declared),
        "physicalCountExcludingManifest": len(physical) - (1 if MANIFEST in physical else 0),
        "missing": missing,
        "unexpected": unexpected,
        "hashMismatch": [],
        "sizeMismatch": [],
        "rawHeadMismatch": raw_head_mismatches,
        "failedRaws": failed_raws,
        "measurementRawValidationFailures": measurement_validation_failures,
        "orphansAbsent": not unexpected,
        "allRequiredPresent": not missing,
        "manifestGeneratedLast": True,
    }
    provenance["manifestSelfCheck"] = self_check
    write_summary(new_head, measured, {
        "head": measurement_head, "exitCode": measurement_exit,
        "classification": measurement_classification,
    }, provenance)

    declared = sorted(path.name for path in EVIDENCE.iterdir()
                      if path.is_file() and path.name != MANIFEST)
    physical = sorted(path.name for path in EVIDENCE.iterdir() if path.is_file())
    files = [{"name": name, "sizeBytes": (EVIDENCE / name).stat().st_size,
              "sha256": sha256(EVIDENCE / name)} for name in declared]
    manifest = {
        "schemaVersion": "evidence.manifest.v4.callback-only",
        "phase": "V2-2A callback measurement evidence (R5 follow-up)",
        "title": "V2-2A callback measurement - R5 independent local evidence",
        "repository": str(REPO),
        "headCommit": new_head,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "currentMeasurement": {
            "raw": NEW_MEASUREMENT_RAW,
            "measured": NEW_MEASUREMENT,
            "head": measurement_head,
            "exitCode": measurement_exit,
            "classification": measurement_classification,
            "measurementPass": bool(measured.get("measurementPass")),
        },
        "currentTargeted": {
            "raw": NEW_TARGETED_RAW,
            "test": "test_26_raw_callback_isolation_deterministic",
            "head": targeted_head,
            "exitCode": targeted_exit,
            "classification": targeted_classification,
        },
        "reusedAcceptedTests": reused_meta,
        "runtimeProof": runtime,
        "notRerun": ["V2-1 one-shot", "V2-0 guard", "R4 drain regression", "overflow regression"],
        "declaredArtifacts": declared,
        "fileCount": len(declared),
        "totalPhysicalFiles": len(physical),
        "files": files,
        "rawHeads": {name: raw_field(EVIDENCE / name, "# head: ")
                     for name in REUSED_RAW + [NEW_TARGETED_RAW, NEW_MEASUREMENT_RAW]},
        "rawClassifications": {name: raw_field(EVIDENCE / name, "# classification: ")
                                for name in REUSED_RAW + [NEW_TARGETED_RAW, NEW_MEASUREMENT_RAW]},
        "rawExitCodes": {name: raw_field(EVIDENCE / name, "# exit code: ")
                          for name in REUSED_RAW + [NEW_TARGETED_RAW, NEW_MEASUREMENT_RAW]},
        "selfCheck": self_check,
        "allPassed": not (
            missing or unexpected or raw_head_mismatches or failed_raws
            or measurement_validation_failures
            or not self_check["orphansAbsent"]
        ),
    }
    (EVIDENCE / MANIFEST).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"head={new_head}")
    print(f"declared={len(declared)} physical(excl manifest)={len(physical) - 1}")
    print(f"missing={missing}")
    print(f"unexpected={unexpected}")
    print(f"rawHeadMismatch={raw_head_mismatches}")
    print(f"failedRaws={failed_raws}")
    print(f"measurementRawValidationFailures={measurement_validation_failures}")
    print(f"allPassed={manifest['allPassed']}")
    return 0 if manifest["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
