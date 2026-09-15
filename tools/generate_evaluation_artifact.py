#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI tool to generate Prediction Evaluation Summary Artifact v1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for p in (str(CORE_DIR), str(APP_DIR), str(PROJECT_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from prediction_evaluation_generator import generate_evaluation_artifact_from_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate dual-track Prediction Evaluation Summary Artifact v1."
    )
    parser.add_argument(
        "history",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "异环拍卖数据.json",
        help="Path to canonical history database (default: 异环拍卖数据.json)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        help="Optional directory to save generated artifact and latest.json",
    )
    args = parser.parse_args()

    artifact = generate_evaluation_artifact_from_file(args.history, output_dir=args.output_dir)
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
