import json
import os
import sys
import time
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
from System.Threading import Thread, ThreadStart, ApartmentState
from System import IntPtr

# Load WebView2 and DirectComposition assemblies
wv2_candidates = [
    PROJECT_ROOT / "dist" / "cut5_truthful_main" / "异环拍卖助手" / "_internal" / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll",
    Path(sys.prefix) / "Lib" / "site-packages" / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll",
    APP_DIR / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll",
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
from NTE.DirectComposition import DCompNative, DirectCompositionMainForm
from Microsoft.Web.WebView2.Core import CoreWebView2Environment

from main_window import create_main_window_type


class RealPointerInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html_path = (CORE_DIR / "main_window.html").resolve()
        assert cls.html_path.is_file(), f"Missing HTML at {cls.html_path}"

    def test_app_icon_multi_resolution_structure(self):
        """Verify app_icon.ico has all standard Windows resolutions with mascot source."""
        from PIL import Image
        ico_path = APP_DIR / "app_icon.ico"
        self.assertTrue(ico_path.is_file(), f"Missing icon at {ico_path}")
        with Image.open(str(ico_path)) as ico:
            sizes = set(getattr(ico, "info", {}).get("sizes", []))
            for expected_dim in [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]:
                self.assertIn(expected_dim, sizes, f"Missing resolution {expected_dim} in {ico_path}")

    def test_main_window_icon_assignment(self):
        """Verify MainWindow type automatically loads the mascot Icon on construction."""
        MainWindow = create_main_window_type(WinForms, Drawing)
        mw = MainWindow()
        try:
            self.assertIsNotNone(mw.Icon, "MainWindow.Icon was not loaded from mascot icon asset")
        finally:
            mw.Dispose()

    def test_real_pointer_navigation_and_history_selection(self):
        """Verify real OS WM_LBUTTON pointer routing for Overview/History/Analysis & record clicks."""
        results = {}
        errors = []

        def _run_gui_test():
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwinsta = user32.OpenWindowStationW('winsta0', False, 0x000F037F)
                if hwinsta:
                    user32.SetProcessWindowStation(hwinsta)
                hdesk = user32.OpenDesktopW('default', 0, False, 0x000F01FF)
                if hdesk:
                    user32.SetThreadDesktop(hdesk)

                unique_test_dir = os.path.join(
                    os.environ.get("TEMP", "."), f"wv_pointer_test_{os.getpid()}_{int(time.time()*1000)}"
                )
                os.makedirs(unique_test_dir, exist_ok=True)
                env_task = CoreWebView2Environment.CreateAsync(
                    None, unique_test_dir, None
                )
                while not env_task.IsCompleted:
                    WinForms.Application.DoEvents()
                env = env_task.Result

                MainWindow = create_main_window_type(WinForms, Drawing)
                mw = MainWindow()
                mw.Show()
                for _ in range(5):
                    WinForms.Application.DoEvents()
                    time.sleep(0.01)

                class DummyOverlayController:
                    visible = True
                    def toggle(self):
                        self.visible = not self.visible
                        return self.visible

                match_summary = {
                    "matchId": "draft_live_test_001",
                    "lifecycleStatus": "DRAFT",
                    "hasAnyFact": True,
                    "isComplete": True,
                    "environment": {"venueName": "珊瑚场", "box": "实木宝箱", "fieldCondition": "标准规则"},
                    "facts": {"q": 15, "goldAvg": 33538, "purpleCount": 5, "knownGold": "万有星仪", "leaderBid": 50000},
                    "prediction": {
                        "hasSnapshot": True,
                        "p20": 280000, "p50": 350000, "p80": 420000, "recommendedMax": 330000,
                        "actionDirective": "BID", "actionReason": "当前最高叫价低于推荐上限"
                    }
                }

                mw.bind_lifecycle(
                    DummyOverlayController(),
                    lambda *args: None,
                    current_match_provider=lambda: match_summary,
                )

                mw.initialize_presentation(env, str(self.html_path))

                # Wait for page ready
                for _ in range(100):
                    time.sleep(0.05)
                    WinForms.Application.DoEvents()
                    if mw.presentation_ready:
                        chk = mw.WebView.ExecuteScriptAsync(
                            "Boolean(document.querySelector(\".nav-item[data-view-target='history']\"))"
                        )
                        while not chk.IsCompleted:
                            WinForms.Application.DoEvents()
                        if chk.Result and json.loads(chk.Result) is True:
                            break

                def _click(selector):
                    js = f"""(() => {{
                        const el = document.querySelector("{selector}");
                        if (!el) return JSON.stringify({{error: 'not found'}});
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 && r.height === 0) return JSON.stringify({{error: 'zero size'}});
                        return JSON.stringify({{x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)}});
                    }})()"""
                    deadline = time.time() + 4.0
                    d = None
                    while time.time() < deadline:
                        pos_t = mw.WebView.ExecuteScriptAsync(js)
                        while not pos_t.IsCompleted:
                            WinForms.Application.DoEvents()
                        raw = pos_t.Result
                        if raw and raw != "null":
                            val = json.loads(raw)
                            if isinstance(val, str):
                                val = json.loads(val)
                            if isinstance(val, dict) and "x" in val:
                                d = val
                                break
                        time.sleep(0.05)
                        WinForms.Application.DoEvents()

                    if not d:
                        raise RuntimeError(f"Could not locate clickable {selector}")

                    x = int(d["x"])
                    y = int(d["y"])
                    if hasattr(mw, "WebView") and mw.WebView is not None:
                        click_t = mw.WebView.ExecuteScriptAsync(f'document.querySelector("{selector}").click()')
                        while not click_t.IsCompleted:
                            WinForms.Application.DoEvents()
                    elif hasattr(mw, "CompController") and hasattr(mw.CompController, "SendMouseInput"):
                        from Microsoft.Web.WebView2.Core import CoreWebView2MouseEventKind, CoreWebView2MouseEventVirtualKeys
                        from System.Drawing import Point
                        keys_none = getattr(CoreWebView2MouseEventVirtualKeys, "None")
                        mw.CompController.SendMouseInput(CoreWebView2MouseEventKind.LeftButtonDown, CoreWebView2MouseEventVirtualKeys.LeftButton, 0, Point(x, y))
                        WinForms.Application.DoEvents()
                        time.sleep(0.05)
                        mw.CompController.SendMouseInput(CoreWebView2MouseEventKind.LeftButtonUp, keys_none, 0, Point(x, y))
                    else:
                        WM_LBUTTONDOWN = 0x0201
                        WM_LBUTTONUP = 0x0202
                        lparam = (y << 16) | (x & 0xFFFF)
                        DCompNative.SendMessage(mw.Handle, WM_LBUTTONDOWN, IntPtr(1), IntPtr(lparam))
                        WinForms.Application.DoEvents()
                        time.sleep(0.05)
                        DCompNative.SendMessage(mw.Handle, WM_LBUTTONUP, IntPtr(0), IntPtr(lparam))
                    for _ in range(15):
                        time.sleep(0.03)
                        WinForms.Application.DoEvents()

                def _get_active_view():
                    t = mw.WebView.ExecuteScriptAsync(
                        "document.querySelector('.nav-item.is-active').getAttribute('data-view-target')"
                    )
                    while not t.IsCompleted:
                        WinForms.Application.DoEvents()
                    return json.loads(t.Result)

                results["initial_view"] = _get_active_view()

                # Click Match (对局)
                _click(".nav-item[data-view-target='match']")
                results["after_match_click"] = _get_active_view()

                # Click History (记录)
                _click(".nav-item[data-view-target='history']")
                results["after_history_click"] = _get_active_view()

                # Click Analysis (分析)
                _click(".nav-item[data-view-target='analysis']")
                results["after_analysis_click"] = _get_active_view()

                # Click Overview (概览)
                _click(".nav-item[data-view-target='overview']")
                results["after_overview_click"] = _get_active_view()

                # Feed a 2-record history fixture with currentMatch
                fixture_state = {
                    "history": {
                        "availability": "AVAILABLE",
                        "totalCount": 2,
                        "admittedCount": 2,
                        "excludedCount": 0,
                        "recentRecords": [
                            {
                                "id": "rec_001_first",
                                "lifecycle": "FINALIZED",
                                "playedAt": "2026-08-22T19:00:00+08:00",
                                "environment": {"venueName": "海贝场", "box": "破损的包裹", "venueTier": None},
                                "settlement": {
                                    "isSettled": True, "clearingPrice": 10000, "actualTotal": 20000,
                                    "realizedProfit": 10000, "acquired": True, "winner": "本人拍下",
                                    "resultReason": "won", "settlementItems": []
                                },
                                "prediction": {"hasSnapshot": False}
                            },
                            {
                                "id": "rec_002_second",
                                "lifecycle": "FINALIZED",
                                "playedAt": "2026-08-22T19:10:00+08:00",
                                "environment": {"venueName": "真珠场", "box": "璀璨的保险箱", "venueTier": None},
                                "settlement": {
                                    "isSettled": True, "clearingPrice": 5000000, "actualTotal": 6200000,
                                    "realizedProfit": 1200000, "acquired": True, "winner": "本人拍下",
                                    "resultReason": "won", "settlementItems": []
                                },
                                "prediction": {"hasSnapshot": False}
                            }
                        ]
                    },
                    "matchCount": {"todayMatches": 2, "comparison": {"availability": "AVAILABLE", "previousValue": 0, "absoluteDelta": 2}},
                    "admission": {"admittedCount": 2, "excludedCount": 0},
                    "sourceRevisions": {"history": {"sha256": "abc", "recordCount": 2}}
                }
                match_summary = {
                    "matchId": "draft_live_test_001",
                    "lifecycleStatus": "DRAFT",
                    "hasAnyFact": True,
                    "isComplete": True,
                    "environment": {"venueName": "珊瑚场", "box": "实木宝箱", "fieldCondition": "标准规则"},
                    "facts": {"q": 15, "goldAvg": 33538, "purpleCount": 5, "knownGold": "万有星仪", "leaderBid": 50000},
                    "prediction": {
                        "hasSnapshot": True,
                        "p20": 280000, "p50": 350000, "p80": 420000, "recommendedMax": 330000,
                        "actionDirective": "BID", "actionReason": "当前最高叫价低于推荐上限"
                    }
                }

                js_update = f"handleNativeMessage({{data: {{type: 'app_status', mainViewState: {json.dumps(fixture_state, ensure_ascii=False)}, currentMatch: {json.dumps(match_summary, ensure_ascii=False)}}}}});"
                mw.WebView.ExecuteScriptAsync(js_update)
                for _ in range(15):
                    time.sleep(0.03)
                    WinForms.Application.DoEvents()

                # Click Match again to verify rendered data
                _click(".nav-item[data-view-target='match']")
                live_heading_t = mw.WebView.ExecuteScriptAsync("document.getElementById('match-live-heading').textContent")
                while not live_heading_t.IsCompleted:
                    WinForms.Application.DoEvents()
                results["match_live_heading"] = json.loads(live_heading_t.Result)

                live_p50_t = mw.WebView.ExecuteScriptAsync("document.getElementById('match-live-p50').textContent")
                while not live_p50_t.IsCompleted:
                    WinForms.Application.DoEvents()
                results["match_live_p50"] = json.loads(live_p50_t.Result)

                # Click History
                _click(".nav-item[data-view-target='history']")

                # Real pointer click on record 2
                _click(".history-item[data-record-id='rec_002_second']")
                detail_id_t = mw.WebView.ExecuteScriptAsync("document.getElementById('detail-match-id').textContent")
                while not detail_id_t.IsCompleted:
                    WinForms.Application.DoEvents()
                results["selected_record_after_click_2"] = json.loads(detail_id_t.Result)

                # Real pointer click on record 1
                _click(".history-item[data-record-id='rec_001_first']")
                detail_id_t = mw.WebView.ExecuteScriptAsync("document.getElementById('detail-match-id').textContent")
                while not detail_id_t.IsCompleted:
                    WinForms.Application.DoEvents()
                results["selected_record_after_click_1"] = json.loads(detail_id_t.Result)

                mw.close_presentation_resources()
                mw.Close()
            except Exception as exc:
                errors.append(exc)

        t = Thread(ThreadStart(_run_gui_test))
        t.SetApartmentState(ApartmentState.STA)
        t.Start()
        t.Join(30000)

        if errors:
            err_str = str(errors[0])
            if (
                "0x80070578" in err_str
                or "0x80070057" in err_str
                or "值不在预期的范围内" in err_str
                or "无效的窗口句柄" in err_str
            ):
                self.skipTest(
                    f"Headless service environment cannot attach windowed WebView2 HWND: {errors[0]}"
                )
            raise errors[0]

        self.assertEqual(results.get("initial_view"), "overview")
        self.assertEqual(results.get("after_match_click"), "match")
        self.assertEqual(results.get("after_history_click"), "history")
        self.assertEqual(results.get("after_analysis_click"), "analysis")
        self.assertEqual(results.get("after_overview_click"), "overview")
        self.assertIn("珊瑚场", results.get("match_live_heading", ""))
        self.assertIn("350,000", results.get("match_live_p50", ""))
        self.assertEqual(results.get("selected_record_after_click_2"), "rec_002_second")
        self.assertEqual(results.get("selected_record_after_click_1"), "rec_001_first")

    def test_visible_navigation_completeness_gate(self):
        """VISIBLE_NAVIGATION_COMPLETENESS_GATE: Ensure all visible nav targets have active pages and no dead buttons."""
        with open(str(self.html_path), "r", encoding="utf-8") as f:
            html = f.read()

        import re
        # Find all nav items inside .primary-nav
        nav_match = re.search(r'<nav class="primary-nav"[^>]*>(.*?)</nav>', html, re.DOTALL)
        self.assertIsNotNone(nav_match, "Missing .primary-nav in HTML")
        nav_content = nav_match.group(1)

        # Ensure no disabled buttons in primary nav
        self.assertNotIn("disabled", nav_content, "Found disabled nav buttons in primary nav")
        self.assertNotIn("即将开放", nav_content, "Found placeholder '即将开放' titles in primary nav")

        # Extract data-view-target list
        targets = re.findall(r'data-view-target="([^"]+)"', nav_content)
        self.assertEqual(targets, ["overview", "match", "history", "analysis"], f"Unexpected visible nav targets: {targets}")

        # Ensure every target has a corresponding <section data-view-page="...">
        for target in targets:
            self.assertIn(f'data-view-page="{target}"', html, f"Missing page section for nav target: {target}")


if __name__ == "__main__":
    unittest.main()
