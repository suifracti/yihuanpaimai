#!/usr/bin/env python3
"""Prepare one replay/reference image for the V2 fixed BGRA8 frame ring.

The image remains the source of truth.  This tool only creates a build-scoped
raw BGRA8 transport copy and a manifest that binds the copy to the source
image, its hashes, the exact geometry, and the capture-boundary timestamp used
by FRAME_READY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2


MAX_WIDTH = 1920
MAX_HEIGHT = 1080
PIXEL_FORMAT_BGRA8 = 1


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def corner_checksum(bgra: bytes, width: int, height: int, stride: int) -> int:
    """Mirror MmfFrameRingWriter.CornerChecksum exactly."""
    last_x = (width - 1) * 4
    last_y = (height - 1) * stride
    total = 0
    for offset in (0, last_x, last_y, last_y + last_x):
        total += sum(bgra[offset : offset + 4])
    return total & 0xFFFFFFFF


def prepare(source: Path, raw_output: Path, metadata_output: Path, timestamp_ns: int | None) -> dict:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source image does not exist: {source}")

    source_bytes = source.read_bytes()
    bgr = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"OpenCV could not decode source image: {source}")
    height, width = bgr.shape[:2]
    if width <= 0 or height <= 0 or width > MAX_WIDTH or height > MAX_HEIGHT:
        raise ValueError(
            f"ERR_FRAME_CAPACITY_EXCEEDED: source geometry {width}x{height} "
            f"exceeds fixed v1 maximum {MAX_WIDTH}x{MAX_HEIGHT}"
        )

    bgra = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    if not bgra.flags.c_contiguous:
        bgra = bgra.copy()
    raw = bgra.tobytes(order="C")
    stride = width * 4
    expected = stride * height
    if len(raw) != expected:
        raise ValueError(f"BGRA byte length {len(raw)} != stride*height {expected}")

    raw_output = raw_output.resolve()
    metadata_output = metadata_output.resolve()
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_bytes(raw)

    capture_timestamp_ns = int(timestamp_ns if timestamp_ns is not None else time.perf_counter_ns())
    metadata = {
        "protocolVersion": "1.0.0",
        "sourceKind": "replay_fixture",
        "sourcePath": str(source),
        "sourceSha256": sha256_bytes(source_bytes),
        "rawPath": str(raw_output),
        "rawSha256": sha256_bytes(raw),
        "width": int(width),
        "height": int(height),
        "stride": int(stride),
        "pixelFormat": PIXEL_FORMAT_BGRA8,
        "bufferLength": int(len(raw)),
        "captureTimestampNs": capture_timestamp_ns,
        "cornerChecksum": corner_checksum(raw, width, height, stride),
        "conversion": "OpenCV BGR -> BGRA8, row-major contiguous",
    }
    metadata_output.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--raw-output", required=True, type=Path)
    parser.add_argument("--metadata-output", required=True, type=Path)
    parser.add_argument("--capture-timestamp-ns", type=int, default=None)
    args = parser.parse_args()
    metadata = prepare(
        args.input,
        args.raw_output,
        args.metadata_output,
        args.capture_timestamp_ns,
    )
    print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
