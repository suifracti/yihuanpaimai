"""Targeted tests for warehouse capture start/stop commands and presentation."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from main_window import MainWindowBridge, OverlayVisibilityController
from warehouse_capture_host import (
    MESSAGE_COMPLETE,
    MESSAGE_DRIVER_NOT_CONFIGURED,
    MESSAGE_ERROR,
    MESSAGE_PARTIAL,
    MESSAGE_START_REQUIRES_TOP,
    PRESENTATION_KEYS,
    REASON_ALREADY_RUNNING,
    REASON_NO_SESSION,
    REASON_SCROLL_DRIVER_NOT_CONFIGURED,
    REASON_STARTED,
    REASON_STOP_REQUESTED,
    WarehouseCaptureHost,
    build_production_warehouse_capture_host,
    production_scroll_driver_is_ready,
)
from warehouse_capture_session import (
    PRODUCTION_SCROLL_DRIVER_ENABLED,
    get_production_scroll_driver,
)

FORBIDDEN_PRESENTATION = (
    "descriptor",
    "relativePath",
    "sha256",
    "imageBytes",
    "sessionToken",
    "hwnd",
    "fileOriginal",
    "savedDescriptors",
    "ledger",
)


class _FakeOverlay:
    def __init__(self):
        self.Visible = True

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


class FakeSession:
    def __init__(self, result, started_event=None, release=None, cancel_token=None, status_sink=None):
        self.result = result
        self.started_event = started_event
        self.release = release
        self.cancel_token = cancel_token
        self.status_sink = status_sink
        self.start_calls = 0

    def start(self):
        self.start_calls += 1
        if self.started_event is not None:
            self.started_event.set()
        if self.status_sink is not None:
            self.status_sink({
                "phase": "CAPTURING",
                "segmentCount": int(self.result.get("segmentCount") or 0),
                "coverageStatus": "PARTIAL",
            })
        if self.release is not None:
            self.release.wait(2.0)
        if self.cancel_token is not None and self.cancel_token.is_cancelled():
            return {
                "accepted": True,
                "coverageStatus": "PARTIAL",
                "terminationReason": "USER_STOP",
                "segmentCount": self.result.get("segmentCount") or 1,
                "savedDescriptors": [{"evidenceId": "kept"}],
            }
        return dict(self.result)


def _factory(result, started_event=None, release=None):
    sessions = []

    def make(*, scene, cancellation_token, status_sink,
             settlement_entered_monotonic=None, game_remaining_s=None, deadline_monotonic=None):
        session = FakeSession(result, started_event, release, cancellation_token, status_sink)
        sessions.append(session)
        return session

    make.sessions = sessions
    return make


class WarehouseCaptureCommandsV1Tests(unittest.TestCase):
    def test_failed_retry_retains_only_same_record_packet_without_claiming_coverage(self):
        host = WarehouseCaptureHost()
        prior = {"recordStableKey": "same-record", "sourceFingerprint": "a" * 64}
        host._review_packet = prior.copy()
        host._active_record_key = 'same-record'
        host._finish({'accepted': False, 'coverageStatus': 'COVERAGE_UNPROVEN',
                      'terminationReason': 'START_REQUIRES_TOP', 'savedDescriptors': []})
        self.assertEqual(host.review_packet_copy(), prior)
        view = host.presentation_payload()
        self.assertTrue(view['packetAvailable'])
        self.assertEqual(view['packetStatus'], 'RETAINED_PREVIOUS_ATTEMPT')
        self.assertEqual(view['coverageStatus'], 'COVERAGE_UNPROVEN')
        host._active_record_key = 'another-record'
        host._finish({'accepted': False, 'coverageStatus': 'COVERAGE_UNPROVEN', 'terminationReason': 'ERROR'})
        self.assertIsNone(host.review_packet_copy())
        self.assertFalse(host.presentation_payload()['packetAvailable'])

    def test_production_driver_disabled_hides_entry_and_rejects_start(self):
        self.assertTrue(PRODUCTION_SCROLL_DRIVER_ENABLED)
        self.assertIsNotNone(get_production_scroll_driver())
        self.assertTrue(production_scroll_driver_is_ready())
        host = build_production_warehouse_capture_host()
        self.assertTrue(host.factory_ready)
        self.assertFalse(host.available)
        payload = host.presentation_payload()
        self.assertFalse(payload["available"])
        started = host.start()
        self.assertFalse(started["ok"])
        self.assertEqual(started["reason"], "TOKEN_INVALID")
        self.assertEqual(host.start_count, 0)
        html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        self.assertIn('id="warehouse-capture-slot"', html)
        self.assertNotIn('id="warehouse-capture-slot" hidden', html)
        self.assertIn("slot.hidden = false", js)
        self.assertNotIn("slot.hidden = !available", js)
        self.assertNotIn("SetForegroundWindow", js)
        self.assertNotIn("SendInput", js)

    def test_explicit_start_launches_once_and_returns_immediately(self):
        started = threading.Event()
        release = threading.Event()
        factory = _factory(
            {
                "accepted": True,
                "coverageStatus": "COMPLETE",
                "terminationReason": "COMPLETE",
                "segmentCount": 3,
                "savedDescriptors": [{}, {}, {}],
            },
            started,
            release,
        )
        host = WarehouseCaptureHost(session_factory=factory, driver_available=True)
        t0 = time.monotonic()
        result = host.start()
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.3)
        self.assertEqual(result["reason"], REASON_STARTED)
        self.assertTrue(started.wait(1.0))
        self.assertEqual(host.start_count, 1)
        self.assertTrue(host.running)
        again = host.start()
        self.assertEqual(again["reason"], REASON_ALREADY_RUNNING)
        self.assertEqual(host.start_count, 1)
        self.assertEqual(len(factory.sessions), 1)
        release.set()
        deadline = time.monotonic() + 1.0
        while host.running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(host.presentation_payload()["state"], "COMPLETE")
        self.assertEqual(host.presentation_payload()["message"], MESSAGE_COMPLETE)

    def test_background_state_maps_and_stop_is_idempotent(self):
        started = threading.Event()
        release = threading.Event()
        factory = _factory(
            {
                "accepted": True,
                "coverageStatus": "COMPLETE",
                "terminationReason": "COMPLETE",
                "segmentCount": 2,
            },
            started,
            release,
        )
        host = WarehouseCaptureHost(session_factory=factory, driver_available=True)
        host.start()
        self.assertTrue(started.wait(1.0))
        presentation = host.presentation_payload()
        self.assertEqual(presentation["state"], "CAPTURING")
        self.assertTrue(presentation["stopAvailable"])
        self.assertIn("已保存 2 段", presentation["message"])
        first_stop = host.stop()
        self.assertEqual(first_stop["reason"], REASON_STOP_REQUESTED)
        second_stop = host.stop()
        self.assertEqual(second_stop["reason"], REASON_STOP_REQUESTED)
        release.set()
        deadline = time.monotonic() + 1.0
        while host.running and time.monotonic() < deadline:
            time.sleep(0.01)
        idle_stop = host.stop()
        self.assertTrue(idle_stop["ok"])
        self.assertEqual(idle_stop["reason"], REASON_NO_SESSION)
        self.assertEqual(host.presentation_payload()["state"], "PARTIAL")
        self.assertEqual(host.presentation_payload()["message"], MESSAGE_PARTIAL)
        # A stopped run cannot poison a new attempt with its cancelled token.
        prior_token = factory.sessions[0].cancel_token
        self.assertTrue(prior_token.is_cancelled())
        self.assertTrue(host.start()["ok"])
        deadline = time.monotonic() + 1.0
        while host.running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(host.running)
        self.assertEqual(len(factory.sessions), 2)
        self.assertIsNot(factory.sessions[1].cancel_token, prior_token)
        self.assertFalse(factory.sessions[1].cancel_token.is_cancelled())
        self.assertEqual(host.presentation_payload()["state"], "COMPLETE")

    def test_failure_copy_and_presentation_whitelist(self):
        cases = (
            ("START_REQUIRES_TOP", "COVERAGE_UNPROVEN", "START_REQUIRES_TOP", MESSAGE_START_REQUIRES_TOP),
            ("SCROLL_DRIVER_NOT_CONFIGURED", "COVERAGE_UNPROVEN", "DRIVER_NOT_CONFIGURED", MESSAGE_DRIVER_NOT_CONFIGURED),
            ("WINDOW_LOST", "PARTIAL", "PARTIAL", MESSAGE_PARTIAL),
            ("SCENE_LEFT", "PARTIAL", "PARTIAL", MESSAGE_PARTIAL),
            ("STORE_FAILED", "PARTIAL", "PARTIAL", MESSAGE_PARTIAL),
            ("MISSING_STABLE_KEY", "COVERAGE_UNPROVEN", "ERROR", MESSAGE_ERROR),
        )
        for reason, coverage, state, message in cases:
            host = WarehouseCaptureHost(
                session_factory=_factory({
                    "accepted": False,
                    "coverageStatus": coverage,
                    "terminationReason": reason,
                    "savedDescriptors": [{"sha256": "should-not-leak", "relativePath": "nope"}],
                }),
                driver_available=True,
            )
            host.start()
            deadline = time.monotonic() + 1.0
            while host.running and time.monotonic() < deadline:
                time.sleep(0.01)
            payload = host.presentation_payload()
            self.assertEqual(set(payload), set(PRESENTATION_KEYS), reason)
            self.assertEqual(payload["state"], state, reason)
            self.assertEqual(payload["message"], message, reason)
            self.assertEqual(payload["terminationReason"], reason)
            blob = str(payload)
            for forbidden in FORBIDDEN_PRESENTATION:
                self.assertNotIn(forbidden, blob)

    def test_native_bridge_commands_ignore_client_authority(self):
        factory = _factory({
            "accepted": True,
            "coverageStatus": "COMPLETE",
            "terminationReason": "COMPLETE",
            "segmentCount": 1,
        })
        host = WarehouseCaptureHost(
            session_factory=factory,
            driver_available=True,
            bindings_probe=lambda: {
                "isSettlement": True,
                "stable": True,
                "recordStableKey": "recBridge01",
                "hwnd": 7,
                "warehouseRoi": (1, 1, 10, 10),
                "scrollState": "TOP",
                "scene": "SETTLEMENT",
                "storeAvailable": True,
            },
        )
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            warehouse_capture_host=host,
        )
        forced = MainWindowBridge(OverlayVisibilityController(_FakeOverlay())).dispatch({
            "action": "start_warehouse_capture",
            "descriptor": {"sha256": "abc"},
            "hwnd": 123,
            "path": "C:/secret.png",
        })
        self.assertEqual(forced["warehouseCaptureCommand"]["reason"], REASON_SCROLL_DRIVER_NOT_CONFIGURED)
        self.assertFalse(forced["warehouseCapture"]["available"])
        prepared = bridge.dispatch({
            "action": "prepare_warehouse_capture",
            "hwnd": 99,
            "ledger": {"no": True},
            "relativePath": "x",
        })
        self.assertEqual(prepared["warehouseCaptureCommand"]["reason"], "PREPARED")
        token = prepared["warehouseCaptureCommand"]["armingToken"]
        started = bridge.dispatch({
            "action": "confirm_warehouse_capture",
            "armingToken": token,
            "hwnd": 99,
        })
        self.assertEqual(started["warehouseCaptureCommand"]["reason"], REASON_STARTED)
        deadline = time.monotonic() + 1.0
        while host.running and time.monotonic() < deadline:
            time.sleep(0.01)
        payload = started["warehouseCapture"]
        self.assertEqual(set(payload), set(PRESENTATION_KEYS))
        self.assertNotIn("hwnd", started)
        self.assertNotIn("ledger", started)
        stopped = bridge.dispatch({"action": "stop_warehouse_capture"})
        self.assertIn(stopped["warehouseCaptureCommand"]["reason"], {REASON_NO_SESSION, REASON_STOP_REQUESTED})

    def test_page_switch_does_not_stop_and_close_cancels(self):
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        overlay = (CORE_DIR / "overlay_alpha.html").read_text(encoding="utf-8")
        main_py = (APP_DIR / "main.py").read_text(encoding="utf-8")
        self.assertIn("function showView(", js)
        self.assertNotIn("stop_warehouse_capture", js.split("function showView")[1].split("function isBridgeReady")[0])
        self.assertIn("cancel-warehouse-capture", main_py)
        self.assertIn("WAREHOUSE_CAPTURE_HOST.stop", main_py)
        self.assertIn('id="warehouseCaptureStatus"', overlay)
        self.assertIn("renderWarehouseCaptureOverlay", overlay)
        self.assertNotIn("start_warehouse_capture", overlay)
        self.assertIn('data-view-target="match"', html)
        self.assertIn('id="warehouse-capture-toggle"', html)
        self.assertNotIn("sha256", html.lower())
        host_src = (APP_DIR / "warehouse_capture_host.py").read_text(encoding="utf-8")
        self.assertNotIn("SendInput", host_src)
        self.assertNotIn("SetForegroundWindow", host_src)
        # The host now owns evidence persistence and reconstruction; module
        # name bans from the pre-persistence host no longer express its contract.
        started = threading.Event()
        release = threading.Event()
        host = WarehouseCaptureHost(
            session_factory=_factory(
                {"accepted": True, "coverageStatus": "COMPLETE", "terminationReason": "COMPLETE"},
                started,
                release,
            ),
            driver_available=True,
        )
        host.start()
        self.assertTrue(started.wait(1.0))
        host.stop()
        self.assertTrue(factory_token_cancelled(host))
        release.set()

    def test_mascot_is_not_driven_by_capture_state(self):
        mascot = (APP_DIR / "mascot_presentation_state.py").read_text(encoding="utf-8")
        self.assertNotIn("warehouseCapture", mascot)
        self.assertNotIn("WAREHOUSE", mascot)


def factory_token_cancelled(host: WarehouseCaptureHost) -> bool:
    return host._cancel.is_cancelled()


if __name__ == "__main__":
    unittest.main()
