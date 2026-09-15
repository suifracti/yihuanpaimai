# -*- coding: utf-8 -*-
"""Phase 13 Targeted Tests: Settlement Warehouse Occupancy DRAFT Persistence.

Verifies:
1. DRAFT exists -> occupancy completion -> persisted DRAFT contains occupancy (AC1, AC2)
2. same record id retained / no duplicate record created (AC3)
3. FINALIZED exists -> strictly unchanged / forbidden mutation (AC4)
4. mismatched match id -> fail-closed, unchanged (AC5)
5. no record exists -> fail-closed, does not create record (AC5)
6. occupancy is None / invalid -> no fake persistence (AC6)
7. repeated completion for same capture -> no duplicates created, idempotent (AC3, AC8)
8. Phase 12 canonical occupancy content preserved byte-for-byte in persisted record (AC2, AC8)
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
TESTS_DIR = PROJECT_ROOT / "tests"
for entry in (str(APP_DIR), str(CORE_DIR), str(TESTS_DIR), "C:/Program Files/Python310/Lib/site-packages"):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_history_store import CanonicalHistoryStore
from current_match import CurrentMatch, CURRENT_MATCH
from warehouse_capture_host import WarehouseCaptureHost
from warehouse_occupancy_adapter import SCHEMA_VERSION


class WarehouseOccupancyDraftPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "异环拍卖数据.json"
        self.store = CanonicalHistoryStore(str(self.db_path))
        CURRENT_MATCH.begin_next_match()

    def tearDown(self):
        self.tmp_dir.cleanup()
        CURRENT_MATCH.begin_next_match()

    def _create_initial_draft(self, match_id="match_test_001"):
        CURRENT_MATCH.id = match_id
        CURRENT_MATCH.lifecycle_status = "DRAFT"
        CURRENT_MATCH.facts["clearingPrice"] = 10000
        CURRENT_MATCH.facts["actualTotal"] = 15000
        CURRENT_MATCH.facts["realizedProfit"] = 5000
        CURRENT_MATCH.facts["settlementReady"] = True
        CURRENT_MATCH.facts["warehouse"] = {
            "slots": [
                {"col": 0, "row": 0, "w": 1, "h": 1, "rarity": "gold", "evidenceLevel": "CONFIRMED", "identifiedName": "ItemA"}
            ]
        }
        draft = CURRENT_MATCH.to_canonical()
        draft["id"] = match_id
        draft["lifecycleStatus"] = "DRAFT"
        persisted = self.store.persist_record_transactional(draft, is_finalized=False)
        return persisted

    def _create_finalized_record(self, match_id="match_finalized_001"):
        CURRENT_MATCH.id = match_id
        CURRENT_MATCH.lifecycle_status = "FINALIZED"
        CURRENT_MATCH.facts["clearingPrice"] = 10000
        CURRENT_MATCH.facts["actualTotal"] = 15000
        CURRENT_MATCH.facts["realizedProfit"] = 5000
        CURRENT_MATCH.facts["settlementReady"] = True
        CURRENT_MATCH.facts["box"] = "皮制宝箱"
        CURRENT_MATCH.facts["fieldCondition"] = "standard"
        final_rec = CURRENT_MATCH.to_canonical()
        final_rec["id"] = match_id
        final_rec["lifecycleStatus"] = "FINALIZED"
        final_rec["settlement"]["verified"] = True
        final_rec["settlement"]["winner"] = "玩家本人"
        final_rec["settlement"]["acquired"] = True
        from canonical_match_record import FORBIDDEN_ROOT_LEGACY_FIELDS
        final_rec = {
            k: v for k, v in final_rec.items()
            if k not in FORBIDDEN_ROOT_LEGACY_FIELDS
        }
        persisted = self.store.persist_record_transactional(final_rec, is_finalized=True)
        return persisted

    def test_completion_preserves_all_non_occupancy_fields_from_disk(self):
        match_id = "match_preserve_disk"
        draft = self._create_initial_draft(match_id)
        draft["qualities"]["gold"]["count"] = 4
        draft["publicIntel"]["totalItems"] = 30
        draft["bidding"]["historicalBids"] = {"R1": [10000, 12000]}
        self.store.persist_record_transactional(draft, is_finalized=False)
        before = self.store.get_record(match_id)
        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        packet = {"recordStableKey": match_id, "tracks": [
            {"trackId": "preserved", "geometryEvidenceStatus": "EXACT",
             "widthCandidates": [1], "heightCandidates": [1]}
        ]}
        for _ in range(2):
            host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet=packet)
            after = CanonicalHistoryStore(self.db_path).get_record(match_id)
            self.assertTrue(after["settlement"].pop("warehouseOccupancy")["tracks"])
            self.assertEqual(after, before)
            self.assertEqual(len(self.store.read_database()["records"]), 1)

    def test_later_auto_archive_preserves_independent_capture(self):
        try:
            from auto_archiver import AutoArchiver
            import test_live_settlement_authority as fixture
        except (ImportError, ModuleNotFoundError):
            self.skipTest("win32gui / main environment not available")
        match_id = "match_capture_then_finalize"
        CURRENT_MATCH.id = match_id
        archiver = AutoArchiver([str(self.db_path)])
        archiver.archive_match(fixture.LiveSettlementAuthorityTests().context(match_id, None))
        packet = {"recordStableKey": match_id, "tracks": [
            {"trackId": "captured", "geometryEvidenceStatus": "EXACT",
             "widthCandidates": [2], "heightCandidates": [3]}]}
        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet=packet)
        occupancy = self.store.get_record(match_id)["settlement"]["warehouseOccupancy"]
        saved = archiver.archive_match(fixture.LiveSettlementAuthorityTests().context(match_id, False))
        self.assertEqual(saved["settlement"]["warehouseOccupancy"], occupancy)
        self.assertEqual(saved["lifecycleStatus"], "FINALIZED")

    def test_late_packet_does_not_change_new_match_or_history(self):
        old_id = "match_old_capture"
        self._create_initial_draft(old_id)
        before = self.store.get_record(old_id)
        CURRENT_MATCH.begin_next_match()
        current_before = copy.deepcopy(CURRENT_MATCH.facts)
        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet={
            "recordStableKey": old_id, "tracks": [
                {"trackId": "late", "geometryEvidenceStatus": "EXACT",
                 "widthCandidates": [1], "heightCandidates": [1]}
            ]})
        self.assertEqual(CURRENT_MATCH.facts, current_before)
        rec_after = self.store.get_record(old_id)
        self.assertIn("warehouseOccupancy", rec_after["settlement"])

    def test_packet_without_match_id_cannot_borrow_current_match(self):
        match_id = "match_missing_packet_key"
        self._create_initial_draft(match_id)
        before = self.store.get_record(match_id)
        current_before = copy.deepcopy(CURRENT_MATCH.facts)
        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet={
            "tracks": [{"trackId": "unbound", "geometryEvidenceStatus": "EXACT",
                        "widthCandidates": [1], "heightCandidates": [1]}]})
        self.assertEqual(CURRENT_MATCH.facts, current_before)
        self.assertEqual(self.store.get_record(match_id), before)

    def test_draft_exists_capture_completion_persists_occupancy(self):
        """1. DRAFT exists -> occupancy completion -> persisted DRAFT on disk contains occupancy (AC1, AC2)"""
        match_id = "match_draft_persist_001"
        self._create_initial_draft(match_id)

        # Confirm initial draft in store does NOT have warehouseOccupancy
        rec_before = self.store.get_record(match_id)
        self.assertNotIn("warehouseOccupancy", rec_before.get("settlement", {}))

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)

        fake_packet = {
            "recordStableKey": match_id,
            "tracks": [
                {"trackId": "trk_01", "geometryEvidenceStatus": "EXACT", "widthCandidates": [2], "heightCandidates": [3]}
            ]
        }

        # Trigger completion
        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet=fake_packet)

        # Verify disk record updated
        rec_after = self.store.get_record(match_id)
        self.assertIsNotNone(rec_after)
        self.assertEqual(rec_after["lifecycleStatus"], "DRAFT")
        self.assertIn("warehouseOccupancy", rec_after["settlement"])
        occ = rec_after["settlement"]["warehouseOccupancy"]
        self.assertEqual(occ["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(len(occ["tracks"]), 1)
        self.assertEqual(occ["tracks"][0]["trackId"], "trk_01")
        self.assertEqual(occ["tracks"][0]["geometryStatus"], "RESOLVED")
        self.assertEqual(occ["tracks"][0]["width"], 2)
        self.assertEqual(occ["tracks"][0]["height"], 3)

    def test_same_record_id_retained_no_duplicate(self):
        """2. Same record id retained / no duplicate record created in history store (AC3)"""
        match_id = "match_no_duplicate_001"
        self._create_initial_draft(match_id)

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        fake_packet = {
            "recordStableKey": match_id,
            "tracks": [
                {"trackId": "trk_unique", "geometryEvidenceStatus": "EXACT", "widthCandidates": [1], "heightCandidates": [1]}
            ]
        }

        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet=fake_packet)

        db_data = self.store.read_database()
        records = db_data.get("records", [])
        matching = [r for r in records if str(r.get("id")) == match_id]
        self.assertEqual(len(records), 1)
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["id"], match_id)

    def test_finalized_record_strictly_unchanged(self):
        """3. FINALIZED record exists -> strictly unchanged / forbidden content overwrite (AC4)"""
        match_id = "match_finalized_001"
        final_rec = self._create_finalized_record(match_id)
        rec_before = copy.deepcopy(self.store.get_record(match_id))

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        fake_packet = {
            "recordStableKey": match_id,
            "tracks": [
                {"trackId": "trk_forbidden", "geometryEvidenceStatus": "EXACT", "widthCandidates": [1], "heightCandidates": [1]}
            ]
        }

        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet=fake_packet)

        rec_after = self.store.get_record(match_id)
        self.assertEqual(rec_after["lifecycleStatus"], "FINALIZED")
        # Item 3: Preserves facts (clearing price, bidding, facts) while safely appending warehouse evidence
        self.assertEqual(rec_after["settlement"]["clearingPrice"], rec_before["settlement"]["clearingPrice"])
        self.assertEqual(rec_after["settlement"]["winner"], rec_before["settlement"]["winner"])
        self.assertIn("warehouseOccupancy", rec_after.get("settlement", {}))

    def test_mismatched_match_id_fail_closed(self):
        """4. Mismatched match id -> fail-closed, does not touch other records (AC5)"""
        match_id_stored = "match_stored_001"
        self._create_initial_draft(match_id_stored)
        rec_before = copy.deepcopy(self.store.get_record(match_id_stored))

        CURRENT_MATCH.id = "match_other_002"

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        fake_packet = {
            "recordStableKey": "match_other_002",
            "tracks": [
                {"trackId": "trk_other", "geometryEvidenceStatus": "EXACT", "widthCandidates": [1], "heightCandidates": [1]}
            ]
        }

        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet=fake_packet)

        # Stored record must remain unchanged
        rec_after = self.store.get_record(match_id_stored)
        self.assertEqual(rec_before, rec_after)

        # No new record created for match_other_002
        self.assertIsNone(self.store.get_record("match_other_002"))

    def test_no_record_exists_fail_closed(self):
        """5. No record in store -> fail-closed, does not create record (AC5)"""
        match_id = "match_unpersisted_001"
        CURRENT_MATCH.id = match_id

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        fake_packet = {
            "recordStableKey": match_id,
            "tracks": [
                {"trackId": "trk_unpersisted", "geometryEvidenceStatus": "EXACT", "widthCandidates": [1], "heightCandidates": [1]}
            ]
        }

        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet=fake_packet)

        # Store remains completely empty
        db_data = self.store.read_database()
        self.assertEqual(len(db_data.get("records", [])), 0)

    def test_occupancy_none_no_fake_persistence(self):
        """6. occupancy adapter returns None / invalid -> no fake persistence (AC6)"""
        match_id = "match_no_tracks_001"
        self._create_initial_draft(match_id)
        rec_before = copy.deepcopy(self.store.get_record(match_id))

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)

        # Empty tracks -> adapter yields None
        fake_packet = {
            "recordStableKey": match_id,
            "tracks": []
        }

        host._finish({"terminationReason": "COMPLETE", "packetAvailable": False}, packet=fake_packet)

        rec_after = self.store.get_record(match_id)
        self.assertEqual(rec_before, rec_after)
        self.assertNotIn("warehouseOccupancy", rec_after.get("settlement", {}))

    def test_repeated_completion_no_duplicates_idempotent(self):
        """7. Repeated completion for same capture -> no duplicate records, idempotent update (AC3, AC8)"""
        match_id = "match_repeat_001"
        self._create_initial_draft(match_id)

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        fake_packet = {
            "recordStableKey": match_id,
            "tracks": [
                {"trackId": "trk_rep_1", "geometryEvidenceStatus": "EXACT", "widthCandidates": [2], "heightCandidates": [2]}
            ]
        }

        # Completion 1
        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet=fake_packet)
        # Completion 2
        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet=fake_packet)

        db_data = self.store.read_database()
        self.assertEqual(len(db_data.get("records", [])), 1)
        rec = self.store.get_record(match_id)
        self.assertEqual(len(rec["settlement"]["warehouseOccupancy"]["tracks"]), 1)

    def test_canonical_occupancy_preserved_byte_for_byte(self):
        """8. Phase 12 canonical occupancy content preserved byte-for-byte in persisted record (AC2, AC8)"""
        match_id = "match_byte_check_001"
        self._create_initial_draft(match_id)

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        fake_packet = {
            "recordStableKey": match_id,
            "tracks": [
                {"trackId": "t1", "geometryEvidenceStatus": "EXACT", "widthCandidates": [2], "heightCandidates": [1]},
                {"trackId": "t2", "geometryEvidenceStatus": "EXACT", "widthCandidates": [1, 2], "heightCandidates": [1]},
                {"trackId": "t3", "geometryEvidenceStatus": "PIXEL_ONLY", "widthCandidates": [1], "heightCandidates": [1]},
            ]
        }

        host._finish({"terminationReason": "COMPLETE", "packetAvailable": True}, packet=fake_packet)

        rec = self.store.get_record(match_id)
        occ = rec["settlement"]["warehouseOccupancy"]

        self.assertEqual(occ["tracks"][0]["trackId"], "t1")
        self.assertEqual(occ["tracks"][0]["geometryStatus"], "RESOLVED")
        self.assertEqual(occ["tracks"][0]["width"], 2)
        self.assertEqual(occ["tracks"][0]["height"], 1)

        self.assertEqual(occ["tracks"][1]["trackId"], "t2")
        self.assertEqual(occ["tracks"][1]["geometryStatus"], "AMBIGUOUS")
        self.assertIsNone(occ["tracks"][1]["width"])

        self.assertEqual(occ["tracks"][2]["trackId"], "t3")
        self.assertEqual(occ["tracks"][2]["geometryStatus"], "UNKNOWN")
        self.assertIsNone(occ["tracks"][2]["width"])

        # Also verify previous warehouse.slots remain intact
        self.assertEqual(rec["warehouse"]["slots"][0]["identifiedName"], "ItemA")


if __name__ == "__main__":
    unittest.main()
