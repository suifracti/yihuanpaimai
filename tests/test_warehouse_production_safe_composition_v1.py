"""Targeted integration tests for 4D2D1B3: Production Safe Driver Composition.

Tests the full lazy production composition:
- WindowCaptureManager frame capture;
- Win32WarehouseOsAdapter + WarehouseWheelDriver scroll requester;
- Win32InputActivityAdapter + WarehouseInputAbortGuard;
- SettlementEvidenceStoreV2 in isolated root;
- Verification that marker is shared and ignored by guard;
- Verification that user input halts session and preserves PARTIAL;
- Verification that cursor is restored after each pulse;
- Verification that production History remains 100% untouched.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from settlement_evidence_store_v2 import SettlementEvidenceStoreV2
from warehouse_capture_host import (
    STATE_COMPLETE,
    STATE_IDLE,
    STATE_PARTIAL,
    STATE_WAITING_FOR_GAME_FOCUS,
    WarehouseCaptureHost,
    build_production_warehouse_capture_host,
)
from warehouse_input_abort_guard import (
    KIND_KEY_DOWN,
    KIND_MARKED_WHEEL,
    KIND_WHEEL,
    REASON_USER_INPUT,
    WarehouseInputAbortGuard,
    Win32InputActivityAdapter,
)
from warehouse_scrollbar_observation import warehouse_search_roi
from warehouse_wheel_driver import (
    DEFAULT_WHEEL_DELTA,
    WAREHOUSE_WHEEL_EXTRA_INFO,
    WarehouseWheelDriver,
)

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_scrollbar_v1"
SESSION_TEST_TIMEOUT_S = 25.0
POSTPROCESS_TEST_TIMEOUT_S = 120.0


def _load_fixture(name: str) -> np.ndarray:
    path = FIXTURES_DIR / name
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Fixture not found: {path}")
    return img


def _compose_full_screen(crop: np.ndarray, width: int = 1920, height: int = 1080) -> np.ndarray:
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x1, y1, x2, y2 = warehouse_search_roi(width, height)
    resized = cv2.resize(crop, (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA)
    canvas[y1:y2, x1:x2] = resized
    return canvas


class _FakeRecordingOsAdapter:
    def __init__(self, game_hwnd: int = 12345, is_fg: bool = False):
        self.game_hwnd = game_hwnd
        self.is_fg = is_fg
        self.cursor_pos = (100, 100)
        self.set_cursor_calls: List[Tuple[int, int]] = []
        self.wheels_sent: List[Tuple[int, int]] = []
        self.set_foreground_calls = 0

    def is_window(self, hwnd: int) -> bool:
        return hwnd == self.game_hwnd

    def is_window_visible(self, hwnd: int) -> bool:
        return hwnd == self.game_hwnd

    def is_iconic(self, hwnd: int) -> bool:
        return False

    def get_foreground_window(self) -> int:
        return self.game_hwnd if self.is_fg else 99999

    def get_window_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        return (0, 0, 1920, 1080)

    def get_client_rect(self, hwnd: int) -> Tuple[int, int, int, int]:
        return (0, 0, 1920, 1080)

    def client_to_screen(self, hwnd: int, x: int, y: int) -> Tuple[int, int]:
        return (int(x), int(y))

    def get_cursor_pos(self) -> Tuple[int, int]:
        return self.cursor_pos

    def set_cursor_pos(self, x: int, y: int) -> bool:
        self.cursor_pos = (int(x), int(y))
        self.set_cursor_calls.append((int(x), int(y)))
        return True

    def send_mouse_wheel(self, delta: int, extra_info: int) -> bool:
        self.wheels_sent.append((int(delta), int(extra_info)))
        return True

    def SetForegroundWindow(self, hwnd: int) -> bool:
        self.set_foreground_calls += 1
        return True


class _FakeInputAdapter:
    def __init__(self):
        self.running = False
        self.callback = None
        self.starts = 0
        self.stops = 0

    def start(self, on_event):
        self.starts += 1
        self.running = True
        self.callback = on_event

    def stop(self):
        self.stops += 1
        self.running = False
        self.callback = None

    def inject_event(self, kind: str, dw_extra_info: int = 0):
        if self.callback is not None:
            self.callback(kind, dw_extra_info)


class TestWarehouseProductionSafeComposition4D2D1B3(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="yh_warehouse_comp_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_lazy_instantiation_has_zero_side_effects(self):
        os_adapter_created = []
        input_adapter_created = []

        host = build_production_warehouse_capture_host(
            os_adapter_factory=lambda: os_adapter_created.append(1),
            input_adapter_factory=lambda: input_adapter_created.append(1),
        )
        self.assertEqual(len(os_adapter_created), 0)
        self.assertEqual(len(input_adapter_created), 0)
        self.assertFalse(host.running)
        self.assertEqual(host.start_count, 0)
        pres = host.presentation()
        self.assertEqual(pres.segment_count, 0)

    def test_full_production_composition_flow_with_isolated_store(self):
        top_crop = _load_fixture("top_warehouse.png")
        mid_crop = _load_fixture("middle_warehouse.png")
        bot_crop = _load_fixture("bottom_warehouse.png")
        top_frame = _compose_full_screen(top_crop)
        mid_frame = _compose_full_screen(mid_crop)
        bot_frame = _compose_full_screen(bot_crop)

        # The production host persists one main settlement frame before it
        # constructs the rolling capture session.  Keep that read explicit so
        # the session itself still starts from an independently captured TOP.
        # Two passive TOP polls precede the first wheel pulse. Movement in this
        # fixture must follow that pulse, rather than advancing on every poll.
        frames = [top_frame, top_frame.copy(), top_frame.copy(), top_frame.copy(), mid_frame, bot_frame]
        frame_idx = [0]

        def _fake_frame_provider():
            def _get_frame(_scene=None):
                idx = frame_idx[0]
                frame_idx[0] += 1
                return frames[min(idx, len(frames) - 1)]
            return _get_frame

        os_adapter = _FakeRecordingOsAdapter(game_hwnd=12345, is_fg=False)
        input_adapter = _FakeInputAdapter()
        store = SettlementEvidenceStoreV2(self.temp_dir)

        snap = {
            "scene": "SETTLEMENT",
            "isSettlement": True,
            "stable": True,
            "recordStableKey": "match-comp-001",
            "hwnd": 12345,
            "warehouseRoi": warehouse_search_roi(1920, 1080),
            "scrollState": "TOP",
            "storeAvailable": True,
            "foreground": False,
            "visible": True,
            "minimized": False,
        }

        host = build_production_warehouse_capture_host(
            bindings_probe=lambda: snap,
            window_adapter=os_adapter,
            os_adapter_factory=lambda: os_adapter,
            input_adapter_factory=lambda: input_adapter,
            store_factory=lambda: store,
            frame_provider_factory=_fake_frame_provider,
            foreground_wait_timeout_s=5.0,
            token_ttl_s=10.0,
        )
        self.addCleanup(lambda: host._thread.join(POSTPROCESS_TEST_TIMEOUT_S) if host._thread else None)

        # 1. Prepare
        prep = host.prepare()
        self.assertTrue(prep["ok"])
        token_id = prep["armingToken"]

        # 2. Confirm while game not foreground
        conf = host.confirm(token_id)
        self.assertTrue(conf["ok"])

        time.sleep(0.08)
        self.assertEqual(host.presentation().state, STATE_WAITING_FOR_GAME_FOCUS)
        self.assertEqual(len(os_adapter.wheels_sent), 0)
        self.assertFalse(input_adapter.running)

        # 3. Restore game foreground
        os_adapter.is_fg = True
        snap["foreground"] = True

        # Input must start promptly; offline identity resolution after capture
        # has a separate wait and is not measured as capture responsiveness.
        deadline = time.monotonic() + SESSION_TEST_TIMEOUT_S
        while not os_adapter.wheels_sent and host.running and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(os_adapter.wheels_sent)
        deadline = time.monotonic() + POSTPROCESS_TEST_TIMEOUT_S
        while host.running and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(host.running)

        # 4. Verify wheel execution and safety contract
        self.assertTrue(len(os_adapter.wheels_sent) >= 1)
        for delta, marker in os_adapter.wheels_sent:
            self.assertEqual(delta, DEFAULT_WHEEL_DELTA)
            self.assertEqual(marker, WAREHOUSE_WHEEL_EXTRA_INFO)

        # 5. Verify cursor restoration: initial cursor was (100, 100)
        self.assertEqual(os_adapter.cursor_pos, (100, 100))

        # 6. Verify zero focus stealing
        self.assertEqual(os_adapter.set_foreground_calls, 0)

        # 7. Verify input adapter was uninstalled
        self.assertFalse(input_adapter.running)
        self.assertEqual(input_adapter.stops, 1)

    def test_user_input_aborts_session_and_preserves_partial(self):
        top_crop = _load_fixture("top_warehouse.png")
        top_frame = _compose_full_screen(top_crop)

        def _fake_frame_provider():
            return lambda _scene=None: top_frame

        os_adapter = _FakeRecordingOsAdapter(game_hwnd=12345, is_fg=True)
        input_adapter = _FakeInputAdapter()
        store = SettlementEvidenceStoreV2(self.temp_dir)

        snap = {
            "scene": "SETTLEMENT",
            "isSettlement": True,
            "stable": True,
            "recordStableKey": "match-abort-002",
            "hwnd": 12345,
            "warehouseRoi": warehouse_search_roi(1920, 1080),
            "scrollState": "TOP",
            "storeAvailable": True,
            "foreground": True,
            "visible": True,
            "minimized": False,
        }

        host = build_production_warehouse_capture_host(
            bindings_probe=lambda: snap,
            window_adapter=os_adapter,
            os_adapter_factory=lambda: os_adapter,
            input_adapter_factory=lambda: input_adapter,
            store_factory=lambda: store,
            frame_provider_factory=_fake_frame_provider,
        )

        prep = host.prepare()
        host.confirm(prep["armingToken"])

        # Wait for input adapter to start and be armed
        deadline = time.monotonic() + 1.0
        while not input_adapter.running and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(input_adapter.running)

        # Simulate physical user key press during capture session
        wheels_at_cancel = len(os_adapter.wheels_sent)
        input_adapter.inject_event(KIND_KEY_DOWN, 0)

        deadline = time.monotonic() + SESSION_TEST_TIMEOUT_S
        while host.running and time.monotonic() < deadline:
            self.assertEqual(
                len(os_adapter.wheels_sent),
                wheels_at_cancel,
                "Physical cancellation must prevent every subsequent wheel pulse",
            )
            time.sleep(0.05)
        self.assertFalse(host.running)
        self.assertEqual(len(os_adapter.wheels_sent), wheels_at_cancel)
        pres = host.presentation()
        self.assertEqual(pres.state, STATE_PARTIAL)
        self.assertEqual(pres.termination_reason, REASON_USER_INPUT)
        self.assertEqual(os_adapter.cursor_pos, (100, 100))

    def test_production_history_remains_strictly_untouched(self):
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if not local_app_data:
            return
        prod_history = Path(local_app_data) / "异环拍卖助手" / "data" / "history" / "异环拍卖数据.json"

        before_exists = prod_history.exists()
        before_sha = None
        before_count = None
        if before_exists:
            raw_before = prod_history.read_bytes()
            before_sha = hashlib.sha256(raw_before).hexdigest()
            try:
                before_count = len(json.loads(raw_before.decode("utf-8")).get("records", []))
            except Exception:
                before_count = None

        # Execute warehouse capture operations using isolated temp store
        self.test_full_production_composition_flow_with_isolated_store()

        after_exists = prod_history.exists()
        self.assertEqual(after_exists, before_exists)
        if before_exists:
            raw_after = prod_history.read_bytes()
            after_sha = hashlib.sha256(raw_after).hexdigest()
            try:
                after_count = len(json.loads(raw_after.decode("utf-8")).get("records", []))
            except Exception:
                after_count = None
            self.assertEqual(after_sha, before_sha, "Production history SHA must remain strictly unchanged across composition workflow")
            self.assertEqual(after_count, before_count, "Production history record count must remain strictly unchanged across composition workflow")


if __name__ == "__main__":
    unittest.main()
