# -*- coding: utf-8 -*-
"""Prove bundled node.exe computes without PATH node. Isolated folder, not daily package."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "diagnosis_20260909" / "p2-bundled-node-verify"
CORE_FILES = [
    "auction_engine_v06.js",
    "shadow_profile_v06.js",
    "live_shadow_compute.js",
    "live_shadow_runtime.js",
    "solver_core_v06.js",
]


def main() -> int:
    src_node = ROOT / "runtime" / "node.exe"
    if not src_node.is_file():
        raise SystemExit("missing runtime/node.exe")
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "core").mkdir(parents=True)
    shutil.copy2(src_node, OUT / "node.exe")
    for name in CORE_FILES:
        shutil.copy2(ROOT / "core" / name, OUT / "core" / name)
    hist = OUT / "hist.json"
    hist.write_text('{"schemaVersion":6,"records":[]}', encoding="utf-8")
    payload = {
        "ctx": {"q": 12, "goldAvg": 74379, "purple": 7, "avg": 74379, "fieldCondition": "standard"},
        "records": [],
    }
    (OUT / "input.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = str(OUT)
    env.pop("NODE_PATH", None)
    proc = subprocess.run(
        [str(OUT / "node.exe"), str(OUT / "core" / "live_shadow_runtime.js"), "--once", "--records", str(hist)],
        cwd=str(OUT),
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
    )
    result = {
        "returncode": proc.returncode,
        "usedBundledNode": True,
        "pathWasPackageOnly": env["PATH"] == str(OUT),
        "stdoutTail": (proc.stdout or "")[-2000:],
        "stderrTail": (proc.stderr or "")[-2000:],
        "nodeBytes": (OUT / "node.exe").stat().st_size,
    }
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
    parsed = json.loads(lines[-1]) if lines else {}
    result["ok"] = proc.returncode == 0 and bool(parsed.get("ok") or parsed.get("insufficient") is not None)
    result["parsedKeys"] = sorted(parsed.keys())
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS" if result["ok"] else "FAIL", "out": str(OUT)}, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
