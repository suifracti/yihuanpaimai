# -*- coding: utf-8 -*-
"""Review Overlay store: independent, traceable sidecar records.

Reviewed itemized truth for Legacy Archive records (and any record that must
not be written back into the source file) is persisted here as an overlay,
NEVER by editing the original legacy JSON.  Each overlay binds:

- legacy source identity (file name + fileSha256 revision + stable record key)
- screenshot uri + sha256
- reviewed itemized truth
- review provenance (reviewedAt, reviewedBy)

Reopening the same legacy record merges original facts + reviewed overlay.
"""

from __future__ import annotations

import datetime
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from runtime_data import runtime_data_paths


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class ReviewOverlayStore:
    """Atomic JSON overlay store under RuntimeDataRoot/state."""

    def __init__(self, overlay_path: Optional[Path] = None):
        if overlay_path is None:
            overlay_path = runtime_data_paths().state_dir / "settlement_review_overlays.json"
        self._path = Path(overlay_path).resolve()
        self._lock = threading.RLock()

    def _read(self) -> Dict[str, Any]:
        if not self._path.is_file():
            return {"schemaVersion": 1, "overlays": []}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict) and isinstance(doc.get("overlays"), list):
                return doc
        except Exception:
            pass
        return {"schemaVersion": 1, "overlays": []}

    def _write(self, doc: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + f".tmp{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(str(tmp), str(self._path))

    def _overlay_key(self, file_sha256: str, record_key: str) -> str:
        return f"{file_sha256}::{record_key}"

    def get_overlay(self, file_sha256: str, record_key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            key = self._overlay_key(file_sha256, record_key)
            for ov in self._read().get("overlays", []):
                if ov.get("overlayKey") == key:
                    return dict(ov)
        return None

    def save_overlay(
        self,
        *,
        file_sha256: str,
        record_key: str,
        source_file_name: str,
        screenshot_uri: Optional[str],
        screenshot_sha256: Optional[str],
        reviewed_items: List[Dict[str, Any]],
        review_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            doc = self._read()
            key = self._overlay_key(file_sha256, record_key)
            now = _now()
            overlay = {
                "overlayKey": key,
                "schemaVersion": 1,
                "source": {
                    "file": source_file_name,
                    "fileSha256": file_sha256,
                    "recordKey": record_key,
                },
                "screenshot": {
                    "uri": screenshot_uri,
                    "sha256": screenshot_sha256,
                },
                "reviewedItems": list(reviewed_items),
                "reviewProvenance": {
                    "reviewedBy": "user",
                    "reviewedAt": now,
                    "reviewMeta": review_meta or {},
                },
            }
            replaced = False
            for i, ov in enumerate(doc["overlays"]):
                if ov.get("overlayKey") == key:
                    doc["overlays"][i] = overlay
                    replaced = True
                    break
            if not replaced:
                doc["overlays"].append(overlay)
            self._write(doc)
            return dict(overlay)

    def remove_screenshot(self, file_sha256: str, record_key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            doc = self._read()
            key = self._overlay_key(file_sha256, record_key)
            for i, ov in enumerate(doc.get("overlays", [])):
                if ov.get("overlayKey") == key:
                    ov["screenshot"] = None
                    self._write(doc)
                    return dict(ov)
        return None
