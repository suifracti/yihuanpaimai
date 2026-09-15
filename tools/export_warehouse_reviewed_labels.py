#!/usr/bin/env python3
"""Manual exporter for warehouse reviewed-label dataset v1.

Does not run unless both --runtime-root and --output-dir are given.
Does not train, write History, or call Solver.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR), str(PROJECT_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from warehouse_reviewed_label_export import export_reviewed_label_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export human-reviewed warehouse identity crops. Manual only."
    )
    parser.add_argument("--runtime-root", required=True, type=Path, help="Isolated runtime data root")
    parser.add_argument("--output-dir", required=True, type=Path, help="Empty-or-owned output directory")
    args = parser.parse_args(argv)
    manifest = export_reviewed_label_dataset(runtime_root=args.runtime_root, output_dir=args.output_dir)
    print(json.dumps({
        "schemaVersion": manifest.get("schemaVersion"),
        "sampleCount": len(manifest.get("samples") or []),
        "rejectedCount": len(manifest.get("rejected") or []),
        "readiness": (manifest.get("readiness") or {}).get("status"),
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
