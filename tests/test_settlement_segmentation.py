# -*- coding: utf-8 -*-
"""Settlement 静态页物理分件：与 14-11-56@238s 人工 GT 做 cell IoU，禁止吞格。"""
import json
import os
import sys
import unittest

import cv2
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "core"))

from settlement_item_recognizer import SettlementItemRecognizer
from settlement_catalog_candidates import (
    SettlementCatalogCandidateResolver,
    STATUS_NO_CATALOG_MATCH,
    STATUS_UNIQUE_IN_CATALOG,
    STATUS_AMBIGUOUS_CANDIDATES,
    STATUS_EXACT_IDENTIFIED,
    DEFAULT_TOP1_SCORE_THRESHOLD,
    DEFAULT_MARGIN_THRESHOLD,
)


def _load_frame():
    path = os.path.join(PROJECT_ROOT, "build", "live_141156", "t238.jpg")
    if not os.path.exists(path):
        return None
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def _load_gt():
    path = os.path.join(PROJECT_ROOT, "tests", "fixtures", "settlement_238_gt.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _cell_set(item):
    if item.get("cells"):
        return {tuple(cell) for cell in item["cells"]}
    cells = set()
    for r in range(item["row"], item["row"] + item["heightCells"]):
        for c in range(item["col"], item["col"] + item["widthCells"]):
            cells.add((r, c))
    return cells


def _iou(a, b):
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _classify(pred_set, gt_items):
    best = None
    best_iou = 0.0
    for gt in gt_items:
        score = _iou(pred_set, _cell_set(gt))
        if score > best_iou:
            best_iou = score
            best = gt
    if best is None or best_iou <= 0:
        return "false_positive", None, 0.0
    gt_set = _cell_set(best)
    if pred_set == gt_set:
        return "ok", best, 1.0
    if pred_set.issuperset(gt_set) and pred_set != gt_set:
        return "merge", best, best_iou
    if gt_set.issuperset(pred_set) and pred_set != gt_set:
        return "split", best, best_iou
    return "mismatch", best, best_iou


class TestSettlementSegmentation238(unittest.TestCase):
    def test_components_match_physical_items(self):
        # The former test accepted any fragment as GT coverage (even IoU=.25),
        # and its eight-row annotation mislabeled part of the red cube as noise.
        # Use independently transcribed rectangles and demand exact set equality.
        from pathlib import Path
        fixture = Path(PROJECT_ROOT) / "tests" / "fixtures" / "settlement_cards_v2"
        samples = json.loads((fixture / "annotations.json").read_text(encoding="utf-8"))
        rec = SettlementItemRecognizer()
        for sample in samples:
            board = cv2.imdecode(np.fromfile(fixture / sample["image"], dtype=np.uint8), 1)
            frame = np.zeros((1080, 1920, 3), np.uint8)
            frame[214:776, 1315:1878] = board
            with self.subTest(sample=sample["image"]):
                ledger = rec.parse_settlement_ledger(frame)
                expected = {tuple(rect) for rect in sample["rectangles"]}
                for key in ("settlementItems", "physicalGroupingHypotheses"):
                    items = ledger[key]
                    actual = {(i["row"], i["col"], i["widthCells"], i["heightCells"]) for i in items}
                    self.assertEqual(actual, expected)
                    self.assertEqual(len(items), len(expected))
                self.assertFalse(ledger["settlementLedgerVerified"])
                expected_names = {tuple(i["rect"]): i["name"] for i in sample.get("identityAnnotations", [])}
                expected_values = {tuple(i["rect"]): i["value"] for i in sample.get("identityAnnotations", []) if "value" in i}
                for item in ledger["settlementItems"]:
                    if item["name"] is not None:
                        key = (item["row"], item["col"], item["widthCells"], item["heightCells"])
                        self.assertEqual(item["name"], expected_names[key])
                        if key in expected_values:
                            self.assertEqual(item["price"], expected_values[key])

    def test_visible_card_boundaries_at_scaled_resolutions(self):
        from pathlib import Path
        fixture = Path(PROJECT_ROOT) / "tests" / "fixtures" / "settlement_cards_v2"
        rec = SettlementItemRecognizer()
        for sample in json.loads((fixture / "annotations.json").read_text(encoding="utf-8")):
            image = cv2.imdecode(np.fromfile(fixture / sample["image"], dtype=np.uint8), 1)
            for scale in (2 / 3, .75, 1, 4 / 3):
                with self.subTest(image=sample["image"], scale=scale):
                    board = cv2.resize(image, None, fx=scale, fy=scale)
                    items = rec._segment_occupied_components(board, board.shape[1] / 10, board.shape[0] / 10)
                    actual = {(i["row"], i["col"], i["widthCells"], i["heightCells"]) for i in items}
                    self.assertEqual(actual, {tuple(r) for r in sample["rectangles"]})
                    self.assertEqual(len(items), len(sample["rectangles"]))

    def test_pixel_template_identity_evidence_disambiguation(self):
        """
        4D2D1M-C3.2I Acceptance Criteria Test:
        - 0 candidate: 不猜身份 (NO_CATALOG_MATCH)
        - 1 candidate: 只标 UNIQUE_IN_CATALOG (不写 canonical truth)
        - 多 candidate: 实际经过 pixel/template comparison
        - 强 Top1 + 足够 margin: 才能 EXACT_IDENTIFIED
        - 弱 Top1 / margin 不足: 保持 AMBIGUOUS_CANDIDATES 并完整保留候选和分数
        - 没有 candidates[0] 首选
        - 不写 knownItems / Solver / History / reviewed truth
        """
        resolver = SettlementCatalogCandidateResolver()
        rec = SettlementItemRecognizer()

        # 1. 0 candidate: 不猜身份
        hyp_0_cand = {
            "groupingHypothesisId": "ghyp_test_0",
            "rarity": "unknown",
            "gridShape": "9x9",
            "widthCells": 9,
            "heightCells": 9,
            "bbox": [0, 0, 90, 90],
        }
        ev_0 = resolver.resolve_identity_evidence(hyp_0_cand)
        self.assertEqual(ev_0["status"], STATUS_NO_CATALOG_MATCH)
        self.assertEqual(ev_0["identityStatus"], STATUS_NO_CATALOG_MATCH)
        self.assertEqual(ev_0["candidateCount"], 0)
        self.assertIsNone(ev_0["candidateCatalogId"])
        self.assertEqual(ev_0["candidateCatalogIds"], [])
        self.assertEqual(ev_0["rankedCandidates"], [])
        self.assertEqual(ev_0["top1Score"], 0.0)
        self.assertEqual(ev_0["margin"], 0.0)

        # 2. 1 candidate: 只标 UNIQUE_IN_CATALOG
        hyp_1_cand = {
            "groupingHypothesisId": "ghyp_test_1",
            "rarity": "white",
            "gridShape": "2x3",
            "widthCells": 2,
            "heightCells": 3,
            "bbox": [0, 0, 60, 90],
        }
        ev_1 = resolver.resolve_identity_evidence(hyp_1_cand)
        self.assertEqual(ev_1["status"], STATUS_UNIQUE_IN_CATALOG)
        self.assertEqual(ev_1["identityStatus"], STATUS_UNIQUE_IN_CATALOG)
        self.assertEqual(ev_1["candidateCount"], 1)
        self.assertEqual(ev_1["candidateCatalogId"], "image1-0-0")
        self.assertEqual(ev_1["candidateCatalogIds"], ["image1-0-0"])
        self.assertEqual(len(ev_1["rankedCandidates"]), 1)
        # 严禁写 reviewed truth / knownItems
        self.assertNotIn("knownItems", ev_1)
        self.assertNotIn("reviewedTruth", ev_1)

        # 3. 多 candidate: 真实 pixel/template 比对测试
        # 使用 4x4 red 候选 (image33-0-0, image35-1-0, image35-1-1)
        hyp_multi = {
            "groupingHypothesisId": "ghyp_test_multi",
            "rarity": "red",
            "gridShape": "4x4",
            "widthCells": 4,
            "heightCells": 4,
            "bbox": [0, 0, 100, 100],
        }
        candidates = resolver.resolve_candidates_for_hypothesis(hyp_multi)
        self.assertGreater(len(candidates), 1)

        # 3a. 无模板 / 未跑出有效分数时：禁止盲选 candidates[0]，必须保持 AMBIGUOUS_CANDIDATES
        ev_no_tpl = resolver.resolve_identity_evidence(hyp_multi, crop_image=np.zeros((100, 100, 3), dtype=np.uint8), templates={})
        self.assertEqual(ev_no_tpl["status"], STATUS_AMBIGUOUS_CANDIDATES)
        self.assertIsNone(ev_no_tpl["candidateCatalogId"])
        self.assertEqual(ev_no_tpl["candidateCount"], len(candidates))
        self.assertEqual(len(ev_no_tpl["rankedCandidates"]), len(candidates))
        self.assertEqual(ev_no_tpl["top1Score"], 0.0)
        self.assertEqual(ev_no_tpl["margin"], 0.0)

        # 构造确定性的合成像素 ROI 与候选模板
        roi = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.circle(roi, (50, 50), 30, (0, 0, 255), -1) # 显著红色中心特征
        cv2.rectangle(roi, (10, 10), (30, 30), (255, 255, 255), -1)

        # 模板 A: 完美匹配 roi
        tpl_a = roi.copy()
        # 模板 B: 明显不同的图案
        tpl_b = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.rectangle(tpl_b, (40, 40), (80, 80), (0, 255, 0), -1)
        # 模板 C: 类似图案但微弱不同
        tpl_c = roi.copy()
        cv2.circle(tpl_c, (50, 50), 10, (0, 0, 0), -1)

        target_cat_id_a = candidates[0]["catalogId"]
        target_cat_id_b = candidates[1]["catalogId"]

        mock_templates_strong = {
            target_cat_id_a: tpl_a,
            target_cat_id_b: tpl_b,
        }

        # 4. 强 Top1 + 足够 margin (>=0.85, margin>=0.08) -> EXACT_IDENTIFIED
        ev_exact = resolver.resolve_identity_evidence(
            hyp_multi,
            crop_image=roi,
            templates=mock_templates_strong,
            top1_threshold=DEFAULT_TOP1_SCORE_THRESHOLD,
            margin_threshold=DEFAULT_MARGIN_THRESHOLD,
        )
        self.assertEqual(ev_exact["status"], STATUS_EXACT_IDENTIFIED)
        self.assertEqual(ev_exact["candidateCatalogId"], target_cat_id_a)
        self.assertGreaterEqual(ev_exact["top1Score"], DEFAULT_TOP1_SCORE_THRESHOLD)
        self.assertGreaterEqual(ev_exact["margin"], DEFAULT_MARGIN_THRESHOLD)
        self.assertEqual(ev_exact["evidenceSource"], "PIXEL_TEMPLATE_MATCH")
        self.assertIsNotNone(ev_exact["templateReference"])
        # 验证 ranked candidates 保留完整
        self.assertEqual(len(ev_exact["rankedCandidates"]), len(candidates))
        self.assertEqual(ev_exact["rankedCandidates"][0]["candidateCatalogId"], target_cat_id_a)

        # 5. 弱 Top1 (Top1 分数未达 0.85 门槛) -> AMBIGUOUS_CANDIDATES
        # 给 tpl_a 增加严重干扰使匹配分数降低
        tpl_weak = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        mock_templates_weak = {
            target_cat_id_a: tpl_weak,
            target_cat_id_b: tpl_b,
        }
        ev_weak = resolver.resolve_identity_evidence(
            hyp_multi,
            crop_image=roi,
            templates=mock_templates_weak,
            top1_threshold=0.85,
            margin_threshold=0.08,
        )
        self.assertEqual(ev_weak["status"], STATUS_AMBIGUOUS_CANDIDATES)
        self.assertIsNone(ev_weak["candidateCatalogId"])
        self.assertEqual(len(ev_weak["rankedCandidates"]), len(candidates))

        # 6. Top1-vs-Top2 Margin 不足 (Margin < 0.08) -> AMBIGUOUS_CANDIDATES
        # 模板 A 和 模板 C 均与 ROI 极其接近
        mock_templates_narrow = {
            target_cat_id_a: tpl_a,
            target_cat_id_b: tpl_c,
        }
        ev_narrow = resolver.resolve_identity_evidence(
            hyp_multi,
            crop_image=roi,
            templates=mock_templates_narrow,
            top1_threshold=0.85,
            margin_threshold=0.20, # 设置较高 margin 门槛以模拟竞争激烈
        )
        self.assertEqual(ev_narrow["status"], STATUS_AMBIGUOUS_CANDIDATES)
        self.assertIsNone(ev_narrow["candidateCatalogId"])
        self.assertLess(ev_narrow["margin"], 0.20)
        self.assertEqual(len(ev_narrow["rankedCandidates"]), len(candidates))

        # 7. 验证真实 Settlement Frame (238s) 解析中的 identityEvidence 全覆盖
        frame = _load_frame()
        if frame is not None:
            ledger = rec.parse_settlement_ledger(frame, actual_total=631993)
            hypotheses = ledger.get("physicalGroupingHypotheses", [])
            self.assertGreater(len(hypotheses), 0)

            for h in hypotheses:
                # 验证每个 grouping hypothesis 均挂载 identityEvidence
                self.assertIn("identityEvidence", h)
                ev = h["identityEvidence"]
                self.assertIn(
                    ev["status"],
                    (STATUS_EXACT_IDENTIFIED, STATUS_AMBIGUOUS_CANDIDATES, STATUS_UNIQUE_IN_CATALOG, STATUS_NO_CATALOG_MATCH),
                )
                self.assertEqual(ev["candidateCount"], len(ev["candidateCatalogIds"]))
                self.assertEqual(ev["candidateCount"], len(ev["rankedCandidates"]))
                # 严禁在 hypothesis 顶层写入已知真实结论
                self.assertNotIn("catalogId", h)
                self.assertNotIn("name", h)
                self.assertNotIn("price", h)
                self.assertNotIn("knownItems", ledger)

    def test_sec488_does_not_claim_unverified_exact(self):
        path = os.path.join(PROJECT_ROOT, "assets", "settlement_frames", "sec_488.jpg")
        if not os.path.exists(path):
            self.skipTest("sec_488 missing")
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        rec = SettlementItemRecognizer()
        ledger = rec.parse_settlement_ledger(img)
        print("sec488 count", ledger["settlementItemCount"], "exact", ledger["settlementExactItemCount"])
        self.assertGreaterEqual(ledger["settlementItemCount"], 1)
        self.assertEqual(ledger["settlementExactItemCount"], 0)
        self.assertFalse(ledger["settlementLedgerVerified"])


if __name__ == "__main__":
    unittest.main()
