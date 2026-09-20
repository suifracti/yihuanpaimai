"""Run the narrow V2-2A R4 acceptance set and preserve untouched raw output.

The output directory is independent from every earlier review bundle. Each raw file
records its exact command, checkout head, exit code, and classification.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(r"D:\yihuanpaimai-v2-2a")
OUT = Path(os.environ.get("V2_2A_R4_RAW_OUT", str(REPO / "build" / "v2-2a-r4" / "raw")))
sys.path.insert(0, str(REPO / "tools" / "v2"))
from dotnet_env import build_env  # noqa: E402


def repo_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                            capture_output=True, text=True, check=False)
    return result.stdout.strip()


def dirty_paths() -> list[str]:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO),
                            capture_output=True, text=True, check=False)
    return [line for line in result.stdout.splitlines() if line.strip()]


def run_capture(args: list[str], name: str, timeout: int = 2400) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(args, cwd=str(REPO), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout,
                            env=build_env())
    combined = result.stdout + result.stderr
    only_independent_v2_1_debt = (
        "INDEPENDENT V2-1 DEBT" in combined
        and "FAILED (" not in combined
        and "ERRORS" not in combined
    )
    classification = "ok" if result.returncode == 0 else (
        "independent" if only_independent_v2_1_debt else "failed")
    payload = (
        f"$ {' '.join(args)}\n"
        f"# cwd: {REPO}\n"
        f"# head: {repo_head()}\n"
        f"# exit code: {result.returncode}\n"
        f"# classification: {classification}\n"
        f"{'-' * 78}\n"
        f"{result.stdout}\n"
        f"{'-' * 78} STDERR {'-' * 68}\n"
        f"{result.stderr}\n"
    )
    (OUT / name).write_text(payload, encoding="utf-8")
    print(f"[{result.returncode}/{classification}] {name}")
    return classification


def main() -> int:
    py = sys.executable
    head_before = repo_head()
    print(f"head before run: {head_before}")
    print(f"dirty paths: {dirty_paths() if dirty_paths() else 'none'}")

    targeted = "tests.test_v2_2a_window_focus_monitor"
    test_class = "tests.test_v2_2a_window_focus_monitor.V22AWindowFocusMonitorTests"
    steps = [
        ([py, "-m", "unittest", targeted, "-v"], "python_targeted_tests_raw.txt"),
        ([py, "-m", "unittest", f"{test_class}.test_27_"
                                  "raw_event_queue_drains_once_and_reports_overflow_delta_once", "-v"],
         "raw_queue_drain_regression_raw.txt"),
        ([py, "-m", "unittest", f"{test_class}.test_26_"
                                  "raw_callback_isolation_deterministic", "-v"],
         "callback_isolation_deterministic_raw.txt"),
        ([py, "-m", "unittest", f"{test_class}.test_25_"
                                  "event_queue_overflow_is_not_a_latch", "-v"],
         "event_queue_overflow_regression_raw.txt"),
        ([py, "-m", "unittest", "tests.test_v2_1_host_supervisor", "-v"],
         "v2_1_guard_oneshot_raw.txt"),
        ([py, "-m", "unittest", "tests.test_v2_host_engine_contracts", "-v"],
         "v2_0_guard_raw.txt"),
    ]

    failures: list[str] = []
    independent: list[str] = []
    for command, name in steps:
        classification = run_capture(command, name)
        if classification == "failed":
            failures.append(name)
        elif classification == "independent":
            independent.append(name)

    head_after = repo_head()
    if head_after != head_before:
        print(f"ERROR: head moved during the acceptance run: {head_before} -> {head_after}")
        failures.append("head-moved-during-run")

    print(f"head after run: {head_after}")
    print("failures:", failures)
    print("independent_v2_1_debt:", independent)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
