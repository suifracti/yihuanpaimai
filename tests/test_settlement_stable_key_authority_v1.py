# -*- coding: utf-8 -*-
"""Regression test suite for Settlement Stable-Key Authority (AC1 - AC6).

Verifies:
AC1: Timing & Identity Authority - CURRENT_MATCH.id propagates to pipeline.current_context['recordStableKey']
AC2: Stable Evidence Natural Persistence - descriptor created with evidenceId and matching recordStableKey
AC3: CurrentMatch Natural Attachment - settlementTruthEvidence and fileOriginals attached
AC4: Natural History Persistence - AutoArchiver saves truthEvidence to CanonicalHistoryStore
AC5: Presentation - SettlementReviewService loads screenshot
AC6: Fail Closed - No match identity provided results in no fake stable key
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "core"))
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from auto_archiver import AutoArchiver
from canonical_history_store import CanonicalHistoryStore
from current_match import CurrentMatch
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from settlement_review import SettlementReviewService
from vision_pipeline import NTEVisionPipeline
from vision_worker_loop import run_vision_capture_loop


class TestSettlementStableKeyAuthorityV1(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        os.environ["YIHUAN_DATA_ROOT"] = self.tmp_dir.name
        self.history_db_path = os.path.join(self.tmp_dir.name, "伂环拍卖数据.json")
        self.history_store = CanonicalHistoryStore(self.history_db_path)
        self.evidence_store = SettlementEvidenceStoreV2(self.tmp_dir.name)
        self.archiver = AutoArchiver(db_paths=[self.history_db_path])

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_production_settlement_stable_key_authority_e2e(self):
        current_match = CurrentMatch()
        expected_match_id = current_match.id
        self.assertTrue(expected_match_id.startswith("draft_"))

        pipeline = NTEVisionPipeline(catalog_path=str(PROJECT_ROOT / "assets" / "catalog_065.json"))
        pipeline._ensure_ocr()

        replay_assets_dir = PROJECT_ROOT / "assets" / "replay_frames"
        settle_assets_dir = PROJECT_ROOT / "assets" / "settlement_frames"

        selected_frames = [
            replay_assets_dir / "frame_0000s_00m00s.jpg",
            replay_assets_dir / "frame_0250s_04m10s.jpg",
            replay_assets_dir / "frame_0075s_01m15s.jpg",
            replay_assets_dir / "frame_0150s_02m30s.jpg",
            settle_assets_dir / "sec_478.jpg",
            settle_assets_dir / "sec_483.jpg",
            settle_assets_dir / "sec_488.jpg",
        ]

        frame_imgs = []
        for f in selected_frames:
            img = cv2.imread(str(f))
            self.assertIsNotNone(img, f"Missing frame {f}")
            frame_imgs.append(img)

        idx = [0]
        stop_flag = {"stop": False}

        def frame_provider():
            i = idx[0]
            if i >= len(frame_imgs):
                stop_flag["stop"] = True
                return None, None, ""
            img = frame_imgs[i]
            idx[0] += 1
            ts = datetime.now(timezone(timedelta(hours=8))).isoformat()
            return 12345, img, ts


        async def main():
            await run_vision_capture_loop(
                pipeline=pipeline,
                stop_flag=stop_flag,
                frame_provider=frame_provider,
                archiver=self.archiver,
                fps=50.0,
                current_match=current_match,
            )


        asyncio.run(main())

        ctx = pipeline.current_context

        # AC1: Current match ID and pipeline stable key match
        self.assertEqual(ctx.get("recordStableKey"), expected_match_id)

        # AC2: Stable Evidence
        file_evidence = ctx.get("settlementFileEvidence") or {}
        ev_id = file_evidence.get("evidenceId")
        rec_key = file_evidence.get("recordStableKey")
        self.assertIsNotNone(ev_id)
        self.assertEqual(rec_key, expected_match_id)

        # AC3: CurrentMatch Attachment
        cm_facts = current_match.facts
        cm_truth = cm_facts.get("settlementTruthEvidence") or cm_facts.get("settlementEvidence")
        self.assertIsNotNone(cm_truth)
        file_origs = cm_truth.get("fileOriginals", [])
        evidence_refs = cm_truth.get("evidenceReferences", [])
        self.assertGreater(len(file_origs), 0)
        self.assertGreater(len(evidence_refs), 0)
        self.assertEqual(file_origs[0]["evidenceId"], ev_id)

        # AC4: Natural History Persistence
        db = self.history_store.read_database()
        records = db.get("records", [])
        self.assertEqual(len(records), 1)
        saved_record = records[0]
        self.assertEqual(saved_record.get("id"), expected_match_id)
        self.assertIn(saved_record.get("lifecycleStatus"), ("DRAFT", "FINALIZED"))
        hist_truth = (saved_record.get("settlement") or {}).get("truthEvidence")
        self.assertIsNotNone(hist_truth)
        self.assertGreater(len(hist_truth.get("fileOriginals", [])), 0)
        self.assertEqual(hist_truth["fileOriginals"][0]["evidenceId"], ev_id)

        # AC5: Presentation
        review_svc = SettlementReviewService(
            data_root_provider=lambda: self.tmp_dir.name,
            history_path_provider=lambda: self.history_db_path,
        )
        session_res = review_svc.create_review_session(saved_record["id"], source="current")
        self.assertTrue(session_res.get("ok"))
        review_dto = session_res.get("review") or {}
        screenshot_info = review_dto.get("screenshot") or {}
        self.assertTrue(screenshot_info.get("available"))
        self.assertIsNotNone(screenshot_info.get("sha256"))

        # AC6: Fail Closed when no match identity provided
        pipe_fail_closed = NTEVisionPipeline(catalog_path=str(PROJECT_ROOT / "assets" / "catalog_065.json"))
        pipe_fail_closed._ensure_ocr()
        ctx_fc = pipe_fail_closed.process_frame(
            frame_imgs[-1],
            captured_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            record_stable_key=None,
        )
        self.assertIsNone(ctx_fc.get("recordStableKey"))
        self.assertIsNone(ctx_fc.get("settlementFileEvidence"))


if __name__ == "__main__":
    unittest.main()
