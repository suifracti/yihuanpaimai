import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.join(PROJECT_ROOT, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from desktop_pet import (  # noqa: E402
    DesktopPetPositionState,
    DesktopPetPositionStore,
    MonitorWorkArea,
    _extract_scaled_pargb,
    alpha_hit_test,
    clamp_pet_position,
)


class DesktopPetContractTests(unittest.TestCase):
    def test_alpha_hit_test_passes_only_authored_visible_pixels(self):
        alpha = bytes((0, 4, 8, 255))
        self.assertFalse(alpha_hit_test(alpha, 2, 2, 0, 0))
        self.assertFalse(alpha_hit_test(alpha, 2, 2, 1, 0))
        self.assertTrue(alpha_hit_test(alpha, 2, 2, 0, 1))
        self.assertTrue(alpha_hit_test(alpha, 2, 2, 1, 1))
        self.assertFalse(alpha_hit_test(alpha, 2, 2, -1, 0))
        self.assertFalse(alpha_hit_test(alpha, 2, 2, 2, 0))

    def test_position_clamp_preserves_negative_secondary_monitor_coordinates(self):
        monitors = (
            MonitorWorkArea("primary", 0, 0, 1920, 1040),
            MonitorWorkArea("left", -1280, 0, 0, 984),
        )
        x, y, monitor = clamp_pet_position(
            -1200, 50, 180, 160, monitors, "left"
        )
        self.assertEqual((x, y, monitor), (-1200, 50, "left"))

    def test_missing_monitor_and_offscreen_position_fail_closed_to_primary(self):
        monitors = (
            MonitorWorkArea("primary", 0, 0, 1920, 1040),
            MonitorWorkArea("right", 1920, 0, 3840, 1040),
        )
        x, y, monitor = clamp_pet_position(
            8000, -5000, 180, 160, monitors, "disconnected"
        )
        self.assertEqual(monitor, "primary")
        self.assertGreaterEqual(x, 12)
        self.assertGreaterEqual(y, 12)
        self.assertLessEqual(x + 180, 1920 - 12)
        self.assertLessEqual(y + 160, 1040 - 12)

    def test_position_store_roundtrips_visibility_monitor_negative_xy_and_dpi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            store = DesktopPetPositionStore(path)
            state = DesktopPetPositionState(False, "left", -900, 80, 144)
            store.save(state)
            self.assertEqual(store.load(), state)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], 1)
            self.assertFalse((path.parent / "state.json.tmp").exists())

    def test_corrupt_position_store_uses_safe_visible_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(
                DesktopPetPositionStore(path).load(), DesktopPetPositionState()
            )

    def test_pet_module_has_no_webview_solver_or_business_runtime_import(self):
        path = os.path.join(APP_DIR, "desktop_pet.py")
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
        forbidden = {
            "webview",
            "Microsoft.Web.WebView2.Core",
            "auction_brain",
            "vision_pipeline",
            "live_shadow",
            "session_fsm",
        }
        self.assertTrue(imports.isdisjoint(forbidden), imports & forbidden)

    def test_main_constructs_one_pet_and_keeps_one_application_message_loop(self):
        source = Path(os.path.join(APP_DIR, "main.py")).read_text(encoding="utf-8")
        self.assertEqual(source.count("DesktopPetController("), 1)
        self.assertEqual(source.count("WinForms.Application.Run(main_window)"), 1)
        self.assertNotIn("Application.Run(desktop_pet", source)
        self.assertIn('(\"close-desktop-pet\", desktop_pet.close)', source)

    def test_pet_uses_per_pixel_layered_rendering_without_transparency_key(self):
        source = Path(os.path.join(APP_DIR, "desktop_pet.py")).read_text(
            encoding="utf-8"
        )
        self.assertIn("WS_EX_LAYERED", source)
        self.assertIn("UpdateLayeredWindow", source)
        self.assertIn("Format32bppPArgb", source)
        self.assertIn("WM_NCHITTEST", source)
        self.assertIn("HTTRANSPARENT", source)
        self.assertNotIn("TransparencyKey", source)
        self.assertIn('menu.Items.Add("打开主窗口")', source)
        self.assertIn('menu.Items.Add("隐藏桌宠")', source)
        self.assertNotIn("NotifyIcon", source)
        self.assertNotIn("Thread(", source)

    @unittest.skipUnless(os.name == "nt", "System.Drawing renderer is Windows-only")
    def test_dpi_render_rebuilds_from_frozen_source_and_keeps_hit_mask_in_sync(self):
        import clr

        clr.AddReference("System.Drawing")
        import System.Drawing as Drawing

        asset = Path(
            PROJECT_ROOT,
            "design",
            "mascot",
            "exports",
            "chibi",
            "mascot_chibi_idle.png",
        )
        width_96, height_96, pixels_96, alpha_96 = _extract_scaled_pargb(
            Drawing, asset, 96
        )
        width_144, height_144, pixels_144, alpha_144 = _extract_scaled_pargb(
            Drawing, asset, 144
        )
        self.assertEqual((width_96, height_96), (140, 133))
        self.assertEqual((width_144, height_144), (210, 200))
        self.assertEqual(len(pixels_96), width_96 * height_96 * 4)
        self.assertEqual(len(alpha_96), width_96 * height_96)
        self.assertEqual(len(pixels_144), width_144 * height_144 * 4)
        self.assertEqual(len(alpha_144), width_144 * height_144)
        self.assertEqual(alpha_96[0], 0)
        self.assertEqual(alpha_144[0], 0)
        self.assertGreater(max(alpha_96), 200)
        self.assertGreater(max(alpha_144), 200)

    def test_bridge_action_surface_does_not_expand_for_pet(self):
        from main_window import MainWindowBridge

        self.assertEqual(
            MainWindowBridge.ALLOWED_ACTIONS,
            frozenset(("toggle_overlay", "get_overlay_visibility", "toggle_main_pin", "set_main_pin", "request_app_status", "delete_history_record", "delete_history_records", "request_legacy_archive", "select_legacy_archive_source", "request_settlement_review", "import_settlement_screenshot", "replace_settlement_screenshot", "delete_settlement_screenshot", "rerun_settlement_recognition", "save_settlement_review", "settlement_item_review_action", "manual_facts", "manual_next_match", "manual_finalize", "manual_bootstrap", "triggered_snapshot", "save_settlement_screenshot", "save_game_screenshot", "start_warehouse_capture", "prepare_warehouse_capture", "confirm_warehouse_capture", "stop_warehouse_capture", "request_warehouse_slot_evidence", "warehouse_instance_decision", "warehouse_identity_review", "export_history_records", "import_history_bundle")),
        )


if __name__ == "__main__":
    unittest.main()
