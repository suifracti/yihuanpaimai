"""Build privacy-cropped warehouse scrollbar fixtures from the 2026-08-25 settlement video."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from warehouse_scrollbar_observation import warehouse_search_roi

SOURCE = Path(r"C:/Users/Administrator/Videos/2026-08-25 21-58-33.mkv")
OUT = ROOT / "tests" / "fixtures" / "warehouse_scrollbar_v1"
FRAMES = {
    "top": 8.0,
    "middle": 20.0,
    "bottom": 40.0,
    "unknown": 0.0,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not SOURCE.is_file():
        print("MISSING_SOURCE", SOURCE)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    source_hash = sha256_file(SOURCE)
    cap = cv2.VideoCapture(str(SOURCE))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    records = []
    for name, seconds in FRAMES.items():
        cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
        ok, frame = cap.read()
        if not ok:
            print("FRAME_FAIL", name, seconds)
            return 3
        x1, y1, x2, y2 = warehouse_search_roi(frame.shape[1], frame.shape[0])
        crop = frame[y1:y2, x1:x2]
        dest = OUT / f"{name}_warehouse.png"
        cv2.imencode(".png", crop)[1].tofile(str(dest))
        records.append({
            "role": name,
            "file": dest.name,
            "timecodeSec": seconds,
            "sourceSize": {"width": width, "height": height},
            "viewportRect": {"x": 0, "y": 0, "width": width, "height": height},
            "cropRect": [x1, y1, x2, y2],
            "cropSize": {"width": int(x2 - x1), "height": int(y2 - y1)},
            "scaled": False,
            "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        })
    cap.release()
    manifest = {
        "schema": "warehouse-scrollbar-fixture-v1",
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sourcePath": str(SOURCE),
        "sourceSha256": source_hash,
        "sourceBytes": SOURCE.stat().st_size,
        "note": "Warehouse panel + scrollbar crops only. Original MKV stays outside Git.",
        "frames": records,
    }
    (OUT / "provenance.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
