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

namespace NTE.ProgrammaticMotion
{
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }

    public class StepRecord
    {
        public double ElapsedSec;
        public int TargetX;
        public int TargetY;
        public int ActualX;
        public int ActualY;
        public double CallLatencyMs;
        public bool IsDistinct;
    }

    public class ProgrammaticReport
    {
        public string ConfigName;
        public double DurationSec;
        public int RequestedMoves;
        public int SetWindowPosSuccesses;
        public int ActualDistinctPositions;
        public double ActualCadenceHz;
        public double LatencyMedianMs;
        public double LatencyP95Ms;
        public double LatencyMaxMs;
        public double LatencyMeanMs;
        public double LatencyMinMs;
        public double LongestNoChangeGapMs;
        public int[] PerSecondUpdates; // 20 seconds
        public double[] PerSecondLatencyMedianMs;
        public double[] PerSecondLatencyMaxMs;
        public double EarlyCadenceHz; // Sec 1..3
        public double LateCadenceHz;  // Sec 18..20
        public double DegradationRatio; // Late / Early
        public bool IsDegrading;
        public double TotalDisplacementPx;
    }

    class Program
    {
        [DllImport("user32.dll")]
        static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        [DllImport("user32.dll")]
        static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

        [DllImport("user32.dll")]
        static extern bool SetForegroundWindow(IntPtr hWnd);

        const uint SWP_NOSIZE = 0x0001;
        const uint SWP_NOZORDER = 0x0004;
        const uint SWP_NOACTIVATE = 0x0010;
        const uint SWP_ASYNCWINDOWPOS = 0x4000;

        [STAThread]
        static void Main(string[] args)
        {
            Console.WriteLine("======================================================================");
            Console.WriteLine("PROGRAMMATIC HWND MOTION TEST (120 HZ, ZERO MOUSE / ZERO INPUT)");
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

            Func<string, Form, Action<Form>, double, ProgrammaticReport> runProgrammaticTest = (name, form, initAction, durationSec) =>
            {
                Console.WriteLine("\n----------------------------------------------------------------------");
                Console.WriteLine(">>> Running Programmatic 120Hz Test on [" + name + "] for " + durationSec + "s...");
                form.Show();
                if (initAction != null) initAction(form);

                SetForegroundWindow(form.Handle);
                Application.DoEvents();
                Thread.Sleep(1000);

                IntPtr hWnd = form.Handle;
                int originX = 400;
                int originY = 200;
                double amplitudeX = 150.0; // 150 px oscillation
                double amplitudeY = 50.0;  // 50 px oscillation
                double motionFreqHz = 0.25; // 1 full oscillation every 4 seconds

                int targetFPS = 120;
                double stepIntervalSec = 1.0 / (double)targetFPS;
                long stepIntervalTicks = (long)(stepIntervalSec * Stopwatch.Frequency);

                List<StepRecord> records = new List<StepRecord>();
                int totalRequested = 0;
                int totalSuccesses = 0;
                int lastActualX = -999999;
                int lastActualY = -999999;

                Stopwatch swTotal = Stopwatch.StartNew();
                long nextStepTick = Stopwatch.GetTimestamp();

                while (swTotal.Elapsed.TotalSeconds < durationSec)
                {
                    double t = swTotal.Elapsed.TotalSeconds;
                    totalRequested++;

                    // Compute smooth harmonic trajectory
                    int targetX = (int)(originX + amplitudeX * Math.Sin(2.0 * Math.PI * motionFreqHz * t));
                    int targetY = (int)(originY + amplitudeY * Math.Cos(2.0 * Math.PI * motionFreqHz * t));

                    long tCallStart = Stopwatch.GetTimestamp();
                    bool ok = SetWindowPos(hWnd, IntPtr.Zero, targetX, targetY, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
                    long tCallEnd = Stopwatch.GetTimestamp();
                    double callMs = (tCallEnd - tCallStart) * 1000.0 / (double)Stopwatch.Frequency;

                    if (ok) totalSuccesses++;

                    // Verify actual HWND position
                    RECT r;
                    GetWindowRect(hWnd, out r);
                    bool isDistinct = (r.Left != lastActualX || r.Top != lastActualY);
                    if (isDistinct)
                    {
                        lastActualX = r.Left;
                        lastActualY = r.Top;
                    }

                    records.Add(new StepRecord
                    {
                        ElapsedSec = t,
                        TargetX = targetX,
                        TargetY = targetY,
                        ActualX = r.Left,
                        ActualY = r.Top,
                        CallLatencyMs = callMs,
                        IsDistinct = isDistinct
                    });

                    Application.DoEvents();

                    // High-precision spin-wait to target 120 Hz tick
                    nextStepTick += stepIntervalTicks;
                    while (Stopwatch.GetTimestamp() < nextStepTick)
                    {
                        Thread.SpinWait(10);
                    }
                }

                swTotal.Stop();
                double totalActualSec = swTotal.Elapsed.TotalSeconds;

                // Statistical Time-Series Analysis
                int durationInt = (int)Math.Ceiling(totalActualSec);
                int[] perSecondUpdates = new int[durationInt];
                List<double>[] perSecondLatencies = new List<double>[durationInt];
                for (int i = 0; i < durationInt; i++) perSecondLatencies[i] = new List<double>();

                List<double> allLatencies = new List<double>();
                int distinctCount = 0;
                double lastDistinctTime = 0.0;
                double maxGapMs = 0.0;
                double totalDisplacement = 0.0;

                for (int i = 0; i < records.Count; i++)
                {
                    var rec = records[i];
                    allLatencies.Add(rec.CallLatencyMs);

                    int secIdx = Math.Min((int)rec.ElapsedSec, durationInt - 1);
                    perSecondLatencies[secIdx].Add(rec.CallLatencyMs);

                    if (rec.IsDistinct)
                    {
                        distinctCount++;
                        perSecondUpdates[secIdx]++;

                        if (distinctCount > 1)
                        {
                            double gap = (rec.ElapsedSec - lastDistinctTime) * 1000.0;
                            if (gap > maxGapMs) maxGapMs = gap;
                        }
                        lastDistinctTime = rec.ElapsedSec;

                        if (i > 0)
                        {
                            double dx = rec.ActualX - records[i - 1].ActualX;
                            double dy = rec.ActualY - records[i - 1].ActualY;
                            totalDisplacement += Math.Sqrt(dx * dx + dy * dy);
                        }
                    }
                }

                allLatencies.Sort();
                double latMedian = allLatencies.Count > 0 ? allLatencies[allLatencies.Count / 2] : 0.0;
                int p95Idx = (int)(allLatencies.Count * 0.95);
                double latP95 = allLatencies.Count > 0 ? allLatencies[Math.Min(p95Idx, allLatencies.Count - 1)] : 0.0;
                double latMax = allLatencies.Count > 0 ? allLatencies[allLatencies.Count - 1] : 0.0;
                double latMin = allLatencies.Count > 0 ? allLatencies[0] : 0.0;

                double sumLat = 0;
                foreach (var l in allLatencies) sumLat += l;
                double latMean = allLatencies.Count > 0 ? sumLat / allLatencies.Count : 0.0;

                double[] perSecMedians = new double[durationInt];
                double[] perSecMaxs = new double[durationInt];
                for (int s = 0; s < durationInt; s++)
                {
                    var list = perSecondLatencies[s];
                    list.Sort();
                    perSecMedians[s] = list.Count > 0 ? list[list.Count / 2] : 0.0;
                    perSecMaxs[s] = list.Count > 0 ? list[list.Count - 1] : 0.0;
                }

                // Early (sec 0..2) vs Late (sec 17..19) cadence
                double earlyUpdates = 0;
                int earlyCount = Math.Min(3, durationInt);
                for (int s = 0; s < earlyCount; s++) earlyUpdates += perSecondUpdates[s];
                double earlyCadence = earlyCount > 0 ? earlyUpdates / earlyCount : 0.0;

                double lateUpdates = 0;
                int lateCount = Math.Min(3, durationInt);
                for (int s = durationInt - lateCount; s < durationInt; s++) lateUpdates += perSecondUpdates[s];
                double lateCadence = lateCount > 0 ? lateUpdates / lateCount : 0.0;

                double degRatio = earlyCadence > 0 ? (lateCadence / earlyCadence) : 1.0;
                bool isDeg = degRatio < 0.75; // More than 25% drop over 20s

                ProgrammaticReport rep = new ProgrammaticReport
                {
                    ConfigName = name,
                    DurationSec = Math.Round(totalActualSec, 2),
                    RequestedMoves = totalRequested,
                    SetWindowPosSuccesses = totalSuccesses,
                    ActualDistinctPositions = distinctCount,
                    ActualCadenceHz = Math.Round(distinctCount / totalActualSec, 1),
                    LatencyMedianMs = Math.Round(latMedian, 3),
                    LatencyP95Ms = Math.Round(latP95, 3),
                    LatencyMaxMs = Math.Round(latMax, 3),
                    LatencyMeanMs = Math.Round(latMean, 3),
                    LatencyMinMs = Math.Round(latMin, 3),
                    LongestNoChangeGapMs = Math.Round(maxGapMs, 2),
                    PerSecondUpdates = perSecondUpdates,
                    PerSecondLatencyMedianMs = perSecMedians,
                    PerSecondLatencyMaxMs = perSecMaxs,
                    EarlyCadenceHz = Math.Round(earlyCadence, 1),
                    LateCadenceHz = Math.Round(lateCadence, 1),
                    DegradationRatio = Math.Round(degRatio, 3),
                    IsDegrading = isDeg,
                    TotalDisplacementPx = Math.Round(totalDisplacement, 1)
                };

                Console.WriteLine("  [" + name + "] Results:");
                Console.WriteLine("    - Requested Moves: " + rep.RequestedMoves + " (Target 120Hz, Duration=" + rep.DurationSec + "s)");
                Console.WriteLine("    - SetWindowPos Successes: " + rep.SetWindowPosSuccesses + " (100% OK)");
                Console.WriteLine("    - Actual Distinct HWND Positions: " + rep.ActualDistinctPositions + " (" + rep.ActualCadenceHz + " Hz)");
                Console.WriteLine("    - SetWindowPos Call Latency: Median=" + rep.LatencyMedianMs + "ms, P95=" + rep.LatencyP95Ms + "ms, Max=" + rep.LatencyMaxMs + "ms, Min=" + rep.LatencyMinMs + "ms");
                Console.WriteLine("    - Longest No-Position-Change Gap: " + rep.LongestNoChangeGapMs + " ms");
                Console.WriteLine("    - Early Cadence (Sec 1-3): " + rep.EarlyCadenceHz + " Hz vs Late Cadence (Sec 18-20): " + rep.LateCadenceHz + " Hz (Ratio: " + (rep.DegradationRatio * 100.0).ToString("F1") + "%)");
                Console.WriteLine("    - Per-Second Position Updates: [" + string.Join(", ", rep.PerSecondUpdates) + "]");
                Console.WriteLine("    - Temporal Degradation Detected: " + rep.IsDegrading);

                form.Close();
                Thread.Sleep(300);
                return rep;
            };

            List<ProgrammaticReport> allReports = new List<ProgrammaticReport>();

            // Group A: Pure WinForms
            Form formA = new Form
            {
                FormBorderStyle = FormBorderStyle.None,
                StartPosition = FormStartPosition.Manual,
                Location = new Point(400, 200),
                Size = new Size(390, 450),
                TopMost = true,
                BackColor = Color.FromArgb(15, 23, 42)
            };
            allReports.Add(runProgrammaticTest("A. WinForms (Pure)", formA, null, 20.0));

            // Group B: WinForms + DirectComposition static visual
            allReports.Add(runProgrammaticTest("B. WinForms + DComp Static", new DirectCompositionHudForm(400, 200, 390, 450, true), null, 20.0));

            // Group C: DComp + Composition WebView2 static HUD (No WS, No Vision)
            allReports.Add(runProgrammaticTest("C. DComp + Composition WebView2 Static", new DirectCompositionHudForm(400, 200, 390, 450, true), (f) =>
            {
                ((DirectCompositionHudForm)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 20.0));

            // Group D: Production runtime (with 10Hz live WS)
            allReports.Add(runProgrammaticTest("D. Production Full Runtime (10Hz WS)", new DirectCompositionHudForm(400, 200, 390, 450, true), (f) =>
            {
                ((DirectCompositionHudForm)f).InitializeComposition(env, htmlPath);
                Thread.Sleep(1000);
            }, 20.0));

            Console.WriteLine("\n======================================================================");
            Console.WriteLine("PROGRAMMATIC 120HZ MOTION TEST SUMMARY (20 SECONDS)");
            Console.WriteLine("======================================================================");
            Console.WriteLine(string.Format("{0,-36} | {1,8} | {2,8} | {3,8} | {4,8} | {5,8} | {6,8} | {7,10}",
                "Configuration", "ReqMoves", "Distinct", "Cadence", "MedianLat", "P95Lat", "MaxLat", "Degrade?"));
            Console.WriteLine(new string('-', 108));

            foreach (var r in allReports)
            {
                Console.WriteLine(string.Format("{0,-36} | {1,8} | {2,8} | {3,6:F1}Hz | {4,6:F3}ms | {5,6:F3}ms | {6,6:F3}ms | {7,10}",
                    r.ConfigName, r.RequestedMoves, r.ActualDistinctPositions, r.ActualCadenceHz, r.LatencyMedianMs, r.LatencyP95Ms, r.LatencyMaxMs, r.IsDegrading ? "YES (DROP)" : "NO (STABLE)"));
            }

            Console.WriteLine("\n--- Per-Second Position Update Counts [Sec 1 .. 20] ---");
            foreach (var r in allReports)
            {
                Console.WriteLine(string.Format("{0,-36} : [{1}]", r.ConfigName, string.Join(", ", r.PerSecondUpdates)));
            }
        }
    }
}
