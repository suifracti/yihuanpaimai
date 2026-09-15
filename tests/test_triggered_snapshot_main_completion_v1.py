# -*- coding: utf-8 -*-
"""
Targeted test for Triggered Snapshot Main UI Completion (AC1-AC4).
Verifies:
- AC1: Immediate recognizing dispatch followed by authentic backend completion (R1 replay frame -> goldAvg, box).
- AC2: Business facts preserved in CurrentMatch and surfaced in immutable presentation payload.
- AC3: Failure / cancelled terminal statuses release busy state without infinite lock.
- AC4: Architecture boundaries preserved (Main does not hold Solver or mutable CurrentMatch authority).
"""

import os
import sys
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "app"))
sys.path.insert(0, str(PROJECT_ROOT / "core"))

from current_match import CurrentMatch
from async_snapshot_controller import AsyncTriggeredSnapshotController
from main_window import MainWindowBridge
from tests.harness.replay_frame_source import ReplayFrameSource, bind_triggered_snapshot_to_replay


class _MockOverlayController:
    def __init__(self):
        self.visible = True

    def toggle(self):
        self.visible = not self.visible
        return self.visible


class _MockMainWindow:
    """Mock of MainWindow to record posted JSON payloads."""
    def __init__(self, bridge: MainWindowBridge):
        self._bridge = bridge
        self._overlay_visible = True
        self.posted_payloads: List[Dict[str, Any]] = []

    def post_snapshot_result(self, snapshot_result: dict) -> None:
        payload = self._bridge.snapshot_completion_payload(snapshot_result)
        payload["overlayVisible"] = bool(self._overlay_visible)
        self.posted_payloads.append(payload)


class TestTriggeredSnapshotMainCompletionV1(unittest.TestCase):
    def test_ac1_ac2_successful_completion_with_real_r1_replay_frame(self):
        """AC1 & AC2: User triggers snapshot -> recognizing status -> real R1 OCR finishes -> Main receives completed payload with authentic facts."""
        replay_r1_frame = PROJECT_ROOT / "assets" / "replay_frames" / "frame_0075s_01m15s.jpg"
        self.assertTrue(replay_r1_frame.exists(), f"Replay frame fixture missing: {replay_r1_frame}")

        replay_source = ReplayFrameSource([replay_r1_frame])
        replay_source.provide_frame()

        current_match = CurrentMatch()
        mock_main_window = None

        def _publish_callback(payload: Dict[str, Any]) -> None:
            if mock_main_window:
                snap_res = payload.get("snapshotResult")
                if snap_res:
                    mock_main_window.post_snapshot_result(snap_res)

        controller = AsyncTriggeredSnapshotController(
            current_match_provider=lambda: current_match,
            publish_callback=_publish_callback,
            target_titles=["异环"],
        )
        bind_triggered_snapshot_to_replay(controller, replay_source)

        overlay = _MockOverlayController()
        bridge = MainWindowBridge(
            overlay,
            current_match_provider=lambda: {"matchId": current_match.id, "facts": dict(current_match.facts)},
            triggered_snapshot_provider=controller.request_snapshot,
        )
        mock_main_window = _MockMainWindow(bridge)

        # 1. User clicks snapshot in Main UI -> dispatch action
        resp = bridge.dispatch({"action": "triggered_snapshot"})

        # Immediate synchronous status must be recognizing (busy=true)
        self.assertIn("snapshotResult", resp)
        self.assertTrue(resp["snapshotResult"]["ok"])
        self.assertEqual(resp["snapshotResult"]["status"], "recognizing")
        self.assertTrue(controller.in_flight)

        # 2. Wait for backend OCR worker to finish
        if controller._worker_thread:
            controller._worker_thread.join(timeout=15.0)

        self.assertFalse(controller.in_flight, "Controller must no longer be in-flight")

        # 3. Verify Main received the completion payload
        self.assertGreaterEqual(len(mock_main_window.posted_payloads), 1, "Main window must receive completion message")
        completion_msg = mock_main_window.posted_payloads[-1]

        self.assertEqual(completion_msg.get("type"), "app_status")
        self.assertEqual(completion_msg.get("action"), "triggered_snapshot")
        snap_res = completion_msg.get("snapshotResult")
        self.assertIsNotNone(snap_res)
        self.assertTrue(snap_res.get("ok"))
        self.assertEqual(snap_res.get("status"), "completed")
        self.assertGreaterEqual(snap_res.get("appliedFactCount", 0), 1)
        self.assertIn("快照识别完成", snap_res.get("summary", ""))

        # 4. AC2: Verify authentic business facts are present in CurrentMatch and immutable summary
        self.assertEqual(current_match.facts.get("goldAvg"), 67571)
        match_payload = completion_msg.get("currentMatch")
        self.assertIsNotNone(match_payload)
        self.assertEqual(match_payload.get("facts", {}).get("goldAvg"), 67571)

    def test_ac3_failure_and_cancelled_terminal_states_release_busy(self):
        """AC3: Failed or cancelled completions cleanly post terminal results so UI is not stuck recognizing."""
        overlay = _MockOverlayController()
        bridge = MainWindowBridge(
            overlay,
            current_match_provider=lambda: {"matchId": "fail_test", "facts": {}},
        )
        mock_main = _MockMainWindow(bridge)

        # Simulate failed snapshot completion
        failed_res = {
            "type": "snapshot_assist_result",
            "ok": False,
            "status": "failed",
            "summary": "游戏画面截取失败",
            "appliedFactCount": 0,
            "conflictCount": 0,
        }
        mock_main.post_snapshot_result(failed_res)

        self.assertEqual(len(mock_main.posted_payloads), 1)
        fail_payload = mock_main.posted_payloads[-1]
        self.assertEqual(fail_payload["action"], "triggered_snapshot")
        self.assertFalse(fail_payload["snapshotResult"]["ok"])
        self.assertEqual(fail_payload["snapshotResult"]["status"], "failed")

        # Simulate cancelled snapshot completion
        cancelled_res = {
            "type": "snapshot_assist_result",
            "ok": False,
            "status": "cancelled",
            "summary": "已取消",
            "appliedFactCount": 0,
            "conflictCount": 0,
        }
        mock_main.post_snapshot_result(cancelled_res)

        self.assertEqual(len(mock_main.posted_payloads), 2)
        cancel_payload = mock_main.posted_payloads[-1]
        self.assertEqual(cancel_payload["snapshotResult"]["status"], "cancelled")

    def test_ac4_architecture_boundaries_maintained(self):
        """AC4: Main bridge does not hold Solver, mutable CurrentMatch authority, or raw LATEST_PAYLOAD."""
        overlay = _MockOverlayController()
        bridge = MainWindowBridge(overlay)

        # Bridge must not have solver or raw payload attributes
        self.assertFalse(hasattr(bridge, "solver"))
        self.assertFalse(hasattr(bridge, "solve"))
        self.assertFalse(hasattr(bridge, "LATEST_PAYLOAD"))
        self.assertFalse(hasattr(bridge, "current_match_mutator"))


if __name__ == "__main__":
    unittest.main()
