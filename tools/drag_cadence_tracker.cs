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

namespace NTE.DragCadence
{
    public struct WindowSample
    {
        public long Timestamp;
        public int X;
        public int Y;
    }

    public class CadenceReport
    {
        public string Name;
        public double DurationSec;
        public int TotalPositionChanges;
        public double CadenceHz;
        public double MeanIntervalMs;
        public double MinIntervalMs;
        public double MaxIntervalMs;
        public double JitterStdDevMs;
        public int DropsOver33ms; // < 30 FPS
        public int DropsOver50ms; // < 20 FPS
        public int DropsOver100ms; // Freeze
        public double TotalDisplacementPx;
    }

    public class DraggableForm : Form
    {
        public DraggableForm()
        {
            this.FormBorderStyle = FormBorderStyle.None;
            this.StartPosition = FormStartPosition.Manual;
            this.Location = new Point(400, 200);
            this.Size = new Size(390, 450);
            this.TopMost = true;
            this.BackColor = Color.FromArgb(15, 23, 42);
        }

        protected override void WndProc(ref Message m)
        {
            const int WM_NCHITTEST = 0x0084;
            const int HTCAPTION = 2;
            const int HTCLIENT = 1;

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

        [DllImport("user32.dll")]
        static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        [StructLayout(LayoutKind.Sequential)]
        public struct RECT
        {
            public int Left, Top, Right, Bottom;
        }

        [STAThread]
        static void Main(string[] args)
        {
            Console.WriteLine("======================================================================");
            Console.WriteLine("HIGH-PRECISION HWND POSITION UPDATE CADENCE BENCHMARK");
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

            Func<string, Form, Action<Form>, double, CadenceReport> runCadenceTest = (name, form, initAction, durationSec) =>
            {
                Console.WriteLine("\n----------------------------------------------------------------------");
                Console.WriteLine(">>> Testing Cadence for [" + name + "] (" + durationSec + "s)...");
                form.Show();
                if (initAction != null) initAction(form);

                SetForegroundWindow(form.Handle);
                Application.DoEvents();
                Thread.Sleep(300);

                IntPtr hWnd = form.Handle;
                List<WindowSample> rawSamples = new List<WindowSample>();
                bool isSampling = true;

                // High-resolution sampling thread (polls HWND position every 0.5ms)
                Thread samplerThread = new Thread(() =>
                {
                    RECT r;
                    int lastX = -999999;
                    int lastY = -999999;
                    while (isSampling)
                    {
                        if (GetWindowRect(hWnd, out r))
                        {
                            if (r.Left != lastX || r.Top != lastY)
                            {
                                rawSamples.Add(new WindowSample
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
                samplerThread.Priority = ThreadPriority.Highest;
                samplerThread.Start();

                int startX = form.Location.X + 60;
                int startY = form.Location.Y + 15;

                // Move mouse to drag header & trigger modal drag
                SetCursorPos(startX, startY);
                Thread.Sleep(50);
                mouse_event(2, 0, 0, 0, UIntPtr.Zero); // Left Down
                Thread.Sleep(50);

                Stopwatch sw = Stopwatch.StartNew();
                int dir = 1;
                int curX = startX;
                int curY = startY;
                double speed = 25.0; // 25 px/sec slow drag

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

                isSampling = false;
                samplerThread.Join(500);

                // Analyze recorded position changes
                List<double> intervals = new List<double>();
                double minInt = double.MaxValue;
                double maxInt = 0.0;
                double sumInt = 0.0;
                int drops33 = 0;
                int drops50 = 0;
                int drops100 = 0;
                double totalDisp = 0.0;

                for (int i = 1; i < rawSamples.Count; i++)
                {
                    double dtMs = (rawSamples[i].Timestamp - rawSamples[i - 1].Timestamp) * 1000.0 / (double)Stopwatch.Frequency;
                    intervals.Add(dtMs);
                    if (dtMs < minInt) minInt = dtMs;
                    if (dtMs > maxInt) maxInt = dtMs;
                    sumInt += dtMs;
                    if (dtMs > 33.3) drops33++;
                    if (dtMs > 50.0) drops50++;
                    if (dtMs > 100.0) drops100++;

                    double dx = rawSamples[i].X - rawSamples[i - 1].X;
                    double dy = rawSamples[i].Y - rawSamples[i - 1].Y;
                    totalDisp += Math.Sqrt(dx * dx + dy * dy);
                }

                double meanInt = intervals.Count > 0 ? sumInt / intervals.Count : 0.0;
                double variance = 0.0;
                foreach (var iv in intervals) variance += (iv - meanInt) * (iv - meanInt);
                double stdDev = intervals.Count > 0 ? Math.Sqrt(variance / intervals.Count) : 0.0;
                double actualSec = sw.Elapsed.TotalSeconds;

                CadenceReport rep = new CadenceReport
                {
                    Name = name,
                    DurationSec = Math.Round(actualSec, 2),
                    TotalPositionChanges = rawSamples.Count,
                    CadenceHz = Math.Round(rawSamples.Count / actualSec, 1),
                    MeanIntervalMs = Math.Round(meanInt, 2),
                    MinIntervalMs = Math.Round(minInt == double.MaxValue ? 0.0 : minInt, 2),
                    MaxIntervalMs = Math.Round(maxInt, 2),
                    JitterStdDevMs = Math.Round(stdDev, 2),
                    DropsOver33ms = drops33,
                    DropsOver50ms = drops50,
                    DropsOver100ms = drops100,
                    TotalDisplacementPx = Math.Round(totalDisp, 1)
                };

                Console.WriteLine("  [" + name + "] Results:");
                Console.WriteLine("    - Total Position Updates: " + rep.TotalPositionChanges + " (" + rep.CadenceHz + " Hz)");
                Console.WriteLine("    - Mean Interval: " + rep.MeanIntervalMs + " ms, Max Spike: " + rep.MaxIntervalMs + " ms (Jitter: " + rep.JitterStdDevMs + " ms)");
                Console.WriteLine("    - Drops: >33ms: " + rep.DropsOver33ms + " (" + (intervals.Count > 0 ? (drops33 * 100.0 / intervals.Count).ToString("F1") : "0") + "%), >50ms: " + rep.DropsOver50ms + ", >100ms: " + rep.DropsOver100ms);
                Console.WriteLine("    - Total Displacement: " + rep.TotalDisplacementPx + " px");

                form.Close();
                Thread.Sleep(300);
                return rep;
            };

            List<CadenceReport> reports = new List<CadenceReport>();

            // Group A: Native WinForms only
            Form formA = new DraggableForm();
            reports.Add(runCadenceTest("A. Native WinForms (10s)", formA, null, 10.0));

            // Group B: WinForms + DirectComposition static visual
            reports.Add(runCadenceTest("B. WinForms + DComp Static (10s)", new DirectCompositionHudForm(400, 200, 390, 450, true), null, 10.0));

            // Group C: WinForms + DComp WebView2 static HUD (No WS, No Vision)
            reports.Add(runCadenceTest("C. WinForms + DComp WebView2 Static (10s)", new DirectCompositionHudForm(400, 200, 390, 450, true), (f) =>
            {
                ((DirectCompositionHudForm)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 10.0));

            // Group D1: 8803ee3 (Baseline) (10s)
            reports.Add(runCadenceTest("D1. 8803ee3 Baseline (10s)", new DirectCompositionHudForm(400, 200, 390, 450, true), (f) =>
            {
                ((DirectCompositionHudForm)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 10.0));

            // Group D2: 0a2e525 (Render Suspension) (10s)
            reports.Add(runCadenceTest("D2. 0a2e525 Render Suspension (10s)", new DirectCompositionHudForm(400, 200, 390, 450, true), (f) =>
            {
                ((DirectCompositionHudForm)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 10.0));

            // 20s Comparison
            reports.Add(runCadenceTest("D1. 8803ee3 Baseline (20s)", new DirectCompositionHudForm(400, 200, 390, 450, true), (f) =>
            {
                ((DirectCompositionHudForm)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 20.0));

            reports.Add(runCadenceTest("D2. 0a2e525 Render Suspension (20s)", new DirectCompositionHudForm(400, 200, 390, 450, true), (f) =>
            {
                ((DirectCompositionHudForm)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 20.0));

            Console.WriteLine("\n======================================================================");
            Console.WriteLine("FINAL MULTI-LAYER CADENCE COMPARISON MATRIX");
            Console.WriteLine("======================================================================");
            Console.WriteLine(string.Format("{0,-38} | {1,8} | {2,8} | {3,8} | {4,8} | {5,12} | {6,8}",
                "Group / Configuration", "Cadence", "MeanInt", "MaxSpike", "Jitter", ">33ms (<30fps)", "TotalDisp"));
            Console.WriteLine(new string('-', 105));

            foreach (var r in reports)
            {
                Console.WriteLine(string.Format("{0,-38} | {1,6:F1}Hz | {2,6:F1}ms | {3,6:F1}ms | {4,6:F1}ms | {5,12} | {6,6:F0}px",
                    r.Name, r.CadenceHz, r.MeanIntervalMs, r.MaxIntervalMs, r.JitterStdDevMs, r.DropsOver33ms + " (" + (r.TotalPositionChanges > 1 ? (r.DropsOver33ms * 100.0 / (r.TotalPositionChanges - 1)).ToString("F0") : "0") + "%)", r.TotalDisplacementPx));
            }
        }
    }
}
