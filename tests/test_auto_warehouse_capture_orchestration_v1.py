# -*- coding: utf-8 -*-
"""Phase 11: Auto Warehouse Capture Orchestration & Once Guard targeted tests.

Strictly mocked / fake host; NO real wheel input or live driver.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from main import (
    CURRENT_MATCH,
    maybe_trigger_auto_warehouse_capture,
    reset_auto_capture_guard,
    get_capture_safety_override,
    set_capture_safety_override,
    register_capture_safety_override_callback,
)


class FakeWarehouseCaptureHost:
    def __init__(self, prepare_ok=True, confirm_ok=True, is_running=False):
        self.prepare_ok = prepare_ok
        self.confirm_ok = confirm_ok
        self._running = is_running
        self.prepare_calls = 0
        self.confirm_calls = 0
        self.confirmed_tokens = []

    def prepare(self):
        self.prepare_calls += 1
        if not self.prepare_ok or self._running:
            return {"ok": False, "reason": "PREPARE_REJECTED", "armingToken": None}
        return {"ok": True, "reason": "PREPARED", "armingToken": f"token_{self.prepare_calls}"}

    def confirm(self, token_id):
        self.confirm_calls += 1
        self.confirmed_tokens.append(token_id)
        if not self.confirm_ok:
            return {"ok": False, "reason": "CONFIRM_FAILED"}
        self._running = True
        return {"ok": True, "reason": "STARTED"}

    def presentation_payload(self):
        return {"state": "IDLE" if not self._running else "STARTING"}


class AutoWarehouseCaptureOrchestrationTests(unittest.TestCase):
    def setUp(self):
        reset_auto_capture_guard()
        CURRENT_MATCH.begin_next_match()

    def tearDown(self):
        reset_auto_capture_guard()
        register_capture_safety_override_callback(None)

    def _ready_ctx(self, match_id="match_auto_001"):
        return {
            "recordStableKey": match_id,
            "scene": "SETTLEMENT",
            "isSettlement": True,
            "settlementReady": True,
            "warehousePresent": True,
            "scrollState": "TOP",
            "gameHwnd": 12345,
            "settlementData": {"stable": True},
        }

    def test_prerequisites_satisfied_triggers_auto_capture_and_safety_override(self):
        """AC1 & AC2 & AC7 & AC10: 满足前提条件时自动调用 prepare -> confirm，并激活 safety override"""
        host = FakeWarehouseCaptureHost(prepare_ok=True, confirm_ok=True)
        ctx = self._ready_ctx("match_001")

        override_invoked = []
        register_capture_safety_override_callback(lambda ov: override_invoked.append(ov))

        res = maybe_trigger_auto_warehouse_capture(ctx, host=host)

        self.assertIsNotNone(res)
        self.assertTrue(res.get("ok"))
        self.assertEqual(host.prepare_calls, 1)
        self.assertEqual(host.confirm_calls, 1)
        self.assertEqual(host.confirmed_tokens, ["token_1"])
        self.assertTrue(get_capture_safety_override())
        self.assertIn(True, override_invoked)

    def test_repeated_same_key_frames_max_one_attempt(self):
        """AC3: 同一 recordStableKey 无论推送多少帧，auto-start 尝试总数最多 1"""
        host = FakeWarehouseCaptureHost(prepare_ok=True, confirm_ok=True)
        ctx = self._ready_ctx("match_same_001")

        # 模拟连续 5 帧推送
        res1 = maybe_trigger_auto_warehouse_capture(ctx, host=host)
        self.assertIsNotNone(res1)
        self.assertTrue(res1.get("ok"))

        for _ in range(4):
            res_subsequent = maybe_trigger_auto_warehouse_capture(ctx, host=host)
            self.assertIsNone(res_subsequent)

        self.assertEqual(host.prepare_calls, 1)
        self.assertEqual(host.confirm_calls, 1)

    def test_failed_or_completed_same_key_never_retries(self):
        """AC4: 即使 session 失败/结束，同一 recordStableKey 后续帧绝不重试"""
        host = FakeWarehouseCaptureHost(prepare_ok=True, confirm_ok=False)
        ctx = self._ready_ctx("match_failed_001")

        # 首次尝试（confirm 失败）
        res1 = maybe_trigger_auto_warehouse_capture(ctx, host=host)
        self.assertIsNotNone(res1)
        self.assertFalse(res1.get("ok"))

        # 模拟 session 已经停止
        host._running = False

        # 后续帧推送
        res2 = maybe_trigger_auto_warehouse_capture(ctx, host=host)
        self.assertIsNone(res2)
        self.assertEqual(host.prepare_calls, 1)
        self.assertEqual(host.confirm_calls, 1)

    def test_new_record_stable_key_allows_one_new_attempt(self):
        """AC5: recordStableKey 改为新一局时，允许一次新的自动尝试"""
        host = FakeWarehouseCaptureHost(prepare_ok=True, confirm_ok=True)
        ctx1 = self._ready_ctx("match_key_001")
        ctx2 = self._ready_ctx("match_key_002")

        res1 = maybe_trigger_auto_warehouse_capture(ctx1, host=host)
        self.assertIsNotNone(res1)
        self.assertEqual(host.confirm_calls, 1)

        # 模拟局 1 结束，host 空闲
        host._running = False

        # 新局推送
        res2 = maybe_trigger_auto_warehouse_capture(ctx2, host=host)
        self.assertIsNotNone(res2)
        self.assertEqual(host.confirm_calls, 2)
        self.assertEqual(host.confirmed_tokens, ["token_1", "token_2"])

    def test_non_settlement_rejected_zero_attempt(self):
        """AC6: 非 SETTLEMENT 场景禁止 auto-start"""
        host = FakeWarehouseCaptureHost(prepare_ok=True, confirm_ok=True)
        ctx = self._ready_ctx("match_not_settle")
        ctx["scene"] = "IN_AUCTION"
        ctx["isSettlement"] = False

        res = maybe_trigger_auto_warehouse_capture(ctx, host=host)
        self.assertIsNone(res)
        self.assertEqual(host.prepare_calls, 0)
        self.assertEqual(host.confirm_calls, 0)

    def test_unstable_settlement_ready_still_allows_warehouse_capture(self):
        """Warehouse capture is independent from settlement amount stability."""
        host = FakeWarehouseCaptureHost(prepare_ok=True, confirm_ok=True)
        ctx = self._ready_ctx("match_unstable")
        ctx["settlementReady"] = False
        ctx["settlementData"] = {"stable": False}

        res = maybe_trigger_auto_warehouse_capture(ctx, host=host)
        self.assertIsNotNone(res)
        self.assertTrue(res.get("ok"))
        self.assertEqual(host.prepare_calls, 1)
        self.assertEqual(host.confirm_calls, 1)

    def test_warehouse_absent_rejected_zero_attempt(self):
        """AC6: warehousePresent=False 禁止 auto-start"""
        host = FakeWarehouseCaptureHost(prepare_ok=True, confirm_ok=True)
        ctx = self._ready_ctx("match_no_wh")
        ctx["warehousePresent"] = False

        res = maybe_trigger_auto_warehouse_capture(ctx, host=host)
        self.assertIsNone(res)
        self.assertEqual(host.prepare_calls, 0)

    def test_non_top_scroll_rejected_zero_attempt(self):
        """AC6: scrollState 非 TOP / NO_SCROLL 禁止 auto-start"""
        host = FakeWarehouseCaptureHost(prepare_ok=True, confirm_ok=True)
        ctx = self._ready_ctx("match_middle_scroll")
        ctx["scrollState"] = "MIDDLE"

        res = maybe_trigger_auto_warehouse_capture(ctx, host=host)
        self.assertIsNone(res)
        self.assertEqual(host.prepare_calls, 0)

    def test_already_running_host_rejected_zero_attempt(self):
        """AC6: host 已经在运行中时禁止重复 auto-start"""
        host = FakeWarehouseCaptureHost(prepare_ok=True, confirm_ok=True, is_running=True)
        ctx = self._ready_ctx("match_running")

        res = maybe_trigger_auto_warehouse_capture(ctx, host=host)
        self.assertIsNone(res)
        self.assertEqual(host.prepare_calls, 0)

    def test_process_live_game_frame_orchestration_flow(self):
        """端到端调用链：process_live_game_frame 在 SETTLEMENT 帧自动执行 capture orchestration"""
        from unittest.mock import patch
        import numpy as np
        from main import process_live_game_frame, set_warehouse_capture_host, WAREHOUSE_CAPTURE_HOST
        fake_host = FakeWarehouseCaptureHost(prepare_ok=True, confirm_ok=True)
        set_warehouse_capture_host(fake_host)
        try:
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            ctx = self._ready_ctx("match_live_flow_001")

            with patch("warehouse_scrollbar_observation.observe_warehouse_scrollbar", return_value={"scrollState": "TOP"}), \
                 patch("warehouse_grid_geometry.observe_warehouse_grid", return_value={"grid": {"status": "OK"}}):
                # Frame 1: triggers auto-capture
                process_live_game_frame(img, game_hwnd=7, ctx=ctx)
                self.assertEqual(fake_host.prepare_calls, 1)
                self.assertEqual(fake_host.confirm_calls, 1)

                # Frame 2: same key, no new attempt
                process_live_game_frame(img, game_hwnd=7, ctx=ctx)
                self.assertEqual(fake_host.prepare_calls, 1)
                self.assertEqual(fake_host.confirm_calls, 1)
        finally:
            set_warehouse_capture_host(WAREHOUSE_CAPTURE_HOST)


if __name__ == "__main__":
    unittest.main()
