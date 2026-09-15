"""Manual export of human-reviewed warehouse identity labels.

Reads Canonical History + Store v2 originals. Does not train, write History,
touch Solver, or run unless explicitly invoked with runtime root and output dir.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import cv2
import numpy as np

from canonical_history_store import CanonicalHistoryStore
from runtime_data import HISTORY_FILENAME
from settlement_evidence_store_v2 import KIND_WAREHOUSE, KIND_WAREHOUSE_SEGMENT, SettlementEvidenceStoreV2
from warehouse_identity_review import ACTION_CONFIRM, ACTION_OVERRIDE, CatalogAuthority
from warehouse_identity_review_persist import _assert_current_source, _validate_artifact, WarehouseIdentityReviewPersistError

SCHEMA_VERSION = "warehouse-reviewed-label-dataset.v1"
MIN_TRACKS_PER_QUALITY = 3
MIN_SOURCES = 2
QUALITIES = ("白", "绿", "蓝", "紫", "金", "红")
FORBIDDEN_ACTIONS = {
    "DEFER": "DEFER",
    "MARK_OUT_OF_CATALOG": "MARK_OUT_OF_CATALOG",
    "EXCLUDE_FALSE_COMPONENT": "EXCLUDE_FALSE_COMPONENT",
    "EXCLUDE_FALSE_PLACEMENT": "EXCLUDE_FALSE_PLACEMENT",
    "FLAG_GEOMETRY_ERROR": "FLAG_GEOMETRY_ERROR",
}
LEGACY_89_MARKERS = frozenset({"legacy-89-group", "89-group", "vision-89", "vision-label-89"})
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PNG_PARAMS = [int(cv2.IMWRITE_PNG_COMPRESSION), 9]


class WarehouseReviewedLabelExportError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def export_reviewed_label_bundle(*, runtime_root, output_path):
    """Publish one fresh ZIP atomically; never mix a new manifest with stale crops."""
    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".zip":
        raise WarehouseReviewedLabelExportError("ZIP_REQUIRED")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".reviewed-labels-", dir=target.parent) as temp:
        stage = Path(temp)
        manifest = export_reviewed_label_dataset(runtime_root=runtime_root, output_dir=stage / "dataset")
        archive = stage / "labels.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted((stage / "dataset").rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(stage / "dataset").as_posix())
        os.replace(archive, target)
    return {"ok": True, "status": "SAVED", "outputPath": str(target),
            "sampleCount": len(manifest["samples"]), "rejectedCount": len(manifest["rejected"]),
            "readiness": manifest["readiness"]["status"]}


def group_id_for(record_stable_key: str, track_id: str) -> str:
    return f"{record_stable_key}::{track_id}"


def export_reviewed_label_dataset(*, runtime_root: Path | str, output_dir: Path | str) -> Dict[str, Any]:
    root = Path(runtime_root).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve()
    if not root.is_absolute() or not out.is_absolute():
        raise WarehouseReviewedLabelExportError("PATH_NOT_ABSOLUTE")
    history_path = root / "history" / HISTORY_FILENAME
    if not history_path.is_file():
        raise WarehouseReviewedLabelExportError("HISTORY_MISSING")
    history_bytes = history_path.read_bytes()
    history_sha = hashlib.sha256(history_bytes).hexdigest()
    store = SettlementEvidenceStoreV2(root)
    history = CanonicalHistoryStore(history_path)
    records = list(history.read_database().get("records") or [])
    records.sort(key=lambda item: str((item or {}).get("id") or "") if isinstance(item, Mapping) else "")

    samples: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    crops: List[Tuple[str, bytes]] = []
    authority = None
    uses_v2 = False

    for record in records:
        if not isinstance(record, Mapping):
            rejected.append(_reject(None, None, "INVALID_ARTIFACT"))
            continue
        record_id = str(record.get("id") or "").strip()
        source = str(record.get("source") or "").strip().lower()
        if source in LEGACY_89_MARKERS or record_id.lower().startswith("g89-"):
            rejected.append(_reject(record_id or None, None, "LEGACY_89_GROUP"))
            continue
        try:
            _assert_current_source(record, record_id)
        except WarehouseIdentityReviewPersistError as exc:
            reason = "LEGACY_SOURCE" if exc.code == "LEGACY_SOURCE_FORBIDDEN" else "CONFLICT"
            if exc.code == "CANCELLED_RECORD":
                reason = "CONFLICT"
            rejected.append(_reject(record_id or None, None, reason))
            continue
        settlement = record.get("settlement") if isinstance(record.get("settlement"), Mapping) else {}
        artifact = settlement.get("warehouseIdentityReview") if isinstance(settlement, Mapping) else None
        if not isinstance(artifact, Mapping):
            continue
        try:
            _validate_artifact(artifact)
            if str(artifact.get("recordStableKey") or "") != record_id:
                raise WarehouseIdentityReviewPersistError("RECORD_KEY_MISMATCH")
        except WarehouseIdentityReviewPersistError:
            rejected.append(_reject(record_id, None, "INVALID_ARTIFACT"))
            continue
        is_v2 = artifact.get("schemaVersion") == "warehouse-identity-review.v2"
        uses_v2 = uses_v2 or is_v2
        if artifact.get("reviewerType") != "HUMAN":
            rejected.append(_reject(record_id, None, "NOT_HUMAN_REVIEWED"))
            continue
        id_key = "reviewUnitId" if is_v2 else "trackId"
        coverage = str(artifact.get("warehouseCoverageStatus") or "COVERAGE_UNPROVEN")
        packet_fp = str(artifact.get("packetFingerprint") or "")
        artifact_fp = str(artifact.get("artifactFingerprint") or "")
        for item in artifact.get("unresolvedUnits" if is_v2 else "unresolvedTracks") or []:
            if not isinstance(item, Mapping):
                continue
            action = str(item.get("action") or "NOT_CONFIRMED")
            rejected.append(_reject(record_id, str(item.get(id_key) or "") or None, FORBIDDEN_ACTIONS.get(action, "NOT_CONFIRMED")))
        for item in artifact.get("excludedUnits" if is_v2 else "excludedTracks") or []:
            if not isinstance(item, Mapping):
                continue
            rejected.append(_reject(record_id, str(item.get(id_key) or "") or None, "EXCLUDE_FALSE_PLACEMENT" if is_v2 else "EXCLUDE_FALSE_COMPONENT"))
        for item in artifact.get("resolvedItems") or []:
            if not isinstance(item, Mapping):
                rejected.append(_reject(record_id, None, "NOT_CONFIRMED"))
                continue
            if is_v2:
                uid = str(item.get(id_key) or "")
                if item.get("provenanceType") != "HUMAN_REVIEWED_CATALOG_ID":
                    rejected.append(_reject(record_id, uid, "NOT_HUMAN_REVIEWED"))
                    continue
                decisions = [d for d in artifact.get("decisions") or [] if isinstance(d, Mapping)
                             and d.get(id_key) == uid and d.get("reviewerType") != "AUTO"
                             and d.get("action") == item.get("action")
                             and d.get("selectedCatalogId") == item.get("catalogId")]
                if len(decisions) != 1:
                    rejected.append(_reject(record_id, uid, "HUMAN_DECISION_MISMATCH"))
                    continue
                authority = authority or CatalogAuthority()
                official = authority.get(str(item.get("catalogId") or ""))
                if not official or official.get("name") != item.get("name") or official.get("quality") != item.get("quality"):
                    rejected.append(_reject(record_id, uid, "CATALOG_MISMATCH"))
                    continue
            frames = _frames_for_item(item)
            for frame in frames:
                sample, crop, reason = _build_sample(
                    item=item,
                    frame=frame,
                    store=store,
                    coverage=coverage,
                    packet_fp=packet_fp,
                    artifact_fp=artifact_fp,
                    record_id=record_id,
                )
                if reason:
                    rejected.append(_reject(record_id, str(item.get(id_key) or "") or None, reason))
                    continue
                samples.append(sample)
                crops.append((sample["relativePath"], crop))

    samples.sort(key=lambda item: (item["groupId"], item["sequenceIndex"], item["sampleId"]))
    rejected.sort(key=lambda item: (str(item.get("recordStableKey") or ""), str(item.get("trackId") or ""), item["reason"]))
    readiness = _readiness(samples)
    manifest = {
        "schemaVersion": "warehouse-reviewed-label-dataset.v2" if uses_v2 else SCHEMA_VERSION,
        "historySha256": history_sha,
        "splitPolicy": {"unit": "groupId", "rule": "SPLIT_BY_GROUP_NEVER_SPLIT_ITEM_FRAMES"},
        "samples": samples,
        "rejected": rejected,
        "readiness": readiness,
    }
    if uses_v2:
        for sample in samples:
            sample["splitGroupId"] = sample["recordStableKey"]
        manifest["splitPolicy"] = {"unit": "splitGroupId", "rule": "SPLIT_BY_MATCH_NEVER_SPLIT_MATCH_ITEMS_OR_FRAMES"}
    _write_export(out, manifest, crops)
    return manifest


def iter_item_frames(item: Mapping[str, Any], extra_frames: Optional[Sequence[Mapping[str, Any]]] = None) -> List[Dict[str, Any]]:
    frames = _frames_for_item(item)
    for extra in extra_frames or []:
        if isinstance(extra, Mapping):
            frames.append({
                "evidenceId": str(extra.get("evidenceId") or ""),
                "bbox": list(extra.get("bbox") or []),
                "sequenceIndex": int(extra.get("sequenceIndex") or 0),
                "sha256": str(extra.get("sha256") or item.get("sha256") or ""),
            })
    frames.sort(key=lambda frame: (int(frame.get("sequenceIndex") or 0), str(frame.get("evidenceId") or "")))
    return frames


def _frames_for_item(item: Mapping[str, Any]) -> List[Dict[str, Any]]:
    frames = [{
        "evidenceId": str(item.get("evidenceId") or ""),
        "bbox": list(item.get("bbox") or []),
        "sequenceIndex": int(item.get("sequenceIndex") or 0),
        "sha256": str(item.get("sha256") or ""),
    }]
    extras = item.get("observations")
    if isinstance(extras, list):
        for extra in extras:
            if not isinstance(extra, Mapping):
                continue
            frames.append({
                "evidenceId": str(extra.get("evidenceId") or item.get("evidenceId") or ""),
                "bbox": list(extra.get("bbox") or item.get("bbox") or []),
                "sequenceIndex": int(extra.get("sequenceIndex") or 0),
                "sha256": str(extra.get("sha256") or item.get("sha256") or ""),
            })
    unique = []
    seen = set()
    for frame in frames:
        token = (frame["evidenceId"], frame["sequenceIndex"], tuple(frame["bbox"]))
        if token in seen:
            continue
        seen.add(token)
        unique.append(frame)
    return unique


def _build_sample(
    *,
    item: Mapping[str, Any],
    frame: Mapping[str, Any],
    store: SettlementEvidenceStoreV2,
    coverage: str,
    packet_fp: str,
    artifact_fp: str,
    record_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[bytes], Optional[str]]:
    action = str(item.get("action") or "")
    if action not in {ACTION_CONFIRM, ACTION_OVERRIDE}:
        return None, None, FORBIDDEN_ACTIONS.get(action, "NOT_CONFIRMED")
    track_id = str(item.get("reviewUnitId") or item.get("trackId") or "").strip()
    if not track_id:
        return None, None, "NOT_CONFIRMED"
    evidence_id = str(frame.get("evidenceId") or "").strip()
    bbox = frame.get("bbox")
    if not evidence_id or not isinstance(bbox, list) or len(bbox) != 4:
        return None, None, "INVALID_BBOX"
    expected_hash = str(frame.get("sha256") or "")
    if not SHA256_RE.fullmatch(expected_hash):
        return None, None, "HASH_MISMATCH"
    try:
        descriptor = _find_descriptor(store, record_id, evidence_id)
    except Exception:
        return None, None, "MISSING_ORIGINAL"
    if descriptor is None:
        return None, None, "MISSING_ORIGINAL"
    kind = str(descriptor.get("kind") or "")
    if kind == KIND_WAREHOUSE:
        return None, None, "THUMBNAIL_ONLY"
    if kind != KIND_WAREHOUSE_SEGMENT:
        return None, None, "INVALID_DESCRIPTOR"
    if str(descriptor.get("recordStableKey") or "") != record_id:
        return None, None, "INVALID_DESCRIPTOR"
    if str(descriptor.get("sha256") or "") != expected_hash:
        return None, None, "HASH_MISMATCH"
    try:
        original = store.load_original(descriptor)
    except Exception:
        return None, None, "MISSING_ORIGINAL"
    actual = hashlib.sha256(original).hexdigest()
    if actual != expected_hash:
        return None, None, "HASH_MISMATCH"
    try:
        crop = _crop_png(original, bbox)
    except WarehouseReviewedLabelExportError as exc:
        return None, None, exc.code
    group_id = group_id_for(record_id, track_id)
    sequence = int(frame.get("sequenceIndex") or 0)
    relative = _crop_relative(record_id, track_id, sequence, evidence_id)
    sample_id = hashlib.sha256(
        f"{group_id}|{evidence_id}|{sequence}|{bbox}|{hashlib.sha256(crop).hexdigest()}".encode("utf-8")
    ).hexdigest()
    sample = {
        "sampleId": sample_id,
        "groupId": group_id,
        "recordStableKey": record_id,
        "trackId": track_id,
        "sequenceIndex": sequence,
        "catalogId": str(item.get("catalogId") or ""),
        "name": str(item.get("name") or ""),
        "quality": None if item.get("quality") in (None, "") else str(item.get("quality")),
        "action": action,
        "warehouseCoverage": coverage if coverage in {"COVERAGE_UNPROVEN", "PARTIAL", "COMPLETE"} else "COVERAGE_UNPROVEN",
        "solverEligible": False,
        "trainingEligible": True,
        "relativePath": relative,
        "cropSha256": hashlib.sha256(crop).hexdigest(),
        "artifactFingerprint": artifact_fp,
        "packetFingerprint": packet_fp,
        "evidenceId": evidence_id,
        "sourceSha256": expected_hash,
        "kind": KIND_WAREHOUSE_SEGMENT,
    }
    if item.get("reviewUnitId"):
        sample.update(reviewUnitId=track_id, provenanceType="HUMAN_REVIEWED_CATALOG_ID",
                      splitGroupId=record_id)
    return sample, crop, None


def _find_descriptor(store: SettlementEvidenceStoreV2, record_id: str, evidence_id: str) -> Optional[Dict[str, Any]]:
    for item in store.list_record_evidence(record_id):
        if str(item.get("evidenceId") or "") == evidence_id:
            return item
    return None


def _crop_png(image_bytes: bytes, bbox: Sequence[Any]) -> bytes:
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or getattr(image, "size", 0) == 0:
        raise WarehouseReviewedLabelExportError("MISSING_ORIGINAL")
    height, width = image.shape[:2]
    if (len(bbox) != 4 or any(isinstance(value, bool) or not isinstance(value, (int, float))
                              or not math.isfinite(value) for value in bbox)
            or not (0 <= bbox[0] < bbox[2] <= width and 0 <= bbox[1] < bbox[3] <= height)):
        raise WarehouseReviewedLabelExportError("INVALID_BBOX")
    try:
        x1 = int(round(float(bbox[0])))
        y1 = int(round(float(bbox[1])))
        x2 = int(round(float(bbox[2])))
        y2 = int(round(float(bbox[3])))
    except (TypeError, ValueError, IndexError) as exc:
        raise WarehouseReviewedLabelExportError("INVALID_BBOX") from exc
    if x2 <= x1 or y2 <= y1 or x1 >= width or y1 >= height or x2 <= 0 or y2 <= 0:
        raise WarehouseReviewedLabelExportError("INVALID_BBOX")
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        raise WarehouseReviewedLabelExportError("INVALID_BBOX")
    ok, buf = cv2.imencode(".png", crop, PNG_PARAMS)
    if not ok:
        raise WarehouseReviewedLabelExportError("INVALID_BBOX")
    return buf.tobytes()


def _crop_relative(record_id: str, track_id: str, sequence: int, evidence_id: str) -> str:
    return f"crops/{_safe(record_id)}/{_safe(track_id)}/{int(sequence):04d}_{_safe(evidence_id)}.png"


def _safe(value: str) -> str:
    text = SAFE_ID_RE.sub("-", str(value or "").strip()) or "x"
    return text[:96]


def _reject(record_id: Optional[str], track_id: Optional[str], reason: str) -> Dict[str, Any]:
    return {
        "recordStableKey": record_id,
        "trackId": track_id,
        "reason": reason,
    }


def _readiness(samples: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_quality = {name: {"tracks": set(), "sources": set()} for name in QUALITIES}
    all_tracks = set()
    all_sources = set()
    for item in samples:
        quality = item.get("quality")
        group_id = item.get("groupId")
        source = item.get("recordStableKey")
        all_tracks.add(group_id)
        all_sources.add(source)
        if quality in by_quality:
            by_quality[quality]["tracks"].add(group_id)
            by_quality[quality]["sources"].add(source)
    stats = {}
    reasons: List[str] = []
    present_ready = True
    present_count = 0
    for name in QUALITIES:
        track_count = len(by_quality[name]["tracks"])
        source_count = len(by_quality[name]["sources"])
        stats[name] = {"trackCount": track_count, "sourceCount": source_count}
        if track_count == 0:
            continue
        present_count += 1
        if track_count < MIN_TRACKS_PER_QUALITY or source_count < MIN_SOURCES:
            present_ready = False
            reasons.append(f"QUALITY_{name}_INSUFFICIENT")
    status = "INSUFFICIENT_EVIDENCE"
    if present_count == 0:
        reasons.append("NO_ELIGIBLE_SAMPLES")
    elif not present_ready:
        reasons.append("QUALITY_GATES_FAILED")
    elif len(all_sources) < MIN_SOURCES:
        present_ready = False
        reasons.append("SOURCE_COUNT_INSUFFICIENT")
    else:
        status = "TRAINING_READY"
        reasons = []
    reasons.sort()
    return {
        "status": status,
        "minTracksPerQuality": MIN_TRACKS_PER_QUALITY,
        "minSources": MIN_SOURCES,
        "byQuality": stats,
        "eligibleTrackCount": len(all_tracks),
        "eligibleSourceCount": len(all_sources),
        "reasons": reasons,
    }


def _write_export(output_dir: Path, manifest: Mapping[str, Any], crops: Iterable[Tuple[str, bytes]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for relative, payload in crops:
        path = output_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    manifest_path = output_dir / "manifest.json"
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(encoded, encoding="utf-8")
