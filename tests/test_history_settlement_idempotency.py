import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "core", _ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from canonical_history_store import CanonicalHistoryStore, HistoryStoreError, FinalizedRecordConflictError
from canonical_match_record import build_canonical_match_record_v7
from manual_terminal import ManualTerminalCoordinator


class TestHistorySettlementIdempotency(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "异环拍卖数据.json"
        self.store = CanonicalHistoryStore(self.db_path)
        self.coordinator = ManualTerminalCoordinator(self.db_path)
        self.match_id = "draft_test_match_unique_001"

        self.base_draft = build_canonical_match_record_v7(
            match_id=self.match_id,
            played_at="2026-09-14T13:07:26+08:00",
            lifecycle_status="DRAFT",
            source="vision-auto-archiver",
            environment={
                "venueTier": "zhongji",
                "venue": "珊瑚",
                "box": "皮制宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
            },
            settlement={
                "status": "pending",
                "verified": False,
                "clearingPrice": 666999.0,
                "actualTotal": 651142.0,
                "realizedProfit": -15857.0,
                "acquired": False,
                "winner": "AsunaDaisuki",
                "settlementWinnerName": "AsunaDaisuki",
                "settlementAuctionAssistantName": "小哎",
                "auctionAssistant": "小哎",
                "isSelfWinner": False,
                "settlementItems": [],
            },
        )

        self.finalized_record = build_canonical_match_record_v7(
            match_id=self.match_id,
            played_at="2026-09-14T13:07:26+08:00",
            lifecycle_status="FINALIZED",
            source="vision-auto-archiver",
            environment={
                "venueTier": "zhongji",
                "venue": "珊瑚",
                "box": "皮制宝箱",
                "boxType": "wood",
                "fieldCondition": "standard",
            },
            settlement={
                "status": "verified",
                "verified": True,
                "clearingPrice": 666999.0,
                "actualTotal": 651142.0,
                "realizedProfit": -15857.0,
                "acquired": False,
                "winner": "AsunaDaisuki",
                "settlementWinnerName": "AsunaDaisuki",
                "settlementAuctionAssistantName": "小哎",
                "auctionAssistant": "小哎",
                "isSelfWinner": False,
                "settlementItems": [],
            },
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_scenario_a_auto_finalize_then_user_confirm(self):
        """Scenario A: Auto-archiver finalizes match, user subsequently confirms in settlement modal."""
        # 1. Auto-finalize persists finalized record
        saved = self.store.persist_record_transactional(self.finalized_record, is_finalized=True)
        self.assertEqual(saved["lifecycleStatus"], "FINALIZED")
        self.assertEqual(len(self.store.read_database()["records"]), 1)

        # 2. User confirms via manual terminal coordinator
        settlement_input = {
            "clearingPrice": 666999.0,
            "actualTotal": 651142.0,
            "acquired": False,
            "winner": "AsunaDaisuki",
            "realizedProfit": -15857.0,
        }
        res = self.coordinator.finalize(self.base_draft, settlement_input)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "FINALIZED")

        # Database must still have exactly 1 record
        records = self.store.read_database()["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], self.match_id)
        self.assertEqual(records[0]["lifecycleStatus"], "FINALIZED")

    def test_scenario_b_double_click_confirm_idempotency(self):
        """Scenario B: User double-clicks confirm; exactly 1 record persists."""
        settlement_input = {
            "clearingPrice": 666999.0,
            "actualTotal": 651142.0,
            "acquired": False,
            "winner": "AsunaDaisuki",
            "realizedProfit": -15857.0,
        }
        res1 = self.coordinator.finalize(self.base_draft, settlement_input)
        self.assertTrue(res1["ok"])

        res2 = self.coordinator.finalize(self.base_draft, settlement_input)
        self.assertTrue(res2["ok"])

        records = self.store.read_database()["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["lifecycleStatus"], "FINALIZED")

    def test_scenario_c_late_evidence_enrichment(self):
        """Scenario C: Late evidence arrival on finalized record enriches without duplicating or altering facts."""
        self.store.persist_record_transactional(self.finalized_record, is_finalized=True)

        evidence_entry = {
            "evidenceId": "sev2_late_001",
            "kind": "manual-settlement",
            "capturedAt": "2026-09-14T13:07:35+08:00",
            "relativePath": "evidence/settlement_v2/blobs/1e/1eeed15c.png",
            "sha256": "1eeed15c" * 8,
            "width": 1920,
            "height": 1080,
        }
        enriched = self.store.append_finalized_evidence(self.match_id, evidence_entry=evidence_entry)
        self.assertEqual(enriched["lifecycleStatus"], "FINALIZED")

        records = self.store.read_database()["records"]
        self.assertEqual(len(records), 1)
        st = records[0]["settlement"]
        self.assertEqual(st["clearingPrice"], 666999.0)
        self.assertEqual(st["actualTotal"], 651142.0)
        self.assertEqual(st["winner"], "AsunaDaisuki")
        self.assertEqual(st["pageCount"], 1)

    def test_scenario_d_review_enrichment_preserves_immutable_facts(self):
        """Scenario D: Identity review sidecar enrichment updates metadata without tampering core prices."""
        self.store.persist_record_transactional(self.finalized_record, is_finalized=True)

        review_update = {
            "reviewedItems": [{"name": "万有星仪", "count": 1}],
            "reviewedAt": "2026-09-14T13:15:00+08:00",
            "reviewProvenance": "MANUAL_HUMAN",
        }
        enriched = self.store.append_finalized_evidence(self.match_id, review_update=review_update)
        self.assertEqual(enriched["settlement"]["reviewedItems"], [{"name": "万有星仪", "count": 1}])

        # Core fields must remain identical
        st = enriched["settlement"]
        self.assertEqual(st["clearingPrice"], 666999.0)
        self.assertEqual(st["actualTotal"], 651142.0)
        self.assertEqual(st["realizedProfit"], -15857.0)
        self.assertEqual(st["winner"], "AsunaDaisuki")

    def test_scenario_e_defensive_deduplication_on_read(self):
        """Scenario E: Defensive deduplication by physical match identity across restarts/re-reads."""
        # Create database file containing both DRAFT and FINALIZED with same matchId/recordStableKey
        raw_db = {
            "version": "v0.6",
            "schemaVersion": 7,
            "records": [
                copy.deepcopy(self.base_draft),
                copy.deepcopy(self.finalized_record),
            ]
        }
        import json
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(raw_db, f)

        # Read database: must defensively collapse into 1 FINALIZED record
        read_back = self.store.read_database()
        self.assertEqual(len(read_back["records"]), 1)
        self.assertEqual(read_back["records"][0]["lifecycleStatus"], "FINALIZED")

    def test_scenario_f_keep_draft_on_finalized_match(self):
        """Scenario F: keep_draft on already finalized match returns ALREADY_FINALIZED and does not downgrade."""
        self.store.persist_record_transactional(self.finalized_record, is_finalized=True)
        res = self.coordinator.keep_draft(self.base_draft)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "ALREADY_FINALIZED")

        records = self.store.read_database()["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["lifecycleStatus"], "FINALIZED")

    def test_scenario_g_forbidden_field_mutation_on_finalized_record(self):
        """Scenario G: Mutating forbidden winner/price fields via enrichment fails closed."""
        self.store.persist_record_transactional(self.finalized_record, is_finalized=True)
        with self.assertRaises(HistoryStoreError):
            self.store.append_finalized_evidence(
                self.match_id,
                review_update={"settlementWinnerName": "FakeWinner"}
            )
        with self.assertRaises(HistoryStoreError):
            self.store.append_finalized_evidence(
                self.match_id,
                review_update={"clearingPrice": 123456}
            )


if __name__ == "__main__":
    unittest.main()
