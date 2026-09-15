"""File-backed Settlement Evidence Store v2.

Stores immutable original PNG/JPEG bytes under an explicit runtime data root.
Does not write History, does not use IndexedDB, and never emits COMPLETE coverage.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import cv2
import numpy as np

SCHEMA_VERSION = "settlement-evidence-original-v2"
INDEX_SCHEMA_VERSION = "settlement-evidence-index-v2"
STORE_RELATIVE_ROOT = "evidence/settlement_v2"
BLOB_RELATIVE_DIR = f"{STORE_RELATIVE_ROOT}/blobs"
INDEX_RELATIVE_DIR = f"{STORE_RELATIVE_ROOT}/index"

KIND_MAIN = "main-settlement"
KIND_WAREHOUSE = "warehouse-supplement"
KIND_WAREHOUSE_SEGMENT = "warehouse-segment"
# A manual game-window screenshot is raw provenance only.  It is deliberately
# not treated as a settlement main frame and never promotes settlement facts.
KIND_MANUAL_GAME = "manual-game"
ALLOWED_KINDS = frozenset({KIND_MAIN, KIND_WAREHOUSE, KIND_WAREHOUSE_SEGMENT, KIND_MANUAL_GAME})

COVERAGE_PARTIAL = "PARTIAL"
COVERAGE_UNPROVEN = "COVERAGE_UNPROVEN"
ALLOWED_COVERAGE_STATUS = frozenset({COVERAGE_PARTIAL, COVERAGE_UNPROVEN})

ALLOWED_COVERAGE_MODES = frozenset({"viewport-segment", "unspecified"})

RECORD_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
MAX_ORIGINAL_BYTES = 40 * 1024 * 1024


class SettlementEvidenceStoreError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def detect_image_type(payload: bytes) -> Optional[Dict[str, str]]:
    if payload.startswith(PNG_MAGIC):
        return {"mimeType": "image/png", "ext": ".png"}
    if payload.startswith(JPEG_MAGIC):
        return {"mimeType": "image/jpeg", "ext": ".jpg"}
    return None


def decode_image_size(payload: bytes) -> tuple[int, int]:
    array = np.frombuffer(payload, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_UNCHANGED)
    if image is None or getattr(image, "size", 0) == 0:
        raise SettlementEvidenceStoreError("INVALID_IMAGE", "image bytes are not decodable")
    height, width = image.shape[:2]
    if width < 1 or height < 1:
        raise SettlementEvidenceStoreError("INVALID_IMAGE", "decoded image has no pixels")
    return int(width), int(height)


def validate_record_stable_key(record_stable_key: str) -> str:
    key = str(record_stable_key or "").strip()
    if not key or not RECORD_KEY_RE.fullmatch(key):
        raise SettlementEvidenceStoreError("INVALID_RECORD_KEY", "recordStableKey rejected")
    if ".." in key or "/" in key or "\\" in key:
        raise SettlementEvidenceStoreError("PATH_TRAVERSAL", "recordStableKey traversal rejected")
    return key


def _validate_coverage(status: str, mode: str) -> tuple[str, str]:
    coverage_status = str(status or "").strip()
    coverage_mode = str(mode or "").strip()
    if coverage_status not in ALLOWED_COVERAGE_STATUS:
        raise SettlementEvidenceStoreError("INVALID_COVERAGE_STATUS", "COMPLETE and unknown statuses are forbidden")
    if coverage_mode not in ALLOWED_COVERAGE_MODES:
        raise SettlementEvidenceStoreError("INVALID_COVERAGE_MODE", "coverageMode is not in the closed set")
    return coverage_status, coverage_mode


class SettlementEvidenceStoreV2:
    def __init__(self, runtime_data_root: Union[str, Path]):
        if runtime_data_root is None or str(runtime_data_root).strip() == "":
            raise SettlementEvidenceStoreError("RUNTIME_ROOT_REQUIRED", "explicit runtime data root is required")
        root = Path(runtime_data_root).expanduser()
        if not root.is_absolute():
            raise SettlementEvidenceStoreError("RUNTIME_ROOT_NOT_ABSOLUTE", "runtime data root must be absolute")
        self._root = root.resolve()
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    def _contained(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise SettlementEvidenceStoreError("PATH_TRAVERSAL", "path escapes runtime data root") from exc
        return resolved

    def _blob_relative(self, digest: str, ext: str) -> str:
        return f"{BLOB_RELATIVE_DIR}/{digest[:2]}/{digest}{ext}"

    def _index_relative(self, record_key: str) -> str:
        return f"{INDEX_RELATIVE_DIR}/{record_key}.json"

    def _resolve_relative(self, relative_path: str) -> Path:
        rel = str(relative_path or "").replace("\\", "/").strip()
        if not rel or rel.startswith("/") or rel.startswith("\\") or ".." in rel.split("/"):
            raise SettlementEvidenceStoreError("PATH_TRAVERSAL", "relativePath rejected")
        if Path(rel).is_absolute():
            raise SettlementEvidenceStoreError("PATH_TRAVERSAL", "absolute paths are forbidden")
        return self._contained(self._root / rel)

    def _atomic_write_bytes(self, destination: Path, payload: bytes) -> None:
        destination = self._contained(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.tmp-{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex}"
        )
        try:
            with temporary.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary), str(destination))
        except Exception:
            raise
        finally:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass

    def _write_immutable_blob(self, destination: Path, payload: bytes, digest: str) -> None:
        destination = self._contained(destination)
        if destination.exists():
            existing = destination.read_bytes()
            existing_digest = _sha256_bytes(existing)
            if existing_digest != digest or existing != payload:
                raise SettlementEvidenceStoreError(
                    "BLOB_HASH_CONFLICT",
                    "existing blob failed fail-closed hash verification",
                )
            return
        self._atomic_write_bytes(destination, payload)
        written = destination.read_bytes()
        if _sha256_bytes(written) != digest or written != payload:
            try:
                destination.unlink()
            except OSError:
                pass
            raise SettlementEvidenceStoreError("BLOB_VERIFY_FAILED", "written blob failed verification")

    def _read_index(self, record_key: str) -> List[Dict[str, Any]]:
        path = self._resolve_relative(self._index_relative(record_key))
        if not path.is_file():
            return []
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise SettlementEvidenceStoreError("INDEX_CORRUPT", "record evidence index is unreadable")
        items = document.get("items") if isinstance(document, dict) else None
        if not isinstance(items, list):
            raise SettlementEvidenceStoreError("INDEX_CORRUPT", "record evidence index has no items")
        return [item for item in items if isinstance(item, dict)]

    def _write_index(self, record_key: str, items: List[Dict[str, Any]]) -> None:
        path = self._resolve_relative(self._index_relative(record_key))
        document = {
            "schemaVersion": INDEX_SCHEMA_VERSION,
            "recordStableKey": record_key,
            "items": items,
        }
        payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        self._atomic_write_bytes(path, payload)

    def _validate_descriptor(self, descriptor: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(descriptor, dict):
            raise SettlementEvidenceStoreError("INVALID_DESCRIPTOR", "descriptor must be an object")
        required = (
            "schemaVersion",
            "evidenceId",
            "recordStableKey",
            "kind",
            "capturedAt",
            "storageMode",
            "relativePath",
            "sha256",
            "byteSize",
            "mimeType",
            "width",
            "height",
            "coverageMode",
            "coverageStatus",
        )
        missing = [key for key in required if key not in descriptor]
        if missing:
            raise SettlementEvidenceStoreError("INVALID_DESCRIPTOR", f"missing fields: {','.join(missing)}")
        if descriptor.get("schemaVersion") != SCHEMA_VERSION:
            raise SettlementEvidenceStoreError("INVALID_DESCRIPTOR", "unsupported schemaVersion")
        if descriptor.get("storageMode") != "file":
            raise SettlementEvidenceStoreError("INVALID_DESCRIPTOR", "storageMode must be file")
        if descriptor.get("evidenceOrigin", "runtime-capture") not in ("runtime-capture", "user-import"):
            raise SettlementEvidenceStoreError("INVALID_ORIGIN", "unsupported evidence origin")
        validate_record_stable_key(str(descriptor.get("recordStableKey") or ""))
        if descriptor.get("kind") not in ALLOWED_KINDS:
            raise SettlementEvidenceStoreError("INVALID_KIND", "kind is not in the closed set")
        _validate_coverage(str(descriptor.get("coverageStatus")), str(descriptor.get("coverageMode")))
        digest = str(descriptor.get("sha256") or "")
        if not SHA256_RE.fullmatch(digest):
            raise SettlementEvidenceStoreError("INVALID_DESCRIPTOR", "sha256 is not a hex digest")
        return descriptor

    def save_original(
        self,
        *,
        record_stable_key: str,
        kind: str,
        image_bytes: bytes,
        captured_at: Optional[str] = None,
        coverage_mode: str = "viewport-segment",
        coverage_status: str = COVERAGE_UNPROVEN,
        evidence_origin: str = "runtime-capture",
    ) -> Dict[str, Any]:
        record_key = validate_record_stable_key(record_stable_key)
        if evidence_origin not in ("runtime-capture", "user-import"):
            raise SettlementEvidenceStoreError("INVALID_ORIGIN", "unsupported evidence origin")
        if kind not in ALLOWED_KINDS:
            raise SettlementEvidenceStoreError("INVALID_KIND", "kind is not in the closed set")
        coverage_status, coverage_mode = _validate_coverage(coverage_status, coverage_mode)
        if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
            raise SettlementEvidenceStoreError("INVALID_IMAGE", "image bytes are empty")
        payload = bytes(image_bytes)
        if len(payload) > MAX_ORIGINAL_BYTES:
            raise SettlementEvidenceStoreError("INVALID_IMAGE", "image exceeds store size limit")

        detected = detect_image_type(payload)
        if detected is None:
            raise SettlementEvidenceStoreError("INVALID_IMAGE", "only PNG and JPEG originals are accepted")
        width, height = decode_image_size(payload)
        digest = _sha256_bytes(payload)
        relative_path = self._blob_relative(digest, detected["ext"])
        captured = str(captured_at or "").strip() or _utc_now()

        with self._lock:
            blob_path = self._resolve_relative(relative_path)
            self._write_immutable_blob(blob_path, payload, digest)

            items = self._read_index(record_key)
            for existing in items:
                if (
                    existing.get("sha256") == digest
                    and existing.get("kind") == kind
                    and existing.get("relativePath") == relative_path
                    and existing.get("evidenceOrigin", "runtime-capture") == evidence_origin
                ):
                    if existing.pop("removedFromGalleryAt", None):
                        self._write_index(record_key, items)
                    return dict(existing)

            descriptor = {
                "schemaVersion": SCHEMA_VERSION,
                "evidenceId": f"sev2_{record_key}_{digest[:16]}_{kind}" + ("_import" if evidence_origin == "user-import" else ""),
                "evidenceOrigin": evidence_origin,
                "recordStableKey": record_key,
                "kind": kind,
                "capturedAt": captured,
                "storageMode": "file",
                "relativePath": relative_path,
                "sha256": digest,
                "byteSize": len(payload),
                "mimeType": detected["mimeType"],
                "width": width,
                "height": height,
                "coverageMode": coverage_mode,
                "coverageStatus": coverage_status,
            }
            items.append(descriptor)
            self._write_index(record_key, items)
            return dict(descriptor)

    def unlink_user_imports(self, record_stable_key: str) -> int:
        """Remove only explicitly imported associations; immutable blobs remain."""
        record_key = validate_record_stable_key(record_stable_key)
        with self._lock:
            items = self._read_index(record_key)
            kept = [item for item in items if item.get("evidenceOrigin") != "user-import"]
            if len(kept) != len(items):
                self._write_index(record_key, kept)
            return len(items) - len(kept)

    def load_original(self, descriptor: Dict[str, Any]) -> bytes:
        descriptor = self._validate_descriptor(descriptor)
        result = self.verify(descriptor)
        if not result.get("ok"):
            raise SettlementEvidenceStoreError(str(result.get("status") or "VERIFY_FAILED"), "original is not loadable")
        path = self._resolve_relative(str(descriptor["relativePath"]))
        return path.read_bytes()

    def verify(self, descriptor: Dict[str, Any]) -> Dict[str, Any]:
        try:
            descriptor = self._validate_descriptor(descriptor)
            path = self._resolve_relative(str(descriptor["relativePath"]))
        except SettlementEvidenceStoreError as exc:
            return {"ok": False, "status": exc.code, "sha256": None}
        if not path.is_file():
            return {"ok": False, "status": "MISSING", "sha256": None}
        actual = _sha256_bytes(path.read_bytes())
        expected = str(descriptor["sha256"])
        if actual != expected:
            return {"ok": False, "status": "HASH_MISMATCH", "sha256": actual}
        return {"ok": True, "status": "OK", "sha256": actual}

    def set_original_removed(self, record_stable_key: str, evidence_id: str, removed: bool) -> None:
        """Remove a screenshot from browsing without destroying shared truth evidence."""
        record_key = validate_record_stable_key(record_stable_key)
        with self._lock:
            items = self._read_index(record_key)
            matches = [item for item in items if item.get("evidenceId") == evidence_id]
            if not evidence_id or not matches:
                raise SettlementEvidenceStoreError("NOT_FOUND", "截图不存在或不属于本局")
            for item in matches:
                if removed:
                    item["removedFromGalleryAt"] = _utc_now()
                else:
                    item.pop("removedFromGalleryAt", None)
            self._write_index(record_key, items)

    def list_record_evidence(self, record_stable_key: str, *, include_removed: bool = False) -> List[Dict[str, Any]]:
        record_key = validate_record_stable_key(record_stable_key)
        with self._lock:
            items = [dict(item) for item in self._read_index(record_key)
                     if include_removed or not item.get("removedFromGalleryAt")]
        items.sort(key=lambda item: (str(item.get("capturedAt") or ""), str(item.get("evidenceId") or "")))
        return items
