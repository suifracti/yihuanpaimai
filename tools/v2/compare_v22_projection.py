#!/usr/bin/env python3
"""Compare one existing local vision route with the V2 Engine projection.

The comparison uses the same replay image but runs the existing Python route in
a fresh pipeline instance. It checks only externally observable scene facts;
the V2 Engine's CurrentMatch and history sidecars remain the authoritative
state evidence and are not used to manufacture the expected values.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "core", ROOT / "app"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from vision_pipeline import NTEVisionPipeline  # noqa: E402


def compare(source: Path, host_result: Path, engine_state: Path) -> dict:
    host = json.loads(host_result.read_text(encoding="utf-8"))
    engine_projection = host["run"]["frameTransfer"]["perceptionPayload"]
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode source image: {source}")

    pipeline = NTEVisionPipeline(catalog_path=str(ROOT / "assets" / "catalog_065.json"))
    # Match the existing live route's warm-up boundary; without this call the
    # pipeline is intentionally allowed to return UNKNOWN before OCR is ready.
    _ = pipeline.ocr
    context = pipeline.process_frame(
        image,
        captured_at="2026-09-20T00:00:00+00:00",
        record_stable_key="existing-route-compare",
        include_heavy_identity=False,
    )
    state = json.loads(engine_state.read_text(encoding="utf-8"))
    checks = {
        "sceneMatches": context.get("scene") == engine_projection.get("scene"),
        "inAuctionMatches": bool(context.get("inAuction")) == bool(engine_projection.get("inAuction")),
        "engineStateSceneMatchesProjection": state.get("pipelineContext", {}).get("scene") == engine_projection.get("scene"),
        "stateIsDraft": state.get("currentMatch", {}).get("lifecycleStatus") == "DRAFT",
        "stateOriginIsReplay": state.get("currentMatch", {}).get("dataOrigin") == "replay",
    }
    return {
        "source": str(source.resolve()),
        "existingRoute": {
            "scene": context.get("scene"),
            "inAuction": bool(context.get("inAuction")),
            "isSettlement": bool(context.get("isSettlement")),
        },
        "v22Projection": {
            "scene": engine_projection.get("scene"),
            "inAuction": bool(engine_projection.get("inAuction")),
            "frameSequence": engine_projection.get("frameSequence"),
        },
        "checks": checks,
        "allChecksPassed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--host-result", required=True, type=Path)
    parser.add_argument("--engine-state", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    result = compare(args.source, args.host_result, args.engine_state)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if result["allChecksPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
