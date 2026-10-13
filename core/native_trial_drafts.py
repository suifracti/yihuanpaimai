"""Isolated, reviewable DRAFT storage for the native live-trial profile."""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from canonical_history_store import CanonicalHistoryStore


class NativeTrialDraftError(RuntimeError):
    """A live-trial DRAFT or its immutable source evidence could not be saved."""


def resolve_native_trial_history_path(
    repo_root: Optional[os.PathLike[str] | str] = None,
    *,
    frozen: Optional[bool] = None,
) -> Path:
    """Honor the explicit runtime root; preserve the source default otherwise."""
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    if is_frozen or str(os.environ.get('YIHUAN_DATA_ROOT') or '').strip():
        from runtime_data import resolve_runtime_data_root

        root = resolve_runtime_data_root() / "native-live-trial"
    else:
        base = Path(repo_root).resolve() if repo_root is not None else Path(__file__).resolve().parents[1]
        root = base / "build" / "native-observation" / "trial-drafts"
    return root / "canonical-history.json"


class NativeTrialDraftStore:
    """A narrow repository wrapper around CanonicalHistoryStore.

    Only live-trial DRAFT records are admitted. Source frames are content-addressed
    and immutable; ordinary frames retain first/latest, with bounded exact-source
    intel frames kept separately rather than recording every observation frame.
    """

    def __init__(self, history_path: os.PathLike[str] | str):
        self.history_path = Path(history_path).resolve()
        self.root = self.history_path.parent
        self.source_frame_root = self.root / "source-frames"
        self._lock = threading.RLock()

    def _store(self) -> CanonicalHistoryStore:
        return CanonicalHistoryStore(self.history_path)

    @staticmethod
    def _is_trial_draft(record: Any) -> bool:
        return (
            isinstance(record, dict)
            and str(record.get("lifecycleStatus") or "").upper() == "DRAFT"
            and str(record.get("dataOrigin") or "").lower() == "live-trial"
        )

    def lookup(self, record_id: str) -> Optional[dict[str, Any]]:
        record = self._store().lookup(record_id)
        return copy.deepcopy(record) if self._is_trial_draft(record) else None

    def list_drafts(self, limit: int = 50) -> list[dict[str, Any]]:
        records = self._store().read_database().get("records") or []
        matches = [
            copy.deepcopy(row)
            for row in records
            if self._is_trial_draft(row)
        ]
        matches.sort(key=lambda row: str(row.get("updatedAt") or row.get("playedAt") or ""), reverse=True)
        return matches[: max(0, int(limit))]

    def _raw_partial_manifest(self, session_id: str) -> Optional[dict[str, Any]]:
        if not re.fullmatch(r"[0-9a-f]{32}", str(session_id or "")):
            return None
        path = self.root / "warehouse-intake" / f"{session_id}.json"
        try:
            if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
                return None
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(manifest, dict):
            return None
        scope = manifest.get("scope")
        pages = manifest.get("pages")
        record_key = scope.get("recordStableKey") if isinstance(scope, dict) else None
        if (
            manifest.get("schemaVersion") != "native-warehouse-intake.v1"
            or manifest.get("sessionId") != session_id
            # Raw originals stay readable while recognition is pending or
            # failed, as well as after it finishes. This reader grants neither
            # content qualification nor coverage; those remain packet/ledger
            # decisions. Do not make original retention depend on OCR state.
            or manifest.get("state") not in {"MANUAL_CAPTURING", "ALIGNING", "PARTIAL", "ERROR", "COMPLETE", "CANCELLED"}
            or not isinstance(record_key, str)
            or not record_key
            or not isinstance(scope.get("observationSessionId"), str)
            or not scope.get("observationSessionId")
            or not isinstance(scope.get("targetInstance"), dict)
            or not scope.get("targetInstance")
            or type(scope.get("matchGeneration")) is not int
            or scope["matchGeneration"] <= 0
            or not isinstance(pages, list)
            or not len(pages)
            or self.lookup(record_key) is None
        ):
            return None
        for page in pages:
            if not isinstance(page, dict):
                return None
            descriptor = page.get("descriptor")
            native_source = page.get("nativeSource")
            width = native_source.get("width") if isinstance(native_source, dict) else None
            height = native_source.get("height") if isinstance(native_source, dict) else None
            if (
                not isinstance(descriptor, dict)
                or descriptor.get("recordStableKey") != record_key
                or not isinstance(native_source, dict)
                or native_source.get("kind") != "native-observation"
                or native_source.get("observationSessionId") != scope["observationSessionId"]
                or native_source.get("targetInstance") != scope["targetInstance"]
                or type(width) is not int
                or type(height) is not int
                or width <= 0
                or height <= 0
                or width * height > 8_388_608
                or type(native_source.get("byteSize")) is not int
                or native_source["byteSize"] != 54 + width * height * 4
                or not re.fullmatch(r"[0-9a-f]{64}", str(native_source.get("sha256") or ""))
                or not re.fullmatch(r"[0-9a-f]{64}", str(page.get("pixelSha256") or ""))
            ):
                return None
        return manifest

    def list_raw_partial_warehouse_archives(self, limit: int = 50) -> list[dict[str, Any]]:
        """List only same-match raw PARTIAL intakes; never promote them to History."""
        directory = self.root / "warehouse-intake"
        try:
            paths = sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        except OSError:
            return []
        result: list[dict[str, Any]] = []
        max_items = min(max(0, int(limit)), 50)
        for path in paths:
            if len(result) >= max_items:
                break
            manifest = self._raw_partial_manifest(path.stem)
            if manifest is None:
                continue
            scope = manifest["scope"]
            result.append({
                "sessionId": manifest["sessionId"],
                "recordStableKey": scope["recordStableKey"],
                "pageCount": len(manifest["pages"]),
                "archiveStatus": "RAW_PARTIAL_ARCHIVED",
                "coverageStatus": "COVERAGE_UNPROVEN",
                "captureState": manifest["state"],
                "terminationReason": str(manifest.get("terminationReason") or "UNKNOWN")[:120],
                "capturePolicy": scope.get("capturePolicy"),
            })
        return result

    def read_raw_partial_warehouse_page(self, session_id: str, page_index: int) -> dict[str, Any]:
        """Return one hash-verified, downscaled preview from an unqualified raw archive."""
        if type(page_index) is not int or page_index < 0:
            return {"ok": False, "status": "INVALID_PAGE_INDEX"}
        manifest = self._raw_partial_manifest(str(session_id or ""))
        if manifest is None:
            return {"ok": False, "status": "RAW_PARTIAL_ARCHIVE_UNAVAILABLE"}
        pages = manifest["pages"]
        if page_index >= len(pages):
            return {"ok": False, "status": "PAGE_NOT_FOUND"}
        page = pages[page_index]
        source = page["nativeSource"]
        verified = self.read_source_image_descriptor(source)
        raw = verified.get("data")
        if verified.get("error") or not isinstance(raw, bytes):
            return {"ok": False, "status": "SOURCE_INTEGRITY_FAILED"}
        if (
            len(raw) < 54
            or raw[:2] != b"BM"
            or len(raw) != 54 + source.get("width", 0) * source.get("height", 0) * 4
            or int.from_bytes(raw[10:14], "little") != 54
            or int.from_bytes(raw[14:18], "little") != 40
            or struct.unpack_from("<ii", raw, 18) != (source.get("width"), -source.get("height"))
            or raw[26:30] != b"\x01\x00\x20\x00"
            or int.from_bytes(raw[30:34], "little") != 0
            or hashlib.sha256(raw).hexdigest() != source.get("sha256")
            or (page.get("bmpSha256") and hashlib.sha256(raw).hexdigest() != page.get("bmpSha256"))
            or (page.get("pixelSha256") and hashlib.sha256(raw[54:]).hexdigest() != page.get("pixelSha256"))
        ):
            return {"ok": False, "status": "SOURCE_INTEGRITY_FAILED"}
        try:
            import cv2
            import numpy as np

            frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
            expected_width, expected_height = source.get("width"), source.get("height")
            if (
                frame is None
                or type(expected_width) is not int
                or type(expected_height) is not int
                or frame.shape[:2] != (expected_height, expected_width)
                or expected_width * expected_height > 8_388_608
            ):
                return {"ok": False, "status": "SOURCE_INTEGRITY_FAILED"}
            scale = min(1.0, 960 / max(expected_width, expected_height))
            if scale < 1.0:
                frame = cv2.resize(frame, (max(1, round(expected_width * scale)), max(1, round(expected_height * scale))))
            encoded, image = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if not encoded:
                return {"ok": False, "status": "PREVIEW_ENCODING_FAILED"}
        except Exception:
            return {"ok": False, "status": "PREVIEW_ENCODING_FAILED"}
        return {
            "ok": True,
            "status": "RAW_PARTIAL_ARCHIVED",
            "coverageStatus": "COVERAGE_UNPROVEN",
            "sessionId": manifest["sessionId"],
            "pageIndex": page_index,
            "pageCount": len(pages),
            "sourceSequence": page.get("sourceSequence"),
            "capturedAt": source.get("capturedAt"),
            "sourceSha256": source.get("sha256"),
            "previewDataUrl": "data:image/jpeg;base64," + base64.b64encode(image.tobytes()).decode("ascii"),
        }

    def patch_inventory_archive(self, record_id: str, settlement_patch: Mapping[str, Any],
                                expected_archive: Mapping[str, Any]) -> dict[str, Any]:
        """Patch only the old trial's settlement branch with an atomic source lease."""
        with self._lock:
            return self._store().update_record_transactional(
                record_id, {"settlement": dict(settlement_patch)},
                expected_inventory_archive=expected_archive,
            )

    def warehouse_capture_attempted(self, record_id: str) -> bool:
        """Even an interrupted marker blocks a second attempt; this is evidence, not billing."""
        key = hashlib.sha256(str(record_id).encode('utf-8')).hexdigest()
        return (self.root / 'warehouse-intake' / 'attempts' / (key + '.json')).exists()

    def claim_warehouse_capture(self, scope: Mapping[str, Any]) -> bool:
        """Durably consume the existing once-per-record permission before opening SOURCE."""
        record_id = str(scope.get('recordStableKey') or '')
        with self._lock:
            if not record_id or self.lookup(record_id) is None:
                raise NativeTrialDraftError('NATIVE_DRAFT_NOT_SAVED')
            key = hashlib.sha256(record_id.encode('utf-8')).hexdigest()
            directory = self.root / 'warehouse-intake' / 'attempts'
            directory.mkdir(parents=True, exist_ok=True)
            try:
                with (directory / (key + '.json')).open('x', encoding='utf-8') as stream:
                    json.dump({'schemaVersion': 'native-warehouse-attempt.v1',
                        'scope': dict(scope), 'attempted': True}, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                return False
            return True

    def capture_frame(self, source_path: os.PathLike[str] | str, metadata: Mapping[str, Any], *, expected_pixel_sha256: Optional[str] = None, max_bytes: Optional[int] = None) -> dict[str, Any]:
        source = Path(source_path).resolve(strict=True)
        if not source.is_file():
            raise NativeTrialDraftError("原始观察帧不存在，草稿尚未保存")
        if max_bytes is None:
            raw = source.read_bytes()
        else:
            if type(max_bytes) is not int or max_bytes <= 0:
                raise NativeTrialDraftError("Invalid original-frame byte limit")
            with source.open("rb") as stream:
                raw = stream.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise NativeTrialDraftError("Original frame exceeds intake byte limit")
        if not raw:
            raise NativeTrialDraftError("原始观察帧为空，草稿尚未保存")
        if expected_pixel_sha256:
            # Host's 32-bit top-down BMP writes the exact worker BGRA buffer after
            # its 54-byte header. A mutable latest-frame path is not provenance.
            if (len(raw) < 54 or raw[:2] != b"BM" or raw[28:30] != b"\x20\x00"
                    or hashlib.sha256(raw[54:]).hexdigest() != expected_pixel_sha256):
                raise NativeTrialDraftError("情报来源帧已被后续采集覆盖；不关联原图")
        digest = hashlib.sha256(raw).hexdigest()
        suffix = source.suffix.lower() if source.suffix.lower() in {".bmp", ".png", ".jpg", ".jpeg"} else ".bin"
        self.source_frame_root.mkdir(parents=True, exist_ok=True)
        target = self.source_frame_root / f"{digest}{suffix}"
        if target.exists():
            if self._sha256(target) != digest:
                raise NativeTrialDraftError("原始证据文件哈希冲突，未覆盖现有文件")
        else:
            temp_name = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=self.source_frame_root, prefix=".frame-", suffix=".tmp", delete=False
                ) as stream:
                    temp_name = stream.name
                    stream.write(raw)
                    stream.flush()
                    try:
                        os.fsync(stream.fileno())
                    except OSError:
                        pass
                if target.exists():
                    if self._sha256(target) != digest:
                        raise NativeTrialDraftError("原始证据文件哈希冲突，未覆盖现有文件")
                else:
                    os.replace(temp_name, target)
                    temp_name = None
            except NativeTrialDraftError:
                raise
            except Exception as exc:
                raise NativeTrialDraftError(f"无法保留原始观察帧：{type(exc).__name__}: {exc}") from exc
            finally:
                if temp_name and Path(temp_name).exists():
                    try:
                        Path(temp_name).unlink()
                    except OSError:
                        pass

        relative_path = target.relative_to(self.root).as_posix()
        meta = dict(metadata or {})
        return {
            "evidenceId": f"native-trial-source:{digest}",
            "kind": "native-observation",
            "source": "native_wgc",
            "relativePath": relative_path,
            "uri": relative_path,
            "mimeType": "image/bmp" if suffix == ".bmp" else "image/png" if suffix == ".png" else "image/jpeg" if suffix in {".jpg", ".jpeg"} else "application/octet-stream",
            "sha256": digest,
            "byteSize": len(raw),
            "width": meta.get("width"),
            "height": meta.get("height"),
            "capturedAt": meta.get("capturedAtUtc"),
            "frameSequence": meta.get("frameSequence"),
            "observationSessionId": meta.get("observationSessionId"),
            "targetInstance": meta.get("targetInstance"),
        }

    def capture_warehouse_slot_source(
        self, source_path: os.PathLike[str] | str, metadata: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Copy one worker-produced activity crop into the existing isolated evidence root."""
        source = Path(source_path).resolve(strict=True)
        if not source.is_file():
            raise NativeTrialDraftError("局内藏品裁图不存在")
        raw = source.read_bytes()
        if not raw:
            raise NativeTrialDraftError("局内藏品裁图为空")
        digest = hashlib.sha256(raw).hexdigest()
        self.source_frame_root.mkdir(parents=True, exist_ok=True)
        target = self.source_frame_root / f"{digest}.png"
        with self._lock:
            if target.exists():
                if self._sha256(target) != digest:
                    raise NativeTrialDraftError("局内藏品裁图哈希冲突，未覆盖已有证据")
            else:
                temp_name = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="wb", dir=self.source_frame_root, prefix=".warehouse-", suffix=".tmp", delete=False
                    ) as stream:
                        temp_name = stream.name
                        stream.write(raw)
                        stream.flush()
                        try:
                            os.fsync(stream.fileno())
                        except OSError:
                            pass
                    if target.exists():
                        if self._sha256(target) != digest:
                            raise NativeTrialDraftError("局内藏品裁图哈希冲突，未覆盖已有证据")
                    else:
                        os.replace(temp_name, target)
                        temp_name = None
                except NativeTrialDraftError:
                    raise
                except Exception as exc:
                    raise NativeTrialDraftError(f"无法保存局内藏品裁图：{type(exc).__name__}: {exc}") from exc
                finally:
                    if temp_name and Path(temp_name).exists():
                        try:
                            Path(temp_name).unlink()
                        except OSError:
                            pass
        meta = dict(metadata or {})
        return {
            **meta,
            "evidenceId": str(meta.get("evidenceId") or f"native-warehouse-crop:{digest}"),
            "kind": "warehouse-activity-crop",
            "relativePath": target.relative_to(self.root).as_posix(),
            "uri": target.relative_to(self.root).as_posix(),
            "mimeType": "image/png",
            "sha256": digest,
            "byteSize": len(raw),
            "workerRelativePath": str(meta.get("relativePath") or ""),
        }

    def save_draft(
        self,
        record: Mapping[str, Any],
        *,
        source_frames: Iterable[Mapping[str, Any]] = (),
        intel_source_frames: Iterable[Mapping[str, Any]] = (),
        warehouse_slot_sources: Iterable[Mapping[str, Any]] = (),
        warehouse_instance_decisions: Iterable[Mapping[str, Any]] = (),
        observation_scope: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        if not isinstance(record, Mapping):
            raise NativeTrialDraftError("草稿内容格式无效")
        draft = copy.deepcopy(dict(record))
        rec_id = str(draft.get("id") or "").strip()
        if not rec_id or draft.get("schemaVersion") != 7 or str(draft.get("lifecycleStatus") or "").upper() != "DRAFT" or str(draft.get("dataOrigin") or "").lower() != "live-trial":
            raise NativeTrialDraftError("仅允许保存 schema v7 的 live-trial DRAFT")

        with self._lock:
            store = self._store()
            existing = store.lookup(rec_id)
            if existing is not None and not self._is_trial_draft(existing):
                raise NativeTrialDraftError("目标记录属于其他数据来源，已拒绝覆盖")

            auction_evidence = draft.get("auctionEvidence")
            if not isinstance(auction_evidence, dict):
                auction_evidence = {}
                draft["auctionEvidence"] = auction_evidence
            prior_native = (existing or {}).get("auctionEvidence") or {}
            prior_native = prior_native.get("nativeObservation") if isinstance(prior_native, dict) else None
            prior_native = prior_native if isinstance(prior_native, dict) else {}
            current_native = auction_evidence.get("nativeObservation")
            current_native = dict(current_native) if isinstance(current_native, dict) else {}
            frames: list[dict[str, Any]] = []
            for candidate in list(prior_native.get("sourceFrames") or []) + list(current_native.get("sourceFrames") or []) + list(source_frames or []):
                if not isinstance(candidate, Mapping):
                    continue
                item = dict(candidate)
                if not item.get("sha256") or not item.get("relativePath"):
                    continue
                if not self._verified_source_path(item):
                    raise NativeTrialDraftError("已关联的原始证据缺失或校验失败，草稿未覆盖")
                if not any(row.get("sha256") == item.get("sha256") for row in frames):
                    frames.append(item)
            if len(frames) > 2:
                frames = [frames[0], frames[-1]]
            scope = dict(observation_scope or {})
            current_native.update({key: scope[key] for key in (
                "profile", "observationSessionId", "targetInstance", "workerFactsRevision",
                "mainFactsRevision", "round", "frameSequence", "capturedAtUtc",
            ) if key in scope})
            current_native["sourceFrames"] = frames
            intel_frames: list[dict[str, Any]] = []
            for candidate in list(prior_native.get("intelSourceFrames") or []) + list(current_native.get("intelSourceFrames") or []) + list(intel_source_frames or []):
                if not isinstance(candidate, Mapping):
                    continue
                item = dict(candidate)
                if not item.get("sha256") or not item.get("relativePath"):
                    continue
                if not self._verified_source_path(item):
                    raise NativeTrialDraftError("已关联的情报原图缺失或校验失败，草稿未覆盖")
                if not any(row.get("observationSessionId") == item.get("observationSessionId")
                           and row.get("frameSequence") == item.get("frameSequence") for row in intel_frames):
                    intel_frames.append(item)
            current_native["intelSourceFrames"] = intel_frames[:24]
            slot_sources_by_instance: dict[str, dict[str, Any]] = {}
            for candidate in list(prior_native.get("warehouseSlotSources") or []) + list(current_native.get("warehouseSlotSources") or []) + list(warehouse_slot_sources or []):
                if not isinstance(candidate, Mapping):
                    continue
                item = dict(candidate)
                if not item.get("evidenceId") or not item.get("sha256") or not item.get("relativePath"):
                    continue
                if not self._verified_source_path(item):
                    raise NativeTrialDraftError("已关联的局内藏品裁图缺失或校验失败，草稿未覆盖")
                instance = item.get("instanceAnchor") if isinstance(item.get("instanceAnchor"), Mapping) else {}
                instance_key = "|".join(str(value) for value in (
                    item.get("matchId"), instance.get("row"), instance.get("col"),
                    instance.get("w"), instance.get("h"), instance.get("rarity"),
                ))
                slot_sources_by_instance[instance_key] = item
            current_native["warehouseSlotSources"] = list(slot_sources_by_instance.values())

            decisions_by_instance: dict[str, dict[str, Any]] = {}
            for candidate in list(prior_native.get("warehouseInstanceDecisions") or []) + list(current_native.get("warehouseInstanceDecisions") or []) + list(warehouse_instance_decisions or []):
                if not isinstance(candidate, Mapping):
                    continue
                item = dict(candidate)
                instance = item.get("instanceAnchor") if isinstance(item.get("instanceAnchor"), Mapping) else {}
                instance_key = "|".join(str(value) for value in (
                    item.get("matchId"), instance.get("row"), instance.get("col"),
                    instance.get("w"), instance.get("h"), instance.get("rarity"),
                ))
                if instance_key.strip("|"):
                    decisions_by_instance[instance_key] = item
            current_native["warehouseInstanceDecisions"] = list(decisions_by_instance.values())
            auction_evidence["nativeObservation"] = current_native
            draft["auctionEvidence"] = auction_evidence
            draft["source"] = "native-live-trial"
            draft["recordStableKey"] = str(draft.get("recordStableKey") or rec_id)

            try:
                return store.persist_record_transactional(
                    draft, is_finalized=False, preserve_archive_sidecars=True
                )
            except Exception as exc:
                raise NativeTrialDraftError(f"DRAFT 保存失败：{type(exc).__name__}: {exc}") from exc

    def update_reviewed_draft(
        self,
        record_id: str,
        patch: Mapping[str, Any],
        *,
        identity_review: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """Update review sidecars only on an existing live-trial DRAFT."""
        with self._lock:
            store = self._store()
            existing = store.lookup(record_id)
            if not self._is_trial_draft(existing):
                raise NativeTrialDraftError("只允许修改已保存的隔离试用草稿")
            try:
                return store.update_record_transactional(
                    record_id, patch, identity_review=identity_review
                )
            except Exception as exc:
                raise NativeTrialDraftError(f"草稿复核保存失败：{type(exc).__name__}: {exc}") from exc

    def discard_draft(self, record_id: str) -> bool:
        """Remove one explicitly discarded isolated DRAFT, leaving source blobs intact."""
        with self._lock:
            store = self._store()
            if not self._is_trial_draft(store.lookup(record_id)):
                return False
            try:
                store.delete_record_transactional(record_id, write_rolling_backup=False)
                return True
            except Exception as exc:
                raise NativeTrialDraftError(f"隔离草稿丢弃失败：{type(exc).__name__}: {exc}") from exc

    def source_images(self, record_id: str) -> list[dict[str, Any]]:
        record = self.lookup(record_id)
        if record is None:
            return []
        native = ((record.get("auctionEvidence") or {}).get("nativeObservation") or {})
        images = []
        descriptors = list(native.get("sourceFrames") or []) + list(native.get("intelSourceFrames") or [])
        seen = set()
        for descriptor in descriptors:
            if not isinstance(descriptor, dict):
                continue
            key = (descriptor.get("observationSessionId"), descriptor.get("frameSequence"),
                   descriptor.get("capturedAt"), descriptor.get("sha256"))
            if key in seen:
                continue
            seen.add(key)
            image = dict(descriptor)
            try:
                path = self._source_path(image)
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != image.get("sha256"):
                    raise NativeTrialDraftError("原始观察帧哈希不匹配")
                image["data"] = raw
            except Exception:
                image["error"] = "原始观察帧缺失或校验失败"
            images.append(image)
        return images

    def warehouse_source_image(self, record_id: str, evidence_id: str) -> Optional[dict[str, Any]]:
        record = self.lookup(record_id)
        if record is None:
            return None
        native = ((record.get("auctionEvidence") or {}).get("nativeObservation") or {})
        descriptor = next((item for item in native.get("warehouseSlotSources") or []
                           if isinstance(item, dict) and item.get("evidenceId") == evidence_id), None)
        if descriptor is None:
            return None
        return self.read_source_image_descriptor(descriptor)

    def read_source_image_descriptor(self, descriptor: Mapping[str, Any]) -> dict[str, Any]:
        """Read one verified image from the isolated evidence root."""
        image = dict(descriptor)
        try:
            path = self._source_path(image)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != image.get("sha256"):
                raise NativeTrialDraftError("局内藏品裁图哈希不匹配")
            image["data"] = raw
        except Exception:
            image["error"] = "局内藏品裁图缺失或校验失败"
        return image

    def _verified_source_path(self, descriptor: Mapping[str, Any]) -> bool:
        try:
            path = self._source_path(descriptor)
            return path.is_file() and self._sha256(path) == str(descriptor.get("sha256") or "").lower()
        except (OSError, ValueError, NativeTrialDraftError):
            return False

    def _source_path(self, descriptor: Mapping[str, Any]) -> Path:
        relative = Path(str(descriptor.get("relativePath") or ""))
        if relative.is_absolute():
            raise NativeTrialDraftError("原始证据路径必须位于试用草稿根目录内")
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.source_frame_root.resolve())
        except ValueError as exc:
            raise NativeTrialDraftError("原始证据路径超出试用证据目录") from exc
        return candidate

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
