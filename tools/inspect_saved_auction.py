"""Inspect saved auction screenshots/state without capture, game input or a live bus.

Preserves the useful measurements from Grok's match-9/10/12 investigation:
the instrument pill is near the bid row, and selecting its menu row is not
the same as pressing Use. The regions below describe those 1920x1080 images;
they are diagnostic measurements, not production control locations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def inspect_image(path: Path) -> dict:
    import cv2
    import numpy as np

    raw = path.read_bytes()
    frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"Cannot decode image: {path}")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mask = np.where(gray >= 165, 255, 0).astype(np.uint8)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
    pills = []
    for index in range(1, count):
        x, y, width, height, area = map(int, stats[index])
        if area < 4000 or width < 140 or not 40 <= height <= 90:
            continue
        cx, cy = map(int, centroids[index])
        pills.append({"center": [cx, cy], "bbox": [x, y, width, height], "area": area})

    # Keep the final watcher's distinct instrument and Use measurements.
    instrument = [p for p in pills if 980 <= p["center"][1] <= 1040
                  and 250 <= p["center"][0] <= 560 and p["bbox"][2] >= 200]
    use = [p for p in pills if 900 <= p["center"][1] <= 1000
           and 180 <= p["center"][0] <= 620 and p["bbox"][2] >= 200]
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "width": frame.shape[1], "height": frame.shape[0], "whitePills": pills,
            "instrumentRegionCandidates": instrument, "useRegionCandidates": use,
            "note": "Saved-pixel measurements only; no OCR identity or click qualification."}


def inspect_state(path: Path) -> dict:
    raw_bytes = path.read_bytes()
    raw = json.loads(raw_bytes)
    state = raw.get("state") or raw
    match = state.get("currentMatch") or {}
    facts = match.get("facts") or {}
    context = state.get("pipelineContext") or {}
    fields = ("venueId", "venue", "boxId", "box", "entryCost", "fieldCondition",
              "q", "goldAvg", "avg", "roundNo", "matchGeneration", "factsRevision")
    return {"path": str(path), "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "frameSequence": raw.get("frameSequence"),
            "envelope": {key: raw.get(key) for key in ("matchGeneration", "factsRevision")},
            "currentMatch": {key: match.get(key) for key in fields},
            "facts": {key: facts.get(key) for key in fields},
            "pipelineContext": {key: context.get(key) for key in (*fields, "scene", "currentEstimate")},
            "note": "Each location is reported separately; missing values are not filled or inferred."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, action="append", default=[], help="Saved screenshot; repeatable")
    parser.add_argument("--state", type=Path, help="Explicit saved latest-business-state.json")
    args = parser.parse_args()
    if not args.image and args.state is None:
        parser.error("provide --image or --state; no live session is selected automatically")
    result = {"images": [inspect_image(path) for path in args.image]}
    if args.state is not None:
        result["state"] = inspect_state(args.state)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
