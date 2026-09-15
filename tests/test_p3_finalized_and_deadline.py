# -*- coding: utf-8 -*-
"""Unit tests for P3 Warehouse:
Item 3: Safe back-write to FINALIZED records and cross-match protection
Item 4: Monotonic settlement deadline, scene-detected entry time, countdown 0s, 69s retry, pause/resume.
"""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path[:0] = [
    str(ROOT),
    str(ROOT / "core"),
    str(ROOT / "app"),
    "C:/Program Files/Python310/Lib/site-packages",
]

from canonical_history_store import CanonicalHistoryStore
from warehouse_capture_host import (
    WarehouseCaptureHost,
    TOTAL_SETTLEMENT_BUDGET_S,
    STATE_WAITING_FOR_GAME_FOCUS,
)
from warehouse_capture_session import WarehouseCaptureSession
from canonical_match_record import build_canonical_match_record_v7


class MockClock:
    def __init__(self, start_time: float = 1000.0):
        self._t = float(start_time)

    def __call__(self) -> float:
        return self._t

    def now(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += float(dt)


class TestP3FinalizedAndDeadline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_p3_finalized_"))
        self.history_path = self.temp_dir / "history" / "异环拍卖数据.json"
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = CanonicalHistoryStore(str(self.history_path))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------
    # Item 3: Safe Back-Write to FINALIZED & Cross-Match Isolation
    # -------------------------------------------------------------
    def test_finalized_backwrite_preserves_facts(self):
        """Host safely appends warehouse evidence to FINALIZED records while strictly protecting facts."""
        match_id = "rec_finalized_test_001"
        rec = build_canonical_match_record_v7(
            match_id=match_id,
            played_at="2026-09-08T14:40:37Z",
            lifecycle_status="FINALIZED",
            source="manual",
            environment={"venue": "珊瑚场", "box": "琉璃宝箱", "fieldCondition": "standard"},
            qualities={"gold": {"count": 4, "avg": 50000}},
            public_intel={"q": 17},
            bidding={
                "roundQuotes": {"R1": [711111, 0, 555555, 333333], "R2": [1222222, 0, 555555, 666666]},
                "historicalBids": {"致敬最良心不歪": {"1": 711111, "2": 1222222}},
            },
            settlement={
                "status": "verified",
                "verified": True,
                "clearingPrice": 1222222,
                "actualTotal": 1556124,
                "realizedProfit": 333902,
                "winner": "致敬最良心不歪",
                "acquired": True,
            },
        )
        self.store.persist_record_transactional(rec, is_finalized=True)

        # Build dummy warehouse packet
        fake_packet = {
            "schemaVersion": "warehouse-review-packet.v2",
            "recordStableKey": match_id,
            "sourceFingerprint": "0" * 64,
            "warehouseCoverage": {"status": "COMPLETE", "segmentCount": 2, "terminationReason": "COMPLETE"},
            "reviewStatus": "REVIEW_REQUIRED",
            "segments": [],
            "reviewUnits": [
                {
                    "reviewUnitId": "unit_001",
                    "worldAnchor": {"row": 0, "col": 0},
                    "shape": {"w": 1, "h": 1, "cells": 1},
                    "status": "CONFIRMED",
                }
            ],
            "warehouseIdentityReview": {"reviewedBy": "auto_session"},
        }
        fake_occupancy = {
            "schemaVersion": "warehouse-occupancy.v1",
            "tracks": [{"trackId": "t1", "row": 0, "col": 0}],
        }

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        res = host._persist_draft_occupancy(fake_packet, fake_occupancy)

        self.assertIsNotNone(res)
        # Verify persistence into store
        saved = self.store.get_record(match_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["lifecycleStatus"], "FINALIZED")
        # Pre-match facts, predictions, quotes, bids MUST be strictly preserved
        self.assertEqual(saved["qualities"]["gold"]["count"], 4)
        self.assertEqual(saved["publicIntel"]["q"], 17)
        self.assertEqual(saved["bidding"]["historicalBids"]["致敬最良心不歪"]["1"], 711111)
        self.assertEqual(saved["settlement"]["clearingPrice"], 1222222)
        self.assertEqual(saved["settlement"]["winner"], "致敬最良心不歪")
        self.assertTrue(saved["settlement"]["acquired"])
        # Warehouse evidence MUST be appended
        self.assertIn("warehouseOccupancy", saved["settlement"])
        self.assertEqual(len(saved["settlement"]["warehouseOccupancy"]["tracks"]), 1)
        self.assertEqual(len(saved["settlement"]["reviewUnits"]), 1)

    def test_cross_match_backwrite_protects_current_match(self):
        """When capture finishes after next match started, writes back to target match without polluting CURRENT_MATCH."""
        old_match_id = "rec_match_previous_001"
        new_match_id = "rec_match_next_002"

        rec_old = build_canonical_match_record_v7(
            match_id=old_match_id,
            played_at="2026-09-08T14:40:37Z",
            lifecycle_status="DRAFT",
            source="manual",
        )
        self.store.persist_record_transactional(rec_old, is_finalized=False)

        # Simulate CURRENT_MATCH has moved to new match
        class FakeCurrentMatch:
            def __init__(self, mid):
                self.id = mid
                self.applied_facts = []

            def apply_facts(self, facts, source=None):
                self.applied_facts.append((facts, source))

        fake_cur = FakeCurrentMatch(new_match_id)

        import sys
        sys.modules["main"] = type(sys)("main")
        sys.modules["main"].CURRENT_MATCH = fake_cur

        fake_packet = {
            "schemaVersion": "warehouse-review-packet.v2",
            "recordStableKey": old_match_id,
            "warehouseCoverage": {"status": "COMPLETE", "segmentCount": 1},
            "reviewUnits": [
                {
                    "reviewUnitId": "u_old_1",
                    "footprint": {"widthCells": 1, "heightCells": 1},
                    "placementStatus": "RESOLVED",
                }
            ],
        }
        fake_occupancy = {"tracks": [{"trackId": "trk_old"}]}

        host = WarehouseCaptureHost(history_store_factory=lambda: self.store)
        host._finish({"accepted": True, "coverageStatus": "COMPLETE"}, packet=fake_packet)

        # Verify old match was updated in history store
        saved_old = self.store.get_record(old_match_id)
        self.assertIsNotNone(saved_old)
        self.assertIn("warehouseOccupancy", saved_old["settlement"])

        # Verify CURRENT_MATCH (new match) was NOT polluted with old match occupancy
        self.assertEqual(len(fake_cur.applied_facts), 0)

    # -------------------------------------------------------------
    # Item 4: Monotonic Deadline, Scene-Detection Entry, Countdown 0s
    # -------------------------------------------------------------
    def test_first_settlement_scene_required_not_button_click(self):
        """First settlement monotonic time must come from actual scene detection, not button click."""
        clock = MockClock(100.0)
        host = WarehouseCaptureHost(clock=clock, driver_available=True)

        # Button click before scene detection
        prep = host.prepare()
        self.assertFalse(prep["ok"])
        # No entry time should be set for non-existent match
        self.assertEqual(len(host._settlement_entry_monotonics), 0)

        # Now simulate scene detection at t=105.0
        clock.advance(5.0)
        host.notify_scene_detected({
            "isSettlement": True,
            "stable": True,
            "warehousePresent": True,
            "recordStableKey": "rec_match_scene_001",
            "hwnd": 12345,
            "storeAvailable": True,
        })
        self.assertEqual(host._settlement_entry_monotonics["rec_match_scene_001"], 105.0)
        self.assertEqual(host._settlement_effective_deadlines["rec_match_scene_001"], 105.0 + 70.0)

    def test_countdown_monotonic_tightening_and_late_old_observation(self):
        """Countdown deadline = t_obs + remaining_s, min-tightened, cannot be relaxed by late old observations."""
        clock = MockClock(1000.0)
        session = WarehouseCaptureSession(
            clock=clock,
            timeout_s=70.0,
            settlement_entered_monotonic=1000.0,
        )
        # Initial deadline from hard budget: 1000 + 70 = 1070
        session.update_game_countdown(50.0, observation_monotonic=1005.0)
        # 1005 + 50 = 1055 < 1070 -> tightened to 1055
        self.assertEqual(session._deadline, 1055.0)

        # Next valid countdown observed at 1010.0: remaining = 40.0 -> 1010 + 40 = 1050 < 1055 -> tightened to 1050
        session.update_game_countdown(40.0, observation_monotonic=1010.0)
        self.assertEqual(session._deadline, 1050.0)

        # Delayed old observation arrives with remaining = 55.0 observed at 1002.0 (1002 + 55 = 1057 > 1050)
        # Monotonic rule: must NOT relax deadline!
        session.update_game_countdown(55.0, observation_monotonic=1002.0)
        self.assertEqual(session._deadline, 1050.0)

    def test_countdown_zero_seconds_immediate_cutoff(self):
        """Remaining 0 seconds is valid deadline and not falsy skipped."""
        clock = MockClock(2000.0)
        session = WarehouseCaptureSession(
            clock=clock,
            timeout_s=70.0,
            settlement_entered_monotonic=2000.0,
        )
        # 0s remaining observed at 2010.0
        clock.advance(10.0)
        session.update_game_countdown(0.0, observation_monotonic=2010.0)
        # Deadline tightened to 2010.0
        self.assertEqual(session._deadline, 2010.0)
        self.assertTrue(session._timed_out())

    def test_retry_at_69th_second_and_timeout_at_71st(self):
        """Capture attempt at 69th second is within 70s budget; at 71st second it times out."""
        clock = MockClock(1000.0)
        match_key = "rec_match_retry_001"

        def fake_probe():
            return {
                "isSettlement": True,
                "stable": True,
                "warehousePresent": True,
                "recordStableKey": match_key,
                "hwnd": 12345,
                "storeAvailable": True,
                "scrollState": "TOP",
                "foreground": True,
            }

        host = WarehouseCaptureHost(
            clock=clock,
            driver_available=True,
            scene_probe=fake_probe,
            session_factory=lambda **kw: None,
        )

        # 1st detection at t=1000.0
        host.notify_scene_detected(fake_probe())
        self.assertEqual(host._settlement_entry_monotonics[match_key], 1000.0)

        # At 69th second (t=1069.0)
        clock.advance(69.0)
        res_69 = host.prepare()
        self.assertTrue(res_69["ok"], f"Expected ok at 69s, got {res_69}")

        # At 71st second (t=1071.0)
        clock.advance(2.0)
        res_71 = host.prepare()
        self.assertFalse(res_71["ok"])
        self.assertEqual(res_71["reason"], "TIMEOUT")

    def test_pause_resume_monotonic_time_not_reset(self):
        """Losing game focus enters WAITING_FOR_GAME_FOCUS without resetting or pausing the monotonic deadline."""
        clock = MockClock(3000.0)
        match_key = "rec_match_focus_001"
        is_fg = [False]
        focus_event = threading.Event()

        def fake_probe():
            return {
                "isSettlement": True,
                "stable": True,
                "warehousePresent": True,
                "recordStableKey": match_key,
                "hwnd": 12345,
                "storeAvailable": True,
                "scrollState": "TOP",
                "foreground": is_fg[0],
            }

        class MockSession:
            def __init__(self, **kw):
                pass
            def start(self):
                return {"accepted": True, "coverageStatus": "COMPLETE", "terminationReason": "COMPLETE"}
            def attach_input_abort_guard(self, _g):
                pass

        def test_idle(dt):
            # Block until focus_event or brief timeout
            focus_event.wait(timeout=0.01)

        host = WarehouseCaptureHost(
            clock=clock,
            driver_available=True,
            scene_probe=fake_probe,
            session_factory=MockSession,
            foreground_wait_timeout_s=10.0,
            idle=test_idle,
        )

        # Initial detection
        host.notify_scene_detected(fake_probe())

        # Launch worker while not in foreground
        token = host._cancel
        t = threading.Thread(target=host._run_worker, args=(token, None), daemon=True)
        t.start()

        import time
        time.sleep(0.05)

        # Should be in waiting for focus
        pres = host.presentation()
        self.assertEqual(pres.state, STATE_WAITING_FOR_GAME_FOCUS)

        # Regain focus at t=3005.0
        clock.advance(5.0)
        is_fg[0] = True
        focus_event.set()

        t.join(timeout=2.0)

        # Verified deadline was preserved at 3000 + 70 = 3070
        self.assertEqual(host._settlement_effective_deadlines[match_key], 3070.0)


if __name__ == "__main__":
    unittest.main()
