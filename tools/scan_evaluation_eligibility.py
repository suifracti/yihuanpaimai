#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Evaluation Eligibility scanner; computes no performance metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from evaluation_eligibility import scan_history_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate History/Prediction/Truth provenance and print reason counts. "
            "No Solver replay or model metric is performed."
        )
    )
    parser.add_argument(
        "history",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "异环拍卖数据.json",
    )
    args = parser.parse_args()
    summary = scan_history_file(args.history)
    print(json.dumps(summary.to_payload(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
