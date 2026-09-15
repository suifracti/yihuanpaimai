"""Isolated tests for explicit human warehouse identity review."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(CORE_DIR),):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from settlement_truth_evidence_contract import ORIGINAL_V2
from warehouse_catalog_geometry import CatalogGeometryIndex
from warehouse_coverage_ledger import REASON_COMPLETE, REASON_USER_STOP, WarehouseCoverageLedger
from warehouse_identity_review import (
    ACTION_CONFIRM,
    ACTION_DEFER,
    ACTION_EXCLUDE,
    ACTION_FLAG,
    ACTION_OUT_OF_CATALOG,
    ACTION_OVERRIDE,
    CatalogAuthority,
    WarehouseIdentityReviewError,
    artifact_fingerprint_for,
    canonical_identity_review,
    resolve_warehouse_identity_review,
)
from warehouse_review_packet import build_warehouse_review_packet


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _descriptor(evidence_id: str, seed: str, key: str = "recIdRev01", **overrides):
    digest = _digest(seed)
    item = {
        "schemaVersion": ORIGINAL_V2,
        "evidenceId": evidence_id,
        "recordStableKey": key,
        "kind": "warehouse-segment",
        "capturedAt": "2026-08-25T12:00:00Z",
        "storageMode": "file",
        "relativePath": f"evidence/settlement_v2/blobs/{digest[:2]}/{digest}.png",
        "sha256": digest,
        "byteSize": 1024,
        "mimeType": "image/png",
        "width": 640,
        "height": 720,
        "coverageMode": "viewport-segment",
        "coverageStatus": "PARTIAL",
    }
    item.update(overrides)
    return item


def _coverage(complete: bool, key: str = "recIdRev01"):
    ledger = WarehouseCoverageLedger(key)
    top = _descriptor("ev-top", "aa", key)
    descriptors = [top]
    ledger.add_segment(top, sequence_index=0, top_proof={"trusted": True, "proofId": "t"})
    if complete:
        mid = _descriptor("ev-mid", "bb", key)
        bot = _descriptor("ev-bot", "cc", key)
        descriptors.extend([mid, bot])
        ledger.add_segment(
            mid,
            sequence_index=1,
            overlap_proof={"trusted": True, "aligned": True, "proofId": "o1", "previousEvidenceId": "ev-top"},
        )
        ledger.add_segment(
            bot,
            sequence_index=2,
            bottom_proof={"trusted": True, "proofId": "b"},
            overlap_proof={"trusted": True, "aligned": True, "proofId": "o2", "previousEvidenceId": "ev-mid"},
        )
        return ledger.finalize(REASON_COMPLETE), descriptors
    return ledger.finalize(REASON_USER_STOP), descriptors


def _track(track_id: str, candidates: list, observations: list, **overrides):
    item = {
        "trackId": track_id,
        "status": "OBSERVED",
        "clipped": False,
        "reasons": [],
        "widthCandidates": [2],
        "heightCandidates": [2],
        "spanCandidates": [4],
        "globalCellMaskCandidates": [{"cellMask": [[1, 1], [1, 1]]}],
        "observations": observations,
        "candidates": candidates,
    }
    item.update(overrides)
    return item


def _obs(oid: str, segment_id: str, sequence: int):
    return {
        "observationId": oid,
        "segmentId": segment_id,
        "sequenceIndex": sequence,
        "localBox": [4.0, 6.0, 40.0, 50.0],
        "status": "OBSERVED",
    }


def _physical(key: str, tracks: list, complete: bool):
    segments = [{"segmentId": "seg0", "sequenceIndex": 0, "originY": 0.0, "scrollState": "TOP", "chainId": 0}]
    if complete:
        segments.extend([
            {"segmentId": "seg1", "sequenceIndex": 1, "originY": 90.0, "scrollState": "MIDDLE", "chainId": 0},
            {"segmentId": "seg2", "sequenceIndex": 2, "originY": 210.0, "scrollState": "BOTTOM", "chainId": 0},
        ])
    return {
        "schemaVersion": "warehouse-physical-ledger.v1",
        "recordStableKey": key,
        "chainStatus": "ACTIVE",
        "segments": segments,
        "tracks": tracks,
        "conflicts": [],
    }


CATALOG = [
    {
        "Id": "catRect",
        "Name": "RectBox",
        "Quality": "金",
        "Width": 2,
        "Height": 2,
        "Cells": 4,
        "Shape": "1100011000000000000000000",
        "Value": 123,
        "File": "nope.png",
    },
    {
        "Id": "catOther",
        "Name": "OtherItem",
        "Quality": "紫",
        "Width": 3,
        "Height": 1,
        "Cells": 3,
        "Shape": "1110000000000000000000000",
        "Value": 9,
        "File": "x.png",
    },
    {
        "Id": "image36-0-1",
        "Name": "QuarantinedItem",
        "Quality": "红",
        "Width": 2,
        "Height": 1,
        "Cells": 1,
        "Shape": "1100000000000000000000000",
        "Value": 1,
        "File": "q.png",
    },
]


class WarehouseIdentityReviewV1Tests(unittest.TestCase):
    def setUp(self):
        self.index = CatalogGeometryIndex(CATALOG)
        self.authority = CatalogAuthority(CATALOG)

    def _packet(self, *, complete=True, extra_tracks=None):
        coverage, descriptors = _coverage(complete)
        candidates = [
            {
                "catalogId": "catRect",
                "name": "RectBox",
                "identityStatus": "CANDIDATE_ONLY",
                "geometry": {"width": 2, "height": 2, "cells": 4, "shape": "1100011000000000000000000"},
                "matchReasons": ["EXACT_CELL_MASK"],
            }
        ]
        tracks = [
            _track(
                "track-a",
                candidates,
                [_obs("obs-a0", "seg0", 0), _obs("obs-a1", "seg1" if complete else "seg0", 1 if complete else 0)],
            )
        ]
        if extra_tracks:
            tracks.extend(extra_tracks)
        physical = _physical("recIdRev01", tracks, complete)
        packet = build_warehouse_review_packet(
            coverage_ledger=coverage,
            physical_ledger=physical,
            descriptors=descriptors,
            catalog_index=self.index,
        )
        packet["tracks"][0]["candidates"] = candidates
        packet["tracks"][0]["bestObservationId"] = "obs-a0"
        packet["sourceFingerprint"] = __import__(
            "warehouse_review_packet", fromlist=["source_fingerprint_for"]
        ).source_fingerprint_for(packet)
        return packet

    def _decision(self, packet, decisions, **overrides):
        document = {
            "schemaVersion": "warehouse-identity-review-decision.v1",
            "recordStableKey": packet["recordStableKey"],
            "packetFingerprint": packet["sourceFingerprint"],
            "reviewedAt": "2026-08-25T15:00:00Z",
            "reviewerType": "HUMAN",
            "decisions": decisions,
        }
        document.update(overrides)
        return document

    def test_fingerprint_mismatch_is_rejected(self):
        packet = self._packet()
        document = self._decision(packet, [])
        document["packetFingerprint"] = "a" * 64
        with self.assertRaises(WarehouseIdentityReviewError) as raised:
            resolve_warehouse_identity_review(packet, document, catalog=self.authority)
        self.assertEqual(raised.exception.code, "PACKET_FINGERPRINT_MISMATCH")

    def test_unknown_and_duplicate_tracks_are_rejected(self):
        packet = self._packet()
        with self.assertRaises(WarehouseIdentityReviewError) as raised:
            resolve_warehouse_identity_review(
                packet,
                self._decision(packet, [{"decisionId": "d1", "trackId": "missing", "action": ACTION_DEFER}]),
                catalog=self.authority,
            )
        self.assertEqual(raised.exception.code, "UNKNOWN_TRACK")
        with self.assertRaises(WarehouseIdentityReviewError) as raised:
            resolve_warehouse_identity_review(
                packet,
                self._decision(packet, [
                    {"decisionId": "d1", "trackId": "track-a", "action": ACTION_DEFER},
                    {"decisionId": "d2", "trackId": "track-a", "action": ACTION_EXCLUDE, "reason": "dup"},
                ]),
                catalog=self.authority,
            )
        self.assertEqual(raised.exception.code, "INVALID_DECISION")

    def test_single_candidate_without_human_decision_stays_unresolved(self):
        packet = self._packet()
        artifact = resolve_warehouse_identity_review(packet, self._decision(packet, []), catalog=self.authority)
        self.assertEqual(artifact["reviewCompletion"], "NOT_STARTED")
        self.assertEqual(artifact["identityResolution"], "NONE")
        self.assertEqual(artifact["resolvedItems"], [])
        self.assertEqual(artifact["unresolvedTracks"][0]["trackId"], "track-a")

    def test_confirm_candidate_reads_name_and_quality_from_catalog(self):
        packet = self._packet()
        artifact = resolve_warehouse_identity_review(
            packet,
            self._decision(packet, [{
                "decisionId": "d1",
                "trackId": "track-a",
                "action": ACTION_CONFIRM,
                "selectedCatalogId": "catRect",
            }]),
            catalog=self.authority,
        )
        item = artifact["resolvedItems"][0]
        self.assertEqual(item["name"], "RectBox")
        self.assertEqual(item["quality"], "金")
        self.assertEqual(item["action"], ACTION_CONFIRM)
        self.assertEqual(item["provenanceType"], "HUMAN_REVIEWED_CATALOG_ID")
        self.assertEqual(item["catalogGeometryStatus"], "INDEXED")
        self.assertEqual(item["evidenceId"], "ev-top")
        self.assertEqual(item["sha256"], _digest("aa"))
        self.assertEqual(item["bbox"], [4.0, 6.0, 40.0, 50.0])
        self.assertEqual(len(artifact["resolvedItems"]), 1)

    def test_non_candidate_cannot_use_confirm_candidate(self):
        packet = self._packet()
        with self.assertRaises(WarehouseIdentityReviewError) as raised:
            resolve_warehouse_identity_review(
                packet,
                self._decision(packet, [{
                    "decisionId": "d1",
                    "trackId": "track-a",
                    "action": ACTION_CONFIRM,
                    "selectedCatalogId": "catOther",
                }]),
                catalog=self.authority,
            )
        self.assertEqual(raised.exception.code, "CATALOG_ID_NOT_CANDIDATE")

    def test_override_requires_reason_and_human_flag(self):
        packet = self._packet()
        with self.assertRaises(WarehouseIdentityReviewError) as raised:
            resolve_warehouse_identity_review(
                packet,
                self._decision(packet, [{
                    "decisionId": "d1",
                    "trackId": "track-a",
                    "action": ACTION_OVERRIDE,
                    "selectedCatalogId": "catOther",
                    "confirmedByHuman": True,
                }]),
                catalog=self.authority,
            )
        self.assertEqual(raised.exception.code, "INVALID_DECISION")
        with self.assertRaises(WarehouseIdentityReviewError) as raised:
            resolve_warehouse_identity_review(
                packet,
                self._decision(packet, [{
                    "decisionId": "d1",
                    "trackId": "track-a",
                    "action": ACTION_OVERRIDE,
                    "selectedCatalogId": "catOther",
                    "overrideReason": "HUMAN_VISUAL_IDENTIFICATION",
                    "confirmedByHuman": False,
                }]),
                catalog=self.authority,
            )
        self.assertEqual(raised.exception.code, "INVALID_DECISION")

    def test_override_keeps_provenance_and_quarantined_flag(self):
        packet = self._packet()
        artifact = resolve_warehouse_identity_review(
            packet,
            self._decision(packet, [{
                "decisionId": "d1",
                "trackId": "track-a",
                "action": ACTION_OVERRIDE,
                "selectedCatalogId": "catOther",
                "overrideReason": "HUMAN_VISUAL_IDENTIFICATION",
                "confirmedByHuman": True,
            }]),
            catalog=self.authority,
        )
        item = artifact["resolvedItems"][0]
        self.assertEqual(item["catalogId"], "catOther")
        self.assertEqual(item["name"], "OtherItem")
        self.assertEqual(item["quality"], "紫")
        self.assertEqual(item["overrideReason"], "HUMAN_VISUAL_IDENTIFICATION")
        self.assertEqual(item["action"], ACTION_OVERRIDE)
        self.assertEqual([c["catalogId"] for c in packet["tracks"][0]["candidates"]], ["catRect"])

        quarantined = resolve_warehouse_identity_review(
            packet,
            self._decision(packet, [{
                "decisionId": "d1",
                "trackId": "track-a",
                "action": ACTION_OVERRIDE,
                "selectedCatalogId": "image36-0-1",
                "overrideReason": "CATALOG_GEOMETRY_MISMATCH",
                "confirmedByHuman": True,
            }]),
            catalog=self.authority,
        )
        self.assertEqual(quarantined["resolvedItems"][0]["catalogGeometryStatus"], "QUARANTINED")
        with self.assertRaises(WarehouseIdentityReviewError) as raised:
            resolve_warehouse_identity_review(
                packet,
                self._decision(packet, [{
                    "decisionId": "d1",
                    "trackId": "track-a",
                    "action": ACTION_CONFIRM,
                    "selectedCatalogId": "image36-0-1",
                }]),
                catalog=self.authority,
            )
        self.assertIn(raised.exception.code, {"CATALOG_ID_NOT_CANDIDATE", "QUARANTINED_REQUIRES_OVERRIDE"})

    def test_out_of_catalog_defer_exclude_and_flag(self):
        packet = self._packet()
        out = resolve_warehouse_identity_review(
            packet,
            self._decision(packet, [{
                "decisionId": "d1",
                "trackId": "track-a",
                "action": ACTION_OUT_OF_CATALOG,
                "reason": "not in book",
            }]),
            catalog=self.authority,
        )
        self.assertEqual(out["resolvedItems"], [])
        self.assertEqual(out["unresolvedTracks"][0]["action"], ACTION_OUT_OF_CATALOG)
        self.assertEqual(out["reviewCompletion"], "COMPLETE")
        self.assertEqual(out["identityResolution"], "PARTIAL")
        blob = json.dumps(out)
        self.assertNotIn("RectBox", blob)

        deferred = resolve_warehouse_identity_review(
            packet,
            self._decision(packet, [{"decisionId": "d1", "trackId": "track-a", "action": ACTION_DEFER}]),
            catalog=self.authority,
        )
        self.assertEqual(deferred["reviewCompletion"], "PARTIAL")
        self.assertEqual(deferred["identityResolution"], "NONE")

        excluded = resolve_warehouse_identity_review(
            packet,
            self._decision(packet, [{
                "decisionId": "d1",
                "trackId": "track-a",
                "action": ACTION_EXCLUDE,
                "reason": "scrollbar thumb",
            }]),
            catalog=self.authority,
        )
        self.assertEqual(excluded["excludedTracks"][0]["trackId"], "track-a")
        self.assertEqual(excluded["resolvedItems"], [])

        flagged = resolve_warehouse_identity_review(
            packet,
            self._decision(packet, [{
                "decisionId": "d1",
                "trackId": "track-a",
                "action": ACTION_FLAG,
                "reason": "needs split",
                "geometryErrorType": "SPLIT_REQUIRED",
            }]),
            catalog=self.authority,
        )
        self.assertEqual(flagged["identityResolution"], "PARTIAL")
        self.assertEqual(flagged["reviewCompletion"], "COMPLETE")

    def test_partial_coverage_cannot_be_fully_resolved(self):
        packet = self._packet(complete=False)
        artifact = resolve_warehouse_identity_review(
            packet,
            self._decision(packet, [{
                "decisionId": "d1",
                "trackId": "track-a",
                "action": ACTION_CONFIRM,
                "selectedCatalogId": "catRect",
            }]),
            catalog=self.authority,
        )
        self.assertEqual(artifact["warehouseCoverageStatus"], "PARTIAL")
        self.assertEqual(artifact["reviewCompletion"], "COMPLETE")
        self.assertEqual(artifact["identityResolution"], "PARTIAL")
        self.assertEqual(artifact["resolvedItems"][0]["name"], "RectBox")

    def test_complete_coverage_and_all_confirms_are_fully_resolved(self):
        packet = self._packet(complete=True)
        artifact = resolve_warehouse_identity_review(
            packet,
            self._decision(packet, [{
                "decisionId": "d1",
                "trackId": "track-a",
                "action": ACTION_CONFIRM,
                "selectedCatalogId": "catRect",
            }]),
            catalog=self.authority,
        )
        self.assertEqual(artifact["warehouseCoverageStatus"], "COMPLETE")
        self.assertEqual(artifact["reviewCompletion"], "COMPLETE")
        self.assertEqual(artifact["identityResolution"], "FULLY_RESOLVED")
        self.assertEqual(len(artifact["resolvedItems"]), 1)

    def test_client_forged_fields_are_rejected(self):
        packet = self._packet()
        document = self._decision(packet, [{
            "decisionId": "d1",
            "trackId": "track-a",
            "action": ACTION_CONFIRM,
            "selectedCatalogId": "catRect",
            "Name": "Fake",
            "Quality": "红",
            "sha256": "f" * 64,
            "bbox": [0, 0, 1, 1],
        }])
        with self.assertRaises(WarehouseIdentityReviewError) as raised:
            resolve_warehouse_identity_review(packet, document, catalog=self.authority)
        self.assertEqual(raised.exception.code, "INVALID_DECISION")

    def test_artifact_is_deterministic_and_closed(self):
        packet = self._packet()
        document = self._decision(packet, [{
            "decisionId": "d1",
            "trackId": "track-a",
            "action": ACTION_CONFIRM,
            "selectedCatalogId": "catRect",
        }])
        first = resolve_warehouse_identity_review(packet, document, catalog=self.authority)
        second = resolve_warehouse_identity_review(packet, document, catalog=self.authority)
        self.assertEqual(first, second)
        self.assertEqual(canonical_identity_review(first), canonical_identity_review(second))
        self.assertEqual(first["artifactFingerprint"], artifact_fingerprint_for(first))
        source = (CORE_DIR / "warehouse_identity_review.py").read_text(encoding="utf-8")
        self.assertNotIn("candidates[0]", source)
        self.assertNotIn("canonical_history", source)
        self.assertNotIn("knownItems", source)
        self.assertNotIn("warehouse_vision", source)
        schema = json.loads(
            (PROJECT_ROOT / "docs" / "contracts" / "warehouse-identity-review-v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertIs(schema["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
