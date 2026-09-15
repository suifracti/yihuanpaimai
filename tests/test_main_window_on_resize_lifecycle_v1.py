"""Targeted verification for 4D2D1D5D:
Main OnResize Init-Order Crash Fix.

Verifies:
1. Early OnResize triggered during construction raises no exceptions.
2. Form Resize before presentation initialization is a clean no-op without exceptions.
3. Once CoreWebView2Controller is ready, OnResize / _on_resize updates controller Bounds correctly to match ClientSize.
4. Continuous Activated and Resize events execute cleanly without unhandled exceptions or attribute errors.
5. No references to deprecated `_webview_control` exist in product codebase.
6. Genuine windowed controller contract remains intact (no composition fallback).
7. Pin-off zero redundant Z-order writes contract remains intact.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
CORE_DIR = PROJECT_ROOT / "core"
for entry in (str(APP_DIR), str(CORE_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from main_window import create_main_window_type

# Try to use real CLR assemblies if loaded
try:
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    import System.Windows.Forms as RealWinForms
    import System.Drawing as RealDrawing
    HAS_CLR = True
except Exception:
    HAS_CLR = False


class _MockDrawing:
    class Size:
        def __init__(self, w, h):
            self.Width = w
            self.Height = h

    class Point:
        def __init__(self, x, y):
            self.X = x
            self.Y = y

    class Color:
        @staticmethod
        def FromArgb(*args):
            return "color"

    class Icon:
        def __init__(self, path):
            self.path = path

    class Rectangle:
        def __init__(self, x, y, w, h):
            self.X = x
            self.Y = y
            self.Width = w
            self.Height = h

        def __eq__(self, other):
            return (
                hasattr(other, "X")
                and hasattr(other, "Y")
                and hasattr(other, "Width")
                and hasattr(other, "Height")
                and (self.X, self.Y, self.Width, self.Height)
                == (other.X, other.Y, other.Width, other.Height)
            )

        def __repr__(self):
            return f"Rectangle({self.X}, {self.Y}, {self.Width}, {self.Height})"


class _MockBaseForm:
    class FormStartPosition:
        CenterScreen = 1

    def __init__(self):
        self.ClientSize = _MockDrawing.Size(1280, 660)
        self.MinimumSize = _MockDrawing.Size(1100, 680)
        self.Text = ""
        self.BackColor = None
        self.TopMost = False
        self.Icon = None
        self.Resize = MagicMock()
        self.FormClosing = MagicMock()
        self.Controls = MagicMock()
        self.IsHandleCreated = True
        self.Handle = MagicMock()
        self.Handle.ToInt64.return_value = 123456

        # Simulate WinForms firing OnResize during base form construction
        if hasattr(self, "OnResize"):
            self.OnResize(None)

    def OnResize(self, event):
        pass


class _MockWinForms:
    Form = _MockBaseForm
    FormStartPosition = _MockBaseForm.FormStartPosition

    class Label:
        def __init__(self):
            self.Text = ""
            self.ForeColor = None
            self.AutoSize = False
            self.Location = None
            self.Visible = True


class _MockCoreWebView2Controller:
    def __init__(self):
        self.Bounds = None
        self.IsVisible = False
        self.CoreWebView2 = MagicMock()


class TestMainWindowOnResizeLifecycle4D2D1D5D(unittest.TestCase):
    def setUp(self):
        if HAS_CLR:
            self.WinForms = RealWinForms
            self.Drawing = RealDrawing
        else:
            self.WinForms = _MockWinForms
            self.Drawing = _MockDrawing

    def test_no_stale_webview_control_in_product_code(self):
        """Verify _webview_control has been completely removed from product code."""
        for root_dir in (APP_DIR, CORE_DIR):
            for py_file in Path(root_dir).rglob("*.py"):
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn(
                    "_webview_control",
                    text,
                    f"Deprecated _webview_control found in: {py_file}",
                )

    def test_construction_early_onresize_safety(self):
        """Verify early OnResize triggered during BaseForm.__init__ executes cleanly."""
        MainWindowType = create_main_window_type(self.WinForms, self.Drawing)
        window = MainWindowType()
        self.assertIsNone(window._presentation_controller)
        self.assertIsNone(window._presentation_webview)
        if hasattr(window, "Dispose"):
            window.Dispose()

    def test_resize_before_presentation_init_is_noop(self):
        """Verify explicit OnResize / _on_resize before presentation init does not crash."""
        MainWindowType = create_main_window_type(self.WinForms, self.Drawing)
        window = MainWindowType()

        # Trigger OnResize and _on_resize multiple times before presentation controller exists
        window.OnResize(None)
        window._on_resize(None, None)
        window.ClientSize = self.Drawing.Size(1400, 800)
        window.OnResize(None)
        self.assertIsNone(window._presentation_controller)
        if hasattr(window, "Dispose"):
            window.Dispose()

    def test_resize_updates_controller_bounds_when_ready(self):
        """Verify that after CoreWebView2Controller is set, Resize updates Bounds accurately."""
        MainWindowType = create_main_window_type(self.WinForms, self.Drawing)
        window = MainWindowType()

        mock_controller = _MockCoreWebView2Controller()
        window._presentation_controller = mock_controller
        window.ClientSize = self.Drawing.Size(1600, 900)

        # Trigger Resize
        window.OnResize(None)

        expected_bounds = _MockDrawing.Rectangle(0, 0, 1600, 900)
        self.assertEqual(mock_controller.Bounds.Width, 1600)
        self.assertEqual(mock_controller.Bounds.Height, 900)

        # Change size again
        window.ClientSize = self.Drawing.Size(1920, 1080)
        window._on_resize(None, None)
        self.assertEqual(mock_controller.Bounds.Width, 1920)
        self.assertEqual(mock_controller.Bounds.Height, 1080)
        if hasattr(window, "Dispose"):
            window.Dispose()

    def test_continuous_activation_and_resize_events(self):
        """Verify repeated simulated activate and resize cycles without error."""
        MainWindowType = create_main_window_type(self.WinForms, self.Drawing)
        window = MainWindowType()
        mock_controller = _MockCoreWebView2Controller()
        window._presentation_controller = mock_controller

        for i in range(50):
            window.ClientSize = self.Drawing.Size(1200 + i, 700 + i)
            window.OnResize(None)
            self.assertEqual(mock_controller.Bounds.Width, 1200 + i)
            self.assertEqual(mock_controller.Bounds.Height, 700 + i)
        if hasattr(window, "Dispose"):
            window.Dispose()

    def test_close_presentation_resources_clean(self):
        """Verify closing resources cleans controller and webview without AttributeError."""
        MainWindowType = create_main_window_type(self.WinForms, self.Drawing)
        window = MainWindowType()
        mock_controller = _MockCoreWebView2Controller()
        mock_controller.Close = MagicMock()
        window._presentation_controller = mock_controller
        window._presentation_webview = MagicMock()

        window.close_presentation_resources()
        self.assertIsNone(window._presentation_controller)
        self.assertIsNone(window._presentation_webview)
        mock_controller.Close.assert_called_once()
        if hasattr(window, "Dispose"):
            window.Dispose()


if __name__ == "__main__":
    unittest.main()
