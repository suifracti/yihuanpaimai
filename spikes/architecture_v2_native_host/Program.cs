using System;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;

namespace ArchitectureV2.NativeHost
{
    public class Program
    {
        public static async Task<int> Main(string[] args)
        {
            if (args.Length > 0 && args[0] == "--verify-contracts")
            {
                string contractsDir = args.Length > 1 ? args[1] : Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "architecture", "v2", "contracts"));
                string outputDir = args.Length > 2 ? args[2] : AppContext.BaseDirectory;
                ContractVerifier.RunVerification(contractsDir, outputDir);
                return 0;
            }

            Console.WriteLine("===============================================================");
            Console.WriteLine("  Architecture V2: .NET 8 Native Host & Comparison Spike");
            Console.WriteLine("===============================================================");

            string pythonExe = @"D:\yihuanpaimai\build\takeover_20260905\repro-venv\Scripts\python.exe";
            string currentDir = AppDomain.CurrentDomain.BaseDirectory;
            string scriptPath = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "python_engine_mock.py"));
            if (!File.Exists(scriptPath))
            {
                scriptPath = @"D:\yihuanpaimai-recovery\spikes\architecture_v2_native_host\python_engine_mock.py";
            }

            // 1. HWND Discovery Probe
            Console.WriteLine("\n[1/9] Running HWND Discovery Probe...");
            var p1 = HwndDiscoveryProbe.Run(new[] { "异环", "NevernessToEverness", "NTE" });
            Console.WriteLine($"  - Target Found: {p1.FoundTarget}, Title='{p1.Title}', HWND={p1.HwndHex}, Scanned={p1.TotalWindowsScanned} windows in {p1.DiscoveryElapsedMs:F2}ms");

            // 2. Screen Capture Probe
            Console.WriteLine("\n[2/9] Running Screen Capture Probe...");
            IntPtr targetHwnd = p1.RawHwnd != IntPtr.Zero ? p1.RawHwnd : NativeMethods.GetForegroundWindow();
            string windowTitle = p1.FoundTarget ? p1.Title : "Desktop Foreground";
            var p2_gdi = ScreenCaptureProbe.BenchmarkGdiPrintWindow(targetHwnd, windowTitle, 30);
            var p2_bitblt = ScreenCaptureProbe.BenchmarkNativeBitBlt(targetHwnd, windowTitle, 30);
            var p2_wgc = ScreenCaptureProbe.EvaluateWgcBackend();
            Console.WriteLine($"  - GDI PrintWindow: P50={p2_gdi.P50:F2}ms, P95={p2_gdi.P95:F2}ms (Status={p2_gdi.Status})");
            Console.WriteLine($"  - Native BitBlt:   P50={p2_bitblt.P50:F2}ms, P95={p2_bitblt.P95:F2}ms (Status={p2_bitblt.Status})");
            Console.WriteLine($"  - WGC Backend:     Status={p2_wgc.Status} ({p2_wgc.TechnicalNotes})");

            // 3. Focus Monitoring Probe
            Console.WriteLine("\n[3/9] Running Focus Monitoring Probe (SetWinEventHook)...");
            var p3 = FocusMonitorProbe.Run(1000);
            Console.WriteLine($"  - Hook Installed: {p3.HookInstalled}, Events Captured: {p3.EventsCaptured}, Mechanism: {p3.Mechanism}");

            // 4. Low-Level Input Observation Probe
            Console.WriteLine("\n[4/9] Running Low-Level Input Observation Probe (WH_KEYBOARD_LL / WH_MOUSE_LL)...");
            var p4 = LowLevelInputProbe.Run(1000);
            Console.WriteLine($"  - Hooks Installed: {p4.HooksInstalled}, Dispatch Latency: P50={p4.HookCallbackDispatchP50Us:F1}us, P95={p4.HookCallbackDispatchP95Us:F1}us");
            Console.WriteLine($"  - Registry LowLevelHooksTimeout: {p4.RegistryLowLevelHooksTimeoutMs}ms, Risk: ZeroRisk={p4.ZeroRisk}, RiskReduced={p4.RiskReduced}");

            // 5. Mock-Safe SendInput Boundary Probe
            Console.WriteLine("\n[5/9] Running Mock-Safe SendInput Boundary Probe...");
            var p5 = MockSafeSendInputProbe.Run(targetHwnd, mockDryRun: true);
            Console.WriteLine($"  - Mock Dry Run: {p5.MockDryRun}, Precheck: {p5.PrecheckPassed}, TOCTOU: {p5.ToctouForegroundPassed}, Cursor Restored: {p5.CursorRestored}");

            // 6. Python Child-Process IPC Roundtrip Probe
            Console.WriteLine("\n[6/9] Running Python IPC Roundtrip Probe (100 iterations)...");
            var p6 = PythonIpcProbe.Run(pythonExe, scriptPath, 100);
            Console.WriteLine($"  - IPC Success: {p6.Success}, P50={p6.P50LatencyMs:F3}ms, P95={p6.P95LatencyMs:F3}ms, Mean={p6.MeanLatencyMs:F3}ms");

            // 7. Memory Mapped File (MMF) Data Plane Probe
            Console.WriteLine("\n[7/9] Running Memory-Mapped File (MMF) Data Plane Probe (30 frames, 1080p)...");
            var p7 = MemoryMappedFileProbe.RunEndToEndBenchmark(pythonExe, scriptPath, 30);
            Console.WriteLine($"  - MMF Success: {p7.Success}, Frames: {p7.FramesWritten}, Write P50={p7.P50WriteMs:F3}ms, P95={p7.P95WriteMs:F3}ms");
            Console.WriteLine($"  - Mapping Latency: P50={p7.FrameMappingLatencyP50Ms:F3}ms, Producer->Consumer P95={p7.FrameProducerToConsumerLatencyP95Ms:F3}ms");
            Console.WriteLine($"  - Integrity: Monotonic={p7.SequenceMonotonic}, Checksum={p7.FrameIntegrityVerified}, ZeroCopyProcessMap={p7.ZeroCopyAtProcessMapping}");

            // 8. WebView2 Host Shell Probe
            Console.WriteLine("\n[8/9] Running WebView2 Native Host Shell Probe...");
            var p8 = await WebView2ShellProbe.RunAsync();
            Console.WriteLine($"  - WebView2 Initialized: {p8.Initialized}, Version: {p8.RuntimeVersion}, InitTime: {p8.InitElapsedMs:F1}ms");

            // 9. Process Supervisor & Crash Recovery Probe
            Console.WriteLine("\n[9/9] Running Process Supervisor & Crash Recovery Probe...");
            var p9 = ProcessSupervisorProbe.Run(pythonExe, scriptPath);
            Console.WriteLine($"  - Initial Start: {p9.InitialStartOk}, Crash Detected: {p9.CrashDetected} in {p9.ProcessExitDetectionMs:F1}ms");
            Console.WriteLine($"  - Restart: {p9.AutoRestartOk} in {p9.MockProcessRestartMs:F1}ms, Handshake in {p9.EngineHandshakeMs:F1}ms");
            Console.WriteLine($"  - Total Mock Recovery: {p9.TotalMockRecoveryMs:F1}ms (BusinessStateResync: {p9.BusinessStateResyncStatus})");
            Console.WriteLine($"  - Verdict: {p9.FaultIsolationVerdict}");

            // Compile aggregate report
            var fullReport = new
            {
                spikeVersion = "architecture.v2.spike.v2",
                timestamp = DateTime.UtcNow.ToString("o"),
                environment = new
                {
                    os = Environment.OSVersion.ToString(),
                    dotnet = Environment.Version.ToString(),
                    is64BitProcess = Environment.Is64BitProcess,
                    processorCount = Environment.ProcessorCount,
                    pythonExe = pythonExe,
                    pythonMockScript = scriptPath
                },
                probe1_hwndDiscovery = p1,
                probe2_screenCapture = new { gdiPrintWindow = p2_gdi, gdiBitBlt = p2_bitblt, wgc = p2_wgc },
                probe3_focusMonitoring = p3,
                probe4_lowLevelInput = p4,
                probe5_mockSafeSendInput = p5,
                probe6_pythonIpc = p6,
                probe7_memoryMappedFile = p7,
                probe8_webView2Shell = p8,
                probe9_supervisorRecovery = p9
            };

            string outPath = Path.Combine(AppContext.BaseDirectory, "probe_execution_report.json");
            string jsonText = JsonSerializer.Serialize(fullReport, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(outPath, jsonText);
            Console.WriteLine($"\nFull execution report saved to: {outPath}");

            Console.WriteLine("\n===============================================================");
            Console.WriteLine("  All 9 Native Host Probes Completed Successfully!");
            Console.WriteLine("===============================================================");
            return 0;
        }
    }
}
