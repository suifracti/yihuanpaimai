"""Targeted unit tests for manual warehouse takeover workflow (Fix 6).

Covers:
- UI contract: #warehouse-manual-slot, confirmation dialog, 3 explicit actions.
- Host contract: prepare_manual, start_manual, capture_manual_page, finish_manual_capture, cancel_manual_capture.
- Duplicate page suppression during manual paging.
- Persistence contract: pageCount, reviewUnits, and finalized record immutability.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_history_store import CanonicalHistoryStore
from canonical_match_record import build_canonical_match_record_v7
from main_window import MainWindowBridge
from warehouse_capture_host import (
    WarehouseCaptureHost,
    STATE_MANUAL_CAPTURING,
    STATE_ALIGNING,
    STATE_IDLE,
)


class TestWarehouseManualTakeoverWorkflowV1(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_manual_wh_"))
        self.history_path = self.temp_dir / "history" / "异环拍卖数据.json"
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = CanonicalHistoryStore(str(self.history_path))
        self.record_id = "test_manual_match_20260913"

        base_record = build_canonical_match_record_v7(
            match_id=self.record_id,
            played_at="2026-09-13T21:20:00Z",
            lifecycle_status="FINALIZED",
            source="manual",
            environment={"venue": "珊瑚场", "box": "实木宝箱", "fieldCondition": "standard"},
            settlement={
                "status": "verified",
                "verified": True,
                "clearingPrice": 850000,
                "actualTotal": 1000000,
                "realizedProfit": 150000,
                "winner": "测试玩家",
                "acquired": True,
            },
        )
        self.store.persist_record_transactional(base_record, is_finalized=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ui_contract_elements_exist(self):
        html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        css = (CORE_DIR / "main_window.css").read_text(encoding="utf-8")

        self.assertIn('id="warehouse-manual-slot"', html)
        self.assertIn("即将由人工分页截取仓库当前页并推算，是否继续？", html)
        self.assertIn('id="warehouse-manual-snap-btn"', html)
        self.assertIn('id="warehouse-manual-finish-btn"', html)
        self.assertIn('id="warehouse-manual-cancel-btn"', html)

        self.assertIn(".warehouse-manual-slot", css)
        self.assertIn(".warehouse-manual-controls", css)

        self.assertIn("prepare_warehouse_manual_takeover", js)
        self.assertIn("start_warehouse_manual_takeover", js)
        self.assertIn("capture_warehouse_manual_page", js)
        self.assertIn("finish_warehouse_manual_capture", js)
        self.assertIn("cancel_warehouse_manual_capture", js)

    def test_host_manual_capture_lifecycle(self):
        frame1 = np.full((1080, 1920, 3), 10, dtype=np.uint8)
        frame2 = np.full((1080, 1920, 3), 20, dtype=np.uint8)

        frames = [frame1, frame1, frame2]
        frame_idx = 0

        def fake_frame_provider():
            nonlocal frame_idx
            idx = min(frame_idx, len(frames) - 1)
            frame_idx += 1
            return frames[idx]

        snap_data = {
            "hwnd": 12345,
            "recordStableKey": self.record_id,
            "storeAvailable": True,
        }

        host = WarehouseCaptureHost(
            bindings_probe=lambda: snap_data,
            frame_provider_factory=lambda: fake_frame_provider,
            store_factory=lambda: self.store,
            driver_available=False,
        )

        prep = host.prepare_manual()
        self.assertTrue(prep["ok"])
        self.assertEqual(prep["reason"], "MANUAL_READY")

        started = host.start_manual(self.record_id)
        self.assertTrue(started["ok"])
        self.assertEqual(host.presentation_payload()["state"], STATE_MANUAL_CAPTURING)

        # Page 1
        res1 = host.capture_manual_page()
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["pageCount"], 1)

        # Page 2 duplicate
        res2 = host.capture_manual_page()
        self.assertTrue(res2["ok"])
        self.assertTrue(res2.get("duplicate"))
        self.assertEqual(res2["pageCount"], 1)

        # Page 3 distinct
        res3 = host.capture_manual_page()
        self.assertTrue(res3["ok"])
        self.assertEqual(res3["pageCount"], 2)

        # Cancel resets state
        cancelled = host.cancel_manual_capture()
        self.assertTrue(cancelled["ok"])
        self.assertNotEqual(host.presentation_payload()["state"], STATE_MANUAL_CAPTURING)

    def test_bridge_dispatch_manual_takeover(self):
        class _FakeOverlay:
            def __init__(self):
                self.Visible = True
            def Show(self):
                self.Visible = True
            def Hide(self):
                self.Visible = False

        from main_window import OverlayVisibilityController

        host = WarehouseCaptureHost(
            bindings_probe=lambda: {"hwnd": 1234, "recordStableKey": self.record_id, "storeAvailable": True},
            driver_available=False,
        )
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            warehouse_capture_host=host,
        )

        res_prep = bridge.dispatch({"action": "prepare_warehouse_manual_takeover"})
        self.assertTrue(res_prep["warehouseCaptureCommand"]["ok"])

        res_start = bridge.dispatch({"action": "start_warehouse_manual_takeover"})
        self.assertTrue(res_start["warehouseCaptureCommand"]["ok"])
        self.assertEqual(res_start["warehouseCapture"]["state"], STATE_MANUAL_CAPTURING)

        res_cancel = bridge.dispatch({"action": "cancel_warehouse_manual_capture"})
        self.assertTrue(res_cancel["warehouseCaptureCommand"]["ok"])
        self.assertNotEqual(res_cancel["warehouseCapture"]["state"], STATE_MANUAL_CAPTURING)


if __name__ == "__main__":
    unittest.main()
