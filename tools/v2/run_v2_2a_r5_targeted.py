"""Run the one targeted regression affected by the diagnostic counter change."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = Path(os.environ.get(
    "V2_2A_R5_CALLBACK_EVIDENCE_OUT",
    str(REPO / "build" / "v2-2a-r5-callback" / "evidence"),
))
RAW = EVIDENCE / "callback_isolation_deterministic_r5_raw.txt"

COMMAND = [
    sys.executable, "-m", "unittest",
    "tests.test_v2_2a_window_focus_monitor.V22AWindowFocusMonitorTests."
    "test_26_raw_callback_isolation_deterministic", "-v",
]


def head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                            capture_output=True, text=True, check=False)
    return result.stdout.strip()


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(COMMAND, cwd=str(REPO), capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            timeout=1800)
    classification = "ok" if result.returncode == 0 else "failed"
    RAW.write_text(
        f"$ {' '.join(COMMAND)}\n"
        f"# cwd: {REPO}\n"
        f"# head: {head()}\n"
        f"# exit code: {result.returncode}\n"
        f"# classification: {classification}\n"
        f"{'-' * 78}\n"
        f"{result.stdout}\n"
        f"{'-' * 78} STDERR {'-' * 68}\n"
        f"{result.stderr}\n",
        encoding="utf-8",
    )
    print(f"targeted exit={result.returncode} classification={classification} raw={RAW}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
