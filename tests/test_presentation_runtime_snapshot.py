import dataclasses
import json
import os
import subprocess
import sys
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(PROJECT_ROOT, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from main_window import MainWindowBridge, OverlayVisibilityController
from presentation_runtime import PresentationRuntimeState


class _FakeOverlay:
    def __init__(self):
        self.Visible = True

    def Show(self):
        self.Visible = True

    def Hide(self):
        self.Visible = False


class PresentationRuntimeSnapshotTests(unittest.TestCase):
    def test_snapshot_is_frozen_and_payload_is_scalar_whitelist(self):
        state = PresentationRuntimeState("running")
        state.observe_transport(
            {
                "scene": "IN_AUCTION",
                "shadowUpdating": True,
                "canonical": {"secret": True},
                "solverInput": {"q": 1},
                "settlementData": {"profit": 9},
                "ocrText": "forbidden",
            }
        )
        snapshot = state.snapshot()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.scene_class = "loading"
        payload = snapshot.to_payload()
        self.assertEqual(
            payload,
            {
                "snapshotVersion": 1,
                "visionProcessState": "running",
                "refreshPending": False,
                "sceneClass": "auction",
                "shadowUpdating": True,
            },
        )

    def test_refresh_completion_is_request_correlated(self):
        state = PresentationRuntimeState()
        state.begin_refresh("new-request")
        state.observe_transport(
            {
                "refreshRequestId": "old-request",
                "refreshPending": False,
                "scene": "AUCTION_LOBBY",
            }
        )
        self.assertTrue(state.snapshot().refresh_pending)
        self.assertEqual(state.snapshot().scene_class, "unknown")
        state.observe_transport(
            {"refreshRequestId": "new-request", "refreshPending": False}
        )
        self.assertFalse(state.snapshot().refresh_pending)

    def test_non_running_vision_clears_pending_refresh_fail_closed(self):
        state = PresentationRuntimeState("running")
        state.begin_refresh("request")
        state.set_vision_process_state("exited")
        self.assertFalse(state.snapshot().refresh_pending)
        self.assertEqual(state.snapshot().vision_process_state, "exited")

    def test_scene_and_shadow_are_sanitized_without_stale_shadow(self):
        state = PresentationRuntimeState()
        state.observe_transport({"inAuction": True, "shadowUpdating": True})
        self.assertEqual(state.snapshot().scene_class, "auction")
        self.assertTrue(state.snapshot().shadow_updating)
        state.observe_transport({"scene": "AUCTION_LOADING", "isLoading": True})
        self.assertEqual(state.snapshot().scene_class, "loading")
        self.assertFalse(state.snapshot().shadow_updating)
        state.observe_transport({"scene": "AUCTION_LOBBY", "inLobby": True})
        self.assertEqual(state.snapshot().scene_class, "lobby")

    def test_bridge_returns_fresh_snapshot_without_expanding_actions(self):
        state = PresentationRuntimeState("running")
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()), state.snapshot
        )
        first = bridge.dispatch({"action": "request_app_status"})
        first["presentationRuntime"]["sceneClass"] = "tampered"
        second = bridge.dispatch({"action": "request_app_status"})
        self.assertEqual(second["presentationRuntime"]["sceneClass"], "unknown")
        self.assertEqual(
            MainWindowBridge.ALLOWED_ACTIONS,
            frozenset(("toggle_overlay", "get_overlay_visibility", "toggle_main_pin", "set_main_pin", "request_app_status", "delete_history_record", "delete_history_records", "request_legacy_archive", "select_legacy_archive_source", "request_settlement_review", "import_settlement_screenshot", "replace_settlement_screenshot", "delete_settlement_screenshot", "rerun_settlement_recognition", "save_settlement_review", "settlement_item_review_action", "manual_facts", "manual_next_match", "manual_finalize", "manual_bootstrap", "triggered_snapshot", "save_settlement_screenshot", "save_game_screenshot", "start_warehouse_capture", "prepare_warehouse_capture", "confirm_warehouse_capture", "stop_warehouse_capture", "warehouse_identity_review", "export_history_records", "import_history_bundle")),
        )

    def test_bridge_rejects_mutable_provider_objects(self):
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            lambda: {"snapshotVersion": 1, "canonical": {}},
        )
        with self.assertRaises(TypeError):
            bridge.dispatch({"action": "request_app_status"})

    def test_javascript_is_a_thin_host_snapshot_consumer(self):
        script = r"""
const binding = require('./core/mascot_runtime_binding.js');
const cases = {
  idle: binding.consumeHostMascotState({snapshotVersion: 1, state: 'idle', assetId: 'mascot.chibi.idle'}),
  loading: binding.consumeHostMascotState({snapshotVersion: 1, state: 'loading', assetId: 'mascot.chibi.loading.v2'}),
  success: binding.consumeHostMascotState({snapshotVersion: 1, state: 'success', assetId: 'mascot.chibi.success'}),
  malformed: binding.consumeHostMascotState({snapshotVersion: 1, state: 'idle'})
};
console.log(JSON.stringify(cases));
"""
        output = subprocess.check_output(
            ["node", "-e", script], cwd=PROJECT_ROOT, encoding="utf-8"
        )
        states = json.loads(output)
        self.assertEqual(states["idle"]["state"], "idle")
        self.assertEqual(states["loading"]["state"], "loading")
        self.assertIsNone(states["success"])
        self.assertIsNone(states["malformed"])

    def test_main_uses_existing_status_action_and_stops_polling_on_shutdown(self):
        path = os.path.join(PROJECT_ROOT, "core", "main_window.js")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('postNative("request_app_status")', source)
        self.assertIn('payload.applicationState === "shutting_down"', source)
        self.assertIn("dashboard.mascotPresentation === null", source)
        self.assertIn("window.clearInterval(dashboard.statusPollTimer)", source)
        self.assertNotIn('postNative("set_mascot_state")', source)


if __name__ == "__main__":
    unittest.main()
