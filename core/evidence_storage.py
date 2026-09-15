# -*- coding: utf-8 -*-
"""Evidence Storage Manager for Settlement Truth Provenance v1.

Handles lossless PNG encoding, SHA-256 calculation, atomic persistence,
and disk byte re-verification in canonical writable data root.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Union
import cv2
import numpy as np


def get_canonical_data_dir() -> Path:
    """Return the authoritative writable data directory for both dev and frozen packaged runs."""
    try:
        from runtime_data import runtime_data_paths
        return runtime_data_paths().root
    except Exception:
        if getattr(sys, "frozen", False):
            exe_path = Path(sys.executable).resolve()
            return exe_path.parent
        return Path(__file__).resolve().parents[1]


def get_evidence_dir(subfolder: str = "settlement") -> Path:
    """Return and create the target evidence directory under canonical data root."""
    evidence_dir = get_canonical_data_dir() / "evidence" / subfolder
    evidence_dir.mkdir(parents=True, exist_ok=True)
    return evidence_dir


def save_evidence_png(
    frame: np.ndarray,
    match_id: str,
    subfolder: str = "settlement",
    data_dir: Optional[Union[str, Path]] = None,
) -> Tuple[str, str]:
    """Encode an image frame to lossless PNG, compute its exact SHA-256, and atomically persist it.

    Returns:
        tuple[relative_uri, sha256_hex]
    """
    if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
        raise ValueError("Invalid frame for evidence persistence")

    success, buf = cv2.imencode(".png", frame)
    if not success or buf is None:
        raise RuntimeError("Failed to encode frame to lossless PNG")

    png_bytes = buf.tobytes()
    digest = hashlib.sha256(png_bytes).hexdigest()

    clean_mid = str(match_id or "unnamed").strip().replace("/", "_").replace("\\", "_")
    filename = f"{clean_mid}_{digest[:16]}.png"
    relative_uri = f"evidence/{subfolder}/{filename}".replace("\\", "/")

    target_root = Path(data_dir).resolve() if data_dir else get_canonical_data_dir()
    target_dir = target_root / "evidence" / subfolder
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    if not target_path.exists():
        # Atomic write via temporary file in the same directory
        with tempfile.NamedTemporaryFile(dir=str(target_dir), delete=False, suffix=".tmp") as tmp_f:
            tmp_f.write(png_bytes)
            tmp_path = Path(tmp_f.name)
        os.replace(tmp_path, target_path)

    return relative_uri, digest


def verify_evidence_file(
    relative_uri: str,
    expected_sha256: str,
    data_dir: Optional[Union[str, Path]] = None,
) -> bool:
    """Read persisted evidence bytes from disk and verify they exactly match expected SHA-256."""
    if not relative_uri or not expected_sha256:
        return False

    target_root = Path(data_dir).resolve() if data_dir else get_canonical_data_dir()
    clean_rel = relative_uri.replace("/", os.sep).replace("\\", os.sep)
    file_path = target_root / clean_rel

    if not file_path.is_file():
        return False

    try:
        data = file_path.read_bytes()
        actual_digest = hashlib.sha256(data).hexdigest()
        return actual_digest == expected_sha256
    except Exception:
        return False
