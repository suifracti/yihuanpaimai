"""Tests for 4D2D1H: Always-Visible Warehouse Capture Status v1.

Verifies:
- All 7 disabled reasons and their honest Chinese messages.
- Button disabled when unavailable; commands blocked.
- Enabled only when all safety conditions are met.
- RUNNING, COMPLETE, PARTIAL states do not regress.
- Frontend whitelist enforcement (no paths, hashes, bboxes, Store, Ledger).
- UI HTML/JS/CSS contract enforcement.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from warehouse_capture_host import (
    DISABLED_REASON_DRIVER_NOT_AVAILABLE,
    DISABLED_REASON_GAME_NOT_DETECTED,
    DISABLED_REASON_MESSAGES,
    DISABLED_REASON_RECORD_KEY_NOT_STABLE,
    DISABLED_REASON_SCROLL_NOT_AT_TOP,
    DISABLED_REASON_SETTLEMENT_NOT_DETECTED,
    DISABLED_REASON_SETTLEMENT_NOT_STABLE,
    DISABLED_REASON_WAREHOUSE_NOT_PRESENT,
    DISABLED_REASON_STORE_NOT_AVAILABLE,
    MESSAGE_COMPLETE,
    MESSAGE_DRIVER_NOT_CONFIGURED,
    MESSAGE_IDLE,
    MESSAGE_PARTIAL,
    MESSAGE_RUNNING,
    MESSAGE_START_REQUIRES_TOP,
    MESSAGE_WAITING_FOR_GAME_FOCUS,
    PRESENTATION_KEYS,
    REASON_PREPARED,
    REASON_SCROLL_DRIVER_NOT_CONFIGURED,
    REASON_STARTED,
    STATE_ALIGNING,
    STATE_CAPTURING,
    STATE_COMPLETE,
    STATE_DRIVER_NOT_CONFIGURED,
    STATE_IDLE,
    STATE_PARTIAL,
    STATE_SCROLLING,
    STATE_START_REQUIRES_TOP,
    STATE_STARTING,
    STATE_WAITING_FOR_GAME_FOCUS,
    WarehouseCaptureHost,
)


class TestWarehouseAlwaysVisibleStatusV1(unittest.TestCase):
    def _dummy_factory(self, **kwargs):
        def factory(**_):
            class _DummySession:
                def start(self):
                    return {"accepted": True, "coverageStatus": "COMPLETE", "terminationReason": "COMPLETE"}
            return _DummySession()
        return factory

    def test_disabled_reason_driver_not_available(self):
        host = WarehouseCaptureHost(session_factory=None, driver_available=False)
        payload = host.presentation_payload()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["disabledReason"], DISABLED_REASON_DRIVER_NOT_AVAILABLE)
        self.assertEqual(payload["message"], DISABLED_REASON_MESSAGES[DISABLED_REASON_DRIVER_NOT_AVAILABLE])
        self.assertFalse(host.prepare()["ok"])
        self.assertEqual(host.prepare()["reason"], REASON_SCROLL_DRIVER_NOT_CONFIGURED)
        self.assertFalse(host.start()["ok"])

    def test_disabled_reason_game_not_detected_when_probe_none_or_hwnd_zero(self):
        host = WarehouseCaptureHost(
            session_factory=self._dummy_factory(),
            driver_available=True,
            bindings_probe=lambda: None,
        )
        payload = host.presentation_payload()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["disabledReason"], DISABLED_REASON_GAME_NOT_DETECTED)
        self.assertEqual(payload["message"], DISABLED_REASON_MESSAGES[DISABLED_REASON_GAME_NOT_DETECTED])

        host_zero_hwnd = WarehouseCaptureHost(
            session_factory=self._dummy_factory(),
            driver_available=True,
            bindings_probe=lambda: {"hwnd": 0, "isSettlement": True, "stable": True, "recordStableKey": "rec_1", "scene": "SETTLEMENT"},
        )
        payload_zero = host_zero_hwnd.presentation_payload()
        self.assertFalse(payload_zero["available"])
        self.assertEqual(payload_zero["disabledReason"], DISABLED_REASON_GAME_NOT_DETECTED)
        self.assertEqual(payload_zero["message"], DISABLED_REASON_MESSAGES[DISABLED_REASON_GAME_NOT_DETECTED])

    def test_disabled_reason_store_not_available(self):
        host = WarehouseCaptureHost(
            session_factory=self._dummy_factory(),
            driver_available=True,
            bindings_probe=lambda: {
                "hwnd": 12345,
                "isSettlement": True,
                "stable": True,
                "recordStableKey": "rec_1",
                "scene": "SETTLEMENT",
                "storeAvailable": False,
            },
        )
        payload = host.presentation_payload()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["disabledReason"], DISABLED_REASON_STORE_NOT_AVAILABLE)
        self.assertEqual(payload["message"], DISABLED_REASON_MESSAGES[DISABLED_REASON_STORE_NOT_AVAILABLE])

    def test_disabled_reason_settlement_not_detected(self):
        host = WarehouseCaptureHost(
            session_factory=self._dummy_factory(),
            driver_available=True,
            bindings_probe=lambda: {
                "hwnd": 12345,
                "isSettlement": False,
                "stable": True,
                "recordStableKey": "rec_1",
                "scene": "IN_AUCTION",
                "storeAvailable": True,
            },
        )
        payload = host.presentation_payload()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["disabledReason"], DISABLED_REASON_SETTLEMENT_NOT_DETECTED)
        self.assertEqual(payload["message"], DISABLED_REASON_MESSAGES[DISABLED_REASON_SETTLEMENT_NOT_DETECTED])

    def test_disabled_reason_warehouse_not_present(self):
        host = WarehouseCaptureHost(
            session_factory=self._dummy_factory(),
            driver_available=True,
            bindings_probe=lambda: {
                "hwnd": 12345,
                "isSettlement": True,
                "stable": True,
                "recordStableKey": "rec_1",
                "scene": "SETTLEMENT",
                "storeAvailable": True,
                "warehousePresent": False,
            },
        )
        payload = host.presentation_payload()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["disabledReason"], DISABLED_REASON_WAREHOUSE_NOT_PRESENT)
        self.assertEqual(payload["message"], DISABLED_REASON_MESSAGES[DISABLED_REASON_WAREHOUSE_NOT_PRESENT])
        self.assertNotEqual(payload["disabledReason"], DISABLED_REASON_SETTLEMENT_NOT_DETECTED)

    def test_disabled_reason_settlement_not_stable(self):
        host = WarehouseCaptureHost(
            session_factory=self._dummy_factory(),
            driver_available=True,
            bindings_probe=lambda: {
                "hwnd": 12345,
                "isSettlement": True,
                "stable": False,
                "recordStableKey": "rec_1",
                "scene": "SETTLEMENT",
                "storeAvailable": True,
            },
        )
        payload = host.presentation_payload()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["disabledReason"], DISABLED_REASON_SETTLEMENT_NOT_STABLE)
        self.assertEqual(payload["message"], DISABLED_REASON_MESSAGES[DISABLED_REASON_SETTLEMENT_NOT_STABLE])

    def test_disabled_reason_record_key_not_stable(self):
        host = WarehouseCaptureHost(
            session_factory=self._dummy_factory(),
            driver_available=True,
            bindings_probe=lambda: {
                "hwnd": 12345,
                "isSettlement": True,
                "stable": True,
                "recordStableKey": "",
                "scene": "SETTLEMENT",
                "storeAvailable": True,
            },
        )
        payload = host.presentation_payload()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["disabledReason"], DISABLED_REASON_RECORD_KEY_NOT_STABLE)
        self.assertEqual(payload["message"], DISABLED_REASON_MESSAGES[DISABLED_REASON_RECORD_KEY_NOT_STABLE])

    def test_disabled_reason_scroll_not_at_top(self):
        host = WarehouseCaptureHost(
            session_factory=self._dummy_factory(),
            driver_available=True,
            bindings_probe=lambda: {
                "hwnd": 12345,
                "isSettlement": True,
                "stable": True,
                "recordStableKey": "rec_1",
                "scene": "SETTLEMENT",
                "storeAvailable": True,
                "scrollState": "MIDDLE",
            },
        )
        prep = host.prepare()
        self.assertFalse(prep["ok"])
        self.assertEqual(prep["reason"], "START_REQUIRES_TOP")
        payload = host.presentation_payload()
        self.assertEqual(payload["disabledReason"], DISABLED_REASON_SCROLL_NOT_AT_TOP)
        self.assertEqual(payload["message"], MESSAGE_START_REQUIRES_TOP)

    def test_enabled_when_all_conditions_met(self):
        host = WarehouseCaptureHost(
            session_factory=self._dummy_factory(),
            driver_available=True,
            bindings_probe=lambda: {
                "hwnd": 12345,
                "isSettlement": True,
                "stable": True,
                "recordStableKey": "rec_1",
                "scene": "SETTLEMENT",
                "storeAvailable": True,
                "scrollState": "TOP",
            },
        )
        payload = host.presentation_payload()
        self.assertTrue(payload["available"])
        self.assertIsNone(payload["disabledReason"])
        self.assertEqual(payload["message"], MESSAGE_IDLE)
        prep = host.prepare()
        self.assertTrue(prep["ok"])
        self.assertEqual(prep["reason"], REASON_PREPARED)

    def test_running_and_terminal_states_messages(self):
        host = WarehouseCaptureHost(session_factory=self._dummy_factory(), driver_available=True)
        pres_running = host._build_presentation(STATE_CAPTURING, 3, "PARTIAL", None)
        self.assertEqual(pres_running.message, MESSAGE_RUNNING.format(n=3))
        self.assertIsNone(pres_running.disabled_reason)

        pres_complete = host._build_presentation(STATE_COMPLETE, 5, "COMPLETE", "COMPLETE")
        self.assertEqual(pres_complete.message, MESSAGE_COMPLETE)

        pres_partial = host._build_presentation(STATE_PARTIAL, 2, "PARTIAL", "USER_STOP")
        self.assertEqual(pres_partial.message, MESSAGE_PARTIAL)

        pres_focus = host._build_presentation(STATE_WAITING_FOR_GAME_FOCUS, 0, "COVERAGE_UNPROVEN", None)
        self.assertEqual(pres_focus.message, MESSAGE_WAITING_FOR_GAME_FOCUS)

    def test_presentation_keys_whitelist_and_no_leakage(self):
        host = WarehouseCaptureHost()
        payload = host.presentation_payload()
        self.assertEqual(set(payload), set(PRESENTATION_KEYS))
        self.assertIn("disabledReason", payload)
        forbidden = [
            "path", "relativepath", "rootpath", "store", "ledger",
            "bbox", "sha256", "hash", "candidates", "image", "imagebytes"
        ]
        for key in payload:
            for f in forbidden:
                self.assertNotIn(f, key.lower())

    def test_html_js_css_contracts(self):
        html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        css = (CORE_DIR / "main_window.css").read_text(encoding="utf-8")

        self.assertIn('id="warehouse-capture-slot"', html)
        self.assertNotIn('id="warehouse-capture-slot" hidden', html)
        self.assertIn('id="warehouse-capture-toggle"', html)
        self.assertIn('id="warehouse-capture-message"', html)

        self.assertIn("slot.hidden = false", js)
        self.assertNotIn("slot.hidden = !available", js)
        self.assertIn("button.disabled = !available && !running", js)
        self.assertIn('if (!slot || warehouseToggle.disabled || slot.dataset.available !== "true") return;', js)

        self.assertIn(".btn-wb-action:disabled", css)
        self.assertIn("pointer-events: none;", css)


if __name__ == "__main__":
    unittest.main()
