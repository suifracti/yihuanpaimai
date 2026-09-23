"""Isolated, reviewable DRAFT storage for the native live-trial profile."""

from __future__ import annotations

import copy
import hashlib
import os
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
    """Keep source runs under build/ and packaged trial data beside its isolated root."""
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    if is_frozen:
        from runtime_data import resolve_runtime_data_root

        root = resolve_runtime_data_root() / "native-live-trial"
    else:
        base = Path(repo_root).resolve() if repo_root is not None else Path(__file__).resolve().parents[1]
        root = base / "build" / "native-observation" / "trial-drafts"
    return root / "canonical-history.json"


class NativeTrialDraftStore:
    """A narrow repository wrapper around CanonicalHistoryStore.

    Only live-trial DRAFT records are admitted. Source frames are content-addressed
    and immutable; the store retains at most the first and latest supplied frame
    for each match rather than recording every observation frame.
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

    def capture_frame(self, source_path: os.PathLike[str] | str, metadata: Mapping[str, Any]) -> dict[str, Any]:
        source = Path(source_path).resolve(strict=True)
        if not source.is_file():
            raise NativeTrialDraftError("原始观察帧不存在，草稿尚未保存")
        raw = source.read_bytes()
        if not raw:
            raise NativeTrialDraftError("原始观察帧为空，草稿尚未保存")
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

    def save_draft(
        self,
        record: Mapping[str, Any],
        *,
        source_frames: Iterable[Mapping[str, Any]] = (),
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
        for descriptor in native.get("sourceFrames") or []:
            if not isinstance(descriptor, dict):
                continue
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
