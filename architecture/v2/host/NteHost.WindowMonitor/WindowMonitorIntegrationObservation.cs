namespace NteHost.WindowMonitor;

/// <summary>
/// Atomic read result for the Integration adapter. The snapshot, derived events,
/// and raw revision fence are captured by WindowMonitor's state owner at one read
/// point; callers must not rebuild this shape by polling Snapshot() and Events
/// independently.
/// </summary>
public sealed record WindowMonitorIntegrationObservation(
    long RawRevisionBeforeBatch,
    long RawRevision,
    bool HasPendingEvents,
    long DroppedSinceLastRead,
    WindowMonitorSnapshot Snapshot,
    IReadOnlyList<WindowMonitorEvent> Events,
    IReadOnlyList<long> RawEventRevisions);
