"""Bounded, source-bound settlement inventory continuation for isolated drafts.

This is historical work, never a late result for CurrentMatch. The pending
state lives in the same DRAFT so a process restart can resume it.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Mapping

import cv2
import numpy as np

from native_trial_drafts import NativeTrialDraftStore


def _archive_source(record: Mapping[str, Any]) -> dict[str, Any] | None:
    native = ((record.get("auctionEvidence") or {}).get("nativeObservation") or {})
    frames = native.get("sourceFrames") or []
    for source in reversed(frames):
        if (source.get("settlementBoundary") is True and source.get("pixelSha256")
                and source.get("observationSessionId") and source.get("targetInstance")
                and type(source.get("frameSequence")) is int and source.get("capturedAt")):
            return source
    return None


def _archive_key(record_id: str, source: Mapping[str, Any]) -> str:
    return hashlib.sha256("|".join(str(value) for value in (
        record_id, source["observationSessionId"], source["targetInstance"],
        source["frameSequence"], source["capturedAt"], source["pixelSha256"],
    )).encode("utf-8")).hexdigest()


def recognize_saved_inventory(store: NativeTrialDraftStore, record_id: str,
                              source: Mapping[str, Any]) -> dict[str, Any]:
    """Reuse existing recognizer and evidence store on one immutable source."""
    from settlement_evidence_store_v2 import COVERAGE_UNPROVEN, KIND_MAIN, SettlementEvidenceStoreV2
    from settlement_item_proposals import extract_settlement_warehouse_proposals
    from settlement_item_recognizer import SettlementItemRecognizer
    from settlement_stable_frame_persist import encode_settlement_original

    verified = store.read_source_image_descriptor(source)
    raw = verified.get("data")
    if (not raw or raw[:2] != b"BM" or raw[28:30] != b"\x20\x00"
            or hashlib.sha256(raw[54:]).hexdigest() != source["pixelSha256"]):
        raise ValueError("结算来源原图校验失败")
    frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        raise ValueError("结算来源原图无法解码")
    record = store.lookup(record_id)
    if record is None:
        raise ValueError("绑定的原局隔离草稿不存在")
    recognizer = SettlementItemRecognizer()
    ledger = recognizer.parse_settlement_ledger(frame, (record.get("settlement") or {}).get("actualTotal"))
    evidence_store = SettlementEvidenceStoreV2(store.root)
    parent = evidence_store.save_original(
        record_stable_key=record_id, kind=KIND_MAIN,
        image_bytes=encode_settlement_original(frame), captured_at=source["capturedAt"],
        coverage_mode="viewport-segment", coverage_status=COVERAGE_UNPROVEN,
    )
    proposals = extract_settlement_warehouse_proposals(
        store=evidence_store, parent_descriptor=parent, recognizer=recognizer, save_crops=True)
    by_geometry = {}
    for proposal in proposals:
        cells = proposal.get("gridCells") or []
        if cells:
            by_geometry[(min(cell[0] for cell in cells), min(cell[1] for cell in cells),
                         proposal["widthCells"], proposal["heightCells"])] = proposal
    items = []
    for item in ledger["settlementItems"]:
        key = (item["row"], item["col"], item["widthCells"], item["heightCells"])
        proposal = by_geometry.get(key)
        if proposal is None:
            raise ValueError(f"结算区域缺少同源裁图：{key}")
        linked = copy.deepcopy(item)
        linked.update(sourcePhase="SETTLEMENT", sourceCapturedAt=source["capturedAt"],
                      parentEvidenceId=parent["evidenceId"], parentSha256=parent["sha256"],
                      cropEvidenceId=proposal["cropEvidenceId"],
                      cropRelativePath=proposal["cropRelativePath"], cropSha256=proposal["cropSha256"])
        linked["identityEvidence"].update(
            recordStableKey=record_id, parentEvidenceId=parent["evidenceId"],
            parentSha256=parent["sha256"], cropEvidenceId=proposal["cropEvidenceId"],
            cropRelativePath=proposal["cropRelativePath"], cropSha256=proposal["cropSha256"])
        items.append(linked)
    if not items:
        raise ValueError("结算终帧没有可关联的可见清单区域")
    visible = {
        "sourcePhase": "SETTLEMENT", "sourceFrameSequence": source["frameSequence"],
        "sourceCapturedAt": source["capturedAt"], "sourcePixelSha256": source["pixelSha256"],
        "parentEvidenceId": parent["evidenceId"], "parentSha256": parent["sha256"],
        "visibleProposalCount": len(items),
        "trustedReferenceMatchCount": sum(item["status"] == "exact" for item in items),
        "coverageStatus": "PARTIAL_VIEWPORT_ONLY", "outsideViewport": "UNKNOWN",
        "itemLedgerVerified": False,
    }
    return {"settlementItems": items, "visibleInventory": visible}


class SettlementInventoryArchive:
    MAX_QUEUED = 8

    def __init__(self, store: NativeTrialDraftStore,
                 processor: Callable[[NativeTrialDraftStore, str, Mapping[str, Any]], dict[str, Any]] = recognize_saved_inventory):
        self.store = store
        self.processor = processor
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="settlement-archive")
        self._scheduled: set[str] = set()
        self._schedule_lock = threading.RLock()

    def enqueue_saved_draft(self, record: Mapping[str, Any]) -> str | None:
        record_id = str(record.get("id") or "")
        source = _archive_source(record)
        if not record_id or source is None or self.store.lookup(record_id) is None:
            return None
        key = _archive_key(record_id, source)
        old = ((self.store.lookup(record_id) or {}).get("settlement") or {}).get("inventoryArchive") or {}
        if old.get("sourceKey") == key:
            if old.get("status") in ("PENDING", "PROCESSING"):
                self._schedule(record_id, key)
            return str(old.get("status") or "")
        if old:
            prior_source = old.get("source") or {}
            if prior_source.get("observationSessionId") != source["observationSessionId"]:
                return None  # no cross-session chronology inference
            prior_sequence = prior_source.get("frameSequence")
            if type(prior_sequence) is not int or prior_sequence >= source["frameSequence"]:
                return None
        archive = {"sourceKey": key, "status": "PENDING", "source": copy.deepcopy(source),
                   "capturedAt": source["capturedAt"], "attempts": 0}
        self.store.patch_inventory_archive(record_id, {"inventoryArchive": archive},
                                           {"sourceKey": old.get("sourceKey")})
        self._schedule(record_id, key)
        return "PENDING"

    def _schedule(self, record_id: str, key: str) -> None:
        with self._schedule_lock:
            if key in self._scheduled or len(self._scheduled) >= self.MAX_QUEUED:
                return
            self._scheduled.add(key)
            future = self.executor.submit(self.process, record_id, key)
            future.add_done_callback(lambda _: self._finished(key))

    def _finished(self, key: str) -> None:
        with self._schedule_lock:
            self._scheduled.discard(key)
        # Keep the executor queue bounded; pending DRAFTs are the durable
        # backlog, not an unbounded in-memory task list.
        try:
            for record in self.store.list_drafts(limit=100000):
                archive = (record.get("settlement") or {}).get("inventoryArchive") or {}
                next_key = archive.get("sourceKey")
                if next_key and next_key not in self._scheduled and archive.get("status") in ("PENDING", "PROCESSING"):
                    self._schedule(record["id"], next_key)
                    break
        except RuntimeError:
            pass  # executor is closing; next launch resumes the DRAFT backlog
        except Exception:
            logging.getLogger(__name__).exception("settlement archive backlog scan failed")

    def process(self, record_id: str, key: str) -> str:
        record = self.store.lookup(record_id)
        archive = ((record or {}).get("settlement") or {}).get("inventoryArchive") or {}
        if archive.get("sourceKey") != key or archive.get("status") not in ("PENDING", "PROCESSING"):
            return "SKIPPED"
        source = archive.get("source") or {}
        try:
            if source.get("settlementBoundary") is not True or _archive_key(record_id, source) != key:
                raise ValueError("结算归档任务与原局/原帧绑定不一致")
            if archive["status"] == "PENDING":
                self.store.patch_inventory_archive(record_id, {"inventoryArchive": {
                    **archive, "status": "PROCESSING", "attempts": int(archive.get("attempts") or 0) + 1,
                }}, {"sourceKey": key, "status": "PENDING"})
            result = self.processor(self.store, record_id, source)
            visible = result.get("visibleInventory") if isinstance(result, dict) else None
            if (not isinstance(visible, dict) or visible.get("sourcePixelSha256") != source["pixelSha256"]
                    or visible.get("sourceFrameSequence") != source["frameSequence"]
                    or visible.get("sourceCapturedAt") != source["capturedAt"]):
                raise ValueError("结算识别结果不属于绑定原帧")
            latest = self.store.lookup(record_id)
            current = ((latest or {}).get("settlement") or {}).get("inventoryArchive") or {}
            if current.get("sourceKey") != key or current.get("status") != "PROCESSING":
                return "SKIPPED"
            # A review may have been added while recognition ran. Only the
            # machine inventory fields are patched; review and prediction stay.
            self.store.patch_inventory_archive(record_id, {
                **result, "inventoryArchive": {**current, "status": "SAVED", "error": None},
            }, {"sourceKey": key, "status": "PROCESSING"})
            return "SAVED"
        except Exception as exc:
            current = (((self.store.lookup(record_id) or {}).get("settlement") or {})
                       .get("inventoryArchive") or {})
            if current.get("sourceKey") == key and current.get("status") == "PROCESSING":
                try:
                    self.store.patch_inventory_archive(record_id, {"inventoryArchive": {
                        **current, "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"[:240],
                    }}, {"sourceKey": key, "status": "PROCESSING"})
                except Exception:
                    logging.getLogger(__name__).exception("failed to persist settlement archive failure for %s", record_id)
            return "FAILED"

    def retry(self, record_id: str) -> str:
        record = self.store.lookup(record_id)
        archive = ((record or {}).get("settlement") or {}).get("inventoryArchive") or {}
        if archive.get("status") != "FAILED":
            return "NOT_FAILED"
        key = archive["sourceKey"]
        self.store.patch_inventory_archive(record_id, {"inventoryArchive": {
            **archive, "status": "PENDING", "error": None,
        }}, {"sourceKey": key, "status": "FAILED"})
        # A retry can arrive before the failed future's done callback clears
        # its in-memory marker. Queue behind it regardless; the persisted
        # PENDING/PROCESSING lease still prevents duplicate commits.
        self.executor.submit(self.process, record_id, key)
        return "PENDING"

    def resume_pending(self) -> int:
        count = 0
        for record in self.store.list_drafts(limit=100000):
            try:
                archive = (record.get("settlement") or {}).get("inventoryArchive") or {}
                if archive.get("status") in ("PENDING", "PROCESSING") and archive.get("sourceKey"):
                    self._schedule(record["id"], archive["sourceKey"])
                    count += 1
                elif not archive and _archive_source(record) is not None:
                    # The original was saved but process termination interrupted
                    # the tiny enqueue window after the DRAFT commit.
                    if self.enqueue_saved_draft(record) == "PENDING":
                        count += 1
            except Exception:
                # This record remains visible as pending in its DRAFT; do not
                # prevent unrelated old matches from resuming.
                logging.getLogger(__name__).exception("settlement archive resume failed for %s", record.get("id"))
                continue
        return count
