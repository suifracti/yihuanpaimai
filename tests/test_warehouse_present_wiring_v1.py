# -*- coding: utf-8 -*-
"""Phase 2: warehousePresent comes only from observe_warehouse_grid; disabled reasons stay split."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

UAT_SETTLEMENT_FRAME = (
    PROJECT_ROOT
    / "build"
    / "uat_4ae5fbb_human"
    / "data-root"
    / "evidence"
    / "settlement_v2"
    / "blobs"
    / "a6"
    / "a60d61c429f0490fd20f5bfa177d24a7929ad25ffb1ec519a3f1abba242bf035.png"
)


def _read_bgr(path: Path):
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    return img


class WarehousePresentWiringTests(unittest.TestCase):
    def setUp(self):
        import main as app_main
        from main import CURRENT_MATCH

        self.app_main = app_main
        self._old_payload = dict(app_main.LATEST_PAYLOAD)
        CURRENT_MATCH.begin_next_match()
        app_main.LATEST_PAYLOAD.clear()

    def tearDown(self):
        from main import CURRENT_MATCH

        CURRENT_MATCH.begin_next_match()
        self.app_main.LATEST_PAYLOAD.clear()
        self.app_main.LATEST_PAYLOAD.update(self._old_payload)

    def test_uat_settlement_frame_grid_ok_sets_present_true_not_settlement_missing(self):
        from warehouse_capture_host import (
            DISABLED_REASON_SETTLEMENT_NOT_DETECTED,
            DISABLED_REASON_WAREHOUSE_NOT_PRESENT,
            WarehouseCaptureHost,
        )
        from warehouse_grid_geometry import observe_warehouse_grid

        self.assertTrue(UAT_SETTLEMENT_FRAME.exists(), f"missing {UAT_SETTLEMENT_FRAME}")
        img = _read_bgr(UAT_SETTLEMENT_FRAME)
        self.assertIsNotNone(img)
        grid_status = observe_warehouse_grid(img, already_cropped=False).get("grid", {}).get("status")
        self.assertEqual(grid_status, "OK")

        ctx = {"isSettlement": True, "scene": "SETTLEMENT", "round": 4}
        payload = self.app_main.process_live_game_frame(img, game_hwnd=7, ctx=ctx)
        self.assertTrue(payload.get("isSettlement"))
        self.assertIs(payload.get("warehousePresent"), True)

        self.app_main.LATEST_PAYLOAD.clear()
        self.app_main.LATEST_PAYLOAD.update(payload)
        snap = self.app_main.get_production_warehouse_bindings()
        self.assertTrue(snap.get("isSettlement"))
        self.assertIs(snap.get("warehousePresent"), True)

        host = WarehouseCaptureHost(
            session_factory=lambda **_: None,
            driver_available=True,
            bindings_probe=lambda: {
                "hwnd": 7,
                "isSettlement": True,
                "stable": True,
                "recordStableKey": "draft_cedfd5dc812144a6b6b17a064a3db511",
                "scene": "SETTLEMENT",
                "storeAvailable": True,
                "scrollState": "TOP",
                "warehousePresent": True,
            },
        )
        presentation = host.presentation_payload()
        self.assertNotEqual(presentation.get("disabledReason"), DISABLED_REASON_SETTLEMENT_NOT_DETECTED)
        self.assertNotEqual(presentation.get("disabledReason"), DISABLED_REASON_WAREHOUSE_NOT_PRESENT)

    def test_settlement_without_grid_stays_fail_closed_with_warehouse_reason(self):
        from warehouse_capture_host import (
            DISABLED_REASON_SETTLEMENT_NOT_DETECTED,
            DISABLED_REASON_WAREHOUSE_NOT_PRESENT,
            DISABLED_REASON_MESSAGES,
            REASON_NOT_SETTLEMENT,
            WarehouseCaptureHost,
        )

        host = WarehouseCaptureHost(
            session_factory=lambda **_: None,
            driver_available=True,
            bindings_probe=lambda: {
                "hwnd": 7,
                "isSettlement": True,
                "stable": True,
                "recordStableKey": "rec_1",
                "scene": "SETTLEMENT",
                "storeAvailable": True,
                "scrollState": "TOP",
                "warehousePresent": False,
            },
        )
        presentation = host.presentation_payload()
        self.assertFalse(presentation.get("available"))
        self.assertEqual(presentation.get("disabledReason"), DISABLED_REASON_WAREHOUSE_NOT_PRESENT)
        self.assertEqual(
            presentation.get("message"),
            DISABLED_REASON_MESSAGES[DISABLED_REASON_WAREHOUSE_NOT_PRESENT],
        )
        self.assertNotEqual(presentation.get("disabledReason"), DISABLED_REASON_SETTLEMENT_NOT_DETECTED)
        prep = host.prepare()
        self.assertFalse(prep.get("ok"))
        self.assertEqual(prep.get("reason"), REASON_NOT_SETTLEMENT)

    def test_missing_hud_field_stays_fail_closed_and_does_not_imply_from_scene(self):
        self.app_main.LATEST_PAYLOAD.update({
            "scene": "SETTLEMENT",
            "isSettlement": True,
            "settlementReady": True,
            "gameHwnd": 7,
        })
        snap = self.app_main.get_production_warehouse_bindings()
        self.assertTrue(snap.get("isSettlement"))
        self.assertIs(snap.get("warehousePresent"), False)

    def test_non_settlement_frame_does_not_set_present_from_scene(self):
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        ctx = {"isSettlement": False, "scene": "IN_AUCTION", "round": 1}
        payload = self.app_main.process_live_game_frame(img, game_hwnd=7, ctx=ctx)
        self.assertIs(payload.get("warehousePresent"), False)
        self.assertFalse(payload.get("isSettlement"))


    def test_phase6_in_auction_warehouse_observation_wiring(self):
        """Phase 6: IN_AUCTION 真实仓库存在时 warehousePresent=True, scrollState 非空; Host 仍 SETTLEMENT_NOT_DETECTED"""
        from warehouse_capture_host import (
            DISABLED_REASON_SETTLEMENT_NOT_DETECTED,
            WarehouseCaptureHost,
        )

        # 1. 验证 UAT 真实真帧切到 IN_AUCTION 场景下
        self.assertTrue(UAT_SETTLEMENT_FRAME.exists(), f"missing {UAT_SETTLEMENT_FRAME}")
        img = _read_bgr(UAT_SETTLEMENT_FRAME)
        self.assertIsNotNone(img)

        ctx_auction = {"isSettlement": False, "scene": "IN_AUCTION", "round": 2}
        payload = self.app_main.process_live_game_frame(img, game_hwnd=7, ctx=ctx_auction)
        self.assertIs(payload.get("warehousePresent"), True)
        self.assertIsNotNone(payload.get("scrollState"))
        self.assertEqual(payload.get("scrollState"), "TOP")
        self.assertFalse(payload.get("isSettlement"))

        # 2. 验证 WarehouseCaptureHost 的 settlement 门禁依然锁死
        host = WarehouseCaptureHost(
            session_factory=lambda **_: None,
            driver_available=True,
            bindings_probe=lambda: {
                "hwnd": 7,
                "isSettlement": False,
                "scene": "IN_AUCTION",
                "stable": True,
                "recordStableKey": "rec_auction",
                "storeAvailable": True,
                "scrollState": payload.get("scrollState"),
                "warehousePresent": payload.get("warehousePresent"),
            },
        )
        presentation = host.presentation_payload()
        self.assertEqual(presentation.get("disabledReason"), DISABLED_REASON_SETTLEMENT_NOT_DETECTED)

        # 3. 真实录像多时间点验证
        p1 = Path(r"C:\Users\Administrator\Videos\2026-08-17 14-11-56.mkv")
        if p1.exists():
            cap1 = cv2.VideoCapture(str(p1))
            fps1 = cap1.get(cv2.CAP_PROP_FPS) or 60.0
            for sec in (75.0, 90.0):
                cap1.set(cv2.CAP_PROP_POS_FRAMES, int(sec * fps1))
                ret, f = cap1.read()
                if ret:
                    ctx = {"isSettlement": False, "scene": "IN_AUCTION", "round": 1}
                    out = self.app_main.process_live_game_frame(f, game_hwnd=7, ctx=ctx)
                    self.assertIs(out.get("warehousePresent"), True, f"14-11-56 @ {sec}s warehousePresent 必须为 True")
                    self.assertIsNotNone(out.get("scrollState"), f"14-11-56 @ {sec}s scrollState 不得为 None")
            cap1.release()

        p2 = Path(r"C:\Users\Administrator\Videos\2026-08-18 11-19-25.mkv")
        if p2.exists():
            cap2 = cv2.VideoCapture(str(p2))
            fps2 = cap2.get(cv2.CAP_PROP_FPS) or 60.0
            cap2.set(cv2.CAP_PROP_POS_FRAMES, int(420.0 * fps2))
            ret, f = cap2.read()
            if ret:
                ctx = {"isSettlement": False, "scene": "IN_AUCTION", "round": 3}
                out = self.app_main.process_live_game_frame(f, game_hwnd=7, ctx=ctx)
                self.assertIs(out.get("warehousePresent"), True, "11-19-25 @ 420s warehousePresent 必须为 True")
                self.assertIsNotNone(out.get("scrollState"), "11-19-25 @ 420s scrollState 不得为 None")
            cap2.release()


if __name__ == "__main__":
    unittest.main()

