import ast
import inspect
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
ASSETS_DIR = PROJECT_ROOT / "assets"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(CORE_DIR))

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
import System.Windows.Forms as WinForms
import System.Drawing as Drawing

# Load WebView2 and DirectComposition assemblies
wv2_candidates = [
    PROJECT_ROOT / "dist" / "cut5_truthful_main" / "异环拍卖助手" / "_internal" / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll",
    Path(sys.prefix) / "Lib" / "site-packages" / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll",
    APP_DIR / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll",
    Path(r"C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll"),
]
wv2_dll = next((p for p in wv2_candidates if p.is_file()), None)
if wv2_dll:
    clr.AddReference(str(wv2_dll))
    winforms_wv2 = wv2_dll.parent / "Microsoft.Web.WebView2.WinForms.dll"
    if winforms_wv2.is_file():
        clr.AddReference(str(winforms_wv2))

dcomp_dll = APP_DIR / "DirectCompositionHost.dll"
if not dcomp_dll.is_file():
    dcomp_dll = PROJECT_ROOT / "dist" / "cut5_truthful_main" / "异环拍卖助手" / "_internal" / "DirectCompositionHost.dll"

from System.Reflection import Assembly
Assembly.LoadFrom(str(dcomp_dll.resolve()))
from Microsoft.Web.WebView2.Core import CoreWebView2Environment

from main_window import (
    MainWindowBridge,
    OverlayVisibilityController,
    ShutdownCoordinator,
    create_main_window_type,
    load_mascot_presentation_contract,
)


class MainWindowWindowedHostContractTests(unittest.TestCase):
    """Runtime contract tests proving Main Window uses genuine standard windowed WebView2 with honest fallback."""

    def test_main_source_forbids_evasive_string_manipulation_and_verifies_complete_fallback(self):
        """Verify main_window.py contains NO evasive string tricks and fallback is fully composed."""
        mw_path = APP_DIR / "main_window.py"
        self.assertTrue(mw_path.is_file(), f"Missing {mw_path}")
        with open(str(mw_path), "r", encoding="utf-8") as f:
            content = f.read()

        # Forbid string-concatenation evasion tricks
        self.assertNotIn('join(["CreateCoreWebView2"', content)
        self.assertNotIn('join(["CreateCore', content)

        # Verify fallback is honest, complete and fully wired
        self.assertIn("DCompNative.CreateDevice()", content)
        self.assertIn("RootVisualTarget = self._dcomp_root_visual", content)
        self.assertIn("self._dcomp_device.Commit()", content)
        self.assertIn("SendMouseInput", content)

    def test_main_window_ast_structure_uses_winforms_webview2_control(self):
        """Verify AST structure of initialize_presentation instantiates Microsoft.Web.WebView2.WinForms.WebView2."""
        mw_path = APP_DIR / "main_window.py"
        with open(str(mw_path), "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        # Find create_main_window_type function
        create_fn = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "create_main_window_type"
        )
        fn_source = ast.unparse(create_fn)

        self.assertIn("environment.CreateCoreWebView2ControllerAsync(self.Handle)", fn_source)
        self.assertIn("self._presentation_controller = controller_task.Result", fn_source)
        self.assertIn("self._presentation_webview = self._presentation_controller.CoreWebView2", fn_source)
        self.assertIn("self._presentation_controller.Bounds = Drawing.Rectangle", fn_source)

    def test_main_window_instance_type_and_child_hierarchy_contract(self):
        """Verify MainWindow instance adheres to standard windowed WinForms Form contract."""
        MainWindow = create_main_window_type(WinForms, Drawing)
        mw = MainWindow()
        try:
            self.assertIsInstance(mw, WinForms.Form)
            self.assertEqual(mw.Text, "异环拍卖助手")
            self.assertTrue(mw.ShowInTaskbar)
            self.assertEqual(mw.FormBorderStyle, WinForms.FormBorderStyle.Sizable)
            self.assertFalse(hasattr(mw, "DCompRootVisual"))
            self.assertFalse(hasattr(mw, "RootVisualTarget"))
            self.assertFalse(hasattr(mw, "DCompTarget"))
            self.assertFalse(hasattr(mw, "DCompDevice"))
        finally:
            mw.Dispose()

    def test_main_window_bridge_and_ui_dispatch_ready(self):
        """Verify MainWindowBridge contract and commands dispatch cleanly without composition dependency."""
        class MockOverlay:
            Visible = True
            def Show(self):
                self.Visible = True
            def Hide(self):
                self.Visible = False
            def toggle(self):
                self.Visible = not self.Visible
                return self.Visible

        overlay = MockOverlay()
        controller = OverlayVisibilityController(overlay)
        bridge = MainWindowBridge(controller)

        # Dispatch status query
        status_resp = bridge.dispatch({"action": "request_app_status"})
        self.assertEqual(status_resp.get("type"), "app_status")
        self.assertIn("presentationData", status_resp)
        self.assertIn("presentationRuntime", status_resp)
        self.assertTrue(status_resp.get("overlayVisible"))

        # Dispatch pin toggling
        pin_resp = bridge.dispatch({"action": "set_main_pin", "pinned": True})
        self.assertTrue(pin_resp.get("mainPinned"))
        self.assertTrue(bridge.user_pinned)

        unpin_resp = bridge.dispatch({"action": "set_main_pin", "pinned": False})
        self.assertFalse(unpin_resp.get("mainPinned"))
        self.assertFalse(bridge.user_pinned)


if __name__ == "__main__":
    unittest.main()
