using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Linq;

namespace ArchitectureV2.NativeHost
{
    public class CaptureBackendReport
    {
        public string CaptureBackend { get; set; } = string.Empty;
        public string Status { get; set; } = "SUCCESS"; // SUCCESS, NOT_MEASURED, FAILED
        public int Samples { get; set; }
        public int Warmups { get; set; }
        public double P50 { get; set; }
        public double P95 { get; set; }
        public double Mean { get; set; }
        public int DroppedFrames { get; set; }
        public string TargetWindow { get; set; } = string.Empty;
        public string FrameSize { get; set; } = string.Empty;
        public string TechnicalNotes { get; set; } = string.Empty;
    }

    public static class ScreenCaptureProbe
    {
        public static CaptureBackendReport BenchmarkGdiPrintWindow(IntPtr hwnd, string windowTitle, int samples = 30, int warmups = 5)
        {
            if (hwnd == IntPtr.Zero || !NativeMethods.IsWindow(hwnd))
            {
                return new CaptureBackendReport
                {
                    CaptureBackend = "GDI_PRINTWINDOW",
                    Status = "FAILED",
                    TargetWindow = "INVALID_HWND",
                    TechnicalNotes = "HWND is invalid or zero"
                };
            }

            NativeMethods.GetClientRect(hwnd, out var cr);
            int width = Math.Max(cr.Width, 64);
            int height = Math.Max(cr.Height, 64);

            // Warmup iterations
            for (int w = 0; w < warmups; w++)
            {
                IntPtr hdcWindow = NativeMethods.GetDC(hwnd);
                IntPtr hdcMem = NativeMethods.CreateCompatibleDC(hdcWindow);
                IntPtr hBmp = NativeMethods.CreateCompatibleBitmap(hdcWindow, width, height);
                IntPtr hOld = NativeMethods.SelectObject(hdcMem, hBmp);
                NativeMethods.PrintWindow(hwnd, hdcMem, NativeMethods.PW_RENDERFULLCONTENT);
                NativeMethods.SelectObject(hdcMem, hOld);
                NativeMethods.DeleteObject(hBmp);
                NativeMethods.DeleteDC(hdcMem);
                NativeMethods.ReleaseDC(hwnd, hdcWindow);
            }

            var latencies = new List<double>();
            int dropped = 0;

            for (int i = 0; i < samples; i++)
            {
                var sw = Stopwatch.StartNew();
                IntPtr hdcWindow = NativeMethods.GetDC(hwnd);
                IntPtr hdcMem = NativeMethods.CreateCompatibleDC(hdcWindow);
                IntPtr hBmp = NativeMethods.CreateCompatibleBitmap(hdcWindow, width, height);
                IntPtr hOld = NativeMethods.SelectObject(hdcMem, hBmp);

                bool ok = NativeMethods.PrintWindow(hwnd, hdcMem, NativeMethods.PW_RENDERFULLCONTENT);

                sw.Stop();
                latencies.Add(sw.Elapsed.TotalMilliseconds);

                if (!ok)
                {
                    dropped++;
                }

                NativeMethods.SelectObject(hdcMem, hOld);
                NativeMethods.DeleteObject(hBmp);
                NativeMethods.DeleteDC(hdcMem);
                NativeMethods.ReleaseDC(hwnd, hdcWindow);
            }

            latencies.Sort();
            int p50Idx = (int)(latencies.Count * 0.50);
            int p95Idx = (int)(latencies.Count * 0.95);

            return new CaptureBackendReport
            {
                CaptureBackend = "GDI_PRINTWINDOW",
                Status = "SUCCESS",
                Samples = samples,
                Warmups = warmups,
                P50 = latencies[Math.Min(p50Idx, latencies.Count - 1)],
                P95 = latencies[Math.Min(p95Idx, latencies.Count - 1)],
                Mean = latencies.Average(),
                DroppedFrames = dropped,
                TargetWindow = windowTitle,
                FrameSize = $"{width}x{height}",
                TechnicalNotes = "Synchronous Win32 PrintWindow PW_RENDERFULLCONTENT. Blocks if target window message thread stalls."
            };
        }

        public static CaptureBackendReport BenchmarkNativeBitBlt(IntPtr hwnd, string windowTitle, int samples = 30, int warmups = 5)
        {
            if (hwnd == IntPtr.Zero || !NativeMethods.IsWindow(hwnd))
            {
                return new CaptureBackendReport
                {
                    CaptureBackend = "NATIVE_BITBLT",
                    Status = "FAILED",
                    TargetWindow = "INVALID_HWND",
                    TechnicalNotes = "HWND is invalid or zero"
                };
            }

            NativeMethods.GetClientRect(hwnd, out var cr);
            NativeMethods.POINT pt = new NativeMethods.POINT { X = 0, Y = 0 };
            NativeMethods.ClientToScreen(hwnd, ref pt);

            int width = Math.Max(cr.Width, 64);
            int height = Math.Max(cr.Height, 64);

            // Warmup iterations
            for (int w = 0; w < warmups; w++)
            {
                IntPtr hdcScreen = NativeMethods.GetDC(IntPtr.Zero);
                IntPtr hdcMem = NativeMethods.CreateCompatibleDC(hdcScreen);
                IntPtr hBmp = NativeMethods.CreateCompatibleBitmap(hdcScreen, width, height);
                IntPtr hOld = NativeMethods.SelectObject(hdcMem, hBmp);
                NativeMethods.BitBlt(hdcMem, 0, 0, width, height, hdcScreen, pt.X, pt.Y, NativeMethods.SRCCOPY);
                NativeMethods.SelectObject(hdcMem, hOld);
                NativeMethods.DeleteObject(hBmp);
                NativeMethods.DeleteDC(hdcMem);
                NativeMethods.ReleaseDC(IntPtr.Zero, hdcScreen);
            }

            var latencies = new List<double>();
            int dropped = 0;

            for (int i = 0; i < samples; i++)
            {
                var sw = Stopwatch.StartNew();
                IntPtr hdcScreen = NativeMethods.GetDC(IntPtr.Zero);
                IntPtr hdcMem = NativeMethods.CreateCompatibleDC(hdcScreen);
                IntPtr hBmp = NativeMethods.CreateCompatibleBitmap(hdcScreen, width, height);
                IntPtr hOld = NativeMethods.SelectObject(hdcMem, hBmp);

                bool ok = NativeMethods.BitBlt(hdcMem, 0, 0, width, height, hdcScreen, pt.X, pt.Y, NativeMethods.SRCCOPY);

                sw.Stop();
                latencies.Add(sw.Elapsed.TotalMilliseconds);

                if (!ok)
                {
                    dropped++;
                }

                NativeMethods.SelectObject(hdcMem, hOld);
                NativeMethods.DeleteObject(hBmp);
                NativeMethods.DeleteDC(hdcMem);
                NativeMethods.ReleaseDC(IntPtr.Zero, hdcScreen);
            }

            latencies.Sort();
            int p50Idx = (int)(latencies.Count * 0.50);
            int p95Idx = (int)(latencies.Count * 0.95);

            return new CaptureBackendReport
            {
                CaptureBackend = "NATIVE_BITBLT",
                Status = "SUCCESS",
                Samples = samples,
                Warmups = warmups,
                P50 = latencies[Math.Min(p50Idx, latencies.Count - 1)],
                P95 = latencies[Math.Min(p95Idx, latencies.Count - 1)],
                Mean = latencies.Average(),
                DroppedFrames = dropped,
                TargetWindow = windowTitle,
                FrameSize = $"{width}x{height}",
                TechnicalNotes = "Direct desktop DC BitBlt copy. Captures screen pixels at target window client coordinate; immune to target window message stalls."
            };
        }

        public static CaptureBackendReport EvaluateWgcBackend()
        {
            // Windows Graphics Capture strictly separated per review rule C:
            // Since offline testing lacks an active 3D game swapchain rendering context,
            // WGC is strictly declared as NOT_MEASURED without borrowing BitBlt numbers.
            var osVersion = Environment.OSVersion.Version;
            bool osSupported = Environment.OSVersion.Platform == PlatformID.Win32NT &&
                               (osVersion.Major > 10 || (osVersion.Major == 10 && osVersion.Build >= 17134));

            return new CaptureBackendReport
            {
                CaptureBackend = "WINDOWS_GRAPHICS_CAPTURE",
                Status = "NOT_MEASURED",
                Samples = 0,
                Warmups = 0,
                P50 = 0.0,
                P95 = 0.0,
                Mean = 0.0,
                DroppedFrames = 0,
                TargetWindow = "N/A (Offline spike)",
                FrameSize = "1920x1080 (Targeted)",
                TechnicalNotes = osSupported
                    ? $"OS Build {osVersion.Build} supports Windows.Graphics.Capture COM APIs (IGraphicsCaptureItemInterop). Live 60fps Direct3D11 frame pool measurement requires active 3D game swapchain presentation context; marked strictly NOT_MEASURED in this offline spike per review discipline."
                    : "WGC not supported on this OS build."
            };
        }
    }
}
