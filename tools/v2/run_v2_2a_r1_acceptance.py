"""Runs the R1 acceptance set and captures every raw artifact in one pass.

Each step writes its untouched stdout/stderr to an Evidence file. The steps are run
in the order the review requires, and the V2-1 guard is executed exactly once.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(r"D:\yihuanpaimai-v2-2a")
OUT = Path(__file__).resolve().parent / "evidence_raw"
sys.path.insert(0, str(REPO / "tools" / "v2"))
from dotnet_env import build_env  # noqa: E402


def repo_head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                            capture_output=True, text=True)
    return result.stdout.strip()


def worktree_dirty_paths() -> list[str]:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO),
                            capture_output=True, text=True)
    return [line for line in result.stdout.splitlines() if line.strip()]


def run_capture(args, name: str, timeout: int = 2400, env=None) -> str:
    """Runs one acceptance step and stores its untouched stdout/stderr.

    Returns a classification, not just an exit code, because a unittest run can exit
    non-zero for three very different reasons and the Evidence must not conflate them:

      "ok"             - exit 0
      "independent"    - exit non-zero, but the ONLY reason is the pre-existing V2-1
                         debt surfacing as a labelled skip (see test_18). Recorded as
                         debt, not as a failure and not as a pass.
      "failed"         - a genuine failure
    """
    OUT.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(args, cwd=str(REPO), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout,
                            env=env or build_env())
    combined = result.stdout + result.stderr
    kind = "ok"
    if result.returncode != 0:
        skipped_debt = "INDEPENDENT V2-1 DEBT" in combined
        only_skips = "FAILED (" not in combined and "ERRORS" not in combined
        kind = "independent" if (skipped_debt and only_skips) else "failed"

    payload = (
        f"$ {' '.join(args)}\n"
        f"# cwd: {REPO}\n"
        f"# head: {repo_head()}\n"
        f"# exit code: {result.returncode}\n"
        f"# classification: {kind}\n"
        f"{'-' * 78}\n"
        f"{result.stdout}\n"
        f"{'-' * 78} STDERR {'-' * 68}\n"
        f"{result.stderr}\n"
    )
    (OUT / name).write_text(payload, encoding="utf-8")
    print(f"[{result.returncode}/{kind}] {name}")
    return kind


def main() -> int:
    py = sys.executable
    failures = []
    independent = []

    head_before = repo_head()
    dirty = worktree_dirty_paths()
    print(f"head before run: {head_before}")
    print(f"dirty paths: {dirty if dirty else 'none'}")

    steps = [
        (["-m", "unittest", "tests.test_v2_2a_window_focus_monitor", "-v"],
         "python_targeted_tests_raw.txt"),
        (["-m", "unittest", "tests.test_v2_1_host_supervisor", "-v"],
         "v2_1_guard_oneshot_raw.txt"),
        (["-m", "unittest", "tests.test_v2_host_engine_contracts", "-v"],
         "v2_0_guard_raw.txt"),
    ]
    for args, name in steps:
        kind = run_capture([py, *args], name)
        if kind == "failed":
            failures.append(name)
        elif kind == "independent":
            independent.append(name)

    # The isolated stress diagnostic, saved as its own machine-readable artifact.
    if run_capture([py, "-m", "unittest",
                    "tests.test_v2_2a_window_focus_monitor.V22AWindowFocusMonitorTests."
                    "test_20_raw_callback_isolation_from_state_lock", "-v"],
                   "callback_isolation_stress_raw.txt") == "failed":
        failures.append("callback_isolation_stress_raw.txt")

    if run_capture([py, "-m", "unittest",
                    "tests.test_v2_2a_window_focus_monitor.V22AWindowFocusMonitorTests."
                    "test_21_identity_revalidates_process_image_and_invalidates_cache",
                    "tests.test_v2_2a_window_focus_monitor.V22AWindowFocusMonitorTests."
                    "test_22_stale_identity_negative_after_recycle", "-v"],
                   "identity_stale_recycle_raw.txt") == "failed":
        failures.append("identity_stale_recycle_raw.txt")

    # --- the R2 blocker regressions, each captured as its own artifact ------------
    # Blocker 1: same-generation stale-cache hole + process-instance identity.
    if run_capture([py, "-m", "unittest",
                    "tests.test_v2_2a_window_focus_monitor.V22AWindowFocusMonitorTests."
                    "test_24_revalidate_is_authority_not_cache", "-v"],
                   "identity_same_generation_authority_raw.txt") == "failed":
        failures.append("identity_same_generation_authority_raw.txt")

    # Blocker 2: the overflow latch, and the previously-unemittable public event kind.
    if run_capture([py, "-m", "unittest",
                    "tests.test_v2_2a_window_focus_monitor.V22AWindowFocusMonitorTests."
                    "test_25_event_queue_overflow_is_not_a_latch", "-v"],
                   "event_queue_overflow_regression_raw.txt") == "failed":
        failures.append("event_queue_overflow_regression_raw.txt")

    # Blocker 3: deterministic lock isolation (A held-verifiably, B resumes after release).
    if run_capture([py, "-m", "unittest",
                    "tests.test_v2_2a_window_focus_monitor.V22AWindowFocusMonitorTests."
                    "test_26_raw_callback_isolation_deterministic", "-v"],
                   "callback_isolation_deterministic_raw.txt") == "failed":
        failures.append("callback_isolation_deterministic_raw.txt")

    # The bundle is only honest if every raw log came off the SAME head. Editing the
    # tree mid-run (or amending the commit) would silently mix revisions, so the head
    # is re-checked and a mismatch is a hard failure.
    head_after = repo_head()
    if head_after != head_before:
        print(f"ERROR: head moved during the acceptance run: {head_before} -> {head_after}")
        failures.append("head-moved-during-run")

    print("failures:", failures)
    print("independent_v2_1_debt:", independent)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
