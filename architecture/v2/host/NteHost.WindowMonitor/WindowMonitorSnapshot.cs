namespace NteHost.WindowMonitor;

/// <summary>
/// The narrow read contract V2-2A exposes. Consumers outside this module see only
/// this shape - never a raw hook, never a Win32 handle they could misuse.
/// </summary>
public sealed record WindowMonitorSnapshot
{
    /// <summary>Target HWND, or 0 when no target is currently held.</summary>
    public long TargetHwnd { get; init; }

    /// <summary>Owning process id of the target window, or 0.</summary>
    public int TargetPid { get; init; }

    /// <summary>The window that currently has foreground, or 0.</summary>
    public long ForegroundHwnd { get; init; }

    /// <summary>
    /// True only when the held target passed a fresh liveness + identity check.
    /// A destroyed or recycled handle always reports false.
    /// </summary>
    public bool IsTargetAlive { get; init; }

    /// <summary>True only when the live target window is the foreground window.</summary>
    public bool IsTargetForeground { get; init; }

    /// <summary>
    /// Increments on every acquisition of a target window. A destroy/recreate cycle
    /// therefore always produces a strictly greater generation.
    /// </summary>
    public long Generation { get; init; }

    /// <summary>Monotonic observation time in the shared QPC nanosecond domain.</summary>
    public long ObservedAtNs { get; init; }

    /// <summary>Human-readable cause of this snapshot, e.g. "initial-scan".</summary>
    public string Reason { get; init; } = string.Empty;

    /// <summary>Target identity detail, or null when no target is held.</summary>
    public WindowIdentity? TargetIdentity { get; init; }
}
