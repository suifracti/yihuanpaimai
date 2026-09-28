"""Run the R4-only measurements into the independent R4 evidence directory."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = Path(os.environ.get("V2_2A_R4_EVIDENCE_OUT",
                             str(REPO / "build" / "v2-2a-r4" / "evidence")))
WORK = Path(os.environ.get("V2_2A_R4_MEASURE_WORK",
                         str(REPO / "build" / "v2-2a-r4" / "measure_work")))
RAW = EVIDENCE / "measure_v2_2a_r4_raw.txt"


def head() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                            capture_output=True, text=True, check=False)
    return result.stdout.strip()


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-u", "tools/v2/measure_v2_2a_r1.py"]
    env = os.environ.copy()
    env.update({
        "V2_2A_EVIDENCE_OUT": str(EVIDENCE),
        "V2_2A_MEASURE_WORK": str(WORK),
        "V2_2A_R4_MINIMAL": "1",
    })
    result = subprocess.run(command, cwd=str(REPO), env=env, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=2400)
    RAW.write_text(
        f"$ {' '.join(command)}\n"
        f"# cwd: {REPO}\n"
        f"# head: {head()}\n"
        f"# exit code: {result.returncode}\n"
        f"# classification: {'ok' if result.returncode == 0 else 'failed'}\n"
        f"{'-' * 78}\n"
        f"{result.stdout}\n"
        f"{'-' * 78} STDERR {'-' * 68}\n"
        f"{result.stderr}\n",
        encoding="utf-8")
    print(f"measurement exit={result.returncode} raw={RAW}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
