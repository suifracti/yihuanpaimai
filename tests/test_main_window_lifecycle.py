import ast
import os
import sys
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(PROJECT_ROOT, "app")
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from main_window import MainWindowBridge, OverlayVisibilityController, ShutdownCoordinator
from main_view_state import unavailable_main_view_state_snapshot


class _FakeOverlay:
    def __init__(self):
        self.Visible = True
        self.WebView = object()
        self.show_calls = 0
        self.hide_calls = 0

    def Show(self):
        self.show_calls += 1
        self.Visible = True

    def Hide(self):
        self.hide_calls += 1
        self.Visible = False


class MainWindowLifecycleTests(unittest.TestCase):
    def test_live_trial_drafts_are_visible_without_entering_formal_history_counts(self):
        draft = {"id": "trial-match", "lifecycleStatus": "DRAFT", "dataOrigin": "live-trial"}
        bridge = MainWindowBridge(
            None,
            main_view_state_provider=lambda: unavailable_main_view_state_snapshot(
                "UNAVAILABLE", "history-not-ready"
            ),
            live_trial_drafts_provider=lambda: [draft],
        )

        payload = bridge.main_view_state_payload()

        self.assertEqual(payload["history"]["liveTrialDrafts"], [draft])
        self.assertEqual(payload["history"]["recentRecords"], [])
        self.assertEqual(payload["history"]["totalCount"], None)

    def test_main_bridge_toggles_the_existing_overlay_controller(self):
        overlay = _FakeOverlay()
        controller = OverlayVisibilityController(overlay)
        bridge = MainWindowBridge(controller)

        response = bridge.dispatch('{"action":"toggle_overlay","requestId":"r-1"}')

        self.assertFalse(response["overlayVisible"])
        self.assertEqual(response["requestId"], "r-1")
        self.assertEqual(overlay.hide_calls, 1)
        self.assertIs(controller.overlay, overlay)

    def test_main_bridge_restart_reports_provider_outcome(self):
        for outcome in (True, False):
            calls = []
            bridge = MainWindowBridge(
                OverlayVisibilityController(_FakeOverlay()),
                start_vision_provider=lambda: calls.append(True) or outcome,
            )
            result = bridge.dispatch({"action": "start_live_vision"})
            self.assertEqual(result["visionStartResult"], {"ok": outcome})
            self.assertEqual(calls, [True])
        bridge = MainWindowBridge(OverlayVisibilityController(_FakeOverlay()))
        self.assertFalse(bridge.dispatch({"action": "start_live_vision"})["visionStartResult"]["ok"])

    def test_main_bridge_status_read_does_not_mutate_overlay(self):
        overlay = _FakeOverlay()
        bridge = MainWindowBridge(OverlayVisibilityController(overlay))

        response = bridge.dispatch({"action": "get_overlay_visibility"})

        self.assertTrue(response["overlayVisible"])
        self.assertEqual(overlay.hide_calls, 0)
        self.assertEqual(overlay.show_calls, 0)
        self.assertEqual(response["solverOwner"], "overlay_runtime")
        self.assertEqual(response["presentationData"], "mock")
        self.assertEqual(
            set(response["presentationRuntime"]),
            {
                "snapshotVersion",
                "visionProcessState",
                "refreshPending",
                "sceneClass",
                "shadowUpdating",
            },
        )

    def test_main_bridge_rejects_non_presentation_authority(self):
        bridge = MainWindowBridge(OverlayVisibilityController(_FakeOverlay()))
        for action in ("solve", "set_current_match", "load_solver", "run_ocr"):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    bridge.dispatch({"action": action})

    def test_main_bridge_routes_triggered_snapshot_as_a_narrow_command(self):
        calls = []
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            triggered_snapshot_provider=lambda: calls.append(True) or {
                "type": "snapshot_assist_result",
                "ok": False,
                "summary": "未检测到游戏窗口",
            },
        )

        response = bridge.dispatch({"action": "triggered_snapshot"})

        self.assertEqual(calls, [True])
        self.assertEqual(response["snapshotResult"]["type"], "snapshot_assist_result")
        self.assertFalse(response["snapshotResult"]["ok"])

    def test_main_bridge_routes_activity_review_and_returns_worker_decision_status(self):
        evidence_payload = {"action": "request_warehouse_slot_evidence", "requestId": "e-1",
                            "matchId": "live-a", "activityEvidenceId": "crop-a"}
        decision_payload = {"action": "warehouse_instance_decision", "requestId": "d-1",
                            "matchId": "live-a", "decision": "CONFIRM_CANDIDATE"}
        calls = []
        bridge = MainWindowBridge(
            OverlayVisibilityController(_FakeOverlay()),
            warehouse_slot_evidence_provider=lambda payload: calls.append(("evidence", payload)) or {
                "ok": True, "sourceAvailable": True, "evidenceId": "crop-a",
            },
            warehouse_instance_decision_provider=lambda payload: calls.append(("decision", payload)) or {
                "status": "PENDING", "commandId": "native-control-14",
            },
        )

        evidence = bridge.dispatch(evidence_payload)
        decision = bridge.dispatch(decision_payload)

        self.assertEqual(calls, [("evidence", evidence_payload), ("decision", decision_payload)])
        self.assertEqual(evidence["warehouseSlotEvidence"]["evidenceId"], "crop-a")
        self.assertEqual(decision["warehouseInstanceDecision"]["status"], "PENDING")

    def test_hide_show_keeps_overlay_and_runtime_identity(self):
        overlay = _FakeOverlay()
        controller = OverlayVisibilityController(overlay)
        overlay_identity = controller.overlay_identity
        runtime = overlay.WebView

        self.assertFalse(controller.toggle())
        self.assertTrue(controller.toggle())

        self.assertIs(controller.overlay, overlay)
        self.assertEqual(controller.overlay_identity, overlay_identity)
        self.assertIs(overlay.WebView, runtime)
        self.assertEqual(overlay.hide_calls, 1)
        self.assertEqual(overlay.show_calls, 1)

    def test_hidden_overlay_does_not_close_or_dispose(self):
        overlay = _FakeOverlay()
        controller = OverlayVisibilityController(overlay)

        controller.hide()

        self.assertFalse(overlay.Visible)
        self.assertFalse(hasattr(overlay, "close_calls"))
        self.assertFalse(hasattr(overlay, "dispose_calls"))

    def test_overlay_topmost_refresh_preserves_explicit_visibility(self):
        path = os.path.join(APP_DIR, "DirectCompositionHost.cs")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()

        self.assertIn("TopmostNoActivateFlags = 0x0013", source)
        self.assertNotIn("SWP_SHOWWINDOW", source)
        self.assertNotIn("0x0053", source)

    def test_visibility_commands_stop_after_shutdown_begins(self):
        overlay = _FakeOverlay()
        controller = OverlayVisibilityController(overlay)
        controller.stop_accepting_commands()

        self.assertTrue(controller.toggle())
        self.assertEqual(overlay.hide_calls, 0)
        self.assertEqual(overlay.show_calls, 0)

    def test_shutdown_coordinator_runs_once_and_in_order(self):
        events = []
        coordinator = ShutdownCoordinator(
            begin_shutdown=lambda: events.append("disable-ui"),
            cleanup_steps=(
                ("draft", lambda: events.append("draft")),
                ("vision", lambda: events.append("vision")),
                ("overlay", lambda: events.append("overlay")),
            ),
            close_main=lambda: events.append("main"),
            prepare_shutdown=lambda: events.append("prepare") or True,
        )

        self.assertTrue(coordinator.request("overlay_exit", True))
        self.assertFalse(coordinator.request("main_close", False))
        self.assertEqual(events, ["prepare", "disable-ui", "draft", "vision", "overlay", "main"])
        self.assertTrue(coordinator.started)
        self.assertEqual(coordinator.reason, "overlay_exit")

    def test_shutdown_keeps_application_running_when_unresolved_draft_close_is_cancelled(self):
        events = []
        coordinator = ShutdownCoordinator(
            begin_shutdown=lambda: events.append("disable-ui"),
            cleanup_steps=(("vision", lambda: events.append("vision")),),
            close_main=lambda: events.append("main"),
            prepare_shutdown=lambda: False,
        )

        self.assertFalse(coordinator.request("main_window_close", False))
        self.assertFalse(coordinator.started)
        self.assertEqual(events, [])

    def test_shutdown_continues_after_one_cleanup_failure(self):
        events = []

        def fail():
            events.append("failed-step")
            raise RuntimeError("expected")

        coordinator = ShutdownCoordinator(
            begin_shutdown=lambda: events.append("disable-ui"),
            cleanup_steps=(("fail", fail), ("after", lambda: events.append("after"))),
            close_main=lambda: events.append("main"),
        )

        self.assertTrue(coordinator.request("test", True))
        self.assertEqual(events, ["disable-ui", "failed-step", "after", "main"])

    def test_source_uses_native_main_as_application_owner(self):
        path = os.path.join(APP_DIR, "main.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()

        self.assertIn("WinForms.Application.Run(main_window)", source)
        self.assertNotIn("WinForms.Application.Run(overlay_form)", source)
        self.assertEqual(source.count("DirectCompositionHudForm("), 1)
        self.assertIn('_business_sot._SOT_PATH = os.path.join(ASSETS_DIR, "business_sot_v06.json")', source)

    def test_overlay_exit_routes_to_coordinator_without_hard_exit(self):
        path = os.path.join(APP_DIR, "main.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        hud_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "HudJsApi")
        exit_method = next(node for node in hud_class.body if isinstance(node, ast.FunctionDef) and node.name == "exit_app")
        method_source = ast.unparse(exit_method)
        self.assertIn("self.shutdown_request", method_source)
        self.assertNotIn("os._exit", method_source)

    def test_main_presentation_host_has_no_solver_or_canonical_state_path(self):
        path = os.path.join(APP_DIR, "main_window.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()

        forbidden = (
            "overlay_alpha.html",
            "auction_engine_v06.js",
            "solver_core_v06.js",
            "v06_adapter.js",
            "CurrentMatch",
        )
        for token in forbidden:
            self.assertNotIn(token, source)

    def test_spec_packages_active_overlay_assets_and_keeps_legacy_hud(self):
        path = os.path.join(APP_DIR, "异环拍卖助手.spec")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()

        for asset in (
            "main_window.html",
            "main_window.css",
            "main_window.js",
            "mascot_runtime_binding.js",
            "overlay_alpha.html",
            "v06_adapter.js",
            "auction_engine_v06.js",
            "tactical_hud.html",
            "business_sot_v06.json",
        ):
            self.assertIn(asset, source)

    def test_main_page_loads_only_its_presentation_assets(self):
        core_dir = os.path.join(PROJECT_ROOT, "core")
        html_path = os.path.join(core_dir, "main_window.html")
        css_path = os.path.join(core_dir, "main_window.css")
        js_path = os.path.join(core_dir, "main_window.js")
        with open(html_path, encoding="utf-8") as fh:
            html = fh.read()
        with open(css_path, encoding="utf-8") as fh:
            css = fh.read()
        with open(js_path, encoding="utf-8") as fh:
            javascript = fh.read()

        self.assertIn('href="main_window.css"', html)
        self.assertIn('src="main_window.js"', html)
        self.assertIn('src="auction_engine_v06.js"', html)
        self.assertIn("AuctionEngineV06.baseCatalogFor", javascript)
        self.assertIn("AuctionEngineV06.normalizeKnownContext", javascript)
        self.assertNotIn("mockDashboardState", javascript)
        self.assertIn("renderHistory", javascript)
        self.assertIn("历史对局", html)
        self.assertIn("History Admission Policy v1", html)
        self.assertIn("--green", css)
        for source in (html, css, javascript):
            for forbidden in (
                "overlay_alpha.html",
                "solver_core_v06.js",
                "v06_adapter.js",
            ):
                self.assertNotIn(forbidden, source)

    def test_main_page_bridge_actions_stay_narrow(self):
        main_js = os.path.join(PROJECT_ROOT, "core", "main_window.js")
        with open(main_js, encoding="utf-8") as fh:
            javascript = fh.read()
        self.assertNotIn("new WebSocket", javascript)
        self.assertNotIn("hudWsClient", javascript)
        self.assertEqual(
            MainWindowBridge.ALLOWED_ACTIONS,
            frozenset(("toggle_overlay", "get_overlay_visibility", "toggle_main_pin", "set_main_pin", "request_app_status", "delete_history_record", "delete_history_records", "request_legacy_archive", "select_legacy_archive_source", "request_settlement_review", "import_settlement_screenshot", "replace_settlement_screenshot", "delete_settlement_screenshot", "rerun_settlement_recognition", "save_settlement_review", "settlement_item_review_action", "manual_facts", "manual_next_match", "manual_finalize", "manual_bootstrap", "start_live_vision", "request_original_screenshots", "delete_original_screenshot", "restore_original_screenshot", "export_reviewed_labels", "triggered_snapshot", "save_settlement_screenshot", "save_game_screenshot", "start_warehouse_capture", "prepare_warehouse_capture", "confirm_warehouse_capture", "stop_warehouse_capture", "request_warehouse_slot_evidence", "warehouse_instance_decision", "warehouse_identity_review", "export_history_records", "import_history_bundle")),
        )

    def test_mascot_presentation_does_not_expand_native_bridge_authority(self):
        path = os.path.join(PROJECT_ROOT, "core", "main_window.js")
        with open(path, encoding="utf-8") as fh:
            javascript = fh.read()

        self.assertIn("presentation_only", javascript)
        self.assertNotIn('postNative("set_mascot_state")', javascript)
        self.assertEqual(
            MainWindowBridge.ALLOWED_ACTIONS,
            frozenset(("toggle_overlay", "get_overlay_visibility", "toggle_main_pin", "set_main_pin", "request_app_status", "delete_history_record", "delete_history_records", "request_legacy_archive", "select_legacy_archive_source", "request_settlement_review", "import_settlement_screenshot", "replace_settlement_screenshot", "delete_settlement_screenshot", "rerun_settlement_recognition", "save_settlement_review", "settlement_item_review_action", "manual_facts", "manual_next_match", "manual_finalize", "manual_bootstrap", "start_live_vision", "request_original_screenshots", "delete_original_screenshot", "restore_original_screenshot", "export_reviewed_labels", "triggered_snapshot", "save_settlement_screenshot", "save_game_screenshot", "start_warehouse_capture", "prepare_warehouse_capture", "confirm_warehouse_capture", "stop_warehouse_capture", "request_warehouse_slot_evidence", "warehouse_instance_decision", "warehouse_identity_review", "export_history_records", "import_history_bundle")),
        )


if __name__ == "__main__":
    unittest.main()
