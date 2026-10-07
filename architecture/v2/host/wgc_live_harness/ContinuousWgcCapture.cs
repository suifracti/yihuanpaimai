using NteHost.Protocol;

namespace WgcLiveHarness;

/// <summary>All WGC/D3D operations, including mapping probes, run on the owner.</summary>
internal sealed class ContinuousWgcCapture : IDisposable
{
    private readonly LatestCapturePump<WgcWindowCapture, CapturedBgraFrame> _pump;
    private readonly Func<WgcWindowCapture, CapturedBgraFrame, CapturedBgraFrame> _validate;
    private WgcWindowCapture? _source;
    private string? _failureClockDiagnostics;
    private readonly string _policy, _observation;
    private long _epoch = 1;
    private readonly object _summaryGate = new();
    private DeliveryVisualSummary? _latestSummary;
    public DeliveryVisualSummary? LatestSummary { get { lock (_summaryGate) return _latestSummary; } }
    public int Width { get; }
    public int Height { get; }
    public int CaptureItemWidth { get; }
    public int CaptureItemHeight { get; }
    public int ClientOffsetX { get; }
    public int ClientOffsetY { get; }
    public bool EnableRequestClockDiagnostics { get; set; }
    public string? LastRequestClockDiagnosticsJson { get; private set; }
    public bool IsStopped => _pump.IsStopped;
    public string? Failure => _pump.Failure;
    public object Statistics() => new { completedReadbacks = _source?.CompletedReadbacks ?? 0,
        buffering = _pump.Statistics(), failureClockDiagnosticsJson = _failureClockDiagnostics,
        maximumPrivateBgraPayloads = 4, maximumPrivateBgraBytes = 4L * 8_294_400 };

    public ContinuousWgcCapture(IntPtr hwnd, int frameWaitMs, int intervalMs, string mode,
        Func<bool> stopped, Func<bool> targetCurrent, Action<string> unconfirmedExit,
        string capturePolicy = CapturePolicy.Strict, string observationSessionId = "")
    {
        _policy = CapturePolicy.Parse(capturePolicy); _observation = observationSessionId;
        long lastSource = 0;
        long acquisitionSequence = 0;
        CapturedBgraFrame Validate(WgcWindowCapture source, CapturedBgraFrame frame)
        {
            if (!targetCurrent()) throw new InvalidOperationException("capture-target-invalid");
            if (!source.IsClientAreaMappingCurrent()) throw new InvalidOperationException("client-area-mapping-changed");
            var rejection = _policy == CapturePolicy.Delivery ? frame.DeliveryProof?.Rejection(ProtocolClock.NowNs()) ??
                (frame.DeliveryProof is null ? "DELIVERY_PROOF_MISSING" : null)
                : BackgroundObservationPolicy.BackgroundReadbackRejection(mode, frame.SourceTimestampNs, frame.CaptureTimestampNs, lastSource);
            if (rejection is not null)
                throw new InvalidOperationException($"{rejection}: source={frame.SourceTimestampNs}; readback={frame.CaptureTimestampNs}; previous={lastSource}");
            lastSource = frame.SourceTimestampNs;
            if (_policy == CapturePolicy.Delivery)
            {
                lock (_summaryGate) _latestSummary = DeliveryVisualSummary.From(frame);
                return frame;
            }
            return frame with { AcquisitionSequence = ++acquisitionSequence };
        }
        _validate = Validate;
        _pump = new(() => _source = new WgcWindowCapture(hwnd), (source, stop) =>
        {
            if (!targetCurrent()) throw new InvalidOperationException("capture-target-invalid");
            source.EnableRequestClockDiagnostics = true;
            var requestClock = QpcClockSample.Read();
            source.RequestGateClockSample = requestClock;
            try { return Validate(source, _policy == CapturePolicy.Delivery
                ? source.CaptureDelivered(frameWaitMs, requestClock.Nanoseconds, long.MaxValue, stop, _observation, Volatile.Read(ref _epoch))
                : source.CaptureAfterRequest(frameWaitMs, requestClock.Nanoseconds, long.MaxValue, stop)); }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _failureClockDiagnostics = _policy == CapturePolicy.Delivery ? source.LastDeliveryDiagnosticJson : source.LastRequestClockDiagnosticsJson;
                throw;
            }
            finally { source.RequestGateClockSample = null; source.EnableRequestClockDiagnostics = false; }
        }, stopped, intervalMs, unconfirmedExit);
        try
        {
            var geometry = _pump.Invoke((source, _) => (source.Width, source.Height,
                source.CaptureItemWidth, source.CaptureItemHeight, source.ClientOffsetX, source.ClientOffsetY), 2000);
            (Width, Height, CaptureItemWidth, CaptureItemHeight, ClientOffsetX, ClientOffsetY) = geometry;
        }
        catch { _pump.Dispose(); throw; }
    }
    public CapturedBgraFrame Capture(int timeoutMs) => _pump.Take(timeoutMs);
    public void ThrowIfFailed()
    {
        if (_pump.FailureException is { } failure)
            throw new InvalidOperationException($"capture-owner-unavailable; clockDiagnostic={_failureClockDiagnostics}", failure);
    }
    public CapturedBgraFrame CaptureAfterRequest(int timeoutMs, long requestNs, long deadlineNs, Func<bool> stopped, QpcClockSample? requestClock = null)
    {
        return _pump.Invoke((source, stop) =>
        {
            source.EnableRequestClockDiagnostics = EnableRequestClockDiagnostics;
            source.RequestGateClockSample = requestClock;
            try { var frame = _policy == CapturePolicy.Delivery
                    ? source.CaptureDelivered(timeoutMs, requestNs, deadlineNs, () => stop() || stopped(), _observation, Volatile.Read(ref _epoch))
                    : source.CaptureAfterRequest(timeoutMs, requestNs, deadlineNs, () => stop() || stopped());
                return _validate(source, frame); }
            finally { LastRequestClockDiagnosticsJson = _policy == CapturePolicy.Delivery ? source.LastDeliveryDiagnosticJson : source.LastRequestClockDiagnosticsJson; source.EnableRequestClockDiagnostics = false; source.RequestGateClockSample = null; }
        }, timeoutMs + 100, discardLatest: true);
    }
    public bool IsClientAreaMappingCurrent()
    {
        // A dead owner is not a negative geometry measurement. Invoke keeps
        // the original capture failure; false is reserved for a real probe.
        ThrowIfFailed();
        if (IsStopped)
            throw new InvalidOperationException($"capture-owner-unavailable: {Failure}; clockDiagnostic={_failureClockDiagnostics}", _pump.FailureException);
        return _pump.Invoke((source, _) => source.IsClientAreaMappingCurrent(), _policy == CapturePolicy.Delivery ? 6000 : 2000);
    }
    public void Dispose() => _pump.Dispose();
    public void InvalidateScope()
    {
        Interlocked.Increment(ref _epoch);
        lock (_summaryGate) _latestSummary = null;
        _pump.Invoke((_, _) => true, 2000, discardLatest: true);
    }
}
