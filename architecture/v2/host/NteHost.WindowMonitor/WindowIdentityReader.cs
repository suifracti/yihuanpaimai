using System.Collections.Concurrent;
using System.Text;
using NteHost.WindowMonitor.Win32;

namespace NteHost.WindowMonitor;

/// <summary>
/// Reads a <see cref="WindowIdentity"/> from a raw HWND, and answers the only
/// question that matters for fail-closed behaviour: "is this handle still the
/// window I think it is?"
///
/// Process image names are cached per pid because resolving them requires opening
/// the process. The cache is explicit and clearable so a pid recycle cannot
/// silently pin a stale image name forever.
/// </summary>
public sealed class WindowIdentityReader
{
    private readonly ConcurrentDictionary<int, string> _imageNameByPid = new();

    /// <summary>Number of process-image resolutions actually performed (cache misses).</summary>
    public long ImageNameResolutions => _imageNameResolutions;

    private long _imageNameResolutions;

    public void InvalidatePid(int pid) => _imageNameByPid.TryRemove(pid, out _);

    public void ClearCache() => _imageNameByPid.Clear();

    /// <summary>
    /// Reads only the window class name. Cheap: no process handle is opened, so it
    /// is safe to call for every top-level window during a recovery scan and use the
    /// result as a filter before resolving process images.
    /// </summary>
    public string ReadClassNameOnly(long hwnd)
    {
        if (hwnd == 0)
        {
            return string.Empty;
        }
        return ReadClassName(new IntPtr(hwnd));
    }

    /// <summary>
    /// Reads the identity of a handle. Returns <see cref="WindowIdentity.None"/> when
    /// the handle is not a live window; it never throws for a dead handle.
    /// </summary>
    public WindowIdentity Read(long hwnd)
    {
        var handle = new IntPtr(hwnd);
        if (hwnd == 0 || !NativeWindowApi.IsWindow(handle))
        {
            return WindowIdentity.None;
        }

        NativeWindowApi.GetWindowThreadProcessId(handle, out var pid);
        if (pid == 0)
        {
            return WindowIdentity.None;
        }

        var className = ReadClassName(handle);
        var title = ReadWindowText(handle);
        var imageName = ResolveImageName((int)pid);
        var visible = NativeWindowApi.IsWindowVisible(handle);

        return new WindowIdentity(hwnd, (int)pid, imageName, className, title, visible);
    }

    /// <summary>
    /// True when the handle is still a live window AND still carries the identity we
    /// recorded. Both halves are required: an HWND is a recyclable integer, so a
    /// live handle alone is not evidence that it is still our target.
    /// </summary>
    /// <param name="requireVisible">
    /// When true, a window that became hidden counts as no longer usable. An
    /// invisible game window cannot be interacted with, so it is treated as lost.
    /// </param>
    public bool IsStillSameWindow(WindowIdentity recorded, bool requireVisible = true)
    {
        if (!recorded.IsPresent)
        {
            return false;
        }

        var handle = new IntPtr(recorded.Hwnd);
        if (!NativeWindowApi.IsWindow(handle))
        {
            return false;
        }

        NativeWindowApi.GetWindowThreadProcessId(handle, out var pid);
        if ((int)pid != recorded.Pid)
        {
            return false;
        }

        var className = ReadClassName(handle);
        if (!string.Equals(className, recorded.ClassName, StringComparison.Ordinal))
        {
            return false;
        }

        return !requireVisible || NativeWindowApi.IsWindowVisible(handle);
    }

    private string ResolveImageName(int pid)
    {
        if (_imageNameByPid.TryGetValue(pid, out var cached))
        {
            return cached;
        }

        var resolved = QueryImageName(pid);
        _imageNameByPid[pid] = resolved;
        Interlocked.Increment(ref _imageNameResolutions);
        return resolved;
    }

    private static string QueryImageName(int pid)
    {
        using var process = NativeWindowApi.OpenProcess(
            NativeWindowApi.PROCESS_QUERY_LIMITED_INFORMATION, false, (uint)pid);
        if (process.IsInvalid)
        {
            return string.Empty;
        }

        var buffer = new StringBuilder(1024);
        var size = (uint)buffer.Capacity;
        if (!NativeWindowApi.QueryFullProcessImageNameW(process, 0, buffer, ref size))
        {
            return string.Empty;
        }

        var full = buffer.ToString();
        if (string.IsNullOrEmpty(full))
        {
            return string.Empty;
        }

        var separator = full.LastIndexOf('\\');
        return separator >= 0 && separator < full.Length - 1 ? full[(separator + 1)..] : full;
    }

    private static string ReadClassName(IntPtr handle)
    {
        var buffer = new StringBuilder(256);
        var length = NativeWindowApi.GetClassNameW(handle, buffer, buffer.Capacity);
        return length > 0 ? buffer.ToString() : string.Empty;
    }

    private static string ReadWindowText(IntPtr handle)
    {
        var buffer = new StringBuilder(512);
        var length = NativeWindowApi.GetWindowTextW(handle, buffer, buffer.Capacity);
        return length > 0 ? buffer.ToString() : string.Empty;
    }
}
