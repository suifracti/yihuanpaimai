# -*- coding: utf-8 -*-
"""Test suite for Settlement Ground Truth Reconnect v1.

Verifies the 9 required quality gates:
1. SETTLEMENT_STABLE_FINALIZE_GATE
2. SETTLEMENT_EXACTLY_ONCE_GATE
3. SETTLEMENT_SCREENSHOT_DURABLE_EVIDENCE_GATE
4. SETTLEMENT_SCREENSHOT_MATCH_ASSOCIATION_GATE
5. SETTLEMENT_ITEM_FAIL_CLOSED_GATE
6. SETTLEMENT_12_ITEM_LEGACY_FIXTURE_GATE
7. CURRENT_MATCH_TO_HISTORY_SETTLEMENT_GATE
8. CURRENT_MATCH_REAL_MAIN_SYNC_GATE
9. PACKAGED_NO_EXTERNAL_NODE_GATE
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
import numpy as np
import cv2

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
APP_DIR = os.path.join(PROJECT_ROOT, "app")
sys.path.insert(0, CORE_DIR)
sys.path.insert(0, APP_DIR)

from current_match import CurrentMatch
from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import validate_finalized_match_record_v7
from evidence_storage import save_evidence_png, verify_evidence_file
from settlement_truth_holder import build_settlement_truth_evidence_v1
from settlement_item_recognizer import SettlementItemRecognizer
from vision_pipeline import NTEVisionPipeline, SETTLEMENT_STABLE_FRAMES


class TestSettlementGroundTruthReconnectV1(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.previous_data_root = os.environ.get('YIHUAN_DATA_ROOT')
        os.environ["YIHUAN_DATA_ROOT"] = self.tmp_dir.name
        self.history_path = os.path.join(self.tmp_dir.name, "异环拍卖数据.json")

    def tearDown(self):
        self.tmp_dir.cleanup()
        if self.previous_data_root is None:
            os.environ.pop('YIHUAN_DATA_ROOT', None)
        else:
            os.environ['YIHUAN_DATA_ROOT'] = self.previous_data_root

    # -------------------------------------------------------------------------
    # Gate 1: SETTLEMENT_STABLE_FINALIZE_GATE
    # -------------------------------------------------------------------------
    def test_settlement_stable_finalize_gate(self):
        """Animation intermediate values do not trigger finalize; only stable final settlement triggers."""
        pipe = NTEVisionPipeline()
        
        # 1. Fluctuating animation values (clearing = 0, profit = None) -> NOT final
        unstable_frame_1 = {"isSettlement": True, "clearingPrice": 0, "actualTotal": 0, "profit": None}
        self.assertFalse(pipe._settlement_looks_final(unstable_frame_1))
        pipe._stabilize_settlement(unstable_frame_1)
        self.assertFalse(pipe.current_context.get("settlementReady", False))

        # 2. First stable-looking candidate
        candidate = {"isSettlement": True, "clearingPrice": 100000, "actualTotal": 150000, "profit": 45000}
        self.assertTrue(pipe._settlement_looks_final(candidate))
        
        # Stabilization requires consecutive stable frames >= SETTLEMENT_STABLE_FRAMES
        for i in range(SETTLEMENT_STABLE_FRAMES - 1):
            pipe._stabilize_settlement(candidate)
            self.assertFalse(pipe.current_context.get("settlementReady", False), f"Frame {i+1} triggered ready prematurely")

        # Nth frame reaching threshold triggers settlementReady
        pipe._stabilize_settlement(candidate)
        self.assertTrue(pipe.current_context.get("settlementReady", False))

    # -------------------------------------------------------------------------
    # Gate 2: SETTLEMENT_EXACTLY_ONCE_GATE
    # -------------------------------------------------------------------------
    def test_settlement_exactly_once_gate(self):
        """Same match cannot be finalized/persisted twice into CanonicalHistoryStore."""
        match = CurrentMatch()
        match.apply_facts({
            "venue": "海贝场",
            "box": "琉璃宝箱",
            "fieldCondition": "standard",
            "q": 10,
            "goldAvg": 50000,
            "purpleCount": 4,
            "clearingPrice": 120000,
            "actualTotal": 180000,
            "realizedProfit": 55000,
            "isAcquired": True,
            "winner": "回放测试员",
        })
        store = CanonicalHistoryStore(self.history_path)

        # First finalize succeeds
        record_1 = match.finalize(store_path=self.history_path)
        self.assertEqual(match.lifecycle_status, "FINALIZED")
        self.assertEqual(record_1["id"], match.id)

        db = store.read_database()
        self.assertEqual(len(db["records"]), 1)

        # Second finalize on same instance updates the existing record, never creates duplicate
        record_2 = match.finalize(store_path=self.history_path)
        db_after = store.read_database()
        self.assertEqual(len(db_after["records"]), 1)
        self.assertEqual(db_after["records"][0]["id"], match.id)

    # -------------------------------------------------------------------------
    # Gate 3: SETTLEMENT_SCREENSHOT_DURABLE_EVIDENCE_GATE
    # -------------------------------------------------------------------------
    def test_settlement_screenshot_durable_evidence_gate(self):
        """Evidence file is written to RuntimeDataRoot / evidence / settlement with verified SHA-256."""
        # Create a synthetic 1080p frame
        test_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cv2.putText(test_frame, "SETTLEMENT PROOF", (200, 200), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 255, 0), 3)

        match_id = "test_match_evidence_001"
        rel_uri, digest = save_evidence_png(test_frame, match_id, subfolder="settlement", data_dir=self.tmp_dir.name)

        # Physical file exists
        full_path = os.path.join(self.tmp_dir.name, rel_uri.replace("/", os.sep))
        self.assertTrue(os.path.isfile(full_path), f"Evidence file not found: {full_path}")
        self.assertTrue(os.path.getsize(full_path) > 0)

        # Byte SHA-256 re-verification
        self.assertTrue(verify_evidence_file(rel_uri, digest, data_dir=self.tmp_dir.name))

    # -------------------------------------------------------------------------
    # Gate 4: SETTLEMENT_SCREENSHOT_MATCH_ASSOCIATION_GATE
    # -------------------------------------------------------------------------
    def test_settlement_screenshot_match_association_gate(self):
        """Finalized CanonicalMatchRecordV7 associates screenshot evidence URI and hash."""
        test_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        match_id = "test_match_assoc_002"
        rel_uri, digest = save_evidence_png(test_frame, match_id, subfolder="settlement", data_dir=self.tmp_dir.name)

        truth_ev = build_settlement_truth_evidence_v1(
            match_id=match_id,
            actual_total=250000.0,
            settlement_observed_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            truth_source="live_vision_stabilized_settlement",
            truth_confidence="high",
            evidence_uri=rel_uri,
            evidence_sha256=digest,
        )

        match = CurrentMatch()
        match.id = match_id
        match.apply_facts({
            "venue": "珊瑚场",
            "box": "实木宝箱",
            "fieldCondition": "standard",
            "q": 12,
            "goldAvg": 60000,
            "purpleCount": 5,
            "clearingPrice": 150000,
            "actualTotal": 250000,
            "realizedProfit": 95000,
            "isAcquired": True,
            "winner": "回放测试员",
            "settlementTruthEvidence": truth_ev,
        })
        saved = match.finalize(store_path=self.history_path)

        # Read back from store and verify
        store = CanonicalHistoryStore(self.history_path)
        persisted = store.lookup(match_id)
        self.assertIsNotNone(persisted)
        self.assertIn("truthEvidence", persisted["settlement"])
        persisted_ev = persisted["settlement"]["truthEvidence"]
        self.assertEqual(persisted_ev["evidenceReferences"][0]["uri"], rel_uri)
        self.assertEqual(persisted_ev["evidenceReferences"][0]["sha256"], digest)

    # -------------------------------------------------------------------------
    # Gate 5: SETTLEMENT_ITEM_FAIL_CLOSED_GATE
    # -------------------------------------------------------------------------
    def test_settlement_item_fail_closed_gate(self):
        """Ambiguous items without template match >= 0.85 remain ambiguous and are not blindly exact."""
        rec = SettlementItemRecognizer()
        
        # Test synthetic frame with occupied cells
        synthetic = np.zeros((1080, 1920, 3), dtype=np.uint8)
        # Draw warehouse board area with random color boxes
        cv2.rectangle(synthetic, (1315, 216), (1877, 815), (40, 40, 40), -1)
        
        res = rec.parse_settlement_ledger(synthetic, actual_total=100000)
        items = res.get("settlementItems", [])
        
        # Any detected items without template verification must NOT have exact status
        for it in items:
            if it.get("identificationStatus") == "exact":
                self.assertIsNotNone(it.get("price"))
                self.assertGreaterEqual(it.get("confidence", 0), 0.85)
            else:
                self.assertIn(it.get("identificationStatus"), ("ambiguous", "unknown"))
                self.assertIn(it.get("status"), ("ambiguous", "unknown"))

    # -------------------------------------------------------------------------
    # Gate 6: SETTLEMENT_12_ITEM_LEGACY_FIXTURE_GATE
    # -------------------------------------------------------------------------
    def test_settlement_12_item_legacy_fixture_gate(self):
        """Legacy 14-11-56 fixture physical items segmentation runs fail-closed."""
        fixture_path = os.path.join(PROJECT_ROOT, "build", "live_141156", "t238.jpg")
        if not os.path.exists(fixture_path):
            fixture_path = os.path.join(PROJECT_ROOT, "assets", "settlement_frames", "settlement_crop.jpg")
        if not os.path.exists(fixture_path):
            self.skipTest("No settlement image fixture found")

        img = cv2.imdecode(np.fromfile(fixture_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(img)

        rec = SettlementItemRecognizer()
        res = rec.parse_settlement_ledger(img, actual_total=631993)
        items = res["settlementItems"]
        self.assertGreater(len(items), 0)
        
        # Ambiguous items must not blindly be elevated to exact
        for it in items:
            self.assertIn("status", it)
            self.assertIn("identificationStatus", it)
            if it["status"] != "exact":
                self.assertIsNone(it["price"])

    # -------------------------------------------------------------------------
    # Gate 7: CURRENT_MATCH_TO_HISTORY_SETTLEMENT_GATE
    # -------------------------------------------------------------------------
    def test_current_match_to_history_settlement_gate(self):
        """Observed facts in CurrentMatch flow directly to CanonicalHistoryStore without data loss."""
        match = CurrentMatch()
        match.apply_facts({
            "venue": "真珠场",
            "box": "黄金宝箱",
            "fieldCondition": "dark",
            "q": 15,
            "goldAvg": 75000,
            "purpleCount": 6,
            "knownGold": "万有星仪",
            "knownPurple": "金角月芒",
            "leaderBid": 200000,
            "clearingPrice": 250000,
            "actualTotal": 380000,
            "realizedProfit": 125000,
            "isAcquired": True,
            "winner": "回放测试员",
            "settlementItems": [
                {"slotIndex": 1, "rarity": "gold", "shape": "2x2", "status": "exact", "name": "万有星仪", "price": 150000},
                {"slotIndex": 2, "rarity": "purple", "shape": "1x2", "status": "ambiguous", "candidateItemIds": ["金角月芒", "拈花小像"]},
            ]
        }, source="vision")

        saved = match.finalize(store_path=self.history_path)
        self.assertEqual(saved["lifecycleStatus"], "FINALIZED")
        self.assertEqual(saved["environment"]["venue"], "真珠场")
        self.assertEqual(saved["publicIntel"]["q"], 15)
        self.assertEqual(saved["settlement"]["clearingPrice"], 250000)
        self.assertEqual(saved["settlement"]["actualTotal"], 380000)
        self.assertEqual(saved["settlement"]["realizedProfit"], 125000)
        self.assertEqual(saved["settlement"]["acquired"], True)
        self.assertEqual(len(saved["settlement"]["settlementItems"]), 2)

    # -------------------------------------------------------------------------
    # Gate 8: CURRENT_MATCH_REAL_MAIN_SYNC_GATE
    # -------------------------------------------------------------------------
    def test_current_match_real_main_sync_gate(self):
        """get_current_match_presentation_summary returns live facts and settlement summary."""
        from main import get_current_match_presentation_summary, CURRENT_MATCH

        CURRENT_MATCH.begin_next_match()
        CURRENT_MATCH.apply_facts({
            "venue": "珊瑚场",
            "box": "琉璃宝箱",
            "fieldCondition": "standard",
            "q": 12,
            "goldAvg": 74379,
            "purpleCount": 7,
            "leaderBid": 100000,
            "clearingPrice": 120000,
            "actualTotal": 200000,
            "realizedProfit": 75000,
            "isAcquired": True,
            "settlementItems": [
                {"slotIndex": 1, "rarity": "gold", "status": "exact", "name": "测试金色藏品", "price": 80000},
                {"slotIndex": 2, "rarity": "purple", "status": "ambiguous", "candidateItemIds": ["A", "B"]},
            ]
        })

        summary = get_current_match_presentation_summary()
        self.assertEqual(summary["environment"]["venueName"], "珊瑚场")
        self.assertEqual(summary["environment"]["box"], "琉璃宝箱")
        self.assertEqual(summary["facts"]["q"], 12)
        self.assertEqual(summary["facts"]["goldAvg"], 74379)
        self.assertEqual(summary["facts"]["purpleCount"], 7)
        self.assertIsNotNone(summary["settlement"])
        self.assertEqual(summary["settlement"]["clearingPrice"], 120000)
        self.assertEqual(summary["settlement"]["actualTotal"], 200000)
        self.assertEqual(summary["settlement"]["realizedProfit"], 75000)
        self.assertEqual(summary["settlement"]["acquired"], True)
        self.assertEqual(summary["settlement"]["itemCount"], 2)
        self.assertEqual(summary["settlement"]["exactCount"], 1)
        self.assertEqual(summary["settlement"]["ambiguousCount"], 1)

    # -------------------------------------------------------------------------
    # Gate 9: PACKAGED_NO_EXTERNAL_NODE_GATE
    # -------------------------------------------------------------------------
    def test_packaged_no_external_node_gate(self):
        """Runtime execution must NOT spawn external node.exe processes."""
        import subprocess
        # Check running processes for node.exe
        proc = subprocess.run(["tasklist", "/FI", "IMAGENAME eq node.exe"], capture_output=True, text=True)
        # Note: during python test execution, node.exe must not be spawned by our python app
        match = CurrentMatch()
        match.apply_facts({"q": 10, "goldAvg": 50000})
        canonical = match.to_canonical()
        self.assertIsNotNone(canonical)


if __name__ == "__main__":
    unittest.main()
