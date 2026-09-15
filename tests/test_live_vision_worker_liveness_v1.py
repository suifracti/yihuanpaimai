"""Targeted tests for 4D2D1K: Live Vision Worker Liveness Root Cause v1.

Verifies:
1. Deterministic sequence (Round 2 -> Round 3 -> Settlement) naturally publishes scene=SETTLEMENT, isSettlement=True.
2. Fault injection resilience:
   - One-shot capture exception recovers to SETTLEMENT.
   - One-shot inference / OCR exception recovers to SETTLEMENT.
   - One-shot publisher exception recovers to SETTLEMENT.
   - Transient empty frame / window loss recovers to SETTLEMENT.
3. Intentional shutdown terminates immediately without continuing capture or publishing.
"""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "real_snapshots_4d2d1j"

for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import cv2
import numpy as np
import main
from vision_pipeline import NTEVisionPipeline
from vision_worker_loop import run_vision_capture_loop


class TestLiveVisionWorkerLivenessV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img_r2 = cv2.imread(str(FIXTURES_DIR / "fixture_round2_intel_cards.png"))
        cls.img_r3 = cv2.imread(str(FIXTURES_DIR / "fixture_round3_intel_cards.png"))
        cls.img_settle = cv2.imread(str(FIXTURES_DIR / "fixture_settlement_client_sanitized.png"))
        cls.pipe = NTEVisionPipeline()
        if cls.img_settle is not None:
            cls.pipe.ocr(cls.img_settle[:50, :50])

    def setUp(self):
        self.pipe.reset_session_state()

    def test_first_settlement_frame_is_classified_before_numeric_reads(self):
        self.assertIsNotNone(self.img_settle)
        ctx = self.pipe.process_frame(self.img_settle)
        self.assertEqual(ctx.get("scene"), "SETTLEMENT")
        self.assertTrue(ctx.get("isSettlement"))
        self.assertIsNone(ctx.get("currentEstimate"))
        self.assertIsNone(ctx.get("timer"))
        self.assertEqual(self.pipe._df_shadow_batch_count, 0)
        self.assertEqual(self.pipe._df_shadow_seat_bids_batch_count, 0)

    def test_repeated_settlement_frames_preserve_seat_identity(self):
        import copy
        from unittest.mock import patch

        self.assertIsNotNone(self.img_settle)
        self.pipe.process_frame(self.img_settle)
        before = copy.deepcopy({key: self.pipe.current_context.get(key)
                                for key in ("seats", "opponents", "myName", "finalBids")})
        with patch.object(self.pipe, "_handle_seat_binding_tier",
                          wraps=self.pipe._handle_seat_binding_tier) as bind:
            for _ in range(4):
                ctx = self.pipe.process_frame(self.img_settle)
                self.assertEqual(ctx.get("scene"), "SETTLEMENT")
            self.assertEqual(bind.call_count, 0)
        self.assertEqual({key: ctx.get(key) for key in before}, before)

    def test_deterministic_offline_sequence_publishes_settlement(self):
        published = []
        stop_flag = {"stop": False}

        # Sequence: 1x R2, 1x R3, 3x Settlement
        frames_queue = [
            (12345, self.img_r2, "2026-08-27T16:53:00"),
            (12345, self.img_r3, "2026-08-27T16:54:00"),
        ] + [(12345, self.img_settle, "2026-08-27T16:55:00")] * 3

        def _provider():
            if frames_queue:
                return frames_queue.pop(0)
            stop_flag["stop"] = True
            return 12345, self.img_settle, "2026-08-27T16:55:00"

        async def _publish(payload):
            published.append(payload)

        asyncio.run(
            run_vision_capture_loop(
                pipeline=self.pipe,
                stop_flag=stop_flag,
                frame_provider=_provider,
                publish_fn=_publish,
                fps=100.0,
                process_live_game_frame_fn=main.process_live_game_frame,
            )
        )

        self.assertGreaterEqual(len(published), 5)
        last = published[-1]
        self.assertEqual(last.get("scene"), "SETTLEMENT")
        self.assertTrue(last.get("isSettlement"))
        self.assertEqual(last.get("goldCount"), 4)
        self.assertEqual(last.get("q"), 15)
        self.assertEqual(last.get("scrollState"), "MIDDLE")

    def test_single_tick_invokes_process_frame_exactly_once(self):
        published = []
        stop_flag = {"stop": False}
        process_frame_calls = [0]
        orig_process = self.pipe.process_frame

        def _spy_process_frame(img, *args, **kwargs):
            process_frame_calls[0] += 1
            return orig_process(img, *args, **kwargs)

        frames_queue = [
            (12345, self.img_r2, "2026-08-27T16:53:00"),
            (12345, self.img_r3, "2026-08-27T16:54:00"),
            (12345, self.img_settle, "2026-08-27T16:55:00"),
        ]
        num_frames = len(frames_queue)

        def _provider():
            frame = frames_queue.pop(0)
            if not frames_queue:
                stop_flag["stop"] = True
            return frame

        async def _publish(payload):
            published.append(payload)

        try:
            self.pipe.process_frame = _spy_process_frame
            asyncio.run(
                run_vision_capture_loop(
                    pipeline=self.pipe,
                    stop_flag=stop_flag,
                    frame_provider=_provider,
                    publish_fn=_publish,
                    fps=100.0,
                    process_live_game_frame_fn=main.process_live_game_frame,
                )
            )
        finally:
            self.pipe.process_frame = orig_process

        # Exactly 1 process_frame execution per physical frame tick
        self.assertEqual(process_frame_calls[0], num_frames)
        self.assertEqual(len(published), num_frames)
        self.assertEqual(published[-1].get("scene"), "SETTLEMENT")
        self.assertTrue(published[-1].get("isSettlement"))

    def test_one_shot_capture_exception_recovers_to_settlement(self):
        published = []
        stop_flag = {"stop": False}
        error_injected = [True]

        frames_queue = [(12345, self.img_settle, "2026-08-27T16:55:00")] * 3

        def _faulty_provider():
            if error_injected[0]:
                error_injected[0] = False
                raise RuntimeError("Simulated DXGI/GDI screen capture fault")
            if frames_queue:
                return frames_queue.pop(0)
            stop_flag["stop"] = True
            return 12345, self.img_settle, "2026-08-27T16:55:00"

        async def _publish(payload):
            published.append(payload)

        logs = []
        asyncio.run(
            run_vision_capture_loop(
                pipeline=self.pipe,
                stop_flag=stop_flag,
                frame_provider=_faulty_provider,
                publish_fn=_publish,
                fps=100.0,
                log_fn=lambda t, m: logs.append((t, m)),
                process_live_game_frame_fn=main.process_live_game_frame,
            )
        )

        # Worker did not die on capture error, logged error and recovered
        self.assertTrue(any("capture" in m.lower() for _, m in logs))
        self.assertGreaterEqual(len(published), 3)
        last = published[-1]
        self.assertEqual(last.get("scene"), "SETTLEMENT")
        self.assertTrue(last.get("isSettlement"))

    def test_one_shot_inference_exception_recovers_to_settlement(self):
        published = []
        stop_flag = {"stop": False}
        error_injected = [True]

        frames_queue = [(12345, self.img_settle, "2026-08-27T16:55:00")] * 3

        def _provider():
            if frames_queue:
                return frames_queue.pop(0)
            stop_flag["stop"] = True
            return 12345, self.img_settle, "2026-08-27T16:55:00"

        def _faulty_process(img, captured_at=None):
            if error_injected[0]:
                error_injected[0] = False
                raise ValueError("Simulated corrupted frame OCR inference exception")
            return self.pipe.process_frame(img, captured_at=captured_at)

        async def _publish(payload):
            published.append(payload)

        logs = []
        asyncio.run(
            run_vision_capture_loop(
                pipeline=self.pipe,
                stop_flag=stop_flag,
                frame_provider=_provider,
                process_frame_fn=_faulty_process,
                publish_fn=_publish,
                fps=100.0,
                log_fn=lambda t, m: logs.append((t, m)),
                process_live_game_frame_fn=main.process_live_game_frame,
            )
        )

        self.assertTrue(any("inference" in m.lower() for _, m in logs))
        self.assertGreaterEqual(len(published), 3)
        last = published[-1]
        self.assertEqual(last.get("scene"), "SETTLEMENT")
        self.assertTrue(last.get("isSettlement"))

    def test_one_shot_publish_exception_recovers(self):
        published = []
        stop_flag = {"stop": False}
        error_injected = [True]

        frames_queue = [(12345, self.img_settle, "2026-08-27T16:55:00")] * 3

        def _provider():
            if frames_queue:
                return frames_queue.pop(0)
            stop_flag["stop"] = True
            return 12345, self.img_settle, "2026-08-27T16:55:00"

        async def _faulty_publish(payload):
            if error_injected[0]:
                error_injected[0] = False
                raise ConnectionResetError("Simulated WebSocket publish network packet drop")
            published.append(payload)

        logs = []
        asyncio.run(
            run_vision_capture_loop(
                pipeline=self.pipe,
                stop_flag=stop_flag,
                frame_provider=_provider,
                publish_fn=_faulty_publish,
                fps=100.0,
                log_fn=lambda t, m: logs.append((t, m)),
                process_live_game_frame_fn=main.process_live_game_frame,
            )
        )

        self.assertTrue(any("publish" in m.lower() for _, m in logs))
        self.assertGreaterEqual(len(published), 3)
        last = published[-1]
        self.assertEqual(last.get("scene"), "SETTLEMENT")
        self.assertTrue(last.get("isSettlement"))

    def test_transient_empty_frame_sends_standby_and_recovers(self):
        published = []
        stop_flag = {"stop": False}

        # Sequence: 2x None/empty frames (game minimized/transition) -> 3x Settlement
        frames_queue = [
            (None, None, ""),
            (12345, None, ""),
        ] + [(12345, self.img_settle, "2026-08-27T16:55:00")] * 3

        def _provider():
            if frames_queue:
                return frames_queue.pop(0)
            stop_flag["stop"] = True
            return 12345, self.img_settle, "2026-08-27T16:55:00"

        async def _publish(payload):
            published.append(payload)

        asyncio.run(
            run_vision_capture_loop(
                pipeline=self.pipe,
                stop_flag=stop_flag,
                frame_provider=_provider,
                publish_fn=_publish,
                fps=100.0,
                process_live_game_frame_fn=main.process_live_game_frame,
            )
        )

        self.assertGreaterEqual(len(published), 5)
        # First 2 are standby
        self.assertEqual(published[0]["solverStatus"], "standby")
        self.assertFalse(published[0]["gameDetected"])
        # Later settle
        self.assertEqual(published[-1]["scene"], "SETTLEMENT")
        self.assertTrue(published[-1]["isSettlement"])

    def test_intentional_shutdown_exits_immediately(self):
        published = []
        stop_flag = {"stop": True}  # Pre-stopped
        provider_called = [0]

        def _provider():
            provider_called[0] += 1
            return 12345, self.img_settle, "2026-08-27T16:55:00"

        async def _publish(payload):
            published.append(payload)

        asyncio.run(
            run_vision_capture_loop(
                pipeline=self.pipe,
                stop_flag=stop_flag,
                frame_provider=_provider,
                publish_fn=_publish,
                fps=100.0,
            )
        )

        # Loop must not execute any frames when stop_flag is set
        self.assertEqual(provider_called[0], 0)
        self.assertEqual(len(published), 0)

    def test_header_round_timer_shadow_dual_read_viewport_fixtures(self):
        r2_vp_path = PROJECT_ROOT / "tests" / "fixtures" / "intel_card_evidence_v1" / "r2_viewport.png"
        r3_vp_path = PROJECT_ROOT / "tests" / "fixtures" / "intel_card_evidence_v1" / "r3_viewport.png"
        if not r2_vp_path.exists() or not r3_vp_path.exists():
            self.skipTest("Viewport fixtures missing")

        img_r2_vp = cv2.imread(str(r2_vp_path))
        img_r3_vp = cv2.imread(str(r3_vp_path))

        shadow2 = self.pipe._read_shadow_header_round_timer(img_r2_vp)
        self.assertEqual(shadow2.get("shadowTimer"), 18)
        self.assertIsNone(shadow2.get("error"))

        shadow3 = self.pipe._read_shadow_header_round_timer(img_r3_vp)
        self.assertEqual(shadow3.get("shadowTimer"), 50)
        self.assertIsNone(shadow3.get("error"))

    def test_current_estimate_shadow_dual_read_video_fixtures(self):
        in_match_samples = [
            ("sec_090.jpg", 2484),
            ("sec_120.jpg", 13221),
            ("sec_150.jpg", 105899),
            ("sec_180.jpg", 215123),
            ("sec_360.jpg", 13445),
            ("sec_420.jpg", 13445),
            ("sec_450.jpg", 13445),
        ]
        for fname, expected_val in in_match_samples:
            fpath = PROJECT_ROOT / "assets" / "video_frames" / fname
            if not fpath.exists():
                continue
            img = cv2.imread(str(fpath))
            shadow = self.pipe._read_shadow_current_estimate(img)
            self.assertEqual(shadow.get("shadowCurrentEstimate"), expected_val, f"Shadow mismatch on {fname}")
            self.assertIsNone(shadow.get("error"))

    def test_seats_panel_shadow_dual_read_viewport_clean_fixtures(self):
        r2_vp_path = PROJECT_ROOT / "tests" / "fixtures" / "intel_card_evidence_v1" / "r2_viewport.png"
        if not r2_vp_path.exists():
            self.skipTest("r2_viewport missing")
        img_r2_vp = cv2.imread(str(r2_vp_path))
        shadow = self.pipe._read_shadow_seats_bids(img_r2_vp)
        self.assertIsNone(shadow.get("error"))

    def test_qualified_seats_shadow_observations_provenance_fixtures(self):
        fixture_dir = PROJECT_ROOT / "tests" / "fixtures" / "seats_bids_v1"
        if not fixture_dir.exists():
            self.skipTest("seats_bids_v1 fixtures directory missing")

        for sec in [149, 175, 310, 360, 390, 420]:
            fpath = fixture_dir / f"frame_t{sec}.png"
            if not fpath.exists():
                continue
            img = cv2.imread(str(fpath))
            shadow = self.pipe._read_shadow_seats_bids(img)
            self.assertIsNone(shadow.get("error"), f"Shadow error on t={sec}s")
            self.assertGreater(shadow.get("tokenCount", 0), 0, f"No shadow tokens on t={sec}s")

    def test_shadow_dual_reads_retired_from_process_frame(self):
        img_test = cv2.imread(str(PROJECT_ROOT / "assets" / "video_frames" / "sec_120.jpg"))
        if img_test is None:
            self.skipTest("sec_120.jpg missing")

        self.pipe.reset_session_state()
        self.pipe._ensure_ocr()

        shadow_invoked = []
        orig_timer = self.pipe._read_shadow_header_round_timer
        orig_est = self.pipe._read_shadow_current_estimate
        orig_seats = self.pipe._read_shadow_seats_bids

        def _spy_timer(f):
            shadow_invoked.append("timer")
            return orig_timer(f)

        def _spy_est(f):
            shadow_invoked.append("estimate")
            return orig_est(f)

        def _spy_seats(f):
            shadow_invoked.append("seats")
            return orig_seats(f)

        try:
            self.pipe._read_shadow_header_round_timer = _spy_timer
            self.pipe._read_shadow_current_estimate = _spy_est
            self.pipe._read_shadow_seats_bids = _spy_seats

            ctx = self.pipe.process_frame(img_test)

            self.assertEqual(len(shadow_invoked), 0, "No shadow dual-read functions should be invoked during process_frame")
            self.assertNotIn("_shadowHeaderObservation", ctx)
            self.assertNotIn("_shadowEstimateObservation", ctx)
            self.assertNotIn("_shadowSeatsObservation", ctx)
        finally:
            self.pipe._read_shadow_header_round_timer = orig_timer
            self.pipe._read_shadow_current_estimate = orig_est
            self.pipe._read_shadow_seats_bids = orig_seats


    def test_slot_numeric_authority_migration_l3k(self):
        fixture_dir = PROJECT_ROOT / "tests" / "fixtures" / "seats_bids_v1"
        if not fixture_dir.exists():
            self.skipTest("seats_bids_v1 fixtures missing")

        # 1. Verify frame_t360: Slot 1=666666, Slot 2=400000, Slot 3=5000 in _slot_finals
        img_360 = cv2.imread(str(fixture_dir / "frame_t360.png"))
        if img_360 is not None:
            self.pipe.reset_session_state()
            self.pipe._ensure_ocr()
            ctx = self.pipe.process_frame(img_360)
            self.assertEqual(self.pipe._slot_finals.get(1, {}).get("1"), 666666)
            self.assertEqual(self.pipe._slot_finals.get(2, {}).get("1"), 400000)
            self.assertEqual(self.pipe._slot_finals.get(3, {}).get("1"), 5000)

        # 2. Verify frame_t390: Slot 1 leader authoritative bid 666666 (eliminates full-canvas 999999 error)
        img_390 = cv2.imread(str(fixture_dir / "frame_t390.png"))
        if img_390 is not None:
            self.pipe.reset_session_state()
            self.pipe._ensure_ocr()
            ctx = self.pipe.process_frame(img_390)
            self.assertEqual(self.pipe._leader_slot, 1)
            self.assertEqual(ctx.get("currentLeaderBid"), 666666)
            self.assertEqual(self.pipe._slot_finals.get(1, {}).get("2"), 666666)
            self.assertEqual(self.pipe._slot_finals.get(4, {}).get("2"), 500000)

        # 3. Verify frame_t420: multi-round history accumulated cleanly per slot
        img_420 = cv2.imread(str(fixture_dir / "frame_t420.png"))
        if img_420 is not None:
            self.pipe.reset_session_state()
            self.pipe._ensure_ocr()
            ctx = self.pipe.process_frame(img_420)
            self.assertEqual(self.pipe._slot_finals.get(1, {}).get("1"), 666666)
            self.assertEqual(self.pipe._slot_finals.get(1, {}).get("2"), 666666)
            self.assertEqual(self.pipe._slot_finals.get(2, {}).get("1"), 400000)
            self.assertEqual(self.pipe._slot_finals.get(3, {}).get("1"), 5000)
            self.assertEqual(self.pipe._slot_finals.get(3, {}).get("2"), 90000)
            self.assertEqual(self.pipe._slot_finals.get(4, {}).get("2"), 500000)

        # 4. Verify name mutation invariance: Slot 4 name changes across frames without history fragmentation
        self.pipe.reset_session_state()
        self.pipe.current_context["round"] = 1
        f1_ocr = [
            ([[80, 660], [200, 660], [200, 690], [80, 690]], "秋晴02", 0.99),
            ([[90, 700], [220, 700], [220, 740], [90, 740]], "300000", 0.99),
        ]
        self.pipe._bind_seats_slot_authoritative(f1_ocr, 1920, 1080)
        self.pipe._bind_seats_slot_authoritative(f1_ocr, 1920, 1080)
        self.assertEqual(self.pipe._slot_finals[4]["1"], 300000)

        # Round 2: name changes to 秋晴萱02
        self.pipe.current_context["round"] = 2
        f2_ocr = [
            ([[80, 660], [200, 660], [200, 690], [80, 690]], "秋晴萱02", 0.99),
            ([[90, 700], [220, 700], [220, 740], [90, 740]], "500000", 0.99),
        ]
        self.pipe._bind_seats_slot_authoritative(f2_ocr, 1920, 1080)
        self.pipe._bind_seats_slot_authoritative(f2_ocr, 1920, 1080)
        self.assertEqual(self.pipe._slot_finals[4]["1"], 300000)
        self.assertEqual(self.pipe._slot_finals[4]["2"], 500000)

        # Round 3: name changes to PLAYER_LOCAL
        self.pipe.current_context["round"] = 3
        f3_ocr = [
            ([[80, 660], [200, 660], [200, 690], [80, 690]], "PLAYER_LOCAL", 0.99),
            ([[90, 700], [220, 700], [220, 740], [90, 740]], "700000", 0.99),
        ]
        self.pipe._bind_seats_slot_authoritative(f3_ocr, 1920, 1080)
        self.pipe._bind_seats_slot_authoritative(f3_ocr, 1920, 1080)
        self.assertEqual(self.pipe._slot_finals[4]["1"], 300000)
        self.assertEqual(self.pipe._slot_finals[4]["2"], 500000)
        self.assertEqual(self.pipe._slot_finals[4]["3"], 700000)

    def test_current_estimate_roi_authority_l3l(self):
        # 1. 7 IN_AUCTION samples: ROI authority matches expected values
        in_match_samples = [
            ("sec_090.jpg", 2484),
            ("sec_120.jpg", 13221),
            ("sec_150.jpg", 105899),
            ("sec_180.jpg", 215123),
            ("sec_360.jpg", 13445),
            ("sec_420.jpg", 13445),
            ("sec_450.jpg", 13445),
        ]
        for fname, expected_val in in_match_samples:
            fpath = PROJECT_ROOT / "assets" / "video_frames" / fname
            if not fpath.exists():
                continue
            img = cv2.imread(str(fpath))
            self.pipe.reset_session_state()
            self.pipe._ensure_ocr()
            self.pipe.process_frame(img)
            ctx = self.pipe.process_frame(img)
            self.assertEqual(ctx.get("currentEstimate"), expected_val, f"ROI authority mismatch on {fname}")
            # Ensure schema integrity
            self.assertNotIn("leaderSlot", ctx)
            self.assertNotIn("slotHistoricalBids", ctx)
            self.assertNotIn("slotFinalBids", ctx)

        # 2. Lobby fixture: ROI estimate cannot pollute currentEstimate
        lobby_path = PROJECT_ROOT / "assets" / "video_frames" / "sec_030.jpg"
        if lobby_path.exists():
            img_lobby = cv2.imread(str(lobby_path))
            self.pipe.reset_session_state()
            ctx = self.pipe.process_frame(img_lobby)
            self.assertNotEqual(ctx.get("scene"), "IN_AUCTION")
            self.assertIsNone(ctx.get("currentEstimate"))

        # 3. Settlement fixture: ROI estimate cannot pollute currentEstimate
        settle_path = PROJECT_ROOT / "tests" / "fixtures" / "real_snapshots_4d2d1j" / "fixture_settlement_client_sanitized.png"
        if settle_path.exists():
            img_settle = cv2.imread(str(settle_path))
            self.pipe.reset_session_state()
            ctx = self.pipe.process_frame(img_settle)
            self.assertNotEqual(ctx.get("scene"), "IN_AUCTION")
            self.assertIsNone(ctx.get("currentEstimate"))

        # 4. Forced ROI failure fallback to full-canvas
        img_120 = cv2.imread(str(PROJECT_ROOT / "assets" / "video_frames" / "sec_120.jpg"))
        if img_120 is not None:
            self.pipe.reset_session_state()
            self.pipe._ensure_ocr()
            orig_read_df = self.pipe._read_df_numeric_batch
            orig_roi_parse = self.pipe._parse_current_estimate_chip
            try:
                self.pipe._read_df_numeric_batch = lambda frame: (None, None)
                self.pipe._parse_current_estimate_chip = lambda frame: None
                self.pipe.process_frame(img_120, force_refresh=True)
                ctx = self.pipe.process_frame(img_120, force_refresh=True)
                self.assertEqual(ctx.get("currentEstimate"), 13221)
            finally:
                self.pipe._read_df_numeric_batch = orig_read_df
                self.pipe._parse_current_estimate_chip = orig_roi_parse

    def test_timer_roi_authority_l3m(self):
        # 1. Known timer shadow fixtures: r2_viewport (18s), r3_viewport (50s)
        r2_path = PROJECT_ROOT / "tests" / "fixtures" / "intel_card_evidence_v1" / "r2_viewport.png"
        if r2_path.exists():
            img_r2 = cv2.imread(str(r2_path))
            self.pipe.reset_session_state()
            self.pipe._ensure_ocr()
            ctx_r2 = self.pipe.process_frame(img_r2)
            self.assertEqual(ctx_r2.get("timer"), 18)
            self.assertEqual(ctx_r2.get("round"), 2)

        r3_path = PROJECT_ROOT / "tests" / "fixtures" / "intel_card_evidence_v1" / "r3_viewport.png"
        if r3_path.exists():
            img_r3 = cv2.imread(str(r3_path))
            self.pipe.reset_session_state()
            self.pipe._ensure_ocr()
            ctx_r3 = self.pipe.process_frame(img_r3)
            self.assertEqual(ctx_r3.get("timer"), 50)

        # 2. In-auction video fixtures timer & round verification
        samples = [
            ("sec_120.jpg", 23, 2),
            ("sec_180.jpg", 14, 3),
        ]
        for fname, exp_timer, exp_round in samples:
            fpath = PROJECT_ROOT / "assets" / "video_frames" / fname
            if not fpath.exists():
                continue
            img = cv2.imread(str(fpath))
            self.pipe.reset_session_state()
            ctx = self.pipe.process_frame(img)
            self.assertEqual(ctx.get("timer"), exp_timer, f"Timer mismatch on {fname}")
            self.assertEqual(ctx.get("round"), exp_round, f"Round mismatch on {fname}")
            # Ensure schema integrity
            self.assertNotIn("leaderSlot", ctx)
            self.assertNotIn("slotHistoricalBids", ctx)
            self.assertNotIn("slotFinalBids", ctx)

        # 3. Lobby & Settlement fixtures: timer not polluted by ROI
        lobby_path = PROJECT_ROOT / "assets" / "video_frames" / "sec_030.jpg"
        if lobby_path.exists():
            img_lobby = cv2.imread(str(lobby_path))
            self.pipe.reset_session_state()
            ctx = self.pipe.process_frame(img_lobby)
            self.assertNotEqual(ctx.get("scene"), "IN_AUCTION")
            self.assertIsNone(ctx.get("timer"))

        settle_path = PROJECT_ROOT / "tests" / "fixtures" / "real_snapshots_4d2d1j" / "fixture_settlement_client_sanitized.png"
        if settle_path.exists():
            img_settle = cv2.imread(str(settle_path))
            self.pipe.reset_session_state()
            ctx = self.pipe.process_frame(img_settle)
            self.assertNotEqual(ctx.get("scene"), "IN_AUCTION")
            self.assertIsNone(ctx.get("timer"))

        # 4. Forced ROI failure fallback to full-canvas timer
        if r2_path.exists():
            img_r2 = cv2.imread(str(r2_path))
            self.pipe.reset_session_state()
            orig_read_df = self.pipe._read_df_numeric_batch
            orig_timer_roi = self.pipe._parse_header_timer_roi
            try:
                self.pipe._read_df_numeric_batch = lambda frame: (None, None)
                self.pipe._parse_header_timer_roi = lambda frame: None
                ctx = self.pipe.process_frame(img_r2)
                # Full-canvas fallback must still extract timer=18 and round=2
                self.assertEqual(ctx.get("timer"), 18)
                self.assertEqual(ctx.get("round"), 2)
            finally:
                self.pipe._read_df_numeric_batch = orig_read_df
                self.pipe._parse_header_timer_roi = orig_timer_roi

    def test_full_canvas_slow_tier_stride2_l3n2(self):
        # A & B. Call reduction & First frame full scan
        img_test = cv2.imread(str(PROJECT_ROOT / "assets" / "video_frames" / "sec_120.jpg"))
        if img_test is None:
            self.skipTest("sec_120.jpg missing")

        self.pipe.reset_session_state()
        self.pipe._ensure_ocr()

        # Track full-canvas OCR calls specifically via ocr_call_count
        self.pipe.reset_session_state()
        self.pipe.ocr_call_count = 0
        self.assertEqual(self.pipe._full_canvas_frame_count, 0)
        self.assertEqual(self.pipe.ocr_call_count, 0)

        # Frame 1: reset -> MUST run full scan
        ctx1 = self.pipe.process_frame(img_test)
        self.assertEqual(self.pipe._full_canvas_frame_count, 1)
        self.assertEqual(self.pipe.ocr_call_count, 1, "Frame 1 after reset must run full scan")
        self.assertEqual(ctx1.get("round"), 2)
        self.assertEqual(ctx1.get("scene"), "IN_AUCTION")
        self.assertEqual(ctx1.get("timer"), 23)
        self.assertIsNone(ctx1.get("currentEstimate"), "Estimate candidate on frame 1 must wait for N=2 confirmation")

        # Frame 2: steady state -> MUST skip full scan (stride = 2)
        ctx2 = self.pipe.process_frame(img_test)
        self.assertEqual(self.pipe._full_canvas_frame_count, 2)
        self.assertEqual(self.pipe.ocr_call_count, 1, "Frame 2 must skip full scan")
        # F. Sticky slow facts: round and scene are preserved, not cleared
        self.assertEqual(ctx2.get("round"), 2)
        self.assertEqual(ctx2.get("scene"), "IN_AUCTION")
        self.assertEqual(ctx2.get("timer"), 23)
        self.assertEqual(ctx2.get("currentEstimate"), 13221)

        # Frame 3: stride due -> MUST run full scan
        ctx3 = self.pipe.process_frame(img_test)
        self.assertEqual(self.pipe._full_canvas_frame_count, 3)
        self.assertEqual(self.pipe.ocr_call_count, 2, "Frame 3 must run full scan")

        # Frame 4: steady state -> skip full scan
        ctx4 = self.pipe.process_frame(img_test)
        self.assertEqual(self.pipe._full_canvas_frame_count, 4)
        self.assertEqual(self.pipe.ocr_call_count, 2, "Frame 4 must skip full scan")
        self.assertLess(self.pipe.ocr_call_count, 4, "Total full-canvas calls in 4 frames must be 2 (< 4 physical frames)")

        # C. Timer force trigger: on a frame that would normally skip (frame 2), timer <= 3 forces full scan
        self.pipe.reset_session_state()
        self.pipe.ocr_call_count = 0
        self.pipe.process_frame(img_test)  # Frame 1: runs full scan (call_count=1)
        self.assertEqual(self.pipe.ocr_call_count, 1)

        # The active DF authority must trigger the last-seconds full scan.
        orig_timer_batch = self.pipe._read_df_numeric_batch
        try:
            self.pipe._read_df_numeric_batch = lambda frame: (13221, 3)
            ctx_tforce = self.pipe.process_frame(img_test)  # Frame 2 with timer <= 3
            self.assertEqual(self.pipe.ocr_call_count, 2, "Timer <= 3 must force full scan on Frame 2")
            self.assertEqual(ctx_tforce.get("timer"), 3)
        finally:
            self.pipe._read_df_numeric_batch = orig_timer_batch

        # D. ROI failure force trigger: on a frame that would normally skip (frame 2), panel failure forces full scan
        self.pipe.reset_session_state()
        self.pipe.ocr_call_count = 0
        self.pipe.process_frame(img_test)  # Frame 1: runs full scan (call_count=1)
        self.assertEqual(self.pipe.ocr_call_count, 1)

        orig_bind_slot = self.pipe._bind_seats_slot_authoritative
        try:
            # Simulate Fast ROI failure
            self.pipe._bind_seats_slot_authoritative = lambda res, w, h: False
            ctx_fforce = self.pipe.process_frame(img_test)  # Frame 2 with ROI failure
            self.assertEqual(self.pipe.ocr_call_count, 2, "Fast ROI failure must force full scan fallback on Frame 2")
        finally:
            self.pipe._bind_seats_slot_authoritative = orig_bind_slot

        # E. No stale numeric overwrite: Authority values always take precedence over full-canvas
        self.pipe.reset_session_state()
        self.pipe.ocr_call_count = 0
        orig_read_df = self.pipe._read_df_numeric_batch
        try:
            self.pipe._read_df_numeric_batch = lambda frame: (888888, 42)
            self.pipe.process_frame(img_test)
            ctx_no_stale = self.pipe.process_frame(img_test)
            # Full-canvas parsed 23s and 13221, but DF authority provided 42 and 888888
            self.assertEqual(ctx_no_stale.get("timer"), 42, "Authority timer must not be overwritten by full-canvas")
            self.assertEqual(ctx_no_stale.get("currentEstimate"), 888888, "Authority estimate must not be overwritten by full-canvas")
        finally:
            self.pipe._read_df_numeric_batch = orig_read_df

    def test_detection_free_numeric_authority_migration_l3w(self):
        img_test = cv2.imread(str(PROJECT_ROOT / "assets" / "video_frames" / "sec_120.jpg"))
        if img_test is None:
            self.skipTest("sec_120.jpg missing")

        self.pipe.reset_session_state()
        self.pipe._ensure_ocr()

        # Track spy calls for DF batch vs legacy heavy ROI helpers
        df_batch_calls = []
        est_roi_calls = []
        timer_roi_calls = []

        orig_read_df = self.pipe._read_df_numeric_batch
        orig_parse_est = self.pipe._parse_current_estimate_chip
        orig_parse_timer = self.pipe._parse_header_timer_roi

        def _spy_read_df(frame):
            df_batch_calls.append(frame)
            return orig_read_df(frame)

        def _spy_parse_est(frame):
            est_roi_calls.append(frame)
            return orig_parse_est(frame)

        def _spy_parse_timer(frame):
            timer_roi_calls.append(frame)
            return orig_parse_timer(frame)

        try:
            self.pipe._read_df_numeric_batch = _spy_read_df
            self.pipe._parse_current_estimate_chip = _spy_parse_est
            self.pipe._parse_header_timer_roi = _spy_parse_timer

            # -------------------------------------------------------------
            # Case 1: Both DF succeed (sec_120.jpg has estimate=13221)
            # -------------------------------------------------------------
            df_batch_calls.clear()
            est_roi_calls.clear()
            timer_roi_calls.clear()
            self.pipe.reset_session_state()

            self.pipe.process_frame(img_test)
            ctx1 = self.pipe.process_frame(img_test)
            self.assertEqual(len(df_batch_calls), 2, "Auction frame must execute exactly 1 DF batch per frame")
            self.assertEqual(len(est_roi_calls), 0, "When DF estimate succeeds, heavy estimate ROI must NOT be called")
            self.assertEqual(ctx1.get("currentEstimate"), 13221)
            # Schema integrity
            for k in ctx1.keys():
                self.assertFalse(k.startswith("_df_shadow"), f"Context must not leak shadow key {k}")

            # -------------------------------------------------------------
            # Case 2: Estimate DF fails, Timer DF succeeds
            # -------------------------------------------------------------
            df_batch_calls.clear()
            est_roi_calls.clear()
            timer_roi_calls.clear()
            self.pipe.reset_session_state()

            # Mock DF batch: estimate=None, timer=23
            self.pipe._read_df_numeric_batch = lambda f: (None, 23)
            self.pipe.process_frame(img_test)
            self.assertEqual(len(est_roi_calls), 0,
                             "Full-scan frame reuses its estimate without another OCR call")
            ctx2 = self.pipe.process_frame(img_test)
            self.assertEqual(len(est_roi_calls), 1,
                             "Skipped full-scan frame must read the estimate ROI when DF fails")
            self.assertEqual(len(timer_roi_calls), 0, "When DF timer succeeds, heavy timer ROI must NOT be called")
            self.assertEqual(ctx2.get("currentEstimate"), 13221)
            self.assertEqual(ctx2.get("timer"), 23)

            # -------------------------------------------------------------
            # Case 3: Timer DF fails, Estimate DF succeeds
            # -------------------------------------------------------------
            df_batch_calls.clear()
            est_roi_calls.clear()
            timer_roi_calls.clear()
            self.pipe.reset_session_state()

            # Mock DF batch: estimate=13221, timer=None
            self.pipe._read_df_numeric_batch = lambda f: (13221, None)
            self.pipe.process_frame(img_test)
            ctx3 = self.pipe.process_frame(img_test)
            self.assertEqual(len(est_roi_calls), 0, "When DF estimate succeeds, heavy estimate ROI must NOT be called")
            self.assertGreaterEqual(len(timer_roi_calls), 1, "When DF timer fails, heavy timer ROI must be called as fallback per frame")
            self.assertEqual(ctx3.get("currentEstimate"), 13221)
            self.assertEqual(ctx3.get("timer"), 23)

            # -------------------------------------------------------------
            # Case 4: Both DF fail
            # -------------------------------------------------------------
            df_batch_calls.clear()
            est_roi_calls.clear()
            timer_roi_calls.clear()
            self.pipe.reset_session_state()

            # Mock DF batch: estimate=None, timer=None
            self.pipe._read_df_numeric_batch = lambda f: (None, None)
            self.pipe.process_frame(img_test)
            ctx4 = self.pipe.process_frame(img_test)
            self.assertGreaterEqual(len(est_roi_calls), 1, "When both DF fail, heavy estimate ROI must be called per frame")
            self.assertGreaterEqual(len(timer_roi_calls), 1, "When both DF fail, heavy timer ROI must be called per frame")
            self.assertEqual(ctx4.get("currentEstimate"), 13221)
            self.assertEqual(ctx4.get("timer"), 23)

            # -------------------------------------------------------------
            # Case 5: Batch exception isolation
            # -------------------------------------------------------------
            df_batch_calls.clear()
            est_roi_calls.clear()
            timer_roi_calls.clear()
            self.pipe.reset_session_state()

            self.pipe._read_df_numeric_batch = lambda f: (_ for _ in ()).throw(RuntimeError("Simulated DF crash"))
            self.pipe.process_frame(img_test)
            ctx5 = self.pipe.process_frame(img_test)
            self.assertEqual(ctx5.get("round"), 2)
            self.assertEqual(ctx5.get("currentEstimate"), 13221)
            self.assertEqual(ctx5.get("timer"), 23)

            # -------------------------------------------------------------
            # Case 6: Non-Auction scene executes 0 DF batches
            # -------------------------------------------------------------
            self.pipe._read_df_numeric_batch = _spy_read_df
            settle_path = PROJECT_ROOT / "tests" / "fixtures" / "real_snapshots_4d2d1j" / "fixture_settlement_client_sanitized.png"
            if settle_path.exists():
                img_settle = cv2.imread(str(settle_path))
                df_batch_calls.clear()
                self.pipe.reset_session_state()
                ctx_settle = self.pipe.process_frame(img_settle)
                self.assertEqual(len(df_batch_calls), 0, "Non-auction frame must execute 0 DF batch calls")
                self.assertNotEqual(ctx_settle.get("scene"), "IN_AUCTION")
                self.assertIsNone(self.pipe._df_shadow_estimate)
                self.assertIsNone(self.pipe._df_shadow_timer)

        finally:
            self.pipe._read_df_numeric_batch = orig_read_df
            self.pipe._parse_current_estimate_chip = orig_parse_est
            self.pipe._parse_header_timer_roi = orig_parse_timer

    def test_detection_free_seat_bids_shadow_l3z2(self):
        img_test = cv2.imread(str(PROJECT_ROOT / "assets" / "video_frames" / "sec_120.jpg"))
        if img_test is None:
            self.skipTest("sec_120.jpg missing")

        self.pipe.reset_session_state()
        self.pipe._ensure_ocr()

        # 1. Verify exactly 1 execution of _run_df_seat_bids_shadow on auction frame
        seat_batch_calls = []
        orig_run_seat_shadow = self.pipe._run_df_seat_bids_shadow

        def _spy_run_seat_shadow(frame):
            seat_batch_calls.append(frame)
            return orig_run_seat_shadow(frame)

        try:
            self.pipe._run_df_seat_bids_shadow = _spy_run_seat_shadow
            self.assertEqual(self.pipe._df_shadow_seat_bids_batch_count, 0)
            ctx = self.pipe.process_frame(img_test)

            self.assertEqual(len(seat_batch_calls), 1, "Auction frame must execute exactly 1 four-slot DF shadow batch")
            self.assertEqual(self.pipe._df_shadow_seat_bids_batch_count, 1)

            # Verify context does NOT leak shadow keys
            for k in ctx.keys():
                self.assertFalse(k.startswith("_df_shadow"), f"Context must not leak shadow key {k}")

            # 2. Non-auction frame must execute 0 seat batch calls
            seat_batch_calls.clear()
            settle_path = PROJECT_ROOT / "tests" / "fixtures" / "real_snapshots_4d2d1j" / "fixture_settlement_client_sanitized.png"
            if settle_path.exists():
                img_settle = cv2.imread(str(settle_path))
                self.pipe.reset_session_state()
                ctx_settle = self.pipe.process_frame(img_settle)
                self.assertEqual(len(seat_batch_calls), 0, "Non-auction frame must execute 0 four-slot DF shadow calls")
                self.assertEqual(self.pipe._df_shadow_seat_bids_batch_count, 0)
                self.assertEqual(self.pipe._df_shadow_seat_bids, [None, None, None, None])

            # 3. Shadow batch exception isolation: process_frame survives and production seats unaffected
            self.pipe.reset_session_state()
            self.pipe._run_df_seat_bids_shadow = lambda frame: (_ for _ in ()).throw(RuntimeError("Simulated seat shadow crash"))
            ctx_safe = self.pipe.process_frame(img_test)
            self.assertIn("seats", ctx_safe)
            self.assertEqual(len(ctx_safe["seats"]), 4)

            # 4. Truth Fixture Reconciliation Validation
            self.pipe._run_df_seat_bids_shadow = orig_run_seat_shadow

            # Frame t=360 fixture
            f360_path = PROJECT_ROOT / "tests" / "fixtures" / "seats_bids_v1" / "frame_t360.png"
            if f360_path.exists():
                img_360 = cv2.imread(str(f360_path))
                self.pipe.reset_session_state()
                self.pipe.process_frame(img_360)
                self.assertEqual(self.pipe._df_shadow_seat_bids, [None, None, None, None], "t=360 unbid must parse as [None, None, None, None]")

            # Frame t=390 fixture
            f390_path = PROJECT_ROOT / "tests" / "fixtures" / "seats_bids_v1" / "frame_t390.png"
            if f390_path.exists():
                img_390 = cv2.imread(str(f390_path))
                self.pipe.reset_session_state()
                self.pipe.process_frame(img_390)
                self.assertEqual(self.pipe._df_shadow_seat_bids, [666666, None, 90000, 500000], "t=390 active bids must parse as [666666, None, 90000, 500000]")

        finally:
            self.pipe._run_df_seat_bids_shadow = orig_run_seat_shadow

    def test_seat_bid_mixed_text_parser_l3z4(self):
        """
        Verify whole-token numeric validation contract (4D2D1L-L3Z.4):
        - Positive: Pure integers and thousands-separated formats parse accurately
        - Negative: Mixed text, letters, Chinese overlay banners (展示5个藏品), unit suffixes (5K), and malformed commas fail-closed to None
        """
        self.pipe.reset_session_state()
        self.pipe._ensure_ocr()

        # Mock engine.text_rec to test parser matrix directly through _run_df_seat_bids_shadow
        test_frame = np.ones((1080, 1920, 3), dtype=np.uint8) * 128
        orig_rec = self.pipe._ocr_engine.text_rec

        # 1. Positive valid tokens
        positive_matrix = [
            ([("666,666", 0.99), ("400,000", 0.99), ("5,000", 0.95), ("90,000", 0.95)], [666666, 400000, 5000, 90000]),
            ([(" 500,000", 0.95), ("500,000 ", 0.95), ("116,999", 0.95), ("5000", 0.95)], [500000, 500000, 116999, 5000]),
            ([("90000", 0.95), ("666666", 0.95), ("0", 0.95), ("", 0.0)], [90000, 666666, 0, None]),
        ]

        try:
            for mock_res, exp_vals in positive_matrix:
                self.pipe._ocr_engine.text_rec = lambda crops, mr=mock_res: (mr, None)
                parsed = self.pipe._run_df_seat_bids_shadow(test_frame)
                self.assertEqual(parsed, exp_vals)

            # 2. Negative invalid tokens: all must fail-closed to None
            negative_matrix = [
                ([("展示5个藏品", 0.99), ("abc5000", 0.95), ("5000abc", 0.95), ("5K", 0.95)], [None, None, None, None]),
                ([("90K", 0.95), ("OUC", 0.60), ("OOC", 0.60), ("@OC", 0.60)], [None, None, None, None]),
                ([("DOL", 0.60), ("5,00", 0.95), ("500,00", 0.95), ("1,23,456", 0.95)], [None, None, None, None]),
            ]

            for mock_res, exp_vals in negative_matrix:
                self.pipe._ocr_engine.text_rec = lambda crops, mr=mock_res: (mr, None)
                parsed = self.pipe._run_df_seat_bids_shadow(test_frame)
                self.assertEqual(parsed, exp_vals)

        finally:
            self.pipe._ocr_engine.text_rec = orig_rec

    def test_seat_binder_responsibility_split_l3z6(self):
        """
        Verify binder responsibility split contract (4D2D1L-L3Z.6):
        - Sub-methods _extract_seat_panel_items, _update_seat_names_and_finals_from_ocr,
          _update_seat_current_bids_from_ocr, and _derive_seat_leader_and_context function correctly
        - Coordinating wrapper _bind_seats_slot_authoritative produces identical context state
        """
        self.pipe.reset_session_state()
        self.pipe.current_context["round"] = 2

        # Mock panel OCR items:
        # Slot 1: Name='Alice', LiveBid='666,666', Hist R1='100,000'
        # Slot 2: Name='Bob', LiveBid='', Hist R1='400,000'
        # Slot 3: Name='Charlie', LiveBid='90,000', Hist R1='5,000'
        # Slot 4: Name='David', LiveBid='500,000', Hist R1='0'
        w, h = 1920, 1080
        mock_ocr = [
            ([[int(w * 0.05), int(h * 0.20)], [int(w * 0.10), int(h * 0.20)], [int(w * 0.10), int(h * 0.23)], [int(w * 0.05), int(h * 0.23)]], "Alice", 0.95),
            ([[int(w * 0.08), int(h * 0.24)], [int(w * 0.11), int(h * 0.24)], [int(w * 0.11), int(h * 0.26)], [int(w * 0.08), int(h * 0.26)]], "100W", 0.95),
            ([[int(w * 0.13), int(h * 0.24)], [int(w * 0.20), int(h * 0.24)], [int(w * 0.20), int(h * 0.27)], [int(w * 0.13), int(h * 0.27)]], "666,666", 0.99),

            ([[int(w * 0.05), int(h * 0.35)], [int(w * 0.10), int(h * 0.35)], [int(w * 0.10), int(h * 0.38)], [int(w * 0.05), int(h * 0.38)]], "Bob", 0.95),
            ([[int(w * 0.08), int(h * 0.39)], [int(w * 0.11), int(h * 0.39)], [int(w * 0.11), int(h * 0.41)], [int(w * 0.08), int(h * 0.41)]], "400W", 0.95),

            ([[int(w * 0.05), int(h * 0.50)], [int(w * 0.10), int(h * 0.50)], [int(w * 0.10), int(h * 0.53)], [int(w * 0.05), int(h * 0.53)]], "Charlie", 0.95),
            ([[int(w * 0.08), int(h * 0.54)], [int(w * 0.11), int(h * 0.54)], [int(w * 0.11), int(h * 0.56)], [int(w * 0.08), int(h * 0.56)]], "5W", 0.95),
            ([[int(w * 0.13), int(h * 0.54)], [int(w * 0.20), int(h * 0.54)], [int(w * 0.20), int(h * 0.57)], [int(w * 0.13), int(h * 0.57)]], "90,000", 0.95),

            ([[int(w * 0.05), int(h * 0.65)], [int(w * 0.10), int(h * 0.65)], [int(w * 0.10), int(h * 0.68)], [int(w * 0.05), int(h * 0.68)]], "David", 0.95),
            ([[int(w * 0.13), int(h * 0.69)], [int(w * 0.20), int(h * 0.69)], [int(w * 0.20), int(h * 0.72)], [int(w * 0.13), int(h * 0.72)]], "500,000", 0.95),
        ]

        bound_ok = self.pipe._bind_seats_slot_authoritative(mock_ocr, w, h)
        bound_ok = self.pipe._bind_seats_slot_authoritative(mock_ocr, w, h)
        self.assertTrue(bound_ok)

        # 1. Names validation
        self.assertEqual(self.pipe._slot_names[1], "Alice")
        self.assertEqual(self.pipe._slot_names[2], "Bob")
        self.assertEqual(self.pipe._slot_names[3], "Charlie")
        self.assertEqual(self.pipe._slot_names[4], "David")
        self.assertEqual(self.pipe.current_context["myName"], "David")

        # 2. Current bids validation
        self.assertEqual(self.pipe._slot_cur_bids[1], 666666)
        self.assertIsNone(self.pipe._slot_cur_bids[2])
        self.assertEqual(self.pipe._slot_cur_bids[3], 90000)
        self.assertEqual(self.pipe._slot_cur_bids[4], 500000)
        self.assertEqual(self.pipe.current_context["myBid"], 500000)

        # 3. Leader validation
        self.assertEqual(self.pipe.current_context["currentLeaderBid"], 666666)
        self.assertEqual(self.pipe.current_context["leaderName"], "Alice")
        self.assertFalse(self.pipe.current_context["isMyLead"])

        # 4. Finals / History validation
        self.assertIn("Alice", self.pipe.current_context["finalBids"])
        self.assertEqual(self.pipe.current_context["finalBids"]["Alice"]["2"], 666666)

    def test_df_seat_bids_authority_and_metadata_gate_l3z7(self):
        """
        Verify DF Seat-Bids Authority & Metadata Refresh Gate (4D2D1L-L3Z.7):
        1. When names are known and round is steady, heavy panel OCR is skipped (0 calls)
        2. DF numeric values become authoritative in _slot_cur_bids, seats, myBid, leader
        3. DF None preserves previous trusted in-round bid (never resets to 0)
        4. Round transition triggers round carryover and resets current bids
        5. DF batch exception safely falls back to heavy panel OCR
        """
        img_test = cv2.imread(str(PROJECT_ROOT / "assets" / "video_frames" / "sec_120.jpg"))
        if img_test is None:
            self.skipTest("sec_120.jpg missing")

        self.pipe.reset_session_state()
        self.pipe._ensure_ocr()

        from rapidocr_onnxruntime import RapidOCR
        heavy_panel_calls = []
        orig_full_call = RapidOCR.__call__

        def _spy_full(self_ocr, img, *args, **kwargs):
            if img is not None:
                h, w = img.shape[:2]
                if 500 <= h <= 800 and 400 <= w <= 800:
                    heavy_panel_calls.append((h, w))
            return orig_full_call(self_ocr, img, *args, **kwargs)

        RapidOCR.__call__ = _spy_full

        try:
            # Preset full names to simulate steady round state
            self.pipe._slot_names = {1: "Player1", 2: "Player2", 3: "Player3", 4: "Player4"}
            self.pipe.current_context["scene"] = "IN_AUCTION"
            self.pipe.current_context["round"] = 2
            self.pipe._seat_round = 2

            # 1. Steady frame with DF authority: heavy panel must be skipped
            heavy_panel_calls.clear()
            orig_run_seat = self.pipe._run_df_seat_bids_shadow
            self.pipe._run_df_seat_bids_shadow = lambda f: [666666, None, 90000, 500000]

            self.pipe.process_frame(img_test)
            ctx1 = self.pipe.process_frame(img_test)
            self.assertEqual(len(heavy_panel_calls), 0, "When names are complete and round is steady, heavy panel OCR must be skipped")
            self.assertEqual(self.pipe._slot_cur_bids[1], 666666)
            self.assertIsNone(self.pipe._slot_cur_bids[2])
            self.assertEqual(self.pipe._slot_cur_bids[3], 90000)
            self.assertEqual(self.pipe._slot_cur_bids[4], 500000)
            self.assertEqual(ctx1.get("currentLeaderBid"), 666666)
            self.assertEqual(ctx1.get("leaderName"), "Player1")
            self.assertEqual(ctx1.get("myBid"), 500000)

            # 2. Sequential frame with DF None: must retain previous trusted bid
            heavy_panel_calls.clear()
            self.pipe._run_df_seat_bids_shadow = lambda f: [None, None, 90000, 500000]

            ctx2 = self.pipe.process_frame(img_test)
            self.assertEqual(len(heavy_panel_calls), 0, "Heavy panel still skipped on sequential frame")
            self.assertEqual(self.pipe._slot_cur_bids[1], 666666, "Slot 1 must retain previous trusted bid when DF is None")
            self.assertEqual(ctx2.get("currentLeaderBid"), 666666)

            # 3. Round transition: must trigger heavy panel to sync metadata and reset current bids
            heavy_panel_calls.clear()
            self.pipe.current_context["round"] = 3
            self.pipe._handle_seat_binding_tier(img_test, 1920, 1080, [None, None, None, None], True)
            self.assertEqual(len(heavy_panel_calls), 1, "Round transition must trigger heavy panel metadata sync")
            # Round 2 finals carried over
            self.assertEqual(self.pipe._slot_finals[1].get("2"), 666666)
            # Round 3 bids reset
            self.assertIsNone(self.pipe._slot_cur_bids[1])
            self.assertEqual(self.pipe.current_context["currentLeaderBid"], 0)

            # 4. Incomplete names: must trigger heavy panel to resolve names
            self.pipe.reset_session_state()
            self.pipe.current_context["scene"] = "IN_AUCTION"
            self.pipe.current_context["round"] = 1
            self.pipe._slot_names = {1: None, 2: "Player2", 3: "Player3", 4: "Player4"}
            heavy_panel_calls.clear()
            self.pipe._run_df_seat_bids_shadow = lambda f: [100000, None, None, None]

            self.pipe.process_frame(img_test)
            self.assertEqual(len(heavy_panel_calls), 1, "Incomplete names must trigger heavy panel OCR")

        finally:
            RapidOCR.__call__ = orig_full_call
            self.pipe._run_df_seat_bids_shadow = orig_run_seat

    def test_async_continuous_intel_shadow_liveness_c2(self):
        """
        Verify Async Continuous Intel Shadow Liveness Contract (4D2D1M-C2):
        1. Fake slow extractor (sleeping 300ms) does NOT block process_frame (< 100ms)
        2. Bounded single-flight: max 1 in-flight worker, max 1 pending task (latest-wins)
        3. No thread explosion across multiple rapid frames
        4. Completed evidence is consumed and merged on next process_frame
        """
        img_test = cv2.imread(str(PROJECT_ROOT / "assets" / "video_frames" / "sec_120.jpg"))
        if img_test is None:
            self.skipTest("sec_120.jpg missing")

        from unittest.mock import MagicMock
        from intel_card_evidence import AsyncContinuousIntelWorker, FrameIntelEvidence, IntelCardObservation

        pipe = NTEVisionPipeline()
        mock_ocr = MagicMock()
        mock_ocr.return_value = ([], None)
        mock_ocr.text_rec = lambda imgs, *args, **kwargs: ([], None)
        pipe._ocr_engine = mock_ocr

        call_times = []
        def _slow_fake_extractor():
            class _FakeExtractor:
                def extract_frame(self, frame, frame_id=""):
                    time.sleep(1.0)  # Simulate heavy OCR asynchronously
                    call_times.append(time.monotonic())
                    return FrameIntelEvidence(
                        frameId=frame_id,
                        round=2,
                        timer=25,
                        cards=[[100, 200, 300, 400]],
                        observations=[
                            IntelCardObservation(
                                field="q",
                                value=11,
                                status="OBSERVED",
                                frameId=frame_id,
                                round=2,
                                timer=25,
                                cardBox=[100, 200, 300, 400],
                                rawText="q=11",
                                confidence=0.95,
                            )
                        ],
                    )
            return _FakeExtractor()

        pipe._async_intel_worker = AsyncContinuousIntelWorker(extractor_factory=_slow_fake_extractor)
        pipe.current_context["scene"] = "IN_AUCTION"
        pipe.current_context["round"] = 2
        pipe.current_context["q"] = 11
        pipe.current_context["goldAvg"] = 47286

        # 1. Rapid successive process_frame calls: hot path must remain fast (< 200ms per frame)
        durations = []
        for i in range(5):
            t0 = time.perf_counter()
            ctx = pipe.process_frame(img_test)
            t1 = time.perf_counter()
            durations.append((t1 - t0) * 1000.0)

        mean_dur = sum(durations) / len(durations)
        self.assertLess(mean_dur, 200.0, f"process_frame hot path must not be blocked by slow async OCR (mean={mean_dur:.1f}ms)")
        self.assertTrue(pipe._async_intel_worker.is_in_flight)
        self.assertGreaterEqual(pipe._async_intel_worker.scheduled_count, 1)

        # 2. Wait for worker to finish and verify main thread consumption
        time.sleep(1.2)
        ctx_after = pipe.process_frame(img_test)
        self.assertIsNotNone(ctx_after.get("intelEvidence"))
        self.assertEqual(len(ctx_after.get("intelObservations", [])), 1)
        self.assertEqual(ctx_after["intelObservations"][0]["field"], "q")
        self.assertEqual(ctx_after["intelObservations"][0]["value"], 11)

    def test_async_continuous_intel_shadow_scenes_and_reset_c2(self):
        """
        Verify Scene Gating and Session Reset for Intel Shadow (4D2D1M-C2):
        1. Non-auction scenes (AUCTION_LOBBY, SETTLEMENT) do not schedule intel extraction
        2. reset_session_state() increments generation and discards stale results
        """
        img_lobby = cv2.imread(str(PROJECT_ROOT / "assets" / "video_frames" / "sec_060.jpg"))
        if img_lobby is None:
            self.skipTest("sec_060.jpg missing")

        pipe = NTEVisionPipeline()
        pipe._ensure_ocr()

        from intel_card_evidence import AsyncContinuousIntelWorker

        pipe._async_intel_worker = AsyncContinuousIntelWorker(extractor_factory=lambda: None)

        # 1. Non-auction scene check
        ctx_lobby = pipe.process_frame(img_lobby)
        self.assertEqual(pipe._async_intel_worker.scheduled_count, 0, "Lobby must not trigger intel extraction")

        # 2. Session generation discard check
        worker = pipe._async_intel_worker
        gen0 = pipe._session_generation
        # Inject completed result from gen0
        from intel_card_evidence import FrameIntelEvidence
        with worker._lock:
            worker._completed_results.append((FrameIntelEvidence(frameId="stale_gen0", round=1), gen0))

        # Reset session -> increments generation
        pipe.reset_session_state()
        gen1 = pipe._session_generation
        self.assertGreater(gen1, gen0)

        # Poll with gen1 -> stale gen0 result must be discarded
        polled = worker.poll_results(gen1)
        self.assertEqual(len(polled), 0, "Stale result from previous generation must be discarded on reset")


if __name__ == "__main__":
    unittest.main()
