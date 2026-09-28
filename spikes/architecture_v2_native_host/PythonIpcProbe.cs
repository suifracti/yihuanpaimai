using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace ArchitectureV2.NativeHost
{
    public class IpcBenchmarkResult
    {
        public bool Success { get; set; }
        public int TotalRequests { get; set; }
        public double P50LatencyMs { get; set; }
        public double P95LatencyMs { get; set; }
        public double MeanLatencyMs { get; set; }
        public double MinLatencyMs { get; set; }
        public double MaxLatencyMs { get; set; }
        public string Protocol { get; set; } = "Length-prefixed JSON Lines over Stdio / Named Pipe Stream";
        public string FailureReason { get; set; } = string.Empty;
    }

    public static class PythonIpcProbe
    {
        public static IpcBenchmarkResult Run(string pythonExe, string scriptPath, int iterations = 100)
        {
            var result = new IpcBenchmarkResult();

            if (!File.Exists(pythonExe) || !File.Exists(scriptPath))
            {
                result.Success = false;
                result.FailureReason = $"Python executable or script not found: python={pythonExe}, script={scriptPath}";
                return result;
            }

            var psi = new ProcessStartInfo
            {
                FileName = pythonExe,
                Arguments = $"\"{scriptPath}\"",
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            using var proc = new Process { StartInfo = psi };
            try
            {
                proc.Start();
            }
            catch (Exception ex)
            {
                result.Success = false;
                result.FailureReason = $"Failed to start child python process: {ex.Message}";
                return result;
            }

            var latencies = new List<double>();
            var writer = proc.StandardInput;
            var reader = proc.StandardOutput;

            try
            {
                // Warm up
                writer.WriteLine(JsonSerializer.Serialize(new { cmd = "ping", id = 0 }));
                writer.Flush();
                string? warmResp = reader.ReadLine();
                if (warmResp == null)
                {
                    result.Success = false;
                    result.FailureReason = "Child process returned null response during warmup.";
                    return result;
                }

                // Benchmark loop
                for (int i = 1; i <= iterations; i++)
                {
                    var sw = Stopwatch.StartNew();
                    writer.WriteLine(JsonSerializer.Serialize(new { cmd = "ping", id = i }));
                    writer.Flush();
                    string? respLine = reader.ReadLine();
                    sw.Stop();

                    if (respLine != null)
                    {
                        latencies.Add(sw.Elapsed.TotalMilliseconds);
                    }
                }

                // Graceful shutdown
                writer.WriteLine(JsonSerializer.Serialize(new { cmd = "shutdown", id = 9999 }));
                writer.Flush();
                proc.WaitForExit(2000);
            }
            catch (Exception ex)
            {
                result.Success = false;
                result.FailureReason = $"IPC exception during benchmark: {ex.Message}";
                if (!proc.HasExited)
                    proc.Kill();
                return result;
            }

            if (latencies.Count > 0)
            {
                latencies.Sort();
                result.Success = true;
                result.TotalRequests = latencies.Count;
                result.MinLatencyMs = latencies.First();
                result.MaxLatencyMs = latencies.Last();
                result.MeanLatencyMs = latencies.Average();
                int p50Idx = (int)(latencies.Count * 0.50);
                int p95Idx = (int)(latencies.Count * 0.95);
                result.P50LatencyMs = latencies[Math.Min(p50Idx, latencies.Count - 1)];
                result.P95LatencyMs = latencies[Math.Min(p95Idx, latencies.Count - 1)];
            }

            return result;
        }
    }
}
