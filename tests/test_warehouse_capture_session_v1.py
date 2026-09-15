"""Isolated tests for warehouse capture session orchestrator v1."""

from __future__ import annotations

import hashlib
import inspect
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = PROJECT_ROOT / "core"
APP_DIR = PROJECT_ROOT / "app"
for entry in (str(CORE_DIR), str(APP_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from runtime_data import runtime_data_paths
from settlement_evidence_store_v2 import (
    KIND_WAREHOUSE_SEGMENT,
    STORE_RELATIVE_ROOT,
    SettlementEvidenceStoreError,
    SettlementEvidenceStoreV2,
)
from warehouse_capture_session import (
    PRODUCTION_SCROLL_DRIVER_ENABLED,
    REASON_CONSECUTIVE_UNCHANGED,
    REASON_OVERLAP_CONFLICT,
    REASON_OVERLAP_UNVERIFIED,
    REASON_SAFETY_STEP_LIMIT,
    REASON_SCENE_LEFT,
    REASON_SCROLL_DRIVER_NOT_CONFIGURED,
    REASON_STABLE_KEY_CHANGED,
    REASON_START_REQUIRES_TOP,
    REASON_STORE_FAILED,
    REASON_TIMEOUT,
    REASON_USER_STOP,
    REASON_WINDOW_LOST,
    WarehouseCaptureSession,
    get_production_scroll_driver,
)
from warehouse_coverage_ledger import STATUS_COMPLETE, STATUS_PARTIAL, STATUS_UNPROVEN
from warehouse_scrollbar_observation import (
    CHANGE_CHANGED,
    CHANGE_UNCHANGED,
    CHANGE_UNKNOWN,
    STATE_BOTTOM,
    STATE_MIDDLE,
    STATE_NO_SCROLL,
    STATE_TOP,
    STATE_UNKNOWN,
)
from warehouse_segment_overlap import DIR_DOWN, STATUS_CONFLICT, STATUS_UNVERIFIED, STATUS_VERIFIED


KEY = "recWHCap01"
FORBIDDEN_INPUT_TOKENS = (
    "SendInput",
    "mouse_event",
    "MOUSEEVENTF",
    "SetCursorPos",
    "win32api",
    "win32gui",
    "mouse_wheel",
    "WebView",
    "pyautogui",
    "pydirectinput",
)


def _bgr(color, size=(48, 32)) -> np.ndarray:
    image = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    image[:] = color
    return image


def _png(color, size=(48, 32)) -> bytes:
    ok, buf = cv2.imencode(".png", _bgr(color, size))
    if not ok or buf is None:
        raise RuntimeError("png encode failed")
    return buf.tobytes()


def _observation(state: str, change: str, fingerprint: str = "") -> dict:
    positions = {
        STATE_TOP: 0.04,
        STATE_MIDDLE: 0.48,
        STATE_BOTTOM: 0.93,
        STATE_NO_SCROLL: 0.0,
        STATE_UNKNOWN: None,
    }
    return {
        "scrollState": state,
        "segmentChange": change,
        "confidence": 0.9 if state != STATE_UNKNOWN else 0.1,
        "warehouseFingerprint": fingerprint or state.lower(),
        "thumbPosition": positions[state],
        "thumbLength": 0.95 if state == STATE_NO_SCROLL else 0.22,
        "trackBox": [1, 1, 3, 20],
        "thumbBox": [1, 1, 3, 4],
        "sourceId": fingerprint or state,
    }


def _verified_down(*_args, prev_id="", next_id="", **_kwargs):
    return {
        "status": STATUS_VERIFIED,
        "direction": DIR_DOWN,
        "verticalOffsetPx": -40,
        "normalizedOffset": -0.2,
        "overlapRatio": 0.41,
        "confidence": 0.9,
        "reason": "CONTENT_ALIGNED",
        "prevId": prev_id,
        "nextId": next_id,
        "supportCount": 5,
    }


def _unverified(*_args, **_kwargs):
    return {
        "status": STATUS_UNVERIFIED,
        "direction": DIR_DOWN,
        "verticalOffsetPx": -12,
        "reason": "LOW_OVERLAP",
        "supportCount": 1,
    }


def _conflict(*_args, **_kwargs):
    return {
        "status": STATUS_CONFLICT,
        "direction": "UP",
        "verticalOffsetPx": 36,
        "reason": "DIRECTION_MISMATCH",
        "supportCount": 4,
    }


class ScriptedFrames:
    def __init__(self, frames):
        self.frames = list(frames)
        self.captures = 0

    def capture(self):
        self.captures += 1
        index = min(self.captures - 1, len(self.frames) - 1)
        return self.frames[index]


class ScriptedObserver:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def observe(self, _frame, **_kwargs):
        self.calls += 1
        index = min(self.calls - 1, len(self.results) - 1)
        return dict(self.results[index])


class ScriptedValidator:
    def __init__(self, views):
        self.views = list(views)
        self.calls = 0

    def validate(self, _raw):
        self.calls += 1
        index = min(self.calls - 1, len(self.views) - 1)
        return dict(self.views[index])


class RecordingScrollRequester:
    def __init__(self):
        self.requests = []

    def request_next_scroll(self):
        self.requests.append({"action": "NEXT_SCROLL", "direction": "DOWN"})


class CountingClock:
    def __init__(self, step=0.0, start=0.0):
        self.t = float(start)
        self.step = float(step)

    def now(self):
        self.t += self.step
        return self.t


class FailingAfterStore:
    def __init__(self, store, fail_on=2):
        self.store = store
        self.fail_on = fail_on
        self.calls = 0

    def save_original(self, **kwargs):
        self.calls += 1
        if self.calls >= self.fail_on:
            raise SettlementEvidenceStoreError("DISK_FULL", "injected store failure")
        return self.store.save_original(**kwargs)

    def list_record_evidence(self, key):
        return self.store.list_record_evidence(key)


def _settlement(key=KEY, stable=True):
    return {
        "isSettlement": True,
        "stable": stable,
        "recordStableKey": key,
        "scene": "SETTLEMENT",
    }


class WarehouseCaptureSessionV1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "runtime"
        self.root.mkdir()
        self.store = SettlementEvidenceStoreV2(self.root)
        self.prod = runtime_data_paths()
        self.prod_history = (
            self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        )
        self.driver = RecordingScrollRequester()
        self.events = []

    def tearDown(self):
        after = self.prod.history_path.read_bytes() if self.prod.history_path.exists() else None
        self.assertEqual(after, self.prod_history)
        self.assertFalse((PROJECT_ROOT / STORE_RELATIVE_ROOT).exists())
        self.tmp.cleanup()

    def _sink(self, event):
        self.events.append(dict(event))

    def _session(self, frames, observations, **kwargs):
        validator = kwargs.pop("validator", ScriptedValidator([_settlement()]))
        return WarehouseCaptureSession(
            frame_provider=kwargs.pop("frame_provider", ScriptedFrames(frames)),
            scene_validator=validator,
            scroll_requester=kwargs.pop("scroll_requester", self.driver),
            cancellation_token=kwargs.pop("cancellation_token", None),
            status_sink=kwargs.pop("status_sink", self._sink),
            clock=kwargs.pop("clock", CountingClock()),
            idle=kwargs.pop("idle", lambda _dt: None),
            timeout_s=kwargs.pop("timeout_s", 20.0),
            store=kwargs.pop("store", self.store),
            observer=kwargs.pop("observer", ScriptedObserver(observations)),
            aligner=kwargs.pop("aligner", _verified_down),
            max_steps=kwargs.pop("max_steps", 16),
            max_unchanged=kwargs.pop("max_unchanged", 3),
            already_cropped=kwargs.pop("already_cropped", True),
            **kwargs,
        )

    def _blobs(self):
        root = self.root / "evidence" / "settlement_v2" / "blobs"
        if not root.exists():
            return []
        return [path for path in root.rglob("*") if path.is_file()]

    def test_constructor_does_not_start(self):
        provider = ScriptedFrames([_bgr((1, 2, 3))])
        WarehouseCaptureSession(
            frame_provider=provider,
            scene_validator=lambda _raw: _settlement(),
            store=self.store,
            idle=lambda _dt: None,
        )
        self.assertEqual(provider.captures, 0)
        self.assertEqual(self.store.list_record_evidence(KEY), [])
        self.assertEqual(self._blobs(), [])

    def _interrupted_middle(self):
        frames = [_bgr((10, 20, 30)), _bgr((40, 50, 60))]
        session = None
        def sink(event):
            if event["event"] == "segment_saved" and event["segmentCount"] == 2:
                session.stop()
        session = self._session(frames, [
            _observation(STATE_TOP, CHANGE_UNKNOWN),
            _observation(STATE_MIDDLE, CHANGE_CHANGED)], status_sink=sink)
        result = session.start()
        self.assertEqual(result["terminationReason"], REASON_USER_STOP)
        self.assertTrue(session.can_resume(KEY))
        return session, result

    def test_middle_resume_keeps_chain_without_duplicate_or_new_deadline(self):
        previous, first = self._interrupted_middle()
        resumed = self._session([_bgr((40, 50, 60)), _bgr((70, 80, 90))], [
            _observation(STATE_MIDDLE, CHANGE_UNKNOWN), _observation(STATE_BOTTOM, CHANGE_CHANGED)],
            clock=CountingClock(start=5), timeout_s=70)
        self.assertTrue(resumed.resume_from(previous))
        result = resumed.start()
        self.assertEqual(resumed._deadline, previous._deadline)
        self.assertEqual(result["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(len(result["savedDescriptors"]), 3)
        self.assertEqual(result["scrollRequestCount"], 2)
        self.assertEqual(result["savedDescriptors"][:2], first["savedDescriptors"])
        self.assertEqual(len(result["ledger"]["overlapProofs"]), 2)
        self.assertEqual(previous.start(), first)  # Frozen prior attempt is unchanged.
        self.assertEqual(len(self._blobs()), 3)
        self.assertFalse(resumed.can_resume(KEY))

    def test_middle_resume_rejects_changed_page_other_match_and_unstable_scene_before_input(self):
        previous, _ = self._interrupted_middle()
        for color, key, stable in [((99, 99, 99), KEY, True),
                                    ((40, 50, 60), "otherMatch", True),
                                    ((40, 50, 60), KEY, False)]:
            with self.subTest(color=color, key=key, stable=stable):
                driver = RecordingScrollRequester()
                resumed = self._session([_bgr(color)], [_observation(STATE_MIDDLE, CHANGE_UNKNOWN)],
                    scroll_requester=driver, validator=ScriptedValidator([_settlement(key, stable)]))
                self.assertTrue(resumed.resume_from(previous))
                result = resumed.start()
                self.assertFalse(result["accepted"])
                self.assertEqual(driver.requests, [])
                self.assertEqual(len(self._blobs()), 2)

    def test_middle_resume_rejects_missing_original_and_expired_budget(self):
        previous, _ = self._interrupted_middle()
        driver = RecordingScrollRequester()
        resumed = self._session([_bgr((40, 50, 60))], [_observation(STATE_MIDDLE, CHANGE_UNKNOWN)],
                                scroll_requester=driver, clock=CountingClock(start=21))
        self.assertTrue(resumed.resume_from(previous))
        self.assertEqual(resumed.start()["terminationReason"], REASON_TIMEOUT)
        self.assertEqual(driver.requests, [])
        descriptor = previous._saved[0]
        (self.root / descriptor["relativePath"]).unlink()
        resumed = self._session([_bgr((40, 50, 60))], [_observation(STATE_MIDDLE, CHANGE_UNKNOWN)],
                                scroll_requester=driver)
        self.assertTrue(resumed.resume_from(previous))
        self.assertEqual(resumed.start()["terminationReason"], REASON_STORE_FAILED)
        self.assertEqual(driver.requests, [])

    def test_resumed_bottom_without_overlap_stays_partial(self):
        previous, first = self._interrupted_middle()
        resumed = self._session([_bgr((40, 50, 60)), _bgr((70, 80, 90))], [
            _observation(STATE_MIDDLE, CHANGE_UNKNOWN), _observation(STATE_BOTTOM, CHANGE_CHANGED)],
            aligner=_unverified)
        self.assertTrue(resumed.resume_from(previous))
        result = resumed.start()
        self.assertEqual(result["coverageStatus"], STATUS_PARTIAL)
        self.assertEqual(result["terminationReason"], REASON_OVERLAP_UNVERIFIED)
        self.assertEqual(result["savedDescriptors"][:2], first["savedDescriptors"])
        self.assertTrue(result["ledger"]["gaps"])
        self.assertFalse(resumed.can_resume(KEY))

    def test_host_arming_resumes_real_session_and_rejects_changed_window_binding(self):
        from warehouse_capture_host import WarehouseCaptureHost
        from test_warehouse_capture_production_arming_v1 import FakeWindow, _bindings
        bindings = _bindings(recordStableKey=KEY)
        sessions = []
        def factory(*, scene, cancellation_token, status_sink, **deadlines):
            attempt = len(sessions)
            def on_event(event):
                if event.get("scrollState"):
                    bindings["scrollState"] = event["scrollState"]
                status_sink(event)
                if attempt == 0 and event["event"] == "segment_saved" and event["segmentCount"] == 2:
                    host.stop()
            colors = [(10, 20, 30), (40, 50, 60)] if attempt == 0 else [(40, 50, 60), (70, 80, 90)]
            states = [STATE_TOP, STATE_MIDDLE] if attempt == 0 else [STATE_MIDDLE, STATE_BOTTOM]
            session = self._session([_bgr(c) for c in colors], [
                _observation(states[0], CHANGE_UNKNOWN), _observation(states[1], CHANGE_CHANGED)],
                cancellation_token=cancellation_token, status_sink=on_event, **deadlines)
            sessions.append(session)
            return session
        host = WarehouseCaptureHost(session_factory=factory, scene_probe=lambda: dict(bindings),
            bindings_probe=lambda: dict(bindings), window_adapter=FakeWindow(),
            driver_available=True, clock=lambda: 0.0, arming_required=True)
        def run():
            prepared = host.prepare()
            self.assertTrue(prepared["ok"], prepared)
            self.assertTrue(host.confirm(prepared["armingToken"])["ok"])
            host._thread.join(10)
            self.assertFalse(host.running)
        run()
        self.assertEqual(host.presentation().coverage_status, STATUS_PARTIAL)
        self.assertTrue(host.presentation().available)
        bindings["warehouseRoi"] = (11, 10, 80, 80)
        self.assertFalse(host.prepare()["ok"])
        bindings["warehouseRoi"] = (10, 10, 80, 80)
        self.assertTrue(host.presentation().available)
        self.assertIn("从当前页继续", host.presentation().message)
        run()
        self.assertEqual(host.presentation().coverage_status, STATUS_COMPLETE)
        self.assertEqual(host.presentation().segment_count, 3)
        self.assertIsNot(sessions[0]._cancellation_token, sessions[1]._cancellation_token)
        self.assertEqual(len(self.driver.requests), 2)
        self.assertIsNone(host._resume_session)

    def test_top_middle_bottom_verified_overlap_is_complete(self):
        top_png = _png((10, 20, 30))
        frames = [top_png, _bgr((40, 50, 60)), _bgr((70, 80, 90))]
        observations = [
            _observation(STATE_TOP, CHANGE_UNKNOWN, "top"),
            _observation(STATE_MIDDLE, CHANGE_CHANGED, "mid"),
            _observation(STATE_BOTTOM, CHANGE_CHANGED, "bot"),
        ]
        result = self._session(frames, observations).start()
        self.assertTrue(result["accepted"])
        self.assertEqual(result["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(result["terminationReason"], "COMPLETE")
        self.assertTrue(result["finalized"])
        self.assertEqual(result["scrollRequestCount"], 2)
        self.assertEqual(len(self.driver.requests), 2)
        listed = self.store.list_record_evidence(KEY)
        self.assertEqual(len(listed), 3)
        self.assertTrue(all(item["kind"] == KIND_WAREHOUSE_SEGMENT for item in listed))
        top_digest = hashlib.sha256(top_png).hexdigest()
        by_hash = {item["sha256"]: item for item in listed}
        self.assertIn(top_digest, by_hash)
        self.assertEqual(self.store.load_original(by_hash[top_digest]), top_png)
        self.assertEqual(len(self._blobs()), 3)
        self.assertEqual(result["ledger"]["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(len(result["ledger"]["overlapProofs"]), 2)
        self.assertTrue(all(item["relativePath"].startswith("evidence/settlement_v2/") for item in listed))
        for path in self._blobs():
            self.assertTrue(str(path).startswith(str(self.root)))

    def test_noscroll_single_viewport_is_complete(self):
        frames = [_bgr((3, 4, 5))]
        observations = [_observation(STATE_NO_SCROLL, CHANGE_UNKNOWN, "full")]
        result = self._session(frames, observations).start()
        self.assertEqual(result["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(result["terminationReason"], "COMPLETE")
        self.assertEqual(result["scrollRequestCount"], 0)
        self.assertEqual(self.driver.requests, [])
        self.assertEqual(len(self.store.list_record_evidence(KEY)), 1)
        self.assertEqual(len(result["ledger"]["segments"]), 1)
        self.assertTrue(result["ledger"]["topEndpoint"]["trusted"])
        self.assertTrue(result["ledger"]["bottomEndpoint"]["trusted"])

    def test_settlement_warehouse_capture_does_not_require_amount_stability(self):
        scene = _settlement(stable=False)
        scene["warehousePresent"] = True
        result = self._session(
            [_bgr((8, 9, 10))],
            [_observation(STATE_NO_SCROLL, CHANGE_UNKNOWN, "early")],
            validator=ScriptedValidator([scene]),
        ).start()
        self.assertTrue(result["accepted"])
        self.assertEqual(result["terminationReason"], "COMPLETE")
        self.assertEqual(len(result["savedDescriptors"]), 1)

    def test_start_from_middle_bottom_unknown_is_rejected_with_zero_writes(self):
        for state in (STATE_MIDDLE, STATE_BOTTOM, STATE_UNKNOWN):
            store = SettlementEvidenceStoreV2(self.root / state)
            driver = RecordingScrollRequester()
            session = self._session(
                [_bgr((9, 9, 9))],
                [_observation(state, CHANGE_UNKNOWN, state.lower())],
                store=store,
                scroll_requester=driver,
            )
            result = session.start()
            self.assertFalse(result["accepted"], state)
            self.assertEqual(result["terminationReason"], REASON_START_REQUIRES_TOP, state)
            self.assertEqual(result["coverageStatus"], STATUS_UNPROVEN, state)
            self.assertEqual(store.list_record_evidence(KEY), [], state)
            self.assertEqual(driver.requests, [], state)
            self.assertEqual(result["savedDescriptors"], [], state)

    def test_user_stop_timeout_window_lost_scene_left_are_partial(self):
        cases = []

        token = {"cancelled": False}

        def sink_cancel(event):
            self.events.append(dict(event))
            if event["event"] == "segment_saved":
                token["cancelled"] = True

        class Token:
            def is_cancelled(self):
                return token["cancelled"]

        cases.append(
            (
                REASON_USER_STOP,
                dict(
                    frames=[_bgr((1, 1, 1)), _bgr((2, 2, 2))],
                    observations=[
                        _observation(STATE_TOP, CHANGE_UNKNOWN, "t"),
                        _observation(STATE_MIDDLE, CHANGE_CHANGED, "m"),
                    ],
                    extras={"cancellation_token": Token(), "status_sink": sink_cancel},
                ),
            )
        )
        timeout_clock = CountingClock()

        def sink_timeout(event):
            self.events.append(dict(event))
            if event["event"] == "segment_saved":
                timeout_clock.t = 100.0

        cases.append(
            (
                REASON_TIMEOUT,
                dict(
                    frames=[_bgr((3, 3, 3)), _bgr((4, 4, 4))],
                    observations=[
                        _observation(STATE_TOP, CHANGE_UNKNOWN, "t"),
                        _observation(STATE_MIDDLE, CHANGE_CHANGED, "m"),
                    ],
                    extras={
                        "clock": timeout_clock,
                        "timeout_s": 15.0,
                        "status_sink": sink_timeout,
                    },
                ),
            )
        )
        cases.append(
            (
                REASON_WINDOW_LOST,
                dict(
                    frames=[_bgr((5, 5, 5)), {"window_lost": True}],
                    observations=[_observation(STATE_TOP, CHANGE_UNKNOWN, "t")],
                    extras={},
                ),
            )
        )
        cases.append(
            (
                REASON_SCENE_LEFT,
                dict(
                    frames=[_bgr((6, 6, 6)), _bgr((7, 7, 7))],
                    observations=[
                        _observation(STATE_TOP, CHANGE_UNKNOWN, "t"),
                        _observation(STATE_MIDDLE, CHANGE_CHANGED, "m"),
                    ],
                    extras={
                        "validator": ScriptedValidator(
                            [_settlement(), {"isSettlement": False, "stable": True, "recordStableKey": KEY}]
                        )
                    },
                ),
            )
        )

        for reason, spec in cases:
            with self.subTest(reason=reason):
                isolated = SettlementEvidenceStoreV2(self.root / reason)
                driver = RecordingScrollRequester()
                session = self._session(
                    spec["frames"],
                    spec["observations"],
                    store=isolated,
                    scroll_requester=driver,
                    **spec["extras"],
                )
                result = session.start()
                self.assertEqual(result["terminationReason"], reason)
                self.assertEqual(result["coverageStatus"], STATUS_PARTIAL)
                self.assertTrue(result["finalized"])
                self.assertEqual(len(isolated.list_record_evidence(KEY)), 1)
                self.assertEqual(len(result["savedDescriptors"]), 1)
                self.assertNotEqual(result["coverageStatus"], STATUS_COMPLETE)

    def test_overlap_unverified_and_conflict_are_partial(self):
        for reason, aligner in (
            (REASON_OVERLAP_UNVERIFIED, _unverified),
            (REASON_OVERLAP_CONFLICT, _conflict),
        ):
            with self.subTest(reason=reason):
                isolated = SettlementEvidenceStoreV2(self.root / reason)
                driver = RecordingScrollRequester()
                result = self._session(
                    [_bgr((11, 12, 13)), _bgr((14, 15, 16))],
                    [
                        _observation(STATE_TOP, CHANGE_UNKNOWN, "t"),
                        _observation(STATE_MIDDLE, CHANGE_CHANGED, "m"),
                    ],
                    store=isolated,
                    scroll_requester=driver,
                    aligner=aligner,
                ).start()
                self.assertEqual(result["terminationReason"], reason)
                self.assertEqual(result["coverageStatus"], STATUS_PARTIAL)
                self.assertEqual(len(isolated.list_record_evidence(KEY)), 2)
                self.assertEqual(len(result["ledger"]["gaps"]), 1)
                self.assertNotEqual(result["coverageStatus"], STATUS_COMPLETE)
                self.assertEqual(len(driver.requests), 1)

    def test_store_failure_has_no_fake_descriptor_and_is_partial(self):
        failing = FailingAfterStore(self.store, fail_on=2)
        result = self._session(
            [_bgr((21, 22, 23)), _bgr((24, 25, 26))],
            [
                _observation(STATE_TOP, CHANGE_UNKNOWN, "t"),
                _observation(STATE_MIDDLE, CHANGE_CHANGED, "m"),
            ],
            store=failing,
        ).start()
        self.assertEqual(result["terminationReason"], REASON_STORE_FAILED)
        self.assertEqual(result["coverageStatus"], STATUS_PARTIAL)
        listed = self.store.list_record_evidence(KEY)
        self.assertEqual(len(listed), 1)
        self.assertEqual(len(result["savedDescriptors"]), 1)
        self.assertEqual(len(result["ledger"]["segments"]), 1)
        self.assertTrue(all(item.get("evidenceId") for item in result["savedDescriptors"]))
        self.assertEqual(len(self._blobs()), 1)

    def test_repeated_unchanged_frames_are_not_saved_twice(self):
        frame = _bgr((31, 32, 33))
        result = self._session(
            [frame, frame, frame, frame],
            [
                _observation(STATE_TOP, CHANGE_UNKNOWN, "same"),
                _observation(STATE_TOP, CHANGE_UNCHANGED, "same"),
                _observation(STATE_TOP, CHANGE_UNCHANGED, "same"),
                _observation(STATE_TOP, CHANGE_UNCHANGED, "same"),
            ],
            max_unchanged=3,
        ).start()
        self.assertEqual(result["terminationReason"], REASON_CONSECUTIVE_UNCHANGED)
        self.assertEqual(result["coverageStatus"], STATUS_PARTIAL)
        self.assertEqual(len(self.store.list_record_evidence(KEY)), 1)
        self.assertEqual(len(self._blobs()), 1)
        self.assertEqual(len(result["savedDescriptors"]), 1)

    def test_safety_step_limit_is_partial_not_complete(self):
        result = self._session(
            [_bgr((41, 42, 43)), _bgr((44, 45, 46)), _bgr((47, 48, 49))],
            [
                _observation(STATE_TOP, CHANGE_UNKNOWN, "t"),
                _observation(STATE_MIDDLE, CHANGE_CHANGED, "m"),
                _observation(STATE_BOTTOM, CHANGE_CHANGED, "b"),
            ],
            max_steps=1,
        ).start()
        self.assertEqual(result["terminationReason"], REASON_SAFETY_STEP_LIMIT)
        self.assertEqual(result["coverageStatus"], STATUS_PARTIAL)
        self.assertNotEqual(result["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(result["scrollRequestCount"], 1)
        self.assertEqual(len(self.store.list_record_evidence(KEY)), 2)
        self.assertEqual(len(self.driver.requests), 1)

    def test_stable_key_change_is_immediate_partial(self):
        result = self._session(
            [_bgr((51, 52, 53)), _bgr((54, 55, 56))],
            [
                _observation(STATE_TOP, CHANGE_UNKNOWN, "t"),
                _observation(STATE_MIDDLE, CHANGE_CHANGED, "m"),
            ],
            validator=ScriptedValidator([_settlement(KEY), _settlement("recWHOther")]),
        ).start()
        self.assertEqual(result["terminationReason"], REASON_STABLE_KEY_CHANGED)
        self.assertEqual(result["coverageStatus"], STATUS_PARTIAL)
        self.assertEqual(len(self.store.list_record_evidence(KEY)), 1)
        self.assertEqual(self.store.list_record_evidence("recWHOther"), [])
        self.assertEqual(len(self.driver.requests), 1)

    def test_missing_driver_and_production_driver_are_disabled(self):
        self.assertIsNotNone(get_production_scroll_driver())
        self.assertTrue(PRODUCTION_SCROLL_DRIVER_ENABLED)
        result = self._session(
            [_bgr((61, 62, 63))],
            [_observation(STATE_TOP, CHANGE_UNKNOWN, "t")],
            scroll_requester=None,
        ).start()
        self.assertEqual(result["terminationReason"], REASON_SCROLL_DRIVER_NOT_CONFIGURED)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["savedDescriptors"], [])
        self.assertEqual(self.store.list_record_evidence(KEY), [])
        self.assertEqual(self._blobs(), [])

    def test_fake_driver_records_requests_without_os_input(self):
        result = self._session(
            [_bgr((71, 72, 73)), _bgr((74, 75, 76)), _bgr((77, 78, 79))],
            [
                _observation(STATE_TOP, CHANGE_UNKNOWN, "t"),
                _observation(STATE_MIDDLE, CHANGE_CHANGED, "m"),
                _observation(STATE_BOTTOM, CHANGE_CHANGED, "b"),
            ],
        ).start()
        self.assertEqual(result["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(self.driver.requests, [
            {"action": "NEXT_SCROLL", "direction": "DOWN"},
            {"action": "NEXT_SCROLL", "direction": "DOWN"},
        ])
        requester_src = inspect.getsource(RecordingScrollRequester)
        session_src = (CORE_DIR / "warehouse_capture_session.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_INPUT_TOKENS:
            self.assertNotIn(token, requester_src)
            self.assertNotIn(token, session_src)
        self.assertNotIn("import ctypes", session_src)
        self.assertNotIn("warehouse_vision", session_src)
        self.assertNotIn("canonical_history", session_src)
        self.assertNotIn("settlement_truth_reviewer", session_src)
        for event in result["statusEvents"]:
            self.assertNotIn("ledger", event)
            self.assertNotIn("store", event)
            self.assertFalse(any(hasattr(value, "add_segment") or hasattr(value, "save_original") for value in event.values()))

    def test_noscroll_does_not_need_driver(self):
        result = self._session(
            [_bgr((81, 82, 83))],
            [_observation(STATE_NO_SCROLL, CHANGE_UNKNOWN, "full")],
            scroll_requester=None,
        ).start()
        self.assertEqual(result["coverageStatus"], STATUS_COMPLETE)
        self.assertEqual(result["scrollRequestCount"], 0)


if __name__ == "__main__":
    unittest.main()
