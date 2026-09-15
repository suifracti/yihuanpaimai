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

namespace NTE.NonModalExperiment
{
    public struct DragSample
    {
        public long Timestamp;
        public int X;
        public int Y;
    }

    public class ExperimentResult
    {
        public string MethodName;
        public double TargetDurationSec;
        public double ActualDurationSec;
        public int WmMouseMoveCount;
        public double WmMouseMoveRateHz;
        public int SetWindowPosCount;
        public double SetWindowPosRateHz;
        public int PositionChangeCount;
        public double CadenceHz;
        public double MedianIntervalMs;
        public double P95IntervalMs;
        public double MaxSpikeMs;
        public double MeanIntervalMs;
        public double JitterStdDevMs;
        public int DropsOver33ms; // < 30 FPS
        public int DropsOver50ms; // < 20 FPS
        public int DropsOver100ms; // Freeze
        public double TotalDisplacementPx;
        public double CpuPercent;
        public bool DegradationDetected;
    }

    // Method A Form: Current HTCAPTION Modal Drag
    public class FormMethodA_ModalDrag : DirectCompositionHudForm
    {
        public int WmMouseMoveCount = 0;
        public int SetWindowPosCount = 0;

        public FormMethodA_ModalDrag(int x, int y, int w, int h) : base(x, y, w, h, true)
        {
        }

        protected override void WndProc(ref Message m)
        {
            const int WM_MOUSEMOVE = 0x0200;
            const int WM_NCHITTEST = 0x0084;
            const int HTCAPTION = 2;
            const int HTCLIENT = 1;

            if (m.Msg == WM_MOUSEMOVE)
            {
                WmMouseMoveCount++;
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

    // Method B Form: Native Non-Modal Manual Drag
    public class FormMethodB_NonModalDrag : DirectCompositionHudForm
    {
        [DllImport("user32.dll")]
        static extern bool SetCapture(IntPtr hWnd);

        [DllImport("user32.dll")]
        static extern bool ReleaseCapture();

        [DllImport("user32.dll")]
        static extern bool GetCursorPos(out POINT lpPoint);

        [DllImport("user32.dll")]
        static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        [StructLayout(LayoutKind.Sequential)]
        public struct POINT { public int X; public int Y; }

        public bool IsDragging = false;
        private Point cursorStart;
        private Point windowStart;

        public int WmMouseMoveCount = 0;
        public int SetWindowPosCount = 0;

        const uint SWP_NOSIZE = 0x0001;
        const uint SWP_NOZORDER = 0x0004;
        const uint SWP_NOACTIVATE = 0x0010;
        const uint SWP_ASYNCWINDOWPOS = 0x4000;

        public FormMethodB_NonModalDrag(int x, int y, int w, int h) : base(x, y, w, h, true)
        {
        }

        protected override void WndProc(ref Message m)
        {
            const int WM_LBUTTONDOWN = 0x0201;
            const int WM_MOUSEMOVE = 0x0200;
            const int WM_LBUTTONUP = 0x0202;
            const int WM_NCHITTEST = 0x0084;
            const int HTCLIENT = 1;

            // 1. All areas return HTCLIENT to stay purely in non-modal Win32 message flow
            if (m.Msg == WM_NCHITTEST)
            {
                m.Result = (IntPtr)HTCLIENT;
                return;
            }

            // 2. Drag initiation
            if (m.Msg == WM_LBUTTONDOWN)
            {
                int screenX = unchecked((short)(m.LParam.ToInt64() & 0xFFFF));
                int screenY = unchecked((short)((m.LParam.ToInt64() >> 16) & 0xFFFF));
                Point pt = this.PointToClient(new Point(screenX, screenY));

                // Check if click is on draggable title area
                if (pt.Y >= 0 && pt.Y <= 38 && (pt.X <= 145 || pt.X >= 245))
                {
                    IsDragging = true;
                    SetCapture(this.Handle);
                    cursorStart = new Point(screenX, screenY);
                    windowStart = this.Location;
                    return; // Consumed: do NOT forward to WebView2
                }
            }
            else if (m.Msg == WM_MOUSEMOVE)
            {
                WmMouseMoveCount++;
                if (IsDragging)
                {
                    POINT curPos;
                    GetCursorPos(out curPos);
                    int newX = windowStart.X + (curPos.X - cursorStart.X);
                    int newY = windowStart.Y + (curPos.Y - cursorStart.Y);

                    SetWindowPos(this.Handle, IntPtr.Zero, newX, newY, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS);
                    SetWindowPosCount++;
                    return; // Consumed: do NOT forward to WebView2 during drag
                }
            }
            else if (m.Msg == WM_LBUTTONUP)
            {
                if (IsDragging)
                {
                    IsDragging = false;
                    ReleaseCapture();
                    return; // Consumed: do NOT forward to WebView2
                }
            }

            // Normal non-drag interactions forward to WebView2
            base.WndProc(ref m);
        }
    }

    class Program
    {
        [DllImport("user32.dll")]
        static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

        [DllImport("user32.dll")]
        static extern bool SetCursorPos(int X, int Y);

        [DllImport("user32.dll")]
        static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

        [DllImport("user32.dll")]
        static extern bool SetForegroundWindow(IntPtr hWnd);

        [StructLayout(LayoutKind.Sequential)]
        public struct RECT { public int Left, Top, Right, Bottom; }

        [STAThread]
        static void Main(string[] args)
        {
            Console.WriteLine("======================================================================");
            Console.WriteLine("EXPERIMENT: NATIVE NON-MODAL DRAG VS HTCAPTION MODAL DRAG");
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

            Process proc = Process.GetCurrentProcess();

            Func<string, DirectCompositionHudForm, double, ExperimentResult> executeTest = (methodName, form, durationSec) =>
            {
                Console.WriteLine("\n----------------------------------------------------------------------");
                Console.WriteLine(">>> Executing [" + methodName + "] for " + durationSec + "s slow drag...");
                form.Show();
                form.InitializeComposition(env, htmlPath);

                SetForegroundWindow(form.Handle);
                Application.DoEvents();
                Thread.Sleep(1000);

                IntPtr hWnd = form.Handle;
                List<DragSample> samples = new List<DragSample>();
                bool isRunning = true;

                // High-precision 1ms sampler thread
                Thread sampler = new Thread(() =>
                {
                    RECT r;
                    int lastX = -999999;
                    int lastY = -999999;
                    while (isRunning)
                    {
                        if (GetWindowRect(hWnd, out r))
                        {
                            if (r.Left != lastX || r.Top != lastY)
                            {
                                samples.Add(new DragSample
                                {
                                    Timestamp = Stopwatch.GetTimestamp(),
                                    X = r.Left,
                                    Y = r.Top
                                });
                                lastX = r.Left;
                                lastY = r.Top;
                            }
                        }
                        Thread.Sleep(1);
                    }
                });
                sampler.Priority = ThreadPriority.Highest;
                sampler.Start();

                int startX = form.Location.X + 60;
                int startY = form.Location.Y + 15;

                SetCursorPos(startX, startY);
                Thread.Sleep(40);
                mouse_event(2, 0, 0, 0, UIntPtr.Zero); // Left Down
                Thread.Sleep(40);

                TimeSpan cpuStartUser = proc.UserProcessorTime;
                TimeSpan cpuStartPriv = proc.PrivilegedProcessorTime;
                Stopwatch sw = Stopwatch.StartNew();

                int dir = 1;
                int curX = startX;
                int curY = startY;
                double speed = 25.0; // 25 px/sec

                while (sw.Elapsed.TotalSeconds < durationSec)
                {
                    Application.DoEvents();

                    curX += (int)(dir * (speed * 0.015));
                    if (curX > startX + 150) dir = -1;
                    else if (curX < startX - 150) dir = 1;

                    SetCursorPos(curX, curY);
                    Thread.Sleep(10);
                }

                sw.Stop();
                mouse_event(4, 0, 0, 0, UIntPtr.Zero); // Left Up
                Thread.Sleep(50);

                isRunning = false;
                sampler.Join(500);

                TimeSpan cpuEndUser = proc.UserProcessorTime;
                TimeSpan cpuEndPriv = proc.PrivilegedProcessorTime;

                double actualSec = sw.Elapsed.TotalSeconds;
                double cpuMs = (cpuEndUser - cpuStartUser).TotalMilliseconds + (cpuEndPriv - cpuStartPriv).TotalMilliseconds;
                double cpuPct = (cpuMs / (actualSec * 1000.0)) * 100.0;

                // Interval statistics
                List<double> intervals = new List<double>();
                double sumInt = 0.0;
                double maxSpike = 0.0;
                int d33 = 0, d50 = 0, d100 = 0;
                double totalDisp = 0.0;

                for (int i = 1; i < samples.Count; i++)
                {
                    double dt = (samples[i].Timestamp - samples[i - 1].Timestamp) * 1000.0 / (double)Stopwatch.Frequency;
                    intervals.Add(dt);
                    sumInt += dt;
                    if (dt > maxSpike) maxSpike = dt;
                    if (dt > 33.3) d33++;
                    if (dt > 50.0) d50++;
                    if (dt > 100.0) d100++;

                    double dx = samples[i].X - samples[i - 1].X;
                    double dy = samples[i].Y - samples[i - 1].Y;
                    totalDisp += Math.Sqrt(dx * dx + dy * dy);
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

                int mouseCount = 0;
                int posCount = 0;
                if (form is FormMethodA_ModalDrag)
                {
                    mouseCount = ((FormMethodA_ModalDrag)form).WmMouseMoveCount;
                    posCount = ((FormMethodA_ModalDrag)form).SetWindowPosCount;
                }
                else if (form is FormMethodB_NonModalDrag)
                {
                    mouseCount = ((FormMethodB_NonModalDrag)form).WmMouseMoveCount;
                    posCount = ((FormMethodB_NonModalDrag)form).SetWindowPosCount;
                }

                ExperimentResult res = new ExperimentResult
                {
                    MethodName = methodName,
                    TargetDurationSec = durationSec,
                    ActualDurationSec = Math.Round(actualSec, 2),
                    WmMouseMoveCount = mouseCount,
                    WmMouseMoveRateHz = Math.Round(mouseCount / actualSec, 1),
                    SetWindowPosCount = posCount,
                    SetWindowPosRateHz = Math.Round(posCount / actualSec, 1),
                    PositionChangeCount = samples.Count,
                    CadenceHz = Math.Round(samples.Count / actualSec, 1),
                    MedianIntervalMs = Math.Round(median, 2),
                    P95IntervalMs = Math.Round(p95, 2),
                    MaxSpikeMs = Math.Round(maxSpike, 2),
                    MeanIntervalMs = Math.Round(mean, 2),
                    JitterStdDevMs = Math.Round(stdDev, 2),
                    DropsOver33ms = d33,
                    DropsOver50ms = d50,
                    DropsOver100ms = d100,
                    TotalDisplacementPx = Math.Round(totalDisp, 1),
                    CpuPercent = Math.Round(cpuPct, 2),
                    DegradationDetected = maxSpike > 100.0 || (intervals.Count > 0 && d33 * 100.0 / intervals.Count > 20.0)
                };

                Console.WriteLine("  [" + methodName + " - " + durationSec + "s] Result:");
                Console.WriteLine("    - WM_MOUSEMOVE: " + res.WmMouseMoveCount + " (" + res.WmMouseMoveRateHz + " Hz)");
                Console.WriteLine("    - SetWindowPos Calls: " + res.SetWindowPosCount + " (" + res.SetWindowPosRateHz + " Hz)");
                Console.WriteLine("    - Position Update Cadence: " + res.CadenceHz + " Hz (" + res.PositionChangeCount + " updates)");
                Console.WriteLine("    - Latency Interval: Median=" + res.MedianIntervalMs + " ms, P95=" + res.P95IntervalMs + " ms, Max=" + res.MaxSpikeMs + " ms");
                Console.WriteLine("    - Stutter Drops: >33ms: " + res.DropsOver33ms + " (" + (intervals.Count > 0 ? (d33 * 100.0 / intervals.Count).ToString("F1") : "0") + "%), >50ms: " + res.DropsOver50ms + ", >100ms: " + res.DropsOver100ms);
                Console.WriteLine("    - CPU: " + res.CpuPercent + "%");

                form.Close();
                Thread.Sleep(300);
                return res;
            };

            List<ExperimentResult> allResults = new List<ExperimentResult>();

            // Method A (HTCAPTION Modal Drag) across 2s, 10s, 20s
            allResults.Add(executeTest("Method A (HTCAPTION Modal Drag)", new FormMethodA_ModalDrag(400, 200, 390, 450), 2.0));
            allResults.Add(executeTest("Method A (HTCAPTION Modal Drag)", new FormMethodA_ModalDrag(400, 200, 390, 450), 10.0));
            allResults.Add(executeTest("Method A (HTCAPTION Modal Drag)", new FormMethodA_ModalDrag(400, 200, 390, 450), 20.0));

            // Method B (Native Non-Modal SetWindowPos Drag) across 2s, 10s, 20s
            allResults.Add(executeTest("Method B (Native Non-Modal Drag)", new FormMethodB_NonModalDrag(400, 200, 390, 450), 2.0));
            allResults.Add(executeTest("Method B (Native Non-Modal Drag)", new FormMethodB_NonModalDrag(400, 200, 390, 450), 10.0));
            allResults.Add(executeTest("Method B (Native Non-Modal Drag)", new FormMethodB_NonModalDrag(400, 200, 390, 450), 20.0));

            Console.WriteLine("\n======================================================================");
            Console.WriteLine("METHOD A VS METHOD B COMPARISON TABLE");
            Console.WriteLine("======================================================================");
            Console.WriteLine(string.Format("{0,-32} | {1,4} | {2,8} | {3,8} | {4,8} | {5,8} | {6,12} | {7,8}",
                "Drag Method", "Sec", "Cadence", "Median", "P95", "MaxSpike", ">33ms (<30f)", "MouseMove"));
            Console.WriteLine(new string('-', 105));

            foreach (var r in allResults)
            {
                Console.WriteLine(string.Format("{0,-32} | {1,3:F0}s | {2,6:F1}Hz | {3,6:F1}ms | {4,6:F1}ms | {5,6:F1}ms | {6,12} | {7,8}",
                    r.MethodName, r.TargetDurationSec, r.CadenceHz, r.MedianIntervalMs, r.P95IntervalMs, r.MaxSpikeMs, r.DropsOver33ms + " (" + (r.PositionChangeCount > 1 ? (r.DropsOver33ms * 100.0 / (r.PositionChangeCount - 1)).ToString("F0") : "0") + "%)", r.WmMouseMoveCount));
            }
        }
    }
}
