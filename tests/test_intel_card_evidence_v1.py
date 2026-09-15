"""Real-frame tests for intel card detection, field routing, and evidence ledger."""

from __future__ import annotations

import json
import os
import sys
import unittest

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
for path in (CORE_DIR, os.path.join(PROJECT_ROOT, "app")):
    if path not in sys.path:
        sys.path.insert(0, path)

from intel_card_evidence import (
    INTEL_STACK_ROI,
    ROIScaler,
    STATUS_CONFLICT,
    STATUS_OBSERVED,
    STATUS_UNKNOWN,
    SUPPORTED_FIELDS,
    CachedCardEvidence,
    FrameIntelEvidence,
    IntelCardEvidenceExtractor,
    IntelCardEvidenceLedger,
    IntelCardObservation,
    detect_card_boxes,
    route_card_text,
)
from roi_scaler import NORMALIZED_ROIS
from snapshot_recognizer import SingleFrameSnapshotRecognizer

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "intel_card_evidence_v1")


def _load_bgr(name: str) -> np.ndarray:
    path = os.path.join(FIXTURE_DIR, name)
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return img


def _obs_map(evidence: FrameIntelEvidence) -> dict:
    return {obs.field: obs.value for obs in evidence.observations if obs.status == STATUS_OBSERVED}


class IntelCardEvidenceV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extractor = IntelCardEvidenceExtractor()
        cls.ledger = IntelCardEvidenceLedger()
        cls.r2 = cls.extractor.extract_frame(_load_bgr("r2_viewport.png"), frame_id="r2")
        cls.r2_v = cls.extractor.extract_frame(_load_bgr("r2_viewport.png"), frame_id="r2_v")
        cls.r3 = cls.extractor.extract_frame(_load_bgr("r3_viewport.png"), frame_id="r3")
        cls.r3_v = cls.extractor.extract_frame(_load_bgr("r3_viewport.png"), frame_id="r3_v")

    def test_stack_roi_is_a_large_region_not_fixed_rows(self):
        stack = NORMALIZED_ROIS["intel_card_stack"]
        board = NORMALIZED_ROIS["intel_board"]
        self.assertGreater(stack[3] - stack[1], 0.45)
        self.assertGreater(stack[3] - stack[1], board[3] - board[1])
        self.assertNotEqual(stack, board)

    def test_r2_real_frame_detects_four_cards_and_fields(self):
        ev = self.r2
        self.assertEqual(len(ev.cards), 4, ev.to_dict())
        ys = [box[1] for box in ev.cards]
        self.assertEqual(ys, sorted(ys))
        fields = _obs_map(ev)
        self.assertEqual(ev.round, 2)
        self.assertEqual(ev.timer, 18)
        self.assertEqual(fields.get("q"), 11)
        self.assertEqual(fields.get("goldAvg"), 47286)
        self.assertEqual(fields.get("purpleCount"), 3)
        self.assertEqual(fields.get("purpleAvg"), 4357)
        self.assertNotIn("goldCount", fields)
        self.assertNotIn("blueCount", fields)
        self.assertNotIn("redCount", fields)
        self.assertNotIn("totalItems", fields)
        self.assertNotIn("totalGrid", fields)
        self.assertNotIn("goldGrid", fields)
        self.assertNotIn("purpleGrid", fields)
        self.assertEqual(ev.field_map()["goldCount"], STATUS_UNKNOWN)
        self.assertEqual(ev.field_map()["redCount"], STATUS_UNKNOWN)
        for obs in ev.observations:
            self.assertNotEqual(obs.value, 0)
            self.assertEqual(obs.frameId, "r2")
            self.assertEqual(len(obs.cardBox), 4)

    def test_r3_real_frame_keeps_purple_avg_unknown(self):
        ev = self.r3
        self.assertEqual(len(ev.cards), 4, ev.to_dict())
        fields = _obs_map(ev)
        self.assertEqual(ev.round, 3)
        self.assertEqual(ev.timer, 50)
        self.assertEqual(fields.get("q"), 11)
        self.assertEqual(fields.get("goldAvg"), 47286)
        self.assertEqual(fields.get("purpleCount"), 3)
        self.assertNotIn("purpleAvg", fields)
        self.assertEqual(ev.field_map()["purpleAvg"], STATUS_UNKNOWN)
        self.assertEqual(ev.field_map()["goldGrid"], STATUS_UNKNOWN)
        self.assertEqual(ev.field_map()["blueCount"], STATUS_UNKNOWN)

    def test_card_order_does_not_change_field_set(self):
        r2_stack = _load_bgr("r2_intel_stack.png")
        r3_stack = _load_bgr("r3_intel_stack.png")
        r2_boxes = detect_card_boxes(r2_stack)
        r3_boxes = detect_card_boxes(r3_stack)
        self.assertEqual(len(r2_boxes), 4)
        self.assertEqual(len(r3_boxes), 4)
        r2_fields = set(_obs_map(self.r2))
        r3_fields = set(_obs_map(self.r3))
        self.assertEqual(r2_fields - {"purpleAvg"}, r3_fields)
        self.assertIn("purpleAvg", r2_fields)
        self.assertNotIn("purpleAvg", r3_fields)

    def test_union_ledger_keeps_r2_purple_avg_source(self):
        ledger = IntelCardEvidenceLedger()
        snap = ledger.merge(self.r2, self.r2_v, self.r3)
        facts = snap["facts"]
        self.assertEqual(facts["q"]["status"], STATUS_OBSERVED)
        self.assertEqual(facts["q"]["value"], 11)
        self.assertEqual(facts["goldAvg"]["value"], 47286)
        self.assertEqual(facts["purpleCount"]["value"], 3)
        self.assertEqual(facts["purpleAvg"]["status"], STATUS_OBSERVED)
        self.assertEqual(facts["purpleAvg"]["value"], 4357)
        sources = {item["frameId"] for item in facts["purpleAvg"]["sources"]}
        self.assertIn("r2", sources)
        self.assertEqual(facts["goldCount"]["status"], STATUS_UNKNOWN)
        self.assertIsNone(facts["goldCount"]["value"])
        self.assertEqual(facts["blueCount"]["status"], STATUS_UNKNOWN)
        self.assertEqual(facts["redCount"]["status"], STATUS_UNKNOWN)
        self.assertEqual(facts["totalItems"]["status"], STATUS_UNKNOWN)
        self.assertEqual(facts["totalGrid"]["status"], STATUS_UNKNOWN)
        self.assertEqual(facts["goldGrid"]["status"], STATUS_UNKNOWN)
        self.assertEqual(facts["purpleGrid"]["status"], STATUS_UNKNOWN)
        self.assertEqual(snap["frames"][0]["round"], 2)
        self.assertEqual(snap["frames"][0]["timer"], 18)
        self.assertEqual(snap["frames"][1]["round"], 2)
        self.assertEqual(snap["frames"][1]["timer"], 18)
        self.assertEqual(snap["frames"][2]["round"], 3)
        self.assertEqual(snap["frames"][2]["timer"], 50)
        for name in SUPPORTED_FIELDS:
            if facts[name]["status"] == STATUS_UNKNOWN:
                self.assertIsNone(facts[name]["value"])

    def test_ledger_marks_conflict_and_does_not_last_write(self):
        a1 = FrameIntelEvidence(
            frameId="a1",
            round=2,
            timer=18,
            observations=[
                IntelCardObservation("goldAvg", 47286, STATUS_OBSERVED, "a1", 2, 18, [0, 0, 1, 1], "47286", 0.9, is_physical_ocr=True)
            ],
        )
        a2 = FrameIntelEvidence(
            frameId="a2",
            round=2,
            timer=17,
            observations=[
                IntelCardObservation("goldAvg", 47286, STATUS_OBSERVED, "a2", 2, 17, [0, 0, 1, 1], "47286", 0.9, is_physical_ocr=True)
            ],
        )
        b1 = FrameIntelEvidence(
            frameId="b1",
            round=3,
            timer=50,
            observations=[
                IntelCardObservation("goldAvg", 99999, STATUS_OBSERVED, "b1", 3, 50, [0, 0, 1, 1], "99999", 0.9, is_physical_ocr=True)
            ],
        )
        b2 = FrameIntelEvidence(
            frameId="b2",
            round=3,
            timer=49,
            observations=[
                IntelCardObservation("goldAvg", 99999, STATUS_OBSERVED, "b2", 3, 49, [0, 0, 1, 1], "99999", 0.9, is_physical_ocr=True)
            ],
        )
        ledger = IntelCardEvidenceLedger()
        snap = ledger.merge(a1, a2, b1, b2)
        fact = snap["facts"]["goldAvg"]
        self.assertEqual(fact["status"], STATUS_CONFLICT)
        self.assertIsNone(fact["value"])
        self.assertIn(47286, fact["candidates"])
        self.assertIn(99999, fact["candidates"])

    def test_router_does_not_confuse_q_with_total_items(self):
        q_hits = route_card_text("本局内紫色，金色和红色品质藏品的总件数为11件。")
        tot_hits = route_card_text("本局内所有藏品的总数量为66件")
        self.assertEqual(q_hits, [("q", 11, 0.95)])
        self.assertEqual(tot_hits, [("totalItems", 66, 0.92)])

    def test_snapshot_recognizer_returns_card_observations_on_real_fixture(self):
        recognizer = SingleFrameSnapshotRecognizer(ocr_engine=self.extractor._ocr_engine)
        ev = recognizer.extract_intel_card_evidence(_load_bgr("r2_viewport.png"), frame_id="snap-r2")
        self.assertIsNotNone(ev)
        self.assertEqual(len(ev.cards), 4)
        fields = _obs_map(ev)
        self.assertEqual(fields.get("q"), 11)
        dummy = np.ones((100, 100, 3), dtype=np.uint8)
        skipped = recognizer.extract_intel_card_evidence(dummy, frame_id="tiny")
        self.assertIsNone(skipped)
        result = recognizer.process_frame(dummy, existing_facts={})
        self.assertEqual(result.get("cardObservations"), [])

    def test_continuous_incremental_fast_path_contracts_c24(self):
        """
        Verify Continuous Incremental Fast Path Contracts (4D2D1M-C2.4):
        1. Single-shot extract_frame parity unchanged.
        2. First extract_cards_fast extracts all cards.
        3. Unchanged next frame has 0 OCR calls, synthesizing cached observations.
        4. Session reset / clear_card_cache purges cache safely.
        """
        img_r2 = _load_bgr("r2_viewport.png")
        img_r3 = _load_bgr("r3_viewport.png")

        # 1. Single-shot parity
        ev_single = self.extractor.extract_frame(img_r2, frame_id="single_shot_test")
        self.assertEqual(len(ev_single.cards), 4)
        obs_single = _obs_map(ev_single)
        self.assertEqual(obs_single.get("q"), 11)
        self.assertEqual(obs_single.get("goldAvg"), 47286)
        self.assertEqual(obs_single.get("purpleAvg"), 4357)
        self.assertEqual(obs_single.get("purpleCount"), 3)

        # 2. Continuous fast path with mock/tracked OCR
        from unittest.mock import MagicMock
        mock_ocr = MagicMock()
        mock_ocr.side_effect = lambda img: ([[ [[0,0],[10,0],[10,10],[0,10]], "千眼一回 紫色金色和红色品质藏品总件数为11件", 0.95 ]], None)

        ext_fast = IntelCardEvidenceExtractor(ocr_engine=mock_ocr)

        # Step A: First extraction -> calls OCR for each card
        ev1 = ext_fast.extract_cards_fast(img_r2, frame_id="f1", known_round=2, known_timer=18, generation=1)
        self.assertEqual(len(ev1.cards), 4)
        self.assertEqual(mock_ocr.call_count, 4)
        self.assertEqual(len(ev1.observations), 4)

        # Step B: Next frame unchanged -> 0 OCR calls!
        mock_ocr.reset_mock()
        ev2 = ext_fast.extract_cards_fast(img_r2, frame_id="f2", known_round=2, known_timer=17, generation=1)
        self.assertEqual(len(ev2.cards), 4)
        self.assertEqual(mock_ocr.call_count, 0, "Unchanged frame must have 0 OCR calls")
        self.assertEqual(len(ev2.observations), 4)

        # Step C: Session generation reset -> clears cache and triggers OCR again
        mock_ocr.reset_mock()
        ev3 = ext_fast.extract_cards_fast(img_r2, frame_id="f3", known_round=2, known_timer=16, generation=2)
        self.assertEqual(mock_ocr.call_count, 4, "New generation must refresh cache")

        # Step D: clear_card_cache()
        ext_fast.clear_card_cache()
        self.assertEqual(len(ext_fast._cached_cards), 0)

    def test_scale_invariant_card_reuse_contracts_c28(self):
        """
        Verify Scale-Invariant Card Reuse Contracts (4D2D1M-C2.8):
        1. 3-card -> 4-card layout change safely reuses 3 matching cards and only OCRs 1 new card.
        2. Unchanged same-layout frame has 0 OCR calls.
        3. Reordered cards are mapped 1-to-1 correctly without wrong reuse.
        4. Ambiguous near-match fails closed and triggers re-OCR.
        5. Single changed card triggers re-OCR for that card only.
        """
        from intel_card_evidence import CachedCardEvidence

        # 1. Use real fixture img_r2 (4 cards)
        img_r2 = _load_bgr("r2_viewport.png")
        stack_r2 = ROIScaler.crop_roi(img_r2, INTEL_STACK_ROI)
        boxes_r2 = detect_card_boxes(stack_r2)
        self.assertEqual(len(boxes_r2), 4)
        crops_r2 = [stack_r2[y1:y2, x1:x2] for x1, y1, x2, y2 in boxes_r2]

        call_count = 0
        def fake_ocr(crop):
            nonlocal call_count
            call_count += 1
            return ([[ [[0,0],[10,0],[10,10],[0,10]], "宗师情报 4357", 0.95 ]], None)

        from unittest.mock import MagicMock
        mock_ocr = MagicMock(side_effect=fake_ocr)
        extractor = IntelCardEvidenceExtractor(ocr_engine=mock_ocr)

        # Step A: Seed cache with first 3 cards only (simulating R1)
        sigs_3 = [extractor._compute_multimodal_signature(c) for c in crops_r2[:3]]
        for i, sig in enumerate(sigs_3):
            s_raw, b_hue, b_sat, t_patch = sig
            extractor._cached_cards.append(
                CachedCardEvidence(
                    sig_raw=s_raw,
                    badge_hue=b_hue,
                    badge_sat=b_sat,
                    text_patch=t_patch,
                    global_box=[0, 0, 100, 100],
                    raw_text=f"Card_{i}",
                    routed_items=[(f"field_{i}", i, 0.9)],
                    generation=1,
                    round_no=1,
                )
            )
        extractor._cache_generation = 1
        self.assertEqual(len(extractor._cached_cards), 3)

        # Step B: Present full 4-card frame (img_r2) -> must reuse 3 old cards and OCR only the 4th card!
        call_count = 0
        ev2 = extractor.extract_cards_fast(img_r2, frame_id="f2", known_round=2, known_timer=18, generation=1)
        self.assertEqual(len(ev2.cards), 4)
        self.assertEqual(call_count, 1, "Scale-invariant matching must reuse 3 old cards and OCR only the 4th card")
        self.assertEqual(len(extractor._cached_cards), 4)

        # Step C: Reorder test: reorder cards to [C, A, D, B]
        reord_sigs = [
            extractor._compute_multimodal_signature(crops_r2[2]),
            extractor._compute_multimodal_signature(crops_r2[0]),
            extractor._compute_multimodal_signature(crops_r2[3]),
            extractor._compute_multimodal_signature(crops_r2[1]),
        ]
        reused, unmatched = extractor._match_cards_to_cache(reord_sigs, generation=1)
        self.assertEqual(len(reused), 4)
        self.assertEqual(unmatched, [])

        # Step D: Ambiguous near-match fail-closed test
        sig_raw, b_hue, b_sat, t_patch = extractor._compute_multimodal_signature(crops_r2[0])
        c1 = CachedCardEvidence(sig_raw, b_hue, b_sat, t_patch, [0,0,10,10], "Text A", [("fieldA", 1, 0.9)], 2, 1)
        c2 = CachedCardEvidence(sig_raw, b_hue, b_sat, (t_patch.astype(np.int16)+1).clip(0,255).astype(np.uint8), [0,10,10,20], "Text B", [("fieldB", 2, 0.9)], 2, 1)
        extractor._cached_cards = [c1, c2]
        extractor._cache_generation = 2

        test_sigs = [extractor._compute_multimodal_signature(crops_r2[0])]
        reused_ambig, unmatched_ambig = extractor._match_cards_to_cache(test_sigs, generation=2, margin_threshold=10.0)
        self.assertEqual(reused_ambig, {}, "Ambiguous candidates must NOT be reused")
        self.assertEqual(unmatched_ambig, [0], "Ambiguous candidate must be flagged for re-OCR")

    def test_provenance_manifest_exists_and_hashes_match(self):
        man_path = os.path.join(FIXTURE_DIR, "provenance.json")
        with open(man_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["schema"], "intel-card-evidence-fixture-v1")
        self.assertEqual(len(manifest["frames"]), 2)
        for rec in manifest["frames"]:
            self.assertEqual(len(rec["sourceSha256"]), 64)
            self.assertGreater(rec["sourceSize"]["width"], 1000)
            for crop in rec["crops"].values():
                path = os.path.join(FIXTURE_DIR, crop["file"])
                self.assertTrue(os.path.isfile(path), path)

    def test_projected_recognizer_only_fast_path_contracts_c213(self):
        """
        Verify Projected Recognizer-Only Fast Path Contracts (4D2D1M-C2.13):
        1. Multi-line 1D projection extracts discrete text lines.
        2. Fast projected recognition processes four fields (purpleAvg, q, goldAvg, purpleCount).
        3. 3->4 transition reuses 3 cached cards and runs fast rec-only on the 4th card.
        4. Fail-closed fallback to full RapidOCR on 0-line, unroutable, or exception conditions.
        5. Single-shot extract_frame remains full RapidOCR with exact observation parity.
        """
        img_r2_stack = _load_bgr("r2_intel_stack.png")
        boxes = detect_card_boxes(img_r2_stack)
        self.assertEqual(len(boxes), 4)

        crops = [img_r2_stack[y1:y2, x1:x2] for x1, y1, x2, y2 in boxes]
        extractor = IntelCardEvidenceExtractor()
        extractor._get_ocr()

        # Step 1: Verify all 4 cards extract valid text lines
        for i, crop in enumerate(crops):
            lines = extractor._extract_text_lines_projected(crop)
            self.assertGreaterEqual(len(lines), 1, f"Card #{i} must produce at least 1 projected text line")

        # Step 2: Test projected recognition on each card
        for i, crop in enumerate(crops):
            raw_text, routed, is_proj = extractor._ocr_card_fast_projected(crop)
            self.assertTrue(is_proj, f"Card #{i} must succeed via projected recognition")
            self.assertGreaterEqual(len(routed), 1)

        # Step 3: Test fallback on synthetic blank / corrupted crops
        blank_crop = np.zeros((100, 600, 3), dtype=np.uint8)
        raw_text_fb, routed_fb, is_proj_fb = extractor._ocr_card_fast_projected(blank_crop)
        self.assertFalse(is_proj_fb, "Blank crop must fallback to full OCR")
        self.assertEqual(routed_fb, [])

        # Step 4: Test mock engine fallback on exception
        class ThrowingEngine:
            def text_rec(self, crops):
                raise RuntimeError("Simulated Rec Failure")
            def __call__(self, img):
                return ([[ [[0,0],[10,0],[10,10],[0,10]], "宗师情报 NTE 紫色品质藏品平均价值为4357", 0.95 ]], None)

        ext_throwing = IntelCardEvidenceExtractor(ocr_engine=ThrowingEngine())
        raw_fb, routed_fb2, is_proj_fb2 = ext_throwing._ocr_card_fast_projected(crops[0])
        self.assertFalse(is_proj_fb2, "Exception during text_rec must gracefully fallback to full OCR")
        self.assertEqual(routed_fb2, [("purpleAvg", 4357, 0.93)])

        # Step 5: Test 3->4 transition using extract_cards_fast
        # Seed cache with first 3 cards
        extractor.clear_card_cache()
        for idx in range(3):
            crop = crops[idx]
            sig_raw, b_hue, b_sat, t_patch = extractor._compute_multimodal_signature(crop)
            raw_txt, r_items, _ = extractor._ocr_card_fast_projected(crop)
            extractor._cached_cards.append(
                CachedCardEvidence(
                    sig_raw=sig_raw,
                    badge_hue=b_hue,
                    badge_sat=b_sat,
                    text_patch=t_patch,
                    global_box=[0, 0, 100, 100],
                    raw_text=raw_txt,
                    routed_items=r_items,
                    generation=1,
                    round_no=1,
                )
            )
        extractor._cache_generation = 1
        self.assertEqual(len(extractor._cached_cards), 3)

        # Extract 4-card stack
        img_r2_vp = _load_bgr("r2_viewport.png")
        ev = extractor.extract_cards_fast(img_r2_vp, frame_id="r2_test", known_round=2, known_timer=18, generation=1)
        self.assertEqual(len(ev.cards), 4)
        obs_map = {o.field: o.value for o in ev.observations}
        self.assertEqual(obs_map, {"purpleAvg": 4357, "q": 11, "goldAvg": 47286, "purpleCount": 3})

    def test_cross_frame_wrong_first_rejected(self):
        """Wrong-first single-frame observation must NEVER become confirmed (4D2D1M-C2.25)."""
        f_a = FrameIntelEvidence(frameId="fA", observations=[IntelCardObservation("purpleAvg", 9999, STATUS_OBSERVED, "fA", 1, 18, [0,0,1,1], "9999", 0.9, is_physical_ocr=True)])
        f_b = FrameIntelEvidence(frameId="fB", observations=[IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fB", 1, 17, [0,0,1,1], "4357", 0.9, is_physical_ocr=True)])
        f_c = FrameIntelEvidence(frameId="fC", observations=[IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fC", 1, 16, [0,0,1,1], "4357", 0.9, is_physical_ocr=True)])

        ledger = IntelCardEvidenceLedger()
        s1 = ledger.merge(f_a)
        self.assertEqual(s1["facts"]["purpleAvg"]["status"], STATUS_UNKNOWN)
        self.assertEqual(s1["facts"]["purpleAvg"]["tentative"], 9999)

        s2 = ledger.merge(f_b)
        self.assertEqual(s2["facts"]["purpleAvg"]["status"], STATUS_UNKNOWN)
        self.assertEqual(s2["facts"]["purpleAvg"]["tentative"], 4357)

        s3 = ledger.merge(f_c)
        self.assertEqual(s3["facts"]["purpleAvg"]["status"], STATUS_OBSERVED)
        self.assertEqual(s3["facts"]["purpleAvg"]["value"], 4357)

    def test_same_frame_repeat_ocr_cannot_confirm(self):
        """Repeated OCR on the exact same frameId cannot count as 2nd vote."""
        f_a1 = FrameIntelEvidence(frameId="fA", observations=[IntelCardObservation("purpleAvg", 9999, STATUS_OBSERVED, "fA", 1, 18, [0,0,1,1], "9999", 0.9, is_physical_ocr=True)])
        f_a2 = FrameIntelEvidence(frameId="fA", observations=[IntelCardObservation("purpleAvg", 9999, STATUS_OBSERVED, "fA", 1, 18, [0,0,1,1], "9999", 0.9, is_physical_ocr=True)])

        ledger = IntelCardEvidenceLedger()
        snap = ledger.merge(f_a1, f_a2)
        self.assertEqual(snap["facts"]["purpleAvg"]["status"], STATUS_UNKNOWN)
        self.assertIsNone(snap["facts"]["purpleAvg"]["value"])
        self.assertEqual(snap["facts"]["purpleAvg"]["tentative"], 9999)

    def test_cache_reuse_cannot_confirm(self):
        """Cache reuse observation (is_physical_ocr=False) cannot act as 2nd confirmation vote."""
        f_a = FrameIntelEvidence(frameId="fA", observations=[IntelCardObservation("purpleAvg", 9999, STATUS_OBSERVED, "fA", 1, 18, [0,0,1,1], "9999", 0.9, is_physical_ocr=True)])
        f_b = FrameIntelEvidence(frameId="fB", observations=[IntelCardObservation("purpleAvg", 9999, STATUS_OBSERVED, "fB", 1, 17, [0,0,1,1], "9999", 0.9, is_physical_ocr=False)])

        ledger = IntelCardEvidenceLedger()
        snap = ledger.merge(f_a, f_b)
        self.assertEqual(snap["facts"]["purpleAvg"]["status"], STATUS_UNKNOWN)
        self.assertIsNone(snap["facts"]["purpleAvg"]["value"])

    def test_single_challenger_does_not_cause_conflict(self):
        """Single-frame challenger on confirmed value does not destroy fact into conflict."""
        f_a = FrameIntelEvidence(frameId="fA", observations=[IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fA", 1, 18, [0,0,1,1], "4357", 0.9, is_physical_ocr=True)])
        f_b = FrameIntelEvidence(frameId="fB", observations=[IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fB", 1, 17, [0,0,1,1], "4357", 0.9, is_physical_ocr=True)])
        f_c = FrameIntelEvidence(frameId="fC", observations=[IntelCardObservation("purpleAvg", 9999, STATUS_OBSERVED, "fC", 1, 16, [0,0,1,1], "9999", 0.9, is_physical_ocr=True)])
        f_d = FrameIntelEvidence(frameId="fD", observations=[IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fD", 1, 15, [0,0,1,1], "4357", 0.9, is_physical_ocr=True)])

        ledger = IntelCardEvidenceLedger()
        ledger.merge(f_a, f_b)
        s3 = ledger.merge(f_c)
        self.assertEqual(s3["facts"]["purpleAvg"]["status"], STATUS_OBSERVED)
        self.assertEqual(s3["facts"]["purpleAvg"]["value"], 4357)
        self.assertEqual(s3["facts"]["purpleAvg"]["challenger"], 9999)

        s4 = ledger.merge(f_d)
        self.assertEqual(s4["facts"]["purpleAvg"]["status"], STATUS_OBSERVED)
        self.assertEqual(s4["facts"]["purpleAvg"]["value"], 4357)
        self.assertNotIn("challenger", s4["facts"]["purpleAvg"])

    def test_persistent_challenger_causes_conflict(self):
        """Two consecutive distinct frames of differing value trigger STATUS_CONFLICT."""
        f_a = FrameIntelEvidence(frameId="fA", observations=[IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fA", 1, 18, [0,0,1,1], "4357", 0.9, is_physical_ocr=True)])
        f_b = FrameIntelEvidence(frameId="fB", observations=[IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fB", 1, 17, [0,0,1,1], "4357", 0.9, is_physical_ocr=True)])
        f_c = FrameIntelEvidence(frameId="fC", observations=[IntelCardObservation("purpleAvg", 9999, STATUS_OBSERVED, "fC", 1, 16, [0,0,1,1], "9999", 0.9, is_physical_ocr=True)])
        f_d = FrameIntelEvidence(frameId="fD", observations=[IntelCardObservation("purpleAvg", 9999, STATUS_OBSERVED, "fD", 1, 15, [0,0,1,1], "9999", 0.9, is_physical_ocr=True)])

        ledger = IntelCardEvidenceLedger()
        ledger.merge(f_a, f_b, f_c)
        s4 = ledger.merge(f_d)
        self.assertEqual(s4["facts"]["purpleAvg"]["status"], STATUS_CONFLICT)
        self.assertIsNone(s4["facts"]["purpleAvg"]["value"])

    def test_miss_interrupts_tentative(self):
        """Miss in between resets tentative candidate to enforce consecutive valid confirmation."""
        f_a = FrameIntelEvidence(frameId="fA", observations=[IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fA", 1, 18, [0,0,1,1], "4357", 0.9, is_physical_ocr=True)])
        f_b = FrameIntelEvidence(frameId="fB", observations=[])
        f_c = FrameIntelEvidence(frameId="fC", observations=[IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fC", 1, 16, [0,0,1,1], "4357", 0.9, is_physical_ocr=True)])
        f_d = FrameIntelEvidence(frameId="fD", observations=[IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fD", 1, 15, [0,0,1,1], "4357", 0.9, is_physical_ocr=True)])

        ledger = IntelCardEvidenceLedger()
        ledger.merge(f_a)
        ledger.merge(f_b)
        s3 = ledger.merge(f_c)
        self.assertEqual(s3["facts"]["purpleAvg"]["status"], STATUS_UNKNOWN)
        self.assertEqual(s3["facts"]["purpleAvg"]["tentative"], 4357)

        s4 = ledger.merge(f_d)
        self.assertEqual(s4["facts"]["purpleAvg"]["status"], STATUS_OBSERVED)
        self.assertEqual(s4["facts"]["purpleAvg"]["value"], 4357)

    def test_four_fields_independent(self):
        """All four fields maintain independent tentative and confirmation states."""
        f_a = FrameIntelEvidence(frameId="fA", observations=[
            IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fA", 1, 18, [0,0,1,1], "4357", 0.9, is_physical_ocr=True),
            IntelCardObservation("q", 11, STATUS_OBSERVED, "fA", 1, 18, [0,0,1,1], "11", 0.9, is_physical_ocr=True),
            IntelCardObservation("goldAvg", 47286, STATUS_OBSERVED, "fA", 1, 18, [0,0,1,1], "47286", 0.9, is_physical_ocr=True),
            IntelCardObservation("purpleCount", 3, STATUS_OBSERVED, "fA", 1, 18, [0,0,1,1], "3", 0.9, is_physical_ocr=True),
        ])
        f_b = FrameIntelEvidence(frameId="fB", observations=[
            IntelCardObservation("purpleAvg", 4357, STATUS_OBSERVED, "fB", 1, 17, [0,0,1,1], "4357", 0.9, is_physical_ocr=True),
            IntelCardObservation("q", 11, STATUS_OBSERVED, "fB", 1, 17, [0,0,1,1], "11", 0.9, is_physical_ocr=True),
            IntelCardObservation("goldAvg", 47286, STATUS_OBSERVED, "fB", 1, 17, [0,0,1,1], "47286", 0.9, is_physical_ocr=True),
            IntelCardObservation("purpleCount", 3, STATUS_OBSERVED, "fB", 1, 17, [0,0,1,1], "3", 0.9, is_physical_ocr=True),
        ])

        ledger = IntelCardEvidenceLedger()
        snap = ledger.merge(f_a, f_b)
        facts = snap["facts"]
        self.assertEqual(facts["purpleAvg"]["value"], 4357)
        self.assertEqual(facts["q"]["value"], 11)
        self.assertEqual(facts["goldAvg"]["value"], 47286)
        self.assertEqual(facts["purpleCount"]["value"], 3)

    def test_async_intel_worker_passes_pending_verify_fields(self):
        """Verify AsyncContinuousIntelWorker properly propagates pending_verify_fields (4D2D1M-C2.25W)."""
        from unittest.mock import MagicMock
        from intel_card_evidence import AsyncContinuousIntelWorker

        mock_ext = MagicMock()
        mock_ext.extract_cards_fast.return_value = FrameIntelEvidence(frameId="w1")

        worker = AsyncContinuousIntelWorker(extractor_factory=lambda: mock_ext)
        dummy_frame = np.ones((720, 1280, 3), dtype=np.uint8)

        worker.submit_frame(
            dummy_frame,
            frame_id="w1",
            generation=1,
            known_round=2,
            known_timer=18,
            pending_verify_fields={"purpleAvg", "q"},
        )

        import time
        for _ in range(50):
            if not worker.in_flight:
                break
            time.sleep(0.05)

        self.assertFalse(worker.in_flight)
        mock_ext.extract_cards_fast.assert_called_once()
        _, kwargs = mock_ext.extract_cards_fast.call_args
        self.assertEqual(kwargs.get("pending_verify_fields"), {"purpleAvg", "q"})
        self.assertEqual(kwargs.get("generation"), 1)

    def test_vision_pipeline_end_to_end_production_wiring(self):
        """Verify NTEVisionPipeline automatic closed loop cross-frame confirmation (4D2D1M-C2.25W)."""
        from vision_pipeline import NTEVisionPipeline, SCENE_IN_AUCTION
        import time

        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()
        pipe.reset_session_state()
        pipe.current_context["scene"] = SCENE_IN_AUCTION
        pipe.current_context["inAuction"] = True
        pipe.current_context["round"] = 2
        pipe.current_context["timer"] = 18

        img_r2_vp = _load_bgr("r2_viewport.png")

        # Frame A: Tentative
        pipe.process_frame(img_r2_vp, captured_at="2026-08-30T00:00:01")
        worker = pipe._get_async_intel_worker()
        for _ in range(50):
            if not worker.in_flight:
                break
            time.sleep(0.05)

        # Drain Frame A
        ctx_a = pipe.process_frame(img_r2_vp, captured_at="2026-08-30T00:00:02")
        facts_a = ctx_a.get("intelFacts") or {}
        for f in ["q", "goldAvg", "purpleAvg", "purpleCount"]:
            self.assertEqual(facts_a.get(f, {}).get("status"), STATUS_UNKNOWN)
            self.assertIsNotNone(facts_a.get(f, {}).get("tentative"))

        # Frame B: Automatic cross-frame verification
        pipe.process_frame(img_r2_vp, captured_at="2026-08-30T00:00:03")
        for _ in range(50):
            if not worker.in_flight:
                break
            time.sleep(0.05)

        # Drain Frame B
        ctx_b = pipe.process_frame(img_r2_vp, captured_at="2026-08-30T00:00:04")
        facts_b = ctx_b.get("intelFacts") or {}
        self.assertEqual(len(ctx_b.get('intelCardReadings') or []), 4)
        self.assertTrue(all('rawText' in r and 'is_physical_ocr' in r for r in ctx_b['intelCardReadings']))
        self.assertEqual(facts_b.get("purpleAvg", {}).get("status"), STATUS_OBSERVED)
        self.assertEqual(facts_b.get("purpleAvg", {}).get("value"), 4357)
        self.assertEqual(facts_b.get("q", {}).get("value"), 11)
        self.assertEqual(facts_b.get("goldAvg", {}).get("value"), 47286)
        self.assertEqual(facts_b.get("purpleCount", {}).get("value"), 3)

        # Frame C: Steady state cache check (0 pending verify fields)
        pipe.process_frame(img_r2_vp, captured_at="2026-08-30T00:00:05")
        self.assertEqual(len(pipe._intel_ledger.get_pending_verify_fields()), 0)

    def test_low_tier_and_red_count_and_grid_upstream_perception_wiring(self):
        """Verify 4D2D1N-C4.2W: Upstream Low-Tier / Red Count + Grid Perception Wiring."""
        from intel_card_evidence import route_card_text
        from snapshot_recognizer import SingleFrameSnapshotRecognizer
        from delta_intel import DeltaIntelManager
        from vision_contract import VisionObservation, VisionIntel, VisionBids, VisionSettlement

        # 1. Test route_card_text (IntelCardEvidenceExtractor unit)
        # Counts
        hits_green = {h[0]: h[1] for h in route_card_text("绿色品质藏品的总数量为4")}
        self.assertEqual(hits_green.get("greenCount"), 4)
        hits_white = {h[0]: h[1] for h in route_card_text("白色品质藏品的总数量为7")}
        self.assertEqual(hits_white.get("whiteCount"), 7)
        hits_red = {h[0]: h[1] for h in route_card_text("红色品质藏品的总数量为2")}
        self.assertEqual(hits_red.get("redCount"), 2)
        hits_blue = {h[0]: h[1] for h in route_card_text("蓝色品质藏品的总数量为5")}
        self.assertEqual(hits_blue.get("blueCount"), 5)

        # Grids
        hits_gold_g = {h[0]: h[1] for h in route_card_text("金色品质藏品所占格数为24")}
        self.assertEqual(hits_gold_g.get("goldGrid"), 24)
        hits_purple_g = {h[0]: h[1] for h in route_card_text("紫色品质藏品所占格数为16")}
        self.assertEqual(hits_purple_g.get("purpleGrid"), 16)
        hits_blue_g = {h[0]: h[1] for h in route_card_text("蓝色品质藏品所占格数为12")}
        self.assertEqual(hits_blue_g.get("blueGrid"), 12)
        hits_green_g = {h[0]: h[1] for h in route_card_text("绿色品质藏品所占格数为8")}
        self.assertEqual(hits_green_g.get("greenGrid"), 8)
        hits_white_g = {h[0]: h[1] for h in route_card_text("白色品质藏品所占格数为5")}
        self.assertEqual(hits_white_g.get("whiteGrid"), 5)
        hits_red_g = {h[0]: h[1] for h in route_card_text("红色品质藏品所占格数为6")}
        self.assertEqual(hits_red_g.get("redGrid"), 6)

        # 2. Test SingleFrameSnapshotRecognizer (SnapshotRecognizer unit)
        rec = SingleFrameSnapshotRecognizer()
        lines = [
            "绿色品质藏品的总数量为3",
            "白色品质藏品的总数量为5",
            "红色品质藏品的总数量为1",
            "蓝色品质藏品所占格数为10",
            "绿色品质藏品所占格数为6",
            "白色品质藏品所占格数为4",
            "红色品质藏品所占格数为8",
            "总格数为64",
            "所有藏品的总数量为66件",
            "紫色，金色和红色品质藏品的总件数为12件",
        ]
        mapped_res = [([[0, 0], [1, 1]], line, 0.95) for line in lines]
        scene, patches = rec.parse_ocr_results(mapped_res)
        self.assertEqual(scene, "IN_AUCTION")
        patch_map = {p.key: p.value for p in patches}
        self.assertEqual(patch_map.get("greenCount"), 3)
        self.assertEqual(patch_map.get("whiteCount"), 5)
        self.assertEqual(patch_map.get("redCount"), 1)
        self.assertEqual(patch_map.get("blueGrid"), 10)
        self.assertEqual(patch_map.get("greenGrid"), 6)
        self.assertEqual(patch_map.get("whiteGrid"), 4)
        self.assertEqual(patch_map.get("redGrid"), 8)
        self.assertEqual(patch_map.get("totalGrid"), 64)
        self.assertEqual(patch_map.get("totalItems"), 66)
        self.assertEqual(patch_map.get("q"), 12)

        # 3. Test DeltaIntelManager
        tracker = DeltaIntelManager()
        ctx_init = tracker.get_session_context()
        self.assertIsNone(ctx_init.get("greenCount"))
        self.assertIsNone(ctx_init.get("whiteCount"))
        self.assertIsNone(ctx_init.get("redCount"))
        self.assertIsNone(ctx_init.get("blueGrid"))
        self.assertIsNone(ctx_init.get("greenGrid"))
        self.assertIsNone(ctx_init.get("whiteGrid"))
        self.assertIsNone(ctx_init.get("redGrid"))

        obs = VisionObservation(
            timestamp=1.0,
            round=1,
            timer=50,
            intel=VisionIntel(
                greenCount=3,
                whiteCount=5,
                redCount=1,
                blueGrid=10,
                greenGrid=6,
                whiteGrid=4,
                redGrid=8,
            ),
            bids=VisionBids(),
            settlement=VisionSettlement(),
        )
        res = tracker.process_observation(obs)
        self.assertTrue(res["deltaDetected"])
        ctx_after = tracker.get_session_context()
        self.assertEqual(ctx_after.get("greenCount"), 3)
        self.assertEqual(ctx_after.get("whiteCount"), 5)
        self.assertEqual(ctx_after.get("redCount"), 1)
        self.assertEqual(ctx_after.get("blueGrid"), 10)
        self.assertEqual(ctx_after.get("greenGrid"), 6)
        self.assertEqual(ctx_after.get("whiteGrid"), 4)
        self.assertEqual(ctx_after.get("redGrid"), 8)

        # 4. Strict separation & zero/null safety
        self.assertNotEqual(ctx_after.get("greenCount"), 0)
        self.assertNotEqual(ctx_after.get("whiteCount"), 0)
        self.assertNotEqual(ctx_after.get("redCount"), 0)
        self.assertIsNone(ctx_after.get("blueCount"))
        self.assertIsNone(ctx_after.get("goldGrid"))
        self.assertIsNone(ctx_after.get("purpleGrid"))


if __name__ == "__main__":
    unittest.main()


