"""Extract visible warehouse item proposals from Evidence Store v2 settlement evidence.

Deterministic geometry and segmentation only (4D2D1M-C3.2).
Never assigns catalog identity, never writes knownItems, never claims COMPLETE coverage.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from settlement_grid import settlement_grid_bounds

from settlement_evidence_store_v2 import (
    COVERAGE_UNPROVEN,
    KIND_MAIN,
    KIND_WAREHOUSE_SEGMENT,
    SettlementEvidenceStoreError,
    SettlementEvidenceStoreV2,
)
from settlement_item_recognizer import SettlementItemRecognizer

PROPOSAL_SCHEMA_VERSION = "settlement-warehouse-proposal.v1"


def extract_settlement_warehouse_proposals(
    *,
    store: SettlementEvidenceStoreV2,
    parent_descriptor: Dict[str, Any],
    recognizer: Optional[SettlementItemRecognizer] = None,
    save_crops: bool = True,
) -> List[Dict[str, Any]]:
    """
    Extract visible warehouse item proposals from a confirmed main-settlement original.

    Guarantees:
    - Input is loaded directly from file-backed Evidence Store v2.
    - Deterministic output ordering (top->bottom, left->right).
    - Every proposal has bbox, normalized bbox, cropSha256, and parent linkage.
    - Absolutely NO catalog identity or knownItems assignment.
    - Coverage status remains strictly COVERAGE_UNPROVEN / PARTIAL.
    """
    if not isinstance(parent_descriptor, dict):
        raise SettlementEvidenceStoreError("INVALID_DESCRIPTOR", "parent descriptor must be a dict")

    parent_evidence_id = str(parent_descriptor.get("evidenceId") or "").strip()
    parent_sha256 = str(parent_descriptor.get("sha256") or "").strip()
    record_key = str(parent_descriptor.get("recordStableKey") or "").strip()

    if not parent_evidence_id or not parent_sha256 or not record_key:
        raise SettlementEvidenceStoreError("INVALID_DESCRIPTOR", "parent descriptor missing mandatory fields")

    if parent_descriptor.get("kind") != KIND_MAIN:
        raise SettlementEvidenceStoreError("INVALID_KIND", f"expected {KIND_MAIN}, got {parent_descriptor.get('kind')}")

    # 1. Load full resolution original image from file-backed store
    image_bytes = store.load_original(parent_descriptor)
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise SettlementEvidenceStoreError("INVALID_IMAGE", "failed to decode parent evidence image")

    h, w = image.shape[:2]

    # 2. Warehouse ROI
    gx1, gy1, gx2, gy2 = settlement_grid_bounds(image)
    warehouse_crop = image[gy1:gy2, gx1:gx2]

    if warehouse_crop.size == 0:
        return []

    ch, cw = warehouse_crop.shape[:2]
    cell_w = cw / 10.0
    cell_h = ch / 10.0

    if recognizer is None:
        recognizer = SettlementItemRecognizer()

    components = recognizer._segment_occupied_components(warehouse_crop, cell_w, cell_h)

    # Sort deterministically by (row, col, widthCells, heightCells)
    components.sort(
        key=lambda c: (c.get("row", 0), c.get("col", 0), c.get("widthCells", 0), c.get("heightCells", 0))
    )

    proposals: List[Dict[str, Any]] = []

    for idx, c in enumerate(components):
        bx1 = int(gx1 + c["col"] * cell_w)
        by1 = int(gy1 + c["row"] * cell_h)
        bx2 = int(gx1 + (c["col"] + c["widthCells"]) * cell_w)
        by2 = int(gy1 + (c["row"] + c["heightCells"]) * cell_h)

        # Clamp to image bounds
        bx1 = max(0, min(w, bx1))
        by1 = max(0, min(h, by1))
        bx2 = max(bx1 + 1, min(w, bx2))
        by2 = max(by1 + 1, min(h, by2))

        item_crop = image[by1:by2, bx1:bx2]
        ok, png_buf = cv2.imencode(".png", item_crop)
        if not ok or png_buf is None:
            continue
        crop_bytes = png_buf.tobytes()
        crop_sha256 = hashlib.sha256(crop_bytes).hexdigest()

        proposal_id = f"prop_{parent_evidence_id[:8]}_{idx:03d}"

        crop_rel_path = None
        crop_evidence_id = None

        if save_crops:
            # Save crop as derivative warehouse-segment blob in EvidenceStore
            crop_desc = store.save_original(
                record_stable_key=record_key,
                kind=KIND_WAREHOUSE_SEGMENT,
                image_bytes=crop_bytes,
                captured_at=parent_descriptor.get("capturedAt"),
                coverage_mode="viewport-segment",
                coverage_status=COVERAGE_UNPROVEN,
            )
            crop_rel_path = crop_desc.get("relativePath")
            crop_evidence_id = crop_desc.get("evidenceId")
        else:
            crop_rel_path = f"evidence/settlement_v2/blobs/{crop_sha256[:2]}/{crop_sha256}.png"

        proposal_record = {
            "schemaVersion": PROPOSAL_SCHEMA_VERSION,
            "proposalId": proposal_id,
            "sequenceIndex": idx,
            "parentEvidenceId": parent_evidence_id,
            "parentSha256": parent_sha256,
            "recordStableKey": record_key,
            "bbox": [bx1, by1, bx2, by2],
            "normalizedBbox": [round(bx1 / w, 6), round(by1 / h, 6), round(bx2 / w, 6), round(by2 / h, 6)],
            "width": bx2 - bx1,
            "height": by2 - by1,
            "gridCells": c.get("cells", []),
            "gridShape": c.get("shape", f"{c.get('widthCells')}x{c.get('heightCells')}"),
            "widthCells": c.get("widthCells", 1),
            "heightCells": c.get("heightCells", 1),
            "occupiedCount": c.get("occupiedCount", len(c.get("cells", []))),
            "rarityObservation": c.get("rarity") or "unknown",
            "qualityObservation": c.get("rarity") or "unknown",
            "cropRelativePath": crop_rel_path,
            "cropSha256": crop_sha256,
            "cropByteSize": len(crop_bytes),
            "cropEvidenceId": crop_evidence_id,
            "warehouseCoverage": "PARTIAL",
            "coverageStatus": COVERAGE_UNPROVEN,
        }
        proposals.append(proposal_record)

    return proposals
