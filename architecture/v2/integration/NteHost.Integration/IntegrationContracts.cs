using NteHost.WindowMonitor;
using NteHost.Input;

namespace NteHost.Integration;

/// <summary>
/// A raw-revision fence supplied by the Integration source adapter. Accepted A
/// snapshots/events do not contain this fence, so a future production bridge must
/// supply it from the event/lifecycle source rather than infer it from WaitForIdle.
/// </summary>
public sealed record IntegrationWindowObservation(
    long RawRevision,
    long RawRevisionBeforeBatch,
    bool HasPendingEvents,
    long DroppedSinceLastRead,
    WindowMonitorSnapshot Snapshot,
    IReadOnlyList<IntegrationWindowEvent> Events)
{
    public bool HasGap => Events.Count > 0
        ? Events[0].RawRevision != RawRevisionBeforeBatch + 1
          || Events[^1].RawRevision != RawRevision
        : RawRevision != RawRevisionBeforeBatch;

    public bool Overflowed => DroppedSinceLastRead > 0;
}

/// <summary>One A-derived transition with the source revision that carried it.</summary>
public sealed record IntegrationWindowEvent(
    long RawRevision,
    WindowMonitorEvent Event);

public interface IWindowObservationSource
{
    IntegrationWindowObservation Read();
}

public sealed record IntegrationFocusView(
    bool IsValid,
    string Reason,
    long TargetId,
    long ForegroundId,
    long FocusEpoch,
    long CaptureSequence,
    long AGeneration,
    long SourceRevision,
    bool IdentityChanged,
    bool FocusChanged,
    bool SourceFenceBroken,
    WindowIdentity? Identity,
    IReadOnlyList<IntegrationWindowEvent> Events)
{
    public FocusSnapshot ToFocusSnapshot(long monotonicNs) =>
        new(
            IsValid,
            TargetId,
            ForegroundId,
            FocusEpoch,
            CaptureSequence,
            monotonicNs);
}
