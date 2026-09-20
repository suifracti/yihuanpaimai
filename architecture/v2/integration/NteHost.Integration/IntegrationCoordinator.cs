using NteHost.Freeze;
using NteHost.Input;

namespace NteHost.Integration;

public sealed record IntegrationArmResult(
    bool Ok,
    string Reason,
    long SessionGeneration,
    long TargetId,
    long FocusEpoch,
    long AGeneration,
    long SourceRevision);

public sealed record IntegrationActionResult(
    bool Ok,
    string Reason,
    bool CPermissionPassed,
    bool CCommitOccurred,
    bool CActuatorReportedSuccess,
    InputActionOutcome? BOutcome,
    long RawSendCallDelta,
    long RawAcceptedDelta,
    long SessionGeneration,
    long TargetId,
    long FocusEpoch,
    IReadOnlyList<FreezeReason> ActiveFreezeReasons,
    string? CLastActuatorError);

/// <summary>
/// Offline-only A/B/C integration seam. It keeps one action under a coordinator
/// fence: C's atomic permission/commit invokes B, and B's final focus/ticket gate
/// is the last boundary before the raw backend. A source failure never becomes an
/// implicit allow. A post-commit freeze is recorded but cannot retract a raw call.
/// </summary>
public sealed class IntegrationCoordinator : IDisposable
{
    private sealed class IntegrationActuatorRejectedException : Exception
    {
        public IntegrationActuatorRejectedException(string reason) : base(reason) { }
    }

    private readonly object _actionFence = new();
    private readonly IInputObserver _observer;
    private readonly IRawInputBackend _raw;
    private readonly CArbitratedRawInputBackend _arbitratedRaw;
    private readonly AWindowFocusAdapter _adapter;
    private readonly IntegrationFocusSnapshotProvider _focusProvider;
    private readonly InputSafetyGuard _guard;
    private readonly FreezeCoordinator _freeze;
    private bool _sessionReady;
    private bool _disposed;

    public IntegrationCoordinator(
        IWindowObservationSource source,
        IInputObserver observer,
        ICursorBackend cursor,
        IRawInputBackend raw,
        IInputTraceSink trace,
        long sessionGeneration = 1,
        InputSafetyOptions? inputOptions = null)
    {
        _observer = observer ?? throw new ArgumentNullException(nameof(observer));
        _raw = raw ?? throw new ArgumentNullException(nameof(raw));
        _adapter = new AWindowFocusAdapter(source ?? throw new ArgumentNullException(nameof(source)));
        _freeze = new FreezeCoordinator(sessionGeneration);
        _focusProvider = new IntegrationFocusSnapshotProvider(_adapter, () => _freeze.ScanPermitted);
        _arbitratedRaw = new CArbitratedRawInputBackend(raw, () => _freeze.ScanPermitted);
        _guard = new InputSafetyGuard(
            observer,
            _focusProvider,
            cursor ?? throw new ArgumentNullException(nameof(cursor)),
            _arbitratedRaw,
            trace ?? throw new ArgumentNullException(nameof(trace)),
            inputOptions ?? new InputSafetyOptions { RestoreCursorOnCleanRelease = true });

        _adapter.ObservationAccepted = OnObservation;
        ObserverStartOutcome started = _observer.Start(ObserveInput);
        if (!started.Ok)
        {
            throw new InvalidOperationException($"observer-start:{started.Reason}");
        }
    }

    public FreezeCoordinator Freeze => _freeze;

    public InputSafetyGuard Guard => _guard;

    public AWindowFocusAdapter FocusAdapter => _adapter;

    public IInputObserver Observer => _observer;

    public IRawInputBackend Raw => _raw;

    public CArbitratedRawInputBackend ArbitratedRaw => _arbitratedRaw;

    /// <summary>Verifier-only hook executed before the action fence is acquired.</summary>
    public Action? BeforeActionFenceForDiagnostics { get; set; }

    public bool SessionReady => _sessionReady;

    public bool StartSession()
    {
        if (!_freeze.ValidateCurrentSession(_freeze.GenerationId, "integration-start"))
        {
            return false;
        }

        string token = _freeze.IssueRearmToken("integration-start");
        RearmOutcome outcome = _freeze.Rearm(
            manualRearmConfirmed: true,
            targetFocusValid: true,
            noGameConflict: true,
            noUserTakeoverActive: true,
            generationId: _freeze.GenerationId,
            rearmToken: token,
            detail: "integration-start");
        _sessionReady = outcome is RearmOutcome.APPLIED or RearmOutcome.ALREADY_ALLOW;
        return _sessionReady;
    }

    public IntegrationArmResult ArmCurrent()
    {
        IntegrationFocusView view = _adapter.CaptureView();
        if (!view.IsValid || !_sessionReady || !_freeze.ScanPermitted)
        {
            string reason = !_sessionReady
                ? "C_SESSION_NOT_READY"
                : !_freeze.ScanPermitted
                    ? "C_FROZEN"
                    : view.Reason;
            return ArmResult(false, reason, view);
        }

        ArmOutcome arm = _guard.Arm(new ArmRequest(view.TargetId));
        return ArmResult(arm.Ok, arm.Reason, view);
    }

    public IntegrationActionResult Execute(InputAction action)
    {
        ArgumentNullException.ThrowIfNull(action);
        BeforeActionFenceForDiagnostics?.Invoke();

        lock (_actionFence)
        {
            long beforeCalls = _raw.SendCallCount;
            long beforeAccepted = _raw.InputsSentCount;
            InputActionOutcome? bOutcome = null;
            bool cCommitted = false;
            bool cSuccess = false;

            bool cResult = _freeze.ExecuteScrollRequest(
                _ =>
                {
                    cCommitted = true;
                    bOutcome = _guard.Execute(action);
                    if (!bOutcome.Ok)
                    {
                        throw new IntegrationActuatorRejectedException(bOutcome.Reason);
                    }

                    cSuccess = true;
                },
                action.WheelDelta,
                _freeze.GenerationId);

            long rawCalls = _raw.SendCallCount - beforeCalls;
            long rawAccepted = _raw.InputsSentCount - beforeAccepted;
            bool permitted = cCommitted;
            string reason = cResult
                ? InputSafetyReasons.Ok
                : bOutcome?.Reason
                    ?? _freeze.LastActuatorError
                    ?? FreezeErrorCodes.Frozen;

            return new IntegrationActionResult(
                cResult && bOutcome?.Ok == true,
                reason,
                permitted,
                cCommitted,
                cSuccess,
                bOutcome,
                rawCalls,
                rawAccepted,
                _freeze.GenerationId,
                _adapter.Last.TargetId,
                _adapter.Last.FocusEpoch,
                _freeze.ActiveReasons,
                _freeze.LastActuatorError);
        }
    }

    /// <summary>
    /// A freeze event uses the same action fence when it comes from another thread.
    /// If it is raised synchronously inside the fenced action (for example by a fake
    /// raw backend after submission), it applies directly and records post-commit
    /// ordering instead of deadlocking.
    /// </summary>
    public bool FreezeAtBoundary(FreezeReason reason, string detail)
    {
        void Apply()
        {
            _freeze.Freeze(reason, detail);
        }

        if (_arbitratedRaw.IsSendFenceHeld)
        {
            Apply();
            return true;
        }

        _arbitratedRaw.RunAtSendFence(Apply);
        return true;
    }

    public RearmOutcome RearmCurrent(string detail)
    {
        string token = _freeze.IssueRearmToken(detail);
        return _freeze.Rearm(true, true, true, !_guard.UserTakeoverSeen,
            _freeze.GenerationId, token, detail);
    }

    private void OnObservation(IntegrationFocusView view)
    {
        if (view.SourceFenceBroken || view.IdentityChanged || view.FocusChanged || !view.IsValid)
        {
            FreezeAtBoundary(FreezeReason.FOCUS_LOST,
                $"A:{view.Reason};sourceRevision={view.SourceRevision};aGeneration={view.AGeneration}");
        }
    }

    private void ObserveInput(ObservedInputEvent observed)
    {
        _guard.OnObservedInput(observed);
        if (_guard.UserTakeoverSeen && observed.Origin != InputEventOrigin.Injected)
        {
            FreezeAtBoundary(FreezeReason.USER_TAKEOVER,
                $"B:{observed.Kind};origin={observed.Origin};sequence={observed.Sequence}");
        }
    }

    private IntegrationArmResult ArmResult(bool ok, string reason, IntegrationFocusView view) =>
        new(ok, reason, _freeze.GenerationId, view.TargetId, view.FocusEpoch,
            view.AGeneration, view.SourceRevision);

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        try
        {
            _guard.Release();
        }
        finally
        {
            _observer.Stop();
        }
    }
}
