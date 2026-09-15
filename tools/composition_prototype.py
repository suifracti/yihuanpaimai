import clr, sys, os, time, json, threading, asyncio, websockets
import ctypes
import ctypes.wintypes as wintypes

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
clr.AddReference(r'C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll')
os.environ['Path'] += r';C:\Program Files\Python310\Lib\site-packages\webview\lib\runtimes\win-x64\native'

from System.Threading import Thread, ThreadStart, ApartmentState
from System import IntPtr, Uri
from System.Drawing import Rectangle, Color
import System.Windows.Forms as WinForms
from Microsoft.Web.WebView2.Core import CoreWebView2Environment

WS_PORT = 8766
TELEMETRY_LOG = []
WS_CONNECTED = threading.Event()
TELEMETRY_RECEIVED = threading.Event()

async def ws_handler(websocket):
    print("[PROTOTYPE:WS] WebSocket client connected from HUD!")
    WS_CONNECTED.set()
    try:
        async for msg in websocket:
            try:
                data = json.loads(msg)
                print(f"[PROTOTYPE:WS] Received message: type={data.get('type')}")
                if data.get("type") == "report_hud_status":
                    status = data.get("status", {})
                    print(f"[PROTOTYPE:WS] HUD Status Report:")
                    print(f"  pywebviewReady: {status.get('pywebviewReady')}")
                    print(f"  auctionEngineLoaded: {status.get('auctionEngineLoaded')}")
                    print(f"  sharedCoreSelfTests: {status.get('sharedCoreSelfTests')}")
                    print(f"  regression1553Passed: {status.get('regression1553Passed')}")
                    TELEMETRY_LOG.append(status)
                    TELEMETRY_RECEIVED.set()
            except Exception as e:
                print(f"[PROTOTYPE:WS] JSON parse error: {e}")
    except websockets.exceptions.ConnectionClosed:
        pass

def run_ws_server():
    async def _runner():
        print(f"[PROTOTYPE:WS] Starting WS server on ws://127.0.0.1:{WS_PORT}...")
        async with websockets.serve(ws_handler, "127.0.0.1", WS_PORT):
            print(f"[PROTOTYPE:WS] WS server ready on ws://127.0.0.1:{WS_PORT}")
            await asyncio.Future()
    try:
        asyncio.run(_runner())
    except Exception as e:
        print(f"[PROTOTYPE:WS] Server error: {e}")

def run_composition_prototype():
    # 1. Start WS server in background daemon thread
    t_ws = threading.Thread(target=run_ws_server, daemon=True)
    t_ws.start()
    time.sleep(0.5)

    comp_controller = None
    form_ref = None

    def _gui_thread():
        nonlocal comp_controller, form_ref
        form = WinForms.Form()
        form_ref = form
        form.Text = "⚡ 异环拍卖助手 DirectComposition Prototype"
        form.Width = 390
        form.Height = 450
        form.FormBorderStyle = WinForms.FormBorderStyle.FixedSingle
        form.StartPosition = WinForms.FormStartPosition.CenterScreen
        form.Show()

        data_folder = r"D:\yihuanpaimai\build\wv2_comp_prototype"
        os.makedirs(data_folder, exist_ok=True)

        print("[PROTOTYPE:GUI] Creating CoreWebView2Environment...")
        env_task = CoreWebView2Environment.CreateAsync(None, data_folder, None)
        while not env_task.IsCompleted:
            WinForms.Application.DoEvents()
        env = env_task.Result
        print("[PROTOTYPE:GUI] Environment created successfully.")

        print(f"[PROTOTYPE:GUI] Calling CreateCoreWebView2CompositionControllerAsync(HWND={form.Handle.ToInt64()})...")
        ctrl_task = env.CreateCoreWebView2CompositionControllerAsync(form.Handle)
        while not ctrl_task.IsCompleted:
            WinForms.Application.DoEvents()

        if ctrl_task.IsFaulted:
            print(f"[PROTOTYPE:GUI] Composition Controller FAULTED: {ctrl_task.Exception}")
            return

        comp_ctrl = ctrl_task.Result
        comp_controller = comp_ctrl
        print("[PROTOTYPE:GUI] Composition Controller CREATED (S_OK)!")

        # Configure WebView2
        wv = comp_ctrl.CoreWebView2
        wv.Settings.IsScriptEnabled = True
        wv.Settings.IsWebMessageEnabled = True
        wv.Settings.AreDevToolsEnabled = True

        comp_ctrl.Bounds = Rectangle(0, 0, form.ClientSize.Width, form.ClientSize.Height)
        comp_ctrl.IsVisible = True

        def on_resize(s, e):
            if comp_ctrl:
                comp_ctrl.Bounds = Rectangle(0, 0, form.ClientSize.Width, form.ClientSize.Height)
        form.Resize += on_resize

        def on_nav_completed(s, e):
            print(f"[PROTOTYPE:GUI] NavigationCompleted: IsSuccess = {e.IsSuccess}")
        wv.NavigationCompleted += on_nav_completed

        # Load tactical_hud.html
        html_path = os.path.abspath(r"D:\yihuanpaimai\core\tactical_hud.html")
        file_uri = Uri(html_path).AbsoluteUri
        print(f"[PROTOTYPE:GUI] Navigating to: {file_uri}")
        wv.Navigate(file_uri)

        # Run Form message loop for 6 seconds to allow JS and WebSocket execution
        t_end = time.time() + 6.0
        while time.time() < t_end:
            WinForms.Application.DoEvents()
            time.sleep(0.05)
            if TELEMETRY_RECEIVED.is_set():
                print("[PROTOTYPE:GUI] Telemetry received, waiting 1 more second to settle...")
                time.sleep(1.0)
                break

        form.Close()
        print("[PROTOTYPE:GUI] Prototype GUI closed cleanly.")

    t_gui = Thread(ThreadStart(_gui_thread))
    t_gui.SetApartmentState(ApartmentState.STA)
    t_gui.Start()
    t_gui.Join()

    print("\n=== PROTOTYPE AUDIT RESULTS ===")
    print(f"1. Composition Controller Created: {comp_controller is not None}")
    print(f"2. WebSocket Connected: {WS_CONNECTED.is_set()}")
    print(f"3. Telemetry Received from tactical_hud.html: {TELEMETRY_RECEIVED.is_set()}")
    if TELEMETRY_LOG:
        print(f"4. Telemetry Data: {json.dumps(TELEMETRY_LOG[-1], indent=2)}")
        passed_regression = TELEMETRY_LOG[-1].get("regression1553Passed")
        passed_tests = TELEMETRY_LOG[-1].get("sharedCoreSelfTests", {}).get("passed")
        print(f"5. Shared Core Self-Tests Passed: {passed_tests}")
        print(f"6. 15:53 Regression Passed: {passed_regression}")

if __name__ == "__main__":
    run_composition_prototype()
