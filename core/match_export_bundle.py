# -*- coding: utf-8 -*-
"""Relocatable match export containing records and their raw evidence files."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from canonical_history_store import CanonicalHistoryStore
from settlement_evidence_store_v2 import (
    SettlementEvidenceStoreError,
    SettlementEvidenceStoreV2,
    decode_image_size,
    detect_image_type,
)


BUNDLE_SCHEMA_VERSION = "match-export-bundle.v1"
_PATH_KEYS = frozenset({"relativePath", "uri", "screenshotUri", "sourcePath", "cropPath"})
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})


class MatchExportError(RuntimeError):
    """Raised when an export cannot be made self-contained and verifiable."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_record_key(record_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(record_id or "").strip()) or "record"


def _is_probable_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip().replace("\\", "/")
    return (
        text.startswith("evidence/")
        or text.startswith("attachments/")
        or text.startswith("file:/")
        or Path(value).is_absolute()
        or Path(value).suffix.lower() in _IMAGE_SUFFIXES
    )


def _resolve_candidate(value: str, data_root: Path) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve a stored relative or absolute path and return (path, relative)."""
    raw = str(value or "").strip()
    if not raw or raw.startswith("data:") or raw.startswith("http://") or raw.startswith("https://"):
        return None, None
    normalized = raw.replace("\\", "/")
    if normalized.startswith("file:///"):
        normalized = normalized[8:]
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (data_root / normalized).resolve()
    else:
        candidate = candidate.resolve()
    if not candidate.is_file():
        return None, None
    try:
        relative = candidate.relative_to(data_root).as_posix()
    except ValueError:
        relative = None
    return candidate, relative


def _package_path_for(local_path: Path, data_root: Path, relative: Optional[str], digest: str) -> str:
    if relative:
        path = relative.replace("\\", "/").lstrip("/")
        if ".." not in path.split("/") and ":" not in path:
            return path
    suffix = local_path.suffix.lower() if local_path.suffix.lower() in _IMAGE_SUFFIXES else ".bin"
    return f"attachments/external/{digest}{suffix}"


def _register_file(
    files: Dict[str, Dict[str, Any]],
    *,
    local_path: Path,
    package_path: str,
    record_id: str,
    kind: str,
    expected_sha: Optional[str] = None,
    expected_image: bool = False,
) -> Dict[str, Any]:
    payload = local_path.read_bytes()
    actual_sha = _sha256(payload)
    if expected_sha and actual_sha != str(expected_sha):
        raise MatchExportError(f"原图校验失败：{local_path.name} SHA-256 不匹配")
    if expected_image or local_path.suffix.lower() in _IMAGE_SUFFIXES:
        detected = detect_image_type(payload)
        if detected is None:
            raise MatchExportError(f"图片不可打开或格式不受支持：{local_path}")
        width, height = decode_image_size(payload)
    else:
        width = height = None
    entry = files.get(package_path)
    if entry is None:
        entry = {
            "path": package_path,
            "sha256": actual_sha,
            "size": len(payload),
            "byteSize": len(payload),
            "recordId": record_id,
            "kind": kind,
            "width": width,
            "height": height,
            "_localPath": str(local_path),
        }
        files[package_path] = entry
    elif entry.get("sha256") != actual_sha:
        raise MatchExportError(f"导出路径发生内容冲突：{package_path}")
    return {key: value for key, value in entry.items() if not key.startswith("_")}


def _rewrite_paths(
    value: Any,
    *,
    data_root: Path,
    files: Dict[str, Dict[str, Any]],
    record_id: str,
    path_map: Dict[str, str],
) -> Any:
    if isinstance(value, list):
        return [
            _rewrite_paths(item, data_root=data_root, files=files, record_id=record_id, path_map=path_map)
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    output = {}
    for key, raw in value.items():
        if key in _PATH_KEYS and _is_probable_path(raw):
            local, relative = _resolve_candidate(str(raw), data_root)
            if local is not None:
                old_key = str(raw)
                package_path = path_map.get(old_key)
                if package_path is None:
                    digest = _sha256(local.read_bytes())
                    package_path = _package_path_for(local, data_root, relative, digest)
                    path_map[old_key] = package_path
                    _register_file(
                        files,
                        local_path=local,
                        package_path=package_path,
                        record_id=record_id,
                        kind="referenced-attachment",
                        expected_image=local.suffix.lower() in _IMAGE_SUFFIXES,
                    )
                output[key] = package_path
            elif Path(str(raw)).is_absolute() or str(raw).startswith("file:"):
                raise MatchExportError(f"引用文件不存在，无法生成完整数据包：{raw}")
            else:
                output[key] = raw
        else:
            output[key] = _rewrite_paths(
                raw,
                data_root=data_root,
                files=files,
                record_id=record_id,
                path_map=path_map,
            )
    return output


def _descriptor_files(
    store: SettlementEvidenceStoreV2,
    record_id: str,
    data_root: Path,
    files: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    record_key = str(record_id).replace(":", "_")
    try:
        descriptors = store.list_record_evidence(record_key)
    except (SettlementEvidenceStoreError, OSError, ValueError) as exc:
        raise MatchExportError(f"读取对局 {record_id} 的原图索引失败：{exc}") from exc
    result = []
    for descriptor in descriptors:
        relative = str(descriptor.get("relativePath") or "").replace("\\", "/")
        local = (data_root / relative).resolve()
        try:
            local.relative_to(data_root)
        except ValueError as exc:
            raise MatchExportError(f"原图路径越界：{relative}") from exc
        if not local.is_file():
            raise MatchExportError(f"原图文件缺失：{relative}")
        checked = store.verify(dict(descriptor))
        if not checked.get("ok"):
            raise MatchExportError(f"原图校验失败：{relative} ({checked.get('status')})")
        entry = _register_file(
            files,
            local_path=local,
            package_path=relative,
            record_id=record_id,
            kind=str(descriptor.get("kind") or "original-image"),
            expected_sha=str(descriptor.get("sha256") or "") or None,
            expected_image=True,
        )
        result.append({
            "captureId": descriptor.get("evidenceId"),
            "evidenceId": descriptor.get("evidenceId"),
            "kind": descriptor.get("kind"),
            "capturedAt": descriptor.get("capturedAt"),
            "relativePath": relative,
            "sha256": descriptor.get("sha256"),
            "width": descriptor.get("width"),
            "height": descriptor.get("height"),
            "coverageMode": descriptor.get("coverageMode"),
            "coverageStatus": descriptor.get("coverageStatus"),
            "packageFile": entry["path"],
        })

    index_path = data_root / "evidence" / "settlement_v2" / "index" / f"{record_key}.json"
    if index_path.is_file():
        _register_file(
            files,
            local_path=index_path,
            package_path=f"evidence/settlement_v2/index/{record_key}.json",
            record_id=record_id,
            kind="evidence-index",
        )
    return result


def export_match_bundle(
    *,
    history_path: Path | str,
    data_root: Path | str,
    output_path: Path | str,
    record_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Export selected (or all) current records and every verifiable attachment."""
    history_path = Path(history_path).resolve()
    data_root = Path(data_root).resolve()
    output_path = Path(output_path).resolve()
    requested = [str(item).strip() for item in (record_ids or []) if str(item).strip()]

    db_data = CanonicalHistoryStore(history_path).read_database()
    all_records = [item for item in (db_data.get("records") or []) if isinstance(item, dict)]
    if requested:
        by_id = {str(item.get("id") or ""): item for item in all_records}
        missing = [item for item in requested if item not in by_id]
        if missing:
            raise MatchExportError(f"所选对局不存在：{', '.join(missing)}")
        records = [copy.deepcopy(by_id[item]) for item in requested]
    else:
        records = [copy.deepcopy(item) for item in all_records]

    store = SettlementEvidenceStoreV2(data_root)
    files: Dict[str, Dict[str, Any]] = {}
    path_map: Dict[str, str] = {}
    manifest_records = []
    rewritten_records = []
    for record in records:
        record_id = str(record.get("id") or "").strip()
        if not record_id:
            raise MatchExportError("记录缺少稳定 id，不能导出")
        captures = _descriptor_files(store, record_id, data_root, files)
        rewritten = _rewrite_paths(
            record,
            data_root=data_root,
            files=files,
            record_id=record_id,
            path_map=path_map,
        )
        if captures:
            settlement = rewritten.setdefault("settlement", {})
            if isinstance(settlement, dict):
                # The record remains business-fact identical; this only makes
                # the package's included image set explicit and relocatable.
                settlement["exportedCaptures"] = captures
        rewritten_records.append(rewritten)
        manifest_records.append({
            "recordId": record_id,
            "lifecycleStatus": record.get("lifecycleStatus"),
            "captureCount": len(captures),
            "sourceInstanceId": ((record.get("settlement") or {}).get("evidenceAttachments") or {}).get("sourceInstanceId")
            if isinstance(record.get("settlement"), dict) else None,
        })

    records_payload = {
        "schemaVersion": "history-export.v2",
        "recordCount": len(manifest_records),
        "records": rewritten_records,
    }
    records_bytes = json.dumps(records_payload, ensure_ascii=False, indent=2).encode("utf-8")
    usage_note = (
        "异环拍卖对局数据包\n\n"
        "本包包含 records.json、manifest.json 以及所选对局的原始图片/附件。\n"
        "解压后按 manifest.json 中的相对路径读取图片；不要把图片当正式图鉴源卡。\n"
    )
    usage_bytes = usage_note.encode("utf-8")

    manifest_files = [
        {key: value for key, value in entry.items() if not key.startswith("_")}
        for entry in files.values()
    ]
    manifest_files.append({
        "path": "records.json",
        "sha256": _sha256(records_bytes),
        "size": len(records_bytes),
        "byteSize": len(records_bytes),
        "recordId": "bundle",
        "kind": "history-records",
        "width": None,
        "height": None,
    })
    manifest_files.append({
        "path": "说明.txt",
        "sha256": _sha256(usage_bytes),
        "size": len(usage_bytes),
        "byteSize": len(usage_bytes),
        "recordId": "bundle",
        "kind": "documentation",
        "width": None,
        "height": None,
    })

    manifest = {
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "exportedAt": _now(),
        "recordCount": len(manifest_records),
        "recordIds": [item["recordId"] for item in manifest_records],
        "recordsPath": "records.json",
        "records": manifest_records,
        "files": manifest_files,
        "source": "local-runtime-data",
        "note": "原始截图保持原始字节与 SHA-256；未完成结算和 unknown 记录仍可导出。",
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output_path.stem}-", suffix=".tmp", dir=str(output_path.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
            archive.writestr("records.json", records_bytes)
            archive.writestr("说明.txt", usage_bytes)
            for package_path, entry in files.items():
                archive.write(entry["_localPath"], package_path)
        os.replace(str(temp_path), str(output_path))
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass

    return {
        "ok": True,
        "status": "SAVED",
        "outputPath": str(output_path),
        "recordCount": len(manifest_records),
        "imageCount": sum(1 for item in files.values() if item.get("width") and item.get("height")),
        "fileCount": len(manifest_files),
        "manifestPath": "manifest.json",
        "bundleSchemaVersion": BUNDLE_SCHEMA_VERSION,
    }
