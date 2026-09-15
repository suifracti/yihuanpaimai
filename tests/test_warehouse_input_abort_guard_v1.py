"""Tests for physical user-input abort guard. Fake adapter only; no user32."""

from __future__ import annotations

import sys
import tempfile
import threading
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

from runtime_data import runtime_data_paths
from settlement_evidence_store_v2 import STORE_RELATIVE_ROOT, SettlementEvidenceStoreV2
from warehouse_capture_host import CaptureCancelToken, WarehouseCaptureHost
from warehouse_capture_session import (
    PRODUCTION_SCROLL_DRIVER_ENABLED,
    REASON_ESCAPE,
    REASON_INPUT_GUARD_FAILED,
    REASON_USER_INPUT,
    WarehouseCaptureSession,
    get_production_scroll_driver,
)
from warehouse_input_abort_guard import (
    KIND_ESCAPE,
    KIND_KEY_DOWN,
    KIND_MARKED_WHEEL,
    KIND_MOUSE_BUTTON,
    KIND_MOUSE_MOVE,
    KIND_WHEEL,
    WarehouseInputAbortGuard,
)
from warehouse_scrollbar_observation import CHANGE_CHANGED, CHANGE_UNKNOWN, STATE_MIDDLE, STATE_TOP
from warehouse_segment_overlap import DIR_DOWN, STATUS_VERIFIED

KEY = "recAbort01"


def _bgr(color, size=(32, 24)):
    image = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    image[:] = color
    return image


def _settlement():
    return {"isSettlement": True, "stable": True, "recordStableKey": KEY}


def _observation(state, change=CHANGE_UNKNOWN, fingerprint=""):
    return {
        "scrollState": state,
        "segmentChange": change,
        "confidence": 0.9,
        "warehouseFingerprint": fingerprint or state.lower(),
        "thumbPosition": 0.1,
        "thumbLength": 0.2,
        "trackBox": [1, 1, 2, 10],
        "thumbBox": [1, 1, 2, 3],
        "sourceId": state,
    }


def _verified_down(*_a, prev_id="", next_id="", **_k):
    return {
        "status": STATUS_VERIFIED,
        "direction": DIR_DOWN,
        "verticalOffsetPx": -8,
        "reason": "CONTENT_ALIGNED",
        "prevId": prev_id,
        "nextId": next_id,
        "supportCount": 5,
    }


class FakeAdapter:
    def __init__(self, *, fail_start=False):
        self.fail_start = fail_start
        self.started = 0
        self.stopped = 0
        self._on_event = None

    def start(self, on_event):
        if self.fail_start:
            raise RuntimeError("hook failed")
        self.started += 1
        self._on_event = on_event

    def stop(self):
        self.stopped += 1
        self._on_event = None

    def emit(self, kind, dw_extra_info=None):
        if self._on_event is None:
            return
        if dw_extra_info is None:
            self._on_event(kind)
        else:
            self._on_event(kind, dw_extra_info)


class ScriptedFrames:
    def __init__(self, frames):
        self.frames = list(frames)
        self.captures = 0

    def capture(self):
        self.captures += 1
        return self.frames[min(self.captures - 1, len(self.frames) - 1)]


class ScriptedObserver:
    def __init__(self, results, on_observe=None):
        self.results = list(results)
        self.calls = 0
        self.on_observe = on_observe

    def observe(self, _frame, **_kwargs):
        if self.on_observe is not None:
            self.on_observe()
        self.calls += 1
        return dict(self.results[min(self.calls - 1, len(self.results) - 1)])


class RecordingScroll:
    def __init__(self):
        self.requests = []

    def request_next_scroll(self):
        self.requests.append("DOWN")


class WarehouseInputAbortGuardV1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "runtime"
        self.root.mkdir()
        self.store = SettlementEvidenceStoreV2(self.root)
        self.prod = runtime_data_paths()
        self.hist = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None

    def tearDown(self):
        after = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        self.assertEqual(after, self.hist)
        self.assertFalse((PROJECT_ROOT / STORE_RELATIVE_ROOT).exists())
        self.tmp.cleanup()

    def _session(self, adapter, *, emit_on_idle=None, emit_on_observe=None):
        token = CaptureCancelToken()
        guard = WarehouseInputAbortGuard(adapter=adapter, cancel_token=token)
        driver = RecordingScroll()
        idle_emits = {"n": 0}

        def idle(_dt):
            idle_emits["n"] += 1
            if emit_on_idle is not None and guard.armed:
                adapter.emit(emit_on_idle)

        session = WarehouseCaptureSession(
            frame_provider=ScriptedFrames([_bgr((1, 1, 1)), _bgr((2, 2, 2)), _bgr((3, 3, 3))]),
            scene_validator=lambda _raw: _settlement(),
            scroll_requester=driver,
            cancellation_token=token,
            idle=idle,
            timeout_s=20.0,
            store=self.store,
            observer=ScriptedObserver(
                [
                    _observation(STATE_TOP, CHANGE_UNKNOWN, "t"),
                    _observation(STATE_MIDDLE, CHANGE_CHANGED, "m"),
                    _observation(STATE_MIDDLE, CHANGE_CHANGED, "m2"),
                ],
                on_observe=emit_on_observe,
            ),
            aligner=_verified_down,
            max_steps=4,
            already_cropped=True,
            input_abort_guard=guard,
            clock=lambda: 0.0,
        )
        return session, guard, driver, token

    def test_keyboard_escape_click_and_wheel_stop(self):
        cases = [
            (KIND_KEY_DOWN, REASON_USER_INPUT),
            (KIND_ESCAPE, REASON_ESCAPE),
            (KIND_MOUSE_BUTTON, REASON_USER_INPUT),
            (KIND_WHEEL, REASON_USER_INPUT),
        ]
        for kind, reason in cases:
            adapter = FakeAdapter()
            session, guard, driver, token = self._session(adapter, emit_on_idle=kind)
            result = session.start()
            self.assertEqual(result["terminationReason"], reason, kind)
            self.assertEqual(result["coverageStatus"], "PARTIAL", kind)
            self.assertGreaterEqual(len(result["savedDescriptors"]), 1, kind)
            self.assertTrue(token.is_cancelled(), kind)
            self.assertEqual(token.reason(), reason, kind)
            self.assertEqual(guard.abort_reason(), reason, kind)
            self.assertEqual(adapter.started, 1, kind)
            self.assertEqual(adapter.stopped, 1, kind)

    def test_marked_wheel_and_mouse_move_do_not_stop(self):
        adapter = FakeAdapter()
        session, guard, driver, token = self._session(adapter, emit_on_idle=KIND_MOUSE_MOVE)
        # force a short loop then natural consecutive-unchanged/safety by not changing forever
        result = session.start()
        self.assertNotEqual(result["terminationReason"], REASON_USER_INPUT)
        self.assertNotEqual(result["terminationReason"], REASON_ESCAPE)
        self.assertFalse(token.is_cancelled())
        self.assertIsNone(guard.abort_reason())
        self.assertGreaterEqual(len(driver.requests), 1)

        adapter2 = FakeAdapter()
        session2, guard2, driver2, token2 = self._session(adapter2, emit_on_idle=KIND_MARKED_WHEEL)
        result2 = session2.start()
        self.assertNotEqual(result2["terminationReason"], REASON_USER_INPUT)
        self.assertFalse(token2.is_cancelled())
        self.assertGreaterEqual(len(driver2.requests), 1)

    def test_start_click_before_arm_does_not_abort(self):
        adapter = FakeAdapter()
        seen = {"n": 0}

        def on_observe():
            seen["n"] += 1
            if seen["n"] == 1:
                adapter.emit(KIND_MOUSE_BUTTON)

        session, guard, driver, token = self._session(adapter, emit_on_observe=on_observe)
        result = session.start()
        self.assertNotEqual(result["terminationReason"], REASON_USER_INPUT)
        self.assertNotEqual(result["terminationReason"], REASON_ESCAPE)

    def test_install_failure_sends_zero_wheel(self):
        adapter = FakeAdapter(fail_start=True)
        session, guard, driver, token = self._session(adapter)
        result = session.start()
        self.assertEqual(result["terminationReason"], REASON_INPUT_GUARD_FAILED)
        self.assertEqual(result["coverageStatus"], "COVERAGE_UNPROVEN")
        self.assertEqual(result["savedDescriptors"], [])
        self.assertEqual(driver.requests, [])
        self.assertEqual(adapter.started, 0)
        self.assertEqual(adapter.stopped, 0)

    def test_stop_and_cleanup_are_idempotent(self):
        adapter = FakeAdapter()
        token = CaptureCancelToken()
        guard = WarehouseInputAbortGuard(adapter=adapter, cancel_token=token)
        self.assertTrue(guard.install())
        self.assertTrue(guard.arm())
        adapter.emit(KIND_KEY_DOWN)
        token.cancel(REASON_USER_INPUT)
        token.cancel("ESCAPE")
        self.assertEqual(token.reason(), REASON_USER_INPUT)
        guard.uninstall()
        guard.uninstall()
        self.assertEqual(adapter.started, 1)
        self.assertEqual(adapter.stopped, 1)

    def test_host_init_failure_does_not_create_session_or_wheel(self):
        factory_calls = []

        def factory(**_kwargs):
            factory_calls.append(1)
            raise AssertionError("session factory must not run")

        def guard_factory(**kwargs):
            return WarehouseInputAbortGuard(adapter=FakeAdapter(fail_start=True), cancel_token=kwargs.get("cancel_token"))

        host = WarehouseCaptureHost(
            session_factory=factory,
            driver_available=True,
            input_guard_factory=guard_factory,
        )
        started = host.start()
        self.assertTrue(started["ok"])
        thread = host._thread
        if thread is not None:
            thread.join(2.0)
        self.assertEqual(factory_calls, [])
        payload = host.presentation_payload()
        self.assertEqual(payload["terminationReason"], "INPUT_GUARD_FAILED")
        self.assertEqual(payload["coverageStatus"], "COVERAGE_UNPROVEN")

    def test_exception_path_uninstalls_and_production_stays_off(self):
        adapter = FakeAdapter()
        token = CaptureCancelToken()
        guard = WarehouseInputAbortGuard(adapter=adapter, cancel_token=token)
        session = WarehouseCaptureSession(
            frame_provider=None,
            scene_validator=lambda _raw: (_ for _ in ()).throw(RuntimeError("boom")),
            scroll_requester=RecordingScroll(),
            cancellation_token=token,
            store=self.store,
            input_abort_guard=guard,
            already_cropped=True,
            idle=lambda _dt: None,
            clock=lambda: 0.0,
        )
        result = session.start()
        self.assertFalse(result["accepted"])
        self.assertEqual(adapter.started, 1)
        self.assertEqual(adapter.stopped, 1)
        self.assertTrue(PRODUCTION_SCROLL_DRIVER_ENABLED)
        self.assertIsNotNone(get_production_scroll_driver())


if __name__ == "__main__":
    unittest.main()
