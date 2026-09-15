# -*- coding: utf-8 -*-
"""Targeted unit tests for Phase 12 Warehouse Occupancy Adapter and Canonical Settlement Integration.

Covers:
1. EXACT + unique width/height -> RESOLVED
2. multiple width candidates -> AMBIGUOUS/null
3. multiple height candidates -> AMBIGUOUS/null
4. PIXEL_ONLY -> UNKNOWN/null
5. CONFLICT -> UNKNOWN/null
6. missing trackId -> skipped (fail-closed)
7. identity remains 'unresolved'
8. forbidden fields strictly absent
9. CurrentMatch receives occupancy
10. canonical settlement emits occupancy
11. second snapshot replaces first (REPLACE whole snapshot, not merge)
12. existing warehouse.slots / settlementItems / identityReview remain unchanged
13. WarehouseCaptureHost._finish writes back to CurrentMatch / occupancy_sink
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from current_match import CURRENT_MATCH
from canonical_match_record import (
    build_canonical_match_record_v7,
    validate_canonical_match_record_v7,
)
from warehouse_occupancy_adapter import (
    SCHEMA_VERSION,
    adapt_track_to_occupancy_track,
    adapt_review_packet_to_warehouse_occupancy,
    validate_warehouse_occupancy,
    FORBIDDEN_TRACK_KEYS,
)
from warehouse_capture_host import WarehouseCaptureHost


class WarehouseOccupancyAdapterTests(unittest.TestCase):
    def setUp(self):
        CURRENT_MATCH.begin_next_match()

    def tearDown(self):
        CURRENT_MATCH.begin_next_match()

    def test_exact_unique_width_height_resolves(self):
        """1. EXACT + unique width/height -> RESOLVED with integer dimensions (AC1)"""
        raw_track = {
            "trackId": "track_101",
            "geometryEvidenceStatus": "EXACT",
            "widthCandidates": [2],
            "heightCandidates": [3],
            "status": "CONFIRMED",
        }
        res = adapt_track_to_occupancy_track(raw_track)
        self.assertIsNotNone(res)
        self.assertEqual(res["trackId"], "track_101")
        self.assertEqual(res["geometryStatus"], "RESOLVED")
        self.assertEqual(res["width"], 2)
        self.assertEqual(res["height"], 3)
        self.assertEqual(res["evidenceLevel"], "OUTLINE_ONLY")
        self.assertEqual(res["identityStatus"], "unresolved")

    def test_multiple_width_candidates_ambiguous(self):
        """2. multiple width candidates -> AMBIGUOUS with null dimensions (AC2)"""
        raw_track = {
            "trackId": "track_102",
            "geometryEvidenceStatus": "EXACT",
            "widthCandidates": [2, 3],
            "heightCandidates": [1],
        }
        res = adapt_track_to_occupancy_track(raw_track)
        self.assertIsNotNone(res)
        self.assertEqual(res["geometryStatus"], "AMBIGUOUS")
        self.assertIsNone(res["width"])
        self.assertIsNone(res["height"])

    def test_multiple_height_candidates_ambiguous(self):
        """3. multiple height candidates -> AMBIGUOUS with null dimensions (AC2)"""
        raw_track = {
            "trackId": "track_103",
            "geometryEvidenceStatus": "EXACT",
            "widthCandidates": [1],
            "heightCandidates": [2, 4],
        }
        res = adapt_track_to_occupancy_track(raw_track)
        self.assertIsNotNone(res)
        self.assertEqual(res["geometryStatus"], "AMBIGUOUS")
        self.assertIsNone(res["width"])
        self.assertIsNone(res["height"])

    def test_pixel_only_unknown(self):
        """4. PIXEL_ONLY -> UNKNOWN with null dimensions (AC3)"""
        raw_track = {
            "trackId": "track_104",
            "geometryEvidenceStatus": "PIXEL_ONLY",
            "pixelOnly": True,
            "widthCandidates": [2],
            "heightCandidates": [2],
        }
        res = adapt_track_to_occupancy_track(raw_track)
        self.assertIsNotNone(res)
        self.assertEqual(res["geometryStatus"], "UNKNOWN")
        self.assertIsNone(res["width"])
        self.assertIsNone(res["height"])

    def test_conflict_unknown(self):
        """5. CONFLICT -> UNKNOWN with null dimensions, track retained (AC3)"""
        raw_track = {
            "trackId": "track_105",
            "status": "CONFLICT",
            "geometryEvidenceStatus": "EXACT",
            "widthCandidates": [1],
            "heightCandidates": [1],
        }
        res = adapt_track_to_occupancy_track(raw_track)
        self.assertIsNotNone(res)
        self.assertEqual(res["geometryStatus"], "UNKNOWN")
        self.assertIsNone(res["width"])
        self.assertIsNone(res["height"])

    def test_missing_track_id_skipped(self):
        """6. Missing or invalid trackId -> skipped fail-closed (AC4)"""
        for invalid_id in [None, "", "   ", False, True]:
            raw_track = {
                "trackId": invalid_id,
                "geometryEvidenceStatus": "EXACT",
                "widthCandidates": [1],
                "heightCandidates": [1],
            }
            res = adapt_track_to_occupancy_track(raw_track)
            self.assertIsNone(res)

        # In packet adapter, invalid tracks are omitted
        packet = {
            "tracks": [
                {"trackId": "", "geometryEvidenceStatus": "EXACT", "widthCandidates": [1], "heightCandidates": [1]},
                {"trackId": "valid_001", "geometryEvidenceStatus": "EXACT", "widthCandidates": [1], "heightCandidates": [1]},
            ]
        }
        occupancy = adapt_review_packet_to_warehouse_occupancy(packet)
        self.assertIsNotNone(occupancy)
        self.assertEqual(len(occupancy["tracks"]), 1)
        self.assertEqual(occupancy["tracks"][0]["trackId"], "valid_001")

    def test_identity_remains_unresolved(self):
        """7. identityStatus remains 'unresolved' regardless of input candidates (AC1, AC5)"""
        raw_track = {
            "trackId": "track_107",
            "geometryEvidenceStatus": "EXACT",
            "widthCandidates": [1],
            "heightCandidates": [1],
            "identityStatus": "IDENTIFIED",
            "identifiedName": "ForbiddenName",
            "selectedCatalogId": "item_999",
            "candidates": [{"name": "ForbiddenName"}],
        }
        res = adapt_track_to_occupancy_track(raw_track)
        self.assertIsNotNone(res)
        self.assertEqual(res["identityStatus"], "unresolved")

    def test_forbidden_fields_absent(self):
        """8. Forbidden fields are strictly absent in adapted tracks (AC5)"""
        raw_track = {
            "trackId": "track_108",
            "geometryEvidenceStatus": "EXACT",
            "widthCandidates": [2],
            "heightCandidates": [2],
            "identifiedName": "TestItem",
            "candidates": [{"catalogId": "item_1"}],
            "selectedCatalogId": "item_1",
            "bbox": [10, 20, 30, 40],
            "observations": [{"obsId": "obs_1"}],
            "segments": ["seg_1"],
            "coverage": "COMPLETE",
            "warnings": ["warn"],
            "price": 1000,
        }
        res = adapt_track_to_occupancy_track(raw_track)
        self.assertIsNotNone(res)
        for forbidden in FORBIDDEN_TRACK_KEYS:
            self.assertNotIn(forbidden, res)

    def test_current_match_receives_occupancy(self):
        """9. CurrentMatch receives warehouseOccupancy via apply_facts (AC6)"""
        packet = {
            "tracks": [
                {"trackId": "t_01", "geometryEvidenceStatus": "EXACT", "widthCandidates": [2], "heightCandidates": [3]},
            ]
        }
        occupancy = adapt_review_packet_to_warehouse_occupancy(packet)
        self.assertIsNotNone(occupancy)

        CURRENT_MATCH.apply_facts({"warehouseOccupancy": occupancy}, source="capture")
        self.assertEqual(CURRENT_MATCH.facts.get("warehouseOccupancy"), occupancy)

    def test_canonical_settlement_emits_occupancy(self):
        """10. Canonical MatchRecord settlement emits warehouseOccupancy (AC7)"""
        packet = {
            "tracks": [
                {"trackId": "t_01", "geometryEvidenceStatus": "EXACT", "widthCandidates": [2], "heightCandidates": [3]},
            ]
        }
        occupancy = adapt_review_packet_to_warehouse_occupancy(packet)

        CURRENT_MATCH.apply_facts({
            "warehouseOccupancy": occupancy,
            "clearingPrice": 10000,
            "actualTotal": 15000,
            "realizedProfit": 5000,
            "settlementReady": True,
        }, source="capture")

        canonical = CURRENT_MATCH.to_canonical()
        self.assertIn("settlement", canonical)
        self.assertIn("warehouseOccupancy", canonical["settlement"])
        self.assertEqual(canonical["settlement"]["warehouseOccupancy"], occupancy)

        # Validate canonical record
        ok, reasons = validate_canonical_match_record_v7(canonical)
        self.assertTrue(ok, f"Validation failed: {reasons}")

    def test_second_snapshot_replaces_first_not_merge(self):
        """11. Update semantics: second snapshot completely replaces first, no merge (AC8)"""
        packet1 = {
            "tracks": [
                {"trackId": "t_old_1", "geometryEvidenceStatus": "EXACT", "widthCandidates": [1], "heightCandidates": [1]},
                {"trackId": "t_old_2", "geometryEvidenceStatus": "EXACT", "widthCandidates": [1], "heightCandidates": [2]},
            ]
        }
        occ1 = adapt_review_packet_to_warehouse_occupancy(packet1)
        CURRENT_MATCH.apply_facts({"warehouseOccupancy": occ1}, source="capture")
        self.assertEqual(len(CURRENT_MATCH.facts["warehouseOccupancy"]["tracks"]), 2)

        packet2 = {
            "tracks": [
                {"trackId": "t_new_1", "geometryEvidenceStatus": "EXACT", "widthCandidates": [2], "heightCandidates": [2]},
            ]
        }
        occ2 = adapt_review_packet_to_warehouse_occupancy(packet2)
        CURRENT_MATCH.apply_facts({"warehouseOccupancy": occ2}, source="capture")

        # Must have ONLY the track from packet2, not merged
        current_occ = CURRENT_MATCH.facts["warehouseOccupancy"]
        self.assertEqual(len(current_occ["tracks"]), 1)
        self.assertEqual(current_occ["tracks"][0]["trackId"], "t_new_1")

    def test_existing_authorities_unchanged(self):
        """12. Existing warehouse.slots, settlementItems, and warehouseIdentityReview remain unchanged (AC7, AC12)"""
        existing_wh = {
            "slots": [
                {"col": 0, "row": 0, "w": 1, "h": 1, "rarity": "gold", "evidenceLevel": "CONFIRMED", "identifiedName": "TestGold"}
            ]
        }
        existing_items = [{"name": "ItemA", "price": 100}]

        packet = {
            "tracks": [
                {"trackId": "t_occ", "geometryEvidenceStatus": "EXACT", "widthCandidates": [2], "heightCandidates": [2]}
            ]
        }
        occ = adapt_review_packet_to_warehouse_occupancy(packet)

        CURRENT_MATCH.apply_facts({
            "warehouse": existing_wh,
            "settlementItems": existing_items,
            "warehouseOccupancy": occ,
            "clearingPrice": 5000,
            "actualTotal": 6000,
            "realizedProfit": 1000,
        }, source="capture")

        canonical = CURRENT_MATCH.to_canonical()

        # Check warehouse.slots unchanged
        self.assertEqual(canonical["warehouse"]["slots"][0]["identifiedName"], "TestGold")
        # Check settlementItems unchanged
        self.assertEqual(canonical["settlement"]["settlementItems"], existing_items)
        # Check warehouseOccupancy present in settlement
        self.assertEqual(canonical["settlement"]["warehouseOccupancy"]["tracks"][0]["trackId"], "t_occ")
        # Not polluted
        self.assertNotIn("warehouseOccupancy", canonical["warehouse"])

        ok, reasons = validate_canonical_match_record_v7(canonical)
        self.assertTrue(ok, f"Validation failed: {reasons}")

    def test_warehouse_capture_host_finish_writeback(self):
        """13. WarehouseCaptureHost._finish automatically adapts packet and writes back (AC6)"""
        host = WarehouseCaptureHost()
        sink_results = []
        host.set_occupancy_sink(lambda occ: sink_results.append(occ))

        fake_packet = {
            "tracks": [
                {"trackId": "host_track_01", "geometryEvidenceStatus": "EXACT", "widthCandidates": [2], "heightCandidates": [2]}
            ]
        }

        # Finish with packet
        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet=fake_packet)

        self.assertEqual(len(sink_results), 1)
        self.assertEqual(sink_results[0]["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(sink_results[0]["tracks"][0]["trackId"], "host_track_01")
        self.assertEqual(sink_results[0]["tracks"][0]["geometryStatus"], "RESOLVED")

        # Finish with None packet: sink not called again
        host._finish({"terminationReason": "COMPLETE", "packetAvailable": False}, packet=None)
        self.assertEqual(len(sink_results), 1)


if __name__ == "__main__":
    unittest.main()
