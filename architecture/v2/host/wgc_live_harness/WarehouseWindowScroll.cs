using System.Runtime.InteropServices;
using NteHost.WindowMonitor;

namespace WgcLiveHarness;

/// <summary>One HWND-bound wheel message. No activation, cursor movement or global input fallback.</summary>
internal static class WarehouseWindowScroll
{
    public static bool SendDown(WarehouseSourceContext context, Func<bool> current)
    {
        var hwnd = (long?)context.Target["targetHwnd"] ?? 0;
        var pid = (int?)context.Target["targetPid"] ?? 0;
        var token = (long?)context.Target["processInstanceToken"] ?? 0;
        if (hwnd <= 0 || hwnd == 0xffff || pid <= 0 || token <= 0 || !current()) return false;
        var identity = new WindowIdentityReader().Read(hwnd);
        var handle = new IntPtr(hwnd);
        if (identity.Pid != pid || identity.ProcessInstanceToken != token || !identity.IsVisible
            || !string.Equals(identity.ProcessImageName, "HTGame.exe", StringComparison.OrdinalIgnoreCase)
            || !string.Equals(identity.ClassName, "UnrealWindow", StringComparison.Ordinal)
            || IsIconic(handle) || !GetClientRect(handle, out var rect)
            || rect.Right - rect.Left != context.Width || rect.Bottom - rect.Top != context.Height) return false;
        // Interior of the existing 16:9 warehouse ROI, including letterbox compensation.
        var width = context.Width; var height = context.Height;
        var vw = width; var vh = height; var vx = 0; var vy = 0;
        if (Math.Abs((double)width / height - 16.0 / 9) >= .02)
        {
            if ((double)width / height > 16.0 / 9) { vw = (int)(height * 16.0 / 9); vx = (width - vw) / 2; }
            else { vh = (int)(width / (16.0 / 9)); vy = (height - vh) / 2; }
        }
        var point = new Point { X = vx + (int)(.83 * vw), Y = vy + (int)(.47 * vh) };
        if (point.X < 0 || point.Y < 0 || point.X >= width || point.Y >= height
            || !ClientToScreen(handle, ref point) || point.X < short.MinValue || point.X > short.MaxValue
            || point.Y < short.MinValue || point.Y > short.MaxValue || !current()) return false;
        var coordinates = unchecked((uint)(ushort)(short)point.X | ((uint)(ushort)(short)point.Y << 16));
        var wheel = unchecked((uint)(ushort)(short)-120 << 16);
        var sent = SendMessageTimeoutW(handle, 0x020A, new UIntPtr(wheel), new IntPtr((long)coordinates),
            0x23, 100, out _); // SMTO_BLOCK | ABORTIFHUNG | ERRORONEXIT
        return sent != IntPtr.Zero && current(); // delivery does not prove that the game scrolled
    }

    [StructLayout(LayoutKind.Sequential)] private struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GetClientRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool ClientToScreen(IntPtr hwnd, ref Point point);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr SendMessageTimeoutW(
        IntPtr hwnd, uint message, UIntPtr wParam, IntPtr lParam, uint flags, uint timeout, out UIntPtr result);
}
