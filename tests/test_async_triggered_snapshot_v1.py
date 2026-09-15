"""Targeted tests for 4D2D1I: Async Triggered Snapshot v1.

Verifies:
- UI handler returns quickly, does not block on slow recognizer
- Single-flight: repeated clicks while in-flight return busy and execute only once
- Success results are merged exactly once and draft is persisted
- Exception and failure states are honestly visible
- Stale results after match switch / new match are safely discarded
- UI HTML/JS/CSS contract enforcement
- App shutdown safety
"""

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

from async_snapshot_controller import AsyncTriggeredSnapshotController


class _FakeMatch:
    def __init__(self, match_id="draft_test_1"):
        self.id = match_id
        self.facts = {"venueId": "coral", "boxId": "box_1"}
        self.applied_sources = []

    def apply_facts(self, facts, source="triggered_snapshot"):
        self.facts.update(facts)
        self.applied_sources.append((dict(facts), source))


class _FakeSlowRecognizer:
    def __init__(self, delay=0.1, result=None, exception=None):
        self.delay = delay
        self.result = result or {
            "ok": True,
            "appliedFacts": {"q": 15, "goldCount": 4},
            "conflicts": [],
            "summary": "快照识别成功",
        }
        self.exception = exception
        self.calls = 0

    def process_frame(self, img, existing_facts=None):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.exception:
            raise self.exception
        return dict(self.result)


class _FakeCaptureManager:
    def __init__(self, fail=False, frame=None):
        self.fail = fail
        self.frame = frame if frame is not None else [1, 2, 3]

    def capture_game_client(self, hwnd):
        if self.fail:
            return None, "fail"
        return self.frame, "fake_client"


class _FakeTracker:
    def __init__(self, hwnd=12345):
        self.hwnd = hwnd

    def find_game_window(self):
        return self.hwnd


class TestAsyncTriggeredSnapshotV1(unittest.TestCase):
    def test_ui_handler_returns_immediately_without_blocking(self):
        slow_rec = _FakeSlowRecognizer(delay=0.3)
        match = _FakeMatch("draft_speed_test")
        persisted = []
        published = []

        controller = AsyncTriggeredSnapshotController(
            recognizer_factory=lambda: slow_rec,
            capture_manager_factory=lambda: _FakeCaptureManager(),
            tracker_factory=lambda: _FakeTracker(),
            window_validator=lambda h: bool(h > 0),
            current_match_provider=lambda: match,
            persist_draft_callback=lambda: persisted.append(True),
            publish_callback=lambda p: published.append(p),
            payload_builder=lambda: {"facts": dict(match.facts)},
        )

        t0 = time.perf_counter()
        resp = controller.request_snapshot()
        elapsed = time.perf_counter() - t0

        # UI request must return in less than 50ms (not waiting 300ms)
        self.assertLess(elapsed, 0.05)
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["status"], "recognizing")
        self.assertEqual(resp["summary"], "正在快照识别游戏画面...")
        self.assertTrue(controller.in_flight)

        # Wait for background worker to finish
        deadline = time.monotonic() + 1.0
        while controller.in_flight and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertFalse(controller.in_flight)
        self.assertEqual(slow_rec.calls, 1)
        self.assertEqual(match.facts.get("q"), 15)
        self.assertEqual(match.facts.get("goldCount"), 4)
        self.assertEqual(len(persisted), 1)
        self.assertGreaterEqual(len(published), 1)
        last_pub = published[-1]
        self.assertTrue(last_pub["snapshotResult"]["ok"])
        self.assertEqual(last_pub["snapshotResult"]["status"], "completed")

    def test_single_flight_repeated_clicks_return_busy(self):
        block_event = threading.Event()

        class _BlockingRecognizer:
            def __init__(self):
                self.calls = 0

            def process_frame(self, img, existing_facts=None):
                self.calls += 1
                block_event.wait(1.0)
                return {"ok": True, "appliedFacts": {"q": 15}, "conflicts": []}

        rec = _BlockingRecognizer()
        match = _FakeMatch("draft_single_flight")
        controller = AsyncTriggeredSnapshotController(
            recognizer_factory=lambda: rec,
            capture_manager_factory=lambda: _FakeCaptureManager(),
            tracker_factory=lambda: _FakeTracker(),
            window_validator=lambda h: bool(h > 0),
            current_match_provider=lambda: match,
            publish_callback=lambda p: None,
        )

        first = controller.request_snapshot()
        self.assertTrue(first["ok"])
        self.assertEqual(first["status"], "recognizing")

        # Second click while in-flight
        second = controller.request_snapshot()
        self.assertFalse(second["ok"])
        self.assertEqual(second["status"], "busy")
        self.assertIn("正在识别中", second["summary"])

        # Third click while in-flight
        third = controller.request_snapshot()
        self.assertFalse(third["ok"])
        self.assertEqual(third["status"], "busy")

        # Release block
        block_event.set()
        deadline = time.monotonic() + 1.0
        while controller.in_flight and time.monotonic() < deadline:
            time.sleep(0.01)

        # Worker should have been executed exactly once
        self.assertEqual(rec.calls, 1)

    def test_stale_results_discarded_after_match_switch(self):
        slow_rec = _FakeSlowRecognizer(delay=0.1)
        match_a = _FakeMatch("draft_match_A")
        match_b = _FakeMatch("draft_match_B")
        current_holder = {"match": match_a}
        persisted = []

        controller = AsyncTriggeredSnapshotController(
            recognizer_factory=lambda: slow_rec,
            capture_manager_factory=lambda: _FakeCaptureManager(),
            tracker_factory=lambda: _FakeTracker(),
            window_validator=lambda h: bool(h > 0),
            current_match_provider=lambda: current_holder["match"],
            persist_draft_callback=lambda: persisted.append(current_holder["match"].id),
            publish_callback=lambda p: None,
        )

        resp = controller.request_snapshot()
        self.assertTrue(resp["ok"])

        # Switch match while OCR is in flight!
        current_holder["match"] = match_b

        # Wait for worker to finish
        deadline = time.monotonic() + 1.0
        while controller.in_flight and time.monotonic() < deadline:
            time.sleep(0.01)

        # Stale results must not be applied to match_b
        self.assertNotIn("q", match_b.facts)
        self.assertNotIn("goldCount", match_b.facts)
        self.assertEqual(persisted, [])  # No draft persist for stale match

    def test_window_not_found_and_capture_failure_honesty(self):
        # 1. Window not found
        published_1 = []
        c1 = AsyncTriggeredSnapshotController(
            tracker_factory=lambda: _FakeTracker(hwnd=0),
            window_validator=lambda h: bool(h > 0),
            publish_callback=lambda p: published_1.append(p),
        )
        c1.request_snapshot()
        deadline = time.monotonic() + 1.0
        while c1.in_flight and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertGreaterEqual(len(published_1), 1)
        res1 = published_1[-1]["snapshotResult"]
        self.assertFalse(res1["ok"])
        self.assertEqual(res1["status"], "failed")
        self.assertIn("未检测到", res1["summary"])

        # 2. Capture failed
        published_2 = []
        c2 = AsyncTriggeredSnapshotController(
            tracker_factory=lambda: _FakeTracker(hwnd=12345),
            capture_manager_factory=lambda: _FakeCaptureManager(fail=True),
            window_validator=lambda h: bool(h > 0),
            publish_callback=lambda p: published_2.append(p),
        )
        c2.request_snapshot()
        deadline = time.monotonic() + 1.0
        while c2.in_flight and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertGreaterEqual(len(published_2), 1)
        res2 = published_2[-1]["snapshotResult"]
        self.assertFalse(res2["ok"])
        self.assertEqual(res2["status"], "failed")
        self.assertIn("截取失败", res2["summary"])

    def test_recognizer_exception_handled_safely(self):
        slow_rec = _FakeSlowRecognizer(delay=0.01, exception=RuntimeError("ONNX engine crash simulation"))
        published = []
        controller = AsyncTriggeredSnapshotController(
            recognizer_factory=lambda: slow_rec,
            capture_manager_factory=lambda: _FakeCaptureManager(),
            tracker_factory=lambda: _FakeTracker(),
            window_validator=lambda h: bool(h > 0),
            publish_callback=lambda p: published.append(p),
        )
        resp = controller.request_snapshot()
        self.assertTrue(resp["ok"])

        deadline = time.monotonic() + 1.0
        while controller.in_flight and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertFalse(controller.in_flight)
        self.assertGreaterEqual(len(published), 1)
        res = published[-1]["snapshotResult"]
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "failed")
        self.assertIn("异常", res["summary"])

    def test_main_window_bridge_handles_async_snapshot_immediately(self):
        from main_window import MainWindowBridge

        class _MockOverlay:
            visible = True
            def toggle(self):
                self.visible = not self.visible
                return self.visible

        slow_rec = _FakeSlowRecognizer(delay=0.3)
        match = _FakeMatch("draft_bridge_test")
        controller = AsyncTriggeredSnapshotController(
            recognizer_factory=lambda: slow_rec,
            capture_manager_factory=lambda: _FakeCaptureManager(),
            tracker_factory=lambda: _FakeTracker(),
            window_validator=lambda h: bool(h > 0),
            current_match_provider=lambda: match,
            publish_callback=lambda p: None,
        )

        bridge = MainWindowBridge(
            _MockOverlay(),
            triggered_snapshot_provider=controller.request_snapshot,
        )

        # Warm up lazy imports
        bridge.dispatch({"action": "request_app_status"})

        t0 = time.perf_counter()
        resp = bridge.dispatch({"action": "triggered_snapshot"})
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 0.05)
        self.assertIn("snapshotResult", resp)
        self.assertTrue(resp["snapshotResult"]["ok"])
        self.assertEqual(resp["snapshotResult"]["status"], "recognizing")
        self.assertTrue(controller.in_flight)
        self.assertTrue(controller._worker_thread.daemon)

        # Tab switch while recognizing must not submit extra tasks
        tab_resp = bridge.dispatch({"action": "request_app_status"})
        self.assertNotIn("snapshotResult", tab_resp)
        self.assertEqual(slow_rec.calls, 1)

        deadline = time.monotonic() + 1.0
        while controller.in_flight and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(controller.in_flight)

    def test_html_js_css_contracts(self):
        html = (CORE_DIR / "main_window.html").read_text(encoding="utf-8")
        js = (CORE_DIR / "main_window.js").read_text(encoding="utf-8")
        css = (CORE_DIR / "main_window.css").read_text(encoding="utf-8")

        self.assertIn('id="match-btn-snapshot"', html)
        self.assertIn('id="match-snapshot-btn-label"', html)
        self.assertIn('id="match-snapshot-status-text"', html)

        self.assertIn("isRecognizing", js)
        self.assertIn("snapBtn.disabled = isRecognizing", js)
        self.assertIn("postNative(\"triggered_snapshot\")", js)

        self.assertIn(".btn-snapshot-action.is-recognizing", css)
        self.assertIn("pointer-events: none;", css)


if __name__ == "__main__":
    unittest.main()
