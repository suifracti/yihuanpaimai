using System.Text.Json.Serialization;

namespace WgcLiveHarness;

[JsonConverter(typeof(JsonStringEnumConverter))]
internal enum MappingState { Current, Unavailable, Changed, TargetInvalid, Stopped }
internal sealed record MappingGeometry(int ItemWidth, int ItemHeight, int ClientWidth, int ClientHeight,
    int OffsetX, int OffsetY);
internal sealed record MappingMeasurement(int? ItemWidth = null, int? ItemHeight = null,
    int? ClientWidth = null, int? ClientHeight = null, int? ClientOriginX = null, int? ClientOriginY = null,
    int? BoundsLeft = null, int? BoundsTop = null, int? BoundsWidth = null, int? BoundsHeight = null);
internal sealed record MappingProbe(MappingState State, string Stage, MappingGeometry Expected,
    MappingMeasurement? Observed, string BoundsSource, string? Error = null)
{
    public string Reason => State switch {
        MappingState.Unavailable => "client-area-mapping-probe-unavailable",
        MappingState.Changed => "client-area-mapping-changed-rebind-unsupported",
        MappingState.TargetInvalid => "capture-target-invalid",
        MappingState.Stopped => "explicit-stop",
        _ => "client-area-mapping-current",
    };
    public static MappingProbe Compare(MappingGeometry expected, MappingMeasurement observed, string source)
    {
        if (observed.ItemWidth is null || observed.ItemHeight is null || observed.ClientWidth is null
            || observed.ClientHeight is null || observed.ClientOriginX is null || observed.ClientOriginY is null
            || observed.BoundsLeft is null || observed.BoundsTop is null || observed.BoundsWidth is null || observed.BoundsHeight is null)
            return new(MappingState.Unavailable, "partial-measurement", expected, observed, source);
        var matches = observed.ItemWidth == expected.ItemWidth && observed.ItemHeight == expected.ItemHeight
            && observed.ClientWidth == expected.ClientWidth && observed.ClientHeight == expected.ClientHeight
            && observed.BoundsWidth == expected.ItemWidth && observed.BoundsHeight == expected.ItemHeight
            && (long?)observed.ClientOriginX - observed.BoundsLeft == expected.OffsetX
            && (long?)observed.ClientOriginY - observed.BoundsTop == expected.OffsetY;
        return new(matches ? MappingState.Current : MappingState.Changed, "compare", expected, observed, source);
    }
}
internal sealed class MappingProbeException(MappingProbe probe) : Exception(probe.Reason)
{
    public MappingProbe Probe { get; } = probe;
}
internal sealed class MappingRejectedException(string reason, MappingProbe first, MappingProbe last) : Exception(reason)
{
    public MappingProbe FirstProbe { get; } = first;
    public MappingProbe LastProbe { get; } = last;
}
internal sealed class CaptureScopeInvalidatedException() : OperationCanceledException("capture-scope-invalidated");

/// <summary>Owner-only probes; readers/publication share the scope lock. No capture, window or input API.</summary>
internal sealed class MappingRecovery
{
    public const int MaxProbeAttempts = 40;
    public const int RetryWindowMs = 2000;
    private readonly object _gate = new();
    private long _epoch = 1;
    private bool _paused;
    private MappingProbe? _first;
    private MappingProbe? _last;
    public long Epoch { get { lock (_gate) return _epoch; } }
    public MappingProbe? FirstProbe { get { lock (_gate) return _first; } }
    public bool IsCurrent(long epoch) { lock (_gate) return !_paused && epoch == _epoch; }
    public bool Publish(long epoch, Action publish)
    {
        lock (_gate) { if (_paused || epoch != _epoch) return false; publish(); return true; }
    }
    public void Invalidate(Action revoke)
    {
        lock (_gate) { _epoch++; revoke(); }
    }
    public void Ensure(Func<MappingProbe> probe, Func<bool> stopped, Func<bool> identityCurrent,
        Action revoke, Action<string, MappingProbe, MappingProbe> transition,
        Func<long>? clock = null, Action<int>? wait = null, MappingProbe? initial = null)
    {
        clock ??= () => Environment.TickCount64;
        wait ??= Thread.Sleep;
        MappingProbe Read()
        {
            var boundary = initial ?? _last ?? _first ?? new MappingProbe(MappingState.Unavailable, "before-probe",
                new(0, 0, 0, 0, 0, 0), null, "not-probed");
            if (stopped()) return boundary with { State = MappingState.Stopped, Stage = "stop" };
            if (!identityCurrent()) return boundary with { State = MappingState.TargetInvalid, Stage = "target-identity" };
            var measured = initial ?? probe(); initial = null;
            _last = measured;
            // Recheck both after a potentially slow OS measurement.
            if (stopped()) return measured with { State = MappingState.Stopped, Stage = "stop-after-probe" };
            if (!identityCurrent()) return measured with { State = MappingState.TargetInvalid, Stage = "target-identity-after-probe" };
            return measured;
        }
        var result = Read();
        if (result.State == MappingState.Current) return;
        lock (_gate) { _first ??= result; _paused = true; _epoch++; revoke(); }
        var first = result;
        transition("suspended", first, result);
        var deadline = checked(clock() + RetryWindowMs);
        int attempts = 0;
        while (result.State == MappingState.Unavailable && attempts++ < MaxProbeAttempts && clock() < deadline)
        {
            wait((int)Math.Min(50, Math.Max(1, deadline - clock())));
            result = Read();
            if (result.State == MappingState.Current && clock() < deadline)
            {
                // The successful probe and identity check both occurred after revocation.
                lock (_gate) _paused = false;
                transition("recovered", first, result);
                return;
            }
            if (result.State == MappingState.Current)
                result = result with { State = MappingState.Unavailable, Stage = "reprobe-after-deadline" };
        }
        var reason = result.State == MappingState.Unavailable ? "client-area-mapping-probe-deadline" : result.Reason;
        transition(reason, first, result);
        throw new MappingRejectedException(reason, first, result);
    }
}
