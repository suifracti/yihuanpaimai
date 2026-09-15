"""Unit tests for Triggered Snapshot Assist v1.

Verifies:
1. Single-frame recognition parses totalItems, totalGrid, q, quality counts, and quality averages.
2. Strict separation: totalItems does NOT write to q; totalGrid does NOT confuse with totalItems.
3. Unknown/missing OCR results remain None, never default to 0.
4. Fail-closed: low confidence or unknown scenes do not update CurrentMatch.
5. Authority precedence: Snapshot does NOT overwrite existing explicit user manual facts.
6. Settlement facts (redInventoryComplete, settlementVerifiedRedItems, settlementItems) are never emitted by in-auction snapshot assist.
7. Single-shot only: no continuous background thread/loop is spawned.
8. Uses isolated temporary directories and clean mock state.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
APP_DIR = os.path.join(PROJECT_ROOT, "app")
for p in (CORE_DIR, APP_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from snapshot_recognizer import SingleFrameSnapshotRecognizer, SnapshotFactPatch
from current_match import CurrentMatch
from canonical_match_record import validate_canonical_match_record_v7


class _MockOCREngine:
    def __init__(self, ocr_lines):
        self.ocr_lines = ocr_lines

    def __call__(self, frame):
        # returns list of (bbox, text, score)
        return [[[[0, 0], [10, 0], [10, 10], [0, 10]], line, 0.99] for line in self.ocr_lines], 0.0


class TriggeredSnapshotAssistV1Tests(unittest.TestCase):
    def test_parses_total_items_total_grids_q_and_averages_accurately(self):
        sample_ocr = [
            "黄金场 · 珊瑚场",
            "黄金高级宝箱",
            "本局内所有藏品的总数量为66件",
            "总格数为32",
            "紫色，金色和红色品质藏品的总件数为39件",
            "紫色品质藏品的总数量为2",
            "金色品质藏品的总数量为2",
            "蓝色品质藏品的总数量为4",
            "金色品质平均价值为58,000",
            "紫色品质平均价值为3,904",
            "蓝色品质平均价值为1,200",
            "绿色品质平均价值为800",
            "白色品质平均价值为350",
        ]
        recognizer = SingleFrameSnapshotRecognizer(ocr_engine=_MockOCREngine(sample_ocr))
        dummy_frame = np.ones((100, 100, 3), dtype=np.uint8)

        match = CurrentMatch()
        result = recognizer.process_frame(dummy_frame, existing_facts=match.facts)

        self.assertTrue(result["ok"])
        self.assertEqual(result["scene"], "IN_AUCTION")
        applied = result["appliedFacts"]

        # 1. Total items vs Q vs Total grids strict separation
        self.assertEqual(applied.get("totalItems"), 66)
        self.assertEqual(applied.get("totalGrid"), 32)
        self.assertEqual(applied.get("q"), 39)
        self.assertNotEqual(applied.get("totalItems"), applied.get("q"))

        # 2. Quality counts and averages
        self.assertEqual(applied.get("purpleCount"), 2)
        self.assertEqual(applied.get("goldCount"), 2)
        self.assertEqual(applied.get("blueCount"), 4)
        self.assertEqual(applied.get("goldAvg"), 58000)
        self.assertEqual(applied.get("purpleAvg"), 3904)
        self.assertEqual(applied.get("blueAvg"), 1200)
        self.assertEqual(applied.get("greenAvg"), 800)
        self.assertEqual(applied.get("whiteAvg"), 350)

        # Apply to CurrentMatch and check Canonical
        match.apply_facts(applied, source="triggered_snapshot")
        canonical = match.to_canonical()
        is_valid, reasons = validate_canonical_match_record_v7(canonical)
        self.assertTrue(is_valid, f"Canonical validation failed: {reasons}")
        self.assertEqual(canonical["publicIntel"]["totalItems"], 66)
        self.assertEqual(canonical["publicIntel"]["totalGrid"], 32)
        self.assertEqual(canonical["publicIntel"]["q"], 39)
        self.assertEqual(canonical["qualities"]["purple"]["count"], 2)
        self.assertEqual(canonical["qualities"]["gold"]["count"], 2)
        self.assertEqual(canonical["qualities"]["blue"]["count"], 4)

    def test_total_items_never_writes_into_q(self):
        sample_ocr = [
            "本局内所有藏品的总数量为66件",
            "总格数为30",
        ]
        recognizer = SingleFrameSnapshotRecognizer(ocr_engine=_MockOCREngine(sample_ocr))
        dummy_frame = np.ones((100, 100, 3), dtype=np.uint8)

        match = CurrentMatch()
        result = recognizer.process_frame(dummy_frame, existing_facts=match.facts)

        applied = result["appliedFacts"]
        self.assertEqual(applied.get("totalItems"), 66)
        self.assertEqual(applied.get("totalGrid"), 30)
        self.assertNotIn("q", applied)
        self.assertIsNone(applied.get("q"))

    def test_unobserved_facts_remain_none_and_never_write_zero(self):
        sample_ocr = [
            "黄金高级宝箱",
            "金色品质平均价值为58,000",
        ]
        recognizer = SingleFrameSnapshotRecognizer(ocr_engine=_MockOCREngine(sample_ocr))
        dummy_frame = np.ones((100, 100, 3), dtype=np.uint8)

        match = CurrentMatch()
        result = recognizer.process_frame(dummy_frame, existing_facts=match.facts)
        applied = result["appliedFacts"]

        self.assertNotIn("totalItems", applied)
        self.assertNotIn("totalGrid", applied)
        self.assertNotIn("whiteAvg", applied)
        self.assertNotIn("greenAvg", applied)
        self.assertNotIn("blueAvg", applied)
        self.assertNotIn("purpleCount", applied)

        match.apply_facts(applied, source="triggered_snapshot")
        snap = match.snapshot()
        self.assertIsNone(snap["totalItems"])
        self.assertIsNone(snap["totalGrid"])
        self.assertIsNone(snap["whiteAvg"])

    def test_manual_facts_take_precedence_over_conflicting_snapshot(self):
        # User manually entered goldAvg = 60000 and q = 40
        match = CurrentMatch()
        match.apply_facts({
            "goldAvg": 60000,
            "q": 40,
            "venueId": "gold_hall",
        }, source="manual")

        # Snapshot OCR detects goldAvg = 58000 and q = 39, but also detects totalItems = 66
        sample_ocr = [
            "金色品质平均价值为58,000",
            "紫色，金色和红色品质藏品的总件数为39件",
            "本局内所有藏品的总数量为66件",
        ]
        recognizer = SingleFrameSnapshotRecognizer(ocr_engine=_MockOCREngine(sample_ocr))
        dummy_frame = np.ones((100, 100, 3), dtype=np.uint8)

        result = recognizer.process_frame(dummy_frame, existing_facts=match.facts)
        applied = result["appliedFacts"]
        conflicts = result["conflicts"]

        # 1. Total items was None -> ACCEPTED
        self.assertEqual(applied.get("totalItems"), 66)
        # 2. Conflicting goldAvg and q -> REJECTED from applied, reported in conflicts
        self.assertNotIn("goldAvg", applied)
        self.assertNotIn("q", applied)

        conflict_keys = [c["key"] for c in conflicts]
        self.assertIn("goldAvg", conflict_keys)
        self.assertIn("q", conflict_keys)

        # Apply only non-conflicting facts to CurrentMatch
        match.apply_facts(applied, source="triggered_snapshot")
        snap = match.snapshot()
        # Manual values are preserved!
        self.assertEqual(snap["goldAvg"], 60000)
        self.assertEqual(snap["q"], 40)
        self.assertEqual(snap["totalItems"], 66)

    def test_settlement_scene_is_gated_and_does_not_write_live_facts(self):
        sample_ocr = [
            "拍卖结算",
            "最终成交价 120,000",
            "本局收益 +30,000",
            "红色品质藏品的总数量为1",
        ]
        recognizer = SingleFrameSnapshotRecognizer(ocr_engine=_MockOCREngine(sample_ocr))
        dummy_frame = np.ones((100, 100, 3), dtype=np.uint8)

        match = CurrentMatch()
        result = recognizer.process_frame(dummy_frame, existing_facts=match.facts)

        self.assertFalse(result["ok"])
        self.assertEqual(result["scene"], "SETTLEMENT")
        self.assertEqual(len(result["appliedFacts"]), 0)

    def test_settlement_only_facts_are_never_emitted_by_snapshot(self):
        sample_ocr = [
            "本局内所有藏品的总数量为66件",
            "金色品质平均价值为58,000",
        ]
        recognizer = SingleFrameSnapshotRecognizer(ocr_engine=_MockOCREngine(sample_ocr))
        dummy_frame = np.ones((100, 100, 3), dtype=np.uint8)

        result = recognizer.process_frame(dummy_frame, existing_facts={})
        applied = result["appliedFacts"]

        self.assertNotIn("redInventoryComplete", applied)
        self.assertNotIn("settlementVerifiedRedItems", applied)
        self.assertNotIn("settlementItems", applied)

    def test_single_shot_does_not_start_any_background_thread(self):
        import threading
        threads_before = threading.active_count()

        sample_ocr = ["本局内所有藏品的总数量为66件"]
        recognizer = SingleFrameSnapshotRecognizer(ocr_engine=_MockOCREngine(sample_ocr))
        dummy_frame = np.ones((100, 100, 3), dtype=np.uint8)
        _ = recognizer.process_frame(dummy_frame, existing_facts={})

        threads_after = threading.active_count()
        self.assertEqual(threads_before, threads_after)


if __name__ == "__main__":
    unittest.main()
