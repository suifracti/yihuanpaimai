"""Targeted unit tests for 4D2D1B2: Foreground Handoff Contract Only.

Tests that after secondary confirmation, if the game window is not yet in foreground:
1. Host enters explicit WAITING_FOR_GAME_FOCUS state without installing hooks or sending wheels;
2. Shows prompt: '请按 Alt+Tab 返回游戏，回到游戏后自动开始';
3. Returning to game via Alt+Tab is NOT treated as user abort;
4. Detects foreground restoration, re-verifies authoritative state (scene, key, ROI, scrollState=TOP, token),
   arms guard and starts session exactly once;
5. If game was already in foreground, follows the exact same verification pipeline;
6. Waiting for focus is a safety pause, not a timeout abort; cancellation, window lost, or binding change still exits with zero input;
7. Never calls SetForegroundWindow or steals focus.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from warehouse_capture_arming import CONFIRM_CAPTION
from warehouse_capture_host import (
    MESSAGE_WAITING_FOR_GAME_FOCUS,
    REASON_BINDING_CHANGED,
    REASON_PREPARED,
    REASON_STARTED,
    REASON_TOKEN_EXPIRED,
    STATE_COMPLETE,
    STATE_IDLE,
    STATE_WAITING_FOR_GAME_FOCUS,
    WarehouseCaptureHost,
)


class _FakeWindowAdapter:
    def __init__(self, game_hwnd: int = 12345, is_fg: bool = False):
        self.game_hwnd = game_hwnd
        self.is_fg = is_fg
        self.visible = True
        self.iconic = False
        self.valid = True
        self.set_foreground_called = 0

    def is_window(self, hwnd: int) -> bool:
        return self.valid and hwnd == self.game_hwnd

    def is_window_visible(self, hwnd: int) -> bool:
        return self.visible and hwnd == self.game_hwnd

    def is_iconic(self, hwnd: int) -> bool:
        return self.iconic

    def get_foreground_window(self) -> int:
        return self.game_hwnd if self.is_fg else 99999

    def SetForegroundWindow(self, hwnd: int) -> bool:
        self.set_foreground_called += 1
        return True


class _FakeGuard:
    def __init__(self, cancel_token=None):
        self.cancel_token = cancel_token
        self.installed = False
        self.armed = False
        self.uninstalled = False

    def install(self) -> bool:
        self.installed = True
        return True

    def arm(self) -> bool:
        self.armed = True
        return True

    def disarm(self) -> None:
        self.armed = False

    def uninstall(self) -> None:
        self.installed = False
        self.armed = False
        self.uninstalled = True


class _FakeSession:
    def __init__(self, scene=None, cancellation_token=None, status_sink=None):
        self.scene = scene
        self.cancellation_token = cancellation_token
        self.status_sink = status_sink
        self.started_count = 0
        self.attached_guard = None
        self.wheels_sent = 0

    def attach_input_abort_guard(self, guard):
        self.attached_guard = guard

    def start(self):
        self.started_count += 1
        return {
            "accepted": True,
            "coverageStatus": "COMPLETE",
            "terminationReason": "COMPLETE",
            "savedDescriptors": [{"path": "seg_01.png"}],
        }


class TestWarehouseForegroundHandoffContract4D2D1B2(unittest.TestCase):
    def _build_snap(
        self,
        *,
        scene: str = "SETTLEMENT",
        is_settlement: bool = True,
        stable: bool = True,
        match_id: str = "match-auth-123",
        hwnd: int = 12345,
        roi: tuple = (1314, 216, 1915, 847),
        scroll_state: str = "TOP",
        foreground: bool = False,
    ) -> Dict[str, Any]:
        return {
            "scene": scene,
            "isSettlement": is_settlement,
            "stable": stable,
            "recordStableKey": match_id,
            "hwnd": hwnd,
            "warehouseRoi": roi,
            "scrollState": scroll_state,
            "storeAvailable": True,
            "foreground": foreground,
            "visible": True,
            "minimized": False,
        }

    def test_handoff_waiting_for_game_focus_and_restore(self):
        snap = self._build_snap(foreground=False)
        win_adapter = _FakeWindowAdapter(game_hwnd=12345, is_fg=False)
        guard_instances = []

        def _guard_factory(cancel_token=None):
            g = _FakeGuard(cancel_token=cancel_token)
            guard_instances.append(g)
            return g

        created_sessions = []

        def _session_factory(**kwargs):
            s = _FakeSession(**kwargs)
            created_sessions.append(s)
            return s

        host = WarehouseCaptureHost(
            session_factory=_session_factory,
            driver_available=True,
            bindings_probe=lambda: snap,
            window_adapter=win_adapter,
            input_guard_factory=_guard_factory,
            arming_required=True,
            foreground_wait_timeout_s=5.0,
        )

        # 1. Prepare secondary confirmation
        prep = host.prepare()
        self.assertTrue(prep["ok"])
        token_id = prep["armingToken"]
        self.assertIsNotNone(token_id)

        # 2. User confirms while game is NOT in foreground (e.g. clicked inside Assistant UI)
        conf = host.confirm(token_id)
        self.assertTrue(conf["ok"])
        self.assertEqual(conf["reason"], REASON_STARTED)

        # 3. Verify host transitions to WAITING_FOR_GAME_FOCUS
        time.sleep(0.08)
        pres = host.presentation()
        self.assertEqual(pres.state, STATE_WAITING_FOR_GAME_FOCUS)
        self.assertEqual(pres.message, MESSAGE_WAITING_FOR_GAME_FOCUS)

        # Verify: NO guard installed, NO guard armed, NO focus stolen
        self.assertEqual(len(guard_instances), 0)
        self.assertEqual(win_adapter.set_foreground_called, 0)
        self.assertEqual(len(created_sessions), 0)

        # 4. User presses Alt+Tab to restore game to foreground
        win_adapter.is_fg = True
        snap["foreground"] = True

        # Wait for worker thread to complete
        time.sleep(0.15)
        self.assertFalse(host.running)
        self.assertEqual(host.presentation().state, STATE_COMPLETE)

        # Verify guard was installed, armed, session run once, and guard uninstalled
        self.assertEqual(len(guard_instances), 1)
        self.assertTrue(guard_instances[0].uninstalled)
        self.assertEqual(len(created_sessions), 1)
        self.assertEqual(created_sessions[0].started_count, 1)
        self.assertEqual(win_adapter.set_foreground_called, 0)

    def test_game_already_foreground_at_confirmation(self):
        snap = self._build_snap(foreground=True)
        win_adapter = _FakeWindowAdapter(game_hwnd=12345, is_fg=True)
        guard_instances = []

        def _guard_factory(cancel_token=None):
            g = _FakeGuard(cancel_token=cancel_token)
            guard_instances.append(g)
            return g

        created_sessions = []

        def _session_factory(**kwargs):
            s = _FakeSession(**kwargs)
            created_sessions.append(s)
            return s

        host = WarehouseCaptureHost(
            session_factory=_session_factory,
            driver_available=True,
            bindings_probe=lambda: snap,
            window_adapter=win_adapter,
            input_guard_factory=_guard_factory,
            arming_required=True,
        )

        prep = host.prepare()
        conf = host.confirm(prep["armingToken"])
        self.assertTrue(conf["ok"])

        time.sleep(0.1)
        self.assertFalse(host.running)
        self.assertEqual(host.presentation().state, STATE_COMPLETE)
        self.assertEqual(len(created_sessions), 1)
        self.assertEqual(win_adapter.set_foreground_called, 0)

    def test_waiting_for_focus_does_not_timeout_abort(self):
        snap = self._build_snap(foreground=False)
        win_adapter = _FakeWindowAdapter(game_hwnd=12345, is_fg=False)
        created_sessions = []

        def _session_factory(**kwargs):
            s = _FakeSession(**kwargs)
            created_sessions.append(s)
            return s

        host = WarehouseCaptureHost(
            session_factory=_session_factory,
            driver_available=True,
            bindings_probe=lambda: snap,
            window_adapter=win_adapter,
            input_guard_factory=lambda **kw: _FakeGuard(**kw),
            arming_required=True,
            foreground_wait_timeout_s=0.05,
        )

        prep = host.prepare()
        host.confirm(prep["armingToken"])

        time.sleep(0.2)
        self.assertTrue(host.running)
        self.assertEqual(host.presentation().state, STATE_WAITING_FOR_GAME_FOCUS)
        self.assertEqual(len(created_sessions), 0)
        self.assertEqual(win_adapter.set_foreground_called, 0)

        win_adapter.is_fg = True
        snap["foreground"] = True
        time.sleep(0.15)
        self.assertFalse(host.running)
        self.assertEqual(host.presentation().state, STATE_COMPLETE)
        self.assertEqual(len(created_sessions), 1)

    def test_cancellation_during_waiting_for_focus(self):
        snap = self._build_snap(foreground=False)
        win_adapter = _FakeWindowAdapter(game_hwnd=12345, is_fg=False)

        host = WarehouseCaptureHost(
            session_factory=_FakeSession,
            driver_available=True,
            bindings_probe=lambda: snap,
            window_adapter=win_adapter,
            input_guard_factory=lambda **kw: _FakeGuard(**kw),
            arming_required=True,
            foreground_wait_timeout_s=5.0,
        )

        prep = host.prepare()
        host.confirm(prep["armingToken"])
        time.sleep(0.05)
        self.assertEqual(host.presentation().state, STATE_WAITING_FOR_GAME_FOCUS)

        # User clicks stop
        stop_res = host.stop()
        self.assertTrue(stop_res["ok"])

        time.sleep(0.1)
        self.assertFalse(host.running)
        pres = host.presentation()
        self.assertEqual(pres.termination_reason, "USER_STOP")

    def test_binding_changed_during_waiting_for_focus_fails_closed(self):
        snap = self._build_snap(foreground=False, match_id="match-orig")
        win_adapter = _FakeWindowAdapter(game_hwnd=12345, is_fg=False)

        host = WarehouseCaptureHost(
            session_factory=_FakeSession,
            driver_available=True,
            bindings_probe=lambda: snap,
            window_adapter=win_adapter,
            input_guard_factory=lambda **kw: _FakeGuard(**kw),
            arming_required=True,
            foreground_wait_timeout_s=2.0,
        )

        prep = host.prepare()
        host.confirm(prep["armingToken"])
        time.sleep(0.05)

        # Match changed before user returns to game
        snap["recordStableKey"] = "match-tampered"
        win_adapter.is_fg = True
        snap["foreground"] = True

        time.sleep(0.1)
        self.assertFalse(host.running)
        pres = host.presentation()
        self.assertEqual(pres.termination_reason, REASON_BINDING_CHANGED)


if __name__ == "__main__":
    unittest.main()
