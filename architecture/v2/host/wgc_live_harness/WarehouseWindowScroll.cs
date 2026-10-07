using System.Runtime.InteropServices;
using NteHost.WindowMonitor;
using NteHost.Protocol;
using System.Text.Json.Nodes;

namespace WgcLiveHarness;

/// <summary>One HWND-bound wheel message. No activation, cursor movement or global input fallback.</summary>
internal static class WarehouseWindowScroll
{
    internal sealed record TargetState(int Pid, long Token, string Image, string ClassName,
        bool Visible, bool Minimized, bool ClientRectAvailable, int Width, int Height, int RectError = 0);
    internal sealed record ScreenPoint(bool Success, int X, int Y, int Error = 0);
    internal sealed record SendResult(long ReturnValue, ulong MessageResult, int Error);
    internal interface IPlatform
    {
        TargetState ReadTarget(long hwnd);
        ScreenPoint ToScreen(long hwnd, int x, int y);
        SendResult Send(long hwnd, uint wheel, uint coordinates);
    }

    private sealed class Win32Platform : IPlatform
    {
        public TargetState ReadTarget(long hwnd)
        {
            var identity = new WindowIdentityReader().Read(hwnd);
            var handle = new IntPtr(hwnd);
            var minimized = IsIconic(handle);
            SetLastError(0);
            var available = GetClientRect(handle, out var rect);
            var error = Marshal.GetLastWin32Error();
            return new(identity.Pid, identity.ProcessInstanceToken, identity.ProcessImageName ?? "",
                identity.ClassName ?? "", identity.IsVisible, minimized, available,
                rect.Right - rect.Left, rect.Bottom - rect.Top, available ? 0 : error);
        }
        public ScreenPoint ToScreen(long hwnd, int x, int y)
        {
            var point = new Point { X = x, Y = y };
            SetLastError(0);
            var converted = ClientToScreen(new IntPtr(hwnd), ref point);
            var error = Marshal.GetLastWin32Error();
            return new(converted, point.X, point.Y, converted ? 0 : error);
        }
        public SendResult Send(long hwnd, uint wheel, uint coordinates)
        {
            // A zero return may have no extended error. Clear first as required
            // by SendMessageTimeout's documented diagnostic contract.
            SetLastError(0);
            var sent = SendMessageTimeoutW(new IntPtr(hwnd), 0x020A, new UIntPtr(wheel), new IntPtr((long)coordinates),
                0x23, 100, out var result);
            var error = Marshal.GetLastWin32Error();
            return new(sent.ToInt64(), result.ToUInt64(), error);
        }
    }

    public static bool SendDown(WarehouseSourceContext context, Func<bool> current,
        Action<JsonObject>? diagnostic = null, IPlatform? platform = null)
    {
        platform ??= new Win32Platform();
        void Log(string stage, JsonObject record)
        {
            record["stage"] = stage; record["comparisonNs"] = ProtocolClock.NowNs();
            record["recordStableKey"] = context.RecordKey; record["matchGeneration"] = context.MatchGeneration;
            try { diagnostic?.Invoke(record); } catch { }
        }
        bool Reject(string reason, JsonObject? checks = null)
        {
            Log("adapter-rejected", new JsonObject { ["reason"] = reason, ["checks"] = checks,
                ["classification"] = "NOT_SENT", ["sendInterfaceInvoked"] = false });
            return false;
        }
        var hwnd = (long?)context.Target["targetHwnd"] ?? 0;
        var pid = (int?)context.Target["targetPid"] ?? 0;
        var token = (long?)context.Target["processInstanceToken"] ?? 0;
        if (hwnd <= 0 || hwnd == 0xffff || pid <= 0 || token <= 0) return Reject("INVALID_TARGET_IDENTITY");
        if (!current()) return Reject("CURRENT_GUARD_REJECTED_BEFORE_TARGET_READ");
        var target = platform.ReadTarget(hwnd);
        var checks = new JsonObject { ["pidMatches"] = target.Pid == pid, ["processTokenMatches"] = target.Token == token,
            ["visible"] = target.Visible, ["notMinimized"] = !target.Minimized,
            ["imageMatches"] = string.Equals(target.Image, "HTGame.exe", StringComparison.OrdinalIgnoreCase),
            ["classMatches"] = target.ClassName == "UnrealWindow", ["clientRectAvailable"] = target.ClientRectAvailable,
            ["clientWidthMatches"] = target.Width == context.Width, ["clientHeightMatches"] = target.Height == context.Height };
        var failed = checks.Where(pair => !pair.Value!.GetValue<bool>()).Select(pair => pair.Key).ToArray();
        Log("adapter-target-check", new JsonObject { ["checks"] = checks.DeepClone(),
            ["failedChecks"] = new JsonArray(failed.Select(name => JsonValue.Create(name)).ToArray()),
            ["observedPid"] = target.Pid, ["observedToken"] = target.Token, ["observedWidth"] = target.Width,
            ["observedHeight"] = target.Height, ["rectErrorRaw"] = target.RectError, ["sendInterfaceInvoked"] = false });
        if (failed.Length != 0) return Reject("WINDOW_IDENTITY_OR_GEOMETRY_REJECTED", checks);
        // Interior of the existing 16:9 warehouse ROI, including letterbox compensation.
        var width = context.Width; var height = context.Height;
        var vw = width; var vh = height; var vx = 0; var vy = 0;
        if (Math.Abs((double)width / height - 16.0 / 9) >= .02)
        {
            if ((double)width / height > 16.0 / 9) { vw = (int)(height * 16.0 / 9); vx = (width - vw) / 2; }
            else { vh = (int)(width / (16.0 / 9)); vy = (height - vh) / 2; }
        }
        var x = vx + (int)(.83 * vw); var y = vy + (int)(.47 * vh);
        if (x < 0 || y < 0 || x >= width || y >= height) return Reject("CLIENT_SCROLL_POINT_OUT_OF_RANGE");
        var point = platform.ToScreen(hwnd, x, y);
        Log("adapter-coordinate-check", new JsonObject { ["converted"] = point.Success, ["screenX"] = point.X,
            ["screenY"] = point.Y, ["coordinateErrorRaw"] = point.Error, ["sendInterfaceInvoked"] = false });
        if (!point.Success) return Reject("CLIENT_TO_SCREEN_FAILED");
        if (point.X < short.MinValue || point.X > short.MaxValue || point.Y < short.MinValue || point.Y > short.MaxValue)
            return Reject("SCREEN_SCROLL_POINT_OUT_OF_RANGE");
        if (!current()) return Reject("CURRENT_GUARD_REJECTED_BEFORE_SEND");
        var coordinates = unchecked((uint)(ushort)(short)point.X | ((uint)(ushort)(short)point.Y << 16));
        var wheel = unchecked((uint)(ushort)(short)-120 << 16);
        var before = ProtocolClock.NowNs();
        SendResult sent;
        try { sent = platform.Send(hwnd, wheel, coordinates); }
        catch (Exception ex)
        {
            Log("send-interface-exception", new JsonObject { ["sendInterfaceInvoked"] = true,
                ["returnValue"] = null, ["exceptionType"] = ex.GetType().Name,
                ["callBeforeNs"] = before, ["classification"] = "SEND_OUTCOME_UNKNOWN",
                ["postScrollFrameReceived"] = false });
            throw; // preserve the existing exception/stop path; never retry uncertain input
        }
        var after = ProtocolClock.NowNs();
        Log("send-interface-returned", new JsonObject { ["sendInterfaceInvoked"] = true,
            ["api"] = "SendMessageTimeoutW", ["hwnd"] = hwnd, ["message"] = 0x020A, ["wheelDelta"] = -120,
            ["flags"] = 0x23, ["timeoutMs"] = 100, ["callBeforeNs"] = before, ["callAfterNs"] = after,
            ["returnValue"] = sent.ReturnValue, ["messageResult"] = sent.MessageResult, ["lastErrorRaw"] = sent.Error,
            ["classification"] = sent.ReturnValue == 0 ? "SEND_FAILED_OR_TIMED_OUT" : "SENT_DISPLACEMENT_UNPROVEN",
            ["errorMeaning"] = sent.ReturnValue == 0 && sent.Error == 0 ? "GENERIC_FAILURE_NO_EXTENDED_ERROR" : "raw error; success error is not a failure",
            ["postScrollFrameReceived"] = false });
        if (sent.ReturnValue == 0) return false;
        var currentAfter = current();
        Log("send-post-guard", new JsonObject { ["sendInterfaceInvoked"] = true,
            ["currentAfterSend"] = currentAfter, ["classification"] = currentAfter ? "SENT_DISPLACEMENT_UNPROVEN" : "SENT_GUARD_LOST",
            ["postScrollFrameReceived"] = false });
        return currentAfter; // delivery does not prove that the game scrolled
    }

    [StructLayout(LayoutKind.Sequential)] private struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool GetClientRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool ClientToScreen(IntPtr hwnd, ref Point point);
    [DllImport("kernel32.dll")] private static extern void SetLastError(uint error);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr SendMessageTimeoutW(
        IntPtr hwnd, uint message, UIntPtr wParam, IntPtr lParam, uint flags, uint timeout, out UIntPtr result);
}
