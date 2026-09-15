# -*- coding: utf-8 -*-
"""
Targeted test for Warehouse Grid Presence Gate (AC1-AC3).
Verifies:
- AC1: Settlement Summary frame (even with scrollbar false positives) blocks Warehouse capture (grid=UNKNOWN -> BLOCKED).
- AC2: In-auction small backpack (grid=OK, scene=IN_AUCTION) blocks Warehouse capture (not post-match -> BLOCKED).
- AC3: Authentic post-match Warehouse frame (settlement=True, grid=OK, scroll=TOP) allows capture session to be PREPARED and STARTED.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "app"))
sys.path.insert(0, str(PROJECT_ROOT / "core"))

from main_window import MainWindowBridge
from warehouse_capture_host import (
    REASON_NOT_SETTLEMENT,
    REASON_START_REQUIRES_TOP,
    REASON_TOKEN_INVALID,
    STATE_START_REQUIRES_TOP,
    WarehouseCaptureHost,
    build_production_warehouse_capture_host,
)
from warehouse_grid_geometry import observe_warehouse_grid
from warehouse_scrollbar_observation import observe_warehouse_scrollbar, warehouse_search_roi
from settlement_evidence_store_v2 import SettlementEvidenceStoreV2


class _MockOverlay:
    def __init__(self):
        self.visible = True

    def toggle(self):
        self.visible = not self.visible
        return self.visible


class FakeWindow:
    def __init__(self, hwnd=7):
        self.hwnd = hwnd
        self.foreground = hwnd
        self.visible = True
        self.minimized = False

    def is_window(self, hwnd):
        return int(hwnd) == int(self.hwnd)

    def is_window_visible(self, hwnd):
        return self.visible and int(hwnd) == int(self.hwnd)

    def is_iconic(self, hwnd):
        return self.minimized

    def get_foreground_window(self):
        return self.foreground


class FakeSession:
    def __init__(self, result=None, cancel_token=None):
        self.result = result or {
            "accepted": True,
            "coverageStatus": "COMPLETE",
            "terminationReason": "COMPLETE",
            "savedDescriptors": [{"evidenceId": "dummy_seg_1"}],
            "scrollRequestCount": 1,
        }
        self.cancel_token = cancel_token
        self.started = False

    def start(self):
        self.started = True
        return dict(self.result)


class TestWarehouseWrongSceneCaptureGateReplayV1(unittest.TestCase):
    def test_ac1_settlement_summary_scrollbar_false_positive_blocked_by_grid(self):
        """AC1: On Settlement Summary frame, even if scrollbar observer has false-positive NO_SCROLL/TOP, grid=UNKNOWN blocks capture."""
        settle_frame_path = PROJECT_ROOT / "assets" / "settlement_frames" / "sec_513.jpg"
        if not settle_frame_path.exists():
            settle_frame_path = PROJECT_ROOT / "assets" / "settlement_frames" / "sec_478.jpg"
        self.assertTrue(settle_frame_path.exists(), f"Settlement frame missing: {settle_frame_path}")

        img_settle = cv2.imdecode(np.fromfile(str(settle_frame_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        grid_obs = observe_warehouse_grid(img_settle)
        # Authoritative grid check on settlement summary frame must be UNKNOWN
        self.assertNotEqual(grid_obs.get("grid", {}).get("status"), "OK")

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SettlementEvidenceStoreV2(tmp_dir)
            created_sessions: List[FakeSession] = []

            def session_factory(*, scene, cancellation_token, status_sink):
                session = FakeSession(cancel_token=cancellation_token)
                created_sessions.append(session)
                return session

            # Even if scrollState was reported as NO_SCROLL or TOP, grid=UNKNOWN must block capture
            bindings_payload = {
                "isSettlement": True,
                "stable": True,
                "recordStableKey": "settle_match_001",
                "hwnd": 7,
                "warehouseRoi": (1315, 216, 1877, 815),
                "scrollState": "NO_SCROLL",  # deliberate false-positive test
                "frame": img_settle,
                "storeAvailable": True,
                "foreground": True,
                "visible": True,
                "minimized": False,
                "scene": "SETTLEMENT",
            }

            host = WarehouseCaptureHost(
                session_factory=session_factory,
                driver_available=True,
                bindings_probe=lambda: dict(bindings_payload),
                window_adapter=FakeWindow(7),
                store_factory=lambda: store,
                arming_required=True,
            )

            bridge = MainWindowBridge(
                _MockOverlay(),
                warehouse_capture_host=host,
            )

            # 1. Prepare request on Settlement Summary frame
            prep_resp = bridge.dispatch({"action": "prepare_warehouse_capture"})
            prep_cmd = prep_resp.get("warehouseCaptureCommand", {})

            # Must fail closed: no armingToken
            self.assertFalse(prep_cmd.get("ok"))
            self.assertIsNone(prep_cmd.get("armingToken"))

            # 2. Confirm without valid token must fail
            conf_resp = bridge.dispatch({"action": "confirm_warehouse_capture", "armingToken": "fake_token"})
            conf_cmd = conf_resp.get("warehouseCaptureCommand", {})
            self.assertFalse(conf_cmd.get("ok"))
            self.assertEqual(conf_cmd.get("reason"), REASON_TOKEN_INVALID)

            # 3. Verify 0 sessions started, 0 scrolls, 0 segments saved
            self.assertFalse(host.running)
            self.assertEqual(len(created_sessions), 0)
            self.assertEqual(host.presentation().segment_count, 0)
            self.assertNotEqual(host.presentation().coverage_status, "COMPLETE")

            # Evidence store must have 0 saved segments
            history_records = store.list_record_evidence("settle_match_001")
            self.assertEqual(len(history_records), 0)

    def test_ac2_in_auction_small_backpack_blocked_by_post_match_eligibility(self):
        """AC2: In-auction frame (frame_0075s) has grid=OK but scene=IN_AUCTION; must be BLOCKED by post-match eligibility."""
        r1_frame_path = PROJECT_ROOT / "assets" / "replay_frames" / "frame_0075s_01m15s.jpg"
        self.assertTrue(r1_frame_path.exists(), f"R1 frame missing: {r1_frame_path}")

        img_r1 = cv2.imdecode(np.fromfile(str(r1_frame_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        grid_obs = observe_warehouse_grid(img_r1)
        # R1 in-auction frame has valid 10x10 grid
        self.assertEqual(grid_obs.get("grid", {}).get("status"), "OK")

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SettlementEvidenceStoreV2(tmp_dir)
            created_sessions: List[FakeSession] = []

            def session_factory(*, scene, cancellation_token, status_sink):
                session = FakeSession(cancel_token=cancellation_token)
                created_sessions.append(session)
                return session

            # In-auction scene bindings: isSettlement=False, scene="IN_AUCTION"
            bindings_payload = {
                "isSettlement": False,
                "stable": True,
                "recordStableKey": "in_auction_001",
                "hwnd": 7,
                "warehouseRoi": (1315, 216, 1877, 815),
                "scrollState": "NO_SCROLL",
                "frame": img_r1,
                "storeAvailable": True,
                "foreground": True,
                "visible": True,
                "minimized": False,
                "scene": "IN_AUCTION",
            }

            host = WarehouseCaptureHost(
                session_factory=session_factory,
                driver_available=True,
                bindings_probe=lambda: dict(bindings_payload),
                window_adapter=FakeWindow(7),
                store_factory=lambda: store,
                arming_required=True,
            )

            bridge = MainWindowBridge(
                _MockOverlay(),
                warehouse_capture_host=host,
            )

            # Prepare request must fail closed
            prep_resp = bridge.dispatch({"action": "prepare_warehouse_capture"})
            prep_cmd = prep_resp.get("warehouseCaptureCommand", {})
            self.assertFalse(prep_cmd.get("ok"))
            self.assertEqual(prep_cmd.get("reason"), REASON_NOT_SETTLEMENT)
            self.assertIsNone(prep_cmd.get("armingToken"))

            # Confirm without valid token must fail
            conf_resp = bridge.dispatch({"action": "confirm_warehouse_capture", "armingToken": "fake_token"})
            conf_cmd = conf_resp.get("warehouseCaptureCommand", {})
            self.assertFalse(conf_cmd.get("ok"))
            self.assertEqual(conf_cmd.get("reason"), REASON_TOKEN_INVALID)

            self.assertFalse(host.running)
            self.assertEqual(len(created_sessions), 0)

    def test_ac3_authentic_post_match_warehouse_fixture_is_accepted(self):
        """AC3: Authentic post-match warehouse fixture (top_warehouse.png) with grid=OK and scroll=TOP is accepted."""
        wh_crop_path = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_scrollbar_v1" / "top_warehouse.png"
        self.assertTrue(wh_crop_path.exists(), f"Warehouse fixture missing: {wh_crop_path}")

        crop = cv2.imdecode(np.fromfile(str(wh_crop_path), dtype=np.uint8), cv2.IMREAD_COLOR)

        size = (1920, 1080)
        canvas = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        x1, y1, x2, y2 = warehouse_search_roi(size[0], size[1])
        dest = canvas[y1:y2, x1:x2]
        resized = cv2.resize(crop, (dest.shape[1], dest.shape[0]), interpolation=cv2.INTER_AREA)
        canvas[y1:y2, x1:x2] = resized

        grid_obs = observe_warehouse_grid(canvas, already_cropped=False)
        self.assertEqual(grid_obs.get("grid", {}).get("status"), "OK")
        sb_obs = observe_warehouse_scrollbar(canvas, already_cropped=False)
        self.assertEqual(sb_obs.get("scrollState"), "TOP")

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SettlementEvidenceStoreV2(tmp_dir)
            created_sessions: List[FakeSession] = []

            def session_factory(*, scene, cancellation_token, status_sink):
                session = FakeSession(cancel_token=cancellation_token)
                created_sessions.append(session)
                return session

            bindings_payload = {
                "isSettlement": True,
                "stable": True,
                "recordStableKey": "post_match_wh_001",
                "hwnd": 7,
                "warehouseRoi": (x1, y1, x2, y2),
                "scrollState": sb_obs.get("scrollState"),
                "frame": canvas,
                "storeAvailable": True,
                "foreground": True,
                "visible": True,
                "minimized": False,
                "scene": "SETTLEMENT",
            }

            host = WarehouseCaptureHost(
                session_factory=session_factory,
                driver_available=True,
                bindings_probe=lambda: dict(bindings_payload),
                window_adapter=FakeWindow(7),
                store_factory=lambda: store,
                arming_required=True,
            )

            bridge = MainWindowBridge(
                _MockOverlay(),
                warehouse_capture_host=host,
            )

            # Prepare request
            prep_resp = bridge.dispatch({"action": "prepare_warehouse_capture"})
            prep_cmd = prep_resp.get("warehouseCaptureCommand", {})
            self.assertTrue(prep_cmd.get("ok"))
            self.assertEqual(prep_cmd.get("reason"), "PREPARED")
            token = prep_cmd.get("armingToken")
            self.assertIsNotNone(token)

            # Confirm request
            conf_resp = bridge.dispatch({"action": "confirm_warehouse_capture", "armingToken": token})
            conf_cmd = conf_resp.get("warehouseCaptureCommand", {})
            self.assertTrue(conf_cmd.get("ok"))
            self.assertEqual(conf_cmd.get("reason"), "STARTED")


if __name__ == "__main__":
    unittest.main()
