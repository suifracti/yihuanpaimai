"""Build privacy-cropped intel-card fixtures from the two real capture frames."""

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

from intel_card_evidence import HEADER_ROI, INTEL_STACK_ROI, strip_recording_chrome
from roi_scaler import ROIScaler

SOURCES = {
    "r2": Path(r"C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-c0998a24-aecb-49f8-a4fd-46b5e64cd116.png"),
    "r3": Path(r"C:/Users/Administrator/AppData/Local/Temp/codex-clipboard-7ae7ea9a-2ba9-4942-a465-f242ce90e3a3.png"),
}
OUT_DIR = ROOT / "tests" / "fixtures" / "intel_card_evidence_v1"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_bgr(path: Path) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"failed to read {path}")
    return img


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("png encode failed")
    return buf.tobytes()


def build_one(frame_id: str, src: Path) -> dict:
    raw = src.read_bytes()
    src_hash = sha256_bytes(raw)
    image = load_bgr(src)
    h, w = image.shape[:2]
    game, chrome = strip_recording_chrome(image)
    gh, gw = game.shape[:2]
    vx, vy, vw, vh = ROIScaler.get_viewport_rect(gw, gh)
    viewport = game[vy : vy + vh, vx : vx + vw]
    ph, pw = viewport.shape[:2]
    sx1, sy1, sx2, sy2 = ROIScaler.scale_roi(INTEL_STACK_ROI, pw, ph)
    hx1, hy1, hx2, hy2 = ROIScaler.scale_roi(HEADER_ROI, pw, ph)
    stack = viewport[sy1:sy2, sx1:sx2]
    header = viewport[hy1:hy2, hx1:hx2]

    canvas = np.zeros_like(viewport)
    canvas[sy1:sy2, sx1:sx2] = stack
    canvas[hy1:hy2, hx1:hx2] = header

    viewport_name = f"{frame_id}_viewport.png"
    stack_name = f"{frame_id}_intel_stack.png"
    header_name = f"{frame_id}_header.png"
    (OUT_DIR / viewport_name).write_bytes(encode_png(canvas))
    (OUT_DIR / stack_name).write_bytes(encode_png(stack))
    (OUT_DIR / header_name).write_bytes(encode_png(header))

    return {
        "frameId": frame_id,
        "sourcePath": str(src),
        "sourceSha256": src_hash,
        "sourceBytes": len(raw),
        "sourceSize": {"width": w, "height": h},
        "recordingChrome": chrome,
        "gameSize": {"width": gw, "height": gh},
        "viewportRect": {"x": vx, "y": vy, "width": vw, "height": vh},
        "intelCardStackRoi": list(ROIScaler.NORMALIZED_ROIS[INTEL_STACK_ROI] if hasattr(ROIScaler, "NORMALIZED_ROIS") else (0.34, 0.13, 0.68, 0.80)),
        "crops": {
            "viewport": {
                "file": viewport_name,
                "rect": [0, 0, pw, ph],
                "sha256": sha256_file(OUT_DIR / viewport_name),
                "size": {"width": pw, "height": ph},
            },
            "intelStack": {
                "file": stack_name,
                "rect": [sx1, sy1, sx2, sy2],
                "sha256": sha256_file(OUT_DIR / stack_name),
                "size": {"width": sx2 - sx1, "height": sy2 - sy1},
            },
            "header": {
                "file": header_name,
                "rect": [hx1, hy1, hx2, hy2],
                "sha256": sha256_file(OUT_DIR / header_name),
                "size": {"width": hx2 - hx1, "height": hy2 - hy1},
            },
        },
        "redactions": [
            "recording player chrome stripped when present",
            "left player names / avatars excluded from derived canvas",
            "UID / bottom action bar excluded from derived canvas",
            "right warehouse excluded from derived canvas",
        ],
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for dbg in OUT_DIR.glob("_dbg_*.png"):
        dbg.unlink()
    missing = [fid for fid, path in SOURCES.items() if not path.is_file()]
    if missing:
        print("MISSING_SOURCE", ",".join(missing))
        return 2

    from roi_scaler import NORMALIZED_ROIS

    records = []
    for frame_id, src in SOURCES.items():
        rec = build_one(frame_id, src)
        rec["intelCardStackRoi"] = list(NORMALIZED_ROIS[INTEL_STACK_ROI])
        rec["headerRoi"] = list(NORMALIZED_ROIS[HEADER_ROI])
        records.append(rec)

    manifest = {
        "schema": "intel-card-evidence-fixture-v1",
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Derived viewport/center-card fixtures only. Original captures stay outside Git.",
        "frames": records,
    }
    (OUT_DIR / "provenance.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("wrote", OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
