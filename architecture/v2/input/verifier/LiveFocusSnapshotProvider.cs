namespace NteHost.Input.Verifier;

/// <summary>
/// Verification-harness focus provider for the live controlled-window scenarios.
///
/// Scope discipline: this is a SNAPSHOT reader, not a monitor. It performs no
/// window discovery, subscribes to no events, tracks no lifecycle, and knows
/// nothing about which window is "the game". Production focus wiring is deferred
/// to the V2-2A/V2-2B integration PR; this type exists so the live scenarios can
/// satisfy the guard's narrow <see cref="IFocusSnapshotProvider"/> contract without
/// pulling any V2-2A implementation into V2-2B.
/// </summary>
internal sealed class LiveFocusSnapshotProvider : IFocusSnapshotProvider
{
    private readonly object _gate = new();
    private readonly long _targetId;
    private long _lastForeground = long.MinValue;
    private long _epoch;
    private long _sequence;

    public LiveFocusSnapshotProvider(long targetId)
    {
        _targetId = targetId;
    }

    public long EpochTransitions
    {
        get { lock (_gate) { return _epoch; } }
    }

    public FocusSnapshot Capture()
    {
        long foreground = (long)ControlledWindowNativeMethods.GetForegroundWindow();

        lock (_gate)
        {
            if (_lastForeground != foreground)
            {
                _lastForeground = foreground;
                _epoch++;
            }

            _sequence++;
            return new FocusSnapshot(true, _targetId, foreground, _epoch, _sequence, TraceClock.NowNs());
        }
    }
}
