"""Two-step production warehouse-capture arming. Fake OS/adapters only."""

from __future__ import annotations

import sys
import tempfile
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
from runtime_data import runtime_data_paths
from warehouse_capture_arming import CONFIRM_CAPTION
from warehouse_capture_host import (
    REASON_BINDING_CHANGED,
    REASON_NOT_SETTLEMENT,
    REASON_PREPARED,
    REASON_START_REQUIRES_TOP,
    REASON_TOKEN_EXPIRED,
    REASON_TOKEN_INVALID,
    REASON_TOKEN_REUSED,
    WarehouseCaptureHost,
    build_production_warehouse_capture_host,
)
from warehouse_capture_session import PRODUCTION_SCROLL_DRIVER_ENABLED, get_production_scroll_driver
from warehouse_input_abort_guard import KIND_KEY_DOWN, WarehouseInputAbortGuard


class _FakeOverlay:
    def __init__(self):
        self.Visible = True

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


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


class FakeInputAdapter:
    def __init__(self, fail_start=False):
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

    def emit(self, kind):
        if self._on_event:
            self._on_event(kind)


class FakeOsAdapter:
    def __init__(self):
        self.wheels = []
        self.cursor = (10, 10)

    def get_cursor_pos(self):
        return self.cursor

    def set_cursor_pos(self, x, y):
        self.cursor = (int(x), int(y))

    def send_mouse_wheel(self, delta, extra_info):
        self.wheels.append((int(delta), int(extra_info)))

    def get_foreground_window(self):
        return 7

    def is_window(self, hwnd):
        return True

    def is_window_visible(self, hwnd):
        return True

    def is_iconic(self, hwnd):
        return False

    def get_client_rect(self, hwnd):
        return (0, 0, 200, 200)

    def client_to_screen(self, hwnd, x, y):
        return (int(x), int(y))


class FakeSession:
    def __init__(self, result, cancel_token=None):
        self.result = result
        self.cancel_token = cancel_token
        self.start_calls = 0
        self.guard = None

    def attach_input_abort_guard(self, guard):
        self.guard = guard

    def start(self):
        self.start_calls += 1
        if self.guard is not None:
            self.guard.install()
            self.guard.arm()
        if self.cancel_token is not None and self.cancel_token.is_cancelled():
            reason = self.cancel_token.reason() or "USER_STOP"
            return {"accepted": True, "coverageStatus": "PARTIAL", "terminationReason": reason, "savedDescriptors": [{"evidenceId": "kept"}]}
        return dict(self.result)


def _bindings(**overrides):
    payload = {
        "isSettlement": True,
        "stable": True,
        "recordStableKey": "recCap01",
        "hwnd": 7,
        "warehouseRoi": (10, 10, 80, 80),
        "scrollState": "TOP",
        "storeAvailable": True,
        "foreground": True,
        "visible": True,
        "minimized": False,
        "scene": "SETTLEMENT",
    }
    payload.update(overrides)
    return payload


class WarehouseCaptureProductionArmingV1Tests(unittest.TestCase):
    def setUp(self):
        self.prod = runtime_data_paths()
        self.hist = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        self.clock = {"t": 0.0}

    def tearDown(self):
        after = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        self.assertEqual(after, self.hist)

    def _host(self, bindings, *, window=None, guard_adapter=None, session_result=None, ttl=12.0):
        sessions = []
        window = window or FakeWindow()
        adapter = guard_adapter if guard_adapter is not None else FakeInputAdapter()

        def factory(*, scene, cancellation_token, status_sink, **deadline_fields):
            session = FakeSession(session_result or {
                "accepted": True, "coverageStatus": "COMPLETE", "terminationReason": "COMPLETE",
                "savedDescriptors": [{}], "scrollRequestCount": 2,
            }, cancellation_token)
            session.deadline_fields = deadline_fields
            sessions.append(session)
            return session

        def guard_factory(cancel_token=None, **_k):
            return WarehouseInputAbortGuard(adapter=adapter, cancel_token=cancel_token)

        host = WarehouseCaptureHost(
            session_factory=factory,
            scene_probe=lambda: dict(bindings),
            driver_available=True,
            bindings_probe=lambda: dict(bindings),
            window_adapter=window,
            input_guard_factory=guard_factory,
            clock=lambda: self.clock["t"],
            token_ttl_s=ttl,
            arming_required=True,
        )
        host._sessions = sessions
        host._guard_adapter = adapter
        return host

    def test_retry_uses_original_deadline_and_rejects_after_budget(self):
        bindings = _bindings(gameRemainingS=40)
        host = self._host(bindings, session_result={
            "accepted": True, "coverageStatus": "PARTIAL", "terminationReason": "USER_STOP",
            "savedDescriptors": [{"evidenceId": "kept"}]})
        def run():
            prepared = host.prepare()
            self.assertTrue(prepared['ok'])
            self.assertTrue(host.confirm(prepared['armingToken'])['ok'])
            deadline = time.monotonic() + 1
            while host.running and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(host.running)
        run()
        first = host._sessions[0].deadline_fields['deadline_monotonic']
        self.assertIsNotNone(first)
        self.clock['t'] = 10
        # A stale repeated countdown may not grant another 40 seconds.
        run()
        self.assertEqual(host._sessions[1].deadline_fields['deadline_monotonic'], first)
        self.clock['t'] = first + .01
        self.assertEqual(host.prepare()['reason'], 'TIMEOUT')
        self.assertEqual(len(host._sessions), 2)

    def test_prepare_confirm_and_token_failures(self):
        host = self._host(_bindings())
        hidden = self._host(_bindings(isSettlement=False, scene="AUCTION"))
        self.assertFalse(hidden.available)
        self.assertEqual(hidden.prepare()["reason"], REASON_NOT_SETTLEMENT)
        self.assertIsNone(hidden.prepare().get("armingToken"))
        prepared = host.prepare()
        self.assertTrue(prepared["ok"])
        self.assertEqual(prepared["reason"], REASON_PREPARED)
        self.assertEqual(prepared["confirmCaption"], CONFIRM_CAPTION)
        token = prepared["armingToken"]
        reused_host = host
        first = reused_host.confirm(token)
        self.assertEqual(first["reason"], "STARTED")
        deadline = time.monotonic() + 1.0
        while host.running and time.monotonic() < deadline:
            time.sleep(0.01)
        again = host.confirm(token)
        self.assertEqual(again["reason"], REASON_TOKEN_INVALID)

        host2 = self._host(_bindings())
        token2 = host2.prepare()["armingToken"]
        self.clock["t"] = 30.0
        self.assertEqual(host2.confirm(token2)["reason"], REASON_TOKEN_EXPIRED)

        host3 = self._host(_bindings())
        token3 = host3.prepare()["armingToken"]
        host3._bindings_probe = lambda: _bindings(hwnd=99)
        self.assertEqual(host3.confirm(token3)["reason"], REASON_BINDING_CHANGED)
        self.assertFalse(host3.running)

    def test_non_top_and_guard_failure_are_zero_input(self):
        host = self._host(_bindings(scrollState="MIDDLE"))
        result = host.prepare()
        self.assertEqual(result["reason"], REASON_START_REQUIRES_TOP)
        self.assertIsNone(result.get("armingToken"))
        self.assertFalse(host.running)
        fail_adapter = FakeInputAdapter(fail_start=True)
        host2 = self._host(_bindings(), guard_adapter=fail_adapter)
        token = host2.prepare()["armingToken"]
        confirmed = host2.confirm(token)
        self.assertTrue(confirmed["ok"])
        thread = host2._thread
        if thread is not None:
            thread.join(2.0)
        self.assertEqual(host2.presentation_payload()["terminationReason"], "INPUT_GUARD_FAILED")
        self.assertEqual(fail_adapter.started, 0)

    def test_user_input_partial_and_stop_idempotent(self):
        adapter = FakeInputAdapter()
        host = self._host(
            _bindings(),
            guard_adapter=adapter,
            session_result={"accepted": True, "coverageStatus": "PARTIAL", "terminationReason": "USER_INPUT", "savedDescriptors": [{"evidenceId": "kept"}]},
        )
        token = host.prepare()["armingToken"]
        host.confirm(token)
        deadline = time.monotonic() + 1.0
        while host.running and time.monotonic() < deadline:
            time.sleep(0.01)
        payload = host.presentation_payload()
        self.assertEqual(payload["coverageStatus"], "PARTIAL")
        first = host.stop()
        second = host.stop()
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])

    def test_complete_does_not_request_up_scroll(self):
        os_adapter = FakeOsAdapter()
        from warehouse_capture_production import PulseDownScrollRequester
        from warehouse_wheel_driver import WarehouseWheelDriver, WarehouseWheelContext, issue_warehouse_wheel_session_token

        driver = WarehouseWheelDriver(os_adapter=os_adapter)

        def ctx():
            return WarehouseWheelContext(
                session_token=issue_warehouse_wheel_session_token(),
                record_stable_key="recCap01",
                expected_stable_key="recCap01",
                hwnd=7,
                tracked_hwnd=7,
                settlement_stable=True,
                warehouse_roi=(10, 10, 80, 80),
            )

        requester = PulseDownScrollRequester(driver, ctx)
        requester.request_next_scroll()
        requester.request_next_scroll()
        self.assertEqual(requester.requests, ["DOWN", "DOWN"])
        self.assertTrue(all(delta < 0 for delta, _extra in os_adapter.wheels))
        self.assertFalse(hasattr(requester, "request_scroll_up"))

    def test_bridge_prepare_confirm_and_no_auto_start(self):
        host = self._host(_bindings())
        bridge = MainWindowBridge(OverlayVisibilityController(_FakeOverlay()), warehouse_capture_host=host)
        prepared = bridge.dispatch({"action": "prepare_warehouse_capture", "hwnd": 1, "path": "C:/x"})
        self.assertEqual(prepared["warehouseCaptureCommand"]["reason"], REASON_PREPARED)
        self.assertNotIn("hwnd", prepared["warehouseCaptureCommand"])
        token = prepared["warehouseCaptureCommand"]["armingToken"]
        started = bridge.dispatch({"action": "confirm_warehouse_capture", "armingToken": token, "hwnd": 99})
        self.assertEqual(started["warehouseCaptureCommand"]["reason"], "STARTED")
        deadline = time.monotonic() + 1.0
        while host.running and time.monotonic() < deadline:
            time.sleep(0.01)
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        self.assertIn(CONFIRM_CAPTION, html)
        self.assertIn("prepare_warehouse_capture", js)
        self.assertIn("confirm_warehouse_capture", js)
        show = js.split("function showView")[1].split("function isBridgeReady")[0]
        self.assertNotIn("prepare_warehouse_capture", show)
        self.assertNotIn("confirm_warehouse_capture", show)
        self.assertIn("warehouse-capture-confirm", show)

    def test_production_factory_is_lazy_and_no_win32_in_tests(self):
        self.assertTrue(PRODUCTION_SCROLL_DRIVER_ENABLED)
        factory = get_production_scroll_driver()
        self.assertIsNotNone(factory)
        self.assertFalse(hasattr(factory, "send_mouse_wheel"))
        host = build_production_warehouse_capture_host()
        self.assertTrue(host.factory_ready)
        self.assertFalse(host.available)
        self.assertEqual(host.start()["reason"], "TOKEN_INVALID")
        self.assertEqual(host.start_count, 0)
        src = (APP_DIR / "warehouse_capture_host.py").read_text(encoding="utf-8")
        self.assertIn("Win32WarehouseOsAdapter", src)
        self.assertNotIn("SendInput", src)

    def test_layout_screenshots(self):
        from playwright.sync_api import sync_playwright

        css = (CORE_DIR / "main_window.css").read_text(encoding="utf-8")
        caption = CONFIRM_CAPTION
        shot_dir = PROJECT_ROOT / "tests" / "fixtures" / "warehouse_capture_production_arming_v1"
        shot_dir.mkdir(parents=True, exist_ok=True)
        pages = {
            "confirm_1280x800.png": f'<button class="btn-wb-action">采集完整仓库</button><div class="warehouse-capture-confirm"><p>{caption}</p><div class="warehouse-capture-confirm-actions"><button class="btn-review-action">取消</button><button class="btn-review-action btn-review-primary">确认开始</button></div></div>',
            "running_1280x800.png": '<button class="btn-wb-action">停止采集</button><span class="warehouse-capture-message">仓库采集中 · 已保存 2 段 · 可停止</span>',
            "partial_1280x800.png": '<button class="btn-wb-action">采集完整仓库</button><span class="warehouse-capture-message">采集已停止 · 证据不完整</span>',
            "complete_1280x800.png": '<button class="btn-wb-action">采集完整仓库</button><span class="warehouse-capture-message">仓库覆盖完成</span>',
        }
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            for name, body in pages.items():
                page.set_content(f"<!doctype html><html><head><meta charset='utf-8'><style>{css}html,body{{margin:0;background:#111318}}</style></head><body><div class='warehouse-capture-slot' style='padding:16px'>{body}</div></body></html>", wait_until="load")
                dest = shot_dir / name
                page.screenshot(path=str(dest), full_page=True)
                self.assertGreaterEqual(dest.stat().st_size, 4000)
            browser.close()


if __name__ == "__main__":
    unittest.main()
