using System.Collections.Concurrent;
using System.Text;
using NteHost.WindowMonitor.Win32;

namespace NteHost.WindowMonitor;

/// <summary>
/// Reads a <see cref="WindowIdentity"/> from a raw HWND, and answers the two
/// questions that matter for fail-closed behaviour:
///   * "what is this handle right now?" (<see cref="Read"/>)
///   * "is this handle still the window I think it is?" (<see cref="Revalidate"/>)
///
/// Process image names are cached per pid because resolving them requires opening
/// the process. A pid is recyclable exactly like an HWND is, so the cache is keyed
/// by <c>(pid, generation)</c> and the generation is bumped on every identity
/// boundary that could have invalidated a cached image. Without that, a recycled
/// pid would keep answering with the old executable's name forever.
/// </summary>
public sealed class WindowIdentityReader
{
    private readonly ConcurrentDictionary<(int Pid, long Generation), string> _imageNameByPid = new();

    /// <summary>
    /// Monotonic cache generation. Bumped by <see cref="InvalidatePid"/> and
    /// <see cref="InvalidateAll"/>. Entries written under an older generation are
    /// unreachable afterwards, so a stale image name cannot be pinned by a recycled
    /// pid even if the eviction itself raced with a concurrent read.
    /// </summary>
    private long _cacheGeneration;

    /// <summary>Current cache generation. Used by tests to prove invalidation happened.</summary>
    public long CacheGeneration => Interlocked.Read(ref _cacheGeneration);

    /// <summary>Number of process-image resolutions actually performed (cache misses).</summary>
    public long ImageNameResolutions => Interlocked.Read(ref _imageNameResolutions);

    private long _imageNameResolutions;

    /// <summary>
    /// Drops the cached image name for one pid. Called at every identity boundary
    /// where the mapping pid-&gt;image could have changed underneath us: target loss,
    /// process generation change, and recovery.
    /// </summary>
    public void InvalidatePid(int pid)
    {
        Interlocked.Increment(ref _cacheGeneration);
        if (pid != 0)
        {
            // Best-effort eviction of the entries we know about; the generation bump
            // is what actually guarantees correctness.
            foreach (var key in _imageNameByPid.Keys)
            {
                if (key.Pid == pid)
                {
                    _imageNameByPid.TryRemove(key, out _);
                }
            }
        }
    }

    /// <summary>Drops every cached image name.</summary>
    public void InvalidateAll()
    {
        Interlocked.Increment(ref _cacheGeneration);
        _imageNameByPid.Clear();
    }

    /// <summary>Back-compat alias for <see cref="InvalidateAll"/>.</summary>
    public void ClearCache() => InvalidateAll();

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

    /// <summary>Reads the image name for a pid through the generation-keyed cache.</summary>
    public string ResolveImageName(int pid)
    {
        var generation = Interlocked.Read(ref _cacheGeneration);
        if (_imageNameByPid.TryGetValue((pid, generation), out var cached))
        {
            return cached;
        }

        var resolved = QueryImageName(pid);
        _imageNameByPid[(pid, generation)] = resolved;
        Interlocked.Increment(ref _imageNameResolutions);
        return resolved;
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
    public bool IsStillSameWindow(WindowIdentity recorded, bool requireVisible = true) =>
        Revalidate(recorded, requireVisible).IsSame;

    /// <summary>
    /// Revalidates the COMPLETE recorded identity, reporting which part failed.
    ///
    /// The full check is the point. A pid + class check would accept a recycled HWND
    /// whose pid was reused by a different executable of the same class name, which
    /// is exactly the recycle scenario this module must fail closed on. The process
    /// image is therefore re-resolved and compared, not inherited from the cache
    /// entry captured at acquisition time.
    /// </summary>
    public IdentityVerdict Revalidate(WindowIdentity recorded, bool requireVisible = true)
    {
        if (!recorded.IsPresent)
        {
            return IdentityVerdict.Fail("no recorded identity");
        }

        var handle = new IntPtr(recorded.Hwnd);
        if (!NativeWindowApi.IsWindow(handle))
        {
            return IdentityVerdict.Fail("handle is no longer a window");
        }

        NativeWindowApi.GetWindowThreadProcessId(handle, out var pid);
        var pidMatches = (int)pid == recorded.Pid;

        var className = ReadClassName(handle);
        var classMatches = string.Equals(className, recorded.ClassName, StringComparison.Ordinal);

        // Only resolve the image when the cheaper fields already agree: resolving
        // opens the process, and there is no point paying for it on a handle we have
        // already rejected for a different reason.
        var imageMatches = false;
        var image = recorded.ProcessImageName;
        if (pidMatches && classMatches)
        {
            image = ResolveImageName((int)pid);
            imageMatches = string.Equals(image, recorded.ProcessImageName, StringComparison.Ordinal);
        }

        var visibleEnough = !requireVisible || NativeWindowApi.IsWindowVisible(handle);

        var isSame = pidMatches && classMatches && imageMatches && visibleEnough;
        var failure = isSame
            ? string.Empty
            : !pidMatches ? "pid changed"
            : !classMatches ? $"class changed ('{className}' != '{recorded.ClassName}')"
            : !imageMatches ? $"process image changed ('{image}' != '{recorded.ProcessImageName}')"
            : "window is no longer visible";

        return new IdentityVerdict(isSame, true, pidMatches, imageMatches, classMatches, visibleEnough, failure);
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
