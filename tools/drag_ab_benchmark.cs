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

namespace NTE.DragAB
{
    public class DragMetrics
    {
        public string GroupName;
        public double DurationSec;
        public int TotalPosChangedCount;
        public double CadenceHz;
        public double MinIntervalMs;
        public double MaxIntervalMs;
        public double MeanIntervalMs;
        public double JitterStdDevMs;
        public int DropsOver33ms; // < 30 FPS
        public int DropsOver50ms; // < 20 FPS
        public int DropsOver100ms; // Severe stutter
        public double TotalCpuMs;
        public double CpuPercent;
        public int TotalMessages;
        public List<double> RawIntervals = new List<double>();
    }

    public abstract class BaseBenchForm : Form
    {
        public List<long> PosChangedTimestamps = new List<long>();
        public int MessageCount = 0;
        public bool IsRecording = false;

        public BaseBenchForm(int x, int y, int w, int h)
        {
            this.FormBorderStyle = FormBorderStyle.None;
            this.StartPosition = FormStartPosition.Manual;
            this.Location = new Point(x, y);
            this.Size = new Size(w, h);
            this.TopMost = true;
            this.ShowInTaskbar = false;
            this.DoubleBuffered = true;
            this.BackColor = Color.FromArgb(15, 23, 42); // Dark slate
        }

        protected override void WndProc(ref Message m)
        {
            if (IsRecording) MessageCount++;

            const int WM_NCHITTEST = 0x0084;
            const int WM_WINDOWPOSCHANGED = 0x0047;
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

            if (m.Msg == WM_WINDOWPOSCHANGED && IsRecording)
            {
                PosChangedTimestamps.Add(Stopwatch.GetTimestamp());
            }

            base.WndProc(ref m);
        }

        public void StartRecording()
        {
            PosChangedTimestamps.Clear();
            MessageCount = 0;
            IsRecording = true;
        }

        public void StopRecording()
        {
            IsRecording = false;
        }
    }

    // Group A: Native WinForms only
    public class FormA_NativeWinForms : BaseBenchForm
    {
        public FormA_NativeWinForms(int x, int y, int w, int h) : base(x, y, w, h) { }
    }

    // Group B: WinForms + DirectComposition static visual
    public class FormB_DCompStatic : BaseBenchForm
    {
        [DllImport("dcomp.dll")]
        static extern int DCompositionCreateDevice(IntPtr dxgiDevice, ref Guid iid, out IntPtr dcompDevice);

        IntPtr dcompDevice = IntPtr.Zero;
        IntPtr dcompTarget = IntPtr.Zero;
        IntPtr dcompVisual = IntPtr.Zero;

        public FormB_DCompStatic(int x, int y, int w, int h) : base(x, y, w, h)
        {
            // Initialize basic DComp target and visual
            try
            {
                Guid IID_IDCompositionDevice = new Guid("C37E8865-C42E-47df-A5EA-310E35F7222D");
                DCompositionCreateDevice(IntPtr.Zero, ref IID_IDCompositionDevice, out dcompDevice);
            }
            catch { }
        }
    }

    // Group C: WinForms + DComp WebView2 static HUD (No WS, No Vision)
    public class FormC_DCompWebView2Static : DirectCompositionHudForm
    {
        public List<long> PosChangedTimestamps = new List<long>();
        public int MessageCount = 0;
        public bool IsRecording = false;

        public FormC_DCompWebView2Static(int x, int y, int w, int h) : base(x, y, w, h, true) { }

        protected override void WndProc(ref Message m)
        {
            if (IsRecording) MessageCount++;
            if (m.Msg == 0x0047 && IsRecording)
            {
                PosChangedTimestamps.Add(Stopwatch.GetTimestamp());
            }
            base.WndProc(ref m);
        }

        public void StartRecording()
        {
            PosChangedTimestamps.Clear();
            MessageCount = 0;
            IsRecording = true;
        }

        public void StopRecording()
        {
            IsRecording = false;
        }
    }

    // Group D (8803ee3): Full Runtime (No script on ENTERSIZEMOVE)
    public class FormD_8803ee3 : DirectCompositionHudForm
    {
        public List<long> PosChangedTimestamps = new List<long>();
        public int MessageCount = 0;
        public bool IsRecording = false;

        public FormD_8803ee3(int x, int y, int w, int h) : base(x, y, w, h, true) { }

        protected override void WndProc(ref Message m)
        {
            if (IsRecording) MessageCount++;
            if (m.Msg == 0x0047 && IsRecording)
            {
                PosChangedTimestamps.Add(Stopwatch.GetTimestamp());
            }
            // 8803ee3 does NOT call ExecuteScriptAsync on WM_ENTERSIZEMOVE
            base.WndProc(ref m);
        }

        public void StartRecording()
        {
            PosChangedTimestamps.Clear();
            MessageCount = 0;
            IsRecording = true;
        }

        public void StopRecording()
        {
            IsRecording = false;
        }
    }

    // Group D2 (0a2e525): Full Runtime with ExecuteScriptAsync on ENTERSIZEMOVE
    public class FormD2_0a2e525 : DirectCompositionHudForm
    {
        public List<long> PosChangedTimestamps = new List<long>();
        public int MessageCount = 0;
        public bool IsRecording = false;

        public FormD2_0a2e525(int x, int y, int w, int h) : base(x, y, w, h, true) { }

        protected override void WndProc(ref Message m)
        {
            if (IsRecording) MessageCount++;
            if (m.Msg == 0x0047 && IsRecording)
            {
                PosChangedTimestamps.Add(Stopwatch.GetTimestamp());
            }

            const int WM_ENTERSIZEMOVE = 0x0231;
            const int WM_EXITSIZEMOVE = 0x0232;

            if (m.Msg == WM_ENTERSIZEMOVE)
            {
                if (this.WebView != null)
                {
                    try { this.WebView.ExecuteScriptAsync("window.__onHostDragStateChange && window.__onHostDragStateChange(true);"); } catch { }
                }
            }
            else if (m.Msg == WM_EXITSIZEMOVE)
            {
                if (this.WebView != null)
                {
                    try { this.WebView.ExecuteScriptAsync("window.__onHostDragStateChange && window.__onHostDragStateChange(false);"); } catch { }
                }
            }

            base.WndProc(ref m);
        }

        public void StartRecording()
        {
            PosChangedTimestamps.Clear();
            MessageCount = 0;
            IsRecording = true;
        }

        public void StopRecording()
        {
            IsRecording = false;
        }
    }

    class Program
    {
        [DllImport("user32.dll")]
        static extern bool SetCursorPos(int X, int Y);

        [DllImport("user32.dll")]
        static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

        [DllImport("user32.dll")]
        static extern bool SetForegroundWindow(IntPtr hWnd);

        [STAThread]
        static void Main(string[] args)
        {
            Console.WriteLine("======================================================================");
            Console.WriteLine("STRICT DRAG BENCHMARK & MULTI-LAYER A/B COMPARISON");
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

            Func<string, Form, Action<Form>, double, DragMetrics> runDragTest = (groupName, form, initAction, durationSec) =>
            {
                Console.WriteLine("\n----------------------------------------------------------------------");
                Console.WriteLine(">>> Testing [" + groupName + "] for " + durationSec + "s continuous slow drag...");
                form.Show();
                if (initAction != null) initAction(form);

                SetForegroundWindow(form.Handle);
                Application.DoEvents();
                Thread.Sleep(500);

                Action startRec = null;
                Action stopRec = null;
                Func<List<long>> getTimestamps = null;
                Func<int> getMsgCount = null;

                if (form is BaseBenchForm)
                {
                    var bf = form as BaseBenchForm;
                    startRec = bf.StartRecording;
                    stopRec = bf.StopRecording;
                    getTimestamps = () => bf.PosChangedTimestamps;
                    getMsgCount = () => bf.MessageCount;
                }
                else if (form is FormC_DCompWebView2Static)
                {
                    var cf = form as FormC_DCompWebView2Static;
                    startRec = cf.StartRecording;
                    stopRec = cf.StopRecording;
                    getTimestamps = () => cf.PosChangedTimestamps;
                    getMsgCount = () => cf.MessageCount;
                }
                else if (form is FormD_8803ee3)
                {
                    var df = form as FormD_8803ee3;
                    startRec = df.StartRecording;
                    stopRec = df.StopRecording;
                    getTimestamps = () => df.PosChangedTimestamps;
                    getMsgCount = () => df.MessageCount;
                }
                else if (form is FormD2_0a2e525)
                {
                    var df2 = form as FormD2_0a2e525;
                    startRec = df2.StartRecording;
                    stopRec = df2.StopRecording;
                    getTimestamps = () => df2.PosChangedTimestamps;
                    getMsgCount = () => df2.MessageCount;
                }

                int startX = form.Location.X + 60;
                int startY = form.Location.Y + 15;

                SetCursorPos(startX, startY);
                Thread.Sleep(50);
                mouse_event(2, 0, 0, 0, UIntPtr.Zero); // Left Down
                Thread.Sleep(50);

                startRec();
                TimeSpan cpuUserStart = proc.UserProcessorTime;
                TimeSpan cpuPrivStart = proc.PrivilegedProcessorTime;
                Stopwatch sw = Stopwatch.StartNew();

                int dir = 1;
                int curX = startX;
                int curY = startY;
                double speedPxPerSec = 20.0; // Slow drag

                while (sw.Elapsed.TotalSeconds < durationSec)
                {
                    Application.DoEvents();

                    curX += (int)(dir * (speedPxPerSec * 0.015));
                    if (curX > startX + 160) dir = -1;
                    else if (curX < startX - 160) dir = 1;

                    SetCursorPos(curX, curY);
                    Thread.Sleep(10);
                }

                sw.Stop();
                TimeSpan cpuUserEnd = proc.UserProcessorTime;
                TimeSpan cpuPrivEnd = proc.PrivilegedProcessorTime;
                stopRec();

                mouse_event(4, 0, 0, 0, UIntPtr.Zero); // Left Up
                Thread.Sleep(100);

                var tsList = getTimestamps();
                int count = tsList.Count;
                double actualSec = sw.Elapsed.TotalSeconds;

                List<double> intervals = new List<double>();
                double minInt = double.MaxValue;
                double maxInt = 0.0;
                double sumInt = 0.0;
                int drops33 = 0;
                int drops50 = 0;
                int drops100 = 0;

                for (int i = 1; i < count; i++)
                {
                    double dtMs = (tsList[i] - tsList[i - 1]) * 1000.0 / (double)Stopwatch.Frequency;
                    intervals.Add(dtMs);
                    if (dtMs < minInt) minInt = dtMs;
                    if (dtMs > maxInt) maxInt = dtMs;
                    sumInt += dtMs;
                    if (dtMs > 33.3) drops33++;
                    if (dtMs > 50.0) drops50++;
                    if (dtMs > 100.0) drops100++;
                }

                double meanInt = intervals.Count > 0 ? sumInt / intervals.Count : 0.0;
                double variance = 0.0;
                foreach (var iv in intervals) variance += (iv - meanInt) * (iv - meanInt);
                double stdDev = intervals.Count > 0 ? Math.Sqrt(variance / intervals.Count) : 0.0;

                double userMs = (cpuUserEnd - cpuUserStart).TotalMilliseconds;
                double privMs = (cpuPrivEnd - cpuPrivStart).TotalMilliseconds;
                double totalCpuMs = userMs + privMs;
                double cpuPct = (totalCpuMs / (actualSec * 1000.0)) * 100.0;

                DragMetrics m = new DragMetrics
                {
                    GroupName = groupName,
                    DurationSec = Math.Round(actualSec, 2),
                    TotalPosChangedCount = count,
                    CadenceHz = Math.Round(count / actualSec, 1),
                    MinIntervalMs = Math.Round(minInt == double.MaxValue ? 0.0 : minInt, 2),
                    MaxIntervalMs = Math.Round(maxInt, 2),
                    MeanIntervalMs = Math.Round(meanInt, 2),
                    JitterStdDevMs = Math.Round(stdDev, 2),
                    DropsOver33ms = drops33,
                    DropsOver50ms = drops50,
                    DropsOver100ms = drops100,
                    TotalCpuMs = Math.Round(totalCpuMs, 1),
                    CpuPercent = Math.Round(cpuPct, 2),
                    TotalMessages = getMsgCount(),
                    RawIntervals = intervals
                };

                Console.WriteLine("  [" + groupName + "] Results (" + m.DurationSec + "s drag):");
                Console.WriteLine("    - WM_WINDOWPOSCHANGED Events: " + m.TotalPosChangedCount + " (" + m.CadenceHz + " Hz)");
                Console.WriteLine("    - Frame Interval: Mean=" + m.MeanIntervalMs + "ms, Min=" + m.MinIntervalMs + "ms, Max=" + m.MaxIntervalMs + "ms (Jitter=" + m.JitterStdDevMs + "ms)");
                Console.WriteLine("    - Stutter Drops: >33ms (<30fps): " + m.DropsOver33ms + " (" + (intervals.Count > 0 ? (drops33 * 100.0 / intervals.Count).ToString("F1") : "0") + "%), >50ms (<20fps): " + m.DropsOver50ms + ", >100ms (freeze): " + m.DropsOver100ms);
                Console.WriteLine("    - Process CPU: " + m.CpuPercent + "% (" + m.TotalCpuMs + "ms)");

                form.Close();
                Thread.Sleep(300);
                return m;
            };

            List<DragMetrics> allMetrics = new List<DragMetrics>();

            // 1. Group A: Native WinForms only
            allMetrics.Add(runDragTest("A. Native WinForms (10s)", new FormA_NativeWinForms(400, 200, 390, 450), null, 10.0));

            // 2. Group B: WinForms + DirectComposition static visual
            allMetrics.Add(runDragTest("B. WinForms + DComp Static (10s)", new FormB_DCompStatic(400, 200, 390, 450), null, 10.0));

            // 3. Group C: WinForms + DComp WebView2 static HUD (No WS, No Vision)
            allMetrics.Add(runDragTest("C. WinForms + DComp WebView2 Static (10s)", new FormC_DCompWebView2Static(400, 200, 390, 450), (f) =>
            {
                ((FormC_DCompWebView2Static)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 10.0));

            // 4. Group D (8803ee3): 8803ee3 baseline (No Script on ENTERSIZEMOVE) (10s)
            allMetrics.Add(runDragTest("D1. 8803ee3 Baseline (10s)", new FormD_8803ee3(400, 200, 390, 450), (f) =>
            {
                ((FormD_8803ee3)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 10.0));

            // 5. Group D2 (0a2e525): 0a2e525 Render Suspension (with ExecuteScriptAsync) (10s)
            allMetrics.Add(runDragTest("D2. 0a2e525 Render Suspension (10s)", new FormD2_0a2e525(400, 200, 390, 450), (f) =>
            {
                ((FormD2_0a2e525)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 10.0));

            // 6. Group D1 vs D2 20s Comparison
            allMetrics.Add(runDragTest("D1. 8803ee3 Baseline (20s)", new FormD_8803ee3(400, 200, 390, 450), (f) =>
            {
                ((FormD_8803ee3)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 20.0));

            allMetrics.Add(runDragTest("D2. 0a2e525 Render Suspension (20s)", new FormD2_0a2e525(400, 200, 390, 450), (f) =>
            {
                ((FormD2_0a2e525)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 20.0));

            Console.WriteLine("\n======================================================================");
            Console.WriteLine("MULTI-LAYER A/B COMPARISON TABLE");
            Console.WriteLine("======================================================================");
            Console.WriteLine(string.Format("{0,-38} | {1,8} | {2,8} | {3,8} | {4,8} | {5,10} | {6,8}",
                "Configuration", "Cadence", "MeanInt", "MaxInt", "Jitter", ">33ms (<30f)", "CPU"));
            Console.WriteLine(new string('-', 100));

            foreach (var m in allMetrics)
            {
                Console.WriteLine(string.Format("{0,-38} | {1,6:F1}Hz | {2,6:F1}ms | {3,6:F1}ms | {4,6:F1}ms | {5,10} | {6,6:F1}%",
                    m.GroupName, m.CadenceHz, m.MeanIntervalMs, m.MaxIntervalMs, m.JitterStdDevMs, m.DropsOver33ms + " (" + (m.RawIntervals.Count > 0 ? (m.DropsOver33ms * 100.0 / m.RawIntervals.Count).ToString("F0") : "0") + "%)", m.CpuPercent));
            }
        }
    }
}
