"""Evidence-backed warehouse review packet.

Read-only composition of Coverage Ledger, physical tracks, geometry
candidates, and Store v2 warehouse-segment descriptors. Does not select
identities, write History, or decide catalog completeness.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from settlement_truth_evidence_contract import RECORD_KEY_RE
from warehouse_catalog_geometry import (
    COVERAGE_UNVERIFIED,
    CatalogGeometryIndex,
    resolve_catalog_candidates,
)
from warehouse_coverage_ledger import STATUS_COMPLETE, STATUS_PARTIAL, STATUS_UNPROVEN

SCHEMA_VERSION = "warehouse-review-packet.v1"
SCHEMA_VERSION_V2 = "warehouse-review-packet.v2"
KIND_WAREHOUSE_SEGMENT = "warehouse-segment"
SHA256_RE = __import__("re").compile(r"^[0-9a-f]{64}$")

REVIEW_REQUIRED = "REVIEW_REQUIRED"
PARTIAL_EVIDENCE = "PARTIAL_EVIDENCE"
NOT_REVIEWABLE = "NOT_REVIEWABLE"

PACKET_KEYS = frozenset({
    "schemaVersion",
    "recordStableKey",
    "sourceFingerprint",
    "warehouseCoverage",
    "catalogCoverageStatus",
    "reviewStatus",
    "segments",
    "tracks",
    "summary",
})
PACKET_V2_KEYS = frozenset({
    "schemaVersion",
    "recordStableKey",
    "sourceFingerprint",
    "warehouseCoverage",
    "catalogCoverageStatus",
    "reviewStatus",
    "segments",
    "reviewUnits",
    "summary",
})
SEGMENT_KEYS = frozenset({
    "evidenceId",
    "kind",
    "sequenceIndex",
    "sha256",
    "width",
    "height",
    "coverageStatus",
    "topEndpointTrusted",
    "bottomEndpointTrusted",
})
TRACK_KEYS = frozenset({
    "trackId",
    "status",
    "clipped",
    "geometryEvidenceStatus",
    "pixelOnly",
    "identityStatus",
    "selectedCatalogId",
    "bestObservationId",
    "observations",
    "candidateStatus",
    "candidates",
    "widthCandidates",
    "heightCandidates",
    "spanCandidates",
})
REVIEW_UNIT_KEYS = frozenset({
    "reviewUnitId",
    "placementStatus",
    "visibility",
    "worldAnchor",
    "footprint",
    "physicalGroupId",
    "geometryEvidenceStatus",
    "identityStatus",
    "selectedCatalogId",
    "bestObservationId",
    "supportingTrackIds",
    "observations",
    "candidateStatus",
    "candidates",
    "widthCandidates",
    "heightCandidates",
    "spanCandidates",
})
WORLD_ANCHOR_KEYS = frozenset({"row", "col"})
FOOTPRINT_KEYS = frozenset({"widthCells", "heightCells"})
OBS_KEYS = frozenset({"observationId", "evidenceId", "sequenceIndex", "bbox", "status", "localGridBbox"})


class WarehouseReviewPacketError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def canonical_warehouse_review_packet(packet: Mapping[str, Any]) -> str:
    return json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True)


def source_fingerprint_for(packet: Mapping[str, Any]) -> str:
    body = {key: packet[key] for key in sorted(packet) if key != "sourceFingerprint"}
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_warehouse_review_packet(packet: Any) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if not isinstance(packet, Mapping):
        return False, ["PACKET_NOT_OBJECT"]
    
    version = packet.get("schemaVersion")
    if version not in (SCHEMA_VERSION, SCHEMA_VERSION_V2):
        reasons.append("SCHEMA_VERSION_INVALID")
        
    allowed_keys = PACKET_V2_KEYS if version == SCHEMA_VERSION_V2 else PACKET_KEYS
    extra = [key for key in packet.keys() if key not in allowed_keys]
    reasons.extend(f"UNKNOWN_FIELD_{key}" for key in extra)
    missing = [key for key in allowed_keys if key not in packet]
    reasons.extend(f"MISSING_{key}" for key in missing)
    
    if not RECORD_KEY_RE.fullmatch(str(packet.get("recordStableKey") or "")):
        reasons.append("RECORD_STABLE_KEY_INVALID")
    if not SHA256_RE.fullmatch(str(packet.get("sourceFingerprint") or "")):
        reasons.append("SOURCE_FINGERPRINT_INVALID")
    coverage = packet.get("warehouseCoverage")
    if not isinstance(coverage, Mapping):
        reasons.append("COVERAGE_NOT_OBJECT")
    else:
        if set(coverage) - {"status", "segmentCount", "terminationReason"}:
            reasons.append("COVERAGE_UNKNOWN_FIELD")
        if coverage.get("status") not in {STATUS_UNPROVEN, STATUS_PARTIAL, STATUS_COMPLETE}:
            reasons.append("COVERAGE_STATUS_INVALID")
        if coverage.get("status") == STATUS_COMPLETE and packet.get("reviewStatus") not in {
            REVIEW_REQUIRED,
            NOT_REVIEWABLE,
        }:
            reasons.append("COMPLETE_IDENTITY_NOT_ISOLATED")
    if packet.get("reviewStatus") not in {REVIEW_REQUIRED, PARTIAL_EVIDENCE, NOT_REVIEWABLE}:
        reasons.append("REVIEW_STATUS_INVALID")
    summary = packet.get("summary")
    if isinstance(summary, Mapping):
        if summary.get("reviewedIdentityCount") != 0:
            reasons.append("REVIEWED_IDENTITY_NOT_ZERO")
        if "totalItems" in summary:
            reasons.append("TOTAL_ITEMS_FORBIDDEN")
    blob = json.dumps(packet, ensure_ascii=False)
    for token in ("relativePath", "imageBytes", "C:\\\\", "/Users/", "knownItems"):
        if token in blob:
            reasons.append("FORBIDDEN_PAYLOAD_TOKEN")
            break

    if version == SCHEMA_VERSION_V2:
        units = packet.get("reviewUnits")
        if isinstance(units, list):
            for unit in units:
                if not isinstance(unit, Mapping):
                    continue
                extra_u = [k for k in unit.keys() if k not in REVIEW_UNIT_KEYS]
                reasons.extend(f"UNKNOWN_FIELD_{k}" for k in extra_u)
                if unit.get("placementStatus") not in {"RESOLVED", "AMBIGUOUS_REGION", "UNKNOWN"}:
                    reasons.append("PLACEMENT_STATUS_INVALID")
                if unit.get("visibility") not in {"FULL", "CLIPPED"}:
                    reasons.append("VISIBILITY_INVALID")
                anchor = unit.get("worldAnchor")
                if not isinstance(anchor, Mapping) or set(anchor) != WORLD_ANCHOR_KEYS:
                    reasons.append("WORLD_ANCHOR_INVALID")
                footprint = unit.get("footprint")
                if not isinstance(footprint, Mapping) or set(footprint) != FOOTPRINT_KEYS:
                    reasons.append("FOOTPRINT_INVALID")
                supp = unit.get("supportingTrackIds")
                if not isinstance(supp, list) or len(supp) == 0:
                    reasons.append("SUPPORTING_TRACKS_EMPTY")
                if unit.get("selectedCatalogId") is not None:
                    reasons.append("SELECTED_CATALOG_NOT_NULL")
                if unit.get("identityStatus") not in {REVIEW_REQUIRED, NOT_REVIEWABLE}:
                    reasons.append("IDENTITY_STATUS_INVALID")
                for candidate in unit.get("candidates") or []:
                    if isinstance(candidate, Mapping) and candidate.get("identityStatus") != "CANDIDATE_ONLY":
                        reasons.append("CANDIDATE_NOT_MARKED")
    else:
        tracks = packet.get("tracks")
        if isinstance(tracks, list):
            for track in tracks:
                if not isinstance(track, Mapping):
                    continue
                extra_t = [k for k in track.keys() if k not in TRACK_KEYS]
                reasons.extend(f"UNKNOWN_FIELD_{k}" for k in extra_t)
                if track.get("selectedCatalogId") is not None:
                    reasons.append("SELECTED_CATALOG_NOT_NULL")
                if track.get("identityStatus") not in {REVIEW_REQUIRED, NOT_REVIEWABLE}:
                    reasons.append("IDENTITY_STATUS_INVALID")
                for candidate in track.get("candidates") or []:
                    if isinstance(candidate, Mapping) and candidate.get("identityStatus") != "CANDIDATE_ONLY":
                        reasons.append("CANDIDATE_NOT_MARKED")
    return len(reasons) == 0, reasons


def build_warehouse_review_packet(
    *,
    coverage_ledger: Mapping[str, Any],
    physical_ledger: Mapping[str, Any],
    descriptors: Sequence[Mapping[str, Any]],
    catalog_index: Optional[CatalogGeometryIndex] = None,
    segment_evidence_map: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    key = str(coverage_ledger.get("recordStableKey") or "").strip()
    physical_key = str(physical_ledger.get("recordStableKey") or "").strip()
    if not RECORD_KEY_RE.fullmatch(key):
        raise WarehouseReviewPacketError("INVALID_RECORD_KEY")
    if physical_key and physical_key != key:
        raise WarehouseReviewPacketError("RECORD_KEY_MISMATCH")

    coverage_status = str(coverage_ledger.get("coverageStatus") or STATUS_UNPROVEN)
    if coverage_status == STATUS_COMPLETE:
        if not coverage_ledger.get("finalized") or coverage_ledger.get("terminationReason") != "COMPLETE":
            raise WarehouseReviewPacketError("COMPLETE_NOT_FINALIZED")

    descriptor_by_id = _index_descriptors(descriptors, key)
    segments = _packet_segments(coverage_ledger, descriptor_by_id)
    evidence_by_sequence = {item["sequenceIndex"]: item["evidenceId"] for item in segments}
    evidence_by_segment_id = dict(segment_evidence_map or {})
    physical_segments = {
        str(item.get("segmentId")): item
        for item in (physical_ledger.get("segments") or [])
        if isinstance(item, Mapping)
    }
    for item in physical_segments.values():
        sequence = item.get("sequenceIndex")
        if sequence in evidence_by_sequence and str(item.get("segmentId")) not in evidence_by_segment_id:
            evidence_by_segment_id[str(item.get("segmentId"))] = evidence_by_sequence[sequence]

    index = catalog_index or CatalogGeometryIndex()
    tracks = _packet_tracks(
        physical_ledger,
        evidence_by_segment_id,
        descriptor_by_id,
        physical_segments,
        index,
    )
    review_status = _review_status(coverage_status, tracks)
    packet = {
        "schemaVersion": SCHEMA_VERSION,
        "recordStableKey": key,
        "sourceFingerprint": "0" * 64,
        "warehouseCoverage": {
            "status": coverage_status,
            "segmentCount": len(segments),
            "terminationReason": coverage_ledger.get("terminationReason"),
        },
        "catalogCoverageStatus": index.catalog_coverage_status or COVERAGE_UNVERIFIED,
        "reviewStatus": review_status,
        "segments": segments,
        "tracks": tracks,
        "summary": {
            "visibleTrackCount": len(tracks),
            "candidateReadyCount": sum(1 for item in tracks if item["candidates"]),
            "conflictCount": sum(1 for item in tracks if item["status"] == "CONFLICT"),
            "reviewedIdentityCount": 0,
        },
    }
    packet["sourceFingerprint"] = source_fingerprint_for(packet)
    ok, reasons = validate_warehouse_review_packet(packet)
    if not ok:
        raise WarehouseReviewPacketError("INVALID_PACKET", ",".join(reasons))
    return packet


def build_warehouse_review_packet_v2(
    *,
    coverage_ledger: Mapping[str, Any],
    review_units: Sequence[Mapping[str, Any]],
    descriptors: Sequence[Mapping[str, Any]],
    catalog_coverage_status: str = COVERAGE_UNVERIFIED,
) -> Dict[str, Any]:
    key = str(coverage_ledger.get("recordStableKey") or "").strip()
    if not RECORD_KEY_RE.fullmatch(key):
        raise WarehouseReviewPacketError("INVALID_RECORD_KEY")

    coverage_status = str(coverage_ledger.get("coverageStatus") or STATUS_UNPROVEN)
    if coverage_status == STATUS_COMPLETE:
        if not coverage_ledger.get("finalized") or coverage_ledger.get("terminationReason") != "COMPLETE":
            raise WarehouseReviewPacketError("COMPLETE_NOT_FINALIZED")

    descriptor_by_id = _index_descriptors(descriptors, key)
    segments = _packet_segments(coverage_ledger, descriptor_by_id)

    if coverage_status == STATUS_UNPROVEN:
        review_status = PARTIAL_EVIDENCE
    else:
        review_status = REVIEW_REQUIRED

    packet = {
        "schemaVersion": SCHEMA_VERSION_V2,
        "recordStableKey": key,
        "sourceFingerprint": "0" * 64,
        "warehouseCoverage": {
            "status": coverage_status,
            "segmentCount": len(segments),
            "terminationReason": coverage_ledger.get("terminationReason"),
        },
        "catalogCoverageStatus": catalog_coverage_status,
        "reviewStatus": review_status,
        "segments": segments,
        "reviewUnits": [dict(u) for u in review_units],
        "summary": {
            "visibleReviewUnitCount": len(review_units),
            "candidateReadyCount": sum(1 for item in review_units if item.get("candidates")),
            "ambiguousCount": sum(
                1
                for item in review_units
                if item.get("placementStatus") in ("AMBIGUOUS_REGION", "UNKNOWN")
                or item.get("candidateStatus") == "AMBIGUOUS"
            ),
            "reviewedIdentityCount": 0,
        },
    }
    packet["sourceFingerprint"] = source_fingerprint_for(packet)
    ok, reasons = validate_warehouse_review_packet(packet)
    if not ok:
        raise WarehouseReviewPacketError("INVALID_PACKET", ",".join(reasons))
    return packet


def _index_descriptors(descriptors: Sequence[Mapping[str, Any]], key: str) -> Dict[str, Mapping[str, Any]]:
    by_id: Dict[str, Mapping[str, Any]] = {}
    for item in descriptors:
        if not isinstance(item, Mapping):
            raise WarehouseReviewPacketError("INVALID_DESCRIPTOR")
        evidence_id = str(item.get("evidenceId") or "").strip()
        digest = str(item.get("sha256") or "")
        if not evidence_id or not SHA256_RE.fullmatch(digest):
            raise WarehouseReviewPacketError("INVALID_DESCRIPTOR")
        if str(item.get("recordStableKey") or "") != key:
            raise WarehouseReviewPacketError("RECORD_KEY_MISMATCH")
        if item.get("kind") != KIND_WAREHOUSE_SEGMENT:
            raise WarehouseReviewPacketError("INVALID_KIND")
        existing = by_id.get(evidence_id)
        if existing is not None and existing.get("sha256") != digest:
            raise WarehouseReviewPacketError("HASH_CONFLICT")
        by_id[evidence_id] = item
    return by_id


def _packet_segments(
    coverage_ledger: Mapping[str, Any],
    descriptors: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    raw = [item for item in (coverage_ledger.get("segments") or []) if isinstance(item, Mapping)]
    seen: set[str] = set()
    segments: List[Dict[str, Any]] = []
    for item in raw:
        evidence_id = str(item.get("evidenceId") or "").strip()
        if not evidence_id:
            raise WarehouseReviewPacketError("ORPHAN_EVIDENCE")
        if evidence_id in seen:
            raise WarehouseReviewPacketError("DUPLICATE_EVIDENCE_ID")
        seen.add(evidence_id)
        descriptor = descriptors.get(evidence_id)
        if descriptor is None:
            raise WarehouseReviewPacketError("ORPHAN_EVIDENCE")
        digest = str(item.get("sha256") or descriptor.get("sha256") or "")
        if digest != descriptor.get("sha256"):
            raise WarehouseReviewPacketError("HASH_MISMATCH")
        sequence = item.get("sequenceIndex")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise WarehouseReviewPacketError("INVALID_SEQUENCE")
        width = descriptor.get("width")
        height = descriptor.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
            raise WarehouseReviewPacketError("INVALID_DESCRIPTOR")
        coverage_status = str(item.get("coverageStatus") or descriptor.get("coverageStatus") or "COVERAGE_UNPROVEN")
        if coverage_status not in {"PARTIAL", "COVERAGE_UNPROVEN"}:
            coverage_status = "COVERAGE_UNPROVEN"
        segments.append({
            "evidenceId": evidence_id,
            "kind": KIND_WAREHOUSE_SEGMENT,
            "sequenceIndex": sequence,
            "sha256": digest,
            "width": int(width),
            "height": int(height),
            "coverageStatus": coverage_status,
            "topEndpointTrusted": bool(item.get("topEndpointTrusted")),
            "bottomEndpointTrusted": bool(item.get("bottomEndpointTrusted")),
        })
    segments.sort(key=lambda item: (item["sequenceIndex"], item["evidenceId"]))
    return segments


def _packet_tracks(
    physical_ledger: Mapping[str, Any],
    evidence_by_segment_id: Mapping[str, str],
    descriptors: Mapping[str, Mapping[str, Any]],
    physical_segments: Mapping[str, Mapping[str, Any]],
    catalog_index: CatalogGeometryIndex,
) -> List[Dict[str, Any]]:
    raw_tracks = [item for item in (physical_ledger.get("tracks") or []) if isinstance(item, Mapping)]
    seen_tracks: set[str] = set()
    seen_obs: set[str] = set()
    tracks: List[Dict[str, Any]] = []
    for raw in raw_tracks:
        track_id = str(raw.get("trackId") or "").strip()
        if not track_id:
            raise WarehouseReviewPacketError("INVALID_TRACK_ID")
        if track_id in seen_tracks:
            raise WarehouseReviewPacketError("DUPLICATE_TRACK_ID")
        seen_tracks.add(track_id)
        observations = _packet_observations(
            raw,
            evidence_by_segment_id,
            descriptors,
            physical_segments,
            seen_obs,
        )
        if not observations:
            raise WarehouseReviewPacketError("TRACK_WITHOUT_OBSERVATION")
        resolved = resolve_catalog_candidates(raw, index=catalog_index)
        pixel_only = "PIXEL_ONLY" in {str(item) for item in (raw.get("reasons") or [])}
        geometry_status = str(resolved.get("geometryEvidenceStatus") or "UNKNOWN")
        if pixel_only:
            geometry_status = "PIXEL_ONLY"
        clipped = bool(raw.get("clipped"))
        if clipped and geometry_status == "EXACT":
            geometry_status = "COMPATIBLE_ONLY"
        candidates = []
        for candidate in resolved.get("candidates") or []:
            if not isinstance(candidate, Mapping):
                continue
            copied = {
                "catalogId": candidate.get("catalogId"),
                "name": candidate.get("name") or "",
                "identityStatus": "CANDIDATE_ONLY",
                "geometry": dict(candidate.get("geometry") or {}),
                "matchReasons": list(candidate.get("matchReasons") or []),
            }
            candidates.append(copied)
        candidates.sort(key=lambda item: str(item["catalogId"]))
        best_id = _select_best_observation(observations, pixel_only)
        identity = NOT_REVIEWABLE if raw.get("status") == "CONFLICT" else REVIEW_REQUIRED
        tracks.append({
            "trackId": track_id,
            "status": str(raw.get("status") or "AMBIGUOUS"),
            "clipped": clipped,
            "geometryEvidenceStatus": geometry_status,
            "pixelOnly": bool(pixel_only),
            "identityStatus": identity,
            "selectedCatalogId": None,
            "bestObservationId": best_id,
            "observations": observations,
            "candidateStatus": str(resolved.get("status") or "UNKNOWN"),
            "candidates": candidates,
            "widthCandidates": list(raw.get("widthCandidates") or []),
            "heightCandidates": list(raw.get("heightCandidates") or []),
            "spanCandidates": list(raw.get("spanCandidates") or []),
        })
    tracks.sort(key=lambda item: item["trackId"])
    return tracks


def _packet_observations(
    track: Mapping[str, Any],
    evidence_by_segment_id: Mapping[str, str],
    descriptors: Mapping[str, Mapping[str, Any]],
    physical_segments: Mapping[str, Mapping[str, Any]],
    seen_obs: set[str],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for raw in track.get("observations") or []:
        if not isinstance(raw, Mapping):
            continue
        observation_id = str(raw.get("observationId") or "").strip()
        if not observation_id:
            raise WarehouseReviewPacketError("INVALID_OBSERVATION_ID")
        if observation_id in seen_obs:
            raise WarehouseReviewPacketError("DUPLICATE_OBSERVATION_ID")
        seen_obs.add(observation_id)
        segment_id = str(raw.get("segmentId") or "")
        evidence_id = evidence_by_segment_id.get(segment_id)
        if not evidence_id:
            raise WarehouseReviewPacketError("ORPHAN_EVIDENCE")
        if evidence_id not in descriptors:
            raise WarehouseReviewPacketError("ORPHAN_EVIDENCE")
        segment = physical_segments.get(segment_id) or {}
        sequence = raw.get("sequenceIndex")
        if sequence is None:
            sequence = segment.get("sequenceIndex")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise WarehouseReviewPacketError("INVALID_SEQUENCE")
        bbox = _observation_bbox(raw, segment)
        items.append({
            "observationId": observation_id,
            "evidenceId": evidence_id,
            "sequenceIndex": sequence,
            "bbox": bbox,
            "status": str(raw.get("status") or "AMBIGUOUS"),
        })
    items.sort(key=lambda item: (item["sequenceIndex"], item["observationId"]))
    return items


def _observation_bbox(raw: Mapping[str, Any], segment: Mapping[str, Any]) -> List[float]:
    if isinstance(raw.get("bbox"), list) and len(raw["bbox"]) == 4:
        return [float(value) for value in raw["bbox"]]
    if isinstance(raw.get("localBox"), list) and len(raw["localBox"]) == 4:
        return [float(value) for value in raw["localBox"]]
    box = raw.get("globalBox")
    if not isinstance(box, list) or len(box) != 4:
        raise WarehouseReviewPacketError("INVALID_BBOX")
    origin_y = float(segment.get("originY") or 0.0)
    return [float(box[0]), float(box[1]) - origin_y, float(box[2]), float(box[3]) - origin_y]


def _select_best_observation(observations: Sequence[Mapping[str, Any]], pixel_only: bool) -> str:
    def rank(item: Mapping[str, Any]) -> Tuple[int, int, int, float, int, str]:
        clipped = 0 if str(item.get("status")) == "OBSERVED" else 1
        # Unclipped complete views already marked OBSERVED in 4C1/4C2.
        exact = 0 if (not pixel_only and item.get("status") == "OBSERVED") else 1
        pixel = 1 if pixel_only else 0
        bbox = item["bbox"]
        area = max(0.0, (float(bbox[2]) - float(bbox[0])) * (float(bbox[3]) - float(bbox[1])))
        return (clipped, exact, pixel, -area, int(item["sequenceIndex"]), str(item["observationId"]))

    return min(observations, key=rank)["observationId"]


def _review_status(coverage_status: str, tracks: Sequence[Mapping[str, Any]]) -> str:
    if not tracks:
        return NOT_REVIEWABLE
    if coverage_status == STATUS_COMPLETE:
        return REVIEW_REQUIRED
    if coverage_status in {STATUS_PARTIAL, STATUS_UNPROVEN}:
        return PARTIAL_EVIDENCE
    return NOT_REVIEWABLE
