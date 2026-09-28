using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;

namespace ArchitectureV2.NativeHost
{
    public class HwndDiscoveryResult
    {
        public bool FoundTarget { get; set; }
        public string HwndHex { get; set; } = "0x0";
        public uint ProcessId { get; set; }
        public string Title { get; set; } = string.Empty;
        public string ClassName { get; set; } = string.Empty;
        public NativeMethods.RECT ClientRect { get; set; }
        public NativeMethods.RECT WindowRect { get; set; }
        public double DiscoveryElapsedMs { get; set; }
        public int TotalWindowsScanned { get; set; }

        [System.Text.Json.Serialization.JsonIgnore]
        public IntPtr RawHwnd { get; set; }
    }

    public static class HwndDiscoveryProbe
    {
        public static HwndDiscoveryResult Run(string[] targetKeywords)
        {
            var sw = Stopwatch.StartNew();
            var matches = new List<(IntPtr hwnd, uint pid, string title, string cls)>();
            int scanned = 0;

            NativeMethods.EnumWindows((hwnd, lParam) =>
            {
                scanned++;
                if (!NativeMethods.IsWindowVisible(hwnd) || NativeMethods.IsIconic(hwnd))
                    return true;

                var sbTitle = new StringBuilder(256);
                NativeMethods.GetWindowText(hwnd, sbTitle, 256);
                string title = sbTitle.ToString();

                var sbCls = new StringBuilder(256);
                NativeMethods.GetClassName(hwnd, sbCls, 256);
                string cls = sbCls.ToString();

                NativeMethods.GetWindowThreadProcessId(hwnd, out uint pid);

                foreach (var kw in targetKeywords)
                {
                    if (title.Contains(kw, StringComparison.OrdinalIgnoreCase))
                    {
                        matches.Add((hwnd, pid, title, cls));
                        return false;
                    }
                }
                return true;
            }, IntPtr.Zero);

            sw.Stop();

            var result = new HwndDiscoveryResult
            {
                TotalWindowsScanned = scanned,
                DiscoveryElapsedMs = sw.Elapsed.TotalMilliseconds
            };

            if (matches.Count > 0)
            {
                var m = matches[0];
                result.FoundTarget = true;
                result.RawHwnd = m.hwnd;
                result.HwndHex = $"0x{m.hwnd.ToInt64():X}";
                result.ProcessId = m.pid;
                result.Title = m.title;
                result.ClassName = m.cls;

                NativeMethods.GetClientRect(m.hwnd, out var cr);
                NativeMethods.GetWindowRect(m.hwnd, out var wr);
                result.ClientRect = cr;
                result.WindowRect = wr;
            }
            else
            {
                // Fallback to active console window or desktop window for non-game environment verification
                IntPtr fallbackHwnd = NativeMethods.GetConsoleWindow();
                if (fallbackHwnd == IntPtr.Zero || !NativeMethods.IsWindow(fallbackHwnd))
                {
                    fallbackHwnd = NativeMethods.GetForegroundWindow();
                }
                if (fallbackHwnd == IntPtr.Zero || !NativeMethods.IsWindow(fallbackHwnd))
                {
                    fallbackHwnd = NativeMethods.GetDesktopWindow();
                }

                if (fallbackHwnd != IntPtr.Zero)
                {
                    var sbTitle = new StringBuilder(256);
                    NativeMethods.GetWindowText(fallbackHwnd, sbTitle, 256);
                    var sbCls = new StringBuilder(256);
                    NativeMethods.GetClassName(fallbackHwnd, sbCls, 256);
                    NativeMethods.GetWindowThreadProcessId(fallbackHwnd, out uint pid);

                    NativeMethods.GetClientRect(fallbackHwnd, out var cr);
                    NativeMethods.GetWindowRect(fallbackHwnd, out var wr);

                    result.FoundTarget = false; // Game was not running, inspected fallback window
                    result.RawHwnd = fallbackHwnd;
                    result.HwndHex = $"0x{fallbackHwnd.ToInt64():X}";
                    result.ProcessId = pid;
                    result.Title = sbTitle.ToString().Length > 0 ? sbTitle.ToString() : "Console/Desktop Window (Spike Fallback)";
                    result.ClassName = sbCls.ToString();
                    result.ClientRect = cr;
                    result.WindowRect = wr;
                }
            }

            return result;
        }
    }
}
