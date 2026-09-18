namespace NteHost.WindowMonitor;

/// <summary>
/// The closed set of transitions V2-2A can report. Keeping this an enum (rather
/// than free-form strings) means a consumer cannot silently miss a new transition.
/// </summary>
public enum WindowMonitorEventKind
{
    /// <summary>A target window was found and taken into custody for the first time.</summary>
    TargetAcquired,

    /// <summary>The held target window went away (destroyed, hidden, or identity changed).</summary>
    TargetLost,

    /// <summary>A target window was found again after a loss, or after a destroy/recreate.</summary>
    TargetReacquired,

    /// <summary>The live target window became the foreground window.</summary>
    ForegroundGained,

    /// <summary>The live target window stopped being the foreground window.</summary>
    ForegroundLost,

    /// <summary>
    /// A handle the module was holding failed liveness or identity validation and
    /// was rejected. This is the fail-closed path; it always accompanies a loss.
    /// </summary>
    StaleHandleRejected,

    /// <summary>
    /// A recovery scan was performed. Emitted so the recovery path is observable and
    /// so a test can prove the module is not busy-polling.
    /// </summary>
    RecoveryScanPerformed,

    /// <summary>The hook callback queue overflowed and records were dropped.</summary>
    EventQueueOverflow,
}

/// <summary>
/// A single observed transition with everything needed to audit it later.
/// </summary>
public sealed record WindowMonitorEvent
{
    /// <summary>Monotonic per-monitor event sequence, starting at 1.</summary>
    public long Sequence { get; init; }

    public WindowMonitorEventKind Kind { get; init; }

    /// <summary>The WinEvent that caused this event, or "synthetic"/"scan" for non-hook causes.</summary>
    public string SourceEvent { get; init; } = string.Empty;

    public long TargetHwnd { get; init; }

    public int TargetPid { get; init; }

    public long ForegroundHwnd { get; init; }

    public bool IsTargetAlive { get; init; }

    public bool IsTargetForeground { get; init; }

    public long Generation { get; init; }

    /// <summary>Monotonic observation time in the shared QPC nanosecond domain.</summary>
    public long ObservedAtNs { get; init; }

    public string Reason { get; init; } = string.Empty;
}
