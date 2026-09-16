# -*- coding: utf-8 -*-
"""Regression tests for Quality Sell Selection Triplet (bundle) semantics:
- S1: incoming lacks all 3 keys -> prior EXACT
- S2: incoming has real evidence -> incoming updates normally
- S3: prior has real evidence, incoming only has acquired=False default -> prior EXACT
- New record acquired=True / acquired=False/None -> full consistent 3-tuples
- Contradictory aggregate / sources -> validator FAIL
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
TESTS_DIR = PROJECT_ROOT / "tests"

for p in (str(PROJECT_ROOT), str(APP_DIR), str(CORE_DIR), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from auto_archiver import AutoArchiver
from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import (
    build_canonical_match_record_v7,
    validate_canonical_match_record_v7,
)
from quality_sell_selection import (
    CANONICAL_QUALITIES,
    DEFAULT_SELF_ACQUIRED_SELECTION,
    DEFAULT_UNKNOWN_SELECTION,
    SOURCE_DEFAULT_SELF_ACQUIRED,
    SOURCE_MANUAL_OVERRIDE,
    SOURCE_UNKNOWN,
    SOURCE_VISUAL_OBSERVED,
    aggregate_selection_source,
    has_concrete_quality_sell_evidence,
    merge_quality_sell_sidecar_bundle,
    normalize_quality_sell_selection,
    normalize_quality_sell_selection_sources,
)


class TestQualitySellBundleTriplet(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_qs_bundle_")
        self.db_path = Path(self.temp_dir) / "异环拍卖数据.json"
        self.store = CanonicalHistoryStore(self.db_path)
        self.archiver = AutoArchiver(db_paths=[str(self.db_path)])

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_builder_acquired_true_generates_full_bundle(self):
        """New record with acquired=True generates complete consistent 3-tuple."""
        rec = build_canonical_match_record_v7(
            match_id="test_new_acq_true",
            played_at="2026-09-16T14:00:00+08:00",
            lifecycle_status="DRAFT",
            source="test",
            settlement={"acquired": True},
        )
        st = rec["settlement"]
        self.assertIn("qualitySellSelection", st)
        self.assertIn("qualitySellSelectionSources", st)
        self.assertIn("qualitySellSelectionSource", st)

        # 5 selected, red unselected
        for q in ("white", "green", "blue", "purple", "gold"):
            self.assertEqual(st["qualitySellSelection"][q], "selected")
        self.assertEqual(st["qualitySellSelection"]["red"], "unselected")

        # All 6 sources default_self_acquired
        for q in CANONICAL_QUALITIES:
            self.assertEqual(st["qualitySellSelectionSources"][q], SOURCE_DEFAULT_SELF_ACQUIRED)

        # Aggregate is default_self_acquired
        self.assertEqual(st["qualitySellSelectionSource"], SOURCE_DEFAULT_SELF_ACQUIRED)

        ok, reasons = validate_canonical_match_record_v7(rec)
        self.assertTrue(ok, f"Validation failed: {reasons}")

    def test_builder_acquired_false_none_generates_full_bundle(self):
        """New record with acquired=False or None generates all-unknown consistent 3-tuple."""
        for acq_val in (False, None):
            with self.subTest(acquired=acq_val):
                rec = build_canonical_match_record_v7(
                    match_id=f"test_new_acq_{acq_val}",
                    played_at="2026-09-16T14:00:00+08:00",
                    lifecycle_status="DRAFT",
                    source="test",
                    settlement={"acquired": acq_val},
                )
                st = rec["settlement"]
                self.assertIn("qualitySellSelection", st)
                self.assertIn("qualitySellSelectionSources", st)
                self.assertIn("qualitySellSelectionSource", st)

                # All 6 unknown
                for q in CANONICAL_QUALITIES:
                    self.assertEqual(st["qualitySellSelection"][q], "unknown")
                    self.assertEqual(st["qualitySellSelectionSources"][q], SOURCE_UNKNOWN)
                self.assertEqual(st["qualitySellSelectionSource"], SOURCE_UNKNOWN)

                ok, reasons = validate_canonical_match_record_v7(rec)
                self.assertTrue(ok, f"Validation failed: {reasons}")

    def test_validator_contradictory_aggregate_and_sources_fails(self):
        """Validator fails-closed when aggregate source contradicts per-color sources."""
        sources = {
            "white": SOURCE_DEFAULT_SELF_ACQUIRED,
            "green": SOURCE_MANUAL_OVERRIDE,  # manual override present
            "blue": SOURCE_VISUAL_OBSERVED,
            "purple": SOURCE_VISUAL_OBSERVED,
            "gold": SOURCE_DEFAULT_SELF_ACQUIRED,
            "red": SOURCE_DEFAULT_SELF_ACQUIRED,
        }
        rec = build_canonical_match_record_v7(
            match_id="test_contradiction",
            played_at="2026-09-16T14:00:00+08:00",
            lifecycle_status="DRAFT",
            source="test",
            settlement={
                "acquired": True,
                "qualitySellSelectionSources": sources,
                # Force contradictory aggregate source:
                "qualitySellSelectionSource": "unknown",
            },
        )
        # Directly overwrite to simulate corrupted or contradictory payload
        rec["settlement"]["qualitySellSelectionSource"] = "unknown"
        rec["settlement"]["qualitySellSelectionSources"] = sources

        ok, reasons = validate_canonical_match_record_v7(rec)
        self.assertFalse(ok, "Validator should fail on contradictory aggregate source")
        self.assertIn("SETTLEMENT_QUALITY_SELL_SELECTION_SOURCE_MISMATCH", reasons)

    def test_validator_incomplete_sources_fails(self):
        """Validator fails when sources dict is missing canonical colors."""
        sources = {
            "white": SOURCE_DEFAULT_SELF_ACQUIRED,
            "green": SOURCE_DEFAULT_SELF_ACQUIRED,
            # Missing blue, purple, gold, red
        }
        rec = build_canonical_match_record_v7(
            match_id="test_incomplete_src",
            played_at="2026-09-16T14:00:00+08:00",
            lifecycle_status="DRAFT",
            source="test",
            settlement={"acquired": True},
        )
        rec["settlement"]["qualitySellSelectionSources"] = sources
        rec["settlement"]["qualitySellSelectionSource"] = SOURCE_DEFAULT_SELF_ACQUIRED

        ok, reasons = validate_canonical_match_record_v7(rec)
        self.assertFalse(ok)
        self.assertIn("SETTLEMENT_QUALITY_SELL_SELECTION_SOURCES_INCOMPLETE", reasons)

    def test_sidecar_merge_s1_incoming_lacks_keys_preserves_prior_exact(self):
        """S1: incoming lacks all quality-sell keys; prior has full bundle -> prior EXACT."""
        prior_sel = {"white": "selected", "green": "unselected", "blue": "selected", "purple": "unselected", "gold": "selected", "red": "unselected"}
        prior_src = {"white": SOURCE_DEFAULT_SELF_ACQUIRED, "green": SOURCE_MANUAL_OVERRIDE, "blue": SOURCE_VISUAL_OBSERVED, "purple": SOURCE_VISUAL_OBSERVED, "gold": SOURCE_DEFAULT_SELF_ACQUIRED, "red": SOURCE_DEFAULT_SELF_ACQUIRED}
        prior_agg = SOURCE_MANUAL_OVERRIDE

        # Write frame 1 (DRAFT)
        rec1 = build_canonical_match_record_v7(
            match_id="match_s1",
            played_at="2026-09-16T14:00:00+08:00",
            lifecycle_status="DRAFT",
            source="test",
            settlement={
                "acquired": True,
                "qualitySellSelection": prior_sel,
                "qualitySellSelectionSources": prior_src,
                "qualitySellSelectionSource": prior_agg,
            },
        )
        self.store.persist_record_transactional(rec1, is_finalized=False)

        # Frame 2: incoming payload has NO quality-sell keys
        rec2_payload = {
            "id": "match_s1",
            "lifecycleStatus": "DRAFT",
            "source": "test",
            "settlement": {
                "clearingPrice": 100000,
                "actualTotal": 200000,
            }
        }
        self.store.persist_record_transactional(rec2_payload, is_finalized=False, preserve_archive_sidecars=True)

        disk_rec = next(r for r in self.store.read_database().get("records", []) if r["id"] == "match_s1")
        st = disk_rec["settlement"]
        self.assertEqual(st["qualitySellSelection"], prior_sel)
        self.assertEqual(st["qualitySellSelectionSources"], prior_src)
        self.assertEqual(st["qualitySellSelectionSource"], prior_agg)

    def test_sidecar_merge_s2_incoming_has_real_evidence_updates_normally(self):
        """S2: incoming has real visual evidence -> incoming updates normally."""
        prior_sel = {"white": "selected", "green": "unselected", "blue": "selected", "purple": "unselected", "gold": "selected", "red": "unselected"}
        prior_src = {"white": SOURCE_DEFAULT_SELF_ACQUIRED, "green": SOURCE_MANUAL_OVERRIDE, "blue": SOURCE_VISUAL_OBSERVED, "purple": SOURCE_VISUAL_OBSERVED, "gold": SOURCE_DEFAULT_SELF_ACQUIRED, "red": SOURCE_DEFAULT_SELF_ACQUIRED}
        prior_agg = SOURCE_MANUAL_OVERRIDE

        # Frame 1
        rec1 = build_canonical_match_record_v7(
            match_id="match_s2",
            played_at="2026-09-16T14:00:00+08:00",
            lifecycle_status="DRAFT",
            source="test",
            settlement={
                "acquired": True,
                "qualitySellSelection": prior_sel,
                "qualitySellSelectionSources": prior_src,
                "qualitySellSelectionSource": prior_agg,
            },
        )
        self.store.persist_record_transactional(rec1, is_finalized=False)

        # Frame 2: incoming has new real visual evidence
        new_sel = {"white": "unselected", "green": "selected", "blue": "unselected", "purple": "selected", "gold": "unselected", "red": "selected"}
        new_src = {q: SOURCE_VISUAL_OBSERVED for q in CANONICAL_QUALITIES}
        new_agg = SOURCE_VISUAL_OBSERVED

        rec2 = build_canonical_match_record_v7(
            match_id="match_s2",
            played_at="2026-09-16T14:00:00+08:00",
            lifecycle_status="FINALIZED",
            source="test",
            environment={
                "venueTier": "zhongji",
                "venue": "shanhu",
                "box": "实木宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
            },
            settlement={
                "status": "verified",
                "verified": True,
                "acquired": True,
                "winner": "玩家本人",
                "clearingPrice": 100000,
                "actualTotal": 200000,
                "realizedProfit": 100000,
                "qualitySellSelection": new_sel,
                "qualitySellSelectionSources": new_src,
                "qualitySellSelectionSource": new_agg,
            },
        )
        self.store.persist_record_transactional(rec2, is_finalized=True, preserve_archive_sidecars=True)

        disk_rec = next(r for r in self.store.read_database().get("records", []) if r["id"] == "match_s2")
        st = disk_rec["settlement"]
        self.assertEqual(st["qualitySellSelection"], new_sel)
        self.assertEqual(st["qualitySellSelectionSources"], new_src)
        self.assertEqual(st["qualitySellSelectionSource"], new_agg)

    def test_sidecar_merge_s3_prior_has_evidence_incoming_derived_unknown_preserves_prior_exact(self):
        """S3: prior has mixed evidence; incoming only has acquired=False derived unknown -> prior EXACT."""
        prior_sel = {"white": "selected", "green": "unselected", "blue": "selected", "purple": "unselected", "gold": "selected", "red": "unselected"}
        prior_src = {
            "white": SOURCE_DEFAULT_SELF_ACQUIRED,
            "green": SOURCE_MANUAL_OVERRIDE,  # manual fact
            "blue": SOURCE_VISUAL_OBSERVED,   # visual fact
            "purple": SOURCE_VISUAL_OBSERVED, # visual fact
            "gold": SOURCE_DEFAULT_SELF_ACQUIRED,
            "red": SOURCE_DEFAULT_SELF_ACQUIRED,
        }
        prior_agg = SOURCE_MANUAL_OVERRIDE

        # Frame 1: DRAFT with prior mixed evidence
        rec1 = build_canonical_match_record_v7(
            match_id="match_s3",
            played_at="2026-09-16T14:00:00+08:00",
            lifecycle_status="DRAFT",
            source="test",
            settlement={
                "acquired": True,
                "qualitySellSelection": prior_sel,
                "qualitySellSelectionSources": prior_src,
                "qualitySellSelectionSource": prior_agg,
            },
        )
        self.store.persist_record_transactional(rec1, is_finalized=False)

        # Frame 2: opponent won (acquired=False), no visual panel evidence -> derived unknown
        ctx2 = {
            "id": "match_s3",
            "matchId": "match_s3",
            "winner": "对手A",
            "clearingPrice": 150000,
            "actualTotal": 300000,
            "profit": -5000, "settlementReady": True,
            "venue": "珊瑚场",
            "box": "实木宝箱",
            "boxType": "实木宝箱",
            "fieldCondition": "standard",
            "settlementData": {
                "isSettlement": True, "settlementReady": True,
                "winner": "对手A",
                "acquired": False,
                "clearingPrice": 150000,
                "actualTotal": 300000,
                "profit": -5000, "settlementReady": True,
                "items": [],
            },
            # No quality_sell provided in ctx2
        }
        self.archiver.archive_match(ctx2)

        disk_rec = next(r for r in self.store.read_database().get("records", []) if r["id"] == "match_s3")
        st = disk_rec["settlement"]
        self.assertEqual(disk_rec["lifecycleStatus"], "FINALIZED")
        # Rule check: prior's ENTIRE bundle is preserved intact!
        self.assertEqual(st["qualitySellSelection"], prior_sel, "Selection must be preserved from prior")
        self.assertEqual(st["qualitySellSelectionSources"], prior_src, "Sources must be preserved from prior")
        self.assertEqual(st["qualitySellSelectionSource"], prior_agg, "Aggregate source must be preserved from prior")

        ok, reasons = validate_canonical_match_record_v7(disk_rec)
        self.assertTrue(ok, f"Finalized record must be valid: {reasons}")


if __name__ == "__main__":
    unittest.main()



