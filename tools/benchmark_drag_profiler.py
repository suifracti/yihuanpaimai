import os, sys, time, ctypes, json, subprocess, threading
from pathlib import Path

PROJECT_ROOT = r"D:\yihuanpaimai"
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
HTML_PATH = os.path.join(CORE_DIR, "tactical_hud.html")
DLL_PATH = os.path.join(PROJECT_ROOT, "app", "DirectCompositionHost.dll")
WV2_DLL = r"C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll"
os.environ['Path'] += r';C:\Program Files\Python310\Lib\site-packages\webview\lib\runtimes\win-x64\native'

# Create a dedicated instrumented C# test harness
CS_CODE = r"""
using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Diagnostics;
using Microsoft.Web.WebView2.Core;
using NTE.DirectComposition;

namespace NTE.Profiling
{
    public class DragProfilingForm : DirectCompositionHudForm
    {
        public long CountWmNcHitTest = 0;
        public long CountWmMouseMove = 0;
        public long CountWmNcLButtonDown = 0;
        public long CountWmWindowPosChanged = 0;
        public long CountWmMove = 0;
        public long CountWmPaint = 0;
        public long CountSendMouseInput = 0;
        public long CountDCompCommit = 0;
        public long CountEnterSizeMove = 0;
        public long CountExitSizeMove = 0;
        public long CountTotalMessages = 0;

        public DragProfilingForm(int x, int y, int w, int h, bool onTop) : base(x, y, w, h, onTop)
        {
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            CountDCompCommit++;
        }

        protected override void WndProc(ref Message m)
        {
            CountTotalMessages++;
            const int WM_NCHITTEST = 0x0084;
            const int WM_MOUSEMOVE = 0x0200;
            const int WM_NCLBUTTONDOWN = 0x00A1;
            const int WM_WINDOWPOSCHANGED = 0x0047;
            const int WM_MOVE = 0x0003;
            const int WM_PAINT = 0x000F;
            const int WM_ENTERSIZEMOVE = 0x0231;
            const int WM_EXITSIZEMOVE = 0x0232;

            switch (m.Msg)
            {
                case WM_NCHITTEST: CountWmNcHitTest++; break;
                case WM_MOUSEMOVE: CountWmMouseMove++; break;
                case WM_NCLBUTTONDOWN: CountWmNcLButtonDown++; break;
                case WM_WINDOWPOSCHANGED: CountWmWindowPosChanged++; break;
                case WM_MOVE: CountWmMove++; break;
                case WM_PAINT: CountWmPaint++; break;
                case WM_ENTERSIZEMOVE: CountEnterSizeMove++; break;
                case WM_EXITSIZEMOVE: CountExitSizeMove++; break;
            }

            // Count SendMouseInput forwarding
            if (m.Msg == WM_MOUSEMOVE || m.Msg == 0x0201 || m.Msg == 0x0202 || m.Msg == 0x0204 || m.Msg == 0x0205)
            {
                // If it's in client area
                int screenX = unchecked((short)(m.LParam.ToInt64() & 0xFFFF));
                int screenY = unchecked((short)((m.LParam.ToInt64() >> 16) & 0xFFFF));
                Point pt = this.PointToClient(new Point(screenX, screenY));
                if (!(pt.Y >= 0 && pt.Y <= 38 && (pt.X <= 145 || pt.X >= 245)))
                {
                    CountSendMouseInput++;
                }
            }

            base.WndProc(ref m);
        }

        public void ResetTelemetry()
        {
            CountWmNcHitTest = 0;
            CountWmMouseMove = 0;
            CountWmNcLButtonDown = 0;
            CountWmWindowPosChanged = 0;
            CountWmMove = 0;
            CountWmPaint = 0;
            CountSendMouseInput = 0;
            CountDCompCommit = 0;
            CountEnterSizeMove = 0;
            CountExitSizeMove = 0;
            CountTotalMessages = 0;
        }
    }
}
"""

with open(r"D:\yihuanpaimai\tools\DragProfilingForm.cs", "w", encoding="utf-8") as f:
    f.write(CS_CODE)

cmd_compile = r'"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /target:library /platform:x64 /out:"D:\yihuanpaimai\tools\DragProfilingForm.dll" /r:"C:\Program Files\Python310\Lib\site-packages\webview\lib\Microsoft.Web.WebView2.Core.dll" /r:"System.Windows.Forms.dll" /r:"System.Drawing.dll" /r:"D:\yihuanpaimai\app\DirectCompositionHost.dll" "D:\yihuanpaimai\tools\DragProfilingForm.cs"'
subprocess.check_call(cmd_compile, shell=True)

import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
clr.AddReference('System.IO')
clr.AddReference(WV2_DLL)
clr.AddReference(DLL_PATH)
clr.AddReference(r"D:\yihuanpaimai\tools\DragProfilingForm.dll")

from System.Threading import Thread, ThreadStart, ApartmentState
import System.Windows.Forms as WinForms
from Microsoft.Web.WebView2.Core import CoreWebView2Environment
from NTE.Profiling import DragProfilingForm

user32 = ctypes.windll.user32
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MOVE = 0x0001

def run_profiling_benchmark():
    print("=" * 70)
    print("LONG-DURATION DRAG PROFILING HARNESS (DIAGNOSTIC BENCHMARK)")
    print("=" * 70)

    form_ref = None
    env_ref = None
    hud_hwnd = None
    is_running = True

    # 1. Start WS server to emulate Vision observations at 10 FPS
    import asyncio, websockets
    ws_received_count = 0
    ws_sent_count = 0

    async def ws_mock_server(ws):
        nonlocal ws_received_count, ws_sent_count
        async for msg in ws:
            ws_received_count += 1
            data = json.loads(msg)
            if data.get("type") == "report_hud_status":
                pass

    def start_mock_ws():
        async def _run():
            nonlocal ws_sent_count
            async with websockets.serve(ws_mock_server, "127.0.0.1", 8766):
                while is_running:
                    await asyncio.sleep(0.1) # 10 FPS observation broadcast
                    payload = {
                        "solverStatus": "valid",
                        "inAuction": True,
                        "gameDetected": True,
                        "round": 2,
                        "timer": 15,
                        "q": 9,
                        "avg": 33538,
                        "knownPurple": ["拈花小像", "金角月芒"],
                        "knownGold": ["万有星仪"],
                        "leaderBid": 120000,
                        "myBid": 110000
                    }
                    # broadcast to all connected
                    # websockets broadcast
                    ws_sent_count += 1
        try:
            asyncio.run(_run())
        except Exception:
            pass

    t_ws = threading.Thread(target=start_mock_ws, daemon=True)
    t_ws.start()

    # 2. Start GUI STA thread
    init_x, init_y = 400, 200
    def _gui():
        nonlocal form_ref, env_ref, hud_hwnd
        form = DragProfilingForm(init_x, init_y, 390, 450, True)
        form_ref = form
        form.Show()
        hud_hwnd = form.Handle.ToInt64()

        data_folder = os.path.join(PROJECT_ROOT, "build", "wv2_profiler_data")
        os.makedirs(data_folder, exist_ok=True)

        env_task = CoreWebView2Environment.CreateAsync(None, data_folder, None)
        while not env_task.IsCompleted:
            WinForms.Application.DoEvents()
        env = env_task.Result
        env_ref = env

        form.InitializeComposition(env, HTML_PATH)

        while is_running:
            WinForms.Application.DoEvents()
            time.sleep(0.002)

        form.Close()

    t_gui = Thread(ThreadStart(_gui))
    t_gui.SetApartmentState(ApartmentState.STA)
    t_gui.Start()

    time.sleep(3.0) # Wait for WebView2 to fully load and connect WS
    
    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint), ("dwHighDateTime", ctypes.c_uint)]

    kernel32 = ctypes.windll.kernel32
    h_proc = kernel32.GetCurrentProcess()

    def get_proc_cpu_ms():
        creation = FILETIME()
        exit_t = FILETIME()
        kernel_t = FILETIME()
        user_t = FILETIME()
        kernel32.GetProcessTimes(h_proc, ctypes.byref(creation), ctypes.byref(exit_t), ctypes.byref(kernel_t), ctypes.byref(user_t))
        k_val = (kernel_t.dwHighDateTime << 32) + kernel_t.dwLowDateTime
        u_val = (user_t.dwHighDateTime << 32) + user_t.dwLowDateTime
        return (u_val / 10000.0), (k_val / 10000.0)

    # Helper function to run a profiling profile
    def profile_scenario(name, duration_sec, is_dragging=False, drag_speed_px_per_sec=10):
        print(f"\n>>> Running Scenario: {name} (Duration={duration_sec}s)...")
        form_ref.ResetTelemetry()
        ws_sent_start = ws_sent_count

        user_start, kernel_start = get_proc_cpu_ms()
        t_start = time.perf_counter()

        rect = form_ref.Bounds
        start_x = rect.X + 60
        start_y = rect.Y + 15

        if is_dragging:
            user32.SetCursorPos(start_x, start_y)
            time.sleep(0.02)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.02)

        steps = int(duration_sec * 50) # 50 mouse updates per sec
        step_interval = 1.0 / 50.0

        current_x = start_x
        current_y = start_y
        direction = 1

        for step in range(steps):
            t_step_start = time.perf_counter()
            if is_dragging:
                # Oscillate back and forth horizontally at slow speed
                dx = int(direction * (drag_speed_px_per_sec / 50.0))
                current_x += dx
                if current_x > start_x + 150:
                    direction = -1
                elif current_x < start_x - 150:
                    direction = 1
                user32.SetCursorPos(current_x, current_y)

            t_elapsed = time.perf_counter() - t_step_start
            t_rem = step_interval - t_elapsed
            if t_rem > 0:
                time.sleep(t_rem)

        if is_dragging:
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.05)

        t_end = time.perf_counter()
        user_end, kernel_end = get_proc_cpu_ms()
        actual_duration = t_end - t_start

        user_cpu_ms = user_end - user_start
        sys_cpu_ms = kernel_end - kernel_start
        total_cpu_ms = user_cpu_ms + sys_cpu_ms
        cpu_pct = (total_cpu_ms / (actual_duration * 1000.0)) * 100.0

        ws_sent_delta = ws_sent_count - ws_sent_start
        ws_rate = ws_sent_delta / actual_duration

        # Read C# telemetry counters
        n_nchittest = form_ref.CountWmNcHitTest
        n_mousemove = form_ref.CountWmMouseMove
        n_winpos = form_ref.CountWmWindowPosChanged
        n_move = form_ref.CountWmMove
        n_paint = form_ref.CountWmPaint
        n_mouse_input = form_ref.CountSendMouseInput
        n_dcomp = form_ref.CountDCompCommit
        n_entersize = form_ref.CountEnterSizeMove
        n_exitsize = form_ref.CountExitSizeMove
        n_total_msg = form_ref.CountTotalMessages

        result = {
            "scenario": name,
            "duration_sec": round(actual_duration, 2),
            "cpu_user_ms": round(user_cpu_ms, 1),
            "cpu_sys_ms": round(sys_cpu_ms, 1),
            "cpu_total_ms": round(total_cpu_ms, 1),
            "cpu_utilization_pct": round(cpu_pct, 2),
            "total_messages": n_total_msg,
            "msg_rate_per_sec": round(n_total_msg / actual_duration, 1),
            "wm_nchittest_count": n_nchittest,
            "wm_nchittest_rate": round(n_nchittest / actual_duration, 1),
            "wm_mousemove_count": n_mousemove,
            "wm_mousemove_rate": round(n_mousemove / actual_duration, 1),
            "wm_windowposchanged_count": n_winpos,
            "wm_windowposchanged_rate": round(n_winpos / actual_duration, 1),
            "wm_move_count": n_move,
            "wm_paint_count": n_paint,
            "webview2_send_mouse_input_count": n_mouse_input,
            "dcomp_commit_count": n_dcomp,
            "ws_observation_sent_count": ws_sent_delta,
            "ws_observation_rate_hz": round(ws_rate, 1),
            "enter_size_move_count": n_entersize,
            "exit_size_move_count": n_exitsize
        }

        print(f"  Result for [{name}]:")
        for k, v in result.items():
            print(f"    - {k}: {v}")
        return result

    # Run 4 scenarios
    r1 = profile_scenario("1. Stationary 10s (静止 10 秒)", 10.0, is_dragging=False)
    r2 = profile_scenario("2. Slow Drag 2s (慢拖 2 秒)", 2.0, is_dragging=True, drag_speed_px_per_sec=20)
    r3 = profile_scenario("3. Slow Drag 10s (慢拖 10 秒)", 10.0, is_dragging=True, drag_speed_px_per_sec=20)
    r4 = profile_scenario("4. Slow Drag 20s (慢拖 20 秒)", 20.0, is_dragging=True, drag_speed_px_per_sec=20)

    # Clean shutdown
    is_running = False
    time.sleep(0.5)

    print("\n" + "=" * 70)
    print("PROFILING COMPARISON MATRIX")
    print("=" * 70)
    print(json.dumps([r1, r2, r3, r4], indent=2, ensure_ascii=False))

    with open(r"D:\yihuanpaimai\tools\drag_profiling_results.json", "w", encoding="utf-8") as f:
        json.dump([r1, r2, r3, r4], f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    run_profiling_benchmark()
