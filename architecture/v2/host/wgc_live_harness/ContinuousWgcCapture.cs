using NteHost.Protocol;

namespace WgcLiveHarness;

/// <summary>All WGC/D3D operations, including mapping probes, run on the owner.</summary>
internal sealed class ContinuousWgcCapture : IDisposable
{
    private readonly LatestCapturePump<WgcWindowCapture, CapturedBgraFrame> _pump;
    private readonly Func<WgcWindowCapture, CapturedBgraFrame, CapturedBgraFrame> _validate;
    private readonly Action<WgcWindowCapture, MappingProbe?> _ensureMapping;
    private WgcWindowCapture? _source;
    private string? _failureClockDiagnostics;
    private readonly string _policy, _observation;
    private readonly MappingRecovery _mapping = new();
    private readonly object _summaryGate = new();
    private DeliveryVisualSummary? _latestSummary;
    private CapturedBgraFrame? _latestDiagnosticFrame;
    private OrdinaryFrameDiscard? _pendingOrdinaryExpiry;
    public OrdinaryFrameDiscard? PendingOrdinaryExpiry { get { lock (_summaryGate) return _pendingOrdinaryExpiry; } }
    public DeliveryVisualSummary? LatestSummary { get { lock (_summaryGate) return _latestSummary; } }
    public DeliveryVisualSummary? LatestScrollSummary { get { lock (_summaryGate)
        return _latestSummary is { } summary ? summary with { DiagnosticFrame = _latestDiagnosticFrame } : null; } }
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
        buffering = _pump.Statistics(), firstMappingFailure = _mapping.FirstProbe,
        failureClockDiagnosticsJson = _failureClockDiagnostics,
        maximumPrivateBgraPayloads = 6, maximumPrivateBgraBytes = 6L * 8_294_400,
        diagnosticLatestFrameSlots = 1, diagnosticRejectedSnapshotSlots = 1 };

    public ContinuousWgcCapture(IntPtr hwnd, int frameWaitMs, int intervalMs, string mode,
        Func<bool> stopped, Func<bool> targetCurrent, Action<string> unconfirmedExit,
        string capturePolicy = CapturePolicy.Strict, string observationSessionId = "",
        Action<long>? mappingRevoked = null, Action<string, MappingProbe, MappingProbe, long>? mappingTransition = null)
    {
        _policy = CapturePolicy.Parse(capturePolicy); _observation = observationSessionId;
        long lastSource = 0;
        long acquisitionSequence = 0;
        void Revoke()
        {
            lock (_summaryGate) { _latestSummary = null; _latestDiagnosticFrame = null; }
            _pump?.DiscardLatest();
            mappingRevoked?.Invoke(_mapping.Epoch);
        }
        void Ensure(WgcWindowCapture source, MappingProbe? initial = null) => _mapping.Ensure(
            source.ProbeClientAreaMapping, stopped, targetCurrent, Revoke,
            (stage, first, last) => mappingTransition?.Invoke(stage, first, last, _mapping.Epoch), initial: initial);
        _ensureMapping = Ensure;
        CapturedBgraFrame Validate(WgcWindowCapture source, CapturedBgraFrame frame, bool ordinary = false)
        {
            Ensure(source);
            if (!_mapping.IsCurrent(frame.CaptureScopeEpoch)) throw new CaptureScopeInvalidatedException();
            var comparedAtNs = ProtocolClock.NowNs();
            var rejection = _policy == CapturePolicy.Delivery ? frame.DeliveryProof?.Rejection(comparedAtNs) ??
                (frame.DeliveryProof is null ? "DELIVERY_PROOF_MISSING" : null)
                : BackgroundObservationPolicy.BackgroundReadbackRejection(mode, frame.SourceTimestampNs, frame.CaptureTimestampNs, lastSource);
            if (ordinary && _policy == CapturePolicy.Delivery && OrdinaryFrameRecovery.Recoverable(frame, comparedAtNs))
            {
                lock (_summaryGate) {
                    _pendingOrdinaryExpiry ??= OrdinaryFrameDiscard.From(frame, comparedAtNs);
                    _latestSummary = null; _latestDiagnosticFrame = null;
                    throw new OrdinaryFrameExpiredException(_pendingOrdinaryExpiry);
                }
            }
            if (rejection is not null)
                throw new InvalidOperationException($"{rejection}: source={frame.SourceTimestampNs}; readback={frame.CaptureTimestampNs}; previous={lastSource}");
            lastSource = frame.SourceTimestampNs;
            if (_policy == CapturePolicy.Delivery)
            {
                lock (_summaryGate) { _latestSummary = DeliveryVisualSummary.From(frame); _latestDiagnosticFrame = frame;
                    if (ordinary) _pendingOrdinaryExpiry = null; }
                return frame;
            }
            return frame with { AcquisitionSequence = ++acquisitionSequence };
        }
        _validate = (source, frame) => Validate(source, frame);
        _pump = new(() => _source = new WgcWindowCapture(hwnd), (source, stop) =>
        {
            Ensure(source);
            var epoch = _mapping.Epoch;
            source.EnableRequestClockDiagnostics = true;
            var requestClock = QpcClockSample.Read();
            source.RequestGateClockSample = requestClock;
            try { return Validate(source, (_policy == CapturePolicy.Delivery
                ? source.CaptureDelivered(frameWaitMs, requestClock.Nanoseconds, long.MaxValue, stop, _observation, epoch)
                : source.CaptureAfterRequest(frameWaitMs, requestClock.Nanoseconds, long.MaxValue, stop)) with { CaptureScopeEpoch = epoch }, ordinary: true); }
            catch (MappingProbeException ex) { Ensure(source, ex.Probe); throw new CaptureScopeInvalidatedException(); }
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
    public bool IsFrameCurrent(CapturedBgraFrame frame) => !IsStopped && _mapping.IsCurrent(frame.CaptureScopeEpoch);
    public bool PublishCurrent(CapturedBgraFrame frame, Action publish) => !IsStopped && _mapping.Publish(frame.CaptureScopeEpoch, publish);
    public string FailureReason(string fallback) => _pump.FailureException is { } failure ? CaptureFailure.Reason(failure, fallback) : fallback;
    public CapturedBgraFrame Capture(int timeoutMs)
    {
        var frame = _pump.Take(timeoutMs);
        if (!IsFrameCurrent(frame)) throw new CaptureScopeInvalidatedException();
        return frame;
    }
    public void ThrowIfFailed()
    {
        if (_pump.FailureException is { } failure)
            throw new InvalidOperationException($"capture-owner-unavailable; clockDiagnostic={_failureClockDiagnostics}", failure);
    }
    public CapturedBgraFrame CaptureAfterRequest(int timeoutMs, long requestNs, long deadlineNs, Func<bool> stopped, QpcClockSample? requestClock = null)
    {
        return _pump.Invoke((source, stop) =>
        {
            if (stop() || stopped()) throw new OperationCanceledException("source-request-cancelled");
            _ensureMapping(source, null);
            var epoch = _mapping.Epoch;
            source.EnableRequestClockDiagnostics = EnableRequestClockDiagnostics;
            source.RequestGateClockSample = requestClock;
            try { var frame = _policy == CapturePolicy.Delivery
                    ? source.CaptureDelivered(timeoutMs, requestNs, deadlineNs, () => stop() || stopped(), _observation, epoch)
                    : source.CaptureAfterRequest(timeoutMs, requestNs, deadlineNs, () => stop() || stopped());
                return _validate(source, frame with { CaptureScopeEpoch = epoch }); }
            catch (MappingProbeException ex) { _ensureMapping(source, ex.Probe); throw new CaptureScopeInvalidatedException(); }
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
        return _pump.Invoke((source, _) => { _ensureMapping(source, null); return true; }, 6000);
    }
    public void Dispose() { _pump.Dispose(); lock (_summaryGate) { _latestSummary = null; _latestDiagnosticFrame = null; } }
    public void InvalidateScope()
    {
        _mapping.Invalidate(() => { lock (_summaryGate) { _latestSummary = null; _latestDiagnosticFrame = null; } _pump.DiscardLatest(); });
    }
}
