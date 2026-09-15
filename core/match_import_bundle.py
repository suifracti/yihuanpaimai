# -*- coding: utf-8 -*-
"""Safely import a relocatable match-history bundle into local runtime data."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import validate_canonical_match_record_v7


BUNDLE_SCHEMA_VERSION = "match-export-bundle.v1"
HISTORY_EXPORT_SCHEMA_VERSION = "history-export.v2"
ALLOWED_EXACT_FILES = frozenset({"records.json", "说明.txt"})
ALLOWED_DIR_PREFIXES = ("evidence/", "attachments/", "crops/")


class MatchImportError(RuntimeError):
    """Raised when an import cannot be verified without overwriting local data."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_member_path(raw: Any) -> str:
    text = str(raw or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or ":" in text:
        raise MatchImportError(f"数据包路径不安全：{raw}")
    path = PurePosixPath(text)
    if any(part in ("", ".", "..") for part in path.parts):
        raise MatchImportError(f"数据包路径不安全：{raw}")
    normalized = path.as_posix()
    if normalized in ALLOWED_EXACT_FILES:
        return normalized
    if any(normalized.startswith(prefix) and len(normalized) > len(prefix) for prefix in ALLOWED_DIR_PREFIXES):
        return normalized
    raise MatchImportError(f"数据包包含不允许导入的文件：{normalized}")


def _read_zip_json(archive: zipfile.ZipFile, name: str) -> Dict[str, Any]:
    try:
        payload = json.loads(archive.read(name).decode("utf-8"))
    except KeyError as exc:
        raise MatchImportError(f"数据包缺少 {name}") from exc
    except Exception as exc:
        raise MatchImportError(f"数据包中的 {name} 无法读取：{exc}") from exc
    if not isinstance(payload, dict):
        raise MatchImportError(f"数据包中的 {name} 不是对象")
    return payload


def _record_for_comparison(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Ignore package-only capture listing when checking idempotency."""
    clean = copy.deepcopy(dict(record))
    settlement = clean.get("settlement")
    if isinstance(settlement, dict):
        settlement.pop("exportedCaptures", None)
    return clean


def _validate_records(records_payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if records_payload.get("schemaVersion") != HISTORY_EXPORT_SCHEMA_VERSION:
        raise MatchImportError("不支持的对局记录包版本")
    records = records_payload.get("records")
    if not isinstance(records, list):
        raise MatchImportError("records.json 缺少 records 列表")
    checked: List[Dict[str, Any]] = []
    seen = set()
    for raw in records:
        if not isinstance(raw, dict):
            raise MatchImportError("records.json 含有非法对局记录")
        record_id = str(raw.get("id") or "").strip()
        if not record_id or record_id in seen:
            raise MatchImportError(f"对局 ID 缺失或重复：{record_id or '<empty>'}")
        seen.add(record_id)
        schema_version = raw.get("schemaVersion")
        if schema_version == 7:
            ok, reasons = validate_canonical_match_record_v7(raw, match_id=record_id)
            if not ok:
                raise MatchImportError(f"对局 {record_id} 校验失败：{','.join(reasons)}")
        elif schema_version not in (6, "6"):
            raise MatchImportError(f"对局 {record_id} 的记录版本不受支持：{schema_version}")
        checked.append(copy.deepcopy(raw))
    return checked


def _parse_strict_file_size(raw_sz: Any, package_path: str) -> int:
    if isinstance(raw_sz, bool):
        raise MatchImportError(f"manifest.json 文件大小不能为布尔值：{package_path}")
    if isinstance(raw_sz, float):
        raise MatchImportError(f"manifest.json 文件大小不能为浮点数：{package_path}")
    if isinstance(raw_sz, int):
        if raw_sz < 0:
            raise MatchImportError(f"manifest.json 文件大小不能为负数：{package_path}")
        return raw_sz
    if isinstance(raw_sz, str):
        if not raw_sz.isdigit():
            raise MatchImportError(f"manifest.json 文件大小字符串格式非法（必须为严格纯数字整数）：{package_path}")
        return int(raw_sz)
    raise MatchImportError(f"manifest.json 文件大小类型非法 ({type(raw_sz).__name__})：{package_path}")


def _validate_manifest_files(manifest: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    if manifest.get("schemaVersion") != BUNDLE_SCHEMA_VERSION:
        raise MatchImportError("不支持的对局数据包版本")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise MatchImportError("manifest.json 缺少文件清单")
    file_map: Dict[str, Dict[str, Any]] = {}
    for raw in files:
        if not isinstance(raw, dict):
            raise MatchImportError("manifest.json 含有非法文件清单")
        package_path = _safe_member_path(raw.get("path"))
        if package_path in file_map:
            raise MatchImportError(f"manifest.json 文件重复：{package_path}")
        digest = str(raw.get("sha256") or "").lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise MatchImportError(f"manifest.json SHA-256 无效：{package_path}")
        size_val = raw.get("size")
        bytesize_val = raw.get("byteSize")
        if size_val is None and bytesize_val is None:
            raise MatchImportError(f"manifest.json 缺少文件大小：{package_path}")
        sz = None
        if size_val is not None:
            sz = _parse_strict_file_size(size_val, package_path)
        if bytesize_val is not None:
            bsz = _parse_strict_file_size(bytesize_val, package_path)
            if sz is not None and sz != bsz:
                raise MatchImportError(f"manifest.json size 与 byteSize 不一致：{package_path}")
            if sz is None:
                sz = bsz
        entry = dict(raw)
        entry["size"] = sz
        file_map[package_path] = entry
    return file_map


def _validate_record_captures(records: Iterable[Mapping[str, Any]], file_map: Mapping[str, Any]) -> None:
    for record in records:
        settlement = record.get("settlement")
        captures = settlement.get("exportedCaptures") if isinstance(settlement, dict) else None
        if not isinstance(captures, list):
            continue
        for capture in captures:
            if not isinstance(capture, dict):
                raise MatchImportError(f"对局 {record.get('id')} 的截图附件无效")
            package_path = _safe_member_path(capture.get("packageFile") or capture.get("relativePath"))
            if package_path not in file_map:
                raise MatchImportError(f"对局 {record.get('id')} 缺少截图文件：{package_path}")
            expected = str(capture.get("sha256") or file_map[package_path].get("sha256") or "").lower()
            if expected and expected != str(file_map[package_path].get("sha256") or "").lower():
                raise MatchImportError(f"对局 {record.get('id')} 的截图清单哈希不一致：{package_path}")


def _stage_files(
    archive: zipfile.ZipFile,
    file_map: Mapping[str, Mapping[str, Any]],
    data_root: Path,
) -> List[Tuple[str, bytes]]:
    staged: List[Tuple[str, bytes]] = []
    for package_path, entry in file_map.items():
        if package_path in ("records.json", "说明.txt"):
            continue
        payload = archive.read(package_path)
        digest = _sha256(payload)
        target = (data_root / package_path).resolve()
        try:
            target.relative_to(data_root)
        except ValueError as exc:
            raise MatchImportError(f"导入路径越界：{package_path}") from exc
        existing = target.read_bytes() if target.is_file() else None
        if existing is not None and _sha256(existing) != digest:
            raise MatchImportError(f"本地已有不同内容，拒绝覆盖：{package_path}")
        staged.append((package_path, payload))
    return staged


def import_match_bundle(
    *,
    history_path: Path | str,
    data_root: Path | str,
    input_path: Path | str,
) -> Dict[str, Any]:
    """Import records and their verified attachments without overwriting facts."""
    history_path = Path(history_path).resolve()
    data_root = Path(data_root).resolve()
    input_path = Path(input_path).resolve()
    if not input_path.is_file():
        raise MatchImportError(f"数据包不存在：{input_path}")

    with zipfile.ZipFile(input_path, "r") as archive:
        raw_namelist = archive.namelist()
        if len(raw_namelist) != len(set(raw_namelist)):
            raise MatchImportError("数据包含有重复文件条目")
        namelist = set(raw_namelist)
        if "manifest.json" not in namelist:
            raise MatchImportError("数据包缺少 manifest.json")

        manifest = _read_zip_json(archive, "manifest.json")
        file_map = _validate_manifest_files(manifest)

        # 1. Exact set equality check: ZIP namelist MUST strictly equal manifest files + {"manifest.json"}
        expected_namelist = set(file_map.keys()) | {"manifest.json"}
        if namelist != expected_namelist:
            extra_files = namelist - expected_namelist
            missing_files = expected_namelist - namelist
            if extra_files:
                raise MatchImportError(f"数据包含有未登记的额外文件：{', '.join(sorted(extra_files))}")
            if missing_files:
                raise MatchImportError(f"数据包缺少登记文件：{', '.join(sorted(missing_files))}")

        # 2. Strict SHA-256 and size verification of EVERY file in file_map against the archive
        # (including records.json, 说明.txt, crops/, evidence/, attachments/)
        for package_path, entry in file_map.items():
            try:
                payload = archive.read(package_path)
            except KeyError as exc:
                raise MatchImportError(f"数据包缺少登记文件：{package_path}") from exc
            digest = _sha256(payload)
            if digest != str(entry.get("sha256") or "").lower():
                raise MatchImportError(f"文件哈希校验失败：{package_path}")
            if len(payload) != int(entry["size"]):
                raise MatchImportError(f"文件大小校验失败：{package_path}")

        # 3. Ensure records.json is in file_map and parse it
        if "records.json" not in file_map:
            raise MatchImportError("数据包缺少 records.json")

        records_payload = _read_zip_json(archive, "records.json")
        records = _validate_records(records_payload)
        _validate_record_captures(records, file_map)
        staged = _stage_files(archive, file_map, data_root)

    store = CanonicalHistoryStore(history_path)
    existing_records = store.read_database().get("records") or []
    existing_by_id = {
        str(item.get("id") or "").strip(): item
        for item in existing_records
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    to_add: List[Dict[str, Any]] = []
    skipped = 0
    for record in records:
        record_id = str(record["id"])
        prior = existing_by_id.get(record_id)
        if prior is None:
            to_add.append(record)
            continue
        if _record_for_comparison(prior) != _record_for_comparison(record):
            raise MatchImportError(f"本地已有同 ID 的不同对局，拒绝覆盖：{record_id}")
        skipped += 1

    # All validation and collision checks happen before any write.
    if staged:
        data_root.mkdir(parents=True, exist_ok=True)
        for package_path, payload in staged:
            target = (data_root / package_path).resolve()
            if target.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}-", dir=str(target.parent))
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    try:
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
                os.replace(str(temp_path), str(target))
            finally:
                if temp_path.exists():
                    temp_path.unlink()

    added = 0
    for record in to_add:
        lifecycle = str(record.get("lifecycleStatus") or "DRAFT").upper()
        store.persist_record_transactional(record, is_finalized=(lifecycle == "FINALIZED"))
        added += 1

    image_count = sum(
        1
        for path in file_map
        if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    return {
        "ok": True,
        "status": "SAVED",
        "inputPath": str(input_path),
        "recordCount": len(records),
        "importedRecordCount": added,
        "skippedRecordCount": skipped,
        "imageCount": image_count,
        "fileCount": len(file_map),
        "bundleSchemaVersion": BUNDLE_SCHEMA_VERSION,
    }
