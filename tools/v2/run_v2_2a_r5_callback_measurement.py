"""Run only the affected callback measurement and preserve its complete raw output.

This runner deliberately does not invoke V2-2A acceptance tests, the overflow
measurement, V2-1, or V2-0. Those already-accepted raw artifacts are reused by the
independent R5 callback evidence builder with their original heads intact.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

REPO = Path(r"D:\yihuanpaimai-v2-2a")
EVIDENCE = Path(os.environ.get(
    "V2_2A_R5_CALLBACK_EVIDENCE_OUT",
    str(REPO / "build" / "v2-2a-r5-callback" / "evidence"),
))
WORK = Path(os.environ.get(
    "V2_2A_R5_CALLBACK_MEASURE_WORK",
    str(REPO / "build" / "v2-2a-r5-callback" / "measure_work"),
))
RAW = EVIDENCE / "callback_measurement_r5_raw.txt"

sys.path.insert(0, str(REPO / "tools" / "v2"))
from dotnet_env import build_env  # noqa: E402
from measure_v2_2a_r1 import measure_isolation  # noqa: E402


def repo_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(REPO), capture_output=True,
        text=True, check=False,
    )
    return result.stdout.strip()


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-u", "tools/v2/run_v2_2a_r5_callback_measurement.py"]
    build_command = [
        "dotnet", "build",
        "architecture/v2/host/window_monitor_harness/WindowMonitorHarness.csproj",
        "-c", "Release", "--nologo", "-v", "q",
    ]
    head_before = repo_head()
    build = subprocess.run(
        build_command, cwd=str(REPO), env=build_env(), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=900,
    )

    output: list[str] = [
        f"$ {' '.join(command)}",
        f"# cwd: {REPO}",
        f"# head before: {head_before}",
        f"# build command: {' '.join(build_command)}",
        f"# build exit code: {build.returncode}",
        "-" * 78,
        "BUILD STDOUT",
        build.stdout,
        "-" * 78,
        "BUILD STDERR",
        build.stderr,
        "-" * 78,
    ]

    exit_code = build.returncode
    measured = None
    if build.returncode == 0:
        try:
            measured = measure_isolation(WORK / "isolation", delay_ms=120, injections=400)
            (EVIDENCE / "callback_isolation_measured.json").write_text(
                json.dumps({
                    "schemaVersion": "v2.2a.callback.isolation.measured.v3",
                    "measurementHead": repo_head(),
                    **measured,
                }, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(measured, indent=2))
            output.extend([
                "MEASUREMENT JSON",
                json.dumps(measured, indent=2),
            ])
            if not measured.get("measurementPass"):
                exit_code = 1
        except Exception:
            exit_code = 1
            error = traceback.format_exc()
            output.extend(["MEASUREMENT EXCEPTION", error])
            print(error, file=sys.stderr)
    else:
        exit_code = exit_code or 1

    head_after = repo_head()
    if head_after != head_before:
        exit_code = 1
        output.append(f"ERROR: head moved during measurement: {head_before} -> {head_after}")

    classification = "ok" if exit_code == 0 else "failed"
    output[2:2] = [
        f"# head: {head_after}",
        f"# exit code: {exit_code}",
        f"# classification: {classification}",
    ]
    RAW.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"measurement exit={exit_code} classification={classification} raw={RAW}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
