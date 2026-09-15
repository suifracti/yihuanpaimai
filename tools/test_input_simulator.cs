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

namespace NTE.SendInputBenchmark
{
    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X; public int Y; }

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }

    [StructLayout(LayoutKind.Sequential)]
    public struct MOUSEINPUT
    {
        public int dx;
        public int dy;
        public uint mouseData;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct INPUT
    {
        [FieldOffset(0)] public int type;
        [FieldOffset(8)] public MOUSEINPUT mi;
    }

    public class BenchReport
    {
        public string MethodName;
        public double DurationSec;
        public int MouseMoveMessages;
        public double MouseMoveRateHz;
        public int SetWindowPosCalls;
        public double SetWindowPosRateHz;
        public int RecordedPositionUpdates;
        public double CadenceHz;
        public double MedianIntervalMs;
        public double P95IntervalMs;
        public double MaxSpikeMs;
        public double JitterStdDevMs;
        public int DropsOver33ms;
        public double TotalDisplacementPx;
    }

    // Method A: HTCAPTION Modal Drag Form
    public class FormA_Modal : DirectCompositionHudForm
    {
        public int MouseMoveCount = 0;
        public int PosChangedCount = 0;
        public List<long> PosTimestamps = new List<long>();

        public FormA_Modal(int x, int y, int w, int h) : base(x, y, w, h, true) { }

        protected override void WndProc(ref Message m)
        {
            const int WM_MOUSEMOVE = 0x0200;
            const int WM_NCHITTEST = 0x0084;
            const int WM_WINDOWPOSCHANGED = 0x0047;
            const int HTCAPTION = 2;
            const int HTCLIENT = 1;

            if (m.Msg == WM_MOUSEMOVE) MouseMoveCount++;
            if (m.Msg == WM_WINDOWPOSCHANGED)
            {
                PosChangedCount++;
                PosTimestamps.Add(Stopwatch.GetTimestamp());
            }

            if (m.Msg == WM_NCHITTEST)
            {
                int screenX = unchecked((short)(m.LParam.ToInt64() & 0xFFFF));
                int screenY = unchecked((short)((m.LParam.ToInt64() >> 16) & 0xFFFF));
                Point pt = this.PointToClient(new Point(screenX, screenY));

                if (pt.Y >= 0 && pt.Y <= 38 && (pt.X <= 145 || pt.X >= 245))
                {
                    m.Result = (IntPtr)HTCAPTION;
                    return;
                }
                m.Result = (IntPtr)HTCLIENT;
                return;
            }

            base.WndProc(ref m);
        }
    }

    // Method B: Native Non-Modal Drag Form
    public class FormB_NonModal : DirectCompositionHudForm
    {
        [DllImport("user32.dll")]
        static extern bool SetCapture(IntPtr hWnd);

        [DllImport("user32.dll")]
        static extern bool ReleaseCapture();

        [DllImport("user32.dll")]
        static extern bool GetCursorPos(out POINT lpPoint);

        [DllImport("user32.dll")]
        static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        public bool IsDragging = false;
        private Point cursorStart;
        private Point windowStart;

        public int MouseMoveCount = 0;
        public int SetWindowPosCalls = 0;
        public int PosChangedCount = 0;
        public List<long> PosTimestamps = new List<long>();

        const uint SWP_NOSIZE = 0x0001;
        const uint SWP_NOZORDER = 0x0004;
        const uint SWP_NOACTIVATE = 0x0010;
        const uint SWP_ASYNCWINDOWPOS = 0x4000;

        public FormB_NonModal(int x, int y, int w, int h) : base(x, y, w, h, true) { }

        protected override void WndProc(ref Message m)
        {
            const int WM_LBUTTONDOWN = 0x0201;
            const int WM_MOUSEMOVE = 0x0200;
            const int WM_LBUTTONUP = 0x0202;
            const int WM_NCHITTEST = 0x0084;
            const int WM_WINDOWPOSCHANGED = 0x0047;
            const int HTCLIENT = 1;

            if (m.Msg == WM_WINDOWPOSCHANGED)
            {
                PosChangedCount++;
                PosTimestamps.Add(Stopwatch.GetTimestamp());
            }

            if (m.Msg == WM_NCHITTEST)
            {
                m.Result = (IntPtr)HTCLIENT;
                return;
            }

            if (m.Msg == WM_LBUTTONDOWN)
            {
                int screenX = unchecked((short)(m.LParam.ToInt64() & 0xFFFF));
                int screenY = unchecked((short)((m.LParam.ToInt64() >> 16) & 0xFFFF));
                Point pt = this.PointToClient(new Point(screenX, screenY));

                if (pt.Y >= 0 && pt.Y <= 38 && (pt.X <= 145 || pt.X >= 245))
                {
                    IsDragging = true;
                    SetCapture(this.Handle);
                    cursorStart = new Point(screenX, screenY);
                    windowStart = this.Location;
                    return;
                }
            }
            else if (m.Msg == WM_MOUSEMOVE)
            {
                MouseMoveCount++;
                if (IsDragging)
                {
                    POINT curPos;
                    GetCursorPos(out curPos);
                    int newX = windowStart.X + (curPos.X - cursorStart.X);
                    int newY = windowStart.Y + (curPos.Y - cursorStart.Y);

                    SetWindowPos(this.Handle, IntPtr.Zero, newX, newY, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS);
                    SetWindowPosCalls++;
                    return;
                }
            }
            else if (m.Msg == WM_LBUTTONUP)
            {
                if (IsDragging)
                {
                    IsDragging = false;
                    ReleaseCapture();
                    return;
                }
            }

            base.WndProc(ref m);
        }
    }

    class Program
    {
        [DllImport("user32.dll", SetLastError = true)]
        static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

        [DllImport("user32.dll")]
        static extern int GetSystemMetrics(int nIndex);

        [DllImport("user32.dll")]
        static extern bool SetForegroundWindow(IntPtr hWnd);

        static void SendHardwareMouseDown(int x, int y)
        {
            int screenW = GetSystemMetrics(0);
            int screenH = GetSystemMetrics(1);

            INPUT[] inputs = new INPUT[2];
            inputs[0].type = 0; // INPUT_MOUSE
            inputs[0].mi.dx = (int)((x * 65535.0) / screenW);
            inputs[0].mi.dy = (int)((y * 65535.0) / screenH);
            inputs[0].mi.dwFlags = 0x8000 | 0x0001; // MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE

            inputs[1].type = 0;
            inputs[1].mi.dwFlags = 0x0002; // MOUSEEVENTF_LEFTDOWN

            SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT)));
        }

        static void SendHardwareMouseMove(int x, int y)
        {
            int screenW = GetSystemMetrics(0);
            int screenH = GetSystemMetrics(1);

            INPUT[] inputs = new INPUT[1];
            inputs[0].type = 0;
            inputs[0].mi.dx = (int)((x * 65535.0) / screenW);
            inputs[0].mi.dy = (int)((y * 65535.0) / screenH);
            inputs[0].mi.dwFlags = 0x8000 | 0x0001; // MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE

            SendInput(1, inputs, Marshal.SizeOf(typeof(INPUT)));
        }

        static void SendHardwareMouseUp()
        {
            INPUT[] inputs = new INPUT[1];
            inputs[0].type = 0;
            inputs[0].mi.dwFlags = 0x0004; // MOUSEEVENTF_LEFTUP
            SendInput(1, inputs, Marshal.SizeOf(typeof(INPUT)));
        }

        [STAThread]
        static void Main(string[] args)
        {
            Console.WriteLine("======================================================================");
            Console.WriteLine("DISCRIMINATIVE BENCHMARK: NON-MODAL SETWINDOWPOS VS HTCAPTION MODAL");
            Console.WriteLine("======================================================================");

            string projectRoot = @"D:\yihuanpaimai";
            string htmlPath = Path.Combine(projectRoot, @"core\tactical_hud.html");
            string wv2Data = Path.Combine(projectRoot, @"build\wv2_bench_data");
            Directory.CreateDirectory(wv2Data);

            CoreWebView2Environment env = null;
            var envTask = CoreWebView2Environment.CreateAsync(null, wv2Data, null);
            while (!envTask.IsCompleted)
            {
                Application.DoEvents();
                Thread.Sleep(10);
            }
            env = envTask.Result;

            Func<string, DirectCompositionHudForm, double, BenchReport> runTest = (name, form, durationSec) =>
            {
                Console.WriteLine("\n>>> Testing [" + name + "] (" + durationSec + "s)...");
                form.Show();
                form.InitializeComposition(env, htmlPath);
                SetForegroundWindow(form.Handle);
                Application.DoEvents();
                Thread.Sleep(1000);

                int startX = form.Location.X + 60;
                int startY = form.Location.Y + 15;

                bool testRunning = true;
                double speed = 25.0;

                // Background input simulation thread (Injects physical SendInput events at 60Hz)
                Thread inputThread = new Thread(() =>
                {
                    Thread.Sleep(200);
                    SendHardwareMouseDown(startX, startY);
                    Thread.Sleep(50);

                    Stopwatch sw = Stopwatch.StartNew();
                    int dir = 1;
                    int curX = startX;
                    int curY = startY;

                    while (sw.Elapsed.TotalSeconds < durationSec && testRunning)
                    {
                        curX += (int)(dir * (speed * 0.016));
                        if (curX > startX + 150) dir = -1;
                        else if (curX < startX - 150) dir = 1;

                        SendHardwareMouseMove(curX, curY);
                        Thread.Sleep(16); // 60 Hz input packets
                    }

                    SendHardwareMouseUp();
                    Thread.Sleep(50);
                });
                inputThread.Start();

                Stopwatch swMain = Stopwatch.StartNew();
                while (swMain.Elapsed.TotalSeconds < durationSec + 0.5 && inputThread.IsAlive)
                {
                    Application.DoEvents();
                    Thread.Sleep(5);
                }

                testRunning = false;
                inputThread.Join(500);

                // Collect results
                List<long> tsList = null;
                int mouseCount = 0;
                int setPosCount = 0;

                if (form is FormA_Modal)
                {
                    var fa = form as FormA_Modal;
                    tsList = fa.PosTimestamps;
                    mouseCount = fa.MouseMoveCount;
                    setPosCount = fa.PosChangedCount;
                }
                else if (form is FormB_NonModal)
                {
                    var fb = form as FormB_NonModal;
                    tsList = fb.PosTimestamps;
                    mouseCount = fb.MouseMoveCount;
                    setPosCount = fb.SetWindowPosCalls;
                }

                double actualSec = swMain.Elapsed.TotalSeconds;
                List<double> intervals = new List<double>();
                double sumInt = 0.0;
                double maxSpike = 0.0;
                int d33 = 0;

                for (int i = 1; i < tsList.Count; i++)
                {
                    double dt = (tsList[i] - tsList[i - 1]) * 1000.0 / (double)Stopwatch.Frequency;
                    intervals.Add(dt);
                    sumInt += dt;
                    if (dt > maxSpike) maxSpike = dt;
                    if (dt > 33.3) d33++;
                }

                intervals.Sort();
                double median = 0.0;
                double p95 = 0.0;
                if (intervals.Count > 0)
                {
                    median = intervals[intervals.Count / 2];
                    int p95Idx = (int)(intervals.Count * 0.95);
                    p95 = intervals[Math.Min(p95Idx, intervals.Count - 1)];
                }

                double mean = intervals.Count > 0 ? sumInt / intervals.Count : 0.0;
                double varSum = 0.0;
                foreach (var iv in intervals) varSum += (iv - mean) * (iv - mean);
                double stdDev = intervals.Count > 0 ? Math.Sqrt(varSum / intervals.Count) : 0.0;

                BenchReport rep = new BenchReport
                {
                    MethodName = name,
                    DurationSec = Math.Round(actualSec, 2),
                    MouseMoveMessages = mouseCount,
                    MouseMoveRateHz = Math.Round(mouseCount / actualSec, 1),
                    SetWindowPosCalls = setPosCount,
                    SetWindowPosRateHz = Math.Round(setPosCount / actualSec, 1),
                    RecordedPositionUpdates = tsList.Count,
                    CadenceHz = Math.Round(tsList.Count / actualSec, 1),
                    MedianIntervalMs = Math.Round(median, 2),
                    P95IntervalMs = Math.Round(p95, 2),
                    MaxSpikeMs = Math.Round(maxSpike, 2),
                    JitterStdDevMs = Math.Round(stdDev, 2),
                    DropsOver33ms = d33
                };

                Console.WriteLine("  [" + name + " - " + durationSec + "s] Result:");
                Console.WriteLine("    - MouseMove msgs: " + rep.MouseMoveMessages + " (" + rep.MouseMoveRateHz + " Hz)");
                Console.WriteLine("    - SetWindowPos: " + rep.SetWindowPosCalls + " (" + rep.SetWindowPosRateHz + " Hz)");
                Console.WriteLine("    - Position Update Cadence: " + rep.CadenceHz + " Hz (" + rep.RecordedPositionUpdates + " updates)");
                Console.WriteLine("    - Interval Distribution: Median=" + rep.MedianIntervalMs + " ms, P95=" + rep.P95IntervalMs + " ms, Max=" + rep.MaxSpikeMs + " ms");
                Console.WriteLine("    - Drops >33ms (<30fps): " + rep.DropsOver33ms + " (" + (intervals.Count > 0 ? (d33 * 100.0 / intervals.Count).ToString("F1") : "0") + "%)");

                form.Close();
                Thread.Sleep(300);
                return rep;
            };

            List<BenchReport> reports = new List<BenchReport>();

            // Method A (HTCAPTION Modal) 2s, 10s, 20s
            reports.Add(runTest("Method A (HTCAPTION Modal)", new FormA_Modal(400, 200, 390, 450), 2.0));
            reports.Add(runTest("Method A (HTCAPTION Modal)", new FormA_Modal(400, 200, 390, 450), 10.0));
            reports.Add(runTest("Method A (HTCAPTION Modal)", new FormA_Modal(400, 200, 390, 450), 20.0));

            // Method B (Native Non-Modal SetWindowPos) 2s, 10s, 20s
            reports.Add(runTest("Method B (Native Non-Modal)", new FormB_NonModal(400, 200, 390, 450), 2.0));
            reports.Add(runTest("Method B (Native Non-Modal)", new FormB_NonModal(400, 200, 390, 450), 10.0));
            reports.Add(runTest("Method B (Native Non-Modal)", new FormB_NonModal(400, 200, 390, 450), 20.0));

            Console.WriteLine("\n======================================================================");
            Console.WriteLine("METHOD A VS METHOD B FINAL CADENCE SUMMARY");
            Console.WriteLine("======================================================================");
            Console.WriteLine(string.Format("{0,-28} | {1,4} | {2,8} | {3,8} | {4,8} | {5,8} | {6,12} | {7,10}",
                "Method", "Sec", "Cadence", "Median", "P95", "MaxSpike", ">33ms (<30f)", "SetWinPos"));
            Console.WriteLine(new string('-', 105));

            foreach (var r in reports)
            {
                Console.WriteLine(string.Format("{0,-28} | {1,3:F0}s | {2,6:F1}Hz | {3,6:F1}ms | {4,6:F1}ms | {5,6:F1}ms | {6,12} | {7,10}",
                    r.MethodName, r.DurationSec, r.CadenceHz, r.MedianIntervalMs, r.P95IntervalMs, r.MaxSpikeMs, r.DropsOver33ms + " (" + (r.RecordedPositionUpdates > 1 ? (r.DropsOver33ms * 100.0 / (r.RecordedPositionUpdates - 1)).ToString("F0") : "0") + "%)", r.SetWindowPosCalls));
            }
        }
    }
}
