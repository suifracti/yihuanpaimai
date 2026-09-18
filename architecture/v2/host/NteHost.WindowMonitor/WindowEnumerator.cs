using NteHost.WindowMonitor.Win32;

namespace NteHost.WindowMonitor;

/// <summary>
/// Top-level window discovery.
///
/// This is the RECOVERY path, not the steady-state path. It is invoked only on
/// start-up, after a loss, and when the event queue overflowed. It is never run on
/// a timer, so the module cannot degrade into high-frequency busy polling.
/// </summary>
public sealed class WindowEnumerator
{
    private readonly WindowIdentityReader _identityReader;

    public WindowEnumerator(WindowIdentityReader identityReader)
    {
        _identityReader = identityReader;
    }

    /// <summary>Number of full top-level enumerations performed.</summary>
    public long EnumerationCount => _enumerationCount;

    private long _enumerationCount;

    /// <summary>
    /// Enumerates top-level windows and returns the identities that satisfy the spec.
    /// Ordered by HWND so the result is deterministic when several candidates exist.
    ///
    /// The cheap class-name read runs first and acts as a filter, so a full process
    /// image resolution (which requires opening the process) only happens for the
    /// handful of windows that could possibly match. A recovery scan therefore does
    /// not touch every process on the desktop.
    /// </summary>
    public IReadOnlyList<WindowIdentity> FindMatches(TargetWindowSpec spec, bool requireVisible = true)
    {
        Interlocked.Increment(ref _enumerationCount);

        var handles = new List<long>();
        NativeWindowApi.EnumWindows((hwnd, _) =>
        {
            handles.Add(hwnd.ToInt64());
            return true;
        }, IntPtr.Zero);

        var matches = new List<WindowIdentity>();
        foreach (var handle in handles)
        {
            var className = _identityReader.ReadClassNameOnly(handle);
            if (string.IsNullOrEmpty(className) ||
                !string.Equals(className, spec.WindowClass, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var identity = _identityReader.Read(handle);
            if (!identity.IsPresent)
            {
                continue;
            }
            if (!spec.Matches(identity.ProcessImageName, identity.ClassName))
            {
                continue;
            }
            // Apply the same visibility rule the validator uses, otherwise a hidden
            // window would be adopted here and rejected a moment later, producing a
            // spurious acquire/loss pair and an inflated generation count.
            if (requireVisible && !identity.IsVisible)
            {
                continue;
            }
            matches.Add(identity);
        }

        matches.Sort((a, b) => a.Hwnd.CompareTo(b.Hwnd));
        return matches;
    }

    /// <summary>Reads the identity of a specific handle, used to promote an event HWND.</summary>
    public WindowIdentity Read(long hwnd) => _identityReader.Read(hwnd);
}
