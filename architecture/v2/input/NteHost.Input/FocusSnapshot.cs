namespace NteHost.Input;

/// <summary>
/// Point-in-time focus/target identity at the instant a guard decision is taken.
///
/// All identity fields are opaque longs. V2-2B never interprets them: it only
/// compares them for equality. The provider must supply a target identity token
/// that changes when a window identity is destroyed and recreated; a recyclable
/// HWND must not be reused as the same token without fresh identity validation.
/// Window discovery, target lifecycle, destroy/recreate tracking and event-driven
/// focus monitoring are Integration scope and are NOT implemented here.
/// </summary>
/// <param name="IsValid">
/// False when the provider cannot produce a trustworthy snapshot at all
/// (no target known, provider unavailable, query failed). The guard fails closed.
/// </param>
/// <param name="TargetId">Opaque identity of the target the guard is acting on.</param>
/// <param name="ForegroundId">Opaque identity of whatever currently owns the foreground.</param>
/// <param name="Epoch">
/// Provider-assigned monotonic counter that advances whenever the provider
/// observes a focus transition. Requiring the final precheck to see the same
/// epoch as the first precheck makes focus flap fail closed: focus leaving and
/// returning between the two prechecks is still rejected.
///
/// LIMITATION (recorded honestly): an epoch produced by a *sampling* provider can
/// only detect a change that is still visible at sample time. Detecting a full
/// flap that opens and closes between two samples requires the event-driven
/// monitor owned by V2-2A. V2-2B therefore proves full flap rejection against the
/// injected fake, and sample-to-sample change rejection against a live provider.
/// </param>
/// <param name="Sequence">Monotonic capture counter; proves the final precheck really re-queried.</param>
public readonly record struct FocusSnapshot(
    bool IsValid,
    long TargetId,
    long ForegroundId,
    long Epoch,
    long Sequence,
    long MonotonicNs);

/// <summary>
/// The ONLY thing V2-2B knows about focus. Intentionally a single method: there is
/// no subscription, no discovery, no lifecycle callback, so no V2-2A implementation
/// can leak into this module and no V2-2A code is required to test it.
/// </summary>
public interface IFocusSnapshotProvider
{
    FocusSnapshot Capture();
}

/// <summary>
/// Deterministic, injectable snapshot provider used by the targeted test matrix.
/// Not a production component: it exists so every precheck branch, including
/// focus mutation between the two prechecks, can be driven exactly and repeated.
/// </summary>
public sealed class FakeFocusSnapshotProvider : IFocusSnapshotProvider
{
    private readonly object _gate = new();
    private long _targetId = 1;
    private long _foregroundId = 1;
    private long _epoch;
    private long _sequence;
    private bool _isValid = true;

    /// <summary>Invoked with the 1-based capture index before the snapshot is built.</summary>
    public Action<long>? OnCapture { get; set; }

    public long CaptureCount { get; private set; }

    public void SetTarget(long targetId)
    {
        lock (_gate) { _targetId = targetId; }
    }

    public void SetForeground(long foregroundId)
    {
        lock (_gate)
        {
            if (_foregroundId != foregroundId)
            {
                _foregroundId = foregroundId;
                _epoch++;
            }
        }
    }

    /// <summary>Force the foreground value without advancing the epoch (models a same-window refocus).</summary>
    public void SetForegroundWithoutEpoch(long foregroundId)
    {
        lock (_gate) { _foregroundId = foregroundId; }
    }

    public void SetValid(bool isValid)
    {
        lock (_gate) { _isValid = isValid; }
    }

    public void BumpEpoch()
    {
        lock (_gate) { _epoch++; }
    }

    public FocusSnapshot Capture()
    {
        long index;
        lock (_gate) { index = ++_sequence; CaptureCount = index; }

        OnCapture?.Invoke(index);

        lock (_gate)
        {
            return new FocusSnapshot(
                _isValid,
                _targetId,
                _foregroundId,
                _epoch,
                _sequence,
                TraceClock.NowNs());
        }
    }
}
