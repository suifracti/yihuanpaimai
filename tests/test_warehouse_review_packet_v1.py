"""Isolated tests for the evidence-backed warehouse review packet."""

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
from warehouse_coverage_ledger import (
    REASON_COMPLETE,
    REASON_USER_STOP,
    STATUS_COMPLETE,
    STATUS_PARTIAL,
    WarehouseCoverageLedger,
)
from warehouse_review_packet import (
    NOT_REVIEWABLE,
    PARTIAL_EVIDENCE,
    REVIEW_REQUIRED,
    SCHEMA_VERSION,
    WarehouseReviewPacketError,
    build_warehouse_review_packet,
    canonical_warehouse_review_packet,
    source_fingerprint_for,
    validate_warehouse_review_packet,
)


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _descriptor(evidence_id: str, seed: str, key: str = "recRev01", **overrides):
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


def _complete_coverage(key: str = "recRev01"):
    ledger = WarehouseCoverageLedger(key)
    top = _descriptor("ev-top", "aa", key)
    mid = _descriptor("ev-mid", "bb", key)
    bot = _descriptor("ev-bot", "cc", key)
    ledger.add_segment(top, sequence_index=0, top_proof={"trusted": True, "proofId": "t"})
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
    return ledger.finalize(REASON_COMPLETE), [top, mid, bot]


def _partial_coverage(key: str = "recRev01"):
    ledger = WarehouseCoverageLedger(key)
    top = _descriptor("ev-top", "aa", key)
    ledger.add_segment(top, sequence_index=0, top_proof={"trusted": True, "proofId": "t"})
    return ledger.finalize(REASON_USER_STOP), [top]


def _track(track_id: str, observations: list, **overrides):
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
    }
    item.update(overrides)
    return item


def _obs(observation_id: str, segment_id: str, sequence: int, box, status="OBSERVED", **extra):
    item = {
        "observationId": observation_id,
        "segmentId": segment_id,
        "sequenceIndex": sequence,
        "localBox": list(box),
        "status": status,
    }
    item.update(extra)
    return item


def _physical(key: str, tracks: list, segments: list | None = None):
    if segments is None:
        segments = [
            {"segmentId": "seg0", "sequenceIndex": 0, "originY": 0.0, "scrollState": "TOP", "chainId": 0},
            {"segmentId": "seg1", "sequenceIndex": 1, "originY": 90.0, "scrollState": "MIDDLE", "chainId": 0},
            {"segmentId": "seg2", "sequenceIndex": 2, "originY": 210.0, "scrollState": "MIDDLE", "chainId": 0},
        ]
    return {
        "schemaVersion": "warehouse-physical-ledger.v1",
        "recordStableKey": key,
        "chainStatus": "ACTIVE",
        "segments": segments,
        "tracks": tracks,
        "conflicts": [],
    }


class WarehouseReviewPacketV1Tests(unittest.TestCase):
    def setUp(self):
        self.index = CatalogGeometryIndex([
            {
                "Id": "catRect",
                "Name": "Rect2x2",
                "Width": 2,
                "Height": 2,
                "Cells": 4,
                "Shape": "1100011000000000000000000",
            },
            {
                "Id": "catEll",
                "Name": "Ell2x2",
                "Width": 2,
                "Height": 2,
                "Cells": 3,
                "Shape": "1000011000000000000000000",
            },
        ])

    def _packet(self, coverage=None, descriptors=None, physical=None, **kwargs):
        if coverage is None or descriptors is None:
            coverage, descriptors = _complete_coverage()
        if physical is None:
            physical = _physical("recRev01", [
                _track("pct1_recRev01_a", [
                    _obs("obs-a0", "seg0", 0, [3, 0, 115, 114]),
                    _obs("obs-a1", "seg1", 1, [3, 20, 115, 134], status="AMBIGUOUS", clippedTop=True),
                ]),
            ])
        return build_warehouse_review_packet(
            coverage_ledger=coverage,
            physical_ledger=physical,
            descriptors=descriptors,
            catalog_index=self.index,
            **kwargs,
        )

    def test_complete_coverage_keeps_identities_review_required(self):
        packet = self._packet()
        self.assertEqual(packet["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(packet["warehouseCoverage"]["status"], STATUS_COMPLETE)
        self.assertEqual(packet["reviewStatus"], REVIEW_REQUIRED)
        self.assertEqual(packet["summary"]["reviewedIdentityCount"], 0)
        self.assertTrue(packet["tracks"])
        for track in packet["tracks"]:
            self.assertEqual(track["identityStatus"], REVIEW_REQUIRED)
            self.assertIsNone(track["selectedCatalogId"])
            self.assertTrue(all(item["identityStatus"] == "CANDIDATE_ONLY" for item in track["candidates"]))
        ok, reasons = validate_warehouse_review_packet(packet)
        self.assertTrue(ok, reasons)

    def test_partial_packet_has_no_total_items_claim(self):
        coverage, descriptors = _partial_coverage()
        physical = _physical("recRev01", [
            _track("pct1_recRev01_a", [_obs("obs-a0", "seg0", 0, [1, 1, 40, 40])]),
        ], segments=[{"segmentId": "seg0", "sequenceIndex": 0, "originY": 0.0, "scrollState": "TOP", "chainId": 0}])
        packet = self._packet(coverage, descriptors, physical)
        self.assertEqual(packet["warehouseCoverage"]["status"], STATUS_PARTIAL)
        self.assertEqual(packet["reviewStatus"], PARTIAL_EVIDENCE)
        self.assertNotIn("totalItems", packet)
        self.assertNotIn("totalItems", packet["summary"])
        blob = json.dumps(packet)
        self.assertNotIn("完整仓库", blob)
        self.assertEqual(packet["summary"]["visibleTrackCount"], 1)

    def test_multi_segment_observations_stay_on_one_track(self):
        packet = self._packet()
        self.assertEqual(len(packet["tracks"]), 1)
        obs = packet["tracks"][0]["observations"]
        self.assertEqual([item["observationId"] for item in obs], ["obs-a0", "obs-a1"])
        self.assertEqual([item["sequenceIndex"] for item in obs], [0, 1])
        self.assertEqual(obs[0]["evidenceId"], "ev-top")
        self.assertEqual(obs[1]["evidenceId"], "ev-mid")

    def test_best_observation_prefers_complete_then_area_then_id(self):
        packet = self._packet()
        self.assertEqual(packet["tracks"][0]["bestObservationId"], "obs-a0")
        coverage, descriptors = _complete_coverage()
        physical = _physical("recRev01", [
            _track("pct1_recRev01_b", [
                _obs("obs-small", "seg0", 0, [0, 0, 10, 10]),
                _obs("obs-large", "seg1", 1, [0, 0, 80, 80]),
            ]),
        ])
        packet = self._packet(coverage, descriptors, physical)
        self.assertEqual(packet["tracks"][0]["bestObservationId"], "obs-large")

    def test_orphan_and_key_hash_mismatches_are_rejected(self):
        coverage, descriptors = _complete_coverage()
        physical = _physical("recRev01", [
            _track("pct1_recRev01_a", [_obs("obs-a0", "missing-seg", 0, [1, 1, 2, 2])]),
        ])
        with self.assertRaises(WarehouseReviewPacketError) as raised:
            self._packet(coverage, descriptors, physical)
        self.assertEqual(raised.exception.code, "ORPHAN_EVIDENCE")
        wrong_key = [dict(descriptors[0]), *descriptors[1:]]
        wrong_key[0] = dict(wrong_key[0], recordStableKey="otherKey")
        with self.assertRaises(WarehouseReviewPacketError) as raised:
            self._packet(coverage, wrong_key)
        self.assertEqual(raised.exception.code, "RECORD_KEY_MISMATCH")
        bad_hash = [dict(descriptors[0], sha256="f" * 64), *descriptors[1:]]
        with self.assertRaises(WarehouseReviewPacketError) as raised:
            self._packet(coverage, bad_hash)
        self.assertEqual(raised.exception.code, "HASH_MISMATCH")

    def test_duplicate_ids_are_rejected(self):
        coverage, descriptors = _complete_coverage()
        physical = _physical("recRev01", [
            _track("same-id", [_obs("obs-a0", "seg0", 0, [1, 1, 2, 2])]),
            _track("same-id", [_obs("obs-b0", "seg0", 0, [3, 3, 6, 6])]),
        ])
        with self.assertRaises(WarehouseReviewPacketError) as raised:
            self._packet(coverage, descriptors, physical)
        self.assertEqual(raised.exception.code, "DUPLICATE_TRACK_ID")
        physical = _physical("recRev01", [
            _track("t1", [_obs("dup", "seg0", 0, [1, 1, 2, 2])]),
            _track("t2", [_obs("dup", "seg1", 1, [1, 1, 2, 2])]),
        ])
        with self.assertRaises(WarehouseReviewPacketError) as raised:
            self._packet(coverage, descriptors, physical)
        self.assertEqual(raised.exception.code, "DUPLICATE_OBSERVATION_ID")

    def test_candidates_preserved_and_single_candidate_not_selected(self):
        packet = self._packet()
        track = packet["tracks"][0]
        ids = [item["catalogId"] for item in track["candidates"]]
        self.assertEqual(ids, sorted(ids))
        self.assertGreaterEqual(len(ids), 1)
        self.assertIsNone(track["selectedCatalogId"])
        self.assertNotEqual(track["identityStatus"], "UNIQUE_IN_CATALOG")
        if len(ids) == 1:
            self.assertNotEqual(track["candidateStatus"], "UNIQUE_IN_CATALOG")

    def test_clipped_and_pixel_only_are_not_upgraded(self):
        coverage, descriptors = _complete_coverage()
        physical = _physical("recRev01", [
            _track(
                "pct1_recRev01_clip",
                [_obs("obs-c", "seg0", 0, [1, 1, 20, 20], status="AMBIGUOUS", clippedBottom=True)],
                clipped=True,
                status="AMBIGUOUS",
                reasons=["CLIPPED_ONLY"],
            ),
            _track(
                "pct1_recRev01_pix",
                [_obs("obs-p", "seg1", 1, [1, 1, 20, 20], status="AMBIGUOUS")],
                status="AMBIGUOUS",
                reasons=["PIXEL_ONLY"],
            ),
        ])
        packet = self._packet(coverage, descriptors, physical)
        by_id = {item["trackId"]: item for item in packet["tracks"]}
        self.assertEqual(by_id["pct1_recRev01_clip"]["geometryEvidenceStatus"], "COMPATIBLE_ONLY")
        self.assertTrue(by_id["pct1_recRev01_clip"]["clipped"])
        self.assertEqual(by_id["pct1_recRev01_pix"]["geometryEvidenceStatus"], "PIXEL_ONLY")
        self.assertTrue(by_id["pct1_recRev01_pix"]["pixelOnly"])

    def test_canonical_json_and_fingerprint_are_stable(self):
        first = self._packet()
        second = self._packet()
        self.assertEqual(first, second)
        self.assertEqual(canonical_warehouse_review_packet(first), canonical_warehouse_review_packet(second))
        self.assertEqual(first["sourceFingerprint"], source_fingerprint_for(first))
        self.assertEqual(len(first["sourceFingerprint"]), 64)

    def test_output_has_no_paths_bytes_quality_or_price(self):
        packet = self._packet()
        blob = canonical_warehouse_review_packet(packet)
        for token in ("relativePath", "imageBytes", "Quality", "Value", "knownItems", "C:\\", "/Users/"):
            self.assertNotIn(token, blob)
        schema = json.loads(
            (PROJECT_ROOT / "docs" / "contracts" / "warehouse-review-packet-v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], SCHEMA_VERSION)

    def test_catalog_count_is_conserved(self):
        report = CatalogGeometryIndex().isolation_report()
        self.assertEqual(report["indexedCount"] + report["isolatedCount"], 200)
        self.assertEqual(report["isolatedCount"], 7)
        self.assertEqual(report["indexedCount"], 193)

    def test_builder_does_not_write_history_or_pick_first(self):
        source = (CORE_DIR / "warehouse_review_packet.py").read_text(encoding="utf-8")
        self.assertNotIn("canonical_history", source)
        self.assertNotIn("candidates[0]", source)
        self.assertNotIn("warehouse_vision", source)
        self.assertNotIn("get_production_scroll_driver", source)
        self.assertNotIn("from known_items", source)


if __name__ == "__main__":
    unittest.main()
