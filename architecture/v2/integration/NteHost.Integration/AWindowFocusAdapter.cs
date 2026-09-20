using System.Globalization;
using System.Text;
using System.Security.Cryptography;
using NteHost.Input;
using NteHost.WindowMonitor;

namespace NteHost.Integration;

/// <summary>
/// Converts A's identity-bearing snapshot/event vocabulary into B's narrow focus
/// provider contract. A.Generation is retained only as provenance; B.Epoch is a
/// separate counter owned here and advances for every observed focus/lifecycle
/// transition, including a complete leave-and-return flap.
/// </summary>
public sealed class AWindowFocusAdapter
{
    private readonly IWindowObservationSource _source;
    private readonly object _gate = new();
    private long _lastRawRevision;
    private long _focusEpoch;
    private long _captureSequence;
    private long? _lastTargetId;
    private IntegrationFocusView _last = new(
        false, "NO_CAPTURE", 0, 0, 0, 0, 0, 0, false, false, true, null,
        Array.Empty<IntegrationWindowEvent>());

    /// <summary>
    /// Called after a batch is interpreted and before the resulting snapshot is
    /// returned. The coordinator uses it to freeze C on a broken source fence or
    /// identity/focus transition. It must never call B.Cancel while B holds its
    /// final-precheck gate; the provider itself fails closed on the next check.
    /// </summary>
    public Action<IntegrationFocusView>? ObservationAccepted { get; set; }

    public AWindowFocusAdapter(IWindowObservationSource source)
    {
        _source = source ?? throw new ArgumentNullException(nameof(source));
    }

    public IntegrationFocusView Last
    {
        get { lock (_gate) return _last; }
    }

    public long FocusEpoch
    {
        get { lock (_gate) return _focusEpoch; }
    }

    public IntegrationFocusView CaptureView()
    {
        IntegrationWindowObservation observation;
        try
        {
            observation = _source.Read();
        }
        catch (Exception ex)
        {
            return Publish(new IntegrationFocusView(
                false, $"SOURCE_EXCEPTION:{ex.GetType().Name}", 0, 0, _focusEpoch,
                ++_captureSequence, 0, _lastRawRevision, false, false, true, null,
                Array.Empty<IntegrationWindowEvent>()));
        }

        IntegrationFocusView view;
        Action<IntegrationFocusView>? callback;
        lock (_gate)
        {
            long capture = ++_captureSequence;
            bool fenceBroken = observation.Overflowed
                || observation.HasPendingEvents
                || observation.HasGap
                || observation.RawRevision < _lastRawRevision;

            if (!fenceBroken)
            {
                _lastRawRevision = observation.RawRevision;
            }
            else
            {
                // The source is no longer trustworthy for this action. Latch the
                // latest revision for diagnostics, but never reconstruct missing
                // transitions by polling or sleeping.
                _lastRawRevision = Math.Max(_lastRawRevision, observation.RawRevision);
            }

            bool focusChanged = false;
            foreach (var item in observation.Events)
            {
                if (IsFocusOrLifecycleTransition(item.Event.Kind))
                {
                    _focusEpoch++;
                    focusChanged = true;
                }
            }

            WindowIdentity? identity = observation.Snapshot.TargetIdentity;
            long targetId = identity is { IsPresent: true }
                ? WindowIdentityToken.For(identity)
                : 0;
            bool identityChanged = _lastTargetId is not null
                && targetId != 0
                && targetId != _lastTargetId.Value;

            bool usable = !fenceBroken
                && observation.Snapshot.IsTargetAlive
                && identity is { IsPresent: true }
                && targetId != 0;

            long foregroundId = usable && observation.Snapshot.IsTargetForeground
                && observation.Snapshot.ForegroundHwnd == observation.Snapshot.TargetHwnd
                ? targetId
                : 0;

            string reason = fenceBroken
                ? DescribeFence(observation)
                : !observation.Snapshot.IsTargetAlive
                    ? "TARGET_NOT_ALIVE"
                    : identity is null || !identity.IsPresent
                        ? "TARGET_IDENTITY_MISSING"
                        : "OK";

            view = new IntegrationFocusView(
                usable,
                reason,
                targetId,
                foregroundId,
                _focusEpoch,
                capture,
                observation.Snapshot.Generation,
                observation.RawRevision,
                identityChanged,
                focusChanged,
                fenceBroken,
                identity,
                observation.Events);

            _lastTargetId = targetId == 0 ? _lastTargetId : targetId;
            _last = view;
            callback = ObservationAccepted;
        }

        // Invoke outside the adapter lock. The callback is deliberately
        // diagnostic/policy-only; B's provider receives this same view.
        callback?.Invoke(view);
        return view;
    }

    private IntegrationFocusView Publish(IntegrationFocusView view)
    {
        Action<IntegrationFocusView>? callback;
        lock (_gate)
        {
            _last = view;
            callback = ObservationAccepted;
        }

        callback?.Invoke(view);
        return view;
    }

    private static bool IsFocusOrLifecycleTransition(WindowMonitorEventKind kind) =>
        kind is WindowMonitorEventKind.ForegroundLost
            or WindowMonitorEventKind.ForegroundGained
            or WindowMonitorEventKind.TargetLost
            or WindowMonitorEventKind.TargetReacquired
            or WindowMonitorEventKind.StaleHandleRejected
            or WindowMonitorEventKind.EventQueueOverflow;

    private static string DescribeFence(IntegrationWindowObservation observation)
    {
        if (observation.Overflowed)
        {
            return $"SOURCE_OVERFLOW:{observation.DroppedSinceLastRead}";
        }

        if (observation.HasPendingEvents)
        {
            return "SOURCE_PENDING_EVENTS";
        }

        if (observation.HasGap)
        {
            return $"SOURCE_REVISION_GAP:{observation.RawRevisionBeforeBatch}->{observation.RawRevision}";
        }

        return "SOURCE_REVISION_REGRESSED";
    }
}

/// <summary>Stable B target identity derived from A's full identity, not HWND alone.</summary>
public static class WindowIdentityToken
{
    public static long For(WindowIdentity identity)
    {
        string material = string.Join("|", identity.Hwnd.ToString(CultureInfo.InvariantCulture),
            identity.Pid.ToString(CultureInfo.InvariantCulture), identity.ProcessImageName,
            identity.ClassName, identity.ProcessInstanceToken.ToString(CultureInfo.InvariantCulture));
        byte[] digest = SHA256.HashData(Encoding.UTF8.GetBytes(material));
        long token = BitConverter.ToInt64(digest, 0) & long.MaxValue;
        return token == 0 ? 1 : token;
    }
}

/// <summary>B provider backed by the A adapter and the independent C session gate.</summary>
public sealed class IntegrationFocusSnapshotProvider : IFocusSnapshotProvider
{
    private readonly AWindowFocusAdapter _adapter;
    private readonly Func<bool> _cPermission;

    public IntegrationFocusSnapshotProvider(AWindowFocusAdapter adapter, Func<bool> cPermission)
    {
        _adapter = adapter;
        _cPermission = cPermission;
    }

    public FocusSnapshot Capture()
    {
        if (!_cPermission())
        {
            return default;
        }

        IntegrationFocusView view = _adapter.CaptureView();
        return view.IsValid ? view.ToFocusSnapshot(TraceClock.NowNs()) : default;
    }
}
