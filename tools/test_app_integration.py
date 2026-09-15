import clr, sys, os, time, json, threading, asyncio, websockets
import ctypes
import ctypes.wintypes as wintypes

PROJECT_ROOT = r"D:\yihuanpaimai"
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
HTML_PATH = os.path.join(CORE_DIR, "tactical_hud.html")

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
clr.AddReference(r'C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll')
os.environ['Path'] += r';C:\Program Files\Python310\Lib\site-packages\webview\lib\runtimes\win-x64\native'

from System.Threading import Thread, ThreadStart, ApartmentState
from System import IntPtr, Uri
from System.Drawing import Rectangle, Point, Size, Color, ColorTranslator
import System.Windows.Forms as WinForms
from Microsoft.Web.WebView2.Core import CoreWebView2Environment

WS_PORT = 8766
TELEMETRY_LOG = []
WS_CONNECTED = threading.Event()
TELEMETRY_RECEIVED = threading.Event()

async def ws_handler(websocket):
    print("[INTEG:WS] WebSocket client connected!")
    WS_CONNECTED.set()
    try:
        async for msg in websocket:
            try:
                data = json.loads(msg)
                print(f"[INTEG:WS] Received msg type: {data.get('type')}")
                if data.get("type") == "report_hud_status":
                    status = data.get("status", {})
                    TELEMETRY_LOG.append(status)
                    TELEMETRY_RECEIVED.set()
            except Exception as e:
                print(f"[INTEG:WS] JSON error: {e}")
    except websockets.exceptions.ConnectionClosed:
        pass

def run_ws():
    async def _runner():
        async with websockets.serve(ws_handler, "127.0.0.1", WS_PORT):
            await asyncio.Future()
    asyncio.run(_runner())

def test_integration():
    t_ws = threading.Thread(target=run_ws, daemon=True)
    t_ws.start()
    time.sleep(0.5)

    form_ref = None

    def _gui():
        nonlocal form_ref
        form = WinForms.Form()
        form_ref = form
        form.Text = "⚡ 异环拍卖战术助手 HUD"
        form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
        form.StartPosition = WinForms.FormStartPosition.Manual
        form.Location = Point(200, 200)
        form.Size = Size(390, 450)
        form.TopMost = True
        form.BackColor = ColorTranslator.FromHtml("#12161f")
        form.Show()

        data_folder = r"D:\yihuanpaimai\build\wv2_comp_integ"
        os.makedirs(data_folder, exist_ok=True)

        env_task = CoreWebView2Environment.CreateAsync(None, data_folder, None)
        while not env_task.IsCompleted:
            WinForms.Application.DoEvents()
        env = env_task.Result

        ctrl_task = env.CreateCoreWebView2CompositionControllerAsync(form.Handle)
        while not ctrl_task.IsCompleted:
            WinForms.Application.DoEvents()
        comp_ctrl = ctrl_task.Result

        wv = comp_ctrl.CoreWebView2
        wv.Settings.IsScriptEnabled = True
        wv.Settings.IsWebMessageEnabled = True
        comp_ctrl.Bounds = Rectangle(0, 0, form.ClientSize.Width, form.ClientSize.Height)
        comp_ctrl.IsVisible = True

        # Injected bridge script
        bridge_script = """
        (function() {
            window.pywebview = {
                api: {
                    exit_app: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'exit_app'})); },
                    snap_to_game: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'snap_to_game'})); },
                    open_config: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'open_config'})); },
                    open_lab: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'open_lab'})); },
                    report_hud_status: function(status) { window.chrome.webview.postMessage(JSON.stringify({action: 'report_hud_status', status: status})); },
                    start_live_vision: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'start_live_vision'})); },
                    begin_drag: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'begin_drag'})); },
                    get_pos: function() { window.chrome.webview.postMessage(JSON.stringify({action: 'get_pos'})); },
                    set_pos: function(x, y) { window.chrome.webview.postMessage(JSON.stringify({action: 'set_pos', x: x, y: y})); },
                    move_rel: function(dx, dy) { window.chrome.webview.postMessage(JSON.stringify({action: 'move_rel', dx: dx, dy: dy})); }
                }
            };
            window.dispatchEvent(new CustomEvent('pywebviewready'));
        })();
        """
        wv.AddScriptToExecuteOnDocumentCreatedAsync(bridge_script)

        def on_web_message(s, e):
            try:
                data = json.loads(e.TryGetWebMessageAsString())
                print(f"[INTEG:BRIDGE] WebMessage action: {data.get('action')}")
            except Exception:
                pass
        wv.WebMessageReceived += on_web_message

        wv.Navigate(Uri(os.path.abspath(HTML_PATH)).AbsoluteUri)

        t_end = time.time() + 6.0
        while time.time() < t_end:
            WinForms.Application.DoEvents()
            time.sleep(0.05)
            if TELEMETRY_RECEIVED.is_set():
                print("[INTEG:GUI] Telemetry received!")
                time.sleep(1.0)
                break

        form.Close()

    t = Thread(ThreadStart(_gui))
    t.SetApartmentState(ApartmentState.STA)
    t.Start()
    t.Join()

    print(f"WS Connected: {WS_CONNECTED.is_set()}")
    print(f"Telemetry: {TELEMETRY_LOG}")

if __name__ == "__main__":
    test_integration()
