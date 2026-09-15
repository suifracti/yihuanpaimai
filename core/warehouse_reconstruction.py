"""Post-capture reconstruction: grid → physical tracks → candidates → review packet.

Does not drive scrolling, windows, or the capture state machine. Only consumes
Store-backed segments and the overlap proofs the session already accepted.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from warehouse_catalog_geometry import CatalogGeometryIndex
from warehouse_grid_geometry import STATUS_OK as GRID_OK, observe_warehouse_grid
from warehouse_physical_ledger import PhysicalComponentLedger
from warehouse_placement_resolver import WarehousePlacementResolver
from warehouse_scrollbar_observation import warehouse_search_roi
from warehouse_review_packet import (
    NOT_REVIEWABLE,
    WarehouseReviewPacketError,
    build_warehouse_review_packet,
    build_warehouse_review_packet_v2,
    canonical_warehouse_review_packet,
)

PACKET_UNAVAILABLE = "UNAVAILABLE"
PACKET_READY = "READY"
PACKET_FAILED = "FAILED"

SNAPSHOT_KEYS = (
    "packetAvailable",
    "packetStatus",
    "packetFingerprint",
    "reviewStatus",
    "warnings",
    "processedCount",
)


class WarehouseReconstructionProcessor:
    def __init__(
        self,
        record_stable_key: str,
        *,
        catalog_index: Optional[CatalogGeometryIndex] = None,
        observe_grid: Optional[Callable[..., Mapping[str, Any]]] = None,
        physical_factory: Optional[Callable[[str], PhysicalComponentLedger]] = None,
        packet_builder: Optional[Callable[..., Mapping[str, Any]]] = None,
        placement_resolver: Optional[WarehousePlacementResolver] = None,
    ):
        self._key = str(record_stable_key or "").strip()
        self._catalog = catalog_index
        self._observe_grid = observe_grid or observe_warehouse_grid
        self._physical_factory = physical_factory or PhysicalComponentLedger
        self._packet_builder = packet_builder or build_warehouse_review_packet
        self._placement_resolver = placement_resolver
        self._seen: set[tuple[str, str]] = set()
        self._descriptors: List[Dict[str, Any]] = []
        self._frames: Dict[str, Any] = {}
        self._source_origins: Dict[str, tuple[int, int]] = {}
        self._warnings: List[str] = []
        self._physical: Optional[PhysicalComponentLedger] = None
        self._coverage: Optional[Dict[str, Any]] = None
        self._packet: Optional[Dict[str, Any]] = None
        self._packet_status = PACKET_UNAVAILABLE

    def accept_segment(
        self,
        frame: Any,
        descriptor: Mapping[str, Any],
        sequence_index: int,
        observer_result: Optional[Mapping[str, Any]] = None,
        overlap_proof: Optional[Mapping[str, Any]] = None,
        *,
        already_cropped: bool = True,
    ) -> Dict[str, Any]:
        evidence_id = str(descriptor.get("evidenceId") or "").strip()
        digest = str(descriptor.get("sha256") or "").strip()
        if not evidence_id or not digest:
            return {"accepted": False, "reason": "INVALID_DESCRIPTOR"}
        if str(descriptor.get("recordStableKey") or self._key) != self._key:
            self._warnings.append("STABLE_KEY_MISMATCH")
            return {"accepted": False, "reason": "STABLE_KEY_MISMATCH"}
        origin = (0, 0)
        if self._placement_resolver is not None and frame is not None:
            height, width = frame.shape[:2]
            if descriptor.get("width") != width or descriptor.get("height") != height:
                self._warnings.append("SOURCE_FRAME_SIZE_MISMATCH")
                return {"accepted": False, "reason": "SOURCE_FRAME_SIZE_MISMATCH"}
            if not already_cropped:
                x1, y1, x2, y2 = warehouse_search_roi(width, height)
                frame = frame[y1:y2, x1:x2].copy()
                origin = (x1, y1)
                already_cropped = True
        token = (evidence_id, digest)
        if token in self._seen:
            return {"accepted": False, "reason": "DUPLICATE"}
        self._seen.add(token)
        self._descriptors.append(dict(descriptor))
        self._source_origins[evidence_id] = origin
        if frame is not None:
            self._frames[evidence_id] = frame

        try:
            observation = self._observe_grid(
                frame,
                already_cropped=already_cropped,
                source_id=evidence_id,
            )
        except Exception:
            self._warnings.append("GRID_FAILED")
            return {"accepted": True, "reason": "GRID_FAILED"}

        grid = observation.get("grid") if isinstance(observation, Mapping) else None
        if not isinstance(grid, Mapping) or grid.get("status") != GRID_OK:
            self._warnings.append("GRID_UNKNOWN")
            return {"accepted": True, "reason": "GRID_UNKNOWN"}

        if self._physical is None:
            self._physical = self._physical_factory(self._key)
        observer = observer_result or {}
        try:
            self._physical.add_segment(
                observation,
                sequence_index=int(sequence_index),
                segment_id=evidence_id,
                overlap=overlap_proof,
                scroll_state=str(observer.get("scrollState") or ""),
                frame=frame,
                record_stable_key=self._key,
            )
        except Exception:
            self._warnings.append("PHYSICAL_LEDGER_FAILED")
            return {"accepted": True, "reason": "PHYSICAL_LEDGER_FAILED"}
        return {"accepted": True, "reason": "OK"}

    def finalize(self, coverage_result: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        self._coverage = dict(coverage_result) if isinstance(coverage_result, Mapping) else None
        try:
            packet = self.build_review_packet()
        except Exception:
            self._packet = None
            self._packet_status = PACKET_FAILED
            self._warnings.append("PACKET_FAILED")
            return self.readonly_snapshot()
        self._packet = packet
        if packet is None or packet.get("reviewStatus") == NOT_REVIEWABLE:
            self._packet_status = PACKET_UNAVAILABLE
        else:
            self._packet_status = PACKET_READY
        return self.readonly_snapshot()

    def build_review_packet(self) -> Optional[Dict[str, Any]]:
        if self._coverage is None or not self._descriptors:
            return None
        physical = (
            self._physical.snapshot()
            if self._physical is not None
            else {
                "schemaVersion": "warehouse-physical-ledger.v1",
                "recordStableKey": self._key,
                "chainStatus": "UNANCHORED",
                "segments": [],
                "tracks": [],
                "conflicts": [],
            }
        )
        if str(physical.get("recordStableKey") or self._key) != self._key:
            raise WarehouseReviewPacketError("RECORD_KEY_MISMATCH")

        if self._placement_resolver is not None:
            review_units = self._placement_resolver.resolve(
                physical_ledger=physical,
                descriptors=self._descriptors,
                frames=self._frames,
            )
            # Resolver geometry is local to the warehouse image. Public evidence
            # boxes always address the immutable source blob named by the SHA.
            review_units = copy.deepcopy(review_units)
            for unit in review_units:
                for observation in unit.get("observations") or []:
                    x, y = self._source_origins[str(observation["evidenceId"])]
                    bbox = observation["bbox"]
                    observation["bbox"] = [bbox[0] + x, bbox[1] + y, bbox[2] + x, bbox[3] + y]
            catalog_status = self._catalog.catalog_coverage_status if self._catalog else "COVERAGE_UNVERIFIED"
            return dict(
                build_warehouse_review_packet_v2(
                    coverage_ledger=self._coverage,
                    review_units=review_units,
                    descriptors=self._descriptors,
                    catalog_coverage_status=catalog_status or "COVERAGE_UNVERIFIED",
                )
            )

        mapping = {str(item["evidenceId"]): str(item["evidenceId"]) for item in self._descriptors}
        return dict(
            self._packet_builder(
                coverage_ledger=self._coverage,
                physical_ledger=physical,
                descriptors=self._descriptors,
                catalog_index=self._catalog,
                segment_evidence_map=mapping,
            )
        )

    def readonly_snapshot(self) -> Dict[str, Any]:
        payload = {
            "packetAvailable": self._packet_status == PACKET_READY,
            "packetStatus": self._packet_status,
            "packetFingerprint": (self._packet or {}).get("sourceFingerprint"),
            "reviewStatus": (self._packet or {}).get("reviewStatus"),
            "warnings": list(self._warnings),
            "processedCount": len(self._seen),
        }
        extra = set(payload) - set(SNAPSHOT_KEYS)
        for key in extra:
            payload.pop(key, None)
        return payload

    def packet_copy(self) -> Optional[Dict[str, Any]]:
        if self._packet is None:
            return None
        return json.loads(canonical_warehouse_review_packet(self._packet))
