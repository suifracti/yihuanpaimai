"""Targeted contract and compatibility tests for review-unit schema v2 (4D2D1Q-UAT13).

Covers:
- V1 packet and review backward compatibility.
- V2 review packet contract with 绝对是亲手钓的鱼 (image10-0-0) and 万有星仪 (image27-0-2).
- Clear boundaries between reviewUnitId, physicalGroupId, and supportingTrackIds.
- UNKNOWN / AMBIGUOUS_REGION schema validity without premature physicalGroupId.
- V2 identity review decision resolution and multi-frame evidence provenance.
- Exporter fail-closed behavior on V2 artifacts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(CORE_DIR),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_history_store import CanonicalHistoryStore
from settlement_evidence_store_v2 import KIND_WAREHOUSE_SEGMENT, SettlementEvidenceStoreV2
from warehouse_identity_review import (
    ACTION_CONFIRM,
    ACTION_DEFER,
    CatalogAuthority,
    DECISION_SCHEMA,
    DECISION_SCHEMA_V2,
    REVIEW_SCHEMA,
    REVIEW_SCHEMA_V2,
    artifact_fingerprint_for,
    resolve_warehouse_identity_review,
    validate_identity_review_decision,
    validate_warehouse_identity_review,
)
from warehouse_identity_review_persist import persist_warehouse_identity_review
from warehouse_identity_review_session import WarehouseIdentityReviewSession
from warehouse_review_packet import (
    SCHEMA_VERSION as PACKET_SCHEMA_V1,
    SCHEMA_VERSION_V2 as PACKET_SCHEMA_V2,
    source_fingerprint_for,
    validate_warehouse_review_packet,
)
from warehouse_reviewed_label_export import export_reviewed_label_dataset


def _png(color=(30, 80, 160), size=(640, 720)) -> bytes:
    image = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    image[:] = color
    return cv2.imencode(".png", image)[1].tobytes()


class TestWarehouseReviewUnitV2(unittest.TestCase):
    def setUp(self):
        catalog_path = PROJECT_ROOT / "assets" / "catalog_065.json"
        self.catalog_data = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.is_file() else []
        self.authority = CatalogAuthority(self.catalog_data)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp_dir.name)
        self.store = SettlementEvidenceStoreV2(self.runtime_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _save_segment(self, key: str, color=(30, 80, 160)) -> dict:
        return self.store.save_original(
            record_stable_key=key,
            kind=KIND_WAREHOUSE_SEGMENT,
            image_bytes=_png(color),
        )

    def _sample_v1_packet(self) -> dict:
        desc = self._save_segment("rec_v1_001", (100, 100, 100))
        packet = {
            "schemaVersion": PACKET_SCHEMA_V1,
            "recordStableKey": "rec_v1_001",
            "sourceFingerprint": "0" * 64,
            "warehouseCoverage": {
                "status": "COMPLETE",
                "segmentCount": 1,
                "terminationReason": None,
            },
            "catalogCoverageStatus": "VERIFIED_COMPLETE",
            "reviewStatus": "REVIEW_REQUIRED",
            "segments": [
                {
                    "evidenceId": desc["evidenceId"],
                    "kind": "warehouse-segment",
                    "sequenceIndex": 0,
                    "sha256": desc["sha256"],
                    "width": 640,
                    "height": 720,
                    "coverageStatus": "PARTIAL",
                    "topEndpointTrusted": True,
                    "bottomEndpointTrusted": True,
                }
            ],
            "tracks": [
                {
                    "trackId": "raw-track-101",
                    "status": "OK",
                    "clipped": False,
                    "geometryEvidenceStatus": "EXACT",
                    "pixelOnly": False,
                    "identityStatus": "REVIEW_REQUIRED",
                    "selectedCatalogId": None,
                    "bestObservationId": "obs-101-0",
                    "observations": [
                        {
                            "observationId": "obs-101-0",
                            "evidenceId": desc["evidenceId"],
                            "sequenceIndex": 0,
                            "bbox": [10.0, 20.0, 100.0, 120.0],
                            "status": "OK",
                        }
                    ],
                    "candidateStatus": "UNIQUE_IN_CATALOG",
                    "candidates": [
                        {
                            "catalogId": "image10-0-0",
                            "name": "绝对是亲手钓的鱼",
                            "identityStatus": "CANDIDATE_ONLY",
                            "geometry": {
                                "width": 5,
                                "height": 5,
                                "cells": 25,
                                "shape": "5x5",
                            },
                            "matchReasons": ["GEOMETRY_MATCH"],
                        }
                    ],
                    "widthCandidates": [5],
                    "heightCandidates": [5],
                    "spanCandidates": [25],
                }
            ],
            "summary": {
                "visibleTrackCount": 1,
                "candidateReadyCount": 1,
                "ambiguousCount": 0,
                "reviewedIdentityCount": 0,
            },
        }
        packet["sourceFingerprint"] = source_fingerprint_for(packet)
        return packet

    def _sample_v2_packet(self) -> dict:
        desc_prev = self._save_segment("rec_v2_002", (20, 90, 180))
        desc_next = self._save_segment("rec_v2_002", (20, 140, 80))
        packet = {
            "schemaVersion": PACKET_SCHEMA_V2,
            "recordStableKey": "rec_v2_002",
            "sourceFingerprint": "0" * 64,
            "warehouseCoverage": {
                "status": "COMPLETE",
                "segmentCount": 2,
                "terminationReason": None,
            },
            "catalogCoverageStatus": "VERIFIED_COMPLETE",
            "reviewStatus": "REVIEW_REQUIRED",
            "segments": [
                {
                    "evidenceId": desc_prev["evidenceId"],
                    "kind": "warehouse-segment",
                    "sequenceIndex": 0,
                    "sha256": desc_prev["sha256"],
                    "width": 640,
                    "height": 720,
                    "coverageStatus": "PARTIAL",
                    "topEndpointTrusted": True,
                    "bottomEndpointTrusted": True,
                },
                {
                    "evidenceId": desc_next["evidenceId"],
                    "kind": "warehouse-segment",
                    "sequenceIndex": 1,
                    "sha256": desc_next["sha256"],
                    "width": 640,
                    "height": 720,
                    "coverageStatus": "PARTIAL",
                    "topEndpointTrusted": True,
                    "bottomEndpointTrusted": True,
                },
            ],
            "reviewUnits": [
                {
                    "reviewUnitId": "unit-world-5-0-5x5",
                    "placementStatus": "RESOLVED",
                    "visibility": "FULL",
                    "worldAnchor": {"row": 5, "col": 0},
                    "footprint": {"widthCells": 5, "heightCells": 5},
                    "physicalGroupId": "group-world-5-0",
                    "geometryEvidenceStatus": "EXACT",
                    "identityStatus": "REVIEW_REQUIRED",
                    "selectedCatalogId": None,
                    "bestObservationId": "obs-fish-prev",
                    "supportingTrackIds": [
                        "raw-track-fish-head",
                        "raw-track-fish-body",
                        "raw-track-fish-tail",
                    ],
                    "observations": [
                        {
                            "observationId": "obs-fish-prev",
                            "evidenceId": desc_prev["evidenceId"],
                            "sequenceIndex": 0,
                            "bbox": [50.0, 0.0, 250.0, 200.0],
                            "status": "FULL",
                        }
                    ],
                    "candidateStatus": "UNIQUE_IN_CATALOG",
                    "candidates": [
                        {
                            "catalogId": "image10-0-0",
                            "name": "绝对是亲手钓的鱼",
                            "identityStatus": "CANDIDATE_ONLY",
                            "geometry": {
                                "width": 5,
                                "height": 5,
                                "cells": 25,
                                "shape": "5x5",
                            },
                            "matchReasons": ["WHOLE_CARD_MATCH", "SIFT_INLIERS_20"],
                        }
                    ],
                    "widthCandidates": [5],
                    "heightCandidates": [5],
                    "spanCandidates": [25],
                },
                {
                    "reviewUnitId": "unit-world-0-0-5x5",
                    "placementStatus": "RESOLVED",
                    "visibility": "FULL",
                    "worldAnchor": {"row": 0, "col": 0},
                    "footprint": {"widthCells": 5, "heightCells": 5},
                    "physicalGroupId": "group-world-0-0",
                    "geometryEvidenceStatus": "EXACT",
                    "identityStatus": "REVIEW_REQUIRED",
                    "selectedCatalogId": None,
                    "bestObservationId": "obs-inst-prev",
                    "supportingTrackIds": [
                        "raw-track-inst-prev",
                        "raw-track-inst-next",
                    ],
                    "observations": [
                        {
                            "observationId": "obs-inst-prev",
                            "evidenceId": desc_prev["evidenceId"],
                            "sequenceIndex": 0,
                            "bbox": [0.0, 0.0, 200.0, 200.0],
                            "status": "FULL",
                        },
                        {
                            "observationId": "obs-inst-next",
                            "evidenceId": desc_next["evidenceId"],
                            "sequenceIndex": 1,
                            "bbox": [0.0, 0.0, 100.0, 200.0],
                            "status": "CLIPPED",
                        },
                    ],
                    "candidateStatus": "UNIQUE_IN_CATALOG",
                    "candidates": [
                        {
                            "catalogId": "image27-0-2",
                            "name": "万有星仪",
                            "identityStatus": "CANDIDATE_ONLY",
                            "geometry": {
                                "width": 5,
                                "height": 5,
                                "cells": 25,
                                "shape": "5x5",
                            },
                            "matchReasons": ["WHOLE_CARD_MATCH", "SIFT_INLIERS_58"],
                        }
                    ],
                    "widthCandidates": [5],
                    "heightCandidates": [5],
                    "spanCandidates": [25],
                },
            ],
            "summary": {
                "visibleReviewUnitCount": 2,
                "candidateReadyCount": 2,
                "ambiguousCount": 0,
                "reviewedIdentityCount": 0,
            },
        }
        packet["sourceFingerprint"] = source_fingerprint_for(packet)
        return packet

    def test_v1_packet_and_review_backward_compatibility(self):
        """V1 packet and review flow must remain 100% valid and readable."""
        v1_packet = self._sample_v1_packet()
        ok, reasons = validate_warehouse_review_packet(v1_packet)
        self.assertTrue(ok, f"V1 packet should validate cleanly: {reasons}")

        decision_doc = {
            "schemaVersion": DECISION_SCHEMA,
            "recordStableKey": "rec_v1_001",
            "packetFingerprint": v1_packet["sourceFingerprint"],
            "reviewedAt": "2026-08-31T12:00:00Z",
            "reviewerType": "HUMAN",
            "decisions": [
                {
                    "decisionId": "dec-01",
                    "trackId": "raw-track-101",
                    "action": ACTION_CONFIRM,
                    "selectedCatalogId": "image10-0-0",
                }
            ],
        }
        ok, reasons = validate_identity_review_decision(decision_doc)
        self.assertTrue(ok, f"V1 decision doc should validate: {reasons}")

        artifact = resolve_warehouse_identity_review(v1_packet, decision_doc, catalog=self.authority)
        self.assertEqual(artifact["schemaVersion"], REVIEW_SCHEMA)
        self.assertEqual(len(artifact["resolvedItems"]), 1)
        self.assertEqual(artifact["resolvedItems"][0]["trackId"], "raw-track-101")
        self.assertEqual(artifact["resolvedItems"][0]["name"], "绝对是亲手钓的鱼")
        self.assertEqual(artifact["resolvedItems"][0]["catalogId"], "image10-0-0")

        ok, reasons = validate_warehouse_identity_review(artifact)
        self.assertTrue(ok, f"V1 review artifact should validate: {reasons}")

    def test_v2_review_unit_contract_and_naming(self):
        """V2 review packet uses reviewUnitId and official naming authority."""
        v2_packet = self._sample_v2_packet()
        ok, reasons = validate_warehouse_review_packet(v2_packet)
        self.assertTrue(ok, f"V2 packet should validate cleanly: {reasons}")

        unit1 = v2_packet["reviewUnits"][0]
        unit2 = v2_packet["reviewUnits"][1]

        # Verify reviewUnitId vs supportingTrackIds
        self.assertEqual(unit1["reviewUnitId"], "unit-world-5-0-5x5")
        self.assertIn("raw-track-fish-head", unit1["supportingTrackIds"])
        self.assertNotEqual(unit1["reviewUnitId"], unit1["supportingTrackIds"][0])

        # Verify official catalog naming
        self.assertEqual(unit1["candidates"][0]["name"], "绝对是亲手钓的鱼")
        self.assertEqual(unit1["candidates"][0]["catalogId"], "image10-0-0")
        self.assertEqual(unit2["candidates"][0]["name"], "万有星仪")
        self.assertEqual(unit2["candidates"][0]["catalogId"], "image27-0-2")

        # Verify worldAnchor, footprint, visibility
        self.assertEqual(unit1["worldAnchor"], {"row": 5, "col": 0})
        self.assertEqual(unit1["footprint"], {"widthCells": 5, "heightCells": 5})
        self.assertEqual(unit1["visibility"], "FULL")

        # Verify multi-frame observations under single review unit
        self.assertEqual(len(unit2["observations"]), 2)
        obs_statuses = [obs["status"] for obs in unit2["observations"]]
        self.assertEqual(obs_statuses, ["FULL", "CLIPPED"])

    def test_v2_unknown_and_ambiguous_contract(self):
        """UNKNOWN / AMBIGUOUS_REGION can enter packet and must not require resolved physicalGroupId."""
        v2_packet = self._sample_v2_packet()
        v2_packet["reviewUnits"].append({
            "reviewUnitId": "unit-world-8-8-ambiguous",
            "placementStatus": "AMBIGUOUS_REGION",
            "visibility": "FULL",
            "worldAnchor": {"row": 8, "col": 8},
            "footprint": {"widthCells": 2, "heightCells": 2},
            "physicalGroupId": None,  # Ambiguous region has no resolved physicalGroupId yet
            "geometryEvidenceStatus": "COMPATIBLE_ONLY",
            "identityStatus": "REVIEW_REQUIRED",
            "selectedCatalogId": None,
            "bestObservationId": "obs-amb-1",
            "supportingTrackIds": ["raw-track-amb-1"],
            "observations": [
                {
                    "observationId": "obs-amb-1",
                    "evidenceId": v2_packet["segments"][0]["evidenceId"],
                    "sequenceIndex": 0,
                    "bbox": [400.0, 400.0, 500.0, 500.0],
                    "status": "FULL",
                }
            ],
            "candidateStatus": "AMBIGUOUS",
            "candidates": [
                {
                    "catalogId": "image11-0-2",
                    "name": "鳞纹",
                    "identityStatus": "CANDIDATE_ONLY",
                    "geometry": {"width": 2, "height": 2, "cells": 4, "shape": "2x2"},
                    "matchReasons": ["GEOMETRY_COMPATIBLE"],
                }
            ],
            "widthCandidates": [2],
            "heightCandidates": [2],
            "spanCandidates": [4],
        })
        v2_packet["summary"]["visibleReviewUnitCount"] = 3
        v2_packet["summary"]["ambiguousCount"] = 1
        v2_packet["sourceFingerprint"] = source_fingerprint_for(v2_packet)

        ok, reasons = validate_warehouse_review_packet(v2_packet)
        self.assertTrue(ok, f"AMBIGUOUS_REGION with physicalGroupId=None should be valid: {reasons}")

        # Fail-closed test on extra unknown fields
        v2_packet["reviewUnits"][0]["illegalExtraField"] = "bad"
        ok, reasons = validate_warehouse_review_packet(v2_packet)
        self.assertFalse(ok)
        self.assertIn("UNKNOWN_FIELD_illegalExtraField", reasons)

    def test_v2_identity_review_resolution_and_provenance(self):
        """V2 decisions link by reviewUnitId and preserve full supporting provenance."""
        v2_packet = self._sample_v2_packet()
        decision_doc = {
            "schemaVersion": DECISION_SCHEMA_V2,
            "recordStableKey": "rec_v2_002",
            "packetFingerprint": v2_packet["sourceFingerprint"],
            "reviewedAt": "2026-08-31T13:00:00Z",
            "reviewerType": "HUMAN",
            "decisions": [
                {
                    "decisionId": "dec-fish-01",
                    "reviewUnitId": "unit-world-5-0-5x5",
                    "action": ACTION_CONFIRM,
                    "selectedCatalogId": "image10-0-0",
                },
                {
                    "decisionId": "dec-inst-02",
                    "reviewUnitId": "unit-world-0-0-5x5",
                    "action": ACTION_CONFIRM,
                    "selectedCatalogId": "image27-0-2",
                },
            ],
        }
        ok, reasons = validate_identity_review_decision(decision_doc)
        self.assertTrue(ok, f"V2 decision doc should validate: {reasons}")

        artifact = resolve_warehouse_identity_review(v2_packet, decision_doc, catalog=self.authority)
        self.assertEqual(artifact["schemaVersion"], REVIEW_SCHEMA_V2)
        self.assertEqual(len(artifact["resolvedItems"]), 2)

        # Check Fish item
        fish_item = next(item for item in artifact["resolvedItems"] if item["reviewUnitId"] == "unit-world-5-0-5x5")
        self.assertEqual(fish_item["name"], "绝对是亲手钓的鱼")
        self.assertEqual(fish_item["catalogId"], "image10-0-0")
        self.assertEqual(fish_item["physicalGroupId"], "group-world-5-0")
        self.assertEqual(
            fish_item["supportingTrackIds"],
            ["raw-track-fish-head", "raw-track-fish-body", "raw-track-fish-tail"],
        )
        self.assertEqual(fish_item["worldAnchor"], {"row": 5, "col": 0})
        self.assertEqual(fish_item["footprint"], {"widthCells": 5, "heightCells": 5})

        # Check Instrument item
        inst_item = next(item for item in artifact["resolvedItems"] if item["reviewUnitId"] == "unit-world-0-0-5x5")
        self.assertEqual(inst_item["name"], "万有星仪")
        self.assertEqual(inst_item["catalogId"], "image27-0-2")
        self.assertEqual(inst_item["physicalGroupId"], "group-world-0-0")
        self.assertEqual(
            inst_item["supportingTrackIds"],
            ["raw-track-inst-prev", "raw-track-inst-next"],
        )

        ok, reasons = validate_warehouse_identity_review(artifact)
        self.assertTrue(ok, f"V2 review artifact should validate: {reasons}")

    def test_v2_session_and_presentation(self):
        """WarehouseIdentityReviewSession indexes by reviewUnitId on V2 packet."""
        v2_packet = self._sample_v2_packet()
        session = WarehouseIdentityReviewSession(store=self.store, catalog=self.authority)
        view = session.open(v2_packet)

        self.assertTrue(view["available"])
        self.assertEqual(view["trackCount"], 2)
        self.assertEqual(view["currentTrackId"], "unit-world-5-0-5x5")

        # Confirm fish candidate
        session.select_candidate("image10-0-0")
        session.apply({"action": ACTION_CONFIRM, "confirmCandidate": True})

        # Move next and confirm instrument
        session.step_track(1)
        session.select_candidate("image27-0-2")
        session.apply({"action": ACTION_CONFIRM, "confirmCandidate": True})

        final_view = session.finalize(reviewed_at="2026-08-31T14:00:00Z")
        self.assertEqual(final_view["reviewCompletion"], "COMPLETE")
        self.assertEqual(final_view["identityResolution"], "FULLY_RESOLVED")

        artifact = session.artifact_copy()
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact["schemaVersion"], REVIEW_SCHEMA_V2)
        self.assertEqual(len(artifact["resolvedItems"]), 2)

    def test_v2_observation_provenance_closure(self):
        """V2 Review Unit observations deterministically resolve to immutable SHA-256 for FULL and CLIPPED."""
        from runtime_data import HISTORY_FILENAME
        v2_packet = self._sample_v2_packet()
        key = v2_packet["recordStableKey"]
        
        # 1. Check Fish (FULL) observation
        fish_unit = next(u for u in v2_packet["reviewUnits"] if u["reviewUnitId"] == "unit-world-5-0-5x5")
        fish_obs = fish_unit["observations"][0]
        self.assertEqual(fish_obs["status"], "FULL")
        self.assertEqual(fish_unit["candidates"][0]["name"], "绝对是亲手钓的鱼")
        self.assertEqual(fish_unit["candidates"][0]["catalogId"], "image10-0-0")
        
        # Resolve evidenceId via packet segments
        seg_map = {s["evidenceId"]: s["sha256"] for s in v2_packet["segments"]}
        self.assertIn(fish_obs["evidenceId"], seg_map)
        fish_sha256 = seg_map[fish_obs["evidenceId"]]
        
        # Resolve evidenceId via immutable store and verify byte hash
        desc_list = self.store.list_record_evidence(key)
        fish_desc = next(d for d in desc_list if d["evidenceId"] == fish_obs["evidenceId"])
        self.assertEqual(fish_desc["sha256"], fish_sha256)
        raw_bytes = self.store.load_original(fish_desc)
        self.assertEqual(hashlib.sha256(raw_bytes).hexdigest(), fish_sha256)

        # 2. Check Instrument (FULL + CLIPPED) multi-frame observations
        inst_unit = next(u for u in v2_packet["reviewUnits"] if u["reviewUnitId"] == "unit-world-0-0-5x5")
        self.assertEqual(inst_unit["candidates"][0]["name"], "万有星仪")
        self.assertEqual(inst_unit["candidates"][0]["catalogId"], "image27-0-2")
        
        obs_full = next(o for o in inst_unit["observations"] if o["status"] == "FULL")
        obs_clipped = next(o for o in inst_unit["observations"] if o["status"] == "CLIPPED")
        
        full_desc = next(d for d in desc_list if d["evidenceId"] == obs_full["evidenceId"])
        clipped_desc = next(d for d in desc_list if d["evidenceId"] == obs_clipped["evidenceId"])
        
        self.assertEqual(seg_map[obs_full["evidenceId"]], full_desc["sha256"])
        self.assertEqual(seg_map[obs_clipped["evidenceId"]], clipped_desc["sha256"])
        self.assertNotEqual(full_desc["sha256"], clipped_desc["sha256"])
        
        # Verify supportingTrackIds raw provenance
        self.assertEqual(inst_unit["supportingTrackIds"], ["raw-track-inst-prev", "raw-track-inst-next"])

        # 3. Reviewed artifact provenance verification via WarehouseIdentityReviewSession
        session = WarehouseIdentityReviewSession(store=self.store, catalog=self.authority)
        session.open(v2_packet)
        session.select_candidate("image10-0-0")
        session.apply({"action": ACTION_CONFIRM, "confirmCandidate": True})
        session.step_track(1)
        session.select_candidate("image27-0-2")
        session.apply({"action": ACTION_CONFIRM, "confirmCandidate": True})
        session.finalize(reviewed_at="2026-08-31T14:30:00Z")
        
        reviewed_art = session.artifact_copy()
        self.assertIsNotNone(reviewed_art)
        self.assertEqual(reviewed_art["schemaVersion"], REVIEW_SCHEMA_V2)
        
        ok, reasons = validate_warehouse_identity_review(reviewed_art)
        self.assertTrue(ok, f"V2 review artifact must validate cleanly: {reasons}")
        
        # Verify Fish resolved item
        fish_resolved = next(item for item in reviewed_art["resolvedItems"] if item["reviewUnitId"] == "unit-world-5-0-5x5")
        self.assertEqual(fish_resolved["name"], "绝对是亲手钓的鱼")
        self.assertEqual(fish_resolved["catalogId"], "image10-0-0")
        self.assertEqual(fish_resolved["evidenceId"], fish_obs["evidenceId"])
        self.assertEqual(fish_resolved["sha256"], fish_sha256)
        self.assertEqual(fish_resolved["supportingTrackIds"], ["raw-track-fish-head", "raw-track-fish-body", "raw-track-fish-tail"])
        self.assertEqual(fish_resolved["worldAnchor"], {"row": 5, "col": 0})
        self.assertEqual(fish_resolved["footprint"], {"widthCells": 5, "heightCells": 5})

        # Verify Instrument resolved item
        inst_resolved = next(item for item in reviewed_art["resolvedItems"] if item["reviewUnitId"] == "unit-world-0-0-5x5")
        self.assertEqual(inst_resolved["name"], "万有星仪")
        self.assertEqual(inst_resolved["catalogId"], "image27-0-2")
        self.assertEqual(inst_resolved["evidenceId"], obs_full["evidenceId"])
        self.assertEqual(inst_resolved["sha256"], full_desc["sha256"])
        self.assertEqual(inst_resolved["supportingTrackIds"], ["raw-track-inst-prev", "raw-track-inst-next"])
        self.assertEqual(inst_resolved["worldAnchor"], {"row": 0, "col": 0})
        self.assertEqual(inst_resolved["footprint"], {"widthCells": 5, "heightCells": 5})

    def test_v2_exporter_fail_closed(self):
        """Label exporter must fail-closed on V2 schema without pretending reviewUnitId is trackId."""
        from runtime_data import HISTORY_FILENAME
        history_dir = self.runtime_root / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        history_file = history_dir / HISTORY_FILENAME
        
        v2_packet = self._sample_v2_packet()
        decision_doc = {
            "schemaVersion": DECISION_SCHEMA_V2,
            "recordStableKey": "rec_v2_002",
            "packetFingerprint": v2_packet["sourceFingerprint"],
            "reviewedAt": "2026-08-31T13:00:00Z",
            "reviewerType": "HUMAN",
            "decisions": [
                {
                    "decisionId": "dec-fish-01",
                    "reviewUnitId": "unit-world-5-0-5x5",
                    "action": ACTION_CONFIRM,
                    "selectedCatalogId": "image10-0-0",
                },
            ],
        }
        artifact = resolve_warehouse_identity_review(v2_packet, decision_doc, catalog=self.authority)
        
        record = {
            "id": "rec_v2_002",
            "schemaVersion": 7,
            "source": "live_capture",
            "lifecycleStatus": "FINALIZED",
            "settlement": {
                "warehouseIdentityReview": artifact,
            },
        }
        history_file.write_text(json.dumps({"version": "v0.67-runtime", "schemaVersion": 7, "records": [record]}), encoding="utf-8")
        
        out_dir = self.runtime_root / "export_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = export_reviewed_label_dataset(runtime_root=self.runtime_root, output_dir=out_dir)
        
        self.assertEqual(len(manifest["samples"]), 0)
        self.assertTrue(any(r.get("reason") == "UNSUPPORTED_V2_SCHEMA" for r in manifest["rejected"]))

    def test_v2_human_reviewed_canonical_history_round_trip_and_proposal_gate(self):
        """V2 human-reviewed artifact is admitted to Canonical History with complete provenance round-trip, while proposals remain non-truth."""
        from canonical_match_record import build_canonical_match_record_v7, validate_canonical_match_record_v7
        from runtime_data import HISTORY_FILENAME

        history_dir = self.runtime_root / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        history_path = history_dir / HISTORY_FILENAME
        history_store = CanonicalHistoryStore(str(history_path))

        key = "rec_v2_roundtrip_001"
        raw_draft = build_canonical_match_record_v7(
            match_id=key,
            lifecycle_status="DRAFT",
            played_at="2026-08-31T14:00:00Z",
            source="live_capture",
        )
        history_store.persist_record_transactional(raw_draft, is_finalized=False)

        # 1. Build a valid V2 review packet with 绝对是亲手钓的鱼 (image10-0-0)
        desc_prev = self._save_segment(key, (20, 90, 180))
        desc_next = self._save_segment(key, (20, 140, 80))
        packet = {
            "schemaVersion": PACKET_SCHEMA_V2,
            "recordStableKey": key,
            "sourceFingerprint": "0" * 64,
            "warehouseCoverage": {
                "status": "COMPLETE",
                "segmentCount": 2,
                "terminationReason": None,
            },
            "catalogCoverageStatus": "VERIFIED_COMPLETE",
            "reviewStatus": "REVIEW_REQUIRED",
            "segments": [
                {
                    "evidenceId": desc_prev["evidenceId"],
                    "kind": "warehouse-segment",
                    "sequenceIndex": 0,
                    "sha256": desc_prev["sha256"],
                    "width": 640,
                    "height": 720,
                    "coverageStatus": "PARTIAL",
                    "topEndpointTrusted": True,
                    "bottomEndpointTrusted": True,
                },
                {
                    "evidenceId": desc_next["evidenceId"],
                    "kind": "warehouse-segment",
                    "sequenceIndex": 1,
                    "sha256": desc_next["sha256"],
                    "width": 640,
                    "height": 720,
                    "coverageStatus": "PARTIAL",
                    "topEndpointTrusted": True,
                    "bottomEndpointTrusted": True,
                },
            ],
            "reviewUnits": [
                {
                    "reviewUnitId": "unit-world-5-0-5x5",
                    "placementStatus": "RESOLVED",
                    "visibility": "FULL",
                    "worldAnchor": {"row": 5, "col": 0},
                    "footprint": {"widthCells": 5, "heightCells": 5},
                    "physicalGroupId": "group-world-5-0",
                    "geometryEvidenceStatus": "EXACT",
                    "identityStatus": "REVIEW_REQUIRED",
                    "selectedCatalogId": None,
                    "bestObservationId": "obs-fish-prev",
                    "supportingTrackIds": [
                        "raw-track-fish-head",
                        "raw-track-fish-body",
                        "raw-track-fish-tail",
                    ],
                    "observations": [
                        {
                            "observationId": "obs-fish-prev",
                            "evidenceId": desc_prev["evidenceId"],
                            "sequenceIndex": 0,
                            "bbox": [50.0, 0.0, 250.0, 200.0],
                            "status": "FULL",
                        }
                    ],
                    "candidates": [
                        {
                            "catalogId": "image10-0-0",
                            "name": "绝对是亲手钓的鱼",
                            "confidence": 0.95,
                            "identityStatus": "CANDIDATE_ONLY",
                        }
                    ],
                }
            ],
            "summary": {
                "visibleUnitCount": 1,
                "candidateReadyCount": 1,
                "ambiguousCount": 0,
                "reviewedIdentityCount": 0,
            },
        }
        packet["sourceFingerprint"] = source_fingerprint_for(packet)

        # 2. Verify: Proposal != Truth (no auto-promotion of candidates to truth)
        session = WarehouseIdentityReviewSession(store=self.store, catalog=self.authority)
        view = session.open(packet)
        self.assertTrue(view["available"])
        self.assertEqual(view["processedCount"], 0)
        self.assertIsNone(session.artifact_copy(), "No reviewed artifact exists before explicit human review")

        # 3. Explicit human decision: Confirm candidate 绝对是亲手钓的鱼 (image10-0-0)
        session.select_candidate("image10-0-0")
        session.apply({"action": ACTION_CONFIRM, "confirmCandidate": True})
        session.finalize(reviewed_at="2026-08-31T15:00:00Z")
        reviewed_art = session.artifact_copy()
        self.assertIsNotNone(reviewed_art)
        self.assertEqual(reviewed_art["schemaVersion"], REVIEW_SCHEMA_V2)
        self.assertEqual(len(reviewed_art["resolvedItems"]), 1)

        # 4. Persist to isolated Canonical History Store
        binding = session.persist_binding()
        self.assertIsNotNone(binding)
        persist_res = persist_warehouse_identity_review(
            session=session,
            history_store=history_store,
            session_id=binding["sessionId"],
            packet_fingerprint=binding["packetFingerprint"],
            record_stable_key=key,
        )
        self.assertTrue(persist_res["ok"])
        self.assertTrue(persist_res["written"])

        # 5. Read back from Canonical History and verify round-trip fidelity
        loaded_record = history_store.lookup(key)
        self.assertIsNotNone(loaded_record)
        
        ok, val_reasons = validate_canonical_match_record_v7(loaded_record, match_id=key)
        self.assertTrue(ok, f"Canonical validation failed for admitted V2 review: {val_reasons}")

        stored_art = loaded_record["settlement"]["warehouseIdentityReview"]
        self.assertEqual(stored_art["schemaVersion"], REVIEW_SCHEMA_V2)
        self.assertEqual(stored_art["recordStableKey"], key)
        self.assertEqual(stored_art["packetFingerprint"], reviewed_art["packetFingerprint"])
        self.assertEqual(stored_art["artifactFingerprint"], reviewed_art["artifactFingerprint"])

        self.assertEqual(len(stored_art["resolvedItems"]), 1)
        fish_item = stored_art["resolvedItems"][0]
        self.assertEqual(fish_item["reviewUnitId"], "unit-world-5-0-5x5")
        self.assertEqual(fish_item["physicalGroupId"], "group-world-5-0")
        self.assertEqual(fish_item["supportingTrackIds"], ["raw-track-fish-head", "raw-track-fish-body", "raw-track-fish-tail"])
        self.assertEqual(fish_item["catalogId"], "image10-0-0")
        self.assertEqual(fish_item["name"], "绝对是亲手钓的鱼")
        self.assertEqual(fish_item["evidenceId"], desc_prev["evidenceId"])
        self.assertEqual(fish_item["sha256"], desc_prev["sha256"])
        self.assertEqual(fish_item["bbox"], [50.0, 0.0, 250.0, 200.0])
        self.assertEqual(fish_item["worldAnchor"], {"row": 5, "col": 0})
        self.assertEqual(fish_item["footprint"], {"widthCells": 5, "heightCells": 5})
        self.assertEqual(fish_item["provenanceType"], "HUMAN_REVIEWED_CATALOG_ID")


if __name__ == "__main__":
    unittest.main()
