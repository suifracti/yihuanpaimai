using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using NTE.DirectComposition;

namespace NTE.DragProfiler
{
    public class ProfilerForm : DirectCompositionHudForm
    {
        public long MsgTotal = 0;
        public long MsgNcHitTest = 0;
        public long MsgMouseMove = 0;
        public long MsgNcLButtonDown = 0;
        public long MsgWindowPosChanged = 0;
        public long MsgMove = 0;
        public long MsgPaint = 0;
        public long MsgEnterSizeMove = 0;
        public long MsgExitSizeMove = 0;
        public long CountSendMouseInput = 0;
        public long CountDCompCommit = 0;
        public long CountWebMessages = 0;

        public ProfilerForm(int x, int y, int w, int h, bool onTop) : base(x, y, w, h, onTop)
        {
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            CountDCompCommit++;
        }

        protected override void WndProc(ref Message m)
        {
            MsgTotal++;
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
                case WM_NCHITTEST: MsgNcHitTest++; break;
                case WM_MOUSEMOVE: MsgMouseMove++; break;
                case WM_NCLBUTTONDOWN: MsgNcLButtonDown++; break;
                case WM_WINDOWPOSCHANGED: MsgWindowPosChanged++; break;
                case WM_MOVE: MsgMove++; break;
                case WM_PAINT: MsgPaint++; break;
                case WM_ENTERSIZEMOVE: MsgEnterSizeMove++; break;
                case WM_EXITSIZEMOVE: MsgExitSizeMove++; break;
            }

            // Check if SendMouseInput is called in base.WndProc
            if (m.Msg == WM_MOUSEMOVE || m.Msg == 0x0201 || m.Msg == 0x0202 || m.Msg == 0x0204 || m.Msg == 0x0205)
            {
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

        public void ResetCounters()
        {
            MsgTotal = 0;
            MsgNcHitTest = 0;
            MsgMouseMove = 0;
            MsgNcLButtonDown = 0;
            MsgWindowPosChanged = 0;
            MsgMove = 0;
            MsgPaint = 0;
            MsgEnterSizeMove = 0;
            MsgExitSizeMove = 0;
            CountSendMouseInput = 0;
            CountDCompCommit = 0;
            CountWebMessages = 0;
        }
    }

    public class ScenarioResult
    {
        public string ScenarioName;
        public double DurationSec;
        public double CpuUserMs;
        public double CpuPrivilegedMs;
        public double CpuTotalMs;
        public double CpuPercent;
        public long TotalMessages;
        public double MessageRateHz;
        public long WmNcHitTestCount;
        public double WmNcHitTestRateHz;
        public long WmMouseMoveCount;
        public double WmMouseMoveRateHz;
        public long WmWindowPosChangedCount;
        public double WmWindowPosChangedRateHz;
        public long WmMoveCount;
        public long WmPaintCount;
        public long SendMouseInputCount;
        public long DCompCommitCount;
        public long EnterSizeMoveCount;
        public long ExitSizeMoveCount;
        public long WsObservationSentCount;
        public double WsObservationRateHz;
    }

    class Program
    {
        [DllImport("user32.dll")]
        static extern bool SetCursorPos(int X, int Y);

        [DllImport("user32.dll")]
        static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

        [STAThread]
        static void Main(string[] args)
        {
            AppDomain.CurrentDomain.AssemblyResolve += (sender, resolveArgs) =>
            {
                string dllName = new System.Reflection.AssemblyName(resolveArgs.Name).Name + ".dll";
                string webviewPath = @"C:\Program Files\Python310\Lib\site-packages\webview\lib\" + dllName;
                if (File.Exists(webviewPath)) return System.Reflection.Assembly.LoadFrom(webviewPath);
                string appPath = @"D:\yihuanpaimai\app\" + dllName;
                if (File.Exists(appPath)) return System.Reflection.Assembly.LoadFrom(appPath);
                return null;
            };

            Console.WriteLine("======================================================================");
            Console.WriteLine("NATIVE LONG-DURATION DRAG PROFILING HARNESS (DIAGNOSTIC RUNNER)");
            Console.WriteLine("======================================================================");

            string projectRoot = @"D:\yihuanpaimai";
            string htmlPath = Path.Combine(projectRoot, @"core\tactical_hud.html");
            string wv2Data = Path.Combine(projectRoot, @"build\wv2_bench_data");
            Directory.CreateDirectory(wv2Data);

            ProfilerForm form = new ProfilerForm(300, 200, 390, 450, true);
            form.Show();

            CoreWebView2Environment env = null;
            var envTask = CoreWebView2Environment.CreateAsync(null, wv2Data, null);
            while (!envTask.IsCompleted)
            {
                Application.DoEvents();
                Thread.Sleep(10);
            }
            env = envTask.Result;

            form.InitializeComposition(env, htmlPath);

            form.WebMessageReceivedCallback += (msg) =>
            {
                form.CountWebMessages++;
            };

            // Wait 3s for UI, JS and WS to stabilize
            Stopwatch swInit = Stopwatch.StartNew();
            while (swInit.ElapsedMilliseconds < 3000)
            {
                Application.DoEvents();
                Thread.Sleep(10);
            }

            Process proc = Process.GetCurrentProcess();
            List<ScenarioResult> results = new List<ScenarioResult>();

            Func<string, double, bool, double, ScenarioResult> runScenario = (name, targetDurationSec, isDrag, dragSpeedPxPerSec) =>
            {
                Console.WriteLine("\n>>> Profiling Scenario: " + name + " (Duration=" + targetDurationSec + "s)...");
                form.ResetCounters();

                TimeSpan cpuUserStart = proc.UserProcessorTime;
                TimeSpan cpuPrivStart = proc.PrivilegedProcessorTime;
                Stopwatch sw = Stopwatch.StartNew();

                Point p = form.Location;
                int startX = p.X + 60;
                int startY = p.Y + 15;

                if (isDrag)
                {
                    SetCursorPos(startX, startY);
                    Thread.Sleep(20);
                    mouse_event(2, 0, 0, 0, UIntPtr.Zero); // Left Down
                    Thread.Sleep(20);
                }

                double elapsedSec = 0;
                int dir = 1;
                int curX = startX;
                int curY = startY;

                while ((elapsedSec = sw.Elapsed.TotalSeconds) < targetDurationSec)
                {
                    Application.DoEvents();

                    if (isDrag)
                    {
                        curX += (int)(dir * (dragSpeedPxPerSec * 0.02));
                        if (curX > startX + 160) dir = -1;
                        else if (curX < startX - 160) dir = 1;
                        SetCursorPos(curX, curY);
                    }

                    Thread.Sleep(15);
                }

                if (isDrag)
                {
                    mouse_event(4, 0, 0, 0, UIntPtr.Zero); // Left Up
                    Thread.Sleep(50);
                }

                sw.Stop();
                TimeSpan cpuUserEnd = proc.UserProcessorTime;
                TimeSpan cpuPrivEnd = proc.PrivilegedProcessorTime;

                double actualDuration = sw.Elapsed.TotalSeconds;
                double userMs = (cpuUserEnd - cpuUserStart).TotalMilliseconds;
                double privMs = (cpuPrivEnd - cpuPrivStart).TotalMilliseconds;
                double totalCpuMs = userMs + privMs;
                double cpuPct = (totalCpuMs / (actualDuration * 1000.0)) * 100.0;

                ScenarioResult res = new ScenarioResult
                {
                    ScenarioName = name,
                    DurationSec = Math.Round(actualDuration, 2),
                    CpuUserMs = Math.Round(userMs, 1),
                    CpuPrivilegedMs = Math.Round(privMs, 1),
                    CpuTotalMs = Math.Round(totalCpuMs, 1),
                    CpuPercent = Math.Round(cpuPct, 2),
                    TotalMessages = form.MsgTotal,
                    MessageRateHz = Math.Round(form.MsgTotal / actualDuration, 1),
                    WmNcHitTestCount = form.MsgNcHitTest,
                    WmNcHitTestRateHz = Math.Round(form.MsgNcHitTest / actualDuration, 1),
                    WmMouseMoveCount = form.MsgMouseMove,
                    WmMouseMoveRateHz = Math.Round(form.MsgMouseMove / actualDuration, 1),
                    WmWindowPosChangedCount = form.MsgWindowPosChanged,
                    WmWindowPosChangedRateHz = Math.Round(form.MsgWindowPosChanged / actualDuration, 1),
                    WmMoveCount = form.MsgMove,
                    WmPaintCount = form.MsgPaint,
                    SendMouseInputCount = form.CountSendMouseInput,
                    DCompCommitCount = form.CountDCompCommit,
                    EnterSizeMoveCount = form.MsgEnterSizeMove,
                    ExitSizeMoveCount = form.MsgExitSizeMove,
                    WsObservationSentCount = form.CountWebMessages,
                    WsObservationRateHz = Math.Round(form.CountWebMessages / actualDuration, 1)
                };

                Console.WriteLine("  Results for [" + name + "]:");
                Console.WriteLine("    - Duration: " + res.DurationSec + "s");
                Console.WriteLine("    - CPU Total: " + res.CpuTotalMs + " ms (" + res.CpuPercent + "% load)");
                Console.WriteLine("    - Total Windows Messages: " + res.TotalMessages + " (" + res.MessageRateHz + " msg/sec)");
                Console.WriteLine("    - WM_NCHITTEST: " + res.WmNcHitTestCount + " (" + res.WmNcHitTestRateHz + " Hz)");
                Console.WriteLine("    - WM_MOUSEMOVE: " + res.WmMouseMoveCount + " (" + res.WmMouseMoveRateHz + " Hz)");
                Console.WriteLine("    - WM_WINDOWPOSCHANGED: " + res.WmWindowPosChangedCount + " (" + res.WmWindowPosChangedRateHz + " Hz)");
                Console.WriteLine("    - WM_PAINT: " + res.WmPaintCount);
                Console.WriteLine("    - SendMouseInput (WebView2): " + res.SendMouseInputCount);
                Console.WriteLine("    - DComp Commit: " + res.DCompCommitCount);

                return res;
            };

            // Run the 4 requested scenarios
            results.Add(runScenario("1. Stationary 10s (静止 10 秒)", 10.0, false, 0));
            results.Add(runScenario("2. Slow Drag 2s (慢拖 2 秒)", 2.0, true, 20));
            results.Add(runScenario("3. Slow Drag 10s (慢拖 10 秒)", 10.0, true, 20));
            results.Add(runScenario("4. Slow Drag 20s (慢拖 20 秒)", 20.0, true, 20));

            form.Close();

            Console.WriteLine("\n======================================================================");
            Console.WriteLine("PROFILING COMPARISON MATRIX SUMMARY");
            Console.WriteLine("======================================================================");
            foreach (var r in results)
            {
                Console.WriteLine(string.Format("{0,-32} | CPU: {1,5:F1}% ({2,6:F1}ms) | MsgRate: {3,6:F1}Hz | WinPos: {4,5} ({5,4:F1}Hz) | NCHitTest: {6,5} | SendMouseInput: {7}",
                    r.ScenarioName, r.CpuPercent, r.CpuTotalMs, r.MessageRateHz, r.WmWindowPosChangedCount, r.WmWindowPosChangedRateHz, r.WmNcHitTestCount, r.SendMouseInputCount));
            }
        }
    }
}
