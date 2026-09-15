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

namespace NTE.HumanDragDiagnostic
{
    public enum DragMode
    {
        ModeA_HTCaptionModal = 0,
        ModeB1_NonModalWithSendMouseInput = 1,
        ModeB2_NonModalWithoutSendMouseInput = 2
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X; public int Y; }

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }

    public class SecondBucket
    {
        public int SecondIndex;
        public int CursorPosSamples;
        public int WmMouseMove;
        public int WmNcMouseMove;
        public int SendMouseInputCalls;
        public int SetWindowPosCalls;
        public int WmWindowPosChanged;
        public int DistinctPositions;
        public double MaxNoChangeGapMs;
    }

    public class SessionReport
    {
        public DragMode Mode;
        public string ModeName;
        public double DurationSec;
        public int TotalWmMouseMove;
        public int TotalWmNcMouseMove;
        public int TotalSendMouseInput;
        public int TotalSetWindowPos;
        public int TotalWindowPosChanged;
        public int TotalDistinctPositions;
        public double OverallCadenceHz;
        public double LongestNoChangeGapMs;
        public List<SecondBucket> PerSecondData = new List<SecondBucket>();
    }

    public class HumanDiagnosticForm : DirectCompositionHudForm
    {
        [DllImport("user32.dll")]
        static extern bool SetCapture(IntPtr hWnd);

        [DllImport("user32.dll")]
        static extern bool ReleaseCapture();

        [DllImport("user32.dll")]
        static extern bool GetCursorPos(out POINT lpPoint);

        [DllImport("user32.dll")]
        static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        [DllImport("user32.dll")]
        static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

        const uint SWP_NOSIZE = 0x0001;
        const uint SWP_NOZORDER = 0x0004;
        const uint SWP_NOACTIVATE = 0x0010;
        const uint SWP_ASYNCWINDOWPOS = 0x4000;

        public DragMode CurrentMode = DragMode.ModeA_HTCaptionModal;
        public bool IsRecording = false;
        public Stopwatch SessionWatch = new Stopwatch();

        // Real-time telemetry counters
        public int CountCursorSamples = 0;
        public int CountWmMouseMove = 0;
        public int CountWmNcMouseMove = 0;
        public int CountSendMouseInput = 0;
        public int CountSetWindowPos = 0;
        public int CountWmWindowPosChanged = 0;
        public int CountDistinctPositions = 0;

        private bool isManualDragging = false;
        private Point cursorStart;
        private Point windowStart;

        private int lastRecordedX = -999999;
        private int lastRecordedY = -999999;
        private long lastPositionChangeTick = 0;
        private double maxGapInCurrentSec = 0.0;
        private double globalMaxGapMs = 0.0;

        private int currentSecondIdx = 0;
        private List<SecondBucket> currentSessionBuckets = new List<SecondBucket>();
        private SecondBucket activeBucket = new SecondBucket();

        public event Action<SessionReport> OnSessionFinished;

        public HumanDiagnosticForm(int x, int y, int w, int h) : base(x, y, w, h, true)
        {
            this.KeyPreview = true;
            this.KeyDown += HumanDiagnosticForm_KeyDown;
        }

        private void HumanDiagnosticForm_KeyDown(object sender, KeyEventArgs e)
        {
            if (e.KeyCode == Keys.F1)
            {
                SetMode(DragMode.ModeA_HTCaptionModal);
            }
            else if (e.KeyCode == Keys.F2)
            {
                SetMode(DragMode.ModeB1_NonModalWithSendMouseInput);
            }
            else if (e.KeyCode == Keys.F3)
            {
                SetMode(DragMode.ModeB2_NonModalWithoutSendMouseInput);
            }
            else if (e.KeyCode == Keys.Space)
            {
                if (!IsRecording) Start20sSession();
            }
        }

        public void SetMode(DragMode mode)
        {
            CurrentMode = mode;
            Console.WriteLine("\n[MODE SWITCHED] -> " + GetModeName(mode));
            UpdateTitleBanner();
        }

        public string GetModeName(DragMode mode)
        {
            switch (mode)
            {
                case DragMode.ModeA_HTCaptionModal: return "Mode A: HTCAPTION Modal Drag";
                case DragMode.ModeB1_NonModalWithSendMouseInput: return "Mode B1: Non-Modal Drag WITH SendMouseInput";
                case DragMode.ModeB2_NonModalWithoutSendMouseInput: return "Mode B2: Non-Modal Drag WITHOUT SendMouseInput (Clean)";
                default: return mode.ToString();
            }
        }

        private void UpdateTitleBanner()
        {
            string banner = "HUD [" + GetModeName(CurrentMode) + "] " + (IsRecording ? "(RECORDING " + (20 - (int)SessionWatch.Elapsed.TotalSeconds) + "s)" : "[F1=A, F2=B1, F3=B2, SPACE=Record]");
            this.Text = banner;
        }

        public void Start20sSession()
        {
            IsRecording = true;
            currentSecondIdx = 1;
            currentSessionBuckets.Clear();
            activeBucket = new SecondBucket { SecondIndex = 1 };

            CountCursorSamples = 0;
            CountWmMouseMove = 0;
            CountWmNcMouseMove = 0;
            CountSendMouseInput = 0;
            CountSetWindowPos = 0;
            CountWmWindowPosChanged = 0;
            CountDistinctPositions = 0;
            globalMaxGapMs = 0.0;
            maxGapInCurrentSec = 0.0;
            lastPositionChangeTick = Stopwatch.GetTimestamp();

            RECT r;
            if (GetWindowRect(this.Handle, out r))
            {
                lastRecordedX = r.Left;
                lastRecordedY = r.Top;
            }

            SessionWatch.Restart();
            Console.WriteLine("\n======================================================================");
            Console.WriteLine(">>> STARTING 20-SECOND HUMAN DRAG RECORDING: " + GetModeName(CurrentMode));
            Console.WriteLine(">>> Please drag the title bar continuously with your real mouse now!");
            Console.WriteLine("======================================================================");
        }

        public void TickSamplingSecond(int sec)
        {
            if (!IsRecording) return;

            activeBucket.SecondIndex = sec;
            activeBucket.MaxNoChangeGapMs = Math.Round(maxGapInCurrentSec, 2);
            currentSessionBuckets.Add(activeBucket);

            Console.WriteLine(string.Format("  [Sec {0,2}/20] Updates: {1,3} | SetWinPos: {2,3} | MouseMove: {3,3} | SendMouseInput: {4,3} | GapMax: {5,5:F1}ms",
                sec, activeBucket.DistinctPositions, activeBucket.SetWindowPosCalls, activeBucket.WmMouseMove + activeBucket.WmNcMouseMove, activeBucket.SendMouseInputCalls, activeBucket.MaxNoChangeGapMs));

            activeBucket = new SecondBucket { SecondIndex = sec + 1 };
            maxGapInCurrentSec = 0.0;
            UpdateTitleBanner();

            if (sec >= 20)
            {
                FinishSession();
            }
        }

        private void FinishSession()
        {
            IsRecording = false;
            SessionWatch.Stop();

            double actualSec = SessionWatch.Elapsed.TotalSeconds;
            SessionReport rep = new SessionReport
            {
                Mode = CurrentMode,
                ModeName = GetModeName(CurrentMode),
                DurationSec = Math.Round(actualSec, 2),
                TotalWmMouseMove = CountWmMouseMove,
                TotalWmNcMouseMove = CountWmNcMouseMove,
                TotalSendMouseInput = CountSendMouseInput,
                TotalSetWindowPos = CountSetWindowPos,
                TotalWindowPosChanged = CountWmWindowPosChanged,
                TotalDistinctPositions = CountDistinctPositions,
                OverallCadenceHz = Math.Round(CountDistinctPositions / actualSec, 1),
                LongestNoChangeGapMs = Math.Round(globalMaxGapMs, 2),
                PerSecondData = new List<SecondBucket>(currentSessionBuckets)
            };

            Console.WriteLine("\n======================================================================");
            Console.WriteLine(">>> 20S SESSION COMPLETED: " + rep.ModeName);
            Console.WriteLine("    - Total Distinct Positions: " + rep.TotalDistinctPositions + " (Overall " + rep.OverallCadenceHz + " Hz)");
            Console.WriteLine("    - SetWindowPos Calls: " + rep.TotalSetWindowPos);
            Console.WriteLine("    - WM_MOUSEMOVE + NC: " + (rep.TotalWmMouseMove + rep.TotalWmNcMouseMove));
            Console.WriteLine("    - SendMouseInput Calls: " + rep.TotalSendMouseInput);
            Console.WriteLine("    - Longest Gap: " + rep.LongestNoChangeGapMs + " ms");
            Console.WriteLine("======================================================================");

            if (OnSessionFinished != null) OnSessionFinished(rep);
            UpdateTitleBanner();
        }

        protected override void WndProc(ref Message m)
        {
            const int WM_LBUTTONDOWN = 0x0201;
            const int WM_MOUSEMOVE = 0x0200;
            const int WM_LBUTTONUP = 0x0202;
            const int WM_LBUTTONDBLCLK = 0x0203;
            const int WM_RBUTTONDOWN = 0x0204;
            const int WM_RBUTTONUP = 0x0205;
            const int WM_RBUTTONDBLCLK = 0x0206;
            const int WM_MBUTTONDOWN = 0x0207;
            const int WM_MBUTTONUP = 0x0208;
            const int WM_MOUSEWHEEL = 0x020A;
            const int WM_MOUSELEAVE = 0x02A3;

            const int WM_NCMOUSEMOVE = 0x00A0;
            const int WM_NCLBUTTONDOWN = 0x00A1;
            const int WM_NCHITTEST = 0x0084;
            const int WM_WINDOWPOSCHANGED = 0x0047;
            const int HTCAPTION = 2;
            const int HTCLIENT = 1;

            if (m.Msg == WM_MOUSEMOVE)
            {
                CountWmMouseMove++;
                if (IsRecording) activeBucket.WmMouseMove++;
            }
            else if (m.Msg == WM_NCMOUSEMOVE)
            {
                CountWmNcMouseMove++;
                if (IsRecording) activeBucket.WmNcMouseMove++;
            }
            else if (m.Msg == WM_WINDOWPOSCHANGED)
            {
                CountWmWindowPosChanged++;
                if (IsRecording)
                {
                    activeBucket.WmWindowPosChanged++;

                    RECT r;
                    if (GetWindowRect(this.Handle, out r))
                    {
                        if (r.Left != lastRecordedX || r.Top != lastRecordedY)
                        {
                            CountDistinctPositions++;
                            activeBucket.DistinctPositions++;

                            long nowTick = Stopwatch.GetTimestamp();
                            double gapMs = (nowTick - lastPositionChangeTick) * 1000.0 / (double)Stopwatch.Frequency;
                            if (gapMs > maxGapInCurrentSec) maxGapInCurrentSec = gapMs;
                            if (gapMs > globalMaxGapMs) globalMaxGapMs = gapMs;

                            lastPositionChangeTick = nowTick;
                            lastRecordedX = r.Left;
                            lastRecordedY = r.Top;
                        }
                    }
                }
            }

            // ---------------------------------------------------------------
            // MODE A: Standard HTCAPTION Modal Drag
            // ---------------------------------------------------------------
            if (CurrentMode == DragMode.ModeA_HTCaptionModal)
            {
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

                // Normal WebView2 mouse forwarding
                ForwardMouseToWebView(ref m);
                base.WndProc(ref m);
                return;
            }

            // ---------------------------------------------------------------
            // MODE B1 & B2: Native Non-Modal Manual Drag
            // ---------------------------------------------------------------
            if (CurrentMode == DragMode.ModeB1_NonModalWithSendMouseInput || CurrentMode == DragMode.ModeB2_NonModalWithoutSendMouseInput)
            {
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
                        isManualDragging = true;
                        SetCapture(this.Handle);
                        cursorStart = new Point(screenX, screenY);
                        windowStart = this.Location;

                        if (CurrentMode == DragMode.ModeB1_NonModalWithSendMouseInput)
                        {
                            ForwardMouseToWebView(ref m);
                        }
                        return;
                    }
                }
                else if (m.Msg == WM_MOUSEMOVE)
                {
                    if (isManualDragging)
                    {
                        POINT curPos;
                        GetCursorPos(out curPos);
                        int newX = windowStart.X + (curPos.X - cursorStart.X);
                        int newY = windowStart.Y + (curPos.Y - cursorStart.Y);

                        SetWindowPos(this.Handle, IntPtr.Zero, newX, newY, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS);
                        CountSetWindowPos++;
                        if (IsRecording) activeBucket.SetWindowPosCalls++;

                        if (CurrentMode == DragMode.ModeB1_NonModalWithSendMouseInput)
                        {
                            ForwardMouseToWebView(ref m);
                        }
                        // Mode B2 strictly suppresses ForwardMouseToWebView
                        return;
                    }
                }
                else if (m.Msg == WM_LBUTTONUP)
                {
                    if (isManualDragging)
                    {
                        isManualDragging = false;
                        ReleaseCapture();

                        if (CurrentMode == DragMode.ModeB1_NonModalWithSendMouseInput)
                        {
                            ForwardMouseToWebView(ref m);
                        }
                        return;
                    }
                }

                // Forward other mouse messages when not dragging
                ForwardMouseToWebView(ref m);
                base.WndProc(ref m);
                return;
            }

            base.WndProc(ref m);
        }

        private void ForwardMouseToWebView(ref Message m)
        {
            if (this.CompController == null) return;

            const int WM_MOUSEMOVE = 0x0200;
            const int WM_LBUTTONDOWN = 0x0201;
            const int WM_LBUTTONUP = 0x0202;
            const int WM_LBUTTONDBLCLK = 0x0203;
            const int WM_RBUTTONDOWN = 0x0204;
            const int WM_RBUTTONUP = 0x0205;
            const int WM_RBUTTONDBLCLK = 0x0206;
            const int WM_MBUTTONDOWN = 0x0207;
            const int WM_MBUTTONUP = 0x0208;
            const int WM_MOUSEWHEEL = 0x020A;
            const int WM_MOUSELEAVE = 0x02A3;

            CoreWebView2MouseEventKind kind = (CoreWebView2MouseEventKind)(-1);
            switch (m.Msg)
            {
                case WM_MOUSEMOVE: kind = CoreWebView2MouseEventKind.Move; break;
                case WM_LBUTTONDOWN: kind = CoreWebView2MouseEventKind.LeftButtonDown; break;
                case WM_LBUTTONUP: kind = CoreWebView2MouseEventKind.LeftButtonUp; break;
                case WM_LBUTTONDBLCLK: kind = CoreWebView2MouseEventKind.LeftButtonDoubleClick; break;
                case WM_RBUTTONDOWN: kind = CoreWebView2MouseEventKind.RightButtonDown; break;
                case WM_RBUTTONUP: kind = CoreWebView2MouseEventKind.RightButtonUp; break;
                case WM_RBUTTONDBLCLK: kind = CoreWebView2MouseEventKind.RightButtonDoubleClick; break;
                case WM_MBUTTONDOWN: kind = CoreWebView2MouseEventKind.MiddleButtonDown; break;
                case WM_MBUTTONUP: kind = CoreWebView2MouseEventKind.MiddleButtonUp; break;
                case WM_MOUSEWHEEL: kind = CoreWebView2MouseEventKind.Wheel; break;
                case WM_MOUSELEAVE: kind = CoreWebView2MouseEventKind.Leave; break;
            }

            if ((int)kind != -1)
            {
                int x = unchecked((short)(m.LParam.ToInt64() & 0xFFFF));
                int y = unchecked((short)((m.LParam.ToInt64() >> 16) & 0xFFFF));
                if (m.Msg == WM_MOUSEWHEEL)
                {
                    Point ptClient = this.PointToClient(new Point(x, y));
                    x = ptClient.X;
                    y = ptClient.Y;
                }

                uint mouseData = (m.Msg == WM_MOUSEWHEEL) ? unchecked((uint)((m.WParam.ToInt64() >> 16) & 0xFFFF)) : 0;
                CoreWebView2MouseEventVirtualKeys keys = CoreWebView2MouseEventVirtualKeys.None;
                long w = m.WParam.ToInt64() & 0xFFFF;
                if ((w & 0x0001) != 0) keys |= CoreWebView2MouseEventVirtualKeys.LeftButton;
                if ((w & 0x0002) != 0) keys |= CoreWebView2MouseEventVirtualKeys.RightButton;
                if ((w & 0x0004) != 0) keys |= CoreWebView2MouseEventVirtualKeys.Shift;
                if ((w & 0x0008) != 0) keys |= CoreWebView2MouseEventVirtualKeys.Control;
                if ((w & 0x0010) != 0) keys |= CoreWebView2MouseEventVirtualKeys.MiddleButton;

                try
                {
                    CountSendMouseInput++;
                    if (IsRecording) activeBucket.SendMouseInputCalls++;
                    this.CompController.SendMouseInput(kind, keys, mouseData, new Point(x, y));
                }
                catch { }
            }
        }
    }

    class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            Console.WriteLine("======================================================================");
            Console.WriteLine("HUMAN REAL-MOUSE DRAG DIAGNOSTIC RUNNER");
            Console.WriteLine("======================================================================");
            Console.WriteLine("Instructions:");
            Console.WriteLine("  1. Press [F1] for Mode A (HTCAPTION Modal Drag)");
            Console.WriteLine("  2. Press [F2] for Mode B1 (Non-Modal WITH SendMouseInput)");
            Console.WriteLine("  3. Press [F3] for Mode B2 (Non-Modal WITHOUT SendMouseInput)");
            Console.WriteLine("  4. Press [SPACE] to start a 20-second real-mouse drag recording session.");
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

            HumanDiagnosticForm form = new HumanDiagnosticForm(400, 200, 390, 450);
            form.Show();
            form.InitializeComposition(env, htmlPath);

            List<SessionReport> allReports = new List<SessionReport>();
            form.OnSessionFinished += (rep) =>
            {
                allReports.Add(rep);
                string jsonPath = Path.Combine(projectRoot, @"tools\human_drag_diagnostic_report.json");
                // Serialize simple JSON
                List<string> repJsonList = new List<string>();
                foreach (var r in allReports)
                {
                    List<string> bJsonList = new List<string>();
                    foreach (var b in r.PerSecondData)
                    {
                        bJsonList.Add(string.Format("{{\"sec\":{0},\"updates\":{1},\"setPos\":{2},\"mouseMove\":{3},\"sendMouseInput\":{4},\"maxGapMs\":{5}}}",
                            b.SecondIndex, b.DistinctPositions, b.SetWindowPosCalls, b.WmMouseMove + b.WmNcMouseMove, b.SendMouseInputCalls, b.MaxNoChangeGapMs));
                    }
                    repJsonList.Add(string.Format("{{\"mode\":\"{0}\",\"cadenceHz\":{1},\"distinctPositions\":{2},\"longestGapMs\":{3},\"seconds\":[{4}]}}",
                        r.ModeName, r.OverallCadenceHz, r.TotalDistinctPositions, r.LongestNoChangeGapMs, string.Join(",", bJsonList)));
                }
                File.WriteAllText(jsonPath, "[" + string.Join(",", repJsonList) + "]");
                Console.WriteLine("[SAVED REPORT] -> " + jsonPath);
            };

            // Global hotkey polling & second timer loop
            int lastSecond = 0;
            Console.WriteLine("\n[READY] Listening for input (F1=Mode A, F2=Mode B1, F3=Mode B2, SPACE/ENTER=Start 20s recording)...");

            while (!form.IsDisposed)
            {
                Application.DoEvents();

                // 1. Check Global Hotkeys (works even if WebView2 has keyboard focus)
                short f1State = GetAsyncKeyState(0x70); // VK_F1
                short f2State = GetAsyncKeyState(0x71); // VK_F2
                short f3State = GetAsyncKeyState(0x72); // VK_F3
                short spaceState = GetAsyncKeyState(0x20); // VK_SPACE
                short enterState = GetAsyncKeyState(0x0D); // VK_RETURN

                if ((f1State & 1) != 0 || (f1State & 0x8000) != 0 && !form.IsRecording)
                {
                    if (form.CurrentMode != DragMode.ModeA_HTCaptionModal) form.SetMode(DragMode.ModeA_HTCaptionModal);
                }
                else if ((f2State & 1) != 0 || (f2State & 0x8000) != 0 && !form.IsRecording)
                {
                    if (form.CurrentMode != DragMode.ModeB1_NonModalWithSendMouseInput) form.SetMode(DragMode.ModeB1_NonModalWithSendMouseInput);
                }
                else if ((f3State & 1) != 0 || (f3State & 0x8000) != 0 && !form.IsRecording)
                {
                    if (form.CurrentMode != DragMode.ModeB2_NonModalWithoutSendMouseInput) form.SetMode(DragMode.ModeB2_NonModalWithoutSendMouseInput);
                }

                if (((spaceState & 1) != 0 || (enterState & 1) != 0) && !form.IsRecording)
                {
                    form.Start20sSession();
                }

                // 2. Check Console Key
                if (Console.KeyAvailable)
                {
                    var key = Console.ReadKey(true);
                    if (key.Key == ConsoleKey.F1) form.SetMode(DragMode.ModeA_HTCaptionModal);
                    else if (key.Key == ConsoleKey.F2) form.SetMode(DragMode.ModeB1_NonModalWithSendMouseInput);
                    else if (key.Key == ConsoleKey.F3) form.SetMode(DragMode.ModeB2_NonModalWithoutSendMouseInput);
                    else if ((key.Key == ConsoleKey.Spacebar || key.Key == ConsoleKey.Enter) && !form.IsRecording)
                    {
                        form.Start20sSession();
                    }
                }

                // 3. Tick 1s buckets
                if (form.IsRecording)
                {
                    int currentSec = (int)form.SessionWatch.Elapsed.TotalSeconds + 1;
                    if (currentSec > lastSecond && currentSec <= 20)
                    {
                        form.TickSamplingSecond(currentSec);
                        lastSecond = currentSec;
                    }
                }
                else
                {
                    lastSecond = 0;
                }
                Thread.Sleep(5);
            }
        }

        [DllImport("user32.dll")]
        static extern short GetAsyncKeyState(int vKey);
    }
}
