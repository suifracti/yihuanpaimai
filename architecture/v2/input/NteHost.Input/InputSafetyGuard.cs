namespace NteHost.Input;

public enum GuardState
{
    Disarmed = 0,
    Armed = 1,
    Cancelled = 2,
    Released = 3,
}

public sealed record InputSafetyOptions
{
    /// <summary>Upper bound on how many self-injected events one arming generation may absorb.</summary>
    public int MaxSelfExemptionsPerArming { get; init; } = 16;

    /// <summary>Lifetime of a one-shot self-injection intent.</summary>
    public int SelfIntentTtlMs { get; init; } = 250;

    /// <summary>Lifetime of a SendInput ticket issued after the final precheck.</summary>
    public int TicketTtlMs { get; init; } = 500;

    /// <summary>Pixel tolerance when matching an expected cursor move. 0 = exact.</summary>
    public int CursorMoveTolerancePx { get; init; }

    /// <summary>Restore the saved cursor on a clean release (never on user takeover).</summary>
    public bool RestoreCursorOnCleanRelease { get; init; } = true;

    /// <summary>Test seam for a deterministic marker; production uses the CSPRNG default.</summary>
    public Func<ulong>? MarkerFactory { get; init; }
}

public sealed record ArmRequest(long TargetId);

public sealed record ArmOutcome(bool Ok, string Reason, FocusSnapshot Snapshot);

public sealed record PrecheckRecord(
    string Stage,
    bool Passed,
    string Reason,
    bool IsValid,
    long TargetId,
    long ForegroundId,
    long Epoch,
    long Sequence,
    long MonotonicNs);

public sealed record InputActionOutcome(
    bool Ok,
    string Reason,
    string Stage,
    long SendCallCount,
    long InputsSentCount,
    bool Precheck1Passed,
    bool FinalPrecheckPassed,
    bool TicketIssued,
    bool SelfExempted,
    string ExemptionDetail,
    bool CursorRestoreAttempted,
    bool CursorRestoreSkipped,
    bool CursorRestored,
    string CursorRestoreReason);

public sealed record CancelOutcome(bool Ok, string Reason, bool AlreadyCancelled);

public sealed record ReleaseOutcome(
    bool Ok,
    string Reason,
    bool AlreadyReleased,
    bool CursorRestoreAttempted,
    bool CursorRestoreSkipped,
    bool CursorRestored,
    string CursorRestoreReason);

/// <summary>
/// V2-2B input safety state machine.
///
/// Ordering contract for every input-producing operation:
///     precheck #1  →  prepare (optional cursor move)  →  final precheck  →  SendInput
/// Any failure before the raw backend is entered fails closed: the operation is
/// disarmed, the cursor is finalised under the takeover policy, and zero SendInput
/// calls are made. Once the raw backend has been entered, the outcome reports the
/// actual call and accepted-record counts; already-submitted input cannot be revoked.
/// Cursor preparation has an explicit commit boundary immediately before the cursor
/// backend call. A cancellation observed before that boundary prevents the cursor
/// side effect; a cancellation racing after the boundary is handled by the normal
/// takeover/restore policy.
///
/// Concurrency contract (this is what makes the TOCTOU guarantee real):
///   * the OS hook callback path (<see cref="OnObservedInput"/>) is lock-free with
///     respect to <c>_stateGate</c>. It only uses atomics plus the ledger lock, so
///     it can never deadlock against an in-flight SendInput that the OS is
///     synchronously dispatching through our own hook procedure.
///   * the execution path holds <c>_stateGate</c> across the final precheck and
///     the raw backend call. An external <see cref="Cancel"/> that successfully
///     linearises before that section prevents the send; a request blocked behind
///     the section takes effect after the send and cannot revoke it. The verifier
///     records both linearisation points explicitly.
///   * the hook callback performs no OS call, so hook latency stays bounded.
///
/// Authority for this module is: Win32 input/hook signal + the focus snapshot taken
/// at the instant of the decision. It does not discover windows, does not monitor
/// window lifecycle, and does not implement any freeze policy.
/// </summary>
public sealed class InputSafetyGuard : ISendInputTicketAuthority
{
    private static long _authorityCounter;
    private const int MaxRecordedPrechecks = 512;

    private readonly object _stateGate = new();
    private readonly IInputObserver _observer;
    private readonly IFocusSnapshotProvider _focus;
    private readonly ICursorBackend _cursor;
    private readonly IRawInputBackend _raw;
    private readonly IInputTraceSink _trace;
    private readonly InputSafetyOptions _options;
    private readonly SelfInjectionLedger _ledger;
    private readonly SafeSendInputExecutor _executor;
    private readonly List<PrecheckRecord> _prechecks = new();

    private int _stateAtomic = (int)GuardState.Disarmed;
    private long _armedTargetId;
    private long _armedEpoch;
    private long _ticketSequence;
    private long _savedX;
    private long _savedY;
    private bool _cursorMoved;
    private bool _cursorFinalized;
    private bool _cursorRestoreAttempted;
    private bool _cursorRestoreSkipped;
    private bool _cursorRestored;
    private string _cursorRestoreReason = string.Empty;
    private string? _cancelReason;
    private string? _lastExemptionDenyReason;
    private string _lastPrecheckFailReason = string.Empty;
    private string _lastPrecheckFailStage = string.Empty;
    private int _userTakeoverSeen;
    private long _cancelCount;
    private long _observedCount;
    private long _ignoredWhileUnarmedCount;
    private long _selfExemptionCount;
    private long _exemptionDeniedCount;
    private long _precheck1PassCount;
    private long _precheck2PassCount;
    private long _precheckFailCount;

    public InputSafetyGuard(
        IInputObserver observer,
        IFocusSnapshotProvider focus,
        ICursorBackend cursor,
        IRawInputBackend rawBackend,
        IInputTraceSink? trace = null,
        InputSafetyOptions? options = null)
    {
        _observer = observer ?? throw new ArgumentNullException(nameof(observer));
        _focus = focus ?? throw new ArgumentNullException(nameof(focus));
        _cursor = cursor ?? throw new ArgumentNullException(nameof(cursor));
        _raw = rawBackend ?? throw new ArgumentNullException(nameof(rawBackend));
        _trace = trace ?? NullInputTraceSink.Instance;
        _options = options ?? new InputSafetyOptions();
        _ledger = new SelfInjectionLedger(_options.MarkerFactory);
        _executor = new SafeSendInputExecutor(_raw, this);
        AuthorityId = Interlocked.Increment(ref _authorityCounter);
    }

    public long AuthorityId { get; }

    public GuardState State => (GuardState)Volatile.Read(ref _stateAtomic);

    public SelfInjectionLedger Ledger => _ledger;

    public SafeSendInputExecutor Executor => _executor;

    public long SendCallCount => _raw.SendCallCount;

    public long InputsSentCount => _raw.InputsSentCount;

    public long CancelCount => Interlocked.Read(ref _cancelCount);

    public long ObservedInputCount => Interlocked.Read(ref _observedCount);

    public long IgnoredWhileUnarmedCount => Interlocked.Read(ref _ignoredWhileUnarmedCount);

    public long SelfExemptionCount => Interlocked.Read(ref _selfExemptionCount);

    public long ExemptionDeniedCount => Interlocked.Read(ref _exemptionDeniedCount);

    public long Precheck1PassCount => Interlocked.Read(ref _precheck1PassCount);

    public long Precheck2PassCount => Interlocked.Read(ref _precheck2PassCount);

    public long PrecheckFailCount => Interlocked.Read(ref _precheckFailCount);

    public string CancelReason => Volatile.Read(ref _cancelReason) ?? string.Empty;

    public string LastExemptionDenyReason => Volatile.Read(ref _lastExemptionDenyReason) ?? string.Empty;

    public bool UserTakeoverSeen => Volatile.Read(ref _userTakeoverSeen) != 0;

    public bool CursorRestoreAttempted => _cursorRestoreAttempted;

    public bool CursorRestoreSkipped => _cursorRestoreSkipped;

    public bool CursorRestored => _cursorRestored;

    public string CursorRestoreReason => _cursorRestoreReason;

    public string LastPrecheckFailReason => _lastPrecheckFailReason;

    public string LastPrecheckFailStage => _lastPrecheckFailStage;

    public IReadOnlyList<PrecheckRecord> Prechecks
    {
        get { lock (_stateGate) { return _prechecks.ToArray(); } }
    }

    // ------------------------------------------------------------------
    // Arm / cancel / release
    // ------------------------------------------------------------------

    public ArmOutcome Arm(ArmRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        _trace.Write(TracePhase.ArmRequested, $"target={request.TargetId}");

        lock (_stateGate)
        {
            switch (State)
            {
                case GuardState.Armed:
                    return RejectArm(InputSafetyReasons.AlreadyArmed);
                case GuardState.Released:
                    return RejectArm(InputSafetyReasons.GuardReleased);
                case GuardState.Cancelled:
                    return RejectArm(InputSafetyReasons.Cancelled);
            }

            if (!_observer.IsRunning)
            {
                return RejectArm(InputSafetyReasons.ObserverNotRunning);
            }

            var snapshot = CheckFocusAtArm();
            if (!snapshot.Ok)
            {
                return RejectArm(snapshot.Reason);
            }

            if (snapshot.Snapshot.TargetId != request.TargetId)
            {
                return RejectArm(InputSafetyReasons.TargetIdMismatch);
            }

            (int X, int Y) saved;
            try
            {
                saved = _cursor.GetPosition();
            }
            catch
            {
                return RejectArm(InputSafetyReasons.BackendError);
            }

            _savedX = saved.X;
            _savedY = saved.Y;
            _cursorMoved = false;
            _cursorFinalized = false;
            _cursorRestoreAttempted = false;
            _cursorRestoreSkipped = false;
            _cursorRestored = false;
            _cursorRestoreReason = string.Empty;
            Interlocked.Exchange(ref _userTakeoverSeen, 0);
            Volatile.Write(ref _cancelReason, null);
            _prechecks.Clear();

            _ledger.BeginGeneration(_options.MaxSelfExemptionsPerArming, _options.SelfIntentTtlMs);

            // Publish the arming identity BEFORE flipping state, so a hook callback
            // that observes the Armed transition can never read a stale epoch.
            Volatile.Write(ref _armedTargetId, snapshot.Snapshot.TargetId);
            Volatile.Write(ref _armedEpoch, snapshot.Snapshot.Epoch);
            Interlocked.Exchange(ref _stateAtomic, (int)GuardState.Armed);

            _trace.Write(
                TracePhase.Armed,
                $"target={snapshot.Snapshot.TargetId};epoch={snapshot.Snapshot.Epoch};marker={InputMarker.ToHex(_ledger.Marker)}");
            return new ArmOutcome(true, InputSafetyReasons.Ok, snapshot.Snapshot);
        }
    }

    /// <summary>
    /// Arm-time focus gate. Kept separate from <see cref="RunPrecheck"/> because at
    /// arm time the guard is still Disarmed and the precheck's own state test would
    /// reject the arming it is supposed to authorise.
    /// </summary>
    private (bool Ok, string Reason, FocusSnapshot Snapshot) CheckFocusAtArm()
    {
        FocusSnapshot snapshot;
        try
        {
            snapshot = _focus.Capture();
        }
        catch
        {
            return (false, InputSafetyReasons.FocusSnapshotInvalid, default);
        }

        if (!snapshot.IsValid)
        {
            return (false, InputSafetyReasons.FocusSnapshotInvalid, snapshot);
        }

        if (snapshot.ForegroundId != snapshot.TargetId)
        {
            return (false, InputSafetyReasons.NotForeground, snapshot);
        }

        return (true, InputSafetyReasons.Ok, snapshot);
    }

    private ArmOutcome RejectArm(string reason)
    {
        _trace.Write(TracePhase.ArmRejected, reason);
        return new ArmOutcome(false, reason, default);
    }

    public CancelOutcome Cancel(string reason)
    {
        string effective = string.IsNullOrEmpty(reason) ? InputSafetyReasons.Cancelled : reason;
        _trace.Write(TracePhase.CancelRequested, effective);

        lock (_stateGate)
        {
            int prior = Interlocked.CompareExchange(
                ref _stateAtomic, (int)GuardState.Cancelled, (int)GuardState.Armed);

            if (prior == (int)GuardState.Armed)
            {
                Interlocked.CompareExchange(ref _cancelReason, effective, null);
                Interlocked.Increment(ref _cancelCount);
                return new CancelOutcome(true, effective, false);
            }

            if (prior == (int)GuardState.Cancelled)
            {
                return new CancelOutcome(false, InputSafetyReasons.AlreadyCancelled, true);
            }

            if (prior == (int)GuardState.Released)
            {
                return new CancelOutcome(false, InputSafetyReasons.GuardReleased, false);
            }

            // Disarmed: record a standing cancel so a later Arm is refused.
            Interlocked.Exchange(ref _stateAtomic, (int)GuardState.Cancelled);
            Interlocked.CompareExchange(ref _cancelReason, effective, null);
            Interlocked.Increment(ref _cancelCount);
            return new CancelOutcome(true, effective, false);
        }
    }

    public ReleaseOutcome Release()
    {
        _trace.Write(TracePhase.ReleaseBegin, State.ToString());

        lock (_stateGate)
        {
            int prior = Interlocked.Exchange(ref _stateAtomic, (int)GuardState.Released);
            bool alreadyReleased = prior == (int)GuardState.Released;

            FinalizeCursorLocked();

            _trace.Write(
                TracePhase.ReleaseDone,
                $"alreadyReleased={alreadyReleased};attempted={_cursorRestoreAttempted};skipped={_cursorRestoreSkipped};restored={_cursorRestored};reason={_cursorRestoreReason}");

            return new ReleaseOutcome(
                true,
                alreadyReleased ? InputSafetyReasons.AlreadyReleased : InputSafetyReasons.Ok,
                alreadyReleased,
                _cursorRestoreAttempted,
                _cursorRestoreSkipped,
                _cursorRestored,
                _cursorRestoreReason);
        }
    }

    /// <summary>
    /// Resets the cursor bookkeeping for one Execute operation. The guard may remain
    /// Armed after a successful operation, so this state is per operation rather than
    /// per arm. Release and fail-closed paths still finalize the current operation
    /// exactly once.
    /// </summary>
    private bool BeginCursorOperation()
    {
        lock (_stateGate)
        {
            if (State != GuardState.Armed)
            {
                return false;
            }

            _cursorMoved = false;
            _cursorFinalized = false;
            _cursorRestoreAttempted = false;
            _cursorRestoreSkipped = false;
            _cursorRestored = false;
            _cursorRestoreReason = string.Empty;
            return true;
        }
    }

    /// <summary>
    /// Makes the cursor-restore decision exactly once for the current Execute
    /// operation. Called from every terminal transition (fail-closed execute and
    /// release) so the decision is deterministic and idempotent within that
    /// operation, while a later Execute starts a fresh cursor lifecycle.
    /// </summary>
    private void FinalizeCursorLocked()
    {
        if (_cursorFinalized)
        {
            return;
        }

        _cursorFinalized = true;

        if (Volatile.Read(ref _userTakeoverSeen) != 0)
        {
            // A human has the pointer. Restoring our saved position here would yank
            // the cursor out from under them, which is exactly what must not happen.
            _cursorRestoreSkipped = true;
            _cursorRestoreReason = InputSafetyReasons.CursorRestoreUserTakeover;
            _trace.Write(TracePhase.CursorRestoreSkipped, InputSafetyReasons.CursorRestoreUserTakeover);
            return;
        }

        if (!_cursorMoved)
        {
            _cursorRestoreReason = InputSafetyReasons.CursorRestoreNotMoved;
            return;
        }

        if (!_options.RestoreCursorOnCleanRelease)
        {
            _cursorRestoreReason = InputSafetyReasons.CursorRestoreDisabled;
            return;
        }

        _cursorRestoreAttempted = true;
        try
        {
            _cursorRestored = _cursor.SetPosition((int)_savedX, (int)_savedY);
            _cursorRestoreReason = _cursorRestored
                ? InputSafetyReasons.CursorRestoreOk
                : InputSafetyReasons.CursorRestoreFailed;
        }
        catch
        {
            _cursorRestored = false;
            _cursorRestoreReason = InputSafetyReasons.CursorRestoreFailed;
        }

        _trace.Write(
            TracePhase.CursorRestore,
            $"restored={_cursorRestored};reason={_cursorRestoreReason}");
    }

    // ------------------------------------------------------------------
    // Observation path (called by the OS hook thread)
    // ------------------------------------------------------------------

    /// <summary>
    /// Entry point for observed input. MUST stay lock-free with respect to the
    /// execution path and MUST NOT perform any OS call: the OS dispatches hook
    /// callbacks synchronously inside SendInput, so blocking here would stall the
    /// machine-wide input stream and could deadlock against an in-flight send.
    /// </summary>
    public void OnObservedInput(in ObservedInputEvent observed)
    {
        Interlocked.Increment(ref _observedCount);
        _trace.Write(TracePhase.ObservedEvent, Describe(observed));

        if (Volatile.Read(ref _stateAtomic) != (int)GuardState.Armed)
        {
            // Not armed: the event is recorded and then dropped. It must not push
            // the guard into a takeover state, and it must not be exempted either.
            Interlocked.Increment(ref _ignoredWhileUnarmedCount);
            _trace.Write(TracePhase.ObservedIgnoredUnarmed, Describe(observed));
            return;
        }

        ExemptionDecision decision = _ledger.Evaluate(observed);
        if (decision.Exempted)
        {
            Interlocked.Increment(ref _selfExemptionCount);
            _trace.Write(TracePhase.ExemptionGranted, Describe(observed));
            return;
        }

        Interlocked.Increment(ref _exemptionDeniedCount);
        Interlocked.Exchange(ref _lastExemptionDenyReason, decision.Reason);

        string reason = ClassifyTakeover(observed);
        _trace.Write(TracePhase.ExemptionDenied, $"{decision.Reason};{Describe(observed)}");
        CancelFromHook(reason, observed);
    }

    private void CancelFromHook(string reason, in ObservedInputEvent observed)
    {
        int prior = Interlocked.CompareExchange(
            ref _stateAtomic, (int)GuardState.Cancelled, (int)GuardState.Armed);

        if (prior != (int)GuardState.Armed)
        {
            return;
        }

        Interlocked.CompareExchange(ref _cancelReason, reason, null);
        Interlocked.Increment(ref _cancelCount);
        Interlocked.Exchange(ref _userTakeoverSeen, 1);
        _trace.Write(TracePhase.Takeover, $"{reason};{Describe(observed)}");
    }

    private static string ClassifyTakeover(in ObservedInputEvent observed) => observed.Kind switch
    {
        InputEventKind.KeyDown => InputSafetyReasons.UserKeyDown,
        InputEventKind.MouseButtonDown => InputSafetyReasons.UserMouseButton,
        InputEventKind.MouseWheel => InputSafetyReasons.UserMouseWheel,
        InputEventKind.MouseHorizontalWheel => InputSafetyReasons.UserMouseHorizontalWheel,
        InputEventKind.MouseMove => InputSafetyReasons.UserMouseMove,
        _ => InputSafetyReasons.UserInputUnknown,
    };

    private static string Describe(in ObservedInputEvent observed)
    {
        string origin = observed.Origin switch
        {
            InputEventOrigin.Hardware => "HW",
            InputEventOrigin.Injected => "INJ",
            InputEventOrigin.LowerIntegrityInjected => "INJ_LOWIL",
            _ => "?",
        };

        return observed.Kind == InputEventKind.MouseMove
            ? $"{observed.Kind}/{origin}/pt={observed.X},{observed.Y}"
            : $"{observed.Kind}/{origin}";
    }

    // ------------------------------------------------------------------
    // Execution path
    // ------------------------------------------------------------------

    public InputActionOutcome Execute(InputAction action)
    {
        ArgumentNullException.ThrowIfNull(action);

        long exemptionBefore = Interlocked.Read(ref _selfExemptionCount);
        long sendBefore = _raw.SendCallCount;

        if (State != GuardState.Armed)
        {
            return Outcome(false, StateReason(), "STATE", sendBefore, false, false, false, false, string.Empty);
        }

        if (!BeginCursorOperation())
        {
            return Outcome(false, StateReason(), "STATE", sendBefore, false, false, false, false, string.Empty);
        }

        // --- precheck #1 ---
        PrecheckRecord first = RunPrecheck("PRECHECK_1");
        if (!first.Passed)
        {
            return FailClosed(action, first.Reason, "PRECHECK_1", sendBefore, first.Passed, false);
        }

        Interlocked.Increment(ref _precheck1PassCount);
        _trace.Write(TracePhase.Precheck1Pass, action.Fingerprint);

        // --- prepare ---
        string? prepareError = RunPrepare(action);
        if (prepareError is not null)
        {
            return FailClosed(action, prepareError, "PREPARE", sendBefore, true, false);
        }

        // --- final precheck + ticket + SendInput, under the state gate ---
        lock (_stateGate)
        {
            if (State != GuardState.Armed)
            {
                string reason = StateReason();
                _trace.Write(TracePhase.SendInputSkipped, reason);
                FinalizeCursorLocked();
                return Outcome(false, reason, "FINAL_PRECHECK", sendBefore, true, false, false, false, string.Empty);
            }

            _trace.Write(TracePhase.Precheck2Begin, action.Fingerprint);
            PrecheckRecord final = RunPrecheck("PRECHECK_2");
            if (!final.Passed)
            {
                _trace.Write(TracePhase.Precheck2Fail, final.Reason);
                return FailClosedLocked(action, final.Reason, "FINAL_PRECHECK", sendBefore, true, false);
            }

            Interlocked.Increment(ref _precheck2PassCount);
            _trace.Write(TracePhase.Precheck2Pass, action.Fingerprint);

            SendInputTicket? ticket = null;
            if (action.Kind != InputActionKind.CursorMove)
            {
                ticket = IssueTicketLocked(action);
                _trace.Write(TracePhase.TicketIssued, $"id={ticket.Id};{action.Fingerprint}");
            }
            else
            {
                // Cursor-move-only actions never reach SendInput by construction.
                _trace.Write(TracePhase.SendInputSkipped, "CURSOR_MOVE_ONLY");
            }

            if (ticket is null)
            {
                FinalizeCursorLocked();
                return Outcome(true, InputSafetyReasons.Ok, "FINAL_PRECHECK", sendBefore, true, true, false, false, string.Empty);
            }

            _trace.Write(TracePhase.SendInputInvoked, action.Fingerprint);
            ExecutorOutcome executorOutcome = _executor.Execute(action, ticket);

            if (!executorOutcome.Ok)
            {
                _trace.Write(TracePhase.TicketRejected, executorOutcome.Reason);
                return FailClosedLocked(action, executorOutcome.Reason, "EXECUTOR", sendBefore, true, false);
            }

            bool selfExempted = Interlocked.Read(ref _selfExemptionCount) > exemptionBefore;

            // A takeover that landed while the OS was dispatching our own injected
            // event is detected here. The send already happened, which is physically
            // unavoidable, but the operation is still reported as cancelled and the
            // cursor is left exactly where the user put it.
            if (State != GuardState.Armed)
            {
                string reason = StateReason();
                FinalizeCursorLocked();
                return Outcome(false, reason, "POST_SEND", sendBefore, true, true, true, selfExempted, string.Empty);
            }

            FinalizeCursorLocked();
            return Outcome(true, InputSafetyReasons.Ok, "COMPLETE", sendBefore, true, true, true, selfExempted, string.Empty);
        }
    }

    private string StateReason() => State switch
    {
        GuardState.Released => InputSafetyReasons.GuardReleased,
        GuardState.Cancelled => InputSafetyReasons.Cancelled,
        GuardState.Armed => InputSafetyReasons.Ok,
        _ => InputSafetyReasons.NotArmed,
    };

    private InputActionOutcome FailClosed(
        InputAction action,
        string reason,
        string stage,
        long sendBefore,
        bool precheck1Passed,
        bool finalPrecheckPassed)
    {
        lock (_stateGate)
        {
            return FailClosedLocked(action, reason, stage, sendBefore, precheck1Passed, finalPrecheckPassed);
        }
    }

    private InputActionOutcome FailClosedLocked(
        InputAction action,
        string reason,
        string stage,
        long sendBefore,
        bool precheck1Passed,
        bool finalPrecheckPassed)
    {
        _lastPrecheckFailReason = reason;
        _lastPrecheckFailStage = stage;
        Interlocked.Increment(ref _precheckFailCount);

        // Fail closed: disarm and make the cursor decision now, once.
        Interlocked.CompareExchange(
            ref _stateAtomic, (int)GuardState.Cancelled, (int)GuardState.Armed);
        Interlocked.CompareExchange(ref _cancelReason, reason, null);

        _trace.Write(TracePhase.SendInputSkipped, $"{stage}:{reason}");
        FinalizeCursorLocked();

        return Outcome(false, reason, stage, sendBefore, precheck1Passed, finalPrecheckPassed, false, false, string.Empty);
    }

    private InputActionOutcome Outcome(
        bool ok,
        string reason,
        string stage,
        long sendBefore,
        bool precheck1Passed,
        bool finalPrecheckPassed,
        bool ticketIssued,
        bool selfExempted,
        string exemptionDetail)
    {
        long sendDelta = _raw.SendCallCount - sendBefore;
        return new InputActionOutcome(
            ok,
            reason,
            stage,
            sendDelta,
            _raw.InputsSentCount,
            precheck1Passed,
            finalPrecheckPassed,
            ticketIssued,
            selfExempted,
            exemptionDetail,
            _cursorRestoreAttempted,
            _cursorRestoreSkipped,
            _cursorRestored,
            _cursorRestoreReason);
    }

    private PrecheckRecord RunPrecheck(string stage)
    {
        if (State == GuardState.Cancelled)
        {
            return RecordPrecheck(stage, false, InputSafetyReasons.Cancelled, default);
        }

        if (State != GuardState.Armed)
        {
            return RecordPrecheck(stage, false, InputSafetyReasons.NotArmed, default);
        }

        if (!_observer.IsRunning)
        {
            return RecordPrecheck(stage, false, InputSafetyReasons.ObserverNotRunning, default);
        }

        FocusSnapshot snapshot;
        try
        {
            snapshot = _focus.Capture();
        }
        catch
        {
            return RecordPrecheck(stage, false, InputSafetyReasons.FocusSnapshotInvalid, default);
        }

        if (!snapshot.IsValid)
        {
            return RecordPrecheck(stage, false, InputSafetyReasons.FocusSnapshotInvalid, snapshot);
        }

        if (snapshot.TargetId != Volatile.Read(ref _armedTargetId))
        {
            return RecordPrecheck(stage, false, InputSafetyReasons.TargetIdMismatch, snapshot);
        }

        if (snapshot.ForegroundId != Volatile.Read(ref _armedTargetId))
        {
            return RecordPrecheck(stage, false, InputSafetyReasons.NotForeground, snapshot);
        }

        if (snapshot.Epoch != Volatile.Read(ref _armedEpoch))
        {
            return RecordPrecheck(stage, false, InputSafetyReasons.FocusEpochChanged, snapshot);
        }

        return RecordPrecheck(stage, true, InputSafetyReasons.Ok, snapshot);
    }

    private PrecheckRecord RecordPrecheck(string stage, bool passed, string reason, FocusSnapshot snapshot)
    {
        var record = new PrecheckRecord(
            stage,
            passed,
            reason,
            snapshot.IsValid,
            snapshot.TargetId,
            snapshot.ForegroundId,
            snapshot.Epoch,
            snapshot.Sequence,
            snapshot.MonotonicNs);

        lock (_stateGate)
        {
            if (_prechecks.Count < MaxRecordedPrechecks)
            {
                _prechecks.Add(record);
            }
        }

        return record;
    }

    private string? RunPrepare(InputAction action)
    {
        _trace.Write(TracePhase.PrepareBegin, action.Fingerprint);

        if (State != GuardState.Armed)
        {
            string reason = StateReason();
            _trace.Write(TracePhase.PrepareAborted, $"{reason}:BEFORE_PREPARE");
            return reason;
        }

        CursorPrepare? prepare = action.Kind == InputActionKind.CursorMove
            ? new CursorPrepare(action.X, action.Y)
            : action.Prepare;

        if (prepare is { } target)
        {
            ulong intentId = _ledger.Register(
                InputActionKind.CursorMove, target.X, target.Y, _options.CursorMoveTolerancePx);
            _trace.Write(TracePhase.SelfIntentRegistered, $"MOVE:{target.X},{target.Y};intent={intentId}");

            if (State != GuardState.Armed)
            {
                _ledger.Abandon(intentId);
                string reason = StateReason();
                _trace.Write(TracePhase.PrepareAborted, $"{reason}:BEFORE_CURSOR_COMMIT");
                return reason;
            }

            bool applied;
            try
            {
                _trace.Write(TracePhase.CursorPrepareInvoked, $"MOVE:{target.X},{target.Y}");
                applied = _cursor.SetPosition(target.X, target.Y);
            }
            catch
            {
                _ledger.Abandon(intentId);
                _trace.Write(TracePhase.PrepareAborted, InputSafetyReasons.BackendError);
                return InputSafetyReasons.BackendError;
            }

            (int X, int Y) actual;
            try
            {
                actual = _cursor.GetPosition();
            }
            catch
            {
                _ledger.Abandon(intentId);
                _trace.Write(TracePhase.PrepareAborted, InputSafetyReasons.BackendError);
                return InputSafetyReasons.BackendError;
            }

            if (!applied || actual.X != target.X || actual.Y != target.Y)
            {
                _ledger.Abandon(intentId);
                _trace.Write(TracePhase.PrepareAborted, $"actual={actual.X},{actual.Y}");
                return InputSafetyReasons.CursorMoveNotApplied;
            }

            lock (_stateGate)
            {
                _cursorMoved = true;
            }

            if (State != GuardState.Armed)
            {
                string reason = StateReason();
                _trace.Write(TracePhase.PrepareAborted, $"{reason}:AFTER_CURSOR_COMMIT");
                return reason;
            }
        }

        if (action.Kind != InputActionKind.CursorMove)
        {
            if (State != GuardState.Armed)
            {
                string reason = StateReason();
                _trace.Write(TracePhase.PrepareAborted, $"{reason}:BEFORE_INTENT");
                return reason;
            }

            ulong intentId = _ledger.Register(action.Kind, 0, 0, 0);
            _trace.Write(TracePhase.SelfIntentRegistered, $"{action.Fingerprint};intent={intentId}");
        }

        _trace.Write(TracePhase.PrepareDone, action.Fingerprint);
        return null;
    }

    private SendInputTicket IssueTicketLocked(InputAction action)
    {
        long now = TraceClock.NowNs();
        long ttlNs = Math.Max(1, (long)_options.TicketTtlMs) * 1_000_000L;
        return new SendInputTicket(
            ++_ticketSequence,
            AuthorityId,
            action.Fingerprint,
            now,
            now + ttlNs,
            _ledger.Marker);
    }

    public string TryConsumeTicket(SendInputTicket ticket, InputAction action)
    {
        lock (_stateGate)
        {
            if (State != GuardState.Armed)
            {
                return InputSafetyReasons.TicketGuardNotArmed;
            }

            return ticket.TryConsume() ? InputSafetyReasons.Ok : InputSafetyReasons.TicketReused;
        }
    }

    /// <summary>Test/verification seam: the executor built by this guard.</summary>
    public ExecutorOutcome ExecuteWithTicket(InputAction action, SendInputTicket? ticket) =>
        _executor.Execute(action, ticket);
}
